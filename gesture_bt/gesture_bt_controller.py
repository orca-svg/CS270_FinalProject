#!/usr/bin/env python3
"""Hand gesture controller for LEGO SPIKE Prime over Pybricks BLE.

This version uses the current MediaPipe Tasks API instead of the removed
`mp.solutions.hands` API. It works with recent MediaPipe releases such as
0.10.30+ and Python versions where `mediapipe.solutions` is no longer present.

Run on a Mac/laptop with a webcam.
It detects one hand with MediaPipe Hand Landmarker, converts hand position into
pan/tilt motor speed commands, and sends commands directly to the Hub over
Bluetooth.

Default gesture contract:
  - Open hand / visible palm: pan and tilt follow hand offset.
  - Open hand -> closed fist transition: send one fire latch.
  - Keyboard q: quit and STOP.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

try:
    import cv2
    import mediapipe as mp
    import numpy as np
except ModuleNotFoundError as exc:
    missing = exc.name
    package = "opencv-python" if missing == "cv2" else missing
    raise SystemExit(
        f"Missing package: {missing}. Install with: "
        f"python -m pip install opencv-python mediapipe numpy bleak"
    ) from exc

try:
    from mediapipe.tasks import python as mp_tasks_python
    from mediapipe.tasks.python import vision as mp_vision
except Exception as exc:
    raise SystemExit(
        "This controller requires the MediaPipe Tasks API. "
        "Install a recent MediaPipe version with: python -m pip install -U mediapipe"
    ) from exc

from pybricks_ble import DEFAULT_HUB_NAME, DryRunSender, PybricksBleSender, clamp

# Official MediaPipe Hand Landmarker model. The controller downloads it once if
# it is not already present locally.
DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"

# MediaPipe hand landmark connections. Defined locally so the code no longer
# depends on the removed mp.solutions.hands.HAND_CONNECTIONS constant.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)


@dataclass
class HandState:
    x: int
    y: int
    dx: int
    dy: int
    pan: int
    tilt: int
    fist: bool


class OpenCVCamera:
    def __init__(self, index: int, width: int, height: int) -> None:
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Could not open camera index {index}. "
                "On macOS, allow Terminal/iTerm/VS Code to access the camera."
            )

    def read(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def close(self) -> None:
        self.cap.release()


def ensure_hand_landmarker_model(model_path: Path, model_url: str) -> Path:
    """Download the MediaPipe .task model once if needed."""
    model_path = model_path.expanduser().resolve()
    if model_path.exists() and model_path.stat().st_size > 0:
        return model_path

    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Hand Landmarker model not found. Downloading to: {model_path}")
    print("This is needed only once.")
    try:
        urllib.request.urlretrieve(model_url, model_path)
    except Exception as exc:
        raise RuntimeError(
            "Could not download the MediaPipe Hand Landmarker model. "
            f"Download it manually from {model_url} and save it as {model_path}"
        ) from exc

    if not model_path.exists() or model_path.stat().st_size == 0:
        raise RuntimeError(f"Model download failed: {model_path}")
    return model_path


def create_hand_landmarker(args: argparse.Namespace):
    model_path = ensure_hand_landmarker_model(Path(args.model_path), args.model_url)
    base_options = mp_tasks_python.BaseOptions(model_asset_path=str(model_path))
    options = mp_vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=args.min_detection_confidence,
        min_hand_presence_confidence=args.min_presence_confidence,
        min_tracking_confidence=args.min_tracking_confidence,
    )
    return mp_vision.HandLandmarker.create_from_options(options)


def estimate_palm_center(landmarks: Sequence[object], width: int, height: int) -> Tuple[int, int]:
    palm_ids = (0, 5, 9, 13, 17)
    xs = [landmarks[i].x * width for i in palm_ids]
    ys = [landmarks[i].y * height for i in palm_ids]
    return int(sum(xs) / len(xs)), int(sum(ys) / len(ys))


def is_closed_fist(landmarks: Sequence[object]) -> bool:
    tips = (8, 12, 16, 20)
    pips = (6, 10, 14, 18)
    bent = 0
    for tip, pip in zip(tips, pips):
        # In image coordinates, y is larger when lower in the image.
        if landmarks[tip].y > landmarks[pip].y:
            bent += 1
    return bent >= 3


def hand_to_speed(
    hand_x: int,
    hand_y: int,
    frame_w: int,
    frame_h: int,
    args: argparse.Namespace,
    fist: bool,
) -> HandState:
    cx, cy = frame_w // 2, frame_h // 2
    dx, dy = hand_x - cx, hand_y - cy

    if fist:
        return HandState(hand_x, hand_y, dx, dy, 0, 0, True)

    if abs(dx) < args.deadzone_px:
        pan = 0
    else:
        pan = int(clamp((dx / (frame_w / 2)) * args.max_pan_speed * args.gain, -args.max_pan_speed, args.max_pan_speed))

    if abs(dy) < args.deadzone_px:
        tilt = 0
    else:
        # Hand above center should tilt up. Image y grows downward, hence minus.
        tilt = int(clamp((-dy / (frame_h / 2)) * args.max_tilt_speed * args.gain, -args.max_tilt_speed, args.max_tilt_speed))

    return HandState(hand_x, hand_y, dx, dy, pan, tilt, False)


def draw_hand_landmarks(frame, landmarks: Sequence[object]) -> None:
    h, w = frame.shape[:2]
    points = []
    for lm in landmarks:
        x = int(clamp(lm.x, 0.0, 1.0) * w)
        y = int(clamp(lm.y, 0.0, 1.0) * h)
        points.append((x, y))

    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, points[a], points[b], (80, 220, 80), 2)
    for i, point in enumerate(points):
        radius = 5 if i in (0, 4, 8, 12, 16, 20) else 3
        cv2.circle(frame, point, radius, (0, 255, 255), -1)


def draw_overlay(frame, state: Optional[HandState], last_command: str, mirror: bool) -> None:
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.drawMarker(frame, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 36, 2)
    cv2.line(frame, (cx, 0), (cx, h), (70, 70, 70), 1)
    cv2.line(frame, (0, cy), (w, cy), (70, 70, 70), 1)

    if state is None:
        cv2.putText(frame, "NO HAND", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    else:
        color = (0, 0, 255) if state.fist else (0, 255, 0)
        label = "FIST = FIRE" if state.fist else "PALM = FOLLOW"
        cv2.circle(frame, (state.x, state.y), 12, color, -1)
        cv2.line(frame, (cx, cy), (state.x, state.y), (0, 255, 255), 2)
        cv2.putText(frame, label, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        cv2.putText(
            frame,
            f"dx={state.dx} dy={state.dy} M,{state.pan},{state.tilt}",
            (12, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (230, 230, 230),
            2,
        )

    cv2.putText(
        frame,
        f"q quit | mirror={'on' if mirror else 'off'}",
        (12, h - 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
    )
    cv2.putText(frame, last_command[-80:], (12, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)


async def run(args: argparse.Namespace) -> None:
    sender = DryRunSender() if args.dry_run else PybricksBleSender(args.hub_name, args.scan_timeout)
    if hasattr(sender, "print_sends"):
        sender.print_sends = args.print_sends
    await sender.connect()

    camera = OpenCVCamera(args.camera, args.width, args.height)
    detector = create_hand_landmarker(args)

    cv2.namedWindow("Gesture BT Controller", cv2.WINDOW_NORMAL)
    last_send_time = 0.0
    last_command = "ready"
    no_hand_since = time.time()
    last_timestamp_ms = 0
    prev_fist = False     # for edge detection: send fire=1 only on open→fist transition
    pending_fire = False  # latch: holds fire=1 until next send interval
    # Track BLE/Hub re-bootstrap so we can tell the user and resend promptly.
    last_seen_recovery_generation = getattr(sender, "recovery_generation", 0)

    try:
        while True:
            frame = camera.read()
            if frame is None:
                print("Camera frame read failed.")
                break
            if args.mirror:
                frame = cv2.flip(frame, 1)

            frame_h, frame_w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            timestamp_ms = int(time.monotonic() * 1000)
            if timestamp_ms <= last_timestamp_ms:
                timestamp_ms = last_timestamp_ms + 1
            last_timestamp_ms = timestamp_ms

            result = detector.detect_for_video(mp_image, timestamp_ms)
            state: Optional[HandState] = None

            if result.hand_landmarks:
                no_hand_since = time.time()
                landmarks = result.hand_landmarks[0]
                draw_hand_landmarks(frame, landmarks)
                hand_x, hand_y = estimate_palm_center(landmarks, frame_w, frame_h)
                cx, cy = frame_w // 2, frame_h // 2
                dx = hand_x - cx
                dy = hand_y - cy
                fist = is_closed_fist(landmarks)
                # pan_err / tilt_err clamped to [-100, 100]
                pan_err  = int(clamp(dx, -100, 100))
                tilt_err = int(clamp(dy, -100, 100))
                # latch fire on open→fist transition; consumed at send time
                if fist and not prev_fist:
                    pending_fire = True
                prev_fist = fist
                state = HandState(hand_x, hand_y, dx, dy, pan_err, tilt_err, fist)
            else:
                # no hand: send zero error, no fire
                pan_err, tilt_err = 0, 0
                prev_fist = False

            now = time.time()

            # BLE/Hub가 재연결 후 핸드셰이크를 재부트스트랩하면 사용자에게 알리고,
            # send_interval 을 기다리지 않고 즉시 최신 aim 명령을 다시 보낸다.
            recovery_generation = getattr(sender, "recovery_generation", 0)
            force_resend = False
            if recovery_generation != last_seen_recovery_generation:
                last_seen_recovery_generation = recovery_generation
                force_resend = True
                print("[RUN] BLE/Hub recovered; resending latest aim command now.")

            if force_resend or now - last_send_time >= args.send_interval:
                if result.hand_landmarks:
                    fire_to_send = 1 if pending_fire else 0
                    command = f"M,{pan_err},{tilt_err},{fire_to_send}"
                else:
                    command = "M,0,0,0"
                if result.hand_landmarks or now - no_hand_since > args.no_hand_stop_delay:
                    # send() 가 False(미전송)를 반환하면 fire latch 를 소실하지 않도록
                    # pending_fire 를 유지하고 다음 루프에서 재시도한다. 루프는 계속 돈다.
                    sent = await sender.send(command)
                    if sent is False:
                        # 미전송: latch 유지, last_send_time 도 갱신하지 않아 곧 재시도.
                        pass
                    else:
                        if result.hand_landmarks:
                            pending_fire = False
                        last_command = command
                        last_send_time = now

            # Hub가 침묵하면(프로그램 멈춤) 사용자에게 알림
            if hasattr(sender, "maybe_warn_stale"):
                sender.maybe_warn_stale()

            draw_overlay(frame, state, last_command, args.mirror)
            cv2.imshow("Gesture BT Controller", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                await sender.send("STOP")
                break

            await asyncio.sleep(0)

    finally:
        with contextlib.suppress(Exception):
            await sender.send("STOP", timeout=0.2)
        with contextlib.suppress(Exception):
            detector.close()
        camera.close()
        cv2.destroyAllWindows()
        await sender.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Do not connect to BLE; print commands only.")
    p.add_argument("--hub-name", default=DEFAULT_HUB_NAME, help="Pybricks BLE hub name.")
    p.add_argument("--scan-timeout", type=float, default=15.0)
    p.add_argument("--print-sends", action="store_true", help="Print every command sent to the Hub for debugging.")
    p.add_argument("--camera", type=int, default=0, help="OpenCV camera index. Use 0 for most webcams.")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--mirror", action="store_true", default=True)
    p.add_argument("--no-mirror", action="store_false", dest="mirror")
    p.add_argument("--deadzone-px", type=int, default=28)
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--max-pan-speed", type=int, default=70)
    p.add_argument("--max-tilt-speed", type=int, default=80)
    p.add_argument("--send-interval", type=float, default=0.10)
    p.add_argument("--no-hand-stop-delay", type=float, default=0.25)
    p.add_argument("--min-detection-confidence", type=float, default=0.65)
    p.add_argument("--min-presence-confidence", type=float, default=0.65)
    p.add_argument("--min-tracking-confidence", type=float, default=0.65)
    p.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH), help="Path to hand_landmarker.task model file.")
    p.add_argument("--model-url", default=DEFAULT_MODEL_URL, help="URL used to download the hand landmarker model if missing.")
    return p


def main() -> None:
    args = build_parser().parse_args()
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
