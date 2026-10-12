# S Knob English display labels

The physical knob's display configuration is separate from Home Assistant's
language. Yeelight Pro 1.33.0 has a supported path for custom display label
images. No verified global screen-language command has been found.

The APK's `MeshRotaryScreenConfigModel.getKeyNameImage` asks the vendor renderer
for PNGs using `POST /common/r/1574912/textToImage` and `{"texts": [...]}`. The
routing argument is the product ID. The service rendered **Relay 1** and
**Relay 2** successfully; the private outputs stay outside the workspace.

`TransferImageManager` uses characteristic
`b19adf7e-b836-40e3-8b06-acc47f2d187e`. The identity command is byte `01` followed
by MD5 of the reversed MAC bytes plus ASCII `YEELIGHT`. The actual knob on the
Pi replied `0100`, matching the app's success branch. Its standard firmware
version characteristic returned an empty string. The app normally enables
name uploads on firmware 1.3.15 or newer.

`PanelInfoBeanFromJson` groups button type 4 into the device list. The rotary
screen model copies that list, sorts it by display index, and uses image type
2 with a zero-based index when uploading its labels. This covers the existing
two built-in relay entries; uploading labels does not add a brightness control
or enable rotation events.

The image packet has header `f0f1f2f3020a00`, little-endian label index and
zero-padded plaintext length, followed by AES-CBC ciphertext and CRC-16/CCITT
of that ciphertext (initial value zero, little endian). The plaintext is image
type, index, zero, vendor PNG, then zero padding to 16 bytes. The key is
MD5(device-key bytes + ASCII `GATTDATA`); the IV is the 11-byte header plus five
zero bytes. This is display image transfer, separate from the Silicon Labs
firmware OTA service.

`tools/knob_display_codec.py` builds bounded packets, and
`tools/upload_knob_labels.py` permits only the verified knob and relay slots
0 and 1. It checks the identity reply and uses acknowledged 20-byte writes,
padding only the final transfer chunk to a four-byte boundary as the app does.
The codec was checked by decrypting both generated label packets and verifying
the original PNGs, label metadata, and CRC. Rendering on the physical screen
must still be checked visually; GATT write acknowledgments alone are insufficient.

Both **Relay 1** (2141 bytes) and **Relay 2** (2349 bytes) were uploaded to the
physical knob from the Pi, with all acknowledged writes completing successfully.
The connection was closed, the temporary upload environment and private bundle
were removed from the Pi, and the original SSH options were restored. The user confirmed both resulting labels display in English. The existing cloud aliases
remain Chinese, so reconfiguring labels in the vendor app may overwrite these
custom images.

## Remaining clock and status menus

The user confirmed the two relay names appear in English. The remaining Chinese
text includes the calendar/date and the relays' on/off status. These are built-in
firmware resources, rather than the custom label images.

Read-only firmware catalog requests to `/upgrade/r/listfile` with `languageCode`
`en` and `zh` returned firmware 1.4.25 with the same file and MD5. Only the release
description differed. The official binary was downloaded and its catalog MD5
verified for offline analysis; it was not flashed onto the knob. Its SHA-256 is
`6ac92c8095206498b1762b6fdd2669148caed9d18b2c08a3b0eaef92c52fddd5`.

That firmware contains both English and Chinese resources, including
`en_week0.png` through `en_week6.png`, `en_dev_state_on.png`, and
`en_dev_state_light_off.png`. However, its display resource prefix is initialized
to `zh`: DRAM location `0x3fca5204` points to the `zh` string at `0x3c087e6c`.
The resource renderer at `0x4201b17c` loads this pointer when formatting
`/spiffs_%d/%s_%s`. The settings initializer at `0x42018d24` also reads it.
No verified setter or exposed language property was found in the inspected
firmware references, app settings model, BLE configuration model, or cloud
device attributes. This is evidence for a default fixed by the firmware build,
not proof that every possible vendor command has been exhausted.

The confirmed label uploader writes only `device_image<index>.png` resources;
it cannot replace the built-in calendar/status assets. Changing these remaining
menus therefore still needs a verified vendor language command or supported
English firmware. No speculative language writes or firmware flashing have
been performed.

### Offline firmware candidate

An offline candidate is available at
`/home/wisp/Downloads/yeegate-s-knob-1.4.25-english.analysis.bin`, with a companion
JSON manifest. **This is an analysis artifact, not a verified OTA update.**
`tools/prepare_knob_english_analysis.py` accepts only the exact verified original
SHA-256 and prepares a reproducible candidate. It changes 35 bytes:

- Two bytes at container offset `0x257e84`: `zh` becomes `en`.
- ESP segment XOR checksum at `0x350f77`: `57` becomes `4e`.
- The 32-byte appended ESP SHA-256 at `0x350f78` is recomputed.

The ESP image starts at `0x250018`. Original and candidate segment checksums and
appended SHA-256 both validate. Every other byte remains unchanged, including
all Mesh/BG21 firmware after `0x350f98`, all assets, and network code. The 68
Chinese PNG asset names all have matching English variants. Changing the
prefix therefore selects existing English resources rather than injecting
translated images. This does not establish that every clock-face decoration
or date layout responds to the prefix; those may have additional fixed assets.

The outer container starts with `kbui` and has an unexplained 32-bit word
`0xc04f566b` at offset 4. Its validation, any device-side signature/secure-boot
requirements, and OTA compatibility have not been established. A locally valid
ESP checksum and SHA-256 do not prove that the full package will be accepted.
The physical knob's current firmware version is also unknown because its BLE
version characteristic was empty. There is no verified rollback/recovery path
for this particular unit, so the candidate has not been sent to it.

Practical next steps are a documented vendor language-setting command, a
supported official English build for the exact product, or further read-only
analysis of the configuration parser. The working custom relay labels can be
kept without any firmware update.

### Native ESP image path and OTA recovery analysis

Offline examination of the firmware's UCP namespace 2 dispatch table
(`0x3c0cfb98`) establishes the following command meanings. None of these should
be sent as a supposedly read-only probe:

| Opcode | Handler | Meaning |
| --- | --- | --- |
| 1 | `0x420259ec` | Start application transfer with length and raw CRC-32 |
| 2 | `0x42025ab4` | Application data, writes through `esp_ota_write` |
| 3 | `0x42025a64` | Final application data; validates and selects boot partition |
| 4 | `0x42025790` | OTA reset/preparation; can erase inactive partitions |
| 7 | `0x42025718` | Start UI asset transfer |
| 8 | `0x420256a4` | UI asset data, writes through `esp_partition_write` |
| 9 | `0x42025620` | Final UI asset data and CRC check |
| 10 | `0x42025afc` | Custom label image write (the already verified label path) |

The language prefix resides in the application image, so opcodes 7–9 cannot
change it. A native application route exists independently of the outer `kbui`
container. The native English analysis image is
`/home/wisp/Downloads/yeegate-s-knob-1.4.25-english.esp.analysis.bin`, 1,052,544
bytes, with raw IEEE CRC-32 `0x1913020f`. Its unmodified official reference is
`/home/wisp/Downloads/yeegate-s-knob-1.4.25-english.esp.official-reference.bin`,
with raw CRC `0x61b36fc9`. Both CRCs were independently checked against the
actual firmware's 256-entry CRC table. The raw CRC uses initial `0xffffffff`
without a final complement. These files and their manifests are offline only.

Application completion verifies the byte count and transfer CRC, then calls
`esp_ota_end` (`0x4205a9dc`, image verification) and
`esp_ota_set_boot_partition` (`0x4205aa64`). It only switches the UI asset bank
if a separate UI asset transfer completed, so an application-only transfer is
supported by the code. This is acceptance-path evidence, not a successful
device test; bootloader signature requirements and installed asset compatibility
remain unverified.

Recovery is weaker than merely having two app slots implies. Startup initializes
UART via `0x42026070`, which calls `0x42025c00`; that function selects the next
application partition and calls `esp_ota_begin` with size `0xffffffff`. The
[official ESP-IDF v5.1-rc1 source](https://github.com/espressif/esp-idf/blob/v5.1-rc1/components/app_update/esp_ota_ops.c)
erases the entire destination partition for that size. The same setup can erase
the inactive `storage_1` or `storage_2` UI bank when it is not empty. Furthermore,
the compiled boot-selection routine writes `ESP_OTA_IMG_UNDEFINED` (`-1`) to
the OTA state, consistent with automatic rollback being disabled in this build.
Thus a preserved old image and automatic rollback cannot be assumed.

The official ESP application descriptor identifies project `esp32s3_UI`, build
`8f602a4-dirty`, date September 11, 2024, ESP-IDF `v5.1-rc1`, and security version
0. These describe the downloaded file, not the version installed on the knob.
The physical device's About/Firmware screen is currently the safest way to read
its installed version; no verified read-only BLE/UCP version query has been
identified. No OTA begin/data/end/reset commands have been issued.

### Configuration audit after clock/weather success

Clock and date synchronization succeeded independently of localization. The
user also confirmed an English outdoor temperature value. Neither changes the
built-in calendar/month or relay on/off language.

The recovered namespace 1 inner `050x` dispatcher (`0x4200c980`) recognizes
subcommands 1, 5, 6, 7, 8, and 9: night mode, scene/device configuration, clock,
and weather data. It contains no language setter; unsupported subcommands return
without updating language. The fully mapped ESP decompilation references the
language-prefix global only when reading it for settings initialization and
asset loading, with no identified setter.

The file writer at `0x4201b2e4` builds paths only for type 1 scene labels and
type 2 device labels, with indices below 16. Supplying another type does not
select an arbitrary asset: it leaves a filename buffer uninitialized. Therefore
extending the working label uploader with guessed image types is not a safe
route to replacing built-in status or calendar images.

No verified reversible language configuration or on-device language API was
found. English relay names, working clock synchronization, and English outdoor
temperature remain available; native month/calendar and on/off translation is
still limited by the firmware default and the lack of verified recovery for a
firmware change. This remains an explicitly incomplete part of the user's goal.

### Application-side acceptance verified offline

The user subsequently reported that the physical firmware screen appears to
show version 1.4.25, matching the downloaded release. This is stronger version
evidence, but does not establish the installed ESP image's exact build hash.

A read-only Ghidra export of the application's ESP-IDF OTA and image-verification
functions is saved at `/tmp/yeegate-esp32-sdk-decompiled.c`. The verifier
`0x42060b38`, called by `esp_image_verify` at `0x42060ca4`, checks the image header,
segments, XOR checksum, and appended SHA-256. Its final check computes SHA-256
and compares 32 bytes with the appended digest. This matches the simple-hash
branch of the
[official ESP-IDF v5.1-rc1 image verifier](https://github.com/espressif/esp-idf/blob/v5.1-rc1/components/bootloader_support/src/esp_image_format.c),
compiled with application signature checking disabled; no signature-verification
branch appears in this application code path.

The native candidate preserves the header and segment sizes and has valid XOR,
SHA-256, and transfer CRC values. Thus it meets the recovered application's
software integrity checks. The actual device's bootloader and hardware fuses
have not been read, and no OTA operation has been attempted. This does not
establish a recovery path: the compiled `esp_ota_begin` code confirms whole-bank
erasure for the startup argument `0xffffffff`, and its boot selection records
`ESP_OTA_IMG_UNDEFINED` rather than a pending-verification state. There is still
no verified safe firmware rollback for the user's unit.


### English HA light entry

The label uploader now also accepts the verified third device image slot
(index 2), limited to the exact label HA Lights. Its vendor-rendered image was
uploaded and physically confirmed English. Holding that icon opens the light
percentage ring; the user confirmed it can reach 0% and 100%. This is display
interaction, and Home Assistant routing remains blocked by encrypted commands.
The native Chinese on/off and settings resources remain unchanged, with
flashing on hold until a recovery path is verified, as the user requested.

### Authorized English OTA attempt — 12 October 2026

After the recovery limitations were explained, the user explicitly requested a
simple English OTA attempt and then confirmed “okay lets try the OTA flash”.
Official OTA authentication succeeded on the Pi. The transfer uses only the
1,052,544-byte native ESP candidate, pinned to SHA-256
`54a2be6c16a53bff7fd5e37dce7d25809d9f0b11c21b5b3f3133ab524d149c2a`.
The exact 35-byte change is documented in [the firmware diff](knob-english-firmware-diff.md).
The English-only change does not add Home Assistant light routing.

`tools/flash_knob_english.py` uses the official authenticated OTA data service,
with an `espf` header, raw IEEE CRC32, 200-byte chunks and ordinary ATT responses.
It does not retry data chunks. The final nonempty chunk is translated by BG21
to ESP UCP opcode 3; all generated UCP flags are zero. BG21 control `03` is
omitted because it schedules a separate Bluetooth bootloader installation path.
The native-only transfer does not enter the update screen; automatic restart
is not established for this path. A normal power cycle and physical language
check may be needed. See
[the transport review](firmware-ota-plan.md) for recovered addresses and limits.

The sender completed all 1,052,544 bytes without an exception in 756 seconds,
waited 10 seconds, and disconnected. No BG21 control `03` was sent. Boot
acceptance and screen language are not yet verified; the user was asked to
perform a normal external power cycle and check Settings and relay status text.
Home Assistant bridge was paused for exclusive BLE access and will be resumed
following the attempt. Hardware recovery remains unverified.

### Physical result confirmed

After a normal external power cycle, the user confirmed “Booted, menus are
English” for Settings and relay On/Off text. The native language patch is now
physically verified running. Exact installed flash bytes were not read back.
The local bridge is started again at version 0.3.4; its logs confirm renewed
clock and outdoor-temperature/weather-icon synchronization. Temporary OTA files
and the private deployment bundle were removed from the Pi, and the original
SSH options were restored and compared successfully. Home Assistant light
rotation routing remains a separate unresolved task.
