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

Hub는 시작 시점, 각 패킷 처리 후, 그리고 RUNNING 상태의 throttled heartbeat로
`rdy`를 보낸다. 이 heartbeat는 Hub 프로그램이 계속 RUNNING이라 startup `rdy`가
다시 나오지 않고, Mac은 readiness를 기다리느라 stdin을 쓰지 못하는 reconnect
deadlock을 막는다.

Mac 송신기는 다음 패킷을 보내기 전에 readiness를 기다리고, 저장된 Hub 프로그램이
멈췄으면 원격 START를 보내며, BLE 링크가 끊기면 재스캔/재연결한다. Hub가
RUNNING인데 `rdy`가 없으면 Mac은 harmless priming stdin packet을 한 번 보내고
Hub가 다시 `rdy`를 출력하기를 기다린다. `balloon_intercept.py`의 복구 replay는
aim-only이며 `fire=1`은 재전송하지 않는다.

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
