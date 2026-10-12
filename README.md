# YeePort

YeePort connects a **Yeelight Pro S Knob** to **Home Assistant OS** over local
Bluetooth Mesh. Use the knob to control your HA lights' brightness, color and
white temperature, with English menus and local clock/weather updates.

Verified on one S Knob (product ID **1574912**, firmware **1.4.25**) and a
Raspberry Pi running HAOS. One-time setup used a Yeelight account; normal
operation uses your local HA/MQTT services. Other Yeelight Pro devices have
not been validated.

## Verified result

The owner confirmed that the knob's English **HA Lights** screen controls the
Home Assistant group `light.knob_lights`: brightness, on/off, RGB color and
Kelvin color temperature all work. On the knob, scroll to **HA Lights** and
hold its icon to open the controls. The bridge release is version 0.5.2.

Color mode explicitly zeros RGBW/RGBWW white channels and preserves brightness.
Use its brightness ring to dim the selected RGB color; use temperature control
separately for warm/cool white lighting.

The bridge also publishes assignable English Home Assistant triggers for
authenticated knob light commands, synchronizes Bangkok time/date, and updates
outdoor temperature and available weather icons from Home Assistant. Optional
brightness speed scaling applies a linear Home Assistant-side ramp from 1× at
2 percentage points per second to a maximum gain of 4× at 12 points per second.
The scaling logic and curve were tested; the user's physical feel of that curve
has not been confirmed. The knob's own ring catches up to Home Assistant after
the turn ends. Haptic strength is not verified as configurable, and knob effects
are not implemented.

## Deployment and replication

The package and the setup's known limits are documented in
[the replication guide](docs/replication-guide.md). Home Assistant add-on
installation and controls are described in [the bridge guide](knob_bridge/DOCS.md).
This repository is a research implementation tied to one physical unit; it is
not a plug-and-play integration for arbitrary knobs. In particular, its
Bluetooth address is still fixed to the owner's device in several source files.

## Commands we used

For the Python tools, create a virtual environment and install the project and
bridge dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r knob_bridge/requirements.txt
```

These are tested entrypoints from the project work. The first runs the local
unit suite; the next two build offline analysis artifacts and the last decodes
a private capture without contacting the knob or Home Assistant. Replace each
uppercase path placeholder with your own file path:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/prepare_knob_english_analysis.py OFFICIAL_1425_PACKAGE OUTPUT.analysis.bin
.venv/bin/python tools/prepare_bg21_key_export.py OFFICIAL_1425_PACKAGE OUTPUT.analysis.gbl
.venv/bin/python tools/decode_knob_mesh.py --keys PRIVATE_KEYS.json --capture PRIVATE_CAPTURE.jsonl --output PRIVATE_DECODED.jsonl
```

The dependency installation and public-source tests were checked in a fresh
virtual environment. Tests requiring private captures or an external firmware
reference skip when those inputs are absent. The full owner's 16-test suite
also passed. Firmware builders reproduced the exact candidate hashes used on
the device, and offline decoding revalidated all 57 brightness-capture packets.
These checks do not repeat firmware flashing.

The hardware and deployment command record is in the [replication guide](docs/replication-guide.md#recorded-command-entrypoints).

## Repository map

- `knob_bridge/` — Home Assistant add-on source, configuration defaults and
  user-facing installation guide.
- `docs/replication-guide.md` — what was verified, prerequisites, and the
  current device-specific and recovery limits.
- `docs/` — protocol investigation and dated research records. Some documents
  describe earlier stages and are historical; the verified current behavior is
  summarized above and in the replication guide.
- `tools/` — research, capture and device-maintenance tools. Several operate on
  the physical knob and are specific to the owner's unit; inspect their source
  before use.

The Home Assistant add-on retains its tested legacy name, **YeeGate S Knob**,
and slug `yeegate_knob`. These names are part of the working deployment and are
not a claim that this project implements a gateway emulator.

## Public release contents

Do not publish device firmware, generated vendor images, account responses,
provisioning captures, Bluetooth captures, logs, or credential/key files.
Use the repository's `.gitignore` and review every staged file before a public
release. Mesh keys and vendor account credentials are not included in this
repository; each owner must use their own credentials and device-specific keys.
