"""Verified slot-3 Mesh commands to MQTT and local Home Assistant lights."""
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidTag
from knob_mesh_commands import decode_light_command
from mesh import fields
from mesh_crypto import decrypt_network
from channel_control import (blend_services, independent_display_state, light_members, selected_rgb)


class BrightnessScaling:
    """Scale authenticated percentage deltas, with a bounded linear speed gain.

    This changes HA brightness, not the encoder's physical detents or firmware
    ring movement. Idle display feedback rebases both percentages afterwards.
    """
    def __init__(self, enabled=False, maximum_gain=4):
        if type(enabled) is not bool or type(maximum_gain) is not int or not 1 <= maximum_gain <= 8:
            raise ValueError('Invalid brightness speed scaling')
        self.enabled, self.maximum_gain = enabled, maximum_gain
        self.raw = self.output = self.when = None

    def rebase(self, percentage):
        self.raw = self.output = percentage
        self.when = None

    def apply(self, raw, now):
        if not self.enabled or self.raw is None:
            result = raw
        elif raw in (0, 100):
            result = raw
        else:
            delta = raw - self.raw
            elapsed = now - self.when if self.when is not None else 1
            speed = abs(delta) / max(elapsed, .02)
            ramp = min(1, max(0, (speed - 2) / 10)) if 0 < elapsed <= .6 else 0
            gain = 1 + ramp * (self.maximum_gain - 1)
            result = min(100, max(0, self.output + delta * gain))
        self.raw, self.output, self.when = raw, result, now
        return round(result)


class LightReceiver:
    def __init__(self, options, watermark_path=Path("/data/mesh-sequence.json")):
        self.address = options["address"].upper()
        self.net_key = bytes.fromhex(options["mesh_net_key"])
        self.app_key = bytes.fromhex(options["mesh_app_key"])
        self.iv_index = int(options["mesh_iv_index"])
        self.source = int(options["mesh_unicast_address"])
        self.destination = int(options.get("mesh_destination", 65278))
        if (self.address != "F8:24:41:39:9F:38" or len(self.net_key) != 16 or len(self.app_key) != 16
                or not 0 <= self.iv_index <= 0xffffffff or not 1 <= self.source <= 0x7fff):
            raise ValueError("Invalid verified Mesh key configuration")
        self.path = Path(watermark_path)
        self.fingerprint = hashlib.sha256(self.net_key + self.app_key +
                    self.iv_index.to_bytes(4, "big") + self.source.to_bytes(2, "big") +
                    self.destination.to_bytes(2, "big")).hexdigest()
        self.highest = -1
        self.last_command = 0
        self.scaling = BrightnessScaling(options.get('brightness_speed_scaling', False),
                                         options.get('brightness_maximum_gain', 4))
        self.separate = options.get('separate_brightness_controls', False)
        self.supergroup = self.separate and options.get('ha_lights_menu_enabled', False)
        self.group_scaling = BrightnessScaling(options.get('brightness_speed_scaling', False),
                                               options.get('brightness_maximum_gain', 4))
        self.warm_scaling = BrightnessScaling(options.get('brightness_speed_scaling', False),
                                              options.get('brightness_maximum_gain', 4))
        try:
            saved = json.loads(self.path.read_text())
            if saved["fingerprint"] == self.fingerprint:
                self.highest = int(saved["sequence"])
                if not -1 <= self.highest <= 0xffffff:
                    raise ValueError("Invalid saved sequence")
        except FileNotFoundError:
            pass

    def receive(self, peer, rssi, data):
        if peer.upper() != self.address:
            return
        for kind, packet in fields(data):
            if kind != 0x2a:
                continue
            try:
                command = decode_light_command(packet, net_key=self.net_key,
                            app_key=self.app_key, device_key=None, iv_index=self.iv_index,
                            source_address=self.source,
                            slot=(3, 4, 5, 6) if self.supergroup else ((3, 4, 5) if self.separate else 3))
            except (ValueError, InvalidTag):
                continue
            if command is None or command.sequence <= self.highest:
                continue
            if command.slot == 4 and command.kind not in ('brightness', 'power'):
                continue
            if command.slot == 5 and command.kind != 'power':
                continue
            # Destination is authenticated inside the network PDU; confirm the
            # exact observed publication address before acting on this slot.
            message = decrypt_network(packet, self.net_key, self.iv_index)
            if message.destination != self.destination:
                continue
            self.highest = command.sequence
            self.last_command = time.monotonic()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"fingerprint": self.fingerprint, "sequence": self.highest}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            event = asdict(command)
            if command.slot == 5:
                event.update(kind='scene', value='usual_red_10')
                self.scaling.rebase(10)
                self.warm_scaling.rebase(0)
                self.group_scaling.rebase(10)
            elif command.slot == 4:
                event['kind'] = 'warm_brightness' if command.kind == 'brightness' else 'warm_power'
            if command.kind == 'brightness':
                event['raw_percentage'] = command.value
                scaling = (self.group_scaling if command.slot == 6 else
                           self.warm_scaling if command.slot == 4 else self.scaling)
                event['value'] = scaling.apply(command.value, self.last_command)
            event.update(event_type=event['kind'] if event['kind'] not in ('power', 'warm_power') else
                         (('warm_' if command.slot == 4 else '') + ('power_on' if command.value else 'power_off')),
                         address=self.address, rssi=rssi, authenticated=True,
                         timestamp=datetime.now(timezone.utc).isoformat())
            yield event


def service_payload(entity, event):
    if not re.fullmatch(r"light\.[a-z0-9_]+", entity):
        raise ValueError("A specific light or light group entity is required")
    value = event["value"]
    if event["kind"] == "brightness":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError("Invalid brightness percentage")
        return ("turn_off", {"entity_id": entity}) if value == 0 else (
            "turn_on", {"entity_id": entity, "brightness_pct": value})
    if event["kind"] == "power" and isinstance(value, bool):
        return ("turn_on" if value else "turn_off"), {"entity_id": entity}
    if event["kind"] == "color_temperature" and type(value) is int and 1000 <= value <= 20000:
        return "turn_on", {"entity_id": entity, "color_temp_kelvin": value}
    if event["kind"] == "color" and isinstance(value, (list, tuple)) and len(value) == 3 and all(
            type(v) is int and 0 <= v <= 255 for v in value):
        return "turn_on", {"entity_id": entity, "rgb_color": list(value)}
    raise ValueError("Unsupported light command")


def call_light(entity, event):
    service, payload = service_payload(entity, event)
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("Home Assistant app API access is required")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    calls = [(service, payload)]
    if event['kind'] == 'color':
        request = Request('http://supervisor/core/api/states', headers=headers)
        with urlopen(request, timeout=10) as response:
            states = {state['entity_id']: state for state in json.load(response)}
        calls = pure_color_services(entity, event, states)
    for service, payload in calls:
        request = Request("http://supervisor/core/api/services/light/" + service,
                          data=json.dumps(payload).encode(), method="POST", headers=headers)
        with urlopen(request, timeout=10) as response:
            response.read()


def pure_color_services(entity, event, states):
    """Target leaf lights in their native color mode, with every white LED off.

    Sending RGB to a mixed HA light group can convert it to RGBWW then RGBW,
    introducing white channels. Avoid those conversions with per-light fields.
    Brightness is intentionally omitted so each lamp retains its brightness.
    """
    service, payload = service_payload(entity, event)
    if event['kind'] != 'color':
        return [(service, payload)]
    rgb, visited, calls = payload['rgb_color'], set(), []

    def visit(target):
        if not re.fullmatch(r'light\.[a-z0-9_]+', target):
            raise ValueError('Invalid light group member')
        if target in visited:
            return
        visited.add(target)
        if len(visited) > 128:
            raise ValueError('Light group is too large')
        state = states.get(target)
        if state is None or state.get('state') in ('unavailable', 'unknown'):
            return
        attributes = state.get('attributes', {})
        members = attributes.get('entity_id')
        if isinstance(members, list):
            for member in members:
                visit(member)
            return
        modes = attributes.get('supported_color_modes', [])
        data = {'entity_id': target}
        if 'rgbww' in modes:
            data['rgbww_color'] = rgb + [0, 0]
        elif 'rgbw' in modes:
            data['rgbw_color'] = rgb + [0]
        elif any(mode in modes for mode in ('rgb', 'hs', 'xy')):
            data['rgb_color'] = rgb.copy()
        else:
            return
        calls.append(('turn_on', data))

    visit(entity)
    if not calls:
        raise ValueError('No available color lights in the configured target')
    return calls


def ha_request(path, payload=None):
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        raise RuntimeError('Home Assistant app API access is required')
    request = Request('http://supervisor/core/api/' + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def warm_white_services(entity, value, states, kelvin=2700):
    # Reuse strict percentage/target validation before constructing any call.
    service_payload(entity, {'kind': 'brightness', 'value': value})
    if value == 0:
        return [('turn_off', {'entity_id': entity})]
    # The color planner resolves nested groups and deduplicates available lights.
    leaves = pure_color_services(entity, {'kind': 'color', 'value': [255, 0, 0]}, states)
    calls = []
    for _, data in leaves:
        target = data['entity_id']
        attributes = states[target].get('attributes', {})
        if 'color_temp' not in attributes.get('supported_color_modes', []):
            continue
        temperature = min(attributes.get('max_color_temp_kelvin', 6500),
                          max(attributes.get('min_color_temp_kelvin', 2000), kelvin))
        calls.append(('turn_on', {'entity_id': target, 'brightness_pct': value,
                                 'color_temp_kelvin': temperature}))
    if not calls:
        raise ValueError('No available warm-white lights in the target')
    return calls


class SeparateLightController:
    """Distinct RGB and warm-white mode/brightness commands plus a fixed scene."""
    def __init__(self, options, request=ha_request):
        self.request = request
        self.kelvin = options.get('warm_white_kelvin', 2700)
        self.scene = options.get('preset_scene', 'scene.usual_red_10')
        if not re.fullmatch(r'scene\.[a-z0-9_]+', self.scene):
            raise ValueError('Invalid preset scene')
        self.rgb = [255, 0, 0]
        self.rgb_level = self.warm_level = 10
        self.independent = options.get('independent_channels', False)
        self.initialized = False

    def sync_feedback(self, state):
        if self.independent and state:
            self.rgb_level, self.warm_level = state['rgb'][1], state['warm'][1]
            self.initialized = True

    def __call__(self, entity, event):
        kind, value = event['kind'], event['value']
        if kind == 'scene':
            if value != 'usual_red_10':
                raise ValueError('Unsupported preset')
            self.request('services/scene/turn_on', {'entity_id': self.scene})
            self.rgb, self.rgb_level, self.warm_level = [255, 0, 0], 10, 0
            self.initialized = True
            return
        states = {state['entity_id']: state for state in self.request('states')}
        if event.get('slot') == 6:
            for service, data in pure_color_services(entity, event, states):
                self.request('services/light/' + service, data)
            # The whole-group action can change both channels. Read their new
            # levels before the next independent-channel action.
            self.initialized = False
            return
        if self.independent:
            if not self.initialized:
                self.sync_feedback(independent_display_state(entity, states))
            self.rgb = selected_rgb(light_members(entity, states), self.rgb)
            if kind in ('brightness', 'warm_brightness', 'power', 'warm_power'):
                warm = kind.startswith('warm_')
                if kind in ('power', 'warm_power'):
                    if type(value) is not bool:
                        raise ValueError('Invalid channel power')
                    value = ((self.warm_level if warm else self.rgb_level) or 10) if value else 0
                if type(value) is not int or not 0 <= value <= 100:
                    raise ValueError('Invalid channel brightness')
                if warm:
                    self.warm_level = value
                else:
                    self.rgb_level = value
                for service, data in blend_services(entity, states, self.rgb, self.rgb_level,
                                                     self.warm_level, self.kelvin):
                    self.request('services/light/' + service, data)
                return
        group = states.get(entity, {})
        attributes = group.get('attributes', {})
        if attributes.get('color_mode') in ('rgb', 'rgbw', 'rgbww'):
            rgb = attributes.get('rgb_color')
            if isinstance(rgb, (tuple, list)) and len(rgb) == 3:
                self.rgb = list(rgb)
        if kind in ('warm_brightness', 'warm_power'):
            if kind == 'warm_power':
                if type(value) is not bool:
                    raise ValueError('Invalid warm power command')
                value = (self.warm_level or 10) if value else 0
            calls = warm_white_services(entity, value, states, self.kelvin)
            self.warm_level = value
        elif kind in ('brightness', 'power'):
            if kind == 'power':
                if type(value) is not bool:
                    raise ValueError('Invalid RGB power command')
                value = (self.rgb_level or 10) if value else 0
            service_payload(entity, {'kind': 'brightness', 'value': value})
            if value == 0:
                calls = [('turn_off', {'entity_id': entity})]
            else:
                calls = pure_color_services(entity, {'kind': 'color', 'value': self.rgb}, states)
                for _, data in calls:
                    data['brightness_pct'] = value
            self.rgb_level = value
        else:
            call_light(entity, event)
            return
        for service, data in calls:
            self.request('services/light/' + service, data)


class LightWorker:
    def __init__(self, entity, callback=call_light):
        self.entity, self.callback = entity, callback
        self.pending = {}
        self.busy = False
        self.wake = asyncio.Event()

    def submit(self, event):
        if event['kind'] == 'scene' or (event.get('slot') == 6 and
                                      event['kind'] == 'power' and event['value'] is False):
            self.pending.clear()
        elif event['kind'] in ('power', 'warm_power') and event['value'] is False:
            if getattr(self.callback, 'independent', False):
                family = ('warm_brightness', 'warm_power') if event['kind'] == 'warm_power' else ('brightness', 'power')
                for kind in family:
                    self.pending.pop(kind, None)
            else:
                self.pending.clear()
        self.pending.pop(event['kind'], None)
        self.pending[event['kind']] = event
        self.wake.set()

    async def run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            await asyncio.sleep(.1)
            events, self.pending = list(self.pending.values()), {}
            self.busy = True
            try:
                for event in events:
                    try:
                        await asyncio.to_thread(self.callback, self.entity, event)
                        print(json.dumps({"light_control": "applied", "entity_id": self.entity,
                                          "kind": event["kind"], "value": event["value"]}), flush=True)
                    except Exception as exc:
                        print(json.dumps({"light_control": "failed", "entity_id": self.entity,
                                          "error": type(exc).__name__}), flush=True)
            finally:
                self.busy = False
