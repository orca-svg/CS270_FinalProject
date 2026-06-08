# 🎯 CS270 Final Project — LEGO SPIKE Pybricks BLE Launcher

[한국어 README](README.ko.md)

> Real-time computer-vision control for a LEGO SPIKE Prime pan-tilt launcher.
> A Mac runs the vision + control loop and drives the Hub directly over
> **Pybricks BLE** — no SPIKE app, no intermediate server.

```text
Mac / laptop  ──Pybricks BLE (GATT c5f50002-…)──►  SPIKE Prime Hub  ──►  Motors A/B/C/D/F
 vision + control loop                              hub_pybricks_gesture_server.py
```

The shared repo is scoped to the Pybricks BLE implementation, its technical
docs, and reproducible run/test instructions. macOS is the primary platform;
Windows-threaded variants (`*_win.py`) and no-robot offline tools
(`*_offline.py`) live alongside the main path for vision/prediction work.

---

## 📝 Recent meeting summary: final-demo AI direction

The team decided to prioritize **AI features that are explainable in the final
video without slowing the real-time tracking/fire loop**. Instead of training and
running a heavy object-classification model inside the main loop, the laptop
keeps the existing vision controller fast and changes only the firing policy
based on a small JSON file written by the voice/LLM side.

Confirmed direction:

1. **Voice/LLM fire-mode switching**
   - Voice commands select demo-friendly modes: precision single-shot, burst,
     safe/no-fire, and guard/sentry.
   - The real-time loop reads only the JSON `mode` field and changes when it
     sends `fire=1`.
2. **Multi-object/color handling remains a supporting story**
   - Balloons remain the most reliable target for drop speed and hit success.
   - Additional colors/objects can be explained through HSV expansion or demo
     scripting if time allows.
3. **Guard/radar mode is a lightweight extension**
   - When no target is visible, the turret can sweep left/right to support the
     defense-system story.
   - 360-degree rotation or distance-sensor radar is optional hardware work.
4. **Do not change the Hub protocol**
   - The Hub continues to receive only the 4-byte `M,pan,tilt,fire` packet.
   - Mode names stay on the laptop; the controller maps them to `fire` timing
     and pan-sweep commands to avoid BLE packet-alignment risk.

This branch (`feat/voice-fire-mode-json`) implements the voice/LLM JSON mode
interface, Windows support, tests, and README/protocol documentation.

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
Pybricks remote `START` command automatically. If the Hub program stops
mid-session, the Mac re-sends `START`, waits for the next `rdy`, and resumes.
BLE connection is retried automatically; `balloon_intercept.py` defaults to
`--connect-attempts 5` and `--scan-timeout 20`. Use `--no-auto-start` only for
manual center-button diagnostics.

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

# Windows: keep OpenCV on the main thread and Bleak on a background thread
python balloon_intercept_win.py --hub-name "Team5" --print-sends
```

Voice/LLM mode switching is implemented as a Mac/Windows controller policy, not
as a Hub packet-format change. The voice-recognition process writes a JSON
object with a `mode` field into `gesture_bt/control_mode.json`; `balloon_intercept.py` and
`balloon_intercept_win.py` read that file and change only when they send
`fire=1` in the existing `M,pan,tilt,fire` command.

The controller-side JSON shape is below. Only `mode` is required; the remaining
fields are optional metadata for voice/LLM debugging and presentation overlays.

```json
{
  "mode": "single",
  "source": "voice",
  "transcript": "single-shot mode",
  "confidence": 0.92,
  "updated_at": "2026-06-06T12:00:00+09:00"
}
```

Allowed `mode` values: `single`, `burst`, `safe`, `guard`.

| Mode | Behavior | Actual effect sent to Hub |
|------|----------|---------------------------|
| `single` | Fire once after target lock | Sends one `fire=1` request |
| `burst` | Repeat while locked | Sends `fire=1` every `--burst-interval`; the Hub fires only when `armed` |
| `safe` | No-fire safety mode | Keeps aiming but never sends `fire=1` |
| `guard` | Sweep when no target is visible | Sends changing pan values in `M,pan,tilt,0`; target engagement uses single policy |

Implemented files:

- `gesture_bt/fire_mode_control.py`: JSON payload builder/reader/writer, mode normalization, fallback handling.
- `gesture_bt/control_mode.json`: Example file for the voice-recognition module to write.
- `gesture_bt/voice_commander.py`: Voice-to-JSON bridge with `Hey you` wake-word gating and `--dry-run-text` verification.
- `gesture_bt/balloon_intercept.py`: macOS/default controller mode policy.
- `gesture_bt/balloon_intercept_win.py`: Windows-threaded controller mode policy.
- `tests/test_fire_mode_control.py`: JSON schema, metadata, fallback, and writer tests.

Note: the Hub never receives the mode string. It still receives only the existing
4-byte `M,pan,tilt,fire` packet; the laptop controller maps modes into `fire`
timing and pan sweep. The Hub-side C-motor reload state machine
(`armed -> firing -> returning -> armed`) is unchanged.

```bash
# Terminal 1: run the interceptor
python balloon_intercept.py --hub-name "Team5" --control-mode-file control_mode.json --print-sends

# Terminal 2: voice commander waits for 'Hey you' (or '헤이 유'), then writes command -> control_mode.json
python voice_commander.py --control-mode-file control_mode.json --language en-US

# Natural commands include: fire/shoot -> single, open fire/rapid fire -> burst,
# 발사/쏴 -> single, 연발/연사 -> burst (use --language ko-KR for Korean).

# If you want direct command mode without a wake phrase
python voice_commander.py --control-mode-file control_mode.json --no-wake-word --language en-US
```

Related options: `--default-fire-mode`, `--burst-interval`, `--guard-sweep-pan`,
`--guard-sweep-speed`, and `--control-mode-file`.

> The current uploaded runner is the working robot path. Keep the Hub powered,
> disconnect Pybricks Code/SPIKE App, and let the Mac script auto-start the
> saved Hub program.

> **Windows / no-robot variants.** On Windows, run `gesture_bt_controller_win.py`
> or `balloon_intercept_win.py` — they run the Bleak BLE loop on a background
> thread and keep OpenCV on the main thread to avoid COM threading conflicts. To
> develop vision/prediction without a robot, `balloon_tracker_offline.py` and
> `hand_tracker_offline.py` run camera-only with no BLE.

---

## 📦 Repository Structure

```text
gesture_bt/
  pybricks_ble.py                    # Shared BLE scan / reconnect / readiness / diagnostics
  fire_mode_control.py               # Shared JSON-based single/burst/safe/guard fire-mode policy
  bt_manual_motor_test.py            # BLE + motor path test (no camera)
  bt_verify_restart_shot.py          # Fire + forced-restart verification
  camera_check.py                    # macOS/OpenCV camera permission check
  hub_angle_reader.py                # Read D/F/C absolute motor angles for home calibration
  calibrate_angle_regression.py      # Fit pixel→pan/tilt angle correction from recorded hits
  gesture_bt_controller.py           # Hand-gesture controller (macOS / single asyncio loop)
  gesture_bt_controller_win.py       # Windows variant: Bleak on a background thread, OpenCV on main thread
  balloon_intercept.py               # HSV detection + parabolic prediction + auto-fire
  balloon_intercept_win.py           # Windows-threaded variant of balloon_intercept
  hub_pybricks_gesture_server.py     # Hub-side BLE server + motor state machine
  hub_pybricks_gesture_server_bak.py # Backup of a previous Hub server build
  requirements_gesture_bt.txt

balloon_tracker_offline.py           # No-robot 3D-physics balloon tracker (camera + mouse HSV picker)
hand_tracker_offline.py              # No-robot MediaPipe hand/gesture tester
balloon_aimbot_design.md             # Balloon trajectory + aimbot design notes (air drag, lead-shot)
models/
  hand_landmarker.task               # MediaPipe model bundled for offline / Windows use

docs/                                # Deep-dive technical docs (EN + ko/)
  ARCHITECTURE.md  PROTOCOL.md  STATE_MACHINES.md  PREDICTION.md
```

The macOS scripts (`gesture_bt_controller.py`, `balloon_intercept.py`) fetch the
MediaPipe hand-landmarker model into `gesture_bt/models/` on first run; that path
is Git-ignored. A copy is committed at the repo root `models/hand_landmarker.task`
so the offline tools and Windows-threaded variants can run without the download.
`gesture_bt/aim_dataset.csv` is generated during fire calibration and is
Git-ignored. Local harness files, virtualenvs, and other side projects are
ignored too, so the GitHub repo stays focused for teammates, instructors, and
TAs.

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
| 0 | opcode | `M` = motion/fire. Hub stop uses Pybricks remote `STOP`; stdin `S` is legacy only |
| 1 | `pan_err_i8` | Signed pan error `[-100, 100]`, encoded `value & 0xFF` |
| 2 | `tilt_err_i8` | Signed tilt error `[-100, 100]`, encoded `value & 0xFF` |
| 3 | `fire` | `1` latches one firing cycle, else `0` |

The current Hub runner does not call `reset_angle()`. Instead it uses the
calibrated absolute home readings measured on the Team5 robot:
`PAN_HOME=-172` on port F, `TILT_HOME=-20` on port D, and `C_HOME=43` on port C.
Signed Mac commands are converted into camera offsets and applied as
`HOME + offset`:

```python
pan_offset  = clamp(pan_val / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
tilt_offset = clamp((tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                    TILT_MIN, TILT_MAX)
pan_motor.track_target(PAN_HOME + pan_offset)
tilt_motor.track_target(TILT_HOME + tilt_offset)
```

The Hub replies `rdy` at startup and after each processed packet. It prints
status lines the Mac echoes as `[Hub] ...`: `HOME_CHECK`, `SERVER_VERSION`,
`READY`, `ARMED`, `FIRE_REQ`, `SPINUP`, `SHOT f=... d=...`, `FIRING`,
`RETURNING`, and `FIRED`.

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
[Hub] FIRE_REQ → SPINUP → SHOT f=... d=... → FIRING → RETURNING → ARMED → FIRED
```

Home-only check:

```bash
python bt_manual_motor_test.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 \
  --home-only --home-seconds 6 --home-pan 0 --home-tilt -100
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
velocity + vertical acceleration, and fires automatically with a one-shot per
target state machine: `TRACKING -> LOCKED -> FIRED_FOR_TARGET -> REARM_WAIT`.
`fire=1` is sent only after the predicted point stays inside the lock window
for `--fire-confirm-frames` consecutive frames. After a shot, the same
continuous target receives aim-only packets until it disappears for
`--target-lost-rearm` seconds.

| Option | Purpose |
|--------|---------|
| `--flight-time` | Projectile travel time used by the parabolic predictor |
| `--fire-px` | Center lock window, in pixels |
| `--fire-confirm-frames` | Consecutive in-window frames required before firing (default `2`) |
| `--target-lost-rearm` | Seconds target must disappear before the next shot is allowed (default `0.5`) |
| `--no-fire` | Track and aim without sending `fire=1` |
| `--min-area` | Minimum red contour area |
| `--send-interval` | Minimum BLE command interval |
| `--post-recovery-replay` | Aim-only replay window after BLE/Hub recovery; fire commands are never replayed |
| `--control-mode-file` | JSON file path written by voice/LLM process |
| `--default-fire-mode` | Fallback mode when the JSON file is missing: `single`, `burst`, `safe`, `guard` |
| `--burst-interval` | Minimum seconds between repeated `fire=1` requests in `burst` mode |
| `--guard-sweep-pan` / `--guard-sweep-speed` | Sweep range/speed when `guard` mode has no visible target |
| `--dataset` / `--no-dataset` | Save or disable `SHOT`-joined calibration rows in `aim_dataset.csv` |
| `--camera`, `--width`, `--height` | Camera index and frame size |
| `--no-auto-start` | Disable Mac-side remote START |
| `--connect-timeout` | BLE connect timeout in seconds (default `45`) |
| `--connect-attempts` | BLE scan/connect retries before giving up (default `5`) |
| `--keep-hub-running` | Leave the Hub program running after the camera script exits (default sends `STOP` so the Hub is ready to re-run) |

### 4. Mode JSON unit test / no-robot verification

The core logic in this branch can be verified without the robot:

```bash
# Run from the repository root
python3 -m py_compile gesture_bt/*.py
python3 -m unittest tests.test_fire_mode_control -v
git diff --check
```

Expected result:

```text
Ran 6 tests ...
OK
```

To verify only the `control_mode.json` read/write shape:

```bash
cd gesture_bt
python3 - <<'PY'
from fire_mode_control import write_control_mode, read_control_mode
write_control_mode("control_mode.json", "BURST", source="voice", transcript="burst mode", confidence=0.95)
print(read_control_mode("control_mode.json"))
PY
# output: burst
```

Before connecting the Hub, use `--no-fire` to check the overlay and mode-change
logs without sending any firing request:

```bash
python balloon_intercept.py --no-fire --control-mode-file control_mode.json --print-sends
```

Windows uses the same JSON file:

```powershell
python balloon_intercept_win.py --no-fire --control-mode-file control_mode.json --print-sends
'{"mode":"guard","source":"manual","transcript":"guard mode"}' | Set-Content control_mode.json
```

### 5. Fire and reconnect verification

```bash
# Single-shot verification
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10 --skip-forced-stop

# Forced STOP, auto-recovery, then shot verification
python bt_verify_restart_shot.py --hub-name "Team5" --print-sends --debug-rx \
  --connect-attempts 5 --connect-timeout 60 --shot-timeout 10
```

Passing output includes `SERVER_VERSION gesture_server_2026_06_03_fire_spinup_state`,
`SHOT f=... d=...`, `RETURNING`, `ARMED`, and `FIRED`.

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
| 4-byte protocol + `rdy` flow control | ✅ | P2 |
| Hub parser self-recovery + stdin flush | ✅ | P2 |
| Hub absolute-home calibration (`F=-172`, `D=-20`, `C=43`) | ✅ | P2 · P5 |
| Manual BLE motor test | ✅ | P2 |
| Hand gesture control + fist-fire latch | ✅ | P3 · P2 |
| Balloon/target HSV interception + parabolic prediction | ✅ | P3 · P4 |
| One-shot-per-target auto-fire FSM | ✅ | P2 · P4 |
| Mac-side remote START + `rdy` flow control | ✅ | P2 |
| Reconnect replay protection: aim-only, never `fire=1` | ✅ | P2 |
| Fire calibration dataset logging on `SHOT f/d` | ✅ | P5 |
| Voice/LLM JSON-based `single`/`burst`/`safe`/`guard` mode switching | ✅ | P2 |
| Windows balloon-intercept controller mode support | ✅ | P2 |
| Team roles + README dashboard + docs | ✅ | P5 |
| Camera-to-turret calibration regression | 🔜 | P5 · P2 |
| Deterministic recorded-video replay harness | 🔜 | P5 |
| Target robustness (area gate, continuity, lost-target recovery) | ⬜ | P3 |
| Flight-time + latency calibration | ⬜ | P4 · P5 |
| Evaluation logging (hit rate, error, session CSV) | ⬜ | P5 |
| Final report figures + demo run | ⬜ | All |

## ✅ To-Do Detail (priority order)

| # | Item | Owner | Why it matters | Device? |
|:-:|------|:-----:|----------------|:-------:|
| 1 | **Camera-to-turret calibration regression** | P5 · P2 | `SHOT f/d` rows are now logged; next step is collecting enough samples and fitting pixel→angle correction. Biggest accuracy lever. | 🔴 Yes |
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
| `[WAIT] Hub not sending rdy` | Hub program has not started/responded yet | Retry with `--debug-rx`; use `--no-auto-start` only for manual center-button diagnostics |
| `READY` does not appear after using Pybricks Code | Pybricks Code still owns BLE or Hub is not advertising | Disconnect Pybricks Code, power-cycle the Hub, wait for Team5 advertising, then run the Mac script |
| `[STALE] Hub is silent` | Link alive but Hub program stopped/crashed | Let auto-recovery send remote `START`; if it repeats, power-cycle the Hub and re-upload the current Hub code |
| `[DISCONNECT]` / `[RECONNECT]` | BLE link dropped | Keep Hub near and powered; tools rescan every 3 s unless `--no-reconnect` |
| Motor points to the wrong side | Camera-to-motor mapping mismatch | Check `pixel_to_motor_vals()` on Mac and `PAN_MIN/PAN_MAX` or `TILT_MIN/TILT_MAX` on the Hub |
| Motor range is too small or too wide | Angle range mismatch | Adjust `PAN_MIN/PAN_MAX` or `TILT_MIN/TILT_MAX` in `hub_pybricks_gesture_server.py` |
| Camera won't open (macOS) | Missing camera permission | Grant Terminal/iTerm/VS Code camera access |

---

*Verified 2026-06-03 against the Team5 Hub with Mac-side remote START, forced
STOP recovery, and single-shot fire logs. Direction: Pybricks BLE direct
control. Repository scope: `gesture_bt/`, `docs/`, root offline tools
(`*_offline.py`), `balloon_aimbot_design.md`, `models/hand_landmarker.task`, and
`README*.md`. Virtualenvs, bytecode caches, local logs, generated datasets, and
the first-run `gesture_bt/models/` download are not uploaded.*
