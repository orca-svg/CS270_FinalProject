# Voice-BLE-Hub Safety

The voice path is fail-safe by default:

```text
microphone -> local/online STT -> control_mode.json
           -> camera fire policy -> Pybricks BLE -> Prime Hub
```

- Camera controllers always start in `safe`.
- Voice writers acquire one shared OS file lock.
- Voice startup and shutdown write `safe`.
- Heartbeats are written every 2 seconds; controllers expire state after 10 seconds.
- Expired commands cannot be restored by heartbeat alone. A new `command_id` is required.
- `single` and `burst` require confidence >= 0.60. `safe` and `guard` do not.
- JSON updates use a temporary file plus `os.replace()`.
- BLE reconnects discard pending fire requests and reset the 0.4-second target lock.
- Windows mode changes purge queued fire requests.
- Every connection validates the expected server version, ports A/B/C/D/F, `RUNNING`,
  and `rdy`. Validation failure requires an explicit `y` override for that process run.
- Launcher wheels A/B remain at full power while the Hub program runs. `safe` blocks the
  trigger but does not stop those wheels.

See the [Korean implementation record](ko/VOICE_BLE_SAFETY.md) for decisions,
data format, implementation details, and the hardware validation checklist.

