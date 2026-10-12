"""Read an isolated, verified UART tap; print commands without serial writes.

Stock display UART: 921600 baud, 8N1. PCB pad mapping/isolation must be verified
first. This tool does not flash, configure the knob, or call HA light services.
"""
import argparse
import json
from pathlib import Path

from knob_uart import KnobUartParser


def run(args):
    parser = KnobUartParser(args.slot)
    if args.capture:
        stream = args.capture.open("rb")
    else:
        import serial
        # Receive-only wiring is required; keep automatic reset lines disabled.
        stream = serial.Serial(port=None, baudrate=921600, timeout=1,
                               bytesize=8, parity="N", stopbits=1,
                               rtscts=False, dsrdtr=False)
        stream.dtr = False
        stream.rts = False
        stream.port = args.port
        stream.open()
    with stream:
        while True:
            chunk = stream.read(256)
            if not chunk and args.capture:
                break
            for event in parser.feed(chunk):
                print(json.dumps(event), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--port", help="Verified receive-only serial tap, e.g. /dev/ttyUSB0")
    source.add_argument("--capture", type=Path, help="Offline binary UART capture")
    p.add_argument("--slot", type=int, default=3)
    try:
        run(p.parse_args())
    except KeyboardInterrupt:
        pass
