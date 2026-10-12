"""Service semantics, command coalescing and real-capture replay rejection."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knob_bridge"))
from light_control import BrightnessScaling, LightReceiver, LightWorker, service_payload
from knob_mesh_commands import decode_light_command, VENDOR_OPCODE
from light_sync import light_display_state


class LightServiceMapping(unittest.TestCase):
    def test_speed_scaling_fine_fast_endpoints_and_feedback(self):
        scaler = BrightnessScaling(True, 4)
        scaler.rebase(50)
        self.assertEqual(scaler.apply(51, 10), 51)
        self.assertEqual(scaler.apply(52, 11), 52)
        self.assertEqual(scaler.apply(53, 11.05), 56)
        self.assertEqual(scaler.apply(52, 11.1), 52)
        self.assertEqual(scaler.apply(100, 11.15), 100)
        self.assertEqual(scaler.apply(0, 11.2), 0)
        scaler.rebase(30)
        self.assertEqual(scaler.apply(31, 12), 31)
        normal = BrightnessScaling(False)
        self.assertEqual(normal.apply(30, 1), 30)
        self.assertEqual(normal.apply(31, 1.01), 31)

    def test_color_temperature_and_rgb_preserve_brightness(self):
        entity = 'light.knob_lights'
        self.assertEqual(service_payload(entity, {'kind': 'color', 'value': (255, 0, 30)}),
                         ('turn_on', {'entity_id': entity, 'rgb_color': [255, 0, 30]}))
        self.assertEqual(service_payload(entity, {'kind': 'color_temperature', 'value': 4000}),
                         ('turn_on', {'entity_id': entity, 'color_temp_kelvin': 4000}))
        for event in [{'kind': 'color', 'value': [True, 0, 0]},
                      {'kind': 'color_temperature', 'value': 0},
                      {'kind': 'color', 'value': [256, 0, 0]}]:
            with self.assertRaises(ValueError):
                service_payload(entity, event)

    def test_firmware_color_selectors_and_big_endian_kelvin(self):
        network = SimpleNamespace(control=False, source=1, sequence=20)
        samples = [(bytes.fromhex('03020000000fa0'), 'color_temperature', 4000),
                   (bytes.fromhex('0303000000ff001e'), 'color', (255, 0, 30)),
                   (bytes.fromhex('03020000000000'), None, None),
                   (bytes.fromhex('0303000000ff00'), None, None)]
        for payload, kind, value in samples:
            with patch('knob_mesh_commands.decrypt_network', return_value=network), patch(
                    'knob_mesh_commands.decrypt_unsegmented_access', return_value=VENDOR_OPCODE + payload):
                command = decode_light_command(b'', net_key=b'', app_key=b'', device_key=None,
                                               iv_index=0, source_address=1)
                self.assertEqual(command.kind if command else None, kind)
                if command:
                    self.assertEqual(command.value, value)

    def test_display_retains_active_color_mode(self):
        state = {'state': 'on', 'attributes': {'brightness': 51, 'color_mode': 'color_temp',
                 'color_temp_kelvin': 4000, 'rgb_color': [255, 200, 150]}}
        self.assertEqual(light_display_state(state, color_controls=True), (True, 20, 2, 4000))
        state['attributes']['color_mode'] = 'rgb'
        self.assertEqual(light_display_state(state, color_controls=True), (True, 20, 1, (255, 200, 150)))

    def test_brightness_and_power_target_only_the_group(self):
        entity = "light.knob_lights"
        self.assertEqual(service_payload(entity, {"kind": "brightness", "value": 0}),
                         ("turn_off", {"entity_id": entity}))
        self.assertEqual(service_payload(entity, {"kind": "brightness", "value": 100}),
                         ("turn_on", {"entity_id": entity, "brightness_pct": 100}))
        self.assertEqual(service_payload(entity, {"kind": "power", "value": False}),
                         ("turn_off", {"entity_id": entity}))
        for event in [{"kind": "brightness", "value": True},
                      {"kind": "brightness", "value": 101},
                      {"kind": "power", "value": 1}]:
            with self.assertRaises(ValueError):
                service_payload(entity, event)

    def test_capture_is_not_reapplied_after_restart(self):
        private = Path("/home/wisp/.local/state/yeegate/knob-mesh-keys.json")
        capture = Path(__file__).resolve().parents[1] / "knob-brightness-ring-capture.jsonl"
        if not private.exists() or not capture.exists():
            self.skipTest("External owner keys and real capture required")
        keys = json.loads(private.read_text())
        options = {"address": keys["address"], "mesh_net_key": keys["net_key"],
                   "mesh_app_key": keys["app_key"], "mesh_iv_index": keys["iv_index"],
                   "mesh_unicast_address": keys["unicast_address"], "mesh_destination": 65278}
        records = []
        for line in capture.read_text().splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        with tempfile.TemporaryDirectory() as folder:
            watermark = Path(folder) / "sequence.json"
            receiver = LightReceiver(options, watermark)
            events = []
            for record in records:
                events.extend(receiver.receive(record["address"], record["rssi"], bytes.fromhex(record["data"])))
            self.assertEqual(len(events), 57)
            self.assertEqual(sum(e["kind"] == "brightness" for e in events), 55)
            receiver = LightReceiver(options, watermark)
            for record in records:
                self.assertEqual(list(receiver.receive(record["address"], record["rssi"],
                                                       bytes.fromhex(record["data"]))), [])


class LightCommandCoalescing(unittest.IsolatedAsyncioTestCase):
    async def test_color_survives_brightness_in_the_same_burst(self):
        calls, complete = [], asyncio.Event()
        loop = asyncio.get_running_loop()
        def callback(entity, event):
            calls.append(service_payload(entity, event))
            if len(calls) == 2:
                loop.call_soon_threadsafe(complete.set)
        worker = LightWorker('light.knob_lights', callback)
        task = asyncio.create_task(worker.run())
        try:
            worker.submit({'kind': 'color', 'value': (255, 0, 0)})
            worker.submit({'kind': 'brightness', 'value': 20})
            worker.submit({'kind': 'brightness', 'value': 21})
            await asyncio.wait_for(complete.wait(), 1)
            self.assertEqual(calls, [('turn_on', {'entity_id': 'light.knob_lights', 'rgb_color': [255, 0, 0]}),
                                     ('turn_on', {'entity_id': 'light.knob_lights', 'brightness_pct': 21})])
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_last_power_off_wins_a_rotation_burst(self):
        calls, complete = [], asyncio.Event()
        loop = asyncio.get_running_loop()
        def callback(entity, event):
            calls.append(service_payload(entity, event))
            loop.call_soon_threadsafe(complete.set)
        worker = LightWorker("light.knob_lights", callback)
        task = asyncio.create_task(worker.run())
        try:
            worker.submit({"kind": "brightness", "value": 40})
            worker.submit({"kind": "brightness", "value": 41})
            worker.submit({"kind": "power", "value": False})
            await asyncio.wait_for(complete.wait(), 1)
            self.assertEqual(calls, [("turn_off", {"entity_id": "light.knob_lights"})])
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    unittest.main()
