# LEGO SPIKE Prime Hub + Pybricks BLE stdin/stdout bridge.
# Save this file on the Hub. Mac-side tools can start it remotely over BLE.

from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port
from pybricks.tools import StopWatch, wait
from usys import stdin, stdout
from uselect import poll

hub = PrimeHub()
SERVER_VERSION = "gesture_server_2026_06_03_fire_spinup_state"


def write_line(text):
    try:
        stdout.write(text + "\n")
    except Exception:
        try:
            stdout.buffer.write((text + "\n").encode("utf-8"))
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
TILT_MIN = 10
TILT_MAX = 120
COMMAND_TIMEOUT_MS = 1000
DEBUG_CMD_LINES = True

# Absolute home references: the motor.angle() readings at the calibrated home
# pose. We do NOT reset_angle, so these absolute-encoder values are reported
# identically after every (re)start. Camera offsets are applied on top, so the
# turret aims at a fixed world point even when the program restarts on a
# reconnect AND the SHOT calibration angles stay consistent across sessions.
# Verify/recalibrate against the "HOME_CHECK" line on a fresh start.
PAN_HOME = -172   # Port F (pan) at pan center -> camera offset 0
TILT_HOME = -20   # Port D (tilt) at tilt bottom (tilt 0 deg)
C_HOME = 43       # Port C (trigger) armed/rest position

C_FIRE_TRAVEL = 190   # degrees the C trigger rotates per shot (relative to arm)
C_FIRE_DC = 100
C_RETURN_DC = 100
C_TOLERANCE = 3
C_LAUNCH_SPINUP_MS = 350
C_FIRE_TIMEOUT_MS = 400
C_RETURN_TIMEOUT_MS = 400

LAUNCH_PWM_A = 100
LAUNCH_PWM_B = -100
SPIN_LAUNCH_ON_START = True

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


def motor_angle(motor):
    if motor is None:
        return "NA"
    try:
        return str(motor.angle())
    except Exception:
        return "ERR"


def start_launcher_wheels():
    ok = True
    if launch_l:
        try:
            launch_l.dc(LAUNCH_PWM_A)
        except Exception:
            write_line("LAUNCH_A_DC_ERR")
            ok = False
    else:
        write_line("LAUNCH_A_MISSING")
        ok = False
    if launch_r:
        try:
            launch_r.dc(LAUNCH_PWM_B)
        except Exception:
            write_line("LAUNCH_B_MISSING")
            ok = False
    return ok


def stop_launcher_wheels():
    for motor in (launch_l, launch_r):
        if motor:
            try:
                motor.stop()
            except Exception:
                pass


c_state = "armed"
c_state_started_ms = 0
FIRE_NONE = 0
FIRE_CONSUMED = 1
FIRE_DONE = 2


def c_update(can_fire):
    global c_state, c_state_started_ms
    if c_motor is None:
        return FIRE_NONE

    now = c_motor.angle()
    elapsed = watch.time() - c_state_started_ms

    if c_state == "armed":
        if can_fire:
            write_line("FIRE_REQ")
            # 발사 휠은 이미 항상 돌고 있으므로, spinup 단계를 거치지 않고 바로 firing 단계로 진입하거나 spinup 대기 시간을 0으로 처리합니다.
            c_state = "firing"
            c_state_started_ms = watch.time()
            try:
                c_motor.dc(C_FIRE_DC)
            except Exception:
                write_line("C_FIRE_DC_ERR")
                c_state = "armed"
                return FIRE_CONSUMED
            write_line("FIRING")
            write_line(
                "SHOT f=" + motor_angle(pan_motor) + " d=" + motor_angle(tilt_motor)
            )
            return FIRE_CONSUMED
    elif c_state == "firing":
        if now >= C_HOME + C_FIRE_TRAVEL - C_TOLERANCE or elapsed >= C_FIRE_TIMEOUT_MS:
            try:
                c_motor.dc(-C_RETURN_DC)
            except Exception:
                write_line("C_RETURN_DC_ERR")
                c_motor.stop()
                c_state = "armed"
                return FIRE_DONE
            c_state = "returning"
            c_state_started_ms = watch.time()
            write_line("RETURNING")
    elif c_state == "returning":
        if now <= C_HOME + C_TOLERANCE or elapsed >= C_RETURN_TIMEOUT_MS:
            c_motor.stop()
            # 발사 완료 후에도 휠 모터를 정지하지 않습니다.
            c_state = "armed"
            write_line("ARMED")
            return FIRE_DONE

    return FIRE_NONE


# Global variable to track periodic report timing
last_angle_print_ms = 0

def main():
    global last_angle_print_ms
    stop_all()
    # 기동하자마자 가속 휠 모터를 100%로 가동합니다.
    if SPIN_LAUNCH_ON_START:
        start_launcher_wheels()

    # Do NOT reset_angle. Resetting would redefine "0" at wherever the turret
    # physically sits at each (re)start, so after a reconnect-triggered restart
    # the camera offsets would drift AND the SHOT calibration angles would be
    # inconsistent between sessions. Keep absolute encoder readings and aim at
    # HOME + camera offset. HOME_CHECK reports the live angles so PAN_HOME/
    # TILT_HOME/C_HOME can be verified or recalibrated against the boot pose.
    write_line(
        "HOME_CHECK pan_angle=" + motor_angle(pan_motor)
        + " tilt_angle=" + motor_angle(tilt_motor)
        + " c_angle=" + motor_angle(c_motor)
        + " (expected pan=" + str(PAN_HOME)
        + " tilt=" + str(TILT_HOME)
        + " c=" + str(C_HOME) + ")"
    )
    write_line("SERVER_VERSION " + SERVER_VERSION)

    # 모터 최고 구동 속도 및 가속도 상향 설정 (조준 반응 속도 극대화)
    # (언제든 롤백할 수 있도록 기본 제한값들을 주석으로 기록해 둡니다)
    # 기본값: speed=약 360~480, acceleration=약 1200~1600 (하드웨어/배터리 상황에 따라 자동 정의)
    if pan_motor:
        try:
            pan_motor.control.limits(speed=1000, acceleration=4000)
        except Exception:
            pass
    if tilt_motor:
        try:
            # 위로 갈 때의 limits 보정은 메인 루프 안에서 동적으로 동작하므로,
            # 여기서는 초기 기본 limits 한계치를 1000, 4000으로 설정해 줍니다.
            tilt_motor.control.limits(speed=1000, acceleration=4000)
        except Exception:
            pass

    hub.display.text("BT")
    write_line("READY")
    write_line("ARMED")

    while hub.buttons.pressed():
        wait(20)

    try:
        stdout.buffer.write(b"rdy")
    except Exception:
        pass

    # pan_target / tilt_target are camera offsets (deg) relative to HOME, NOT
    # absolute motor angles. The absolute track target is HOME + offset.
    pan_target = 0.0
    tilt_target = 0.0
    # Hold position until the first camera command arrives. On a reconnect this
    # stops the turret from snapping back to HOME first; it moves directly to
    # the world position the camera asks for.
    have_target = False
    can_fire = False
    last_cmd_ms = watch.time()
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
                    if fire == 1 and c_state == "armed":
                        can_fire = True
                    have_target = True
                    last_cmd_ms = watch.time()
                    if DEBUG_CMD_LINES:
                        write_line(
                            "CMD pan_val="
                            + str(pan_val)
                            + " tilt_val="
                            + str(tilt_val)
                            + " pan_abs="
                            + str(int(PAN_HOME + pan_target))
                            + " tilt_abs="
                            + str(int(TILT_HOME + tilt_target))
                            + " pan_angle="
                            + motor_angle(pan_motor)
                            + " tilt_angle="
                            + motor_angle(tilt_motor)
                        )
                # Do not stop on stdin packets. The Mac side uses the
                # Pybricks remote STOP command when it intentionally exits.
                # Treating any stdin payload as STOP can terminate the Hub
                # program if BLE stdin framing is ever offset by a byte.
            try:
                stdout.buffer.write(b"rdy")
            except Exception:
                pass

        try:
            if have_target:
                if pan_motor:
                    pan_motor.track_target(int(PAN_HOME + pan_target))
                if tilt_motor:
                    goal_tilt = int(TILT_HOME + tilt_target)
                    curr_tilt = tilt_motor.angle()
                    # 위로 들어올리는 기동 (목표각이 현재각보다 높을 때)
                    if goal_tilt > curr_tilt + 2:
                        # 한계 전압/토크 세기를 최대로 높여서 힘을 강하게 줍니다 (가속도와 토크 한계 조정)
                        # Pybricks limits: (speed, acceleration, torque)
                        # 기본 토크보다 넉넉하게 100% 한계치(또는 1000mNm 등 큰 값)를 부여하여 중력을 이기게 합니다.
                        tilt_motor.control.limits(torque=1000)
                    else:
                        # 평소 수준(기본 토크 한계)으로 원복하여 모터 부하와 발열을 방지합니다.
                        tilt_motor.control.limits(torque=300)
                    
                    tilt_motor.track_target(goal_tilt)
        except Exception:
            pass

        try:
            fire_result = c_update(can_fire)
            if fire_result != FIRE_NONE:
                can_fire = False
            if fire_result == FIRE_DONE:
                write_line("FIRED")
        except Exception:
            write_line("C_UPDATE_ERR")
            can_fire = False

        if watch.time() - last_cmd_ms > COMMAND_TIMEOUT_MS:
            pan_target = 0.0
            tilt_target = 0.0

        # 주기적으로 현재 모터 실제 각도 및 rdy 하트비트 송신 (200ms 간격)
        if watch.time() - last_angle_print_ms > 200:
            write_line(
                "ANGLE_REPORT pan=" + motor_angle(pan_motor)
                + " tilt=" + motor_angle(tilt_motor)
            )
            try:
                stdout.buffer.write(b"rdy")
            except Exception:
                pass
            last_angle_print_ms = watch.time()

        wait(5)

    stop_all()
    hub.display.text("X")


try:
    main()
except Exception as exc:
    write_line("HUB_EXCEPTION " + str(exc))
    stop_all()
    hub.display.text("X")
