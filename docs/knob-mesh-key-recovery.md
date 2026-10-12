# S Knob Mesh key recovery progress

The English OTA updated the ESP display processor. The missing Mesh keys are
managed by the separate BG21 Bluetooth processor. This investigation made no
new firmware writes or provisioning changes.

## Confirmed factory-secret read operation

Official BG21 firmware has a read-only factory diagnostic command in
`0x14950`, case command 0 / subcommand `0x3e` / argument 1. It copies each byte
from `0x0fe00000` to `0x0fe0001f` to the configured diagnostic serial output,
then sends a normal success response. There is no flash erase/write in this
branch. Adjacent commands write user data; they must not be confused with it.

Decoder `0x10a40` maps byte 0 to command bits 7:6 and subcommand bits 5:0;
byte 1 gives the argument in bits 7:2. The corresponding read command is
`3e 04`. Its expected response is 32 raw page bytes followed by the diagnostic
status. This is a factory serial command, **not a BLE or UCP command**.

Helper `0x11dbc` copies the 16-byte secret from `0x0fe0000e` through
`0x0fe0001d`. Thus it is contained entirely in that 32-byte read. Binding
authentication derives MD5(secret || ASCII `YEEMESH`). The official application
image excludes this per-unit page.

The factory diagnostic path configures peripheral `0x40058000`, whereas the
normal ESP/BG21 UCP UART uses peripheral `0x40040000`. Therefore the diagnostic
read must not be assumed accessible by forwarding bytes over the inter-chip
UART or the B19 image characteristic. Physical pins and usable factory entry
on this particular unit remain unverified. No command was sent to the device.

## Existing UCP key request is insufficient

BG21 namespace 4/opcode 9 handler `0x27fac` returns the value computed by
`0x143d6`: MD5(NodeDevKey || `GATTDATA`). This is the display-transfer key,
already derivable from the owner's known NodeDevKey. It does not return the
factory secret, NetKey, or AppKey. Namespace 4/opcode 8 rewrites the user page;
it is not a key-reading command and must not be used for this investigation.

Silicon Labs also documents a local
[node key-reading API](https://docs.silabs.com/btmesh/latest/bluetooth-mesh-api/sl-btmesh-node#sl-btmesh-node-get-key).
That API's presence does not establish an exposed BLE command in this firmware.

## Prepared offline recovery pipeline

`tools/recover_knob_mesh_keys.py` loads the saved 160-byte binding response and
real advertisement capture without contacting the knob. Given a verified raw
factory-page read or the exact 16-byte secret, it decrypts the response using
the recovered AES-CBC scheme. It extracts NetKey, NodeDevKey, AppKey, IV index,
and unicast address using the provisioning handler's field layout.

It requires the recovered NodeDevKey to equal the known owner device key, then
requires at least three distinct real captured packets to pass network MIC
authentication, including a packet from the recovered unicast address. Only
then can it create a new private JSON file, with mode 0600. It never prints key
values, overwrites an existing credential file, or claims application-layer
decryption from a valid network MIC alone.

Current audit found a 160-byte saved binding blob and 57 distinct network packets,
all with NID 63. Supplying the known NodeDevKey as the factory secret was rejected.
The existing network decoder's three independent BlueZ/specification vector
tests pass. Actual Mesh keys have **not** been recovered.

The next software route to assess is an authenticated key-export diagnostic in
the BG21 firmware. This would be a different firmware operation from the ESP
English update, requiring its own GBL integrity/acceptance investigation and
recovery assessment. An ESP-only patch cannot directly read BG21 flash. A
verified factory serial read is the hardware alternative.

## Real recovery completed

Following an explicitly authorized BG21 diagnostic OTA, the per-unit factory
secret was exported after successful NodeDevKey authentication and saved
privately. The blob format byte is 0, not the decoder's initial assumed 1; the
vendor handler skips that byte. Real DeviceKey comparison and MIC checks now
recover and validate the NetKey/AppKey. All 57 unique brightness-ring packets
and all 25 direction-test packets authenticate at both network and application
layers. `tools/decode_knob_mesh.py` writes decrypted payloads to a mode-0600
file without printing them. `tools/knob_mesh_commands.py` recognizes only the
verified vendor 0xc1/company 0x0164 brightness/power payloads for slot 3.
Stock Bluetooth firmware restoration follows capture of the export.
