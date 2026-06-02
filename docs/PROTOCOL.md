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
| 0 | opcode | `M` for motion/fire, `S` for stop |
| 1 | `pan_err_i8` | signed pan error encoded as `value & 0xFF` |
| 2 | `tilt_err_i8` | signed tilt error encoded as `value & 0xFF` |
| 3 | `fire` | `1` triggers one firing cycle, `0` otherwise |

Examples:

```text
M,100,0,0  -> b'\x06' + b'M\x64\x00\x00'
M,0,0,1    -> b'\x06' + b'M\x00\x00\x01'
STOP       -> b'\x06' + b'S\x00\x00\x00'
```

## Control Rule

The Hub treats the Mac values as image-space error, not absolute motor angle.

```python
pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

## Flow Control

The Hub replies with `rdy` after processing packets and also emits periodic
heartbeat/status lines. The Mac sender waits for readiness and warns when Hub
notifications become stale.

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
| `[STALE]` | Hub stopped sending heartbeat/status notifications |
| `[DISCONNECT]` / `[RECONNECT]` | Link loss and automatic rescan |
