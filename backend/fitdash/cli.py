"""JSON command boundary for the Noctalia service."""

import argparse
import json
import os
import random
import time
from pathlib import Path

from fitdash.cache import Busy, Cache
from fitdash.model import number, present, today
from fitdash.oauth import AuthError, Vault, authenticate, refreshed, SCOPES
from fitdash.providers.google_health import ApiError, GoogleHealth


def default_state():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "fitdash-widget"


def snapshot(cache):
    data = cache.read("snapshot.json", {})
    if data.get("version") != 1 or not isinstance(data.get("metrics"), list):
        return {"version": 1, "status": "disconnected", "metrics": []}
    if any(not isinstance(m, dict) or not isinstance(m.get("key"), str) for m in data["metrics"]):
        return {"version": 1, "status": "invalid_cache", "metrics": []}
    try:
        if not isinstance(data.get("settings", {}), dict):
            raise ValueError("settings")
        keys = set()
        for item in data["metrics"]:
            if item["key"] in keys:
                raise ValueError("duplicate metric")
            keys.add(item["key"])
            if item.get("value") is not None:
                if isinstance(item["value"], (bool, str)):
                    raise ValueError("measurement type")
                number(item["value"])
            for key in ("fetched_at",):
                if key in item and (isinstance(item[key], (bool, str)) or number(item[key]) is None):
                    raise ValueError("timestamp")
            if not all(isinstance(item.get(key, ""), str) for key in ("period", "unit", "status", "group")):
                raise ValueError("metadata")
        for key in ("updated_at", "retry_at", "attempted_at"):
            if key in data and (isinstance(data[key], (bool, str)) or number(data[key]) is None):
                raise ValueError("timestamp")
        today(data.get("timezone", ""))
    except (ValueError, TypeError, KeyError):
        return {"version": 1, "status": "invalid_cache", "metrics": []}
    return data


def sync(cache, vault, args):
    old = snapshot(cache)
    now = time.time()
    schedule = cache.read("scheduler.json", {})
    try:
        if any(isinstance(v, (bool, str)) or number(v) is None for v in schedule.values()):
            raise ValueError("invalid schedule")
        if schedule.get("attempted_at", 0) > now + 60 or schedule.get("retry_at", 0) > now + 86400:
            raise ValueError("invalid schedule")
    except (ValueError, TypeError):
        schedule = {}
    # Source changes invalidate values; don't show data from the previous selection.
    if old.get("source", args.source) != args.source:
        old = {"version": 1, "metrics": []}
        cache.remove("snapshot.json")
        schedule = {}
    if now < schedule.get("retry_at", 0):
        return old
    if now - schedule.get("attempted_at", 0) < (30 if args.force else args.interval):
        return old
    schedule["attempted_at"] = now
    cache.write("scheduler.json", schedule)
    credentials = refreshed(vault)
    api = GoogleHealth(credentials.token, credentials.scopes, args.source)
    settings = old.get("settings", {})
    if now - settings.get("_fetched_at", 0) > 86400:
        try:
            settings = api.settings()
            settings["_fetched_at"] = now
        except ApiError:
            pass
    timezone = args.timezone or settings.get("timeZone", "")
    day = today(timezone)
    old_metrics = {m["key"]: m for m in old.get("metrics", [])}

    def due(group):
        entries = [m for m in old_metrics.values() if m.get("group") == group]
        return args.force or not entries or any(now - m.get("fetched_at", 0) >= 1800 for m in entries)

    fetch_sleep, fetch_vitals = args.sleep and due("sleep"), args.vitals and due("vitals")
    metrics = api.collect(day, fetch_sleep, fetch_vitals)
    if any(m["status"] == "reconnect_required" for m in metrics):
        credentials = refreshed(vault, force=True)
        api = GoogleHealth(credentials.token, credentials.scopes, args.source)
        metrics = api.collect(day, fetch_sleep, fetch_vitals)
    transient = {"error", "rate_limited", "invalid_response"}
    history = []
    failures, retry_after = 0, 0
    for i, m in enumerate(metrics):
        history.extend(m.pop("recent", []))
        if m["status"] in transient:
            failures += 1
            retry_after = max(retry_after, m.get("retry_after", 0))
            previous = old_metrics.get(m["key"])
            if previous and previous.get("value") is not None:
                metrics[i] = dict(previous, status="stale", error=m["status"])
        else:
            m["fetched_at"] = now
    for group, enabled, fetched in (
        ("sleep", args.sleep, fetch_sleep),
        ("vitals", args.vitals, fetch_vitals),
    ):
        if enabled and not fetched:
            metrics.extend(m for m in old_metrics.values() if m.get("group") == group)
    if failures:
        attempt = min(8, schedule.get("failures", 0) + 1)
        schedule.update(
            failures=attempt,
            retry_at=now + max(retry_after, min(3600, 30 * 2**attempt) + random.uniform(0, 15)),
        )
    else:
        schedule.update(failures=0, retry_at=0)
    data = dict(
        version=1,
        status=(
            "reconnect_required"
            if any(m["status"] == "reconnect_required" for m in metrics)
            else "partial"
            if failures
            else "connected"
        ),
        metrics=metrics,
        settings=settings,
        timezone=timezone,
        source=args.source,
        updated_at=max((m.get("fetched_at", 0) for m in metrics), default=old.get("updated_at", 0)),
        attempted_at=now,
        retry_at=schedule.get("retry_at", 0),
    )
    cache.merge_history(history + metrics, day)
    cache.write("snapshot.json", data)
    cache.write("scheduler.json", schedule)
    cache.write("auth.json", {"status": "connected"})
    return data


def execute(args):
    cache = Cache(args.state_dir)
    vault = Vault("democe/fitdash")
    if args.command == "demo":
        from fitdash.model import metric

        d = today(args.timezone).isoformat()
        data = {
            "version": 1,
            "status": "demo",
            "metrics": [
                metric("steps", 8432, "", d, group="activity", fetched_at=time.time()),
                metric("distance", 6100000, "mm", d, group="activity", fetched_at=time.time()),
                metric("active-zone-minutes", 32, "min", d, group="activity", fetched_at=time.time()),
                metric("sleep", 462, "sleep_min", d, group="sleep", fetched_at=time.time()),
                metric("resting-heart-rate", 61, "bpm", d, group="vitals", fetched_at=time.time()),
            ],
        }
    elif args.command == "status":
        data = snapshot(cache)
        auth = cache.read("auth.json", {})
        if auth.get("status") == "authorizing" and time.time() - auth.get("started_at", 0) < 330:
            data["status"] = "authorizing"
        elif auth.get("status") == "authorizing":
            data["status"] = "authorization_timeout"
        elif auth.get("status") not in (None, "connected"):
            data["status"] = auth["status"]
    else:
        with cache.lock():
            try:
                if args.command == "auth":
                    try:
                        scopes = [
                            s
                            for s in SCOPES
                            if (args.sleep or ".sleep." not in s)
                            and (args.vitals or ".health_metrics_and_measurements." not in s)
                        ]
                        authenticate(args.client, vault, cache, scopes)
                    except AuthError as error:
                        cache.write("auth.json", {"status": str(error)})
                        raise
                    data = sync(cache, vault, args)
                elif args.command == "sync":
                    data = sync(cache, vault, args)
                elif args.command == "clear-cache":
                    cache.clear_health()
                    data = {"version": 1, "status": "cache_cleared", "metrics": []}
                    cache.write("snapshot.json", data)
                else:
                    creds = vault.load()
                    vault.clear()
                    for name in ("snapshot.json", "scheduler.json", "history.json", "auth.json"):
                        cache.remove(name)
                    data = {"version": 1, "status": "disconnected", "metrics": []}
                    if creds:
                        import requests

                        try:
                            r = requests.post(
                                "https://oauth2.googleapis.com/revoke",
                                data={"token": creds.refresh_token or creds.token},
                                timeout=10,
                            )
                            if r.status_code != 200:
                                data["status"] = "disconnected_revocation_failed"
                        except requests.RequestException:
                            data["status"] = "disconnected_revocation_failed"
            except AuthError as error:
                data = snapshot(cache)
                data["status"] = str(error)
                cache.write("snapshot.json", data)
            except Exception as error:
                # Keep cache and credentials intact; never expose exception messages.
                data = snapshot(cache)
                data.update(status="backend_error", error_type=type(error).__name__)
                cache.write("snapshot.json", data)
                if args.command == "auth":
                    cache.write("auth.json", {"status": "backend_error"})
    units = args.units
    if units == "auto":
        units = (
            "imperial" if data.get("settings", {}).get("distanceUnit") == "DISTANCE_UNIT_MILES" else "metric"
        )
    return present(
        data, time.time(), units, today(args.timezone or data.get("timezone", "")).isoformat(), args.interval
    )


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["status", "sync", "auth", "disconnect", "clear-cache", "demo"])
    p.add_argument("--state-dir", default=str(default_state()))
    p.add_argument("--client", default=str(Path.home() / ".config/fitdash-widget/client.json"))
    p.add_argument("--interval", type=int, default=300)
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--source", choices=["all-sources", "google-wearables", "google-sources"], default="all-sources"
    )
    p.add_argument("--timezone", default="")
    p.add_argument("--units", choices=["auto", "metric", "imperial"], default="auto")
    p.add_argument("--sleep", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--vitals", action=argparse.BooleanOptionalAction, default=True)
    return p


def main():
    args = parser().parse_args()
    try:
        data = execute(args)
    except Busy:
        data = {"version": 1, "status": "busy"}
    except Exception as error:
        # Never return upstream exception text: it may contain credentials or payloads.
        data = {"version": 1, "status": "backend_error", "metrics": [], "error_type": type(error).__name__}
    print(json.dumps(data, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
