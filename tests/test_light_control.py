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
from light_control import (BrightnessScaling, LightReceiver, LightWorker, service_payload,
                           pure_color_services, SeparateLightController, warm_white_services)
from knob_mesh_commands import decode_light_command, VENDOR_OPCODE
from light_sync import light_display_state, read_light_state
from display_config import test_menu_packets
from channel_control import blend_services, independent_display_state, selected_rgb, light_members


class LightServiceMapping(unittest.TestCase):
    def test_supergroup_commands_keep_separate_slots_and_are_opt_in(self):
        options = {'address': 'F8:24:41:39:9F:38', 'mesh_net_key': '00' * 16,
                   'mesh_app_key': '11' * 16, 'mesh_iv_index': 0,
                   'mesh_unicast_address': 5, 'separate_brightness_controls': True}
        payloads = [bytes.fromhex(v) for v in ['060100000032', '06030000000000ff',
                    '06020000000fa0', '0600000000000000']]
        with tempfile.TemporaryDirectory() as folder:
            for enabled in (False, True):
                options['ha_lights_menu_enabled'] = enabled
                receiver = LightReceiver(options, Path(folder) / str(enabled))
                events = []
                for sequence, payload in enumerate(payloads, 1):
                    message = SimpleNamespace(control=False, source=5, sequence=sequence,
                                              destination=65278)
                    with patch('light_control.fields', return_value=[(0x2a, b'packet')]), patch(
                            'light_control.decrypt_network', return_value=message), patch(
                            'knob_mesh_commands.decrypt_network', return_value=message), patch(
                            'knob_mesh_commands.decrypt_unsegmented_access', return_value=VENDOR_OPCODE + payload):
                        events.extend(receiver.receive(options['address'], -60, b''))
                self.assertEqual([(e['kind'], e['value'], e['slot']) for e in events],
                    [('brightness', 50, 6), ('color', (0, 0, 255), 6),
                     ('color_temperature', 4000, 6), ('power', False, 6)] if enabled else [])

    def test_supergroup_targets_all_lights_and_reloads_channel_levels(self):
        states = [{'entity_id': 'light.group', 'state': 'on', 'attributes':
                   {'entity_id': ['light.bulb'], 'brightness': 38, 'color_mode': 'rgbww',
                    'rgb_color': [255, 0, 0]}},
                  {'entity_id': 'light.bulb', 'state': 'on', 'attributes':
                   {'supported_color_modes': ['rgbww', 'color_temp'], 'brightness': 38,
                    'color_mode': 'rgbww', 'rgbww_color': [170, 0, 0, 0, 255]}}]
        calls = []
        def request(path, payload=None):
            if path == 'states':
                return states
            calls.append((path, payload))
        controller = SeparateLightController({'independent_channels': True}, request)
        controller.sync_feedback({'rgb': (True, 10), 'warm': (True, 15)})
        controller('light.group', {'kind': 'brightness', 'value': 50, 'slot': 6})
        self.assertEqual(calls.pop(), ('services/light/turn_on',
                                      {'entity_id': 'light.group', 'brightness_pct': 50}))
        controller('light.group', {'kind': 'color', 'value': [0, 0, 255], 'slot': 6})
        self.assertEqual(calls.pop(), ('services/light/turn_on',
                  {'entity_id': 'light.bulb', 'rgbww_color': [0, 0, 255, 0, 0]}))
        states[1]['attributes'].update(brightness=128, rgbww_color=[0, 0, 255, 0, 0])
        controller('light.group', {'kind': 'warm_brightness', 'value': 15, 'slot': 4})
        self.assertEqual(controller.rgb_level, 50)
        self.assertEqual(calls.pop(), ('services/light/turn_on',
                  {'entity_id': 'light.bulb', 'brightness': 128,
                   'rgbww_color': [0, 0, 255, 0, 76]}))
        controller('light.group', {'kind': 'color_temperature', 'value': 4000, 'slot': 6})
        self.assertEqual(calls.pop(), ('services/light/turn_on',
                       {'entity_id': 'light.group', 'color_temp_kelvin': 4000}))
        controller('light.group', {'kind': 'power', 'value': False, 'slot': 6})
        self.assertEqual(calls.pop(), ('services/light/turn_off', {'entity_id': 'light.group'}))

    def test_supergroup_display_preserves_menu_slots_and_full_color_state(self):
        import io
        states = [{'entity_id': 'light.group', 'state': 'on', 'attributes':
                   {'entity_id': ['light.bulb'], 'brightness': 38, 'color_mode': 'color_temp',
                    'color_temp_kelvin': 4000}},
                  {'entity_id': 'light.bulb', 'state': 'on', 'attributes':
                   {'supported_color_modes': ['rgbww', 'color_temp'], 'brightness': 38,
                    'color_mode': 'color_temp', 'color_temp_kelvin': 4000}}]
        with patch.dict('os.environ', {'SUPERVISOR_TOKEN': 'test'}), patch(
                'light_sync.urlopen', return_value=io.BytesIO(json.dumps(states).encode())):
            display = read_light_state('light.group', separate_controls=True,
                                       independent_channels=True, ha_lights_menu=True)
        self.assertEqual(display, {'rgb': (False, 0), 'warm': (True, 15),
                                  'group': (True, 15, 2, 4000)})
        menu = test_menu_packets(1, separate_controls=True, ha_lights_menu=True)
        self.assertEqual([(p[11 + 4], p[11 + 7]) for p in menu],
                         [(1, 24), (2, 24), (3, 2), (4, 2), (5, 1), (6, 4)])
        self.assertIn(b'HA Lights', menu[-1])

    def test_separate_menu_routes_warm_and_every_preset_press(self):
        options = {'address': 'F8:24:41:39:9F:38', 'mesh_net_key': '00' * 16,
                   'mesh_app_key': '11' * 16, 'mesh_iv_index': 0,
                   'mesh_unicast_address': 5, 'separate_brightness_controls': True}
        payloads = [bytes.fromhex(value) for value in [
            '04010000000f', '0500000000010000', '0500000000000000',
            '0403000000ff0000', '05010000000f']]
        with tempfile.TemporaryDirectory() as folder:
            receiver = LightReceiver(options, Path(folder) / 'sequence.json')
            events = []
            for sequence, payload in enumerate(payloads, 1):
                message = SimpleNamespace(control=False, source=5, sequence=sequence,
                                          destination=65278)
                with patch('light_control.fields', return_value=[(0x2a, b'packet')]), patch(
                        'light_control.decrypt_network', return_value=message), patch(
                        'knob_mesh_commands.decrypt_network', return_value=message), patch(
                        'knob_mesh_commands.decrypt_unsegmented_access', return_value=VENDOR_OPCODE + payload):
                    events.extend(receiver.receive(options['address'], -60, b''))
            self.assertEqual([(e['kind'], e['value']) for e in events],
                             [('warm_brightness', 15), ('scene', 'usual_red_10'),
                              ('scene', 'usual_red_10')])
            self.assertEqual(receiver.highest, 3)

    def test_independent_blend_preserves_levels_and_feedback(self):
        states = {'light.group': {'entity_id': 'light.group', 'state': 'on', 'attributes':
                  {'entity_id': ['light.bulb', 'light.strip', 'light.bar']}},
                  'light.bulb': {'entity_id': 'light.bulb', 'state': 'on', 'attributes':
                  {'supported_color_modes': ['rgbww', 'color_temp'], 'color_mode': 'rgbww',
                   'rgbww_color': [170, 0, 0, 0, 255], 'brightness': 38}},
                  'light.strip': {'entity_id': 'light.strip', 'state': 'on', 'attributes':
                  {'supported_color_modes': ['rgbw', 'color_temp'], 'color_mode': 'rgbw',
                   'rgbw_color': [170, 0, 0, 255], 'brightness': 38}},
                  'light.bar': {'entity_id': 'light.bar', 'state': 'on', 'attributes':
                  {'supported_color_modes': ['rgb', 'color_temp'], 'color_mode': 'rgb',
                   'rgb_color': [255, 0, 0], 'brightness': 26}}}
        self.assertEqual(independent_display_state('light.group', states),
                         {'rgb': (True, 10), 'warm': (True, 15)})
        self.assertEqual(selected_rgb(light_members('light.group', states), [0, 0, 255]), [255, 0, 0])
        calls = blend_services('light.group', states, [255, 0, 0], 10, 15)
        self.assertEqual(calls[0], ('turn_on', {'entity_id': 'light.bulb', 'brightness': 38,
                                             'rgbww_color': [170, 0, 0, 0, 255]}))
        self.assertEqual(calls[1][1]['rgbw_color'], [170, 0, 0, 255])
        self.assertEqual(calls[2][1]['brightness_pct'], 10)
        calls = blend_services('light.group', states, [255, 0, 0], 0, 15)
        self.assertEqual(calls[0][1]['rgbww_color'], [0, 0, 0, 0, 255])
        self.assertEqual(calls[2][1]['color_temp_kelvin'], 2700)
        self.assertTrue(all(service == 'turn_off' for service, _ in
                            blend_services('light.group', states, [255, 0, 0], 0, 0)))
        with self.assertRaises(ValueError):
            blend_services('light.group', states, [255, 0, 0], 10, 101)

    def test_separate_controls_switch_modes_and_scene_restores_red(self):
        states = [
            {'entity_id': 'light.group', 'state': 'on', 'attributes':
                {'entity_id': ['light.rgbww', 'light.rgbw', 'light.rgb'],
                 'color_mode': 'rgbww', 'rgb_color': [0, 0, 255]}},
            *[{'entity_id': 'light.' + mode, 'state': 'on', 'attributes':
                {'supported_color_modes': [mode, 'color_temp'], 'min_color_temp_kelvin': 2700,
                 'max_color_temp_kelvin': 6500}} for mode in ['rgbww', 'rgbw', 'rgb']]]
        calls = []
        def request(path, payload=None):
            if path == 'states':
                return states
            calls.append((path, payload))
            return []
        controller = SeparateLightController({}, request)
        controller('light.group', {'kind': 'warm_brightness', 'value': 15})
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(data['brightness_pct'] == 15 and data['color_temp_kelvin'] == 2700
                            for _, data in calls))
        states[0]['attributes'].update(color_mode='color_temp', rgb_color=[255, 200, 100])
        calls.clear()
        controller('light.group', {'kind': 'brightness', 'value': 20})
        self.assertEqual(calls[0], ('services/light/turn_on',
            {'entity_id': 'light.rgbww', 'rgbww_color': [0, 0, 255, 0, 0], 'brightness_pct': 20}))
        self.assertTrue(all(data['brightness_pct'] == 20 for _, data in calls))
        calls.clear()
        controller('light.group', {'kind': 'scene', 'value': 'usual_red_10'})
        self.assertEqual(calls, [('services/scene/turn_on', {'entity_id': 'scene.usual_red_10'})])
        self.assertEqual(controller.rgb, [255, 0, 0])
        with self.assertRaises(ValueError):
            controller('light.group', {'kind': 'warm_brightness', 'value': 101})

    def test_display_reports_separate_mode_brightness(self):
        state = {'state': 'on', 'attributes': {'brightness': 26, 'color_mode': 'rgbww'}}
        self.assertEqual(light_display_state(state, separate_controls=True),
                         {'rgb': (True, 10), 'warm': (False, 0)})
        state['attributes']['color_mode'] = 'color_temp'
        self.assertEqual(light_display_state(state, separate_controls=True),
                         {'rgb': (False, 0), 'warm': (True, 10)})

    def test_mixed_group_color_disables_all_white_channels(self):
        def state(modes, **extra):
            return {'state': 'on', 'attributes': {'supported_color_modes': modes, **extra}}
        states = {'light.group': state(['rgbww'], entity_id=['light.warm', 'light.strip', 'light.rgb',
                         'light.offline', 'light.white', 'light.nested']),
                  'light.nested': state(['rgbww'], entity_id=['light.warm', 'light.group']),
                  'light.warm': state(['color_temp', 'rgbww'], rgbww_color=[10, 20, 30, 61, 61]),
                  'light.strip': state(['rgbw'], rgbw_color=[10, 20, 30, 38]),
                  'light.rgb': state(['rgb']), 'light.white': state(['color_temp']),
                  'light.offline': {'state': 'unavailable', 'attributes': {'supported_color_modes': ['rgb']}}}
        calls = pure_color_services('light.group', {'kind': 'color', 'value': [255, 36, 33]}, states)
        self.assertEqual(calls, [('turn_on', {'entity_id': 'light.warm', 'rgbww_color': [255, 36, 33, 0, 0]}),
                                ('turn_on', {'entity_id': 'light.strip', 'rgbw_color': [255, 36, 33, 0]}),
                                ('turn_on', {'entity_id': 'light.rgb', 'rgb_color': [255, 36, 33]})])
        self.assertEqual(pure_color_services('light.group', {'kind': 'color_temperature', 'value': 4000}, states),
                         [('turn_on', {'entity_id': 'light.group', 'color_temp_kelvin': 4000})])

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
    async def test_supergroup_off_cancels_pending_channel_changes(self):
        worker = LightWorker('light.group', SimpleNamespace(independent=True))
        worker.submit({'kind': 'warm_brightness', 'value': 30, 'slot': 4})
        worker.submit({'kind': 'brightness', 'value': 10, 'slot': 3})
        worker.submit({'kind': 'power', 'value': False, 'slot': 6})
        self.assertEqual(list(worker.pending.values()),
                         [{'kind': 'power', 'value': False, 'slot': 6}])

    async def test_warm_off_preserves_pending_rgb_in_independent_mode(self):
        calls, complete = [], asyncio.Event()
        loop = asyncio.get_running_loop()
        def callback(entity, event):
            calls.append((event['kind'], event['value']))
            if len(calls) == 2:
                loop.call_soon_threadsafe(complete.set)
        callback.independent = True
        worker = LightWorker('light.knob_lights', callback)
        task = asyncio.create_task(worker.run())
        try:
            worker.submit({'kind': 'warm_brightness', 'value': 30})
            worker.submit({'kind': 'brightness', 'value': 10})
            worker.submit({'kind': 'warm_power', 'value': False})
            await asyncio.wait_for(complete.wait(), 1)
            self.assertEqual(calls, [('brightness', 10), ('warm_power', False)])
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

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
