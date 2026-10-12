# YeeGate S Knob

Version 0.5.1 decrypts and authenticates this provisioned S Knob's light commands
locally. Its third entry, **HA Lights**, controls the configured Home Assistant
light group. Clock and weather synchronization remain local. No Yeelight login
or cloud credentials are used during operation.

## Use the knob

Scroll to **HA Lights**. Hold its icon to open the brightness ring, then rotate
clockwise to brighten or counterclockwise to dim. The decoded percentage is
applied to the selected Home Assistant group. Zero percent turns the group off.
The entry's on/off commands also control that group. Relay 1 and Relay 2 are not
mapped by this light-control feature.

Enable `color_controls_enabled` for the built-in full-color light interface.
The existing English **HA Lights** entry then exposes brightness, white color
temperature and RGB color controls. Color commands use Home Assistant's
`rgb_color`; temperature commands use `color_temp_kelvin`. Individual lights
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
