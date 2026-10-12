"""Raw Mesh activity extraction. Packet contents remain encrypted."""

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import struct


def reports(packet):
    if len(packet) < 4 or packet[0] != 0x3E or packet[2] not in (2, 13):
        return
    subtype, count, offset = packet[2], packet[3], 4
    for _ in range(count):
        fixed = 9 if subtype == 2 else 24
        if offset + fixed > len(packet):
            return
        report = packet[offset:]
        start = 2 if subtype == 2 else 3
        address = ":".join(f"{v:02X}" for v in reversed(report[start:start + 6]))
        size = report[fixed - 1]
        end = offset + fixed + size
        if end > len(packet) or (subtype == 2 and end >= len(packet)):
            return
        rssi = struct.unpack("b", packet[end:end + 1] if subtype == 2 else report[13:14])[0]
        yield address, rssi, packet[offset + fixed:end]
        offset = end + (1 if subtype == 2 else 0)


def fields(data):
    offset = 0
    while offset < len(data):
        size = data[offset]
        if not size or offset + size + 1 > len(data):
            return
        yield data[offset + 1], data[offset + 2:offset + size + 1]
        offset += size + 1


class Activity:
    def __init__(self, address, deduplicate_seconds=30):
        self.address = address.upper()
        self.window = deduplicate_seconds
        self.seen = OrderedDict()

    def receive(self, address, rssi, data, now):
        if address.upper() != self.address:
            return
        while self.seen and next(iter(self.seen.values())) <= now - self.window:
            self.seen.popitem(last=False)
        for kind, payload in fields(data):
            if kind != 0x2A or len(payload) < 14:
                continue
            if payload in self.seen:
                continue
            self.seen[payload] = now
            if len(self.seen) > 2048:
                self.seen.popitem(last=False)
            yield {"event_type": "mesh_activity", "address": self.address,
                   "packet_id": hashlib.sha256(payload).hexdigest()[:16],
                   "packet_length": len(payload), "rssi": rssi,
                   "timestamp": datetime.now(timezone.utc).isoformat()}
