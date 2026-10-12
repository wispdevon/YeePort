"""Experimental discovery advertisement, not a working Yeelight gateway."""

import argparse
import asyncio

from dbus_fast import Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType
from dbus_fast.service import ServiceInterface, dbus_property, method
from dbus_fast.constants import PropertyAccess


class Advertisement(ServiceInterface):
    def __init__(self, pid, mac):
        super().__init__("org.bluez.LEAdvertisement1")
        # APK 1.33.0 parses a big-endian uint32 PID, a reversed MAC,
        # a big-endian uint64 device ID, and a flags byte (19 bytes total).
        # NearbyGatewaysListModel filters the embedded MAC through
        # GatewayScanMacPolicy, accepting F8:24:41:* or a fixed exception set.
        # The device ID below is a local test value, not a cloud identity.
        self.payload = (pid.to_bytes(4, "big")
                        + bytes.fromhex(mac.replace(":", ""))[::-1]
                        + (1).to_bytes(8, "big") + b"\x00")

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> 's':
        return "peripheral"

    @dbus_property(access=PropertyAccess.READ)
    def Discoverable(self) -> 'b':
        return True

    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> 's':
        return "YeeGate S20"

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> 'as':
        return ["0000fe99-0000-1000-8000-00805f9b34fb"]

    @dbus_property(access=PropertyAccess.READ)
    def ManufacturerData(self) -> 'a{qv}':
        return {0x0164: Variant("ay", self.payload)}

    @method()
    def Release(self):
        print("Advertisement released by BlueZ", flush=True)


async def run(args):
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    path = "/org/bluez/" + args.adapter
    obj = bus.get_proxy_object("org.bluez", path, await bus.introspect("org.bluez", path))
    props = obj.get_interface("org.freedesktop.DBus.Properties")
    mac = (await props.call_get("org.bluez.Adapter1", "Address")).value
    adv = Advertisement(args.pid, args.identity_mac)
    adv_path = "/org/yeegate/advertisement"
    bus.export(adv_path, adv)
    manager = obj.get_interface("org.bluez.LEAdvertisingManager1")
    registered = False
    try:
        await manager.call_register_advertisement(adv_path, {})
        registered = True
        print(f"EXPERIMENTAL gateway PID {args.pid}, adapter {mac}, advertised identity {args.identity_mac}, payload {adv.payload.hex()}", flush=True)
        print(f"Advertising for {args.seconds}s. Discovery only; pairing is not implemented.", flush=True)
        await asyncio.sleep(args.seconds)
    finally:
        if registered:
            await manager.call_unregister_advertisement(adv_path)
        bus.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, choices=[14336, 14337], default=14336)
    parser.add_argument("--adapter", default="hci0")
    parser.add_argument("--identity-mac", default="F8:24:41:EE:00:01",
                        help="Embedded test identity; does not change the adapter MAC")
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error("--seconds must be between 1 and 600")
    import re
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", args.identity_mac):
        parser.error("--identity-mac must be six colon-separated hexadecimal bytes")
    asyncio.run(run(args))
