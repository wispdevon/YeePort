"""Decode the APK's single-packet configuration format in memory only."""

import json

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def decode_config(packet, key):
    if len(packet) < 39 or packet[:2] != b"\x05\x02":
        raise ValueError("Unsupported configuration packet")
    if packet[2:5] != b"\x00\x01\x01":
        raise ValueError("Fragmented configuration is not implemented")
    ciphertext = packet[23:]
    if len(ciphertext) % 16:
        raise ValueError("Invalid encrypted configuration length")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(packet[7:23])).decryptor()
    plaintext = (decryptor.update(ciphertext) + decryptor.finalize()).rstrip(b"\x00")
    if len(plaintext) != int.from_bytes(packet[5:7], "big"):
        raise ValueError("Configuration length does not match declared length")
    try:
        config = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Exception text may contain credentials; replace it entirely.
        raise ValueError("Configuration is not valid JSON") from None
    if not isinstance(config, dict) or config.get("method") != "config_device":
        raise ValueError("Unsupported configuration method")
    return config
