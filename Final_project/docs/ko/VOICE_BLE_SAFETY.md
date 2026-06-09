# 음성-BLE-Hub 안전성 보강 기록

## 1. 프로젝트 방향 변화

초기 음성 제어는 온라인 음성 API가 인식한 모드를 JSON에 기록하는 구조였다. 최종
프로젝트에서는 인터넷 상태와 API 지연에 덜 의존하고 카메라 프레임 처리를 막지 않도록
다음 구조로 변경했다.

```text
마이크
  -> macOS MLX Whisper / Windows faster-whisper
  -> control_mode.json
  -> 카메라 추적 및 발사 정책
  -> Pybricks BLE
  -> Prime Hub의 M,pan,tilt,fire 처리
```

음성 인식과 카메라는 별도 프로세스로 실행한다. 따라서 Whisper 추론 중에도 카메라 루프는
계속 동작한다. Hub 프로토콜은 변경하지 않고 기존 4바이트 `M,pan,tilt,fire`를 유지한다.
음성은 Hub를 직접 조작하지 않고 노트북의 발사 정책만 변경한다.

## 2. 이번에 결정한 사항

| 항목 | 결정 |
|---|---|
| 호출명 | `옵티머스`, `옵티 머스`, Whisper 영문 전사 `Optimus` |
| 발사 confidence | `single`, `burst`는 0.60 이상 |
| 비발사 명령 | `safe`, `guard`는 confidence 제한 없이 적용 |
| heartbeat | 음성 프로세스가 2초마다 갱신 |
| 모드 TTL | 10초 동안 heartbeat가 없으면 자동 `SAFE` |
| 시작·종료 | 모델 로딩 전과 정상/예외 종료 시 `SAFE` 기록 |
| 만료 복구 | 같은 `command_id` heartbeat만으로 복구하지 않고 새 명령 요구 |
| BLE 재연결 | 대기 중인 `fire=1`을 폐기하고 표적을 0.4초부터 재확인 |
| Windows 큐 | 모드 변경 시 발사 요청을 제거하고 최신 `fire=0`만 유지 |
| Hub 검증 | 서버 버전과 A/B/C/D/F 포트, `RUNNING`, `rdy` 확인 |
| 검증 우회 | 실패 시 `y/N`; `y`를 선택하면 현재 실행 동안 유지 |
| 발사 휠 | Hub 프로그램 실행 중 A/B 휠을 계속 100% 회전 |

`SAFE`는 C 모터 격발을 막지만 A/B 발사 휠을 정지시키지 않는다. Hub 전원이 켜지고
프로그램이 실행 중인 동안 발사 휠이 회전할 수 있으므로 물리적 접근 전에 Hub 프로그램을
종료하거나 전원을 내려야 한다.

## 3. 실제 적용 방식

### 음성 프로세스

음성 프로세스는 `control_mode.json.lock`에 OS 파일 잠금을 획득한다. MLX, Windows
faster-whisper, 기존 온라인 음성 프로세스 중 하나가 실행 중이면 두 번째 프로세스는
파일을 덮지 않고 종료한다.

잠금 획득 직후 모델을 불러오기 전에 `SAFE`를 기록한다. 명령을 받으면 새로운
`command_id`를 만들고, heartbeat는 같은 명령의 `heartbeat_at`만 갱신한다. JSON은 같은
디렉터리의 임시 파일에 완전히 쓴 뒤 `os.replace()`로 교체한다.

```json
{
  "mode": "single",
  "session_id": "음성 프로세스 UUID",
  "command_id": "명령 UUID",
  "updated_at": "명령이 결정된 시각",
  "heartbeat_at": "최근 생존 갱신 시각",
  "source": "voice-local-mlx-whisper",
  "transcript": "Optimus, 발사",
  "confidence": 0.86
}
```

`single` 또는 `burst`가 0.60 미만이면 JSON을 변경하지 않는다. 호출 상태는 유지되므로
사용자는 `옵티머스`를 반복하지 않고 명령만 다시 말할 수 있다. `멈춰`, `안전`은
confidence와 관계없이 즉시 `SAFE`로 처리한다.

### 카메라 컨트롤러

macOS와 Windows 컨트롤러는 CLI 값이나 기존 JSON과 관계없이 `SAFE`로 시작한다.
정상 JSON을 읽은 뒤에만 선택된 모드로 전환한다.

- heartbeat가 10초 이상 오래되면 `SAFE`
- JSON이 일시적으로 깨지면 마지막 정상 모드를 TTL까지 유지
- TTL 만료 후 같은 `command_id`가 다시 heartbeat를 보내도 `SAFE` 유지
- 새로운 음성 명령의 `command_id`가 들어와야 다시 활성화

모드가 바뀌면 `fire_pending`, 표적 잠금, 단발/연발 상태를 초기화한다. Windows는 BLE
큐도 비우고 최신 `M,pan,tilt,0` 조준 명령만 남긴다.

### BLE 재연결

BLE 단절이나 쓰기 실패 후 기존 `fire=1`은 재전송하지 않는다. 재연결되면 최신
`fire=0` 조준만 복원하고, 표적을 다시 0.4초 연속 검출한 뒤 새로운 발사 요청을 만든다.
연결 세대마다 Hub 검증이 끝나기 전에는 명령 전송을 허용하지 않는다.

### Hub 검증

Hub 시작 로그에서 다음 항목을 수집한다.

```text
SERVER_VERSION gesture_server_2026_06_03_fire_spinup_state
PORT_A_OK
PORT_B_OK
PORT_C_OK
PORT_D_TILT_OK
PORT_F_PAN_OK
```

추가로 Pybricks 상태가 `RUNNING`이고 `rdy`가 수신됐는지 확인한다. 하나라도 실패하면
`Continue with this unverified Hub for this run? [y/N]:`를 표시한다. Enter 또는 `N`은
종료하고, `y`는 현재 노트북 프로그램이 끝날 때까지 검증 우회를 유지한다.

## 4. 사용자가 수행한 작업

이번 프로젝트에서 사용자가 진행하고 결정한 작업은 다음과 같이 정리할 수 있다.

1. 온라인 API 중심 음성 인식을 Apple Silicon의 MLX Whisper 로컬 추론으로 전환했다.
2. Windows에서도 동일한 명령 구조를 쓰도록 faster-whisper CPU/GPU 경로를 구성했다.
3. 카메라 빨간색 검출 범위와 작은 픽셀 노이즈 제거 처리를 macOS와 Windows에 맞췄다.
4. `발사`, `연발`, `멈춰`, `경계` 등 자연어 명령과 안전 명령 우선순위를 정의했다.
5. 호출명을 `옵티머스`로 변경하고 실제 Whisper의 `Optimus` 전사 변형을 반영했다.
6. 음성 명령이 오래되거나 프로세스가 종료될 때 자동으로 `SAFE`가 되는 정책을 결정했다.
7. BLE 재연결 시 이전 발사 요청을 버리고 표적을 다시 확인하도록 결정했다.
8. Prime Hub 서버 버전과 모터 포트를 연결 때마다 검증하도록 결정했다.
9. 발사 휠은 시연 반응 속도를 위해 계속 회전시키되 물리적 주의사항을 명시했다.
10. 자동 테스트와 macOS/Windows 단계별 실행 문서를 프로젝트에 정리했다.

## 5. 한계와 후속 검증

- Windows 실기에서 faster-whisper CPU `int8`, 마이크 장치, BLE 스레드를 함께 검증해야 한다.
- 실제 Prime Hub에서 연결 중 전원 차단과 재연결을 반복해 발사 요청이 재생되지 않는지 확인해야 한다.
- 음성 프로세스를 `burst` 상태에서 강제 종료하고 10초 안에 `SAFE`로 바뀌는지 확인해야 한다.
- 실제 교실 소음에서 confidence 0.60의 오거부와 오인식 비율을 측정해야 한다.
- 발사 휠 상시 회전으로 인한 배터리 소모, 발열, 물리적 접촉 위험을 관리해야 한다.

### 실기 체크리스트

- [ ] Hub에 최신 `hub_pybricks_gesture_server.py` 저장
- [ ] A/B/C/D/F 포트가 모두 `OK`
- [ ] `[HUB-VALID]` 성공 로그 확인
- [ ] 음성 프로세스 시작 즉시 JSON이 `safe`
- [ ] `옵티머스 발사`가 confidence 0.60 이상에서만 `single`
- [ ] `옵티머스 멈춰`가 즉시 `safe`
- [ ] 음성 프로세스 강제 종료 후 10초 내 화면 모드가 `SAFE`
- [ ] `burst` 중 BLE 단절 후 재연결 직후 발사하지 않음
- [ ] 재연결 후 표적 0.4초 재확인
- [ ] Windows 모드 변경 시 이전 큐의 발사 요청이 실행되지 않음

