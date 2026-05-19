#!/usr/bin/env python3
"""Q-learning aiming prototype for the LEGO-K3/LAMD launcher.

Run this file on the Raspberry Pi or a laptop connected to the camera.
It tracks a fluorescent circular marker, converts the target offset into
a small discrete state, chooses pan/tilt correction commands with
epsilon-greedy Q-learning, and updates a Q-table from manual hit/miss input.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    missing_package = exc.name
    raise SystemExit(
        f"Missing required package: {missing_package}. "
        "Install dependencies with `pip install opencv-python numpy` "
        "on the Raspberry Pi or laptop that will run the camera trainer."
    ) from exc


ACTION_NAMES = (
    "LEFT",
    "RIGHT",
    "UP",
    "DOWN",
    "UP_LEFT",
    "UP_RIGHT",
    "DOWN_LEFT",
    "DOWN_RIGHT",
    "HOLD",
)

X_BINS = ("LEFT", "CENTER", "RIGHT")
Y_BINS = ("UP", "CENTER", "DOWN")
STATE_NAMES = tuple(f"{x}_{y}" for y in Y_BINS for x in X_BINS)


@dataclass(frozen=True)
class MarkerConfig:
    """HSV marker threshold and contour filtering settings."""

    hsv_low: Tuple[int, int, int]
    hsv_high: Tuple[int, int, int]
    min_area: float
    morph_kernel: int


@dataclass(frozen=True)
class TargetObservation:
    center_x: int
    center_y: int
    radius: float
    area: float
    dx: int
    dy: int
    confidence: float


class QLearner:
    def __init__(
        self,
        q_table_path: Path,
        alpha: float = 0.2,
        gamma: float = 0.9,
        epsilon: float = 0.3,
        min_epsilon: float = 0.05,
        epsilon_decay: float = 0.98,
    ) -> None:
        self.q_table_path = q_table_path
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.min_epsilon = min_epsilon
        self.epsilon_decay = epsilon_decay
        self.q_table = self._load_q_table()

    def _new_state_values(self) -> Dict[str, float]:
        return {action: 0.0 for action in ACTION_NAMES}

    def _load_q_table(self) -> Dict[str, Dict[str, float]]:
        if not self.q_table_path.exists():
            return {state: self._new_state_values() for state in STATE_NAMES}

        with self.q_table_path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)

        q_table = {state: self._new_state_values() for state in STATE_NAMES}
        for state, action_values in loaded.get("q_table", loaded).items():
            if state not in q_table:
                continue
            for action, value in action_values.items():
                if action in q_table[state]:
                    q_table[state][action] = float(value)

        self.epsilon = float(loaded.get("epsilon", self.epsilon))
        return q_table

    def save(self) -> None:
        payload = {
            "alpha": self.alpha,
            "gamma": self.gamma,
            "epsilon": self.epsilon,
            "min_epsilon": self.min_epsilon,
            "epsilon_decay": self.epsilon_decay,
            "q_table": self.q_table,
        }
        self.q_table_path.parent.mkdir(parents=True, exist_ok=True)
        with self.q_table_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    def choose_action(self, state: str) -> str:
        if random.random() < self.epsilon:
            return random.choice(ACTION_NAMES)

        values = self.q_table[state]
        best_value = max(values.values())
        best_actions = [action for action, value in values.items() if value == best_value]
        return random.choice(best_actions)

    def update_episode(self, transitions: Iterable[Tuple[str, str]], reward: float) -> None:
        discounted_reward = reward
        for state, action in reversed(list(transitions)):
            old_value = self.q_table[state][action]
            self.q_table[state][action] = old_value + self.alpha * (
                discounted_reward - old_value
            )
            discounted_reward *= self.gamma

        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)


class CommandSender:
    def send(self, command: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class PrintCommandSender(CommandSender):
    def send(self, command: str) -> None:
        print(f"[DRY-RUN] {command}")


class TcpCommandSender(CommandSender):
    """Simple TCP sender for later Bluetooth PAN/socket integration."""

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


def discretize_state(dx: int, dy: int, deadband_px: int) -> str:
    if dx < -deadband_px:
        x_bin = "LEFT"
    elif dx > deadband_px:
        x_bin = "RIGHT"
    else:
        x_bin = "CENTER"

    if dy < -deadband_px:
        y_bin = "UP"
    elif dy > deadband_px:
        y_bin = "DOWN"
    else:
        y_bin = "CENTER"

    return f"{x_bin}_{y_bin}"


def detect_marker(frame: np.ndarray, config: MarkerConfig) -> Optional[TargetObservation]:
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

    center_x = int(moments["m10"] / moments["m00"])
    center_y = int(moments["m01"] / moments["m00"])
    (_, _), radius = cv2.minEnclosingCircle(contour)
    frame_h, frame_w = frame.shape[:2]
    dx = center_x - frame_w // 2
    dy = center_y - frame_h // 2
    confidence = min(1.0, area / max(config.min_area * 8.0, 1.0))

    return TargetObservation(
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        area=area,
        dx=dx,
        dy=dy,
        confidence=confidence,
    )


def draw_debug_overlay(
    frame: np.ndarray,
    observation: Optional[TargetObservation],
    state: Optional[str],
    action: Optional[str],
    epsilon: float,
    episode: int,
    step: int,
) -> np.ndarray:
    frame_h, frame_w = frame.shape[:2]
    center = (frame_w // 2, frame_h // 2)
    cv2.drawMarker(frame, center, (255, 255, 255), cv2.MARKER_CROSS, 28, 2)

    if observation is not None:
        target = (observation.center_x, observation.center_y)
        cv2.circle(frame, target, int(observation.radius), (0, 255, 0), 2)
        cv2.line(frame, center, target, (0, 255, 255), 2)
        cv2.putText(
            frame,
            f"dx={observation.dx} dy={observation.dy} conf={observation.confidence:.2f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
    else:
        cv2.putText(
            frame,
            "NO_TARGET",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )

    cv2.putText(
        frame,
        f"ep={episode} step={step} eps={epsilon:.2f} state={state or '-'} action={action or '-'}",
        (10, frame_h - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    return frame


def wait_for_observation(
    cap: cv2.VideoCapture,
    config: MarkerConfig,
    deadband_px: int,
    episode: int,
    step: int,
    epsilon: float,
    window_name: str,
) -> Tuple[Optional[TargetObservation], Optional[str], bool]:
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to read a camera frame.")
            return None, None, False

        observation = detect_marker(frame, config)
        state = (
            discretize_state(observation.dx, observation.dy, deadband_px)
            if observation is not None
            else None
        )

        debug_frame = draw_debug_overlay(
            frame, observation, state, None, epsilon, episode, step
        )
        cv2.imshow(window_name, debug_frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            return None, None, False
        if observation is not None:
            return observation, state, True


def ask_hit_or_miss() -> float:
    while True:
        value = input("Result after FIRE: hit or miss? [h/m/q] ").strip().lower()
        if value in ("h", "hit"):
            return 1.0
        if value in ("m", "miss"):
            return -1.0
        if value in ("q", "quit"):
            raise KeyboardInterrupt
        print("Please enter h, m, or q.")


def make_command_sender(args: argparse.Namespace) -> CommandSender:
    if args.dry_run:
        return PrintCommandSender()
    if not args.host:
        raise ValueError("Use --dry-run or provide --host for TCP command sending.")
    return TcpCommandSender(args.host, args.port, args.socket_timeout)


def run_training(args: argparse.Namespace) -> None:
    q_path = Path(args.q_table)
    learner = QLearner(
        q_path,
        alpha=args.alpha,
        gamma=args.gamma,
        epsilon=args.epsilon,
        min_epsilon=args.min_epsilon,
        epsilon_decay=args.epsilon_decay,
    )
    marker_config = MarkerConfig(
        hsv_low=args.hsv_low,
        hsv_high=args.hsv_high,
        min_area=args.min_area,
        morph_kernel=args.morph_kernel,
    )
    sender = make_command_sender(args)
    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    if not cap.isOpened():
        sender.close()
        raise RuntimeError(f"Could not open camera {args.camera}")

    window_name = "Q-learning Aim Trainer"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    print("Press q in the camera window to quit.")
    print(f"Q-table: {q_path}")

    try:
        for episode in range(1, args.episodes + 1):
            transitions: List[Tuple[str, str]] = []
            print(f"\nEpisode {episode}/{args.episodes}")

            for step in range(1, args.aim_steps + 1):
                observation, state, keep_running = wait_for_observation(
                    cap,
                    marker_config,
                    args.deadband_px,
                    episode,
                    step,
                    learner.epsilon,
                    window_name,
                )
                if not keep_running:
                    raise KeyboardInterrupt
                if observation is None or state is None:
                    print("NO_TARGET")
                    continue

                action = learner.choose_action(state)
                transitions.append((state, action))
                command = f"AIM,{action}"
                sender.send(command)
                print(
                    f"step={step} state={state} action={action} "
                    f"dx={observation.dx} dy={observation.dy}"
                )
                time.sleep(args.action_delay)

            if not transitions:
                print("Episode skipped because no target was detected.")
                continue

            sender.send("FIRE")
            reward = ask_hit_or_miss()
            learner.update_episode(transitions, reward)
            learner.save()
            print(
                f"updated with reward={reward:+.0f}; "
                f"epsilon={learner.epsilon:.3f}"
            )

    except KeyboardInterrupt:
        print("\nStopping trainer.")
    finally:
        learner.save()
        sender.close()
        cap.release()
        cv2.destroyAllWindows()


def build_parser() -> argparse.ArgumentParser:
    default_q_table = Path(__file__).with_name("q_table.json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print commands only.")
    parser.add_argument("--host", help="TCP host for Hub command receiver.")
    parser.add_argument("--port", type=int, default=9999, help="TCP command port.")
    parser.add_argument("--socket-timeout", type=float, default=3.0)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--aim-steps", type=int, default=5)
    parser.add_argument("--action-delay", type=float, default=0.35)
    parser.add_argument("--deadband-px", type=int, default=35)
    parser.add_argument("--min-area", type=float, default=120.0)
    parser.add_argument("--morph-kernel", type=int, default=5)
    parser.add_argument("--hsv-low", type=parse_hsv, default=(35, 80, 80))
    parser.add_argument("--hsv-high", type=parse_hsv, default=(90, 255, 255))
    parser.add_argument("--q-table", default=str(default_q_table))
    parser.add_argument("--alpha", type=float, default=0.2)
    parser.add_argument("--gamma", type=float, default=0.9)
    parser.add_argument("--epsilon", type=float, default=0.3)
    parser.add_argument("--min-epsilon", type=float, default=0.05)
    parser.add_argument("--epsilon-decay", type=float, default=0.98)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_training(args)


if __name__ == "__main__":
    main()
