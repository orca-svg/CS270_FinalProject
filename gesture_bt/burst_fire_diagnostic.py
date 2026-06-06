"""Direct burst-fire diagnostic for LEGO SPIKE Pybricks Hub.

This bypasses camera tracking and control_mode.json. It repeatedly sends
M,pan,tilt,1 so you can tell whether a burst failure is in the Hub/C motor path
or in the vision lock / mode-policy path.

Example:
    python burst_fire_diagnostic.py --hub-name Team5 --shots 5 --interval 1.0 --print-sends --debug-rx
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time

from pybricks_ble import PybricksBleSender


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-name", default="Team5")
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--connect-timeout", type=float, default=45.0)
    parser.add_argument("--connect-attempts", type=int, default=5)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--send-timeout", type=float, default=3.0)
    parser.add_argument("--shots", type=int, default=5, help="Number of fire=1 requests to send.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between fire=1 requests. Use >=1.0 first.")
    parser.add_argument("--pan", type=int, default=0, help="Pan command value, -100..100.")
    parser.add_argument("--tilt", type=int, default=0, help="Tilt command value, -100..100.")
    parser.add_argument("--settle", type=float, default=1.0, help="Aim-only settle time before first shot.")
    parser.add_argument("--keep-hub-running", action="store_true", help="Do not STOP the Hub program on exit.")
    parser.add_argument("--print-sends", action="store_true")
    parser.add_argument("--debug-rx", action="store_true")
    return parser


async def run(args: argparse.Namespace) -> None:
    sender = PybricksBleSender(
        args.hub_name,
        scan_timeout=args.scan_timeout,
        connect_timeout=args.connect_timeout,
        connect_attempts=args.connect_attempts,
        auto_start=True,
    )
    sender.print_sends = args.print_sends
    sender.debug_rx = args.debug_rx

    hub_counts = {"FIRE_REQ": 0, "FIRING": 0, "RETURNING": 0, "ARMED": 0, "FIRED": 0, "SHOT": 0}

    def handle_line(line: str) -> None:
        print(f"[Hub] {line}")
        for key in hub_counts:
            if line.startswith(key):
                hub_counts[key] += 1

    sender.line_handler = handle_line  # type: ignore[assignment]

    await sender.connect()
    await sender.wait_until_ready(timeout=args.ready_timeout)

    aim_command = f"M,{args.pan},{args.tilt},0"
    fire_command = f"M,{args.pan},{args.tilt},1"
    print(f"[DIAG] aim={aim_command} fire={fire_command} shots={args.shots} interval={args.interval:.2f}s")
    print("[DIAG] If [SEND] lines appear but Hub FIRE_REQ/SHOT do not, inspect Hub/C motor/armed state.")

    await sender.send(aim_command, timeout=args.send_timeout)
    await asyncio.sleep(args.settle)

    for shot_idx in range(1, args.shots + 1):
        print(f"[DIAG] request {shot_idx}/{args.shots}: {fire_command}")
        sent = await sender.send(fire_command, timeout=args.send_timeout)
        print(f"[DIAG] request {shot_idx} sent={sent}")
        await asyncio.sleep(args.interval)

    # Give Hub time to report final RETURNING/ARMED/FIRED lines.
    await asyncio.sleep(1.0)
    print("[DIAG] summary " + " ".join(f"{k}={v}" for k, v in hub_counts.items()))

    with contextlib.suppress(Exception):
        await sender.send(aim_command, timeout=0.5)
    await sender.close(send_stop=not args.keep_hub_running)


def main() -> None:
    asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    main()
