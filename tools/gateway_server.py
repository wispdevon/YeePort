"""Experimental S20 discovery and initial GATT handshake; no cloud enrollment."""

import argparse
import asyncio
import json
import signal
from datetime import datetime, timezone
from pathlib import Path

from dbus_fast import Message, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType, PropertyAccess, MessageType
from dbus_fast.errors import DBusError
from dbus_fast.service import ServiceInterface, dbus_property, method

from advertise_gateway import Advertisement
from gateway_handshake import GatewayHandshake
from gateway_config import decode_config
from gateway_enrollment import probe_endpoint

ROOT = "/org/yeegate/gatt"
SERVICE = ROOT + "/service0"
UUID = "0000fe99-0000-1000-8000-00805f9b34fb"


class PairingAgent(ServiceInterface):
    def __init__(self, peers, log, bus=None):
        super().__init__("org.bluez.Agent1")
        self.peers = {p.upper().replace(":", "_") for p in peers}
        self.log = log
        self.bus = bus

    async def check(self, device):
        allowed = device.rsplit("dev_", 1)[-1].upper() in self.peers
        if not allowed and self.bus:
            # BlueZ retains the original private-address object path after
            # resolving a bonded peer. Authorize its resolved identity too.
            reply = await self.bus.call(Message(
                destination="org.bluez", path=device,
                interface="org.freedesktop.DBus.Properties", member="Get",
                signature="ss", body=["org.bluez.Device1", "Address"]))
            if reply.message_type == MessageType.METHOD_RETURN and reply.body:
                address = reply.body[0].value.upper().replace(":", "_")
                allowed = address in self.peers
        if not allowed:
            self.log("pairing_rejected", device=device)
            raise DBusError("org.bluez.Error.Rejected", "Peer not authorized for this test")
        self.log("pairing_authorized", device=device)

    @method()
    def Release(self):
        self.log("pairing_agent_released")

    @method()
    async def RequestAuthorization(self, device: 'o'):
        await self.check(device)

    @method()
    async def RequestConfirmation(self, device: 'o', passkey: 'u'):
        await self.check(device)

    @method()
    async def AuthorizeService(self, device: 'o', uuid: 's'):
        await self.check(device)

    @method()
    def RequestPinCode(self, device: 'o') -> 's':
        raise DBusError("org.bluez.Error.Rejected", "PIN entry is not implemented")

    @method()
    def RequestPasskey(self, device: 'o') -> 'u':
        raise DBusError("org.bluez.Error.Rejected", "Passkey entry is not implemented")

    @method()
    def Cancel(self):
        self.log("pairing_cancelled")


class Service(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.GattService1")

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's':
        return UUID

    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> 'b':
        return True


class Characteristic(ServiceInterface):
    def __init__(self, short, flags, log, receive=None):
        super().__init__("org.bluez.GattCharacteristic1")
        self.short, self.flags, self.log, self.receive = short, flags, log, receive
        self.notifying = False
        self.value = b""

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's':
        return f"000000{self.short}-0000-1000-8000-00805f9b34fb"

    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> 'o':
        return SERVICE

    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> 'as':
        return self.flags

    @dbus_property(access=PropertyAccess.READ)
    def Value(self) -> 'ay':
        return self.value

    @dbus_property(access=PropertyAccess.READ)
    def Notifying(self) -> 'b':
        return self.notifying

    @method()
    def ReadValue(self, options: 'a{sv}') -> 'ay':
        self.log("read", characteristic=self.short)
        return self.value

    @method()
    def WriteValue(self, value: 'ay', options: 'a{sv}'):
        self.log("write", characteristic=self.short, length=len(value))
        if self.receive:
            self.receive(bytes(value))

    @method()
    def StartNotify(self):
        self.notifying = True
        self.emit_properties_changed({"Notifying": True})
        self.log("subscribe", characteristic=self.short)

    @method()
    def StopNotify(self):
        self.notifying = False
        self.emit_properties_changed({"Notifying": False})
        self.log("unsubscribe", characteristic=self.short)

    def notify(self, value):
        if not self.notifying:
            raise ValueError("Client has not subscribed to gateway notifications")
        self.value = value
        self.emit_properties_changed({"Value": value})
        self.log("notify", characteristic=self.short, length=len(value))


class Application(ServiceInterface):
    def __init__(self, entries):
        super().__init__("org.freedesktop.DBus.ObjectManager")
        self.entries = entries

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        return self.entries


async def run(args):
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    with args.log.open("a", encoding="utf-8") as stream:
        def log(event, **fields):
            record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
            line = json.dumps(record)
            print(line, flush=True)
            stream.write(line + "\n")
            stream.flush()

        handshake = GatewayHandshake()
        configuration = None
        enrollment_tasks = set()

        async def inspect_enrollment(config):
            try:
                log("enrollment_endpoint", **await probe_endpoint(config))
            except ValueError as exc:
                log("enrollment_endpoint_error", message=str(exc))
            log("enrollment_pending", reason="device_registration_protocol_unknown",
                enrollment_complete=False)

        def receive(value):
            nonlocal handshake, configuration
            try:
                if value.startswith(bytes.fromhex("05000164")) and handshake.complete:
                    handshake = GatewayHandshake()
                    configuration = None
                if handshake.complete:
                    # Do not log onboarding contents, credentials, or session keys.
                    configuration = decode_config(value, handshake.aes_key)
                    log("configuration_decoded", length=len(value),
                        method="config_device", enrollment_complete=False)
                    # 0503 acknowledges configuration transfer. It is distinct
                    # from 0504 enrollment status; no cloud success is claimed.
                    # Keep configuration only in memory for future enrollment.
                    outgoing.notify(bytes.fromhex("0503"))
                    log("configuration_acknowledged", enrollment_complete=False)
                    task = asyncio.create_task(inspect_enrollment(configuration))
                    enrollment_tasks.add(task)
                    task.add_done_callback(enrollment_tasks.discard)
                    return
                reply = handshake.receive(value)
                if reply:
                    outgoing.notify(reply)
                    log("key_exchange_replied", enrollment_complete=False)
            except ValueError as exc:
                log("handshake_error", message=str(exc))
                handshake = GatewayHandshake()

        service = Service()
        incoming = Characteristic("55", ["write", "write-without-response", "notify"], log, receive)
        outgoing = Characteristic("66", ["notify", "read"], log)
        entries = {SERVICE: {service.name: {"UUID": Variant("s", UUID), "Primary": Variant("b", True)}}}
        for index, char in enumerate((incoming, outgoing)):
            entries[SERVICE + f"/char{index}"] = {char.name: {
                "UUID": Variant("s", char.UUID), "Service": Variant("o", SERVICE),
                "Flags": Variant("as", char.flags),
            }}
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        def connection_event(message):
            if (message.message_type == MessageType.SIGNAL
                    and message.interface == "org.freedesktop.DBus.Properties"
                    and message.member == "PropertiesChanged"
                    and message.body[0] == "org.bluez.Device1"):
                changed = message.body[1]
                for key in ("Connected", "ServicesResolved"):
                    if key in changed:
                        log("connection_state", device=message.path,
                            property=key, value=changed[key].value)
            return False
        bus.add_message_handler(connection_event)
        daemon = bus.get_proxy_object("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                      await bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus"))
        await daemon.get_interface("org.freedesktop.DBus").call_add_match(
            "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'"
        )
        bus.export(ROOT, Application(entries))
        bus.export(SERVICE, service)
        bus.export(SERVICE + "/char0", incoming)
        bus.export(SERVICE + "/char1", outgoing)
        adapter = "/org/bluez/" + args.adapter
        obj = bus.get_proxy_object("org.bluez", adapter, await bus.introspect("org.bluez", adapter))
        gatt = obj.get_interface("org.bluez.GattManager1")
        manager = obj.get_interface("org.bluez.LEAdvertisingManager1")
        props = obj.get_interface("org.freedesktop.DBus.Properties")
        original_pairable = (await props.call_get("org.bluez.Adapter1", "Pairable")).value
        agent_manager = None
        agent_path = "/org/yeegate/agent"
        if args.pairing_peer:
            agent_obj = bus.get_proxy_object("org.bluez", "/org/bluez",
                                             await bus.introspect("org.bluez", "/org/bluez"))
            agent_manager = agent_obj.get_interface("org.bluez.AgentManager1")
            bus.export(agent_path, PairingAgent(args.pairing_peer, log, bus))
        adv_path = "/org/yeegate/advertisement"
        bus.export(adv_path, Advertisement(args.pid, args.identity_mac))
        registered_gatt = registered_adv = registered_agent = changed_pairable = False
        try:
            if agent_manager:
                await agent_manager.call_register_agent(agent_path, "NoInputNoOutput")
                registered_agent = True
                await agent_manager.call_request_default_agent(agent_path)
                await props.call_set("org.bluez.Adapter1", "Pairable", Variant("b", True))
                changed_pairable = True
                log("pairing_enabled", restricted_to=args.pairing_peer)
            await gatt.call_register_application(ROOT, {})
            registered_gatt = True
            await manager.call_register_advertisement(adv_path, {})
            registered_adv = True
            log("ready", pid=args.pid, identity_mac=args.identity_mac, enrollment_complete=False)
            try:
                await asyncio.wait_for(stop.wait(), args.seconds)
            except TimeoutError:
                pass
        finally:
            for task in enrollment_tasks:
                task.cancel()
            if enrollment_tasks:
                await asyncio.gather(*enrollment_tasks, return_exceptions=True)
            cleanup = []
            if registered_adv:
                cleanup.append(lambda: manager.call_unregister_advertisement(adv_path))
            if registered_gatt:
                cleanup.append(lambda: gatt.call_unregister_application(ROOT))
            if registered_agent:
                cleanup.append(lambda: agent_manager.call_unregister_agent(agent_path))
            if changed_pairable:
                cleanup.append(lambda: props.call_set("org.bluez.Adapter1", "Pairable", Variant("b", original_pairable)))
            for action in cleanup:
                try:
                    await action()
                except Exception as exc:
                    log("cleanup_error", message=str(exc))
            bus.disconnect()
            log("stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", default="hci0")
    parser.add_argument("--pid", type=int, choices=[14336, 14337], default=14336)
    parser.add_argument("--identity-mac", default="F8:24:41:EE:00:01")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--log", type=Path, default=Path("gateway-events.jsonl"))
    parser.add_argument("--pairing-peer", action="append", default=[],
                        help="Allow temporary Bluetooth pairing with this address only (repeatable)")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("--seconds must be between 1 and 3600")
    asyncio.run(run(args))
