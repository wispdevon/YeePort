"""User-selected menu targets, capacity, local labels and import isolation."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'knob_bridge'))
from light_imports import imported_menu, prepare_import, render_label
from PIL import Image
from light_control import LightReceiver, LightWorker, SeparateLightController
from knob_mesh_commands import VENDOR_OPCODE
from display_config import test_menu_packets
from light_sync import read_light_state


class ImportedMenu(unittest.TestCase):
    def setUp(self):
        self.options = {'separate_brightness_controls': True, 'ha_lights_menu_enabled': True}
        self.states = {'light.bulb': {'entity_id': 'light.bulb', 'state': 'on', 'attributes':
                       {'supported_color_modes': ['rgbww', 'color_temp']}},
                       'light.lamp': {'entity_id': 'light.lamp', 'state': 'off', 'attributes':
                       {'supported_color_modes': ['brightness']}},
                       'light.switch': {'entity_id': 'light.switch', 'state': 'off', 'attributes':
                       {'supported_color_modes': ['onoff']}}}

    def test_import_keeps_existing_slots_and_derives_supported_controls(self):
        records = prepare_import(self.options, [{'entity_id': 'light.bulb', 'name': 'Wiz Bulb'},
                          {'entity_id': 'light.lamp', 'name': 'Desk Lamp'}], self.states)
        self.options['imported_lights'] = records
        menu = imported_menu(self.options)
        self.assertEqual([(x['slot'], x['entity_id'], x['controls']) for x in menu],
                         [(7, 'light.bulb', 'color'), (8, 'light.lamp', 'brightness')])
        self.options.update(separate_brightness_controls=False,
                            imported_lights=prepare_import({'separate_brightness_controls': False},
                               [{'entity_id': 'light.switch', 'name': 'Switch'}], self.states))
        self.assertEqual(imported_menu(self.options)[0]['slot'], 4)
        self.assertEqual(imported_menu(self.options)[0]['controls'], 'switch')

    def test_rejects_overflow_duplicates_unknown_entities_and_non_english_names(self):
        item = {'entity_id': 'light.bulb', 'name': 'Wiz Bulb'}
        invalid = [[item] * 3, [item, item], [{'entity_id': 'sensor.temp', 'name': 'Temp'}],
                   [{'entity_id': 'light.unknown', 'name': 'Unknown'}],
                   [{'entity_id': 'light.bulb', 'name': '灯'}],
                   [{'entity_id': 'light.bulb', 'name': ' ' * 4}],
                   [{'entity_id': 'light.bulb', 'name': 'x' * 25}]]
        for records in invalid:
            with self.subTest(records=records), self.assertRaises(ValueError):
                prepare_import(self.options, records, self.states)

    def test_local_label_matches_verified_png_shape_and_fits_long_names(self):
        for name in ('Wiz Bulb', 'ABCDEFGHIJKLMNOPQRSTUVWX'):
            png = render_label(name)
            image = Image.open(io.BytesIO(png))
            self.assertEqual((image.size, image.mode), ((240, 48), 'RGBA'))
            self.assertIsNotNone(image.getbbox())
            self.assertLessEqual(len(png), 60000)

    def test_authenticated_imports_wait_for_menu_sync_and_route_to_their_entity(self):
        options = dict(self.options, address='F8:24:41:39:9F:38', mesh_net_key='00' * 16,
                       mesh_app_key='11' * 16, mesh_iv_index=0, mesh_unicast_address=5,
                       imported_lights=prepare_import(self.options,
                           [{'entity_id': 'light.bulb', 'name': 'Bulb'}], self.states))
        for separate, slot in [(True, 7), (False, 4)]:
            options['separate_brightness_controls'] = separate
            with tempfile.TemporaryDirectory() as folder:
                receiver = LightReceiver(options, Path(folder) / 'sequence.json')
                message = SimpleNamespace(control=False, source=5, sequence=1, destination=65278)
                plain = VENDOR_OPCODE + bytes((slot, 3, 0, 0, 0, 0, 0, 255))
                with patch('light_control.fields', return_value=[(0x2a, b'packet')]), patch(
                        'light_control.decrypt_network', return_value=message), patch(
                        'knob_mesh_commands.decrypt_network', return_value=message), patch(
                        'knob_mesh_commands.decrypt_unsegmented_access', return_value=plain):
                    self.assertEqual(list(receiver.receive(options['address'], -60, b'')), [])
                    receiver.imports_ready = True
                    events = list(receiver.receive(options['address'], -60, b''))
                    self.assertEqual(len(events), 1)
                    self.assertEqual((events[0]['entity_id'], events[0]['kind'], events[0]['value']),
                                     ('light.bulb', 'color', (0, 0, 255)))
                    self.assertTrue(events[0]['imported'])

    def test_imported_controls_do_not_change_the_supergroup(self):
        options = dict(self.options, independent_channels=True,
                       imported_lights=prepare_import(self.options,
                           [{'entity_id': 'light.bulb', 'name': 'Bulb'}], self.states))
        calls = []
        def request(path, payload=None):
            if path == 'states':
                return list(self.states.values())
            calls.append((path, payload))
        controller = SeparateLightController(options, request)
        controller('light.group', {'slot': 7, 'kind': 'brightness', 'value': 30})
        self.assertEqual(calls.pop(), ('services/light/turn_on',
                                      {'entity_id': 'light.bulb', 'brightness_pct': 30}))
        controller('light.group', {'slot': 7, 'kind': 'color', 'value': [0, 0, 255]})
        self.assertEqual(calls.pop(), ('services/light/turn_on',
                    {'entity_id': 'light.bulb', 'rgbww_color': [0, 0, 255, 0, 0]}))

    def test_imported_menu_and_feedback_use_matching_slots(self):
        options = dict(self.options, imported_lights=prepare_import(self.options,
                     [{'entity_id': 'light.bulb', 'name': 'Bulb'}], self.states))
        rows = imported_menu(options)
        packets = test_menu_packets(1, separate_controls=True, ha_lights_menu=True,
                                    imported_lights=rows)
        self.assertEqual((len(packets), packets[-1][15], packets[-1][18]), (7, 7, 4))
        self.states['light.group'] = {'entity_id': 'light.group', 'state': 'off', 'attributes':
                                     {'entity_id': ['light.bulb']}}
        self.states['light.bulb']['attributes'].update(brightness=51, color_mode='rgbww',
                                                      rgbww_color=[0, 0, 255, 0, 0], rgb_color=[0, 0, 255])
        with patch.dict('os.environ', {'SUPERVISOR_TOKEN': 'test'}), patch(
                'light_sync.urlopen', return_value=io.BytesIO(json.dumps(list(self.states.values())).encode())):
            state = read_light_state('light.group', separate_controls=True, independent_channels=True,
                                     ha_lights_menu=True, imported_lights=rows)
        self.assertEqual(state['imports'], {7: (True, 20, 1, (0, 0, 255))})

    def test_coalescing_keeps_different_imported_lights_independent(self):
        worker = LightWorker('light.group', SimpleNamespace(independent=True))
        worker.submit({'slot': 7, 'kind': 'brightness', 'value': 20, 'imported': True, 'entity_id': 'light.bulb'})
        worker.submit({'slot': 8, 'kind': 'brightness', 'value': 30, 'imported': True, 'entity_id': 'light.lamp'})
        worker.submit({'slot': 7, 'kind': 'power', 'value': False, 'imported': True, 'entity_id': 'light.bulb'})
        self.assertEqual([(e['slot'], e['kind']) for e in worker.pending.values()],
                         [(8, 'brightness'), (7, 'power')])
