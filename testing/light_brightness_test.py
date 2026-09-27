#!/usr/bin/env python3
"""Guided FED2 (light) brightness test.

Steps through a range of values on the light characteristic to determine
whether it's true brightness control or just on/off. See
research/PROTOCOL.md, "Light (FED2)" section, for context and to record
the result.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from bleak import BleakClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "controller"))
from looi_protocol import Looi, clamp, find_device  # noqa: E402

SWEEP_VALUES = [0x00, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xC0, 0xFF]
HOLD_S = 1.5


async def run_sweep(looi: Looi) -> None:
    print(f"\nSweeping light values, holding each for {HOLD_S:.1f}s. Watch the light.\n")
    for value in SWEEP_VALUES:
        print(f"  -> sending 0x{value:02X} ({value})")
        await looi.set_light(value)
        await asyncio.sleep(HOLD_S)
    await looi.set_light(0x00)
    note = (
        await asyncio.to_thread(
            input,
            "\nDescribe what you saw across the sweep "
            "(e.g. 'off, then full brightness at 0x02, no change after') > ",
        )
    ).strip()
    print(f"\nNoted: {note}")
    print("Add this to research/PROTOCOL.md under 'Light (FED2)' once you're done.")


async def run_custom(looi: Looi) -> None:
    print("\nEnter values 0-255 (or 0x..) one at a time. Blank/q to finish.")
    while True:
        raw = (await asyncio.to_thread(input, "light value > ")).strip().lower()
        if raw in ("", "q"):
            break
        try:
            value = clamp(int(raw, 0), 0, 255)
        except ValueError:
            print("Enter a number 0-255 (decimal or 0x.. hex), or blank/q to finish.")
            continue
        await looi.set_light(value)
        print(f"Sent 0x{value:02X} ({value})")


async def main(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    print(f"Connecting to {address}...")
    async with BleakClient(address, timeout=20.0) as client:
        looi = Looi(client)
        await looi.connect_and_init()
        heartbeat_task = asyncio.create_task(looi.heartbeat_loop())
        try:
            await run_sweep(looi)
            again = (await asyncio.to_thread(input, "\nTry individual custom values too? (y/n) > ")).strip().lower()
            if again == "y":
                await run_custom(looi)
        finally:
            await looi.shutdown()
            heartbeat_task.cancel()
    print("Disconnected.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided LOOI light-brightness test.")
    parser.add_argument("--address", help="BLE address/UUID. If omitted, scan for a device named LOOI.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
