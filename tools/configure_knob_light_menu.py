"""Add a reversible brightness display entry while preserving both relays.

This does not claim that Mesh destinations or Home Assistant rotation feedback
are configured. --restore hides the experimental third entry again.
"""
import argparse, asyncio, hashlib, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'knob_bridge'))
from display_config import test_menu_packets, light_state_packet
from bleak import BleakClient, BleakScanner

ADDRESS = 'F8:24:41:39:9F:38'
CHARACTERISTIC = 'b19adf7e-b836-40e3-8b06-acc47f2d187e'

async def configure(restore, state_snapshot=None):
    device = await BleakScanner.find_device_by_address(ADDRESS, timeout=20, adapter='hci0')
    if device is None:
        raise RuntimeError('Knob not found')
    packets = test_menu_packets(int(time.time()) & 255, restore=restore)
    if state_snapshot:
        if restore:
            raise ValueError('A light-state snapshot cannot accompany relay-only restoration')
        state = json.loads(Path(state_snapshot).read_text())
        packets.append(light_state_packet(power=state['power'], brightness=state['brightness']))
    async with BleakClient(device, timeout=20) as client:
        char = client.services.get_characteristic(CHARACTERISTIC)
        if char is None:
            raise RuntimeError('Verified display UART is missing')
        replies = asyncio.Queue()
        await client.start_notify(char, lambda _, data: replies.put_nowait(bytes(data)))
        auth = b'\x01' + hashlib.md5(bytes.fromhex(ADDRESS.replace(':',''))[::-1] + b'YEELIGHT').digest()
        await client.write_gatt_char(char, auth, response=True)
        if await asyncio.wait_for(replies.get(), 5) != b'\x01\x00':
            raise RuntimeError('Display identity rejected')
        for packet in packets:
            for offset in range(0, len(packet), 20):
                part = packet[offset:offset+20]
                if offset + len(part) == len(packet):part += b'\xff' * ((-len(part)) % 4)
                await client.write_gatt_char(char, part, response=True)
                await asyncio.sleep(.05)
            await asyncio.sleep(.15)
        await client.stop_notify(char)
    print(json.dumps({'entries_written':2 if restore else 3,'brightness_entry_requested':not restore,
                      'state_sent':bool(state_snapshot),
                      'screen_confirmation':'required','rotation_to_home_assistant':'not established'}))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--restore',action='store_true');parser.add_argument('--state-snapshot',type=Path);args=parser.parse_args()
    asyncio.run(configure(args.restore,args.state_snapshot))
