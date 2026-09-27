#!/usr/bin/env python3
"""Manual LOOI controller for Windows.

Everyday driver: WASD movement, exact head position, light on/off, and a
live sensor watch. Protocol/connection code lives in looi_protocol.py.
Guided diagnostics (e.g. the light brightness sweep) live under testing/.

Menu:
  1) Drive with WASD (live)
  2) Set head to an exact position
  3) Light on/off (or a brightness value)
  4) Watch cliff/touch sensors live
"""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient

if sys.platform != "win32":
    raise SystemExit("This script uses msvcrt for keyboard input and only runs on Windows.")

import msvcrt

from looi_protocol import Looi, clamp, find_device

DEADMAN_TIMEOUT_S = 2.0
STEP_LEVELS = {"1": 8, "2": 16, "3": 32, "4": 64, "5": 127}


def key_pressed() -> bool:
    return msvcrt.kbhit()


def read_key() -> str:
    return msvcrt.getwch()


async def drive_mode(looi: Looi) -> None:
    state = looi.move_state
    state.stop()
    state.last_key_time = time.time()
    print(
        f"""
Drive mode (WASD)
  w/s = speed +/- step   a/d = turn +/- step   space = stop
  1..5 = step 8/16/32/64/127 (current step: {state.step})
  q = back to menu (stops first)
  Auto-stop if no key is pressed for {DEADMAN_TIMEOUT_S:.0f}s
"""
    )
    while True:
        if key_pressed():
            key = read_key().lower()
            state.last_key_time = time.time()
            if key == "q":
                break
            elif key == "w":
                state.speed = clamp(state.speed + state.step, -127, 127)
            elif key == "s":
                state.speed = clamp(state.speed - state.step, -127, 127)
            elif key == "a":
                state.turn = clamp(state.turn + state.step, -127, 127)
            elif key == "d":
                state.turn = clamp(state.turn - state.step, -127, 127)
            elif key == " ":
                state.stop()
            elif key in STEP_LEVELS:
                state.step = STEP_LEVELS[key]
            print(f"\rspeed={state.speed:4d} turn={state.turn:4d} step={state.step:3d}   ", end="", flush=True)

        if (state.speed != 0 or state.turn != 0) and time.time() - state.last_key_time > DEADMAN_TIMEOUT_S:
            state.stop()
            print(f"\nAuto-stop: no key pressed for {DEADMAN_TIMEOUT_S:.0f}s")

        await asyncio.sleep(0.02)

    state.stop()
    print("\nBack to menu (stopped).")


async def head_mode(looi: Looi) -> None:
    print(
        """
Head position
  Enter a value 0-255 (decimal, or 0x.. hex). 0 = full up, 90 / 0x5A = center, 255 = full down.
  Blank or q = back to menu
"""
    )
    while True:
        raw = (await asyncio.to_thread(input, "head value > ")).strip().lower()
        if raw in ("", "q"):
            break
        try:
            value = int(raw, 0)
        except ValueError:
            print("Enter a number 0-255 (decimal or 0x.. hex), or blank/q to go back.")
            continue
        value = clamp(value, 0, 255)
        await looi.set_head(value)
        print(f"Sent head = {value} (0x{value:02X})")


async def light_mode(looi: Looi) -> None:
    print(
        """
Light
  on / off, or a brightness value 0-255
  (for a guided brightness sweep, see testing/light_brightness_test.py)
  q = back to menu
"""
    )
    while True:
        raw = (await asyncio.to_thread(input, "light > ")).strip().lower()
        if raw == "q":
            break
        if raw == "":
            continue
        if raw == "on":
            value = 0xFF
        elif raw == "off":
            value = 0x00
        else:
            try:
                value = int(raw, 0)
            except ValueError:
                print("Type on, off, a number 0-255, or q.")
                continue
        value = clamp(value, 0, 255)
        await looi.set_light(value)
        print(f"Sent light = {value} (0x{value:02X})")


async def sensor_watch_mode(looi: Looi) -> None:
    print(
        """
Sensor watch (live)
  Lift each corner (cliff sensors) and touch the left/right side pads and the
  front center pad. Every change prints below as it arrives.
  Press ENTER to go back to menu.
"""
    )
    if looi.last_battery:
        print(f"Last battery reading: {looi.last_battery[0]}%")
    looi.watch_sensors = True
    await asyncio.to_thread(input, "")
    looi.watch_sensors = False


async def main(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    print(f"Connecting to {address}...")

    async with BleakClient(address, timeout=20.0) as client:
        looi = Looi(client)
        await looi.connect_and_init()
        heartbeat_task = asyncio.create_task(looi.heartbeat_loop())
        battery_task = asyncio.create_task(looi.battery_loop())
        try:
            while True:
                print(
                    """
Menu
  1) Drive (WASD, live)
  2) Head position (exact value)
  3) Light on/off
  4) Sensor watch (cliff + touch, live)
  q) Quit
"""
                )
                choice = (await asyncio.to_thread(input, "> ")).strip().lower()
                if choice == "1":
                    await drive_mode(looi)
                elif choice == "2":
                    await head_mode(looi)
                elif choice == "3":
                    await light_mode(looi)
                elif choice == "4":
                    await sensor_watch_mode(looi)
                elif choice == "q":
                    break
                else:
                    print("Unknown choice.")
        finally:
            await looi.shutdown()
            heartbeat_task.cancel()
            battery_task.cancel()
    print("Disconnected.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual LOOI BLE controller (Windows).")
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
