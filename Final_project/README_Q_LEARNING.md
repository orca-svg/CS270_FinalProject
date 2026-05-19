# Aiming AI Prototypes

This folder contains two experimental aiming approaches without changing the
existing `ShootingCode.py` or `OpenCV.py` files.

The recommended approach is now **data-driven calibration**, not hit/miss
Q-learning. It is faster to collect and easier to defend in the presentation.

## Files

- `calibration_targeting.py`: recommended. Collects `dx,dy -> pan/tilt angle`
  calibration data and runs real-time interpolation.
- `q_learning_aim_trainer.py`: run on the Raspberry Pi or laptop with the
  camera. It tracks a fluorescent marker, chooses aim actions, sends commands,
  asks for manual hit/miss feedback, and saves `q_table.json`.
- `rl_hub_runner.py`: run on the SPIKE Hub. It accepts `AIM,<ACTION>`, `FIRE`,
  `AIM_ABS,horizontal,vertical`, `CENTER`, and `STOP` commands and drives the
  launcher motors.
- `CALIBRATION_IMPLEMENTATION_PLAN.md`: implementation plan for the recommended
  calibration approach.
- `q_table.json`: created automatically after the first training episode.

## Recommended Calibration Workflow

Install dependencies on the Pi or camera laptop:

```bash
pip install opencv-python numpy
```

Collect calibration data:

```bash
python3 Final_project/calibration_targeting.py collect
```

Move the target to several image positions. Manually aim the launcher so the
reticle is aligned with the marker. Press `s`, then enter the current horizontal
and vertical motor angles. The samples are saved to:

```text
Final_project/aim_calibration.csv
```

Inspect the dataset:

```bash
python3 Final_project/calibration_targeting.py inspect
```

Run live prediction without Hub connection:

```bash
python3 Final_project/calibration_targeting.py run --dry-run
```

Run live prediction through a TCP bridge:

```bash
python3 Final_project/calibration_targeting.py run --host <bridge-ip> --port 9999
```

During run mode:

- `f` sends `FIRE`
- `c` sends `CENTER`
- `q` quits

## Learning Design

This section describes the older Q-learning prototype. Keep it as a backup, but
prefer the calibration workflow above.

- State: `dx,dy` camera error discretized into 3 by 3 bins.
- Actions: `LEFT`, `RIGHT`, `UP`, `DOWN`, `UP_LEFT`, `UP_RIGHT`,
  `DOWN_LEFT`, `DOWN_RIGHT`, `HOLD`.
- Episode: detect target, run 5 aim correction steps, fire once, enter hit/miss.
- Reward: hit is `+1`, miss is `-1`.
- Policy: epsilon-greedy Q-learning.
- Defaults: `alpha=0.2`, `gamma=0.9`, epsilon decays from `0.3` to `0.05`.

## Dry-run Test

Use dry-run first. It exercises camera tracking and Q-table updates without
connecting to the Hub.

```bash
python3 Final_project/q_learning_aim_trainer.py --dry-run --episodes 3
```

Press `q` in the camera window to quit. After each `FIRE`, type:

- `h` for hit
- `m` for miss
- `q` to stop

## Marker Tuning

The default HSV range is for a bright green marker:

```bash
--hsv-low 35,80,80 --hsv-high 90,255,255
```

If detection is unstable, tune the values:

- Increase `--min-area` to ignore small noise.
- Decrease `--min-area` if the marker is far away.
- Adjust hue range for the actual marker color.
- Keep lighting as constant as possible.

## Hub Test

Run `rl_hub_runner.py` on the SPIKE Hub. With the current prototype command
source, type commands into the console:

```text
AIM,LEFT
AIM,UP_RIGHT
AIM_ABS,-12,35
AIM,HOLD
FIRE
CENTER
STOP
```

The file has a `command_source()` function that should be replaced with the
Bluetooth PAN/socket receiver from the class skeleton when that code is ready.

## TCP Integration Hook

The trainer already supports a simple TCP command sender for later integration:

```bash
python3 Final_project/q_learning_aim_trainer.py --host <hub-or-bridge-ip> --port 9999
```

If the Hub cannot directly run a TCP server, use a bridge process on the
Raspberry Pi or laptop that receives these commands and forwards them through
the Bluetooth PAN/socket code from class.

## Presentation Wording

Use this wording instead of claiming a DQN implementation:

> We implemented a lightweight Q-learning prototype for real-hardware aiming.
> The camera extracts the target error vector as state, the agent selects one
> of nine pan-tilt correction actions, and after each shot we manually label
> hit or miss as the reward. This lets the system gradually update its aiming
> policy from real launcher feedback while keeping the control loop simple
> enough for the LEGO SPIKE and Raspberry Pi environment.
