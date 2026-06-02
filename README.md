[한국어 README](README.ko.md)

# CS270 Final Project — LEGO SPIKE Gesture-Controlled Launcher

Real-time hand-gesture BLE control system for a LEGO SPIKE Prime pan-tilt launcher.
A Mac running MediaPipe hand tracking sends motor commands over BLE to the Hub, which accumulates a target angle, tracks it, and fires on a fist gesture.

## Quick Start

```bash
# 1. Clone and enter the gesture_bt directory
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

# 2. Create a virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt

# 3. Test camera + gesture detection WITHOUT connecting to Hub
python gesture_bt_controller.py --dry-run

# 4. Test BLE + motor wiring WITHOUT camera (Hub must be running)
python bt_manual_motor_test.py --hub-name "Team5"

# 5. Full gesture control
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

## Repository Structure

```text
gesture_bt/
  gesture_bt_controller.py       # Mac-side: MediaPipe hand detection + BLE sender
  hub_pybricks_gesture_server.py # Hub-side: Pybricks BLE server + motor state machine
  bt_manual_motor_test.py        # Manual BLE motor test (no camera)
  requirements_gesture_bt.txt    # Mac-side Python dependencies
  models/
    hand_landmarker.task         # MediaPipe hand landmark model (auto-downloaded on first run)

Final_project/
  calibration_targeting.py       # Calibration-based aiming prototype
  q_learning_aim_trainer.py      # Q-learning aiming prototype
  rl_hub_runner.py               # SPIKE Hub command runner
  hand_follow_controller.py      # Hand-follow prototype
  OpenCV.py                      # OpenCV experiment
  ShootingCode.py                # Launcher firing experiment
  CALIBRATION_IMPLEMENTATION_PLAN.md
  README_Q_LEARNING.md
  HAND_FOLLOW_TEST.md

docs/                            # Reserved for project documentation
```

## Hardware

Port assignments are taken directly from the `safe_motor(Port.X, ...)` calls in
`gesture_bt/hub_pybricks_gesture_server.py`.

| Port | Motor | Role |
|------|-------|------|
| A | `launch_l` | Left launcher wheel (PWM +100) |
| B | `launch_r` | Right launcher wheel (PWM −100, opposite direction) |
| C | `c_motor` | Fire/reload mechanism (reciprocating) |
| D | `tilt_motor` | Tilt axis |
| F | `pan_motor` | Pan axis |

Missing motors are tolerated: each port is probed with `safe_motor`, which logs
`PORT_<label>_OK` or `PORT_<label>_MISSING` and returns `None` on failure.

## Setup

### 1. Hub (Pybricks)

1. Go to [Pybricks Code](https://code.pybricks.com) and connect to the SPIKE Hub.
2. Open `gesture_bt/hub_pybricks_gesture_server.py` and upload it to the Hub.
3. **Position the robot at the zero/loaded state before running**: pan, tilt, and the C
   motor all call `reset_angle(0)` at startup, so the physical pose at launch becomes
   the 0° reference (pan/tilt center, C motor fully loaded).
4. Click Run once in Pybricks Code to verify the Hub prints `READY` and `rdy`.
5. Click Stop, then **disconnect Pybricks Code** (the Mac BLE client cannot connect while Pybricks Code holds the connection).
6. When the Mac script connects, press the Hub center button to start the saved program.

### 2. Mac — Install dependencies

```bash
cd CS270_FinalProject/gesture_bt   # or wherever you cloned the repo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

Dependencies:

```text
opencv-python
mediapipe>=0.10.30
numpy
bleak
```

The MediaPipe Hand Landmarker model is downloaded automatically on first run if
`models/hand_landmarker.task` is not already present. An internet connection is
required only for that first download.

### 3. Dry-run test (no Hub needed)

Test camera + gesture detection without any BLE connection:

```bash
python gesture_bt_controller.py --dry-run
```

A camera preview window opens. Commands that would be sent to the Hub are printed
to the terminal instead:

```text
[DRY] M,20,-15,0
[DRY] M,-35,10,0
[DRY] M,0,0,0
```

Use this step to confirm the camera opens, MediaPipe detects your hand, and the
fist gesture registers correctly before connecting to the Hub.

### 4. Manual BLE test (no camera)

With the Hub running its saved program, test BLE + motor wiring:

```bash
python bt_manual_motor_test.py --hub-name "Team5"
```

When the terminal says `BLE connected`, press the Hub center button once.

Expected output:

```text
[Hub] READY
[Hub] ARMED
Hub rdy received. Starting fixed-packet motor test...
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,-100,0,0 -> b'M\x9c\x00\x00'
...
[SEND] M,0,0,1 -> b'M\x00\x00\x01'
[Hub] FIRING
[Hub] RETURNING
[Hub] ARMED
[Hub] FIRED
Manual motor test done.
```

> **Note:** The default `--hub-name` in this script is `Team5`. Adjust to match
> your Hub's Bluetooth name.

### 5. Gesture control

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

When BLE connects, press the Hub center button. A camera preview appears showing
hand landmark tracking.

**Gestures:**

| Gesture | Action |
|---------|--------|
| Open palm in frame | Pan/tilt tracking — palm offset from frame center drives `pan_err`/`tilt_err` |
| No hand detected | Sends `M,0,0,0` after `--no-hand-stop-delay` seconds (default 0.25 s) |
| Closed fist (open→fist transition) | Fires once — `fire=1` is edge-detected and latched until the next send interval |
| Hand in center deadzone | Pan/tilt commands are zero (deadzone = `--deadzone-px`, default 28 px) |

**Keyboard:**

| Key | Action |
|-----|--------|
| `q` | Quit and send STOP to Hub |

> **Note:** The camera overlay displays `c center | f fire | w/x wheels` but those
> keys are **not currently active**. The only keyboard shortcut is `q` to quit.
> Firing is exclusively triggered by the closed-fist gesture.

**Common options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--hub-name` | `Pybricks Hub` | Pybricks BLE hub name to scan for |
| `--dry-run` | off | Skip BLE; print commands only |
| `--print-sends` | off | Print every command/packet sent to the Hub |
| `--scan-timeout` | 15.0 | BLE scan timeout (seconds) |
| `--camera` | 0 | OpenCV camera index |
| `--picamera2` | off | Use Raspberry Pi Picamera2 instead of OpenCV |
| `--width` / `--height` | 640 / 480 | Capture resolution |
| `--mirror` / `--no-mirror` | mirror on | Horizontal flip of the preview/frame |
| `--deadzone-px` | 28 | Center deadzone in pixels |
| `--gain` | 1.0 | Speed gain multiplier |
| `--max-pan-speed` | 70 | Pan speed clamp |
| `--max-tilt-speed` | 80 | Tilt speed clamp |
| `--send-interval` | 0.10 | Minimum seconds between BLE sends |
| `--no-hand-stop-delay` | 0.25 | Seconds with no hand before sending a stop |
| `--min-detection-confidence` | 0.65 | MediaPipe detection threshold |
| `--min-presence-confidence` | 0.65 | MediaPipe presence threshold |
| `--min-tracking-confidence` | 0.65 | MediaPipe tracking threshold |
| `--model-path` | `models/hand_landmarker.task` | Local model file path |
| `--model-url` | MediaPipe float16 model URL | Download source if model is missing |

## Troubleshooting

**`Could not open camera index 0`**
On macOS, go to System Settings → Privacy & Security → Camera and allow access
for Terminal, iTerm2, or your IDE.

**`Could not find 'Team5'`**
- Disconnect Pybricks Code from the Hub.
- Close the LEGO SPIKE app.
- Make sure the Hub is powered on.
- Confirm the Hub's Bluetooth name matches `--hub-name` exactly.

**Hub connects but never sends `rdy` / Mac is stuck waiting**
Press the Hub center button to start the saved program. The Hub only sends `rdy`
after the program starts. If the Hub button LED is off, the program is not running.

**Model download fails on first run**
An internet connection is required for the one-time download of
`models/hand_landmarker.task`. To download it manually, use:

```bash
# macOS / Linux
curl -L -o gesture_bt/models/hand_landmarker.task \
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
```

Or pass `--model-path /path/to/hand_landmarker.task` to use a file you already have.

## BLE Protocol

Mac → Hub: 4-byte fixed packet written to the Pybricks command characteristic
(`c5f50002-8280-46da-89f4-6d8051e4aeef`) with a leading `0x06` Pybricks prefix.

| Byte | Field | Description |
|------|-------|-------------|
| 0 | Opcode | `M` (`0x4D`) = motor command, `S` (`0x53`) = stop and exit |
| 1 | pan_err | int8 sent as `value & 0xFF`, clamped to [−100, +100] |
| 2 | tilt_err | int8 sent as `value & 0xFF`, clamped to [−100, +100] |
| 3 | fire | 0 or 1 (1 latches a shot on the Hub) |

The `S` opcode (`b"S\x00\x00\x00"`) stops all motors and exits the Hub loop.

Hub → Mac: the Hub replies `b"rdy"` once at startup and again after each 4-byte
packet, providing one-in-flight flow control. Status lines (`READY`, `ARMED`,
`FIRING`, `RETURNING`, `FIRED`) are sent as newline-terminated text and printed
as `[Hub] ...`.

## Architecture Notes

**Target-accumulation tracking (Hub)**: each `M` packet nudges an internal target
angle rather than commanding a raw speed:

```
pan_target  = clamp(pan_target  − PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target − TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

The Hub then calls `pan_motor.track_target()` / `tilt_motor.track_target()` every
loop iteration (~5 ms wait).

**C-motor fire state machine (reciprocating)**:

```
armed → firing (dc +C_FIRE_DC to C_FIRE_ANGLE°) → returning (dc −C_RETURN_DC to 0°) → armed
```

**Fire latch**: `fire=1` is edge-detected on the open→fist transition and held
until the next send interval, so one fist gesture = exactly one shot.

**Safety timeout**: if no packet arrives within `COMMAND_TIMEOUT_MS` (1000 ms),
the Hub resets pan/tilt targets to 0.

**BLE deadlock recovery**: the Hub sends a periodic `rdy` heartbeat every
`RDY_INTERVAL_MS` (200 ms) even when idle, preventing permanent stall from a
dropped notification.

**Crash resilience**: motor operations are wrapped in per-block `try/except`;
`main()` is wrapped in `try/except BaseException` that always runs `stop_all()`
and shows `X` on the Hub display.

## Motion Constants (Hub)

| Constant | Value | Description |
|----------|-------|-------------|
| `PAN_SIGN` | 1 | Flip to −1 if pan moves the wrong way |
| `TILT_SIGN` | 1 | Flip to −1 if tilt moves the wrong way |
| `PAN_MIN` / `PAN_MAX` | −35 / 35° | Pan target travel limits |
| `TILT_MIN` / `TILT_MAX` | 0 / 80° | Tilt target travel limits |
| `PAN_SPEED` | 600 deg/s | Pan tracking speed |
| `TILT_SPEED` | 500 deg/s | Tilt tracking speed |
| `GAIN` | 0.05 | Degrees of target change per unit of error per packet |
| `COMMAND_TIMEOUT_MS` | 1000 ms | Re-centers pan/tilt if no command received |
| `C_FIRE_ANGLE` | 170° | C-motor fire (release) position |
| `C_FIRE_DC` | 80 | Forward (fire) duty-cycle % |
| `C_RETURN_DC` | 50 | Reverse (reload) duty-cycle % |
| `C_TOLERANCE` | 3° | Angle tolerance for state transitions |
| `LAUNCH_PWM_A` | 100 | Port A launcher-wheel PWM |
| `LAUNCH_PWM_B` | −100 | Port B launcher-wheel PWM (opposite direction) |
