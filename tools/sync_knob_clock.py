"""Send the verified clock-only update, with no firmware or provisioning changes."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "knob_bridge"))
from clock_sync import clock_packet, sync_once


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--adapter", default="hci0")
    args = parser.parse_args()
    sent = asyncio.run(sync_once(args.timezone, adapter=args.adapter))
    print(json.dumps({"local_time_sent": sent, "bytes_written": 19,
                      "physical_screen_confirmation": "required"}))
