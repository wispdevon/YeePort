"""Authenticate the physical knob; optionally complete vendor binding."""

import asyncio
import argparse
import base64
import json

from bleak import BleakClient
from yeelight_cloud import Cloud

AUTH_IN = "00000011-0000-1000-8000-00805f9b34fb"
AUTH_OUT = "00000022-0000-1000-8000-00805f9b34fb"


async def authenticate(provision=False):
    cloud = Cloud()
    device = json.loads((cloud.path.parent / "knob-device.json").read_text())
    received = asyncio.Queue()
    def notified(_, data):
        received.put_nowait(bytes(data))

    async with BleakClient(device["mac"], timeout=15) as client:
        print("Connected to physical knob", flush=True)
        for service in client.services:
            if service.uuid == "0000fe99-0000-1000-8000-00805f9b34fb":
                for char in service.characteristics:
                    if "notify" in char.properties:
                        await client.start_notify(char, notified)
        await client.write_gatt_char(AUTH_IN, bytes.fromhex("05000164"), response=False)
        reply = await asyncio.wait_for(received.get(), 5)
        if reply != bytes.fromhex("05010164"):
            raise ValueError("Unexpected knob start response")
        print("Knob start confirmed", flush=True)
        context = {"did": int(device["did"]), "deviceId": device["deviceId"]}
        initial = await asyncio.to_thread(cloud.post, "/device/w/handshake", context,
                                         device["houseId"])
        data = initial["data"]
        random = base64.b64decode(data["random"], validate=True)
        if len(random) != 16:
            raise ValueError("Unexpected cloud challenge size")
        await client.write_gatt_char(AUTH_IN, b"\x05\x02" + random, response=False)
        reply = await asyncio.wait_for(received.get(), 5)
        if len(reply) != 50 or reply[:2] != b"\x05\x03":
            raise ValueError("Unexpected device challenge response")
        print("Knob answered cloud challenge", flush=True)
        encode = lambda b: base64.b64encode(b).decode("ascii")
        pid = int(device["pid"])
        body = {**context, "iv": encode(reply[2:18]),
                "encryptResult": encode(reply[18:34]), "random": encode(reply[34:50]),
                "sessionId": data["sessionId"], "mac": device["mac"],
                "pid": pid, "type": (pid >> 16) & 255}
        response = await asyncio.to_thread(cloud.post, "/device/w/handshake", body,
                                          device["houseId"])
        cloud.save_private("knob-authentication.json", response)
        result = response.get("data", {})
        print("Cloud authenticated knob; response fields:", sorted(result), flush=True)
        if not provision:
            print("No binding payload sent; no network keys assigned", flush=True)
            return
        packet = b"\x05\x04" + base64.b64decode(result["encryptResult"], validate=True)
        # BlueZ reports 23 until AcquireWrite/AcquireNotify exposes negotiated MTU.
        await client._backend._acquire_mtu()
        if len(packet) > client.mtu_size - 3:
            raise ValueError("Negotiated MTU is too small for the binding packet")
        await client.write_gatt_char(AUTH_IN, packet, response=False)
        print("Binding payload sent", flush=True)
        reply = await asyncio.wait_for(received.get(), 10)
        if reply[:2] != b"\x05\x05":
            raise ValueError("Knob did not acknowledge binding completion")
        print("Knob acknowledged binding completion", flush=True)
        confirmation = await asyncio.to_thread(cloud.post, "/device/w/handshake",
            {"deviceId": device["deviceId"], "confirm": 1,
             "sessionId": result["sessionId"]}, device["houseId"])
        cloud.save_private("knob-binding-confirmation.json", confirmation)
        fresh = await asyncio.to_thread(cloud.post,
            "/device/" + device["deviceId"] + "/r/detail", None, device["houseId"])
        cloud.save_private("knob-bound-detail.json", fresh)
        print("Binding confirmed in cloud; updated detail saved privately", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(authenticate(args.provision), 75))
