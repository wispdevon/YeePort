# Changelog

## 0.7.0 — 2026-10-13

### Added

- Optional full-color **HA Lights** entry alongside RGB Lights, Warm White,
  and Red 10%, controlling the same Home Assistant light group.
- Whole-group brightness preserves the current RGB/white mix; color and
  temperature controls retain their existing behavior.

Enable `ha_lights_menu_enabled` with `separate_brightness_controls` to use
the extra entry. Upload its private English label at device-image index 5.
