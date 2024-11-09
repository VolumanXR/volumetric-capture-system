import sys
import threading
from picamera2 import Picamera2
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk

# Initialize Picamera2
picam2 = Picamera2()

# Default camera configuration for natural view
config = picam2.create_preview_configuration(
    main={"format": "RGB888", "size": (1280, 720)},
    controls={
        "FrameRate": 30.0,
        "Brightness": 0.0,
        "Contrast": 1.0,
        "Saturation": 1.0,
        "Sharpness": 1.0,
        "AwbEnable": True,  # Auto White Balance enabled
        "AeEnable": True,   # Auto Exposure enabled
    }
)
picam2.configure(config)

# Start the camera
picam2.start()

# Function to update camera controls based on GUI input
def update_controls():
    controls = {}
    frame_rate = float(fps_scale.get())
    controls["FrameRate"] = frame_rate

    shutter_angle = float(shutter_angle_scale.get())
    exposure_time = (shutter_angle / 360.0) * (1.0 / frame_rate) * 1_000_000  # in microseconds

    iso_value = float(iso_scale.get())

    controls["Brightness"] = float(brightness_scale.get()) / 100.0
    controls["Contrast"] = float(contrast_scale.get()) / 100.0
    controls["Saturation"] = float(saturation_scale.get()) / 100.0
    controls["Sharpness"] = float(sharpness_scale.get()) / 100.0

    # Handle Auto Exposure
    if ae_var.get():
        controls["AeEnable"] = True
        # Do not set ExposureTime or AnalogueGain when auto exposure is enabled
    else:
        controls["AeEnable"] = False
        controls["ExposureTime"] = int(exposure_time)
        controls["AnalogueGain"] = iso_value / 100.0  # Assuming ISO 100 corresponds to AnalogueGain 1.0

    # Handle White Balance
    wb_selection = wb_var.get()
    if wb_selection == 'Auto':
        controls["AwbEnable"] = True
        # Do not set ColourGains when auto white balance is enabled
    else:
        controls["AwbEnable"] = False
        # Set 'ColourGains' based on selected white balance
        if wb_selection == '3200K':
            controls["ColourGains"] = (2.3, 1.3)
        elif wb_selection == '4400K':
            controls["ColourGains"] = (1.8, 1.5)
        elif wb_selection == '5600K':
            controls["ColourGains"] = (1.5, 1.8)

    picam2.set_controls(controls)

# Function to update resolution
def update_resolution():
    width = int(width_entry.get())
    height = int(height_entry.get())
    picam2.stop()
    config = picam2.create_preview_configuration(
        main={"format": "RGB888", "size": (width, height)},
        controls={
            "FrameRate": float(fps_scale.get()),
            "Brightness": float(brightness_scale.get()) / 100.0,
            "Contrast": float(contrast_scale.get()) / 100.0,
            "Saturation": float(saturation_scale.get()) / 100.0,
            "Sharpness": float(sharpness_scale.get()) / 100.0,
            "AwbEnable": awb_enabled(),
            "AeEnable": ae_var.get(),
        }
    )
    picam2.configure(config)
    picam2.start()

def awb_enabled():
    return wb_var.get() == 'Auto'

# Function to display camera preview
def camera_preview():
    while True:
        frame = picam2.capture_array()
        cv2.imshow("Camera Preview", frame)
        if cv2.waitKey(1) == ord('q'):
            break
    picam2.stop()
    cv2.destroyAllWindows()
    sys.exit()

# Create the main window
root = tk.Tk()
root.title("Raspberry Pi Camera Controls")

# Resolution settings
resolution_frame = ttk.LabelFrame(root, text="Resolution")
resolution_frame.pack(fill="x", padx=5, pady=5)

ttk.Label(resolution_frame, text="Width:").grid(row=0, column=0, padx=5, pady=5)
width_entry = ttk.Entry(resolution_frame)
width_entry.insert(0, "1280")
width_entry.grid(row=0, column=1, padx=5, pady=5)

ttk.Label(resolution_frame, text="Height:").grid(row=1, column=0, padx=5, pady=5)
height_entry = ttk.Entry(resolution_frame)
height_entry.insert(0, "720")
height_entry.grid(row=1, column=1, padx=5, pady=5)

apply_resolution_button = ttk.Button(resolution_frame, text="Apply", command=update_resolution)
apply_resolution_button.grid(row=2, column=0, columnspan=2, pady=5)

# Frame Rate
fps_scale = tk.Scale(root, from_=1, to=60, orient=tk.HORIZONTAL, label="Frame Rate (FPS)", command=lambda x: update_controls())
fps_scale.set(30)
fps_scale.pack(fill="x", padx=5, pady=5)

# Shutter Angle
shutter_angle_scale = tk.Scale(root, from_=1, to=360, orient=tk.HORIZONTAL, label="Shutter Angle (degrees)", command=lambda x: update_controls())
shutter_angle_scale.set(180)
shutter_angle_scale.pack(fill="x", padx=5, pady=5)

# ISO (Analogue Gain)
iso_scale = tk.Scale(root, from_=100, to=6400, orient=tk.HORIZONTAL, label="ISO", command=lambda x: update_controls())
iso_scale.set(100)
iso_scale.pack(fill="x", padx=5, pady=5)

# Brightness
brightness_scale = tk.Scale(root, from_=-100, to=100, orient=tk.HORIZONTAL, label="Brightness", command=lambda x: update_controls())
brightness_scale.set(0)
brightness_scale.pack(fill="x", padx=5, pady=5)

# Contrast
contrast_scale = tk.Scale(root, from_=0, to=200, orient=tk.HORIZONTAL, label="Contrast", command=lambda x: update_controls())
contrast_scale.set(100)
contrast_scale.pack(fill="x", padx=5, pady=5)

# Saturation
saturation_scale = tk.Scale(root, from_=0, to=200, orient=tk.HORIZONTAL, label="Saturation", command=lambda x: update_controls())
saturation_scale.set(100)
saturation_scale.pack(fill="x", padx=5, pady=5)

# Sharpness
sharpness_scale = tk.Scale(root, from_=0, to=200, orient=tk.HORIZONTAL, label="Sharpness", command=lambda x: update_controls())
sharpness_scale.set(100)
sharpness_scale.pack(fill="x", padx=5, pady=5)

# Auto Exposure
ae_var = tk.BooleanVar(value=True)
ae_check = ttk.Checkbutton(root, text="Auto Exposure", variable=ae_var, command=update_controls)
ae_check.pack(anchor='w', padx=5, pady=5)

# White Balance Dropdown
wb_label = ttk.Label(root, text="White Balance:")
wb_label.pack(anchor='w', padx=5, pady=5)

wb_var = tk.StringVar(value='Auto')
wb_options = ['Auto', '3200K', '4400K', '5600K']
wb_menu = ttk.OptionMenu(root, wb_var, wb_var.get(), *wb_options, command=lambda x: update_controls())
wb_menu.pack(anchor='w', padx=5, pady=5)

# Start the camera preview in a separate thread
threading.Thread(target=camera_preview, daemon=True).start()

# Start the GUI event loop
root.mainloop()
