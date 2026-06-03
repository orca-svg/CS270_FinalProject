"""Shared Pybricks BLE client utilities for LEGO SPIKE controllers."""

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

PYBRICKS_CMD_STOP_USER_PROGRAM = 0
PYBRICKS_CMD_START_USER_PROGRAM = 1


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
    _EVENT_STATUS_REPORT = 0
    _EVENT_WRITE_STDOUT = 1
    _STATUS_USER_PROGRAM_RUNNING = 0x40

    def __init__(
        self,
        hub_name: str,
        scan_timeout: float = 15.0,
        *,
        connect_timeout: float = 45.0,
        connect_attempts: int = 3,
        connect_retry_delay: float = 2.0,
        reconnect: bool = True,
        stale_timeout: float = 2.0,
        auto_start: bool = True,
        allow_open_loop: bool = False,
        restart_on_stop: bool = True,
    ):
        self.hub_name = hub_name
        self.scan_timeout = scan_timeout
        self.connect_timeout = connect_timeout
        self.connect_attempts = max(1, int(connect_attempts))
        self.connect_retry_delay = connect_retry_delay
        self.reconnect = reconnect
        self.stale_timeout = stale_timeout
        self.auto_start = auto_start
        self.allow_open_loop = allow_open_loop
        self.restart_on_stop = restart_on_stop

        self.client = None
        self.ready = asyncio.Event()
        self.connected = False
        self.print_sends = False
        self.debug_rx = False
        # Optional callback invoked with each complete Hub stdout line. Lets
        # callers (e.g. dataset loggers) react to Hub messages like "SHOT ...".
        self.line_handler = None

        self._rx_debug_count = 0
        self._program_running: Optional[bool] = None
        self._running_event = asyncio.Event()
        self._stdout_seen = False
        self._open_loop = False
        self._ever_sent_stdin = False
        self.last_wait_log = 0.0
        self.last_rx = 0.0
        self._connect_time = 0.0
        self._rx_text_buffer = ""
        self._reconnecting = False
        self._connecting = False
        self._stale_warned = False
        self._closing = False
        self._loop = None
        self._last_start_attempt = 0.0
        self._start_cooldown = 1.5
        self.recovery_generation = 0

    async def _find_device(self):
        print(f"[SCAN] name='{self.hub_name}' timeout={self.scan_timeout:.1f}s")
        device = await BleakScanner.find_device_by_name(self.hub_name, timeout=self.scan_timeout)
        if device:
            print(f"[SCAN] found by name: {device.name or '(unknown)'}")
            return device

        print(f"[SCAN] name miss. Falling back to Pybricks service UUID {PYBRICKS_SERVICE_UUID}.")
        service_uuid = PYBRICKS_SERVICE_UUID.lower()

        def matches_pybricks(d, _advertisement_data):
            metadata = getattr(d, "metadata", {}) or {}
            uuids = [str(u).lower() for u in metadata.get("uuids", [])]
            return service_uuid in uuids

        with contextlib.suppress(Exception):
            device = await BleakScanner.find_device_by_filter(matches_pybricks, timeout=self.scan_timeout)
            if device:
                print(f"[SCAN] found by Pybricks service UUID: {device.name or '(unknown)'}")
                return device

        candidates = await BleakScanner.discover(timeout=self.scan_timeout)
        pybricks_hubs = []
        for candidate in candidates:
            metadata = getattr(candidate, "metadata", {}) or {}
            uuids = [str(u).lower() for u in metadata.get("uuids", [])]
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
        last_error = None
        for attempt in range(1, self.connect_attempts + 1):
            if attempt > 1:
                print(f"[BLE] reconnecting scan attempt {attempt}/{self.connect_attempts}")

            device = await self._find_device()
            if not device:
                last_error = RuntimeError(
                    f"Could not find '{self.hub_name}' and no Pybricks Hub found nearby."
                )
            else:
                try:
                    await self._do_connect(device)
                    return
                except Exception as exc:
                    last_error = exc
                    print(f"[BLE] connect attempt {attempt}/{self.connect_attempts} failed: {exc}")

            if attempt < self.connect_attempts:
                await asyncio.sleep(self.connect_retry_delay)

        raise RuntimeError(
            f"Could not connect to '{self.hub_name}'. Disconnect Pybricks Code/SPIKE app, "
            "power-cycle the Hub, and try again."
        ) from last_error

    async def _do_connect(self, device) -> None:
        self._loop = asyncio.get_running_loop()

        def handle_disconnect(_client):
            was_connecting = self._connecting
            self.connected = False
            self.ready.clear()
            print(f"\n[DISCONNECT] up={time.time() - self._connect_time:.1f}s last_hub_rx={time.time() - self.last_rx:.1f}s")
            if was_connecting:
                return
            if self.reconnect and not self._closing and not self._reconnecting and self._loop and self._loop.is_running():
                self._loop.call_soon(lambda: asyncio.ensure_future(self._reconnect_loop()))

        self.client = BleakClient(device, disconnected_callback=handle_disconnect, timeout=self.connect_timeout)
        self._connecting = True
        try:
            await self.client.connect()
            self._rx_text_buffer = ""
            self.ready.clear()
            self._program_running = None
            self._stdout_seen = False
            self._open_loop = False
            self._stale_warned = False
            self.connected = True
            self.recovery_generation += 1
            self._connect_time = time.time()
            self.last_rx = self._connect_time
            print(f"[BLE] connected to {device.name or '(unknown)'}")
            await self.client.start_notify(PYBRICKS_COMMAND_EVENT_CHAR_UUID, self._handle_rx)
            print("[NOTIFY] started.")
        except Exception:
            failed_client = self.client
            with contextlib.suppress(Exception):
                await failed_client.disconnect()
            self.client = None
            self.connected = False
            self.ready.clear()
            raise
        finally:
            self._connecting = False
        if self.auto_start:
            await self._start_user_program()

    async def _start_user_program(self) -> None:
        """Opt-in remote start.

        This sends only START. The previous STOP-then-START sequence is too
        aggressive for troubleshooting because it can stop a program that was
        already starting from the Hub button.
        """
        if not self.client or not self.connected:
            return
        try:
            self._last_start_attempt = time.time()
            self.ready.clear()
            self._stdout_seen = False
            self._open_loop = False
            await self.client.write_gatt_char(
                PYBRICKS_COMMAND_EVENT_CHAR_UUID,
                bytes([PYBRICKS_CMD_START_USER_PROGRAM]),
                response=True,
            )
            print("[START] sent remote START command to Hub.")
        except Exception as exc:
            print(f"[START] could not auto-start the saved program ({exc}). Press the Hub center button to start it manually.")

    async def _stop_user_program(self) -> None:
        """Remote-stop the saved Hub program without using Hub stdin."""
        if not self.client or not self.connected:
            return
        await self.client.write_gatt_char(
            PYBRICKS_COMMAND_EVENT_CHAR_UUID,
            bytes([PYBRICKS_CMD_STOP_USER_PROGRAM]),
            response=True,
        )
        print("[STOP] sent remote STOP command to Hub.")

    async def _prime_handshake(self) -> bool:
        """Bypass the ready gate and write one harmless stdin packet.

        After a BLE reconnect where the Hub program keeps RUNNING, the Hub does
        not re-emit startup rdy and never reads stdin, so the rdy handshake never
        re-bootstraps and send() blocks on ready.wait() forever. The Hub only
        acts on the 'M' opcode; 'S' over stdin is ignored (it is NOT treated as a
        STOP). But reading any stdin packet makes the Hub emit rdy, which
        re-bootstraps the handshake. This is backward compatible with Hub
        firmware that has no heartbeat rdy.
        """
        if not self.client or not self.connected:
            return False
        try:
            await self.client.write_gatt_char(
                PYBRICKS_COMMAND_EVENT_CHAR_UUID,
                b"\x06" + b"S\x00\x00\x00",
                response=True,
            )
            print("[PRIME] wrote priming stdin packet to re-bootstrap Hub rdy handshake.")
            return True
        except Exception as exc:
            print(f"[PRIME] priming stdin write failed: {exc}")
            return False

    async def _reconnect_loop(self) -> None:
        self._reconnecting = True
        attempt = 0
        try:
            while self.reconnect and not self._closing and not self.connected:
                attempt += 1
                print(f"[RECONNECT] attempt={attempt}")
                device = await self._find_device()
                if not device:
                    print("[RECONNECT] Hub not found. Retrying in 3s.")
                    await asyncio.sleep(3.0)
                    continue
                try:
                    await self._do_connect(device)
                    print("[RECONNECT] BLE reconnected. Waiting up to 2s for Hub rdy.")
                    await asyncio.wait_for(self.ready.wait(), timeout=2.0)
                    print("[READY] reconnect rdy received; Hub program resumed.")
                except asyncio.TimeoutError:
                    if self._program_running is False:
                        print("[WAIT] BLE reconnected, but Hub rdy is missing and program is STOPPED. Retrying remote START once.")
                        await self._start_user_program()
                    else:
                        print("[WAIT] BLE reconnected, Hub program RUNNING but no rdy. Priming stdin once to re-bootstrap.")
                        await self._prime_handshake()
                    try:
                        await asyncio.wait_for(self.ready.wait(), timeout=3.0)
                        print("[READY] reconnect rdy received after recovery retry.")
                    except asyncio.TimeoutError:
                        print("[RECONNECT] rdy still missing; disconnecting and retrying scan.")
                        with contextlib.suppress(Exception):
                            await self.client.disconnect()
                        self.connected = False
                        self.ready.clear()
                        await asyncio.sleep(2.0)
                except Exception as exc:
                    print(f"[RECONNECT] error: {exc}. Retrying in 3s.")
                    await asyncio.sleep(3.0)
        finally:
            self._reconnecting = False

    async def _wait_for_connected(self, timeout: float) -> bool:
        if self.connected and self.client:
            return True
        if not self.reconnect or self._closing:
            return False

        self._loop = asyncio.get_running_loop()
        if not self._reconnecting:
            self._loop.call_soon(lambda: asyncio.ensure_future(self._reconnect_loop()))

        deadline = self._loop.time() + timeout
        while self._loop.time() < deadline:
            if self.connected and self.client:
                return True
            await asyncio.sleep(0.1)
        return bool(self.connected and self.client)

    def _handle_rx(self, _, data: bytearray) -> None:
        if not data:
            return
        if self.debug_rx and self._rx_debug_count < 80:
            self._rx_debug_count += 1
            print(f"[RX] {bytes(data).hex()}")

        event = data[0]
        if event == self._EVENT_STATUS_REPORT:
            if len(data) >= 5:
                flags = int.from_bytes(bytes(data[1:5]), "little")
                running = bool(flags & self._STATUS_USER_PROGRAM_RUNNING)
                if running != self._program_running:
                    self._program_running = running
                    state = "RUNNING" if running else "STOPPED"
                    print(f"[STATUS] Hub user program: {state} (flags=0x{flags:08x})")
                if running:
                    self._running_event.set()
                else:
                    self._running_event.clear()
                    self.ready.clear()
                    self._stdout_seen = False
                    self._open_loop = False
            self.last_rx = time.time()
            return

        if event != self._EVENT_WRITE_STDOUT:
            return

        self.last_rx = time.time()
        self._stale_warned = False
        self._stdout_seen = True
        payload = bytes(data[1:])
        payload_lower = payload.lower()
        if b"rdy" in payload_lower:
            self.ready.set()
            idx = payload_lower.find(b"rdy")
            payload = payload[:idx] + payload[idx + 3 :]

        text = payload.decode("utf-8", errors="replace")
        if not text:
            return

        self._rx_text_buffer += text
        while "\n" in self._rx_text_buffer:
            line, self._rx_text_buffer = self._rx_text_buffer.split("\n", 1)
            line = line.strip()
            if line:
                print(f"[Hub] {line}")
                if self.line_handler is not None:
                    try:
                        self.line_handler(line)
                    except Exception as exc:
                        print(f"[Hub] line_handler error: {exc}")

    async def resume_if_stopped(self, timeout: float = 4.0) -> bool:
        if self._program_running is not False:
            return True
        if not self.auto_start or not self.restart_on_stop:
            return False

        now = time.time()
        wait_for_cooldown = self._start_cooldown - (now - self._last_start_attempt)
        if wait_for_cooldown > 0:
            await asyncio.sleep(wait_for_cooldown)

        print("[RECOVER] Hub user program is STOPPED; sending remote START.")
        await self._start_user_program()

        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
            print("[RECOVER] rdy received after restart.")
            self.recovery_generation += 1
            return True
        except asyncio.TimeoutError:
            print("[RECOVER] remote START sent, but no rdy arrived yet.")
            return False

    async def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Wait for the Hub program to send stdout rdy.

        The previous version returned failure after only one second once the
        Hub status became RUNNING. In practice the user may still be releasing
        CENTER at that point, and the Hub sends rdy only after that release.
        """
        loop = asyncio.get_running_loop()
        start = loop.time()
        deadline = start + timeout
        running_seen_at: Optional[float] = None

        if self.auto_start:
            print("[ACTION] Mac will remote-start the saved Hub program if it is STOPPED.")
            print("[ACTION] Keep Pybricks Code/SPIKE app disconnected while this script is running.")
        else:
            print("[ACTION] Start the saved Hub program with CENTER before running this script.")
            print("[ACTION] If the Hub stays STOPPED, power-cycle it and press CENTER first.")

        while loop.time() < deadline:
            if self.ready.is_set():
                print("[READY] rdy received.")
                return True

            if self._program_running:
                if running_seen_at is None:
                    running_seen_at = loop.time()
                if self.allow_open_loop and loop.time() - running_seen_at >= 1.0 and not self._stdout_seen:
                    self._open_loop = True
                    print("[READY] Hub status = RUNNING but no stdout rdy; proceeding in OPEN-LOOP mode.")
                    return True

                wait_for = min(1.0, max(0.0, deadline - loop.time()))
                try:
                    await asyncio.wait_for(self.ready.wait(), timeout=wait_for)
                    print("[READY] rdy received.")
                    return True
                except asyncio.TimeoutError:
                    now = time.time()
                    if now - self.last_wait_log > 3.0:
                        print("[WAIT] Hub status = RUNNING; waiting for stdout/rdy. Release CENTER if you are still pressing it.")
                        self.last_wait_log = now
                    continue

            await asyncio.sleep(0.2)

        if self._program_running:
            print("[WAIT] Hub status = RUNNING but stdout/rdy did not arrive before timeout.")
            print("[WAIT] Do not send stdin yet; power-cycle the Hub and retry.")
        else:
            print(
                "[WAIT] The Hub program did not start. Confirm Pybricks Code/SPIKE app is disconnected, "
                "power-cycle the Hub, and retry. Use --no-auto-start only for manual CENTER diagnostics."
            )
        return False

    async def send(self, command: str, timeout: float = 1.0, *, _primed: bool = False) -> bool:
        if not self.client or not self.connected:
            if not await self._wait_for_connected(timeout=max(2.0, timeout)):
                print(f"[BLE] not connected; skipped {command.strip()!r}")
                return False

        command_name = command.strip().upper()
        if self._program_running is False and command_name != "STOP":
            if not await self.resume_if_stopped(timeout=max(2.0, timeout)):
                print(f"[STATUS] Hub user program is STOPPED; skipped {command.strip()!r}")
                return False

        if not self._open_loop:
            try:
                await asyncio.wait_for(self.ready.wait(), timeout=timeout)
                self.ready.clear()
            except asyncio.TimeoutError:
                if self._program_running is False and command_name != "STOP":
                    if await self.resume_if_stopped(timeout=max(2.0, timeout)):
                        return await self.send(command, timeout=timeout)
                if (
                    not _primed
                    and self._program_running
                    and command_name != "STOP"
                ):
                    # RUNNING but rdy keeps timing out post-reconnect: the Hub
                    # never re-bootstrapped its rdy handshake. One-shot prime to
                    # make the Hub emit rdy, then retry exactly once instead of
                    # returning False indefinitely.
                    print("[PRIME] Hub RUNNING but rdy stalled; priming once to re-bootstrap handshake.")
                    if await self._prime_handshake():
                        try:
                            await asyncio.wait_for(self.ready.wait(), timeout=max(2.0, timeout))
                            self.recovery_generation += 1
                            print("[READY] rdy received after priming; handshake re-bootstrapped.")
                            return await self.send(command, timeout=timeout, _primed=True)
                        except asyncio.TimeoutError:
                            print("[PRIME] priming sent, but no rdy arrived yet.")
                            return False
                if self.allow_open_loop and self._program_running and not self._stdout_seen:
                    self._open_loop = True
                    print("[OPEN-LOOP] Hub program is RUNNING but no rdy is arriving; switching to open-loop sending.")
                else:
                    now = time.time()
                    if now - self.last_wait_log > 2.0:
                        print("[WAIT] Hub program is not sending rdy. Confirm the saved program is running and apps are disconnected.")
                        self.last_wait_log = now
                    return False

        try:
            packet = packet_for(command)
        except ValueError as exc:
            print(f"[SEND] invalid command: {exc}")
            return False

        if self.print_sends:
            print(f"[SEND] {command.strip()} -> {packet!r}")

        try:
            await asyncio.wait_for(
                self.client.write_gatt_char(
                    PYBRICKS_COMMAND_EVENT_CHAR_UUID,
                    b"\x06" + packet,
                    response=True,
                ),
                timeout=max(0.5, timeout),
            )
            self._ever_sent_stdin = True
            return True
        except asyncio.CancelledError:
            client_is_connected = bool(self.connected and self.client and getattr(self.client, "is_connected", False))
            if client_is_connected:
                raise
            print("[BLE] write cancelled after disconnect; reconnecting.")
            self.connected = False
            self.ready.clear()
            if self.reconnect and not self._closing and not self._reconnecting and self._loop and self._loop.is_running():
                self._loop.call_soon(lambda: asyncio.ensure_future(self._reconnect_loop()))
            return False
        except asyncio.TimeoutError:
            print(f"[BLE] write timed out after {timeout:.1f}s; reconnecting.")
            self.connected = False
            self.ready.clear()
            if self.reconnect and not self._closing and not self._reconnecting and self._loop and self._loop.is_running():
                self._loop.call_soon(lambda: asyncio.ensure_future(self._reconnect_loop()))
            return False
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

    async def close(self, *, send_stop: bool = False) -> None:
        """Disconnect BLE.

        STOP is opt-in. This avoids the failure path where a late rdy arrives
        after startup timed out and close() accidentally stops the Hub program.
        """
        self._closing = True
        if not self.client:
            return
        if send_stop and self.connected:
            with contextlib.suppress(Exception):
                await self._stop_user_program()
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
        return None

    async def close(self, *, send_stop: bool = False) -> None:
        return None
