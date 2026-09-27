"""Shared helper for the guided testing/ scripts.

Each script in testing/ walks through a list of labeled steps (an approach
pass, a pose to hold, etc.), and for each one: prints instructions, waits
for ENTER to start, logs every event from *both* subscribed notify
characteristics (FED9 telemetry and FED5, which the reference repo found
quiet but we haven't independently confirmed on this unit) with an
elapsed-time-in-step column, until ENTER again, then takes an optional
note. This is that shared step runner plus the common CSV shape, so each
test script only needs its own list of (label, instruction) pairs.
"""

import asyncio
import time

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "controller"))
from looi_protocol import Looi, decode_fed9  # noqa: E402

CSV_HEADER = ["recorded_at", "step", "elapsed_in_step_s_or_note", "elapsed_total_s", "source", "raw_hex", "decoded_or_note"]


async def run_guided_step(
    looi: Looi,
    label: str,
    instruction: str,
    writer: "csv._writer",
    log_file,
    run_start: float,
    skippable: bool = True,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"STEP: {label}")
    print(instruction)
    prompt = "Press ENTER to start recording" + (" (or 's' to skip) > " if skippable else " > ")
    choice = (await asyncio.to_thread(input, prompt)).strip().lower()
    if skippable and choice == "s":
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), label, "skipped", "", "", "", ""])
        log_file.flush()
        print(f"Skipped {label}.")
        return

    step_start = time.time()

    def log_event(source: str, raw: bytes, decoded: str) -> None:
        elapsed = time.time() - step_start
        total_elapsed = time.time() - run_start
        print(f"  [{label}] +{elapsed:5.2f}s  {source}  {raw.hex()}  {decoded}")
        writer.writerow(
            [
                time.strftime("%Y-%m-%d %H:%M:%S"),
                label,
                f"{elapsed:.2f}",
                f"{total_elapsed:.2f}",
                source,
                raw.hex(),
                decoded,
            ]
        )
        log_file.flush()

    def on_fed9(raw: bytes) -> None:
        if raw:
            log_event(f"FED9 0x{raw[0]:02x}", raw, decode_fed9(raw))

    def on_fed5(raw: bytes) -> None:
        log_event("FED5", raw, "(no known decoding -- reference repo calls this quiet)")

    looi.on_fed9 = on_fed9
    looi.on_fed5 = on_fed5
    print("Recording... press ENTER again to stop.")
    await asyncio.to_thread(input, "")
    looi.on_fed9 = None
    looi.on_fed5 = None

    note = (await asyncio.to_thread(input, f"Optional note for '{label}' (blank to skip) > ")).strip()
    if note:
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), label, "note", "", "", "", note])
        log_file.flush()
