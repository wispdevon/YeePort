"""The APK-derived first stage of S20 onboarding, without enrollment."""

import hashlib

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

START = bytes.fromhex("05000164")
REPLY = bytes.fromhex("05010164")


class GatewayHandshake:
    def __init__(self):
        self.pending = bytearray()
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.aes_key = None
        self.complete = False

    def receive(self, data):
        if self.complete:
            return None
        self.pending.extend(data)
        if len(self.pending) > 68:
            raise ValueError("Unexpected initial handshake length")
        if len(self.pending) >= 4 and self.pending[:4] != START:
            raise ValueError("Unsupported initial handshake header")
        if len(self.pending) < 68:
            return None
        peer = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b"\x04" + bytes(self.pending[4:])
        )
        secret = self.private_key.exchange(ec.ECDH(), peer)
        # GatewayProvisioningDeviceEncryptConfigInfoState._hashAesKey:
        # MD5(shared ECDH secret || UTF8("YEEMESH")).
        self.aes_key = hashlib.md5(secret + b"YEEMESH").digest()
        self.complete = True
        self.pending.clear()
        public_key = self.private_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )[1:]
        return REPLY + public_key
