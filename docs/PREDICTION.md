# Balloon / Target Prediction

`gesture_bt/balloon_intercept.py` uses `ParabolicTracker` for lead-shot aiming.
The predictor estimates horizontal velocity, vertical velocity, and vertical
acceleration from successive target centers.

## Model

For a detected target center `(x, y)` and lead time `t`:

```text
pred_x = x + vx * t
pred_y = y + vy * t + 0.5 * ay * t^2
```

`vx`, `vy`, and `ay` are smoothed with exponential moving averages so single
noisy HSV detections do not dominate the aim point.

## CLI Controls

| Option | Meaning |
|--------|---------|
| `--flight-time` | Expected projectile travel time in seconds |
| `--lead-frames` | Extra frame-based lead added to `flight-time` |
| `--velocity-smoothing` | EMA coefficient for `vx` and `vy` |
| `--accel-smoothing` | EMA coefficient for vertical acceleration |

The effective prediction time is:

```text
lead_time = flight_time + lead_frames * last_frame_dt
```

## Calibration Work

The predictor is implemented, but `flight_time` and latency still need physical
calibration. P4/P5 should record trial videos or CSV logs and tune constants
against measured hit/miss and predicted-point error.
