# master_camera_controller.py (Updated Layout)

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
import logging
from pathlib import Path


# Configuration
CAMERA_LIST_FILE = 'camera_list.json'
#SCRIPT_DIR = Path(__file__).resolve().parent
#CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent.parent,  'utils','camera_list.json') 
MASTER_SETTINGS_FILE = 'camera_settings.json'

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
    'blue_gain': 1.0,
    'preview_resolution': '360p',
    'selected_camera_id': ''
}

# Mapping of preview resolutions to heights
PREVIEW_RESOLUTIONS = {
    '240p': 240,
    '360p': 360,
    '480p': 480,
    '720p': 720,
    '1080p': 1080
}

# Configure Logging
logging.basicConfig(level=logging.ERROR,  # Set to ERROR to reduce verbosity
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger("MasterCameraController")

# Load camera list from camera_list.json
def load_camera_list():
    if not os.path.exists(CAMERA_LIST_FILE):
        messagebox.showerror("Error", f"{CAMERA_LIST_FILE} not found.")
        sys.exit(1)
    try:
        with open(CAMERA_LIST_FILE, 'r') as f:
            cameras = json.load(f)
            camera_dict = {}
            for cam in cameras:
                name = cam.get('name')
                ip = cam.get('ip')
                if name and ip:
                    # Extract ID from name, e.g., "CAM01" -> "01"
                    cam_id = ''.join(filter(str.isdigit, name))
                    camera_dict[cam_id] = ip
            return camera_dict
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load {CAMERA_LIST_FILE}: {e}")
        sys.exit(1)

camera_dict = load_camera_list()

# Load master settings from camera_settings.json if it exists
def load_master_settings():
    if os.path.exists(MASTER_SETTINGS_FILE):
        try:
            with open(MASTER_SETTINGS_FILE, 'r') as f:
                saved_settings = json.load(f)
            # Merge saved settings into default settings
            merged_settings = default_settings.copy()
            merged_settings.update(saved_settings)
            return merged_settings
        except Exception as e:
            logger.error(f"Failed to load {MASTER_SETTINGS_FILE}: {e}")
            return default_settings.copy()
    else:
        return default_settings.copy()

# Save master settings to camera_settings.json
def save_master_settings(settings):
    try:
        with open(MASTER_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
        logger.debug("Saved settings to camera_settings.json")
    except Exception as e:
        logger.error(f"Failed to save settings to {MASTER_SETTINGS_FILE}: {e}")

# Function to send control settings to a specific camera
def send_controls_to_camera(ip, settings):
    try:
        control_endpoint = f'http://{ip}:5000/controls'
        response = requests.post(control_endpoint, json=settings, timeout=5)
        if response.status_code != 200:
            logger = logging.getLogger("send_controls_to_camera")
            logger.error(f"Failed to update controls for {ip}: {response.text}")
    except Exception as e:
        logger = logging.getLogger("send_controls_to_camera")
        logger.error(f"Failed to update controls for {ip}: {e}")

# Function to save settings to a specific camera
def save_settings_remote(ip, settings):
    try:
        save_endpoint = f'http://{ip}:5000/save_settings'
        response = requests.post(save_endpoint, json=settings, timeout=5)
        if response.status_code != 200:
            logger = logging.getLogger("save_settings_remote")
            logger.error(f"Failed to save settings for {ip}: {response.text}")
    except Exception as e:
        logger = logging.getLogger("save_settings_remote")
        logger.error(f"Failed to save settings for {ip}: {e}")

# Function to load settings from a specific camera
def load_settings_from_camera(ip):
    try:
        load_endpoint = f'http://{ip}:5000/load_settings'
        response = requests.get(load_endpoint, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            logger = logging.getLogger("load_settings_from_camera")
            logger.error(f"Failed to load settings for {ip}: {response.text}")
            return default_settings.copy()
    except Exception as e:
        logger = logging.getLogger("load_settings_from_camera")
        logger.error(f"Failed to load settings for {ip}: {e}")
        return default_settings.copy()

class MasterCameraController:
    def __init__(self, root, camera_dict, master_settings):
        self.root = root
        self.root.title("VolumanXR - Camera Settings")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.camera_dict = camera_dict  # Mapping of camera ID to IP
        self.selected_camera_id = tk.StringVar()
        self.selected_camera_ip = None

        # Initialize settings from master_settings
        self.settings = master_settings.copy()

        # Initialize video stream variables
        self.frame_queue = queue.Queue(maxsize=1)  # Minimal buffering
        self.stop_event = threading.Event()
        self.video_thread = None

        # Initialize metrics variables
        self.frame_count = 0
        self.total_bytes = 0
        self.fps = 0
        self.bandwidth = 0  # in MB/s
        self.cpu_usage = 0  # in %

        # Initialize GUI elements
        self.create_gui()

        # If a selected_camera_id exists in settings, set it in the Camera ID input field
        if self.settings.get('selected_camera_id'):
            selected_cam_id = self.settings['selected_camera_id']
            if selected_cam_id in self.camera_dict:
                self.camera_id_entry.insert(0, selected_cam_id)
                self.selected_camera_id.set(selected_cam_id)
                self.selected_camera_ip = self.camera_dict[selected_cam_id]

        # Start the UI update loop
        self.update_video()

        # Start the metrics update loop
        self.update_metrics()

        # If we have a selected camera from startup, start video stream immediately
        if self.selected_camera_ip:
            self.start_video_stream()

    def create_gui(self):
        # Main container frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Configure grid
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=2)
        main_frame.rowconfigure(1, weight=1)

        # Live View Settings Frame (top-left)
        live_view_frame = ttk.LabelFrame(main_frame, text="Live View Settings")
        live_view_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        # Camera Settings Frame (below Live View)
        camera_settings_frame = ttk.LabelFrame(main_frame, text="Camera Settings")
        camera_settings_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        # Video Frame (right side)
        video_frame = ttk.LabelFrame(main_frame, text="Live Video")
        video_frame.grid(row=0, column=1, rowspan=2, sticky="nsew")
        main_frame.rowconfigure(0, weight=0)
        main_frame.rowconfigure(1, weight=1)

        # --- Live View Settings Widgets ---

        # Camera ID Selection
        ttk.Label(live_view_frame, text="Camera ID:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.camera_id_entry = ttk.Entry(live_view_frame, width=10)
        self.camera_id_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        select_button = ttk.Button(live_view_frame, text="Select", command=self.select_camera)
        select_button.grid(row=0, column=2, padx=5, pady=5)

        # Preview Resolution Dropdown
        preview_res_label = ttk.Label(live_view_frame, text="Preview Resolution:")
        preview_res_label.grid(row=1, column=0, padx=5, pady=5, sticky="e")

        self.preview_res_var = tk.StringVar(value=self.settings.get('preview_resolution', '360p'))
        preview_res_options = list(PREVIEW_RESOLUTIONS.keys())

        def preview_res_selection_changed(value):
            self.update_controls()
            # If camera is selected, restart video stream
            if self.selected_camera_ip:
                self.start_video_stream()

        self.preview_res_menu = ttk.OptionMenu(live_view_frame, self.preview_res_var, self.preview_res_var.get(), *preview_res_options, command=preview_res_selection_changed)
        self.preview_res_menu.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # --- Camera Settings Widgets ---

        # Resolution settings
        resolution_frame = ttk.Frame(camera_settings_frame)
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
        self.fps_scale = tk.Scale(camera_settings_frame, from_=1, to=60, orient=tk.HORIZONTAL, label="Frame Rate (FPS)", command=lambda x: self.update_controls())
        self.fps_scale.set(self.settings.get('frame_rate', 25))
        self.fps_scale.pack(fill="x", padx=5, pady=5)

        # Shutter Angle
        self.shutter_angle_scale = tk.Scale(camera_settings_frame, from_=1, to=360, orient=tk.HORIZONTAL, label="Shutter Angle (degrees)", command=lambda x: self.update_controls())
        self.shutter_angle_scale.set(self.settings.get('shutter_angle', 180))
        self.shutter_angle_scale.pack(fill="x", padx=5, pady=5)

        # ISO (Analogue Gain)
        self.iso_scale = tk.Scale(camera_settings_frame, from_=100, to=6400, orient=tk.HORIZONTAL, label="ISO", command=lambda x: self.update_controls())
        self.iso_scale.set(self.settings.get('iso', 100))
        self.iso_scale.pack(fill="x", padx=5, pady=5)
        
        # Auto Exposure
        self.ae_var = tk.BooleanVar(value=self.settings.get('auto_exposure', True))
        self.ae_check = ttk.Checkbutton(camera_settings_frame, text="Auto Exposure", variable=self.ae_var, command=self.update_controls)
        self.ae_check.pack(anchor='w', padx=5, pady=5)

        # Brightness
        self.brightness_scale = tk.Scale(camera_settings_frame, from_=-100, to=100, orient=tk.HORIZONTAL, label="Brightness", command=lambda x: self.update_controls())
        self.brightness_scale.set(self.settings.get('brightness', 0))
        self.brightness_scale.pack(fill="x", padx=5, pady=5)

        # Contrast
        self.contrast_scale = tk.Scale(camera_settings_frame, from_=0, to=200, orient=tk.HORIZONTAL, label="Contrast", command=lambda x: self.update_controls())
        self.contrast_scale.set(self.settings.get('contrast', 100))
        self.contrast_scale.pack(fill="x", padx=5, pady=5)

        # Saturation
        self.saturation_scale = tk.Scale(camera_settings_frame, from_=0, to=200, orient=tk.HORIZONTAL, label="Saturation", command=lambda x: self.update_controls())
        self.saturation_scale.set(self.settings.get('saturation', 100))
        self.saturation_scale.pack(fill="x", padx=5, pady=5)

        # Sharpness
        self.sharpness_scale = tk.Scale(camera_settings_frame, from_=0, to=200, orient=tk.HORIZONTAL, label="Sharpness", command=lambda x: self.update_controls())
        self.sharpness_scale.set(self.settings.get('sharpness', 100))
        self.sharpness_scale.pack(fill="x", padx=5, pady=5)

        # Flicker Control Dropdown
        flicker_label = ttk.Label(camera_settings_frame, text="Flicker Control:")
        flicker_label.pack(anchor='w', padx=5, pady=5)

        self.flicker_var = tk.StringVar(value=self.settings.get('flicker_control', 'Off'))
        flicker_options = ['Off', '50Hz', '60Hz', 'Manual']

        def flicker_selection_changed(value):
            self.update_controls()
            if value == 'Manual':
                # Show the flicker period slider
                self.flicker_period_scale.pack(fill="x", padx=5, pady=5)
            else:
                self.flicker_period_scale.pack_forget()

        self.flicker_menu = ttk.OptionMenu(camera_settings_frame, self.flicker_var, self.flicker_var.get(), *flicker_options, command=flicker_selection_changed)
        self.flicker_menu.pack(anchor='w', padx=5, pady=5)

        # Flicker Period Slider for Manual Mode
        self.flicker_period_scale = tk.Scale(camera_settings_frame, from_=10, to=1000, orient=tk.HORIZONTAL, label="Flicker Period (Hz)", command=lambda x: self.update_controls())
        self.flicker_period_scale.set(self.settings.get('flicker_period', 50))
        if self.settings.get('flicker_control', 'Off') == 'Manual':
            self.flicker_period_scale.pack(fill="x", padx=5, pady=5)

        # White Balance Dropdown
        wb_label = ttk.Label(camera_settings_frame, text="White Balance:")
        wb_label.pack(anchor='w', padx=5, pady=5)

        self.wb_var = tk.StringVar(value=self.settings.get('white_balance', 'Auto'))
        wb_options = ['Auto', '3200K', '4400K', '5600K', 'Manual']

        def wb_selection_changed(value):
            self.update_controls()
            if value == 'Manual':
                self.red_gain_scale.pack(fill="x", padx=5, pady=5)
                self.blue_gain_scale.pack(fill="x", padx=5, pady=5)
            else:
                self.red_gain_scale.pack_forget()
                self.blue_gain_scale.pack_forget()

        self.wb_menu = ttk.OptionMenu(camera_settings_frame, self.wb_var, self.wb_var.get(), *wb_options, command=wb_selection_changed)
        self.wb_menu.pack(anchor='w', padx=5, pady=5)

        # Red Gain Slider
        self.red_gain_scale = tk.Scale(camera_settings_frame, from_=0.0, to=8.0, resolution=0.1, orient=tk.HORIZONTAL, label="Red Gain", command=lambda x: self.update_controls())
        self.red_gain_scale.set(self.settings.get('red_gain', 1.0))

        # Blue Gain Slider
        self.blue_gain_scale = tk.Scale(camera_settings_frame, from_=0.0, to=8.0, resolution=0.1, orient=tk.HORIZONTAL, label="Blue Gain", command=lambda x: self.update_controls())
        self.blue_gain_scale.set(self.settings.get('blue_gain', 1.0))

        if self.settings.get('white_balance', 'Auto') == 'Manual':
            self.red_gain_scale.pack(fill="x", padx=5, pady=5)
            self.blue_gain_scale.pack(fill="x", padx=5, pady=5)

        # Save Settings Button
        save_button = ttk.Button(camera_settings_frame, text="Save Settings", command=self.save_settings)
        save_button.pack(anchor='w', padx=5, pady=5)

        # Metrics Frame above the video
        metrics_frame = ttk.Frame(video_frame)
        metrics_frame.pack(fill="x", padx=5, pady=5)

        # FPS Label
        self.fps_label = ttk.Label(metrics_frame, text="FPS: 0")
        self.fps_label.pack(side="left", padx=5)

        # Bandwidth Label
        self.bandwidth_label = ttk.Label(metrics_frame, text="Bandwidth: 0 MB/s")
        self.bandwidth_label.pack(side="left", padx=5)

        # CPU Usage Label
        self.cpu_label = ttk.Label(metrics_frame, text="CPU Usage: 0%")
        self.cpu_label.pack(side="left", padx=5)

        # Video Label
        self.video_label = ttk.Label(video_frame)
        self.video_label.pack(fill="both", expand=True)

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
            'blue_gain': float(self.blue_gain_scale.get()),
            'preview_resolution': self.preview_res_var.get()
        }

        # Adjust settings based on visibility
        if self.flicker_var.get() != 'Manual':
            settings.pop('flicker_period', None)
        if self.wb_var.get() != 'Manual':
            settings.pop('red_gain', None)
            settings.pop('blue_gain', None)

        # Update internal settings
        self.settings.update(settings)

        # Save master settings immediately
        save_master_settings(self.settings)

        # Send settings to all cameras
        threading.Thread(target=self.send_controls_to_all_cameras, args=(settings,), daemon=True).start()

    def send_controls_to_all_cameras(self, settings):
        threads = []
        for cam_id, ip in self.camera_dict.items():
            t = threading.Thread(target=send_controls_to_camera, args=(ip, settings))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

    def save_settings(self):
        # Save current settings to all remote cameras
        threading.Thread(target=self.save_settings_to_all_cameras, args=(self.settings,), daemon=True).start()

    def save_settings_to_all_cameras(self, settings):
        threads = []
        for cam_id, ip in self.camera_dict.items():
            t = threading.Thread(target=save_settings_remote, args=(ip, settings))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        messagebox.showinfo("Success", "Settings saved to all cameras successfully.")

    def select_camera(self):
        cam_id = self.camera_id_entry.get().strip()
        if cam_id not in self.camera_dict:
            messagebox.showerror("Error", f"Camera ID '{cam_id}' not found.")
            return
        self.selected_camera_id.set(cam_id)
        self.selected_camera_ip = self.camera_dict[cam_id]

        # Save selected camera ID to settings
        self.settings['selected_camera_id'] = cam_id
        save_master_settings(self.settings)

        self.start_video_stream()

    def start_video_stream(self):
        # Stop existing video thread if any
        if self.video_thread and self.video_thread.is_alive():
            self.stop_event.set()
            self.video_thread.join(timeout=1)
            self.stop_event.clear()

        # Clear the frame queue
        with self.frame_queue.mutex:
            self.frame_queue.queue.clear()

        # Start new video thread
        self.video_thread = threading.Thread(target=self.video_loop, daemon=True)
        self.video_thread.start()

        # Start CPU monitoring thread
        self.cpu_thread = threading.Thread(target=self.cpu_loop, daemon=True)
        self.cpu_thread.start()

    def video_loop(self):
        try:
            video_feed_url = f'http://{self.selected_camera_ip}:5000/video_feed'
            cap = cv2.VideoCapture(video_feed_url)
            if not cap.isOpened():
                messagebox.showerror("Error", f"Failed to open video stream for camera ID {self.selected_camera_id.get()}.")
                return
            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    continue
                # Convert BGR to RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Resize frame based on preview_resolution while maintaining aspect ratio
                preview_resolution = self.settings.get('preview_resolution', '360p')
                preview_height = PREVIEW_RESOLUTIONS.get(preview_resolution, 360)
                original_width = self.settings.get('width', 1280)
                original_height = self.settings.get('height', 720)
                aspect_ratio = original_width / original_height if original_height != 0 else 16/9
                preview_width = int(preview_height * aspect_ratio)
                frame = cv2.resize(frame, (preview_width, preview_height))

                # Convert to PIL Image
                img = Image.fromarray(frame)
                # Convert to ImageTk
                imgtk = ImageTk.PhotoImage(image=img)
                # Estimate frame size in bytes
                frame_size = frame.nbytes

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
            logger = logging.getLogger("video_loop")
            logger.error(f"Video loop error for camera ID {self.selected_camera_id.get()}: {e}")

    def cpu_loop(self):
        try:
            status_endpoint = f'http://{self.selected_camera_ip}:5000/status'
            while not self.stop_event.is_set():
                response = requests.get(status_endpoint, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    self.cpu_usage = data.get('cpu_usage', 0)
                else:
                    logger = logging.getLogger("cpu_loop")
                    logger.error(f"Failed to get CPU usage for camera ID {self.selected_camera_id.get()}: {response.text}")
                time.sleep(1)
        except Exception as e:
            logger = logging.getLogger("cpu_loop")
            logger.error(f"CPU loop error for camera ID {self.selected_camera_id.get()}: {e}")

    def update_video(self):
        try:
            if not self.frame_queue.empty():
                imgtk, frame_size = self.frame_queue.get()
                self.video_label.imgtk = imgtk
                self.video_label.configure(image=imgtk)
        except Exception as e:
            logger = logging.getLogger("update_video")
            logger.error(f"UI update error: {e}")
        finally:
            # Schedule the next frame update
            self.root.after(15, self.update_video)  # ~66 FPS to match queue consumption

    def update_metrics(self):
        # Update FPS and Bandwidth labels every second
        self.fps = self.frame_count
        self.bandwidth = self.total_bytes / (1024 * 1024)  # MB/s

        # Update labels
        self.fps_label.config(text=f"FPS: {self.fps}")
        self.bandwidth_label.config(text=f"Bandwidth: {self.bandwidth:.2f} MB/s")
        self.cpu_label.config(text=f"CPU Usage: {self.cpu_usage}%")

        # Reset counters
        self.frame_count = 0
        self.total_bytes = 0

        # Schedule the next metrics update
        self.root.after(1000, self.update_metrics)

    def on_closing(self):
        # Stop the video thread
        self.stop_event.set()
        if self.video_thread and self.video_thread.is_alive():
            self.video_thread.join(timeout=1)
        if hasattr(self, 'cpu_thread') and self.cpu_thread.is_alive():
            self.cpu_thread.join(timeout=1)
        self.root.destroy()

if __name__ == '__main__':
    master_settings = load_master_settings()
    root = tk.Tk()
    app = MasterCameraController(root, camera_dict, master_settings)
    root.mainloop()
