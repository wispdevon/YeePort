# Yeelight Pro 1.33.0 discovery findings

Analyzed locally from the user-provided Android APK, SHA-256
`c6ad96fb97fe8baecb2e264ab5f07f6b6e3f30939616bded0459d459fb6b672d`.
The app was not installed or executed. Android findings need live verification
against the user's iPhone app; iOS behavior may differ.

## Product identity

Bundled `res/product_configs/device/pid/14336.json` identifies the original
S20 BLE Mesh gateway. `14337.json` identifies the enhanced version.
Bundled `res/configs/products.json` identifies `1574912` as the S-series
wall knob-screen switch.

## Bluetooth discovery

Blutter decoded `libapp.so` using its Dart 3.11.5 snapshot. Analysis artifacts
are at `/tmp/yeegate-apk/dart-analysis/`; these are temporary and not required
to run the project.

`YeelightIotLibraryBluetooth.scanYeelightDevices` at `0x133ca14` scans for
FE99 and FE87. `parseAdvertisementData` at `0xf5c9ac` handles FE99 Mesh
advertisements with manufacturer ID `0x0164` and at least 19 payload bytes:

| Offset | Length | Interpretation |
| --- | --- | --- |
| 0 | 4 | Product ID, big-endian |
| 4 | 6 | Device MAC, little-endian byte order |
| 10 | 8 | Device ID, big-endian |
| 18 | 1 | Bit 0: flag; bit 1: identify; bit 2: GATT common config |

The gateway scan uses `DevScanMode` requiring flag bit 0 to be zero. The
gateway predicate at `0x133c7b0` recognizes IDs 14336–14339 and 17000064.

`NearbyGatewaysListModel` applies `GatewayScanMacPolicy` to the embedded
MAC. `isAllowedForNearbyGatewayScan` at `0x1340758` accepts MACs matching
`^F8:24:41(:[A-F0-9]{2}){3}$` or a fixed 43-address exception set.
Our first two trials used the host adapter's B0:3C:DC prefix, which fails
this Android policy. The user subsequently confirmed discovery on the iPhone
with the corrected embedded identity; the exact iOS filter code is unverified.

The revised advertisement uses the synthetic embedded identity
`F8:24:41:EE:00:01`, product 14336, test device ID 1, and flags 0. It does
not change the host adapter address. Test device ID 1 is not a valid known
Yeelight cloud enrollment identity. Advertisement-only pairing stalled at 20%.

`tools/gateway_server.py` now exports FE99 with gateway input characteristic
`00000055` and output characteristic `00000066`. It implements the initial
P-256 public-key response and session-key derivation. Encrypted configuration
transfer and cloud enrollment remain unimplemented.

The user reported error `00187` at 20% with the first GATT implementation;
the server logged no subscriptions or writes. In the Android APK,
`WifiDeviceBindModel.connectErrorCodeWithLogicBindSteps` at `0x1f89310`
selects `00187` for `KBindLogicSteps.linking` (enum index 1). This indicates
a linking-step timeout, rather than an observed key-exchange rejection.
Connection-state logging and explicit advertisement discoverability were
added for the next diagnostic attempt. The exact reason is not yet established.

The repeated attempt still returned `00187` without GATT callbacks. A BlueZ
snapshot showed the iPhone (user-confirmed name `Iridescence`) already connected
and bonded to the computer. Refreshing that specific connection produced
Connected=false followed by Connected=true, still without gateway subscriptions
or writes. These connection signals alone do not establish that Yeelight Pro
opened the gateway service; the phone also has an existing host Bluetooth bond.
An independent iPhone BLE service-discovery test is needed to distinguish
host GATT/caching problems from the Yeelight app's connection behavior.

nRF Connect was also reported stuck connecting. The supplied CSV contains
only Scanner On, Device Scanned, and Scanner Off; it has no connection or
service-discovery events, so it does not identify the failure reason.
With explicit user authorization, `hci0` was powered off and on and the gateway
service restarted. Saved bonds were retained. Post-reset independent BLE
connection verification is pending. The phone immediately reconnected over
both BR/EDR and LE after the reset. Under the user's authorization to disconnect
and reset the Bluetooth connection, only the host bond for the user-confirmed
iPhone was then removed via Adapter1.RemoveDevice. The user must also forget
the `claymore` computer pairing on the iPhone to clear its half of that bond.
The mouse bond was not removed. The existing dual connection is a possible
confounder, not a proven cause of the emulator linking failure.

The next nRF Connect CSV confirmed a successful connection at 17:07:08 and
FE99 characteristic discovery (`0055`, `0066`) at 17:07:12. The phone then
disconnected at 17:07:14 while discovering descriptors of host audio services.
A second connection lasted about two seconds. The gateway service stayed running
and recorded no subscriptions or writes; no gateway application timeout or
explicit disconnect is implemented. The CSV does not contain a disconnect
reason. A host HCI capture is required to determine the disconnect initiator,
reason code, and any security exchange. `btmon` capture requires privileges not
available to the agent; reading a user-created btsnoop file is possible locally.

## Confirmed disconnect cause from HCI capture

The user created `connection.btsnoop` and reproduced the disconnect twice.
Both LE connections succeeded with the host in Peripheral role and iPhone
resolvable address `40:20:74:03:7C:BC`. The host's GATT client attempted to
read the phone's Battery Level (handle 0x0011); the phone returned Insufficient
Authentication. The host requested security; the iPhone sent a Pairing Request,
and the host responded Pairing Failed: Pairing not supported (0x05).
The adapter was Pairable=false. Both attempts ended with a host-issued
Disconnect and Connection Terminated By Local Host (0x16).

The gateway now supports optional `--pairing-peer ADDRESS` arguments to register
a temporary NoInputNoOutput agent restricted to the listed phone addresses and
enable adapter Pairable for its lifetime. Unlisted peers are rejected. The
original Pairable setting is restored on normal termination. This setting
addresses the observed security refusal; live validation is pending. New
Bluetooth bonds created during testing remain saved until explicitly removed.

The user confirmed the iPhone showed a pairing prompt, completed pairing, and
remained connected until manually disconnected. The third nRF Connect CSV
confirms complete service/descriptor discovery, including CCC descriptors for
both gateway characteristics. The server recorded pairing authorization for
the captured phone address. This validates independent Bluetooth/GATT access;
Yeelight Pro gateway onboarding and knob provisioning remain unverified.

## Remaining work

The app contains separate GatewayProvisioning and MeshProvisioning state
machines. Standard Bluetooth Mesh provisioning is not sufficient evidence of
compatibility with either. Trace their message framing, handshake, encryption,
and cloud binding before implementing enrollment or assigning mesh keys.

`GatewayProvisioningStartState.createProvisioningStartPDU` at `0x1f8c160`
generates a local public key and constructs `05 00 01 64 || public_key`.
The first field is written as a little-endian uint16. This is a vendor
protocol message, unlike the standard Mesh Invite `03 00 00` used in our
initial capabilities probes. Its response header is `05 01 01 64`, followed
by the gateway's public key. The Java crypto plugin uses secp256r1, raw
32-byte big-endian X followed by 32-byte big-endian Y. The session AES key
is MD5(shared ECDH secret || UTF8("YEEMESH")). This stage was verified
locally for fragmented input, equivalent peer key agreement, and malformed
key rejection. Live iPhone key exchange is still pending.
# Yeelight Pro connection capture (2026-10-12)

`pro-pairing.btsnoop` contains two incoming BLE connections from the iPhone.
In the first, the desktop sends an SMP Pairing Failed response with reason
`Numeric comparison failed` after a local User Confirmation Negative Reply.
Classic Bluetooth connection attempts overlap BLE pairing. In the second,
classic authentication fails and the desktop explicitly disconnects both
classic and BLE links. These failures precede any gateway handshake writes.

The iPhone device object retains its original random-address path
`/org/bluez/hci0/dev_40_20_74_03_7C_BC` even though its Address property is now
`98:B3:79:6F:6A:10`. Set that object's PreferredBearer from `bredr` to `le`
and disconnected it to apply the change. BlueZ documents this setting as
removing the device from automatic connection when advertising. This is an
isolation step; successful Yeelight Pro onboarding is still unverified.
Connection logs now include the device object path.

Enrollment endpoint observation: the live app config selects
`iot-lb-sg.yeelight.com:80`; TCP connection succeeds but no unsolicited data
arrives. A separate unauthenticated HTTP HEAD probe receives the non-HTTP
CRLF-terminated JSON `{"result":"ERROR"}`. This establishes that HTTP
registration cannot simply be assumed from port 80. It does not establish
the gateway authentication message schema or whether a manufacturer key is
required. We have no validated gateway-to-cloud registration transaction.
The `20193` result is therefore still expected. Further blind app retries
add no useful evidence; firmware or a reference gateway's cloud exchange
would provide the missing implementation evidence.

`20193` is the default error for KBindLogicSteps.queryDeviceInfo (index 8)
when no more specific error exists. BaseDeviceBindModel.queryDeviceSlot calls
Api.getDeviceSlotDetail; UrlUtils.getUrlDeviceSlotIdDetails builds
`/device/<id>/r/detail`. BLE configuration acknowledgement starts cloud polling.
The phone's config supplies server, port, bind_token, Wi-Fi credentials,
houseId/resId and url; the APK does not include gateway firmware. Added a
bounded TCP reachability/banner-length probe for the supplied server/port.
It sends no application credentials and logs no banner contents. A local
socket test verifies connectivity and redaction. It does not register the
device; the gateway-to-cloud registration/authentication protocol remains
unknown. No successful enrollment notification is fabricated.

At 17:51 the app reached 75% after the server decoded configuration and sent
0503. Thus discovery, Bluetooth pairing, gateway key exchange, configuration
decryption and transfer acknowledgement are now live-verified. The next
APK handler is GatewayEnrollmentStatusListenState: notification payloads
include a length and JSON with `code`/`info`. The app also has cloud binding
and gateway enrollment checks; a synthetic notification alone would not
prove registration. The advertised DID is still a test value, and no valid
gateway cloud identity or device registration flow has been established.

Live configuration decoding succeeded at 17:47:55: 327-byte packet decrypts
and validates as `config_device`. The following `00080` reflects a missing
configuration acknowledgement. GatewayProvisioningCompleteState.parseData
(0x13c81cc) reads the first two notification bytes and accepts header `0503`,
then transitions toward enrollment status. The server now sends `0503` only
after validated configuration receipt, retaining configuration in memory.
This is not a `0504` enrollment-success response; cloud registration is still
unimplemented. No configuration values are logged or written to disk.

The app reports `00080` after the first successful key exchange. APK function
WifiDeviceBindModel.connectErrorCodeWithLogicBindSteps maps enum index 5,
`KBindLogicSteps.sendConfig`, to `00080`. It is a configuration-stage error,
not proof of cloud rejection or invalid Wi-Fi credentials. No fresh GATT
writes reached the newly started decoder while the previous phone link
remained connected. Disconnected only the iPhone link to allow a fresh attempt;
its bond was preserved.

At 17:45 the iPhone app reached 40%: subscribed to 0066, wrote the 68-byte
start/key message to 0055, accepted our 68-byte response, then wrote a 327-byte
configuration message. This confirms the first gateway key exchange works.
Added a single-packet configuration decoder using APK-derived AES-CBC with
zero padding, IV at bytes 7:23, declared plaintext length at bytes 5:7, and
ciphertext from byte 23. Synthetic round-trip and malformed-packet checks pass;
live configuration decoding is pending. Credentials are discarded and never
logged. No cloud enrollment or completion acknowledgement is implemented.

System D-Bus capture `connection-calls.txt` identifies sender `:1.231`, PID
271179 (`tetherd`), calling Device1.Connect on the iPhone. Pausing that process
stopped the repeated connection loop and PreferredBearer remained `le`.
The user explicitly requested killing and removing tetherd. Its executable
was already deleted; the process was killed and residual user data/state
directories removed. No installed package or startup entry was found in the
checked locations. Gateway enrollment remains unverified.

The fifth nRF export and server events show pairing authorized at 17:32:37
for the allowed private-address device. Later brief reconnections have no
`pairing_rejected` event; the same device resolves to the iPhone identity.
Hands-free profile attempts and PreferredBearer reverting to `bredr` continue.
Pausing KDE Connect and stopping WirePlumber together also did not eliminate
all attempts; both were restored. A system D-Bus method-call trace is needed
to distinguish client-initiated Connect/Disconnect calls from BlueZ policy.

The fourth nRF export confirms service and descriptor discovery on both gateway
characteristics, followed by disconnects. Server events identify explicit
pairing-agent rejection at 17:29:31 and 17:29:39: the iPhone now uses private
address `7B:80:1C:AE:B8:54`, absent from the original peer allowlist. This
address was added to the running server's allowlist. Private addresses rotate;
the fixed-address allowlist is a temporary diagnostic mechanism, not suitable
for unattended deployment.

Follow-up: PreferredBearer reverted to `bredr` during repeated connections.
Temporarily pausing KDE Connect and stopping WirePlumber did not individually
stop the loop; both were restored. The stale iPhone device/bond was removed
again to allow a clean pairing. No other device bonds were removed. The
Android APK's BleMeshManager.connect uses a five-second Duration (5,000,000
microseconds); this does not establish the iOS app's timeout.
