import asyncio
import cv2
import numpy as np
import time
import contextlib
from bleak import BleakClient, BleakScanner

# ==========================================
# 1. Pybricks BLE 통신 설정 (수정 불필요)
# ==========================================
PYBRICKS_COMMAND_EVENT_CHAR_UUID = "c5f50002-8280-46da-89f4-6d8051e4aeef"
HUB_NAME = "Team5"

# --- 모터 범위 (hub_pybricks_gesture_server.py 상수와 반드시 일치) ---
PAN_MAX_DEG  = 35   # pan 범위: [-35°, +35°]  (Port F)
TILT_MIN_DEG =  0   # tilt 최소 각도 (Port D)
TILT_MAX_DEG = 80   # tilt 최대 각도 (Port D)

# --- 포물선 예측 및 발사 튜닝 ---
FLIGHT_TIME      = 0.4   # 고무줄 체공 시간 (초) — 멀수록 크게
SMOOTHING        = 0.3   # 속도 EMA 가중치 (클수록 빠르고 노이즈 많음)
ACCEL_SMOOTHING  = 0.05  # 가속도 EMA 가중치 (노이즈 억제용, 낮게 유지)
FIRE_PX          = 20    # 예측 지점이 화면 중심에서 이 픽셀 이내이면 발사
SEND_INTERVAL    = 0.1   # BLE 전송 최소 간격 (초)

class PybricksBleSender:
    def __init__(self, hub_name):
        self.hub_name = hub_name
        self.client = None
        self.ready = asyncio.Event()
        self.connected = False

    async def connect(self):
        print(f"[{self.hub_name}] BLE 로봇 찾는 중...")
        device = await BleakScanner.find_device_by_name(self.hub_name, timeout=10.0)
        if not device:
            raise RuntimeError("로봇을 찾을 수 없습니다. 전원과 Pybricks 코드를 확인하세요.")

        self.client = BleakClient(device, disconnected_callback=self._handle_disconnect)
        await self.client.connect()
        await self.client.start_notify(PYBRICKS_COMMAND_EVENT_CHAR_UUID, self._handle_rx)
        self.connected = True
        print("✅ BLE 연결 완료! 로봇의 버튼을 눌러 프로그램을 시작하세요.")

    def _handle_disconnect(self, _):
        self.connected = False
        print("🚨 로봇 연결 끊김!")

    def _handle_rx(self, _, data: bytearray):
        if data and data[0] == 0x01:
            payload = bytes(data[1:])
            if b"rdy" in payload:
                self.ready.set()

    @staticmethod
    def _i8(value):
        return max(-100, min(100, int(value))) & 0xFF

    async def send(self, pan_err, tilt_err, fire):
        if not self.client or not self.connected: return
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=1.0)
            self.ready.clear()
            packet = bytes([ord("M"), self._i8(pan_err), self._i8(tilt_err), int(fire) & 0xFF])
            await self.client.write_gatt_char(PYBRICKS_COMMAND_EVENT_CHAR_UUID, b"\x06" + packet, response=True)
        except asyncio.TimeoutError:
            pass

    async def close(self):
        if self.client:
            await self.client.disconnect()


def pixel_to_motor_vals(px, py, frame_w, frame_h):
    """고정 카메라 픽셀 좌표 → 절대 모터 각도 명령값 [-100, +100] 변환.

    웹캠이 포탑에 달리지 않고 독립적으로 고정되어 있으므로,
    픽셀 위치를 모터 각도로 직접 1:1 매핑한다.

    pan  (Port F): px=0 → -PAN_MAX_DEG, px=frame_w → +PAN_MAX_DEG
    tilt (Port D): py=0(상단) → TILT_MAX_DEG(위), py=frame_h(하단) → TILT_MIN_DEG(아래)
    """
    # pan: 화면 좌우 전체 → [-PAN_MAX_DEG, +PAN_MAX_DEG]
    pan_deg = (px - frame_w / 2) / (frame_w / 2) * PAN_MAX_DEG
    pan_deg = max(-PAN_MAX_DEG, min(PAN_MAX_DEG, pan_deg))
    pan_val = int(pan_deg / PAN_MAX_DEG * 100)   # [-100, +100]

    # tilt: 화면 상하 전체 → [TILT_MAX_DEG, TILT_MIN_DEG] (위로 갈수록 각도 큼)
    tilt_frac = 1.0 - py / frame_h               # 1.0=상단, 0.0=하단
    tilt_deg  = TILT_MIN_DEG + tilt_frac * (TILT_MAX_DEG - TILT_MIN_DEG)
    tilt_deg  = max(TILT_MIN_DEG, min(TILT_MAX_DEG, tilt_deg))
    # [TILT_MIN_DEG, TILT_MAX_DEG] → [-100, +100]
    tilt_val  = int((tilt_deg - TILT_MIN_DEG) / (TILT_MAX_DEG - TILT_MIN_DEG) * 200 - 100)

    return pan_val, tilt_val


# ==========================================
# 2. 메인 포물선 예측 사격 비전 루프
# ==========================================
async def run_shooter():
    sender = PybricksBleSender(HUB_NAME)
    await sender.connect()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("🚨 카메라를 열 수 없습니다.")
        return

    FRAME_W, FRAME_H = 640, 480
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    CENTER_X, CENTER_Y = FRAME_W // 2, FRAME_H // 2

    # 상태 추적 변수 초기화
    prev_x, prev_y = None, None
    prev_time = time.time()
    vx_smooth, vy_smooth = 0.0, 0.0
    prev_vy = 0.0
    ay_smooth = 0.0
    last_send_time = 0

    print("🎯 포물선 요격 시스템 가동! 표적을 위로 던져보세요.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret: break
            frame = cv2.flip(frame, 1)
            
            # 빨간색 추출
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask1 = cv2.inRange(hsv, np.array([0, 120, 70]), np.array([10, 255, 255]))
            mask2 = cv2.inRange(hsv, np.array([170, 120, 70]), np.array([180, 255, 255]))
            mask = mask1 + mask2
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            target_x, target_y = None, None
            fire_trigger = 0

            if contours:
                c = max(contours, key=cv2.contourArea)
                if cv2.contourArea(c) > 500:
                    x, y, w, h = cv2.boundingRect(c)
                    target_x, target_y = x + w // 2, y + h // 2
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.circle(frame, (target_x, target_y), 5, (0, 255, 0), -1)

            current_time = time.time()
            dt = current_time - prev_time

            if target_x is not None and target_y is not None:
                if prev_x is not None and dt > 0:
                    # 1. 속도 연산 (1차 예측)
                    vx_raw = (target_x - prev_x) / dt
                    vy_raw = (target_y - prev_y) / dt
                    
                    vx_smooth = (SMOOTHING * vx_raw) + ((1 - SMOOTHING) * vx_smooth)
                    vy_smooth = (SMOOTHING * vy_raw) + ((1 - SMOOTHING) * vy_smooth)
                    
                    # 2. 가속도 연산 (2차 예측: 중력 포물선 궤적)
                    ay_raw = (vy_smooth - prev_vy) / dt
                    ay_smooth = (ACCEL_SMOOTHING * ay_raw) + ((1 - ACCEL_SMOOTHING) * ay_smooth)
                
                # 3. 미래 위치(조준점) 계산 (X축은 등속, Y축은 등가속도)
                predict_x = int(target_x + (vx_smooth * FLIGHT_TIME))
                predict_y = int(target_y + (vy_smooth * FLIGHT_TIME) + (0.5 * ay_smooth * (FLIGHT_TIME ** 2)))
                
                predict_x = max(0, min(FRAME_W, predict_x))
                predict_y = max(0, min(FRAME_H, predict_y))

                # 시각화 (현재 타겟과 예측 지점 연결)
                cv2.line(frame, (target_x, target_y), (predict_x, predict_y), (0, 255, 255), 2)
                cv2.circle(frame, (predict_x, predict_y), 10, (0, 0, 255), 2)
                
                # 디버깅: 속도와 가속도 표시
                cv2.putText(frame, f"VY: {int(vy_smooth)} AY: {int(ay_smooth)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.putText(frame, "PARABOLIC PREDICT", (predict_x - 40, predict_y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

                # 4. 절대 모터 각도 계산 (고정 카메라 → 독립 모터 직접 변환)
                pan_val, tilt_val = pixel_to_motor_vals(predict_x, predict_y, FRAME_W, FRAME_H)

                # 발사 조건: 예측 지점이 화면 중심 FIRE_PX 이내
                # (pan ≈ 0°, tilt ≈ 중간값 → 정면 기준 발사)
                if abs(predict_x - CENTER_X) < FIRE_PX and abs(predict_y - CENTER_Y) < FIRE_PX:
                    fire_trigger = 1
                    cv2.putText(frame, "FIRE!!!", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

                # 다음 프레임 계산을 위한 값 저장
                prev_x, prev_y = target_x, target_y
                prev_vy = vy_smooth
            else:
                # 표적 없음: pan=0°, tilt=중간값(40°)으로 복귀
                pan_val, tilt_val = 0, 0
                prev_x, prev_y = None, None
                vx_smooth, vy_smooth = 0.0, 0.0
                prev_vy = 0.0
                ay_smooth = 0.0

            prev_time = current_time

            cv2.line(frame, (CENTER_X - 20, CENTER_Y), (CENTER_X + 20, CENTER_Y), (255, 255, 255), 2)
            cv2.line(frame, (CENTER_X, CENTER_Y - 20), (CENTER_X, CENTER_Y + 20), (255, 255, 255), 2)

            if current_time - last_send_time >= SEND_INTERVAL:
                await sender.send(pan_val, tilt_val, fire_trigger)
                last_send_time = current_time

            cv2.imshow("Aimbot System (Parabolic Prediction)", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        await sender.send(0, 0, 0)
        cap.release()
        cv2.destroyAllWindows()
        await sender.close()

if __name__ == "__main__":
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(run_shooter())