"""Offline recovery of S Knob Mesh keys from its saved binding response.

Requires the real per-unit factory secret or a raw BG21 user-page read. Never
contacts the device, changes provisioning, or prints recovered key values.
Known device-key comparison and real network MICs are required before export.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from analyze_mesh_capture import ad_structures
from mesh_crypto import decrypt_network, network_keys

ADDRESS = "F8:24:41:39:9F:38"


def captured_packets(path):
    packets = set()
    for line in Path(path).read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("address", "").upper() != ADDRESS:
            continue
        if "fields" in record:
            packets.update(bytes.fromhex(f["data"]) for f in record["fields"] if f["type"] == 0x2a)
        elif "data" in record:
            packets.update(payload for kind, payload in ad_structures(bytes.fromhex(record["data"]))
                           if kind == 0x2a)
    return sorted(packets)


def decode_binding(blob, secret, expected_device_key):
    if len(blob) != 160 or len(secret) != 16 or len(expected_device_key) != 16:
        raise ValueError("Unexpected binding/secret/device-key size")
    key = hashlib.md5(secret + b"YEEMESH").digest()
    dec = Cipher(algorithms.AES(key), modes.CBC(blob[:16])).decryptor()
    plain = dec.update(blob[16:]) + dec.finalize()
    # BG21 0x13a8c passes DeviceKey first and NetKey second to provisioning;
    # its app-key command takes the third key. Addresses use big-endian bytes.
    # The vendor handler skips byte zero; this unit's real binding uses 0.
    # Do not invent a marker check. Known DeviceKey plus real network MICs
    # below provide the acceptance evidence.
    if plain[17:33] != expected_device_key:
        raise ValueError("Factory secret does not match the saved binding and known device key")
    net_key, app_key = plain[1:17], plain[33:49]
    iv_index = int.from_bytes(plain[49:53], "little")
    address = int.from_bytes(plain[53:55], "big")
    if not 1 <= address <= 0x7fff:
        raise ValueError("Invalid provisioning unicast address")
    return net_key, app_key, iv_index, address


def recover(blob, secret, expected_device_key, packets):
    net_key, app_key, iv_index, address = decode_binding(blob, secret, expected_device_key)
    authenticated = []
    for packet in packets:
        try:
            message = decrypt_network(packet, net_key, iv_index)
        except (ValueError, InvalidTag):
            continue
        authenticated.append(message)
    # Distinct capture packets with valid network MICs, including this node's
    # unicast source, establish a real match beyond CBC marker plausibility.
    if len(authenticated) < 3 or not any(m.source == address for m in authenticated):
        raise ValueError("Binding keys did not authenticate at least three real knob packets")
    return {"address": ADDRESS, "net_key": net_key.hex(), "app_key": app_key.hex(),
            "device_key": expected_device_key.hex(), "iv_index": iv_index,
            "unicast_address": address, "nid": network_keys(net_key)[0],
            "authenticated_packets": len(authenticated),
            "application_mic_verified": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binding", required=True, type=Path)
    p.add_argument("--device-config", required=True, type=Path)
    p.add_argument("--capture", required=True, type=Path)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--factory-secret", type=Path, help="Exactly 16 raw binary bytes")
    group.add_argument("--user-page", type=Path, help="Raw 32+ byte read starting at BG21 0x0fe00000")
    p.add_argument("--output", type=Path, help="Private, newly created key JSON; never overwritten")
    args = p.parse_args()
    config = json.loads(args.device_config.read_text())
    if config["address"].upper() != ADDRESS:
        raise ValueError("Device configuration mismatch")
    blob = base64.b64decode(json.loads(args.binding.read_text())["data"]["encryptResult"], validate=True)
    packets = captured_packets(args.capture)
    summary = {"binding_bytes": len(blob), "unique_network_packets": len(packets),
               "observed_nids": sorted({packet[0] & 0x7f for packet in packets}),
               "device_contacted": False}
    if args.factory_secret is None and args.user_page is None:
        print(json.dumps({**summary, "factory_secret_available": False,
                          "keys_recovered": False}))
        return
    if args.output is None:
        raise ValueError("Recovery requires --output; secret values are never printed")
    if args.user_page is not None:
        page = args.user_page.read_bytes()
        if len(page) < 32:
            raise ValueError("A complete 32-byte factory-page read is required")
        secret = page[14:30]
    else:
        secret = args.factory_secret.read_bytes()
    result = recover(blob, secret, bytes.fromhex(config["device_key"]), packets)
    # Exclusive creation with mode 0600, preserving existing credentials.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({**summary, "keys_recovered": True,
                      "authenticated_packets": result["authenticated_packets"],
                      "application_mic_verified": False}))


if __name__ == "__main__":
    main()
