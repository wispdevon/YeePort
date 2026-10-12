"""Capture BLE advertisements without connecting or changing device state."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakScanner

MESH_SERVICES = {
    "00001827-0000-1000-8000-00805f9b34fb": "mesh_provisioning",
    "00001828-0000-1000-8000-00805f9b34fb": "mesh_proxy",
}


async def scan(seconds, output):
    count = 0
    seen = set()
    with output.open("w", encoding="utf-8") as stream:
        def record(device, advertisement):
            nonlocal count
            data = {
                "address": device.address,
                "name": advertisement.local_name,
                "rssi": advertisement.rssi,
                "service_uuids": advertisement.service_uuids,
                "service_data": {k: v.hex() for k, v in advertisement.service_data.items()},
                "manufacturer_data": {
                    str(k): v.hex() for k, v in advertisement.manufacturer_data.items()
                },
                "mesh_services": [
                    MESH_SERVICES[u.lower()]
                    for u in advertisement.service_uuids
                    if u.lower() in MESH_SERVICES
                ],
            }
            # Keep changed payloads, without filling the capture with RSSI updates.
            signature = json.dumps({k: v for k, v in data.items() if k != "rssi"}, sort_keys=True)
            if signature in seen:
                return
            seen.add(signature)
            data["time"] = datetime.now(timezone.utc).isoformat()
            stream.write(json.dumps(data) + "\n")
            stream.flush()
            count += 1
            if (data["mesh_services"]
                    or 0x0164 in advertisement.manufacturer_data
                    or "yee" in (data["name"] or "").lower()):
                print(json.dumps(data), flush=True)

        async with BleakScanner(detection_callback=record):
            await asyncio.sleep(seconds)
    print(f"Saved {count} distinct advertisements to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("ble-capture.jsonl"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error("--seconds must be between 1 and 300")
    asyncio.run(scan(args.seconds, args.output))


if __name__ == "__main__":
    main()
