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
- No Android device is available, but the protocol is device-side, not platform-side, so validation doesn't require Android specifically. Two options, in order of preference:
  1. **BLE sniffer dongle** (e.g. Nordic nRF52840 dongle running the Nordic sniffer firmware) plugged into this Windows PC, capturing over-the-air packets with Wireshark while the official app runs on the iPhone 13. Confirms `FE00` payloads and anything Phase 1 found, independent of phone OS.
  2. If a dongle isn't available/practical: explore what the rootless jailbreak on the iPhone SE can expose (e.g. Apple's PacketLogger workflow, or a CoreBluetooth-logging tweak) as a fallback — noted as lower-confidence/more fragile than a dedicated sniffer.
- This phase is exploratory and its exact steps depend on what Phase 1 turns up (if the `FE00` format is fully recoverable from static analysis alone, live sniffing may only be needed to spot-check rather than reverse from scratch).

### Phase 4 — Build the PC control library
- Package: `controller/looi/` — extend/re-implement (with credit, respecting the reference repo's license) the known-good movement/sensor/handshake logic, then add:
  - Decoded `FE00` gesture playback, exposed as named, explicitly triggerable actions (directly addressing "actions happen randomly instead of being triggered").
  - A small event/trigger framework: e.g. "on front touch → play X", "on command → play Y" — replacing reliance on the robot's own autonomous idle loop.
  - A sensor-reactive stop/backoff behavior using the documented cliff/touch sensors as an immediate, low-risk mitigation for collisions (real vision-based avoidance is a Phase 5 concern).
- Keep the existing repo's `SAFETY.md` guidance (clear test area, low speed first, no motor stalling) as the operating procedure while testing.

### Phase 5 — Obstacle-avoidance prototype (exploratory)
- Once Phase 1 confirms whether/how the stock app does camera-based navigation, prototype an improved version in Python (OpenCV / a small vision model) driving the Phase 4 library — this stays a PC-tethered prototype for now (e.g. laptop webcam or phone-as-webcam), not the final on-device form.

### Explicitly deferred (future milestone, not built now)
- Custom iOS app (Swift + CoreBluetooth) wrapping the validated protocol, behavior engine, and vision logic. Design choices above (clean protocol module, explicit trigger framework) are made so this port is straightforward later, but no iOS code is written in this pass.

## Verification
- Phase 0: `git log` shows initial commit; repo structure present.
- Phase 1: decompiled output present under `research/apk/`, findings written to `research/PROTOCOL.md` with specific byte-level detail for `FE00` (or explicitly marked unresolved if static analysis isn't enough).
- Phase 4: manual hardware test on the real robot — connect, run handshake, send a movement command, trigger a decoded gesture, confirm sensor notifications arrive — following the safety procedure (clear area, low speed) each time, since this drives a physical device.
