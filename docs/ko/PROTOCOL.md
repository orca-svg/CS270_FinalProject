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
| 0 | opcode | `M` = 이동/발사, `S` = 정지 |
| 1 | `pan_err_i8` | signed pan 오차를 `value & 0xFF`로 인코딩 |
| 2 | `tilt_err_i8` | signed tilt 오차를 `value & 0xFF`로 인코딩 |
| 3 | `fire` | `1`이면 발사 1회, 평소 `0` |

예시:

```text
M,100,0,0  -> b'\x06' + b'M\x64\x00\x00'
M,0,0,1    -> b'\x06' + b'M\x00\x00\x01'
STOP       -> b'\x06' + b'S\x00\x00\x00'
```

## 제어 규칙

Hub는 Mac 값을 절대 모터 각도가 아니라 이미지 공간 오차로 처리한다.

```python
pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

## 흐름 제어

Hub는 패킷 처리 후 `rdy`를 보내고 주기적으로 heartbeat/status line을 출력한다.
Mac 송신기는 readiness를 기다리고 Hub notification이 오래 멈추면 경고한다.

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
| `[STALE]` | Hub heartbeat/status notification 중단 |
| `[DISCONNECT]` / `[RECONNECT]` | 링크 끊김과 자동 재스캔 |
