"""Verify Team5 BLE restart recovery and Hub SHOT angle output.

Before running this, upload hub_pybricks_gesture_server.py to the Hub.
The script checks:
1. BLE connect + remote START + rdy.
2. HOME command reaches the Hub.
3. A forced STOPPED state is recovered by the next command.
4. A fire command produces a Hub stdout line like "SHOT f=... d=...".
"""

from __future__ import annotations

import argparse
import asyncio
import re

from pybricks_ble import (
    PYBRICKS_COMMAND_EVENT_CHAR_UUID,
    PYBRICKS_CMD_STOP_USER_PROGRAM,
    PybricksBleSender,
)


SHOT_RE = re.compile(r"SHOT\s+f=(-?\d+)\s+d=(-?\d+)")
HOME_COMMAND = "M,0,-100,0"
FIRE_COMMAND = "M,0,-100,1"


async def wait_for_shot(lines: list[str], timeout: float) -> tuple[int, int] | None:
    deadline = asyncio.get_running_loop().time() + timeout
    checked = 0
    while asyncio.get_running_loop().time() < deadline:
        for line in lines[checked:]:
            match = SHOT_RE.search(line)
            if match:
                return int(match.group(1)), int(match.group(2))
        checked = len(lines)
        await asyncio.sleep(0.1)
    return None


async def wait_for_line(lines: list[str], text: str, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    checked = 0
    while asyncio.get_running_loop().time() < deadline:
        for line in lines[checked:]:
            if text in line:
                return True
        checked = len(lines)
        await asyncio.sleep(0.1)
    return False


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-name", default="Team5")
    parser.add_argument("--scan-timeout", type=float, default=15.0)
    parser.add_argument("--connect-timeout", type=float, default=60.0)
    parser.add_argument("--connect-attempts", type=int, default=5)
    parser.add_argument("--ready-timeout", type=float, default=25.0)
    parser.add_argument("--shot-timeout", type=float, default=8.0)
    parser.add_argument(
        "--skip-forced-stop",
        action="store_true",
        help="Skip the forced STOP/recovery section and test a clean single fire only.",
    )
    parser.add_argument("--keep-hub-running", action="store_true")
    parser.add_argument("--print-sends", action="store_true")
    parser.add_argument("--debug-rx", action="store_true")
    args = parser.parse_args()

    lines: list[str] = []

    def on_line(line: str) -> None:
        lines.append(line)

    hub = PybricksBleSender(
        args.hub_name,
        scan_timeout=args.scan_timeout,
        connect_timeout=args.connect_timeout,
        connect_attempts=args.connect_attempts,
        reconnect=False,
        auto_start=True,
        restart_on_stop=True,
    )
    hub.print_sends = args.print_sends
    hub.debug_rx = args.debug_rx
    hub.line_handler = on_line

    try:
        print("[VERIFY] connect + remote START")
        await hub.connect()
        if not await hub.wait_until_ready(timeout=args.ready_timeout):
            raise SystemExit("[VERIFY] FAIL: initial rdy not received")

        print("[VERIFY] send HOME")
        if not await hub.send(HOME_COMMAND, timeout=8.0):
            raise SystemExit("[VERIFY] FAIL: HOME send failed")

        if not args.skip_forced_stop:
            print("[VERIFY] force Hub user program STOPPED")
            await hub.client.write_gatt_char(
                PYBRICKS_COMMAND_EVENT_CHAR_UUID,
                bytes([PYBRICKS_CMD_STOP_USER_PROGRAM]),
                response=True,
            )
            for _ in range(30):
                if hub._program_running is False:
                    break
                await asyncio.sleep(0.2)
            if hub._program_running is not False:
                raise SystemExit("[VERIFY] FAIL: STOPPED status was not observed")

            print("[VERIFY] send HOME again; this should trigger auto recovery")
            if not await hub.send(HOME_COMMAND, timeout=8.0):
                raise SystemExit("[VERIFY] FAIL: recovery send failed")

        print("[VERIFY] fire once and wait for SHOT f=... d=...")
        lines.clear()
        if not await hub.send(FIRE_COMMAND, timeout=8.0):
            raise SystemExit("[VERIFY] FAIL: fire send failed")
        shot = await wait_for_shot(lines, timeout=args.shot_timeout)
        if shot is None:
            print(f"[VERIFY] captured Hub lines after fire: {lines!r}")
            raise SystemExit("[VERIFY] FAIL: SHOT line was not received from Hub stdout")

        pan_angle, tilt_angle = shot
        if not await wait_for_line(lines, "ARMED", timeout=args.shot_timeout):
            print(f"[VERIFY] captured Hub lines after SHOT: {lines!r}")
            raise SystemExit("[VERIFY] FAIL: ARMED line was not received after fire")

        print(f"[VERIFY] PASS: received SHOT f={pan_angle} d={tilt_angle} and ARMED")

        await asyncio.sleep(1.0)
        await hub.send(HOME_COMMAND, timeout=8.0)
    finally:
        await hub.close(send_stop=not args.keep_hub_running)
        print("[VERIFY] closed")


if __name__ == "__main__":
    asyncio.run(main())
