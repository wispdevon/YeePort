"""Visually test the 30 installed weather icons, then restore real weather.

The temperature number deliberately displays the icon ID during this test.
Only the verified display weather setter is sent: no images or firmware.
Pause the production bridge first to avoid competing Bluetooth connections.
"""
import argparse
import asyncio
import binascii
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knob_bridge"))
from bleak import BleakClient, BleakScanner
from clock_sync import KNOB_ADDRESS, DISPLAY_CHARACTERISTIC
from weather_sync import weather_packet

ICONS = (
    (1, "Sunny"), (2, "Overcast"), (3, "Partly cloudy"),
    (10, "Light rain"), (11, "Showers"), (12, "Drizzle"),
    (13, "Drizzle"), (14, "Drizzle"), (15, "Light rain"),
    (16, "Moderate rain"), (17, "Heavy rain"), (20, "Thunder"),
    (21, "Thundershowers"), (30, "Light rain"), (31, "Hail"),
    (32, "Hail"), (33, "Hail"), (40, "Sleet"), (41, "Sleet"),
    (42, "Moderate snow"), (43, "Light snow"), (44, "Light snow"),
    (45, "Light snow"), (46, "Heavy snow"), (50, "Fog"),
    (51, "Fog"), (60, "Haze"), (61, "Haze"), (62, "Haze"),
    (70, "Sandstorm"),
)


def test_packet(key, title, sequence):
    if (key, title) not in ICONS:
        raise ValueError("Only verified installed weather assets may be tested")
    label = ("Test: " + title).encode("ascii")
    number = str(key).encode("ascii")
    payload = b"\x05\x09" + bytes((len(label),)) + label
    payload += bytes((len(number),)) + number + bytes((key,))
    header = bytes.fromhex("f0f1f2f3") + bytes((1, 0x1c, 0))
    header += struct.pack("<HH", sequence, len(payload))
    return header + payload + struct.pack("<H", binascii.crc_hqx(payload, 0))


async def cycle(seconds, snapshot):
    if not 1 <= seconds <= 30:
        raise ValueError("Hold time must be 1–30 seconds")
    restore = weather_packet(snapshot["temperature_c"], condition=snapshot["condition"])
    device = await BleakScanner.find_device_by_address(KNOB_ADDRESS, timeout=20, adapter="hci0")
    if device is None:
        raise RuntimeError("Knob not found")
    async with BleakClient(device, timeout=20) as client:
        char = client.services.get_characteristic(DISPLAY_CHARACTERISTIC)
        if char is None:
            raise RuntimeError("Verified display UART missing")
        queue = asyncio.Queue()
        await client.start_notify(char, lambda _, data: queue.put_nowait(bytes(data)))
        identity = hashlib.md5(bytes.fromhex(KNOB_ADDRESS.replace(":", ""))[::-1] + b"YEELIGHT").digest()
        await client.write_gatt_char(char, b"\x01" + identity, response=True)
        if await asyncio.wait_for(queue.get(), 5) != b"\x01\x00":
            raise RuntimeError("Display identity rejected")

        async def send(packet):
            for offset in range(0, len(packet), 20):
                chunk = packet[offset:offset + 20]
                if offset + len(chunk) == len(packet):
                    chunk += b"\xff" * ((-len(chunk)) % 4)
                await client.write_gatt_char(char, chunk, response=True)
                await asyncio.sleep(.05)

        try:
            for sequence, (key, name) in enumerate(ICONS, 1):
                await send(test_packet(key, name, sequence))
                print(json.dumps({"icon_id": key, "name": name, "hold_seconds": seconds}), flush=True)
                await asyncio.sleep(seconds)
        finally:
            if client.is_connected:
                await send(restore)
                print(json.dumps({"restored_temperature_c": snapshot["temperature_c"],
                                  "restored_condition": snapshot["condition"]}), flush=True)
                await client.stop_notify(char)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(cycle(args.seconds, json.loads(args.snapshot.read_text())))
