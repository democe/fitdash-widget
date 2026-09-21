"""Small stable presentation model, independent of API response shapes."""

import locale
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass


def number(value):
    if value is None or isinstance(value, bool):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Invalid measurement")
    return int(value) if value.is_integer() else value


def civil_date(value):
    return date(int(value["year"]), int(value["month"]), int(value["day"])).isoformat()


def today(timezone=""):
    return datetime.now(ZoneInfo(timezone) if timezone else None).date()


def format_value(value, unit, units="metric"):
    if value is None:
        return "—"
    if unit == "mm":
        value /= 1_609_344 if units == "imperial" else 1_000_000
        return locale.format_string("%.2f", value, grouping=True) + (" mi" if units == "imperial" else " km")
    if unit == "sleep_min":
        return f"{int(value) // 60} h {int(value) % 60:02d} min"
    decimals = 1 if unit in ("ms", "%") else 0
    return locale.format_string("%." + str(decimals) + "f", value, grouping=True) + (
        f" {unit}" if unit else ""
    )


def metric(key, value=None, unit="", period="", status="available", **extra):
    value = number(value)
    return dict(
        key=key,
        value=value,
        unit=unit,
        period=period,
        status="no_data" if value is None and status == "available" else status,
        **extra,
    )


def present(snapshot, now, units, current_date, interval=300):
    import copy

    result = copy.deepcopy(snapshot)
    for item in result.get("metrics", []):
        item["display"] = format_value(item.get("value"), item.get("unit", ""), units)
        age = now - item.get("fetched_at", 0)
        if item.get("status") == "available" and (
            age > (5400 if item.get("group") in ("sleep", "vitals") else max(900, interval * 3))
            or (item.get("group") == "activity" and item.get("period") != current_date)
        ):
            item["status"] = "stale"
    steps = next((m for m in result.get("metrics", []) if m["key"] == "steps"), {})
    result["steps"] = steps.get("value") if steps.get("period") == current_date else None
    result["steps_stale"] = steps.get("status") == "stale"
    result["steps_text"] = format_value(result["steps"], "")
    result["today"] = current_date
    return result
