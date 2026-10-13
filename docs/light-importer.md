# Import Home Assistant lights into the S Knob

YeePort 0.8.0 includes a light importer inside Home Assistant.

1. Open the **YeePort S Knob** app/add-on page and click **Open Web UI**.
2. Choose a Home Assistant light or light group.
3. Enter an English menu name of up to 24 characters.
4. Click **Import to knob** and wait for **Menu updated**.
5. Scroll to the new entry on the knob and hold its icon to open its controls.

The bridge briefly restarts when applying a change. Keep the knob awake and
within Bluetooth range. The page reconnects automatically and reports when
the display update succeeds. Use **Remove** beside an imported light to remove
its entry. Settings survive restarts in the app's `imported_lights` option.

## Available space and controls

The verified menu format supports **eight entries**. The current layout uses
six: Relay 1, Relay 2, RGB Lights, Warm White, Red 10%, and HA Lights. This
leaves room for **two imports**. A light group uses one entry and controls all
its available members. To make more room, disable `separate_brightness_controls`
in the app configuration: the menu then retains both relays and HA Lights,
leaving five import slots.

The importer derives controls from Home Assistant's supported color modes:

| Entity capability | Knob controls |
| --- | --- |
| RGB color and white temperature | Brightness, RGB, white temperature, on/off |
| Dimmable | Brightness and on/off |
| On/off only | Toggle |

Each imported entry targets its selected entity, independently of the main
HA Lights group. Color selection clears native RGBW/RGBWW white channels,
consistent with the existing pure-color controls. Unsupported controls aren't
offered. Unavailable entities are marked in the chooser.

## One-time private setup

The owner's installation is already configured. For another provisioned unit,
set `display_device_key` to the same private 32-hex-character `device_key` used
in its successful label-upload bundle. This is separate from the network key,
application key, and factory secret. Keep all key fields private.

Labels are rendered locally as English 240×48 RGBA PNGs and sent through the
verified authenticated label-upload codec. Adding entries does not require a
Yeelight login. The web interface exposes light choices and menu records,
and never returns the private key/options object. It runs behind
[Home Assistant ingress](https://developers.home-assistant.io/docs/apps/presentation/#ingress).

## Verification

The local suite covers menu capacity, duplicate/invalid targets, supported
controls, local PNG shape, authenticated slot routing, synchronization gating,
independent targets, and API validation/persistence/credential isolation.
Browser checks exercised import, removal, required-field validation, keyboard
navigation and a 320-pixel mobile layout with no application console errors.
The in-app browser was unavailable; these checks used local Chromium with an
in-memory Home Assistant/Supervisor fixture. Live Pi verification is recorded
in [the bridge work log](knob-local-bridge.md).

The owner confirmed a real import appears on the physical knob and controls
the selected light. Local English labels are verified on this unit.
