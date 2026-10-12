"""Extract raw Bluetooth Mesh advertisements from BlueZ btmon captures."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import struct

MESH_TYPES = {0x29: "provisioning", 0x2A: "network", 0x2B: "beacon"}
EPOCH_OFFSET = 0x00DCDDB30F2F8000


def advertising_reports(packet):
    if len(packet) < 4 or packet[0] != 0x3E:
        return
    subtype, count, offset = packet[2], packet[3], 4
    if subtype not in (0x02, 0x0D):
        return
    for _ in range(count):
        fixed = 9 if subtype == 0x02 else 24
        if offset + fixed > len(packet):
            return
        report = packet[offset:]
        start = 2 if subtype == 0x02 else 3
        address = ":".join(f"{b:02X}" for b in reversed(report[start:start + 6]))
        length = report[fixed - 1]
        end = offset + fixed + length
        if end > len(packet) or (subtype == 0x02 and end >= len(packet)):
            return
        rssi = struct.unpack("b", packet[end:end + 1] if subtype == 0x02
                             else report[13:14])[0]
        yield address, rssi, packet[offset + fixed:end]
        offset = end + (1 if subtype == 0x02 else 0)


def ad_structures(data):
    offset = 0
    while offset < len(data):
        length = data[offset]
        if not length or offset + length + 1 > len(data):
            return
        yield data[offset + 1], data[offset + 2:offset + length + 1]
        offset += length + 1


def extract(path, address, all_mesh=False):
    with path.open("rb") as stream:
        header = stream.read(16)
        if len(header) != 16 or header[:8] != b"btsnoop\0" or struct.unpack(">II", header[8:]) != (1, 2001):
            raise ValueError("Expected BlueZ monitor btsnoop format")
        while metadata := stream.read(24):
            if len(metadata) != 24:
                raise ValueError("Truncated btsnoop record header")
            original, included, flags, drops, timestamp = struct.unpack(">IIIIQ", metadata)
            packet = stream.read(included)
            if len(packet) != included:
                raise ValueError("Truncated btsnoop packet")
            if flags & 0xFFFF != 3:
                continue
            for peer, rssi, data in advertising_reports(packet):
                fields = [{"kind": MESH_TYPES.get(kind, f"ad_{kind:02x}"),
                           "type": kind, "data": payload.hex()}
                          for kind, payload in ad_structures(data)]
                if peer != address and not (all_mesh and any(f["type"] in MESH_TYPES for f in fields)):
                    continue
                yield {"time": datetime.fromtimestamp((timestamp - EPOCH_OFFSET) / 1e6,
                                                       timezone.utc).isoformat(),
                       "address": peer, "rssi": rssi, "fields": fields}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--address", default="F8:24:41:39:9F:38")
    parser.add_argument("--all-mesh", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("knob-raw-advertisements.jsonl"))
    args = parser.parse_args()
    count = mesh = 0
    with args.output.open("w") as stream:
        for record in extract(args.capture, args.address.upper(), args.all_mesh):
            stream.write(json.dumps(record) + "\n")
            count += 1
            mesh += sum(field["type"] in MESH_TYPES for field in record["fields"])
    print(f"Saved {count} advertisements containing {mesh} Mesh fields to {args.output}")
