# master_camera_controller.py

import sys
import json
import os
import requests
import cv2
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import io
import numpy as np
import threading
import queue
import time

# Configuration
REMOTE_PI_IP = '192.168.179.27'  # Replace with your Raspberry Pi's correct IP address
REMOTE_PI_PORT = 5000
CONTROL_ENDPOINT = f'http://{REMOTE_PI_IP}:{REMOTE_PI_PORT}/controls'
VIDEO_FEED_URL = f'http://{REMOTE_PI_IP}:{REMOTE_PI_PORT}/video_feed'
SAVE_SETTINGS_ENDPOINT = f'http://{REMOTE_PI_IP}:{REMOTE_PI_PORT}/save_settings'
LOAD_SETTINGS_ENDPOINT = f'http://{REMOTE_PI_IP}:{REMOTE_PI_PORT}/load_settings'

# Default settings
default_settings = {
    'width': 1280,
    'height': 720,
    'frame_rate': 25,
    'shutter_angle': 180,
    'iso': 100,
    'brightness': 0,
    'contrast': 100,
    'saturation': 100,
    'sharpness': 100,
    'auto_exposure': True,
    'flicker_control': 'Off',
    'flicker_period': 50,
    'white_balance': 'Auto',
    'red_gain': 1.0,
    'blue_gain': 1.0
}

# Function to load settings from the remote Pi
def load_settings():
    try:
        response = requests.get(LOAD_SETTINGS_ENDPOINT, timeout=5)
        if response.status_code == 200:
            settings = response.json()
            return settings
        else:
            messagebox.showerror("Error", f"Failed to load settings: {response.text}")
            return default_settings.copy()
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load settings: {e}")
        return default_settings.copy()

# Function to save settings to the remote Pi
def save_settings_remote(settings):
    try:
        response = requests.post(SAVE_SETTINGS_ENDPOINT, json=settings, timeout=5)
        if response.status_code == 200:
            messagebox.showinfo("Success", "Settings saved successfully.")
        else:
            messagebox.showerror("Error", f"Failed to save settings: {response.text}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save settings: {e}")

# Function to send control settings to the remote Pi
def send_controls(settings):
    try:
        response = requests.post(CONTROL_ENDPOINT, json=settings, timeout=5)
        if response.status_code != 200:
            messagebox.showerror("Error", f"Failed to update controls: {response.text}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to update controls: {e}")

class MasterCameraController:
    def __init__(self, root):
        self.root = root
        self.root.title("Master PC Raspberry Pi Camera Controls")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Load settings
        self.settings = load_settings()

        # Load camera list
        with open('camera_list.json', 'r') as f:
            self.camera_list = json.load(f)

        self.selected_camera = self.camera_list[0]  # Default to the first camera
        self.update_camera_endpoints()

        # Initialize GUI
        self.create_gui()

        # Initialize video stream variables
        self.frame_queue = queue.Queue(maxsize=10)  # Limit queue size to prevent memory issues
        self.stop_event = threading.Event()
        self.video_thread = threading.Thread(target=self.video_loop, daemon=True)
        self.video_thread.start()

        # Initialize metrics variables
        self.frame_count = 0
        self.total_bytes = 0
        self.fps = 0
        self.bandwidth = 0  # in MB/s

        # Start the UI update loop
        self.update_video()

        # Start the metrics update loop
        self.update_metrics()

    def create_gui(self):
        # Main container frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Settings Frame (Left)
        settings_frame = ttk.LabelFrame(main_frame, text="Camera Settings")
        settings_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Video Frame (Right)
        video_frame = ttk.LabelFrame(main_frame, text="Live Video")
        video_frame.grid(row=0, column=1, sticky="nsew")

        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        # --- Settings Widgets ---

        # Resolution settings
        resolution_frame = ttk.Frame(settings_frame)
        resolution_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(resolution_frame, text="Width:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.width_entry = ttk.Entry(resolution_frame, width=10)
        self.width_entry.insert(0, str(self.settings.get('width', 1280)))
        self.width_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(resolution_frame, text="Height:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.height_entry = ttk.Entry(resolution_frame, width=10)
        self.height_entry.insert(0, str(self.settings.get('height', 720)))
        self.height_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        apply_resolution_button = ttk.Button(resolution_frame, text="Apply", command=self.apply_resolution)
        apply_resolution_button.grid(row=2, column=0, columnspan=2, pady=5)

        # Frame Rate
        self.fps_scale = tk.Scale(settings_frame, from_=1, to=60, orient=tk.HORIZONTAL, label="Frame Rate (FPS)", command=lambda x: self.update_controls())
        self.fps_scale.set(self.settings.get('frame_rate', 25))
        self.fps_scale.pack(fill="x", padx=5, pady=5)

        # Shutter Angle
        self.shutter_angle_scale = tk.Scale(settings_frame, from_=1, to=360, orient=tk.HORIZONTAL, label="Shutter Angle (degrees)", command=lambda x: self.update_controls())
        self.shutter_angle_scale.set(self.settings.get('shutter_angle', 180))
        self.shutter_angle_scale.pack(fill="x", padx=5, pady=5)

        # ISO (Analogue Gain)
        self.iso_scale = tk.Scale(settings_frame, from_=100, to=6400, orient=tk.HORIZONTAL, label="ISO", command=lambda x: self.update_controls())
        self.iso_scale.set(self.settings.get('iso', 100))
        self.iso_scale.pack(fill="x", padx=5, pady=5)

        # Brightness
        self.brightness_scale = tk.Scale(settings_frame, from_=-100, to=100, orient=tk.HORIZONTAL, label="Brightness", command=lambda x: self.update_controls())
        self.brightness_scale.set(self.settings.get('brightness', 0))
        self.brightness_scale.pack(fill="x", padx=5, pady=5)

        # Contrast
        self.contrast_scale = tk.Scale(settings_frame, from_=0, to=200, orient=tk.HORIZONTAL, label="Contrast", command=lambda x: self.update_controls())
        self.contrast_scale.set(self.settings.get('contrast', 100))
        self.contrast_scale.pack(fill="x", padx=5, pady=5)

        # Saturation
        self.saturation_scale = tk.Scale(settings_frame, from_=0, to=200, orient=tk.HORIZONTAL, label="Saturation", command=lambda x: self.update_controls())
        self.saturation_scale.set(self.settings.get('saturation', 100))
        self.saturation_scale.pack(fill="x", padx=5, pady=5)

        # Sharpness
        self.sharpness_scale = tk.Scale(settings_frame, from_=0, to=200, orient=tk.HORIZONTAL, label="Sharpness", command=lambda x: self.update_controls())
        self.sharpness_scale.set(self.settings.get('sharpness', 100))
        self.sharpness_scale.pack(fill="x", padx=5, pady=5)

        # Auto Exposure
        self.ae_var = tk.BooleanVar(value=self.settings.get('auto_exposure', True))
        self.ae_check = ttk.Checkbutton(settings_frame, text="Auto Exposure", variable=self.ae_var, command=self.update_controls)
        self.ae_check.pack(anchor='w', padx=5, pady=5)

        # Flicker Control Dropdown
        flicker_label = ttk.Label(settings_frame, text="Flicker Control:")
        flicker_label.pack(anchor='w', padx=5, pady=5)

        self.flicker_var = tk.StringVar(value=self.settings.get('flicker_control', 'Off'))
        flicker_options = ['Off', '50Hz', '60Hz', 'Manual']

        def flicker_selection_changed(value):
            self.update_controls()
            if value == 'Manual':
                # Show the flicker period slider
                self.flicker_period_scale.pack(fill="x", padx=5, pady=5)
            else:
                # Hide the flicker period slider
                self.flicker_period_scale.pack_forget()

        self.flicker_menu = ttk.OptionMenu(settings_frame, self.flicker_var, self.flicker_var.get(), *flicker_options, command=flicker_selection_changed)
        self.flicker_menu.pack(anchor='w', padx=5, pady=5)

        # Flicker Period Slider for Manual Mode
        self.flicker_period_scale = tk.Scale(settings_frame, from_=10, to=1000, orient=tk.HORIZONTAL, label="Flicker Period (Hz)", command=lambda x: self.update_controls())
        self.flicker_period_scale.set(self.settings.get('flicker_period', 50))

        # Show or hide flicker period slider based on default setting
        if self.settings.get('flicker_control', 'Off') == 'Manual':
            self.flicker_period_scale.pack(fill="x", padx=5, pady=5)

        # White Balance Dropdown
        wb_label = ttk.Label(settings_frame, text="White Balance:")
        wb_label.pack(anchor='w', padx=5, pady=5)

        self.wb_var = tk.StringVar(value=self.settings.get('white_balance', 'Auto'))
        wb_options = ['Auto', '3200K', '4400K', '5600K', 'Manual']

        def wb_selection_changed(value):
            self.update_controls()
            if value == 'Manual':
                # Show the red and blue gain sliders
                self.red_gain_scale.pack(fill="x", padx=5, pady=5)
                self.blue_gain_scale.pack(fill="x", padx=5, pady=5)
            else:
                # Hide the red and blue gain sliders
                self.red_gain_scale.pack_forget()
                self.blue_gain_scale.pack_forget()

        self.wb_menu = ttk.OptionMenu(settings_frame, self.wb_var, self.wb_var.get(), *wb_options, command=wb_selection_changed)
        self.wb_menu.pack(anchor='w', padx=5, pady=5)

        # Red Gain Slider
        self.red_gain_scale = tk.Scale(settings_frame, from_=0.0, to=8.0, resolution=0.1, orient=tk.HORIZONTAL, label="Red Gain", command=lambda x: self.update_controls())
        self.red_gain_scale.set(self.settings.get('red_gain', 1.0))

        # Blue Gain Slider
        self.blue_gain_scale = tk.Scale(settings_frame, from_=0.0, to=8.0, resolution=0.1, orient=tk.HORIZONTAL, label="Blue Gain", command=lambda x: self.update_controls())
        self.blue_gain_scale.set(self.settings.get('blue_gain', 1.0))

        # Show or hide red and blue gain sliders based on default setting
        if self.settings.get('white_balance', 'Auto') == 'Manual':
            self.red_gain_scale.pack(fill="x", padx=5, pady=5)
            self.blue_gain_scale.pack(fill="x", padx=5, pady=5)

        # Save Settings Button
        save_button = ttk.Button(settings_frame, text="Save Settings", command=self.save_settings)
        save_button.pack(anchor='w', padx=5, pady=5)

        # --- Video Feed Widget ---

        # Metrics Frame above the video
        metrics_frame = ttk.Frame(video_frame)
        metrics_frame.pack(fill="x", padx=5, pady=5)
        
        camera_id_label = ttk.Label(metrics_frame, text="Camera ID:")
        camera_id_label.pack(anchor='w', padx=5, pady=5)

        self.camera_id_entry = ttk.Entry(metrics_frame)
        self.camera_id_entry.pack(anchor='w', padx=5, pady=5)

        select_camera_button = ttk.Button(metrics_frame, text="Select Camera", command=self.select_camera)
        select_camera_button.pack(anchor='w', padx=5, pady=5)

        # CPU Label
        self.cpu_label = ttk.Label(metrics_frame, text="CPU: 0%")
        self.cpu_label.pack(side="left", padx=5)
        
        # FPS Label
        self.fps_label = ttk.Label(metrics_frame, text="FPS: 0")
        self.fps_label.pack(side="left", padx=5)

        # Bandwidth Label
        self.bandwidth_label = ttk.Label(metrics_frame, text="Bandwidth: 0 MB/s")
        self.bandwidth_label.pack(side="left", padx=5)

        # Video Label
        self.video_label = ttk.Label(video_frame)
        self.video_label.pack(fill="both", expand=True)

    def select_camera(self):
        camera_id = self.camera_id_entry.get()
        camera_name = f"CAM{camera_id.zfill(2)}"
        matching_camera = next((cam for cam in self.camera_list if cam['name'] == camera_name), None)
        if matching_camera:
            self.selected_camera = matching_camera
            self.update_camera_endpoints()
        else:
            messagebox.showerror("Error", "Invalid Camera ID.")
            
    def update_camera_endpoints(self):
        camera_ip = self.selected_camera['ip']
        self.CONTROL_ENDPOINT = f"http://{camera_ip}:5000/controls"
        self.VIDEO_FEED_URL = f"http://{camera_ip}:5000/video_feed"
        self.CPU_USAGE_ENDPOINT = f"http://{camera_ip}:5000/cpu_usage"
    
    def apply_resolution(self):
        width = self.width_entry.get()
        height = self.height_entry.get()
        if not width.isdigit() or not height.isdigit():
            messagebox.showerror("Error", "Width and Height must be integers.")
            return
        self.settings['width'] = int(width)
        self.settings['height'] = int(height)
        self.update_controls()

    def update_controls(self):
        # Gather all settings from the GUI
        settings = {
            'width': int(self.width_entry.get()),
            'height': int(self.height_entry.get()),
            'frame_rate': int(self.fps_scale.get()),
            'shutter_angle': int(self.shutter_angle_scale.get()),
            'iso': int(self.iso_scale.get()),
            'brightness': int(self.brightness_scale.get()),
            'contrast': int(self.contrast_scale.get()),
            'saturation': int(self.saturation_scale.get()),
            'sharpness': int(self.sharpness_scale.get()),
            'auto_exposure': bool(self.ae_var.get()),
            'flicker_control': self.flicker_var.get(),
            'flicker_period': int(self.flicker_period_scale.get()),
            'white_balance': self.wb_var.get(),
            'red_gain': float(self.red_gain_scale.get()),
            'blue_gain': float(self.blue_gain_scale.get())
        }

        # Adjust settings based on visibility
        if self.flicker_var.get() != 'Manual':
            settings.pop('flicker_period', None)
        if self.wb_var.get() != 'Manual':
            settings.pop('red_gain', None)
            settings.pop('blue_gain', None)

        self.settings.update(settings)
        send_controls(settings)

    def save_settings(self):
        # Save current settings to the remote Pi
        save_settings_remote(self.settings)

    def video_loop(self):
        try:
            cap = cv2.VideoCapture(VIDEO_FEED_URL)
            if not cap.isOpened():
                messagebox.showerror("Error", "Failed to open video stream.")
                return
            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    continue
                # Resize frame to desired size
                frame = cv2.resize(frame, (1280, 720))
                # Convert BGR to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Convert to PIL Image
                img = Image.fromarray(frame)
                # Convert to ImageTk
                imgtk = ImageTk.PhotoImage(image=img)
                # Estimate frame size in bytes (RGB: 3 bytes per pixel)
                frame_size = frame.nbytes  # Total bytes of the numpy array
                # Put the frame and its size in the queue
                if not self.frame_queue.full():
                    self.frame_queue.put((imgtk, frame_size))
                # Update metrics
                self.frame_count += 1
                self.total_bytes += frame_size
                # Control the frame rate
                time.sleep(1 / self.settings.get('frame_rate', 25))
            cap.release()
        except Exception as e:
            print(f"Video loop error: {e}")

    def update_video(self):
        try:
            if not self.frame_queue.empty():
                imgtk, frame_size = self.frame_queue.get()
                self.video_label.imgtk = imgtk
                self.video_label.configure(image=imgtk)
        except Exception as e:
            print(f"UI update error: {e}")
        finally:
            # Schedule the next frame update
            self.root.after(15, self.update_video)  # ~66 FPS to match queue consumption

    def update_metrics(self):
        # Fetch CPU usage from the selected camera
        try:
            response = requests.get(self.CPU_USAGE_ENDPOINT, timeout=5)
            if response.status_code == 200:
                cpu_usage = response.json().get("cpu_usage", 0)
            else:
                cpu_usage = 0
        except Exception as e:
            cpu_usage = 0

        self.cpu_label.config(text=f"CPU: {cpu_usage}%")
        
        # Update FPS and Bandwidth labels every second
        self.fps = self.frame_count
        # Convert bytes to Megabytes
        self.bandwidth = self.total_bytes / (1024 * 1024)  # MB/s

        # Update labels
        self.fps_label.config(text=f"FPS: {self.fps}")
        self.bandwidth_label.config(text=f"Bandwidth: {self.bandwidth:.2f} MB/s")

        # Reset counters
        self.frame_count = 0
        self.total_bytes = 0

        # Schedule the next metrics update
        self.root.after(1000, self.update_metrics)  # Update every 1 second

    def on_closing(self):
        # Stop the video thread
        self.stop_event.set()
        self.video_thread.join(timeout=1)
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    app = MasterCameraController(root)
    root.mainloop()