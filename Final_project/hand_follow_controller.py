#!/usr/bin/env python3
"""Laptop camera hand-follow controller for LEGO SPIKE pan/tilt testing.

This script tracks a hand from the laptop webcam and converts the hand center
into absolute pan/tilt angles for the LEGO launcher head. It sends commands in
the same format accepted by rl_hub_runner.py:

    AIM_ABS,<horizontal_angle>,<vertical_angle>

Use --dry-run first to verify tracking and angle output before connecting the
Hub communication bridge.
"""

from __future__ import annotations

import argparse
import socket
import time
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import cv2
    import mediapipe as mp
    import serial
except ModuleNotFoundError as exc:
    missing_package = exc.name
    pip_name = "pyserial" if missing_package == "serial" else missing_package
    raise SystemExit(
        f"Missing required package: {missing_package}. "
        f"Install dependencies with `pip install opencv-python mediapipe pyserial`."
    ) from exc


@dataclass(frozen=True)
class HandObservation:
    x: int
    y: int
    dx: float
    dy: float
    horizontal_angle: float
    vertical_angle: float


class CommandSender:
    def send(self, command: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class PrintCommandSender(CommandSender):
    def send(self, command: str) -> None:
        print(f"[DRY-RUN] {command}")


class TcpCommandSender(CommandSender):
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def send(self, command: str) -> None:
        self.sock.sendall((command.strip() + "\n").encode("utf-8"))

    def close(self) -> None:
        self.sock.close()


class SerialCommandSender(CommandSender):
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        time.sleep(2) # Allow connection to stabilize

    def send(self, command: str) -> None:
        self.ser.write((command.strip() + "\n").encode("utf-8"))

    def close(self) -> None:
        self.ser.close()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def smooth(previous: Optional[float], current: float, alpha: float) -> float:
    if previous is None:
        return current
    return previous * (1.0 - alpha) + current * alpha


def make_sender(args: argparse.Namespace) -> CommandSender:
    if args.dry_run:
        return PrintCommandSender()
    if args.serial_port:
        return SerialCommandSender(args.serial_port, args.baudrate, args.socket_timeout)
    if not args.host:
        raise ValueError("Use --dry-run, --serial-port, or pass --host for TCP command sending.")
    return TcpCommandSender(args.host, args.port, args.socket_timeout)


def estimate_hand_center(
    landmarks,
    frame_width: int,
    frame_height: int,
) -> Tuple[int, int]:
    # Average wrist and MCP landmarks for a stable palm center.
    palm_indices = (0, 5, 9, 13, 17)
    xs = [landmarks.landmark[i].x * frame_width for i in palm_indices]
    ys = [landmarks.landmark[i].y * frame_height for i in palm_indices]
    return int(sum(xs) / len(xs)), int(sum(ys) / len(ys))


def map_hand_to_angles(
    hand_x: int,
    hand_y: int,
    frame_width: int,
    frame_height: int,
    args: argparse.Namespace,
) -> HandObservation:
    center_x = frame_width / 2.0
    center_y = frame_height / 2.0
    dx = hand_x - center_x
    dy = hand_y - center_y

    normalized_x = dx / center_x
    normalized_y = dy / center_y

    horizontal = args.horizontal_center + normalized_x * args.horizontal_range * args.gain
    # Image y grows downward. A hand above center should increase the tilt angle.
    vertical = args.vertical_center - normalized_y * args.vertical_range * args.gain

    horizontal = clamp(horizontal, args.horizontal_min, args.horizontal_max)
    vertical = clamp(vertical, args.vertical_min, args.vertical_max)

    return HandObservation(hand_x, hand_y, dx, dy, horizontal, vertical)


def draw_overlay(
    frame,
    observation: Optional[HandObservation],
    last_command: str,
    mirror: bool,
) -> None:
    frame_h, frame_w = frame.shape[:2]
    center = (frame_w // 2, frame_h // 2)
    cv2.drawMarker(frame, center, (255, 255, 255), cv2.MARKER_CROSS, 32, 2)
    cv2.line(frame, (center[0], 0), (center[0], frame_h), (60, 60, 60), 1)
    cv2.line(frame, (0, center[1]), (frame_w, center[1]), (60, 60, 60), 1)

    if observation is None:
        cv2.putText(
            frame,
            "NO_HAND",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
    else:
        cv2.circle(frame, (observation.x, observation.y), 12, (0, 255, 0), -1)
        cv2.line(frame, center, (observation.x, observation.y), (0, 255, 255), 2)
        cv2.putText(
            frame,
            "dx={:.0f} dy={:.0f} h={:.1f} v={:.1f}".format(
                observation.dx,
                observation.dy,
                observation.horizontal_angle,
                observation.vertical_angle,
            ),
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )

    cv2.putText(
        frame,
        "q=quit c=center f=fire mirror={}".format("on" if mirror else "off"),
        (10, frame_h - 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        frame,
        last_command[-90:],
        (10, frame_h - 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
    )


def run(args: argparse.Namespace) -> None:
    sender = make_sender(args)
    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    if not cap.isOpened():
        sender.close()
        raise RuntimeError(f"Could not open camera {args.camera}")

    # Initialize MediaPipe Hands
    from mediapipe.python.solutions import hands as mp_hands
    from mediapipe.python.solutions import drawing_utils as mp_draw
    
    last_send_time = 0.0
    smoothed_h = None
    smoothed_v = None
    last_command = "ready"

    cv2.namedWindow("Hand Follow Controller", cv2.WINDOW_NORMAL)
    print("Press q to quit, c to center, f to fire.")

    try:
        with mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=args.min_detection_confidence,
            min_tracking_confidence=args.min_tracking_confidence,
        ) as hands:
            while True:
                ok, frame = cap.read()
                if not ok:
                    print("Failed to read camera frame.")
                    break

                if args.mirror:
                    frame = cv2.flip(frame, 1)

                frame_h, frame_w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = hands.process(rgb)
                observation = None

                if results.multi_hand_landmarks:
                    landmarks = results.multi_hand_landmarks[0]
                    mp_draw.draw_landmarks(frame, landmarks, mp_hands.HAND_CONNECTIONS)
                    hand_x, hand_y = estimate_hand_center(landmarks, frame_w, frame_h)
                    observation = map_hand_to_angles(hand_x, hand_y, frame_w, frame_h, args)
                    smoothed_h = smooth(smoothed_h, observation.horizontal_angle, args.smoothing)
                    smoothed_v = smooth(smoothed_v, observation.vertical_angle, args.smoothing)

                    now = time.time()
                    if now - last_send_time >= args.send_interval:
                        command = "AIM_ABS,{:.2f},{:.2f}".format(smoothed_h, smoothed_v)
                        sender.send(command)
                        last_command = command
                        last_send_time = now

                draw_overlay(frame, observation, last_command, args.mirror)
                cv2.imshow("Hand Follow Controller", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("c"):
                    sender.send("CENTER")
                    last_command = "CENTER"
                    smoothed_h = args.horizontal_center
                    smoothed_v = args.vertical_center
                if key == ord("f"):
                    sender.send("FIRE")
                    last_command = "FIRE"

    finally:
        sender.close()
        cap.release()
        cv2.destroyAllWindows()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print commands only.")
    parser.add_argument("--serial-port", help="USB/Bluetooth serial port of the SPIKE Hub (e.g. /dev/tty.LEGOHub).")
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--host", help="TCP host for a Hub command bridge.")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--socket-timeout", type=float, default=3.0)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--mirror", action="store_true", default=True)
    parser.add_argument("--no-mirror", action="store_false", dest="mirror")
    parser.add_argument("--send-interval", type=float, default=0.20)
    parser.add_argument("--smoothing", type=float, default=0.35)
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--horizontal-center", type=float, default=0.0)
    parser.add_argument("--horizontal-min", type=float, default=-35.0)
    parser.add_argument("--horizontal-max", type=float, default=35.0)
    parser.add_argument("--horizontal-range", type=float, default=35.0)
    parser.add_argument("--vertical-center", type=float, default=40.0)
    parser.add_argument("--vertical-min", type=float, default=0.0)
    parser.add_argument("--vertical-max", type=float, default=80.0)
    parser.add_argument("--vertical-range", type=float, default=40.0)
    parser.add_argument("--min-detection-confidence", type=float, default=0.6)
    parser.add_argument("--min-tracking-confidence", type=float, default=0.6)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(args)


if __name__ == "__main__":
    main()
