import time
import os
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder

# Initialize PiCamera2
picam2 = Picamera2()

# Configure the camera
video_config = picam2.create_video_configuration(main={"size": (1920, 1080)}, controls={"FrameRate": 30})
picam2.configure(video_config)
picam2.start()

# Encoder setup
bitrate = 10000  # Adjust as needed (in kbps)
local_encoder = H264Encoder(bitrate * 1000)

# Test recording file path
recording_file = "test_recording.h264"

# Measure start_recording time
start_time = time.perf_counter()
picam2.start_recording(local_encoder, recording_file)
end_time = time.perf_counter()

# Print the execution time
print(f"picam2.start_recording() took {end_time - start_time:.6f} seconds.")

# Stop the recording after a short duration
time.sleep(1)  # Record for 1 second
picam2.stop_recording()
picam2.stop()

# Delete the test recording file
if os.path.exists(recording_file):
    os.remove(recording_file)
    print(f"Deleted test file: {recording_file}")
else:
    print("Test recording file not found, nothing to delete.")
