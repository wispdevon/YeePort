"""Reflect HA light-group state in the knob's verified slot-3 display cache."""
import asyncio
import base64
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from bleak import BleakClient
from clock_sync import KNOB_ADDRESS, DISPLAY_CHARACTERISTIC
from display_config import light_state_packet, color_light_state_packet, test_menu_packets
from knob_display_codec import label_packet
from channel_control import independent_display_state


def light_display_state(state, *, color_controls=False, separate_controls=False):
    if state.get("state") not in ("on", "off"):
        return None
    brightness = state.get("attributes", {}).get("brightness")
    if brightness is None and state["state"] == "off":
        brightness = 0
    if type(brightness) is not int or not 0 <= brightness <= 255:
        return None
    result = state["state"] == "on", round(brightness * 100 / 255)
    if separate_controls:
        mode = state.get('attributes', {}).get('color_mode')
        rgb_on = result[0] and mode in ('rgb', 'rgbw', 'rgbww', 'hs', 'xy')
        warm_on = result[0] and mode == 'color_temp'
        return {'rgb': (rgb_on, result[1] if rgb_on else 0),
                'warm': (warm_on, result[1] if warm_on else 0)}
    if not color_controls:
        return result
    attributes = state.get("attributes", {})
    kelvin, rgb = attributes.get("color_temp_kelvin"), attributes.get("rgb_color")
    if attributes.get("color_mode") == "color_temp" and type(kelvin) is int and 1000 <= kelvin <= 20000:
        return result + (2, kelvin)
    if isinstance(rgb, (list, tuple)) and len(rgb) == 3 and all(type(v) is int and 0 <= v <= 255 for v in rgb):
        return result + (1, tuple(rgb))
    return result + (2, 4000)


def read_light_state(entity, color_controls=False, separate_controls=False, independent_channels=False,
                     ha_lights_menu=False):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("Home Assistant app API access is required")
    request = Request("http://supervisor/core/api/states" + ('' if independent_channels else '/' + entity),
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as response:
        if independent_channels:
            states = {s['entity_id']: s for s in json.load(response)}
            result = independent_display_state(entity, states)
            group = states.get(entity, {})
        else:
            group = json.load(response)
            result = light_display_state(group, color_controls=color_controls,
                                         separate_controls=separate_controls)
        if result is not None and separate_controls and ha_lights_menu:
            full_color = light_display_state(group, color_controls=True)
            if full_color is None:
                return None
            result['group'] = full_color
        return result


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
            # Rehydrate entry types before their state setters, preserving both
            # relay entries and the existing label indices.
            for entry in test_menu_packets(int(time.time()) & 255,
                                          color_controls=not isinstance(state, dict) and len(state) == 4,
                                          separate_controls=isinstance(state, dict),
                                          ha_lights_menu=isinstance(state, dict) and 'group' in state):
                for offset in range(0, len(entry), 20):
                    chunk = entry[offset:offset + 20]
                    if offset + len(chunk) == len(entry):
                        chunk += b"\xff" * ((-len(chunk)) % 4)
                    await client.write_gatt_char(DISPLAY_CHARACTERISTIC, chunk, response=True)
                    await asyncio.sleep(.05)
                await asyncio.sleep(.15)
            label_file = Path('/share/yeeport-display-labels.json')
            if isinstance(state, dict) and label_file.exists():
                bundle = json.loads(label_file.read_text())
                expected = [(2, 'RGB Lights'), (3, 'Warm White'), (4, 'Red 10%')]
                if 'group' in state:
                    expected.append((5, 'HA Lights'))
                if (bundle['address'].upper() != KNOB_ADDRESS or
                    [(x['index'], x['label']) for x in bundle['labels']] != expected):
                    raise ValueError('Invalid bounded display label bundle')
                for label in bundle['labels']:
                    packet = label_packet(base64.b64decode(label['png'], validate=True),
                                          image_type=2, index=label['index'],
                                          device_key=bytes.fromhex(bundle['device_key']))
                    for offset in range(0, len(packet), 20):
                        chunk = packet[offset:offset + 20]
                        if offset + len(chunk) == len(packet):
                            chunk += b'\xff' * ((-len(chunk)) % 4)
                        await client.write_gatt_char(DISPLAY_CHARACTERISTIC, chunk, response=True)
                        await asyncio.sleep(.05)
                    print(json.dumps({'display_label_uploaded': label['label']}), flush=True)
                label_file.unlink()
        if isinstance(state, dict):
            for slot, row in [(3, state['rgb']), (4, state['warm']), (5, (False, 0))]:
                if busy():
                    return False
                packet = light_state_packet(slot=slot, power=row[0], brightness=row[1],
                                            sequence=int(time.monotonic() * 10) & 0xffff)
                await client.write_gatt_char(DISPLAY_CHARACTERISTIC, packet, response=True)
                await asyncio.sleep(.1)
            if 'group' in state:
                if busy():
                    return False
                group = state['group']
                packet = color_light_state_packet(slot=6, power=group[0], brightness=group[1],
                          mode=group[2], value=group[3], sequence=int(time.monotonic() * 10) & 0xffff)
                await client.write_gatt_char(DISPLAY_CHARACTERISTIC, packet, response=True)
            return True
        args = dict(power=state[0], brightness=state[1], sequence=int(time.monotonic() * 10) & 0xffff)
        packet = (color_light_state_packet(**args, mode=state[2], value=state[3]) if len(state) == 4
                  else light_state_packet(**args))
        await client.write_gatt_char(DISPLAY_CHARACTERISTIC, packet, response=True)
        return True


async def run_light_sync(entity, stopped, *, lock, find_device, busy, suppress_activity,
                         color_controls=False, on_feedback=None, separate_controls=False,
                         on_warm_feedback=None, independent_channels=False, on_levels_feedback=None,
                         ha_lights_menu=False, on_group_feedback=None):
    last_state, last_sent = None, 0
    while not stopped.is_set():
        try:
            if not busy():
                state = await asyncio.to_thread(read_light_state, entity, color_controls, separate_controls,
                                                independent_channels and separate_controls, ha_lights_menu)
                if state is not None and (state != last_state or time.monotonic() - last_sent >= 30):
                    async with lock:
                        if not busy():
                            suppress_activity(110)
                            try:
                                device = await find_device(KNOB_ADDRESS)
                                sent = await asyncio.wait_for(send_light_state(
                                    device, state, busy, initialize_menu=last_state is None), 100 if separate_controls else 35)
                            finally:
                                suppress_activity(5)
                            if sent:
                                last_state, last_sent = state, time.monotonic()
                                if on_feedback and not busy():
                                    on_feedback(state['rgb'][1] if separate_controls else state[1])
                                    if separate_controls and on_warm_feedback:
                                        on_warm_feedback(state['warm'][1])
                                    if separate_controls and on_levels_feedback:
                                        on_levels_feedback(state)
                                    if separate_controls and 'group' in state and on_group_feedback:
                                        on_group_feedback(state['group'][1])
                                print(json.dumps({"light_display": "synchronized", "entity_id": entity,
                                                  "state": state}), flush=True)
        except Exception as exc:
            print(json.dumps({"light_display": "retry", "error": type(exc).__name__}), flush=True)
        try:
            await asyncio.wait_for(stopped.wait(), 5)
        except TimeoutError:
            pass
