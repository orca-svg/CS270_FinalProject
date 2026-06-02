[한국어 README](README.ko.md)

# CS270 Final Project — LEGO SPIKE Auto-Aiming Launcher

Real-time computer-vision aimbot for a LEGO SPIKE Prime pan-tilt launcher.
A Mac with a **fixed webcam** detects a red object, predicts its parabolic
trajectory, converts the predicted screen position into **absolute pan/tilt motor
angles**, and fires automatically when the target is aligned — all over BLE to a
Pybricks Hub.

> **Design note — camera and motors are independent.** The webcam is mounted
> separately from the turret and does **not** move with the pan/tilt motors.
> The controller therefore maps each pixel position to an *absolute* motor angle
> (not an incremental correction). See [How It Works](#how-it-works) and
> [Roadmap](#current-progress--roadmap).

## Quick Start

```bash
# 1. Clone and enter the gesture_bt directory
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

# 2. Create a virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt

# 3. Manual BLE + motor test (Hub must be running)
python bt_manual_motor_test.py --hub-name "Team5"

# 4. Full aimbot mode
python gesture_bt_controller.py
```

## Repository Structure

```text
gesture_bt/
  gesture_bt_controller.py       # Mac-side: red-object tracker + parabolic predictor + auto-fire
  hub_pybricks_gesture_server.py # Hub-side: Pybricks BLE server + motor state machine
  bt_manual_motor_test.py        # Manual BLE motor test (no camera)
  requirements_gesture_bt.txt    # Mac-side Python dependencies
  models/                        # (legacy) MediaPipe model — no longer used by controller

Final_project/
  calibration_targeting.py       # Calibration-based aiming prototype (see Roadmap)
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

Port assignments from `hub_pybricks_gesture_server.py`:

| Port | Motor | Role |
|------|-------|------|
| A | `launch_l` | Left launcher wheel (PWM +100) |
| B | `launch_r` | Right launcher wheel (PWM −100, opposite direction) |
| C | `c_motor` | Fire/reload mechanism (reciprocating) |
| D | `tilt_motor` | Tilt axis (0°–80°) |
| F | `pan_motor` | Pan axis (−35°–+35°) |

Missing motors are tolerated: each port is probed with `safe_motor`, which logs
`PORT_<label>_OK` or `PORT_<label>_MISSING` and returns `None` on failure.

## How It Works

### Controller (`gesture_bt_controller.py`)

The aimbot loop runs at camera frame rate (640×480) and does five things each frame:

**1. Red object detection (HSV color masking)**

```python
mask1 = cv2.inRange(hsv, [0,  120, 70], [10,  255, 255])   # lower red hue
mask2 = cv2.inRange(hsv, [170,120, 70], [180, 255, 255])   # upper red hue
```

The largest red contour above 500 px² is the target. A green bounding box and
center dot are drawn on the preview.

**2. Velocity + acceleration estimation**

```
vx = (target_x - prev_x) / dt        # raw velocity (px/s)
vy = (target_y - prev_y) / dt

vx_smooth = SMOOTHING * vx + (1-SMOOTHING) * vx_smooth     # EMA filter
vy_smooth = SMOOTHING * vy + (1-SMOOTHING) * vy_smooth

ay = (vy_smooth - prev_vy) / dt      # raw vertical acceleration
ay_smooth = ACCEL_SMOOTHING * ay + (1-ACCEL_SMOOTHING) * ay_smooth
```

**3. Parabolic intercept prediction**

```
predict_x = target_x + vx_smooth * FLIGHT_TIME
predict_y = target_y + vy_smooth * FLIGHT_TIME + 0.5 * ay_smooth * FLIGHT_TIME²
```

The predicted point is visualised with a red circle and a yellow line from the
current position.

**4. Pixel → absolute motor angle (fixed-camera mapping)**

Because the camera is fixed and the motors move independently, the predicted
pixel is mapped directly to an absolute motor angle by `pixel_to_motor_vals()`:

```
pan:  px = 0 (left)   → −35°      px = 640 (right)  → +35°
tilt: py = 0 (top)    →  80° (up) py = 480 (bottom) →  0° (down)
```

Both values are normalised to the BLE byte range `[-100, +100]` before sending.

**5. Aim and auto-fire**

```
if abs(predict_x - CENTER_X) < FIRE_PX and abs(predict_y - CENTER_Y) < FIRE_PX:
    fire_trigger = 1     # "FIRE!!!" shown on preview
```

Every `SEND_INTERVAL` (100 ms) the Mac sends `M, pan_val, tilt_val, fire_trigger`
(4-byte packet) to the Hub. The Hub sets the absolute target angle and fires the
C-motor state machine on `fire=1`.

### Tuning Constants

Edit these at the top of `gesture_bt_controller.py`. **`PAN_MAX_DEG` /
`TILT_MIN_DEG` / `TILT_MAX_DEG` must match the Hub constants exactly.**

| Constant | Default | Description |
|----------|---------|-------------|
| `HUB_NAME` | `"Team5"` | Pybricks BLE hub name |
| `PAN_MAX_DEG` | `35` | Pan range ±deg (must equal Hub `PAN_MAX`) |
| `TILT_MIN_DEG` / `TILT_MAX_DEG` | `0` / `80` | Tilt range (must equal Hub `TILT_MIN`/`TILT_MAX`) |
| `FLIGHT_TIME` | `0.4` s | Estimated projectile flight time; increase for longer range |
| `SMOOTHING` | `0.3` | Velocity EMA weight (higher = faster but noisier) |
| `ACCEL_SMOOTHING` | `0.05` | Acceleration EMA weight (keep low to suppress noise) |
| `FIRE_PX` | `20` px | Auto-fire when predicted error < this on both axes |
| `SEND_INTERVAL` | `0.1` s | BLE command rate |

## Setup

### 1. Hub (Pybricks)

1. Go to [Pybricks Code](https://code.pybricks.com) and connect to the SPIKE Hub.
2. Upload `gesture_bt/hub_pybricks_gesture_server.py`.
3. **Position the robot at the zero/loaded state**: pan, tilt, and the C motor all
   call `reset_angle(0)` at startup, so the physical pose at launch becomes the
   reference (pan center, tilt down at 0°, C motor fully loaded).
4. Run once to verify `READY` and `rdy` appear; then Stop and **disconnect
   Pybricks Code** so the Mac BLE client can connect.
5. The Hub program starts when you press the Hub center button.

### 2. Mac — Install dependencies

```bash
cd CS270_FinalProject/gesture_bt
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

> `mediapipe` is listed for compatibility. The aimbot controller does **not**
> use MediaPipe; it uses OpenCV HSV color masking only.

### 3. Manual BLE test (no camera)

With the Hub running its saved program, confirm BLE + motor wiring:

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
...
[SEND] M,0,0,1 -> b'M\x00\x00\x01'
[Hub] FIRING
[Hub] RETURNING
[Hub] ARMED
[Hub] FIRED
Manual motor test done.
```

### 4. Aimbot mode

```bash
python gesture_bt_controller.py
```

The hub name is hardcoded as `HUB_NAME = "Team5"` in the script. Edit it if your
Hub has a different name.

When BLE connects, press the Hub center button. A camera preview window titled
**"Aimbot System (Parabolic Prediction)"** appears. Hold or throw a **red object**
in front of the camera:

- A green box tracks the detected object.
- A yellow line shows the predicted intercept point (red circle).
- **"FIRE!!!"** appears when the predicted point is within `FIRE_PX` of the frame
  center and `fire=1` is sent to the Hub.
- Press `q` to quit.

## Current Progress & Roadmap

### Done ✅

- 4-byte BLE protocol with `rdy` flow control + 200 ms heartbeat (deadlock recovery)
- Hub firmware: per-block `try/except`, top-level crash guard, safety timeout
- Manual motor test path (`bt_manual_motor_test.py`)
- Red-object detection (HSV masking, largest-contour selection)
- Parabolic prediction (velocity + vertical acceleration, EMA-smoothed)
- **Fixed-camera → absolute motor-angle mapping** (independent camera/turret)
- C-motor reciprocating fire state machine with auto-fire trigger

### Next steps 🔜 (priority order)

| # | Item | Why it matters | Device needed? |
|---|------|----------------|----------------|
| 1 | **Camera↔turret calibration** | The current pixel→angle map is a *linear guess*. Because the camera is independent of the turret, a target at pixel (px,py) does not trivially correspond to a motor angle. A calibration step (sample known targets, fit a mapping) is the biggest accuracy lever. Repo already has `Final_project/calibration_targeting.py` + `CALIBRATION_IMPLEMENTATION_PLAN.md` to build on. | Yes (slots) |
| 2 | **Add `--no-ble` / camera-only mode** | The controller currently *requires* the robot to run. A no-BLE mode lets vision/prediction work proceed on a laptop without monopolising the single device — unblocks parallel teamwork. | No |
| 3 | **FLIGHT_TIME / drop calibration** | One hardcoded constant. Measure real projectile flight time and (optionally) make it distance-dependent for accurate lead. | Yes (slots) |
| 4 | **Latency compensation** | BLE + processing delay adds to effective lead time. Measure end-to-end latency and fold it into the prediction horizon. | Yes (slots) |
| 5 | **CLI args** | Hub name, camera index, and HSV range are hardcoded. Add `argparse` so each team member can run without editing source. | No |
| 6 | **Target robustness** | Add min/max area gating, tracking continuity across frames, and lost-target recovery to reduce false locks. | No |
| 7 | **Evaluation & logging** | Log hit rate and prediction error to CSV for the final report; design a repeatable test target. | Partial |

## Team Workflow (5 members, 1 shared device)

**Defined roles**

| Member | Role | Focus |
|--------|------|-------|
| P1 | Hardware Engineer | Robot build, launcher mechanism, motor mounting, wiring |
| P2 | HW↔SW Integration | Hub firmware, BLE protocol, calibration bridge, fire timing |

**Suggested roles for the remaining three**

| Member | Role | Focus |
|--------|------|-------|
| P3 | Vision Engineer | Red detection robustness, target tracking (roadmap #6) |
| P4 | Prediction / Algorithm | Parabolic model, FLIGHT_TIME, latency comp, lead-shot math (roadmap #3, #4) |
| P5 | Calibration & Test / Docs | Calibration procedure (#1), evaluation harness (#7), run device sessions, docs |

### Parallel vs. sequential — the single-device constraint

Only **one robot exists**, so device-dependent work must be **time-shared in
booked slots**, while device-free work runs fully in parallel.

**Device-FREE work — anyone, anytime, in parallel (no robot):**

- Vision tuning on recorded clips / live webcam — *requires roadmap #2 (`--no-ble` mode)*
- Prediction algorithm development & offline validation
- Pixel→angle math and calibration-model design
- CLI args, logging/evaluation harness, documentation & report

**Device-DEPENDENT work — must reserve the robot (one team at a time):**

- HW build & mechanical tuning (P1)
- Hub firmware flash + BLE/motor bring-up (P2)
- Live angle calibration (P2 + P5)
- FLIGHT_TIME measurement & live firing tests (P4 + P5)
- End-to-end integration runs (all)

### Suggested phased schedule

| Phase | Has the device | Working in parallel (no device) |
|-------|----------------|--------------------------------|
| **1. Build & bring-up** | P1 builds robot; P2 flashes firmware & runs `bt_manual_motor_test.py` in short slots | P3 vision on webcam, P4 prediction on recorded video, P5 builds `--no-ble` mode (#2) + calibration plan |
| **2. Calibration** | P2 + P5 run calibration sessions (#1) | P3/P4 keep refining offline; P5 finalises eval harness (#7) |
| **3. Integration & tuning** | Scheduled slots for end-to-end runs, FLIGHT_TIME (#3) & latency (#4) | Whoever is not on the device tunes constants from logged data and writes the report |

> **Tip:** Do as much as possible device-free. Landing roadmap #2 (`--no-ble`
> mode) early multiplies the team's effective throughput, since 3 of 5 members
> can then make progress without ever touching the robot.

## BLE Protocol

Mac → Hub: 4-byte fixed packet, written to the Pybricks command characteristic
(`c5f50002-8280-46da-89f4-6d8051e4aeef`) with a leading `0x06` Pybricks prefix.

| Byte | Field | Description |
|------|-------|-------------|
| 0 | Opcode | `M` (`0x4D`) = motor command, `S` (`0x53`) = stop and exit |
| 1 | pan_val | Absolute pan angle, `[-100, +100]` → `[PAN_MIN, PAN_MAX]`, sent as `value & 0xFF` |
| 2 | tilt_val | Absolute tilt angle, `[-100, +100]` → `[TILT_MIN, TILT_MAX]`, sent as `value & 0xFF` |
| 3 | fire | 0 normally, 1 when predicted error < `FIRE_PX` on both axes |

Hub → Mac: the Hub replies `b"rdy"` after each packet. The Mac waits on this
before sending the next packet (1 s timeout, silently skipped on failure).
Status lines (`READY`, `ARMED`, `FIRING`, `RETURNING`, `FIRED`) are printed
as `[Hub] ...`.

## Architecture Notes

**Absolute-angle motor control (Hub).** Each `M` packet sets the target angle
directly (no accumulation), reflecting the fixed-camera design:

```
pan_target  = clamp(pan_val  / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_target = clamp((tilt_val + 100) / 200.0 * (TILT_MAX − TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
```

The Hub then calls `pan_motor.track_target()` / `tilt_motor.track_target()` every
loop iteration (~5 ms wait).

**C-motor fire state machine (reciprocating):**

```
armed → firing (+C_FIRE_DC to C_FIRE_ANGLE°) → returning (−C_RETURN_DC to 0°) → armed
```

**Safety timeout:** if no packet arrives within 1000 ms, the Hub re-centers
pan/tilt targets.

**Emergency stop:** pressing any Hub button exits the loop; the Mac sends a zero
packet on shutdown.

**BLE deadlock recovery:** the Hub sends a periodic `rdy` heartbeat every 200 ms
even when idle, so a single dropped notification does not permanently stall the
Mac's `asyncio.Event` wait.

## Motion Constants (Hub)

| Constant | Value | Description |
|----------|-------|-------------|
| `PAN_MIN` / `PAN_MAX` | −35 / 35° | Pan target travel limits |
| `TILT_MIN` / `TILT_MAX` | 0 / 80° | Tilt target travel limits |
| `PAN_SPEED` | 600 deg/s | Pan tracking speed |
| `TILT_SPEED` | 500 deg/s | Tilt tracking speed |
| `COMMAND_TIMEOUT_MS` | 1000 ms | Re-centers pan/tilt if no command received |
| `C_FIRE_ANGLE` | 170° | C-motor fire (release) position |
| `C_FIRE_DC` | 80 | Forward (fire) duty-cycle % |
| `C_RETURN_DC` | 50 | Reverse (reload) duty-cycle % |
| `C_TOLERANCE` | 3° | Angle tolerance for state transitions |
| `LAUNCH_PWM_A` | 100 | Port A launcher-wheel PWM |
| `LAUNCH_PWM_B` | −100 | Port B launcher-wheel PWM (opposite direction) |
