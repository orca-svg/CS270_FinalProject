#!/usr/bin/env python3
"""Camera-based generic object interception controller for LEGO SPIKE Prime (Windows Threaded Model detection).

This script uses MediaPipe's Object Detector task API to classify and track generic objects (like sports balls, bottles, cups)
rather than relying on HSV color-masking. It runs the MediaPipe detector and BLE client in background threads to avoid UI freezes.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import re
import time
import urllib.request
import threading
import queue
from pathlib import Path
from typing import Optional, Tuple

try:
    import cv2
    import numpy as np
    import mediapipe as mp
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package. Install with: python -m pip install opencv-python numpy mediapipe bleak") from exc

try:
    from mediapipe.tasks import python as mp_tasks_python
    from mediapipe.tasks.python import vision as mp_vision
except Exception as exc:
    raise SystemExit(
        "This controller requires the MediaPipe Tasks API. "
        "Install a recent MediaPipe version with: python -m pip install -U mediapipe"
    ) from exc

from pybricks_ble import DEFAULT_HUB_NAME, DryRunSender, PybricksBleSender, clamp


PAN_MAX_DEG = 35
TILT_MIN_DEG = 10
TILT_MAX_DEG = 120.0

SMOOTHING = 0.6
ACCEL_SMOOTHING = 0.3
TARGET_LOST_REARM = 0.5
SEND_INTERVAL = 0.1
HOME_SEND_INTERVAL = 0.5
HOME_PAN_VAL = 0
HOME_TILT_VAL = -100

TRACKING = "TRACKING"
LOCKED = "LOCKED"
FIRED_FOR_TARGET = "FIRED_FOR_TARGET"
REARM_WAIT = "REARM_WAIT"

SHOT_RE = re.compile(r"SHOT\s+f=(-?\d+)\s+d=(-?\d+)")

# Default EfficientDet-Lite0 model (coco classes: sports ball, bottle, cup, etc.)
DEFAULT_DETECTOR_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/float16/1/efficientdet_lite0.task"
)
DEFAULT_DETECTOR_PATH = Path(__file__).resolve().parent / "models" / "efficientdet_lite0.task"


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


def ensure_detector_model(model_path: Path, model_url: str) -> Path:
    model_path = model_path.expanduser().resolve()
    if model_path.exists() and model_path.stat().st_size > 0:
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Object Detector model not found. Downloading to: {model_path}")
    try:
        urllib.request.urlretrieve(model_url, model_path)
    except Exception as exc:
        raise RuntimeError("Could not download the MediaPipe Object Detector model.") from exc
    return model_path


def create_object_detector(args: argparse.Namespace):
    model_path = ensure_detector_model(Path(args.model_path), args.model_url)
    base_options = mp_tasks_python.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.ObjectDetectorOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.VIDEO,
        score_threshold=args.min_score,
        category_allowlist=args.allowed_categories,
    )
    return mp_vision.ObjectDetector.create_from_options(options)


def pixel_to_motor_vals(px: int, py: int, frame_w: int, frame_h: int) -> tuple[int, int]:
    # 1.1x scaling added to Pan as requested previously
    pan_deg = (px - frame_w / 2) / (frame_w / 2) * PAN_MAX_DEG * 1.1
    pan_deg = max(-PAN_MAX_DEG, min(PAN_MAX_DEG, pan_deg))
    pan_val = int(pan_deg / PAN_MAX_DEG * 100)

    tilt_frac = 1.0 - py / frame_h
    # Non-linear 1.25x scaling for Tilt as requested previously
    tilt_frac_warped = tilt_frac ** 1.25
    tilt_deg = TILT_MIN_DEG + tilt_frac_warped * (TILT_MAX_DEG - TILT_MIN_DEG)
    tilt_deg = max(TILT_MIN_DEG, min(TILT_MAX_DEG, tilt_deg))
    tilt_val = int((tilt_deg - TILT_MIN_DEG) / (TILT_MAX_DEG - TILT_MIN_DEG) * 200 - 100)

    return pan_val, tilt_val


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


# =====================================================================
# BACKGROUND BLE THREAD (Consumer)
# =====================================================================
def ble_worker(args: argparse.Namespace, cmd_queue: queue.Queue, stop_event: threading.Event, logger: FireDatasetLogger | None, ready_event: threading.Event):
    """Background thread that runs the asyncio loop for Bluetooth communication."""
    async def _ble_loop():
        sender = DryRunSender() if args.dry_run else PybricksBleSender(
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
        
        if logger is not None:
            sender.line_handler = logger.on_hub_line
            
        try:
            print("[BLE Thread] Connecting to Hub...")
            await sender.connect()
            if not await sender.wait_until_ready(timeout=args.ready_timeout):
                print("[BLE Thread] Hub rdy not received.")
                stop_event.set()
                return
            ready_event.set()
        except Exception as exc:
            print(f"[BLE Thread] Connection failed: {exc}")
            stop_event.set()
            return

        while not stop_event.is_set():
            try:
                cmd = cmd_queue.get(timeout=0.05)
                while not cmd_queue.empty():
                    next_cmd = cmd_queue.get_nowait()
                    if next_cmd == "STOP" or cmd == "STOP":
                        cmd = "STOP"
                    else:
                        if "M," in cmd and "M," in next_cmd:
                            parts_cmd = cmd.split(",")
                            parts_next = next_cmd.split(",")
                            fire_status = "1" if (parts_cmd[3] == "1" or parts_next[3] == "1") else "0"
                            cmd = f"M,{parts_next[1]},{parts_next[2]},{fire_status}"
                        else:
                            cmd = next_cmd
                
                if cmd == "STOP":
                    await sender.send(f"M,{args.home_pan},{args.home_tilt},0", timeout=0.5)
                    break
                
                if ",1" in cmd and getattr(sender, "_program_running", None) is False:
                    parts = cmd.split(",")
                    cmd = f"M,{parts[1]},{parts[2]},0"

                await sender.send(cmd, timeout=args.send_timeout)
                    
            except queue.Empty:
                pass
            
            if hasattr(sender, "maybe_warn_stale"):
                sender.maybe_warn_stale()
                
            await asyncio.sleep(0.01)

        print("[BLE Thread] Cleaning up...")
        if getattr(sender, "connected", False):
            with contextlib.suppress(Exception):
                await sender.send(f"M,{args.home_pan},{args.home_tilt},0", timeout=0.5)
        await sender.close(send_stop=not args.keep_hub_running)
        print("[BLE Thread] Exited.")

    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(_ble_loop())


# =====================================================================
# MAIN CAMERA THREAD (Producer)
# =====================================================================
def run_camera(args: argparse.Namespace) -> None:
    logger = None
    if not args.no_dataset:
        logger = FireDatasetLogger(Path(args.dataset))
        print(f"[DATASET] Logging fire samples to {logger.path}")

    cmd_queue = queue.Queue()
    stop_event = threading.Event()
    ready_event = threading.Event()
    
    ble_thread = threading.Thread(
        target=ble_worker, 
        args=(args, cmd_queue, stop_event, logger, ready_event), 
        daemon=True
    )
    ble_thread.start()

    print("[Main] Waiting for BLE Thread to connect and ready...")
    while not ready_event.is_set() and not stop_event.is_set():
        time.sleep(0.1)
        
    if stop_event.is_set():
        print("[Main] BLE Thread failed to initialize. Exiting.")
        return

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        stop_event.set()
        raise SystemExit(f"Could not open camera index {args.camera}.")

    frame_w = args.width
    frame_h = args.height
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_h)
    center_x = frame_w // 2
    center_y = frame_h // 2

    detector = create_object_detector(args)
    cv2.namedWindow("Object Intercept (Win)", cv2.WINDOW_NORMAL)

    prev_X, prev_Y, prev_Z = None, None, None
    prev_time = time.time()
    vx_smooth = 0.0
    vy_smooth = 0.0
    vz_smooth = 0.0
    prev_vy = 0.0
    last_send_time = 0.0
    last_home_send_time = 0.0
    last_aim_command: str | None = None
    fire_state = TRACKING
    target_lost_since: float | None = None
    fire_pending = False
    pending_fire_context: dict | None = None
    target_first_seen_time: float | None = None
    last_timestamp_ms = 0

    OBJECT_SIZE_CM = args.object_size_cm
    FOCAL_LENGTH = args.focal_length
    DRAG_K = 1.5
    GRAVITY_CM_S2 = 250.0

    print("=====================================================")
    print(" 🚀 Windows Multi-Thread AI Object Interceptor Started")
    print(f" 🎯 Targeting Category Allowlist: {args.allowed_categories}")
    print("=====================================================")

    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                print("Camera frame read failed.")
                break
            if args.mirror:
                frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            timestamp_ms = int(time.monotonic() * 1000)
            if timestamp_ms <= last_timestamp_ms:
                timestamp_ms = last_timestamp_ms + 1
            last_timestamp_ms = timestamp_ms

            detection_result = detector.detect_for_video(mp_image, timestamp_ms)

            target_x = None
            target_y = None
            X_cm, Y_cm, Z_cm = None, None, None
            predict_x = None
            predict_y = None
            fire_trigger = 0
            pan_val = args.home_pan
            tilt_val = args.home_tilt

            best_detection = None
            best_area = 0

            # Find the largest detection matching our target criteria
            if detection_result.detections:
                for detection in detection_result.detections:
                    bbox = detection.bounding_box
                    area = bbox.width * bbox.height
                    if area > best_area:
                        best_area = area
                        best_detection = detection

            if best_detection is not None:
                bbox = best_detection.bounding_box
                target_x = bbox.origin_x + bbox.width // 2
                target_y = bbox.origin_y + bbox.height // 2

                # Draw bounding box and label
                category = best_detection.categories[0]
                label = f"{category.category_name} ({int(category.score * 100)}%)"
                cv2.rectangle(frame, (bbox.origin_x, bbox.origin_y), 
                              (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height), (0, 255, 0), 2)
                cv2.putText(frame, label, (bbox.origin_x, bbox.origin_y - 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                pixel_size = max(bbox.width, bbox.height)
                Z_cm = (OBJECT_SIZE_CM * FOCAL_LENGTH) / pixel_size if pixel_size > 0 else 300.0
                X_cm = ((target_x - center_x) * Z_cm) / FOCAL_LENGTH
                Y_cm = -((target_y - center_y) * Z_cm) / FOCAL_LENGTH

            current_time = time.time()
            dt = current_time - prev_time

            if target_x is not None and target_y is not None:
                if fire_state == REARM_WAIT:
                    fire_state = FIRED_FOR_TARGET
                target_lost_since = None

                if target_first_seen_time is None:
                    target_first_seen_time = current_time

                if prev_X is not None and dt > 0:
                    vx_raw = (X_cm - prev_X) / dt
                    vy_raw = (Y_cm - prev_Y) / dt
                    vz_raw = (Z_cm - prev_Z) / dt
                    vx_smooth = SMOOTHING * vx_raw + (1 - SMOOTHING) * vx_smooth
                    vy_smooth = SMOOTHING * vy_raw + (1 - SMOOTHING) * vy_smooth
                    vz_smooth = SMOOTHING * vz_raw + (1 - SMOOTHING) * vz_smooth

                # Predict 3D Trajectory using Drag & Gravity simulation
                sim_X, sim_Y, sim_Z = X_cm, Y_cm, Z_cm
                sim_vx, sim_vy, sim_vz = vx_smooth, vy_smooth, vz_smooth

                # Distance-based flight time calculation
                current_flight_time = (Z_cm / 600.0) + 0.1
                current_flight_time = max(0.15, min(0.8, current_flight_time))

                sim_steps = 10
                sim_dt = current_flight_time / sim_steps

                for _ in range(sim_steps):
                    ax = -DRAG_K * sim_vx
                    ay = -DRAG_K * sim_vy - GRAVITY_CM_S2
                    az = -DRAG_K * sim_vz
                    
                    sim_X += sim_vx * sim_dt
                    sim_Y += sim_vy * sim_dt
                    sim_Z += sim_vz * sim_dt
                    sim_vx += ax * sim_dt
                    sim_vy += ay * sim_dt
                    sim_vz += az * sim_dt

                if sim_Z > 0:
                    predict_x = int((sim_X * FOCAL_LENGTH) / sim_Z + center_x)
                    predict_y = int((-sim_Y * FOCAL_LENGTH) / sim_Z + center_y)
                else:
                    predict_x, predict_y = target_x, target_y

                predict_x = max(0, min(frame_w, predict_x))
                predict_y = max(0, min(frame_h, predict_y))

                cv2.line(frame, (target_x, target_y), (predict_x, predict_y), (0, 255, 255), 2)
                cv2.circle(frame, (predict_x, predict_y), 10, (0, 0, 255), 2)
                cv2.putText(frame, f"Depth: {int(Z_cm)}cm  EstT: {current_flight_time:.2f}s", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                pan_val, tilt_val = pixel_to_motor_vals(predict_x, predict_y, frame_w, frame_h)
                last_aim_command = f"M,{pan_val},{tilt_val},0"

                # 0.4s Fire Latch delay
                detected_duration = current_time - target_first_seen_time
                if fire_state in (TRACKING, LOCKED):
                    if detected_duration >= 0.4:
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
                            if logger is not None:
                                logger.mark_fire(pending_fire_context)
                            fire_state = FIRED_FOR_TARGET
                        cv2.putText(frame, "FIRE", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                    else:
                        fire_state = TRACKING
                        cv2.putText(frame, f"LOCKING: {0.4 - detected_duration:.2f}s", (20, 80), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                elif fire_state == FIRED_FOR_TARGET or fire_state == REARM_WAIT:
                    cv2.putText(frame, "FIRED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)

                prev_x = target_x
                prev_y = target_y
                prev_vy = vy_smooth
                prev_X, prev_Y, prev_Z = X_cm, Y_cm, Z_cm
            else:
                target_first_seen_time = None
                prev_x = None
                prev_y = None
                prev_X, prev_Y, prev_Z = None, None, None
                vx_smooth, vy_smooth, vz_smooth = 0.0, 0.0, 0.0
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

            prev_time = current_time

            cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (255, 255, 255), 2)
            cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (255, 255, 255), 2)

            if fire_pending or current_time - last_send_time >= args.send_interval:
                command_fire = 1 if fire_pending else fire_trigger
                command = f"M,{pan_val},{tilt_val},{command_fire}"
                
                if target_x is None and current_time - last_home_send_time < args.home_send_interval:
                    cv2.imshow("Object Intercept (Win)", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        cmd_queue.put("STOP")
                        stop_event.set()
                        break
                    continue

                cmd_queue.put(command)
                last_send_time = current_time
                if target_x is None:
                    last_home_send_time = current_time
                if command_fire == 1:
                    fire_pending = False

            cv2.imshow("Object Intercept (Win)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                cmd_queue.put("STOP")
                stop_event.set()
                break

    finally:
        stop_event.set()
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        print("[Main] Waiting for BLE thread to finish...")
        ble_thread.join(timeout=1.5)
        print("[Main] Exited cleanly.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Do not connect to BLE; print commands only.")
    parser.add_argument("--hub-name", default="Team5")
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--connect-timeout", type=float, default=45.0)
    parser.add_argument("--connect-attempts", type=int, default=5)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--stale-timeout", type=float, default=2.0)
    parser.add_argument("--no-reconnect", action="store_true")
    parser.add_argument("--no-auto-start", action="store_true")
    parser.add_argument("--keep-hub-running", action="store_true")
    parser.add_argument("--mirror", action="store_true", default=True)
    parser.add_argument("--no-mirror", action="store_false", dest="mirror")
    parser.add_argument("--print-sends", action="store_true")
    parser.add_argument("--debug-rx", action="store_true")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--object-size-cm", type=float, default=20.0, help="Approximate diameter of targeted objects.")
    parser.add_argument("--focal-length", type=float, default=550.0, help="Camera lens focal length for depth estimation.")
    parser.add_argument("--target-lost-rearm", type=nonnegative_float, default=TARGET_LOST_REARM)
    parser.add_argument("--send-interval", type=float, default=SEND_INTERVAL)
    parser.add_argument("--home-send-interval", type=float, default=HOME_SEND_INTERVAL)
    parser.add_argument("--send-timeout", type=float, default=2.0)
    parser.add_argument("--no-fire", action="store_true")
    parser.add_argument("--home-pan", type=command_value, default=HOME_PAN_VAL)
    parser.add_argument("--home-tilt", type=command_value, default=HOME_TILT_VAL)
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "aim_dataset.csv"),
        help="CSV path for fire-time D/F motor angle samples.",
    )
    parser.add_argument(
        "--no-dataset",
        action="store_true",
        help="Disable fire-time dataset logging.",
    )
    
    # MediaPipe object detection specific parameters
    parser.add_argument(
        "--model-path", 
        default=str(DEFAULT_DETECTOR_PATH), 
        help="Path to EfficientDet-Lite0 model file."
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
        default=["sports ball", "bottle", "cup", "banana", "apple", "orange"],
        help="List of COCO categories allowed to be tracked and intercepted."
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_camera(args)


if __name__ == "__main__":
    main()
