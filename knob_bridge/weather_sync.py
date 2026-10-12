"""Bounded outdoor temperature updates through the verified S Knob UART setter.

The temperature is Celsius and comes from Home Assistant weather. Weather keys
select installed firmware assets verified in the official 1.4.25 resource table.
Unsupported conditions use key zero, for which the table has no weather asset.
This module never uploads weather images, firmware, or relay settings.
"""

import asyncio
import binascii
import hashlib
import math
import struct
import time

from bleak import BleakClient, BleakScanner
from clock_sync import DISPLAY_CHARACTERISTIC, KNOB_ADDRESS
from weather_source import read_supervisor_weather


CONDITION_LABELS = {
    "clear-night": "Clear night", "cloudy": "Cloudy", "exceptional": "Outdoor",
    "fog": "Fog", "hail": "Hail", "lightning": "Thunderstorms",
    "lightning-rainy": "Thunderstorms", "partlycloudy": "Partly cloudy",
    "pouring": "Heavy rain", "rainy": "Rainy", "snowy": "Snowy",
    "snowy-rainy": "Snow and rain", "sunny": "Sunny", "windy": "Windy",
    "windy-variant": "Windy",
}

# Official ESP32 data table at 0x3fca157c: 149 records, 104 bytes each.
# Type 5 records store the image key at +88 and its filename at +4.
# qing=clear/sunny, yin=overcast, duoyun=partly cloudy. Rain/snow variants
# select the closest installed asset; these are existing files, not uploads.
CONDITION_ICON_KEYS = {
    "sunny": 1, "cloudy": 2, "partlycloudy": 3,
    "rainy": 10, "pouring": 17, "lightning": 20, "lightning-rainy": 21,
    "hail": 31, "snowy": 43, "snowy-rainy": 40, "fog": 50,
}


def weather_packet(temperature_c, *, sequence=1, condition=None):
    if (isinstance(temperature_c, bool) or not isinstance(temperature_c, (int, float))
            or not math.isfinite(temperature_c) or not -100 <= temperature_c <= 100):
        raise ValueError("A finite, bounded Celsius outdoor temperature is required")
    if not 0 <= sequence <= 65535:
        raise ValueError("A 16-bit sequence is required")
    label = CONDITION_LABELS.get(condition, "Outdoor").encode("ascii")
    temperature = format(temperature_c, ".1f").rstrip("0").rstrip(".").encode("ascii")
    if temperature == b"-0":
        temperature = b"0"
    if len(label) > 23 or len(temperature) > 8:
        raise ValueError("Weather strings exceed verified firmware buffer bounds")
    payload = b"\x05\x09" + bytes((len(label),)) + label
    payload += bytes((len(temperature),)) + temperature + bytes((CONDITION_ICON_KEYS.get(condition, 0),))
    header = bytes.fromhex("f0f1f2f3") + bytes((1, 0x1c, 0))
    header += struct.pack("<HH", sequence, len(payload))
    return header + payload + struct.pack("<H", binascii.crc_hqx(payload, 0))


async def sync_temperature_once(temperature_c, *, address=KNOB_ADDRESS, adapter="hci0", device=None, condition=None):
    if address.upper() != KNOB_ADDRESS:
        raise ValueError("Only the verified S Knob is accepted")
    packet = weather_packet(temperature_c, condition=condition)
    if device is None:
        device = await BleakScanner.find_device_by_address(address, timeout=20, adapter=adapter)
    if device is None:
        raise RuntimeError("Knob not found")
    async with BleakClient(device, timeout=20) as client:
        char = client.services.get_characteristic(DISPLAY_CHARACTERISTIC)
        if char is None:
            raise RuntimeError("Verified display UART is missing")
        queue = asyncio.Queue()
        await client.start_notify(char, lambda _, data: queue.put_nowait(bytes(data)))
        identity = hashlib.md5(bytes.fromhex(address.replace(":", ""))[::-1] + b"YEELIGHT").digest()
        await client.write_gatt_char(char, b"\x01" + identity, response=True)
        if await asyncio.wait_for(queue.get(), 5) != b"\x01\x00":
            raise RuntimeError("Display identity handshake failed")
        for offset in range(0, len(packet), 20):
            chunk = packet[offset:offset + 20]
            if offset + len(chunk) == len(packet):
                chunk += b"\xff" * ((-len(chunk)) % 4)
            await client.write_gatt_char(char, chunk, response=True)
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        await client.stop_notify(char)
    return {"temperature_c_sent": temperature_c, "label": CONDITION_LABELS.get(condition, "Outdoor"),
            "bytes_written": len(packet), "weather_icon_key": CONDITION_ICON_KEYS.get(condition, 0),
            "weather_icon": "installed" if condition in CONDITION_ICON_KEYS else "unavailable",
            "physical_screen_confirmation": "required"}


async def run_weather_sync(options, stopped, *, lock, suppress_activity, find_device=None):
    """Read HA every five minutes, update changed values, refresh hourly.

    The caller shares the clock updater's BLE lock and activity-suppression
    callback. API failures or stale readings leave the last displayed value
    untouched; they never substitute zero or a fabricated outdoor reading.
    """
    if not options.get("weather_sync_enabled", False):
        return
    address = options.get("address", KNOB_ADDRESS).upper()
    adapter = options.get("adapter", "hci0")
    entity = options.get("weather_entity", "weather.forecast_home")
    if address != KNOB_ADDRESS:
        raise ValueError("Weather sync is only supported for the verified S Knob")
    previous_temperature = None
    previous_sent_at = 0
    while not stopped.is_set():
        try:
            weather = await asyncio.to_thread(read_supervisor_weather, entity)
            if weather["available"]:
                temperature = round(weather["temperature_c"], 1)
                reading = (temperature, CONDITION_LABELS.get(weather.get("condition"), "Outdoor"),
                           CONDITION_ICON_KEYS.get(weather.get("condition"), 0))
                if reading != previous_temperature or time.monotonic() - previous_sent_at >= 3600:
                    async with lock:
                        suppress_activity(80)
                        try:
                            kwargs = {"device": await find_device(address)} if find_device else {}
                            await asyncio.wait_for(sync_temperature_once(
                                temperature, address=address, adapter=adapter,
                                condition=weather.get("condition"), **kwargs), timeout=50)
                            previous_temperature = reading
                            previous_sent_at = time.monotonic()
                            icon_status = ("installed weather icon key " + str(reading[2])
                                           if reading[2] else "weather icon unavailable")
                            print("Knob outdoor temperature synchronized: " + str(temperature) +
                                  " C; " + reading[1] + " (" + icon_status + ")", flush=True)
                        finally:
                            suppress_activity(5)
            else:
                print("Knob outdoor temperature unchanged: " + weather["reason"], flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("Knob weather sync will retry (" + type(error).__name__ + ": " + str(getattr(error, "dbus_error", "")) + ")", flush=True)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=300)
        except TimeoutError:
            pass
