"""Request Mesh provisioning capabilities; never assign keys or addresses."""

import argparse
import asyncio
import json
from pathlib import Path

from bleak import BleakClient

DATA_IN = "00002adb-0000-1000-8000-00805f9b34fb"
DATA_OUT = "00002adc-0000-1000-8000-00805f9b34fb"


async def probe(address, output):
    packets = []
    received = asyncio.Event()

    def record(_, data):
        packet = bytes(data)
        packets.append(packet.hex())
        # Complete Proxy PDU, provisioning type, Capabilities opcode.
        if len(packet) == 13 and packet[:2] == b"\x03\x01":
            received.set()

    async with BleakClient(address, timeout=15) as client:
        await client.start_notify(DATA_OUT, record)
        # Proxy header: complete provisioning PDU. Invite: attention timer zero.
        await client.write_gatt_char(DATA_IN, b"\x03\x00\x00", response=False)
        try:
            await asyncio.wait_for(received.wait(), timeout=8)
        except TimeoutError:
            pass
        await client.stop_notify(DATA_OUT)
    result = {"address": address, "packets": packets, "capabilities": None}
    for raw in packets:
        p = bytes.fromhex(raw)
        if len(p) == 13 and p[:2] == b"\x03\x01":
            result["capabilities"] = {
                "elements": p[2], "algorithms": int.from_bytes(p[3:5], "big"),
                "public_key_type": p[5], "static_oob_type": p[6],
                "output_oob_size": p[7], "output_oob_actions": int.from_bytes(p[8:10], "big"),
                "input_oob_size": p[10], "input_oob_actions": int.from_bytes(p[11:13], "big"),
            }
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--output", type=Path, default=Path("knob-capabilities.json"))
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(probe(args.address, args.output), timeout=45))
