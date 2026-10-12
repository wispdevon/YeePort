"""Authenticated Bluetooth Mesh network decoding for offline investigation.

Device keys are not network keys. This module only accepts a caller-supplied
NetKey and IV index; it never treats unauthenticated plaintext as a gesture.
Vectors: BlueZ unit/test-mesh-crypto.c, Bluetooth Mesh Profile section 8.
"""
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM


def aes_cmac(key, message):
    c = CMAC(algorithms.AES(key))
    c.update(message)
    return c.finalize()


def network_keys(net_key, p=b"\x00"):
    if len(net_key) != 16:
        raise ValueError("A 16-byte NetKey is required")
    salt = aes_cmac(bytes(16), b"smk2")
    t = aes_cmac(salt, net_key)
    t1 = aes_cmac(t, p + b"\x01")
    t2 = aes_cmac(t, t1 + p + b"\x02")
    t3 = aes_cmac(t, t2 + p + b"\x03")
    return t1[-1] & 0x7f, t2, t3


def application_id(app_key):
    if len(app_key) != 16:
        raise ValueError("A 16-byte AppKey is required")
    salt = aes_cmac(bytes(16), b"smk4")
    t = aes_cmac(salt, app_key)
    return aes_cmac(t, b"id6\x01")[-1] & 0x3f


@dataclass(frozen=True)
class NetworkMessage:
    control: bool
    ttl: int
    sequence: int
    source: int
    destination: int
    lower_transport: bytes


def decrypt_network(packet, net_key, iv_index, *, p=b"\x00"):
    if not 14 <= len(packet) <= 29 or not 0 <= iv_index <= 0xffffffff:
        raise ValueError("Invalid Mesh network packet or IV index")
    nid, encryption, privacy = network_keys(net_key, p)
    if packet[0] & 0x7f != nid or packet[0] >> 7 != iv_index & 1:
        raise InvalidTag("Network identifier or IV parity does not match")
    privacy_plain = bytes(5) + iv_index.to_bytes(4, "big") + packet[7:14]
    e = Cipher(algorithms.AES(privacy), modes.ECB()).encryptor()
    mask = e.update(privacy_plain) + e.finalize()
    header = bytes(a ^ b for a, b in zip(packet[1:7], mask))
    control = bool(header[0] & 0x80)
    nonce = b"\x00" + header + bytes(2) + iv_index.to_bytes(4, "big")
    plain = AESCCM(encryption, tag_length=8 if control else 4).decrypt(
        nonce, packet[7:], None)
    source = int.from_bytes(header[4:6], "big")
    destination = int.from_bytes(plain[:2], "big")
    if not 1 <= source <= 0x7fff or destination == 0 or len(plain) < 3:
        raise ValueError("Authenticated packet has invalid Mesh addresses or payload")
    return NetworkMessage(control, header[0] & 0x7f,
                          int.from_bytes(header[1:4], "big"), source,
                          destination, plain[2:])


def decrypt_unsegmented_access(message, iv_index, *, app_key=None,
                               device_key=None, label_uuid=None):
    """Verify upper-transport MIC and return plaintext access opcode+parameters.

    Network MIC success alone is insufficient. Segmented messages require
    reassembly and their original SeqAuth; they are explicitly rejected here.
    """
    lower = message.lower_transport
    if message.control or len(lower) < 6 or lower[0] & 0x80:
        raise ValueError("An unsegmented access message is required")
    if not 0 <= iv_index <= 0xffffffff or not 0 <= message.sequence <= 0xffffff:
        raise ValueError("Invalid IV index or sequence")
    akf = bool(lower[0] & 0x40)
    aid = lower[0] & 0x3f
    key = app_key if akf else device_key
    if key is None or len(key) != 16:
        raise ValueError("The matching AppKey or DeviceKey is required")
    if (akf and application_id(key) != aid) or (not akf and aid != 0):
        raise InvalidTag("Access key identifier does not match")
    virtual = 0x8000 <= message.destination <= 0xbfff
    if virtual:
        if label_uuid is None or len(label_uuid) != 16:
            raise ValueError("Virtual-address access requires its label UUID")
        salt = aes_cmac(bytes(16), b"vtad")
        address = 0x8000 | (int.from_bytes(aes_cmac(salt, label_uuid)[-2:], "big") & 0x3fff)
        if address != message.destination:
            raise ValueError("Label UUID does not match the virtual destination")
    elif label_uuid is not None:
        raise ValueError("Label UUID must only be supplied for a virtual destination")
    nonce = bytes((1 if akf else 2, 0)) + message.sequence.to_bytes(3, "big")
    nonce += message.source.to_bytes(2, "big") + message.destination.to_bytes(2, "big")
    nonce += iv_index.to_bytes(4, "big")
    return AESCCM(key, tag_length=4).decrypt(nonce, lower[1:], label_uuid)
