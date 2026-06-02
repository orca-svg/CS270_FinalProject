# State Machines

## Hub Firing Flow

```mermaid
stateDiagram-v2
  [*] --> READY
  READY --> ARMED: motors available
  ARMED --> FIRING: fire byte = 1
  FIRING --> RETURNING: fire angle reached or timeout
  RETURNING --> ARMED: reload complete
  ARMED --> STOPPED: STOP or Hub button
  FIRING --> STOPPED: STOP or Hub button
  RETURNING --> STOPPED: STOP or Hub button
```

The Hub keeps pan/tilt tracking independent from the firing state so the turret
can continue aiming while the launcher is armed.

The Hub prints angle snapshots during the shot:

| Log | Timing |
|-----|--------|
| `SHOT_START` | `fire=1` is accepted and the C motor starts moving |
| `SHOT_RELEASE` | The C motor reaches `C_FIRE_ANGLE - C_TOLERANCE` |
| `SHOT_DONE` | The C motor returns to the armed position |

Each snapshot includes actual `pan_F`, `tilt_D`, `c_C` motor angles plus
`target_pan` and `target_tilt`.

## Mac Target Interception Flow

```mermaid
stateDiagram-v2
  [*] --> Detecting
  Detecting --> Tracking: HSV target found
  Tracking --> Detecting: target lost
  Tracking --> Locked: predicted point within threshold
  Locked --> Tracking: predicted point leaves threshold
  Locked --> FireLatch: hold frames satisfied
  FireLatch --> Tracking: send M,dx,dy,1 once
```

`balloon_intercept.py` sends `fire=1` only for one packet. Subsequent packets
return to `fire=0` while pan/tilt error continues to update.

## Hand Gesture Flow

Palm-visible frames drive pan/tilt error. A fist transition latches `fire=1`
once, then clears the fire byte on the next send interval.
