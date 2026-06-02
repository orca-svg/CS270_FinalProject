# Changelog (Archive)

[한국어](ko/CHANGELOG.md)

This document archives the project's major changes in a **Cause → Change →
Resolution/Effect** format. It records what changed, why, and how it was solved,
so the team avoids re-litigating decisions and prevents regressions.

All changes are on `main`; the dated work is concentrated on 2026-06-02.

## Timeline Summary

| Date | Commit | Summary | Type |
|------|--------|---------|------|
| 05-31 | `2150593` | Gesture BLE controller v7 + bug fixes | Feature |
| 05-31 | `feb7585` | Technical spec docs + Hub heartbeat fix | Docs/Fix |
| 05-31 | `caa21ce` | Korean README + `docs/ko/` | Docs |
| 06-02 | `67d0e45` | README Quick Start / dry-run / keyboard accuracy | Docs |
| 06-02 | `1b16708` | Replace hand-gesture with parabolic aimbot | Feature |
| 06-02 | `6e69ae7` | Fixed-camera, independent-motor (absolute angle) control | Feature *(later superseded)* |
| 06-02 | `cc143bb` | Sync README to fixed-camera design + roadmap/team | Docs |
| 06-02 | `e9926af` | Confirm roles + progress/task dashboard | Docs |
| 06-02 | `7b8a815` | **PR #1**: Pybricks BLE repository reorganization | Architecture |
| 06-02 | `b256832` | README readability rewrite + dry-run drift fix | Docs |

---

## 1. README run-instruction accuracy (`67d0e45`)

- **Cause:** Run steps were scattered, and the camera overlay advertised
  `c / f / w / x` keys while only `q` (quit) was actually active — users could
  try keys that did nothing.
- **Change:** Added a 5-step Quick Start, a dry-run pre-check, expected
  manual-BLE-test output, and a Troubleshooting section. Documented that the
  overlay keys are inactive.
- **Resolution/Effect:** A new teammate can follow the steps in order; confusion
  from dead keys is removed.

## 2. Hand-gesture → parabolic aimbot (`1b16708`)

- **Cause:** The user switched the controller from hand gestures (MediaPipe) to
  **red-object tracking + parabolic trajectory prediction + auto-fire**.
- **Change:** Rewrote the controller to detect the target via HSV masking,
  estimate velocity (1st) + vertical acceleration (2nd) with EMA, predict the
  future impact point, and auto-fire when the predicted error is within a
  center threshold. Updated the README with the 4-step algorithm.
- **Resolution/Effect:** Established the basis for a C-RAM-style "intercept a
  thrown object" demo.

## 3. Fixed-camera, independent-motor (absolute angle) control (`6e69ae7`) — ⚠️ later superseded

- **Cause:** The original code assumed the camera was mounted on the turret and
  moved with it, so it fed pixel *errors* the Hub accumulated. The real setup is
  a **fixed webcam with independent motors**.
- **Change:** Added `pixel_to_motor_vals()` to map pixel coordinates directly to
  absolute motor angles `[-100, +100]`, and changed the Hub to set absolute
  angles instead of accumulating (`pan_target = pan_val/100 * PAN_MAX`).
- **Resolution/Effect:** Implemented a direct mapping that matched the
  fixed-camera structure at the time.
- **Current status:** **Superseded.** PR #1 (`7b8a815`) reunified the team on the
  error-accumulation model (`PAN_SIGN`, `GAIN`) and split the interception logic
  into a separate `balloon_intercept.py`. The current Hub protocol is therefore
  **error accumulation**, and the absolute-angle conversion is not used.
  (Recorded explicitly to prevent regression.)
  → The precise pixel↔angle correspondence is planned to be solved by a
  **camera-to-turret calibration** (roadmap item), tied to
  [`PREDICTION.md`](PREDICTION.md).

## 4. README design sync + roadmap/team (`cc143bb`)

- **Cause:** The code had moved to auto-aiming, but the README still described
  the old gesture flow, and progress / next steps / team split were undocumented.
- **Change:** Synced the README to the then-current code and added "Progress /
  Roadmap / 5-member team workflow (with the single-device constraint)". Fully
  rewrote the Korean README.
- **Resolution/Effect:** The README began acting as a **team operations doc**,
  not just an intro.

## 5. Confirm roles + dashboard (`e9926af`)

- **Cause:** The team finalized the 5 roles (P1–P5) and needed a more visible
  progress table.
- **Change:** Promoted roles to a confirmed table and added a dashboard mapping
  each module's status (✅/🔜/⬜) to an owner, plus a priority to-do table with a
  device-required flag.
- **Resolution/Effect:** Who-owns-what and how-far-along is visible at a glance.

## 6. PR #1 — Pybricks BLE repo reorganization (`7b8a815`)

- **Cause:** Needed to clarify the shared repo's direction (direct Pybricks BLE)
  and tidy the code structure.
- **Change:**
  - Extracted a shared BLE client `pybricks_ble.py` (scan / reconnect /
    readiness / diagnostics).
  - Split auto-aiming into `balloon_intercept.py` (HSV + parabolic + auto-fire).
  - Kept the hand-gesture controller `gesture_bt_controller.py`.
  - Added Hub parser self-recovery (desync resync), stdin flush, crash
    visibility (`ERR_*`, `FATAL`, `BTN_STOP`), and shot snapshots
    (`SHOT_START/RELEASE/DONE`).
  - Added `docs/`: ARCHITECTURE / PROTOCOL / STATE_MACHINES / PREDICTION.
  - Reunified Hub control on **error accumulation** (`PAN_SIGN`, `GAIN`),
    superseding item 3.
- **Resolution/Effect:** Clear module responsibilities; much better BLE
  stability and diagnostic visibility.

## 7. README readability rewrite + dry-run drift fix (`b256832`)

- **Cause 1 (readability):** After the reorg, the README was long and dense, hard
  to skim.
- **Cause 2 (drift):** The dashboard listed "camera-only / no-BLE mode" as
  pending, but both `gesture_bt_controller.py` and `balloon_intercept.py` **already
  support `--dry-run`** (code ↔ doc mismatch).
- **Change:**
  - Added a one-line architecture diagram and a "Which script do I run?"
    entry-point table.
  - Emoji section headers and a ✅/🔜/⬜ icon dashboard for skimmability.
  - Linked `docs/` for deep dives instead of duplicating (progressive disclosure).
  - Corrected `--dry-run` to ✅ Done and surfaced it prominently; reframed the
    open item as a **deterministic recorded-video replay harness**.
  - Cross-checked protocol/option tables against the actual CLI args
    (e.g., added `--fire-cooldown`).
- **Resolution/Effect:** The README matches the code, and a newcomer can decide
  "what to run" within seconds.

---

## Key Lessons

- **Verify docs against code.** Like the dry-run drift in item 7, a mismatch
  between what's documented and what works leads to mis-prioritized effort.
- **Record superseded decisions.** The absolute-angle approach in item 3 was
  dropped; without a record, the next person repeats it or gets confused.
- **Design around the single-device constraint.** Thanks to `--dry-run`, 3 of 5
  members can work in parallel without the robot — the key to team throughput.
