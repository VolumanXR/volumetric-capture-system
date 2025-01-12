# master_controller.py v0.9

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import os
import hashlib
import zmq
import uuid
import statistics
from pathlib import Path
import socket

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent, 'utils', 'camera_list.json')
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'
MASTER_PC_IP = '0.0.0.0'  # For ZMQ or TCP server to bind to all interfaces
MASTER_PC_PORT = 50005

LASTIME = None
NO_RESPONSE_TIMEOUT = 2.0  # If no status in 2 seconds, show "NO RESPONSE"

CONNECTION_MODES = ["ZMQ", "TCP", "UDP"]

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
        self.text.config(state='normal')
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

        self.cameras = []         # Loaded from camera_list.json
        self.camera_status = {}   # ip -> { 'state', 'last_seen', 'storage_remaining_mb', 'sessions', ... }

        # Track the chosen communication mode
        self.connection_mode = tk.StringVar(value=CONNECTION_MODES[0])  # Default is "ZMQ"

        self.load_camera_list()

        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR)

        # ZMQ setup
        self.context = zmq.Context()
        self.router_socket = self.context.socket(zmq.ROUTER)
        self.router_socket.bind(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
        self.poller = zmq.Poller()
        self.poller.register(self.router_socket, zmq.POLLIN)

        # identity -> ip mapping (used in ZMQ mode)
        self.connected_cameras = {}
        # reverse: ip -> identity mapping (used in ZMQ mode)
        self.ip_to_identity = {}

        # Build the UI
        self.create_widgets()

        # Initialize status for all cameras to "NO RESPONSE" so they appear immediately
        for cam in self.cameras:
            ip = cam['ip']
            self.camera_status[ip] = {
                'state': 'NO RESPONSE',
                'last_seen': 0,
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }

        # Start the background threads
        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_loop_zmq, daemon=True)
        self.receive_thread.start()

        # Periodic check for "NO RESPONSE"
        self.status_check_thread = threading.Thread(target=self.periodic_status_check, daemon=True)
        self.status_check_thread.start()

    def load_camera_list(self):
        with open(CAMERA_LIST_FILE, 'r') as f:
            self.cameras = json.load(f)
            # Remove 'port' usage if present
            for c in self.cameras:
                if 'port' in c:
                    del c['port']

    def create_widgets(self):
        # Session Frame
        session_frame = ttk.LabelFrame(self.root, text='Session Control')
        session_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(session_frame, text='Session Name:').grid(row=0, column=0, padx=5, pady=5)
        self.session_entry = ttk.Entry(session_frame)
        self.session_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(session_frame, text='Bitrate (Kbps):').grid(row=1, column=0, padx=5, pady=5)
        self.bitrate_entry = ttk.Entry(session_frame)
        self.bitrate_entry.insert(0, '15000')
        self.bitrate_entry.grid(row=1, column=1, padx=5, pady=5)

        start_button = ttk.Button(session_frame, text='Start Recording', command=self.start_recording)
        start_button.grid(row=2, column=0, padx=5, pady=5)

        stop_button = ttk.Button(session_frame, text='Stop Recording', command=self.stop_recording)
        stop_button.grid(row=2, column=1, padx=5, pady=5)

        # Still Frame
        still_frame = ttk.LabelFrame(self.root, text='Still Image Control')
        still_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(still_frame, text='Session Name for Still:').grid(row=0, column=0, padx=5, pady=5)
        self.still_name_entry = ttk.Entry(still_frame)
        self.still_name_entry.grid(row=0, column=1, padx=5, pady=5)

        capture_button = ttk.Button(still_frame, text='Capture Still Image', command=self.capture_stills)
        capture_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5)

        # Comm Mode Frame
        comm_frame = ttk.LabelFrame(self.root, text='Communication Mode')
        comm_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(comm_frame, text='Select Mode: ').grid(row=0, column=0, padx=5, pady=5, sticky='e')
        mode_dropdown = ttk.OptionMenu(
            comm_frame, 
            self.connection_mode, 
            CONNECTION_MODES[0], 
            *CONNECTION_MODES
        )
        mode_dropdown.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        # The self.connection_mode variable will hold "ZMQ", "TCP", or "UDP"

        # Camera Status Frame
        status_frame = ttk.LabelFrame(self.root, text='Camera Status')
        status_frame.pack(fill='both', expand=True, padx=5, pady=5)

        columns = ('Name', 'IP', 'State', 'Last Seen', 'Storage Remaining (MB)', 'Sessions')
        self.status_tree = ttk.Treeview(status_frame, columns=columns, show='headings')
        for col in columns:
            self.status_tree.heading(col, text=col, command=lambda c=col: self.sort_by_column(c))
            # ^ adding a command to allow sorting when column header clicked
        self.status_tree.pack(side='left', fill='both', expand=True)

        # Add a scrollbar
        scroll_y = ttk.Scrollbar(status_frame, orient='vertical', command=self.status_tree.yview)
        self.status_tree.configure(yscrollcommand=scroll_y.set)
        scroll_y.pack(side='right', fill='y')

        # Control Frame with debug + connected label
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=5, pady=5)

        debug_button = ttk.Button(control_frame, text='Toggle Debug Mode', command=self.toggle_debug)
        debug_button.grid(row=0, column=0, padx=5, pady=5)

        self.connected_label = ttk.Label(control_frame, text='Connected 0 / 0')
        self.connected_label.grid(row=0, column=1, padx=5, pady=5)

    def toggle_debug(self):
        if self.debug_window:
            self.debug_window.destroy()
            self.debug_window = None
            self.debug_mode = False
        else:
            self.debug_window = DebugWindow(self.root)
            self.debug_mode = True

    def log_event(self, message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(EVENT_LOG, 'a') as log_file:
            log_file.write(f'[{timestamp}] {message}\n')
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message('MASTER', message)

    def periodic_status_check(self):
        """Periodically checks each camera's 'last_seen' time. If older than
        NO_RESPONSE_TIMEOUT seconds, set state to 'NO RESPONSE'."""
        global LASTIME
        while self.running:
            # Execute about once per second
            time.sleep(1)
            current_time = time.time()
            for ip, status in self.camera_status.items():
                last_seen = status.get('last_seen', 0)
                if (current_time - last_seen) > NO_RESPONSE_TIMEOUT:
                    if status['state'] != 'NO RESPONSE':
                        self.camera_status[ip]['state'] = 'NO RESPONSE'
                        self.update_status_tree(ip)

            # Update the "connected X / Y" label
            # Count how many are not "NO RESPONSE"
            total_cameras = len(self.cameras)
            alive = sum(1 for ip, st in self.camera_status.items() if st['state'] != 'NO RESPONSE')
            self.update_connected_label(alive, total_cameras)

    def update_connected_label(self, connected, total):
        def _update():
            self.connected_label.config(text=f'Connected {connected} / {total}')
        self.root.after(0, _update)

    # Sorting logic
    def sort_by_column(self, column_name):
        """
        Sort the TreeView rows based on the selected column.
        We'll detect the column index from the columns tuple.
        """
        columns = ('Name', 'IP', 'State', 'Last Seen', 'Storage Remaining (MB)', 'Sessions')
        col_index = columns.index(column_name)

        # Get all rows
        rows = list(self.status_tree.get_children())
        # Extract the values from each row
        def get_value(item):
            return self.status_tree.item(item, 'values')[col_index]

        # If numeric sort is needed, do a numeric parse, else do string
        if column_name in ["Last Seen", "Storage Remaining (MB)"]:
            # try numeric
            try:
                rows.sort(key=lambda item: float(get_value(item)) if get_value(item).replace('.', '', 1).isdigit() else 0.0)
            except:
                rows.sort(key=lambda item: get_value(item))
        else:
            rows.sort(key=lambda item: get_value(item))

        # Re-insert them
        for item in rows:
            self.status_tree.move(item, '', 'end')

    def receive_loop_zmq(self):
        """Receive loop for ZMQ messages (default mode)."""
        global LASTIME
        while self.running:
            # Only poll if the user has selected ZMQ mode
            if self.connection_mode.get() != "ZMQ":
                # Sleep some to avoid busy loop
                time.sleep(1)
                continue

            socks = dict(self.poller.poll(1000))
            if self.router_socket in socks and socks[self.router_socket] == zmq.POLLIN:
                frames = self.router_socket.recv_multipart()
                identity = frames[0]
                message = json.loads(frames[1].decode())
                self.handle_message_zmq(identity, message)

    def handle_message_zmq(self, identity, message):
        """Handle messages that come in via ZMQ mode."""
        task = message.get('task')
        ip = message.get('ip', 'Unknown')

        # Register camera identity -> IP
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
            self.log_event(f'Camera registered (ZMQ): {ip}')

        elif task == 'STATUS':
            state = message.get('state')
            storage_remaining = message.get('storage_remaining_mb')
            sessions = message.get('sessions', [])
            self.camera_status.setdefault(ip, {})
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

        elif task == 'REC_START_ACK':
            ack_time = message.get('start_time', 0)
            expected_state = self.camera_status[ip].get('pending_start_time', None)
            if expected_state is not None and abs(expected_state - ack_time) < 0.1:
                self.camera_status[ip]['state'] = 'PREPARING'
            else:
                self.camera_status[ip]['state'] = 'SYNC ISSUE'
            self.update_status_tree(ip)

        elif task == 'REC_STILL_ACK':
            ack_time = message.get('start_time', 0)
            expected_still_time = self.camera_status[ip].get('pending_still_time', None)
            if expected_still_time is not None and abs(expected_still_time - ack_time) < 0.1:
                self.camera_status[ip]['state'] = 'PREPARING_STILL'
            else:
                self.camera_status[ip]['state'] = 'SYNC ISSUE'
            self.update_status_tree(ip)

        # Keep track of last_seen
        if ip in self.camera_status:
            self.camera_status[ip]['last_seen'] = time.time()

    def update_status_tree(self, ip):
        """Update or insert a row in the status tree for the given ip."""
        camera = next((c for c in self.cameras if c['ip'] == ip), None)
        if camera:
            name = camera['name']
        else:
            name = 'Unknown'

        status = self.camera_status.get(ip, {})
        state = status.get('state', 'Unknown')
        last_seen = status.get('last_seen', 0)
        last_seen_str = time.strftime('%H:%M:%S', time.localtime(last_seen)) if last_seen > 0 else 'N/A'
        storage = status.get('storage_remaining_mb', 'N/A')
        sessions = ', '.join(status.get('sessions', []))

        found = False
        for item in self.status_tree.get_children():
            values = self.status_tree.item(item, 'values')
            if values[1] == ip:
                self.status_tree.item(item, values=(name, ip, state, last_seen_str, storage, sessions))
                found = True
                break
        if not found:
            self.status_tree.insert('', 'end', values=(name, ip, state, last_seen_str, storage, sessions))

    # The user-chosen connection method will apply to these sending methods:

    def send_message(self, ip, message_dict):
        """Send a message to the camera with the given IP via the selected mode."""
        mode = self.connection_mode.get()
        if mode == "ZMQ":
            self.send_message_zmq(ip, message_dict)
        elif mode == "TCP":
            self.send_message_tcp(ip, message_dict)
        elif mode == "UDP":
            self.send_message_udp(ip, message_dict)
        else:
            self.log_event(f"Unknown send mode {mode}")

    def broadcast_message(self, message_dict):
        """Broadcast to all cameras, depending on mode."""
        for ip in [c['ip'] for c in self.cameras]:
            self.send_message(ip, message_dict)

    def send_message_zmq(self, ip, message_dict):
        """ZMQ-based send."""
        identity = self.ip_to_identity.get(ip)
        if identity:
            self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])

    def send_message_tcp(self, ip, message_dict):
        """
        Example of a simple TCP approach:
        1) Connect to (ip, MASTER_PC_PORT).
        2) Send JSON.
        3) Possibly wait for ack or close.
        NOTE: You would need a corresponding TCP server on each Pi.
        This is a simplistic example with no retries, error handling, etc.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect((ip, MASTER_PC_PORT))
            data = json.dumps(message_dict).encode('utf-8')
            s.sendall(data)
            s.close()
        except Exception as e:
            self.log_event(f"TCP send to {ip} failed: {e}")

    def send_message_udp(self, ip, message_dict):
        """
        Example of a simple UDP approach:
        1) Send JSON to (ip, MASTER_PC_PORT) via UDP.
        2) Possibly no ack, or you can implement an ack with a wait here.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            data = json.dumps(message_dict).encode('utf-8')
            s.sendto(data, (ip, MASTER_PC_PORT))
            s.close()
        except Exception as e:
            self.log_event(f"UDP send to {ip} failed: {e}")

    def calculate_checksum(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_next_multiple_of_5_sec(self, min_gap=5):
        now = time.time()
        local_now = time.localtime(now)
        current_sec = local_now.tm_sec
        next_5 = (current_sec // 5 + 1) * 5
        if next_5 >= 60:
            next_5 -= 60
            base_minute = time.mktime((
                local_now.tm_year, 
                local_now.tm_mon, 
                local_now.tm_mday,
                local_now.tm_hour,
                local_now.tm_min + 1,
                0,
                local_now.tm_wday,
                local_now.tm_yday,
                local_now.tm_isdst
            ))
            candidate_time = base_minute + next_5
        else:
            base_minute = time.mktime((
                local_now.tm_year, 
                local_now.tm_mon, 
                local_now.tm_mday,
                local_now.tm_hour,
                local_now.tm_min,
                0,
                local_now.tm_wday,
                local_now.tm_yday,
                local_now.tm_isdst
            ))
            candidate_time = base_minute + next_5

        if (candidate_time - now) < min_gap:
            next_5 += 5
            if next_5 >= 60:
                next_5 -= 60
                base_minute = time.mktime((
                    local_now.tm_year, 
                    local_now.tm_mon, 
                    local_now.tm_mday,
                    local_now.tm_hour,
                    local_now.tm_min + 1,
                    0,
                    local_now.tm_wday,
                    local_now.tm_yday,
                    local_now.tm_isdst
                ))
            candidate_time = base_minute + next_5
        return candidate_time

    def start_recording(self):
        session_name = self.session_entry.get()
        bitrate = self.bitrate_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        start_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.log_event(f"Scheduling recording at {time.strftime('%H:%M:%S', time.localtime(start_time))}")

        # For each camera, store the pending start time
        for ip in [c['ip'] for c in self.cameras]:
            self.camera_status[ip]['pending_start_time'] = start_time

        # Send command
        for ip in [c['ip'] for c in self.cameras]:
            msg = {
                'task': 'REC_START',
                'session_name': session_name,
                'bitrate': bitrate,
                'start_time': start_time
            }
            self.send_message(ip, msg)

    def stop_recording(self):
        self.log_event('Sending REC_STOP command to all cameras...')
        for ip in [c['ip'] for c in self.cameras]:
            message = {'task': 'REC_STOP'}
            self.send_message(ip, message)

    def capture_stills(self):
        session_name = self.still_name_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name for the still.')
            return
        
        capture_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.log_event(f"Scheduling still capture at {time.strftime('%H:%M:%S', time.localtime(capture_time))}")

        for ip in [c['ip'] for c in self.cameras]:
            self.camera_status[ip]['pending_still_time'] = capture_time

        for ip in [c['ip'] for c in self.cameras]:
            msg = {
                'task': 'REC_STILL',
                'session_name': session_name,
                'start_time': capture_time
            }
            self.send_message(ip, msg)

    def on_close(self):
        self.running = False
        self.root.destroy()

if __name__ == '__main__':
    LASTIME = time.time()
    root = tk.Tk()
    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
