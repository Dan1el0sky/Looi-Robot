# LOOI Robot — Reverse Engineering & Custom Control Project

## Context

The user owns a LOOI robot (a phone-docking desktop robot by TangibleFuture) and an iPhone 13 plus a rootless-jailbroken iPhone SE 2nd gen. The stock experience is limited: the robot collides with objects, plays "random" idle actions instead of ones that can be deliberately triggered, and the official app only exposes ~3 games. The goal is to build a full custom control stack for the robot — first as a PC-based BLE controller to prove out the protocol and behavior logic, later (explicitly a future milestone, not part of this build) as a custom iOS app.

Key research done during discussion, before writing this plan:
- **Prior art exists and is substantial**: [andrey-tut/LOOI-Robot](https://github.com/andrey-tut/LOOI-Robot) is an open-source, unofficial reverse-engineering project for this exact robot. It documents the BLE GATT protocol and ships a working Python/Bleak controller. We are not starting from zero.
- **Known protocol** (from that repo's `docs/PROTOCOL.md` and related docs):
  - `FEDA` — activation handshake (`01` → `03`) required before any control works
  - `FED0` — movement: two signed bytes `[speed, turn]`, sent continuously (~every 30ms)
  - `FED1` — head pitch (center byte `0x5A`)
  - `FED2` — headlight brightness
  - `FED8` — battery / USB power status (read)
  - `FED9` — notifications: 4 active-low cliff/contact sensors, touch events (left/right/front), phone-dock attach/detach, partial IMU (two signed 8-bit axes)
  - `FE00` — scripted gesture payloads: **sniffed but explicitly marked "not integrated yet"** in the reference repo — this is the most likely home of the hidden animation/behavior library behind "random" actions and the missing games
- **No dedicated forward-facing obstacle sensor is documented** — only cliff (edge/fall) sensors and touch. This strongly suggests the stock app's "obstacle avoidance" (such as it is) runs as computer vision on the phone's own camera, not on the robot. Supporting evidence: the official app (`com.TangibleFuture.looiRobot`, v2.9.2 on APKPure) is **985.7MB** — far too large for a simple BLE remote, consistent with bundled on-device ML/vision models.
- A direct fetch of the FCC filing (`fccid.io/2BLAY-01`) the user linked returned HTTP 403; it likely has useful internal-photos/RF details but needs a different access method (e.g. `fcc.report` mirror, or manual browser visit) — deferred to when it's actually needed.

Given this, the plan front-loads validating and extending the existing protocol work (especially decoding `FE00` gestures and finding the vision/navigation logic in the APK) rather than sniffing BLE traffic from scratch.

## Scope for this pass

Build the project skeleton and get through protocol research + a working PC-side control library. The custom iOS app is an explicit future milestone — not implemented now, only accounted for in the design so today's protocol/behavior layer is reusable later.

## Plan

### Phase 0 — Project scaffolding
- `git init` in `D:\Looi-Robot` (currently empty except this session's `CLAUDE.md`).
- Create baseline structure:
  - `README.md` — project purpose, hardware, safety notes, credit to `andrey-tut/LOOI-Robot` as prior art.
  - `research/` — decompiled APK notes, protocol findings, FCC filing notes.
  - `reference/` — the `andrey-tut/LOOI-Robot` repo, pulled in as a `git submodule` (keeps their commit history and license separate rather than copy-pasting their code).
  - `controller/` — our own Python package (built on `bleak`, cross-platform, runs on this Windows PC without needing Android or iOS).
  - `.gitignore` (Python venv, decompiled APK output, logs).
- First commit.

### Phase 1 — Acquire and decompile the official APK
- **Requires explicit go-ahead before downloading**, per the assistant's own file-download rule (source: the APKPure link the user provided, `com.TangibleFuture.looiRobot`, XAPK, ~985MB) — will confirm filename/source/size at that point rather than assuming approval from this plan.
- Decompile with `jadx` (Java source recovery) and `apktool` (resources/assets) into `research/apk/`.
- Specifically hunt for:
  1. The `FE00` gesture payload format (opcode table, byte layout) — this unlocks the full animation/behavior library.
  2. Any full BLE characteristic/UUID table the app defines, to check for characteristics the reference repo hasn't documented.
  3. The obstacle-avoidance / navigation code path — confirm whether it's phone-camera CV (model files, e.g. `.tflite`/`.onnx`/`.mlmodel` under assets, or a vision SDK) versus anything robot-side.
  4. Game logic for the existing 3 games, as a template for adding more.

### Phase 2 — Consolidate protocol knowledge
- Write up `research/PROTOCOL.md` in our own repo: merge the reference repo's documented characteristics with whatever Phase 1 adds (especially `FE00`), noting confidence level (verified vs inferred) for each.
- Cross-reference against the FCC filing (`2BLAY-01`) for the actual BLE chipset/module and motor driver — informs realistic limits (e.g. max safe motor command rate, radio range).

### Phase 3 — Validate against live traffic
- **Confirmed: the PC's built-in Bluetooth radios cannot do this.** This machine has an Intel Wireless Bluetooth combo chip and a Broadcom BCM20702B0 dongle; neither supports promiscuous/monitor-mode BLE capture, and that's a hardware/firmware limitation of standard Bluetooth controllers — switching this PC to Linux would not unlock it (BlueZ has the same HCI-level restriction; it only logs the host's own connections, not third-party over-the-air traffic). No BLE sniffer dongle is currently owned.
- Given that, the plan doesn't depend on sniffing as the primary method:
  1. **Primary: decompile + direct fuzzing.** Phase 1's decompilation may reveal the `FE00` byte table directly in app source/constants. Separately, since our own Phase 4 controller already connects to the robot as its own BLE central (via `bleak`, no phone involved), we can try candidate `FE00` payloads ourselves and observe the robot's reaction directly — no sniffer needed for this.
  2. **Optional confirmation: cheap dedicated sniffer.** A real over-the-air capture (to see exactly what the official app sends) still needs dedicated sniffer hardware — e.g. a ~$10 Nordic nRF52840 dongle flashed with Nordic's sniffer firmware, or a TI CC2540-based sniffer dongle. This is inexpensive and works on Windows or Linux, but it's a small hardware purchase, not something built in — buy one later only if fuzzing + decompilation leave gaps.
  3. Lower-confidence fallback: whatever the rootless jailbreak on the iPhone SE can expose (e.g. a CoreBluetooth-logging tweak) — kept as a last resort, not the plan of record.
- This phase is exploratory and may end up mostly unnecessary if Phase 1 + direct fuzzing fully resolve `FE00`.

### Phase 4 — Build the PC control library
- Package: `controller/looi/` — extend/re-implement (with credit, respecting the reference repo's license) the known-good movement/sensor/handshake logic, then add:
  - Decoded `FE00` gesture playback, exposed as named, explicitly triggerable actions (directly addressing "actions happen randomly instead of being triggered").
  - A small event/trigger framework: e.g. "on front touch → play X", "on command → play Y" — replacing reliance on the robot's own autonomous idle loop.
  - A sensor-reactive stop/backoff behavior using the documented cliff/touch sensors as an immediate, low-risk mitigation for collisions (real vision-based avoidance is a Phase 5 concern).
- Keep the existing repo's `SAFETY.md` guidance (clear test area, low speed first, no motor stalling) as the operating procedure while testing.

### Phase 5 — Obstacle-avoidance prototype (exploratory)
- Once Phase 1 confirms whether/how the stock app does camera-based navigation, prototype an improved version in Python (OpenCV / a small vision model) driving the Phase 4 library — this stays a PC-tethered prototype for now (e.g. laptop webcam or phone-as-webcam), not the final on-device form.

### Deferred — deep-dive into the reference repo (not now)
- The `reference/` submodule (`andrey-tut/LOOI-Robot`) has more in it than the top-level protocol summary already pulled into this plan: `docs/EXPERIMENTS.md`, `docs/CONTROL_LAB.md`, `docs/FED9_TELEMETRY.md`, `docs/OPEN_QUESTIONS.md`, `docs/ROADMAP.md`, and the actual controller scripts (`looi_keyboard_control.py`, `looi_control_lab.py`, `looi_analyze_sensors.py`).
- Worth a dedicated pass later to: mine `OPEN_QUESTIONS.md` for anything the maintainer already flagged as unresolved (may overlap with our `FE00`/obstacle-avoidance questions), read the actual Python implementation rather than just the docs summary (docs can drift from code), and check the repo's issues/commit history for any progress since we cloned it (e.g. if `FE00` gets integrated upstream, that removes work from our Phase 1/3).
- Deferred because Phase 1 (APK decompilation) is a more direct route to the open questions we care about most (`FE00`, obstacle avoidance) — this is a secondary/backfill source, not a blocker.

### Explicitly deferred (future milestone, not built now)
- Custom iOS app (Swift + CoreBluetooth) wrapping the validated protocol, behavior engine, and vision logic. Design choices above (clean protocol module, explicit trigger framework) are made so this port is straightforward later, but no iOS code is written in this pass.

## Verification
- Phase 0: `git log` shows initial commit; repo structure present.
- Phase 1: decompiled output present under `research/apk/`, findings written to `research/PROTOCOL.md` with specific byte-level detail for `FE00` (or explicitly marked unresolved if static analysis isn't enough).
- Phase 4: manual hardware test on the real robot — connect, run handshake, send a movement command, trigger a decoded gesture, confirm sensor notifications arrive — following the safety procedure (clear area, low speed) each time, since this drives a physical device.
