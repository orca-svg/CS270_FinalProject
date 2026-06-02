# 🎯 CS270 Final Project — LEGO SPIKE Pybricks BLE Launcher

[한국어 README](README.ko.md)

> Real-time computer-vision control for a LEGO SPIKE Prime pan-tilt launcher.
> A Mac runs the vision + control loop and drives the Hub directly over
> **Pybricks BLE** — no SPIKE app, no intermediate server.

```text
Mac / laptop  ──Pybricks BLE (GATT c5f50002-…)──►  SPIKE Prime Hub  ──►  Motors A/B/C/D/F
 vision + control loop                              hub_pybricks_gesture_server.py
```

The shared repo is intentionally scoped to the Pybricks BLE implementation,
its technical docs, and reproducible run/test instructions.

---

## 🚀 Quick Start

```bash
git clone https://github.com/orca-svg/CS270_FinalProject.git
cd CS270_FinalProject/gesture_bt

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_gesture_bt.txt
```

**Then:** in [Pybricks Code](https://code.pybricks.com), upload
`hub_pybricks_gesture_server.py`, run it once, and disconnect. Press the Hub
center button to start the saved program when the Mac connects.

## 🧭 Which script do I run?

Three Mac-side entry points, all sharing `pybricks_ble.py` for BLE:

| Script | Purpose | Needs robot? |
|--------|---------|:------------:|
| **`bt_manual_motor_test.py`** | Verify BLE + motor wiring with no camera. **Run this first.** | ✅ Yes |
| **`gesture_bt_controller.py`** | Hand-gesture control (MediaPipe): palm aims, fist fires. | `--dry-run` → No |
| **`balloon_intercept.py`** | C-RAM demo: HSV target detection + parabolic lead-shot + auto-fire. | `--dry-run` → No |

```bash
# 1) Wiring check (robot required)
python bt_manual_motor_test.py --hub-name "Team5" --print-sends

# 2) Hand gesture control
python gesture_bt_controller.py --hub-name "Team5" --print-sends

# 3) Balloon / target interception  (preferred demo)
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

> 💡 **No robot? Use `--dry-run`.** Both `gesture_bt_controller.py` and
> `balloon_intercept.py` run the full camera/vision/prediction loop and just
> print packets instead of sending BLE — so vision and prediction work can
> proceed in parallel without occupying the single Hub.

---

## 📦 Repository Structure

```text
gesture_bt/
  pybricks_ble.py                # Shared BLE scan / reconnect / readiness / diagnostics
  bt_manual_motor_test.py        # BLE + motor path test (no camera)
  gesture_bt_controller.py       # Hand-gesture controller
  balloon_intercept.py           # HSV detection + parabolic prediction + auto-fire
  hub_pybricks_gesture_server.py # Hub-side BLE server + motor state machine
  requirements_gesture_bt.txt

docs/                            # Deep-dive technical docs (EN + ko/)
  ARCHITECTURE.md  PROTOCOL.md  STATE_MACHINES.md  PREDICTION.md
  CHANGELOG.md                   # Change archive (cause → change → resolution)
```

The MediaPipe hand-landmarker model downloads on first run and is Git-ignored.
Local harness files, virtualenvs, and other side projects are ignored too, so
the GitHub repo stays focused for teammates, instructors, and TAs.

## 🔌 Hardware Map

| Port | Motor | Role |
|:----:|-------|------|
| A | `launch_l` | Left launcher wheel |
| B | `launch_r` | Right launcher wheel (opposite direction) |
| C | `c_motor` | Fire / reload mechanism (reciprocating) |
| D | `tilt_motor` | Tilt axis (0°–80°) |
| F | `pan_motor` | Pan axis (−35°–+35°) |

Each port is probed with `safe_motor()`. Missing motors log `PORT_<label>_MISSING`
and are skipped — so D/F pan-tilt tests still run while A/B/C are incomplete.

---

## 📡 BLE Protocol (summary)

The Mac writes to the Pybricks command/event characteristic with a leading
`0x06` prefix. The Hub reads **exactly 4 bytes** per command and self-recovers if
byte alignment is lost.

| Byte | Field | Meaning |
|:----:|-------|---------|
| 0 | opcode | `M` = motion/fire, `S` = stop and exit |
| 1 | `pan_err_i8` | Signed pan error `[-100, 100]`, encoded `value & 0xFF` |
| 2 | `tilt_err_i8` | Signed tilt error `[-100, 100]`, encoded `value & 0xFF` |
| 3 | `fire` | `1` latches one firing cycle, else `0` |

The Hub **accumulates** errors into a target angle (it does not command raw speed):

```python
pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
```

The Hub replies `rdy` after each packet (plus a 200 ms heartbeat to survive
dropped notifications), and prints status lines the Mac echoes as `[Hub] ...`:
`READY`, `ARMED`, `FIRING`, `RETURNING`, `FIRED`, and shot snapshots
`SHOT_START / SHOT_RELEASE / SHOT_DONE` (with live `pan_F`, `tilt_D`, `c_C` angles).

> 📖 Full details: [`docs/PROTOCOL.md`](docs/PROTOCOL.md) ·
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
> [`docs/STATE_MACHINES.md`](docs/STATE_MACHINES.md) ·
> [`docs/PREDICTION.md`](docs/PREDICTION.md) ·
> [`docs/CHANGELOG.md`](docs/CHANGELOG.md) (change archive)

---

## ▶️ Workflows

### 1. Manual BLE + motor test (do this first)

```bash
python bt_manual_motor_test.py --hub-name "Team5" --print-sends
```

Expected path:

```text
[SCAN] name='Team5' timeout=15.0s
[BLE] connected to Team5
[Hub] READY
[Hub] ARMED
[READY] first rdy received.
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,0,0,1   -> b'M\x00\x00\x01'
[Hub] SHOT_START ... → FIRING → SHOT_RELEASE → RETURNING → SHOT_DONE → ARMED → FIRED
```

### 2. Hand gesture control

```bash
python gesture_bt_controller.py --hub-name "Team5" --print-sends
```

| Input | Behavior |
|-------|----------|
| Palm visible | Pan/tilt follows hand offset from screen center |
| Fist transition | Sends `fire=1` once |
| No hand | Sends zero error after the no-hand delay |
| `q` | Sends `STOP` and exits |

### 3. Balloon / target interception (preferred demo)

```bash
python balloon_intercept.py --hub-name "Team5" --color-picker --print-sends
```

Detects a colored target by HSV, predicts a future impact point from smoothed
velocity + vertical acceleration, and fires once the predicted point holds
inside the lock threshold for `--hold-frames`.

| Option | Purpose |
|--------|---------|
| `--color-picker` | Click the target color in the camera window |
| `--hsv-lower`, `--hsv-upper` | Fixed HSV range (skip the picker) |
| `--flight-time` | Projectile travel time used by the parabolic predictor |
| `--lead-frames` | Extra frame-based lead on top of `--flight-time` |
| `--velocity-smoothing` / `--accel-smoothing` | EMA coefficients (velocity / vertical accel) |
| `--fire-threshold` | Pixel error threshold for auto-fire |
| `--hold-frames` | Consecutive lock frames required before firing |
| `--fire-cooldown` | Seconds to suppress re-fire after a shot |
| `--mode rl` | Experimental Q-table correction layer (`--qtable`) |

---

## 👥 Team & Roles (confirmed)

| Member | Role | Focus |
|:------:|------|-------|
| **P1** | 🔧 Hardware Engineer | Robot build, launcher mechanism, motor mounting, wiring |
| **P2** | 🔗 HW/SW Integration | Hub firmware, BLE protocol, calibration bridge, fire timing |
| **P3** | 👁️ Vision Engineer | HSV detection robustness, target tracking, camera parameters |
| **P4** | 📐 Prediction / Algorithm | Lead-shot math, flight-time tuning, latency compensation |
| **P5** | 🎯 Calibration & Test / Docs | Calibration routine, evaluation harness, session ops, README/report |

## 📊 Project Dashboard

**Legend:** ✅ Done · 🔜 In progress · ⬜ Planned

| Module | Status | Owner |
|--------|:------:|:-----:|
| Pybricks BLE direct architecture | ✅ | P2 |
| 4-byte protocol + `rdy` flow control + heartbeat | ✅ | P2 |
| Hub parser self-recovery + stdin flush | ✅ | P2 |
| Hub crash visibility (`ERR_*`, `FATAL`, `BTN_STOP`) | ✅ | P2 |
| Manual BLE motor test | ✅ | P2 |
| Hand gesture control + fist-fire latch | ✅ | P3 · P2 |
| Balloon/target HSV interception + parabolic prediction | ✅ | P3 · P4 |
| `--dry-run` camera-only mode (no robot) | ✅ | P3 · P5 |
| Team roles + README dashboard + docs | ✅ | P5 |
| Camera-to-turret calibration routine | 🔜 | P5 · P2 |
| Deterministic recorded-video replay harness | 🔜 | P5 |
| Target robustness (area gate, continuity, lost-target recovery) | ⬜ | P3 |
| Flight-time + latency calibration | ⬜ | P4 · P5 |
| Evaluation logging (hit rate, error, session CSV) | ⬜ | P5 |
| Final report figures + demo run | ⬜ | All |

## ✅ To-Do Detail (priority order)

| # | Item | Owner | Why it matters | Device? |
|:-:|------|:-----:|----------------|:-------:|
| 1 | **Camera-to-turret calibration** | P5 · P2 | Error-based steering works, but repeatable interception needs a measured pixel→angle mapping plus sign/gain confirmation. Biggest accuracy lever. | 🔴 Yes |
| 2 | **Recorded-video replay harness** | P5 | `--dry-run` already runs live without a robot; a deterministic clip-replay mode lets P3/P4 compare detection/prediction changes on identical input. | 🟢 No |
| 3 | **Target robustness** | P3 | Min/max area gating, frame-to-frame continuity, and lost-target recovery cut false locks and accidental shots. | 🟢 No |
| 4 | **Flight-time / latency calibration** | P4 · P5 | BLE + processing + projectile delay set the correct lead; measure and fold into the predictor. | 🔴 Yes |
| 5 | **Evaluation logging** | P5 | Hit/miss, prediction error, and trial conditions to CSV — evidence for the final report. | 🟡 Partial |
| 6 | **Final integration & demo** | All | Validate the full Hub + camera + target + launcher loop under demo conditions. | 🔴 Yes |

## 🤝 Team Workflow With One Robot

Run device-free work in parallel; book the single robot in short slots.

| Phase | 🔴 Robot slot | 🟢 Parallel work (no robot) |
|-------|--------------|-----------------------------|
| **1. Bring-up** | P1/P2: wiring, Hub upload, `bt_manual_motor_test.py` | P3 HSV tuning (`--dry-run`), P4 prediction on clips, P5 docs |
| **2. Calibration** | P2/P5: signs, gains, thresholds | P3 detection robustness, P4 lead/latency model |
| **3. Integration** | All: scheduled end-to-end trials | P5 logs results, P3/P4 tune from recorded data |
| **4. Report/demo** | Final rehearsal | P5 prepares README/report figures + demo notes |

> 💡 Because `--dry-run` exists, **3 of 5 members can make progress without the
> robot at any time.** Reserve robot slots for wiring, calibration, and live firing.

---

## 🛠️ Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `[SCAN] no matching Hub` | App still connected, Hub off, or wrong name | Disconnect Pybricks Code/SPIKE app, power-cycle Hub, retry (UUID fallback runs after a name miss) |
| `[BLE] connected` but no `[READY]` | Saved Hub program not running | Press Hub center button; confirm display shows `BT` |
| `[WAIT] Hub not sending rdy` | No readiness heartbeat yet | Press center button, disconnect other apps, confirm `BT` on display |
| `[STALE] Hub is silent` | Link alive but Hub program stopped/crashed | Restart Hub program; check `[Hub] FATAL...` output |
| `[DISCONNECT]` / `[RECONNECT]` | BLE link dropped | Keep Hub near and powered; tools rescan every 3 s unless `--no-reconnect` |
| Motor moves the wrong way | Sign mismatch | Flip `PAN_SIGN` / `TILT_SIGN` in Hub code |
| Motor barely moves | Gain too low | Increase `GAIN` carefully in Hub code |
| Camera won't open (macOS) | Missing camera permission | Grant Terminal/iTerm/VS Code camera access |

---

*Verified 2026-06-02 against `orca-svg/CS270_FinalProject@main`. Direction:
Pybricks BLE direct control. Repo boundary: `gesture_bt/`, `docs/`, `README*.md`.
Harness files, venvs, archives, and the MediaPipe `.task` model are Git-ignored.*
