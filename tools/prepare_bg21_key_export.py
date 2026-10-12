"""Build an OFFLINE BG21 key-export analysis candidate; no device operations."""
import argparse
import binascii
import hashlib
import json
import struct
import subprocess
import tempfile
from pathlib import Path

OFFICIAL_SHA = "6ac92c8095206498b1762b6fdd2669148caed9d18b2c08a3b0eaef92c52fddd5"
GBL_START = 0x350f98
GBL_SHA = "63a665f822086ab494c8e2aa12b90835d37245a9f4a47d94ea57a55774050205"
APP_BASE = 0x10000
HOOK_ADDRESS = 0x48d00
PATCH_ADDRESS = 0x11f94
CRC_RESIDUE = 0x2144df1c


def tags(blob):
    position = 0
    result = []
    while position < len(blob):
        if position + 8 > len(blob):
            raise ValueError("Truncated GBL tag")
        kind, length = struct.unpack_from("<II", blob, position)
        end = position + 8 + length
        if end > len(blob):
            raise ValueError("Truncated GBL payload")
        result.append((kind, blob[position + 8:end]))
        position = end
    if [kind for kind, _ in result] != [0x03a617eb, 0xf40a0af4, 0xfd0303fd,
                                       0xfd0303fd, 0xfc0404fc]:
        raise ValueError("Unexpected signed/encrypted or other GBL structure")
    if result[0][1] != struct.pack("<II", 0x03000000, 0):
        raise ValueError("Unexpected GBL flags/version")
    if len(result[-1][1]) != 4 or binascii.crc32(blob) != CRC_RESIDUE:
        raise ValueError("Invalid GBL checksum")
    return result


def assemble():
    source = Path(__file__).with_name("bg21_key_export.S")
    with tempfile.TemporaryDirectory(prefix="yeegate-bg21-build-") as folder:
        root = Path(folder)
        script = root / "hook.ld"
        script.write_text("ENTRY(key_export_hook)\nSECTIONS { . = 0x48d00; .text : { *(.text) } }\n"
                          "vendor_dispatch = 0x2f471;\nnotify_original = 0x11f69;\n"
                          "original_continue = 0x11f99;\n")
        def compile_file(src, script, stem):
            obj, elf, binary = (root / (stem + ext) for ext in (".o", ".elf", ".bin"))
            subprocess.run(["clang", "--target=arm-none-eabi", "-mcpu=cortex-m33", "-mthumb",
                            "-c", str(src), "-o", str(obj)], check=True)
            subprocess.run(["ld.lld", "-T", str(script), str(obj), "-o", str(elf)], check=True)
            subprocess.run(["llvm-objcopy", "-O", "binary", str(elf), str(binary)], check=True)
            return binary.read_bytes()
        hook = compile_file(source, script, "hook")
        branch_source = root / "branch.S"
        branch_source.write_text(".syntax unified\n.cpu cortex-m33\n.thumb\n.section .text,\"ax\"\n"
                                 ".global branch\n.thumb_func\nbranch: b.w key_export_hook\n")
        script.write_text("ENTRY(branch)\nSECTIONS { . = 0x11f94; .text : { *(.text) } }\n"
                          "key_export_hook = 0x48d01;\n")
        branch = compile_file(branch_source, script, "branch")
    if len(branch) != 4 or not 0 < len(hook) <= 0x300 or len(hook) % 4:
        raise ValueError("Unexpected hook size or alignment")
    return hook, branch


def prepare(source, output):
    source = Path(source).read_bytes()
    if hashlib.sha256(source).hexdigest() != OFFICIAL_SHA:
        raise ValueError("Only the exact official S Knob 1.4.25 package is accepted")
    original = source[GBL_START:]
    if hashlib.sha256(original).hexdigest() != GBL_SHA:
        raise ValueError("Unexpected BG21 package")
    records = tags(original)
    address = struct.unpack_from("<I", records[3][1])[0]
    app = records[3][1][4:]
    if address != APP_BASE or len(app) != HOOK_ADDRESS - APP_BASE:
        raise ValueError("Unexpected native application layout")
    patch_offset = PATCH_ADDRESS - APP_BASE
    if app[patch_offset:patch_offset + 4] != bytes.fromhex("1df06cfa"):
        raise ValueError("Original GATT dispatcher instruction does not match")
    hook, branch = assemble()
    patched = bytearray(app)
    patched[patch_offset:patch_offset + 4] = branch
    patched.extend(hook)
    records[3] = (records[3][0], struct.pack("<I", APP_BASE) + patched)
    prefix = b"".join(struct.pack("<II", kind, len(data)) + data for kind, data in records[:-1])
    prefix += struct.pack("<II", 0xfc0404fc, 4)
    candidate = prefix + struct.pack("<I", binascii.crc32(prefix))
    verified = tags(candidate)
    if verified[:3] != tags(original)[:3]:
        raise ValueError("Header, metadata or 0x4000 program region was modified")
    output = Path(output)
    if not output.name.endswith(".analysis.gbl"):
        raise ValueError("Output must end with .analysis.gbl")
    output.write_bytes(candidate)
    native = output.with_suffix(".bin")
    native.write_bytes(patched)
    manifest = {"purpose": "offline candidate; boot acceptance/recovery unverified",
                "official_gbl_sha256": GBL_SHA,
                "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                "native_candidate_sha256": hashlib.sha256(patched).hexdigest(),
                "image_size": len(candidate), "hook_address": hex(HOOK_ADDRESS),
                "hook_size": len(hook), "patch_address": hex(PATCH_ADDRESS),
                "original_instruction": app[patch_offset:patch_offset + 4].hex(),
                "replacement_instruction": branch.hex(), "gbl_crc_valid": True,
                "gbl_signed": False, "gbl_encrypted": False,
                "first_program_region_unchanged": True, "factory_page_included": False,
                "secret_export_gate": "OTA-auth success 07030164 on characteristic 0x34",
                "export_notification": "0704 followed by 16-byte per-unit factory secret",
                "device_written": False, "boot_acceptance_verified": False,
                "recovery_verified": False}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))
    return patched


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    prepare(a.source, a.output)
