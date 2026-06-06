#!/usr/bin/env python3
"""Camera-based balloon interception controller for LEGO SPIKE Prime (Windows Threaded Version).

This version is specifically adapted to run the asyncio Bleak loop in a background thread 
while keeping the OpenCV GUI in the main thread to prevent COM threading conflicts on Windows.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import math
import re
import time
import threading
import queue
from pathlib import Path

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    raise SystemExit("Missing package. Install with: python -m pip install opencv-python numpy bleak") from exc

from fire_mode_control import describe_burst_decision, read_control_mode
from pybricks_ble import DEFAULT_HUB_NAME, DryRunSender, PybricksBleSender, clamp


PAN_MAX_DEG = 35
TILT_MIN_DEG = 0
TILT_MAX_DEG = 120.0

FLIGHT_TIME = 0.4
SMOOTHING = 0.6
ACCEL_SMOOTHING = 0.3
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
    pan_deg = (px - frame_w / 2) / (frame_w / 2) * PAN_MAX_DEG * 1.1
    pan_deg = max(-PAN_MAX_DEG, min(PAN_MAX_DEG, pan_deg))
    pan_val = int(pan_deg / PAN_MAX_DEG * 100)

    tilt_frac = 1.0 - py / frame_h
    # 위로 올라갈수록(tilt_frac이 1.0에 가까워질수록) 비율을 점진적으로 가중 보정 (1.25승 적용)
    tilt_frac_warped = tilt_frac ** 1.25
    tilt_deg = TILT_MIN_DEG + tilt_frac_warped * (TILT_MAX_DEG - TILT_MIN_DEG)
    tilt_deg = max(TILT_MIN_DEG, min(TILT_MAX_DEG, tilt_deg))
    tilt_val = int((tilt_deg - TILT_MIN_DEG) / (TILT_MAX_DEG - TILT_MIN_DEG) * 200 - 100)

    return pan_val, tilt_val


def red_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 빨간색 검출 조건을 더 빡빡하게 제한 (채도 최저 110, 명도 최저 65)
    mask1 = cv2.inRange(hsv, np.array([0, 110, 65]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([170, 110, 65]), np.array([180, 255, 255]))
    mask = mask1 + mask2

    # 모폴로지 연산으로 조각난 마스크 구멍들을 메우고, 테두리 노이즈 제거 (5x5 둥근 커널 사용)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


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
            # Check if connection was lost or program state changed
            # Map the recovery generation for the main loop to read if needed
            nonlocal_recovery_gen = sender.recovery_generation
            
            try:
                # 큐에 쌓인 이전 명령어들을 모두 비우고 가장 최신 명령만 가져옵니다.
                # (단, M,...1 처럼 fire=1 신호가 큐 중간에 있었거나, STOP 명령이 들어오면 유실을 방지합니다)
                cmd = cmd_queue.get(timeout=0.05)
                while not cmd_queue.empty():
                    next_cmd = cmd_queue.get_nowait()
                    if next_cmd == "STOP" or cmd == "STOP":
                        cmd = "STOP"
                    else:
                        if "M," in cmd and "M," in next_cmd:
                            parts_cmd = cmd.split(",")
                            parts_next = next_cmd.split(",")
                            # 이전이나 현재 명령어 중 하나라도 발사 신호(1)가 있으면 강제로 유지
                            fire_status = "1" if (parts_cmd[3] == "1" or parts_next[3] == "1") else "0"
                            cmd = f"M,{parts_next[1]},{parts_next[2]},{fire_status}"
                        else:
                            cmd = next_cmd
                
                # Check for STOP program
                if cmd == "STOP":
                    await sender.send(f"M,{args.home_pan},{args.home_tilt},0", timeout=0.5)
                    break
                
                # If we have a pending fire cmd but the hub program is stopped, drop the fire
                if ",1" in cmd and getattr(sender, "_program_running", None) is False:
                    # Strip fire
                    parts = cmd.split(",")
                    cmd = f"M,{parts[1]},{parts[2]},0"

                # Send command
                sent = await sender.send(cmd, timeout=args.send_timeout)
                
                # If this was a fire command and it was successfully sent
                if ",1" in cmd and sent and logger is not None:
                    # This tells the main thread we successfully fired, 
                    # but since the logger context is filled in the main thread, 
                    # we will handle dataset logging matching inside line_handler (on_hub_line).
                    pass
                    
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

    # 스레드 전용 비동기 루프 실행
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
    
    # 백그라운드 블루투스 통신 스레드 시작
    ble_thread = threading.Thread(
        target=ble_worker, 
        args=(args, cmd_queue, stop_event, logger, ready_event), 
        daemon=True
    )
    ble_thread.start()

    print("[Main] Waiting for BLE Thread to connect and ready...")
    # Wait for ready_event or stop_event
    while not ready_event.is_set() and not stop_event.is_set():
        time.sleep(0.1)
        
    if stop_event.is_set():
        print("[Main] BLE Thread failed to initialize. Exiting.")
        return

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        stop_event.set()
        raise SystemExit(
            f"Could not open camera index {args.camera}. On macOS, allow camera access."
        )

    frame_w = args.width
    frame_h = args.height
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_h)
    center_x = frame_w // 2
    center_y = frame_h // 2

    cv2.namedWindow("Balloon Intercept (Win)", cv2.WINDOW_NORMAL)

    prev_x = None
    prev_y = None
    prev_X, prev_Y, prev_Z = None, None, None
    prev_time = time.time()
    vx_smooth = 0.0
    vy_smooth = 0.0
    vz_smooth = 0.0
    prev_vy = 0.0
    ay_smooth = 0.0
    last_send_time = 0.0
    last_home_send_time = 0.0
    last_aim_command: str | None = None
    fire_state = TRACKING
    fire_confirm_count = 0
    target_lost_since: float | None = None
    fire_pending = False
    pending_fire_context: dict | None = None
    target_first_seen_time: float | None = None
    control_mode_path = Path(args.control_mode_file)
    current_fire_mode = args.default_fire_mode
    last_mode_read_time = 0.0
    last_burst_fire_time = 0.0
    last_burst_debug_time = 0.0
    last_burst_debug_reason = ""

    print("=====================================================")
    print(" 🚀 Windows Multi-Thread Interceptor Started")
    print(f" 🔊 Fire mode default={current_fire_mode} control_file={control_mode_path}")
    print("=====================================================")

    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                print("Camera frame read failed.")
                break
            if args.mirror:
                frame = cv2.flip(frame, 1)

            # 풍선 바운딩 박스 크기로부터 3D 거리(Z) 및 X, Y 물리 좌표 추정
            # balloon_tracker_offline.py의 3D 캘리브레이션 물리 상수들을 그대로 차용
            OBJECT_SIZE_CM = 20.0
            FOCAL_LENGTH = 550.0
            DRAG_K = 1.5         # 공기저항 계수
            GRAVITY_CM_S2 = 250.0 # 부력 상쇄 유효 중력가속도 (cm/s^2)

            contours, _ = cv2.findContours(red_mask(frame), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            target_x = None
            target_y = None
            X_cm, Y_cm, Z_cm = None, None, None
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
                    
                    # 3D Depth (Z) 추정
                    pixel_size = max(w, h)
                    Z_cm = (OBJECT_SIZE_CM * FOCAL_LENGTH) / pixel_size if pixel_size > 0 else 300.0
                    # 3D X, Y 물리적 위치 (cm) 변환 (y좌표는 이미지 상하 반전 고려하여 마이너스)
                    X_cm = ((target_x - center_x) * Z_cm) / FOCAL_LENGTH
                    Y_cm = -((target_y - center_y) * Z_cm) / FOCAL_LENGTH

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

                if target_first_seen_time is None:
                    target_first_seen_time = current_time

                # 3D 속도 미분 및 필터링
                if prev_X is not None and dt > 0:
                    vx_raw = (X_cm - prev_X) / dt
                    vy_raw = (Y_cm - prev_Y) / dt
                    vz_raw = (Z_cm - prev_Z) / dt
                    vx_smooth = SMOOTHING * vx_raw + (1 - SMOOTHING) * vx_smooth
                    vy_smooth = SMOOTHING * vy_raw + (1 - SMOOTHING) * vy_smooth
                    vz_smooth = SMOOTHING * vz_raw + (1 - SMOOTHING) * vz_smooth

                # 풍선 거리 Z_cm에 따른 동적 비행시간 매핑 (탄속을 약 600cm/s로 추정)
                # 거리가 멀어질수록 비행시간이 늘어나며, 최소 0.15초 ~ 최대 0.8초 한계 제한
                current_flight_time = (Z_cm / 600.0) + 0.1
                current_flight_time = max(0.15, min(0.8, current_flight_time))

                # 3D 물리 공간상에서 공기저항 및 중력이 결합된 다단 시뮬레이션
                sim_X, sim_Y, sim_Z = X_cm, Y_cm, Z_cm
                sim_vx, sim_vy, sim_vz = vx_smooth, vy_smooth, vz_smooth

                sim_steps = 10
                sim_dt = current_flight_time / sim_steps

                for _ in range(sim_steps):
                    # 공기 저항력 (a = -k * v)
                    ax = -DRAG_K * sim_vx
                    # 부력이 반영된 중력가속도 + Y축 공기 저항력
                    ay = -DRAG_K * sim_vy - GRAVITY_CM_S2
                    az = -DRAG_K * sim_vz
                    
                    # 3D 위치 및 속도 전진 오일러 갱신
                    sim_X += sim_vx * sim_dt
                    sim_Y += sim_vy * sim_dt
                    sim_Z += sim_vz * sim_dt
                    sim_vx += ax * sim_dt
                    sim_vy += ay * sim_dt
                    sim_vz += az * sim_dt

                # 예측된 3D 궤적 지점을 다시 2D 픽셀 좌표계로 역투사 (Projection)
                if sim_Z > 0:
                    predict_x = int((sim_X * FOCAL_LENGTH) / sim_Z + center_x)
                    predict_y = int((-sim_Y * FOCAL_LENGTH) / sim_Z + center_y)
                else:
                    predict_x, predict_y = target_x, target_y

                predict_x = max(0, min(frame_w, predict_x))
                predict_y = max(0, min(frame_h, predict_y))

                cv2.line(frame, (target_x, target_y), (predict_x, predict_y), (0, 255, 255), 2)
                cv2.circle(frame, (predict_x, predict_y), 10, (0, 0, 255), 2)
                cv2.putText(frame, f"Depth: {int(Z_cm)}cm  EstT: {current_flight_time:.2f}s  VY:{int(vy_smooth)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                pan_val, tilt_val = pixel_to_motor_vals(predict_x, predict_y, frame_w, frame_h)
                last_aim_command = f"M,{pan_val},{tilt_val},0"

                # Fire policy is selected by the voice-control JSON file. The Hub
                # protocol stays M,pan,tilt,fire; modes only change when fire=1 is sent.
                detected_duration = current_time - target_first_seen_time
                if current_fire_mode == "safe":
                    fire_confirm_count = 0
                    fire_pending = False
                    pending_fire_context = None
                    fire_state = TRACKING
                    cv2.putText(frame, "SAFE: FIRE DISABLED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                elif current_fire_mode == "burst":
                    fire_confirm_count = 0
                    burst_fire_px = args.burst_fire_px if args.burst_fire_px is not None else args.fire_px
                    in_burst_fire_window = abs(predict_x - center_x) < burst_fire_px and abs(predict_y - center_y) < burst_fire_px
                    burst_decision = describe_burst_decision(
                        current_time=current_time,
                        last_burst_fire_time=last_burst_fire_time,
                        burst_interval=args.burst_interval,
                        in_fire_window=in_burst_fire_window,
                        no_fire=args.no_fire,
                        hub_program_running=None,
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
                            f"state={fire_state} no_fire={args.no_fire}"
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
                            if logger is not None:
                                logger.mark_fire(pending_fire_context)
                            last_burst_fire_time = current_time
                            cv2.putText(frame, "BURST FIRE", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                        else:
                            cv2.putText(frame, "BURST LOCK", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 3)
                    else:
                        fire_state = TRACKING
                else:
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
                            # 화면에 남은 시간 피드백 표시
                            cv2.putText(frame, f"LOCKING: {0.4 - detected_duration:.2f}s", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
                    elif fire_state == FIRED_FOR_TARGET or fire_state == REARM_WAIT:
                        # 한번 쏘았으면 풍선을 계속 인식하고 있는 동안(세션이 끊기지 않는 동안) 추가 격발 방지
                        cv2.putText(frame, "FIRED", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)

                prev_x = target_x
                prev_y = target_y
                prev_X, prev_Y, prev_Z = X_cm, Y_cm, Z_cm
            else:
                target_first_seen_time = None  # 풍선을 완전히 놓치면 세션 종료 및 시간 초기화
                prev_x = None
                prev_y = None
                prev_X, prev_Y, prev_Z = None, None, None
                vx_smooth, vy_smooth, vz_smooth = 0.0, 0.0, 0.0
                fire_confirm_count = 0
                fire_pending = False
                pending_fire_context = None
                if fire_state == FIRED_FOR_TARGET:
                    # 발사 완료 후 대기 상태로 전환
                    fire_state = REARM_WAIT
                    target_lost_since = current_time
                elif fire_state == REARM_WAIT and target_lost_since is not None:
                    # 표적이 사라진 상태가 일정 시간(args.target_lost_rearm) 지속되면 재준비 완료(TRACKING)
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

            cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (255, 255, 255), 2)
            cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (255, 255, 255), 2)
            cv2.putText(frame, f"MODE: {current_fire_mode.upper()}", (10, frame_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # Send command queue update
            if fire_pending or current_time - last_send_time >= args.send_interval:
                command_fire = 1 if fire_pending else fire_trigger
                command = f"M,{pan_val},{tilt_val},{command_fire}"
                
                if target_x is None and current_time - last_home_send_time < args.home_send_interval:
                    cv2.imshow("Balloon Intercept (Win)", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        cmd_queue.put("STOP")
                        stop_event.set()
                        break
                    continue

                cmd_queue.put(command)
                if args.fire_debug and command_fire == 1:
                    print(f"[FIRE-DEBUG] queued_fire_command={command}")
                last_send_time = current_time
                if target_x is None:
                    last_home_send_time = current_time
                if command_fire == 1:
                    # fire request queued, clear local pending flag
                    fire_pending = False

            cv2.imshow("Balloon Intercept (Win)", frame)
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
    parser.add_argument("--mirror", action="store_true", default=True, help="Mirror the camera image.")
    parser.add_argument("--no-mirror", action="store_false", dest="mirror", help="Do not mirror the camera image.")
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_camera(args)


if __name__ == "__main__":
    main()
