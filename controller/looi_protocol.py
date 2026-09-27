"""Shared LOOI BLE protocol code: connection, handshake, and decoding.

Protocol reference: reference/docs/PROTOCOL.md. Reimplemented without
termios/tty/select so it runs on Windows (see research/PROTOCOL.md for why).
Used by controller/looi_manual_control.py and the scripts under testing/.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

NAME_CONTAINS = "LOOI"

CHAR_MOVE = "0000fed0-0000-1000-8000-00805f9b34fb"
CHAR_HEAD = "0000fed1-0000-1000-8000-00805f9b34fb"
CHAR_LIGHT = "0000fed2-0000-1000-8000-00805f9b34fb"
CHAR_SENS = "0000fed5-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY = "0000fed8-0000-1000-8000-00805f9b34fb"
CHAR_STREAM = "0000fed9-0000-1000-8000-00805f9b34fb"
CHAR_FEDA = "0000feda-0000-1000-8000-00805f9b34fb"
UUID_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"

MOVE_INTERVAL_S = 0.03
BATTERY_INTERVAL_S = 4.0


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def signed_byte(value: int) -> int:
    return clamp(value, -127, 127) & 0xFF


def int8(value: int) -> int:
    return value - 256 if value >= 128 else value


def decode_fed9(data: bytes) -> str:
    if not data:
        return "empty"
    if data == b"\x11\x01\x00":
        return "boot/init complete"
    if data == b"\x05":
        return "phone docked"
    if data == b"\x06":
        return "phone removed"
    packet_type = data[0]
    if packet_type == 0x01 and len(data) >= 5:
        fl, fr, rl, rr = data[1], data[2], data[3], data[4]
        active = [
            name
            for name, value in (("front-left", fl), ("front-right", fr), ("rear-left", rl), ("rear-right", rr))
            if value == 0
        ]
        return f"cliff sensors FL={fl} FR={fr} RL={rl} RR={rr} (triggered: {', '.join(active) if active else 'none'})"
    if packet_type == 0x02 and len(data) >= 3:
        # Reference repo calls this "IMU-like". Live testing (research/PROTOCOL.md,
        # "Front proximity signal") instead shows one byte at a time ramping
        # 255->0 as an object approaches the front and 0->255 as it retreats --
        # this looks like a two-zone front proximity sensor, not (only) an IMU.
        return f"front-proximity/imu candidate ch_a={data[1]} ch_b={data[2]}"
    if packet_type == 0x09 and len(data) >= 2:
        return f"left side touch {'pressed' if data[1] == 1 else 'released'}"
    if packet_type == 0x0A and len(data) >= 2:
        return f"right side touch {'pressed' if data[1] == 1 else 'released'}"
    if packet_type == 0x0B and len(data) >= 2:
        return f"external power {'connected' if data[1] == 1 else 'disconnected'}"
    if packet_type == 0x0E and len(data) >= 3:
        return f"motion/attitude candidate b1={data[1]} b2={data[2]}"
    if packet_type == 0x12 and len(data) >= 3:
        return f"front touch event b1={data[1]} b2={data[2]}"
    return f"unknown type=0x{packet_type:02x} len={len(data)}"


@dataclass
class MoveState:
    speed: int = 0
    turn: int = 0
    step: int = 32
    last_key_time: float = 0.0

    def payload(self) -> bytes:
        return bytes([signed_byte(self.speed), signed_byte(self.turn)])

    def stop(self) -> None:
        self.speed = 0
        self.turn = 0


class Looi:
    def __init__(self, client: BleakClient):
        self.client = client
        self.chars: dict[str, Any] = {}
        self.last_battery: Optional[bytes] = None
        self.running = True
        self.watch_sensors = False
        self.move_state = MoveState()
        self.on_fed9: Optional[Callable[[bytes], None]] = None
        self.on_fed5: Optional[Callable[[bytes], None]] = None

    async def connect_and_init(self) -> None:
        try:
            manufacturer = bytes(await self.client.read_gatt_char(UUID_MANUFACTURER))
            print(f"Device info (2A29): {manufacturer!r}")
        except Exception as exc:
            print(f"2A29 read skipped: {exc}")

        for _attempt in range(12):
            try:
                _ = self.client.services
                break
            except BleakError:
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Bluetooth service discovery did not complete")

        required = [CHAR_MOVE, CHAR_HEAD, CHAR_LIGHT, CHAR_SENS, CHAR_BATTERY, CHAR_STREAM, CHAR_FEDA]
        missing = []
        for uuid in required:
            characteristic = self.client.services.get_characteristic(uuid)
            if characteristic is None:
                missing.append(uuid)
            else:
                self.chars[uuid] = characteristic
        if missing:
            raise RuntimeError("Missing characteristics: " + ", ".join(missing))

        print("Handshake: FEDA <- 01")
        await self._write(CHAR_FEDA, b"\x01", response=True)
        await asyncio.sleep(0.1)

        print("Subscribing to FED5 / FED9")
        await self.client.start_notify(self.chars[CHAR_SENS], self._on_fed5)
        await self.client.start_notify(self.chars[CHAR_STREAM], self._on_fed9)
        await asyncio.sleep(0.3)

        print("Handshake: FEDA <- 03")
        await self._write(CHAR_FEDA, b"\x03", response=True)
        await asyncio.sleep(0.2)

        await self._write(CHAR_MOVE, b"\x00\x00", response=False)
        battery = bytes(await self.client.read_gatt_char(self.chars[CHAR_BATTERY]))
        self.last_battery = battery
        percent = battery[0] if battery else None
        status = "USB power" if len(battery) > 1 and battery[1] == 1 else "battery"
        print(f"Connected. Battery: {percent}% ({status})")

    async def _write(self, uuid: str, payload: bytes, response: bool) -> None:
        await self.client.write_gatt_char(self.chars[uuid], payload, response=response)

    def _on_fed5(self, _sender: Any, data: bytearray) -> None:
        # Subscribed for compatibility; reference repo found it quiet in local
        # testing, but we haven't independently confirmed that on this unit.
        if self.on_fed5:
            self.on_fed5(bytes(data))

    def _on_fed9(self, _sender: Any, data: bytearray) -> None:
        raw = bytes(data)
        if self.watch_sensors:
            print(f"\n[sensor] {raw.hex()} -> {decode_fed9(raw)}")
        if self.on_fed9:
            self.on_fed9(raw)

    async def heartbeat_loop(self) -> None:
        while self.running:
            try:
                await self._write(CHAR_MOVE, self.move_state.payload(), response=False)
            except Exception as exc:
                print(f"\nheartbeat error: {exc}")
                await asyncio.sleep(0.2)
            await asyncio.sleep(MOVE_INTERVAL_S)

    async def battery_loop(self) -> None:
        while self.running:
            try:
                self.last_battery = bytes(await self.client.read_gatt_char(self.chars[CHAR_BATTERY]))
            except Exception:
                pass
            await asyncio.sleep(BATTERY_INTERVAL_S)

    async def set_head(self, value: int) -> None:
        await self._write(CHAR_HEAD, bytes([clamp(value, 0, 255)]), response=False)

    async def set_light(self, value: int) -> None:
        await self._write(CHAR_LIGHT, bytes([clamp(value, 0, 255)]), response=True)

    async def shutdown(self) -> None:
        self.running = False
        try:
            await self._write(CHAR_MOVE, b"\x00\x00", response=False)
            await self._write(CHAR_LIGHT, b"\x00", response=True)
        except Exception:
            pass


async def find_device(address: Optional[str]) -> str:
    if address:
        return address
    print(f"Scanning for a device containing '{NAME_CONTAINS}'...")
    device = await BleakScanner.find_device_by_filter(
        lambda discovered, _adv: NAME_CONTAINS.lower() in (discovered.name or "").lower(),
        timeout=8.0,
    )
    if not device:
        raise RuntimeError("LOOI not found. Close the official app, check Bluetooth, and try again.")
    print(f"Found {device.name} at {device.address}")
    return device.address
