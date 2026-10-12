# S Knob local Home Assistant bridge investigation

Device: PID 1574912, BLE address F8:24:41:39:9F:38, name
`Yee-s3_knob 9f:38`, advertised DID 3789763.

Live observations:

- Action advertisement capture did not reveal decoded button/rotation events.
- FE99 vendor authentication input is 0011; output is 0022.
- Writing `05000164` yields `05010164`, verified twice on the physical knob.
- Writing `0502` plus a local random 16-byte challenge yields a 50-byte `0503`
  response. No network keys or node address were assigned.
- APK MeshProvisioningHandler uses this vendor handshake before mesh binding.
  It requests a cloud challenge through `/device/w/handshake`, sends it to the
  device, then submits the encrypted device response to the same endpoint.
  The HTTP helper supplies Bearer authorization and bizType `yp`.

The user selected Yeelight login for initial provisioning, with local operation
as the eventual target. QR login follows the official yeelight-home repository's
scan-login contract. Credentials are stored with mode 0600 under
`~/.local/state/yeegate/credentials.json`, outside this workspace. They are never
printed. QR login is pending; a local Home Assistant event bridge is not yet
implemented or validated. HAOS deployment follows provisioning and event decoding.

The user separately scanned the QR printed on the physical device and added it
to their Yeelight account with name `knob`. That is distinct from the computer's
QR sign-in request, which is still pending approval. The account device slot
may supply the deviceId required by the initial `/device/w/handshake` request.

QR authorization completed. Regional account credentials indicate Singapore.
IoT reads with `bizType=1` returned no homes; using `bizType=0` (or the backend
default) returns the user's home and device records. There are two knob slots:
one unbound placeholder and one bound record matching the physical MAC and DID.
The matching record includes a 16-byte hex deviceKey but no ltk. Its parent
gateway slot has PID 17000064 and is unbound. Account/device responses are saved
privately outside the workspace, never printed. Initial cloud handshake for
the physical knob succeeds and returns `random` and `sessionId`.

`tools/authenticate_knob.py` implements the live challenge flow without sending
the final binding payload. Device response is expected as `0503` plus IV (16),
encrypted challenge result (16), and device random (16). The second cloud
request includes did, deviceId, random, iv, encryptResult, sessionId, mac, pid
and type (PID bits 16:24), matching the APK. Live end-to-end authentication is
pending; the first post-login attempt connected but received no start reply
outside pairing mode.

Live authentication and provisioning subsequently succeeded after a desktop
Bluetooth adapter reset and the user entering pairing mode. The physical knob
answered the cloud-generated challenge; the second cloud handshake returned
encryptResult (160 decoded bytes) and sessionId. The client sent `0504` plus
that encrypted result, received `0505`, then confirmed via handshake POST
`{deviceId, confirm: 1, sessionId}`. Confirmation succeeded. Updated slot detail
was saved privately; ltk remains empty, deviceKey is present. Thus this is now
a provisioned physical device, but readable local events are not established.
The standard Mesh Invite still returned no Capabilities after vendor binding.
The first bound-device GATT notification capture returned no event packets;
the user confirmed starting the requested actions only after that capture ended,
so it does not prove the device sends no GATT events during interaction.
Started a fresh advertisement capture once actions were confirmed underway.

Added `tools/analyze_mesh_capture.py` to extract Mesh AD types 0x29/0x2a/0x2b
from BlueZ monitor btsnoop records, including legacy and extended advertising.
Checked both layouts and malformed lengths with synthetic packets, and
verified extraction of the two known knob advertisements in pro-pairing.btsnoop.
Raw interaction capture `knob-events.btsnoop` is requested but not yet present.
Root privileges are required for btmon; normal Bleak advertisements can omit
raw Mesh advertisement structures.

One extra unknown service is Silicon Labs OTA (1d14d6ee-fd63-4fa1-bfa4-
8f47b42119f0); it is not an input-event interface and was not written.
Reference: https://www.silabs.com/documents/public/application-notes/AN984-Implementing-Over-the-Air-Firmware-Upgrade.pdf

Tools:

- `tools/probe_knob.py`: notifications and optional transient vendor challenges.
- `tools/yeelight_login.py`: QR sign-in and private credential storage.

References:

- https://github.com/Yeelight/yeelight-home/tree/main/internal/auth
- APK ProvisioningStartState.createProvisioningStartPDU, address 0x13c5904.
- APK HttpRequest.getRandom1fromCloud, address 0x13cdb84.
- APK HttpRequest.getBindInfo, address 0x13ccd7c.

## Local MQTT bridge deployment — 2026-10-12

The raw interaction capture is now available. It contains eight Mesh network
AD 0x2a transmissions representing three distinct encrypted 25-byte packets
from F8:24:41:39:9F:38. Retrieved device keys do not match these packets' NID
under standard Mesh k2 derivation; the network/app keys are still unresolved.
Press and rotation semantics remain undecoded.

`knob_bridge/` extracts new encrypted packets into generic `mesh_activity`
events and suppresses duplicate transmissions for 30 seconds. An isolated
MQTT integration check confirmed nine replayed transmissions yield three
distinct events. Replay went only to a disposable local test broker.

Installed `local_yeegate_knob` 0.1.0 on the user's HAOS Raspberry Pi at
homeassistant.local, configured a dedicated Mosquitto login, and enabled
automatic boot. Pi Bluetooth startup and MQTT discovery passed:
`event.knob_mesh_activity` exists and is available, initially with unknown
state until its first packet. Fresh physical activity reception is pending.
The desktop bridge was stopped before starting the Pi bridge.

Deployment used a temporary SSH key added through the authenticated
Supervisor WebSocket API. The original SSH options were restored afterward.
HA/Yeelight tokens and MQTT credentials are outside the source tree in
/home/wisp/.local/state/yeegate with private file permissions.

## Action assignment — 0.1.1

Fresh physical knob Mesh activity was received on the Pi at
2026-10-12T11:45:59Z. Added a retained MQTT device automation trigger called
Mesh activity, and installed an English Home Assistant blueprint
`yeegate/knob_activity.yaml` with an action selector. Home Assistant's
device trigger API and blueprint loader verified both registrations.
Updated the Pi app to 0.1.1 and confirmed it is running. Separate gesture
assignment remains blocked by unresolved Mesh decoding; the physical knob's
screen language has not been changed, and no verified language property was
found in the available catalog or rotary-screen configuration model.

## Rotation investigation — 2026-10-12

The user wants all lights shown in their dashboard view controlled by twisting.
The Sunny dashboard Main View references four light entities: Wiz Bulb, Wiz
Strip, YN Light Bar, and Light1. Created light.knob_lights with precisely these
four members and two Home Assistant scripts (yeegate_brighten_lights and
yeegate_dim_lights), using brightness_step_pct +5/-5. These scripts have not
been connected to generic activity, and were not executed during setup.
Home Assistant validated the configurations and loaded both script entities.

The user confirmed rotating the physical knob navigates menu items, which
are the two built-in light relay switches. A 90-second raw Pi HCI capture
(knob-pi-rotation.jsonl) recorded 111 unchanged manufacturer advertisements
and three retransmissions of one unique encrypted network packet. This does
not establish rotation direction or brightness messages. No authenticated
Mesh decryption was obtained from 17 available/candidate keys; none matched
the observed NID. The cloud /panel/r/detail endpoint confirms two visible
built-in switch entries and hidden unconfigured controls.

A separate user-requested agent is investigating English display labels and
the vendor BLE label-transfer transport; no firmware has been changed.

User confirmed the physical relay labels now read Relay 1 and Relay 2 after
the display-only uploads. This does not enable dimming or gesture events.


### 12 October: clock/weather and menu recovery

User confirmed correct Bangkok time/date and Outdoor 27°C. App 0.3.3 adds
periodic clock and HA weather updates using Supervisor API permission, no
long-lived HA token or Yeelight account at runtime. Concurrent nested Bleak
scan sessions initially failed with BlueZ InProgress; updates now reuse the
bridge scanner and serialize GATT access. Successful clock and temperature
writes were logged on the Pi after this correction.

Device-menu 0507 visibility is inverse on the wire: visible=1 becomes internal
hide=0. An initial incorrect flag hid the menu; corrected two-relay restoration
was physically confirmed. A subsequent third dimmable entry appeared but had
Chinese text and no functional controls. It was removed, restoring two relays.
No brightness automation is wired to generic activity, and direction remains
encrypted/unresolved.


App 0.3.4 selects existing weather icons through the verified installed type-5
resource table. The user confirmed the cloud icon with HA cloudy/27°C. All 30
installed icon IDs can be cycled with the test tool without uploading assets or
firmware. IDs are displayed in the temperature field only during this test.


### Continued HA light display investigation

Physical About screen is reported as v1.4.25. Standard BLE firmware/hardware/
software revision fields were re-read and each returned one zero byte.
No BLE version confirmation was obtained.

Recovered display-state path: namespace 1 opcode 0c -> 420262ac -> queue
event 17 -> 4200c2dc -> 4200da30 -> 4200d13c for ptype 2. Payload byte
0 is ready bit 7 plus one-based slot; byte 1 is property-presence mask
(power bit 0, brightness bit 1); byte 2 is brightness percentage << 1
plus power. This updates the screen cache and UI, not physical relay output.

A vendor-rendered English HA Lights label was uploaded to type-2 slot 2
(2685-byte packet). The corrected three-entry menu and HA light.knob_lights
state on/13% were then sent. Write acknowledgments passed. The user confirmed the English label and that
holding the light icon opens a percentage ring, adjustable between 0% and 100%. Raw capture is saved separately in
knob-light-control-capture.jsonl. Rotation routing is still unverified.

The controlled ring interaction capture contains 194 transmissions, 57 unique
encrypted Mesh packets (55 length 27, two length 29), all NID 63. This is
substantially different from list navigation's single unique packet. Thirty-six
owner-record/identity candidates produced no matching standard Mesh network
key, so no authenticated brightness payload was decoded and no Home Assistant
light command was issued from these packets. BLE UART identity notification
code was also checked; it forwards input to the display but does not expose
plaintext brightness commands as notifications. Parent gateway detail was
read from the owner's account and contains configuration schemas, not keys.

Full built-in English translation is explicitly on hold at the user's request
until recovery is verified. The user reports a wall-powered knob and no
3.3 V UART adapter. See knob-firmware-recovery.md; no firmware was sent.


### Login and Mesh decryption audit

Added tools/mesh_crypto.py with authenticated network decoding and public
BlueZ/Bluetooth specification vector tests (flooding/friendship k2, control
network message, segmented-access network message, corrupted MIC rejection).
All tests passed. This rules out those implementation steps as the cause of
failed owner-key decoding, rather than treating random plaintext as valid.

Fresh authenticated reads of /house/r/all, /device/<owned knob>/r/detail,
/v2/house/r/<owned house>/properties and owned gateway detail succeed. No
NetKey/AppKey export was found. Three distinct 16-byte candidate values in
those owner records have no standard flooding NID match to the 57 packets
(NID 63). Broader owner-record/session derivation candidates also failed.
The previous gateway emulator intentionally kept its config/keys in memory
only and has no saved network credential export.

Recovered vendor provisioning forwards an encrypted binding blob from server
to the knob. BG21 firmware copies a 16-byte per-unit secret from user-data
flash 0x0fe0000e and derives MD5(secret + YEEMESH) for that exchange. The
official OTA image excludes this per-unit region. Login authenticates account
API requests; it does not by itself provide that factory secret or the
plaintext network/application keys inside the binding blob. This audit does
not prove there is no other supported vendor key export, but none was found
in the audited APIs or app provisioning path. HA rotation routing remains
blocked by missing keys, not by an absent brightness ring.


### Encrypted motion correlation and legacy dimmer comparison

The user supplied ble_monitor issue353. Its tested legacy dimmers use FE95,
MiBeaconV3 and a readable twelve-byte beacon key after RC4-based authentication.
This knob's saved GATT table contains neither FE95 nor the 00000014 beacon-key
characteristic; its captured advertisements carry Mesh AD2a, not FE95 service
data. The older script's fixed handle writes were therefore not sent.
Reference: https://github.com/custom-components/ble_monitor/issues/353

In a controlled ring test, five clockwise steps changed50→55 and produced five
unique27-byte packets. Five counterclockwise steps changed55→50 and produced
six27-byte packets (five in the paced burst, one earlier). A second five-step
counterclockwise test changed50→45 and produced four27-byte packets plus an
unrelated25-byte packet. The final clockwise repetition was requested but not
confirmed; it is excluded from conclusions. Ciphertext bytes in the earlier55
unique27-byte sample vary throughout, averaging roughly50% changed bits; all
55 encrypted destination prefixes are distinct. No reliable direction pattern
was established. Activity/bursts may identify interaction, but packet count,
length and raw ciphertext were not used to control HA brightness.

An alternative plaintext UART path was identified and a passive parser prepared;
see knob-firmware-recovery.md. This could avoid Mesh decryption or a firmware
change if safe serial access is obtained. Hardware validation remains pending.

### Mesh keys recovered through authenticated BG21 diagnostic OTA

On 12 October 2026 the owner authorized an authenticated BG21 export candidate
and subsequent stock restoration. The compiled ARM notification hook passed
emulation and CRC/package checks. It exported the per-unit factory secret
after successful NodeDevKey-based OTA authentication. Secret and complete
validated notification were saved privately, mode 0600. The recovered binding
keys authenticate all 57 brightness-ring packets and all 25 direction-test
packets at BOTH network and application layers. The 57-packet capture contains
55 absolute brightness commands and two power commands for slot 3, vendor
opcode 0xc1/company 0x0164. Direction tests decode to increasing percentages
clockwise and decreasing percentages counterclockwise.

The original BG21 GBL was restored and a fresh valid authentication produced
no diagnostic export, verifying stock behavior. Both finish writes returned
ATT 0x0e despite subsequent functional boot verification. No chunks were
retried after partial data writes. Exact installed flash bytes were not read
back. Temporary Pi files were removed and the bridge/SSH options restored.
Missing Mesh keys are now resolved; mapping authenticated slot-3 commands into
Home Assistant light services remains the integration task. See
[the key-export record](bg21-key-export-candidate.md) and
[the recovery pipeline](knob-mesh-key-recovery.md).

### Authenticated HA light integration — 0.4.1

Installed bridge 0.4.1 and configured the recovered network/application keys
privately in the app options. Slot 3, source address and publication destination
65278 are verified before dispatch. New MQTT event `event.knob_light_command`
and English device triggers expose brightness and on/off commands. Direct
control targets `light.knob_lights`, containing the four dashboard lights.
Zero brightness turns the group off; nonzero percentages call light.turn_on
with brightness_pct. Native Relay 1/2 slots remain outside this mapping.

A persisted sequence watermark rejects repeats across app restarts. Rapid
commands share one worker and coalesce into the newest requested state.
Offline capture validation, restart replay rejection, service mapping and
coalescing checks passed. Clock and weather sync remain functional.

The first physical test reported HA Lights offline on the knob while the HA
group was on. Added display-state feedback: poll HA every five seconds, send
changed state when idle, and refresh every thirty seconds. The verified
namespace 1/opcode 0c cache setter sets slot 3 ready and writes on/brightness
without changing physical relays. Shared BLE lock and busy checks prevent
feedback during rotation/service calls. A real Pi log confirms on/13% was sent.
Physical availability and live light response are awaiting user verification.


## Full-color controls and rotation response — 12 October 2026

The user confirmed that brightness control now works. Pi logs independently
show authenticated slot-3 brightness commands applied to `light.knob_lights`.
The 0.4.2 menu reinitialization restored the missing runtime entry type.

Version 0.5.1 is installed and running with automatic startup. It configures
HA Lights as ptype 4, preserving the two relays and the existing English label.
ESP handlers 4200df84 and 4200d25c establish the outbound selector-2 big-endian
Kelvin, selector-3 RGB bytes, and inbound state format. The decoder now accepts
these formats after both Mesh MIC checks, and maps them to Home Assistant
`color_temp_kelvin` and `rgb_color`. Display feedback preserves HA's active
color mode. A coalescing fix retains different properties in a single command
burst instead of losing a color change when brightness arrives immediately
after it. Live physical color/temperature validation is requested and pending.

At the user's request, speed scaling is enabled with maximum gain 4. The gain
ramps linearly with authenticated percentage-change speed, from 1x at 2 points
per second to 4x at 12 points per second; a pause over 0.6 seconds returns the
next change to 1x. Endpoints remain 0 and 100. This is a bridge response based
on command arrival timing, not a change to native encoder mechanics. During a
turn the ring keeps its firmware curve, then idle feedback aligns it to HA.
The public addon documentation explains how to change or disable this setting.

No physical haptic strength/resistance API is verified. Offline decompilation
of 4204fc80/4204fcfc identifies a WTVxx/WTN6 voice-prompt command on GPIO 1,
confirming that the exposed Sounds setting controls audio, not proving motor
haptics are adjustable. No haptic or new firmware writes were performed.

All 15 tests pass, including the original private authenticated packet replay,
Mesh cryptographic vectors, color/temperature format guards, mixed-property
coalescing, speed curve/endpoints and display-mode preservation. The distributable
ZIP contains source and blank credential defaults only. The Pi options retain
private Mesh and MQTT credentials outside the workspace.

The owner subsequently confirmed RGB color and white temperature control with
“works great.” The full-color controls are now physically verified on this unit.


### RGB-only color selection (0.5.2)

The owner requested color and color brightness without warm/cool white mixing.
Live HA state initially showed Wiz RGBWW channels [255,0,10,61,61] and Wiz RGBW
channels [255,3,0,38]. Color control now resolves available light-group members
and sends their native RGBWW/RGBW/RGB field with all white channels explicitly
zero, without a brightness field. An immediate live test preserved brightness
26/26/18 on the three available lights and reported both Wiz white outputs zero.
The Pi bridge is running 0.5.2. Subsequent authenticated knob color commands
were applied through the new bridge, and both Wiz devices still report zero
white channels. Temperature control remains a separate Kelvin operation.
All 16 tests pass, including mixed groups with duplicate/nested members,
unavailable members, and white-only lights. Repository docs record the behavior.

### Independent RGB and warm-white brightness (0.6.1)

The owner requested independent RGB and warm-white levels that can blend,
plus a red 10% preset in Home Assistant and on the knob. Version 0.6.1 is
installed with separate controls and independent channels enabled. The menu
preserves both relays and adds English RGB Lights, Warm White, and Red 10%
entries. The owner confirmed these entries are visible. Authenticated slot-3
RGB brightness and slot-5 preset commands have reached Home Assistant.

The two Wiz lights receive native RGBWW/RGBW channel values with a shared
brightness normalized to the larger channel level. Idle display feedback
derives each channel's effective level from those values. A live Home Assistant
test verified RGB 10% with warm white 15%, then RGB 20% while warm stayed at
15%. The YN integration exposes separate modes, so that bar follows RGB while
RGB is above zero and switches to warm white when RGB is zero.

The saved scene `scene.usual_red_10` restored the three available group members
to pure red at brightness 26/255, with white channels zero. Its fourth member
was unavailable. The owner confirmed the physical Warm White ring changes
warm intensity while red stays on, and both channels remain on together.
Slot-4 routing and repeated preset presses are covered by the local tests.
