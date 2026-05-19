# Data-driven Aiming Calibration Plan

## Goal

Replace slow hit/miss reinforcement learning with a small calibration dataset
that maps camera target error to launcher pan-tilt angles.

The system should answer this question in real time:

```text
Given target dx,dy in the camera image, what horizontal/vertical angles should
the launcher move to?
```

## Approach

1. Attach a fluorescent circular marker to the missile target.
2. Detect the marker with OpenCV HSV thresholding.
3. Manually aim the launcher at several target positions.
4. Save samples as:

```csv
target_x,target_y,dx,dy,vx,vy,horizontal_angle,vertical_angle
```

5. Estimate future target error if needed:

```text
lead_dx = dx + vx * lead_time
lead_dy = dy + vy * lead_time
```

6. Predict aiming angle with inverse-distance interpolation over the nearest
   calibration samples.
7. Send `AIM_ABS,horizontal_angle,vertical_angle` to the Hub.

## Implementation

- `calibration_targeting.py collect`
  - Opens the camera.
  - Detects the marker.
  - Press `s` when the launcher is manually aligned.
  - Enter the current horizontal and vertical motor angles.
  - Appends a row to `aim_calibration.csv`.

- `calibration_targeting.py run`
  - Loads `aim_calibration.csv`.
  - Detects the marker in real time.
  - Predicts the required angles by nearest-neighbor interpolation.
  - Sends `AIM_ABS,horizontal,vertical`.
  - Press `f` to send `FIRE`.
  - Press `c` to send `CENTER`.

- `rl_hub_runner.py`
  - Handles `AIM_ABS,horizontal,vertical`.
  - Clamps angles to mechanical limits.
  - Reuses the same motor map as `ShootingCode.py`.

## Data Collection Strategy

Start with a 3 by 3 grid:

```text
top-left     top-center     top-right
mid-left     center         mid-right
bottom-left  bottom-center  bottom-right
```

Collect at least one sample per cell. For a stronger demo, collect:

- 3 samples per cell: minimum useful dataset, around 27 rows.
- 5 samples per cell: better interpolation, around 45 rows.
- Multiple distances if the target distance changes.

Keep lighting and camera position fixed during the demo.

## Validation

- Inspect the dataset:

```bash
python3 Final_project/calibration_targeting.py inspect
```

- Dry-run real-time aiming:

```bash
python3 Final_project/calibration_targeting.py run --dry-run
```

- Confirm that predicted angles move smoothly as the target moves.
- Then connect the Hub/bridge and run without `--dry-run`.

## Presentation Wording

Use this instead of DQN or full reinforcement learning:

> We use a data-driven aiming calibration method. The camera extracts the
> target's image-plane error and velocity, and the system interpolates from
> real calibration samples to predict the horizontal and vertical launcher
> angles. This avoids slow hit-or-miss reward collection while still learning
> from the physical launcher setup.
