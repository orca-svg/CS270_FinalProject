from spike import Motor, MotorPair, PrimeHub
from spike.control import Timer, wait_for_seconds


hub = PrimeHub()
timer = Timer()

# Port map
# A: left launch wheel motor
# B: right launch wheel motor
# C: rubber-band pull/release motor
# D: horizontal direction motor
# F: vertical angle motor
launch_pair = MotorPair("A", "B")
c_motor = Motor("C")
horizontal_motor = Motor("F")
vertical_motor = Motor("D")


A_SPEED = -100
B_SPEED = -100
KEEPALIVE_SECONDS = 0.02
MAX_SHOTS = 7
ENABLE_FIRE = True
ENABLE_HORIZONTAL_MOVE = True
ENABLE_VERTICAL_MOVE = False

C_LOAD_TARGET = 20
C_FIRE_TARGET = 200
C_LOAD_SPEED = 50
C_FIRE_SPEED = 100
C_TOLERANCE = 1

VERTICAL_LOW_ANGLE = 0
VERTICAL_HIGH_ANGLE = 80
VERTICAL_SPEED = 30
VERTICAL_TOLERANCE = 2

HORIZONTAL_CENTER_ANGLE = 0
HORIZONTAL_LEFT_ANGLE = -35
HORIZONTAL_RIGHT_ANGLE = 35
HORIZONTAL_SPEED = 35
HORIZONTAL_TOLERANCE = 2


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


def start_c_loading():
    return "loading", C_LOAD_TARGET


def update_c_motor(state, target_raw, can_fire):
    if state == "loading":
        arrived = update_position_motor(
            c_motor,
            target_raw,
            C_LOAD_SPEED,
            C_TOLERANCE,
        )
        if arrived:
            return "loaded", target_raw, False

        return state, target_raw, False

    if state == "loaded":
        c_motor.stop()
        if can_fire:
            return "firing", C_FIRE_TARGET, False
        return state, target_raw, False

    if state == "firing":
        arrived = update_position_motor(
            c_motor,
            target_raw,
            C_FIRE_SPEED,
            C_TOLERANCE,
        )
        if arrived:
            return "fired", target_raw, True

        return state, target_raw, False

    c_motor.stop()
    return state, target_raw, False


def update_vertical_motor(target_angle):
    arrived = update_position_motor(
        vertical_motor,
        target_angle,
        VERTICAL_SPEED,
        VERTICAL_TOLERANCE,
    )

    if not arrived:
        return target_angle

    if target_angle == VERTICAL_HIGH_ANGLE:
        return VERTICAL_LOW_ANGLE
    return VERTICAL_HIGH_ANGLE


def horizontal_target_for_phase(phase):
    if phase == "aim_left":
        return HORIZONTAL_LEFT_ANGLE
    if phase == "aim_right":
        return HORIZONTAL_RIGHT_ANGLE
    return HORIZONTAL_CENTER_ANGLE


def next_horizontal_phase_after_side(phase):
    if phase == "aim_left":
        return "center_after_left"
    return "center_after_right"


def next_horizontal_phase_after_center(phase):
    if phase == "center_after_left":
        return "aim_right"
    return "aim_left"


def run_performance():
    shot_count = 0
    c_state, c_target_raw = start_c_loading()
    vertical_target_angle = VERTICAL_HIGH_ANGLE
    horizontal_phase = "aim_left"

    if ENABLE_FIRE:
        hub.light_matrix.write("GO")
    else:
        hub.light_matrix.write("MOVE")

    while not ENABLE_FIRE or shot_count < MAX_SHOTS:
        if hub.left_button.was_pressed():
            break

        if ENABLE_FIRE:
            start_launch_wheels()
        else:
            launch_pair.stop()
            c_motor.stop()

        if ENABLE_VERTICAL_MOVE:
            vertical_target_angle = update_vertical_motor(vertical_target_angle)
        else:
            vertical_motor.stop()

        if ENABLE_HORIZONTAL_MOVE:
            horizontal_target_angle = horizontal_target_for_phase(horizontal_phase)
            horizontal_arrived = update_position_motor(
                horizontal_motor,
                horizontal_target_angle,
                HORIZONTAL_SPEED,
                HORIZONTAL_TOLERANCE,
            )
        else:
            horizontal_motor.stop()
            horizontal_arrived = True

        shot_fired = False
        if ENABLE_FIRE:
            can_fire = not ENABLE_HORIZONTAL_MOVE or (
                horizontal_phase in ("aim_left", "aim_right")
                and horizontal_arrived
            )
            c_state, c_target_raw, shot_fired = update_c_motor(
                c_state,
                c_target_raw,
                can_fire,
            )

        if shot_fired:
            shot_count += 1
            hub.light_matrix.write(str(shot_count))
            horizontal_phase = next_horizontal_phase_after_side(horizontal_phase)
            c_state, c_target_raw = start_c_loading()
        elif ENABLE_HORIZONTAL_MOVE and horizontal_arrived:
            if horizontal_phase in ("center_after_left", "center_after_right"):
                horizontal_phase = next_horizontal_phase_after_center(horizontal_phase)
            elif not ENABLE_FIRE:
                horizontal_phase = next_horizontal_phase_after_side(horizontal_phase)

        wait_for_seconds(KEEPALIVE_SECONDS)

    stop_all()
    hub.light_matrix.write("RDY")


stop_all()
c_motor.set_degrees_counted(C_LOAD_TARGET)
vertical_motor.set_degrees_counted(VERTICAL_LOW_ANGLE)
horizontal_motor.set_degrees_counted(HORIZONTAL_CENTER_ANGLE)
hub.light_matrix.write("RDY")

print("Performance launcher ready")
while True:
    if hub.left_button.was_pressed():
        stop_all()
        hub.light_matrix.write("STOP")
        break

    if hub.right_button.was_pressed():
        run_performance()

    wait_for_seconds(0.05)
