# LEGO SPIKE Prime Hub + Pybricks BLE stdin/stdout bridge.
# Save this file on the Hub, then start it with the Hub CENTER button.

from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port
from pybricks.tools import StopWatch, wait
from usys import stdin, stdout
from uselect import poll

hub = PrimeHub()


def write_line(text):
    try:
        stdout.buffer.write(text.encode("utf-8") + b"\n")
    except Exception:
        pass


def safe_motor(port, label):
    try:
        motor = Motor(port)
        write_line("PORT_" + label + "_OK")
        return motor
    except Exception:
        write_line("PORT_" + label + "_MISSING")
        return None


launch_l = safe_motor(Port.A, "A")
launch_r = safe_motor(Port.B, "B")
c_motor = safe_motor(Port.C, "C")
tilt_motor = safe_motor(Port.D, "D_TILT")
pan_motor = safe_motor(Port.F, "F_PAN")

PAN_MIN = -35
PAN_MAX = 35
TILT_MIN = 0
TILT_MAX = 80
COMMAND_TIMEOUT_MS = 1000
RDY_INTERVAL_MS = 200

C_FIRE_ANGLE = 170
C_FIRE_DC = 80
C_RETURN_DC = 50
C_TOLERANCE = 3

LAUNCH_PWM_A = 100
LAUNCH_PWM_B = -100

keyboard = poll()
keyboard.register(stdin)
watch = StopWatch()


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def i8(byte_value):
    return byte_value - 256 if byte_value > 127 else byte_value


def stop_all():
    for motor in (launch_l, launch_r, c_motor, tilt_motor, pan_motor):
        if motor:
            try:
                motor.stop()
            except Exception:
                pass


def start_launcher_wheels():
    if launch_l:
        launch_l.dc(LAUNCH_PWM_A)
    if launch_r:
        launch_r.dc(LAUNCH_PWM_B)


c_state = "armed"


def c_update(can_fire):
    global c_state
    if c_motor is None:
        return False

    now = c_motor.angle()

    if c_state == "armed":
        if can_fire:
            c_motor.dc(C_FIRE_DC)
            c_state = "firing"
            write_line("FIRING")
    elif c_state == "firing":
        if now >= C_FIRE_ANGLE - C_TOLERANCE:
            c_motor.dc(-C_RETURN_DC)
            c_state = "returning"
            write_line("RETURNING")
    elif c_state == "returning":
        if now <= C_TOLERANCE:
            c_motor.stop()
            c_state = "armed"
            write_line("ARMED")
            return True

    return False


def main():
    stop_all()

    if pan_motor:
        pan_motor.reset_angle(0)
    if tilt_motor:
        tilt_motor.reset_angle(0)
    if c_motor:
        c_motor.reset_angle(0)

    start_launcher_wheels()
    hub.display.text("BT")
    write_line("READY")
    write_line("ARMED")

    while hub.buttons.pressed():
        wait(20)

    try:
        stdout.buffer.write(b"rdy")
    except Exception:
        pass

    pan_target = 0.0
    tilt_target = 0.0
    can_fire = False
    last_cmd_ms = watch.time()
    last_rdy_ms = watch.time()
    running = True

    while running:
        if keyboard.poll(0):
            data = stdin.buffer.read(4)
            if data and len(data) == 4:
                opcode = data[0]
                if opcode == ord("M"):
                    pan_val = i8(data[1])
                    tilt_val = i8(data[2])
                    fire = data[3]
                    pan_target = clamp(pan_val / 100.0 * PAN_MAX, PAN_MIN, PAN_MAX)
                    tilt_target = clamp(
                        (tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                        TILT_MIN,
                        TILT_MAX,
                    )
                    if fire == 1:
                        can_fire = True
                    last_cmd_ms = watch.time()
                elif opcode == ord("S"):
                    running = False
            try:
                stdout.buffer.write(b"rdy")
                last_rdy_ms = watch.time()
            except Exception:
                pass
        elif watch.time() - last_rdy_ms >= RDY_INTERVAL_MS:
            try:
                stdout.buffer.write(b"rdy")
                last_rdy_ms = watch.time()
            except Exception:
                pass

        try:
            if pan_motor:
                pan_motor.track_target(int(pan_target))
            if tilt_motor:
                tilt_motor.track_target(int(tilt_target))
        except Exception:
            pass

        try:
            shot_fired = c_update(can_fire)
            if shot_fired:
                write_line("FIRED")
                can_fire = False
        except Exception:
            pass

        if watch.time() - last_cmd_ms > COMMAND_TIMEOUT_MS:
            pan_target = 0.0
            tilt_target = 0.0

        if hub.buttons.pressed():
            running = False

        wait(5)

    stop_all()
    hub.display.text("X")


try:
    main()
except BaseException:
    stop_all()
    hub.display.text("X")
