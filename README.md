[한국어 README](README.ko.md)

# CS270 Final Project — LEGO SPIKE Auto-Aiming Launcher

Real-time computer-vision aimbot for a LEGO SPIKE Prime pan-tilt launcher.
A Mac detects a red object with a camera, predicts its parabolic trajectory,
aims the turret at the predicted intercept point, and fires automatically when
aligned — all over BLE to a Pybricks Hub.

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

Port assignments from `hub_pybricks_gesture_server.py`:

| Port | Motor | Role |
|------|-------|------|
| A | `launch_l` | Left launcher wheel (PWM +100) |
| B | `launch_r` | Right launcher wheel (PWM −100, opposite direction) |
| C | `c_motor` | Fire/reload mechanism (reciprocating) |
| D | `tilt_motor` | Tilt axis |
| F | `pan_motor` | Pan axis |

Missing motors are tolerated: each port is probed with `safe_motor`, which logs
`PORT_<label>_OK` or `PORT_<label>_MISSING` and returns `None` on failure.

## How It Works

### Controller (`gesture_bt_controller.py`)

The aimbot loop runs at camera frame rate (640×480) and does four things each frame:

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

**4. Aim and auto-fire**

```
pan_err  = predict_x - CENTER_X      # pixels from frame center
tilt_err = predict_y - CENTER_Y

if abs(pan_err) < 20 and abs(tilt_err) < 20:
    fire_trigger = 1     # "FIRE!!!" shown on preview
```

Every 100 ms the Mac sends `M, -pan_err, tilt_err, fire_trigger` (4-byte packet)
to the Hub over BLE. The Hub accumulates a target angle and fires the C-motor
state machine on `fire=1`.

### Tuning Constants

Edit these at the top of `gesture_bt_controller.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `HUB_NAME` | `"Team5"` | Pybricks BLE hub name |
| `FLIGHT_TIME` | `0.4` s | Estimated rubber-band flight time; increase for longer range |
| `SMOOTHING` | `0.3` | Velocity EMA weight (higher = faster but noisier) |
| `ACCEL_SMOOTHING` | `0.05` | Acceleration EMA weight (keep low to suppress noise) |
| Fire deadzone | `20` px | Auto-fire when predicted error < 20 px on both axes |
| Send interval | `0.1` s | BLE command rate |

## Setup

### 1. Hub (Pybricks)

1. Go to [Pybricks Code](https://code.pybricks.com) and connect to the SPIKE Hub.
2. Upload `gesture_bt/hub_pybricks_gesture_server.py`.
3. **Position the robot at the zero/loaded state**: pan, tilt, and the C motor all
   call `reset_angle(0)` at startup, so the physical pose at launch becomes the
   reference (pan/tilt center, C motor fully loaded).
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
- **"FIRE!!!"** appears when the predicted point is within 20 px of the frame center
  and `fire=1` is sent to the Hub.
- Press `q` to quit.

## Troubleshooting

**`BLE 로봇을 찾을 수 없습니다`**
- Disconnect Pybricks Code from the Hub.
- Close the LEGO SPIKE app.
- Make sure the Hub is powered on.
- Confirm `HUB_NAME` in the script matches your Hub's Bluetooth name exactly.

**Hub connects but never fires**
- The C motor (`safe_motor(Port.C, "C")`) must be connected and at the loaded
  position (angle 0) when the Hub program starts.
- Press the Hub center button to start the saved program after BLE connects.
- Check `[Hub] ARMED` appears — if `PORT_C_MISSING` appears, the C motor is not
  wired to Port C.

**Red object not detected**
- Use a clearly red object under good lighting.
- The HSV ranges are `[0,120,70]–[10,255,255]` (lower red) and
  `[170,120,70]–[180,255,255]` (upper red). Adjust if your lighting shifts the hue.
- The minimum contour area is 500 px²; bring the object closer if it reads as too small.

**Camera not opening**
On macOS, go to System Settings → Privacy & Security → Camera and allow access
for Terminal, iTerm2, or your IDE.

## BLE Protocol

Mac → Hub: 4-byte fixed packet, written to the Pybricks command characteristic
(`c5f50002-8280-46da-89f4-6d8051e4aeef`) with a leading `0x06` Pybricks prefix.

| Byte | Field | Description |
|------|-------|-------------|
| 0 | Opcode | `M` (`0x4D`) = motor command, `S` (`0x53`) = stop and exit |
| 1 | pan_err | `−pan_err` clamped to [−100, +100], sent as `value & 0xFF` |
| 2 | tilt_err | `tilt_err` clamped to [−100, +100], sent as `value & 0xFF` |
| 3 | fire | 0 normally, 1 when predicted error < 20 px on both axes |

Hub → Mac: the Hub replies `b"rdy"` after each packet. The Mac waits on this
before sending the next packet (1 s timeout, silently skipped on failure).
Status lines (`READY`, `ARMED`, `FIRING`, `RETURNING`, `FIRED`) are printed
as `[Hub] ...`.

## Architecture Notes

**Hub motor control** is unchanged from the original gesture controller: target
angles accumulate per packet and `track_target()` runs every ~5 ms.

**C-motor fire state machine (reciprocating)**:

```
armed → firing (+C_FIRE_DC to C_FIRE_ANGLE°) → returning (−C_RETURN_DC to 0°) → armed
```

**Safety timeout**: if no packet arrives within 1000 ms, the Hub re-centers
pan/tilt targets.

**Emergency stop**: pressing any Hub button exits the loop; the Mac sends a zero
packet on shutdown (no explicit STOP opcode in this version).

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
