# Angle reader for manual HOME calibration.
# Upload this file to Pybricks Code, run it, move the turret by hand, and read
# the printed absolute motor angles. It does not emit BLE rdy spam.

from pybricks.hubs import PrimeHub
from pybricks.pupdevices import Motor
from pybricks.parameters import Port
from pybricks.tools import wait

hub = PrimeHub()


def safe_motor(port, label):
    try:
        motor = Motor(port)
        print("PORT_" + label + "_OK")
        return motor
    except Exception:
        print("PORT_" + label + "_MISSING")
        return None


launch_l = safe_motor(Port.A, "A")
launch_r = safe_motor(Port.B, "B")
c_motor = safe_motor(Port.C, "C")
tilt_motor = safe_motor(Port.D, "D_TILT")
pan_motor = safe_motor(Port.F, "F_PAN")


def stop_all():
    for motor in (launch_l, launch_r, c_motor, tilt_motor, pan_motor):
        if motor:
            try:
                motor.stop()
            except Exception:
                pass


def angle_text(motor):
    if motor is None:
        return "NA"
    try:
        return str(motor.angle())
    except Exception:
        return "ERR"


stop_all()
hub.display.text("A")

print("ANGLE_READER_READY")
print("Move the turret by hand. Use these values for PAN_HOME/TILT_HOME/C_HOME.")
print("CENTER button exits.")

while True:
    print(
        "ANGLES"
        + " pan_F=" + angle_text(pan_motor)
        + " tilt_D=" + angle_text(tilt_motor)
        + " c_C=" + angle_text(c_motor)
    )
    if hub.buttons.pressed():
        break
    wait(500)

stop_all()
hub.display.text("X")
