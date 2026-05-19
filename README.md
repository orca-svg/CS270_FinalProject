# CS270 Final Project

LEGO-K3 / LAMD aiming prototype for the CS270 final project.

This repository contains experimental code for connecting Raspberry Pi camera
tracking with LEGO SPIKE launcher control. The current recommended approach is
data-driven aiming calibration: collect a small set of camera-error to pan-tilt
angle samples, then interpolate the required launcher angle in real time.

## Project Structure

```text
Final_project/
  calibration_targeting.py              # Recommended calibration workflow
  CALIBRATION_IMPLEMENTATION_PLAN.md    # Implementation and experiment plan
  README_Q_LEARNING.md                  # Usage notes for aiming prototypes
  rl_hub_runner.py                      # SPIKE Hub command runner
  q_learning_aim_trainer.py             # Backup Q-learning prototype
```

## Recommended Workflow

Install camera-side dependencies on the Raspberry Pi or laptop:

```bash
pip install opencv-python numpy
```

Collect calibration samples:

```bash
python3 Final_project/calibration_targeting.py collect
```

Inspect the saved dataset:

```bash
python3 Final_project/calibration_targeting.py inspect
```

Run live targeting without a Hub connection:

```bash
python3 Final_project/calibration_targeting.py run --dry-run
```

Run the SPIKE Hub command runner on the Hub:

```text
Final_project/rl_hub_runner.py
```

Supported commands include:

```text
AIM_ABS,-12,35
FIRE
CENTER
STOP
```

## Notes

- `ShootingCode.py` and `OpenCV.py` from the local project were intentionally
  not modified.
- `q_learning_aim_trainer.py` is kept as a backup prototype. The calibration
  workflow is the practical path for the final demo because it avoids slow
  hit/miss reward collection.
