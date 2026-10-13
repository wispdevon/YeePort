# Changelog

## 0.8.0 — 2026-10-13

### Added

- **Open Web UI** light importer inside Home Assistant: choose lights or
  groups, name their English menu entries, and import or remove them yourself.
- Local English label rendering using the private `display_device_key`.
- Independent imported-light controls and saved `imported_lights` records.

The verified eight-entry menu allows two imports alongside the current six
controls, or five with separate brightness controls disabled. New imports
briefly restart the bridge and become active after display synchronization.

## 0.7.0 — 2026-10-13

### Added

- Optional full-color **HA Lights** entry alongside RGB Lights, Warm White,
  and Red 10%, controlling the same Home Assistant light group.
- Whole-group brightness preserves the current RGB/white mix; color and
  temperature controls retain their existing behavior.

Enable `ha_lights_menu_enabled` with `separate_brightness_controls` to use
the extra entry. Upload its private English label at device-image index 5.
