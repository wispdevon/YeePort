"""Inspect the display transfer service and perform its identity handshake only.

No image data, firmware, binding, or reset command is sent. The handshake is
derived from Yeelight Pro 1.33.0 TransferImageManager._sendDeviceIdentifyAction.
It does not change screen labels or prove the firmware supports label uploads.
"""

import argparse
import asyncio
import hashlib
import json

from bleak import BleakClient, BleakScanner

DISPLAY_CHARACTERISTIC = "b19adf7e-b836-40e3-8b06-acc47f2d187e"
FIRMWARE_CHARACTERISTIC = "00002a26-0000-1000-8000-00805f9b34fb"


async def probe(address, adapter):
    device = await BleakScanner.find_device_by_address(address, timeout=15, adapter=adapter)
    if device is None:
        print(json.dumps({"stage": "scan", "found": False}))
        return
    async with BleakClient(device, timeout=20) as client:
        characteristic = client.services.get_characteristic(DISPLAY_CHARACTERISTIC)
        print(json.dumps({"stage": "services", "display_transfer": characteristic is not None}))
        firmware = client.services.get_characteristic(FIRMWARE_CHARACTERISTIC)
        if firmware is not None:
            raw = bytes(await client.read_gatt_char(firmware))
            print(json.dumps({"stage": "firmware", "text": raw.decode("ascii", errors="replace").strip("\x00")}))
        if characteristic is None:
            return
        replies = []
        await client.start_notify(characteristic, lambda _, data: replies.append(bytes(data)))
        identity = hashlib.md5(bytes.fromhex(address.replace(":", ""))[::-1] + b"YEELIGHT").digest()
        await client.write_gatt_char(characteristic, b"\x01" + identity, response=True)
        await asyncio.sleep(4)
        print(json.dumps({"stage": "identity", "replies": [data.hex() for data in replies]}))
        await client.stop_notify(characteristic)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="F8:24:41:39:9F:38")
    parser.add_argument("--adapter", default="hci0")
    args = parser.parse_args()
    asyncio.run(probe(args.address, args.adapter))
