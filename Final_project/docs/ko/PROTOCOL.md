# Pybricks BLE 프로토콜

Mac 측 Python은 Pybricks command/event characteristic에 쓴다.

```text
c5f50002-8280-46da-89f4-6d8051e4aeef
```

Pybricks write에는 선행 `0x06` prefix가 필요하다. Hub 프로그램은 그 뒤의
4바이트 패킷을 처리한다.

## 패킷 형식

| Byte | Field | 의미 |
|------|-------|------|
| 0 | opcode | `M` = 이동/발사. Hub 정지는 Pybricks 원격 `STOP` 사용; stdin `S`는 legacy 용도 |
| 1 | `pan_err_i8` | signed pan 오차를 `value & 0xFF`로 인코딩 |
| 2 | `tilt_err_i8` | signed tilt 오차를 `value & 0xFF`로 인코딩 |
| 3 | `fire` | `1`이면 발사 1회, 평소 `0` |

예시:

```text
M,100,0,0  -> b'\x06' + b'M\x64\x00\x00'
M,0,0,1    -> b'\x06' + b'M\x00\x00\x01'
```

## 발사 모드

음성 인식/LLM 모드 전환은 Hub의 4바이트 패킷을 바꾸지 않는다. Mac 또는 Windows
컨트롤러가 작은 JSON 파일을 읽고 `fire=1`을 언제 보낼지 결정한다. 기존 `mode` 전용
파일도 호환하지만 현재 음성 프로세스는 명령 식별자와 heartbeat를 함께 기록한다.

```json
{
  "mode": "single",
  "session_id": "음성-프로세스-UUID",
  "command_id": "음성-명령-UUID",
  "source": "voice-local-mlx-whisper",
  "transcript": "단발 모드",
  "confidence": 0.92,
  "updated_at": "2026-06-09T12:00:00+09:00",
  "heartbeat_at": "2026-06-09T12:00:02+09:00"
}
```

음성 프로세스는 `command_id`와 `updated_at`을 유지한 채 2초마다 `heartbeat_at`을
갱신한다. 컨트롤러는 `SAFE`로 시작하며 10초 만료 후 같은 명령의 heartbeat만으로는
복구하지 않는다. JSON은 임시 파일 작성 후 `os.replace()`로 원자적으로 교체한다.

| Mode | 컨트롤러 정책 |
|------|---------------|
| `single` | 표적 lock 후 `fire=1`을 1회 보내고 표적 상실/rearm까지 대기 |
| `burst` | lock 상태에서 `--burst-interval`보다 빠르지 않게 `fire=1` 반복 요청 |
| `safe` | `fire=1`을 보내지 않음 |
| `guard` | 표적 미검출 시 pan sweep; 표적 교전은 single-shot 정책 사용 |

Hub는 여전히 `M,pan,tilt,fire`만 보고, C 모터 상태가 `armed`일 때 `fire == 1`이면
1회 발사한다.

## 제어 규칙

Hub는 시작 시 모터 각도를 reset하지 않는다. Team5 로봇에서 측정한 절대 홈
기준값(`PAN_HOME=-172`, `TILT_HOME=-20`, `C_HOME=43`)을 사용하고, Mac 명령값을
홈 기준 카메라 offset으로 적용한다.

```python
pan_offset  = clamp(pan_val / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_offset = clamp((tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
pan_motor.track_target(PAN_HOME + pan_offset)
tilt_motor.track_target(TILT_HOME + tilt_offset)
```

## 흐름 제어

Hub는 시작 시점과 각 패킷 처리 후 `rdy`를 보낸다. Mac 송신기는 다음 패킷을
보내기 전에 readiness를 기다리고, 저장된 Hub 프로그램이 멈췄으면 원격 START를
보내며, 서버 버전과 A/B/C/D/F 포트를 검증하고, BLE 링크가 끊기면 재스캔/재연결한다.
복구 replay는 aim-only이며 `fire=1`을 폐기하고 표적을 0.4초부터 다시 확인한다.

Hub 상태 라인은 `HOME_CHECK`, `SERVER_VERSION`, `READY`, `ARMED`, `FIRE_REQ`,
`SPINUP`, `SHOT f=... d=...`, `FIRING`, `RETURNING`, `FIRED`를 포함한다.

## Mac BLE 진단

모든 Mac 측 도구는 `gesture_bt/pybricks_ble.py`를 사용한다. 공용 클라이언트는
먼저 정확한 Hub 이름으로 스캔하고, 실패하면 Pybricks service UUID로 fallback한다.
연결 상태는 고정 prefix로 출력한다.

| Prefix | 의미 |
|--------|------|
| `[SCAN]` | 이름 스캔, UUID fallback, Hub 미발견 |
| `[BLE]` | BLE 연결, 송신 생략, write 실패 |
| `[NOTIFY]` | Pybricks command/event notification 시작 |
| `[READY]` | 최초 또는 재연결 후 `rdy` 수신 |
| `[WAIT]` | BLE는 연결됐지만 Hub readiness 미수신 |
| `[STALE]` | Hub readiness/status notification 중단 |
| `[DISCONNECT]` / `[RECONNECT]` | 링크 끊김과 자동 재스캔 |
