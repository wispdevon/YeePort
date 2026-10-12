"""Authenticated, narrowly validated S Knob light command decoding."""
from dataclasses import dataclass

from mesh_crypto import decrypt_network, decrypt_unsegmented_access

VENDOR_OPCODE = bytes((0xc1, 0x64, 0x01))


@dataclass(frozen=True)
class LightCommand:
    kind: str
    value: int | bool | tuple[int, int, int]
    slot: int
    source: int
    sequence: int


def decode_light_command(packet, *, net_key, app_key, device_key, iv_index,
                         source_address, slot=3):
    """Return an absolute brightness or power command after both MIC checks.

    Raw advertisements must also be filtered by the known physical BLE MAC by
    the caller. Destination binding and replay rejection belong to that caller.
    """
    message = decrypt_network(packet, net_key, iv_index)
    if message.control or message.source != source_address:
        return None
    plain = decrypt_unsegmented_access(message, iv_index, app_key=app_key,
                                       device_key=device_key)
    if plain[:3] != VENDOR_OPCODE:
        return None
    payload = plain[3:]
    if not payload or payload[0] != slot:
        return None
    if len(payload) == 6 and payload[1:5] == bytes((1, 0, 0, 0)) and payload[5] <= 100:
        return LightCommand("brightness", payload[5], slot, message.source, message.sequence)
    # ESP 4200df84: selector 2 sends big-endian Kelvin, selector 3 RGB.
    if len(payload) == 7 and payload[1:5] == bytes((2, 0, 0, 0)):
        kelvin = int.from_bytes(payload[5:7], "big")
        if 1000 <= kelvin <= 20000:
            return LightCommand("color_temperature", kelvin, slot, message.source, message.sequence)
    if len(payload) == 8 and payload[1:5] == bytes((3, 0, 0, 0)):
        return LightCommand("color", tuple(payload[5:8]), slot, message.source, message.sequence)
    if (len(payload) == 8 and payload[1:5] == bytes(4) and payload[5] in (0, 1)
            and payload[6:] == bytes(2)):
        return LightCommand("power", bool(payload[5]), slot, message.source, message.sequence)
    return None
