# YeePort replication guide

This guide describes the verified YeePort result and what another owner would
need to reproduce it. The success was with a Yeelight Pro S Knob, product ID
1574912, on Home Assistant OS on a Raspberry Pi. It was the physical knob's
local Mesh bridge, not a gateway emulator registered through the Yeelight app.

## What is verified

The owner confirmed the following on the physical unit with bridge 0.5.1;
0.5.2 adds explicit RGB-only channel selection:

- The knob's English **HA Lights** entry controls a Home Assistant light group.
  Hold the entry's icon to open controls; brightness, on/off, RGB color and
  Kelvin temperature were confirmed working.
- Home Assistant exposes English, assignable triggers for authenticated
  brightness, on, off, color and color-temperature commands. Generic Mesh
  activity is also available for diagnostics, but it does not identify a
  distinct press or gesture.
- Bangkok clock/date and outdoor temperature/weather updates work. Weather
  icons depend on assets already installed on this knob; unsupported
  conditions have no matching icon.
- Optional bridge-side brightness scaling uses authenticated command timing.
  The configured and software-tested curve was a linear ramp from 1× at 2
  percentage points per second to 4× at 12 points per second, returning to 1×
  after an idle pause. The physical feel of this curve has not been confirmed.
  The displayed ring catches up after the turn.

Haptic strength has no verified setting. Effects are not implemented.

Version 0.6.1 adds an optional separate menu with RGB Lights, Warm White and
Red 10%. Enable `separate_brightness_controls` to use it. With `independent_channels` enabled, each ring preserves the other channel's
level on native RGBW/RGBWW devices. RGB-only devices follow RGB while it is
above zero and use warm-white temperature mode when RGB is zero;
`warm_white_kelvin` defaults to 2700 K for this fallback. Create a persistent HA
scene with pure-red native RGB/RGBW/RGBWW values, zero white channels, brightness
26 out of 255, and state on for the target members. Point `preset_scene` at its
entity ID. The owner's scene is `scene.usual_red_10`, named Usual Red 10%.
These HA actions were exercised successfully and the English labels uploaded;
the owner confirmed the English entries and live RGB/preset commands.
Independent blending passed live HA tests. The owner also confirmed the physical
Warm White ring increases white light while RGB stays on.
See the [bridge guide](../knob_bridge/DOCS.md#red-preset-and-separate-menu-labels)
for the private, one-time label bundle. No firmware flash is part of this change.

In 0.5.2, color commands address each available group member using its native
RGB/RGBW/RGBWW field, explicitly zeroing white channels and leaving brightness
unchanged. A live API check verified zero white channels on both Wiz devices
and unchanged brightness on all three available color lights. Temperature mode
continues to use warm/cool white channels independently.

## Requirements

A replication attempt needs a compatible Yeelight Pro S Knob, a Home Assistant
OS host with Bluetooth in range, the Mosquitto add-on and MQTT integration, and
an owner-provisioned knob. The bridge's Home Assistant add-on needs host D-Bus,
Bluetooth monitor permissions, and the Supervisor API. Its manifest targets
`aarch64` and `amd64`.

The source defaults deliberately have empty Mesh keys, disabled light control,
and a placeholder light group. The verified unit required its own network key,
application key, IV index and node unicast address. These are not included here
and cannot be substituted from another knob or installation. Create a Home
Assistant light group that names the lights to control, then configure
`light_entity` to that group. The verified group was `light.knob_lights`.

## Verified deployment path

For the tested Home Assistant OS setup, the bridge directory was copied to
`/addons/yeegate_knob`, the local add-on store was reloaded, and **YeeGate S
Knob** was installed and started. Mosquitto and the MQTT integration were
already installed. The app used Supervisor broker credentials (blank MQTT host)
and the Home Assistant API for weather. These are the deployment steps recorded
for the working Pi installation; they have not been validated against a clean,
unconfigured Home Assistant instance.

In the add-on configuration, an owner must supply their own Mesh keys and
addressing values, choose the target light group, and enable light control.
`color_controls_enabled` enables the full-color controls, and
`brightness_speed_scaling` enables the optional speed response. The tested
add-on retains its legacy name **YeeGate S Knob** and slug `yeegate_knob`; the
name has not been changed as part of the project rename. The defaults
remain conservative and do not activate light control without keys and an
explicit target. See [the add-on guide](../knob_bridge/DOCS.md) for the
configuration fields, Home Assistant trigger names, and runtime behavior.

## Provisioning and keys

The owner added the physical knob to their Yeelight account through the vendor
app as a one-time provisioning step. The bridge itself uses no Yeelight login
or cloud credentials at runtime.

The repository does not automate device/catalog retrieval from a new Yeelight
account. The cloud helpers implement individual API requests, but another owner
must identify their own knob and prepare the device record, OTA config, and
saved handshake response used by the tools. A successful QR login alone does
not create those inputs or recover Mesh keys.

The keys needed by local control were recovered for this specific unit through
an authenticated, temporary BG21 diagnostic OTA, then the unit's stock BG21
firmware was restored. The recovered keys authenticated both the network and
application MICs in the captured light commands. The diagnostic image and the
stock image are not part of this repository. Neither the login flow nor account
binding alone yielded the plain Mesh keys.

This repository does not offer a safe, generic firmware-flashing recipe. The
recovery work was specific to firmware 1.4.25 and the owner's exact unit. The
knob is wall-powered, a recovery or rollback path has not been verified, and a
failed diagnostic OTA can leave BLE access unavailable. The diagnostic OTA
recovers the per-unit factory secret; its prerequisites are the owner's
authenticated device key, the saved binding response, and an interaction
capture. An owner-side verified stock image of the exact version is also
required for restoration. The diagnostic utility pins the exact original
image hash. Do not use a firmware blob or key from another unit.

## Recorded command entrypoints

The commands below record successful entrypoints and flags from work on this
unit. Firmware commands are historical records, not instructions to try on a
different knob. The commands have not been rerun on fresh hardware for this
guide. Replace uppercase placeholders with paths and values belonging to your
own setup; never paste credentials, keys, or recovered responses into a public
issue or commit.

Keep every private input/output outside the checkout and replace placeholders
with absolute paths. Never reuse this repository's example values as credentials.

### Local and offline commands

These do not contact the physical knob. Keep generated images, decoded output,
captures and key files in a private working directory.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/prepare_knob_english_analysis.py OFFICIAL_1425_PACKAGE OUTPUT.analysis.bin
.venv/bin/python tools/prepare_bg21_key_export.py OFFICIAL_1425_PACKAGE OUTPUT.analysis.gbl
.venv/bin/python tools/decode_knob_mesh.py --keys PRIVATE_KEYS.json --capture PRIVATE_CAPTURE.jsonl --output PRIVATE_DECODED.jsonl
```

The two preparation tools only create offline analysis candidates. They pin
the expected original image hashes; their output is not proof of firmware
acceptance or rollback. The decoder requires the recovered keys and writes
output exclusively to a new private file. Its access messages must pass both
Mesh MIC checks before they are accepted as decoded commands.

### Account and provisioning entrypoints

The QR login command used the Singapore region. It saves the login response to
`~/.local/state/yeegate/credentials.json` with private permissions and creates
`yeelight-login.png` in the current directory by default. The QR image and
credentials must remain private.

```sh
.venv/bin/python tools/yeelight_login.py --region sg
.venv/bin/python tools/authenticate_knob.py --provision
```

`authenticate_knob.py` reads `knob-device.json` next to the private credentials
file and, with `--provision`, sends the vendor binding response to the physical
knob. It saves private `knob-authentication.json`,
`knob-binding-confirmation.json`, and `knob-bound-detail.json` files beside the
credentials. Do not run it against a knob unless you intend vendor provisioning
for that device. This is not a general Mesh-key export operation.

The following are the minimum input shapes used by the tools, with placeholders
only. The QR login's token values are private:

```json
{
  "region": "sg",
  "token": { "accessToken": "PRIVATE_TOKEN", "clientId": "OPTIONAL_CLIENT_ID" }
}
```

The owner-prepared device record uses these fields:

```json
{
  "did": 1234567,
  "deviceId": "PRIVATE_DEVICE_ID",
  "houseId": "PRIVATE_HOUSE_ID",
  "pid": 1574912,
  "mac": "OWNER_KNOB_MAC"
}
```

The owner-prepared OTA config uses these fields:

```json
{ "address": "OWNER_KNOB_MAC", "device_key": "32_HEX_CHAR_PRIVATE_KEY" }
```

The device ID, house ID, device key and MAC above are examples of field types,
not values to copy. The `device_key` is separate from the network and
application keys.

For key recovery, the saved `knob-authentication.json` handshake response must
contain the encoded binding under this field path:

```json
{ "data": { "encryptResult": "BASE64_PRIVATE_BINDING_BLOB" } }
```

### Firmware research entrypoints — high risk

These commands write firmware to the physical unit. They are included to record
what the project used, not as a safe or universal procedure. The S Knob is
wall-powered. No verified recovery or rollback path exists for a failed
BG21 OTA, and loss of BLE access is possible. The tools hardcode the tested
unit's address and the BG21 utility accepts only pinned image hashes tied to
S Knob 1.4.25. The offline BG21 builder pins the official package SHA-256 to
`6ac92c8095206498b1762b6fdd2669148caed9d18b2c08a3b0eaef92c52fddd5`; the
updater separately pins the diagnostic candidate and exact official restore
GBL hashes in source. Do not substitute a different unit, firmware version,
or image.

The English display path used the offline builder followed by its separately
validated native ESP image. The OTA accepts only the pinned candidate hash and
requires a physical boot/display check afterward:

```sh
.venv/bin/python tools/flash_knob_english.py --config PRIVATE_OTA_CONFIG.json --image PRIVATE_ENGLISH_ESP.analysis.bin --result PRIVATE_ESP_RESULT.json --flash
```

The diagnostic BG21 candidate was made offline from the exact official 1.4.25
package. The following command is the recorded diagnostic transfer form; the
fresh-power-cycle flag is mandatory. The tool makes one upload attempt and does
not retry chunks:

```sh
.venv/bin/python tools/flash_knob_bg21.py --config PRIVATE_OTA_CONFIG.json --image PRIVATE_DIAGNOSTIC.analysis.gbl --result PRIVATE_DIAGNOSTIC_RESULT.json --flash --fresh-power-cycle-confirmed
```

On this unit, both diagnostic and stock transfers sent every byte, but the
final control `03` write returned ATT Unlikely Error (`0x0e`). The diagnostic
export on a new authenticated connection established that the diagnostic
application had booted. After restoration, a new authenticated connection with
no diagnostic export established stock notification behavior. Neither a
completed upload nor that final ATT error alone proves installation success
or failure. We did not retry data chunks. Exact installed flash bytes were
not read back.

With the authenticated diagnostic application running, the read tool performs
authentication only and saves the factory secret and recovered keys as new
private files. `PRIVATE_BINDING_RESPONSE.json` must be the saved vendor
handshake response containing `data.encryptResult`; `PRIVATE_CAPTURE.jsonl`
must be a capture from this same knob. The CLI refuses to overwrite existing
secret/key output files.

```sh
.venv/bin/python tools/read_knob_factory_secret.py --config PRIVATE_OTA_CONFIG.json --binding PRIVATE_BINDING_RESPONSE.json --capture PRIVATE_CAPTURE.jsonl --secret-output PRIVATE_FACTORY_SECRET.bin --keys-output PRIVATE_KEYS.json
```

The recorded sequence restored the exact owner-verified stock BG21 GBL using
the same single-attempt updater after confirming a fresh BG21 boot. Restoration
must also use a stock image for the exact version. No stock-image acquisition
or extraction command is provided here. This records the updater invocation
shape; use only the exact stock GBL already verified for the owner's unit:

```sh
.venv/bin/python tools/flash_knob_bg21.py --config PRIVATE_OTA_CONFIG.json --image OWNER_VERIFIED_STOCK.bg21.gbl --result PRIVATE_RESTORE_RESULT.json --flash --fresh-power-cycle-confirmed
```

The subsequent no-write check was:

```sh
.venv/bin/python tools/probe_knob_ota.py --config PRIVATE_OTA_CONFIG.json --verify-stock
```

The key-recovery utility verifies the network MIC against real packets. The
following offline decode then verifies the access/application MICs before
classifying light commands:

```sh
.venv/bin/python tools/decode_knob_mesh.py --keys PRIVATE_KEYS.json --capture PRIVATE_CAPTURE.jsonl --output PRIVATE_DECODED.jsonl
```

The generated key JSON has this shape; values are intentionally omitted:

```json
{
  "address": "OWNER_KNOB_MAC",
  "net_key": "PRIVATE_32_HEX_CHAR_KEY",
  "app_key": "PRIVATE_32_HEX_CHAR_KEY",
  "device_key": "PRIVATE_32_HEX_CHAR_KEY",
  "iv_index": 0,
  "unicast_address": 1,
  "nid": 0,
  "authenticated_packets": 0,
  "application_mic_verified": false
}
```

The recovery output's `application_mic_verified` is false because that tool
validates network authentication; the later decoder performs access MIC
verification. Never publish this JSON.

### Deployment transfer used on the Pi

The tested deployment copied the add-on source into an already-created
`/addons/yeegate_knob` directory on the configured Home Assistant host. An
owner-specific SSH key option was used and is represented here by `SSH_KEY`;
the destination host and existing installation are also placeholders. This
does not bootstrap or configure a clean Home Assistant OS installation.

```sh
tar -C knob_bridge --exclude=__pycache__ -cf - . | ssh -i SSH_KEY hassio@HA_HOST 'tar -xf - -C /addons/yeegate_knob'
```

After the copy, the local add-on store was reloaded and **YeeGate S Knob** was
installed and started in Home Assistant. The tested install used Supervisor
MQTT credentials and the Home Assistant API for weather. See
[the add-on guide](../knob_bridge/DOCS.md) for the runtime configuration.

## Current reproducibility limits

This checkout is not yet a general-purpose integration:

- The owner's Bluetooth address is hardcoded in several bridge and research
  files. Changing only the add-on `address` setting does not make another unit
  supported; device checks and filters must also be reviewed and adapted.
- The bridge expects the owner's Mesh network/application keys, IV index and
  node address. It does not provision a new knob or export these values.
- The exact diagnostic OTA and rollback process has not been validated as a
  safe procedure for another device or firmware version.
- Clean-instance Home Assistant installation has not been recorded. The
  deployment steps above describe the tested Pi, not a universal setup guide.
- Available screen icons and device-side language depend on the knob's firmware
  and resources. English firmware was installed and confirmed on the tested
  device; no firmware image is distributed here.

For those reasons, treat this as a documented working setup and research base,
not a promise of plug-and-play compatibility or a universal knob recipe.

## Public repository hygiene

Never commit firmware blobs, generated Yeelight/vendor images, QR login images,
account or provisioning responses, keys, credentials, raw Bluetooth captures,
or logs. Captures can expose device identifiers and provisioning or ciphertext
data even when the payload is not readable. `.gitignore` covers common local
artifacts, but it cannot recognize every sensitive file and does not remove
files already tracked. Review the complete staged file list before publishing.
