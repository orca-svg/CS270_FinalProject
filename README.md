[한국어 README](README.ko.md)

# CS270 Final Project — LEGO SPIKE Gesture-Controlled Launcher

Real-time hand-gesture BLE control system for a LEGO SPIKE Prime pan-tilt launcher.
A Mac running MediaPipe hand tracking sends motor commands over BLE to the Hub, which accumulates a target angle, tracks it, and fires on a fist gesture.

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

Upload `gesture_bt/hub_pybricks_gesture_server.py` via [Pybricks Code](https://code.pybricks.com).
Position the robot at the zero/loaded state before running: pan, tilt, and the C
motor all call `reset_angle(0)` at startup, so the physical pose at launch becomes
the 0° reference (pan/tilt center, C motor loaded). Press the Hub center button to start.

### 2. Mac

```bash
cd gesture_bt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

Dependencies (`requirements_gesture_bt.txt`):

```text
opencv-python
mediapipe>=0.10.30
numpy
bleak
```

The MediaPipe Hand Landmarker model is downloaded automatically on first run if
`gesture_bt/models/hand_landmarker.task` is not already present.

### 3. Manual BLE test (no camera)

```bash
python bt_manual_motor_test.py --hub-name "Team5"
```

Press the Hub center button when BLE connects and wait for `[Hub] READY`. The
script drives a fixed sequence of pan/tilt target pushes and one fire, confirming
motor wiring before using the camera. Default `--hub-name` is `Team5`.

### 4. Gesture control

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

Common command-line options (from `build_parser`):

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

| Gesture / Key | Action |
|---------------|--------|
| Open palm | Pan/tilt tracking: palm offset from frame center → pan_err/tilt_err |
| Closed fist (open→fist transition) | Fire once (edge-detected, latched until next send) |
| `q` | Quit and send STOP |

## BLE Protocol

Mac → Hub: 4-byte fixed packet, written to the Pybricks command characteristic
(`c5f50002-8280-46da-89f4-6d8051e4aeef`) with a leading `0x06` Pybricks prefix.
The packet layout is built by `PybricksBleSender._packet_for` and parsed on the
Hub in the main loop.

| Byte | Field | Description |
|------|-------|-------------|
| 0 | Opcode | `M` (`0x4D`) = motor command, `S` (`0x53`) = stop and exit |
| 1 | pan_err | int8 sent as `value & 0xFF`, clamped to [−100, +100] |
| 2 | tilt_err | int8 sent as `value & 0xFF`, clamped to [−100, +100] |
| 3 | fire | 0 or 1 (1 latches a shot on the Hub) |

The `S` opcode is sent as `b"S\x00\x00\x00"` and stops all motors, exiting the
Hub loop.

Hub → Mac: the Hub replies `b"rdy"` once at startup and again after each received
4-byte packet. The Mac waits on this `rdy` (an `asyncio.Event`) before sending the
next packet, giving simple one-in-flight flow control. Status lines such as
`READY`, `ARMED`, `FIRING`, `RETURNING`, and `FIRED` are sent as newline-terminated
text and printed as `[Hub] ...`.

## Architecture Notes

Derived directly from `hub_pybricks_gesture_server.py` and `gesture_bt_controller.py`.

**Target-accumulation tracking (Hub)**: each `M` packet nudges an internal target
angle rather than commanding a raw speed:

```
pan_target  = clamp(pan_target  − PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target − TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

The Hub then calls `pan_motor.track_target(int(pan_target))` /
`tilt_motor.track_target(int(tilt_target))` every loop iteration (~5 ms wait).

**C-motor fire state machine (reciprocating)**:

```
armed → firing (dc +C_FIRE_DC to C_FIRE_ANGLE°) → returning (dc −C_RETURN_DC to 0°) → armed
```

`armed` waits for `can_fire`; `firing` advances until the angle reaches
`C_FIRE_ANGLE − C_TOLERANCE`; `returning` reverses until the angle is within
`C_TOLERANCE` of 0°, at which point the shot is reported `FIRED` and the latch clears.

**Fire latch**: on the Mac, `fire=1` is edge-detected on the open→fist transition
(`pending_fire`) and held until the next send interval, so a fist is sent exactly
once per gesture regardless of frame timing.

**Safety timeout**: if no packet arrives within `COMMAND_TIMEOUT_MS`, the Hub
resets `pan_target` and `tilt_target` to 0 (re-centers).

**Emergency stop**: pressing any Hub button exits the loop; the Mac sends STOP on
`q` or on shutdown.

**BLE deadlock recovery**: the Hub sends a periodic `rdy` heartbeat every
`RDY_INTERVAL_MS` (200 ms) even when no packet arrives, so a single dropped `rdy`
does not permanently stall the Mac's `asyncio.Event` wait.

**Crash resilience**: motor operations inside the Hub loop are wrapped in
per-block `try/except`, and `main()` is wrapped in a top-level `try/except
BaseException` that always runs `stop_all()` and shows `X` on the display.

## Motion Constants (Hub)

Values quoted verbatim from the constant block in
`gesture_bt/hub_pybricks_gesture_server.py`.

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
