# CS270 Final Project: LEGO SPIKE Prime Pan/Tilt Hand-Follow Controller

This project implements a real-time hand-following system using a laptop webcam and MediaPipe to control a LEGO SPIKE Prime pan/tilt launcher. It translates hand coordinates from the webcam into horizontal/vertical target angles and transmits them to the LEGO Hub over a Bluetooth serial link.

## Project Structure
- `hand_follow_controller.py`: The host-side (PC) controller that captures video frames, runs hand landmark detection using MediaPipe, and transmits coordinate-based angle commands over a serial port.
- `rl_hub_runner.py`: The client-side (LEGO SPIKE Prime) MicroPython runner that polls the serial stream, executes pan/tilt motor adjustments, and fires the launcher.
- `ShootingCode.py`: A standalone reference shooter script containing the optimized motor loading/firing sequence.

## Key Features Implemented

### 1. Robust Non-blocking Serial Parser
- Implemented a character-by-character non-blocking stream parser on the SPIKE Hub using `sys.stdin` and `uselect`.
- Prevents the `NameError: name 'input' isn't defined` crash common in SPIKE Prime MicroPython environments.
- Ensures the Hub's main thread does not stall, keeping the physical emergency stop button (`left_button`) fully active even during waiting intervals.

### 2. Mechanical Backlash-Compensated Firing Sequence
- Integrates a 0.5-second stabilization period before/after firing.
- Implements a recoil movement of 200 degrees backward and forward, returning to a preload state (20 degrees) to ensure consistent mechanical tension and reduce gear slippage.

## Setup and Installation

### Prerequisites
- macOS or Windows with Python 3.11+
- MediaPipe compatible webcam
- LEGO SPIKE Prime Hub paired via Bluetooth (baudrate: `115200`)

### Installation
1. Clone the repository and navigate into it:
   ```bash
   git clone https://github.com/orca-svg/CS270_FinalProject.git
   cd CS270_FinalProject
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install required dependencies:
   ```bash
   pip install opencv-python mediapipe pyserial
   ```

## How to Run

### Step 1: Upload the Hub Runner
1. Open the LEGO SPIKE App on your computer.
2. Create a new Python project.
3. Copy the entire contents of `rl_hub_runner.py` and paste it into the editor.
4. Upload and execute the script on your SPIKE Hub. The Hub's matrix display should show `"RL"`, and the terminal console should output `RL hub runner ready`.

### Step 2: Start the Host Controller
1. Find your Bluetooth serial port name (e.g., `/dev/tty.LEGOHubTEST_0207` on macOS).
2. Execute the hand controller:
   ```bash
   python hand_follow_controller.py --serial-port /dev/tty.LEGOHubTEST_0207
   ```
3. A camera window will open. Move your hand to control the launcher.
   - Press **`c`** on the window to center the launcher.
   - Press **`f`** on the window to trigger the stabilized firing sequence.
   - Press **`q`** on the window to quit the application safely.
