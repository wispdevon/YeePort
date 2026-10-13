"""Local Bluetooth Mesh activity to Home Assistant MQTT discovery bridge."""

import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import threading
import time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bleak import BleakScanner
import paho.mqtt.client as mqtt

from mesh import Activity, reports
from clock_sync import run_clock_sync
from weather_sync import run_weather_sync
from light_control import LightReceiver, LightWorker, SeparateLightController
from light_sync import run_light_sync
from light_imports import imported_menu
from import_ui import start_ui


def mqtt_settings(options):
    if options.get("mqtt_host"):
        return {"host": options["mqtt_host"], "port": options.get("mqtt_port", 1883),
                "username": options.get("mqtt_username", ""),
                "password": options.get("mqtt_password", ""),
                "ssl": options.get("mqtt_tls", False)}
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("Set mqtt_host or run as a Home Assistant app with MQTT service access")
    request = Request("http://supervisor/services/mqtt",
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if result.get("result") != "ok":
        raise RuntimeError("Supervisor MQTT service is unavailable")
    return result["data"]


def discovery(address, name):
    identifier = "yeegate_" + address.replace(":", "").lower()
    topic = "yeegate/" + identifier
    return "homeassistant/event/" + identifier + "/activity/config", {
        "name": "Mesh activity", "unique_id": identifier + "_activity",
        "state_topic": topic + "/event", "event_types": ["mesh_activity"],
        "availability_topic": topic + "/availability", "icon": "mdi:gesture-tap",
        "device": {"identifiers": [identifier], "name": name,
                   "manufacturer": "Yeelight", "model": "S Knob (1574912)",
                   "connections": [["bluetooth", address.upper()]]}}, topic


def action_discovery(address, name):
    """Expose only the activity we can actually recognize in the UI."""
    _, event_config, topic = discovery(address, name)
    identifier = "yeegate_" + address.replace(":", "").lower()
    return "homeassistant/device_automation/" + identifier + "/activity/config", {
        "automation_type": "trigger", "type": "activity", "subtype": "Mesh",
        "topic": topic + "/event", "payload": "mesh_activity",
        "value_template": "{{ value_json.event_type }}",
        "device": event_config["device"],
    }


def light_discovery(address, name):
    _, existing, topic = discovery(address, name)
    identifier = "yeegate_" + address.replace(":", "").lower()
    yield "homeassistant/event/" + identifier + "/light/config", {
        "name": "Light command", "unique_id": identifier + "_light_command",
        "state_topic": topic + "/light_command", "event_types": ["brightness", "power_on", "power_off", "color", "color_temperature", "warm_brightness", "warm_power_on", "warm_power_off", "scene"],
        "availability_topic": topic + "/availability", "icon": "mdi:lightbulb",
        "device": existing["device"]}
    for action, label in [("brightness", "Brightness changed"), ("power_on", "Light turned on"),
                          ("power_off", "Light turned off"), ("color", "Color changed"),
                          ("color_temperature", "Color temperature changed"),
                          ("warm_brightness", "Warm-white brightness changed"),
                          ("warm_power_on", "Warm white turned on"),
                          ("warm_power_off", "Warm white turned off"),
                          ("scene", "Red 10% preset pressed")]:
        yield "homeassistant/device_automation/" + identifier + "/" + action + "/config", {
            "automation_type": "trigger", "type": label, "subtype": "HA Lights",
            "topic": topic + "/light_command", "payload": action,
            "value_template": "{{ value_json.event_type }}", "device": existing["device"]}


async def run(options):
    address = options.get("address", "F8:24:41:39:9F:38").upper()
    adapter = options.get("adapter", "hci0")
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address) or not re.fullmatch(r"hci\d+", adapter):
        raise ValueError("Invalid device address or adapter")
    if options.get("clock_sync_enabled", False):
        ZoneInfo(options.get("timezone", "Asia/Bangkok"))
        if address != "F8:24:41:39:9F:38" or not 300 <= int(options.get("clock_sync_interval", 3600)) <= 86400:
            raise ValueError("Invalid clock synchronization device or interval")
    if options.get("weather_sync_enabled", False):
        if address != "F8:24:41:39:9F:38" or not re.fullmatch(r"weather\.[a-z0-9_]+", options.get("weather_entity", "weather.forecast_home")):
            raise ValueError("Invalid weather synchronization device or entity")
    settings = mqtt_settings(options)
    config_topic, config, topic = discovery(address, options.get("name", "Knob"))
    action_topic, action_config = action_discovery(address, options.get("name", "Knob"))
    receiver = None
    if options.get("mesh_net_key") or options.get("mesh_app_key"):
        receiver = LightReceiver(options)
    if options.get("light_control_enabled", False) and receiver is None:
        raise ValueError("Verified Mesh keys are required for light control")
    light_worker = LightWorker(options.get("light_entity", "light.knob_lights")) if (
        receiver is not None and options.get("light_control_enabled", False)) else None
    imports = imported_menu(options)
    if light_worker and (options.get('separate_brightness_controls', False) or imports):
        light_worker.callback = SeparateLightController(options)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="yeegate-knob-" + address.replace(":", "").lower())
    if settings.get("username"):
        client.username_pw_set(settings["username"], settings.get("password", ""))
    if settings.get("ssl"):
        client.tls_set()
    client.will_set(topic + "/availability", "offline", qos=1, retain=True)
    connected = threading.Event()
    ready = False

    def announce():
        client.publish(config_topic, json.dumps(config), qos=1, retain=True)
        client.publish(action_topic, json.dumps(action_config), qos=1, retain=True)
        if receiver:
            for destination, payload in light_discovery(address, options.get("name", "Knob")):
                client.publish(destination, json.dumps(payload), qos=1, retain=True)
        client.publish(topic + "/availability", "online" if ready else "offline", qos=1, retain=True)

    def on_connect(client, userdata, flags, reason, properties):
        if not reason.is_failure:
            connected.set()
            client.subscribe("homeassistant/status")
            announce()

    def on_disconnect(client, userdata, flags, reason, properties):
        connected.clear()

    def on_message(client, userdata, message):
        if message.topic == "homeassistant/status" and message.payload == b"online":
            announce()

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    client.connect_async(settings["host"], int(settings["port"]), keepalive=60)
    client.loop_start()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    activity = Activity(address)
    monitor = None
    clock_task = None
    weather_task = None
    light_task = None
    light_sync_task = None
    ui_server = None
    local_gatt_lock = asyncio.Lock()
    suppress_until = 0

    def suppress_activity(seconds):
        nonlocal suppress_until
        suppress_until = time.monotonic() + seconds

    def readable():
        try:
            raw = monitor.recv(65535)
        except BlockingIOError:
            return
        if len(raw) < 6:
            return
        opcode, index, size = struct.unpack("<HHH", raw[:6])
        if opcode != 3 or index != int(adapter[3:]) or len(raw) < size + 6:
            return
        for peer, rssi, data in reports(raw[6:6 + size]):
            if receiver:
                for event in receiver.receive(peer, rssi, data):
                    if connected.is_set():
                        client.publish(topic + "/light_command", json.dumps(event), qos=0, retain=False)
                    if light_worker:
                        light_worker.submit(event)
                    print(json.dumps(event), flush=True)
            for event in activity.receive(peer, rssi, data, time.monotonic()):
                # Disconnected events are intentionally discarded, not replayed.
                if connected.is_set() and time.monotonic() >= suppress_until:
                    client.publish(topic + "/event", json.dumps(event), qos=0, retain=False)
                    print(json.dumps(event), flush=True)

    try:
        if os.environ.get('SUPERVISOR_TOKEN'):
            ui_server = await asyncio.to_thread(start_ui, options,
                          lambda: bool(light_worker and receiver.imports_ready))
        monitor = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
        # Python <3.14 only accepts the legacy HCI address tuple. Use Linux's
        # sockaddr_hci layout directly to select the monitor channel reliably.
        address_buffer = ctypes.create_string_buffer(struct.pack("=HHH", socket.AF_BLUETOOTH, 65535, 2))
        libc = ctypes.CDLL(None, use_errno=True)
        libc.bind.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
        libc.bind.restype = ctypes.c_int
        if libc.bind(monitor.fileno(), address_buffer, 6) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        monitor.setblocking(False)
        loop.add_reader(monitor.fileno(), readable)
        scanner = BleakScanner(adapter=adapter)

        async def find_device(peer):
            # Reuse our scan session: another StartDiscovery on the same BlueZ
            # connection fails with InProgress and can stop the primary scan.
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                for device in scanner.discovered_devices:
                    if device.address.upper() == peer:
                        return device
                await asyncio.sleep(0.2)
            raise RuntimeError("Knob not found in the active scan")

        async with scanner:
            ready = True
            if connected.is_set():
                announce()
            print("Listening for authenticated HA Lights commands" if receiver else
                  "Listening for knob Mesh activity; action labels are not decoded", flush=True)
            if light_worker:
                light_task = asyncio.create_task(light_worker.run())
                def light_busy():
                    return (light_worker.busy or bool(light_worker.pending) or
                            time.monotonic() - receiver.last_command < 3)
                light_sync_task = asyncio.create_task(run_light_sync(
                    light_worker.entity, stopped, lock=local_gatt_lock, find_device=find_device,
                    busy=light_busy, suppress_activity=suppress_activity,
                    color_controls=options.get("color_controls_enabled", False),
                    on_feedback=receiver.scaling.rebase,
                    separate_controls=options.get('separate_brightness_controls', False),
                    on_warm_feedback=receiver.warm_scaling.rebase,
                    independent_channels=options.get('independent_channels', False),
                    on_levels_feedback=getattr(light_worker.callback, 'sync_feedback', None),
                    ha_lights_menu=options.get('ha_lights_menu_enabled', False),
                    on_group_feedback=receiver.group_scaling.rebase,
                    imported_lights=imports, display_device_key=options.get('display_device_key', ''),
                    on_import_feedback=receiver.import_feedback))
            clock_task = asyncio.create_task(run_clock_sync(
                options, stopped, lock=local_gatt_lock, suppress_activity=suppress_activity,
                find_device=find_device))
            weather_task = asyncio.create_task(run_weather_sync(
                options, stopped, lock=local_gatt_lock, suppress_activity=suppress_activity,
                find_device=find_device))
            await stopped.wait()
    finally:
        if ui_server:
            await asyncio.to_thread(ui_server.shutdown)
            ui_server.server_close()
        sync_tasks = [task for task in (clock_task, weather_task, light_task, light_sync_task) if task]
        for task in sync_tasks:
            task.cancel()
        await asyncio.gather(*sync_tasks, return_exceptions=True)
        if monitor:
            loop.remove_reader(monitor.fileno())
            monitor.close()
        if connected.is_set():
            client.publish(topic + "/availability", "offline", qos=1, retain=True).wait_for_publish(3)
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--options", type=Path, default=Path("/data/options.json"))
    args = parser.parse_args()
    asyncio.run(run(json.loads(args.options.read_text())))
