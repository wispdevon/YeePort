"""Ingress-only import API, validation, credential isolation and persistence."""
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'knob_bridge'))
from import_ui import ImportManager, make_server
from light_control import LightReceiver
import tempfile


class ImportAPI(unittest.TestCase):
    def setUp(self):
        self.options = {'separate_brightness_controls': True, 'ha_lights_menu_enabled': True,
                        'display_device_key': '22' * 16, 'light_control_enabled': True,
                        'mesh_net_key': '00' * 16, 'mqtt_password': 'private-test-password',
                        'imported_lights': []}
        self.states = [{'entity_id': 'light.bulb', 'state': 'on', 'attributes':
                        {'friendly_name': 'Bulb', 'supported_color_modes': ['rgbww', 'color_temp']}},
                       {'entity_id': 'light.lamp', 'state': 'off', 'attributes':
                        {'friendly_name': 'Lamp', 'supported_color_modes': ['brightness']}}]
        self.saved, self.restarted = [], threading.Event()
        def supervisor(path, payload=None):
            if path.endswith('/info'):
                return {'options': self.options}
            if path.endswith('/options'):
                self.saved.append(payload['options'])
            if path.endswith('/restart'):
                self.restarted.set()
            return {}
        self.manager = ImportManager(self.options, request=lambda path: self.states,
                                     supervisor=supervisor, ready=lambda: True)
        self.server = make_server(self.manager, host='127.0.0.1', port=0, allowed_clients=('127.0.0.1',))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def call(self, path='api/state', data=None, headers=None):
        headers = {'Content-Type': 'application/json', **(headers or {})}
        request = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                          headers=headers)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def test_lists_lights_and_capacity_without_credentials(self):
        status, data = self.call()
        self.assertEqual(status, 200)
        self.assertEqual((data['capacity'], data['remaining']), (2, 2))
        self.assertEqual([x['entity_id'] for x in data['lights']], ['light.bulb', 'light.lamp'])
        for value in ('22' * 16, '00' * 16, 'private-test-password'):
            self.assertNotIn(value, json.dumps(data))

    def test_empty_menu_waits_for_display_sync_before_reporting_ready(self):
        options = dict(self.options, address='F8:24:41:39:9F:38', mesh_app_key='11' * 16,
                       mesh_iv_index=0, mesh_unicast_address=5)
        with tempfile.TemporaryDirectory() as folder:
            receiver = LightReceiver(options, Path(folder) / 'sequence.json')
            self.manager.ready = lambda: receiver.imports_ready
            self.assertFalse(self.call()[1]['ready'])
            receiver.import_feedback({})
            self.assertTrue(self.call()[1]['ready'])

    def test_serves_ingress_relative_assets_and_blocks_private_paths(self):
        request = Request(self.url, headers={'X-Ingress-Path': '/api/hassio_ingress/example'})
        with urlopen(request, timeout=3) as response:
            page = response.read().decode()
            self.assertIn('script-src', response.headers['Content-Security-Policy'])
            self.assertIn('/api/hassio_ingress/example/app.js', page)
            self.assertNotIn('__YEEPORT_BASE__', page)
        self.assertEqual(self.call('config.json')[0], 404)
        self.assertEqual(self.call('api/state', headers={'X-Forwarded-For': 'untrusted'})[0], 200)

    def test_rejects_non_ingress_clients_even_with_forwarded_header(self):
        self.server.allowed_clients = ()
        self.assertEqual(self.call(headers={'X-Forwarded-For': '172.30.32.2'})[0], 403)

    def test_rejects_missing_csrf_and_invalid_import_before_saving(self):
        self.assertEqual(self.call('api/import', {'lights': []})[0], 403)
        csrf = self.call()[1]['csrf']
        self.assertEqual(self.call('api/import', {'lights': [{'entity_id': 'sensor.bad', 'name': 'Bad'}]},
                                  {'X-YeePort-CSRF': csrf})[0], 400)
        self.assertEqual(self.saved, [])

    def test_import_persists_options_and_requests_bridge_restart(self):
        csrf = self.call()[1]['csrf']
        status, result = self.call('api/import', {'lights': [{'entity_id': 'light.bulb', 'name': 'Wiz Bulb'}]},
                                   {'X-YeePort-CSRF': csrf})
        self.assertEqual(status, 200)
        self.assertTrue(result['saved'])
        self.assertEqual(self.saved[0]['imported_lights'],
                         [{'entity_id': 'light.bulb', 'name': 'Wiz Bulb', 'controls': 'color'}])
        self.assertEqual(self.saved[0]['mqtt_password'], 'private-test-password')
        self.assertTrue(self.restarted.wait(3))
        self.assertEqual(self.call('api/import', {'lights': []}, {'X-YeePort-CSRF': csrf})[0], 409)

    def test_remove_saves_empty_list_and_overflow_is_rejected(self):
        csrf = self.call()[1]['csrf']
        records = [{'entity_id': 'light.bulb', 'name': 'Bulb'}] * 3
        self.assertEqual(self.call('api/import', {'lights': records}, {'X-YeePort-CSRF': csrf})[0], 400)
        self.options['imported_lights'] = [{'entity_id': 'light.bulb', 'name': 'Bulb', 'controls': 'color'}]
        self.assertEqual(self.call('api/import', {'lights': []}, {'X-YeePort-CSRF': csrf})[0], 200)
        self.assertEqual(self.saved[0]['imported_lights'], [])
