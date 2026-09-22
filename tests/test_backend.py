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


def test_units_and_missing_values(monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setattr("locale.localeconv", lambda: {"decimal_point": ".", "thousands_sep": "", "grouping": []})
    assert format_value(1609344, "mm", "imperial").endswith("1.00 mi")
    assert format_value(462, "sleep_min") == "7 h 42 min"
    assert format_value(None, "") == "—"
    with pytest.raises(ValueError):
        metric("steps", float("nan"))


@pytest.mark.parametrize("separator,grouping,expected", [("", [], "10000"), (",", [3, 0], "10,000"), (".", [3, 0], "10.000"), ("\u202f", [3, 0], "10\u202f000")])
def test_goal_formatting_and_progress(monkeypatch, separator, grouping, expected):
    monkeypatch.setattr("locale.localeconv", lambda: {"decimal_point": ".", "thousands_sep": separator, "grouping": grouping})
    snap = {"metrics": [metric("steps", 8432, period="2026-09-21", group="activity")]}
    res = present(snap, 100, "metric", "2026-09-21", goal=10000)
    assert res["goal"] == 10000
    assert res["goal_text"] == expected
    assert res["goal_percent"] == 84

    args = parser().parse_args(["status", "--goal", "12500"])
    assert args.goal == 12500


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


@pytest.mark.parametrize("language", ["en_US.UTF-8", "fr_FR.UTF-8", "zz_ZZ.UTF-8"])
def test_oauth_validates_state_and_does_not_log_code(tmp_path, monkeypatch, capsys, language):
    monkeypatch.setenv("LC_ALL", language)
    monkeypatch.delenv("LANGUAGE", raising=False)
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
    responses = []
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
                        responses.append((r.headers, r.read().decode("utf-8")))
                except urllib.error.HTTPError as error:
                    callback_statuses.append(error.code)
                    responses.append((error.headers, error.read().decode("utf-8")))

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
    for headers, body in responses:
        assert "charset=utf-8" in headers["Content-Type"]
        assert headers["Cache-Control"] == "no-store"
        assert "never-log-this-code" not in body
    if language.startswith("fr"):
        assert "Réponse d’autorisation non valide" in responses[0][1]
        assert "Autorisation reçue" in responses[1][1]
        assert 'lang="fr"' in responses[1][1]
    else:
        assert "Invalid authorization callback" in responses[0][1]
        assert "Authorization received" in responses[1][1]
    flow.fetch_token.assert_called_once_with(code="never-log-this-code", timeout=20)
    vault.save.assert_called_once()
    assert cache.read("auth.json")["status"] == "connected"
    output = capsys.readouterr()
    assert "never-log-this-code" not in output.out + output.err


def test_oauth_denied_does_not_replace_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
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

    responses = []

    def make(_host, _port, app, **_kwargs):
        server.handle_request.side_effect = lambda: responses.extend(app(
            {"PATH_INFO": "/", "QUERY_STRING": "state=" + state["state"] + "&error=access_denied"}, Mock()
        ))
        return server

    monkeypatch.setattr("fitdash.oauth.make_server", make)
    vault = Mock()
    with pytest.raises(AuthError, match="authorization_denied"):
        authenticate(client, vault, Cache(tmp_path / "state"))
    assert "L’autorisation a été refusée" in b"".join(responses).decode("utf-8")
    vault.save.assert_not_called()
    flow.fetch_token.assert_not_called()


def test_corrupt_snapshot_schema_recovers(tmp_path):
    from fitdash.cli import snapshot

    cache = Cache(tmp_path)
    cache.write("snapshot.json", {"version": 1, "metrics": [{"key": "steps", "value": "garbage"}]})
    assert snapshot(cache)["status"] == "invalid_cache"


def test_history_prunes_and_replaces_corrections(tmp_path):
    cache = Cache(tmp_path)
    cache.write("history.json", {"2026-09-01": {"steps": 100}, "2026-09-20": {"steps": {"value": 900}}})
    cache.merge_history([metric("steps", 800, period="2026-09-20")], date(2026, 9, 21))
    history = cache.read("history.json")
    assert "2026-09-01" not in history
    assert history["2026-09-20"]["steps"]["value"] == 800
    cache.clear_health()
    assert cache.read("history.json") is None


def test_recent_days_backfill_is_separate_from_today():
    client = api(
        {
            "rollupDataPoints": [
                {
                    "civilStartTime": {"date": {"year": 2026, "month": 9, "day": 20}},
                    "steps": {"countSum": "1200"},
                },
                {
                    "civilStartTime": {"date": {"year": 2026, "month": 9, "day": 21}},
                    "steps": {"countSum": "200"},
                },
            ]
        }
    )
    result = client.daily(("steps", "steps", "countSum", ""), date(2026, 9, 21), recent_days=2)
    assert result["value"] == 200
    assert result["recent"][0]["value"] == 1200
    assert result["recent"][0]["period"] == "2026-09-20"


def test_sleep_and_vitals_keep_original_fetch_time_until_due(tmp_path, monkeypatch):
    cache = Cache(tmp_path)
    cache.write(
        "snapshot.json",
        {
            "version": 1,
            "metrics": [
                metric("sleep", 400, period="2026-09-21", group="sleep", fetched_at=990),
                metric("resting-heart-rate", 60, period="2026-09-21", group="vitals", fetched_at=990),
            ],
        },
    )
    client = Mock()
    client.settings.return_value = {}
    client.collect.return_value = [metric("steps", 100, period="2026-09-21", group="activity")]
    monkeypatch.setattr("fitdash.cli.GoogleHealth", Mock(return_value=client))
    monkeypatch.setattr("fitdash.cli.refreshed", Mock(return_value=Mock(token="fake", scopes=[])))
    monkeypatch.setattr("fitdash.cli.time.time", lambda: 1000)
    result = sync(cache, Mock(), parser().parse_args(["sync"]))
    assert client.collect.call_args.args[1:] == (False, False)
    assert next(m for m in result["metrics"] if m["key"] == "sleep")["fetched_at"] == 990


def test_transient_refresh_failure_does_not_require_reauthorization():
    from google.auth.exceptions import RefreshError

    credentials = Mock(valid=False)
    credentials.refresh.side_effect = RefreshError("service unavailable", retryable=True)
    vault = Mock()
    vault.load.return_value = credentials
    with pytest.raises(AuthError, match="^offline$"):
        refreshed(vault)
    vault.clear.assert_not_called()


def test_translations_key_parity():
    from pathlib import Path

    trans_dir = Path(__file__).resolve().parents[1] / "translations"
    en = json.loads((trans_dir / "en.json").read_text(encoding="utf-8"))
    for lang_file in trans_dir.glob("*.json"):
        data = json.loads(lang_file.read_text(encoding="utf-8"))
        assert set(data.keys()) == set(en.keys()), f"Key mismatch in {lang_file.name}"


@pytest.mark.parametrize("environment,expected", [
    ({"LANG": "fr_CA.UTF-8"}, "fr"),
    ({"LANG": "en_US.UTF-8", "LC_MESSAGES": "fr_FR.UTF-8"}, "fr"),
    ({"LC_ALL": "C", "LANGUAGE": "fr"}, "en"),
    ({"LC_ALL": "en_US.UTF-8", "LANGUAGE": "zz:fr:en"}, "fr"),
    ({"LANG": "../../fr"}, "en"),
])
def test_callback_locale_selection(monkeypatch, environment, expected):
    from fitdash.i18n import translation_catalog

    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    language, messages = translation_catalog()
    assert language == expected
    assert messages["oauth.received"]


@pytest.mark.parametrize("language,hour", [("en", "h"), ("fr", "h"), ("nl", "u"), ("zz", "h")])
def test_localized_unit_presentation(monkeypatch, language, hour):
    monkeypatch.setenv("LC_ALL", language + "_XX.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.setattr("locale.localeconv", lambda: {
        "decimal_point": ",", "thousands_sep": ".", "grouping": [3, 0],
    })
    assert format_value(1609344, "mm", "imperial") == "1,00 mi"
    assert format_value(1000000, "mm") == "1,00 km"
    assert format_value(462, "sleep_min") == f"7 {hour} 42 min"
    assert format_value(420, "sleep_min") == f"7 {hour} 00 min"
    for unit, expected in [("kcal", "12 kcal"), ("bpm", "12 bpm"),
                           ("ms", "12,0 ms"), ("%", "12,0 %"), ("min", "12 min")]:
        assert format_value(12, unit) == expected
    assert format_value(0, "bpm") == "0 bpm"
    assert format_value(None, "bpm") == "—"
    assert format_value(1234, "") == "1.234"
    snap = {"metrics": [metric("sleep", 462, "sleep_min")]}
    assert present(snap, 0, "metric", "2026-09-22")["metrics"][0]["display"] == f"7 {hour} 42 min"
    assert snap["metrics"][0]["unit"] == "sleep_min"
    assert "display" not in snap["metrics"][0]


def test_unit_templates_control_labels_and_spacing():
    messages = {"format.measurement": "{value}\u00a0{unit}", "unit.bpm": "beats/min"}
    assert format_value(60, "bpm", messages=messages) == "60\u00a0beats/min"


def test_translation_format_placeholders():
    from pathlib import Path
    from string import Formatter

    directory = Path(__file__).resolve().parents[1] / "translations"
    for path in directory.glob("*.json"):
        messages = json.loads(path.read_text(encoding="utf-8"))
        for key, expected in {
            "format.measurement": {"value", "unit"},
            "format.sleep": {"hours", "hour_unit", "minutes", "minute_unit"},
            "format.date": {"year", "month", "day"},
        }.items():
            fields = {field for _, field, _, _ in Formatter().parse(messages[key]) if field is not None}
            assert fields == expected, (path.name, key)


@pytest.mark.parametrize("language,expected", [
    ("en", "09/22/2026"), ("fr", "22/09/2026"), ("nl", "22-09-2026"),
])
def test_localized_dates_preserve_civil_dates(monkeypatch, language, expected):
    from datetime import datetime
    from fitdash.i18n import translation_catalog
    from fitdash.model import format_date

    monkeypatch.setenv("LC_ALL", language + "_XX.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
    _, messages = translation_catalog()
    stamp = datetime(2026, 9, 22, 12).timestamp()
    snap = {"updated_at": stamp, "metrics": [
        metric("steps", 123, period="2026-09-22", group="activity", fetched_at=stamp),
        metric("sleep", 400, "sleep_min", period="2026-09-21"),
    ]}
    result = present(snap, stamp, "metric", "2026-09-22")
    assert result["today_text"] == expected
    assert result["updated_date_text"] == expected
    assert result["metrics"][0]["period_text"] == expected
    assert result["metrics"][1]["period_text"] == format_date("2026-09-21", messages)
    assert result["today"] == "2026-09-22"
    assert result["steps"] == 123
    assert snap["metrics"][0]["period"] == "2026-09-22"
    assert "period_text" not in snap["metrics"][0]
    assert format_date("2024-02-29", messages) != "—"
    for invalid in (None, "", "2025-02-29", "invalid"):
        assert format_date(invalid, messages) == "—"
