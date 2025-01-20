# master_controller.py v8.2 - Fixed DEBUG
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
import paramiko
from datetime import datetime

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent.parent,  'utils','camera_list.json')
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'
MASTER_PC_IP = '0.0.0.0'  # Bind to all interfaces
MASTER_PC_PORT = 50005

LASTIME = time.time()

NO_RESPONSE_TIMEOUT = 2.0  # If no status in 2 seconds, show "NO RESPONSE"

class DebugWindow(tk.Toplevel):
    def __init__(self, master, on_close_callback=None):
        super().__init__(master)
        self.title('VolumanXR - Debug Window')
        self.on_close_callback = on_close_callback  # Store the callback

        self.create_widgets()
        # Override the window's "X" close to ensure we can also do cleanup:
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

    def _handle_close(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

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
        # If not paused, allow normal insertion
        self.text.config(state='normal')
        self.text.insert('end', f'{who}: {message}\n')
        self.text.see('end')

    def clear_messages(self):
        self.text.config(state='normal')
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
        self.load_camera_list()

        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR)

        self.context = zmq.Context()
        self.router_socket = self.context.socket(zmq.ROUTER)
        self.router_socket.bind(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
        self.poller = zmq.Poller()
        self.poller.register(self.router_socket, zmq.POLLIN)

        # identity -> ip mapping
        self.connected_cameras = {}
        # reverse: ip -> identity mapping
        self.ip_to_identity = {}

        self.create_widgets()

        # Initialize status for all cameras to "NO RESPONSE"
        # so they appear immediately in the UI
        for cam in self.cameras:
            ip = cam['ip']
            self.camera_status[ip] = {
                'state': 'NO RESPONSE',
                'last_seen': 0,
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }

        # Start the receive thread
        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
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

        ttk.Label(still_frame, text='Session Name for Still:').grid(row=0, column=0, padx=5, pady=5)
        self.still_name_entry = ttk.Entry(still_frame)
        self.still_name_entry.grid(row=0, column=1, padx=5, pady=5)

        capture_button = ttk.Button(still_frame, text='Capture Still Image', command=self.capture_stills)
        capture_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5)

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
            self.debug_window = DebugWindow(self.root, on_close_callback=self._debug_window_closed)
            self.debug_mode = True

    def _debug_window_closed(self):
        """Called when the DebugWindow is closed with the X button."""
        self.debug_window = None
        self.debug_mode = False

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
        if time.time() - LASTIME > 1:
            while self.running:
                current_time = time.time()
                for ip, status in self.camera_status.items():
                    last_seen = status.get('last_seen', 0)
                    if (current_time - last_seen) > NO_RESPONSE_TIMEOUT:
                        # Overwrite only if we don't already have "NO RESPONSE"
                        if status['state'] != 'NO RESPONSE':
                            self.camera_status[ip]['state'] = 'NO RESPONSE'
                            self.update_status_tree(ip)
            LASTIME = time.time()

    def receive_loop(self):
        lasttime2 = time.perf_counter()
        while self.running:
            socks = dict(self.poller.poll(500))
            if self.router_socket in socks and socks[self.router_socket] == zmq.POLLIN:
                frames = self.router_socket.recv_multipart()
                identity = frames[0]
                message = json.loads(frames[1].decode())
                self.handle_message(identity, message)
            if time.perf_counter() - lasttime2 > 1:
                self.update_status_tree_all()
                lasttime2 = time.perf_counter()


    def handle_message(self, identity, message):
        task = message.get('task')
        ip = message.get('ip', 'Unknown')

        # Always log full incoming messages so they show in the debug window:
        self.log_event(f"Incoming message from {ip}: {message}")

        # Register camera identity -> IP
        if task == 'REGISTER':
            self.connected_cameras[identity] = ip
            self.ip_to_identity[ip] = identity
            # Set default camera_status
            self.camera_status[ip] = {
                'state': 'STANDBY',
                'last_seen': time.time(),
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }
            #self.update_status_tree(ip)
            self.log_event(f'Camera registered: {ip}')

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
            #self.update_status_tree(ip)

        elif task == 'FILE_TRANSFER_COMPLETE':
            # For completeness; same as before
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

        # The Pi acknowledges the start time
        elif task == 'REC_START_ACK':
            ack_time = message.get('start_time', 0)
            # Compare with what we *thought* we gave it:
            # If the Pi echoes the same start_time, mark the Pi "PREPARING"
            # Otherwise: "SYNC ISSUE"
            expected_state = self.camera_status[ip].get('pending_start_time', None)
            if expected_state is not None and abs(expected_state - ack_time) < 0.1:
                # Times match
                self.camera_status[ip]['state'] = 'PREPARING'
            else:
                self.camera_status[ip]['state'] = 'SYNC ISSUE'
            #self.update_status_tree(ip)

        # The Pi acknowledges the still capture time
        elif task == 'REC_STILL_ACK':
            ack_time = message.get('start_time', 0)
            expected_still_time = self.camera_status[ip].get('pending_still_time', None)
            if expected_still_time is not None and abs(expected_still_time - ack_time) < 0.1:
                self.camera_status[ip]['state'] = 'PREPARING_STILL'
            else:
                self.camera_status[ip]['state'] = 'SYNC ISSUE'
            #self.update_status_tree(ip)

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

        # Find if we already have an entry
        found = False
        for item in self.status_tree.get_children():
            values = self.status_tree.item(item, 'values')
            if values[1] == ip:
                self.status_tree.item(item, values=(name, ip, state, last_seen_str, storage, sessions))
                found = True
                break
        if not found:
            self.status_tree.insert('', 'end', values=(name, ip, state, last_seen_str, storage, sessions))

    def update_status_tree_all(self):
        for ip in self.camera_status:
            self.update_status_tree(ip)

    def update_status_tree_loop(self):
        self.root.after(500, self.update_status_tree_all)

    def send_message(self, ip, message_dict):
        """Send a ZMQ message to the camera with the given IP."""
        identity = self.ip_to_identity.get(ip)
        if identity:
            self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])

    def broadcast_message(self, message_dict):
        """Send a ZMQ message to all connected cameras."""
        for ip in self.ip_to_identity:
            self.send_message(ip, message_dict)

    def calculate_checksum(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_next_multiple_of_5_sec(self, min_gap=5):
        """
        Return a float (timestamp) that is the next multiple of 5 seconds
        from the current minute that is at least min_gap seconds in the future.
        Example: If it's currently HH:MM:03, the next multiple of 5 is HH:MM:05,
        but that's only 2 seconds away, so we skip to HH:MM:10 which is 7 seconds away.
        """
        now = time.time()
        local_now = time.localtime(now)
        current_sec = local_now.tm_sec
        # Next raw multiple of 5 from the current second
        next_5 = (current_sec // 5 + 1) * 5
        if next_5 >= 60:
            # we have to bump to next minute
            next_5 -= 60
            # compute the base time at the top of the next minute
            base_minute = time.mktime((
                local_now.tm_year,
                local_now.tm_mon,
                local_now.tm_mday,
                local_now.tm_hour,
                local_now.tm_min + 1,
                0,  # second
                local_now.tm_wday,
                local_now.tm_yday,
                local_now.tm_isdst
            ))
            candidate_time = base_minute + next_5
        else:
            # remain in same minute
            base_minute = time.mktime((
                local_now.tm_year,
                local_now.tm_mon,
                local_now.tm_mday,
                local_now.tm_hour,
                local_now.tm_min,
                0,  # second
                local_now.tm_wday,
                local_now.tm_yday,
                local_now.tm_isdst
            ))
            candidate_time = base_minute + next_5

        # Check if gap < min_gap
        if (candidate_time - now) < min_gap:
            # jump another 5 sec
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

        # For each connected camera, store the pending start time
        for ip in self.ip_to_identity:
            self.camera_status[ip]['pending_start_time'] = start_time

        # Instruct each camera to start at that time
        for ip in self.ip_to_identity:
            msg = {
                'task': 'REC_START',
                'session_name': session_name,
                'bitrate': bitrate,
                'start_time': start_time
            }
            self.send_message(ip, msg)

    def stop_recording(self):
        for ip in self.ip_to_identity:
            message = {'task': 'REC_STOP'}
            self.send_message(ip, message)
        self.log_event('Sent REC_STOP command.')

    def capture_stills(self):
        session_name = self.still_name_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name for the still.')
            return

        capture_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.log_event(f"Scheduling still capture at {time.strftime('%H:%M:%S', time.localtime(capture_time))}")

        for ip in self.ip_to_identity:
            self.camera_status[ip]['pending_still_time'] = capture_time

        for ip in self.ip_to_identity:
            msg = {
                'task': 'REC_STILL',
                'session_name': session_name,
                'start_time': capture_time
            }
            self.send_message(ip, msg)

    def on_close(self):
        self.running = False
        self.root.destroy()

def update_dist_time():
    try:
        # Get the current system time
        current_time = datetime.now().strftime("%d %b %Y %H:%M:%S")

        # SSH connection setup
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # Automatically add host keys

        # Connect to the remote host
        client.connect('10.50.100.5', username='voluman', password='xr')

        # Prepare the command to set the time
        command = f'sudo date -s "{current_time}"'

        # Execute the command to set the time
        stdin, stdout, stderr = client.exec_command(command)

        # # Handling sudo prompt for password
        # stdin.write(password + '\n')
        # stdin.flush()

        # Get output and errors (if any)
        output = stdout.read().decode('utf-8')
        errors = stderr.read().decode('utf-8')

        # Print the output and errors (if any)
        if output:
            print("Output:", output)
        if errors:
            print("Errors:", errors)

        # Close the SSH connection
        client.close()

    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == '__main__':
    root = tk.Tk()
    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    #app.update_status_tree_all()
    root.mainloop()
