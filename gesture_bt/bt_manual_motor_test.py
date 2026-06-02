"""Manual BLE motor-path test for the Pybricks Hub 4-byte protocol.

Run this before camera control to isolate BLE/Hub/motor issues.

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
    parser.add_argument("--connect-timeout", type=float, default=45.0)
    parser.add_argument("--connect-attempts", type=int, default=3)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--stale-timeout", type=float, default=2.0)
    parser.add_argument("--no-reconnect", action="store_true", help="Do not rescan after BLE disconnect.")
    parser.add_argument("--print-sends", action="store_true", help="Print every 4-byte packet sent to the Hub.")
    parser.add_argument(
        "--auto-start",
        action="store_true",
        default=True,
        help=(
            "Send the BLE remote START command after connecting. Enabled by default because Team5 stays STOPPED otherwise."
        ),
    )
    parser.add_argument(
        "--no-auto-start",
        dest="auto_start",
        action="store_false",
        help="Disable remote START and require starting the Hub program with CENTER.",
    )
    parser.add_argument("--debug-rx", action="store_true", help="Print raw hex of BLE notifications and running-state.")
    parser.add_argument(
        "--allow-open-loop",
        action="store_true",
        help="Diagnostic only: send stdin packets when status is RUNNING but stdout/rdy is absent.",
    )
    args = parser.parse_args()

    hub = PybricksBleSender(
        args.hub_name,
        args.scan_timeout,
        connect_timeout=args.connect_timeout,
        connect_attempts=args.connect_attempts,
        reconnect=not args.no_reconnect,
        stale_timeout=args.stale_timeout,
        auto_start=args.auto_start,
        allow_open_loop=args.allow_open_loop,
    )
    hub.print_sends = args.print_sends
    hub.debug_rx = args.debug_rx

    try:
        await hub.connect()
        ready = await hub.wait_until_ready(timeout=args.ready_timeout)
        if not ready:
            raise SystemExit("Hub rdy not received; start the saved Hub program and retry.")

        print("Starting 4-byte BLE motor test...")
        commands = (
            "M,100,0,0",
            "M,100,0,0",
            "M,100,0,0",
            "M,-100,0,0",
            "M,-100,0,0",
            "M,-100,0,0",
            "M,0,0,0",
            "M,0,100,0",
            "M,0,100,0",
            "M,0,-100,0",
            "M,0,-100,0",
            "M,0,0,0",
            "M,0,0,1",
            "M,0,0,0",
            "M,0,0,0",
            "M,0,0,0",
            "M,0,0,0",
            "STOP",
        )
        for cmd in commands:
            await hub.send(cmd, timeout=10.0)
            hub.maybe_warn_stale()
            await asyncio.sleep(COMMAND_DELAY)

        print("Manual motor test done.")
    finally:
        await hub.close(send_stop=False)


if __name__ == "__main__":
    asyncio.run(main())
