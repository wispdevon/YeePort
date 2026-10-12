"""Read the authenticated diagnostic export and validate Mesh keys privately.

Requires the diagnostic BG21 image already running. Sends authentication only;
no OTA control, firmware data, reset, or provisioning commands.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path

from bleak import BleakClient, BleakScanner
from probe_knob_ota import ADDRESS, authenticate
from recover_knob_mesh_keys import captured_packets, recover


def private_create(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


async def read_secret(config_path, binding_path, capture_path, secret_output, keys_output):
    config = json.loads(Path(config_path).read_text())
    if config["address"].upper() != ADDRESS:
        raise ValueError("Device mismatch")
    if Path(secret_output).exists() or Path(keys_output).exists():
        raise ValueError("Refusing to overwrite existing private credentials")
    device_key = bytes.fromhex(config["device_key"])
    blob = base64.b64decode(json.loads(Path(binding_path).read_text())["data"]["encryptResult"], validate=True)
    packets = captured_packets(capture_path)
    received = []
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20)
    if device is None:
        raise RuntimeError("Knob not found")
    async with BleakClient(device, timeout=20) as client:
        await client._backend._acquire_mtu()
        await authenticate(client, device_key, secret_receiver=received.append)
    secret = received[0]
    private_create(secret_output, secret)
    keys = recover(blob, secret, device_key, packets)
    private_create(keys_output, (json.dumps(keys, indent=2) + "\n").encode())
    print(json.dumps({"factory_secret_received": True, "keys_recovered": True,
                      "authenticated_network_packets": keys["authenticated_packets"],
                      "application_mic_verified": False, "firmware_bytes_sent": 0}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("config", "binding", "capture", "secret-output", "keys-output"):
        p.add_argument("--" + option, required=True, type=Path)
    a = p.parse_args()
    asyncio.run(read_secret(a.config, a.binding, a.capture, a.secret_output, a.keys_output))
