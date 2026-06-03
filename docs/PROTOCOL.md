# Pybricks BLE Protocol

Mac-side Python writes to the Pybricks command/event characteristic:

```text
c5f50002-8280-46da-89f4-6d8051e4aeef
```

Pybricks expects a leading `0x06` command prefix on writes. After that prefix,
the Hub program consumes 4-byte packets.

## Packet Format

| Byte | Field | Meaning |
|------|-------|---------|
| 0 | opcode | `M` for motion/fire. Hub stop uses the Pybricks remote `STOP`; stdin `S` is legacy only |
| 1 | `pan_err_i8` | signed pan error encoded as `value & 0xFF` |
| 2 | `tilt_err_i8` | signed tilt error encoded as `value & 0xFF` |
| 3 | `fire` | `1` triggers one firing cycle, `0` otherwise |

Examples:

```text
M,100,0,0  -> b'\x06' + b'M\x64\x00\x00'
M,0,0,1    -> b'\x06' + b'M\x00\x00\x01'
```

## Control Rule

The Hub does not reset motor angles at startup. It uses calibrated absolute
home readings from the Team5 robot (`PAN_HOME=-172`, `TILT_HOME=-20`,
`C_HOME=43`) and applies Mac command values as camera offsets on top of home.

```python
pan_offset  = clamp(pan_val / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_offset = clamp((tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
pan_motor.track_target(PAN_HOME + pan_offset)
tilt_motor.track_target(TILT_HOME + tilt_offset)
```

## Flow Control

The Hub replies with `rdy` at startup and after processing each packet. The Mac
sender waits for readiness before sending the next packet, can remote-start a
stopped saved program, and reconnects/rescans after BLE link loss. Recovery
replay in `balloon_intercept.py` is aim-only; `fire=1` is never replayed.

Hub status lines include `HOME_CHECK`, `SERVER_VERSION`, `READY`, `ARMED`,
`FIRE_REQ`, `SPINUP`, `SHOT f=... d=...`, `FIRING`, `RETURNING`, and `FIRED`.

## Mac BLE Diagnostics

All Mac-side tools use `gesture_bt/pybricks_ble.py`. The shared client first
scans by exact Hub name and then falls back to the Pybricks service UUID. It
prints connection state with stable prefixes:

| Prefix | Meaning |
|--------|---------|
| `[SCAN]` | Name scan, UUID fallback, or no matching Hub |
| `[BLE]` | BLE connected, skipped send, or write failure |
| `[NOTIFY]` | Pybricks command/event notifications started |
| `[READY]` | First or reconnect `rdy` received |
| `[WAIT]` | BLE is connected but Hub readiness is missing |
| `[STALE]` | Hub stopped sending readiness/status notifications |
| `[DISCONNECT]` / `[RECONNECT]` | Link loss and automatic rescan |
