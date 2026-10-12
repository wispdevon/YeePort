"""Send a fresh, validated HA outdoor temperature snapshot to the physical knob."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knob_bridge"))
from weather_sync import sync_temperature_once


def snapshot_temperature(snapshot):
    weather = snapshot["weather"]
    if weather.get("available") is not True:
        raise ValueError("Fresh outdoor weather is unavailable; refusing a placeholder temperature")
    reported = datetime.fromisoformat(weather["reported_at"].replace("Z", "+00:00"))
    if reported.tzinfo is None:
        raise ValueError("Weather timestamp requires a timezone")
    age = (datetime.now(timezone.utc) - reported).total_seconds()
    if age < -300 or age > 10800:
        raise ValueError("Outdoor weather snapshot is stale")
    return weather["temperature_c"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--adapter", default="hci0")
    args = parser.parse_args()
    temperature = snapshot_temperature(json.loads(args.snapshot.read_text()))
    print(json.dumps(asyncio.run(sync_temperature_once(temperature, adapter=args.adapter))))
