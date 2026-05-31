# CS270 Final Project — LEGO SPIKE Gesture-Controlled Launcher

Real-time hand-gesture BLE control system for a LEGO SPIKE Prime pan-tilt launcher.
A Mac running MediaPipe hand tracking sends motor commands over BLE to the Hub, which tracks the target and fires on fist gesture.

## Repository Structure

```text
gesture_bt/
  gesture_bt_controller.py       # Mac-side: MediaPipe hand detection + BLE sender
  hub_pybricks_gesture_server.py # Hub-side: Pybricks BLE server + motor state machine
  bt_manual_motor_test.py        # Manual BLE motor test (no camera)
  requirements_gesture_bt.txt    # Mac-side Python dependencies
  models/
    hand_landmarker.task         # MediaPipe hand landmark model

Final_project/
  calibration_targeting.py       # Earlier calibration-based aiming prototype
  q_learning_aim_trainer.py      # Q-learning aiming prototype (backup)
  rl_hub_runner.py               # SPIKE Hub command runner
  hand_follow_controller.py      # Hand-follow prototype
  CALIBRATION_IMPLEMENTATION_PLAN.md
  README_Q_LEARNING.md
  HAND_FOLLOW_TEST.md
```

## Hardware

- LEGO SPIKE Prime Hub (Pybricks firmware)
- Port A/B: launcher wheels (opposite directions)
- Port C: fire mechanism (reciprocating)
- Port D: tilt motor
- Port F: pan motor

## Setup

### 1. Hub (Pybricks)

Upload `gesture_bt/hub_pybricks_gesture_server.py` via [Pybricks Code](https://code.pybricks.com).
Position the robot at the zero/loaded state before running. Press the center button to start.

### 2. Mac

```bash
cd gesture_bt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

### 3. Manual BLE test (no camera)

```bash
python bt_manual_motor_test.py --hub-name "Team5"
```

Press the Hub center button when BLE connects. Confirms motor wiring before using the camera.

### 4. Gesture control

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

| Gesture | Action |
|---------|--------|
| Open palm | Pan/tilt tracking (hand position → error signal) |
| Closed fist (transition) | Fire once |

## BLE Protocol

Mac → Hub: 4-byte fixed packet (after `0x06` Pybricks prefix)

| Byte | Field | Description |
|------|-------|-------------|
| 0 | Opcode | `M` = motor command, `S` = stop |
| 1 | pan_err | Signed int8, –100 to +100 |
| 2 | tilt_err | Signed int8, –100 to +100 |
| 3 | fire | 0 or 1 |

Hub → Mac: `b"rdy"` after each received packet, plus heartbeat every 200 ms.

## Architecture Notes

**Hub state machine (C motor)**

```
armed → firing (dc 80% forward to 150°) → returning (dc 50% reverse to 0°) → armed
```

**Fire latch**: `fire=1` is edge-detected on the Mac (open→fist transition) and latched until the next send interval, preventing timing-related misses.

**BLE deadlock recovery**: Hub sends a periodic `rdy` heartbeat every 200 ms regardless of incoming packets, so a single dropped `rdy` does not permanently stall communication.

**Crash resilience**: Motor exceptions inside the Hub loop are caught per-block so a transient motor fault does not crash the program. All exceptions at the top level are caught to ensure `stop_all()` always runs.

## Motion Constants (Hub)

| Constant | Value | Description |
|----------|-------|-------------|
| `GAIN` | 0.05 | Degrees of target change per 1 unit of error per packet |
| `PAN_MIN/MAX` | –35 / +35° | Pan travel limits |
| `TILT_MIN/MAX` | 0 / 80° | Tilt travel limits |
| `PAN_SPEED` | 600 deg/s | Pan tracking speed |
| `TILT_SPEED` | 500 deg/s | Tilt tracking speed |
| `C_FIRE_ANGLE` | 150° | Fire position for C motor |
| `COMMAND_TIMEOUT_MS` | 1000 ms | Centers pan/tilt if no command received |
