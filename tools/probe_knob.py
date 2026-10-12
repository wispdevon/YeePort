"""Capture knob notifications; optionally request vendor handshake metadata."""

import argparse
import asyncio
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient

SERVICE = "0000fe99-0000-1000-8000-00805f9b34fb"
AUTH_IN = "00000011-0000-1000-8000-00805f9b34fb"
# APK ProvisioningStartState.createProvisioningStartPDU (0x13c5904).
START = bytes.fromhex("05000164")


async def probe(args):
    with args.output.open("a", encoding="utf-8") as stream:
        confirmed = asyncio.Event()
        def log(event, **fields):
            record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
            line = json.dumps(record)
            stream.write(line + "\n")
            stream.flush()
            print(line, flush=True)

        def notified(characteristic, data):
            log("notification", characteristic=characteristic.uuid,
                length=len(data), data=bytes(data).hex())
            if bytes(data) == bytes.fromhex("05010164"):
                confirmed.set()

        async with BleakClient(args.address, timeout=15) as client:
            log("connected", address=args.address)
            subscribed = []
            for service in client.services:
                if service.uuid.lower() != SERVICE:
                    continue
                for characteristic in service.characteristics:
                    if "notify" in characteristic.properties:
                        await client.start_notify(characteristic, notified)
                        subscribed.append(characteristic)
                        log("subscribed", characteristic=characteristic.uuid)
            if args.handshake:
                await client.write_gatt_char(AUTH_IN, START, response=False)
                log("start_sent", data=START.hex(), network_keys_assigned=False)
                if args.challenge:
                    await asyncio.wait_for(confirmed.wait(), 5)
                    # Only exercises the transient challenge/response exchange.
                    # Does not authenticate, bind, or assign network keys.
                    challenge = secrets.token_bytes(16)
                    await client.write_gatt_char(AUTH_IN, b"\x05\x02" + challenge,
                                                 response=False)
                    log("challenge_sent", length=16, network_keys_assigned=False)
            await asyncio.sleep(args.seconds)
            for characteristic in subscribed:
                await client.stop_notify(characteristic)
            log("finished", network_keys_assigned=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--handshake", action="store_true")
    parser.add_argument("--challenge", action="store_true",
                        help="Send a local random challenge after the start reply")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("knob-notifications.jsonl"))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120:
        parser.error("--seconds must be between 1 and 120")
    if args.challenge and not args.handshake:
        parser.error("--challenge requires --handshake")
    asyncio.run(asyncio.wait_for(probe(args), args.seconds + 45))
