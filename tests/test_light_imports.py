"""User-selected menu targets, capacity, local labels and import isolation."""
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'knob_bridge'))
from light_imports import imported_menu, prepare_import, render_label
from PIL import Image


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
