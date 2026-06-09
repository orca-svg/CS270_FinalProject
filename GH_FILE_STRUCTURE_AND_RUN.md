# GitHub 파일 구조와 실행 방법 정리

이 문서는 GitHub `origin/main`에 올라가 있는 Gesture-BT 프로젝트의 파일 구조와, 실제 실행할 때 신경 써야 하는 파일만 간단히 정리한 것이다.

## 1. GitHub 파일 구조

GitHub `origin/main` 기준 구조:

```text
CS270_FinalProject/
├── README.md
├── README.ko.md
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PREDICTION.md
│   ├── PROTOCOL.md
│   ├── STATE_MACHINES.md
│   └── ko/
│       ├── ARCHITECTURE.md
│       ├── PREDICTION.md
│       ├── PROTOCOL.md
│       └── STATE_MACHINES.md
└── gesture_bt/
    ├── requirements_gesture_bt.txt
    ├── pybricks_ble.py
    ├── hub_pybricks_gesture_server.py
    ├── bt_manual_motor_test.py
    ├── bt_verify_restart_shot.py
    ├── balloon_intercept.py
    ├── gesture_bt_controller.py
    ├── camera_check.py
    ├── hub_angle_reader.py
    └── calibrate_angle_regression.py
```

## 2. 실행할 때 실제로 신경 쓸 파일

평소 실행에서 중요한 파일은 아래 6개다.

```text
gesture_bt/
├── hub_pybricks_gesture_server.py   # Pybricks Code에 올릴 Hub 코드
├── bt_manual_motor_test.py          # 1차 연결/홈/D-F/발사 기본 테스트
├── bt_verify_restart_shot.py        # 발사 + 재연결 복구 검증
├── camera_check.py                  # Mac 카메라 권한 확인
├── balloon_intercept.py             # 최종 자동 요격 실행
└── pybricks_ble.py                  # 공용 BLE 모듈, 직접 실행하지 않음
```

## 3. 로컬 실행 경로

기존 실행 경로를 그대로 쓰면 된다.

```bash
cd /Users/junyeop_lee/Desktop/kaist/2026_S/지로설/gesture_bt
source .venv/bin/activate
```

현재 이 경로는 GitHub main 워크트리의 `gesture_bt`로 연결되어 있다.

```text
/Users/junyeop_lee/Desktop/kaist/2026_S/지로설/gesture_bt
  -> ../CS270_FinalProject_publish/gesture_bt
```

따라서 위 경로에서 실행하면 GitHub main 기준 코드가 실행된다.

## 4. Hub에 올릴 파일

Pybricks Code에 올릴 파일은 하나다.

```text
hub_pybricks_gesture_server.py
```

주의:

- Pybricks Code에 파일을 저장한 뒤 Mac script 실행 전 Pybricks Code/SPIKE App 연결을 끊는다.
- Mac script가 Hub 프로그램을 remote START한다.
- Hub 중앙 버튼으로 직접 시작하는 방식은 진단용으로만 생각한다.

## 5. 기본 실행 순서

전체 실행은 아래 순서로 하면 된다.

```text
1. Hub 코드 업로드
2. 홈/기본 연결 확인
3. 발사 검증
4. 카메라 확인
5. 자동 요격 실행
```

## 6. 홈/기본 연결 확인

```bash
python bt_manual_motor_test.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 \
  --home-only --home-seconds 6 --home-pan 0 --home-tilt -100
```

확인할 것:

```text
[BLE] connected to Team5
[START] sent remote START command to Hub.
[READY] rdy received.
HOME_CHECK ... expected pan=-172 tilt=-20 c=43
```

## 7. 단발 발사 검증

```bash
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10 --skip-forced-stop
```

성공 로그:

```text
[VERIFY] PASS: received SHOT f=<angle> d=<angle> and ARMED
```

## 8. 강제 STOP 후 복구 + 발사 검증

연결 복구까지 확인하고 싶으면 아래 명령을 실행한다.

```bash
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10
```

성공 조건:

```text
STOPPED 상태 감지
remote START 복구
SHOT f=... d=...
ARMED
FIRED
```

## 9. 카메라 확인

```bash
python camera_check.py
```

카메라가 열리지 않으면 macOS 설정에서 Terminal/iTerm/VS Code의 Camera 권한을 허용한다.

## 10. 자동 요격 실행

발사 없이 카메라와 D/F 조준만 확인:

```bash
python balloon_intercept.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --scan-timeout 20 --no-fire
```

자동 발사 포함:

```bash
python balloon_intercept.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --scan-timeout 20 \
  --fire-confirm-frames 2 --target-lost-rearm 0.5
```

## 11. 실행 시 고려할 핵심 사항

아래만 기억하면 된다.

```text
1. Hub에는 hub_pybricks_gesture_server.py만 업로드한다.
2. Mac 실행은 지로설/gesture_bt에서 한다.
3. Pybricks Code/SPIKE App 연결은 Mac script 실행 전에 끊는다.
4. pybricks_ble.py는 직접 실행하지 않는다.
5. .venv, models/, aim_dataset.csv는 로컬 실행용이며 GitHub에는 올라가지 않는다.
6. 자동 실행 순서는 bt_manual_motor_test.py -> bt_verify_restart_shot.py -> camera_check.py -> balloon_intercept.py 이다.
```

## 12. 보조 파일의 역할

| 파일 | 역할 | 평소 실행 필요 여부 |
|------|------|------------------|
| `pybricks_ble.py` | BLE 연결/START/STOP/reconnect 공용 모듈 | 직접 실행하지 않음 |
| `gesture_bt_controller.py` | 손 제스처 제어 실험용 | 선택 |
| `hub_angle_reader.py` | 손으로 맞춘 D/F/C 각도 읽기 | 캘리브레이션 때만 |
| `calibrate_angle_regression.py` | `aim_dataset.csv` 기반 보정 회귀 | 데이터가 쌓인 뒤 |
| `requirements_gesture_bt.txt` | Python dependency 목록 | 초기 설치 때만 |

## 13. 가장 짧은 기준

최소 기준은 아래 한 줄이다.

```text
Hub에는 hub_pybricks_gesture_server.py만 올리고, Mac에서는 bt_manual_motor_test.py -> bt_verify_restart_shot.py -> camera_check.py -> balloon_intercept.py 순서로 실행한다.
```

