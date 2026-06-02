[English README](README.md)

# CS270 기말 프로젝트 — LEGO SPIKE 자동 조준 발사기

LEGO SPIKE Prime 팬-틸트 발사기를 위한 실시간 컴퓨터 비전 자동 조준 시스템.
**고정 웹캠**을 가진 Mac이 빨간 물체를 감지하고, 포물선 궤적을 예측하여, 예측된
화면 위치를 **절대 팬/틸트 모터 각도**로 변환하고, 표적이 정렬되면 자동으로
발사한다 — 모두 BLE를 통해 Pybricks Hub와 통신한다.

> **설계 노트 — 카메라와 모터는 독립적이다.** 웹캠은 포탑과 분리되어 고정되어
> 있으며 팬/틸트 모터와 **함께 움직이지 않는다.** 따라서 컨트롤러는 각 픽셀
> 위치를 (증분 보정이 아닌) *절대* 모터 각도로 매핑한다.
> [작동 원리](#작동-원리)와 [로드맵](#현재-진행-상황--로드맵)을 참조하라.

## 빠른 시작

```bash
# 1. 클론 후 gesture_bt 디렉토리로 이동
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

# 2. 가상환경 생성 및 의존성 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt

# 3. 수동 BLE + 모터 테스트 (Hub가 실행 중이어야 함)
python bt_manual_motor_test.py --hub-name "Team5"

# 4. 전체 자동 조준 모드
python gesture_bt_controller.py
```

## 저장소 구조

```text
gesture_bt/
  gesture_bt_controller.py       # Mac 측: 빨간 물체 추적 + 포물선 예측 + 자동 발사
  hub_pybricks_gesture_server.py # Hub 측: Pybricks BLE 서버 + 모터 상태 머신
  bt_manual_motor_test.py        # 수동 BLE 모터 테스트 (카메라 없음)
  requirements_gesture_bt.txt    # Mac 측 Python 의존성
  models/                        # (레거시) MediaPipe 모델 — 현재 컨트롤러에서 미사용

Final_project/
  calibration_targeting.py       # 캘리브레이션 기반 조준 프로토타입 (로드맵 참조)
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

`hub_pybricks_gesture_server.py`의 포트 할당:

| Port | Motor | 역할 |
|------|-------|------|
| A | `launch_l` | 왼쪽 발사 휠 (PWM +100) |
| B | `launch_r` | 오른쪽 발사 휠 (PWM −100, 반대 방향) |
| C | `c_motor` | 발사/장전 메커니즘 (왕복 운동) |
| D | `tilt_motor` | 틸트 축 (0°–80°) |
| F | `pan_motor` | 팬 축 (−35°–+35°) |

모터가 누락되어도 허용된다: 각 포트는 `safe_motor`로 탐지되며,
`PORT_<label>_OK` 또는 `PORT_<label>_MISSING`을 로깅하고 실패 시 `None`을 반환한다.

## 작동 원리

### 컨트롤러 (`gesture_bt_controller.py`)

자동 조준 루프는 카메라 프레임 속도(640×480)로 실행되며 매 프레임 다섯 가지를 수행한다:

**1. 빨간 물체 감지 (HSV 색상 마스킹)**

```python
mask1 = cv2.inRange(hsv, [0,  120, 70], [10,  255, 255])   # 낮은 빨강 색조
mask2 = cv2.inRange(hsv, [170,120, 70], [180, 255, 255])   # 높은 빨강 색조
```

500 px² 이상의 가장 큰 빨간 컨투어가 표적이 된다. 프리뷰에 초록 경계 상자와
중심점이 그려진다.

**2. 속도 + 가속도 추정**

```
vx = (target_x - prev_x) / dt        # 원시 속도 (px/s)
vy = (target_y - prev_y) / dt

vx_smooth = SMOOTHING * vx + (1-SMOOTHING) * vx_smooth     # EMA 필터
vy_smooth = SMOOTHING * vy + (1-SMOOTHING) * vy_smooth

ay = (vy_smooth - prev_vy) / dt      # 원시 수직 가속도
ay_smooth = ACCEL_SMOOTHING * ay + (1-ACCEL_SMOOTHING) * ay_smooth
```

**3. 포물선 요격 예측**

```
predict_x = target_x + vx_smooth * FLIGHT_TIME
predict_y = target_y + vy_smooth * FLIGHT_TIME + 0.5 * ay_smooth * FLIGHT_TIME²
```

예측 지점은 빨간 원과 현재 위치로부터의 노란 선으로 시각화된다.

**4. 픽셀 → 절대 모터 각도 (고정 카메라 매핑)**

카메라가 고정되어 있고 모터가 독립적으로 움직이므로, 예측된 픽셀은
`pixel_to_motor_vals()`에 의해 절대 모터 각도로 직접 매핑된다:

```
pan:  px = 0 (왼쪽)  → −35°       px = 640 (오른쪽) → +35°
tilt: py = 0 (상단)  →  80° (위)  py = 480 (하단)   →  0° (아래)
```

두 값 모두 전송 전에 BLE 바이트 범위 `[-100, +100]`으로 정규화된다.

**5. 조준 및 자동 발사**

```
if abs(predict_x - CENTER_X) < FIRE_PX and abs(predict_y - CENTER_Y) < FIRE_PX:
    fire_trigger = 1     # 프리뷰에 "FIRE!!!" 표시
```

`SEND_INTERVAL`(100 ms)마다 Mac은 `M, pan_val, tilt_val, fire_trigger`
(4바이트 패킷)를 Hub로 전송한다. Hub는 절대 목표 각도를 설정하고 `fire=1`일 때
C 모터 상태 머신을 발동한다.

### 튜닝 상수

`gesture_bt_controller.py` 상단에서 편집한다. **`PAN_MAX_DEG` /
`TILT_MIN_DEG` / `TILT_MAX_DEG`는 Hub 상수와 정확히 일치해야 한다.**

| Constant | Default | 설명 |
|----------|---------|-------------|
| `HUB_NAME` | `"Team5"` | Pybricks BLE 허브 이름 |
| `PAN_MAX_DEG` | `35` | 팬 범위 ±도 (Hub `PAN_MAX`와 일치 필수) |
| `TILT_MIN_DEG` / `TILT_MAX_DEG` | `0` / `80` | 틸트 범위 (Hub `TILT_MIN`/`TILT_MAX`와 일치 필수) |
| `FLIGHT_TIME` | `0.4` s | 추정 발사체 체공 시간; 멀수록 크게 |
| `SMOOTHING` | `0.3` | 속도 EMA 가중치 (클수록 빠르지만 노이즈 많음) |
| `ACCEL_SMOOTHING` | `0.05` | 가속도 EMA 가중치 (노이즈 억제용, 낮게 유지) |
| `FIRE_PX` | `20` px | 양 축 예측 오차가 이 값 미만이면 자동 발사 |
| `SEND_INTERVAL` | `0.1` s | BLE 명령 전송 주기 |

## 설정

### 1. Hub (Pybricks)

1. [Pybricks Code](https://code.pybricks.com)에 접속하여 SPIKE Hub에 연결한다.
2. `gesture_bt/hub_pybricks_gesture_server.py`를 업로드한다.
3. **로봇을 영점/장전 상태에 위치시킨다**: 팬, 틸트, C 모터 모두 시작 시
   `reset_angle(0)`을 호출하므로, 실행 시점의 물리적 자세가 기준점이 된다
   (팬 중앙, 틸트 0°(아래), C 모터 장전 상태).
4. 한 번 실행하여 `READY`와 `rdy`가 나타나는지 확인한 뒤 Stop하고, Mac BLE
   클라이언트가 연결할 수 있도록 **Pybricks Code 연결을 해제**한다.
5. Hub 중앙 버튼을 누르면 Hub 프로그램이 시작된다.

### 2. Mac — 의존성 설치

```bash
cd CS270_FinalProject/gesture_bt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

의존성:

```text
opencv-python
mediapipe>=0.10.30
numpy
bleak
```

> `mediapipe`는 호환성을 위해 명시되어 있다. 자동 조준 컨트롤러는 MediaPipe를
> **사용하지 않으며**, OpenCV HSV 색상 마스킹만 사용한다.

### 3. 수동 BLE 테스트 (카메라 없음)

Hub가 저장된 프로그램을 실행 중인 상태에서 BLE + 모터 배선을 확인한다:

```bash
python bt_manual_motor_test.py --hub-name "Team5"
```

터미널에 `BLE connected`가 표시되면 Hub 중앙 버튼을 한 번 누른다.

예상 출력:

```text
[Hub] READY
[Hub] ARMED
Hub rdy received. Starting fixed-packet motor test...
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
...
[SEND] M,0,0,1 -> b'M\x00\x00\x01'
[Hub] FIRING
[Hub] RETURNING
[Hub] ARMED
[Hub] FIRED
Manual motor test done.
```

### 4. 자동 조준 모드

```bash
python gesture_bt_controller.py
```

허브 이름은 스크립트에 `HUB_NAME = "Team5"`로 하드코딩되어 있다. Hub 이름이
다르면 수정한다.

BLE가 연결되면 Hub 중앙 버튼을 누른다. **"Aimbot System (Parabolic
Prediction)"** 제목의 카메라 프리뷰 창이 나타난다. 카메라 앞에서 **빨간 물체**를
들거나 던진다:

- 초록 상자가 감지된 물체를 추적한다.
- 노란 선이 예측 요격 지점(빨간 원)을 표시한다.
- 예측 지점이 화면 중심에서 `FIRE_PX` 이내이고 `fire=1`이 Hub로 전송되면
  **"FIRE!!!"**가 표시된다.
- `q`를 눌러 종료한다.

## 현재 진행 상황 & 로드맵

### 완료 ✅

- `rdy` 흐름 제어 + 200 ms 하트비트(교착 복구)를 갖춘 4바이트 BLE 프로토콜
- Hub 펌웨어: 블록별 `try/except`, 최상위 크래시 가드, 안전 타임아웃
- 수동 모터 테스트 경로 (`bt_manual_motor_test.py`)
- 빨간 물체 감지 (HSV 마스킹, 최대 컨투어 선택)
- 포물선 예측 (속도 + 수직 가속도, EMA 평활화)
- **고정 카메라 → 절대 모터 각도 매핑** (독립적인 카메라/포탑)
- 자동 발사 트리거를 갖춘 C 모터 왕복 발사 상태 머신

### 다음 단계 🔜 (우선순위 순)

| # | 항목 | 중요한 이유 | 기기 필요? |
|---|------|------------|----------|
| 1 | **카메라↔포탑 캘리브레이션** | 현재 픽셀→각도 매핑은 *선형 추정*일 뿐이다. 카메라가 포탑과 독립적이므로, 픽셀 (px,py)의 표적이 모터 각도에 단순 대응하지 않는다. 캘리브레이션 단계(알려진 표적 샘플링 후 매핑 적합)가 정확도를 가장 크게 좌우한다. 저장소에 이미 `Final_project/calibration_targeting.py` + `CALIBRATION_IMPLEMENTATION_PLAN.md`가 있다. | 예 (슬롯) |
| 2 | **`--no-ble` / 카메라 전용 모드 추가** | 현재 컨트롤러는 실행에 로봇이 *반드시* 필요하다. no-BLE 모드는 비전/예측 작업을 단일 기기 점유 없이 노트북에서 진행할 수 있게 해 병렬 협업을 가능케 한다. | 아니오 |
| 3 | **FLIGHT_TIME / 낙하 캘리브레이션** | 하드코딩된 단일 상수. 실제 발사체 체공 시간을 측정하고 (선택적으로) 거리 의존적으로 만들어 정확한 리드를 구현한다. | 예 (슬롯) |
| 4 | **지연 보상** | BLE + 처리 지연이 유효 리드 시간에 더해진다. 종단 간 지연을 측정하여 예측 구간에 반영한다. | 예 (슬롯) |
| 5 | **CLI 인자** | 허브 이름, 카메라 인덱스, HSV 범위가 하드코딩됨. `argparse`를 추가하여 소스 수정 없이 각자 실행 가능하게 한다. | 아니오 |
| 6 | **표적 강건성** | 최소/최대 면적 게이팅, 프레임 간 추적 연속성, 표적 소실 복구를 추가하여 오탐 잠금을 줄인다. | 아니오 |
| 7 | **평가 & 로깅** | 최종 보고서용으로 명중률과 예측 오차를 CSV로 기록하고, 반복 가능한 테스트 표적을 설계한다. | 부분 |

## 팀 작업 분담 (5명, 기기 1대 공유)

**정해진 역할**

| 팀원 | 역할 | 집중 영역 |
|------|------|----------|
| P1 | 하드웨어 엔지니어 | 로봇 제작, 발사 메커니즘, 모터 장착, 배선 |
| P2 | HW↔SW 연결 | Hub 펌웨어, BLE 프로토콜, 캘리브레이션 브리지, 발사 타이밍 |

**나머지 3명 제안 역할**

| 팀원 | 역할 | 집중 영역 |
|------|------|----------|
| P3 | 비전 엔지니어 | 빨간 물체 감지 강건성, 표적 추적 (로드맵 #6) |
| P4 | 예측 / 알고리즘 | 포물선 모델, FLIGHT_TIME, 지연 보상, 리드 샷 수학 (로드맵 #3, #4) |
| P5 | 캘리브레이션 & 테스트 / 문서 | 캘리브레이션 절차(#1), 평가 하네스(#7), 기기 세션 운영, 문서 |

### 병렬 vs 순차 — 단일 기기 제약

로봇이 **1대뿐**이므로, 기기 의존 작업은 **예약된 슬롯으로 시분할**하고, 기기
없이 가능한 작업은 완전히 병렬로 진행한다.

**기기 불필요 작업 — 누구나, 언제든, 병렬로 (로봇 없이):**

- 녹화 영상 / 실시간 웹캠으로 비전 튜닝 — *로드맵 #2(`--no-ble` 모드) 필요*
- 예측 알고리즘 개발 및 오프라인 검증
- 픽셀→각도 수학 및 캘리브레이션 모델 설계
- CLI 인자, 로깅/평가 하네스, 문서 및 보고서

**기기 의존 작업 — 로봇 예약 필요 (한 번에 한 팀):**

- HW 제작 & 기계적 튜닝 (P1)
- Hub 펌웨어 플래시 + BLE/모터 구동 확인 (P2)
- 실측 각도 캘리브레이션 (P2 + P5)
- FLIGHT_TIME 측정 & 실사격 테스트 (P4 + P5)
- 종단 간 통합 실행 (전원)

### 권장 단계별 일정

| 단계 | 기기 사용자 | 병렬 진행 (기기 없이) |
|------|-----------|---------------------|
| **1. 제작 & 구동** | P1 로봇 제작; P2 펌웨어 플래시 & 짧은 슬롯으로 `bt_manual_motor_test.py` 실행 | P3 웹캠 비전, P4 녹화 영상 예측, P5 `--no-ble` 모드(#2) + 캘리브레이션 계획 |
| **2. 캘리브레이션** | P2 + P5 캘리브레이션 세션(#1) 진행 | P3/P4 오프라인 정제 지속; P5 평가 하네스(#7) 완성 |
| **3. 통합 & 튜닝** | 예약 슬롯으로 종단 간 실행, FLIGHT_TIME(#3) & 지연(#4) | 기기를 쓰지 않는 인원은 로깅 데이터로 상수 튜닝 및 보고서 작성 |

> **팁:** 가능한 한 많은 작업을 기기 없이 수행하라. 로드맵 #2(`--no-ble` 모드)를
> 초기에 완료하면 5명 중 3명이 로봇을 만지지 않고도 진척을 낼 수 있어 팀 전체
> 처리량이 배가된다.

## BLE 프로토콜

Mac → Hub: 4바이트 고정 패킷으로, 선행 `0x06` Pybricks 접두사와 함께 Pybricks
명령 characteristic(`c5f50002-8280-46da-89f4-6d8051e4aeef`)에 기록된다.

| Byte | Field | 설명 |
|------|-------|-------------|
| 0 | Opcode | `M` (`0x4D`) = 모터 명령, `S` (`0x53`) = 정지 및 종료 |
| 1 | pan_val | 절대 팬 각도, `[-100, +100]` → `[PAN_MIN, PAN_MAX]`, `value & 0xFF`로 전송 |
| 2 | tilt_val | 절대 틸트 각도, `[-100, +100]` → `[TILT_MIN, TILT_MAX]`, `value & 0xFF`로 전송 |
| 3 | fire | 평소 0, 양 축 예측 오차가 `FIRE_PX` 미만이면 1 |

Hub → Mac: Hub는 각 패킷 수신 후 `b"rdy"`로 응답한다. Mac은 다음 패킷을 보내기
전에 이를 기다린다(1초 타임아웃, 실패 시 조용히 건너뜀). 상태 라인(`READY`,
`ARMED`, `FIRING`, `RETURNING`, `FIRED`)은 `[Hub] ...` 형식으로 출력된다.

## 아키텍처 노트

**절대 각도 모터 제어 (Hub).** 각 `M` 패킷은 (누적 없이) 목표 각도를 직접
설정하며, 이는 고정 카메라 설계를 반영한다:

```
pan_target  = clamp(pan_val  / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_target = clamp((tilt_val + 100) / 200.0 * (TILT_MAX − TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
```

이후 Hub는 매 루프 반복마다(~5 ms 대기) `pan_motor.track_target()` /
`tilt_motor.track_target()`를 호출한다.

**C 모터 발사 상태 머신 (왕복 운동):**

```
armed → firing (+C_FIRE_DC to C_FIRE_ANGLE°) → returning (−C_RETURN_DC to 0°) → armed
```

**안전 타임아웃:** 1000 ms 이내에 패킷이 도착하지 않으면 Hub는 팬/틸트 목표를
재중앙 정렬한다.

**비상 정지:** Hub 버튼을 누르면 루프가 종료된다; Mac은 종료 시 영점 패킷을 전송한다.

**BLE 교착 복구:** Hub는 유휴 상태에서도 200 ms마다 주기적 `rdy` 하트비트를
전송하므로, `rdy` 하나가 누락되어도 Mac의 `asyncio.Event` 대기가 영구히 멈추지 않는다.

## 모션 상수 (Hub)

| Constant | Value | 설명 |
|----------|-------|-------------|
| `PAN_MIN` / `PAN_MAX` | −35 / 35° | 팬 목표 이동 한계 |
| `TILT_MIN` / `TILT_MAX` | 0 / 80° | 틸트 목표 이동 한계 |
| `PAN_SPEED` | 600 deg/s | 팬 추적 속도 |
| `TILT_SPEED` | 500 deg/s | 틸트 추적 속도 |
| `COMMAND_TIMEOUT_MS` | 1000 ms | 명령 미수신 시 팬/틸트 재중앙 정렬 |
| `C_FIRE_ANGLE` | 170° | C 모터 발사(릴리스) 위치 |
| `C_FIRE_DC` | 80 | 전진(발사) 듀티 사이클 % |
| `C_RETURN_DC` | 50 | 역전(장전) 듀티 사이클 % |
| `C_TOLERANCE` | 3° | 상태 전이를 위한 각도 허용 오차 |
| `LAUNCH_PWM_A` | 100 | Port A 발사 휠 PWM |
| `LAUNCH_PWM_B` | −100 | Port B 발사 휠 PWM (반대 방향) |
