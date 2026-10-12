# S Knob firmware recovery verification

Recovery remains unverified. The user reports a wall-powered knob and has no
3.3 V USB-to-UART adapter. No recovery connector or PCB test-pad mapping has been
verified on this particular unit. The user subsequently explicitly authorized
a language-only OTA attempt despite these limits. On 12 October 2026, official
OTA authentication succeeded and all 1,052,544 native ESP candidate bytes were
transferred without a sender error. The user confirmed normal boot with English Settings and relay On/Off menus
after an external power cycle. Hardware recovery remains unverified.
This does not establish boot acceptance or UART recovery. No GPIO or eFuse
writes were performed.

## What the official update contains

The MD5-verified official v1.4.25 package contains UI resources, one ESP32-S3
application image, and the separate BG21 Bluetooth firmware. Scanning the full
package found only one structurally valid ESP image, starting at `0x250018`,
with application entry point `0x40379aec`. It found no valid ESP partition-table
entries and no second ESP image identifiable as a software bootloader.

This is an OTA update package, not a verified full flash backup. The extracted
official application is a useful reference, but cannot replace the missing
installed bootloader, partition table, OTA metadata, configuration, and calibration
data. A verified backup of the physical unit is needed for a complete restore.

## Why Bluetooth does not establish recovery

The BG21 update parser at `0x28558` recognizes `espf` and `kbui` headers and
forwards application/UI update commands to the ESP using UCP. This depends on the
ESP application running its UCP receiver. No verified bridge to the ESP ROM
download protocol or control of the ESP boot strapping pins was found.

The ESP's `boot_loader_scr` record at `0x3fca5288` names an ordinary LVGL startup
screen. Its callbacks (`0x4201e1cc`, `0x4201eaec`, `0x4201de04`) create widgets,
display startup progress, and manage timers inside the application. It is not a
separate bootloader or fallback application.

The exposed BG21 factory GPIO table contains D3, D4, A5, and A6, plus an invalid
sentinel. Their physical functions on this unit have not been mapped. They do
not establish a verified way to drive ESP GPIO0 or EN. They were not exercised.

## Hardware needed to verify independent recovery

The chip-level requirements below are verified by Espressif documentation.
They are **not a pinout for the S Knob PCB**.

| Requirement | Purpose and current evidence |
| --- | --- |
| Electrically safe, isolated access to the low-voltage controller | The unit is wall-powered; an unverified mains circuit must not be connected to a computer or serial adapter. Inspection and isolation require appropriate hardware expertise. |
| 3.3 V logic USB-to-UART adapter | ESP32-S3 logic operates around 3.3 V; suitable signal levels must be confirmed. This is not authorization to supply power to an unidentified PCB pad. |
| Verified ESP UART0 TX/RX and ground test points | Chip defaults are GPIO43/U0TXD and GPIO44/U0RXD. Their PCB locations are unknown. |
| Verified access to GPIO0, EN/reset, and GPIO46's strap state | ROM download mode requires GPIO0 low during reset and GPIO46 low or floating. Board circuitry and accessibility are unknown. |
| Independent ROM connection while the application is not running | Proves recovery does not depend on the screen application or its UCP receiver. |
| Read-only security information and complete flash backup | Determines whether ROM read/restore operations are permitted and preserves the actual installed bootloader, partition table, settings, and application. |

Espressif's [boot-mode documentation](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/advanced-topics/boot-mode-selection.html)
describes the boot straps. Its [ESP32-S3 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf)
identifies UART0 on GPIO43/44 and the nominal 3.3 V supply/logic domain.

### The stock inter-chip UART is not the recovery UART

The compiled firmware configures **UART1 TX=GPIO19 and RX=GPIO20** in
`0x42026070`, calling `uart_set_pin(1, 19, 20, -1, -1)`. This is the link used
for BG21-to-ESP UCP traffic. Its compiled baud rate is 921600, with 8 data bits,
no parity and one stop bit. GPIO19/20 also serve as the ESP32-S3 native USB pins,
so a usable native USB recovery connection cannot be assumed from the chip's
USB capability. The actual product may repurpose these pins and expose only
power at an external connector. UART0 GPIO43/44 is a separate chip-level route.

## Checks required before calling recovery verified

With suitable hardware and a verified PCB mapping, the first operations should
be read-only ROM identification/security checks, followed by reading flash where
permitted. `--no-stub` avoids loading a software helper into RAM; no erase,
write, or eFuse-programming command is part of the verification stage.

Secure UART download mode can restrict commands to security information and
limited flash-writing operations; ROM download mode can also be disabled
permanently. Therefore neither an adapter nor entering download mode alone
proves that a complete backup or restore is possible.
[Espressif security documentation](https://docs.espressif.com/projects/esp-idf/en/v5.1/esp32s3/security/security.html)
explains these restrictions. The [esptool flash-read documentation](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/basic-commands.html#read-flash-contents-read-flash)
describes reading the installed contents where allowed.

Recovery can be considered established only after identifying this unit,
confirming its security restrictions, obtaining and validating its full backup,
parsing its actual partition layout, and confirming an independent restore path
that remains available if the application does not boot. The backup must stay
private because it may contain account, device, and provisioning data.

At present, those hardware checks cannot be performed with the available setup.
The English application candidate is being tested through the native ESP OTA
path following the user's explicit authorization. The working English labels
and Home Assistant bridge do not require it to be flashed.


## Passive control capture before any firmware patch

The display sends plaintext brightness commands before the BG21 creates Mesh
packets. Recovered path: 420214d8 -> 4200e424 -> 4200de00 -> 42026038.
For a dimmable entry, namespace 1/opcode 1 payload is slot,01,00,00,00,percent
(6 bytes), followed by the generic UCP payload CRC. A power change is slot,
00,00,00,00,power,00,00 (8 bytes). A passive receive-only tap on the verified
display TX signal could capture these commands without exporting Mesh keys or
flashing firmware. No physical pad mapping or hardware capture has verified it
yet. tools/knob_uart.py parses bounded CRC-valid frames; tools/read_knob_uart.py
reads an offline capture or verified isolated serial tap and prints commands.
Its synthetic fragmented/noisy input, CRC rejection and slot filtering checks
passed, but it has not controlled live Home Assistant lights.

Once the controller is safely isolated and its pads are identified, passive
UART capture is the first useful hardware step. Flash/recovery UART0 remains
a separate interface. Do not infer a safe ground or power connection from
a pad label or from these chip-level GPIO numbers.
