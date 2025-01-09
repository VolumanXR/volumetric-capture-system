# master_controller.py v5
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



# Configuration
# Directory setup
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent,  'utils','camera_list.json')  
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'
MASTER_PC_IP = '0.0.0.0'  # Bind to all interfaces
MASTER_PC_PORT = 50005

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
        self.router_socket.bind(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
        self.poller = zmq.Poller()
        self.poller.register(self.router_socket, zmq.POLLIN)

        self.connected_cameras = {}  # identity -> ip
        self.ip_to_identity = {}

        self.create_widgets()

        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()

    def load_camera_list(self):
        with open(CAMERA_LIST_FILE, 'r') as f:
            self.cameras = json.load(f)
            # Remove port usage from cameras if present
            for c in self.cameras:
                if 'port' in c:
                    del c['port']

    def create_widgets(self):
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

        still_frame = ttk.LabelFrame(self.root, text='Still Image Control')
        still_frame.pack(fill='x', padx=5, pady=5)

        self.compression_format_var = tk.StringVar(value='jpeg')
        compression_formats = ['jpeg', 'png', 'raw']
        ttk.Label(still_frame, text='Format:').grid(row=0, column=0, padx=5, pady=5)
        format_menu = ttk.OptionMenu(still_frame, self.compression_format_var, 'jpeg', *compression_formats)
        format_menu.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(still_frame, text='Compression (%):').grid(row=1, column=0, padx=5, pady=5)
        self.compression_entry = ttk.Entry(still_frame)
        self.compression_entry.insert(0, '100')
        self.compression_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(still_frame, text='Still Base Name:').grid(row=2, column=0, padx=5, pady=5)
        self.still_name_entry = ttk.Entry(still_frame)
        self.still_name_entry.grid(row=2, column=1, padx=5, pady=5)

        capture_button = ttk.Button(still_frame, text='Capture Still Image', command=self.capture_stills)
        capture_button.grid(row=3, column=0, columnspan=2, padx=5, pady=5)

        status_frame = ttk.LabelFrame(self.root, text='Camera Status')
        status_frame.pack(fill='both', expand=True, padx=5, pady=5)

        columns = ('Name', 'IP', 'State', 'Last Seen', 'Storage Remaining (MB)', 'Sessions')
        self.status_tree = ttk.Treeview(status_frame, columns=columns, show='headings')
        for col in columns:
            self.status_tree.heading(col, text=col)
        self.status_tree.pack(fill='both', expand=True)

        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=5, pady=5)

        debug_button = ttk.Button(control_frame, text='Toggle Debug Mode', command=self.toggle_debug)
        debug_button.grid(row=0, column=0, padx=5, pady=5)

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

    def receive_loop(self):
        while self.running:
            socks = dict(self.poller.poll(1000))
            if self.router_socket in socks and socks[self.router_socket] == zmq.POLLIN:
                frames = self.router_socket.recv_multipart()
                identity = frames[0]
                message = json.loads(frames[1].decode())
                self.handle_message(identity, message)

    def handle_message(self, identity, message):
        task = message.get('task')
        ip = message.get('ip', 'Unknown')
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
            self.camera_status[ip] = {
                'state': state,
                'last_seen': time.time(),
                'storage_remaining_mb': storage_remaining,
                'sessions': sessions
            }
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
        # No further log output here to keep output minimal

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

        found = False
        for item in self.status_tree.get_children():
            values = self.status_tree.item(item, 'values')
            if values[1] == ip:
                self.status_tree.item(item, values=(name, ip, state, last_seen_str, storage, sessions))
                found = True
                break
        if not found:
            self.status_tree.insert('', 'end', values=(name, ip, state, last_seen_str, storage, sessions))

    def send_message(self, ip, message_dict):
        identity = self.ip_to_identity.get(ip)
        if identity:
            self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])

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
        # Offset calculation for still capture
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

    def on_close(self):
        self.running = False
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
