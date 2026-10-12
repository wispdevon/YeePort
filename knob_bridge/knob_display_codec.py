"""Yeelight Pro display label image codec, recovered from its 1.33.0 APK.

This module only constructs packets. It does not send them. Types 1 and 2 are
scene/device label images. APK PanelInfoBean groups type-4 buttons as devices;
the two built-in relays therefore use type 2 with zero-based display ordering.
"""

import binascii
import hashlib
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = bytes.fromhex("f0f1f2f3020a00")


def label_packet(png: bytes, *, image_type: int, index: int, device_key: bytes) -> bytes:
    if image_type not in (1, 2):
        raise ValueError("Only verified scene/device label image types are accepted")
    if not 0 <= index < 16 or len(device_key) != 16:
        raise ValueError("Invalid label index or device key")
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or not 0 < len(png) <= 60000:
        raise ValueError("A bounded vendor-rendered PNG is required")
    plain = bytes((image_type, index, 0)) + png
    plain += bytes((-len(plain)) % 16)
    header = MAGIC + struct.pack("<HH", index, len(plain))
    iv = header + bytes(5)
    key = hashlib.md5(device_key + b"GATTDATA").digest()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(plain) + encryptor.finalize()
    return header + encrypted + struct.pack("<H", binascii.crc_hqx(encrypted, 0))
