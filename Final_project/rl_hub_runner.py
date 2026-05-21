"""SPIKE Hub command runner for Q-learning aiming experiments.

Run this file on the SPIKE Hub. It intentionally does not import or modify
ShootingCode.py; the working launcher code remains untouched.

Prototype command interface:
    AIM,LEFT
    AIM,UP_RIGHT
    AIM,HOLD
    AIM_ABS,-12,35
    FIRE
    STOP

The command_source() function is the integration point for Bluetooth PAN or
socket skeleton code from class materials. Until that is wired in, commands
can be typed into the SPIKE console with input().
"""

from spike import Motor, MotorPair, PrimeHub
from spike.control import wait_for_seconds


hub = PrimeHub()

# Same port map as ShootingCode.py.
# A: left launch wheel motor
# B: right launch wheel motor
# C: rubber-band pull/release motor
# F: horizontal direction motor
# D: vertical angle motor
launch_pair = MotorPair("A", "B")
c_motor = Motor("C")
horizontal_motor = Motor("F")
vertical_motor = Motor("D")

A_SPEED = -100
B_SPEED = -100
KEEPALIVE_SECONDS = 0.02

C_LOAD_TARGET = 20
C_FIRE_TARGET = 200
C_LOAD_SPEED = 50
C_FIRE_SPEED = 100
C_TOLERANCE = 1

HORIZONTAL_CENTER_ANGLE = 0
HORIZONTAL_MIN_ANGLE = -35
HORIZONTAL_MAX_ANGLE = 35
HORIZONTAL_STEP_DEGREES = 7
HORIZONTAL_SPEED = 35
HORIZONTAL_TOLERANCE = 2

VERTICAL_LOW_ANGLE = 0
VERTICAL_HIGH_ANGLE = 80
VERTICAL_STEP_DEGREES = 7
VERTICAL_SPEED = 30
VERTICAL_TOLERANCE = 2

VALID_ACTIONS = (
    "LEFT",
    "RIGHT",
    "UP",
    "DOWN",
    "UP_LEFT",
    "UP_RIGHT",
    "DOWN_LEFT",
    "DOWN_RIGHT",
    "HOLD",
)

horizontal_target_angle = HORIZONTAL_CENTER_ANGLE
vertical_target_angle = VERTICAL_LOW_ANGLE


def clamp(value, low, high):
    return max(low, min(high, value))


def stop_all():
    launch_pair.stop()
    c_motor.stop()
    horizontal_motor.stop()
    vertical_motor.stop()


def start_launch_wheels():
    launch_pair.start_tank(A_SPEED, B_SPEED)


def signed_speed_to_target(current, target, speed, tolerance):
    error = target - current
    if abs(error) <= tolerance:
        return 0
    if error > 0:
        return speed
    return -speed


def update_position_motor(motor, target_angle, speed, tolerance):
    current_angle = motor.get_degrees_counted()
    motor_speed = signed_speed_to_target(
        current_angle,
        target_angle,
        speed,
        tolerance,
    )

    if motor_speed == 0:
        motor.stop()
        return True

    motor.start(motor_speed)
    return False


def run_motor_to_target(motor, target_angle, speed, tolerance):
    while True:
        if hub.left_button.was_pressed():
            stop_all()
            return False

        arrived = update_position_motor(motor, target_angle, speed, tolerance)
        if arrived:
            return True
        wait_for_seconds(KEEPALIVE_SECONDS)


def run_c_to_raw_target(target_raw, speed):
    while True:
        if hub.left_button.was_pressed():
            stop_all()
            return False

        arrived = update_position_motor(
            c_motor,
            target_raw,
            speed,
            C_TOLERANCE,
        )
        if arrived:
            return True

        wait_for_seconds(KEEPALIVE_SECONDS)


def load_launcher():
    return run_c_to_raw_target(C_LOAD_TARGET, C_LOAD_SPEED)


def fire_once():
    hub.light_matrix.write("FIR")
    start_launch_wheels()

    fired = run_c_to_raw_target(C_FIRE_TARGET, C_FIRE_SPEED)
    if not fired:
        launch_pair.stop()
        return False

    loaded = load_launcher()
    launch_pair.stop()
    if loaded:
        hub.light_matrix.write("OK")
    return loaded


def apply_aim_action(action):
    global horizontal_target_angle, vertical_target_angle

    if action not in VALID_ACTIONS:
        hub.light_matrix.write("BAD")
        return False

    if "LEFT" in action:
        horizontal_target_angle -= HORIZONTAL_STEP_DEGREES
    if "RIGHT" in action:
        horizontal_target_angle += HORIZONTAL_STEP_DEGREES
    if "UP" in action:
        vertical_target_angle += VERTICAL_STEP_DEGREES
    if "DOWN" in action:
        vertical_target_angle -= VERTICAL_STEP_DEGREES

    horizontal_target_angle = clamp(
        horizontal_target_angle,
        HORIZONTAL_MIN_ANGLE,
        HORIZONTAL_MAX_ANGLE,
    )
    vertical_target_angle = clamp(
        vertical_target_angle,
        VERTICAL_LOW_ANGLE,
        VERTICAL_HIGH_ANGLE,
    )

    if action == "HOLD":
        horizontal_motor.stop()
        vertical_motor.stop()
        hub.light_matrix.write("HLD")
        return True

    h_ok = run_motor_to_target(
        horizontal_motor,
        horizontal_target_angle,
        HORIZONTAL_SPEED,
        HORIZONTAL_TOLERANCE,
    )
    v_ok = run_motor_to_target(
        vertical_motor,
        vertical_target_angle,
        VERTICAL_SPEED,
        VERTICAL_TOLERANCE,
    )
    if h_ok and v_ok:
        hub.light_matrix.write("AIM")
    return h_ok and v_ok


def parse_command(raw_command):
    parts = raw_command.strip().upper().split(",")
    if not parts or parts[0] == "":
        return None, None
    if parts[0] == "AIM" and len(parts) == 2:
        return "AIM", parts[1]
    if parts[0] == "AIM_ABS" and len(parts) == 3:
        return "AIM_ABS", (parts[1], parts[2])
    return parts[0], None


def apply_absolute_aim(horizontal_angle, vertical_angle):
    global horizontal_target_angle, vertical_target_angle

    try:
        horizontal_target_angle = float(horizontal_angle)
        vertical_target_angle = float(vertical_angle)
    except ValueError:
        hub.light_matrix.write("BAD")
        return False

    horizontal_target_angle = clamp(
        horizontal_target_angle,
        HORIZONTAL_MIN_ANGLE,
        HORIZONTAL_MAX_ANGLE,
    )
    vertical_target_angle = clamp(
        vertical_target_angle,
        VERTICAL_LOW_ANGLE,
        VERTICAL_HIGH_ANGLE,
    )

    h_ok = run_motor_to_target(
        horizontal_motor,
        horizontal_target_angle,
        HORIZONTAL_SPEED,
        HORIZONTAL_TOLERANCE,
    )
    v_ok = run_motor_to_target(
        vertical_motor,
        vertical_target_angle,
        VERTICAL_SPEED,
        VERTICAL_TOLERANCE,
    )
    if h_ok and v_ok:
        hub.light_matrix.write("ABS")
    return h_ok and v_ok


def handle_command(raw_command):
    command, value = parse_command(raw_command)
    if command is None:
        return True

    if command == "AIM":
        apply_aim_action(value)
        return True

    if command == "AIM_ABS":
        horizontal_angle, vertical_angle = value
        apply_absolute_aim(horizontal_angle, vertical_angle)
        return True

    if command == "FIRE":
        fire_once()
        return True

    if command == "CENTER":
        center_launcher()
        return True

    if command == "STOP":
        stop_all()
        hub.light_matrix.write("STOP")
        return False

    hub.light_matrix.write("UNK")
    return True


def center_launcher():
    global horizontal_target_angle, vertical_target_angle
    horizontal_target_angle = HORIZONTAL_CENTER_ANGLE
    vertical_target_angle = VERTICAL_LOW_ANGLE
    run_motor_to_target(
        horizontal_motor,
        horizontal_target_angle,
        HORIZONTAL_SPEED,
        HORIZONTAL_TOLERANCE,
    )
    run_motor_to_target(
        vertical_motor,
        vertical_target_angle,
        VERTICAL_SPEED,
        VERTICAL_TOLERANCE,
    )


def command_source():
    """Yield command strings.

    Replace this function with the Bluetooth PAN/socket receiver from the
    class skeleton when available.
    """

    while True:
        try:
            yield input("cmd> ")
        except KeyboardInterrupt:
            yield "STOP"


def main():
    stop_all()
    c_motor.set_degrees_counted(C_LOAD_TARGET)
    vertical_motor.set_degrees_counted(VERTICAL_LOW_ANGLE)
    horizontal_motor.set_degrees_counted(HORIZONTAL_CENTER_ANGLE)
    hub.light_matrix.write("RL")

    print("RL hub runner ready")
    for raw_command in command_source():
        if hub.left_button.was_pressed():
            stop_all()
            hub.light_matrix.write("STOP")
            break
        keep_running = handle_command(raw_command)
        if not keep_running:
            break


main()
