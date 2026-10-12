"""Validate Home Assistant outdoor weather without inventing missing readings."""

from datetime import datetime, timezone
import json
import math
import os
import re
from urllib.request import Request, urlopen


def weather_temperature(state, now, *, max_age_seconds=10800):
    if state.get("state") in (None, "unknown", "unavailable"):
        return {"available": False, "reason": "weather_unavailable"}
    attributes = state.get("attributes", {})
    temperature = attributes.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        return {"available": False, "reason": "temperature_missing"}
    if not math.isfinite(temperature):
        return {"available": False, "reason": "temperature_invalid"}
    units = attributes.get("temperature_unit")
    if units == "°F":
        temperature = (temperature - 32) * 5 / 9
    elif units != "°C":
        return {"available": False, "reason": "temperature_unit_unknown"}
    reported = state.get("last_reported") or state.get("last_updated")
    try:
        reported_at = datetime.fromisoformat(reported.replace("Z", "+00:00"))
        if reported_at.tzinfo is None:
            raise ValueError("Weather timestamp must have an offset")
        age = (now - reported_at).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return {"available": False, "reason": "weather_timestamp_missing"}
    if age < -300 or age > max_age_seconds:
        return {"available": False, "reason": "weather_stale"}
    if not -100 <= temperature <= 100:
        return {"available": False, "reason": "temperature_out_of_range"}
    return {"available": True, "entity_id": state["entity_id"],
            "temperature_c": round(temperature, 2),
            "condition": state["state"], "reported_at": reported_at.isoformat(),
            "age_seconds": max(0, round(age))}


def read_supervisor_weather(entity_id="weather.forecast_home"):
    """Use the app's built-in HA API proxy permission and ephemeral token."""
    if not re.fullmatch(r"weather\.[a-z0-9_]+", entity_id):
        raise ValueError("A weather entity ID is required")
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("Home Assistant app API access is required")
    request = Request("http://supervisor/core/api/states/" + entity_id,
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as response:
        state = json.load(response)
    return weather_temperature(state, datetime.now(timezone.utc))
