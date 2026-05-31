#!/usr/bin/env python3
"""Hand gesture controller for LEGO SPIKE Prime over Pybricks BLE.

This version uses the current MediaPipe Tasks API instead of the removed
`mp.solutions.hands` API. It works with recent MediaPipe releases such as
0.10.30+ and Python versions where `mediapipe.solutions` is no longer present.

Run on a laptop with a webcam or on a Raspberry Pi with a USB/RPi camera.
It detects one hand with MediaPipe Hand Landmarker, converts hand position into
pan/tilt motor speed commands, and sends commands directly to the Hub over
Bluetooth.

Default gesture contract:
  - Open hand / visible palm: pan and tilt follow hand offset.
  - Closed fist: stop/hold the pan and tilt motors.
  - Keyboard t: run pan/tilt motor TEST.
  - Keyboard f: send FIRE manually.
  - Keyboard c: center/stop pan and tilt.
  - Keyboard w/x: launcher wheels on/off.
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
    from bleak import BleakClient, BleakScanner
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package: bleak. Install with: python -m pip install bleak") from exc

try:
    from mediapipe.tasks import python as mp_tasks_python
    from mediapipe.tasks.python import vision as mp_vision
except Exception as exc:
    raise SystemExit(
        "This controller requires the MediaPipe Tasks API. "
        "Install a recent MediaPipe version with: python -m pip install -U mediapipe"
    ) from exc

PYBRICKS_COMMAND_EVENT_CHAR_UUID = "c5f50002-8280-46da-89f4-6d8051e4aeef"
DEFAULT_HUB_NAME = "Pybricks Hub"

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


class PybricksBleSender:
    def __init__(self, hub_name: str, scan_timeout: float = 15.0) -> None:
        self.hub_name = hub_name
        self.scan_timeout = scan_timeout
        self.client: Optional[BleakClient] = None
        self.ready = asyncio.Event()
        self.connected = False
        self.last_wait_log = 0.0
        self.print_sends = False
        self._rx_text_buffer = ""

    async def connect(self) -> None:
        print(f"Scanning for BLE hub named '{self.hub_name}'...")
        device = await BleakScanner.find_device_by_name(self.hub_name, timeout=self.scan_timeout)
        if device is None:
            raise RuntimeError(
                f"Could not find '{self.hub_name}'. Disconnect Pybricks Code, "
                "turn the Hub on, and make sure the Hub program is not already running."
            )

        def handle_disconnect(_: BleakClient) -> None:
            self.connected = False
            print("Hub disconnected.")

        self.client = BleakClient(device, disconnected_callback=handle_disconnect)
        await self.client.connect()
        await self.client.start_notify(PYBRICKS_COMMAND_EVENT_CHAR_UUID, self._handle_rx)
        self.connected = True
        print("BLE connected. Start the saved Hub program with the Hub center button.")

    def _handle_rx(self, _: int, data: bytearray) -> None:
        if not data:
            return
        if data[0] == 0x01:
            payload = bytes(data[1:])
            if b"rdy" in payload:
                self.ready.set()
                payload = payload.replace(b"rdy", b"")

            text = payload.decode("utf-8", errors="replace")
            if not text:
                return
            self._rx_text_buffer += text
            while "\n" in self._rx_text_buffer:
                line, self._rx_text_buffer = self._rx_text_buffer.split("\n", 1)
                line = line.strip()
                if line:
                    print(f"[Hub] {line}")

    @staticmethod
    def _i8(value: int) -> int:
        value = max(-100, min(100, int(value)))
        return value & 0xFF

    def _packet_for(self, command: str) -> bytes:
        cmd = command.strip().upper()
        if cmd.startswith("M,"):
            parts = cmd.split(",")
            if len(parts) != 4:
                return b"S\x00\x00\x00"
            pan_err = self._i8(float(parts[1]))
            tilt_err = self._i8(float(parts[2]))
            fire = int(parts[3]) & 0xFF
            return bytes([ord("M"), pan_err, tilt_err, fire])
        if cmd == "STOP":
            return b"S\x00\x00\x00"
        return b"S\x00\x00\x00"

    async def send(self, command: str, timeout: float = 1.0) -> None:
        if not self.client or not self.connected:
            return
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            now = time.time()
            if now - self.last_wait_log > 2.0:
                print("[WAIT] Hub program is not sending rdy yet. Press the Hub center button, "
                      "or check that the Hub display shows BT and the saved program did not crash.")
                self.last_wait_log = now
            return
        self.ready.clear()
        packet = self._packet_for(command)
        if self.print_sends:
            print(f"[SEND] {command.strip()} -> {packet!r}")
        await self.client.write_gatt_char(
            PYBRICKS_COMMAND_EVENT_CHAR_UUID,
            b"\x06" + packet,
            response=True,
        )

    async def close(self) -> None:
        if self.client:
            with contextlib.suppress(Exception):
                await self.send("STOP", timeout=0.2)
            with contextlib.suppress(Exception):
                await self.client.disconnect()


class DryRunSender:
    async def connect(self) -> None:
        print("DRY RUN: no BLE connection. Commands will be printed only.")

    async def send(self, command: str, timeout: float = 0.0) -> None:
        print(f"[DRY] {command}")

    async def close(self) -> None:
        pass


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


class PiCamera2Source:
    def __init__(self, width: int, height: int) -> None:
        try:
            from picamera2 import Picamera2
        except ModuleNotFoundError as exc:
            raise RuntimeError("picamera2 is not installed. Try OpenCV camera mode first.") from exc
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        self.picam2.configure(config)
        self.picam2.start()
        time.sleep(0.5)

    def read(self):
        rgb = self.picam2.capture_array()
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def close(self) -> None:
        self.picam2.stop()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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
        label = "FIST = HOLD" if state.fist else "PALM = FOLLOW"
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
        f"q quit | c center | f fire | w/x wheels | mirror={'on' if mirror else 'off'}",
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

    camera = PiCamera2Source(args.width, args.height) if args.picamera2 else OpenCVCamera(args.camera, args.width, args.height)
    detector = create_hand_landmarker(args)

    cv2.namedWindow("Gesture BT Controller", cv2.WINDOW_NORMAL)
    last_send_time = 0.0
    last_command = "ready"
    no_hand_since = time.time()
    last_timestamp_ms = 0
    prev_fist = False     # for edge detection: send fire=1 only on open→fist transition
    pending_fire = False  # latch: holds fire=1 until next send interval

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
            if now - last_send_time >= args.send_interval:
                if result.hand_landmarks:
                    fire_to_send = 1 if pending_fire else 0
                    pending_fire = False
                    command = f"M,{pan_err},{tilt_err},{fire_to_send}"
                else:
                    command = "M,0,0,0"
                if result.hand_landmarks or now - no_hand_since > args.no_hand_stop_delay:
                    await sender.send(command)
                    last_command = command
                    last_send_time = now

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
    p.add_argument("--picamera2", action="store_true", help="Use Raspberry Pi Picamera2 instead of OpenCV VideoCapture.")
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
