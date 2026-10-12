"""Prepare an OFFLINE ANALYSIS candidate; never flash or upload firmware.

Only the exact MD5-verified official S Knob 1.4.25 image is accepted. The outer
container validation and hardware rollback remain unverified. The output is
deliberately named .analysis.bin and must not be used as an OTA update.
"""
import argparse
import binascii
import hashlib
import json
import struct
from pathlib import Path

OFFICIAL_SHA256 = "6ac92c8095206498b1762b6fdd2669148caed9d18b2c08a3b0eaef92c52fddd5"
ESP_START = 0x250018
LANGUAGE_OFFSET = 0x257E84


def esp_integrity(blob):
    if blob[ESP_START] != 0xE9 or blob[ESP_START + 23] != 1:
        raise ValueError("Unexpected ESP image header")
    cursor = ESP_START + 24
    checksum = 0xEF
    for _ in range(blob[ESP_START + 1]):
        _, length = struct.unpack_from("<II", blob, cursor)
        cursor += 8
        if cursor + length > len(blob):
            raise ValueError("Malformed ESP segment")
        for value in blob[cursor:cursor + length]:
            checksum ^= value
        cursor += length
    checksum_offset = ESP_START + ((cursor - ESP_START + 16) // 16) * 16 - 1
    digest_offset = checksum_offset + 1
    digest = hashlib.sha256(blob[ESP_START:digest_offset]).digest()
    return checksum_offset, checksum, digest_offset, digest


def prepare(source, output):
    original = Path(source).read_bytes()
    if hashlib.sha256(original).hexdigest() != OFFICIAL_SHA256:
        raise ValueError("Input is not the verified official 1.4.25 image")
    if original[LANGUAGE_OFFSET:LANGUAGE_OFFSET + 3] != b"zh\x00":
        raise ValueError("Expected language literal is missing")
    checksum_offset, checksum, digest_offset, digest = esp_integrity(original)
    if original[checksum_offset] != checksum or original[digest_offset:digest_offset + 32] != digest:
        raise ValueError("Official ESP integrity check failed")
    candidate = bytearray(original)
    candidate[LANGUAGE_OFFSET:LANGUAGE_OFFSET + 2] = b"en"
    _, checksum, _, _ = esp_integrity(candidate)
    candidate[checksum_offset] = checksum
    _, _, _, digest = esp_integrity(candidate)
    candidate[digest_offset:digest_offset + 32] = digest
    check_at, expected, sha_at, expected_sha = esp_integrity(candidate)
    assert candidate[check_at] == expected
    assert candidate[sha_at:sha_at + 32] == expected_sha
    allowed = {LANGUAGE_OFFSET, LANGUAGE_OFFSET + 1, checksum_offset}
    allowed.update(range(digest_offset, digest_offset + 32))
    changes = [i for i, (a, b) in enumerate(zip(original, candidate)) if a != b]
    assert set(changes) <= allowed
    destination = Path(output)
    if not destination.name.endswith(".analysis.bin"):
        raise ValueError("Output must end with .analysis.bin")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(candidate)
    manifest = {
        "purpose": "offline analysis only; OTA acceptance and rollback unverified",
        "official_version": "1.4.25", "input_sha256": OFFICIAL_SHA256,
        "output_sha256": hashlib.sha256(candidate).hexdigest(),
        "image_size": len(candidate), "changed_bytes": len(changes),
        "changed_offsets": [hex(i) for i in changes],
        "language_literal": {"offset": hex(LANGUAGE_OFFSET), "before": "zh", "after": "en"},
        "esp_checksum_offset": hex(checksum_offset),
        "esp_sha256_offset": hex(digest_offset),
        "esp_integrity_valid": True,
        "outer_container_integrity_verified": False,
        "ota_acceptance_verified": False, "hardware_rollback_verified": False,
        "bg21_image_unchanged": candidate[0x350F98:] == original[0x350F98:],
        "device_written": False,
    }
    destination.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    # A native ESP image is a separate offline artifact. No transport or OTA
    # code exists in this tool; extraction does not establish device acceptance.
    esp_end = digest_offset + 32
    native = bytes(candidate[ESP_START:esp_end])
    reference = original[ESP_START:esp_end]
    native_path = destination.with_name(destination.name.replace(".analysis.bin", ".esp.analysis.bin"))
    reference_path = destination.with_name(destination.name.replace(".analysis.bin", ".esp.official-reference.bin"))
    native_path.write_bytes(native)
    reference_path.write_bytes(reference)
    native_manifest = dict(manifest)
    native_manifest.update({
        "image_format": "native ESP32-S3 application image; offline analysis only",
        "image_size": len(native), "output_sha256": hashlib.sha256(native).hexdigest(),
        "reference_sha256": hashlib.sha256(reference).hexdigest(),
        "changed_offsets": [hex(i - ESP_START) for i in changes],
        "esp_checksum_offset": hex(checksum_offset - ESP_START),
        "esp_sha256_offset": hex(digest_offset - ESP_START),
        "language_literal": {"offset": hex(LANGUAGE_OFFSET - ESP_START), "before": "zh", "after": "en"},
        "ucp_transfer_crc32_raw_ieee": hex(binascii.crc32(native) ^ 0xFFFFFFFF),
        "ucp_transfer_crc32_reference": hex(binascii.crc32(reference) ^ 0xFFFFFFFF),
        "reference_is_verified_hardware_rollback": False,
    })
    native_path.with_suffix(".json").write_text(json.dumps(native_manifest, indent=2) + "\n")
    print(json.dumps({"artifact": str(destination), "changed_bytes": len(changes),
                      "native_artifact": str(native_path),
                      "esp_integrity_valid": True, "device_written": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    prepare(args.source, args.output)
