"""Read clock and outdoor weather data for a future verified knob transport.

This tool does not send Bluetooth packets or update the physical knob. It uses
Home Assistant's configured timezone and selected weather entity, and never
substitutes a made-up temperature when weather data is missing or stale.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request
from zoneinfo import ZoneInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knob_bridge"))
from weather_source import weather_temperature


def make_snapshot(config, weather_state, *, now=None, max_age_seconds=10800):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Clock time must have a timezone")
    zone_name = config["time_zone"]
    local = now.astimezone(ZoneInfo(zone_name))
    return {
        "physical_knob_updated": False,
        "clock": {"unix_seconds": int(now.timestamp()), "timezone": zone_name,
                  "utc_offset_seconds": int(local.utcoffset().total_seconds()),
                  "local_iso": local.isoformat(timespec="seconds"),
                  "year": local.year, "month": local.month, "day": local.day,
                  "hour": local.hour, "minute": local.minute, "second": local.second,
                  "weekday_iso": local.isoweekday()},
        "weather": weather_temperature(weather_state, now,
                                       max_age_seconds=max_age_seconds),
    }


def read_snapshot(credentials_path, *, entity_id="weather.forecast_home",
                  max_age_seconds=10800):
    if not entity_id.startswith("weather.") or any(c not in
            "abcdefghijklmnopqrstuvwxyz0123456789_." for c in entity_id):
        raise ValueError("A weather entity ID is required")
    credentials = json.loads(Path(credentials_path).read_text())
    headers = {"Authorization": "Bearer " + credentials["token"]}

    def get(path):
        request = urllib.request.Request(credentials["url"].rstrip("/") + path,
                                         headers=headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    return make_snapshot(get("/api/config"), get("/api/states/" + entity_id),
                         max_age_seconds=max_age_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path,
                        default=Path.home() / ".local/state/yeegate/homeassistant.json")
    parser.add_argument("--weather", default="weather.forecast_home")
    parser.add_argument("--max-weather-age", type=int, default=10800)
    args = parser.parse_args()
    if args.max_weather_age <= 0:
        parser.error("--max-weather-age must be positive seconds")
    print(json.dumps(read_snapshot(args.credentials, entity_id=args.weather,
                                   max_age_seconds=args.max_weather_age), indent=2))
