"""Authenticate the official OTA service only; sends no control or image data."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

AUTH = "b35e3d49-12b2-4346-9912-0c7f5eb9bbc8"
CONTROL = "f7bf3564-fb6d-4e53-88a4-5e37e0326063"
DATA = "984227f3-34fc-4045-a5d0-2c581f81a153"
ADDRESS = "F8:24:41:39:9F:38"


async def authenticate(client, device_key, *, secret_receiver=None, require_export=True):
    queue = asyncio.Queue()
    await client.start_notify(AUTH, lambda _, value: queue.put_nowait(bytes(value)))
    try:
        await client.write_gatt_char(AUTH, bytes.fromhex("07000164"), response=False)
        try:
            challenge = await asyncio.wait_for(queue.get(), 3)
        except TimeoutError:
            # A pending state-1 challenge is cleared by this same request. The
            # following request creates a fresh challenge; no OTA control write.
            await client.write_gatt_char(AUTH, bytes.fromhex("07000164"), response=False)
            challenge = await asyncio.wait_for(queue.get(), 10)
        if len(challenge) != 130 or challenge[:2] != b"\x07\x01":
            raise ValueError(f"Unexpected OTA challenge type/length: {challenge[:2].hex()}/{len(challenge)}")
        key = hashlib.md5(device_key + b"MESHOTA").digest()
        iv = os.urandom(16)
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        packet = b"\x07\x02" + iv + enc.update(challenge[2:]) + enc.finalize()
        if client.mtu_size - 3 < len(packet):
            raise ValueError("Negotiated ATT payload is too small for atomic OTA authentication")
        await client.write_gatt_char(AUTH, packet, response=False)
        result = await asyncio.wait_for(queue.get(), 15)
        if result != bytes.fromhex("07030164"):
            raise ValueError(f"OTA authentication rejected: {result.hex()}")
        if secret_receiver is not None:
            try:
                export = await asyncio.wait_for(queue.get(), 5)
            except TimeoutError:
                if not require_export:
                    return True
                raise
            if len(export) != 18 or export[:2] != b"\x07\x04":
                raise ValueError("Expected authenticated factory-secret export is missing")
            secret_receiver(export[2:])
        return True
    finally:
        if client.is_connected:
            await client.stop_notify(AUTH)


async def probe(config_path, verify_stock=False):
    config = json.loads(Path(config_path).read_text())
    if config["address"].upper() != ADDRESS:
        raise ValueError("Only the configured S Knob is allowed")
    key = bytes.fromhex(config["device_key"])
    if len(key) != 16:
        raise ValueError("Invalid device key")
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20)
    if device is None:
        raise RuntimeError("Knob not found")
    async with BleakClient(device, timeout=20) as client:
        if any(client.services.get_characteristic(uuid) is None for uuid in (AUTH, CONTROL, DATA)):
            raise ValueError("Official OTA service characteristics are missing")
        # BlueZ's public mtu_size can stay at 23 until AcquireWrite negotiates it.
        acquire = getattr(client._backend, "_acquire_mtu", None)
        if acquire is not None:
            await acquire()
        print(json.dumps({"stage": "connected", "mtu": client.mtu_size,
                          "auth_payload_limit": client.services.get_characteristic(AUTH).max_write_without_response_size}), flush=True)
        for _ in range(50):
            if client.services.get_characteristic(AUTH).max_write_without_response_size >= 146:
                break
            await asyncio.sleep(.1)
        exports = []
        authenticated = await authenticate(client, key,
                            secret_receiver=(lambda _: exports.append(True)) if verify_stock else None,
                            require_export=not verify_stock)
        result = {"stage": "ota_auth", "authenticated": authenticated,
                  "firmware_bytes_sent": 0, "control_commands_sent": 0}
        if verify_stock:
            result["diagnostic_export_seen"] = bool(exports)
            result["stock_behavior_verified"] = not exports
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private label deployment JSON")
    parser.add_argument("--verify-stock", action="store_true", help="Confirm no diagnostic export after valid authentication")
    args = parser.parse_args()
    asyncio.run(probe(args.config, args.verify_stock))
