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
`hub_pybricks_gesture_server.py`, save it on the Hub, and disconnect Pybricks
Code/SPIKE App before running the Mac script. The Mac-side tools send a
Pybricks remote `START` command automatically, using the Team5 connection path
verified on 2026-06-03. If the Hub program stops mid-session, the Mac re-sends
`START` and re-syncs on the next `rdy`, so the run recovers without a restart.
BLE connection is retried automatically (`--connect-attempts`, default 3); raise
`--connect-attempts`/`--connect-timeout` if the first scan is flaky. Use
`--no-auto-start` only if you want to start the Hub program manually with the
center button.

## 🧭 Which script do I run?

Three Mac-side entry points, all sharing `pybricks_ble.py` for BLE:

| Script | Purpose | Needs robot? |
|--------|---------|:------------:|
| **`bt_manual_motor_test.py`** | Verify BLE + motor wiring with no camera. **Run this first.** | ✅ Yes |
| **`gesture_bt_controller.py`** | Hand-gesture control (MediaPipe): palm aims, fist fires. | ✅ Yes |
| **`balloon_intercept.py`** | C-RAM demo: red target detection + parabolic lead-shot + auto-fire. | ✅ Yes |

```bash
# 1) Wiring check (robot required)
python bt_manual_motor_test.py --hub-name "Team5" --print-sends

# 2) Hand gesture control
python gesture_bt_controller.py --hub-name "Team5" --print-sends

# 3) Balloon / target interception  (preferred demo)
python balloon_intercept.py --hub-name "Team5" --print-sends
```

> The current uploaded runner is the working robot path. Keep the Hub powered,
> disconnect Pybricks Code/SPIKE App, and let the Mac script auto-start the
> saved Hub program.

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

The current Hub runner maps signed command values directly into absolute target
angles:

```python
pan_target  = clamp(pan_val / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_target = clamp((tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
```

The Hub replies `rdy` after each packet (plus a 200 ms heartbeat to survive
dropped notifications), and prints status lines the Mac echoes as `[Hub] ...`:
`READY`, `ARMED`, `FIRING`, `RETURNING`, and `FIRED`.

> 📖 Full details: [`docs/PROTOCOL.md`](docs/PROTOCOL.md) ·
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
> [`docs/STATE_MACHINES.md`](docs/STATE_MACHINES.md) ·
> [`docs/PREDICTION.md`](docs/PREDICTION.md)

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
[START] sent remote START command to Hub.
[STATUS] Hub user program: RUNNING
[READY] rdy received.
[SEND] M,100,0,0 -> b'M\x64\x00\x00'
[SEND] M,0,0,1   -> b'M\x00\x00\x01'
[Hub] FIRING → RETURNING → ARMED → FIRED
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
python balloon_intercept.py --hub-name "Team5" --print-sends
```

Detects a red target by HSV, predicts a future impact point from smoothed
velocity + vertical acceleration, and fires when the predicted point enters the
center lock window.

| Option | Purpose |
|--------|---------|
| `--flight-time` | Projectile travel time used by the parabolic predictor |
| `--fire-px` | Center lock window, in pixels |
| `--min-area` | Minimum red contour area |
| `--send-interval` | Minimum BLE command interval |
| `--camera`, `--width`, `--height` | Camera index and frame size |
| `--no-auto-start` | Disable Mac-side remote START |
| `--connect-timeout` | BLE connect timeout in seconds (default `45`) |
| `--connect-attempts` | BLE scan/connect retries before giving up (default `3`) |
| `--keep-hub-running` | Leave the Hub program running after the camera script exits (default sends `STOP` so the Hub is ready to re-run) |

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
| Mac-side remote START + `rdy` flow control | ✅ | P2 |
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
| 2 | **Recorded-video replay harness** | P5 | A deterministic clip-replay mode lets P3/P4 compare detection/prediction changes on identical input without occupying the robot. | 🟢 No |
| 3 | **Target robustness** | P3 | Min/max area gating, frame-to-frame continuity, and lost-target recovery cut false locks and accidental shots. | 🟢 No |
| 4 | **Flight-time / latency calibration** | P4 · P5 | BLE + processing + projectile delay set the correct lead; measure and fold into the predictor. | 🔴 Yes |
| 5 | **Evaluation logging** | P5 | Hit/miss, prediction error, and trial conditions to CSV — evidence for the final report. | 🟡 Partial |
| 6 | **Final integration & demo** | All | Validate the full Hub + camera + target + launcher loop under demo conditions. | 🔴 Yes |

## 🤝 Team Workflow With One Robot

Run device-free work in parallel; book the single robot in short slots.

| Phase | 🔴 Robot slot | 🟢 Parallel work (no robot) |
|-------|--------------|-----------------------------|
| **1. Bring-up** | P1/P2: wiring, Hub upload, `bt_manual_motor_test.py` | P3 HSV tuning, P4 prediction on clips, P5 docs |
| **2. Calibration** | P2/P5: signs, gains, thresholds | P3 detection robustness, P4 lead/latency model |
| **3. Integration** | All: scheduled end-to-end trials | P5 logs results, P3/P4 tune from recorded data |
| **4. Report/demo** | Final rehearsal | P5 prepares README/report figures + demo notes |

> 💡 Reserve robot slots for wiring, calibration, and live firing. Vision and
> prediction changes should be developed against saved camera clips whenever possible.

---

## 🛠️ Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `[SCAN] no matching Hub` | App still connected, Hub off, or wrong name | Disconnect Pybricks Code/SPIKE app, power-cycle Hub, retry (UUID fallback runs after a name miss) |
| Repeating `STOPPED` status after connect | Saved Hub program is not running | Default scripts send remote `START` automatically; verify `[START] sent remote START command to Hub.` appears |
| Hub stops mid-run, then resumes | Hub program ended; Mac auto-recovered | Expected: Mac re-sends `START` (`[RECOVER] ... sending remote START`) and continues on the next `rdy` |
| First connect fails, second succeeds | BLE scan/connect is flaky on first try | Expected with default 3 retries; raise `--connect-attempts`/`--connect-timeout` if it persists |
| `[BLE] connected` but no `[READY]` | Hub program did not send `rdy` | Keep `--auto-start` enabled, disconnect Pybricks Code/SPIKE App, power-cycle Hub, retry |
| `[WAIT] Hub not sending rdy` | No readiness heartbeat yet | Retry with `--debug-rx`; use `--no-auto-start` only for manual center-button diagnostics |
| `[STALE] Hub is silent` | Link alive but Hub program stopped/crashed | Restart Hub program; check `[Hub] FATAL...` output |
| `[DISCONNECT]` / `[RECONNECT]` | BLE link dropped | Keep Hub near and powered; tools rescan every 3 s unless `--no-reconnect` |
| Motor points to the wrong side | Camera-to-motor mapping mismatch | Check `pixel_to_motor_vals()` on Mac and `PAN_MIN/PAN_MAX` or `TILT_MIN/TILT_MAX` on the Hub |
| Motor range is too small or too wide | Angle range mismatch | Adjust `PAN_MIN/PAN_MAX` or `TILT_MIN/TILT_MAX` in `hub_pybricks_gesture_server.py` |
| Camera won't open (macOS) | Missing camera permission | Grant Terminal/iTerm/VS Code camera access |

---

*Verified 2026-06-03 against the Team5 Hub with Mac-side remote START. Direction:
Pybricks BLE direct control. Repository scope: `gesture_bt/`, `docs/`,
`README*.md`. Virtualenvs, bytecode caches, local logs, and MediaPipe `.task`
models are intentionally not uploaded.*
Pybricks BLE direct control. Repo boundary: `gesture_bt/`, `docs/`, `README*.md`.
Harness files, venvs, archives, and the MediaPipe `.task` model are Git-ignored.*
