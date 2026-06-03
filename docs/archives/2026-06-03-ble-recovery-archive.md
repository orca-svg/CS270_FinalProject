# 2026-06-03 Gesture-BT BLE Recovery Archive

## Baseline Commit

```text
db20895 Harden Gesture-BT fire recovery flow
```

Archive issue:

```text
https://github.com/orca-svg/CS270_FinalProject/issues/3
```

## Baseline Root Causes

- Hub could be connected over BLE while the saved user program was STOPPED.
- D/F motor home drifted when the Hub program restarted from an arbitrary physical pose.
- Automatic fire could repeat on one continuous target.
- Reconnect replay needed to avoid re-sending `fire=1`.
- Fire calibration needed actual Hub F/D angles joined with Mac target context.

## Baseline Fixes

- Mac remote START/reconnect recovery in `pybricks_ble.py`.
- Absolute home references in Hub code:
  - `PAN_HOME=-172`
  - `TILT_HOME=-20`
  - `C_HOME=43`
- Hub fire sequence:
  - `FIRE_REQ`
  - `SPINUP`
  - `SHOT f=... d=...`
  - `FIRING`
  - `RETURNING`
  - `ARMED`
  - `FIRED`
- One-shot-per-target FSM in `balloon_intercept.py`.
- Aim-only replay after recovery.
- `aim_dataset.csv` generation from Mac context and Hub `SHOT f/d`.

## Follow-up Issue

```text
https://github.com/orca-svg/CS270_FinalProject/issues/4
```

Newly observed follow-up:

- BLE can reconnect while Hub program remains RUNNING.
- Startup `rdy` is not re-emitted because the program did not restart.
- Mac waits for `rdy` before writing stdin.
- Hub waits for stdin before emitting the next post-packet `rdy`.
- Result: handshake deadlock.

## Follow-up Fix Direction

- Hub emits a throttled `rdy` heartbeat while RUNNING.
- Mac can send one harmless priming stdin packet if RUNNING but `rdy` is missing.
- Gesture controller resends latest aim after recovery and preserves fire latch if send fails.

## Verification Policy

Static checks:

```bash
python3 -m py_compile gesture_bt/pybricks_ble.py gesture_bt/balloon_intercept.py gesture_bt/gesture_bt_controller.py gesture_bt/hub_pybricks_gesture_server.py gesture_bt/bt_manual_motor_test.py gesture_bt/bt_verify_restart_shot.py
python3 - <<'PY'
from gesture_bt.pybricks_ble import packet_for
assert packet_for("M,0,-100,1") == b"M\\x00\\x9c\\x01"
assert packet_for("M,3,-5,1") == b"M\\x03\\xfb\\x01"
print("packet protocol ok")
PY
```

Hardware checks when a Hub is available:

```bash
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10 --skip-forced-stop

python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10
```
