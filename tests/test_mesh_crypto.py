"""Published Bluetooth Mesh vectors, independently of YeeGate packet builders.

Source: https://github.com/bluez/bluez/blob/master/unit/test-mesh-crypto.c
Mesh Profile sections 8.2.2, 8.2.3, 8.3.1 and 8.3.6.
All keys below are public specification vectors, not device credentials.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cryptography.exceptions import InvalidTag
from mesh_crypto import network_keys, decrypt_network, application_id, decrypt_unsegmented_access

KEY = bytes.fromhex("7dd7364cd842ad18c17c2b820c84c3d6")


class MeshCryptoVectors(unittest.TestCase):
    def test_application_virtual_address_vector(self):
        app_key = bytes.fromhex("63964771734fbd76e3b40519d1d94a48")
        self.assertEqual(application_id(app_key), 0x26)
        packet = bytes.fromhex("e8d85caecef1e3ed31f3fdcf88a411135fea55df730b6b28e255")
        message = decrypt_network(packet, KEY, 0x12345677)
        uuid = bytes.fromhex("0073e7e4d8b9440faf8415df4c56c0e1")
        plain = decrypt_unsegmented_access(message, 0x12345677, app_key=app_key, label_uuid=uuid)
        self.assertEqual(plain.hex(), "d50a0048656c6c6f")
        with self.assertRaises(InvalidTag):
            decrypt_unsegmented_access(message, 0x12345676, app_key=app_key, label_uuid=uuid)
        with self.assertRaises(ValueError):
            decrypt_unsegmented_access(message, 0x12345677, app_key=app_key)

    def test_flooding_and_friendship_derivation(self):
        nid, enc, privacy = network_keys(KEY)
        self.assertEqual(nid, 0x68)
        self.assertEqual(enc.hex(), "0953fa93e7caac9638f58820220a398e")
        self.assertEqual(privacy.hex(), "8b84eedec100067d670971dd2aa700cf")
        nid, enc, privacy = network_keys(KEY, bytes.fromhex("01120123450000072f"))
        self.assertEqual(nid, 0x5e)
        self.assertEqual(enc.hex(), "be635105434859f484fc798e043ce40e")
        self.assertEqual(privacy.hex(), "5d396d4b54d3cbafe943e051fe9a4eb8")

    def test_control_network_message(self):
        packet = bytes.fromhex("68eca487516765b5e5bfdacbaf6cb7fb6bff871f035444ce83a670df")
        result = decrypt_network(packet, KEY, 0x12345678)
        self.assertEqual((result.control, result.ttl, result.sequence,
                          result.source, result.destination), (True, 0, 1, 0x1201, 0xfffd))
        self.assertEqual(result.lower_transport.hex(), "034b50057e400000010000")

    def test_segmented_access_network_message(self):
        packet = bytes.fromhex("68cab5c5348a230afba8c63d4e686364979deaf4fd40961145939cda0e")
        result = decrypt_network(packet, KEY, 0x12345678)
        self.assertEqual((result.control, result.ttl, result.sequence,
                          result.source, result.destination), (False, 4, 0x3129ab, 3, 0x1201))
        self.assertEqual(result.lower_transport.hex(), "8026ac01ee9dddfd2169326d23f3afdf")
        with self.assertRaises(InvalidTag):
            decrypt_network(packet[:-1] + bytes((packet[-1] ^ 1,)), KEY, 0x12345678)


if __name__ == "__main__":
    unittest.main()
