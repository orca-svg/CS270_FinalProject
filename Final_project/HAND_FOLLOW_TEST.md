# Hand-follow Test Plan

This is the quickest demo path before the full calibration dataset is ready.
The laptop camera tracks a hand and sends absolute pan/tilt commands to the
LEGO SPIKE Hub so the launcher head follows the hand.

## 1. Install Dependencies on the Laptop

```bash
pip install opencv-python mediapipe
```

## 2. Dry-run Camera Test

Run this first without connecting the Hub:

```bash
python3 Final_project/hand_follow_controller.py --dry-run
```

Expected behavior:

- A camera window opens.
- Your palm landmarks are drawn.
- The green hand center follows your hand.
- The terminal prints commands like:

```text
[DRY-RUN] AIM_ABS,-12.34,48.20
```

Controls:

- `q`: quit
- `c`: send `CENTER`
- `f`: send `FIRE`

If left/right feels reversed, run:

```bash
python3 Final_project/hand_follow_controller.py --dry-run --no-mirror
```

## 3. Hub-side Manual Test

Run `rl_hub_runner.py` on the SPIKE Hub.

Before connecting live tracking, type commands manually:

```text
AIM_ABS,-20,40
AIM_ABS,20,40
AIM_ABS,0,70
AIM_ABS,0,10
CENTER
STOP
```

Confirm:

- Negative horizontal angle moves one way.
- Positive horizontal angle moves the other way.
- Larger vertical angle points upward.
- `FIRE` moves the C motor from 20 to 200, then returns from 200 to 20
  for the next projectile.
- `CENTER` returns to the neutral position.

If direction is reversed, adjust the sign in `hand_follow_controller.py` by
using `--gain -1.0` only for quick testing, or fix the motor direction mapping
in the Hub code.

## 4. Live Connection

The laptop script can send commands to a TCP bridge:

```bash
python3 Final_project/hand_follow_controller.py --host <bridge-ip> --port 9999
```

The bridge must forward newline-delimited commands to the Hub:

```text
AIM_ABS,horizontal,vertical
CENTER
FIRE
STOP
```

If you use the class Bluetooth PAN/socket skeleton, the only required behavior
is to pass these command strings into `handle_command()` in `rl_hub_runner.py`.

## 5. Tuning

Start conservative:

```bash
python3 Final_project/hand_follow_controller.py --dry-run --gain 0.6 --send-interval 0.3
```

Then increase responsiveness:

```bash
python3 Final_project/hand_follow_controller.py --dry-run --gain 1.0 --send-interval 0.2
```

Useful parameters:

- `--gain`: bigger values move farther for the same hand offset.
- `--smoothing`: bigger values react faster but jitter more.
- `--send-interval`: smaller values send commands more frequently.
- `--horizontal-min/max`: mechanical safety range for left/right.
- `--vertical-min/max`: mechanical safety range for up/down.

## 6. Demo Goal

For the interim demo, do not fire automatically. Show:

```text
hand moves left/right/up/down
-> laptop camera tracks palm center
-> laptop sends AIM_ABS commands
-> LEGO pan/tilt head follows the hand
```

After this works, reuse the same command path for missile marker tracking.
