# hub_pybricks_gesture_server.py
# LEGO SPIKE Prime Hub + Pybricks BLE stdin/stdout bridge.
# Current Hub program: position-tracking + fire state machine
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
PAN_SIGN   = 1      # flip to -1 if pan moves opposite direction
TILT_SIGN  = 1      # flip to -1 if tilt moves opposite direction
PAN_MIN    = -35    # degrees
PAN_MAX    =  35
TILT_MIN   =   0
TILT_MAX   =  80
PAN_SPEED  = 600    # deg/s for track_target
TILT_SPEED = 500
GAIN       = 0.05   # degrees of target change per 1 unit of error
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

# --- 수신 프레이밍 (디싱크 자가 치유) ---
# stdin은 4바이트 프레임의 연속이지만, 부분 읽기/바이트 유실/재시작 잔여 바이트로
# 정렬이 깨질 수 있다. opcode가 유효하지 않으면 1바이트씩 버려 재동기화한다.
rx_buf = bytearray()
VALID_OPCODES = (ord("M"), ord("S"))
RX_BUF_MAX = 64  # 폭주 시 메모리 보호

# --- 루프 예외를 조용히 삼키지 않고 노출 (1초당 1회로 throttle) ---
_last_err_ms = 0


def loop_err(tag, exc):
    global _last_err_ms
    now = watch.time()
    if now - _last_err_ms > 1000:
        write_line("ERR_" + tag + ":" + str(exc))
        _last_err_ms = now


def drain_stdin():
    """시작 시 재시작 이전에 남은 잔여 바이트를 비워 디싱크를 예방한다."""
    dropped = 0
    while keyboard.poll(0):
        b = stdin.buffer.read(1)
        if not b:
            break
        dropped += 1
    if dropped:
        write_line("FLUSH_STDIN:" + str(dropped))


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


def angle_text(motor):
    if motor is None:
        return "NA"
    try:
        return str(motor.angle())
    except Exception:
        return "ERR"


def write_angle_log(label, pan_target, tilt_target):
    write_line(
        label
        + " pan_F=" + angle_text(pan_motor)
        + " tilt_D=" + angle_text(tilt_motor)
        + " c_C=" + angle_text(c_motor)
        + " target_pan=" + str(int(pan_target))
        + " target_tilt=" + str(int(tilt_target))
    )


# --- C motor state machine (왕복 방식) ---
# armed   : 장전 완료(0°), 발사 대기. 모터 정지.
# firing  : 전진 → C_FIRE_ANGLE° (발사/고무줄 해제)
# returning: 후진 → 0° (재장전)

c_state = "armed"


def c_update(can_fire, pan_target, tilt_target):
    global c_state
    if c_motor is None:
        return False

    now = c_motor.angle()

    if c_state == "armed":
        if can_fire:
            c_motor.dc(C_FIRE_DC)
            c_state = "firing"
            write_angle_log("SHOT_START", pan_target, tilt_target)
            write_line("FIRING")

    elif c_state == "firing":
        if now >= C_FIRE_ANGLE - C_TOLERANCE:
            write_angle_log("SHOT_RELEASE", pan_target, tilt_target)
            c_motor.dc(-C_RETURN_DC)
            c_state = "returning"
            write_line("RETURNING")

    elif c_state == "returning":
        if now <= C_TOLERANCE:
            c_motor.stop()
            c_state = "armed"
            write_angle_log("SHOT_DONE", pan_target, tilt_target)
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

    # 재시작 시 이전 세션의 잔여 stdin 바이트를 비워 디싱크를 예방
    rx_buf[:] = b""
    drain_stdin()

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
        # --- 사용 가능한 모든 바이트를 1바이트씩 비차단으로 흡수 ---
        while keyboard.poll(0):
            b = stdin.buffer.read(1)
            if not b:
                break
            rx_buf.extend(b)
        # 폭주 시 메모리 보호: 뒤쪽 RX_BUF_MAX 바이트만 유지
        if len(rx_buf) > RX_BUF_MAX:
            del rx_buf[0:len(rx_buf) - RX_BUF_MAX]

        # --- 완전한 4바이트 프레임 처리 (자가 치유 재동기화) ---
        processed = False
        while len(rx_buf) >= 4:
            if rx_buf[0] not in VALID_OPCODES:
                # 정렬이 깨짐 → 1바이트 버리고 재동기화
                del rx_buf[0]
                continue
            opcode = rx_buf[0]
            d1, d2, d3 = rx_buf[1], rx_buf[2], rx_buf[3]
            del rx_buf[0:4]
            if opcode == ord("M"):
                pan_err  = i8(d1)
                tilt_err = i8(d2)
                fire     = d3
                pan_target  = clamp(pan_target  - PAN_SIGN  * pan_err  * GAIN, PAN_MIN,  PAN_MAX)
                tilt_target = clamp(tilt_target - TILT_SIGN * tilt_err * GAIN, TILT_MIN, TILT_MAX)
                if fire == 1:
                    can_fire = True   # latch until shot fires
                last_cmd_ms = watch.time()
            elif opcode == ord("S"):
                running = False
            processed = True

        # --- rdy: 패킷을 처리했거나 주기적 하트비트 시점이면 송신 ---
        if processed or (watch.time() - last_rdy_ms >= RDY_INTERVAL_MS):
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
        except Exception as e:
            loop_err("TRACK", e)

        # --- C motor state machine ---
        try:
            shot_fired = c_update(can_fire, pan_target, tilt_target)
            if shot_fired:
                write_line("FIRED")
                can_fire = False   # 래치 해제, 다음 주먹 = 다음 발사
        except Exception as e:
            loop_err("CMOTOR", e)

        # --- safety timeout ---
        if watch.time() - last_cmd_ms > COMMAND_TIMEOUT_MS:
            pan_target  = 0.0
            tilt_target = 0.0

        # --- hub button emergency stop ---
        if hub.buttons.pressed():
            write_line("BTN_STOP")
            running = False

        wait(5)

    stop_all()
    hub.display.text("X")


try:
    main()
except BaseException as e:
    # 왜 멈췄는지 Mac 로그에 남긴다 (연결이 살아있으면 전달됨)
    try:
        write_line("FATAL:" + str(e))
    except Exception:
        pass
    stop_all()
    hub.display.text("X")
