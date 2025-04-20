from picamera2 import Picamera2
from libcamera import controls
import time
import socket

# Initialize the camera
picam2 = Picamera2()

# Set default configuration
config = picam2.create_preview_configuration()
picam2.configure(config)

# Start the camera
picam2.start()
picam2.options["quality"] = 100
time.sleep(5)  # Allow camera to warm up

# Function to update camera settings
def update_settings(exposure=None, gain=None, awb_mode=None, resolution=None, focus=None):
    if resolution:
        picam2.stop()
        config = picam2.create_preview_configuration(main={'size': resolution})
        picam2.configure(config)
        picam2.start()
        # time.sleep(2)
    if exposure is not None and gain is not None:
        exp_time = int(1000 / exposure)*1000 
        picam2.set_controls({"AeEnable": False, "ExposureTime": exp_time, "AnalogueGain": gain})
    if awb_mode:
        # if awb_mode == "Auto":
        #     picam2.set_controls({"AwbMode": controls.AwbModeEnum.Auto})
        # elif awb_mode == "Daylight":
        #     picam2.set_controls({"AwbMode": controls.AwbModeEnum.Daylight})
        # elif awb_mode == "Tungsten":
        #     picam2.set_controls({"AwbMode": controls.AwbModeEnum.Tungsten})

        picam2.set_controls({"AwbMode": getattr(controls.AwbModeEnum, awb_mode)})
        print(getattr(controls.AwbModeEnum, awb_mode))
        print(controls.AwbModeEnum.Daylight)
    if focus:
        f_position = 1/focus
        picam2.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": focus})	
    print("Settings updated")

# def get_ip_suffix():
#     """
#     Ermittelt den Suffix (letzten zwei Ziffern) der IP-Adresse des aktuellen Geräts.
#     """
#     ip = socket.gethostbyname(socket.gethostname())
#     print(f"IP Adress: {ip}")
#     last_octet = ip.split('.')[-1]
#     return last_octet

# Example settings to test
test_settings = [
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0001},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0002},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0004},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0008},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0016},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0032},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0064},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0128},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0256},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.0512},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.1024},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.2048},
    # {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.4096},
    {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 0.8},
    {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 1},
    {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 1.2},
    {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 1.4},
    {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 1.6},
    {"resolution": (1920*2, 1080*2), "awb_mode": "Daylight", "exposure": 50, "gain": 1.4, "focus": 1.8}    
]

ip_suffix = 64

# Apply settings and capture a test image
for i, settings in enumerate(test_settings):
    print(f"Applying settings {i+1}: {settings}")
    update_settings(**settings)
    time.sleep(2)
    config = picam2.stream_configuration("main")
    width, height = config["size"]
    print(f"Resolution: {width}x{height}")
    # Füge den Suffix der IP-Adresse an den Dateinamen an 
    filename = f"test_image_CAM{ip_suffix}_{settings['focus']}.jpg"
    # picam2.set_controls({"AfTrigger": controls.AfTriggerEnum.Start})
    # time.sleep(2)
    lens_position = picam2.capture_metadata()['LensPosition']
    print(f"Focus position: {lens_position}")
    picam2.capture_file(filename)
    print(f"Captured {filename}")

# Stop the camera
picam2.stop()
print("Testing complete.")
