import cv2

def open_live_preview():
    cap = cv2.VideoCapture(4)  # 0 für die erste angeschlossene Kamera

    if not cap.isOpened():
        print("Error: Could not open video device.")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture frame. Exiting...")
            break

        cv2.imshow('Live Preview', frame)

        # Beenden, wenn die 'q'-Taste gedrückt wird
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Ressourcen freigeben
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    open_live_preview()