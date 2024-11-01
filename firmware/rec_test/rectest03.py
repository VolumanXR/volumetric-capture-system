import cv2
import os
import time
import glob

# Constants
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30
DURATION = 10  # Duration of each recording in seconds
CODEC = 'H264'  # H.264 codec
BITRATES_Mbps = [1, 2, 4, 8]  # Bitrates in Mbps

# Create recordings folder if it doesn't exist
RECORDINGS_DIR = 'recordings'
os.makedirs(RECORDINGS_DIR, exist_ok=True)

def get_next_recording_filename(bitrate_mbps):
    """Generates a new unique filename by checking existing recording files."""
    files = glob.glob(f"{RECORDINGS_DIR}/rec*_br{bitrate_mbps}Mbps.mp4")
    if not files:
        return f"{RECORDINGS_DIR}/rec1_br{bitrate_mbps}Mbps.mp4"
    # Find the max recording number and increment
    latest_recording = max([int(f.split('rec')[-1].split('_br')[0]) for f in files])
    return f"{RECORDINGS_DIR}/rec{latest_recording + 1}_br{bitrate_mbps}Mbps.mp4"

def record_video_for_bitrate(bitrate_mbps):
    """Records a 10-second video with the specified bitrate."""
    bitrate = bitrate_mbps * 1_000_000  # Convert Mbps to bps

    # Set up video capture
    cap = cv2.VideoCapture(4)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # Define the video codec and create VideoWriter object
    filename = get_next_recording_filename(bitrate_mbps)
    fourcc = cv2.VideoWriter_fourcc(*CODEC)
    out = cv2.VideoWriter(filename, fourcc, FPS, (VIDEO_WIDTH, VIDEO_HEIGHT))
    
    print(f"Recording with bitrate {bitrate_mbps} Mbps started...")

    start_time = time.time()
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture frame. Exiting...")
            break
        
        # Write the frame to the output file
        out.write(frame)

        # Check if exactly 10 seconds have elapsed
        if (time.time() - start_time) >= DURATION:
            print(f"Recording with bitrate {bitrate_mbps} Mbps completed.")
            break

    # Release resources
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    print(f"Recording saved as {filename}")

if __name__ == "__main__":
    # Loop through each bitrate and record a video
    for bitrate_mbps in BITRATES_Mbps:
        record_video_for_bitrate(bitrate_mbps)
