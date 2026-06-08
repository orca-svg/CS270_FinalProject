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
import urllib.request
from pathlib import Path

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package. Install with: python -m pip install opencv-python numpy bleak") from exc

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks_python
    from mediapipe.tasks.python import vision as mp_vision
    HAS_MEDIAPIPE = True
except Exception:
    HAS_MEDIAPIPE = False

from fire_mode_control import describe_burst_decision, describe_visibility_fire_decision, read_control_mode
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


DEFAULT_DETECTOR_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/float16/1/efficientdet_lite0.task"
)
DEFAULT_DETECTOR_PATH = Path(__file__).resolve().parent / "models" / "efficientdet_lite0.task"


def ensure_detector_model(model_path: Path, model_url: str) -> Path:
    model_path = model_path.expanduser().resolve()
    if model_path.exists() and model_path.stat().st_size > 1000000:
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Object Detector model not found. Downloading to: {model_path}")
    try:
        import ssl
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(model_url, context=context) as response, open(model_path, 'wb') as out_file:
            out_file.write(response.read())
    except Exception as exc:
        if model_path.exists():
            try:
                model_path.unlink()
            except Exception:
                pass
        print("\n" + "="*80)
        print("❌ [오류] 모델 파일을 자동 다운로드하지 못했습니다 (네트워크/SSL 연결 문제).")
        print("아래 링크를 브라우저 주소창에 복사해서 모델 파일을 직접 다운로드해 주세요:")
        print(f"🔗 {model_url}")
        print(f"다운로드한 파일을 다음 위치에 저장해 주세요: {model_path}")
        print("="*80 + "\n")
        raise RuntimeError("Could not download the MediaPipe Object Detector model.") from exc
    return model_path


def create_object_detector(args: argparse.Namespace):
    if not HAS_MEDIAPIPE:
        raise SystemExit(
            "MediaPipe is not installed. Install with: python -m pip install mediapipe"
        )
    model_path = ensure_detector_model(Path(args.model_path), args.model_url)
    base_options = mp_tasks_python.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.ObjectDetectorOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.VIDEO,
        score_threshold=args.min_score,
        category_allowlist=args.allowed_categories,
        max_results=args.max_results,
    )
    return mp_vision.ObjectDetector.create_from_options(options)


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
        target_first_seen_time: float | None = None
        fire_pending = False
        pending_fire_context: dict | None = None
        control_mode_path = Path(args.control_mode_file)
        current_fire_mode = args.default_fire_mode
        last_mode_read_time = 0.0
        last_burst_fire_time = 0.0
        last_burst_debug_time = 0.0
        last_burst_debug_reason = ""

        detector = None
        last_timestamp_ms = 0
        if args.tracking_mode == "model":
            detector = create_object_detector(args)

        print("[RUN] Balloon interception started. Press q in the camera window to quit.")
        print(f"[MODE] tracking={args.tracking_mode} default={current_fire_mode} control_file={control_mode_path}")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.flip(frame, 1)

            target_x = None
            target_y = None
            predict_x = None
            predict_y = None
            fire_trigger = 0
            pan_val = args.home_pan
            tilt_val = args.home_tilt

            # 물리 거리 가시화를 위한 로컬 가중 상수
            OBJECT_SIZE_CM = 20.0
            FOCAL_LENGTH = 550.0

            if args.tracking_mode == "model":
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb = np.ascontiguousarray(rgb)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                timestamp_ms = int(time.monotonic() * 1000)
                if timestamp_ms <= last_timestamp_ms:
                    timestamp_ms = last_timestamp_ms + 1
                last_timestamp_ms = timestamp_ms

                detection_result = detector.detect_for_video(mp_image, timestamp_ms)

                if detection_result.detections:
                    best_detection = None
                    best_area = 0
                    for detection in detection_result.detections:
                        bbox = detection.bounding_box
                        area = bbox.width * bbox.height
                        if area > best_area:
                            best_area = area
                            best_detection = detection

                    for detection in detection_result.detections:
                        bbox = detection.bounding_box
                        cx = bbox.origin_x + bbox.width // 2
                        cy = bbox.origin_y + bbox.height // 2

                        pixel_size_item = max(bbox.width, bbox.height)
                        Z_cm_item = (OBJECT_SIZE_CM * FOCAL_LENGTH) / pixel_size_item if pixel_size_item > 0 else 300.0

                        category = detection.categories[0]

                        if detection is best_detection:
                            target_x = cx
                            target_y = cy

                            cv2.rectangle(frame, (bbox.origin_x, bbox.origin_y), 
                                          (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height), (0, 0, 255), 3)
                            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)
                            label = f"[TARGET] {category.category_name} ({int(category.score * 100)}%) - {int(Z_cm_item)}cm"
                            cv2.putText(frame, label, (bbox.origin_x, bbox.origin_y - 5), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                        else:
                            cv2.rectangle(frame, (bbox.origin_x, bbox.origin_y), 
                                          (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height), (0, 255, 0), 2)
                            cv2.circle(frame, (cx, cy), 4, (0, 255, 0), -1)
                            label = f"{category.category_name} ({int(category.score * 100)}%) - {int(Z_cm_item)}cm"
                            cv2.putText(frame, label, (bbox.origin_x, bbox.origin_y - 5), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            else:
                contours, _ = cv2.findContours(red_mask(frame), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                valid_contours = []
                for contour in contours:
                    if cv2.contourArea(contour) > args.min_area:
                        valid_contours.append(contour)

                if valid_contours:
                    target_contour = max(valid_contours, key=cv2.contourArea)

                    for contour in valid_contours:
                        x, y, w, h = cv2.boundingRect(contour)
                        cx = x + w // 2
                        cy = y + h // 2

                        pixel_size_item = max(w, h)
                        Z_cm_item = (OBJECT_SIZE_CM * FOCAL_LENGTH) / pixel_size_item if pixel_size_item > 0 else 300.0

                        if contour is target_contour:
                            target_x = cx
                            target_y = cy

                            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 3)
                            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)
                            label = f"[TARGET] balloon - {int(Z_cm_item)}cm"
                            cv2.putText(frame, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                        else:
                            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                            cv2.circle(frame, (cx, cy), 4, (0, 255, 0), -1)
                            label = f"balloon - {int(Z_cm_item)}cm"
                            cv2.putText(frame, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

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
                if target_first_seen_time is None:
                    target_first_seen_time = current_time
                if fire_state == REARM_WAIT:
                    fire_state = TRACKING
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

                visibility_decision = describe_visibility_fire_decision(
                    current_time=current_time,
                    target_first_seen_time=target_first_seen_time,
                    required_visible_seconds=args.target_visible_seconds,
                    target_visible=True,
                    no_fire=args.no_fire,
                    hub_program_running=getattr(sender, "_program_running", None),
                )
                if current_fire_mode == "safe":
                    fire_confirm_count = 0
                    fire_pending = False
                    pending_fire_context = None
                    fire_state = TRACKING
                    cv2.putText(frame, "SAFE: FIRE DISABLED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                elif current_fire_mode == "burst":
                    fire_confirm_count = 0
                    if not visibility_decision["should_request_fire"]:
                        if args.fire_debug and (
                            visibility_decision["reason"] != last_burst_debug_reason
                            or current_time - last_burst_debug_time >= args.fire_debug_interval
                        ):
                            print(
                                "[FIRE-DEBUG] mode=burst "
                                f"reason={visibility_decision['reason']} "
                                f"visible_elapsed={visibility_decision['visible_elapsed']:.2f}s "
                                f"remaining={visibility_decision['remaining_visible_seconds']:.2f}s "
                                f"state={fire_state} no_fire={args.no_fire} "
                                f"hub_running={getattr(sender, '_program_running', None)}"
                            )
                            last_burst_debug_reason = visibility_decision["reason"]
                            last_burst_debug_time = current_time
                        fire_state = TRACKING
                        cv2.putText(
                            frame,
                            f"BURST LOCKING: {visibility_decision['remaining_visible_seconds']:.2f}s",
                            (20, 80),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.8,
                            (0, 255, 255),
                            2,
                        )
                    else:
                        burst_decision = describe_burst_decision(
                            current_time=current_time,
                            last_burst_fire_time=last_burst_fire_time,
                            burst_interval=args.burst_interval,
                            target_visible=True,
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
                                f"dx={dx} dy={dy} "
                                f"visible_elapsed={visibility_decision['visible_elapsed']:.2f}s "
                                f"cooldown={burst_decision['cooldown_remaining']:.2f}s "
                                f"state={fire_state} no_fire={args.no_fire} "
                                f"hub_running={getattr(sender, '_program_running', None)}"
                            )
                            last_burst_debug_reason = burst_decision["reason"]
                            last_burst_debug_time = current_time
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
                    if fire_state in (TRACKING, LOCKED):
                        if visibility_decision["should_request_fire"]:
                            fire_state = LOCKED
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
                            cv2.putText(
                                frame,
                                f"LOCKING: {visibility_decision['remaining_visible_seconds']:.2f}s",
                                (20, 80),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                1,
                                (0, 255, 255),
                                2,
                            )
                    elif fire_state == FIRED_FOR_TARGET:
                        fire_confirm_count = 0
                        fire_trigger = 0
                        cv2.putText(frame, "FIRED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

                prev_x = target_x
                prev_y = target_y
                prev_vy = vy_smooth
            else:
                target_first_seen_time = None
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
    parser.add_argument("--target-visible-seconds", type=nonnegative_float, default=0.4, help="Seconds a target must stay visible before single/burst can request fire=1.")
    parser.add_argument("--burst-fire-px", type=int, default=None, help="Deprecated diagnostic option; burst now fires after --target-visible-seconds while target remains visible.")
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
    
    # Tracking Mode & MediaPipe config
    parser.add_argument(
        "--tracking-mode",
        choices=["color", "model"],
        default="color",
        help="Select tracking method: 'color' (HSV contour) or 'model' (MediaPipe Object Detector)."
    )
    parser.add_argument(
        "--model-path",
        default=str(DEFAULT_DETECTOR_PATH),
        help="Path to EfficientDet-Lite0 model file (used in model tracking mode)."
    )
    parser.add_argument(
        "--model-url",
        default=DEFAULT_DETECTOR_URL,
        help="URL to download EfficientDet-Lite0 model if missing."
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.45,
        help="Minimum confidence threshold for classification."
    )
    parser.add_argument(
        "--allowed-categories",
        nargs="+",
        default=["sports ball"],
        help="List of COCO categories allowed to be tracked and intercepted."
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of objects to detect simultaneously in model tracking mode."
    )
    return parser


def main() -> None:
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(run_shooter(build_parser().parse_args()))


if __name__ == "__main__":
    main()
