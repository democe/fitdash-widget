"""Read-only Google Health v4 adapter, based on the discovery schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests

from fitdash.model import civil_date, metric, number
from fitdash.oauth import PREFIX

BASE = "https://health.googleapis.com/v4/users/me/"
ACTIVITY = [
    ("steps", "steps", "countSum", ""),
    ("distance", "distance", "millimetersSum", "mm"),
    ("active-energy-burned", "activeEnergyBurned", "kcalSum", "kcal"),
    ("active-zone-minutes", "activeZoneMinutes", None, "min"),
]
VITALS = [
    ("resting-heart-rate", "daily-resting-heart-rate", "dailyRestingHeartRate", "beatsPerMinute", "bpm"),
    (
        "hrv",
        "daily-heart-rate-variability",
        "dailyHeartRateVariability",
        "averageHeartRateVariabilityMilliseconds",
        "ms",
    ),
    ("spo2", "daily-oxygen-saturation", "dailyOxygenSaturation", "averagePercentage", "%"),
]


class ApiError(Exception):
    def __init__(self, status, retry_after=0):
        self.status, self.retry_after = status, retry_after


class GoogleHealth:
    def __init__(self, token, scopes, source="all-sources"):
        self.token = token
        self.scopes = set(scopes or [])
        self.source = "users/me/dataSourceFamilies/" + source

    def request(self, path, body=None, params=None):
        try:
            with requests.request(
                "POST" if body is not None else "GET",
                BASE + path,
                headers={"Authorization": "Bearer " + self.token},
                json=body,
                params=params,
                timeout=(4, 8),
                stream=True,
            ) as response:
                if response.status_code != 200:
                    retry = response.headers.get("Retry-After", "0")
                    raise ApiError(response.status_code, min(86400, int(retry)) if retry.isdigit() else 0)
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ApiError(502)
                    chunks.append(chunk)
                import json

                result = json.loads(b"".join(chunks))
                if not isinstance(result, dict):
                    raise ApiError(502)
                return result
        except (requests.RequestException, ValueError):
            raise ApiError(503) from None

    def settings(self):
        if PREFIX + "settings.readonly" not in self.scopes:
            return {}
        return self.request("settings")

    def daily(self, spec, day, recent_days=1):
        datatype, field, value_field, unit = spec

        def civil(d):
            return {"date": {"year": d.year, "month": d.month, "day": d.day}}

        body = {
            "range": {
                "start": civil(day - timedelta(days=recent_days - 1)),
                "end": civil(day + timedelta(days=1)),
            },
            "windowSizeDays": 1,
            "dataSourceFamily": self.source,
        }
        response = self.request("dataTypes/" + datatype + "/dataPoints:dailyRollUp", body)
        rows = response.get("rollupDataPoints", [])
        matching = [r for r in rows if civil_date(r["civilStartTime"]["date"]) == day.isoformat()]
        if len(matching) > 1:
            raise ValueError("Unexpected duplicate rollups")
        data = matching[0].get(field) if matching else None
        value = None
        if data is not None:
            if value_field:
                # Protobuf omits scalar zero defaults within a present value message.
                value = number(data.get(value_field, 0))
            else:
                value = sum(
                    number(data.get(k, 0))
                    for k in ("sumInPeakHeartZone", "sumInFatBurnHeartZone", "sumInCardioHeartZone")
                )
        result = metric(datatype, value, unit, day.isoformat(), group="activity")
        recent = []
        for row in rows:
            period = civil_date(row["civilStartTime"]["date"])
            if not (str(day - timedelta(days=recent_days - 1)) <= period < str(day)) or field not in row:
                continue
            previous = row[field]
            previous_value = (
                number(previous.get(value_field, 0))
                if value_field
                else sum(
                    number(previous.get(k, 0))
                    for k in ("sumInPeakHeartZone", "sumInFatBurnHeartZone", "sumInCardioHeartZone")
                )
            )
            recent.append(metric(datatype, previous_value, unit, period, group="activity"))
        result["recent"] = recent
        return result

    def records(self, datatype, expression):
        params = {"filter": expression, "pageSize": 25, "dataSourceFamily": self.source}
        points, seen = [], set()
        for _ in range(8):
            response = self.request("dataTypes/" + datatype + "/dataPoints:reconcile", params=params)
            points.extend(response.get("dataPoints", []))
            token = response.get("nextPageToken")
            if not token:
                return points
            if token in seen:
                raise ValueError("Repeated page token")
            seen.add(token)
            params["pageToken"] = token
        raise ValueError("Too many pages")

    def vital(self, spec, day):
        key, datatype, field, value_field, unit = spec
        attr = datatype.replace("-", "_") + ".date"
        rows = self.records(
            datatype, f'{attr} >= "{day - timedelta(days=6)}" AND {attr} < "{day + timedelta(days=1)}"'
        )
        values = [r[field] for r in rows if field in r]
        values.sort(key=lambda r: civil_date(r["date"]), reverse=True)
        selected = values[0] if values else None
        return metric(
            key,
            selected.get(value_field) if selected else None,
            unit,
            civil_date(selected["date"]) if selected else day.isoformat(),
            group="vitals",
        )

    def sleep(self, day):
        rows = self.records(
            "sleep",
            f'sleep.interval.civil_end_time >= "{day - timedelta(days=2)}" AND sleep.interval.civil_end_time < "{day + timedelta(days=1)}"',
        )
        sleeps = [r["sleep"] for r in rows if "sleep" in r]
        sleeps.sort(key=lambda r: r["interval"]["endTime"], reverse=True)
        # Prefer the latest main sleep, falling back to the latest recorded sleep.
        mains = [r for r in sleeps if r.get("metadata", {}).get("mainSleep")]
        selected = (mains or sleeps or [None])[0]
        value, period = None, day.isoformat()
        if selected:
            value = selected.get("summary", {}).get("minutesAsleep")
            end = selected["interval"]
            period = civil_date(end["civilEndTime"]["date"]) if "civilEndTime" in end else end["endTime"][:10]
        return metric("sleep", value, "sleep_min", period, group="sleep")

    def collect(self, day, sleep=True, vitals=True):
        jobs = [(s[0], "activity", lambda s=s: self.daily(s, day, recent_days=2)) for s in ACTIVITY]
        if sleep:
            jobs.append(("sleep", "sleep", lambda: self.sleep(day)))
        if vitals:
            jobs.extend((s[0], "vitals", lambda s=s: self.vital(s, day)) for s in VITALS)

        def fetch(job):
            key, group, fn = job
            scope = {
                "activity": "activity_and_fitness",
                "sleep": "sleep",
                "vitals": "health_metrics_and_measurements",
            }[group]
            if PREFIX + scope + ".readonly" not in self.scopes:
                return metric(key, period=day.isoformat(), status="not_authorized", group=group)
            try:
                return fn()
            except ApiError as error:
                status = {
                    401: "reconnect_required",
                    403: "not_authorized",
                    404: "unsupported",
                    429: "rate_limited",
                }.get(error.status, "error")
                return metric(
                    key, period=day.isoformat(), status=status, group=group, retry_after=error.retry_after
                )
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                return metric(key, period=day.isoformat(), status="invalid_response", group=group)

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(fetch, jobs))
