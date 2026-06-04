import cv2
import mediapipe as mp
import time

# =================================================================
# 인공지능(AI) 손 인식 및 제스처 판별기 (MediaPipe 적용)
# =================================================================
# 튜닝 패널 없이, 구글 MediaPipe 라이브러리를 사용하여 
# 자동으로 손의 관절(Landmarks)을 추적하고 어떤 동작인지(엄지척 등) 판별합니다.

def main():
    # 1. MediaPipe 손 인식 모듈 초기화
    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    # 손 인식 모델 설정 (최대 손 개수 1개, 신뢰도 0.7 이상)
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7
    )

    # 2. 카메라 설정
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("🚨 웹캠을 열 수 없습니다.")
        return

    # 화면 해상도
    FRAME_W, FRAME_H = 640, 480
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

    print("----------------------------------------------------------------")
    print("🖐️ AI 손 인식 및 제스처 트래킹 가동 (Tuning Free)")
    print("  - 카메라에 손을 보여주면 자동으로 관절을 인식합니다.")
    print("  - 손동작(가위/바위/보/엄지척)을 변경해보세요.")
    print("  - 'q' 키: 프로그램 종료")
    print("----------------------------------------------------------------")

    prev_time = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 거울처럼 보이도록 좌우 반전
        frame = cv2.flip(frame, 1)

        # MediaPipe는 RGB 포맷을 사용하므로 BGR에서 RGB로 변환
        image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # 3. AI 모델을 통해 손 인식 수행
        results = hands.process(image_rgb)

        gesture_text = "NONE"
        gesture_color = (255, 255, 255)

        # 4. 손이 화면에 인식되었다면
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                # 손 관절(뼈대)을 화면에 예쁘게 그리기
                mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
                    mp_drawing_styles.get_default_hand_landmarks_style(),
                    mp_drawing_styles.get_default_hand_connections_style()
                )

                # --- 제스처 판별(Gesture Recognition) 로직 ---
                # 각 손가락의 끝부분(Tip)과 중간 마디(PIP/DIP)의 y좌표(상하 위치)를 비교하여
                # 손가락이 펴져 있는지 접혀 있는지 판단합니다. (y좌표는 화면 위쪽이 0으로 작습니다)
                
                lm = hand_landmarks.landmark
                
                # 각 손가락이 펴져 있는지 여부 (True / False)
                # 엄지는 x좌표(좌우) 혹은 y좌표 복합 판단이 필요하지만 간단히 y좌표와 위치로 근사
                thumb_is_up = lm[mp_hands.HandLandmark.THUMB_TIP].y < lm[mp_hands.HandLandmark.THUMB_IP].y
                index_is_open = lm[mp_hands.HandLandmark.INDEX_FINGER_TIP].y < lm[mp_hands.HandLandmark.INDEX_FINGER_PIP].y
                middle_is_open = lm[mp_hands.HandLandmark.MIDDLE_FINGER_TIP].y < lm[mp_hands.HandLandmark.MIDDLE_FINGER_PIP].y
                ring_is_open = lm[mp_hands.HandLandmark.RING_FINGER_TIP].y < lm[mp_hands.HandLandmark.RING_FINGER_PIP].y
                pinky_is_open = lm[mp_hands.HandLandmark.PINKY_TIP].y < lm[mp_hands.HandLandmark.PINKY_PIP].y

                # 펴진 손가락 개수 계산 (엄지 제외)
                fingers_open_count = index_is_open + middle_is_open + ring_is_open + pinky_is_open

                # 조건에 따른 제스처 이름 부여
                if thumb_is_up and fingers_open_count == 0:
                    gesture_text = "THUMBS UP! (Good)"
                    gesture_color = (0, 255, 0)
                elif fingers_open_count == 4 and thumb_is_up:
                    gesture_text = "OPEN HAND (Paper)"
                    gesture_color = (255, 255, 0)
                elif fingers_open_count == 0 and not thumb_is_up:
                    gesture_text = "FIST (Rock)"
                    gesture_color = (0, 0, 255)
                elif index_is_open and middle_is_open and ring_is_open == 0 and pinky_is_open == 0:
                    gesture_text = "PEACE (Scissors)"
                    gesture_color = (255, 0, 255)
                else:
                    gesture_text = "TRACKING..."
                    gesture_color = (200, 200, 200)

                # 손의 중심점(손바닥 중앙 대략 9번 관절) 찾기
                cx = int(lm[mp_hands.HandLandmark.MIDDLE_FINGER_MCP].x * FRAME_W)
                cy = int(lm[mp_hands.HandLandmark.MIDDLE_FINGER_MCP].y * FRAME_H)
                
                # 타겟팅 포인터 표시
                cv2.circle(frame, (cx, cy), 10, (0, 255, 255), 2)
                cv2.circle(frame, (cx, cy), 2, (0, 255, 255), -1)

        # FPS (초당 프레임 수) 계산
        current_time = time.time()
        fps = 1 / (current_time - prev_time) if (current_time - prev_time) > 0 else 0
        prev_time = current_time

        # 5. 화면 UI 렌더링 (HUD)
        cv2.rectangle(frame, (10, 10), (350, 110), (0, 0, 0), -1)
        cv2.putText(frame, "=== AI GESTURE RECOGNITION ===", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        
        # 인식된 제스처 텍스트 출력
        cv2.putText(frame, gesture_text, (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.9, gesture_color, 2)
        
        cv2.putText(frame, f"FPS: {int(fps)}", (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        # 6. 창에 띄우기
        cv2.imshow("AI Hand Tracker & Gesture", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
