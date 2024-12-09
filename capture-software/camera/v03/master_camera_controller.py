# master_camera_controller.py

import sys
import json
import os
import requests
import cv2
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import threading
import queue
import time
import psutil

# Configuration
CAMERA_LIST_FILE = 'camera_list.json'  # Path to your camera list JSON

# Function to load camera list from JSON
def load_camera_list():
    if not os.path.exists(CAMERA_LIST_FILE):
        messagebox.showerror("Error", f"{CAMERA_LIST_FILE} not found.")
        return []
    try:
        with open(CAMERA_LIST_FILE, 'r') as f:
            cameras = json.load(f)
            return cameras
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load {CAMERA_LIST_FILE}: {e}")
        return []

# Function to send control settings to a specific camera
def send_controls(camera_ip, settings):
    try:
        control_endpoint = f'http://{camera_ip}:5000/controls'
        response = requests.post(control_endpoint, json=settings, timeout=5)
        if response.status_code != 200:
            print(f"Failed to update controls for {camera_ip}: {response.text}")
    except Exception as e:
        print(f"Error updating controls for {camera_ip}: {e}")

# Function to send settings to all cameras
def send_controls_to_all(cameras, settings):
    threads = []
    for camera in cameras:
        camera_ip = camera['ip']
        thread = threading.Thread(target=send_controls, args=(camera_ip, settings))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

# Function to load settings from the master PC
def load_settings():
    # Define default settings; these should match the remote settings
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
    return default_settings.copy()

class CameraStream:
    def __init__(self, camera, queue, label):
        self.camera = camera
        self.camera_name = camera['name']
        self.camera_ip = camera['ip']
        self.queue = queue
        self.label = label
        self.capture = None
        self.thread = threading.Thread(target=self.start_stream, daemon=True)
        self.thread.start()

    def start_stream(self):
        # GStreamer pipeline for HTTP MJPEG streaming
        # Using OpenCV's VideoCapture to read from HTTP MJPEG stream
        stream_url = f"http://{self.camera_ip}:8080"  # Updated port to 8080
        self.capture = cv2.VideoCapture(stream_url)
        if not self.capture.isOpened():
            print(f"Failed to open stream for {self.camera_name} at {stream_url}")
            return
        while True:
            if not self.capture.isOpened():
                break
            ret, frame = self.capture.read()
            if not ret:
                print(f"Stream ended or failed for {self.camera_name}")
                break
            # Put frame in queue
            if not self.queue.full():
                self.queue.put(frame)
            else:
                # Drop frame if queue is full
                pass
        self.capture.release()

    def update_label(self):
        if not self.queue.empty():
            frame = self.queue.get()
            # Convert frame to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Convert to PIL Image
            img = Image.fromarray(frame)
            imgtk = ImageTk.PhotoImage(image=img)
            self.label.imgtk = imgtk
            self.label.configure(image=imgtk)

class MasterCameraController:
    def __init__(self, root, cameras):
        self.root = root
        self.root.title("Master PC Raspberry Pi Camera Controls")
        self.cameras = cameras

        # Initialize GUI elements
        self.create_gui()

        # Initialize settings
        self.settings = load_settings()

        # Initialize network counters
        self.initial_bytes_recv = psutil.net_io_counters().bytes_recv
        self.previous_bytes_recv = self.initial_bytes_recv
        self.current_bandwidth = 0  # in MB/s

        # Dictionary to hold camera streams
        self.camera_streams = {}

    def create_gui(self):
        # Top Frame for Controls
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill="x", padx=10, pady=5)

        # Camera ID Input
        ttk.Label(control_frame, text="Camera ID:").pack(side="left", padx=5)
        self.camera_id_var = tk.StringVar()
        self.camera_id_entry = ttk.Entry(control_frame, textvariable=self.camera_id_var, width=5)
        self.camera_id_entry.pack(side="left", padx=5)
        self.camera_id_entry.bind("<Return>", lambda event: self.select_camera())

        # View Options
        ttk.Label(control_frame, text="View:").pack(side="left", padx=5)
        self.view_option_var = tk.StringVar(value="Single")
        view_options = ["Single", "10", "20", "35", "All"]
        self.view_option_menu = ttk.OptionMenu(control_frame, self.view_option_var, self.view_option_var.get(), *view_options, command=self.update_view)
        self.view_option_menu.pack(side="left", padx=5)

        # Select Button
        select_button = ttk.Button(control_frame, text="Select Camera", command=self.select_camera)
        select_button.pack(side="left", padx=5)

        # Save Settings Button
        save_button = ttk.Button(control_frame, text="Save Settings to All", command=self.save_settings)
        save_button.pack(side="right", padx=5)

        # Frame for Video Feeds
        self.video_container = ttk.Frame(self.root)
        self.video_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Scrollbar for Video Feeds
        self.canvas = tk.Canvas(self.video_container)
        self.scrollbar = ttk.Scrollbar(self.video_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Metrics Frame
        metrics_frame = ttk.Frame(self.root)
        metrics_frame.pack(fill="x", padx=10, pady=5)

        # Bandwidth Label
        self.bandwidth_label = ttk.Label(metrics_frame, text="Bandwidth: 0 MB/s")
        self.bandwidth_label.pack(side="left", padx=5)

        # FPS Label
        self.fps_label = ttk.Label(metrics_frame, text="FPS: N/A")
        self.fps_label.pack(side="left", padx=5)

    def select_camera(self):
        camera_id = self.camera_id_var.get().strip()
        if not camera_id:
            messagebox.showerror("Error", "Please enter a Camera ID.")
            return
        # Find camera with the given ID
        selected_cameras = [cam for cam in self.cameras if cam['name'].endswith(camera_id)]
        if not selected_cameras:
            messagebox.showerror("Error", f"No camera found with ID {camera_id}.")
            return
        self.display_cameras(selected_cameras)

    def update_view(self, view_option):
        if view_option == "Single":
            # Optionally, prompt to select a camera
            pass
        elif view_option == "All":
            self.display_cameras(self.cameras)
        else:
            try:
                num = int(view_option)
                selected_cameras = self.cameras[:num]
                self.display_cameras(selected_cameras)
            except ValueError:
                pass

    def display_cameras(self, selected_cameras):
        # Clear existing streams
        for camera_name, stream in self.camera_streams.items():
            # In a more advanced implementation, you might want to close the streams
            pass
        self.camera_streams.clear()

        # Clear the scrollable frame
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        # Create video labels and start streams
        for idx, camera in enumerate(selected_cameras):
            frame = ttk.LabelFrame(self.scrollable_frame, text=f"{camera['name']} ({camera['ip']})")
            frame.grid(row=idx // 2, column=idx % 2, padx=5, pady=5, sticky="nsew")

            label = ttk.Label(frame)
            label.pack()

            # Initialize queue for frames
            frame_queue = queue.Queue(maxsize=10)

            # Initialize and start camera stream
            camera_stream = CameraStream(camera, frame_queue, label)
            self.camera_streams[camera['name']] = camera_stream

        # Start the video update loop
        self.update_video()

    def update_video(self):
        for camera_name, stream in self.camera_streams.items():
            stream.update_label()
        # Schedule the next frame update
        self.root.after(30, self.update_video)  # Update every 30 ms (~33 FPS)

    def save_settings(self):
        # Collect current settings from the GUI
        settings = {
            'width': self.settings['width'],
            'height': self.settings['height'],
            'frame_rate': self.settings['frame_rate'],
            'shutter_angle': self.settings['shutter_angle'],
            'iso': self.settings['iso'],
            'brightness': self.settings['brightness'],
            'contrast': self.settings['contrast'],
            'saturation': self.settings['saturation'],
            'sharpness': self.settings['sharpness'],
            'auto_exposure': self.settings['auto_exposure'],
            'flicker_control': self.settings['flicker_control'],
            'flicker_period': self.settings['flicker_period'],
            'white_balance': self.settings['white_balance'],
            'red_gain': self.settings['red_gain'],
            'blue_gain': self.settings['blue_gain']
        }

        # Send settings to all cameras
        send_controls_to_all(self.cameras, settings)
        messagebox.showinfo("Success", "Settings synchronized to all cameras.")

    def update_metrics(self):
        # Update network bandwidth usage
        current_bytes_recv = psutil.net_io_counters().bytes_recv
        bytes_received = current_bytes_recv - self.previous_bytes_recv
        self.previous_bytes_recv = current_bytes_recv
        self.current_bandwidth = bytes_received / (1024 * 1024)  # MB/s

        # Update title with bandwidth info
        self.root.title(f"Master PC Raspberry Pi Camera Controls - Bandwidth: {self.current_bandwidth:.2f} MB/s")

        # Update FPS (Placeholder as FPS tracking is not implemented)
        self.fps_label.config(text=f"FPS: N/A")

        # Schedule the next metrics update
        self.root.after(1000, self.update_metrics)  # Update every 1 second

    def on_closing(self):
        # Release all video captures
        for stream in self.camera_streams.values():
            if stream.capture and stream.capture.isOpened():
                stream.capture.release()
        self.root.destroy()

class CameraStream:
    def __init__(self, camera, queue, label):
        self.camera = camera
        self.camera_name = camera['name']
        self.camera_ip = camera['ip']
        self.queue = queue
        self.label = label
        self.capture = None
        self.thread = threading.Thread(target=self.start_stream, daemon=True)
        self.thread.start()

    def start_stream(self):
        # GStreamer pipeline for HTTP MJPEG streaming
        # Using OpenCV's VideoCapture to read from HTTP MJPEG stream
        stream_url = f"http://{self.camera_ip}:8080"  # Updated port to 8080
        self.capture = cv2.VideoCapture(stream_url)
        if not self.capture.isOpened():
            print(f"Failed to open stream for {self.camera_name} at {stream_url}")
            return
        while True:
            if not self.capture.isOpened():
                break
            ret, frame = self.capture.read()
            if not ret:
                print(f"Stream ended or failed for {self.camera_name}")
                break
            # Put frame in queue
            if not self.queue.full():
                self.queue.put(frame)
            else:
                # Drop frame if queue is full
                pass
        self.capture.release()

    def update_label(self):
        if not self.queue.empty():
            frame = self.queue.get()
            # Convert frame to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Convert to PIL Image
            img = Image.fromarray(frame)
            imgtk = ImageTk.PhotoImage(image=img)
            self.label.imgtk = imgtk
            self.label.configure(image=imgtk)

if __name__ == '__main__':
    # Load camera list
    cameras = load_camera_list()
    if not cameras:
        sys.exit(1)

    # Create main window
    root = tk.Tk()
    app = MasterCameraController(root, cameras)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.update_metrics()  # Start metrics update loop
    root.mainloop()
