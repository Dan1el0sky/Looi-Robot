#!/usr/bin/env python3
"""Guided FED9 (sensor stream) approach test, front area.

First attempt filtered to only type 0x12 ("front touch" per the reference
repo) and captured nothing across 3 real touches. Turned out the real
signal is type 0x02 (see research/PROTOCOL.md, "Front proximity signal") --
this logs every FED9 event type during each pass instead of pre-guessing
which one matters, while moving an object continuously from out-of-range
to touching, once per pass.
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

PASS_INSTRUCTION = (
    "Start with the object out of range (arm's length away). Once recording\n"
    "starts, move it slowly and steadily toward the sensor until it touches,\n"
    "over about 5 seconds."
)


async def main(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    print(f"Connecting to {address}...")

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"front_sensor_{time.strftime('%Y%m%d-%H%M%S')}.csv"

    async with BleakClient(address, timeout=20.0) as client:
        looi = Looi(client)
        await looi.connect_and_init()
        heartbeat_task = asyncio.create_task(looi.heartbeat_loop())

        with log_path.open("w", newline="", encoding="utf-8") as log_file:
            writer = csv.writer(log_file)
            writer.writerow(CSV_HEADER)
            log_file.flush()

            print(f"\nRunning {args.passes} approach passes. No ruler needed -- just move steadily.")
            run_start = time.time()
            try:
                for pass_num in range(1, args.passes + 1):
                    await run_guided_step(looi, f"pass {pass_num}", PASS_INSTRUCTION, writer, log_file, run_start)
            finally:
                await looi.shutdown()
                heartbeat_task.cancel()

    print(f"\nDone. Log written to: {log_path}")
    print(
        "Look at elapsed_in_step_s vs the decoded values: changes only right at the\n"
        "end of a pass mean contact-only; changes that start earlier and keep moving\n"
        "as it gets closer mean a real proximity signal. Add the conclusion to\n"
        "research/PROTOCOL.md under 'Front sensor' / 'Front proximity signal'."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided LOOI front-sensor approach test.")
    parser.add_argument("--address", help="BLE address/UUID. If omitted, scan for a device named LOOI.")
    parser.add_argument("--log-dir", default="testing/logs", help="Directory to write the CSV log into.")
    parser.add_argument("--passes", type=int, default=3, help="Number of approach passes to run.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
