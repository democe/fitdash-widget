"""Small stable presentation model, independent of API response shapes."""

import locale
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fitdash.i18n import translation_catalog

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


def format_value(value, unit, units="metric", messages=None):
    if value is None:
        return "—"
    if unit and messages is None:
        _, messages = translation_catalog()
    if unit == "sleep_min":
        return messages["format.sleep"].format(
            hours=int(value) // 60, minutes=f"{int(value) % 60:02d}",
            hour_unit=messages["unit.h"], minute_unit=messages["unit.min"],
        )
    if unit == "mm":
        value /= 1_609_344 if units == "imperial" else 1_000_000
        unit = "mi" if units == "imperial" else "km"
        decimals = 2
    else:
        decimals = 1 if unit in ("ms", "%") else 0
    text = locale.format_string("%." + str(decimals) + "f", value, grouping=True)
    if not unit:
        return text
    return messages["format.measurement"].format(
        value=text, unit=messages.get("unit." + unit, unit)
    )


def format_date(value, messages):
    """Present a civil date without converting it through a time zone."""
    if not value:
        return "—"
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        return "—"
    return messages["format.date"].format(
        year=f"{day.year:04d}", month=f"{day.month:02d}", day=f"{day.day:02d}"
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


def present(snapshot, now, units, current_date, interval=300, goal=10000):
    import copy

    _, messages = translation_catalog()
    result = copy.deepcopy(snapshot)
    for item in result.get("metrics", []):
        item["display"] = format_value(item.get("value"), item.get("unit", ""), units, messages)
        item["period_text"] = format_date(item.get("period"), messages)
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
    result["goal"] = number(goal)
    result["goal_text"] = format_value(result["goal"], "")
    result["goal_percent"] = (
        int(math.floor(result["steps"] / result["goal"] * 100))
        if result["steps"] is not None and result["goal"]
        else None
    )
    result["today"] = current_date
    result["today_text"] = format_date(current_date, messages)
    if result.get("updated_at") is not None:
        # Fetch timestamps use desktop local time, as the shell did previously.
        fetched = datetime.fromtimestamp(result["updated_at"])
        result["updated_date_text"] = format_date(fetched.date().isoformat(), messages)
    return result
