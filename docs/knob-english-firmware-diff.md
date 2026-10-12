# S Knob English firmware byte diff

Reference: official Yeelight S Knob v1.4.25 ESP application extracted from the verified vendor package. The installed device reports v1.4.25, but no firmware read-back was obtained; this is not a comparison against a physical flash dump.

Both applications are 1,052,544 bytes. Exactly 35 bytes differ. Offsets below are relative to the native ESP application, not the outer vendor container.

```diff
# Language resource prefix at 0x00007e6c
- 7a 68 00  # "zh\0"
+ 65 6e 00  # "en\0"

# ESP XOR checksum at 0x00100f5f
- 57
+ 4e

# Embedded image SHA-256 at 0x00100f60 (32 bytes)
- a6db48d54d3dc6e4c1ba7ba11ebfe2714a842b4ca808485a1aa95c0039ab2bfb
+ af7a5abdec16b65f5d4026ffa5d73c31365733131cdb424ec642229e3bf8382b
```

The only functional change is the two-byte language prefix. The other 33 changed bytes repair the image checksum and embedded SHA-256. The patch selects existing English UI resources; it does not replace assets, add Mesh decoding, change light-control logic, or modify executable instructions. All bytes outside these positions match the official application.

File SHA-256:

- Reference: `ef462d036dc1c3ec2e42902e517a9a2f1215a376571940130224261dc131d1f8`
- Candidate: `54a2be6c16a53bff7fd5e37dce7d25809d9f0b11c21b5b3f3133ab524d149c2a`

The prepared full vendor-container candidate retains identical UI assets and BG21 firmware, but its outer integrity mechanism is unverified. Only the native ESP candidate is being investigated for OTA. Native integrity checks pass; boot acceptance and recovery remain unverified. OTA authentication succeeded on 12 October 2026. A subsequently authorized OTA transfer sent all 1,052,544 native image bytes on 12 October 2026. Sender completed without errors; after a normal external power cycle, the user confirmed English Settings and relay On/Off menus. The running language patch is physically verified; exact installed flash bytes were not read back.
