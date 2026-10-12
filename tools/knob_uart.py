"""Passive parser for S Knob display-to-Bluetooth plaintext UART commands.

Recovered v1.4.25 path: 420214d8 -> 4200e424 -> 4200de00 -> 42026038.
No hardware capture has verified this codec yet. It does not write serial data.
"""
import binascii
import struct

MAGIC = bytes.fromhex("f0f1f2f3")


class KnobUartParser:
    def __init__(self, slot=3):
        if not 1 <= slot <= 8:
            raise ValueError("Expected light slot must be 1–8")
        self.slot = slot
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        events = []
        while True:
            start = self.buffer.find(MAGIC)
            if start < 0:
                self.buffer[:] = self.buffer[-3:]
                break
            del self.buffer[:start]
            if len(self.buffer) < 11:
                break
            size = struct.unpack_from("<H", self.buffer, 9)[0]
            if size > 255:
                del self.buffer[0]
                continue
            total = size + 13
            if len(self.buffer) < total:
                break
            frame = bytes(self.buffer[:total])
            payload = frame[11:-2]
            if struct.unpack_from("<H", frame, total - 2)[0] != binascii.crc_hqx(payload, 0):
                del self.buffer[0]
                continue
            del self.buffer[:total]
            if frame[4:7] != bytes((1, 1, 0)) or size not in (6, 8):
                continue
            if payload[0] != self.slot or payload[2:5] != bytes(3):
                continue
            common = {"slot": self.slot, "sequence": struct.unpack_from("<H", frame, 7)[0]}
            if size == 6 and payload[1] == 1 and payload[5] <= 100:
                events.append({**common, "event_type": "brightness",
                               "brightness_pct": payload[5]})
            elif (size == 8 and payload[1] == 0 and payload[5] in (0, 1)
                  and payload[6:] == bytes(2)):
                events.append({**common, "event_type": "power", "power": bool(payload[5])})
        return events
