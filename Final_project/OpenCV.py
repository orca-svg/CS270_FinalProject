import cv2
from ultralytics import YOLO

def main():
    # Load the YOLOv8 nano model (fastest, good for real-time)
    print("Loading YOLOv8 model...")
    model = YOLO('yolov8n.pt') 

    # Open the default webcam (0)
    print("Opening webcam...")
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    # Set window to be resizable
    cv2.namedWindow('Object Detection', cv2.WINDOW_NORMAL)

    print("Starting detection. Press 'q' to quit.")

    while True:
        # Read a frame from the webcam
        ret, frame = cap.read()
        
        if not ret:
            print("Error: Failed to grab frame.")
            break

        # Run YOLO inference on the frame
        # stream=True is memory efficient for videos
        results = model(frame, stream=True, verbose=False)

        # Draw the results on the frame
        for r in results:
            annotated_frame = r.plot()
            
        # Display the annotated frame
        cv2.imshow('Object Detection', annotated_frame)

        # Break the loop if 'q' is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Release resources
    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
