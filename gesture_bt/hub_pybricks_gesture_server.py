# hub_pybricks_gesture_server.py
# LEGO SPIKE Prime Hub + Pybricks BLE stdin/stdout bridge.
# V8: position-tracking + fire state machine
#
# PC sends exactly 4 bytes per command (after 0x06 prefix):
#   b'M', pan_err_i8, tilt_err_i8, fire(0/1)
#     -> accumulate target angle: pan_target -= PAN_SIGN * pan_err * GAIN
#     -> fire=1 latches one shot
#   b'S', 0, 0, 0  -> stop all and exit

from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port, Stop
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


launch_l  = safe_motor(Port.A, "A")
launch_r  = safe_motor(Port.B, "B")
c_motor   = safe_motor(Port.C, "C")
tilt_motor = safe_motor(Port.D, "D_TILT")
pan_motor  = safe_motor(Port.F, "F_PAN")

# --- motion constants (tune these if directions/ranges are wrong) ---
# 웹캠은 포탑과 독립. Mac이 픽셀 좌표를 절대 각도로 직접 변환하여 전송한다.
# Pan  byte: [-100, +100] → [PAN_MIN, PAN_MAX]
# Tilt byte: [-100, +100] → [TILT_MIN, TILT_MAX]  (-100=TILT_MIN, +100=TILT_MAX)
PAN_MIN    = -35    # degrees
PAN_MAX    =  35
TILT_MIN   =   0
TILT_MAX   =  80
PAN_SPEED  = 600    # deg/s for track_target
TILT_SPEED = 500
COMMAND_TIMEOUT_MS = 1000
RDY_INTERVAL_MS   = 200  # rdy를 못 받은 Mac을 복구하기 위한 주기적 재전송 간격

# --- C motor constants (왕복 방식) ---
# 시작 위치(0°) = 장전 완료 상태. 로봇을 장전 위치에 놓고 Run할 것.
# 발사: 0° → C_FIRE_ANGLE° 전진 (고무줄 해제)
# 재장전: C_FIRE_ANGLE° → 0° 후진 (원위치)
C_FIRE_ANGLE  = 170  # 발사 위치 (degrees). 실제 메커니즘에 맞게 조정
C_FIRE_DC     = 80  # 전진(발사) dc %
C_RETURN_DC   = 50  # 후진(재장전) dc %
C_TOLERANCE   = 3   # degrees

# --- launcher wheels (A/B spin opposite directions to launch) ---
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
    for m in (launch_l, launch_r, c_motor, tilt_motor, pan_motor):
        if m:
            try:
                m.stop()
            except Exception:
                pass


def start_launcher_wheels():
    if launch_l:
        launch_l.dc(LAUNCH_PWM_A)
    if launch_r:
        launch_r.dc(LAUNCH_PWM_B)


# --- C motor state machine (왕복 방식) ---
# armed   : 장전 완료(0°), 발사 대기. 모터 정지.
# firing  : 전진 → C_FIRE_ANGLE° (발사/고무줄 해제)
# returning: 후진 → 0° (재장전)

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
            return True  # 발사+재장전 완료

    return False


def main():
    stop_all()

    # Reset motor reference angles (robot must be at center/low/fire position)
    if pan_motor:
        pan_motor.reset_angle(0)
    if tilt_motor:
        tilt_motor.reset_angle(0)
    # C모터: 현재 물리 위치를 장전 완료(0°)로 기준 설정
    # → 로봇을 장전 완료 상태로 놓고 Run할 것
    if c_motor:
        c_motor.reset_angle(0)

    start_launcher_wheels()
    hub.display.text("BT")
    write_line("READY")
    write_line("ARMED")

    while hub.buttons.pressed():
        wait(20)

    # Send initial rdy so Mac can begin
    try:
        stdout.buffer.write(b"rdy")
    except Exception:
        pass

    pan_target  = 0.0
    tilt_target = 0.0
    can_fire    = False
    last_cmd_ms = watch.time()
    last_rdy_ms = watch.time()
    running = True

    while running:
        # --- non-blocking BLE packet check ---
        if keyboard.poll(0):
            data = stdin.buffer.read(4)
            if data and len(data) == 4:
                opcode = data[0]
                if opcode == ord("M"):
                    pan_val  = i8(data[1])   # -100..+100
                    tilt_val = i8(data[2])   # -100..+100
                    fire     = data[3]
                    # 절대 각도 직접 설정 (고정 카메라 → 독립 모터 구조)
                    # pan_val: -100 → PAN_MIN(-35°), +100 → PAN_MAX(+35°)
                    pan_target  = clamp(pan_val  / 100.0 * PAN_MAX,
                                        PAN_MIN, PAN_MAX)
                    # tilt_val: -100 → TILT_MIN(0°), +100 → TILT_MAX(80°)
                    tilt_target = clamp(
                        (tilt_val + 100) / 200.0 * (TILT_MAX - TILT_MIN) + TILT_MIN,
                        TILT_MIN, TILT_MAX)
                    if fire == 1:
                        can_fire = True   # latch until shot fires
                    last_cmd_ms = watch.time()
                elif opcode == ord("S"):
                    running = False
            # Acknowledge: ready for next packet
            try:
                stdout.buffer.write(b"rdy")
                last_rdy_ms = watch.time()
            except Exception:
                pass

        # --- periodic rdy heartbeat: rdy 손실 시 Mac 데드락 복구 ---
        elif watch.time() - last_rdy_ms >= RDY_INTERVAL_MS:
            try:
                stdout.buffer.write(b"rdy")
                last_rdy_ms = watch.time()
            except Exception:
                pass

        # --- pan / tilt position tracking ---
        try:
            if pan_motor:
                pan_motor.track_target(int(pan_target))
            if tilt_motor:
                tilt_motor.track_target(int(tilt_target))
        except Exception:
            pass

        # --- C motor state machine ---
        try:
            shot_fired = c_update(can_fire)
            if shot_fired:
                write_line("FIRED")
                can_fire = False   # 래치 해제, 다음 주먹 = 다음 발사
        except Exception:
            pass

        # --- safety timeout ---
        if watch.time() - last_cmd_ms > COMMAND_TIMEOUT_MS:
            pan_target  = 0.0
            tilt_target = 0.0

        # --- hub button emergency stop ---
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
