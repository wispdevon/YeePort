"""Verified physical S Knob calendar clock updates over authenticated BLE UART.

This module uses no Yeelight cloud credentials or Mesh network keys. Firmware
OTA and provisioning are not part of this transport. Bangkok time/date were
confirmed on the physical screen after a controlled test of this exact setter.
"""

import asyncio
import binascii
from datetime import datetime, timezone
import hashlib
import struct
from zoneinfo import ZoneInfo

from bleak import BleakClient, BleakScanner

KNOB_ADDRESS = "F8:24:41:39:9F:38"
DISPLAY_CHARACTERISTIC = "b19adf7e-b836-40e3-8b06-acc47f2d187e"


def clock_packet(zone_name, *, now=None, sequence=1):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or not 0 <= sequence <= 65535:
        raise ValueError("An aware clock and 16-bit sequence are required")
    local = now.astimezone(ZoneInfo(zone_name))
    # The knob's C calendar clock uses GMT; its normal gateway therefore sends
    # local calendar seconds. User verified this offset on the physical screen.
    firmware_epoch = int(now.timestamp() + local.utcoffset().total_seconds())
    payload = b"\x05\x08" + struct.pack("<I", firmware_epoch)
    header = bytes.fromhex("f0f1f2f3") + bytes((1, 0x1c, 0))
    header += struct.pack("<HH", sequence, len(payload))
    return header + payload + struct.pack("<H", binascii.crc_hqx(payload, 0))


async def sync_once(zone_name, *, address=KNOB_ADDRESS, adapter="hci0", device=None):
    """Deliver one clock update and close the connection, returning sent time.

    Firmware's clock acknowledgment travels to its Bluetooth Mesh router rather
    than back to this GATT notification. We require the identity reply and
    acknowledged writes, and do not wait for a nonexistent GATT clock reply.
    """
    if address.upper() != KNOB_ADDRESS:
        raise ValueError("Only the verified S Knob is accepted")
    ZoneInfo(zone_name)
    if device is None:
        device = await BleakScanner.find_device_by_address(address, timeout=20, adapter=adapter)
    if device is None:
        raise RuntimeError("Knob not found")
    async with BleakClient(device, timeout=20) as client:
        char = client.services.get_characteristic(DISPLAY_CHARACTERISTIC)
        if char is None:
            raise RuntimeError("Verified display UART is missing")
        queue = asyncio.Queue()
        await client.start_notify(char, lambda _, data: queue.put_nowait(bytes(data)))
        identity = hashlib.md5(bytes.fromhex(address.replace(":", ""))[::-1] + b"YEELIGHT").digest()
        await client.write_gatt_char(char, b"\x01" + identity, response=True)
        if await asyncio.wait_for(queue.get(), 5) != b"\x01\x00":
            raise RuntimeError("Display identity handshake failed")
        now = datetime.now(timezone.utc)
        packet = clock_packet(zone_name, now=now)
        # All 19 clock bytes plus final ff alignment padding fit one default-MTU
        # write. This is the same packet tested on the user's physical knob.
        await client.write_gatt_char(char, packet + b"\xff", response=True)
        await asyncio.sleep(0.2)
        await client.stop_notify(char)
        return now.astimezone(ZoneInfo(zone_name)).isoformat(timespec="seconds")


async def run_clock_sync(options, stopped, *, lock, suppress_activity, find_device=None):
    """Sync at startup/hourly, retry missed devices, and suppress our own traffic.

    ``lock`` is a shared asyncio lock for local knob GATT operations.
    ``suppress_activity(seconds)`` must replace the suppression deadline, so the
    final five-second grace shortens the initial timeout covering connection.
    The callback is synchronous and invoked on the bridge's event loop.
    """
    if not options.get("clock_sync_enabled", False):
        return
    zone_name = options.get("timezone", "Asia/Bangkok")
    ZoneInfo(zone_name)
    interval = int(options.get("clock_sync_interval", 3600))
    if not 300 <= interval <= 86400:
        raise ValueError("Clock sync interval must be between 300 and 86400 seconds")
    address = options.get("address", KNOB_ADDRESS).upper()
    adapter = options.get("adapter", "hci0")
    if address != KNOB_ADDRESS:
        raise ValueError("Clock sync is only supported for the verified S Knob")
    while not stopped.is_set():
        delay = interval
        async with lock:
            suppress_activity(80)
            try:
                kwargs = {"device": await find_device(address)} if find_device else {}
                sent = await asyncio.wait_for(
                    sync_once(zone_name, address=address, adapter=adapter, **kwargs), timeout=50)
                print("Knob clock synchronized: " + sent, flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Bleak error bodies may include low-level details. Log the
                # category only; the next retry needs no cloud intervention.
                print("Knob clock sync will retry (" + type(error).__name__ + ": " + str(getattr(error, "dbus_error", "")) + ")", flush=True)
                delay = 300
            finally:
                suppress_activity(5)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=delay)
        except TimeoutError:
            pass
