# S Knob native ESP OTA transport review

Offline review of official 1.4.25 firmware and Yeelight Pro 1.33.0 APK. This document records protocol evidence; it is not evidence of a successful update or verified recovery. No OTA commands were sent by this investigation.

## Official BLE authentication

Service `1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0` exposes auth `b35e3d49-12b2-4346-9912-0c7f5eb9bbc8`, control `f7bf3564-fb6d-4e53-88a4-5e37e0326063`, and data `984227f3-34fc-4045-a5d0-2c581f81a153`.

BG21 handler `0x122a8`, called by the GATT write event for handle `0x34`, establishes three authentication states:

1. State 0 accepts value `07 00 01 64`, generates 128 random bytes, and notifies `07 01` followed by those bytes. State becomes 1.
2. State 1 accepts `07 02`, a 16-byte IV, and 128-byte AES-CBC ciphertext. The key is MD5 of the 16-byte node device key followed by ASCII `MESHOTA`. Firmware obtains that node key from the current node record at offset `+10`; APK parses its key hex string in forward byte order.
3. Decrypted bytes must equal the challenge. Success notifies `07 03 01 64` and sets state 2.

APK `AesHelper.encryptData` uses CBC, zero-padding only when input is not already a multiple of 16 bytes, and returns IV followed by ciphertext. Its default IV is MD5 of the decimal epoch-millisecond string; an explicit 16-byte IV is supported. Thus the 128-byte challenge produces exactly 128 ciphertext bytes, with no extra PKCS#7 block.

Authentication state is not explicitly reset by the exported disconnect handler. A second `07 00 01 64` in state 1 falls through the auth error branch and resets state to 0 without generating a challenge; another identical request then starts a fresh challenge. This branch sends a vendor Mesh error status but invokes no OTA erase or data handler.

## Official native-image stream

In authenticated state 2, control handle `0x2f` value `00` enables data acceptance. Data handle `0x32` forwards to `0x28558` only while this enable flag is set. Control `03` clears enable, marks a pending completion flag, and resets authentication. It must not be assumed appropriate for a native-only ESP update.

On disconnect, the pending-completion/success branch schedules Thumb callback `0x12841`. Exact ARM assembly at `0x12840` calls the Gecko bootloader interface function at offset `+0x18`, writes reset magic `0xf00f0202` to RAM `0x20000000`, then calls `0x199f4`. This is a BG21 bootloader completion/reset path, despite a native-only stream having no BG21 GBL image. Its behavior without a GBL image has not been demonstrated. Do not use this completion sequence for the native-only candidate.

Correction: the completion-screen restart path requires the OTA screen to have been entered first. Native-only start does not enter that screen. The following path is established only for a transfer that already entered `boot_loader_scr`:

1. UI-asset start opcode 7 (`0x42025718`) posts queue-8 event type 0 through `0x42009b38`. `0x4201a83c` switches UI using `0x42018df0` to table `0x3fca5288`, named `boot_loader_scr`; its event callback is `0x4201eaec`. Native firmware start opcode 1 instead posts type 2 through `0x42009b80`, which does not switch screens. The only exported caller of `0x42009b38` is UI-asset start; auth and BLE control `00` do not invoke it.
2. Successful native commit calls `0x42009bec`, posting queue-8 event type 5. `0x420097a4` dispatches to `0x4201a83c`, which sends UI event 12 through `0x4200f304`.
3. `boot_loader_scr` handles event 12 by scheduling a 100-ms timer, callback `0x4201df6c`. That callback increments the progress counter, reschedules its animation, and calls `0x4200390c` once the counter exceeds 12. Exact Xtensa instructions at `0x4201e055..0x4201e05a` confirm the condition and call.
4. `0x4200390c` runs shutdown handlers then calls the ESP IRAM restart helpers at `0x40389078`, `0x4037a0c0`, and `0x40379e38`. This establishes restart after the completion animation when that screen is active. It does **not** establish self-restart for a native-only `espf` stream, because that stream omits UI-asset start and therefore omits screen entry.

Opcode 3 posts event type 3 after the commit helper posts type 5. Type 3 returns from the progress timer callback without cancelling an existing boot-loader-screen completion animation. In a native-only transfer, successful CRC/image validation and boot-partition selection can occur while the normal UI remains active; automatic restart remains unverified. Inserting UI-asset start merely to enter the screen would begin another flash operation and is not a justified workaround. OTA-reset opcode 4 can abort and erase partitions and must not be used as a reboot command.

Native ESP stream header is 12 bytes: ASCII `espf`, LE32 raw IEEE CRC32, LE32 image byte length. Raw CRC starts at `0xffffffff` and has no final XOR. The alternative package tag is `kbui`, not `espu`.

BG21 translates the native header to namespace 2 opcode 1; ordinary image chunks to opcode 2; the final nonempty chunk to opcode 3. Every generated UCP frame has flags zero. Frame length is payload length plus 13; the firmware accepts its builder only when total length is below 261. A 200-byte data chunk is within this bound. There is no chunk offset or duplicate detection: replaying a chunk appends it again.

UCP format is magic `f0 f1 f2 f3`, namespace byte, opcode byte, flags byte, LE16 sequence, LE16 payload length, payload, then LE16 CRC16-CCITT of payload with initial value zero.

ESP namespace 2 command table at `0x3c0cfb98`:

| Opcode | Handler | Meaning |
| --- | --- | --- |
| 1 | `0x420259ec` | Native firmware start: LE32 size and LE32 raw CRC |
| 2 | `0x42025ab4` | Native firmware data |
| 3 | `0x42025a64` | Final native firmware data |
| 4 | `0x42025790` | Reset/prepare, mutating operation |
| 7 | `0x42025718` | UI asset start |
| 8 | `0x420256a4` | UI asset data |
| 9 | `0x42025620` | Final UI asset data |
| 10 | `0x42025afc` | Custom label image write |

The native commit helper `0x4202584c` commits whenever accumulated byte count reaches the declared size, including from opcode 2. It verifies raw CRC, calls `esp_ota_end`, then selects the new boot partition. Therefore the last nonempty chunk must use opcode 3; sending a last opcode-2 chunk and then an empty opcode 3 risks a second commit of an invalid OTA handle.

## Acknowledgement and completion limits

ESP generic UCP flag-bit-0 acknowledgement is emitted before the command handler. More seriously, exact Xtensa assembly at `0x42025f27` and `0x42025f2a` writes its empty CRC into the first two bytes of the received payload, corrupting that payload before dispatch. Never request this generic ACK on firmware frames. The official BG21 sender correctly sets flags zero.

ESP completion is namespace 2 opcode 4 status zero. BG21 handler `0x2555c` sets its success flag `+0x268`; nonzero statuses invoke `0x25520`, which sends vendor Mesh status bytes `20 01 08 04 <status>`. It does not directly notify the image characteristic or the OTA control characteristic. Ordinary ATT write responses establish reception by BG21, not successful flash processing by ESP32.

The authenticated B19 custom-image characteristic can forward raw UART frames, but has no demonstrated direct return path for OTA acknowledgements. Prefer the official OTA service and prove its authentication before any firmware write. Remaining validation concerns are ESP completion observability, final control/disconnect behavior, and sustained pacing without UART queue overflow. No per-chunk ESP acknowledgement has been established.

## Candidate and recovery

The prepared native candidate changes the locale literal `zh` to `en`, recalculates the ESP XOR checksum, and replaces its appended SHA256. The existing matching English resources are selected by the prefix; physical menu coverage still requires device verification. Native application integrity checks match this format. Actual bootloader security fuses and recoverability have not been verified.

See [hardware recovery investigation](knob-firmware-recovery.md). A stock ESP32 application image and the vendor OTA container are not full flash backups. Automatic rollback is not established; current SDK boot metadata uses `ESP_OTA_IMG_UNDEFINED`. The user has no UART adapter and no verified S Knob PCB recovery pinout. These limits remain even if BLE authentication succeeds.

## Actual authorized attempt

On 12 October 2026, the root agent authenticated the official OTA service and
transferred the entire pinned native English candidate in 756 seconds without
a sender exception. It omitted BG21 control `03`, waited ten seconds, then
disconnected. The screen remained normal throughout the native-only transfer.
After a normal external power cycle, the user confirmed English Settings and
relay On/Off menus. The running language patch is physically verified. No exact
flash read-back or UART recovery check was obtained. The local bridge and
original SSH options were restored, and temporary Pi deployment files removed.
