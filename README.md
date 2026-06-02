# CS270 Final Project — LEGO SPIKE Pybricks BLE Launcher

[Korean README](README.ko.md)

Real-time computer-vision control for a LEGO SPIKE Prime pan-tilt launcher.
The project direction is now fixed on **Mac/Python → Pybricks BLE → SPIKE Hub**.
The shared repository is intentionally scoped to the current Pybricks BLE
implementation, project documentation, and reproducible run/test instructions.

## Project Direction

Primary architecture:

```text
Mac / laptop
  gesture_bt/gesture_bt_controller.py   # hand gesture control
  gesture_bt/balloon_intercept.py       # C-RAM style target interception
        |
        | Pybricks BLE, GATT c5f50002-8280-46da-89f4-6d8051e4aeef
        v
SPIKE Prime Hub
  gesture_bt/hub_pybricks_gesture_server.py
        |
        v
Motors A/B/C/D/F
```

## Quick Start

```bash
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt

# 1. Upload hub_pybricks_gesture_server.py in Pybricks Code, run once, then disconnect.
# 2. Start the saved Hub program with the Hub center button when the Mac connects.

python bt_manual_motor_test.py --hub-name "Team5"
python gesture_bt_controller.py --hub-name "Team5" --print-sends
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

## Repository Structure

```text
gesture_bt/
  pybricks_ble.py               # Shared Pybricks BLE scan/reconnect/diagnostic client
  gesture_bt_controller.py       # Mac-side hand gesture controller over Pybricks BLE
  balloon_intercept.py           # HSV target detection, parabolic lead-shot prediction, auto-fire
  hub_pybricks_gesture_server.py # Hub-side Pybricks BLE server and motor state machine
  bt_manual_motor_test.py        # BLE + motor path test without camera logic
  requirements_gesture_bt.txt

docs/
  ARCHITECTURE.md                # Current Pybricks BLE architecture
  PROTOCOL.md                    # 4-byte Pybricks BLE protocol
  STATE_MACHINES.md              # Hub and Mac control state machines
  PREDICTION.md                  # Parabolic target prediction model
  ko/                            # Korean technical docs
```

The MediaPipe hand landmarker model is downloaded on first run and ignored by
Git. Local harness files are also ignored so the GitHub repository stays focused
for teammates, instructors, and TAs.

## Hardware Map

| Port | Motor | Role |
|------|-------|------|
| A | `launch_l` | Left launcher wheel |
| B | `launch_r` | Right launcher wheel, opposite direction |
| C | `c_motor` | Fire/reload mechanism |
| D | `tilt_motor` | Tilt axis |
| F | `pan_motor` | Pan axis |

The Hub code probes each port with `safe_motor()`. Missing motors are logged as
`PORT_<label>_MISSING`, so D/F pan-tilt tests can still run while A/B/C hardware
is incomplete.

## BLE Protocol

Mac writes to the Pybricks command/event characteristic with a leading `0x06`
prefix. The Hub reads exactly 4 bytes per command and self-recovers if byte
alignment is lost.

| Byte | Field | Meaning |
|------|-------|---------|
| 0 | opcode | `M` = motion/fire command, `S` = stop and exit |
| 1 | `pan_err_i8` | Signed pan error, `[-100, 100]` encoded as `value & 0xFF` |
| 2 | `tilt_err_i8` | Signed tilt error, `[-100, 100]` encoded as `value & 0xFF` |
| 3 | `fire` | `1` latches one firing cycle, otherwise `0` |

Hub update rule:

```python
pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

Hub replies with `rdy` after processed packets and also sends a periodic heartbeat
every 200 ms to prevent deadlocks after a lost notification. Status lines such as
`READY`, `ARMED`, `FIRING`, `RETURNING`, and `FIRED` are printed by the Mac as
`[Hub] ...`.
Shot angle snapshots are printed as `SHOT_START`, `SHOT_RELEASE`, and
`SHOT_DONE`, including actual `pan_F`, `tilt_D`, `c_C` motor angles and the
current pan/tilt targets.

All Mac-side tools use `gesture_bt/pybricks_ble.py` for BLE scan, notification,
readiness, stale-Hub warnings, and reconnect diagnostics.

## Main Workflows

### 1. Manual BLE and Motor Test

Use this before camera work.

```bash
cd gesture_bt
source .venv/bin/activate
python bt_manual_motor_test.py --hub-name "Team5" --print-sends
```

Expected path:

```text
[SCAN] name='Team5' timeout=15.0s
[BLE] connected to Team5
[NOTIFY] started. Start the saved Hub program with the Hub center button if needed.
[Hub] READY
[Hub] ARMED
[READY] first rdy received.
Starting 4-byte BLE motor test...
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,0,0,1 -> b'M\x00\x00\x01'
[Hub] SHOT_START pan_F=... tilt_D=... c_C=... target_pan=... target_tilt=...
[Hub] FIRING
[Hub] SHOT_RELEASE pan_F=... tilt_D=... c_C=... target_pan=... target_tilt=...
[Hub] RETURNING
[Hub] SHOT_DONE pan_F=... tilt_D=... c_C=... target_pan=... target_tilt=...
[Hub] ARMED
[Hub] FIRED
```

### 2. Hand Gesture Control

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

Behavior:

| Input | Behavior |
|-------|----------|
| Palm visible | Pan/tilt follows hand offset from screen center |
| Fist transition | Sends `fire=1` once |
| No hand | Sends zero error after the no-hand delay |
| `q` | Sends `STOP` and exits |

### 3. Balloon / Target Interception

```bash
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

This is the preferred C-RAM demo path. It detects a colored target using HSV,
predicts a future impact point with smoothed velocity and vertical acceleration,
and fires after the predicted point remains within the lock threshold for the
configured number of frames.

Important options:

| Option | Purpose |
|--------|---------|
| `--color-picker` | Click the target color in the camera window |
| `--hsv-lower`, `--hsv-upper` | Run without the picker using a fixed HSV range |
| `--flight-time` | Projectile travel time used by the parabolic predictor |
| `--lead-frames` | Extra frame-based lead added on top of `--flight-time` |
| `--velocity-smoothing` | EMA coefficient for target velocity |
| `--accel-smoothing` | EMA coefficient for vertical acceleration |
| `--fire-threshold` | Pixel error threshold for auto-fire |
| `--hold-frames` | Consecutive lock frames required before fire |
| `--mode rl` | Experimental Q-table correction layer |

## Team & Roles

Roles are now confirmed.

| Member | Role | Focus |
|--------|------|-------|
| P1 | Hardware Engineer | Robot build, launcher mechanism, motor mounting, wiring |
| P2 | HW/SW Integration | Hub firmware, BLE protocol, calibration bridge, fire timing |
| P3 | Vision Engineer | HSV target detection robustness, target tracking, camera parameters |
| P4 | Prediction / Algorithm | Lead-shot math, flight-time tuning, latency compensation |
| P5 | Calibration & Test / Docs | Calibration procedure, evaluation harness, session ops, README/report |

## Project Dashboard

Status legend: Done = complete, Next = active priority, Planned = queued.

| Module | Status | Owner |
|--------|:------:|:-----:|
| Pybricks BLE direct architecture selected | Done | P2 |
| 4-byte packet protocol + `rdy` flow control | Done | P2 |
| Hub parser self-recovery + stdin flush | Done | P2 |
| Hub crash visibility (`ERR_*`, `FATAL`, `BTN_STOP`) | Done | P2 |
| Manual BLE motor test | Done | P2 |
| Hand gesture control over BLE | Done | P3/P2 |
| Fist-triggered fire latch | Done | P3/P2 |
| Balloon/target HSV interception with parabolic prediction | Done | P3/P4 |
| Team role split and README dashboard | Done | P5 |
| Camera-only / no-BLE mode for target interception | Next | P5 |
| Camera-to-turret calibration routine | Next | P5/P2 |
| Target robustness: area gates, continuity, lost-target recovery | Planned | P3 |
| Flight-time and latency calibration | Planned | P4/P5 |
| Evaluation logging: hit rate, error, session CSV | Planned | P5 |
| Final report figures and protocol explanation | Planned | P5 |

## To-Do Detail

| # | Item | Owner | Why it matters | Device? |
|:-:|------|:-----:|----------------|:-------:|
| 1 | Camera-only / no-BLE mode | P5 | Lets P3/P4/P5 iterate on vision, prediction, and logging without occupying the single robot. | No |
| 2 | Camera-to-turret calibration | P5/P2 | Current error-based steering works, but repeatable interception needs measured mapping and sign/gain confirmation. | Yes |
| 3 | Target robustness | P3 | Reduces false locks and accidental shots under noisy lighting/backgrounds. | No |
| 4 | Flight-time / latency calibration | P4/P5 | BLE, processing, and projectile delay determine the correct lead. | Yes |
| 5 | Evaluation logging | P5 | Needed for final report evidence: hit/miss, prediction error, constants, and trial conditions. | Partial |
| 6 | Final integration slots | All | Validate the full Hub + camera + target + launcher loop under demo conditions. | Yes |

## Team Workflow With One Robot

Device-free work should run in parallel. Device-dependent work should be booked
in short slots.

| Phase | Robot slot | Parallel work without robot |
|-------|------------|-----------------------------|
| 1. Bring-up | P1/P2 run wiring, Hub upload, `bt_manual_motor_test.py` | P3 tunes HSV, P4 tests prediction on clips, P5 updates docs |
| 2. Calibration | P2/P5 tune signs, gains, and target thresholds | P3 improves detection, P4 computes lead/latency model |
| 3. Integration | All run scheduled end-to-end trials | P5 logs results, P3/P4 tune from recorded data |
| 4. Report/demo | Short final demo rehearsal | P5 prepares README/report figures and final demo notes |

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `[SCAN] no matching Hub` | Pybricks Code/SPIKE app still connected, Hub off, or wrong name | Disconnect apps, power-cycle Hub, retry; UUID fallback runs after name miss |
| `[BLE] connected` but no `[READY]` | Saved Hub program not running | Press Hub center button; confirm Hub display shows `BT` |
| `[WAIT] Hub program is not sending rdy` | Hub has not sent readiness heartbeat | Press Hub center button, disconnect Pybricks Code/SPIKE app, confirm display shows `BT` |
| `[STALE] Hub is silent` | BLE link alive but Hub program stopped/crashed | Restart Hub program and check `[Hub] FATAL...` output |
| `[DISCONNECT]` / `[RECONNECT]` | BLE link dropped | Keep Hub nearby and powered; default tools rescan every 3 seconds unless `--no-reconnect` is used |
| Motor moves opposite direction | Sign mismatch | Flip `PAN_SIGN` or `TILT_SIGN` in Hub code |
| Motor barely moves | Gain too low | Increase `GAIN` in Hub code carefully |
| Camera cannot open on macOS | Camera permission missing | Grant Terminal/iTerm/VS Code camera access |

## Verified As Of 2026-06-02

- GitHub remote: `orca-svg/CS270_FinalProject`, default branch `main`.
- Current direction: Pybricks BLE direct control.
- Shared repo boundary: `gesture_bt/`, `docs/`, `README.md`, and
  `README.ko.md`.
- Local-only/generated files are ignored: harness files, virtual environments,
  zip archives, local copies, and MediaPipe `.task` model files.
- Python syntax check passes for the tracked `gesture_bt/*.py` runtime files.
