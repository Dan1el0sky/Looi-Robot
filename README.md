# LOOI Robot — Custom Control Project

Unofficial project to understand and extend a LOOI robot (TangibleFuture) beyond
what the stock app exposes: full access to its action/animation library
(instead of "random" idle behavior), sensor-reactive collision handling, and
eventually a custom control app.

This is not starting from zero — [andrey-tut/LOOI-Robot](https://github.com/andrey-tut/LOOI-Robot)
already reverse-engineered much of the BLE protocol (vendored under `reference/`,
GPLv3, with full attribution to the original author). This project builds on
that work, fills in the gaps (notably the `FE00` gesture command set, which
the reference repo sniffed but didn't integrate), and adds a trigger-based
behavior layer.

See [docs/PLAN.md](docs/PLAN.md) for the full project plan and
[CLAUDE.md](CLAUDE.md) for working conventions.

## Layout

- `reference/` — a vendored copy of `andrey-tut/LOOI-Robot` ([source](https://github.com/andrey-tut/LOOI-Robot), GPLv3 — see `reference/LICENSE`), kept as-is for reference.
- `research/` — decompiled APK notes, protocol findings, FCC filing notes.
- `controller/` — our own Python control library (built on `bleak`).
- `docs/` — project plan and other project-level docs.

## Hardware

- Robot: LOOI (TangibleFuture), FCC ID `2BLAY-01`.
- Official app: `com.TangibleFuture.looiRobot` (Android), also available on iOS.
- Control phones on hand: iPhone 13, jailbroken (rootless) iPhone SE 2nd gen. No Android device.

## Safety

This drives a physical robot. Always test in a clear area, start at low speed,
and never let the motors stall against an obstacle. See
[`reference/docs/SAFETY.md`](reference/docs/SAFETY.md) for the baseline
procedure this project follows.
