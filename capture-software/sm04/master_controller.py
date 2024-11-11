# master_pc_gui.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import socket
import threading
import time
import json
import os
import hashlib

# Configuration
LISTEN_PORT = 50000
BROADCAST_PORT = 50005
BROADCAST_IP = '192.168.179.255'  # Assuming this is the broadcast IP for the network
CAMERA_LIST_FILE = 'camera_list.json'
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'

class DebugWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title('VolumanXR - Debug Window')
        self.create_widgets()

    def create_widgets(self):
        self.text = tk.Text(self)
        self.text.pack(fill='both', expand=True)
        
        # Control buttons
        control_frame = ttk.Frame(self)
        control_frame.pack(fill='x', padx=5, pady=5)

        clear_messages_button = ttk.Button(control_frame, text='Clear Messages', command=self.clear_messages)
        clear_messages_button.grid(row=0, column=0, padx=5, pady=5)
        
        pause_messages_button = ttk.Button(control_frame, text='Pause Messages', command=self.pause_messages)
        pause_messages_button.grid(row=0, column=1, padx=5, pady=5)
        
        resume_messages_button = ttk.Button(control_frame, text='Resume Messages', command=self.resume_messages)
        resume_messages_button.grid(row=0, column=2, padx=5, pady=5)

    # Function to insert messages
    def insert_message(self, ip, message):
        self.text.insert('end', f'{ip}: {message}\n')
        self.text.see('end')
        
    # Function to clear messages    
    def clear_messages(self):
        self.text.delete('1.0', 'end')
        
    # Function to pause messages
    def pause_messages(self):
        self.text.config(state='disabled')
        
    # Function to resume messages
    def resume_messages(self):
        self.text.config(state='normal')
        

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title('VolumanXR - Camera Control UI')
        self.debug_window = None
        self.debug_mode = False

        # Global variables
        self.cameras = []
        self.camera_status = {}
        self.load_camera_list()

        # Create sessions directory if it doesn't exist
        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR)

        # Build GUI
        self.create_widgets()

        # Start threads
        self.running = True
        self.udp_thread = threading.Thread(target=self.receive_udp_messages, daemon=True)
        self.udp_thread.start()
        self.monitor_thread = threading.Thread(target=self.monitor_pis, daemon=True)
        self.monitor_thread.start()

    def load_camera_list(self):
        with open(CAMERA_LIST_FILE, 'r') as f:
            self.cameras = json.load(f)

    def create_widgets(self):
        # Session frame
        session_frame = ttk.LabelFrame(self.root, text='Session Control')
        session_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(session_frame, text='Session Name:').grid(row=0, column=0, padx=5, pady=5)
        self.session_entry = ttk.Entry(session_frame)
        self.session_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(session_frame, text='Bitrate (Kbps):').grid(row=1, column=0, padx=5, pady=5)
        self.bitrate_entry = ttk.Entry(session_frame)
        self.bitrate_entry.insert(0, '15000')  # Default bitrate
        self.bitrate_entry.grid(row=1, column=1, padx=5, pady=5)

        start_button = ttk.Button(session_frame, text='Start Recording', command=self.start_recording)
        start_button.grid(row=2, column=0, padx=5, pady=5)

        stop_button = ttk.Button(session_frame, text='Stop Recording', command=self.stop_recording)
        stop_button.grid(row=2, column=1, padx=5, pady=5)

        # Still image frame
        still_frame = ttk.LabelFrame(self.root, text='Still Image Control')
        still_frame.pack(fill='x', padx=5, pady=5)

        self.compression_format_var = tk.StringVar(value='jpeg')
        compression_formats = ['jpeg', 'png', 'raw']
        ttk.Label(still_frame, text='Format:').grid(row=0, column=0, padx=5, pady=5)
        format_menu = ttk.OptionMenu(still_frame, self.compression_format_var, 'jpeg', *compression_formats)
        format_menu.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(still_frame, text='Compression (%):').grid(row=1, column=0, padx=5, pady=5)
        self.compression_entry = ttk.Entry(still_frame)
        self.compression_entry.insert(0, '100')  # Default compression
        self.compression_entry.grid(row=1, column=1, padx=5, pady=5)

        capture_button = ttk.Button(still_frame, text='Capture Still Image', command=self.capture_stills)
        capture_button.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        # Status frame
        status_frame = ttk.LabelFrame(self.root, text='Camera Status')
        status_frame.pack(fill='both', expand=True, padx=5, pady=5)

        columns = ('Name', 'IP', 'State', 'Last Seen', 'Storage Remaining (MB)', 'Sessions')
        self.status_tree = ttk.Treeview(status_frame, columns=columns, show='headings')
        for col in columns:
            self.status_tree.heading(col, text=col)
        self.status_tree.pack(fill='both', expand=True)

        # Control buttons
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=5, pady=5)

        get_storage_button = ttk.Button(control_frame, text='Get Storage Info', command=self.get_storage_info)
        get_storage_button.grid(row=0, column=0, padx=5, pady=5)

        get_sessions_button = ttk.Button(control_frame, text='Get Sessions Info', command=self.get_sessions_info)
        get_sessions_button.grid(row=0, column=1, padx=5, pady=5)

        download_button = ttk.Button(control_frame, text='Download Sessions', command=self.download_sessions)
        download_button.grid(row=0, column=2, padx=5, pady=5)

        delete_button = ttk.Button(control_frame, text='Delete Sessions', command=self.delete_sessions)
        delete_button.grid(row=0, column=3, padx=5, pady=5)

        settings_button = ttk.Button(control_frame, text='Send Camera Settings', command=self.send_camera_settings)
        settings_button.grid(row=0, column=4, padx=5, pady=5)

        debug_button = ttk.Button(control_frame, text='Toggle Debug Mode', command=self.toggle_debug)
        debug_button.grid(row=0, column=5, padx=5, pady=5)

    # Function to toggle debug mode
    def toggle_debug(self):
        if self.debug_window:
            self.debug_window.destroy()
            self.debug_window = None
            self.debug_mode = False
        else:
            self.debug_window = DebugWindow(self.root)
            self.debug_mode = True

    # Function to log events
    def log_event(self, message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(EVENT_LOG, 'a') as log_file:
            log_file.write(f'[{timestamp}] {message}\n')
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message('MASTER', message)

    # Function to send broadcast messages
    def send_broadcast_message(self, message_dict):
        message = json.dumps(message_dict)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(message.encode(), (BROADCAST_IP, BROADCAST_PORT))
        sock.close()
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message('Broadcast', message)

    # Function to send unicast messages
    def send_unicast_message(self, message_dict, ip, port):
        message = json.dumps(message_dict)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(message.encode(), (ip, port))
        sock.close()
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message(ip, message)

    # Function to receive UDP messages
    def receive_udp_messages(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('', LISTEN_PORT))
        sock.settimeout(1)
        while self.running:
            try:
                data, addr = sock.recvfrom(4096)
                message = json.loads(data.decode())
                self.handle_udp_message(message, addr)
            except socket.timeout:
                continue
            except Exception as e:
                self.log_event(f'Error receiving UDP message: {e}')

    # Function to handle incoming UDP messages
    def handle_udp_message(self, message, addr):
        task = message.get('task')
        ip = message.get('ip')
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message(ip, json.dumps(message))
        if task == 'STATUS':
            state = message.get('state')
            storage_remaining = message.get('storage_remaining_mb')
            sessions = message.get('sessions')
            last_seen = time.time()
            self.camera_status[ip] = {
                'state': state,
                'last_seen': last_seen,
                'storage_remaining_mb': storage_remaining,
                'sessions': sessions
            }
            self.update_status_tree(ip)
        elif task == 'FILE_TRANSFER_COMPLETE':
            filename = message.get('file')
            checksum = message.get('checksum')
            # Verify checksum
            local_file = os.path.join(SESSIONS_DIR, filename)
            if os.path.exists(local_file):
                local_checksum = self.calculate_checksum(local_file)
                if local_checksum == checksum:
                    self.log_event(f'File {filename} transferred successfully and checksum verified.')
                else:
                    self.log_event(f'Checksum mismatch for file {filename}.')
            else:
                self.log_event(f'File {filename} not found for checksum verification.')
        elif task == 'STORAGE_INFO':
            storage_remaining = message.get('storage_remaining_mb')
            self.camera_status[ip]['storage_remaining_mb'] = storage_remaining
            self.update_status_tree(ip)
        elif task == 'SESSIONS_INFO':
            sessions = message.get('sessions')
            self.camera_status[ip]['sessions'] = sessions
            self.update_status_tree(ip)
        elif task == 'SETTINGS_UPDATED':
            self.log_event(f'Camera settings updated on {ip}.')
        # Handle additional tasks as needed

    # Function to update the status tree
    def update_status_tree(self, ip):
        camera = next((c for c in self.cameras if c['ip'] == ip), None)
        if camera:
            name = camera['name']
        else:
            name = 'Unknown'

        status = self.camera_status.get(ip, {})
        state = status.get('state', 'Unknown')
        last_seen = status.get('last_seen', 0)
        last_seen_str = time.strftime('%H:%M:%S', time.localtime(last_seen))
        storage = status.get('storage_remaining_mb', 'N/A')
        sessions = ', '.join(status.get('sessions', []))

        # Check if the camera is already in the tree
        found = False
        for item in self.status_tree.get_children():
            values = self.status_tree.item(item, 'values')
            if values[1] == ip:
                # Update the existing entry
                self.status_tree.item(item, values=(name, ip, state, last_seen_str, storage, sessions))
                found = True
                break

        if not found:
            # Insert a new entry
            self.status_tree.insert('', 'end', values=(name, ip, state, last_seen_str, storage, sessions))

    # Function to monitor Pis and update status if they have not responded
    def monitor_pis(self):
        while self.running:
            now = time.time()
            for camera in self.cameras:
                ip = camera['ip']
                status = self.camera_status.get(ip, {})
                last_seen = status.get('last_seen', 0)
                state = status.get('state', 'Unknown')
                time_since_seen = now - last_seen
                if time_since_seen > 10:
                    # Update status to 'No Response'
                    state = 'No Response'
                    status['state'] = state
                    self.camera_status[ip] = status
                    self.update_status_tree(ip)
            time.sleep(1)

    # Function to calculate MD5 checksum
    def calculate_checksum(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    # Function to start recording
    def start_recording(self):
        session_name = self.session_entry.get()
        bitrate = self.bitrate_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        start_time = time.time() + 5  # Start in 5 seconds
        message = {
            'task': 'REC_START',
            'session_name': session_name,
            'bitrate': bitrate,
            'start_time': start_time
        }
        self.send_broadcast_message(message)
        self.log_event('Sent REC_START command with scheduled start time.')

    # Function to stop recording
    def stop_recording(self):
        message = {'task': 'REC_STOP'}
        self.send_broadcast_message(message)
        self.log_event('Sent REC_STOP command.')

    # Function to capture still images
    def capture_stills(self):
        session_name = self.session_entry.get()
        compression_format = self.compression_format_var.get()
        compression = self.compression_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        message = {
            'task': 'REC_STILL',
            'session_name': session_name,
            'compression_format': compression_format,
            'compression': compression
        }
        self.send_broadcast_message(message)
        self.log_event('Sent REC_STILL command.')

    # Function to get storage info
    def get_storage_info(self):
        message = {'task': 'GET_STORAGE'}
        self.send_broadcast_message(message)
        self.log_event('Requested storage info from all cameras.')

    # Function to get sessions info
    def get_sessions_info(self):
        message = {'task': 'GET_SESSIONS'}
        self.send_broadcast_message(message)
        self.log_event('Requested sessions info from all cameras.')

    # Function to download sessions
    def download_sessions(self):
        session_name = self.session_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        # Create session directory
        session_dir = os.path.join(SESSIONS_DIR, session_name)
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        # Send transmit commands to each camera one by one
        for camera in self.cameras:
            ip = camera['ip']
            port = camera['port']
            if session_name in self.camera_status.get(ip, {}).get('sessions', []):
                message = {
                    'task': 'TRANSMIT_SESSION',
                    'session_name': session_name
                }
                self.send_unicast_message(message, ip, port)
                self.log_event(f'Requested session {session_name} from {ip}.')
                # Wait or handle synchronization as needed
                time.sleep(1)  # Adjust as necessary

    # Function to delete sessions
    def delete_sessions(self):
        if messagebox.askyesno('Confirm', 'Are you sure you want to delete all sessions on all cameras?'):
            message = {'task': 'DELETE_SESSIONS'}
            self.send_broadcast_message(message)
            self.log_event('Sent DELETE_SESSIONS command.')

    # Function to send camera settings
    def send_camera_settings(self):
        settings_file = filedialog.askopenfilename(title='Select Camera Settings File', filetypes=[('JSON Files', '*.json')])
        if settings_file:
            with open(settings_file, 'r') as f:
                settings = json.load(f)
            message = {
                'task': 'UPDATE_SETTINGS',
                'settings': settings
            }
            self.send_broadcast_message(message)
            self.log_event('Sent camera settings to all cameras.')

    def on_close(self):
        self.running = False
        self.root.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
