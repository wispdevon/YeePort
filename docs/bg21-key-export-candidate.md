# Authenticated BG21 factory-secret export candidate

Prepared offline, then tested with explicit authorization on 12 October 2026.
The secret and Mesh keys were recovered, and stock BG21 behavior restored as
recorded below. This is a different processor and transfer from the successful
ESP English update.

## Exact patch

The native BG21 application has one four-byte instruction replacement at
`0x11f94`: `1d f0 6c fa` (call the BGAPI dispatcher) becomes `36 f0 b4 be`
(branch to `0x48d00`). A 124-byte Thumb hook is appended at `0x48d00`, remaining
within the last flash page already covered by the official program image.
Assembly source: `tools/bg21_key_export.S`.

The hook invokes the original dispatcher with the original arguments. Only
when the notification is on attribute `0x34`, has length 4, and equals
`07 03 01 64`, it sends an additional notification to the same connection:
`07 04` followed by the sixteen bytes at `0x0fe0000e`.

The existing authentication handler at `0x122a8` emits that success reply only
after decrypting and checking its 128-byte random challenge with
MD5(NodeDevKey || `MESHOTA`). The hook does not remove or bypass authentication,
modify stored keys, change pairing, or write the factory page. The normal
success reply remains unchanged. Stock applications may ignore the additional
notification; hardware compatibility is unverified.

## Package and verification

The official raw GBL has a plaintext header, no signature/certificate tags,
two program regions at `0x4000` and `0x10000`, and an end CRC. This is consistent
with the [Silicon Labs GBL format](https://docs.silabs.com/shared-content/latest/bootloader-user-guide-gsdk-4/02-gecko-bootloader-file-format).
The candidate preserves the first region and metadata, modifies/extends only
the second region, and recalculates the end CRC. The entire candidate matches
the standard CRC residue `0x2144df1c`. It includes no per-unit user-page data.
Signature-tag absence does not establish the installed bootloader's security
configuration or acceptance of modified code. Its actual flash was not read.

Candidate: `/home/wisp/Downloads/yeegate-bg21-key-export.analysis.gbl`

- Size: 279,956 bytes.
- SHA-256: `75385a9b0e7a1a1da7a56ef5dfd78e2e8451082cd0ec34437070aeb81cf46e15`.
- Manifest: same filename with `.json` suffix.
- Reproducible builder: `tools/prepare_bg21_key_export.py`.

Restore reference: `/home/wisp/Downloads/yeegate-bg21-1.4.25-official-restore.gbl`

- Exact original GBL, 279,832 bytes.
- SHA-256: `63a665f822086ab494c8e2aa12b90835d37245a9f4a47d94ea57a55774050205`.
- Restoration through OTA still requires a running Bluetooth application. It
  does not constitute verified recovery after a failed boot.

Unicorn executed the actual patched ARM notification wrapper and hook. Only
vendor memcpy and the synchronous BGAPI dispatcher were mocked. Checks passed
for preserved saved registers/stack/return value; successful export ordering;
capture of the original connection before SDK buffer clobber; and equivalence
to stock behavior for challenge, failed/wrong/extended success, display identity,
and provisioning replies. These checks do not model radio, flash installation,
or bootloader behavior. Three independent network-crypto vector tests also pass.

## Prepared single-attempt workflow

`tools/flash_knob_bg21.py` permits only the pinned candidate or exact stock GBL.
Its default mode validates locally. Physical writes additionally require
`--flash --fresh-power-cycle-confirmed`.

The official OTA service authenticates with the known NodeDevKey, enables data
with control `00`, then transfers raw GBL in 200-byte writes with pacing. In
contrast to the ESP-only update, BG21 GBL install requires control `03` after
all bytes and a subsequent disconnect. Static firmware routes that request to
its Gecko bootloader installation/reset callback. ATT responses establish
Bluetooth reception, not storage-write or install success. The recovered
storage writer ignores its backend return code, so the sender must not claim
successful installation from completed writes alone.

There are no chunk offsets or safe retries. An interrupted BG21 attempt requires
a fresh external power cycle before restarting; app initialization clears its
upload offset. No automatic retry or reset command is used.

After the diagnostic application boots, `tools/read_knob_factory_secret.py`
performs authentication only, saves the exported secret privately, and runs
the saved binding/capture validation. Recovered keys require a known device-key
match and at least three real network MICs. Keys and secret are never printed;
new files are created with mode 0600. Application-layer decoding remains a
separate next step after recovery.

Once the secret and keys are saved, the exact original BG21 GBL is available
to remove the diagnostic hook. The ESP English application is not contained
in either BG21 GBL, so this operation does not replace that English patch.

The owner has no verified BG21 UART/SWD recovery connector or backup. BG21
failure could remove the only demonstrated BLE/OTA route. The earlier ESP UART
findings do not establish recovery for this Bluetooth processor.

## Authorized hardware attempt

The user explicitly authorized BG21 diagnostic OTA and restoration of stock
firmware. After a confirmed external power cycle, the sender transferred all
279,956 bytes in 203 seconds. The subsequent control `03` write returned ATT
Unlikely Error (0x0e). That response does not establish whether the application
armed its install/reset callback. No data chunks were retried. A separate
authentication/export probe is checking whether the diagnostic application
actually runs.

The authenticated probe returned `0704` plus the real per-unit secret after
valid OTA authentication, proving the diagnostic application runs despite the
finish-write ATT error. The export is saved in private local files
`knob-factory-secret.bin` (16 bytes) and `knob-authenticated-export.bin`
(18 bytes) under `/home/wisp/.local/state/yeegate`, with mode 0600. The recovery
decoder initially rejected a guessed marker byte; the actual blob uses byte
zero = 0, which the vendor handler does not validate. Removing that invented
check while retaining DeviceKey comparison and network MIC validation recovered
the real keys. All 57 brightness-ring packets and all 25 direction-test packets
pass BOTH network and application MIC checks. The 57-packet set contains
55 brightness and two power commands for display slot 3, vendor opcode 0xc1,
company 0x0164. Stock restoration is in progress.

## Stock restoration verified

The exact original GBL transferred in 169 seconds. Its finish request also
returned ATT 0x0e, but a new authenticated connection then succeeded and
produced no diagnostic export over the observation interval. This verifies
restored stock notification behavior; no exact flash read-back was performed.
The ESP English image was not replaced. Temporary Pi files, including the
exported secret, were removed after private local copies were saved. The
Home Assistant bridge was restarted and original SSH options restored.
No Home Assistant light service calls were made during this investigation;
runtime command routing is a separate integration step.
