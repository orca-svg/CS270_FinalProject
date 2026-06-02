#!/usr/bin/env python3
"""Manual BLE motor-path test for the Pybricks Hub 4-byte protocol.

Run this BEFORE camera control to isolate BLE/Hub/motor issues.

Usage:
    python bt_manual_motor_test.py --hub-name "Team5" --print-sends
"""
from __future__ import annotations

import argparse
import asyncio

from pybricks_ble import PybricksBleSender


COMMAND_DELAY = 0.45


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-name", default="Team5")
    parser.add_argument("--scan-timeout", type=float, default=15.0)
    parser.add_argument("--ready-timeout", type=float, default=20.0)
    parser.add_argument("--stale-timeout", type=float, default=2.0)
    parser.add_argument("--no-reconnect", action="store_true", help="Do not rescan after BLE disconnect.")
    parser.add_argument("--print-sends", action="store_true", help="Print every 4-byte packet sent to the Hub.")
    args = parser.parse_args()

    hub = PybricksBleSender(
        args.hub_name,
        args.scan_timeout,
        reconnect=not args.no_reconnect,
        stale_timeout=args.stale_timeout,
    )
    hub.print_sends = args.print_sends
    await hub.connect()

    try:
        ready = await hub.wait_until_ready(timeout=args.ready_timeout)
        if not ready:
            raise SystemExit("Hub rdy not received; start the saved Hub program and retry.")
        print("Starting 4-byte BLE motor test...")

        # Position-tracking test:
        #   pan/tilt errors drive target angle accumulation on the Hub.
        #   fire=1 latches one shot (Hub must be loaded to fire).
        commands = [
            "M,100,0,0",    # push pan target left
            "M,100,0,0",
            "M,100,0,0",
            "M,-100,0,0",   # push pan target right
            "M,-100,0,0",
            "M,-100,0,0",
            "M,0,0,0",      # return to roughly center
            "M,0,100,0",    # push tilt target down
            "M,0,100,0",
            "M,0,-100,0",   # push tilt target up
            "M,0,-100,0",
            "M,0,0,0",
            "M,0,0,1",      # fire 1 shot
            "M,0,0,0",
            "M,0,0,0",
            "M,0,0,0",
            "M,0,0,0",
            "STOP",
        ]
        for cmd in commands:
            await hub.send(cmd, timeout=10.0)
            hub.maybe_warn_stale(args.stale_timeout)
            await asyncio.sleep(COMMAND_DELAY)
        print("Manual motor test done.")
    finally:
        await hub.close()


if __name__ == "__main__":
    asyncio.run(main())
