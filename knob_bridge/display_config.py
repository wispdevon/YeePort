"""Bounded S Knob device-menu configuration recovered from firmware 1.4.25.

This configures display entries, not destination Mesh bindings. No firmware,
provisioning, factory settings, or relay output commands are constructed.
"""
import binascii
import struct
from light_imports import CONTROL_TYPES


def device_entry_packet(*, version, total, slot, name, ptype, component=1,
                        node_type=2, icon=7, hidden=False, open_type=0,
                        room='', sequence=1):
    if not 1 <= total <= 8 or not 1 <= slot <= total:
        raise ValueError('Only eight bounded, one-based display entries are supported')
    if not all(isinstance(v, int) and 0 <= v <= 255
               for v in (version, ptype, component, node_type, icon, open_type)):
        raise ValueError('Display metadata must fit one byte')
    if not 0 <= sequence <= 65535:
        raise ValueError('Invalid sequence')
    title, area = name.encode('utf-8'), room.encode('utf-8')
    if not 1 <= len(title) <= 32 or len(area) > 32 or b'\0' in title + area:
        raise ValueError('Display names must fit bounded, NUL-free firmware buffers')
    # Wire byte is 'visible'; firmware converts zero to its internal hide flag.
    payload = bytes((5, 7, version, total, slot, int(not hidden), icon,
                     ptype, node_type, open_type, component, len(title)))
    payload += title + bytes((len(area),)) + area
    header = bytes.fromhex('f0f1f2f3') + bytes((1, 0x1c, 0))
    header += struct.pack('<HH', sequence, len(payload))
    return header + payload + struct.pack('<H', binascii.crc_hqx(payload, 0))


def test_menu_packets(version, *, restore=False, color_controls=False, separate_controls=False,
                      ha_lights_menu=False, imported_lights=()):
    rows = [('Relay 1', 24, 1), ('Relay 2', 24, 2)]
    if not restore:
        rows.append(('RGB Lights' if separate_controls else 'HA Lights',
                     2 if separate_controls else (4 if color_controls else 2), 1))
        if separate_controls:
            rows.extend([('Warm White', 2, 1), ('Red 10%', 1, 1)])
            if ha_lights_menu:
                rows.append(('HA Lights', 4, 1))
        for row in imported_lights:
            if row['slot'] != len(rows) + 1:
                raise ValueError('Imported menu slots must follow the existing entries')
            rows.append((row['name'], CONTROL_TYPES[row['controls']], 1))
    return [device_entry_packet(version=version, total=len(rows), slot=i,
                                name=name, ptype=ptype, component=component,
                                sequence=i)
            for i, (name, ptype, component) in enumerate(rows, 1)]


def light_state_packet(*, slot=3, brightness, power, sequence=4):
    """Display-only dimmable-light state: namespace 1/op 0c, ready slot + flags.

    Firmware 420262ac -> event 17 -> 4200c2dc -> 4200d13c updates the
    configured dimmable entry's state, not a relay or destination device.
    """
    if not 1 <= slot <= 8 or type(brightness) is not int or not 0 <= brightness <= 100:
        raise ValueError('Invalid display slot or brightness percentage')
    if type(power) is not bool or not 0 <= sequence <= 65535:
        raise ValueError('Invalid power or sequence')
    payload = bytes((slot | 0x80, 3, (brightness << 1) | int(power)))
    header = bytes.fromhex('f0f1f2f3') + bytes((1, 0x0c, 0))
    header += struct.pack('<HH', sequence, len(payload))
    return header + payload + struct.pack('<H', binascii.crc_hqx(payload, 0))


def color_light_state_packet(*, power, brightness, mode, value, slot=3, sequence=4):
    """ESP 4200d25c ptype-4 state: flags 7, power/brightness, mode, value."""
    if type(power) is not bool or type(brightness) is not int or not 0 <= brightness <= 100:
        raise ValueError('Invalid light state')
    if not 1 <= slot <= 8 or not 0 <= sequence <= 65535:
        raise ValueError('Invalid display slot or sequence')
    if mode == 2 and type(value) is int and 1000 <= value <= 20000:
        color = value.to_bytes(2, 'big')
    elif mode == 1 and isinstance(value, (tuple, list)) and len(value) == 3 and all(
            type(v) is int and 0 <= v <= 255 for v in value):
        color = bytes(value)
    else:
        raise ValueError('Invalid color mode or value')
    payload = bytes((slot | 0x80, 7, (brightness << 1) | int(power), mode)) + color
    header = bytes.fromhex('f0f1f2f3') + bytes((1, 0x0c, 0)) + struct.pack('<HH', sequence, len(payload))
    return header + payload + struct.pack('<H', binascii.crc_hqx(payload, 0))
