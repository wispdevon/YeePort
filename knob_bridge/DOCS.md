# YeeGate S Knob

Version 0.6.1 decrypts and authenticates this provisioned S Knob's light commands
locally. Its third entry, **HA Lights**, controls the configured Home Assistant
light group. Clock and weather synchronization remain local. No Yeelight login
or cloud credentials are used during operation.

## Use the knob

With `separate_brightness_controls` enabled, the menu has **RGB Lights**,
**Warm White**, and a **Red 10%** preset entry after the two relays. Hold either
light icon to open its brightness ring. With `independent_channels` enabled,
RGB Lights changes RGB intensity while preserving warm-white intensity, and
Warm White changes the warm LED intensity while preserving RGB. Turning either
channel to zero leaves the other running. Both zero turns the lights off.

The two Wiz lights expose native RGBW/RGBWW channels and support this blend.
The YN bar exposes RGB and temperature as separate modes: it follows RGB while
RGB is above zero, then follows warm white when RGB is zero. The warm fallback
uses `warm_white_kelvin` (2700 K by default). The bridge reconstructs each
channel's effective brightness from native color values and master brightness
for the two rings; HA's ordinary brightness attribute is the shared master level.

The preset entry activates the persistent Home Assistant scene configured in
`preset_scene`, normally `scene.usual_red_10`, and resets RGB to 10% and warm
white to zero. This scene must exist in HA. Disabling `independent_channels`
uses the earlier behavior in which each brightness entry selects its mode.

The original HA Lights menu described below remains available when
`separate_brightness_controls` is disabled.

Scroll to **HA Lights**. Hold its icon to open the brightness ring, then rotate
clockwise to brighten or counterclockwise to dim. The decoded percentage is
applied to the selected Home Assistant group. Zero percent turns the group off.
The entry's on/off commands also control that group. Relay 1 and Relay 2 are not
mapped by this light-control feature.

Enable `color_controls_enabled` for the built-in full-color light interface.
The existing English **HA Lights** entry then exposes brightness, white color
temperature and RGB color controls. Color targets each available member in its
native mode: `rgbww_color: [R,G,B,0,0]`, `rgbw_color: [R,G,B,0]`, or
`rgb_color: [R,G,B]`. This explicitly switches off warm/cool white LEDs instead
of letting a mixed light group convert color into white-channel output.
Color changes preserve each light's brightness; brightness changes then dim
the selected RGB color. Temperature commands separately use `color_temp_kelvin`. Individual lights
may have different supported ranges or be unavailable. Changing color does not
explicitly change brightness. This feature is recovered from firmware handlers
4200df84 and 4200d25c; the owner confirmed physical color/temperature control.

## Rotation response and feedback

Set `brightness_speed_scaling` to true for fine slow turns and larger fast
changes. `brightness_maximum_gain` (1–8, default 4) sets the maximum gain.
The gain ramps linearly from 1× at two percentage points per second to the
maximum at twelve points per second, using authenticated command arrival times.
After a pause longer than 0.6 seconds, the next change uses 1×. Endpoints remain
0% and 100%. This estimates speed from percentage changes, not raw encoder
detents, and radio packet loss can affect it.

This scales Home Assistant brightness. During rotation, the physical ring
continues to follow the firmware's own curve; after three seconds idle, state
feedback aligns it with HA. Set `brightness_speed_scaling` to false for the
original absolute-percentage behavior. These options do not change physical
vibration or resistance. No verified haptic strength command has been found;
the on-device Sounds setting is separate.

The installed target `light.knob_lights` contains the four dashboard lights:
Wiz Bulb, Wiz Strip, YN Light Bar and Light1. No extra automation is needed for
this default behavior. Change `light_entity` in the app configuration to select
another specific light/group, or disable `light_control_enabled` to use custom
automations instead.

The bridge reads the group's current state every five seconds, sends changes
to the knob when it is idle, and refreshes its display cache every thirty
seconds. This restores the entry after a knob reboot. Feedback waits while a
command is being applied and for three seconds after rotation, so it does not
replace the ring value during an active turn.

## Assign Home Assistant actions

Open Settings → Automations & scenes, create an automation, choose a Device
trigger, then select **Knob**. Authenticated triggers are **Brightness changed**,
**Light turned on**, **Light turned off**, **Color changed** and
**Color temperature changed**, with subtype **HA Lights**.
Home Assistant also exposes `event.knob_light_command`; its event attributes
include command kind, value, slot and sequence. Brightness values are absolute
percentages, with `raw_percentage` preserving the knob's original value when
speed scaling is enabled. Separate press/hold triggers are not decoded.

The older Mesh activity trigger and `event.knob_mesh_activity` remain available
for diagnostics. Periodic status traffic can produce those generic events;
use the authenticated light-command triggers for control automations.

## Install and configure

Install the Mosquitto broker app and MQTT integration. Copy this directory to
HAOS `/addons/yeegate_knob`, reload the app store, install/update YeeGate S Knob,
and start it. Keep the knob within Bluetooth range of the Pi. The app uses host
Bluetooth/D-Bus access and NET_ADMIN/NET_RAW; AppArmor is disabled in this
experimental build.

Leave MQTT host blank for Supervisor broker credentials, or supply the external
broker settings. Configure the verified `mesh_net_key`, `mesh_app_key`,
`mesh_iv_index` and `mesh_unicast_address` from the private recovery file.
The key fields use password inputs and must remain private. The verified
publication destination for this unit is 65278 and HA Lights is slot 3.
Enable `light_control_enabled` only with valid keys and a specific `light_entity`.

Both network and application MICs, physical BLE MAC, source address,
publication destination, vendor opcode, slot and command format are checked.
Duplicate/out-of-order commands are rejected, and the last accepted sequence
is saved under `/data/mesh-sequence.json` to prevent reapplication after an app
restart. Rapid commands share one worker and combine into the newest requested
state. Failed service calls are logged and not retried as stale commands.

Reprovisioning or a Mesh IV-index change requires matching key/configuration
updates; this release does not automate network credential refresh.

## Red preset and separate-menu labels

The installed **Usual Red 10%** scene contains the four target lights with
brightness 26 out of 255, pure RGB red, and zero white channels. It is saved in
HA's scene configuration and survives scene reloads/restarts. Activate it from
Settings → Automations & scenes → Scenes, or target `scene.usual_red_10` in an
automation. Unavailable members receive their desired state when a later
activation finds them available; activating a scene does not queue retries.

The new device-menu labels use the existing authenticated image-upload codec.
An owner-prepared, mode-0600 bundle at `/share/yeeport-display-labels.json`
contains `address`, `device_key`, and `labels`, with exact index/name pairs
2/`RGB Lights`, 3/`Warm White`, and 4/`Red 10%`. Each label's `png` is its
base64 vendor-rendered PNG. The app mounts `/share`, uploads only those bounded
device-image slots during initial menu setup, then deletes the bundle. Keep
this file private; the package and repository contain no label images or keys.

The owner confirmed the three new English entries are visible. Authenticated
RGB ring and preset presses have reached HA and executed successfully. A live
blend test verified RGB 10% + warm 15%, then RGB 20% with warm still 15%, and
preset restoration to RGB 10% + warm 0%. The owner confirmed the physical
Warm White ring works and both RGB and warm white stay on together.
The prior single-entry color/temperature UI is physically verified.

## Clock, weather and screen language

Clock synchronization runs at startup and hourly using `timezone`
(Asia/Bangkok by default). Outdoor weather reads `weather.forecast_home` every
five minutes through the app's internal Home Assistant API access. Changed
readings/icons are sent, with an hourly refresh. Missing/stale readings preserve
the last display. Clock, weather and light feedback serialize BLE connections
and reuse the active scan.

This unit's native English menus were verified after the separate English ESP
OTA. The bridge package does not include firmware or change the screen language.
The English relay and HA Lights names were uploaded separately.

Only one bridge instance per knob should run. For standalone Linux, MQTT event
publishing is available with a private options file; automatic HA light control
and weather feedback require the Home Assistant app API environment.

Home Assistant service calls follow its [REST API](https://developers.home-assistant.io/docs/api/rest/).
