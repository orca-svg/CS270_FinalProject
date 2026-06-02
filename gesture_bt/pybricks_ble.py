"""Shared Pybricks BLE client utilities for the LEGO SPIKE controllers."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Optional

try:
    from bleak import BleakClient, BleakScanner
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package: bleak. Install with: python -m pip install bleak") from exc

PYBRICKS_COMMAND_EVENT_CHAR_UUID = "c5f50002-8280-46da-89f4-6d8051e4aeef"
PYBRICKS_SERVICE_UUID = "c5f50001-8280-46da-89f4-6d8051e4aeef"
DEFAULT_HUB_NAME = "Pybricks Hub"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def i8(value: int | float) -> int:
    return int(clamp(int(value), -100, 100)) & 0xFF


def packet_for(command: str) -> bytes:
    """Build the 4-byte position-tracking packet used by the Hub program."""
    cmd = command.strip().upper()
    if cmd.startswith("M,"):
        parts = cmd.split(",")
        if len(parts) != 4:
            raise ValueError(f"Motion command must have 4 fields: {command!r}")
        pan_err = i8(float(parts[1]))
        tilt_err = i8(float(parts[2]))
        fire = int(parts[3]) & 0xFF
        return bytes([ord("M"), pan_err, tilt_err, fire])
    if cmd == "STOP":
        return b"S\x00\x00\x00"
    raise ValueError(f"Unknown command: {command!r}")


class PybricksBleSender:
    def __init__(
        self,
        hub_name: str,
        scan_timeout: float = 15.0,
        *,
        reconnect: bool = True,
        stale_timeout: float = 2.0,
    ) -> None:
        self.hub_name = hub_name
        self.scan_timeout = scan_timeout
        self.reconnect = reconnect
        self.stale_timeout = stale_timeout
        self.client: Optional[BleakClient] = None
        self.ready = asyncio.Event()
        self.connected = False
        self.print_sends = False
        self.last_wait_log = 0.0
        self.last_rx = 0.0
        self._connect_time = 0.0
        self._rx_text_buffer = ""
        self._reconnecting = False
        self._stale_warned = False
        self._closing = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def _find_device(self):
        print(f"[SCAN] name='{self.hub_name}' timeout={self.scan_timeout:.1f}s")
        device = await BleakScanner.find_device_by_name(self.hub_name, timeout=self.scan_timeout)
        if device is not None:
            print(f"[SCAN] found by name: {device.name or '(unknown)'}")
            return device

        print(f"[SCAN] name miss. Falling back to Pybricks service UUID {PYBRICKS_SERVICE_UUID}.")
        service_uuid = PYBRICKS_SERVICE_UUID.lower()

        def matches_pybricks(candidate, advertisement_data) -> bool:
            service_uuids = [str(u).lower() for u in getattr(advertisement_data, "service_uuids", [])]
            return service_uuid in service_uuids

        with contextlib.suppress(Exception):
            device = await BleakScanner.find_device_by_filter(matches_pybricks, timeout=self.scan_timeout)
            if device is not None:
                print(f"[SCAN] found by Pybricks service UUID: {device.name or '(unknown)'}")
                return device

        candidates = await BleakScanner.discover(timeout=self.scan_timeout)
        pybricks_hubs = []
        for candidate in candidates:
            metadata = getattr(candidate, "metadata", {}) or {}
            uuids = [str(u).lower() for u in (metadata.get("uuids") or [])]
            if service_uuid in uuids:
                pybricks_hubs.append(candidate)

        if pybricks_hubs:
            names = [d.name or "(unknown)" for d in pybricks_hubs]
            print(f"[SCAN] found Pybricks Hub candidates: {names}")
            print(f"[SCAN] using first candidate. For stable scans, run with --hub-name '{pybricks_hubs[0].name}'.")
            return pybricks_hubs[0]

        print("[SCAN] no matching Hub. Disconnect Pybricks Code/SPIKE app, power-cycle Hub, and retry.")
        return None

    async def connect(self) -> None:
        self._closing = False
        device = await self._find_device()
        if device is None:
            raise RuntimeError(
                f"Could not find '{self.hub_name}' and no Pybricks Hub found nearby. "
                "Disconnect Pybricks Code/SPIKE app, turn the Hub on, and try again."
            )
        await self._do_connect(device)

    async def _do_connect(self, device) -> None:
        self._loop = asyncio.get_running_loop()

        def handle_disconnect(_: BleakClient) -> None:
            self.connected = False
            self.ready.clear()
            now = time.time()
            up = now - self._connect_time if self._connect_time else 0.0
            silent = now - self.last_rx if self.last_rx else -1.0
            print(f"\n[DISCONNECT] up={up:.1f}s last_hub_rx={silent:.1f}s")
            if self.reconnect and not self._closing and not self._reconnecting and self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._reconnect_loop()))

        self.client = BleakClient(device, disconnected_callback=handle_disconnect)
        await self.client.connect()
        self._rx_text_buffer = ""
        self.ready.clear()
        self._stale_warned = False
        self.connected = True
        self._connect_time = time.time()
        self.last_rx = time.time()
        print(f"[BLE] connected to {device.name or '(unknown)'}")
        await self.client.start_notify(PYBRICKS_COMMAND_EVENT_CHAR_UUID, self._handle_rx)
        print("[NOTIFY] started. Start the saved Hub program with the Hub center button if needed.")

    async def _reconnect_loop(self) -> None:
        self._reconnecting = True
        attempt = 0
        while self.reconnect and not self._closing and not self.connected:
            attempt += 1
            print(f"[RECONNECT] attempt={attempt}")
            try:
                device = await self._find_device()
                if device is None:
                    print("[RECONNECT] Hub not found. Retrying in 3s.")
                    await asyncio.sleep(3.0)
                    continue
                await self._do_connect(device)
                print("[RECONNECT] BLE reconnected. Waiting up to 2s for Hub rdy.")
                try:
                    await asyncio.wait_for(self.ready.wait(), timeout=2.0)
                    print("[READY] reconnect rdy received; Hub program resumed.")
                except asyncio.TimeoutError:
                    print("[WAIT] BLE reconnected, but Hub rdy is missing. Press the Hub center button if the saved program stopped.")
                break
            except Exception as exc:
                print(f"[RECONNECT] error: {exc}. Retrying in 3s.")
                await asyncio.sleep(3.0)
        self._reconnecting = False

    def _handle_rx(self, _: int, data: bytearray) -> None:
        if not data or data[0] != 0x01:
            return
        self.last_rx = time.time()
        self._stale_warned = False
        payload = bytes(data[1:])
        if b"rdy" in payload:
            self.ready.set()
            payload = payload.replace(b"rdy", b"")

        text = payload.decode("utf-8", errors="replace")
        if not text:
            return
        self._rx_text_buffer += text
        while "\n" in self._rx_text_buffer:
            line, self._rx_text_buffer = self._rx_text_buffer.split("\n", 1)
            line = line.strip()
            if line:
                print(f"[Hub] {line}")

    async def wait_until_ready(self, timeout: float = 20.0) -> bool:
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
            print("[READY] first rdy received.")
            return True
        except asyncio.TimeoutError:
            print("[WAIT] Hub did not send rdy. Press Hub center button, disconnect Pybricks Code/SPIKE app, and confirm Hub display shows BT.")
            return False

    async def send(self, command: str, timeout: float = 1.0) -> bool:
        if not self.client or not self.connected:
            print(f"[BLE] not connected; skipped {command.strip()!r}")
            return False
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            now = time.time()
            if now - self.last_wait_log > 2.0:
                print("[WAIT] Hub program is not sending rdy. Press Hub center button, disconnect Pybricks Code/SPIKE app, and confirm display shows BT.")
                self.last_wait_log = now
            return False

        self.ready.clear()
        try:
            packet = packet_for(command)
        except ValueError as exc:
            print(f"[SEND] invalid command: {exc}")
            return False

        if self.print_sends:
            print(f"[SEND] {command.strip()} -> {packet!r}")
        try:
            await self.client.write_gatt_char(
                PYBRICKS_COMMAND_EVENT_CHAR_UUID,
                b"\x06" + packet,
                response=True,
            )
            return True
        except Exception as exc:
            print(f"[BLE] write failed: {exc}")
            self.connected = False
            self.ready.clear()
            if self.reconnect and not self._closing and not self._reconnecting and self._loop and self._loop.is_running():
                self._loop.call_soon(lambda: asyncio.ensure_future(self._reconnect_loop()))
            return False

    def maybe_warn_stale(self, silence_limit: Optional[float] = None) -> None:
        limit = self.stale_timeout if silence_limit is None else silence_limit
        if not self.connected or self._stale_warned or not self.last_rx:
            return
        if time.time() - self.last_rx > limit:
            print("[STALE] Hub is silent. BLE may still be connected, but the saved Hub program may be stopped/crashed.")
            self._stale_warned = True

    async def close(self) -> None:
        self._closing = True
        if self.client:
            with contextlib.suppress(Exception):
                await self.send("STOP", timeout=0.2)
            with contextlib.suppress(Exception):
                await self.client.disconnect()


class DryRunSender:
    print_sends = False

    async def connect(self) -> None:
        print("DRY RUN: no BLE connection. Commands will be printed only.")

    async def wait_until_ready(self, timeout: float = 0.0) -> bool:
        print("[READY] dry-run ready.")
        return True

    async def send(self, command: str, timeout: float = 0.0) -> bool:
        print(f"[DRY] {command}")
        return True

    def maybe_warn_stale(self, silence_limit: Optional[float] = None) -> None:
        return

    async def close(self) -> None:
        pass
