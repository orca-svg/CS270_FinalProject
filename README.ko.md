# CS270 기말 프로젝트 — LEGO SPIKE Pybricks BLE 발사기

[English README](README.md)

LEGO SPIKE Prime 팬-틸트 발사기를 위한 실시간 컴퓨터 비전 제어 프로젝트입니다.
현재 프로젝트 방향은 **Mac/Python → Pybricks BLE → SPIKE Hub** 직결 방식으로
고정합니다. 공유 GitHub 저장소는 현재 Pybricks BLE 구현, 프로젝트 문서,
재현 가능한 실행/검증 절차만 담도록 범위를 좁힙니다.

## 프로젝트 방향

주력 아키텍처:

```text
Mac / laptop
  gesture_bt/gesture_bt_controller.py   # 손 제스처 제어
  gesture_bt/balloon_intercept.py       # C-RAM 스타일 표적 요격
        |
        | Pybricks BLE, GATT c5f50002-8280-46da-89f4-6d8051e4aeef
        v
SPIKE Prime Hub
  gesture_bt/hub_pybricks_gesture_server.py
        |
        v
Motors A/B/C/D/F
```

## 빠른 시작

```bash
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt

# 1. Pybricks Code에서 hub_pybricks_gesture_server.py 업로드, 1회 실행, 연결 해제
# 2. Mac이 BLE 연결되면 Hub 중앙 버튼으로 저장 프로그램 시작

python bt_manual_motor_test.py --hub-name "Team5"
python gesture_bt_controller.py --hub-name "Team5" --print-sends
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

## 저장소 구조

```text
gesture_bt/
  pybricks_ble.py               # 공유 Pybricks BLE 스캔/재연결/진단 클라이언트
  gesture_bt_controller.py       # Mac 측 손 제스처 Pybricks BLE 컨트롤러
  balloon_intercept.py           # HSV 표적 탐지, 포물선 리드샷 예측, 자동 발사
  hub_pybricks_gesture_server.py # Hub 측 Pybricks BLE 서버와 모터 상태 머신
  bt_manual_motor_test.py        # 카메라 없이 BLE + 모터 경로 테스트
  requirements_gesture_bt.txt

docs/
  ARCHITECTURE.md                # 현재 Pybricks BLE 아키텍처
  PROTOCOL.md                    # 4바이트 Pybricks BLE 프로토콜
  STATE_MACHINES.md              # Hub와 Mac 제어 상태 머신
  PREDICTION.md                  # 포물선 표적 예측 모델
  ko/                            # 한국어 기술 문서
```

MediaPipe hand landmarker 모델은 최초 실행 시 다운로드되며 Git에는 올리지
않습니다. 로컬 하네스 파일도 무시하여 팀원/교수/TA가 보는 GitHub는 프로젝트
실행 코드와 문서 중심으로 유지합니다.

## 하드웨어 포트

| Port | Motor | 역할 |
|------|-------|------|
| A | `launch_l` | 왼쪽 발사 휠 |
| B | `launch_r` | 오른쪽 발사 휠, 반대 방향 |
| C | `c_motor` | 발사/재장전 메커니즘 |
| D | `tilt_motor` | 틸트 축 |
| F | `pan_motor` | 팬 축 |

Hub 코드는 각 포트를 `safe_motor()`로 탐지합니다. 모터가 없어도
`PORT_<label>_MISSING`만 출력하고 계속 실행하므로, A/B/C가 미완성인 상태에서도
D/F 팬-틸트 테스트가 가능합니다.

## BLE 프로토콜

Mac은 Pybricks command/event characteristic에 선행 `0x06`을 붙여 씁니다. Hub는
명령마다 정확히 4바이트를 읽고, 바이트 정렬이 깨져도 재동기화합니다.

| Byte | Field | 의미 |
|------|-------|------|
| 0 | opcode | `M` = 이동/발사 명령, `S` = 정지 후 종료 |
| 1 | `pan_err_i8` | signed pan 오차, `[-100, 100]`를 `value & 0xFF`로 인코딩 |
| 2 | `tilt_err_i8` | signed tilt 오차, `[-100, 100]`를 `value & 0xFF`로 인코딩 |
| 3 | `fire` | `1`이면 발사 1회 래치, 평소 `0` |

Hub 갱신 규칙:

```python
pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

Hub는 패킷 처리 후 `rdy`를 보내고, 유실된 notification으로 교착이 생기지 않도록
200 ms마다 heartbeat도 보냅니다. `READY`, `ARMED`, `FIRING`, `RETURNING`,
`FIRED` 같은 상태 라인은 Mac에서 `[Hub] ...` 형식으로 출력됩니다.
발사 각도 스냅샷은 `SHOT_START`, `SHOT_RELEASE`, `SHOT_DONE`으로 출력되며,
실제 `pan_F`, `tilt_D`, `c_C` 모터 각도와 현재 pan/tilt 목표 각도를 포함합니다.

모든 Mac 측 도구는 `gesture_bt/pybricks_ble.py`를 통해 BLE 스캔, notification,
readiness, Hub 침묵 경고, 재연결 진단을 공통으로 처리합니다.

## 주요 실행 흐름

### 1. 수동 BLE + 모터 테스트

카메라 작업 전에 먼저 실행합니다.

```bash
cd gesture_bt
source .venv/bin/activate
python bt_manual_motor_test.py --hub-name "Team5" --print-sends
```

예상 흐름:

```text
[SCAN] name='Team5' timeout=15.0s
[BLE] connected to Team5
[NOTIFY] started. Start the saved Hub program with the Hub center button if needed.
[Hub] READY
[Hub] ARMED
[READY] first rdy received.
Starting 4-byte BLE motor test...
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,0,0,1 -> b'M\x00\x00\x01'
[Hub] SHOT_START pan_F=... tilt_D=... c_C=... target_pan=... target_tilt=...
[Hub] FIRING
[Hub] SHOT_RELEASE pan_F=... tilt_D=... c_C=... target_pan=... target_tilt=...
[Hub] RETURNING
[Hub] SHOT_DONE pan_F=... tilt_D=... c_C=... target_pan=... target_tilt=...
[Hub] ARMED
[Hub] FIRED
```

### 2. 손 제스처 제어

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

동작:

| 입력 | 동작 |
|------|------|
| 손바닥 | 화면 중심 대비 손 오차를 따라 팬/틸트 이동 |
| 주먹 전환 | `fire=1`을 한 번 전송 |
| 손 미검출 | 지연 후 0 오차 전송 |
| `q` | `STOP` 전송 후 종료 |

### 3. 풍선 / 표적 요격

```bash
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

이 경로를 C-RAM 데모 주력으로 둡니다. HSV로 표적을 감지하고, EMA로 부드럽게
추정한 속도와 수직 가속도를 사용해 미래 탄착점을 예측하며, 설정된 프레임 수 동안
예측점이 조준 상태를 유지하면 자동 발사합니다.

주요 옵션:

| 옵션 | 목적 |
|------|------|
| `--color-picker` | 카메라 창에서 표적 색상을 클릭해 HSV 범위 설정 |
| `--hsv-lower`, `--hsv-upper` | 고정 HSV 범위로 실행 |
| `--flight-time` | 포물선 예측에 사용할 발사체 도달 예상 시간 |
| `--lead-frames` | `--flight-time`에 추가할 프레임 기반 리드 보정 |
| `--velocity-smoothing` | 표적 속도 EMA 계수 |
| `--accel-smoothing` | 수직 가속도 EMA 계수 |
| `--fire-threshold` | 자동 발사 허용 픽셀 오차 |
| `--hold-frames` | 발사 전 연속 조준 프레임 수 |
| `--mode rl` | 실험적 Q-table 보정 레이어 |

## 팀 역할

역할은 확정된 상태입니다.

| 팀원 | 역할 | 집중 영역 |
|------|------|----------|
| P1 | 하드웨어 엔지니어 | 로봇 제작, 발사 메커니즘, 모터 장착, 배선 |
| P2 | HW/SW 통합 | Hub 펌웨어, BLE 프로토콜, 캘리브레이션 브리지, 발사 타이밍 |
| P3 | 비전 엔지니어 | HSV 표적 감지 강건성, 표적 추적, 카메라 파라미터 |
| P4 | 예측 / 알고리즘 | 리드샷 수학, 체공 시간 튜닝, 지연 보상 |
| P5 | 캘리브레이션 & 테스트 / 문서 | 캘리브레이션 절차, 평가 하네스, 세션 운영, README/보고서 |

## 프로젝트 대시보드

상태: Done = 완료, Next = 현재 우선순위, Planned = 대기.

| 모듈 | 상태 | 담당 |
|------|:---:|:---:|
| Pybricks BLE 직결 아키텍처 선택 | Done | P2 |
| 4바이트 패킷 프로토콜 + `rdy` 흐름 제어 | Done | P2 |
| Hub 파서 자가 복구 + stdin flush | Done | P2 |
| Hub 크래시 가시화 (`ERR_*`, `FATAL`, `BTN_STOP`) | Done | P2 |
| 수동 BLE 모터 테스트 | Done | P2 |
| 손 제스처 BLE 제어 | Done | P3/P2 |
| 주먹 기반 발사 래치 | Done | P3/P2 |
| 풍선/표적 HSV 요격 + 포물선 예측 | Done | P3/P4 |
| 팀 역할 분배와 README 대시보드 | Done | P5 |
| 표적 요격용 camera-only / no-BLE 모드 | Next | P5 |
| 카메라-포탑 캘리브레이션 루틴 | Next | P5/P2 |
| 표적 강건성: 면적 게이트, 연속 추적, 소실 복구 | Planned | P3 |
| 체공 시간과 지연 캘리브레이션 | Planned | P4/P5 |
| 평가 로깅: 명중률, 오차, 세션 CSV | Planned | P5 |
| 최종 보고서 그림과 프로토콜 설명 | Planned | P5 |

## 할 일 상세

| # | 항목 | 담당 | 중요한 이유 | 기기 필요? |
|:-:|------|:---:|------------|:---------:|
| 1 | Camera-only / no-BLE 모드 | P5 | 로봇 1대를 점유하지 않고도 P3/P4/P5가 비전, 예측, 로깅을 병렬 개발할 수 있습니다. | No |
| 2 | 카메라-포탑 캘리브레이션 | P5/P2 | 현재 오차 기반 조향은 동작하지만, 반복 가능한 요격에는 측정 기반 mapping과 sign/gain 확인이 필요합니다. | Yes |
| 3 | 표적 감지 강건성 | P3 | 조명과 배경 노이즈에서 false lock과 오발을 줄입니다. | No |
| 4 | 체공 시간 / 지연 캘리브레이션 | P4/P5 | BLE, 처리 시간, 발사체 지연이 올바른 리드샷을 결정합니다. | Yes |
| 5 | 평가 로깅 | P5 | 최종 보고서에 필요한 명중/실패, 예측 오차, 상수, 실험 조건 근거를 남깁니다. | Partial |
| 6 | 최종 통합 슬롯 | All | 데모 조건에서 Hub + 카메라 + 표적 + 발사기를 전체 검증합니다. | Yes |

## 로봇 1대 기준 팀 워크플로우

기기 없이 가능한 일은 병렬로 진행하고, 기기 의존 작업은 짧은 슬롯으로 예약합니다.

| 단계 | 로봇 슬롯 | 로봇 없이 병렬 진행 |
|------|----------|-------------------|
| 1. 구동 | P1/P2 배선, Hub 업로드, `bt_manual_motor_test.py` | P3 HSV 튜닝, P4 영상 기반 예측, P5 문서 업데이트 |
| 2. 캘리브레이션 | P2/P5 sign, gain, threshold 튜닝 | P3 감지 개선, P4 리드/지연 모델 |
| 3. 통합 | 전체 end-to-end 예약 테스트 | P5 결과 로깅, P3/P4 녹화 데이터 기반 튜닝 |
| 4. 보고서/데모 | 최종 리허설 | P5 README/보고서 그림과 최종 데모 설명 정리 |

## 문제 해결

| 증상 | 가능 원인 | 조치 |
|------|----------|------|
| `[SCAN] no matching Hub` | Pybricks Code/SPIKE 앱 점유, Hub 꺼짐, 이름 불일치 | 앱 연결 해제, Hub 재부팅, 재시도; 이름 실패 후 UUID fallback이 실행됨 |
| `[BLE] connected` 후 `[READY]` 없음 | 저장된 Hub 프로그램 미실행 | Hub 중앙 버튼을 누르고 화면 `BT` 확인 |
| `[WAIT] Hub program is not sending rdy` | Hub readiness heartbeat 미수신 | Hub 중앙 버튼, Pybricks Code/SPIKE 앱 연결 해제, 화면 `BT` 확인 |
| `[STALE] Hub is silent` | BLE 링크는 살아 있지만 Hub 프로그램 중단/크래시 | Hub 프로그램 재시작, `[Hub] FATAL...` 로그 확인 |
| `[DISCONNECT]` / `[RECONNECT]` | BLE 링크 끊김 | Hub 전원/거리 확인; 기본 도구는 `--no-reconnect`가 없으면 3초마다 재스캔 |
| 모터 방향 반대 | sign 불일치 | Hub 코드의 `PAN_SIGN` 또는 `TILT_SIGN` 반전 |
| 모터 이동이 너무 작음 | gain 부족 | Hub 코드의 `GAIN`을 조심스럽게 증가 |
| macOS에서 카메라 미동작 | 카메라 권한 없음 | Terminal/iTerm/VS Code 카메라 권한 허용 |

## 2026-06-02 검증 상태

- GitHub remote: `orca-svg/CS270_FinalProject`, 기본 브랜치 `main`.
- 현재 방향: Pybricks BLE 직결 제어.
- 공유 repo 범위: `gesture_bt/`, `docs/`, `README.md`, `README.ko.md`.
- 하네스 파일, 가상환경, zip 아카이브, 로컬 복사본, MediaPipe `.task` 모델
  파일은 로컬 전용/생성물로 보고 Git에서 무시합니다.
- 추적 중인 `gesture_bt/*.py` 런타임 파일의 Python 문법 검사를 통과했습니다.
