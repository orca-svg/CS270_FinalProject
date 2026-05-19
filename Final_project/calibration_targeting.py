#!/usr/bin/env python3
"""Data-driven aiming calibration for the LEGO-K3/LAMD launcher.

This is the practical alternative to hit/miss reinforcement learning.
It collects a small number of calibration samples and uses interpolation to
map camera target error (dx, dy) to launcher angles.

Modes:
    collect   Save dx,dy -> horizontal_angle,vertical_angle samples.
    run       Predict angles from live camera input and send AIM_ABS commands.
    inspect   Print a quick summary of the collected calibration dataset.
"""

from __future__ import annotations

import argparse
import csv
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    missing_package = exc.name
    raise SystemExit(
        f"Missing required package: {missing_package}. "
        "Install dependencies with `pip install opencv-python numpy`."
    ) from exc


CSV_FIELDS = (
    "timestamp",
    "target_x",
    "target_y",
    "dx",
    "dy",
    "vx",
    "vy",
    "horizontal_angle",
    "vertical_angle",
)


@dataclass(frozen=True)
class MarkerConfig:
    hsv_low: Tuple[int, int, int]
    hsv_high: Tuple[int, int, int]
    min_area: float
    morph_kernel: int


@dataclass(frozen=True)
class TargetObservation:
    target_x: int
    target_y: int
    dx: float
    dy: float
    vx: float
    vy: float
    radius: float
    area: float


@dataclass(frozen=True)
class CalibrationSample:
    dx: float
    dy: float
    vx: float
    vy: float
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


def parse_hsv(value: str) -> Tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("HSV values must look like H,S,V")
    try:
        h, s, v = (int(part.strip()) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("HSV values must be integers") from exc
    if not (0 <= h <= 179 and 0 <= s <= 255 and 0 <= v <= 255):
        raise argparse.ArgumentTypeError("HSV ranges are H 0-179, S/V 0-255")
    return h, s, v


def detect_marker(
    frame: np.ndarray,
    config: MarkerConfig,
    previous: Optional[Tuple[float, float, float]],
) -> Optional[TargetObservation]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(config.hsv_low), np.array(config.hsv_high))

    if config.morph_kernel > 1:
        kernel = np.ones((config.morph_kernel, config.morph_kernel), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    if area < config.min_area:
        return None

    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        return None

    target_x = int(moments["m10"] / moments["m00"])
    target_y = int(moments["m01"] / moments["m00"])
    (_, _), radius = cv2.minEnclosingCircle(contour)
    frame_h, frame_w = frame.shape[:2]
    dx = float(target_x - frame_w // 2)
    dy = float(target_y - frame_h // 2)
    now = time.time()

    vx = 0.0
    vy = 0.0
    if previous is not None:
        prev_x, prev_y, prev_t = previous
        dt = max(now - prev_t, 1e-6)
        vx = (target_x - prev_x) / dt
        vy = (target_y - prev_y) / dt

    return TargetObservation(target_x, target_y, dx, dy, vx, vy, radius, area)


def draw_overlay(
    frame: np.ndarray,
    observation: Optional[TargetObservation],
    predicted: Optional[Tuple[float, float]],
    mode: str,
) -> np.ndarray:
    frame_h, frame_w = frame.shape[:2]
    center = (frame_w // 2, frame_h // 2)
    cv2.drawMarker(frame, center, (255, 255, 255), cv2.MARKER_CROSS, 28, 2)

    if observation is None:
        cv2.putText(frame, "NO_TARGET", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    else:
        target = (observation.target_x, observation.target_y)
        cv2.circle(frame, target, int(observation.radius), (0, 255, 0), 2)
        cv2.line(frame, center, target, (0, 255, 255), 2)
        cv2.putText(
            frame,
            "dx={:.0f} dy={:.0f} vx={:.1f} vy={:.1f}".format(
                observation.dx, observation.dy, observation.vx, observation.vy
            ),
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
        )

    if predicted is not None:
        cv2.putText(
            frame,
            "AIM_ABS h={:.1f} v={:.1f}".format(predicted[0], predicted[1]),
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
        )

    cv2.putText(
        frame,
        "mode={} | s=save, q=quit".format(mode),
        (10, frame_h - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    return frame


def append_sample(csv_path: Path, observation: TargetObservation, horizontal: float, vertical: float) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": "{:.6f}".format(time.time()),
                "target_x": observation.target_x,
                "target_y": observation.target_y,
                "dx": "{:.4f}".format(observation.dx),
                "dy": "{:.4f}".format(observation.dy),
                "vx": "{:.4f}".format(observation.vx),
                "vy": "{:.4f}".format(observation.vy),
                "horizontal_angle": "{:.4f}".format(horizontal),
                "vertical_angle": "{:.4f}".format(vertical),
            }
        )


def load_samples(csv_path: Path) -> List[CalibrationSample]:
    if not csv_path.exists():
        return []

    samples: List[CalibrationSample] = []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(
                CalibrationSample(
                    dx=float(row["dx"]),
                    dy=float(row["dy"]),
                    vx=float(row.get("vx", 0.0)),
                    vy=float(row.get("vy", 0.0)),
                    horizontal_angle=float(row["horizontal_angle"]),
                    vertical_angle=float(row["vertical_angle"]),
                )
            )
    return samples


def inverse_distance_predict(
    samples: Sequence[CalibrationSample],
    dx: float,
    dy: float,
    k: int,
    power: float,
) -> Tuple[float, float]:
    if not samples:
        raise ValueError("No calibration samples are available.")

    distances = []
    for sample in samples:
        dist = ((sample.dx - dx) ** 2 + (sample.dy - dy) ** 2) ** 0.5
        distances.append((dist, sample))
    distances.sort(key=lambda item: item[0])

    selected = distances[: max(1, min(k, len(distances)))]
    if selected[0][0] < 1e-6:
        sample = selected[0][1]
        return sample.horizontal_angle, sample.vertical_angle

    weighted_h = 0.0
    weighted_v = 0.0
    total_weight = 0.0
    for dist, sample in selected:
        weight = 1.0 / max(dist, 1e-6) ** power
        weighted_h += sample.horizontal_angle * weight
        weighted_v += sample.vertical_angle * weight
        total_weight += weight
    return weighted_h / total_weight, weighted_v / total_weight


def make_sender(args: argparse.Namespace) -> CommandSender:
    if args.dry_run:
        return PrintCommandSender()
    if not args.host:
        raise ValueError("Use --dry-run or pass --host for TCP command sending.")
    return TcpCommandSender(args.host, args.port, args.socket_timeout)


def read_angle(prompt: str) -> float:
    while True:
        value = input(prompt).strip()
        try:
            return float(value)
        except ValueError:
            print("Enter a numeric angle.")


def open_camera(args: argparse.Namespace) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera {args.camera}")
    return cap


def run_collect(args: argparse.Namespace) -> None:
    config = MarkerConfig(args.hsv_low, args.hsv_high, args.min_area, args.morph_kernel)
    cap = open_camera(args)
    window_name = "Calibration Collector"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    previous = None
    saved = 0

    print("Move the launcher until the reticle is aligned with the marker.")
    print("Press s in the camera window, then enter current horizontal/vertical angles.")
    print("Press q to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Failed to read frame.")
                break
            observation = detect_marker(frame, config, previous)
            if observation is not None:
                previous = (observation.target_x, observation.target_y, time.time())
            cv2.imshow(window_name, draw_overlay(frame, observation, None, "collect"))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                if observation is None:
                    print("No marker detected. Sample not saved.")
                    continue
                horizontal = read_angle("Current horizontal angle: ")
                vertical = read_angle("Current vertical angle: ")
                append_sample(Path(args.dataset), observation, horizontal, vertical)
                saved += 1
                print(f"Saved sample {saved}: dx={observation.dx:.0f}, dy={observation.dy:.0f}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def run_live(args: argparse.Namespace) -> None:
    samples = load_samples(Path(args.dataset))
    if not samples:
        raise RuntimeError(f"No calibration samples found at {args.dataset}")

    config = MarkerConfig(args.hsv_low, args.hsv_high, args.min_area, args.morph_kernel)
    sender = make_sender(args)
    cap = open_camera(args)
    window_name = "Calibration Targeting"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    previous = None
    last_sent = 0.0

    print(f"Loaded {len(samples)} calibration samples.")
    print("Press q in the camera window to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Failed to read frame.")
                break

            observation = detect_marker(frame, config, previous)
            predicted = None
            if observation is not None:
                previous = (observation.target_x, observation.target_y, time.time())
                lead_dx = observation.dx + observation.vx * args.lead_time
                lead_dy = observation.dy + observation.vy * args.lead_time
                predicted = inverse_distance_predict(samples, lead_dx, lead_dy, args.neighbors, args.power)
                now = time.time()
                if now - last_sent >= args.send_interval:
                    sender.send("AIM_ABS,{:.2f},{:.2f}".format(predicted[0], predicted[1]))
                    last_sent = now

            cv2.imshow(window_name, draw_overlay(frame, observation, predicted, "run"))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("f"):
                sender.send("FIRE")
            if key == ord("c"):
                sender.send("CENTER")
    finally:
        sender.close()
        cap.release()
        cv2.destroyAllWindows()


def run_inspect(args: argparse.Namespace) -> None:
    samples = load_samples(Path(args.dataset))
    print(f"dataset: {args.dataset}")
    print(f"samples: {len(samples)}")
    if not samples:
        return
    print("dx range: {:.1f} to {:.1f}".format(min(s.dx for s in samples), max(s.dx for s in samples)))
    print("dy range: {:.1f} to {:.1f}".format(min(s.dy for s in samples), max(s.dy for s in samples)))
    print(
        "horizontal range: {:.1f} to {:.1f}".format(
            min(s.horizontal_angle for s in samples),
            max(s.horizontal_angle for s in samples),
        )
    )
    print(
        "vertical range: {:.1f} to {:.1f}".format(
            min(s.vertical_angle for s in samples),
            max(s.vertical_angle for s in samples),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    default_dataset = Path(__file__).with_name("aim_calibration.csv")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "run", "inspect"))
    parser.add_argument("--dataset", default=str(default_dataset))
    parser.add_argument("--dry-run", action="store_true", help="Print commands instead of sending them.")
    parser.add_argument("--host", help="TCP host for a command bridge.")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--socket-timeout", type=float, default=3.0)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--hsv-low", type=parse_hsv, default=(35, 80, 80))
    parser.add_argument("--hsv-high", type=parse_hsv, default=(90, 255, 255))
    parser.add_argument("--min-area", type=float, default=120.0)
    parser.add_argument("--morph-kernel", type=int, default=5)
    parser.add_argument("--neighbors", type=int, default=4)
    parser.add_argument("--power", type=float, default=2.0)
    parser.add_argument("--lead-time", type=float, default=0.0)
    parser.add_argument("--send-interval", type=float, default=0.25)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.mode == "collect":
        run_collect(args)
    elif args.mode == "run":
        run_live(args)
    elif args.mode == "inspect":
        run_inspect(args)


if __name__ == "__main__":
    main()
