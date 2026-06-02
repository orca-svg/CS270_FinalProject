#!/usr/bin/env python3
"""Balloon interception controller for LEGO SPIKE Prime over Pybricks BLE.

Detects a balloon by its HSV color, predicts its parabolic motion, auto-aims
via pan/tilt, and fires automatically when the predicted impact point is
centered.

Hub code: hub_pybricks_gesture_server.py (no changes needed)
Packet format: b'\\x06' + [ord('M'), pan_err_i8, tilt_err_i8, fire(0/1)]

Usage:
    # Interactive color picker (recommended)
    python balloon_intercept.py --hub-name "Team5" --color-picker

    # Direct HSV range
    python balloon_intercept.py --hub-name "Team5" --hsv-lower "25,80,80" --hsv-upper "45,255,255"

    # Dry run (no BLE)
    python balloon_intercept.py --dry-run --color-picker
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"Missing package: {exc.name}. Install with: pip install opencv-python numpy"
    ) from exc

from pybricks_ble import DryRunSender, PybricksBleSender, clamp

# ---------------------------------------------------------------------------
# BalloonDetector
# ---------------------------------------------------------------------------

class BalloonDetector:
    """HSV 색상 분리로 풍선 중심을 탐지한다."""

    MIN_AREA = 300       # 노이즈 제거용 최소 contour 면적 (픽셀²)
    MIN_CIRCULARITY = 0.3  # 원형도 하한 (0~1). 풍선=둥글므로 낮은 임계값 사용

    def __init__(self, hsv_lower: Tuple[int, int, int], hsv_upper: Tuple[int, int, int]) -> None:
        self.lower = np.array(hsv_lower, dtype=np.uint8)
        self.upper = np.array(hsv_upper, dtype=np.uint8)

    def detect(self, frame) -> Optional[Tuple[int, int, int]]:
        """frame에서 풍선을 탐지해 (cx, cy, radius)를 반환. 미탐지 시 None."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower, self.upper)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best = None
        best_area = 0.0
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.MIN_AREA:
                continue
            perimeter = cv2.arcLength(c, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < self.MIN_CIRCULARITY:
                continue
            if area > best_area:
                best_area = area
                best = c

        if best is None:
            return None

        (x, y), radius = cv2.minEnclosingCircle(best)
        return int(x), int(y), int(radius)

    def debug_mask(self, frame):
        """디버그용: 현재 마스크 이미지를 반환."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower, self.upper)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)
        return mask


def color_picker(cap, width: int, height: int) -> Tuple[Tuple[int,int,int], Tuple[int,int,int]]:
    """인터랙티브 색상 피커. 풍선 클릭 → HSV 범위 자동 계산. 스페이스바로 확정."""
    print("\n[COLOR PICKER] 카메라 창에서 풍선을 클릭하세요. 스페이스바로 확정.")

    clicked_samples: list = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            frame = param["frame"]
            if frame is None:
                return
            h, w = frame.shape[:2]
            # 클릭 주변 8×8 패치 샘플링
            x1, y1 = max(0, x - 8), max(0, y - 8)
            x2, y2 = min(w, x + 8), min(h, y + 8)
            patch = frame[y1:y2, x1:x2]
            hsv_patch = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            flat = hsv_patch.reshape(-1, 3).astype(float)
            clicked_samples.append(flat)
            print(f"[COLOR PICKER] 클릭 ({x},{y}) 샘플 추가 (총 {len(clicked_samples)}개). "
                  "여러 곳 클릭 가능. 스페이스바로 확정.")

    cv2.namedWindow("Color Picker", cv2.WINDOW_NORMAL)
    state = {"frame": None}
    cv2.setMouseCallback("Color Picker", on_mouse, param=state)

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.resize(frame, (width, height))
        state["frame"] = frame.copy()

        # 현재 범위로 마스크 미리보기 (샘플이 있을 때만)
        display = frame.copy()
        if clicked_samples:
            all_samples = np.vstack(clicked_samples)
            mean = all_samples.mean(axis=0)
            std = all_samples.std(axis=0)
            lo = np.clip(mean - 2.5 * std, 0, [179, 255, 255]).astype(np.uint8)
            hi = np.clip(mean + 2.5 * std, 0, [179, 255, 255]).astype(np.uint8)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, lo, hi)
            mask = cv2.erode(mask, None, iterations=2)
            mask = cv2.dilate(mask, None, iterations=2)
            colored_mask = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            colored_mask[:, :, 1] = 0  # 초록 채널 제거 → 빨강+파랑 오버레이
            display = cv2.addWeighted(display, 0.6, colored_mask, 0.4, 0)
            cv2.putText(display, f"HSV lower={tuple(lo)} upper={tuple(hi)}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.putText(display, "Click balloon | SPACE=confirm | q=quit",
                    (10, height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.imshow("Color Picker", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(" ") and clicked_samples:
            break
        if key == ord("q"):
            cv2.destroyWindow("Color Picker")
            raise SystemExit("Color picker cancelled.")

    cv2.destroyWindow("Color Picker")
    all_samples = np.vstack(clicked_samples)
    mean = all_samples.mean(axis=0)
    std = all_samples.std(axis=0)
    lo = tuple(np.clip(mean - 2.5 * std, 0, [179, 255, 255]).astype(int))
    hi = tuple(np.clip(mean + 2.5 * std, 0, [179, 255, 255]).astype(int))
    print(f"[COLOR PICKER] 확정: lower={lo} upper={hi}")
    return lo, hi  # type: ignore


# ---------------------------------------------------------------------------
# ParabolicTracker — 이동 예측 (리드샷)
# ---------------------------------------------------------------------------

class ParabolicTracker:
    """EMA 속도와 수직 가속도를 추정해 포물선 미래 위치를 예측한다."""

    DEFAULT_FRAME_DT = 1.0 / 30.0

    def __init__(self, velocity_smoothing: float = 0.3, accel_smoothing: float = 0.05) -> None:
        self.velocity_smoothing = clamp(velocity_smoothing, 0.0, 1.0)
        self.accel_smoothing = clamp(accel_smoothing, 0.0, 1.0)
        self.x: Optional[float] = None
        self.y: Optional[float] = None
        self.t: Optional[float] = None
        self.vx_smooth = 0.0
        self.vy_smooth = 0.0
        self.ay_smooth = 0.0
        self.last_dt = self.DEFAULT_FRAME_DT

    def update(self, x: int, y: int, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        x_f = float(x)
        y_f = float(y)

        if self.x is not None and self.y is not None and self.t is not None:
            dt = max(now - self.t, 1e-3)
            self.last_dt = dt
            raw_vx = (x_f - self.x) / dt
            raw_vy = (y_f - self.y) / dt

            old_vy = self.vy_smooth
            self.vx_smooth = (
                self.velocity_smoothing * raw_vx
                + (1.0 - self.velocity_smoothing) * self.vx_smooth
            )
            self.vy_smooth = (
                self.velocity_smoothing * raw_vy
                + (1.0 - self.velocity_smoothing) * self.vy_smooth
            )
            raw_ay = (self.vy_smooth - old_vy) / dt
            self.ay_smooth = (
                self.accel_smoothing * raw_ay
                + (1.0 - self.accel_smoothing) * self.ay_smooth
            )

        self.x = x_f
        self.y = y_f
        self.t = now

    def lead_time(self, flight_time: float, lead_frames: int) -> float:
        """초 단위 비행시간에 프레임 기반 보정치를 더한다."""
        return max(0.0, flight_time) + max(0, lead_frames) * self.last_dt

    def predict(
        self,
        flight_time: float,
        lead_frames: int = 0,
        frame_w: Optional[int] = None,
        frame_h: Optional[int] = None,
    ) -> Tuple[int, int]:
        """포물선 운동식으로 미래 위치를 예측한다."""
        if self.x is None or self.y is None:
            return 0, 0

        dt = self.lead_time(flight_time, lead_frames)
        pred_x = self.x + self.vx_smooth * dt
        pred_y = self.y + self.vy_smooth * dt + 0.5 * self.ay_smooth * dt * dt

        if frame_w is not None:
            pred_x = clamp(pred_x, 0, frame_w - 1)
        if frame_h is not None:
            pred_y = clamp(pred_y, 0, frame_h - 1)
        return int(pred_x), int(pred_y)

    def stats(self, flight_time: float, lead_frames: int) -> Tuple[float, float, float, float]:
        """오버레이 표시용 (lead_time, vx, vy, ay)."""
        return (
            self.lead_time(flight_time, lead_frames),
            self.vx_smooth,
            self.vy_smooth,
            self.ay_smooth,
        )

    def reset(self) -> None:
        self.x = None
        self.y = None
        self.t = None
        self.vx_smooth = 0.0
        self.vy_smooth = 0.0
        self.ay_smooth = 0.0
        self.last_dt = self.DEFAULT_FRAME_DT


# ---------------------------------------------------------------------------
# AimController — 자동 발사 판단
# ---------------------------------------------------------------------------

class AimController:
    def __init__(
        self,
        fire_threshold: int,
        hold_frames: int,
        fire_cooldown: float,
    ) -> None:
        self.fire_threshold = fire_threshold
        self.hold_frames = hold_frames
        self.fire_cooldown = fire_cooldown
        self._lock_count = 0
        self._last_fire = 0.0

    def update(self, dx: int, dy: int) -> bool:
        """dx, dy를 받아 이번 프레임에 발사해야 하면 True 반환."""
        locked = abs(dx) <= self.fire_threshold and abs(dy) <= self.fire_threshold
        if locked:
            self._lock_count += 1
        else:
            self._lock_count = 0

        if (
            self._lock_count >= self.hold_frames
            and time.time() - self._last_fire > self.fire_cooldown
        ):
            self._lock_count = 0
            self._last_fire = time.time()
            return True
        return False

    @property
    def lock_count(self) -> int:
        return self._lock_count


# ---------------------------------------------------------------------------
# Q-Learning layer (선택적, --mode rl)
# ---------------------------------------------------------------------------

class QTableAgent:
    """State: dx/dy 3구간씩 9-state. Action: 9방향 미세 보정."""

    STATES = 9       # (left/center/right) × (up/center/down)
    ACTIONS = 9      # (same grid)
    CORRECTION = 15  # 각 방향 보정 픽셀값

    def __init__(self, alpha: float = 0.2, gamma: float = 0.9, epsilon: float = 0.3,
                 qtable_path: str = "qtable.json") -> None:
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.qtable_path = qtable_path
        self.q = np.zeros((self.STATES, self.ACTIONS))
        self._episode: list = []  # (state, action) pairs this episode
        self._load()

    def _load(self) -> None:
        p = Path(self.qtable_path)
        if p.exists():
            try:
                data = json.loads(p.read_text())
                self.q = np.array(data)
                print(f"[RL] Q-table loaded from {self.qtable_path}")
            except Exception:
                pass

    def save(self) -> None:
        Path(self.qtable_path).write_text(json.dumps(self.q.tolist()))
        print(f"[RL] Q-table saved to {self.qtable_path}")

    def _bin(self, dx: int, dy: int, frame_w: int, frame_h: int) -> int:
        """dx,dy → 0~8 state index (3×3 grid)."""
        bx = 0 if dx < -frame_w // 6 else (2 if dx > frame_w // 6 else 1)
        by = 0 if dy < -frame_h // 6 else (2 if dy > frame_h // 6 else 1)
        return by * 3 + bx

    def _action_to_delta(self, action: int) -> Tuple[int, int]:
        """action(0~8) → (dpan_err, dtilt_err) 보정값."""
        row, col = divmod(action, 3)
        dpan  = (col - 1) * self.CORRECTION   # -CORR, 0, +CORR
        dtilt = (row - 1) * self.CORRECTION
        return dpan, dtilt

    def act(self, dx: int, dy: int, frame_w: int, frame_h: int) -> Tuple[int, int, int]:
        """현재 state에서 action 선택. (dpan, dtilt, state) 반환."""
        state = self._bin(dx, dy, frame_w, frame_h)
        if np.random.rand() < self.epsilon:
            action = np.random.randint(self.ACTIONS)
        else:
            action = int(np.argmax(self.q[state]))
        self._episode.append((state, action))
        dpan, dtilt = self._action_to_delta(action)
        return dpan, dtilt, state

    def record_result(self, hit: bool) -> None:
        """에피소드 완료 후 reward 역전파."""
        reward = 1.0 if hit else -1.0
        for t, (s, a) in enumerate(reversed(self._episode)):
            discounted = reward * (self.gamma ** t)
            self.q[s, a] += self.alpha * (discounted - self.q[s, a])
        self._episode.clear()
        self.save()
        print(f"[RL] Episode result: {'HIT' if hit else 'MISS'}, reward={reward:.1f}")


# ---------------------------------------------------------------------------
# Draw helpers
# ---------------------------------------------------------------------------

def draw_intercept_overlay(
    frame,
    target: Optional[Tuple[int, int, int]],
    aim_point: Optional[Tuple[int, int]],
    dx: int,
    dy: int,
    lock_count: int,
    hold_frames: int,
    last_command: str,
    fire_threshold: int,
    motion_stats: Optional[Tuple[float, float, float, float]] = None,
) -> None:
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2

    # 조준선
    cv2.line(frame, (cx - 30, cy), (cx + 30, cy), (200, 200, 200), 1)
    cv2.line(frame, (cx, cy - 30), (cx, cy + 30), (200, 200, 200), 1)
    # 발사 임계 원
    cv2.circle(frame, (cx, cy), fire_threshold, (0, 200, 0), 1)

    if target is not None:
        tx, ty, radius = target
        # 풍선 탐지 원
        cv2.circle(frame, (tx, ty), radius, (0, 140, 255), 2)
        cv2.circle(frame, (tx, ty), 4, (0, 140, 255), -1)

        if aim_point:
            ax, ay = aim_point
            cv2.circle(frame, (ax, ay), 6, (0, 255, 255), -1)
            cv2.line(frame, (cx, cy), (ax, ay), (0, 255, 255), 1)

        # 상태 표시
        lock_pct = lock_count / hold_frames
        if lock_pct >= 1.0:
            status_color = (0, 0, 255)
            status = "FIRE!"
        elif lock_pct > 0:
            status_color = (0, 255, 255)
            status = f"LOCKED {lock_count}/{hold_frames}"
        else:
            status_color = (255, 140, 0)
            status = "TRACKING"

        cv2.putText(frame, status, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)
        cv2.putText(frame, f"dx={dx} dy={dy}", (12, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (230, 230, 230), 2)
        if motion_stats is not None:
            lead_time, vx, vy, ay = motion_stats
            cv2.putText(frame, f"lead={lead_time:.2f}s vx={vx:.0f} vy={vy:.0f} ay={ay:.0f}",
                        (12, 94), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1)
    else:
        cv2.putText(frame, "NO TARGET", (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

    cv2.putText(frame, last_command[-80:], (12, h - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    cv2.putText(frame, "q=quit | m=mask | h=hit | miss=m (RL mode)",
                (12, h - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> None:
    # BLE sender
    sender = DryRunSender() if args.dry_run else PybricksBleSender(args.hub_name, args.scan_timeout)
    if hasattr(sender, "print_sends"):
        sender.print_sends = args.print_sends

    # Camera
    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera {args.camera}. Allow camera access in macOS settings.")

    # Color picker or CLI HSV
    if args.color_picker:
        hsv_lower, hsv_upper = color_picker(cap, args.width, args.height)
    else:
        hsv_lower = tuple(int(v) for v in args.hsv_lower.split(","))
        hsv_upper = tuple(int(v) for v in args.hsv_upper.split(","))

    detector  = BalloonDetector(hsv_lower, hsv_upper)  # type: ignore
    tracker   = ParabolicTracker(args.velocity_smoothing, args.accel_smoothing)
    aim_ctrl  = AimController(args.fire_threshold, args.hold_frames, args.fire_cooldown)
    ql_agent  = QTableAgent(qtable_path=args.qtable) if args.mode == "rl" else None

    await sender.connect()

    cv2.namedWindow("Balloon Intercept", cv2.WINDOW_NORMAL)
    last_send_time = 0.0
    last_command   = "ready"
    show_mask      = False
    pending_fire   = False

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Camera frame read failed.")
                break
            if args.mirror:
                frame = cv2.flip(frame, 1)

            frame_h, frame_w = frame.shape[:2]

            # 탐지
            result = detector.detect(frame)
            aim_point: Optional[Tuple[int, int]] = None
            motion_stats: Optional[Tuple[float, float, float, float]] = None
            dx, dy = 0, 0

            if result is not None:
                tx, ty, _ = result
                tracker.update(tx, ty, time.time())
                ax, ay = tracker.predict(args.flight_time, args.lead_frames, frame_w, frame_h)
                aim_point = (ax, ay)
                motion_stats = tracker.stats(args.flight_time, args.lead_frames)
                cx, cy = frame_w // 2, frame_h // 2
                dx = int(clamp(ax - cx, -100, 100))
                dy = int(clamp(ay - cy, -100, 100))
            else:
                tracker.reset()

            # 자동 발사 판단
            should_fire = aim_ctrl.update(dx, dy) if result else False
            if should_fire:
                pending_fire = True

            # Q-learning 보정 (--mode rl)
            if ql_agent and result:
                dpan, dtilt, _ = ql_agent.act(dx, dy, frame_w, frame_h)
                dx = int(clamp(dx + dpan, -100, 100))
                dy = int(clamp(dy + dtilt, -100, 100))

            # 전송
            now = time.time()
            if now - last_send_time >= args.send_interval:
                fire_byte = 1 if pending_fire else 0
                pending_fire = False
                command = f"M,{dx},{dy},{fire_byte}"
                await sender.send(command)
                last_command = command
                last_send_time = now

            if hasattr(sender, "maybe_warn_stale"):
                sender.maybe_warn_stale()

            # 화면
            if show_mask and result is not None:
                mask = detector.debug_mask(frame)
                cv2.imshow("Balloon Intercept", cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))
            else:
                draw_intercept_overlay(
                    frame, result, aim_point, dx, dy,
                    aim_ctrl.lock_count, args.hold_frames,
                    last_command, args.fire_threshold, motion_stats,
                )
                cv2.imshow("Balloon Intercept", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                await sender.send("STOP")
                break
            elif key == ord("m"):
                if ql_agent:
                    ql_agent.record_result(hit=False)
                else:
                    show_mask = not show_mask
            elif key == ord("h") and ql_agent:
                ql_agent.record_result(hit=True)

            await asyncio.sleep(0)

    finally:
        with contextlib.suppress(Exception):
            await sender.send("STOP", timeout=0.2)
        cap.release()
        cv2.destroyAllWindows()
        await sender.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hub-name",        default="Team5",        help="Pybricks Hub BLE 이름")
    p.add_argument("--scan-timeout",    type=float, default=15.0)
    p.add_argument("--dry-run",         action="store_true",    help="BLE 없이 명령만 출력")
    p.add_argument("--print-sends",     action="store_true",    help="전송 패킷 출력")
    p.add_argument("--camera",          type=int, default=0)
    p.add_argument("--width",           type=int, default=640)
    p.add_argument("--height",          type=int, default=480)
    p.add_argument("--mirror",          action="store_true", default=True)
    p.add_argument("--no-mirror",       action="store_false", dest="mirror")
    # 색상 설정
    p.add_argument("--color-picker",    action="store_true",    help="시작 시 클릭으로 풍선 색 선택")
    p.add_argument("--hsv-lower",       default="25,80,80",     help="HSV 하한 'H,S,V' (노란색 기본)")
    p.add_argument("--hsv-upper",       default="45,255,255",   help="HSV 상한 'H,S,V'")
    # 발사 제어
    p.add_argument("--fire-threshold",  type=int,   default=30, help="자동 발사 허용 픽셀 오차")
    p.add_argument("--hold-frames",     type=int,   default=3,  help="연속 조준 확인 프레임 수")
    p.add_argument("--fire-cooldown",   type=float, default=3.0,help="발사 후 재발사 금지 시간(초)")
    p.add_argument("--flight-time",     type=float, default=0.40, help="투사체 도달 예상 시간(초)")
    p.add_argument("--lead-frames",     type=int,   default=0,  help="flight-time에 추가할 프레임 기반 리드 보정")
    p.add_argument("--velocity-smoothing", type=float, default=0.30, help="속도 EMA 계수(0~1)")
    p.add_argument("--accel-smoothing", type=float, default=0.05, help="수직 가속도 EMA 계수(0~1)")
    # 전송 타이밍
    p.add_argument("--send-interval",   type=float, default=0.10)
    # AI 모드
    p.add_argument("--mode",            choices=["tracking", "rl"], default="tracking",
                   help="tracking=비례제어, rl=Q-learning")
    p.add_argument("--qtable",          default="qtable.json",  help="Q-table 저장 경로")
    return p


def main() -> None:
    args = build_parser().parse_args()
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
