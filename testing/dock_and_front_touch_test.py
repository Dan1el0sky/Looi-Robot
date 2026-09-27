#!/usr/bin/env python3
"""Guided phone-dock and front-center-touch test.

Two things not yet confirmed on this unit: the phone dock attach/detach
event (FED9 0x05/0x06) and the front-center touch event (FED9 0x12, which
never fired during the front-sensor approach test -- see
research/PROTOCOL.md, "Front sensor"/"Sensor inventory"). This logs every
FED9 (and FED5) event during a few guided attempts at each.
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

STEPS = [
    (
        "phone_dock_attach_detach",
        "Attach your phone to the dock/mount on the robot's head, hold it in place\n"
        "for a couple of seconds, then remove it again.",
    ),
    (
        "front_touch_firm_press",
        "Press firmly on the front-center area a few times. If nothing happens, try\n"
        "slightly different spots/heights and note where (if anywhere) something fires.",
    ),
    (
        "front_touch_hold",
        "Press and hold the front-center area firmly for about 3 seconds, then release.",
    ),
]


async def main(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    print(f"Connecting to {address}...")

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"dock_and_front_touch_{time.strftime('%Y%m%d-%H%M%S')}.csv"

    async with BleakClient(address, timeout=20.0) as client:
        looi = Looi(client)
        await looi.connect_and_init()
        heartbeat_task = asyncio.create_task(looi.heartbeat_loop())

        with log_path.open("w", newline="", encoding="utf-8") as log_file:
            writer = csv.writer(log_file)
            writer.writerow(CSV_HEADER)
            log_file.flush()

            print(f"\n{len(STEPS)} steps. Type 's' at any start prompt to skip one.")
            run_start = time.time()
            try:
                for label, instruction in STEPS:
                    await run_guided_step(looi, label, instruction, writer, log_file, run_start)
            finally:
                await looi.shutdown()
                heartbeat_task.cancel()

    print(f"\nDone. Log written to: {log_path}")
    print(
        "Check for FED9 0x05/0x06 (dock attach/detach) and 0x12 (front touch) in the log.\n"
        "Add the result to research/PROTOCOL.md under 'Sensor inventory'."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided LOOI phone-dock and front-touch test.")
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
