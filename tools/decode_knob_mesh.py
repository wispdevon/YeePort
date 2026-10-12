"""Offline network + unsegmented access decryption into a private JSONL file.

Requires recovered real keys. Every access payload must pass both MICs. This
tool does not transmit BLE or invoke any Home Assistant action.
"""
import argparse
import json
import os
from collections import Counter
from pathlib import Path

from cryptography.exceptions import InvalidTag
from analyze_mesh_capture import ad_structures
from mesh_crypto import decrypt_network, decrypt_unsegmented_access
from recover_knob_mesh_keys import ADDRESS


def access_opcode(plain):
    if not plain or plain[0] == 0x7f:
        raise ValueError("Invalid access opcode")
    if plain[0] < 0x80:
        return {"format": "sig", "opcode": plain[0], "parameters": plain[1:].hex()}
    if plain[0] < 0xc0:
        if len(plain) < 2:
            raise ValueError("Truncated SIG opcode")
        return {"format": "sig", "opcode": int.from_bytes(plain[:2], "big"),
                "parameters": plain[2:].hex()}
    if len(plain) < 3:
        raise ValueError("Truncated vendor opcode")
    return {"format": "vendor", "opcode": plain[0],
            "company_id": int.from_bytes(plain[1:3], "little"),
            "parameters": plain[3:].hex()}


def decode(keys_path, capture_path, output_path):
    keys = json.loads(Path(keys_path).read_text())
    if keys["address"].upper() != ADDRESS:
        raise ValueError("Key file device mismatch")
    net_key = bytes.fromhex(keys["net_key"])
    app_key = bytes.fromhex(keys["app_key"])
    device_key = bytes.fromhex(keys["device_key"])
    iv_index = keys["iv_index"]
    seen, counts = set(), Counter()
    output_fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(output_fd, "w") as output:
        for line in Path(capture_path).read_text().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("address", "").upper() != ADDRESS:
                continue
            if "fields" in record:
                packets = [bytes.fromhex(f["data"]) for f in record["fields"] if f["type"] == 0x2a]
            else:
                packets = [p for kind, p in ad_structures(bytes.fromhex(record.get("data", "")))
                           if kind == 0x2a]
            for packet in packets:
                if packet in seen:
                    continue
                seen.add(packet)
                try:
                    message = decrypt_network(packet, net_key, iv_index)
                except (ValueError, InvalidTag):
                    counts["network_rejected"] += 1
                    continue
                counts["network_authenticated"] += 1
                decoded = {"time": record.get("timestamp", record.get("time")),
                           "source": message.source, "destination": message.destination,
                           "sequence": message.sequence, "control": message.control,
                           "network_mic_verified": True, "access_mic_verified": False,
                           "lower_transport": message.lower_transport.hex()}
                if not message.control:
                    try:
                        plain = decrypt_unsegmented_access(message, iv_index,
                                                           app_key=app_key, device_key=device_key)
                        decoded.update(access_opcode(plain))
                        decoded["access_mic_verified"] = True
                        counts["access_authenticated"] += 1
                    except (ValueError, InvalidTag) as exc:
                        decoded["access_error"] = str(exc)
                        counts["access_unresolved"] += 1
                else:
                    counts["control_messages"] += 1
                output.write(json.dumps(decoded) + "\n")
    print(json.dumps({"unique_packets": len(seen), **counts, "device_contacted": False}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("keys", "capture", "output"):
        p.add_argument("--" + option, required=True, type=Path)
    a = p.parse_args()
    decode(a.keys, a.capture, a.output)
