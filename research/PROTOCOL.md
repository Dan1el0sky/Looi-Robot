# LOOI Protocol — Our Findings

This tracks what we've confirmed on the actual hardware, on top of the
baseline protocol documented in [`reference/docs/PROTOCOL.md`](../reference/docs/PROTOCOL.md)
(the vendored `andrey-tut/LOOI-Robot` docs). Anything not listed here as
tested on our unit should still be treated as only what the reference repo
claims, not independently confirmed.

## Environment this was tested on

- Windows 11, Python 3.13.5, `bleak` 3.0.2 (installed system-wide, not a venv).
- `bleak` 3.0.2 API is confirmed compatible with the reference repo's calls
  (`BleakScanner.find_device_by_filter`, `BleakClient(address, timeout=...)`,
  `start_notify`, `write_gatt_char`, `read_gatt_char`) — checked signatures
  directly, no code changes needed for the BLE calls themselves.

## Windows compatibility

The reference repo's "recommended" scripts —
`looi_keyboard_control.py`, `looi_control_lab.py`, `wasd.py`, `connect.py` —
all `import termios`/`tty`/`select` for live keyboard input. Those modules
are POSIX-only and these scripts crash immediately on Windows
(`ModuleNotFoundError: termios`).

`reference/looi_interactive_probe.py` has no such dependency (menu +
`input()`-driven) and runs fine on Windows as-is.

For live WASD driving on Windows, we wrote
[`controller/looi_manual_control.py`](../controller/looi_manual_control.py):
same handshake/protocol, reimplemented with `msvcrt` instead of
`termios`/`tty`/`select` for non-blocking key reads. Menu: drive (WASD, latched
speed/turn with a 2s deadman auto-stop), exact head value, light on/off, and
a live sensor watch. Do not edit files under `reference/` — that's a
vendored, as-is copy of the upstream repo; new control code goes in
`controller/`.

Shared connection/handshake/decoding code lives in
[`controller/looi_protocol.py`](../controller/looi_protocol.py) (the `Looi`
class, `decode_fed9`, `find_device`) so it isn't duplicated between the
everyday driver and one-off diagnostics. One-off guided experiments — things
used to characterize a specific open question rather than to drive the
robot day to day — live under `testing/`, each a standalone script that
imports from `controller/looi_protocol.py`:
- `testing/capture_utils.py` — shared "run one labeled step, log every FED9
  *and* FED5 event with elapsed time, optional note" logic used by the two
  scripts below. FED5 is subscribed alongside FED9 (per the handshake) but
  the reference repo found it quiet in their own testing — we log it too
  now so that assumption isn't just inherited unverified.
- `testing/light_brightness_test.py` — the FED2 brightness sweep.
- `testing/front_sensor_test.py` — runs approach passes (object moved from
  out-of-range to touching) while logging every FED9 event type, to work
  out which one(s) actually respond near the front.
- `testing/tilt_test.py` — walks through a set of poses (tilt forward/back/
  left/right, roll onto each side, near-vertical nose up/down, yaw rotate,
  optional flip) to check whether `FED9` `0x02` responds to tilt as well as
  proximity, and to catch anything else unexpected from other sensors.
- `testing/dock_and_front_touch_test.py` — phone dock attach/detach and a
  few deliberate front-center touch attempts, since `0x12` never fired
  during the approach test.

## Confirmed working (live hardware test, 2026-09-27)

- BLE connect, `FEDA` activation handshake (`01` then `03`), and `FED5`/`FED9`
  notification subscription — succeeded via both
  `reference/looi_interactive_probe.py` and `controller/looi_manual_control.py`.
- `FED8` battery read — returned a plausible percentage during the handshake
  health check.
- `FED9` notify stream — live sensor events do arrive and print as they
  happen.
- `FED2` light: **on/off only, no brightness control on this unit.** Ran
  `testing/light_brightness_test.py` on 2026-09-27: swept
  `0x00, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xC0, 0xFF`, 1.5s each.
  Result (Daniel's words): "just on the whole time (no brightness control),
  like we only need to send on/off values, there is no brightness." So
  `0x00` = off, and every value from `0x02` up through `0xFF` looked
  identically full-on — no visible intermediate brightness anywhere in that
  range. This contradicts the reference repo's README, which marks `FED2`
  brightness as "Verified" across `0x00`-`0xFF`; on our unit it behaves like
  the community note in `reference/docs/PROTOCOL.md` describing `0x03` as an
  on/off-style activation, not the finer-grained claim. The exact on/off
  threshold between `0x00` and `0x02` (i.e. whether `0x01` alone is enough)
  wasn't explicitly reported and is still open, but is low-value to chase
  further — treat `FED2` as binary going forward: send `0x00` for off and
  any of `0xFF`/`0x01` for on.

- **`FED9` type `0x02` is a front proximity signal, not (only) an IMU axis
  pair.** The reference repo's README/`PROTOCOL.md` calls this "IMU-like",
  with the hypothesis "two signed 8-bit IMU/motion axes; isolated tests show
  one byte changes at a time" — that last observation is exactly right, but
  the cause looks wrong for our unit. Ran `testing/front_sensor_test.py` on
  2026-09-27 doing several approach passes with the robot stationary on a
  table (a toilet paper roll, then a hand, moved slowly toward the front and
  back, nothing else touched): logged in `testing/logs/front_sensor_*.csv`.

  Pattern across all passes: with nothing near the front, both bytes sit
  at `0xFF` (255). As the object approaches, **one byte at a time ramps down
  from 255 toward 0** — the second byte (`ch_b`) does this first, covering
  what looks like a "medium approach" zone; once it bottoms out at 0, the
  first byte (`ch_a`) starts ramping down from 255 toward 0 for the final
  approach to contact, where both bytes are near/at 0. Pulling the object
  back reverses this exactly (both climb back toward 255). This is a smooth,
  smoothly-many-samples-per-second, monotonic signal tied to how close the
  object is — not a single tilt/motion event. Daniel's own read of it while
  watching, twice, independently: "started detecting at about 3cm" and
  "detected at about 4-3cm" (toilet paper roll and hand respectively) — i.e.
  detection range starts roughly 3-4cm out and reaches 0/0 at contact.

  So on this unit, `FED9` `0x02` is a two-zone analog front proximity
  sensor — decoder in `controller/looi_protocol.py` now prints it as
  `front-proximity/imu candidate ch_a=X ch_b=Y` rather than "imu-like
  axis_a/axis_b", using raw unsigned 0-255 values (the proximity reading
  direction makes more sense unsigned than as a signed int8). The tilt-test
  result below confirms it's proximity-only, not tilt-sensitive, so the
  "imu candidate" half of that label is a leftover from the reference
  repo's original guess rather than something we've confirmed — kept in the
  decoder output for now as a pointer back to that history, not as a claim.

  This also resolves the earlier "front distance sensor isn't fully
  decoded" report — the sensor is real, it just isn't on the channel
  (`0x12`) the docs originally pointed at (see below).

- `FED9` type `0x12` ("front touch" per the reference repo): **confirmed
  working**, just needed a firmer, deliberate press — the earlier approach
  test (a toilet paper roll / hand moved slowly to "touching") never
  triggered it, but pressing directly on the front-center with real
  pressure does. Ran `testing/dock_and_front_touch_test.py` on 2026-09-27:
  got a stream of `12 00 00` (occasionally `12 00 02`) events repeating
  roughly every 0.15-0.2s *while held down*, not a single clean press/
  release pair — matches the reference repo's own note that "the front
  event currently appears as a pulse-like notification, not as a clean
  press/release pair." So both the front proximity (`0x02`, light contact/
  approach) and front touch (`0x12`, a real press) are real and distinct on
  this unit; the earlier "never fired" conclusion was about test technique,
  not missing hardware.

- `FED9` type `0x05`/`0x06` (phone dock attach/detach): **confirmed
  working**. Same test, attach/detach cycle done twice — `05` fired on
  attach, `06` on removal, both times, exactly as documented.

- `FED1` head position and `FED0` movement (WASD drive, via
  `controller/looi_manual_control.py`): confirmed working on this unit
  (Daniel, 2026-09-27).

- **`FED9` `0x02` is proximity-only, not tilt-sensitive** (resolves the
  question below). Ran `testing/tilt_test.py` on 2026-09-27: tilt forward,
  tilt backward, tilt left, tilt right, roll onto left side, roll onto
  right side, near-vertical nose-down, near-vertical nose-up — `0x02` fired
  **zero times** across all eight of those poses. It only appeared during
  the `yaw_rotate` step (rotating flat on the table), and Daniel's own note
  for that step explains why: "(my hand touched the front sensor)" — i.e.
  it was proximity to his hand during that pose, not the rotation itself.
  So across a real, varied set of orientation changes with nothing
  deliberately in front, this channel stayed completely silent unless
  something was actually near the front. Treat `0x02` as a dedicated front
  proximity sensor going forward, independent of tilt/orientation.
- Same run, incidental confirmation: `FED9` `0x01` (the four cliff sensors)
  fired constantly and sensibly while handling/tilting the unit — different
  combinations of `FL/FR/RL/RR` dropping to `0` as different corners lifted
  off the table and recovering to `1` once flat again. Matches the
  reference repo's active-low four-corner description; no surprises, but
  good real-world confirmation. (Left/right side touch events also fired
  throughout, as expected from gripping the unit to tilt it — handling
  noise, not signal, per Daniel's own caveat before the test.)

## Sensor inventory (what's actually on this unit, and likely technology)

Summary for a quick read, based on everything above plus the reference
repo's own `docs/FED9_TELEMETRY.md`. "Technology" is an inference from
behavior (range, response shape), not something read from a datasheet —
treat those as reasonable guesses, not fact.

| Sensor | Channel | Behavior | Likely technology | Status on this unit |
|---|---|---|---|---|
| Cliff/edge x4 (FL/FR/RL/RR) | `FED9 0x01` | Binary, active-low | IR floor-reflectance (no-surface-detected), same family as vacuum-robot cliff sensors | Confirmed working |
| Side touch, left | `FED9 0x09` | Binary press/release | Touch pad (capacitive most likely; can't confirm from software) | Confirmed working |
| Side touch, right | `FED9 0x0A` | Binary press/release | Same as left | Confirmed working |
| Front proximity | `FED9 0x02` | Analog 0-255, two channels, ramps smoothly, ~3-4cm range | IR proximity (LED + phototransistor) — short range and analog ramp don't fit ultrasonic or a simple digital touch | Confirmed working, proximity-only (see tilt test) |
| Front-center touch | `FED9 0x12` | Repeating pulse (~every 0.15-0.2s) while pressed, not a clean press/release pair | Touch pad (capacitive most likely) or a light mechanical switch | Confirmed working — needs a firm press, not just light contact |
| Phone dock attach/detach | `FED9 0x05`/`0x06` | Binary event | Mechanical switch or magnet/hall sensor in the cradle (guess, not tested) | Confirmed working |
| Battery % / USB present | `FED8` (read) + `FED9 0x0B` (event) | Percent + flag / binary event | Power-management IC, not an environmental sensor | Confirmed working (battery read; `0x0B` not specifically tested) |
| "Motion/attitude candidate" | `FED9 0x0E` | Reference repo: appears during yaw/roll/slide on *their* unit | Unknown | **Never fired** during our tilt test, including the yaw-rotate step — unconfirmed whether this exists on this unit |
| Dedicated IMU/gyro for orientation | — | — | — | No evidence of one. Notably, the reference repo's own docs say `0x02` "strongly appears during nose-down pitch tests" on *their* unit — our tilt test found the opposite (zero response across 8 tilt/roll/vertical poses). That's a real discrepancy between units, not just a naming mixup — see below. |

**Discrepancy worth flagging**: the reference repo's `docs/FED9_TELEMETRY.md`
describes `0x02` as tilt-responsive on their hardware ("strongly appears
during nose-down pitch tests", suggested events like
`tilt_nose_down_detected`, `orientation_changed`) and describes `0x0E` as
appearing "during yaw, roll, slide, and some vertical position changes."
On this unit, neither happened even once across 8 varied tilt/roll/vertical
poses with nothing in front of it (`0x12` is fine — see above, it just
needed a firmer press, unrelated to tilt). So the tilt/yaw-responsiveness
gap is specifically about `0x02`/`0x0E`, not a general "this unit's front
area doesn't work" situation. Take the reference repo's specific byte-level
claims as *their unit's* behavior, not guaranteed to transfer.

## Where things are

- `reference/` — vendored, unmodified copy of `andrey-tut/LOOI-Robot` (GPLv3).
  Treat as read-only reference; don't patch it, add new scripts here instead.
- `controller/looi_protocol.py` — shared connection/handshake/decoding code.
- `controller/looi_manual_control.py` — our own Windows-native manual
  controller (WASD drive, exact head value, light on/off, live sensor
  watch). This is the one to run day-to-day on this machine.
- `testing/` — standalone guided experiments, all resolved so far.
  `capture_utils.py` holds the shared step-runner; `light_brightness_test.py`
  (light is on/off only), `front_sensor_test.py` (found the front proximity
  signal, `0x02`), `tilt_test.py` (`0x02` is proximity-only, not
  tilt-sensitive), and `dock_and_front_touch_test.py` (phone dock and
  front-touch `0x12` both confirmed working) are the actual tests.
- `docs/PLAN.md` — overall project plan/phases.
- This file — running log of what's actually been confirmed vs. still open,
  specific to our unit and this Windows setup.
