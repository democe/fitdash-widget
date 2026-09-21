import json
import os
from datetime import date
from unittest.mock import Mock

import pytest

from fitdash.cache import Busy, Cache
from fitdash.cli import parser, sync
from fitdash.model import format_value, metric, present
from fitdash.oauth import PREFIX, AuthError, Vault, refreshed
from fitdash.providers.google_health import GoogleHealth, ApiError


def api(response):
    client = GoogleHealth("test-token", [PREFIX + "activity_and_fitness.readonly"])
    client.request = Mock(return_value=response)
    return client


def test_zero_rollup_is_not_missing():
    day = date(2026, 9, 21)
    client = api(
        {
            "rollupDataPoints": [
                {"civilStartTime": {"date": {"year": 2026, "month": 9, "day": 21}}, "steps": {}}
            ]
        }
    )
    result = client.daily(("steps", "steps", "countSum", ""), day)
    assert result["value"] == 0 and result["status"] == "available"
    client.request.return_value = {"rollupDataPoints": []}
    assert client.daily(("steps", "steps", "countSum", ""), day)["status"] == "no_data"


def test_duplicate_rollups_rejected():
    row = {"civilStartTime": {"date": {"year": 2026, "month": 9, "day": 21}}, "steps": {"countSum": "12"}}
    with pytest.raises(ValueError):
        api({"rollupDataPoints": [row, row]}).daily(("steps", "steps", "countSum", ""), date(2026, 9, 21))


def test_rollup_uses_civil_midnight_and_source():
    client = api({"rollupDataPoints": []})
    client.daily(("steps", "steps", "countSum", ""), date(2026, 3, 8))
    request = client.request.call_args.args[1]
    assert request["range"]["start"] == {"date": {"year": 2026, "month": 3, "day": 8}}
    assert request["range"]["end"] == {"date": {"year": 2026, "month": 3, "day": 9}}
    assert request["dataSourceFamily"].endswith("all-sources")


def test_midnight_does_not_display_yesterday_steps_as_today():
    old = {"metrics": [metric("steps", 8000, period="2026-09-20", group="activity", fetched_at=100)]}
    result = present(old, 101, "metric", "2026-09-21")
    assert result["steps"] is None
    assert result["metrics"][0]["status"] == "stale"
    assert result["metrics"][0]["period"] == "2026-09-20"
    assert old["metrics"][0]["status"] == "available"


def test_units_and_missing_values():
    assert format_value(1609344, "mm", "imperial").endswith("1.00 mi")
    assert format_value(462, "sleep_min") == "7 h 42 min"
    assert format_value(None, "") == "—"
    with pytest.raises(ValueError):
        metric("steps", float("nan"))


def test_private_atomic_cache_and_corruption(tmp_path):
    cache = Cache(tmp_path / "state")
    cache.write("snapshot.json", {"version": 1})
    assert os.stat(cache.directory).st_mode & 0o777 == 0o700
    assert os.stat(cache.directory / "snapshot.json").st_mode & 0o777 == 0o600
    assert cache.read("snapshot.json")["version"] == 1
    (cache.directory / "snapshot.json").write_text("{broken")
    assert cache.read("snapshot.json", {}) == {}
    assert not list(cache.directory.glob(".write-*"))


def test_operation_lock_prevents_overlap(tmp_path):
    cache = Cache(tmp_path)
    with cache.lock():
        with pytest.raises(Busy):
            with Cache(tmp_path).lock():
                pass


def test_missing_scope_does_not_make_network_request():
    client = GoogleHealth("token", [])
    client.request = Mock(side_effect=AssertionError("unexpected request"))
    results = client.collect(date(2026, 9, 21))
    assert all(m["status"] == "not_authorized" for m in results)
    client.request.assert_not_called()


def test_repeated_pagination_token_rejected():
    client = api({"dataPoints": [], "nextPageToken": "again"})
    with pytest.raises(ValueError):
        client.records("sleep", "filter")
    assert client.request.call_count == 2


def test_sleep_uses_summary_not_time_in_bed():
    client = api(
        {
            "dataPoints": [
                {
                    "sleep": {
                        "interval": {
                            "endTime": "2026-09-21T12:00:00Z",
                            "civilEndTime": {"date": {"year": 2026, "month": 9, "day": 21}},
                        },
                        "summary": {"minutesAsleep": "420", "minutesInSleepPeriod": "500"},
                        "metadata": {"mainSleep": True},
                    }
                }
            ]
        }
    )
    assert client.sleep(date(2026, 9, 21))["value"] == 420
    assert "civil_end_time" in client.request.call_args.kwargs["params"]["filter"]


def test_api_error_is_per_metric():
    client = api({})
    client.request.side_effect = ApiError(429, 123)
    result = client.collect(date(2026, 9, 21), sleep=False, vitals=False)
    assert all(m["status"] == "rate_limited" and m["retry_after"] == 123 for m in result)


def test_transient_error_preserves_prior_value_and_backs_off(tmp_path, monkeypatch):
    cache = Cache(tmp_path)
    cache.write(
        "snapshot.json",
        {
            "version": 1,
            "metrics": [metric("steps", 123, period="2026-09-21", fetched_at=99, group="activity")],
        },
    )
    client = Mock()
    client.settings.return_value = {"timeZone": "America/Boise"}
    client.collect.return_value = [metric("steps", status="rate_limited", retry_after=400, group="activity")]
    monkeypatch.setattr("fitdash.cli.GoogleHealth", Mock(return_value=client))
    monkeypatch.setattr("fitdash.cli.refreshed", Mock(return_value=Mock(token="fake", scopes=[])))
    monkeypatch.setattr("fitdash.cli.time.time", lambda: 1000)
    result = sync(cache, Mock(), parser().parse_args(["sync", "--force"]))
    assert result["metrics"][0]["value"] == 123
    assert result["metrics"][0]["fetched_at"] == 99
    assert result["metrics"][0]["status"] == "stale"
    assert result["retry_at"] >= 1400
    sync(cache, Mock(), parser().parse_args(["sync", "--force"]))
    assert client.collect.call_count == 1


def test_401_refresh_is_attempted_once(tmp_path, monkeypatch):
    client = Mock()
    client.settings.return_value = {}
    client.collect.return_value = [metric("steps", status="reconnect_required")]
    monkeypatch.setattr("fitdash.cli.GoogleHealth", Mock(return_value=client))
    refresh = Mock(return_value=Mock(token="fake", scopes=[]))
    monkeypatch.setattr("fitdash.cli.refreshed", refresh)
    result = sync(Cache(tmp_path), Mock(), parser().parse_args(["sync"]))
    assert client.collect.call_count == 2
    assert refresh.call_count == 2
    assert refresh.call_args.kwargs == {"force": True}
    assert result["status"] == "reconnect_required"


def test_vault_saves_actual_granted_scopes(monkeypatch):
    backend = Mock()
    monkeypatch.setattr("fitdash.oauth.Keyring", Mock(return_value=backend))
    credentials = Mock(granted_scopes=["activity"])
    credentials.to_json.return_value = json.dumps({"scopes": ["activity", "sleep"]})
    Vault("test").save(credentials)
    assert json.loads(backend.set_password.call_args.args[2])["scopes"] == ["activity"]


def test_revoked_credentials_become_reconnect():
    from google.auth.exceptions import RefreshError

    credentials = Mock(valid=False)
    credentials.refresh.side_effect = RefreshError("secret must not appear")
    vault = Mock()
    vault.load.return_value = credentials
    with pytest.raises(AuthError, match="^reconnect_required$"):
        refreshed(vault)
    vault.save.assert_not_called()


def test_oauth_validates_state_and_does_not_log_code(tmp_path, monkeypatch, capsys):
    import threading
    import urllib.parse
    import urllib.request
    from fitdash.oauth import authenticate

    client_file = tmp_path / "client.json"
    client_file.write_text(
        json.dumps(
            {
                "installed": {
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
    )
    flow = Mock()
    flow.credentials = Mock(refresh_token="fake-refresh")
    flow.authorization_url.side_effect = lambda **kw: (
        "https://accounts.google.com/?state=" + kw["state"],
        kw["state"],
    )
    monkeypatch.setattr("fitdash.oauth.InstalledAppFlow.from_client_config", Mock(return_value=flow))
    callback_statuses = []
    threads = []

    def open_browser(url):
        state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

        def callback():
            for supplied_state in ("wrong", state):
                target = (
                    flow.redirect_uri
                    + "?"
                    + urllib.parse.urlencode({"state": supplied_state, "code": "never-log-this-code"})
                )
                try:
                    with urllib.request.urlopen(target) as r:
                        callback_statuses.append(r.status)
                except urllib.error.HTTPError as error:
                    callback_statuses.append(error.code)

        thread = threading.Thread(target=callback)
        thread.start()
        threads.append(thread)
        return True

    monkeypatch.setattr("fitdash.oauth.webbrowser.open", open_browser)
    vault = Mock()
    cache = Cache(tmp_path / "state")
    authenticate(client_file, vault, cache)
    for thread in threads:
        thread.join(timeout=5)
    assert callback_statuses == [400, 200]
    flow.fetch_token.assert_called_once_with(code="never-log-this-code", timeout=20)
    vault.save.assert_called_once()
    assert cache.read("auth.json")["status"] == "connected"
    output = capsys.readouterr()
    assert "never-log-this-code" not in output.out + output.err


def test_oauth_denied_does_not_replace_credentials(tmp_path, monkeypatch):
    from fitdash.oauth import authenticate

    client = tmp_path / "client.json"
    client.write_text(
        json.dumps(
            {
                "installed": {
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
    )
    flow = Mock()
    state = {}
    flow.authorization_url.side_effect = lambda **kw: (
        state.update(kw) or "https://accounts.google.com/",
        kw["state"],
    )
    monkeypatch.setattr("fitdash.oauth.InstalledAppFlow.from_client_config", Mock(return_value=flow))
    monkeypatch.setattr("fitdash.oauth.webbrowser.open", Mock(return_value=True))
    server = Mock(server_port=12345)
    server.__enter__ = Mock(return_value=server)
    server.__exit__ = Mock(return_value=False)

    def make(_host, _port, app, **_kwargs):
        server.handle_request.side_effect = lambda: app(
            {"PATH_INFO": "/", "QUERY_STRING": "state=" + state["state"] + "&error=access_denied"}, Mock()
        )
        return server

    monkeypatch.setattr("fitdash.oauth.make_server", make)
    vault = Mock()
    with pytest.raises(AuthError, match="authorization_denied"):
        authenticate(client, vault, Cache(tmp_path / "state"))
    vault.save.assert_not_called()
    flow.fetch_token.assert_not_called()
