"""Single-attempt native ESP English OTA for the verified S Knob.

Never sends BG21 completion/control 03, never retries image chunks, and never
claims flash acceptance from ATT success. A physical reboot/display check is
required because native ESP completion is not exposed as a BLE notification.
"""
import argparse
import asyncio
import binascii
import hashlib
import json
import struct
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner
from probe_knob_ota import ADDRESS, AUTH, CONTROL, DATA, authenticate

EXPECTED_SHA256 = "54a2be6c16a53bff7fd5e37dce7d25809d9f0b11c21b5b3f3133ab524d149c2a"
EXPECTED_SIZE = 1052544


def image_header(image):
    if len(image) != EXPECTED_SIZE or hashlib.sha256(image).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Only the verified language-only native candidate is accepted")
    if image[:1] != b"\xe9" or image[0x7e6c:0x7e6f] != b"en\0":
        raise ValueError("Image format or language literal mismatch")
    return b"espf" + struct.pack("<II", binascii.crc32(image) ^ 0xffffffff, len(image))


async def flash(config_path, image_path, result_path):
    image = Path(image_path).read_bytes()
    header = image_header(image)
    config = json.loads(Path(config_path).read_text())
    if config["address"].upper() != ADDRESS:
        raise ValueError("Device identity mismatch")
    key = bytes.fromhex(config["device_key"])
    if len(key) != 16:
        raise ValueError("Invalid device key")
    result = {"image_sha256": EXPECTED_SHA256, "image_size": len(image),
              "bytes_sent": 0, "transfer_complete": False, "boot_verified": False,
              "device_flash_acceptance_verified": False, "bg21_control_03_sent": False}
    def record():
        Path(result_path).write_text(json.dumps(result, indent=2) + "\n")
    record()
    try:
        device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20)
        if device is None:
            raise RuntimeError("Knob not found")
        async with BleakClient(device, timeout=20) as client:
            if any(client.services.get_characteristic(u) is None for u in (AUTH, CONTROL, DATA)):
                raise ValueError("Official OTA service is missing")
            acquire = getattr(client._backend, "_acquire_mtu", None)
            if acquire is not None:
                await acquire()
            if client.mtu_size < 149:
                raise ValueError("Negotiated MTU is too small")
            await authenticate(client, key)
            print(json.dumps({"stage": "authenticated", "mtu": client.mtu_size}), flush=True)
            # Control 00 only enables the authenticated stream. Header forwards
            # native start with flags=0; BG21 emits op3 for the final data chunk.
            await client.write_gatt_char(CONTROL, b"\0", response=True)
            await client.write_gatt_char(DATA, header, response=True)
            await asyncio.sleep(1)
            start = time.monotonic()
            next_report = 0
            for offset in range(0, len(image), 200):
                chunk = image[offset:offset + 200]
                # No retry: receiver has no offset field and appends each chunk.
                await client.write_gatt_char(DATA, chunk, response=True)
                result["bytes_sent"] = offset + len(chunk)
                percent = result["bytes_sent"] * 100 // len(image)
                if percent >= next_report:
                    record()
                    print(json.dumps({"stage": "transfer", "percent": percent,
                                      "bytes_sent": result["bytes_sent"],
                                      "elapsed_seconds": round(time.monotonic() - start)}), flush=True)
                    next_report = percent + 5
                await asyncio.sleep(.05)
            result["transfer_complete"] = True
            record()
            # Give the ESP flash validator time, then disconnect normally.
            # Control 03 invokes BG21 bootloader installation; omit for ESP-only.
            await asyncio.sleep(10)
            print(json.dumps({"stage": "transfer_finished", "physical_boot_check_required": True,
                              "normal_power_cycle_may_be_required": True,
                              "device_flash_acceptance_verified": False}), flush=True)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        record()
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--flash", action="store_true", help="Perform the authorized single OTA attempt")
    a = p.parse_args()
    if not a.flash:
        print(json.dumps({"header": image_header(Path(a.image).read_bytes()).hex(),
                          "sha256": EXPECTED_SHA256, "device_written": False}))
    else:
        asyncio.run(flash(a.config, a.image, a.result))
