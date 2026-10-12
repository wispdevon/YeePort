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
                            source_address=self.source, slot=3)
            except (ValueError, InvalidTag):
                continue
            if command is None or command.sequence <= self.highest:
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
            if command.kind == 'brightness':
                event['raw_percentage'] = command.value
                event['value'] = self.scaling.apply(command.value, self.last_command)
            event.update(event_type=command.kind if command.kind != "power" else
                         ("power_on" if command.value else "power_off"),
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
    request = Request("http://supervisor/core/api/services/light/" + service,
                      data=json.dumps(payload).encode(), method="POST",
                      headers={"Authorization": "Bearer " + token,
                               "Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:
        response.read()


class LightWorker:
    def __init__(self, entity, callback=call_light):
        self.entity, self.callback = entity, callback
        self.pending = {}
        self.busy = False
        self.wake = asyncio.Event()

    def submit(self, event):
        if event['kind'] == 'power' and event['value'] is False:
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
