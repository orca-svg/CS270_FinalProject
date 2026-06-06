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
import csv
import math
import re
import time
from pathlib import Path

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package. Install with: python -m pip install opencv-python numpy bleak") from exc

from fire_mode_control import describe_burst_decision, read_control_mode
from pybricks_ble import PybricksBleSender


PAN_MAX_DEG = 35
TILT_MIN_DEG = 0
TILT_MAX_DEG = 80

FLIGHT_TIME = 0.4
SMOOTHING = 0.3
ACCEL_SMOOTHING = 0.05
FIRE_PX = 20
FIRE_CONFIRM_FRAMES = 2
TARGET_LOST_REARM = 0.5
SEND_INTERVAL = 0.1
HOME_SEND_INTERVAL = 0.5
HOME_PAN_VAL = 0
HOME_TILT_VAL = -100
POST_RECOVERY_REPLAY_SECONDS = 1.5
MODE_READ_INTERVAL = 0.2

TRACKING = "TRACKING"
LOCKED = "LOCKED"
FIRED_FOR_TARGET = "FIRED_FOR_TARGET"
REARM_WAIT = "REARM_WAIT"


# Matches the Hub "SHOT f=<pan_angle> d=<tilt_angle>" report emitted at fire.
SHOT_RE = re.compile(r"SHOT\s+f=(-?\d+)\s+d=(-?\d+)")


def command_value(text: str) -> int:
    value = int(text)
    if value < -100 or value > 100:
        raise argparse.ArgumentTypeError("must be between -100 and 100")
    return value


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def nonnegative_float(text: str) -> float:
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return value


class FireDatasetLogger:
    """Join the Mac-side aim context with the Hub-reported D/F motor angles.

    The Mac calls ``mark_fire`` when it sends a fire command, stashing the
    current target/command context. When the Hub reports the actual pan(F) and
    tilt(D) motor angles via a "SHOT f=.. d=.." line, ``on_hub_line`` pairs them
    with the stashed context and appends one CSV row. The CSV is consumable by
    calibrate_angle_regression.py (it reads x,y,pan_angle,tilt_angle).
    """

    FIELDS = (
        "timestamp",
        "x",
        "y",
        "predict_x",
        "predict_y",
        "pan_val",
        "tilt_val",
        "pan_angle",
        "tilt_angle",
    )

    def __init__(self, path: Path) -> None:
        self.path = path
        self.pending: dict | None = None
        self.count = 0
        self._ensure_header()

    def _ensure_header(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(self.FIELDS)

    def mark_fire(self, context: dict) -> None:
        self.pending = context

    def on_hub_line(self, line: str) -> None:
        match = SHOT_RE.search(line)
        if not match or self.pending is None:
            return
        pan_angle = int(match.group(1))
        tilt_angle = int(match.group(2))
        ctx = self.pending
        self.pending = None
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(
                [
                    "{:.3f}".format(ctx["timestamp"]),
                    ctx["x"],
                    ctx["y"],
                    ctx["predict_x"],
                    ctx["predict_y"],
                    ctx["pan_val"],
                    ctx["tilt_val"],
                    pan_angle,
                    tilt_angle,
                ]
            )
        self.count += 1
        print(
            f"[DATASET] sample {self.count}: x={ctx['x']} y={ctx['y']} "
            f"pan_angle={pan_angle} tilt_angle={tilt_angle} -> {self.path.name}"
        )


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


def make_fire_context(
    timestamp: float,
    target_x: int,
    target_y: int,
    predict_x: int,
    predict_y: int,
    pan_val: int,
    tilt_val: int,
) -> dict:
    return {
        "timestamp": timestamp,
        "x": target_x,
        "y": target_y,
        "predict_x": predict_x,
        "predict_y": predict_y,
        "pan_val": pan_val,
        "tilt_val": tilt_val,
    }


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

    logger = None
    if not args.no_dataset:
        logger = FireDatasetLogger(Path(args.dataset))
        sender.line_handler = logger.on_hub_line
        print(f"[DATASET] logging fire samples to {logger.path}")

    cap = None
    try:
        await sender.connect()
        if not await sender.wait_until_ready(timeout=args.ready_timeout):
            raise SystemExit("Hub rdy not received. Check Hub power and saved Pybricks program.")

        cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            raise SystemExit(
                f"Could not open camera index {args.camera}. On macOS, allow camera access for "
                "the terminal app running this script in System Settings > Privacy & Security > Camera."
            )

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
        last_home_send_time = 0.0
        last_seen_recovery_generation = sender.recovery_generation
        replay_until = 0.0
        last_aim_command: str | None = None
        fire_state = TRACKING
        fire_confirm_count = 0
        target_lost_since: float | None = None
        fire_pending = False
        pending_fire_context: dict | None = None
        control_mode_path = Path(args.control_mode_file)
        current_fire_mode = args.default_fire_mode
        last_mode_read_time = 0.0
        last_burst_fire_time = 0.0
        last_burst_debug_time = 0.0
        last_burst_debug_reason = ""

        print("[RUN] Balloon interception started. Press q in the camera window to quit.")
        print(f"[MODE] default={current_fire_mode} control_file={control_mode_path}")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.flip(frame, 1)

            contours, _ = cv2.findContours(red_mask(frame), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            target_x = None
            target_y = None
            predict_x = None
            predict_y = None
            fire_trigger = 0
            pan_val = args.home_pan
            tilt_val = args.home_tilt

            if contours:
                contour = max(contours, key=cv2.contourArea)
                if cv2.contourArea(contour) > args.min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    target_x = x + w // 2
                    target_y = y + h // 2
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.circle(frame, (target_x, target_y), 5, (0, 255, 0), -1)

            current_time = time.time()
            if current_time - last_mode_read_time >= MODE_READ_INTERVAL:
                next_mode = read_control_mode(control_mode_path, current_fire_mode)
                if next_mode != current_fire_mode:
                    print(f"[MODE] {current_fire_mode} -> {next_mode}")
                    fire_confirm_count = 0
                    fire_pending = False
                    pending_fire_context = None
                    fire_state = TRACKING
                    current_fire_mode = next_mode
                last_mode_read_time = current_time
            dt = current_time - prev_time

            if target_x is not None and target_y is not None:
                if fire_state == REARM_WAIT:
                    fire_state = FIRED_FOR_TARGET
                target_lost_since = None

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
                last_aim_command = f"M,{pan_val},{tilt_val},0"

                in_fire_window = abs(predict_x - center_x) < args.fire_px and abs(predict_y - center_y) < args.fire_px
                burst_fire_px = args.burst_fire_px if args.burst_fire_px is not None else args.fire_px
                in_burst_fire_window = abs(predict_x - center_x) < burst_fire_px and abs(predict_y - center_y) < burst_fire_px
                if current_fire_mode == "safe":
                    fire_confirm_count = 0
                    fire_pending = False
                    pending_fire_context = None
                    fire_state = TRACKING
                    cv2.putText(frame, "SAFE: FIRE DISABLED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                elif current_fire_mode == "burst":
                    fire_confirm_count = 0
                    burst_decision = describe_burst_decision(
                        current_time=current_time,
                        last_burst_fire_time=last_burst_fire_time,
                        burst_interval=args.burst_interval,
                        in_fire_window=in_burst_fire_window,
                        no_fire=args.no_fire,
                        hub_program_running=getattr(sender, "_program_running", None),
                    )
                    if args.fire_debug and (
                        burst_decision["reason"] != last_burst_debug_reason
                        or current_time - last_burst_debug_time >= args.fire_debug_interval
                    ):
                        dx = predict_x - center_x
                        dy = predict_y - center_y
                        print(
                            "[FIRE-DEBUG] mode=burst "
                            f"reason={burst_decision['reason']} "
                            f"request={burst_decision['should_request_fire']} "
                            f"dx={dx} dy={dy} window={burst_fire_px} "
                            f"cooldown={burst_decision['cooldown_remaining']:.2f}s "
                            f"state={fire_state} no_fire={args.no_fire} "
                            f"hub_running={getattr(sender, '_program_running', None)}"
                        )
                        last_burst_debug_reason = burst_decision["reason"]
                        last_burst_debug_time = current_time
                    if in_burst_fire_window:
                        fire_state = LOCKED
                        if burst_decision["should_request_fire"]:
                            fire_pending = True
                            pending_fire_context = make_fire_context(
                                current_time,
                                target_x,
                                target_y,
                                predict_x,
                                predict_y,
                                pan_val,
                                tilt_val,
                            )
                            last_burst_fire_time = current_time
                            cv2.putText(frame, "BURST FIRE", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                        else:
                            cv2.putText(frame, "BURST LOCK", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 3)
                    else:
                        fire_state = TRACKING
                else:
                    if fire_state in (TRACKING, LOCKED):
                        if in_fire_window:
                            fire_confirm_count += 1
                            fire_state = LOCKED
                            if fire_confirm_count >= args.fire_confirm_frames:
                                if not args.no_fire:
                                    fire_pending = True
                                    pending_fire_context = make_fire_context(
                                        current_time,
                                        target_x,
                                        target_y,
                                        predict_x,
                                        predict_y,
                                        pan_val,
                                        tilt_val,
                                    )
                                    fire_state = FIRED_FOR_TARGET
                                cv2.putText(frame, "FIRE", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                        else:
                            fire_confirm_count = 0
                            fire_state = TRACKING
                    elif fire_state == FIRED_FOR_TARGET:
                        fire_confirm_count = 0
                        fire_trigger = 0
                        if in_fire_window:
                            cv2.putText(frame, "FIRED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

                    if in_fire_window and fire_state == LOCKED:
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
                fire_confirm_count = 0
                fire_pending = False
                pending_fire_context = None
                if fire_state == FIRED_FOR_TARGET:
                    fire_state = REARM_WAIT
                    target_lost_since = current_time
                elif fire_state == REARM_WAIT and target_lost_since is not None:
                    if current_time - target_lost_since >= args.target_lost_rearm:
                        fire_state = TRACKING
                        target_lost_since = None
                elif fire_state == LOCKED:
                    fire_state = TRACKING

            if target_x is None and current_fire_mode == "guard":
                pan_val = int(math.sin(current_time * args.guard_sweep_speed) * args.guard_sweep_pan)
                tilt_val = args.home_tilt
                cv2.putText(frame, "GUARD SWEEP", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

            prev_time = current_time

            if sender.recovery_generation != last_seen_recovery_generation:
                last_seen_recovery_generation = sender.recovery_generation
                replay_until = current_time + args.post_recovery_replay
                fire_pending = False
                pending_fire_context = None
                print("[RUN] BLE/Hub recovered; replaying latest aim command briefly.")

            cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (255, 255, 255), 2)
            cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (255, 255, 255), 2)
            cv2.putText(frame, f"MODE: {current_fire_mode.upper()}", (10, frame_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            if fire_pending or current_time - last_send_time >= args.send_interval:
                command_fire = 1 if fire_pending else fire_trigger
                command = f"M,{pan_val},{tilt_val},{command_fire}"
                if command_fire == 1 and getattr(sender, "_program_running", None) is False:
                    if args.fire_debug:
                        print("[FIRE-DEBUG] suppressing fire=1 because Hub user program is STOPPED")
                    command = f"M,{pan_val},{tilt_val},0"
                    command_fire = 0
                    fire_pending = False
                    pending_fire_context = None
                if current_time < replay_until and last_aim_command is not None:
                    command = last_aim_command
                    command_fire = 0
                if target_x is None and current_time - last_home_send_time < args.home_send_interval:
                    cv2.imshow("Balloon Intercept", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                    continue
                sent = await sender.send(command, timeout=args.send_timeout)
                if args.fire_debug and command_fire == 1:
                    print(f"[FIRE-DEBUG] fire_command_sent={sent} command={command}")
                last_send_time = current_time
                if target_x is None and sent:
                    last_home_send_time = current_time
                if command_fire == 1:
                    if sent and logger is not None and pending_fire_context is not None:
                        logger.mark_fire(pending_fire_context)
                    fire_pending = False
                    pending_fire_context = None

            cv2.imshow("Balloon Intercept", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        if getattr(sender, "connected", False):
            with contextlib.suppress(Exception):
                await sender.send(f"M,{args.home_pan},{args.home_tilt},0", timeout=0.5)
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        await sender.close(send_stop=not args.keep_hub_running)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-name", default="Team5")
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--connect-timeout", type=float, default=45.0)
    parser.add_argument("--connect-attempts", type=int, default=5)
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
    parser.add_argument("--fire-confirm-frames", type=positive_int, default=FIRE_CONFIRM_FRAMES)
    parser.add_argument("--target-lost-rearm", type=nonnegative_float, default=TARGET_LOST_REARM)
    parser.add_argument("--send-interval", type=float, default=SEND_INTERVAL)
    parser.add_argument("--home-send-interval", type=float, default=HOME_SEND_INTERVAL)
    parser.add_argument("--send-timeout", type=float, default=2.0)
    parser.add_argument("--post-recovery-replay", type=float, default=POST_RECOVERY_REPLAY_SECONDS)
    parser.add_argument("--control-mode-file", default=str(Path(__file__).with_name("control_mode.json")), help="JSON file written by voice recognition: {'mode':'single|burst|safe|guard'}.")
    parser.add_argument("--default-fire-mode", choices=["single", "burst", "safe", "guard"], default="single")
    parser.add_argument("--burst-interval", type=float, default=0.7, help="Seconds between repeated fire=1 requests in burst mode.")
    parser.add_argument("--burst-fire-px", type=int, default=None, help="Burst-mode lock window in pixels. Defaults to --fire-px; increase for diagnostics if burst never reaches lock.")
    parser.add_argument("--fire-debug", action="store_true", help="Print why fire=1 is or is not requested, especially in burst mode.")
    parser.add_argument("--fire-debug-interval", type=float, default=0.5, help="Minimum seconds between repeated fire-debug lines with the same reason.")
    parser.add_argument("--guard-sweep-pan", type=command_value, default=70, help="Maximum pan command used for guard-mode sweep, -100..100.")
    parser.add_argument("--guard-sweep-speed", type=float, default=1.2, help="Guard-mode sweep speed multiplier.")
    parser.add_argument("--no-fire", action="store_true", help="Track targets but never send fire=1; useful for D/F recovery tests.")
    parser.add_argument("--home-pan", type=command_value, default=HOME_PAN_VAL, help="Pan value sent when no target is visible, -100..100.")
    parser.add_argument("--home-tilt", type=command_value, default=HOME_TILT_VAL, help="Tilt value sent when no target is visible, -100..100.")
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).with_name("aim_dataset.csv")),
        help="CSV path for fire-time D/F motor angle samples (x,y,pan_angle,tilt_angle).",
    )
    parser.add_argument(
        "--no-dataset",
        action="store_true",
        help="Disable fire-time dataset logging.",
    )
    return parser


def main() -> None:
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(run_shooter(build_parser().parse_args()))


if __name__ == "__main__":
    main()
