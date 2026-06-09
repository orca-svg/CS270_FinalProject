# Local Voice Recognition

`voice_commander_local.py` runs Whisper locally and writes recognized fire modes
to `control_mode.json`. Apple Silicon macOS uses MLX Whisper; Windows uses
faster-whisper. Both use the same microphone VAD and command parser.

Models are downloaded automatically on first use and then reused from the user
cache. The defaults are `mlx-community/whisper-base-mlx` on macOS and `base` on
Windows.

## macOS Apple Silicon

```bash
cd "/path/to/Final_project"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r gesture_bt/requirements_voice_mlx.txt
cd gesture_bt
python voice_commander_local.py --list-devices
python voice_commander_local.py --backend mlx --language ko
```

## Windows PowerShell

Python 3.11 or 3.12, 64-bit, is recommended.

```powershell
cd "C:\path\to\Final_project"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r gesture_bt\requirements_voice_windows.txt
cd gesture_bt
python voice_commander_local.py --list-devices
python voice_commander_local.py --backend faster-whisper --model base `
  --compute-device cpu --compute-type int8 --language ko
```

Run camera and voice in separate terminals. Use `balloon_tracker_offline.py`
without a robot, or `balloon_intercept.py` / `balloon_intercept_win.py` with the
Hub. See [the Korean guide](ko/LOCAL_VOICE.md) for the complete staged procedure
and latency tuning options.
