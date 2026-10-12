"""Reflect HA light-group state in the knob's verified slot-3 display cache."""
import asyncio
import hashlib
import json
import os
import time
from urllib.request import Request, urlopen

from bleak import BleakClient
from clock_sync import KNOB_ADDRESS, DISPLAY_CHARACTERISTIC
from display_config import light_state_packet, color_light_state_packet, test_menu_packets


def light_display_state(state, *, color_controls=False):
    if state.get("state") not in ("on", "off"):
        return None
    brightness = state.get("attributes", {}).get("brightness")
    if brightness is None and state["state"] == "off":
        brightness = 0
    if type(brightness) is not int or not 0 <= brightness <= 255:
        return None
    result = state["state"] == "on", round(brightness * 100 / 255)
    if not color_controls:
        return result
    attributes = state.get("attributes", {})
    kelvin, rgb = attributes.get("color_temp_kelvin"), attributes.get("rgb_color")
    if attributes.get("color_mode") == "color_temp" and type(kelvin) is int and 1000 <= kelvin <= 20000:
        return result + (2, kelvin)
    if isinstance(rgb, (list, tuple)) and len(rgb) == 3 and all(type(v) is int and 0 <= v <= 255 for v in rgb):
        return result + (1, tuple(rgb))
    return result + (2, 4000)


def read_light_state(entity, color_controls=False):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("Home Assistant app API access is required")
    request = Request("http://supervisor/core/api/states/" + entity,
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as response:
        return light_display_state(json.load(response), color_controls=color_controls)


async def send_light_state(device, state, busy, *, initialize_menu=False):
    async with BleakClient(device, timeout=20) as client:
        replies = asyncio.Queue()
        await client.start_notify(DISPLAY_CHARACTERISTIC,
                                  lambda _, data: replies.put_nowait(bytes(data)))
        identity = hashlib.md5(bytes.fromhex(KNOB_ADDRESS.replace(":", ""))[::-1] + b"YEELIGHT").digest()
        await client.write_gatt_char(DISPLAY_CHARACTERISTIC, b"\x01" + identity, response=True)
        if await asyncio.wait_for(replies.get(), 5) != b"\x01\x00":
            raise RuntimeError("Display identity rejected")
        if busy():
            return False
        if initialize_menu:
            # Rehydrate the same verified three entries before the type-specific
            # state setter. Keep both relay entries and existing label indices.
            for entry in test_menu_packets(int(time.time()) & 255, color_controls=len(state) == 4):
                for offset in range(0, len(entry), 20):
                    chunk = entry[offset:offset + 20]
                    if offset + len(chunk) == len(entry):
                        chunk += b"\xff" * ((-len(chunk)) % 4)
                    await client.write_gatt_char(DISPLAY_CHARACTERISTIC, chunk, response=True)
                    await asyncio.sleep(.05)
                await asyncio.sleep(.15)
        args = dict(power=state[0], brightness=state[1], sequence=int(time.monotonic() * 10) & 0xffff)
        packet = (color_light_state_packet(**args, mode=state[2], value=state[3]) if len(state) == 4
                  else light_state_packet(**args))
        await client.write_gatt_char(DISPLAY_CHARACTERISTIC, packet, response=True)
        return True


async def run_light_sync(entity, stopped, *, lock, find_device, busy, suppress_activity,
                         color_controls=False, on_feedback=None):
    last_state, last_sent = None, 0
    while not stopped.is_set():
        try:
            if not busy():
                state = await asyncio.to_thread(read_light_state, entity, color_controls)
                if state is not None and (state != last_state or time.monotonic() - last_sent >= 30):
                    async with lock:
                        if not busy():
                            suppress_activity(80)
                            try:
                                device = await find_device(KNOB_ADDRESS)
                                sent = await asyncio.wait_for(send_light_state(
                                    device, state, busy, initialize_menu=last_state is None), 35)
                            finally:
                                suppress_activity(5)
                            if sent:
                                last_state, last_sent = state, time.monotonic()
                                if on_feedback and not busy():
                                    on_feedback(state[1])
                                print(json.dumps({"light_display": "synchronized", "entity_id": entity,
                                                  "power": state[0], "brightness_pct": state[1]}), flush=True)
        except Exception as exc:
            print(json.dumps({"light_display": "retry", "error": type(exc).__name__}), flush=True)
        try:
            await asyncio.wait_for(stopped.wait(), 5)
        except TimeoutError:
            pass
