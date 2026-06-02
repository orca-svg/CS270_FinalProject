"""Camera-based balloon interception controller for the Team5 Pybricks Hub.

This is the project runner, not a manual BLE test. It detects a red target,
predicts its future position, maps that point to pan/tilt command values, and
sends the 4-byte Pybricks protocol through the fixed BLE sender.

Run:
    python -u balloon_intercept.py --hub-name Team5
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package. Install with: python -m pip install opencv-python numpy bleak") from exc

from pybricks_ble import PybricksBleSender


PAN_MAX_DEG = 35
TILT_MIN_DEG = 0
TILT_MAX_DEG = 80

FLIGHT_TIME = 0.4
SMOOTHING = 0.3
ACCEL_SMOOTHING = 0.05
FIRE_PX = 20
SEND_INTERVAL = 0.1


def pixel_to_motor_vals(px: int, py: int, frame_w: int, frame_h: int) -> tuple[int, int]:
    pan_deg = (px - frame_w / 2) / (frame_w / 2) * PAN_MAX_DEG
    pan_deg = max(-PAN_MAX_DEG, min(PAN_MAX_DEG, pan_deg))
    pan_val = int(pan_deg / PAN_MAX_DEG * 100)

    tilt_frac = 1.0 - py / frame_h
    tilt_deg = TILT_MIN_DEG + tilt_frac * (TILT_MAX_DEG - TILT_MIN_DEG)
    tilt_deg = max(TILT_MIN_DEG, min(TILT_MAX_DEG, tilt_deg))
    tilt_val = int((tilt_deg - TILT_MIN_DEG) / (TILT_MAX_DEG - TILT_MIN_DEG) * 200 - 100)

    return pan_val, tilt_val


def red_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0, 120, 70]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([170, 120, 70]), np.array([180, 255, 255]))
    return mask1 + mask2


async def run_shooter(args: argparse.Namespace) -> None:
    sender = PybricksBleSender(
        args.hub_name,
        scan_timeout=args.scan_timeout,
        connect_timeout=args.connect_timeout,
        connect_attempts=args.connect_attempts,
        reconnect=not args.no_reconnect,
        stale_timeout=args.stale_timeout,
        auto_start=not args.no_auto_start,
        allow_open_loop=False,
    )
    sender.print_sends = args.print_sends
    sender.debug_rx = args.debug_rx

    cap = None
    try:
        await sender.connect()
        if not await sender.wait_until_ready(timeout=args.ready_timeout):
            raise SystemExit("Hub rdy not received. Check Hub power and saved Pybricks program.")

        cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            raise SystemExit(f"Could not open camera index {args.camera}.")

        frame_w = args.width
        frame_h = args.height
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_h)
        center_x = frame_w // 2
        center_y = frame_h // 2

        prev_x = None
        prev_y = None
        prev_time = time.time()
        vx_smooth = 0.0
        vy_smooth = 0.0
        prev_vy = 0.0
        ay_smooth = 0.0
        last_send_time = 0.0

        print("[RUN] Balloon interception started. Press q in the camera window to quit.")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.flip(frame, 1)

            contours, _ = cv2.findContours(red_mask(frame), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            target_x = None
            target_y = None
            fire_trigger = 0
            pan_val = 0
            tilt_val = 0

            if contours:
                contour = max(contours, key=cv2.contourArea)
                if cv2.contourArea(contour) > args.min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    target_x = x + w // 2
                    target_y = y + h // 2
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.circle(frame, (target_x, target_y), 5, (0, 255, 0), -1)

            current_time = time.time()
            dt = current_time - prev_time

            if target_x is not None and target_y is not None:
                if prev_x is not None and dt > 0:
                    vx_raw = (target_x - prev_x) / dt
                    vy_raw = (target_y - prev_y) / dt
                    vx_smooth = SMOOTHING * vx_raw + (1 - SMOOTHING) * vx_smooth
                    vy_smooth = SMOOTHING * vy_raw + (1 - SMOOTHING) * vy_smooth
                    ay_raw = (vy_smooth - prev_vy) / dt
                    ay_smooth = ACCEL_SMOOTHING * ay_raw + (1 - ACCEL_SMOOTHING) * ay_smooth

                predict_x = int(target_x + vx_smooth * args.flight_time)
                predict_y = int(target_y + vy_smooth * args.flight_time + 0.5 * ay_smooth * (args.flight_time**2))
                predict_x = max(0, min(frame_w, predict_x))
                predict_y = max(0, min(frame_h, predict_y))

                cv2.line(frame, (target_x, target_y), (predict_x, predict_y), (0, 255, 255), 2)
                cv2.circle(frame, (predict_x, predict_y), 10, (0, 0, 255), 2)
                cv2.putText(frame, f"VY:{int(vy_smooth)} AY:{int(ay_smooth)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                pan_val, tilt_val = pixel_to_motor_vals(predict_x, predict_y, frame_w, frame_h)
                if abs(predict_x - center_x) < args.fire_px and abs(predict_y - center_y) < args.fire_px:
                    fire_trigger = 1
                    cv2.putText(frame, "FIRE", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

                prev_x = target_x
                prev_y = target_y
                prev_vy = vy_smooth
            else:
                prev_x = None
                prev_y = None
                vx_smooth = 0.0
                vy_smooth = 0.0
                prev_vy = 0.0
                ay_smooth = 0.0

            prev_time = current_time

            cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (255, 255, 255), 2)
            cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (255, 255, 255), 2)

            if current_time - last_send_time >= args.send_interval:
                await sender.send(f"M,{pan_val},{tilt_val},{fire_trigger}", timeout=1.0)
                last_send_time = current_time

            cv2.imshow("Balloon Intercept", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        with contextlib.suppress(Exception):
            await sender.send("M,0,0,0", timeout=0.5)
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        await sender.close(send_stop=not args.keep_hub_running)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-name", default="Team5")
    parser.add_argument("--scan-timeout", type=float, default=15.0)
    parser.add_argument("--connect-timeout", type=float, default=45.0)
    parser.add_argument("--connect-attempts", type=int, default=3)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--stale-timeout", type=float, default=2.0)
    parser.add_argument("--no-reconnect", action="store_true")
    parser.add_argument("--no-auto-start", action="store_true", help="Disable remote START and require Hub CENTER start.")
    parser.add_argument("--keep-hub-running", action="store_true", help="Leave the Hub program running after the camera program exits.")
    parser.add_argument("--print-sends", action="store_true")
    parser.add_argument("--debug-rx", action="store_true")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--min-area", type=float, default=500.0)
    parser.add_argument("--flight-time", type=float, default=FLIGHT_TIME)
    parser.add_argument("--fire-px", type=int, default=FIRE_PX)
    parser.add_argument("--send-interval", type=float, default=SEND_INTERVAL)
    return parser


def main() -> None:
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(run_shooter(build_parser().parse_args()))


if __name__ == "__main__":
    main()
