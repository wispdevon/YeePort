# Physical knob clock and outdoor weather synchronization

The user selected outdoor temperature from Home Assistant. The source is
`weather.forecast_home`; Home Assistant's configured timezone is `Asia/Bangkok`.
`tools/knob_sync_source.py` reads both through the authenticated HA API. It
converts Fahrenheit to Celsius when needed and marks unknown, unavailable,
nonfinite, unsupported-unit, or stale weather as unavailable. The default
maximum weather age is three hours. It supplies UTC epoch, local date/time,
and UTC offset; it does not itself change the physical device.

The official 1.4.25 ESP32 firmware has a clock setter reachable through the
authenticated `b19adf7e-b836-40e3-8b06-acc47f2d187e` display UART. After the
verified identity exchange (`01` + identity digest, reply `0100`), its UCP
packet is:

```text
f0 f1 f2 f3 | 01 1c 00 | sequence LE16 | 06 00 |
05 08 | calendar epoch LE32 | payload CRC16/CCITT LE16
```

The CRC uses initial value zero. Namespace 1/opcode `1c` goes through
`42025df8` and `42026740`, which prepend a six-byte internal header. The
`4202635c` handler dispatches internal message 18. `4200ca7c` selects byte
`05`, `4200c980` selects byte `08`, and `4200c920` reads the four-byte epoch,
sets the RTC, stores `timestamp`, and refreshes the clock display. This path
does not require a Mesh NetKey, provisioning changes, firmware OTA, or custom
image uploads.

The clock renderer reads libc local time, and no application timezone setup
has been found in this firmware. `tools/sync_knob_clock.py` therefore shifts
the epoch by HA's current timezone offset for the firmware's calendar clock.
This encoding must be verified against the displayed time, including any
day/month rollover. Source and codec checks cover midnight/year rollover and
the packet namespace, length, payload, and CRC.

A controlled clock-only test on the Pi completed on 12 October 2026 at
19:38:32 in Asia/Bangkok: identity returned `0100` and the 19-byte UCP packet
was sent with an acknowledged 20-byte write including final `ff` padding.
No notification followed on the B19 characteristic. The setter's acknowledgment
is sent back to the Bluetooth MCU's Mesh router, so GATT write acknowledgment
does not establish that the physical screen changed. User display confirmation
was subsequently provided: the user confirmed the time and date were correct.
The bridge was resumed and temporary SSH access and its
Python environment were removed after this test.

The weather setter is adjacent: namespace 1/opcode `1c`, inner bytes `05 09`,
then a length-prefixed weather text, a length-prefixed numeric temperature
string, and a weather asset key byte. `4200c800` stores `weat_temp`, weather
text, and `weat_key`, and refreshes the weather display. Keep weather text at
most 23 bytes and numeric temperature at most 8 bytes so the firmware's
fixed-size buffers remain terminated. The renderer appends Celsius to the
numeric string.

The final weather byte selects an existing type-5 weather image. The first
controlled temperature update used label `Outdoor`, the fresh HA value `27`
Celsius, and key zero. The identity reply was `0100` and the 27-byte packet
completed with acknowledged writes. The user confirmed the physical display
shows 27°C, then clarified that the condition should be represented by an icon.

The official firmware's initialized data segment provides the concrete icon
mapping: array base `0x3fca157c`, 149 records of 104 bytes, filename at offset 4,
image type at offset 84, and image key at offset 88. Records 50–79 contain the
weather images below. These are existing compiled asset names and selectors;
no custom weather image upload is involved.

| HA condition | Key | Firmware image |
| --- | ---: | --- |
| sunny | 1 | qing.bin.gz (clear/sunny) |
| cloudy | 2 | yin.bin.gz (overcast) |
| partlycloudy | 3 | duoyun.bin.gz (partly cloudy) |
| rainy | 10 | xiaoyu.bin.gz (light rain) |
| pouring | 17 | dayu.bin.gz (heavy rain) |
| lightning | 20 | leiyu.bin.gz (thunderstorm) |
| lightning-rainy | 21 | leizhenyu.bin.gz (thundershower) |
| hail | 31 | bingbao.bin.gz (hail) |
| snowy | 43 | xiaoxue.bin.gz (light snow) |
| snowy-rainy | 40 | yujiaxue.bin.gz (sleet) |
| fog | 50 | wu.bin.gz (fog) |

HA's coarse conditions select the closest supported image. Cloudy selects
overcast because HA has a distinct partly-cloudy condition. Unsupported
clear-night, windy, exceptional, or unknown conditions use key zero instead of
inventing a moon/wind icon.

Renderer behavior was verified directly from Xtensa instructions, since the
Ghidra export omitted hardware-loop semantics: `42019e08` loops over all 149
records and clears all type-5 images; `42019e2c` loops over the same array,
enables the matching type-5/key record, and returns -1 when none exists. No
type-5 key zero exists in the table, so the fallback leaves weather icons
disabled. The user's prior Sunny icon is consistent with the verified key-1
`qing` image; key 1 is also the firmware's initialized default.

`knob_bridge/weather_sync.py` constructs this bounded packet and performs the
same authenticated display UART exchange. `tools/sync_knob_weather.py` accepts
a source snapshot, rejects stale/unavailable data, and sends the numeric
temperature. Celsius/Fahrenheit conversion takes place in the source helper.
No firmware/images/relay/network changes are part of these updates. Do not send
type-5 images with the relay-label uploader: the common GATT image writer only
initializes filenames for types 1 and 2.

Its periodic `run_weather_sync` helper reads the selected HA weather entity
every five minutes, sends a changed temperature, and refreshes an unchanged
value hourly. It shares the clock updater's BLE operation lock and suppresses
our own Mesh traffic during the write and for five seconds afterward. A shared-scan lookup takes at most 20 seconds; each
connection has a 50-second timeout; cancellation releases the lock and
restores normal activity processing after the grace period. Stale/unavailable
weather or API failures keep the last displayed reading, rather than inventing
one, and retry on the next poll.

`knob_bridge/weather_source.py` uses Home Assistant's supported internal app
API proxy and `SUPERVISOR_TOKEN`. The app must enable `homeassistant_api: true`
and copy both weather modules into its image. The runtime needs neither the
user's long-lived token nor a Yeelight cloud account. This proxy mechanism is
documented in [Home Assistant app communication](https://developers.home-assistant.io/docs/apps/communication/).
Version 0.3.3 integrates and deploys the periodic helper on the Pi. Clock and
temperature writes both succeeded in app logs; the user confirmed time/date
and 27°C. Version 0.3.4 is running with the verified icon mapping above. The app logged
Cloudy with installed icon key 2, and the user confirmed the cloud icon is visible.
`tools/cycle_knob_weather_icons.py` tests all 30 installed type-5 keys using
the same bounded weather setter; the temperature field shows the test ID,
then the real temperature and condition are restored.
`knob_bridge/clock_sync.py` provides the same verified setter for startup and
hourly synchronization, with a five-minute retry after missed connections. Its
caller must hold a shared local BLE operation lock and suppress generic Mesh
activity during each clock write and for five seconds after it, so clock replies
cannot trigger lighting automations. Periodic synchronization is deployed and a startup clock update was verified
in Pi app logs.

Namespace 2 opcodes 1–4 and 7–9 are firmware/assets transfer paths. Namespace
4/opcode 7 is miscellaneous configuration including provisioning behavior.
They are not clock/weather setters and must not be used for data sync.


The user reported the slow visual test looked good, then requested a complete
one-second cycle. All 30 IDs were sent successfully at a one-second hold,
including fog, haze and sandstorm. The tool restored cloudy/27°C afterward,
and the automatic bridge was resumed. No per-ID visual failures were reported.
