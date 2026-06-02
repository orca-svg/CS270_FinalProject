# 🎯 CS270 기말 프로젝트 — LEGO SPIKE Pybricks BLE 발사기

[English README](README.md)

> LEGO SPIKE Prime 팬-틸트 발사기를 위한 실시간 컴퓨터 비전 제어 프로젝트.
> Mac이 비전 + 제어 루프를 돌리고 **Pybricks BLE**로 Hub를 직접 구동한다 —
> SPIKE 앱도, 중간 서버도 없다.

```text
Mac / laptop  ──Pybricks BLE (GATT c5f50002-…)──►  SPIKE Prime Hub  ──►  Motors A/B/C/D/F
 비전 + 제어 루프                                    hub_pybricks_gesture_server.py
```

공유 저장소는 Pybricks BLE 구현, 기술 문서, 재현 가능한 실행/검증 절차만 담도록
범위를 좁힌다.

---

## 🚀 빠른 시작

```bash
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

**그다음:** [Pybricks Code](https://code.pybricks.com)에서
`hub_pybricks_gesture_server.py`를 업로드하고 1회 실행 후 연결을 해제한다.
Mac이 BLE로 연결되면 Hub 중앙 버튼을 눌러 저장된 프로그램을 시작한다.

## 🧭 어떤 스크립트를 실행하나?

Mac 측 진입점은 3개이며, 모두 `pybricks_ble.py`로 BLE를 공유한다:

| 스크립트 | 용도 | 로봇 필요? |
|---------|------|:---------:|
| **`bt_manual_motor_test.py`** | 카메라 없이 BLE + 모터 배선 검증. **가장 먼저 실행.** | ✅ 예 |
| **`gesture_bt_controller.py`** | 손 제스처 제어(MediaPipe): 손바닥 조준, 주먹 발사. | `--dry-run` → 아니오 |
| **`balloon_intercept.py`** | C-RAM 데모: HSV 표적 탐지 + 포물선 리드샷 + 자동 발사. | `--dry-run` → 아니오 |

```bash
# 1) 배선 확인 (로봇 필요)
python bt_manual_motor_test.py --hub-name "Team5" --print-sends

# 2) 손 제스처 제어
python gesture_bt_controller.py --hub-name "Team5" --print-sends

# 3) 풍선 / 표적 요격  (데모 주력)
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

> 💡 **로봇이 없으면 `--dry-run`을 쓴다.** `gesture_bt_controller.py`와
> `balloon_intercept.py` 모두 카메라/비전/예측 루프를 전부 실행하고 BLE 전송 대신
> 패킷을 출력한다 — 단일 Hub를 점유하지 않고도 비전·예측 작업을 병렬로 진행할 수 있다.

---

## 📦 저장소 구조

```text
gesture_bt/
  pybricks_ble.py                # 공유 BLE 스캔 / 재연결 / readiness / 진단
  bt_manual_motor_test.py        # 카메라 없이 BLE + 모터 경로 테스트
  gesture_bt_controller.py       # 손 제스처 컨트롤러
  balloon_intercept.py           # HSV 탐지 + 포물선 예측 + 자동 발사
  hub_pybricks_gesture_server.py # Hub 측 BLE 서버 + 모터 상태 머신
  requirements_gesture_bt.txt

docs/                            # 심화 기술 문서 (영문 + ko/)
  ARCHITECTURE.md  PROTOCOL.md  STATE_MACHINES.md  PREDICTION.md
```

MediaPipe hand-landmarker 모델은 최초 실행 시 다운로드되며 Git에서 무시된다.
로컬 하네스 파일, 가상환경, 다른 사이드 프로젝트도 무시하여 팀원/교수/TA가 보는
GitHub 저장소를 실행 코드와 문서 중심으로 유지한다.

## 🔌 하드웨어 포트

| Port | Motor | 역할 |
|:----:|-------|------|
| A | `launch_l` | 왼쪽 발사 휠 |
| B | `launch_r` | 오른쪽 발사 휠 (반대 방향) |
| C | `c_motor` | 발사 / 재장전 메커니즘 (왕복) |
| D | `tilt_motor` | 틸트 축 (0°–80°) |
| F | `pan_motor` | 팬 축 (−35°–+35°) |

각 포트는 `safe_motor()`로 탐지한다. 모터가 없으면 `PORT_<label>_MISSING`만
출력하고 건너뛰므로, A/B/C가 미완성이어도 D/F 팬-틸트 테스트가 가능하다.

---

## 📡 BLE 프로토콜 (요약)

Mac은 Pybricks command/event characteristic에 선행 `0x06`을 붙여 쓴다. Hub는
명령마다 **정확히 4바이트**를 읽고, 바이트 정렬이 깨져도 재동기화한다.

| Byte | Field | 의미 |
|:----:|-------|------|
| 0 | opcode | `M` = 이동/발사, `S` = 정지 후 종료 |
| 1 | `pan_err_i8` | signed pan 오차 `[-100, 100]`, `value & 0xFF`로 인코딩 |
| 2 | `tilt_err_i8` | signed tilt 오차 `[-100, 100]`, `value & 0xFF`로 인코딩 |
| 3 | `fire` | `1`이면 발사 1회 래치, 평소 `0` |

Hub는 오차를 목표 각도로 **누적**한다 (원시 속도를 명령하지 않음):

```python
pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

Hub는 패킷마다 `rdy`를 보내고(유실 notification 대비 200 ms 하트비트 포함),
Mac이 `[Hub] ...`로 출력하는 상태 라인을 전송한다: `READY`, `ARMED`, `FIRING`,
`RETURNING`, `FIRED`, 그리고 발사 스냅샷 `SHOT_START / SHOT_RELEASE / SHOT_DONE`
(실시간 `pan_F`, `tilt_D`, `c_C` 각도 포함).

> 📖 상세: [`docs/PROTOCOL.md`](docs/PROTOCOL.md) ·
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
> [`docs/STATE_MACHINES.md`](docs/STATE_MACHINES.md) ·
> [`docs/PREDICTION.md`](docs/PREDICTION.md)

---

## ▶️ 실행 흐름

### 1. 수동 BLE + 모터 테스트 (가장 먼저)

```bash
python bt_manual_motor_test.py --hub-name "Team5" --print-sends
```

예상 흐름:

```text
[SCAN] name='Team5' timeout=15.0s
[BLE] connected to Team5
[Hub] READY
[Hub] ARMED
[READY] first rdy received.
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,0,0,1   -> b'M\x00\x00\x01'
[Hub] SHOT_START ... → FIRING → SHOT_RELEASE → RETURNING → SHOT_DONE → ARMED → FIRED
```

### 2. 손 제스처 제어

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

| 입력 | 동작 |
|------|------|
| 손바닥 | 화면 중심 대비 손 오차를 따라 팬/틸트 이동 |
| 주먹 전환 | `fire=1`을 한 번 전송 |
| 손 미검출 | 지연 후 0 오차 전송 |
| `q` | `STOP` 전송 후 종료 |

### 3. 풍선 / 표적 요격 (데모 주력)

```bash
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

HSV로 표적을 감지하고, EMA로 부드럽게 추정한 속도 + 수직 가속도로 미래 탄착점을
예측하며, 예측점이 `--hold-frames` 동안 조준 임계 내에 머무르면 자동 발사한다.

| 옵션 | 목적 |
|------|------|
| `--color-picker` | 카메라 창에서 표적 색상 클릭 |
| `--hsv-lower`, `--hsv-upper` | 고정 HSV 범위 (피커 생략) |
| `--flight-time` | 포물선 예측에 쓰는 발사체 도달 예상 시간 |
| `--lead-frames` | `--flight-time`에 더할 프레임 기반 리드 보정 |
| `--velocity-smoothing` / `--accel-smoothing` | EMA 계수 (속도 / 수직 가속도) |
| `--fire-threshold` | 자동 발사 허용 픽셀 오차 |
| `--hold-frames` | 발사 전 연속 조준 프레임 수 |
| `--fire-cooldown` | 발사 후 재발사 금지 시간(초) |
| `--mode rl` | 실험적 Q-table 보정 레이어 (`--qtable`) |

---

## 👥 팀 & 역할 (확정)

| 팀원 | 역할 | 집중 영역 |
|:----:|------|----------|
| **P1** | 🔧 하드웨어 엔지니어 | 로봇 제작, 발사 메커니즘, 모터 장착, 배선 |
| **P2** | 🔗 HW/SW 통합 | Hub 펌웨어, BLE 프로토콜, 캘리브레이션 브리지, 발사 타이밍 |
| **P3** | 👁️ 비전 엔지니어 | HSV 감지 강건성, 표적 추적, 카메라 파라미터 |
| **P4** | 📐 예측 / 알고리즘 | 리드샷 수학, 체공 시간 튜닝, 지연 보상 |
| **P5** | 🎯 캘리브레이션 & 테스트 / 문서 | 캘리브레이션 절차, 평가 하네스, 세션 운영, README/보고서 |

## 📊 프로젝트 대시보드

**범례:** ✅ 완료 · 🔜 진행 중 · ⬜ 예정

| 모듈 | 상태 | 담당 |
|------|:----:|:----:|
| Pybricks BLE 직결 아키텍처 | ✅ | P2 |
| 4바이트 프로토콜 + `rdy` 흐름 제어 + 하트비트 | ✅ | P2 |
| Hub 파서 자가 복구 + stdin flush | ✅ | P2 |
| Hub 크래시 가시화 (`ERR_*`, `FATAL`, `BTN_STOP`) | ✅ | P2 |
| 수동 BLE 모터 테스트 | ✅ | P2 |
| 손 제스처 제어 + 주먹 발사 래치 | ✅ | P3 · P2 |
| 풍선/표적 HSV 요격 + 포물선 예측 | ✅ | P3 · P4 |
| `--dry-run` 카메라 전용 모드 (로봇 불필요) | ✅ | P3 · P5 |
| 팀 역할 + README 대시보드 + 문서 | ✅ | P5 |
| 카메라-포탑 캘리브레이션 루틴 | 🔜 | P5 · P2 |
| 결정적 녹화 영상 리플레이 하네스 | 🔜 | P5 |
| 표적 강건성 (면적 게이트, 연속 추적, 소실 복구) | ⬜ | P3 |
| 체공 시간 + 지연 캘리브레이션 | ⬜ | P4 · P5 |
| 평가 로깅 (명중률, 오차, 세션 CSV) | ⬜ | P5 |
| 최종 보고서 그림 + 데모 | ⬜ | 전원 |

## ✅ 할 일 상세 (우선순위 순)

| # | 항목 | 담당 | 중요한 이유 | 기기? |
|:-:|------|:----:|------------|:----:|
| 1 | **카메라-포탑 캘리브레이션** | P5 · P2 | 오차 기반 조향은 동작하지만, 반복 가능한 요격에는 측정 기반 픽셀→각도 mapping과 sign/gain 확인이 필요하다. 정확도를 가장 크게 좌우한다. | 🔴 예 |
| 2 | **녹화 영상 리플레이 하네스** | P5 | `--dry-run`은 이미 로봇 없이 라이브 실행을 지원한다. 결정적 클립 리플레이 모드를 추가하면 P3/P4가 동일 입력에서 감지/예측 변경을 비교할 수 있다. | 🟢 아니오 |
| 3 | **표적 강건성** | P3 | 최소/최대 면적 게이팅, 프레임 간 연속성, 소실 복구로 false lock과 오발을 줄인다. | 🟢 아니오 |
| 4 | **체공 시간 / 지연 캘리브레이션** | P4 · P5 | BLE + 처리 + 발사체 지연이 올바른 리드를 결정한다. 측정하여 예측기에 반영한다. | 🔴 예 |
| 5 | **평가 로깅** | P5 | 명중/실패, 예측 오차, 실험 조건을 CSV로 — 최종 보고서 근거. | 🟡 부분 |
| 6 | **최종 통합 & 데모** | 전원 | 데모 조건에서 Hub + 카메라 + 표적 + 발사기 전체 루프 검증. | 🔴 예 |

## 🤝 로봇 1대 기준 팀 워크플로우

기기 없이 가능한 일은 병렬로, 단일 로봇은 짧은 슬롯으로 예약한다.

| 단계 | 🔴 로봇 슬롯 | 🟢 로봇 없이 병렬 진행 |
|------|------------|---------------------|
| **1. 구동** | P1/P2: 배선, Hub 업로드, `bt_manual_motor_test.py` | P3 HSV 튜닝(`--dry-run`), P4 영상 기반 예측, P5 문서 |
| **2. 캘리브레이션** | P2/P5: sign, gain, threshold | P3 감지 강건성, P4 리드/지연 모델 |
| **3. 통합** | 전원: 예약된 end-to-end 테스트 | P5 결과 로깅, P3/P4 녹화 데이터 기반 튜닝 |
| **4. 보고서/데모** | 최종 리허설 | P5 README/보고서 그림 + 데모 설명 정리 |

> 💡 `--dry-run`이 있으므로 **5명 중 3명은 언제든 로봇 없이 진척을 낼 수 있다.**
> 로봇 슬롯은 배선, 캘리브레이션, 실사격에 집중 배정하라.

---

## 🛠️ 문제 해결

| 증상 | 가능 원인 | 조치 |
|------|----------|------|
| `[SCAN] no matching Hub` | 앱이 점유 중, Hub 꺼짐, 이름 불일치 | Pybricks Code/SPIKE 앱 연결 해제, Hub 재부팅, 재시도 (이름 실패 후 UUID fallback 실행) |
| `[BLE] connected`인데 `[READY]` 없음 | 저장된 Hub 프로그램 미실행 | Hub 중앙 버튼; 화면 `BT` 확인 |
| `[WAIT] Hub not sending rdy` | readiness 하트비트 아직 없음 | 중앙 버튼, 다른 앱 연결 해제, 화면 `BT` 확인 |
| `[STALE] Hub is silent` | 링크는 살아있으나 Hub 프로그램 정지/크래시 | Hub 프로그램 재시작; `[Hub] FATAL...` 확인 |
| `[DISCONNECT]` / `[RECONNECT]` | BLE 링크 끊김 | Hub를 가까이·전원 유지; `--no-reconnect`가 아니면 3초마다 재스캔 |
| 모터가 반대로 움직임 | 부호 불일치 | Hub 코드의 `PAN_SIGN` / `TILT_SIGN` 반전 |
| 모터가 거의 안 움직임 | gain 과소 | Hub 코드의 `GAIN`을 신중히 증가 |
| macOS 카메라 미동작 | 카메라 권한 없음 | Terminal/iTerm/VS Code 카메라 권한 허용 |

---

*2026-06-02 기준 `orca-svg/CS270_FinalProject@main`에 대해 검증. 방향: Pybricks
BLE 직결 제어. 저장소 범위: `gesture_bt/`, `docs/`, `README*.md`. 하네스 파일,
가상환경, 아카이브, MediaPipe `.task` 모델은 Git에서 무시됨.*
