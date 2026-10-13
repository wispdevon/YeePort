"""Home Assistant ingress UI for importing lights; never serves credentials."""
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from light_control import ha_request
from light_imports import base_slot_count, imported_menu, light_controls, prepare_import, render_label


def supervisor_request(path, payload=None):
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        raise RuntimeError('Home Assistant app API access is required.')
    request = Request('http://supervisor/' + path,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f'Home Assistant app API returned status {error.code}.') from None
    if result.get('result') != 'ok':
        raise RuntimeError('Home Assistant app API rejected the request.')
    return result.get('data', {})


class ImportManager:
    def __init__(self, options, request=ha_request, supervisor=supervisor_request, ready=lambda: True):
        self.options, self.request, self.supervisor, self.ready = options, request, supervisor, ready
        self.csrf = secrets.token_urlsafe(32)
        self.saving = self.restart_failed = False
        self.lock = threading.Lock()

    def state(self):
        states = self.request('states')
        lights = sorted([{'entity_id': s['entity_id'],
                         'name': s.get('attributes', {}).get('friendly_name', s['entity_id']),
                         'available': s.get('state') not in ('unavailable', 'unknown'),
                         'controls': light_controls(s)} for s in states if s['entity_id'].startswith('light.')],
                        key=lambda s: (s['name'].casefold(), s['entity_id']))
        builtins = ['Relay 1', 'Relay 2']
        if self.options.get('separate_brightness_controls', False):
            builtins += ['RGB Lights', 'Warm White', 'Red 10%']
            if self.options.get('ha_lights_menu_enabled', False):
                builtins.append('HA Lights')
        else:
            builtins.append('HA Lights')
        imports = imported_menu(self.options)
        capacity = 8 - base_slot_count(self.options)
        return {'lights': lights, 'imported': imports, 'builtins': builtins, 'capacity': capacity,
                'remaining': capacity - len(imports), 'csrf': self.csrf,
                'ready': bool(self.ready()), 'restarting': self.saving,
                'restart_failed': self.restart_failed,
                'control_enabled': self.options.get('light_control_enabled', False),
                'setup_needed': not bool(re.fullmatch(r'[0-9a-fA-F]{32}', self.options.get('display_device_key', '')))}

    def save(self, selected):
        with self.lock:
            if self.saving or not self.ready():
                raise BlockingIOError('Wait for the current menu update to finish.')
            latest = self.supervisor('addons/self/info')['options']
            if not latest.get('light_control_enabled', False):
                raise ValueError('Enable light control in the app configuration first.')
            if not re.fullmatch(r'[0-9a-fA-F]{32}', latest.get('display_device_key', '')):
                raise ValueError('Set the recovered display device key in the app configuration first.')
            states = {s['entity_id']: s for s in self.request('states')}
            records = prepare_import(latest, selected, states)
            # Confirm the local font/renderer works before saving any options.
            for record in records:
                render_label(record['name'])
            if records != latest.get('imported_lights', []):
                self.supervisor('addons/self/options', {'options': dict(latest, imported_lights=records)})
                self.saving = True
                threading.Thread(target=self._restart, daemon=True).start()
            return {'saved': True, 'lights': records}

    def _restart(self):
        time.sleep(1)
        try:
            self.supervisor('addons/self/restart', {})
        except Exception as error:
            self.restart_failed = True
            print(json.dumps({'import_restart': 'failed', 'error': type(error).__name__}), flush=True)


def make_server(manager, host='0.0.0.0', port=8099, allowed_clients=('172.30.32.2',)):
    static = Path(__file__).with_name('web')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type='application/json'):
            if content_type == 'application/json':
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                             "frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def authorize(self):
            if self.client_address[0] not in self.server.allowed_clients:
                self.respond(403, {'error': 'Open YeePort through Home Assistant.'})
                return False
            return True

        def do_GET(self):
            if not self.authorize():
                return
            path = self.path.split('?')[0]
            if path == '/api/state':
                try:
                    self.respond(200, manager.state())
                except Exception as error:
                    print(json.dumps({'import_ui': 'state_failed', 'error': type(error).__name__}), flush=True)
                    self.respond(503, {'error': 'Could not read Home Assistant lights. Try refreshing.'})
                return
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                     '/style.css': ('style.css', 'text/css'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            if path not in files:
                self.respond(404, {'error': 'Not found.'})
                return
            name, content_type = files[path]
            body = (static / name).read_bytes()
            if name == 'index.html':
                base = self.headers.get('X-Ingress-Path', '')
                if base and not re.fullmatch(r'/[a-zA-Z0-9_/-]+', base):
                    self.respond(400, {'error': 'Invalid Home Assistant path.'})
                    return
                body = body.replace(b'__YEEPORT_BASE__', html.escape(base.rstrip('/') + '/', quote=True).encode())
            self.respond(200, body, content_type)

        def do_POST(self):
            if not self.authorize():
                return
            if self.path != '/api/import':
                self.respond(404, {'error': 'Not found.'})
                return
            if not secrets.compare_digest(self.headers.get('X-YeePort-CSRF', ''), manager.csrf):
                self.respond(403, {'error': 'Refresh this page before saving.'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 8192 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Invalid import request.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {'lights'}:
                    raise ValueError('Choose a list of lights.')
                self.respond(200, manager.save(data['lights']))
            except BlockingIOError as error:
                self.respond(409, {'error': str(error)})
            except ValueError as error:
                self.respond(400, {'error': str(error)})
            except Exception as error:
                print(json.dumps({'import_ui': 'save_failed', 'error': type(error).__name__}), flush=True)
                self.respond(503, {'error': 'Could not finish saving. Check the app log and try again.'})
    server = ThreadingHTTPServer((host, port), Handler)
    server.allowed_clients = allowed_clients
    return server


def start_ui(options, ready):
    info = supervisor_request('addons/self/info')
    manager = ImportManager(options, ready=ready)
    server = make_server(manager, port=info['ingress_port'])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print('YeePort light importer is available through Home Assistant.', flush=True)
    return server
