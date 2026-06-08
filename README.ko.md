# 🎯 CS270 기말 프로젝트 — LEGO SPIKE Pybricks BLE 발사기

[English README](README.md)

> LEGO SPIKE Prime 팬-틸트 발사기를 위한 실시간 컴퓨터 비전 제어 프로젝트.
> Mac이 비전 + 제어 루프를 돌리고 **Pybricks BLE**로 Hub를 직접 구동한다 —
> SPIKE 앱도, 중간 서버도 없다.

```text
Mac / laptop  ──Pybricks BLE (GATT c5f50002-…)──►  SPIKE Prime Hub  ──►  Motors A/B/C/D/F
 비전 + 제어 루프                                    hub_pybricks_gesture_server.py
```

공유 저장소는 Pybricks BLE 구현, 기술 문서, 재현 가능한 실행/검증 절차를 담는다.
주력 플랫폼은 macOS이며, Windows 스레드 변형(`*_win.py`)과 로봇 없이 도는 오프라인
도구(`*_offline.py`)가 비전/예측 작업용으로 주력 경로와 함께 들어 있다.

---

## 📝 최근 회의 정리: 최종 데모 AI 기능 방향

회의에서는 “새 모델을 직접 학습시키는 것”보다 **기존 추적/발사 루프를 깨지 않고
영상에서 설명 가능한 AI 활용 요소를 추가**하는 방향으로 정리했다. 특히 표적 추적과
발사 정확도는 이미 지연에 민감하므로, 무거운 물체 분류 모델을 메인 루프에 직접 넣기보다
노트북 쪽에서 모드 정책을 결정하고 Hub에는 기존 4바이트 명령만 보내는 구조를 유지한다.

확정/우선순위:

1. **음성 인식 기반 모드 전환**
   - “단발/정밀 사격”, “연발/위협 사격”, “발사 중지”, “경계 모드”처럼 데모용으로
     설명하기 좋은 모드를 음성/LLM 쪽에서 JSON으로 기록한다.
   - 실시간 추적 루프는 그 JSON의 `mode`만 읽어서 `fire=1` 전송 정책을 바꾼다.
2. **다중 색상/표적 대응은 보조 스토리라인**
   - 풍선/비닐봉투 등 여러 낙하물을 검토했지만, 실제 성공률과 낙하 속도를 고려하면
     풍선 중심 데모가 가장 안정적이다.
   - 필요하면 색상 HSV 범위 확장이나 영상 편집/시연 시나리오로 “다양한 표적 대응”을
     설명한다.
3. **경계/레이더 모드는 시간 남을 때의 추가 요소**
   - 표적이 없을 때 좌우로 sweep하며 감시하는 모습을 보여주면 방어 시스템 스토리텔링에
     도움이 된다.
   - 거리 센서/360도 회전은 하드웨어 여건에 따라 선택 사항으로 둔다.
4. **Hub 프로토콜은 변경하지 않음**
   - Hub는 계속 `M,pan,tilt,fire` 4바이트만 받는다.
   - 모드 문자열은 Hub로 직접 보내지 않고, Mac/Windows 컨트롤러가 모드에 따라 `fire`와
     pan sweep 명령을 조절한다. BLE 정렬 오류 위험을 줄이기 위한 결정이다.

이번 브랜치(`feat/voice-fire-mode-json`)는 위 결정 중 **음성/LLM 모드 전환 + Windows 대응 +
테스트/문서화**를 구현한 브랜치다.

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
`hub_pybricks_gesture_server.py`를 Hub에 저장하고, Mac 스크립트를 실행하기 전
Pybricks Code/SPIKE App 연결을 해제한다. Mac 측 도구는 Pybricks 원격 `START`를
자동 전송한다. 실행 도중 Hub 프로그램이 멈추면 Mac이 `START`를 다시 보내고 다음
`rdy`에 재동기화한 뒤 이어서 진행한다. BLE 연결은 자동 재시도된다.
`balloon_intercept.py`의 기본값은 `--connect-attempts 5`, `--scan-timeout 20`이다.
Hub 중앙 버튼으로 직접 시작하는 진단 때만 `--no-auto-start`를 사용한다.

## 🧭 어떤 스크립트를 실행하나?

Mac 측 진입점은 3개이며, 모두 `pybricks_ble.py`로 BLE를 공유한다:

| 스크립트 | 용도 | 로봇 필요? |
|---------|------|:---------:|
| **`bt_manual_motor_test.py`** | 카메라 없이 BLE + 모터 배선 검증. **가장 먼저 실행.** | ✅ 예 |
| **`gesture_bt_controller.py`** | 손 제스처 제어(MediaPipe): 손바닥 조준, 주먹 발사. | ✅ 예 |
| **`balloon_intercept.py`** | C-RAM 데모: 빨간 표적 탐지 + 포물선 리드샷 + 자동 발사. | ✅ 예 |

```bash
# 1) 배선 확인 (로봇 필요)
python bt_manual_motor_test.py --hub-name "Team5" --print-sends

# 2) 손 제스처 제어
python gesture_bt_controller.py --hub-name "Team5" --print-sends

# 3) 풍선 / 표적 요격  (데모 주력)
python balloon_intercept.py --hub-name "Team5" --print-sends

# Windows에서는 OpenCV GUI를 메인 스레드에 두는 스레드 변형을 사용
python balloon_intercept_win.py --hub-name "Team5" --print-sends
```

음성 인식/LLM 모드 전환은 Hub 패킷 형식을 바꾸지 않고 Mac/Windows 컨트롤러의
발사 정책으로 구현한다. 기은 쪽 음성 인식 프로세스가 `gesture_bt/control_mode.json`에
`mode` 필드를 포함한 JSON을 써 주면, `balloon_intercept.py`와
`balloon_intercept_win.py`가 이를 읽어 기존 `M,pan,tilt,fire` 명령의 `fire` byte
전송 타이밍만 바꾼다.

준엽 쪽 컨트롤러가 받는 JSON 형태는 아래와 같다. 필수 필드는 `mode` 하나이고,
나머지는 음성 인식/LLM 디버깅 및 발표 시각화용 메타데이터라서 없어도 된다.

```json
{
  "mode": "single",
  "source": "voice",
  "transcript": "단발 모드",
  "confidence": 0.92,
  "updated_at": "2026-06-06T12:00:00+09:00"
}
```

허용 `mode`: `single`, `burst`, `safe`, `guard`.

| Mode | 동작 | Hub에 전달되는 실제 효과 |
|------|------|--------------------------|
| `single` | 표적이 처음 보인 뒤 0.4초 확인되면 1회 발사 | `fire=1`을 한 번만 보냄 |
| `burst` | 표적이 처음 보인 뒤 0.4초 확인되면 반복 발사 시작 | 이후 `--burst-interval`마다 `fire=1` 요청. Hub가 `armed`일 때만 실제 발사 |
| `safe` | 안전/발사 금지 | 조준은 하되 `fire=1`을 보내지 않음 |
| `guard` | 표적 미검출 시 좌우 경계 sweep | `M,pan,tilt,0`에서 pan 값이 좌우로 변함. 표적 발견 시 single 정책 사용 |

구현 파일:

- `gesture_bt/fire_mode_control.py`: JSON payload 생성/읽기/쓰기, mode 정규화, fallback 처리.
- `gesture_bt/control_mode.json`: 음성 인식 모듈이 써야 하는 예시 입력 파일.
- `gesture_bt/balloon_intercept.py`: macOS/기본 컨트롤러에 `single`, `burst`, `safe`, `guard` 반영.
- `gesture_bt/balloon_intercept_win.py`: Windows 스레드 변형에도 동일 모드 정책 반영.
- `tests/test_fire_mode_control.py`: JSON schema, metadata, fallback, writer 테스트.

주의: Hub는 모드 문자열을 직접 알지 못한다. Hub에는 기존 4바이트 `M,pan,tilt,fire`만
전달되고, 모드에 따른 판단은 노트북 컨트롤러가 수행한다. 따라서 발사 후 C 모터 재장전
상태머신(`armed -> firing -> returning -> armed`)도 기존 Hub 코드 그대로 유지된다.

```bash
# 터미널 1: 요격 컨트롤러 실행
python balloon_intercept.py --hub-name "Team5" --control-mode-file control_mode.json --print-sends

# 터미널 2: 음성 인식 대신 수동으로 모드 변경 테스트
echo '{"mode":"single"}' > control_mode.json   # 0.4초 확인 후 정밀 단발
echo '{"mode":"burst"}'  > control_mode.json   # 0.4초 확인 후 --burst-interval마다 반복 발사
echo '{"mode":"safe"}'   > control_mode.json   # 발사 금지
echo '{"mode":"guard"}'  > control_mode.json   # 표적 미검출 시 좌우 sweep 경계 모드
```

기은님 음성 인식 모듈을 붙일 때는 두 번째 터미널에서 `voice_commander.py`를 실행한다.
기본값은 오작동 방지를 위해 먼저 `Hey you` 호출어를 들은 뒤 다음 문장을 명령으로 처리한다.
이 프로세스가 마이크 음성을 `single`, `burst`, `safe`, `guard`로 해석해 같은
`control_mode.json`에 기록하고, 요격 루프는 다음 프레임부터 변경된 모드를 읽는다.

```bash
# 필요 시 음성 인식 의존성 설치. PyAudio는 OS별로 별도 설치가 필요할 수 있음.
python -m pip install -r requirements_gesture_bt.txt
python -m pip install pyaudio

# 터미널 2: 실제 마이크 음성 명령 -> control_mode.json
# 기본 동작: "Hey you" 호출어 후 다음 문장을 명령으로 처리
python voice_commander.py --control-mode-file control_mode.json --language en-US

# 호출어 없이 모든 인식 문장을 바로 명령으로 처리하고 싶으면
python voice_commander.py --control-mode-file control_mode.json --no-wake-word --language en-US

# 한국어 명령으로 테스트하고 싶으면
python voice_commander.py --control-mode-file control_mode.json --language ko-KR

# 마이크 없이 JSON 연동만 빠르게 확인
python voice_commander.py --control-mode-file control_mode.json --dry-run-text "연발 모드"
```

지원 명령 예시:

- `single`, `one`, `precision`, `단발`, `한 발`, `정밀` → `single`
- `burst`, `auto`, `fire at will`, `연발`, `연사`, `자동` → `burst`
- `safe`, `stop`, `cease`, `안전`, `정지`, `사격 중지` → `safe`
- `guard`, `search`, `patrol`, `경계`, `수색`, `레이더` → `guard`

주의: Hub에는 모드 문자열이 직접 전송되지 않고, 기존 4바이트 `M,pan,tilt,fire`
프로토콜만 유지된다. 음성 모듈은 JSON만 쓰고, 실제 발사 타이밍 판단은
`balloon_intercept.py`/`balloon_intercept_win.py`가 수행한다.

관련 옵션: `--default-fire-mode`, `--target-visible-seconds`, `--burst-interval`,
`--fire-debug`, `--guard-sweep-pan`, `--guard-sweep-speed`, `--control-mode-file`.
`--target-visible-seconds`의 기본값은 0.4초이며, 표적이 사라지면 타이머가 리셋된다.

연발이 안 될 때는 먼저 아래처럼 **카메라/표적 인식 루프를 우회**해서 Hub와 C 모터가
반복 발사 요청을 실제로 처리하는지 확인한다.

```bash
python burst_fire_diagnostic.py --hub-name "Team5" --shots 5 --interval 1.0 --print-sends --debug-rx
```

해석:

- `[SEND] M,0,0,1`이 반복되고 Hub 로그에 `FIRE_REQ`, `SHOT`, `RETURNING`, `ARMED`,
  `FIRED`가 반복되면 Hub/C 모터는 정상이고, 문제는 카메라 lock 조건이나 모드 JSON 쪽이다.
- `[SEND] M,0,0,1`은 반복되는데 Hub의 `FIRE_REQ`/`SHOT`이 부족하면 C 모터가 아직
  `armed`로 복귀하지 않았거나 포트/기계 장전 문제가 있다. 이때는 `--interval 1.2`처럼
  간격을 늘려 본다.
- 직접 진단은 성공하지만 `balloon_intercept.py`에서만 연발이 안 되면 아래처럼 실행해서
  어떤 조건이 막는지 본다.

```bash
python balloon_intercept.py \
  --hub-name "Team5" \
  --control-mode-file control_mode.json \
  --default-fire-mode burst \
  --target-visible-seconds 0.4 \
  --burst-interval 1.0 \
  --fire-debug \
  --print-sends \
  --debug-rx
```

`[FIRE-DEBUG]`의 주요 reason:

- `visible_warmup`: 표적이 화면에 잡혔지만 아직 `--target-visible-seconds`만큼 유지되지 않았다.
- `target_not_visible`: 표적이 현재 화면에서 사라져 0.4초 타이머가 리셋되었다.
- `cooldown`: burst 모드에서 `--burst-interval` 대기 중이다.
- `no_fire_flag`: `--no-fire`로 실행 중이라 fire=1을 막고 있다.
- `hub_program_stopped`: Hub 사용자 프로그램이 STOPPED 상태라 fire=1을 억제했다.
- `ready`: 다음 전송에서 `fire=1` 요청이 나가야 한다.

> 현재 업로드 경로는 실제 로봇에서 검증된 실행 경로다. Hub 전원을 켜고
> Pybricks Code/SPIKE App 연결을 끊은 뒤, Mac 스크립트가 저장된 Hub 프로그램을
> 자동 시작하게 둔다.

> **Windows / 로봇 없는 변형.** Windows에서는 `gesture_bt_controller_win.py` 또는
> `balloon_intercept_win.py`를 실행한다 — Bleak BLE 루프를 백그라운드 스레드에서
> 돌리고 OpenCV를 메인 스레드에 두어 Windows COM 스레딩 충돌을 피한다. 로봇 없이
> 비전/예측을 개발하려면 `balloon_tracker_offline.py`, `hand_tracker_offline.py`가
> BLE 없이 카메라만으로 동작한다.

---

## 📦 저장소 구조

```text
gesture_bt/
  pybricks_ble.py                    # 공유 BLE 스캔 / 재연결 / readiness / 진단
  fire_mode_control.py               # JSON 기반 single/burst/safe/guard 발사 모드 정책
  bt_manual_motor_test.py            # 카메라 없이 BLE + 모터 경로 테스트
  bt_verify_restart_shot.py          # 발사 + 강제 재시작 검증
  camera_check.py                    # macOS/OpenCV 카메라 권한 확인
  hub_angle_reader.py                # 홈 캘리브레이션용 D/F/C 절대 각도 읽기
  calibrate_angle_regression.py      # 기록된 명중점으로 픽셀→팬/틸트 각도 보정식 피팅
  gesture_bt_controller.py           # 손 제스처 컨트롤러 (macOS / 단일 asyncio 루프)
  gesture_bt_controller_win.py       # Windows 변형: Bleak는 백그라운드 스레드, OpenCV는 메인 스레드
  balloon_intercept.py               # HSV 탐지 + 포물선 예측 + 자동 발사
  balloon_intercept_win.py           # balloon_intercept의 Windows 스레드 변형
  hub_pybricks_gesture_server.py     # Hub 측 BLE 서버 + 모터 상태 머신
  hub_pybricks_gesture_server_bak.py # 이전 Hub 서버 빌드 백업본
  requirements_gesture_bt.txt

balloon_tracker_offline.py           # 로봇 없이 도는 3D 물리 풍선 트래커 (카메라 + 마우스 HSV 스포이드)
hand_tracker_offline.py              # 로봇 없이 도는 MediaPipe 손/제스처 테스터
balloon_aimbot_design.md             # 풍선 궤적 + 자동조준 설계 노트 (공기저항, 리드샷)
models/
  hand_landmarker.task               # 오프라인 / Windows 용으로 동봉한 MediaPipe 모델

docs/                                # 심화 기술 문서 (영문 + ko/)
  ARCHITECTURE.md  PROTOCOL.md  STATE_MACHINES.md  PREDICTION.md
```

macOS 스크립트(`gesture_bt_controller.py`, `balloon_intercept.py`)는 최초 실행 시
MediaPipe hand-landmarker 모델을 `gesture_bt/models/`에 다운로드하며 이 경로는
Git에서 무시된다. 오프라인 도구와 Windows 스레드 변형이 다운로드 없이 동작하도록
저장소 루트 `models/hand_landmarker.task`에 사본을 커밋해 둔다. 발사 캘리브레이션
중 생성되는 `gesture_bt/aim_dataset.csv`는 Git에서 무시된다. 로컬 하네스 파일,
가상환경, 다른 사이드 프로젝트도 무시하여 팀원/교수/TA가 보는 GitHub 저장소를
실행 코드와 문서 중심으로 유지한다.

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
| 0 | opcode | `M` = 이동/발사. Hub 정지는 Pybricks 원격 `STOP` 사용; stdin `S`는 legacy 용도 |
| 1 | `pan_err_i8` | signed pan 오차 `[-100, 100]`, `value & 0xFF`로 인코딩 |
| 2 | `tilt_err_i8` | signed tilt 오차 `[-100, 100]`, `value & 0xFF`로 인코딩 |
| 3 | `fire` | `1`이면 발사 1회 래치, 평소 `0` |

현재 Hub runner는 `reset_angle()`을 호출하지 않는다. 대신 Team5 로봇에서 측정한
절대 홈 기준값을 사용한다: F 포트 `PAN_HOME=-172`, D 포트 `TILT_HOME=-20`,
C 포트 `C_HOME=43`. Mac의 signed 명령은 카메라 offset으로 변환한 뒤
`HOME + offset`으로 적용한다:

```python
pan_offset  = clamp(pan_val / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_offset = clamp((tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
pan_motor.track_target(PAN_HOME + pan_offset)
tilt_motor.track_target(TILT_HOME + tilt_offset)
```

Hub는 시작 시점과 각 패킷 처리 후 `rdy`를 보낸다. Mac이 `[Hub] ...`로 출력하는
상태 라인은 `HOME_CHECK`, `SERVER_VERSION`, `READY`, `ARMED`, `FIRE_REQ`,
`SPINUP`, `SHOT f=... d=...`, `FIRING`, `RETURNING`, `FIRED`이다.

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
[START] sent remote START command to Hub.
[STATUS] Hub user program: RUNNING
[READY] rdy received.
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,0,0,1   -> b'M\x00\x00\x01'
[Hub] FIRE_REQ → SPINUP → SHOT f=... d=... → FIRING → RETURNING → ARMED → FIRED
```

홈 위치만 확인:

```bash
python bt_manual_motor_test.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 \
  --home-only --home-seconds 6 --home-pan 0 --home-tilt -100
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
python balloon_intercept.py --hub-name "Team5" --print-sends
```

HSV로 빨간 표적을 감지하고, EMA로 부드럽게 추정한 속도 + 수직 가속도로 미래
탄착점을 예측한다. 자동 발사는 한 표적 1발 상태기계로 동작한다:
`TRACKING -> LOCKED -> FIRED_FOR_TARGET -> REARM_WAIT`. 예측점이 lock window 안에
`--fire-confirm-frames` 프레임 연속 들어올 때만 `fire=1`을 보내며, 발사 후 같은
연속 표적에는 `--target-lost-rearm`초 동안 사라지기 전까지 조준 명령만 보낸다.

| 옵션 | 목적 |
|------|------|
| `--flight-time` | 포물선 예측에 쓰는 발사체 도달 예상 시간 |
| `--fire-px` | 화면 중심 lock window 픽셀 크기 |
| `--fire-confirm-frames` | 발사 전 lock window 안에 연속으로 들어와야 하는 프레임 수(기본 `2`) |
| `--target-lost-rearm` | 다음 발사를 허용하기 위해 표적이 사라져야 하는 시간(기본 `0.5`) |
| `--no-fire` | `fire=1` 없이 추적/조준만 수행 |
| `--min-area` | 빨간 contour 최소 면적 |
| `--send-interval` | BLE 명령 최소 전송 간격 |
| `--post-recovery-replay` | BLE/Hub 복구 직후 aim-only replay 시간; `fire=1`은 재전송하지 않음 |
| `--control-mode-file` | 음성 인식/LLM 프로세스가 쓰는 모드 JSON 파일 경로 |
| `--default-fire-mode` | JSON 파일이 없을 때 사용할 기본 모드: `single`, `burst`, `safe`, `guard` |
| `--burst-interval` | `burst` 모드에서 반복 `fire=1` 요청 사이 최소 시간 |
| `--guard-sweep-pan` / `--guard-sweep-speed` | `guard` 모드에서 표적 미검출 시 좌우 탐색 sweep 범위/속도 |
| `--dataset` / `--no-dataset` | `SHOT`과 결합한 캘리브레이션 row를 `aim_dataset.csv`에 저장/비활성화 |
| `--camera`, `--width`, `--height` | 카메라 인덱스와 프레임 크기 |
| `--no-auto-start` | Mac 측 원격 START 비활성화 |
| `--connect-timeout` | BLE 연결 타임아웃(초, 기본 `45`) |
| `--connect-attempts` | 포기 전 BLE 스캔/연결 재시도 횟수(기본 `5`) |
| `--keep-hub-running` | 카메라 스크립트 종료 후에도 Hub 프로그램 유지(기본은 `STOP` 전송으로 재실행 준비) |

### 4. 모드 JSON 단위 테스트 / 로봇 없는 검증

로봇 없이도 이번 브랜치의 핵심 로직은 아래 명령으로 검증할 수 있다.

```bash
# 저장소 루트에서 실행
python3 -m py_compile gesture_bt/*.py
python3 -m unittest tests.test_fire_mode_control -v
git diff --check
```

예상 결과:

```text
Ran 6 tests ...
OK
```

로봇 없이 `control_mode.json` 입출력 형태만 확인하려면:

```bash
cd gesture_bt
python3 - <<'PY'
from fire_mode_control import write_control_mode, read_control_mode
write_control_mode("control_mode.json", "BURST", source="voice", transcript="연발 모드", confidence=0.95)
print(read_control_mode("control_mode.json"))
PY
# 출력: burst
```

카메라/Hub 연결 전에는 `--no-fire`로 화면 overlay와 모드 전환 로그만 확인할 수 있다.

```bash
python balloon_intercept.py --no-fire --control-mode-file control_mode.json --print-sends
```

Windows에서는 같은 JSON 파일을 대상으로 아래처럼 실행한다.

```powershell
python balloon_intercept_win.py --no-fire --control-mode-file control_mode.json --print-sends
'{"mode":"guard","source":"manual","transcript":"경계 모드"}' | Set-Content control_mode.json
```

### 5. 발사와 재연결 검증

```bash
# 단발 발사 검증
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10 --skip-forced-stop

# 강제 STOP 후 자동 복구 + 발사 검증
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10
```

통과 로그에는 `SERVER_VERSION gesture_server_2026_06_03_fire_spinup_state`,
`SHOT f=... d=...`, `RETURNING`, `ARMED`, `FIRED`가 포함된다.

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
| 4바이트 프로토콜 + `rdy` 흐름 제어 | ✅ | P2 |
| Hub 파서 자가 복구 + stdin flush | ✅ | P2 |
| Hub 절대 홈 캘리브레이션 (`F=-172`, `D=-20`, `C=43`) | ✅ | P2 · P5 |
| 수동 BLE 모터 테스트 | ✅ | P2 |
| 손 제스처 제어 + 주먹 발사 래치 | ✅ | P3 · P2 |
| 풍선/표적 HSV 요격 + 포물선 예측 | ✅ | P3 · P4 |
| 한 표적 1발 자동 발사 FSM | ✅ | P2 · P4 |
| Mac 측 원격 START + `rdy` 흐름 제어 | ✅ | P2 |
| 재연결 replay 보호: aim-only, `fire=1` 재전송 없음 | ✅ | P2 |
| `SHOT f/d` 기반 발사 캘리브레이션 데이터 로깅 | ✅ | P5 |
| 음성/LLM JSON 기반 `single`/`burst`/`safe`/`guard` 모드 전환 | ✅ | P2 |
| Windows 풍선 요격 컨트롤러 모드 전환 대응 | ✅ | P2 |
| 팀 역할 + README 대시보드 + 문서 | ✅ | P5 |
| 카메라-포탑 캘리브레이션 회귀 | 🔜 | P5 · P2 |
| 결정적 녹화 영상 리플레이 하네스 | 🔜 | P5 |
| 표적 강건성 (면적 게이트, 연속 추적, 소실 복구) | ⬜ | P3 |
| 체공 시간 + 지연 캘리브레이션 | ⬜ | P4 · P5 |
| 평가 로깅 (명중률, 오차, 세션 CSV) | ⬜ | P5 |
| 최종 보고서 그림 + 데모 | ⬜ | 전원 |

## ✅ 할 일 상세 (우선순위 순)

| # | 항목 | 담당 | 중요한 이유 | 기기? |
|:-:|------|:----:|------------|:----:|
| 1 | **카메라-포탑 캘리브레이션 회귀** | P5 · P2 | 이제 `SHOT f/d` row가 기록된다. 다음 단계는 충분한 샘플을 모아 픽셀→각도 보정식을 맞추는 것이다. 정확도를 가장 크게 좌우한다. | 🔴 예 |
| 2 | **녹화 영상 리플레이 하네스** | P5 | 결정적 클립 리플레이 모드를 추가하면 P3/P4가 동일 입력에서 감지/예측 변경을 비교할 수 있다. | 🟢 아니오 |
| 3 | **표적 강건성** | P3 | 최소/최대 면적 게이팅, 프레임 간 연속성, 소실 복구로 false lock과 오발을 줄인다. | 🟢 아니오 |
| 4 | **체공 시간 / 지연 캘리브레이션** | P4 · P5 | BLE + 처리 + 발사체 지연이 올바른 리드를 결정한다. 측정하여 예측기에 반영한다. | 🔴 예 |
| 5 | **평가 로깅** | P5 | 명중/실패, 예측 오차, 실험 조건을 CSV로 — 최종 보고서 근거. | 🟡 부분 |
| 6 | **최종 통합 & 데모** | 전원 | 데모 조건에서 Hub + 카메라 + 표적 + 발사기 전체 루프 검증. | 🔴 예 |

## 🤝 로봇 1대 기준 팀 워크플로우

기기 없이 가능한 일은 병렬로, 단일 로봇은 짧은 슬롯으로 예약한다.

| 단계 | 🔴 로봇 슬롯 | 🟢 로봇 없이 병렬 진행 |
|------|------------|---------------------|
| **1. 구동** | P1/P2: 배선, Hub 업로드, `bt_manual_motor_test.py` | P3 HSV 튜닝, P4 영상 기반 예측, P5 문서 |
| **2. 캘리브레이션** | P2/P5: sign, gain, threshold | P3 감지 강건성, P4 리드/지연 모델 |
| **3. 통합** | 전원: 예약된 end-to-end 테스트 | P5 결과 로깅, P3/P4 녹화 데이터 기반 튜닝 |
| **4. 보고서/데모** | 최종 리허설 | P5 README/보고서 그림 + 데모 설명 정리 |

> 💡 로봇 슬롯은 배선, 캘리브레이션, 실사격에 집중 배정하라. 비전/예측 변경은
> 가능한 한 저장된 카메라 클립 기준으로 개발한다.

---

## 🛠️ 문제 해결

| 증상 | 가능 원인 | 조치 |
|------|----------|------|
| `[SCAN] no matching Hub` | 앱이 점유 중, Hub 꺼짐, 이름 불일치 | Pybricks Code/SPIKE 앱 연결 해제, Hub 재부팅, 재시도 (이름 실패 후 UUID fallback 실행) |
| 연결 후 `STOPPED` 반복 | 저장된 Hub 프로그램 미실행 | 기본 스크립트는 원격 `START`를 자동 전송한다. `[START] sent remote START command to Hub.` 로그 확인 |
| 실행 도중 멈췄다가 다시 진행 | Hub 프로그램 종료 후 Mac이 자동 복구 | 정상 동작: Mac이 `START` 재전송(`[RECOVER] ... sending remote START`) 후 다음 `rdy`에 재개 |
| 첫 연결 실패, 두 번째 성공 | 첫 시도에서 BLE 스캔/연결 불안정 | 기본 3회 재시도로 예상되는 동작. 계속되면 `--connect-attempts`/`--connect-timeout` 상향 |
| `[BLE] connected`인데 `[READY]` 없음 | Hub 프로그램이 `rdy`를 보내지 않음 | `--auto-start` 기본값 유지, Pybricks Code/SPIKE App 연결 해제, Hub 재부팅 후 재시도 |
| `[WAIT] Hub not sending rdy` | Hub 프로그램이 아직 시작/응답하지 않음 | `--debug-rx`로 재시도. 수동 중앙 버튼 진단 때만 `--no-auto-start` 사용 |
| Pybricks Code 사용 후 `READY`가 안 보임 | Pybricks Code가 BLE를 점유 중이거나 Hub가 advertising하지 않음 | Pybricks Code 연결 해제, Hub 전원 재시작, Team5 advertising을 기다린 뒤 Mac 스크립트 실행 |
| `[STALE] Hub is silent` | 링크는 살아있으나 Hub 프로그램 정지/크래시 | 자동 복구가 원격 `START`를 보내게 둔다. 반복되면 Hub 전원 재시작 후 현재 Hub 코드를 다시 업로드 |
| `[DISCONNECT]` / `[RECONNECT]` | BLE 링크 끊김 | Hub를 가까이·전원 유지; `--no-reconnect`가 아니면 3초마다 재스캔 |
| 모터가 반대쪽을 가리킴 | 카메라-모터 매핑 불일치 | Mac의 `pixel_to_motor_vals()`와 Hub의 `PAN_MIN/PAN_MAX`, `TILT_MIN/TILT_MAX` 확인 |
| 모터 범위가 너무 작거나 큼 | 각도 범위 불일치 | `hub_pybricks_gesture_server.py`의 `PAN_MIN/PAN_MAX`, `TILT_MIN/TILT_MAX` 조정 |
| macOS 카메라 미동작 | 카메라 권한 없음 | Terminal/iTerm/VS Code 카메라 권한 허용 |

---

*2026-06-03 Team5 Hub에서 Mac 측 원격 START, 강제 STOP 복구, 단발 발사 로그로
검증. 방향: Pybricks BLE 직결 제어. 저장소 범위: `gesture_bt/`, `docs/`, 루트
오프라인 도구(`*_offline.py`), `balloon_aimbot_design.md`,
`models/hand_landmarker.task`, `README*.md`. 가상환경, bytecode cache, local log,
generated dataset, 최초 실행 시 받는 `gesture_bt/models/` 다운로드는 업로드하지 않음.*
