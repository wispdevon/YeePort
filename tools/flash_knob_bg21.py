"""Single-attempt BG21 OTA for the pinned diagnostic or official restore GBL.

This replaces the Bluetooth processor application. A sender result does not
prove bootloader acceptance. BLE recovery requires that application to boot.
Fresh external power cycle required after any interrupted BG21 transfer.
"""
import argparse
import asyncio
import hashlib
import json
import struct
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner
from prepare_bg21_key_export import tags, GBL_SHA
from probe_knob_ota import ADDRESS, AUTH, CONTROL, DATA, authenticate

DIAGNOSTIC_SHA = "75385a9b0e7a1a1da7a56ef5dfd78e2e8451082cd0ec34437070aeb81cf46e15"


def validate(blob):
    digest = hashlib.sha256(blob).hexdigest()
    if digest not in (DIAGNOSTIC_SHA, GBL_SHA):
        raise ValueError("Only the verified diagnostic or exact official restore GBL is accepted")
    records = tags(blob)
    if [struct.unpack_from("<I", records[i][1])[0] for i in (2, 3)] != [0x4000, 0x10000]:
        raise ValueError("Unexpected flash program regions")
    return digest


async def flash(config_path, image_path, result_path):
    blob = Path(image_path).read_bytes()
    digest = validate(blob)
    config = json.loads(Path(config_path).read_text())
    if config["address"].upper() != ADDRESS:
        raise ValueError("Device mismatch")
    key = bytes.fromhex(config["device_key"])
    if len(key) != 16:
        raise ValueError("Invalid device key")
    result = {"image_sha256": digest, "image_size": len(blob), "bytes_sent": 0,
              "transfer_complete": False, "install_requested": False, "boot_verified": False}
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
            await client._backend._acquire_mtu()
            if client.mtu_size < 149:
                raise ValueError("Negotiated MTU too small")
            await authenticate(client, key)
            await client.write_gatt_char(CONTROL, b"\0", response=True)
            start, next_report = time.monotonic(), 0
            for offset in range(0, len(blob), 200):
                chunk = blob[offset:offset + 200]
                await client.write_gatt_char(DATA, chunk, response=True)
                result["bytes_sent"] = offset + len(chunk)
                percent = result["bytes_sent"] * 100 // len(blob)
                if percent >= next_report:
                    record()
                    print(json.dumps({"stage": "transfer", "percent": percent,
                                      "elapsed_seconds": round(time.monotonic() - start)}), flush=True)
                    next_report = percent + 10
                await asyncio.sleep(.05)
            result["transfer_complete"] = True
            record()
            await asyncio.sleep(3)
            # Unlike the ESP-only flow, this GBL requires the BG21 bootloader
            # install/reset request. On disconnect its scheduled callback runs.
            await client.write_gatt_char(CONTROL, b"\x03", response=True)
            result["install_requested"] = True
            record()
        print(json.dumps({"stage": "install_requested", "boot_verified": False}), flush=True)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        record()
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("config", "image", "result"):
        p.add_argument("--" + option, required=True, type=Path)
    p.add_argument("--flash", action="store_true")
    p.add_argument("--fresh-boot-confirmed", "--fresh-power-cycle-confirmed",
                   dest="fresh_boot_confirmed", action="store_true",
                   help="External power cycle or verified completed BG21 reboot; upload offset must be zero")
    a = p.parse_args()
    if not a.flash:
        print(json.dumps({"image_sha256": validate(a.image.read_bytes()), "device_written": False}))
    elif not a.fresh_boot_confirmed:
        p.error("A fresh BG21 boot is required before starting a transfer")
    else:
        asyncio.run(flash(a.config, a.image, a.result))
