# master_controller.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import json
import os
import hashlib
import zmq
import uuid
import statistics
import math
import socket
import struct
import subprocess
import logging

# Configure logging
logging.basicConfig(filename='master_controller.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# Configuration
CAMERA_LIST_FILE = 'camera_list.json'
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'
MASTER_PC_IP = '0.0.0.0'  # Bind to all interfaces or specify the Master PC's IP
MASTER_PC_PORT = 50005
TCP_DOWNLOAD_PORT = 50006  # Fixed TCP port for downloads

class DebugWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title('VolumanXR - Debug Window')
        self.create_widgets()

    def create_widgets(self):
        self.text = tk.Text(self)
        self.text.pack(fill='both', expand=True)
        
        control_frame = ttk.Frame(self)
        control_frame.pack(fill='x', padx=5, pady=5)

        clear_messages_button = ttk.Button(control_frame, text='Clear Messages', command=self.clear_messages)
        clear_messages_button.grid(row=0, column=0, padx=5, pady=5)
        
        pause_messages_button = ttk.Button(control_frame, text='Pause Messages', command=self.pause_messages)
        pause_messages_button.grid(row=0, column=1, padx=5, pady=5)
        
        resume_messages_button = ttk.Button(control_frame, text='Resume Messages', command=self.resume_messages)
        resume_messages_button.grid(row=0, column=2, padx=5, pady=5)

    def insert_message(self, who, message):
        self.text.insert('end', f'{who}: {message}\n')
        self.text.see('end')
        
    def clear_messages(self):
        self.text.delete('1.0', 'end')
        
    def pause_messages(self):
        self.text.config(state='disabled')
        
    def resume_messages(self):
        self.text.config(state='normal')

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title('VolumanXR - Camera Control UI')
        self.debug_window = None
        self.debug_mode = False

        self.cameras = []
        self.camera_status = {}
        self.load_camera_list()

        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR)

        self.context = zmq.Context()
        self.router_socket = self.context.socket(zmq.ROUTER)
        try:
            self.router_socket.bind(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
            logging.info(f"Master ROUTER socket bound to {MASTER_PC_IP}:{MASTER_PC_PORT}")
        except zmq.ZMQError as e:
            messagebox.showerror("ZMQ Error", f"Failed to bind to {MASTER_PC_IP}:{MASTER_PC_PORT}: {e}")
            logging.error(f"Failed to bind ZMQ socket: {e}")
            exit(1)
        self.poller = zmq.Poller()
        self.poller.register(self.router_socket, zmq.POLLIN)

        self.connected_cameras = {}  # identity -> ip
        self.ip_to_identity = {}

        self.create_widgets()

        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()

    def load_camera_list(self):
        if not os.path.exists(CAMERA_LIST_FILE):
            logging.error(f"Camera list file {CAMERA_LIST_FILE} not found.")
            return
        with open(CAMERA_LIST_FILE, 'r') as f:
            self.cameras = json.load(f)
            # Remove port usage from cameras if present
            for c in self.cameras:
                if 'port' in c:
                    del c['port']

    def create_widgets(self):
        # Top Frame for Controls
        control_frame = ttk.Frame(self.root)
        control_frame.pack(side='top', fill='x', padx=5, pady=5)

        # Session Name Entry
        ttk.Label(control_frame, text='Session Name:').grid(row=0, column=0, padx=5, pady=5, sticky='e')
        self.session_entry = ttk.Entry(control_frame)
        self.session_entry.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        # Bitrate Entry
        ttk.Label(control_frame, text='Bitrate (kbps):').grid(row=1, column=0, padx=5, pady=5, sticky='e')
        self.bitrate_entry = ttk.Entry(control_frame)
        self.bitrate_entry.insert(0, '15000')  # Default bitrate
        self.bitrate_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        # Still Image Controls
        ttk.Label(control_frame, text='Still Format:').grid(row=2, column=0, padx=5, pady=5, sticky='e')
        self.compression_format_var = tk.StringVar(value='jpeg')
        ttk.Combobox(control_frame, textvariable=self.compression_format_var, values=['jpeg', 'png']).grid(row=2, column=1, padx=5, pady=5, sticky='w')

        ttk.Label(control_frame, text='Compression (%):').grid(row=3, column=0, padx=5, pady=5, sticky='e')
        self.compression_entry = ttk.Entry(control_frame)
        self.compression_entry.insert(0, '100')  # Default compression
        self.compression_entry.grid(row=3, column=1, padx=5, pady=5, sticky='w')

        ttk.Label(control_frame, text='Still Base Name:').grid(row=4, column=0, padx=5, pady=5, sticky='e')
        self.still_name_entry = ttk.Entry(control_frame)
        self.still_name_entry.insert(0, 'Still')
        self.still_name_entry.grid(row=4, column=1, padx=5, pady=5, sticky='w')

        # Buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=10)

        self.start_button = ttk.Button(button_frame, text='Start Recording', command=self.start_recording)
        self.start_button.grid(row=0, column=0, padx=5)

        self.stop_button = ttk.Button(button_frame, text='Stop Recording', command=self.stop_recording)
        self.stop_button.grid(row=0, column=1, padx=5)

        self.capture_button = ttk.Button(button_frame, text='Capture Still', command=self.capture_stills)
        self.capture_button.grid(row=0, column=2, padx=5)

        self.share_settings_button = ttk.Button(button_frame, text='Share Camera Settings', command=self.share_camera_settings)
        self.share_settings_button.grid(row=0, column=3, padx=5)

        self.debug_button = ttk.Button(button_frame, text='Toggle Debug Window', command=self.toggle_debug)
        self.debug_button.grid(row=0, column=4, padx=5)

        # Sessions Treeview
        sessions_frame = ttk.Frame(self.root)
        sessions_frame.pack(fill='both', expand=True, padx=5, pady=5)

        columns = ('Session Name', 'First Clip Size', 'Total Session Size', 'Missing Clips', 'Status')
        self.sessions_tree = ttk.Treeview(sessions_frame, columns=columns, show='headings')
        for col in columns:
            self.sessions_tree.heading(col, text=col)
            self.sessions_tree.column(col, width=150, anchor='center')
        self.sessions_tree.pack(fill='both', expand=True)

        # Session Management Buttons
        manage_frame = ttk.Frame(self.root)
        manage_frame.pack(fill='x', padx=5, pady=5)

        self.download_button = ttk.Button(manage_frame, text='Download Session', command=self.download_session)
        self.download_button.grid(row=0, column=0, padx=5, pady=5)

        self.delete_local_button = ttk.Button(manage_frame, text='Delete Session (Local)', command=self.delete_session_local)
        self.delete_local_button.grid(row=0, column=1, padx=5, pady=5)

        self.delete_remote_button = ttk.Button(manage_frame, text='Delete Session (Remote)', command=self.delete_session_remote)
        self.delete_remote_button.grid(row=0, column=2, padx=5, pady=5)

        self.open_sessions_button = ttk.Button(manage_frame, text='Open Sessions Folder', command=self.open_local_sessions_folder)
        self.open_sessions_button.grid(row=0, column=3, padx=5, pady=5)

        # Progress Bars and Labels
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill='x', padx=5, pady=5)

        self.current_file_label = ttk.Label(progress_frame, text="Current Session: N/A")
        self.current_file_label.pack(fill='x', padx=5, pady=2)

        self.current_progress = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.current_progress.pack(fill='x', padx=5, pady=2)

        self.current_eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.current_eta_label.pack(fill='x', padx=5, pady=2)

        self.overall_progress = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.overall_progress.pack(fill='x', padx=5, pady=2)

        self.overall_eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.overall_eta_label.pack(fill='x', padx=5, pady=2)

        # Event Log
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill='both', expand=True, padx=5, pady=5)

        self.log_text = tk.Text(log_frame, height=10)
        self.log_text.pack(fill='both', expand=True)

        # Refresh Sessions
        self.get_sessions()

    def toggle_debug(self):
        if self.debug_window:
            self.debug_window.destroy()
            self.debug_window = None
            self.debug_mode = False
        else:
            self.debug_window = DebugWindow(self.root)
            self.debug_mode = True

    def share_camera_settings(self):
        settings_file = filedialog.askopenfilename(title='Select Camera Settings File', filetypes=[('JSON Files', '*.json')])
        if settings_file:
            try:
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                message = {
                    'task': 'UPDATE_SETTINGS',
                    'settings': settings
                }
                self.broadcast_message(message)
                self.log_event('Shared camera settings with all cameras.')
            except Exception as e:
                logging.error(f"Failed to share camera settings: {e}")
                messagebox.showerror("Error", f"Failed to share camera settings: {e}")

    def log_event(self, message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(EVENT_LOG, 'a') as log_file:
            log_file.write(f'[{timestamp}] {message}\n')
        logging.info(message)
        self.log_text.insert('end', f'[{timestamp}] {message}\n')
        self.log_text.see('end')
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message('MASTER', message)

    def receive_loop(self):
        while self.running:
            try:
                socks = dict(self.poller.poll(1000))
                if self.router_socket in socks and socks[self.router_socket] == zmq.POLLIN:
                    frames = self.router_socket.recv_multipart()
                    if len(frames) != 2:
                        self.log_event(f'Invalid message format received: {frames}')
                        continue
                    identity = frames[0]
                    message = json.loads(frames[1].decode())
                    self.handle_message(identity, message)
            except Exception as e:
                self.log_event(f'Error in receive_loop: {e}')

    def handle_message(self, identity, message):
        task = message.get('task')
        ip = message.get('ip', 'Unknown')
        if not task:
            self.log_event(f'Ignored message without task from {ip}: {message}')
            return  # Ignore messages without a task
        if task == 'REGISTER':
            self.connected_cameras[identity] = ip
            self.ip_to_identity[ip] = identity
            self.camera_status[ip] = {
                'state': 'STANDBY',
                'last_seen': time.time(),
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }
            self.update_status_tree(ip)
            self.log_event(f'Camera registered: {ip}')
        elif task == 'STATUS':
            state = message.get('state')
            storage_remaining = message.get('storage_remaining_mb')
            sessions = message.get('sessions', [])
            self.camera_status[ip].update({
                'state': state,
                'last_seen': time.time(),
                'storage_remaining_mb': storage_remaining,
                'sessions': sessions
            })
            self.update_status_tree(ip)
        elif task == 'FILE_TRANSFER_COMPLETE':
            filename = message.get('file')
            checksum = message.get('checksum')
            local_file = os.path.join(SESSIONS_DIR, filename)
            if os.path.exists(local_file):
                local_checksum = self.calculate_checksum(local_file)
                if local_checksum == checksum:
                    self.log_event(f'File {filename} transferred and verified.')
                else:
                    self.log_event(f'Checksum mismatch for file {filename}.')
            else:
                self.log_event(f'File {filename} not found for checksum verification.')
        elif task == 'SETTINGS_UPDATED':
            self.log_event(f'Camera settings updated on {ip}.')
        elif task == 'SYNC_RESPONSE':
            # Handle offset calculation
            master_send_time = message.get('master_send_time')
            pi_receive_time = message.get('pi_receive_time')
            master_receive_time = time.time()
            round_trip = master_receive_time - master_send_time
            offset = (master_send_time - pi_receive_time) + (round_trip / 2.0)
            # Store offset temporarily
            if 'offset_measurements' not in self.camera_status[ip]:
                self.camera_status[ip]['offset_measurements'] = []
            self.camera_status[ip]['offset_measurements'].append(offset)
        elif task == 'ERROR':
            error_msg = message.get('message', 'Unknown error.')
            self.log_event(f'Error from {ip}: {error_msg}')
        else:
            self.log_event(f'Unknown task from {ip}: {task}')

    def update_status_tree(self, ip):
        camera = next((c for c in self.cameras if c['ip'] == ip), None)
        if camera:
            name = camera['name']
        else:
            name = 'Unknown'

        status = self.camera_status.get(ip, {})
        state = status.get('state', 'Unknown')
        last_seen = status.get('last_seen', 0)
        last_seen_str = time.strftime('%H:%M:%S', time.localtime(last_seen)) if last_seen else 'N/A'
        storage = status.get('storage_remaining_mb', 'N/A')
        sessions = ', '.join(status.get('sessions', []))

        # Check if camera already exists in the tree
        found = False
        for item in self.sessions_tree.get_children():
            values = self.sessions_tree.item(item, 'values')
            if values[1] == ip:
                self.sessions_tree.item(item, values=(name, ip, state, last_seen_str, storage, sessions))
                found = True
                break
        if not found:
            self.sessions_tree.insert('', 'end', values=(name, ip, state, last_seen_str, storage, sessions))

    def send_message(self, ip, message_dict):
        identity = self.ip_to_identity.get(ip)
        if identity:
            try:
                self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])
                self.log_event(f"Sent message to {ip}: {message_dict}")
            except Exception as e:
                self.log_event(f'Failed to send message to {ip}: {e}')

    def broadcast_message(self, message_dict):
        for ip in self.ip_to_identity:
            self.send_message(ip, message_dict)

    def calculate_checksum(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def start_recording(self):
        session_name = self.session_entry.get()
        bitrate = self.bitrate_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        if not bitrate.isdigit():
            messagebox.showerror('Error', 'Bitrate must be a number.')
            return
        # Offset calculation phase
        self.log_event('Calculating offsets...')
        for ip in self.ip_to_identity:
            self.camera_status[ip]['offset_measurements'] = []
        # Perform multiple measurements
        for _ in range(5):
            for ip in self.ip_to_identity:
                req_time = time.time()
                msg = {
                    'task': 'SYNC_REQUEST',
                    'master_send_time': req_time
                }
                self.send_message(ip, msg)
            time.sleep(0.3)
        # Compute final offsets
        offsets = {}
        for ip in self.ip_to_identity:
            measurements = self.camera_status[ip].get('offset_measurements', [])
            if measurements:
                offsets[ip] = statistics.mean(measurements)
            else:
                offsets[ip] = 0.0
        # Choose a future start time
        start_time = time.time() + 5
        for ip in self.ip_to_identity:
            local_start = start_time - offsets[ip]
            message = {
                'task': 'REC_START',
                'session_name': session_name,
                'bitrate': bitrate,
                'start_time': local_start
            }
            self.send_message(ip, message)
        self.log_event('Sent REC_START command with offset compensation.')

    def stop_recording(self):
        for ip in self.ip_to_identity:
            message = {'task': 'REC_STOP'}
            self.send_message(ip, message)
        self.log_event('Sent REC_STOP command.')

    def capture_stills(self):
        session_name = self.session_entry.get()
        compression_format = self.compression_format_var.get()
        compression = self.compression_entry.get()
        still_name = self.still_name_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        if not still_name:
            messagebox.showerror('Error', 'Please enter a still base name.')
            return
        if not compression.isdigit():
            messagebox.showerror('Error', 'Compression must be a number.')
            return
        # Offset calculation for still capture
        self.log_event('Calculating offsets for still capture...')
        for ip in self.ip_to_identity:
            self.camera_status[ip]['offset_measurements'] = []
        for _ in range(5):
            for ip in self.ip_to_identity:
                req_time = time.time()
                msg = {
                    'task': 'SYNC_REQUEST',
                    'master_send_time': req_time
                }
                self.send_message(ip, msg)
            time.sleep(0.3)
        offsets = {}
        for ip in self.ip_to_identity:
            measurements = self.camera_status[ip].get('offset_measurements', [])
            if measurements:
                offsets[ip] = statistics.mean(measurements)
            else:
                offsets[ip] = 0.0
        # Choose a future capture time
        capture_time = time.time() + 5
        for ip in self.ip_to_identity:
            local_cap = capture_time - offsets[ip]
            message = {
                'task': 'REC_STILL',
                'session_name': session_name,
                'compression_format': compression_format,
                'compression': compression,
                'still_name': still_name,
                'start_time': local_cap
            }
            self.send_message(ip, message)
        self.log_event('Sent REC_STILL command with offset compensation.')

    def get_sessions(self):
        threading.Thread(target=self.get_sessions_thread, daemon=True).start()

    def get_sessions_thread(self):
        self.sessions = []
        self.session_info = {}

        all_sessions = set()
        for cam in self.cameras:
            ip = cam['ip']
            sessions = self.query_sessions(ip)
            for s in sessions:
                all_sessions.add(s)

        self.sessions = sorted(all_sessions)

        for session_name in self.sessions:
            self.session_info[session_name] = {
                "clip_sizes": {},
            }
            for cam in self.cameras:
                info = self.query_session_info(cam['ip'], session_name)
                self.session_info[session_name]["clip_sizes"][cam['name']] = info

        self.update_sessions_tree()

    def query_sessions(self, ip):
        request = {"task": "GET_SESSIONS"}
        sessions = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((ip, TCP_DOWNLOAD_PORT))
                sock.sendall(json.dumps(request).encode())
                # Receive JSON response length (8 bytes)
                length_data = self.recvall(sock, 8)
                if not length_data or len(length_data) < 8:
                    raise Exception("Failed to read JSON length from server.")
                (msg_length,) = struct.unpack('!Q', length_data)

                # Receive JSON response
                json_data = self.recvall(sock, msg_length)
                if len(json_data) < msg_length:
                    raise Exception("Incomplete JSON response from server.")

                response = json.loads(json_data.decode())
                sessions = response.get('sessions', [])
                logging.info(f"Received sessions from {ip}: {sessions}")
        except Exception as e:
            logging.error(f"Failed to get sessions from {ip}: {e}")
        return sessions

    def query_session_info(self, ip, session_name):
        request = {"task": "GET_SESSION_INFO", "session_name": session_name}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((ip, TCP_DOWNLOAD_PORT))
                sock.sendall(json.dumps(request).encode())
                # Receive JSON response length (8 bytes)
                length_data = self.recvall(sock, 8)
                if not length_data or len(length_data) < 8:
                    raise Exception("Failed to read JSON length from server.")
                (msg_length,) = struct.unpack('!Q', length_data)

                # Receive JSON response
                json_data = self.recvall(sock, msg_length)
                if len(json_data) < msg_length:
                    raise Exception("Incomplete JSON response from server.")

                response = json.loads(json_data.decode())
                if response.get('status') == 'OK':
                    return response.get('file_size', None)
                else:
                    return None
        except Exception as e:
            logging.error(f"Failed to get session info from {ip} for {session_name}: {e}")
            return None

    def update_sessions_tree(self):
        def update():
            for i in self.sessions_tree.get_children():
                self.sessions_tree.delete(i)

            for session_name in self.sessions:
                clip_sizes = self.session_info[session_name]["clip_sizes"]
                found_sizes = [sz for sz in clip_sizes.values() if sz is not None]

                if found_sizes:
                    first_found_size = found_sizes[0]
                    session_size = sum(found_sizes)
                else:
                    first_found_size = 0
                    session_size = 0

                not_found_cams = [cam_name for cam_name, sz in clip_sizes.items() if sz is None]
                not_found_str = ", ".join(not_found_cams) if not_found_cams else ""

                # Determine Status
                status = self.determine_session_status(session_name, clip_sizes)

                # Convert sizes to a human-readable format
                readable_first_size = self.convert_size(first_found_size)
                readable_session_size = self.convert_size(session_size)

                self.sessions_tree.insert("", "end", values=(
                    session_name,
                    readable_first_size,
                    readable_session_size,
                    not_found_str,
                    status
                ))
        self.root.after(0, update)

    def determine_session_status(self, session_name, clip_sizes):
        session_folder = os.path.join(SESSIONS_DIR, session_name)
        cameras_with_clips = [(cam, sz) for cam, sz in clip_sizes.items() if sz is not None]

        if not os.path.exists(session_folder):
            return "Remote"

        available_count = 0
        expected_count = len(cameras_with_clips)
        for cam, sz in cameras_with_clips:
            ip = next((c['ip'] for c in self.cameras if c['name'] == cam), None)
            if not ip:
                continue
            suffix = '_' + ip.split('.')[-1]
            file_name = f"{session_name}{suffix}.h264"
            file_path = os.path.join(session_folder, file_name)
            if os.path.exists(file_path) and os.path.getsize(file_path) == sz:
                available_count += 1

        if available_count == 0:
            return "Remote"
        elif available_count < expected_count:
            return "Local (Incomplete)"
        else:
            return "Local"

    def download_session(self):
        selection = self.sessions_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.sessions_tree.item(session_item, "values")
        session_name = session_values[0]
        threading.Thread(target=self.download_session_thread, args=(session_name,), daemon=True).start()

    def download_session_thread(self, session_name):
        self.current_downloading_session = session_name
        self.update_current_session_label()

        clip_sizes = self.session_info[session_name]["clip_sizes"]
        cameras_with_session = [(cam['name'], cam['ip'], sz) for cam in self.cameras if (sz := clip_sizes.get(cam['name'], None)) is not None]

        if not cameras_with_session:
            messagebox.showerror("Error", f"No Raspberry Pis have the session '{session_name}'.")
            self.current_downloading_session = None
            self.update_current_session_label()
            return

        session_folder = os.path.join(SESSIONS_DIR, session_name)
        os.makedirs(session_folder, exist_ok=True)

        total_bytes = sum(sz for _, _, sz in cameras_with_session)
        total_received = 0
        overall_start_time = time.time()

        self.update_overall_progress(0, overall_start_time, total_received, total_bytes)

        for cam_name, ip, file_size in cameras_with_session:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)
                    request = {'task': 'DOWNLOAD_SESSION', 'session_name': session_name}
                    sock.connect((ip, TCP_DOWNLOAD_PORT))
                    sock.sendall(json.dumps(request).encode())

                    # Receive JSON response length (8 bytes)
                    length_data = self.recvall(sock, 8)
                    if not length_data or len(length_data) < 8:
                        raise Exception("Failed to read JSON length from server.")
                    (msg_length,) = struct.unpack('!Q', length_data)

                    # Receive JSON response
                    json_data = self.recvall(sock, msg_length)
                    if len(json_data) < msg_length:
                        raise Exception("Incomplete JSON response from server.")

                    response = json.loads(json_data.decode())

                    if response.get('status') != 'OK':
                        error_message = response.get('message', 'Unknown error.')
                        messagebox.showerror("Error", f"From {ip}: {error_message}")
                        continue

                    suffix = '_' + ip.split('.')[-1]
                    file_name = f"{session_name}{suffix}.h264"
                    file_path = os.path.join(session_folder, file_name)

                    self.update_current_file_info(ip, file_name)

                    bytes_received = 0
                    start_time = time.time()
                    with open(file_path, 'wb') as f:
                        while bytes_received < file_size:
                            data = sock.recv(4096)
                            if not data:
                                break
                            f.write(data)
                            bytes_received += len(data)
                            total_received += len(data)
                            self.update_current_progress(bytes_received, file_size, start_time)
                            self.update_overall_progress((total_received / total_bytes) * 100, overall_start_time, total_received, total_bytes)

                    if bytes_received < file_size:
                        raise Exception("Connection lost during file transfer.")
                    self.log_event(f"Downloaded session {session_name} from {ip} successfully.")
            except Exception as e:
                self.log_event(f"Failed to download session from {ip}: {e}")
                messagebox.showerror("Error", f"Failed to download session from {ip}: {e}")

        self.update_current_file_info("N/A", "N/A")
        self.update_current_progress(0, 1, 0)
        self.update_overall_progress(100, overall_start_time, total_received, total_bytes)
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully from all available Raspberry Pis.")

        self.current_downloading_session = None
        self.update_current_session_label()
        self.get_sessions()

    def delete_session_local(self):
        selection = self.sessions_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.sessions_tree.item(session_item, "values")
        session_name = session_values[0]

        confirm = messagebox.askyesno("Delete Session (Local)", f"Are you sure you want to delete the session '{session_name}' locally?")
        if confirm:
            session_folder = os.path.join(SESSIONS_DIR, session_name)
            if os.path.exists(session_folder):
                try:
                    for root_dir, dirs, files in os.walk(session_folder, topdown=False):
                        for file in files:
                            os.remove(os.path.join(root_dir, file))
                        for d in dirs:
                            os.rmdir(os.path.join(root_dir, d))
                    os.rmdir(session_folder)
                    messagebox.showinfo("Info", f"Session '{session_name}' deleted locally.")
                except Exception as e:
                    logging.error(f"Failed to delete session '{session_name}' locally: {e}")
                    messagebox.showerror("Error", f"Failed to delete session '{session_name}' locally: {e}")
            else:
                messagebox.showinfo("Info", f"Session '{session_name}' not found locally.")
            self.get_sessions()

    def delete_session_remote(self, session_name=None):
        selection = self.sessions_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.sessions_tree.item(session_item, "values")
        session_name = session_values[0]

        confirm = messagebox.askyesno("Delete Session (Remote)", f"Are you sure you want to delete the session '{session_name}' on all Raspberry Pis?")
        if confirm:
            threading.Thread(target=self.delete_session_remote_thread, args=(session_name,), daemon=True).start()

    def delete_session_remote_thread(self, session_name):
        cameras_with_session = [cam for cam in self.cameras if self.session_info.get(session_name, {}).get("clip_sizes", {}).get(cam['name'], None) is not None]

        if not cameras_with_session:
            messagebox.showinfo("Info", f"No Raspberry Pis have the session '{session_name}'.")
            return

        delete_results = {}
        for cam in cameras_with_session:
            cam_name = cam['name']
            ip = cam['ip']
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)
                    request = {"task": "DELETE_SESSION", "session_name": session_name}
                    sock.connect((ip, TCP_DOWNLOAD_PORT))
                    sock.sendall(json.dumps(request).encode())

                    # Receive JSON response length (8 bytes)
                    length_data = self.recvall(sock, 8)
                    if not length_data or len(length_data) < 8:
                        raise Exception("Failed to read JSON length from server.")
                    (msg_length,) = struct.unpack('!Q', length_data)

                    # Receive JSON response
                    json_data = self.recvall(sock, msg_length)
                    if len(json_data) < msg_length:
                        raise Exception("Incomplete JSON response from server.")

                    response = json.loads(json_data.decode())
                    if response.get('status') == 'OK':
                        delete_results[cam_name] = (True, "Deleted successfully.")
                    else:
                        delete_results[cam_name] = (False, response.get('message', 'Unknown error.'))
            except Exception as e:
                logging.error(f"Failed to send delete request to {ip}: {e}")
                delete_results[cam_name] = (False, str(e))

        # Prepare summary message
        success_cams = [cam for cam, res in delete_results.items() if res[0]]
        failed_cams = [f"{cam} ({msg})" for cam, res in delete_results.items() if not res[0] for msg in [res[1]]]

        if success_cams:
            message = f"Successfully deleted session '{session_name}' on the following cameras:\n" + ", ".join(success_cams)
            messagebox.showinfo("Success", message)

        if failed_cams:
            message = f"Failed to delete session '{session_name}' on the following cameras:\n" + ", ".join(failed_cams)
            messagebox.showerror("Error", message)

        # Refresh the session list after deletion
        self.get_sessions()

    def open_local_sessions_folder(self):
        # Open the local sessions folder in the file explorer
        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR, exist_ok=True)
        try:
            if os.name == 'nt':  # Windows
                os.startfile(os.path.abspath(SESSIONS_DIR))
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(["open", os.path.abspath(SESSIONS_DIR)])
            else:  # Linux and others
                subprocess.Popen(["xdg-open", os.path.abspath(SESSIONS_DIR)])
        except Exception as e:
            logging.error(f"Failed to open sessions folder: {e}")
            messagebox.showerror("Error", f"Failed to open sessions folder: {e}")

    def update_current_file_info(self, ip, file_name):
        def update():
            self.current_file_label.config(text=f"IP: {ip}, File: {file_name}")
        self.root.after(0, update)

    def update_current_session_label(self):
        def update():
            if hasattr(self, 'current_downloading_session') and self.current_downloading_session:
                self.current_file_label.config(text=f"Current Session: {self.current_downloading_session}")
            else:
                self.current_file_label.config(text="Current Session: N/A")
        self.root.after(0, update)

    def update_current_progress(self, bytes_received, file_size, start_time):
        percentage = bytes_received / file_size * 100 if file_size > 0 else 0
        elapsed_time = time.time() - start_time
        speed = bytes_received / elapsed_time if elapsed_time > 0 else 0
        eta = (file_size - bytes_received) / speed if speed > 0 else float('inf')
        eta_formatted = self.format_eta(eta)

        def update():
            self.current_progress['value'] = percentage
            self.current_eta_label.config(text=f"ETA: {eta_formatted}")
        self.root.after(0, update)

    def update_overall_progress(self, percentage, start_time, total_received, total_bytes):
        if start_time is None or percentage == 0:
            eta_formatted = "Calculating..."
        else:
            elapsed_time = time.time() - start_time
            speed = total_received / elapsed_time if elapsed_time > 0 else 0
            remaining = total_bytes - total_received
            eta = remaining / speed if speed > 0 else float('inf')
            eta_formatted = self.format_eta(eta)

        def update():
            self.overall_progress['value'] = percentage
            self.overall_eta_label.config(text=f"ETA: {eta_formatted}")
        self.root.after(0, update)

    def format_eta(self, eta_seconds):
        if eta_seconds == float('inf') or eta_seconds < 0:
            return "Calculating..."
        minutes, seconds = divmod(int(eta_seconds), 60)
        return f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    def convert_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def send_message(self, ip, message_dict):
        identity = self.ip_to_identity.get(ip)
        if identity:
            try:
                self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])
                self.log_event(f"Sent message to {ip}: {message_dict}")
            except Exception as e:
                self.log_event(f'Failed to send message to {ip}: {e}')

    def broadcast_message(self, message_dict):
        for ip in self.ip_to_identity:
            self.send_message(ip, message_dict)

    def get_sessions(self):
        threading.Thread(target=self.get_sessions_thread, daemon=True).start()

    def get_sessions_thread(self):
        self.sessions = []
        self.session_info = {}

        all_sessions = set()
        for cam in self.cameras:
            ip = cam['ip']
            sessions = self.query_sessions(ip)
            for s in sessions:
                all_sessions.add(s)

        self.sessions = sorted(all_sessions)

        for session_name in self.sessions:
            self.session_info[session_name] = {
                "clip_sizes": {},
            }
            for cam in self.cameras:
                info = self.query_session_info(cam['ip'], session_name)
                self.session_info[session_name]["clip_sizes"][cam['name']] = info

        self.update_sessions_tree()

    def query_sessions(self, ip):
        request = {"task": "GET_SESSIONS"}
        sessions = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((ip, TCP_DOWNLOAD_PORT))
                sock.sendall(json.dumps(request).encode())
                # Receive JSON response length (8 bytes)
                length_data = self.recvall(sock, 8)
                if not length_data or len(length_data) < 8:
                    raise Exception("Failed to read JSON length from server.")
                (msg_length,) = struct.unpack('!Q', length_data)

                # Receive JSON response
                json_data = self.recvall(sock, msg_length)
                if len(json_data) < msg_length:
                    raise Exception("Incomplete JSON response from server.")

                response = json.loads(json_data.decode())
                sessions = response.get('sessions', [])
                logging.info(f"Received sessions from {ip}: {sessions}")
        except Exception as e:
            logging.error(f"Failed to get sessions from {ip}: {e}")
        return sessions

    def query_session_info(self, ip, session_name):
        request = {"task": "GET_SESSION_INFO", "session_name": session_name}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((ip, TCP_DOWNLOAD_PORT))
                sock.sendall(json.dumps(request).encode())
                # Receive JSON response length (8 bytes)
                length_data = self.recvall(sock, 8)
                if not length_data or len(length_data) < 8:
                    raise Exception("Failed to read JSON length from server.")
                (msg_length,) = struct.unpack('!Q', length_data)

                # Receive JSON response
                json_data = self.recvall(sock, msg_length)
                if len(json_data) < msg_length:
                    raise Exception("Incomplete JSON response from server.")

                response = json.loads(json_data.decode())
                if response.get('status') == 'OK':
                    return response.get('file_size', None)
                else:
                    return None
        except Exception as e:
            logging.error(f"Failed to get session info from {ip} for {session_name}: {e}")
            return None

    def update_sessions_tree(self):
        def update():
            for i in self.sessions_tree.get_children():
                self.sessions_tree.delete(i)

            for session_name in self.sessions:
                clip_sizes = self.session_info[session_name]["clip_sizes"]
                found_sizes = [sz for sz in clip_sizes.values() if sz is not None]

                if found_sizes:
                    first_found_size = found_sizes[0]
                    session_size = sum(found_sizes)
                else:
                    first_found_size = 0
                    session_size = 0

                not_found_cams = [cam_name for cam_name, sz in clip_sizes.items() if sz is None]
                not_found_str = ", ".join(not_found_cams) if not_found_cams else ""

                # Determine Status
                status = self.determine_session_status(session_name, clip_sizes)

                # Convert sizes to a human-readable format
                readable_first_size = self.convert_size(first_found_size)
                readable_session_size = self.convert_size(session_size)

                self.sessions_tree.insert("", "end", values=(
                    session_name,
                    readable_first_size,
                    readable_session_size,
                    not_found_str,
                    status
                ))
        self.root.after(0, update)

    def determine_session_status(self, session_name, clip_sizes):
        session_folder = os.path.join(SESSIONS_DIR, session_name)
        cameras_with_clips = [(cam, sz) for cam, sz in clip_sizes.items() if sz is not None]

        if not os.path.exists(session_folder):
            return "Remote"

        available_count = 0
        expected_count = len(cameras_with_clips)
        for cam, sz in cameras_with_clips:
            ip = next((c['ip'] for c in self.cameras if c['name'] == cam), None)
            if not ip:
                continue
            suffix = '_' + ip.split('.')[-1]
            file_name = f"{session_name}{suffix}.h264"
            file_path = os.path.join(session_folder, file_name)
            if os.path.exists(file_path) and os.path.getsize(file_path) == sz:
                available_count += 1

        if available_count == 0:
            return "Remote"
        elif available_count < expected_count:
            return "Local (Incomplete)"
        else:
            return "Local"

    def download_session_thread(self, session_name):
        self.current_downloading_session = session_name
        self.update_current_session_label()

        clip_sizes = self.session_info[session_name]["clip_sizes"]
        cameras_with_session = [(cam['name'], cam['ip'], sz) for cam in self.cameras if (sz := clip_sizes.get(cam['name'], None)) is not None]

        if not cameras_with_session:
            messagebox.showerror("Error", f"No Raspberry Pis have the session '{session_name}'.")
            self.current_downloading_session = None
            self.update_current_session_label()
            return

        session_folder = os.path.join(SESSIONS_DIR, session_name)
        os.makedirs(session_folder, exist_ok=True)

        total_bytes = sum(sz for _, _, sz in cameras_with_session)
        total_received = 0
        overall_start_time = time.time()

        self.update_overall_progress(0, overall_start_time, total_received, total_bytes)

        for cam_name, ip, file_size in cameras_with_session:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)
                    request = {'task': 'DOWNLOAD_SESSION', 'session_name': session_name}
                    sock.connect((ip, TCP_DOWNLOAD_PORT))
                    sock.sendall(json.dumps(request).encode())

                    # Receive JSON response length (8 bytes)
                    length_data = self.recvall(sock, 8)
                    if not length_data or len(length_data) < 8:
                        raise Exception("Failed to read JSON length from server.")
                    (msg_length,) = struct.unpack('!Q', length_data)

                    # Receive JSON response
                    json_data = self.recvall(sock, msg_length)
                    if len(json_data) < msg_length:
                        raise Exception("Incomplete JSON response from server.")

                    response = json.loads(json_data.decode())

                    if response.get('status') != 'OK':
                        error_message = response.get('message', 'Unknown error.')
                        messagebox.showerror("Error", f"From {ip}: {error_message}")
                        continue

                    suffix = '_' + ip.split('.')[-1]
                    file_name = f"{session_name}{suffix}.h264"
                    file_path = os.path.join(session_folder, file_name)

                    self.update_current_file_info(ip, file_name)

                    bytes_received = 0
                    start_time = time.time()
                    with open(file_path, 'wb') as f:
                        while bytes_received < file_size:
                            data = sock.recv(4096)
                            if not data:
                                break
                            f.write(data)
                            bytes_received += len(data)
                            total_received += len(data)
                            self.update_current_progress(bytes_received, file_size, start_time)
                            self.update_overall_progress((total_received / total_bytes) * 100, overall_start_time, total_received, total_bytes)

                    if bytes_received < file_size:
                        raise Exception("Connection lost during file transfer.")
                    self.log_event(f"Downloaded session {session_name} from {ip} successfully.")
            except Exception as e:
                self.log_event(f"Failed to download session from {ip}: {e}")
                messagebox.showerror("Error", f"Failed to download session from {ip}: {e}")

        self.update_current_file_info("N/A", "N/A")
        self.update_current_progress(0, 1, 0)
        self.update_overall_progress(100, overall_start_time, total_received, total_bytes)
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully from all available Raspberry Pis.")

        self.current_downloading_session = None
        self.update_current_session_label()
        self.get_sessions()

    def delete_session_local(self):
        selection = self.sessions_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.sessions_tree.item(session_item, "values")
        session_name = session_values[0]

        confirm = messagebox.askyesno("Delete Session (Local)", f"Are you sure you want to delete the session '{session_name}' locally?")
        if confirm:
            session_folder = os.path.join(SESSIONS_DIR, session_name)
            if os.path.exists(session_folder):
                try:
                    for root_dir, dirs, files in os.walk(session_folder, topdown=False):
                        for file in files:
                            os.remove(os.path.join(root_dir, file))
                        for d in dirs:
                            os.rmdir(os.path.join(root_dir, d))
                    os.rmdir(session_folder)
                    messagebox.showinfo("Info", f"Session '{session_name}' deleted locally.")
                except Exception as e:
                    logging.error(f"Failed to delete session '{session_name}' locally: {e}")
                    messagebox.showerror("Error", f"Failed to delete session '{session_name}' locally: {e}")
            else:
                messagebox.showinfo("Info", f"Session '{session_name}' not found locally.")
            self.get_sessions()

    def delete_session_remote(self, session_name=None):
        selection = self.sessions_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.sessions_tree.item(session_item, "values")
        session_name = session_values[0]

        confirm = messagebox.askyesno("Delete Session (Remote)", f"Are you sure you want to delete the session '{session_name}' on all Raspberry Pis?")
        if confirm:
            threading.Thread(target=self.delete_session_remote_thread, args=(session_name,), daemon=True).start()

    def delete_session_remote_thread(self, session_name):
        cameras_with_session = [cam for cam in self.cameras if self.session_info.get(session_name, {}).get("clip_sizes", {}).get(cam['name'], None) is not None]

        if not cameras_with_session:
            messagebox.showinfo("Info", f"No Raspberry Pis have the session '{session_name}'.")
            return

        delete_results = {}
        for cam in cameras_with_session:
            cam_name = cam['name']
            ip = cam['ip']
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)
                    request = {"task": "DELETE_SESSION", "session_name": session_name}
                    sock.connect((ip, TCP_DOWNLOAD_PORT))
                    sock.sendall(json.dumps(request).encode())

                    # Receive JSON response length (8 bytes)
                    length_data = self.recvall(sock, 8)
                    if not length_data or len(length_data) < 8:
                        raise Exception("Failed to read JSON length from server.")
                    (msg_length,) = struct.unpack('!Q', length_data)

                    # Receive JSON response
                    json_data = self.recvall(sock, msg_length)
                    if len(json_data) < msg_length:
                        raise Exception("Incomplete JSON response from server.")

                    response = json.loads(json_data.decode())
                    if response.get('status') == 'OK':
                        delete_results[cam_name] = (True, "Deleted successfully.")
                    else:
                        delete_results[cam_name] = (False, response.get('message', 'Unknown error.'))
            except Exception as e:
                logging.error(f"Failed to send delete request to {ip}: {e}")
                delete_results[cam_name] = (False, str(e))

        # Prepare summary message
        success_cams = [cam for cam, res in delete_results.items() if res[0]]
        failed_cams = [f"{cam} ({msg})" for cam, res in delete_results.items() if not res[0] for msg in [res[1]]]

        if success_cams:
            message = f"Successfully deleted session '{session_name}' on the following cameras:\n" + ", ".join(success_cams)
            messagebox.showinfo("Success", message)

        if failed_cams:
            message = f"Failed to delete session '{session_name}' on the following cameras:\n" + ", ".join(failed_cams)
            messagebox.showerror("Error", message)

        # Refresh the session list after deletion
        self.get_sessions()

    def open_local_sessions_folder(self):
        # Open the local sessions folder in the file explorer
        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR, exist_ok=True)
        try:
            if os.name == 'nt':  # Windows
                os.startfile(os.path.abspath(SESSIONS_DIR))
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(["open", os.path.abspath(SESSIONS_DIR)])
            else:  # Linux and others
                subprocess.Popen(["xdg-open", os.path.abspath(SESSIONS_DIR)])
        except Exception as e:
            logging.error(f"Failed to open sessions folder: {e}")
            messagebox.showerror("Error", f"Failed to open sessions folder: {e}")

    def recvall(self, sock, n):
        """Receive exactly n bytes or fewer if EOF is encountered."""
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                break
            data += packet
        return data

    def update_current_file_info(self, ip, file_name):
        def update():
            self.current_file_label.config(text=f"IP: {ip}, File: {file_name}")
        self.root.after(0, update)

    def update_current_session_label(self):
        def update():
            if hasattr(self, 'current_downloading_session') and self.current_downloading_session:
                self.current_file_label.config(text=f"Current Session: {self.current_downloading_session}")
            else:
                self.current_file_label.config(text="Current Session: N/A")
        self.root.after(0, update)

    def update_current_progress(self, bytes_received, file_size, start_time):
        percentage = bytes_received / file_size * 100 if file_size > 0 else 0
        elapsed_time = time.time() - start_time
        speed = bytes_received / elapsed_time if elapsed_time > 0 else 0
        eta = (file_size - bytes_received) / speed if speed > 0 else float('inf')
        eta_formatted = self.format_eta(eta)

        def update():
            self.current_progress['value'] = percentage
            self.current_eta_label.config(text=f"ETA: {eta_formatted}")
        self.root.after(0, update)

    def update_overall_progress(self, percentage, start_time, total_received, total_bytes):
        if start_time is None or percentage == 0:
            eta_formatted = "Calculating..."
        else:
            elapsed_time = time.time() - start_time
            speed = total_received / elapsed_time if elapsed_time > 0 else 0
            remaining = total_bytes - total_received
            eta = remaining / speed if speed > 0 else float('inf')
            eta_formatted = self.format_eta(eta)

        def update():
            self.overall_progress['value'] = percentage
            self.overall_eta_label.config(text=f"ETA: {eta_formatted}")
        self.root.after(0, update)

    def format_eta(self, eta_seconds):
        if eta_seconds == float('inf') or eta_seconds < 0:
            return "Calculating..."
        minutes, seconds = divmod(int(eta_seconds), 60)
        return f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    def convert_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def run(self):
        self.root.mainloop()

    def on_close(self):
        self.running = False
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    app.run()
