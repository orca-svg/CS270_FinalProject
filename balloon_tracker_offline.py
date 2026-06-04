import cv2
import numpy as np
import time

# =================================================================
# 3D 물리 예측 엔진 + 마우스 스포이드 자동 색상 튜닝
# =================================================================

def nothing(x):
    pass

# 전역 변수 (마우스 클릭용)
latest_hsv = None
auto_hsv_update = False
picked_hsv = None

def mouse_click(event, x, y, flags, param):
    global auto_hsv_update, picked_hsv, latest_hsv
    # 마우스 왼쪽 버튼을 클릭했을 때
    if event == cv2.EVENT_LBUTTONDOWN and latest_hsv is not None:
        if y < latest_hsv.shape[0] and x < latest_hsv.shape[1]:
            picked_hsv = latest_hsv[y, x]
            auto_hsv_update = True

def main():
    global latest_hsv, auto_hsv_update, picked_hsv

    # 1. 카메라 설정
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("🚨 웹캠을 열 수 없습니다.")
        return

    FRAME_W, FRAME_H = 640, 480
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    
    CX = FRAME_W / 2.0
    CY = FRAME_H / 2.0

    # 2. 색상 튜닝 패널 창
    cv2.namedWindow("Tuning Panel")
    cv2.resizeWindow("Tuning Panel", 400, 300)

    cv2.createTrackbar("H Min", "Tuning Panel", 0, 179, nothing)
    cv2.createTrackbar("S Min", "Tuning Panel", 120, 255, nothing)
    cv2.createTrackbar("V Min", "Tuning Panel", 70, 255, nothing)
    cv2.createTrackbar("H Max", "Tuning Panel", 10, 179, nothing)
    cv2.createTrackbar("S Max", "Tuning Panel", 255, 255, nothing)
    cv2.createTrackbar("V Max", "Tuning Panel", 255, 255, nothing)
    
    cv2.createTrackbar("Min Area", "Tuning Panel", 500, 20000, nothing)

    # 마우스 콜백을 메인 윈도우에 연결하기 위해 먼저 창을 생성합니다.
    cv2.namedWindow("Color Object Aimbot")
    cv2.setMouseCallback("Color Object Aimbot", mouse_click)

    # 3D 물리, 캘리브레이션, 모터 범위 상수
    OBJECT_SIZE_CM = 20.0  
    FOCAL_LENGTH = 550.0  
    DRAG_K = 1.5         
    GRAVITY_CM_S2 = 250.0 
    LATENCY_COMPENSATION = 0.4  
    SMOOTHING_VEL = 0.25
    PAN_MAX_DEG  = 35.0
    TILT_MIN_DEG = 0.0
    TILT_MAX_DEG = 80.0

    prev_X, prev_Y, prev_Z = None, None, None
    prev_time = time.time()
    vx_smooth, vy_smooth, vz_smooth = 0.0, 0.0, 0.0
    trail_points_2d = []
    MAX_TRAIL_LEN = 20
    gravity_enabled = True

    print("----------------------------------------------------------------")
    print("🎨 색상 스포이드(Eyedropper) 추적 모드 가동")
    print("  - 슬라이더를 만질 필요가 없습니다!")
    print("  - 카메라 화면(Color Object Aimbot)에 대고 내 지갑/핸드폰을")
    print("    마우스로 딱 '클릭' 해보세요. 자동으로 색상이 튜닝됩니다.")
    print("  - 키보드 'g' 키를 누르면 중력 예측(Gravity ON/OFF)을 토글할 수 있습니다.")
    print("----------------------------------------------------------------")

    while True:
        ret, frame = cap.read()
        if not ret: break

        frame = cv2.flip(frame, 1)
        latest_hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 마우스로 클릭해서 색상을 뽑아왔다면 슬라이더를 자동 세팅
        if auto_hsv_update and picked_hsv is not None:
            h, s, v = picked_hsv
            
            # 클릭한 픽셀 색상 기준으로 여유 범위를 잡아줍니다.
            h_min, h_max = max(0, int(h)-10), min(179, int(h)+10)
            s_min, s_max = max(0, int(s)-60), min(255, int(s)+60)
            v_min, v_max = max(0, int(v)-60), min(255, int(v)+60)
            
            cv2.setTrackbarPos("H Min", "Tuning Panel", h_min)
            cv2.setTrackbarPos("H Max", "Tuning Panel", h_max)
            cv2.setTrackbarPos("S Min", "Tuning Panel", s_min)
            cv2.setTrackbarPos("S Max", "Tuning Panel", s_max)
            cv2.setTrackbarPos("V Min", "Tuning Panel", v_min)
            cv2.setTrackbarPos("V Max", "Tuning Panel", v_max)
            
            auto_hsv_update = False
            print(f"👉 띠링! 자동 색상 세팅 완료 (H:{h}, S:{s}, V:{v})")

        # 트랙바 값 획득 및 마스크 생성
        h_min = cv2.getTrackbarPos("H Min", "Tuning Panel")
        s_min = cv2.getTrackbarPos("S Min", "Tuning Panel")
        v_min = cv2.getTrackbarPos("V Min", "Tuning Panel")
        h_max = cv2.getTrackbarPos("H Max", "Tuning Panel")
        s_max = cv2.getTrackbarPos("S Max", "Tuning Panel")
        v_max = cv2.getTrackbarPos("V Max", "Tuning Panel")
        min_area = cv2.getTrackbarPos("Min Area", "Tuning Panel")

        lower_bound = np.array([h_min, s_min, v_min])
        upper_bound = np.array([h_max, s_max, v_max])
        mask = cv2.inRange(latest_hsv, lower_bound, upper_bound)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # 컨투어 분석
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        target_detected = False
        best_rect = None

        if contours:
            c = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(c)
            if area >= min_area:
                x, y, w, h = cv2.boundingRect(c)
                best_rect = (x, y, w, h)
                target_detected = True

        current_time = time.time()
        dt = current_time - prev_time

        # 3D 물리 시뮬레이션
        if target_detected:
            x, y, w, h = best_rect
            px_x = x + w // 2
            px_y = y + h // 2

            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (px_x, px_y), 4, (0, 0, 255), -1)

            trail_points_2d.append((px_x, px_y))
            if len(trail_points_2d) > MAX_TRAIL_LEN:
                trail_points_2d.pop(0)

            pixel_size = max(w, h)
            if pixel_size > 0:
                Z_cm = (OBJECT_SIZE_CM * FOCAL_LENGTH) / pixel_size
            else:
                Z_cm = 300.0

            X_cm = ((px_x - CX) * Z_cm) / FOCAL_LENGTH
            Y_cm = -((px_y - CY) * Z_cm) / FOCAL_LENGTH

            if prev_X is not None and dt > 0:
                vx_raw = (X_cm - prev_X) / dt
                vy_raw = (Y_cm - prev_Y) / dt
                vz_raw = (Z_cm - prev_Z) / dt

                vx_smooth = (SMOOTHING_VEL * vx_raw) + ((1.0 - SMOOTHING_VEL) * vx_smooth)
                vy_smooth = (SMOOTHING_VEL * vy_raw) + ((1.0 - SMOOTHING_VEL) * vy_smooth)
                vz_smooth = (SMOOTHING_VEL * vz_raw) + ((1.0 - SMOOTHING_VEL) * vz_smooth)

            sim_X, sim_Y, sim_Z = X_cm, Y_cm, Z_cm
            sim_vx, sim_vy, sim_vz = vx_smooth, vy_smooth, vz_smooth

            sim_steps = 10
            sim_dt = LATENCY_COMPENSATION / sim_steps

            for _ in range(sim_steps):
                ax = -DRAG_K * sim_vx
                g_val = GRAVITY_CM_S2 if gravity_enabled else 0.0
                ay = -DRAG_K * sim_vy - g_val
                az = -DRAG_K * sim_vz
                sim_X += sim_vx * sim_dt
                sim_Y += sim_vy * sim_dt
                sim_Z += sim_vz * sim_dt
                sim_vx += ax * sim_dt
                sim_vy += ay * sim_dt
                sim_vz += az * sim_dt

            yaw_rad = np.arctan2(sim_X, sim_Z)
            pitch_rad = np.arctan2(sim_Y, sim_Z)
            yaw_deg = np.degrees(yaw_rad)
            pitch_deg = np.degrees(pitch_rad)

            pan_val = int((yaw_deg / PAN_MAX_DEG) * 100)
            pan_val = max(-100, min(100, pan_val))
            tilt_val = int(((pitch_deg - TILT_MIN_DEG) / (TILT_MAX_DEG - TILT_MIN_DEG)) * 200 - 100)
            tilt_val = max(-100, min(100, tilt_val))

            if sim_Z > 0:
                pred_px_x = int((sim_X * FOCAL_LENGTH) / sim_Z + CX)
                pred_px_y = int((-sim_Y * FOCAL_LENGTH) / sim_Z + CY)
                pred_px_x = max(0, min(FRAME_W, pred_px_x))
                pred_px_y = max(0, min(FRAME_H, pred_px_y))

                cv2.line(frame, (px_x, px_y), (pred_px_x, pred_px_y), (0, 0, 255), 2)
                rect_size = 20
                cv2.rectangle(frame, (pred_px_x - rect_size, pred_px_y - rect_size), 
                                     (pred_px_x + rect_size, pred_px_y + rect_size), (0, 0, 255), 2)
                cv2.circle(frame, (pred_px_x, pred_px_y), 3, (0, 0, 255), -1)
                
                g_label = "With Gravity" if gravity_enabled else "No Gravity"
                cv2.putText(frame, f"PRED ({g_label}, t+{LATENCY_COMPENSATION}s)", (pred_px_x + 25, pred_px_y - 5), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

            cv2.rectangle(frame, (5, 5), (410, 160), (0, 0, 0), -1)
            cv2.putText(frame, "=== EYEDROPPER COLOR 3D TRACKING ===", (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            cv2.putText(frame, f"Depth (Z) : {int(Z_cm)} cm", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame, f"Current 3D: ({int(X_cm)}, {int(Y_cm)}, {int(Z_cm)})", (15, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"Predicted : ({int(sim_X)}, {int(sim_Y)}, {int(sim_Z)})", (15, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            cv2.putText(frame, f"Motor CMD : Pan {pan_val} / Tilt {tilt_val}", (15, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
            cv2.putText(frame, f"Gravity (g): {'ON' if gravity_enabled else 'OFF'} (Press 'g' to Toggle)", (15, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            
            prev_X, prev_Y, prev_Z = X_cm, Y_cm, Z_cm

        else:
            prev_X, prev_Y, prev_Z = None, None, None
            vx_smooth, vy_smooth, vz_smooth = 0.0, 0.0, 0.0
            if len(trail_points_2d) > 0:
                trail_points_2d.pop(0)
            
            cv2.putText(frame, "CLICK your object to track!", (FRAME_W//2 - 150, FRAME_H//2), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        prev_time = current_time

        for i in range(1, len(trail_points_2d)):
            if trail_points_2d[i-1] is None or trail_points_2d[i] is None: continue
            thickness = int(np.sqrt(MAX_TRAIL_LEN / float(i + 1)) * 2.5)
            cv2.line(frame, trail_points_2d[i-1], trail_points_2d[i], (0, 255, 255), thickness)

        cv2.imshow("Color Object Aimbot", frame)
        cv2.imshow("Binary Mask (HSV Filter)", mask)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('g'):
            gravity_enabled = not gravity_enabled
            print(f"👉 중력 시뮬레이션 변경: {'ON' if gravity_enabled else 'OFF'}")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
