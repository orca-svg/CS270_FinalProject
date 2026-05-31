[English README](README.md)

# CS270 기말 프로젝트 — LEGO SPIKE 제스처 제어 발사기

LEGO SPIKE Prime 팬-틸트 발사기를 위한 실시간 손 제스처 BLE 제어 시스템.
MediaPipe 손 추적을 실행하는 Mac이 BLE를 통해 모터 명령을 Hub로 전송하면, Hub는 목표 각도를 누적하여 추적하고 주먹 제스처에 발사한다.

## 저장소 구조

```text
gesture_bt/
  gesture_bt_controller.py       # Mac 측: MediaPipe 손 감지 + BLE 송신기
  hub_pybricks_gesture_server.py # Hub 측: Pybricks BLE 서버 + 모터 상태 머신
  bt_manual_motor_test.py        # 수동 BLE 모터 테스트 (카메라 없음)
  requirements_gesture_bt.txt    # Mac 측 Python 의존성
  models/
    hand_landmarker.task         # MediaPipe 손 랜드마크 모델

Final_project/
  calibration_targeting.py       # 캘리브레이션 기반 조준 프로토타입
  q_learning_aim_trainer.py      # Q-learning 조준 프로토타입
  rl_hub_runner.py               # SPIKE Hub 명령 실행기
  hand_follow_controller.py      # 손 추종 프로토타입
  OpenCV.py                      # OpenCV 실험
  ShootingCode.py                # 발사기 발사 실험
  CALIBRATION_IMPLEMENTATION_PLAN.md
  README_Q_LEARNING.md
  HAND_FOLLOW_TEST.md

docs/                            # 프로젝트 문서용 예약 디렉토리
```

## 하드웨어

포트 할당은 `gesture_bt/hub_pybricks_gesture_server.py`의 `safe_motor(Port.X, ...)`
호출에서 직접 가져온 것이다.

| Port | Motor | 역할 |
|------|-------|------|
| A | `launch_l` | 왼쪽 발사 휠 (PWM +100) |
| B | `launch_r` | 오른쪽 발사 휠 (PWM −100, 반대 방향) |
| C | `c_motor` | 발사/장전 메커니즘 (왕복 운동) |
| D | `tilt_motor` | 틸트 축 |
| F | `pan_motor` | 팬 축 |

모터가 누락되어도 허용된다: 각 포트는 `safe_motor`로 탐지되며, 이는
`PORT_<label>_OK` 또는 `PORT_<label>_MISSING`을 로깅하고 실패 시 `None`을 반환한다.

## 설정

### 1. Hub (Pybricks)

`gesture_bt/hub_pybricks_gesture_server.py`를 [Pybricks Code](https://code.pybricks.com)를 통해 업로드한다.
실행 전 로봇을 영점/장전 상태에 위치시킨다: 팬, 틸트, C 모터 모두 시작 시
`reset_angle(0)`을 호출하므로, 실행 시점의 물리적 자세가 0° 기준점이 된다
(팬/틸트 중앙, C 모터 장전 상태). Hub 중앙 버튼을 눌러 시작한다.

### 2. Mac

```bash
cd gesture_bt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

의존성 (`requirements_gesture_bt.txt`):

```text
opencv-python
mediapipe>=0.10.30
numpy
bleak
```

`gesture_bt/models/hand_landmarker.task`가 아직 존재하지 않으면 MediaPipe Hand
Landmarker 모델이 최초 실행 시 자동으로 다운로드된다.

### 3. 수동 BLE 테스트 (카메라 없음)

```bash
python bt_manual_motor_test.py --hub-name "Team5"
```

BLE가 연결되면 Hub 중앙 버튼을 누르고 `[Hub] READY`를 기다린다. 이 스크립트는
고정된 팬/틸트 목표 푸시 시퀀스와 한 번의 발사를 실행하여, 카메라를 사용하기
전에 모터 배선을 확인한다. 기본 `--hub-name`은 `Team5`이다.

### 4. 제스처 제어

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

자주 사용하는 커맨드라인 옵션 (`build_parser` 기준):

| Option | Default | 설명 |
|--------|---------|-------------|
| `--hub-name` | `Pybricks Hub` | 스캔할 Pybricks BLE 허브 이름 |
| `--dry-run` | off | BLE 생략; 명령만 출력 |
| `--print-sends` | off | Hub로 전송되는 모든 명령/패킷 출력 |
| `--scan-timeout` | 15.0 | BLE 스캔 타임아웃 (초) |
| `--camera` | 0 | OpenCV 카메라 인덱스 |
| `--picamera2` | off | OpenCV 대신 Raspberry Pi Picamera2 사용 |
| `--width` / `--height` | 640 / 480 | 캡처 해상도 |
| `--mirror` / `--no-mirror` | mirror on | 프리뷰/프레임의 수평 반전 |
| `--deadzone-px` | 28 | 중앙 데드존 (픽셀) |
| `--gain` | 1.0 | 속도 게인 배수 |
| `--max-pan-speed` | 70 | 팬 속도 제한 |
| `--max-tilt-speed` | 80 | 틸트 속도 제한 |
| `--send-interval` | 0.10 | BLE 전송 간 최소 간격 (초) |
| `--no-hand-stop-delay` | 0.25 | 손이 없을 때 정지 전송까지의 시간 (초) |
| `--min-detection-confidence` | 0.65 | MediaPipe 감지 임계값 |
| `--min-presence-confidence` | 0.65 | MediaPipe 존재 임계값 |
| `--min-tracking-confidence` | 0.65 | MediaPipe 추적 임계값 |
| `--model-path` | `models/hand_landmarker.task` | 로컬 모델 파일 경로 |
| `--model-url` | MediaPipe float16 모델 URL | 모델이 없을 때 다운로드 소스 |

| Gesture / Key | 동작 |
|---------------|--------|
| Open palm | 팬/틸트 추적: 프레임 중앙으로부터의 손바닥 오프셋 → pan_err/tilt_err |
| Closed fist (open→fist transition) | 한 번 발사 (엣지 감지, 다음 전송까지 래치) |
| `q` | 종료 후 STOP 전송 |

## BLE 프로토콜

Mac → Hub: 4바이트 고정 패킷으로, 선행 `0x06` Pybricks 접두사와 함께 Pybricks
명령 characteristic(`c5f50002-8280-46da-89f4-6d8051e4aeef`)에 기록된다.
패킷 레이아웃은 `PybricksBleSender._packet_for`로 구성되며 Hub의 메인 루프에서
파싱된다.

| Byte | Field | 설명 |
|------|-------|-------------|
| 0 | Opcode | `M` (`0x4D`) = 모터 명령, `S` (`0x53`) = 정지 및 종료 |
| 1 | pan_err | `value & 0xFF`로 전송되는 int8, [−100, +100]으로 클램프 |
| 2 | tilt_err | `value & 0xFF`로 전송되는 int8, [−100, +100]으로 클램프 |
| 3 | fire | 0 또는 1 (1은 Hub에서 발사를 래치) |

`S` opcode는 `b"S\x00\x00\x00"`로 전송되며 모든 모터를 정지하고 Hub 루프를 종료한다.

Hub → Mac: Hub는 시작 시 한 번, 그리고 4바이트 패킷을 수신할 때마다 `b"rdy"`로
응답한다. Mac은 다음 패킷을 보내기 전에 이 `rdy`(`asyncio.Event`)를 기다리며,
이는 단순한 in-flight 1개 방식의 흐름 제어를 제공한다. `READY`, `ARMED`,
`FIRING`, `RETURNING`, `FIRED` 같은 상태 라인은 줄바꿈으로 종료되는 텍스트로
전송되며 `[Hub] ...` 형식으로 출력된다.

## 아키텍처 노트

`hub_pybricks_gesture_server.py`와 `gesture_bt_controller.py`에서 직접 도출되었다.

**목표 누적 추적 (Hub)**: 각 `M` 패킷은 원시 속도를 명령하는 대신 내부 목표
각도를 조금씩 움직인다:

```
pan_target  = clamp(pan_target  − PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target − TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

이후 Hub는 매 루프 반복마다(~5 ms 대기) `pan_motor.track_target(int(pan_target))` /
`tilt_motor.track_target(int(tilt_target))`를 호출한다.

**C 모터 발사 상태 머신 (왕복 운동)**:

```
armed → firing (dc +C_FIRE_DC to C_FIRE_ANGLE°) → returning (dc −C_RETURN_DC to 0°) → armed
```

`armed`는 `can_fire`를 기다린다; `firing`은 각도가
`C_FIRE_ANGLE − C_TOLERANCE`에 도달할 때까지 전진한다; `returning`은 각도가
0°의 `C_TOLERANCE` 이내가 될 때까지 역전하며, 이 시점에 발사가 `FIRED`로
보고되고 래치가 해제된다.

**발사 래치**: Mac에서 `fire=1`은 open→fist 전이(`pending_fire`)에서 엣지
감지되어 다음 전송 간격까지 유지되므로, 프레임 타이밍과 무관하게 제스처당
정확히 한 번만 주먹이 전송된다.

**안전 타임아웃**: `COMMAND_TIMEOUT_MS` 이내에 패킷이 도착하지 않으면 Hub는
`pan_target`과 `tilt_target`을 0으로 재설정한다(재중앙 정렬).

**비상 정지**: Hub 버튼을 누르면 루프가 종료된다; Mac은 `q` 입력 또는 종료 시
STOP을 전송한다.

**BLE 교착 복구**: Hub는 패킷이 도착하지 않을 때에도 `RDY_INTERVAL_MS`(200 ms)
마다 주기적인 `rdy` 하트비트를 전송하므로, `rdy` 하나가 누락되어도 Mac의
`asyncio.Event` 대기가 영구적으로 멈추지 않는다.

**크래시 복원력**: Hub 루프 내의 모터 동작은 블록별 `try/except`로 감싸여 있으며,
`main()`은 항상 `stop_all()`을 실행하고 디스플레이에 `X`를 표시하는 최상위
`try/except BaseException`으로 감싸여 있다.

## 모션 상수 (Hub)

`gesture_bt/hub_pybricks_gesture_server.py`의 상수 블록에서 그대로 인용한 값이다.

| Constant | Value | 설명 |
|----------|-------|-------------|
| `PAN_SIGN` | 1 | 팬이 반대로 움직이면 −1로 변경 |
| `TILT_SIGN` | 1 | 틸트가 반대로 움직이면 −1로 변경 |
| `PAN_MIN` / `PAN_MAX` | −35 / 35° | 팬 목표 이동 한계 |
| `TILT_MIN` / `TILT_MAX` | 0 / 80° | 틸트 목표 이동 한계 |
| `PAN_SPEED` | 600 deg/s | 팬 추적 속도 |
| `TILT_SPEED` | 500 deg/s | 틸트 추적 속도 |
| `GAIN` | 0.05 | 패킷당 오차 단위별 목표 변화 각도 |
| `COMMAND_TIMEOUT_MS` | 1000 ms | 명령 미수신 시 팬/틸트 재중앙 정렬 |
| `C_FIRE_ANGLE` | 170° | C 모터 발사(릴리스) 위치 |
| `C_FIRE_DC` | 80 | 전진(발사) 듀티 사이클 % |
| `C_RETURN_DC` | 50 | 역전(장전) 듀티 사이클 % |
| `C_TOLERANCE` | 3° | 상태 전이를 위한 각도 허용 오차 |
| `LAUNCH_PWM_A` | 100 | Port A 발사 휠 PWM |
| `LAUNCH_PWM_B` | −100 | Port B 발사 휠 PWM (반대 방향) |
