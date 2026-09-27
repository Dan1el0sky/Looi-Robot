#!/usr/bin/env python3
"""Guided tilt/orientation test.

Walks through a set of poses, logging every FED9 event during each one, to
check whether FED9 type 0x02 (currently decoded as "front-proximity/imu
candidate" -- see research/PROTOCOL.md, "Front proximity signal") responds
to tilt as well as to a nearby object, and to see what else (if anything)
fires from the cliff/touch/dock sensors while handling the unit this way.

Keep the unit away from anything in front of it for these poses, so any
FED9 0x02 changes can be attributed to tilt rather than proximity. Every
step can be skipped ('s' at the start prompt) if it doesn't feel safe to
do with your unit.
"""

import argparse
import asyncio
import csv
import sys
import time
from pathlib import Path

from bleak import BleakClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "controller"))
from looi_protocol import Looi, find_device  # noqa: E402
from capture_utils import CSV_HEADER, run_guided_step  # noqa: E402

POSES = [
    ("flat_baseline", "Set it flat and still on the table, nothing nearby in front. Don't touch it."),
    ("tilt_forward", "Tilt it forward (head/nose end down) a moderate amount and hold."),
    ("tilt_backward", "Tilt it backward (head/nose end up) a moderate amount and hold."),
    ("tilt_left", "Tilt it to the left a moderate amount and hold."),
    ("tilt_right", "Tilt it to the right a moderate amount and hold."),
    ("roll_left_90", "Lay it on its left side (about 90 degrees) and hold."),
    ("roll_right_90", "Lay it on its right side (about 90 degrees) and hold."),
    ("nose_down_90", "Stand it up close to vertical, nose/head end down, and hold."),
    ("nose_up_90", "Stand it up close to vertical, nose/head end up, and hold."),
    ("yaw_rotate", "Keep it flat and just rotate/spin it in place, left then right a couple of times."),
    ("flip_upside_down", "If you're comfortable doing it: flip it fully upside down and hold. Skip if not."),
    ("back_to_flat", "Set it back down flat and still, nothing nearby in front."),
]


async def main(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    print(f"Connecting to {address}...")

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"tilt_test_{time.strftime('%Y%m%d-%H%M%S')}.csv"

    async with BleakClient(address, timeout=20.0) as client:
        looi = Looi(client)
        await looi.connect_and_init()
        heartbeat_task = asyncio.create_task(looi.heartbeat_loop())

        with log_path.open("w", newline="", encoding="utf-8") as log_file:
            writer = csv.writer(log_file)
            writer.writerow(CSV_HEADER)
            log_file.flush()

            print(
                f"\n{len(POSES)} poses total. Keep it away from anything in front so any\n"
                "FED9 0x02 change can be attributed to tilt, not proximity. Type 's' at\n"
                "any start prompt to skip a pose."
            )
            run_start = time.time()
            try:
                for label, instruction in POSES:
                    await run_guided_step(looi, label, instruction, writer, log_file, run_start)
            finally:
                await looi.shutdown()
                heartbeat_task.cancel()

    print(f"\nDone. Log written to: {log_path}")
    print(
        "Check whether type 0x02 changed during any pose with nothing in front of it --\n"
        "if so, it's tilt-sensitive too (not purely proximity). Also note anything\n"
        "unexpected from the cliff/touch/dock sensors while handling it this way.\n"
        "Add the conclusion to research/PROTOCOL.md under 'Front proximity signal'."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided LOOI tilt/orientation test.")
    parser.add_argument("--address", help="BLE address/UUID. If omitted, scan for a device named LOOI.")
    parser.add_argument("--log-dir", default="testing/logs", help="Directory to write the CSV log into.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
