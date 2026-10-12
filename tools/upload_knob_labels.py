"""Upload bounded vendor-rendered English device label images.

Input is a private deployment bundle created by the operator. This tool accepts
only the built-in relay slots (type 2, indices 0/1) or the HA Lights slot (2).
It never writes to firmware OTA characteristics or changes device provisioning.
"""
import argparse
import asyncio
import base64
import hashlib
import json
from pathlib import Path

from bleak import BleakClient, BleakScanner
from knob_display_codec import label_packet
from probe_knob_display import DISPLAY_CHARACTERISTIC


async def upload(bundle_path):
    bundle = json.loads(Path(bundle_path).read_text())
    address = bundle["address"]
    key = bytes.fromhex(bundle["device_key"])
    labels = bundle["labels"]
    indices = [x["index"] for x in labels]
    if address.upper() != "F8:24:41:39:9F:38" or not (
            indices == [0, 1] or (indices == [2] and labels[0]["label"] == "HA Lights")):
        raise ValueError("Only the verified relay slots or HA Lights slot are accepted")
    packets = [(x["label"], label_packet(base64.b64decode(x["png"], validate=True),
                image_type=2, index=x["index"], device_key=key)) for x in labels]
    device = await BleakScanner.find_device_by_address(address, timeout=15, adapter="hci0")
    if device is None:
        raise RuntimeError("Knob not found")
    async with BleakClient(device, timeout=20) as client:
        characteristic = client.services.get_characteristic(DISPLAY_CHARACTERISTIC)
        if characteristic is None:
            raise RuntimeError("Verified display characteristic is missing")
        queue = asyncio.Queue()
        await client.start_notify(characteristic, lambda _, data: queue.put_nowait(bytes(data)))
        identity = hashlib.md5(bytes.fromhex(address.replace(":", ""))[::-1] + b"YEELIGHT").digest()
        await client.write_gatt_char(characteristic, b"\x01" + identity, response=True)
        reply = await asyncio.wait_for(queue.get(), 5)
        if reply != b"\x01\x00":
            raise RuntimeError("Display identity handshake did not succeed")
        print("Display identity accepted", flush=True)
        for label, packet in packets:
            # 20-byte chunks are aligned to four bytes and fit default ATT MTU.
            for offset in range(0, len(packet), 20):
                chunk = packet[offset:offset + 20]
                if offset + len(chunk) == len(packet):
                    chunk += b"\xff" * ((-len(chunk)) % 4)
                await client.write_gatt_char(characteristic, chunk, response=True)
                await asyncio.sleep(0.05)
            print(json.dumps({"label": label, "bytes_written": len(packet),
                              "display_confirmation": "requires visual check"}), flush=True)
            await asyncio.sleep(1)
        await client.stop_notify(characteristic)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    args = parser.parse_args()
    asyncio.run(upload(args.bundle))
