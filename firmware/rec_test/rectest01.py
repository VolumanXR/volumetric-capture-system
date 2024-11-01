import cv2
import os
import time
from datetime import datetime
import glob
from tqdm import tqdm
import time

# Constants
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30
BITRATE = 4000000  # Adjust this value for bitrate (in bits per second)
CODEC = 'H264'  # H.264 codec

# Create recordings folder if it doesn't exist
RECORDINGS_DIR = 'recordings'
os.makedirs(RECORDINGS_DIR, exist_ok=True)


def get_next_recording_filename():
    """Generates a new unique filename by checking existing recording files."""
    files = glob.glob(f"{RECORDINGS_DIR}/rec*.mp4")
    if not files:
        return f"{RECORDINGS_DIR}/rec1.mp4"
    # Find the max recording number and increment
    latest_recording = max([int(f.split('rec')[-1].split('.mp4')[0]) for f in files])
    return f"{RECORDINGS_DIR}/rec{latest_recording + 1}.mp4"


def record_video(duration=None, start_immediately=False):
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open video device.")
        return

    # Set the desired FPS
    fps = 30  # Set this to the desired FPS
    cap.set(cv2.CAP_PROP_FPS, fps)

    # Get the actual FPS
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Actual FPS: {actual_fps}")

    # Define the codec and create VideoWriter object
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    filename = 'output.avi'
    out = cv2.VideoWriter(filename, fourcc, actual_fps, (640, 480))

    recording = start_immediately
    start_time = None

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Failed to capture image.")
            break

        cv2.imshow('frame', frame)

        key = cv2.waitKey(1)
        if key == 32:  # Space key pressed
            if not recording:
                print("Recording started...")
                recording = True
                start_time = time.time()
                if duration:
                    progress_bar.reset()
            else:
                print("Recording stopped.")
                break

        if recording:
            out.write(frame)
            # If a specific duration is set, stop when reached
            if duration:
                elapsed_time = time.time() - start_time
                progress_bar.n = elapsed_time
                progress_bar.refresh()
                if elapsed_time > duration:
                    print("Recording completed.")
                    break

    # Release resources
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    if duration:
        progress_bar.close()
    print(f"Recording saved as {filename}")

if __name__ == "__main__":
    # Set duration to None for infinite recording
    duration = 10  # e.g., duration in seconds, or None for infinite
    start_immediately = True  # Set to True to start recording automatically
    record_video(duration=duration, start_immediately=start_immediately)