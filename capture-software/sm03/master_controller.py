# master_pc_gui.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import socket
import threading
import time
import json
import os
import hashlib
import netifaces

# Configuration
LISTEN_PORT = 50000
BROADCAST_PORT = 50005
BROADCAST_IP = '192.168.179.255'
CAMERA_LIST_FILE = 'camera_list.json'
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'

# Global variables
cameras = []
camera_status = {}
debug_mode = False

# Create sessions directory if it doesn't exist
if not os.path.exists(SESSIONS_DIR):
    os.makedirs(SESSIONS_DIR)

# Load camera list
with open(CAMERA_LIST_FILE, 'r') as f:
    cameras = json.load(f)

# Function to log events
def log_event(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(EVENT_LOG, 'a') as log_file:
        log_file.write(f'[{timestamp}] {message}\n')
    if debug_mode:
        print(f'[{timestamp}] {message}')

# Function to send broadcast messages
def send_broadcast_message(message_dict):
    message = json.dumps(message_dict)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(message.encode(), (BROADCAST_IP, BROADCAST_PORT))
    sock.close()

# Function to send unicast messages
def send_unicast_message(message_dict, ip, port):
    message = json.dumps(message_dict)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(message.encode(), (ip, port))
    sock.close()

# Function to receive UDP messages
def receive_udp_messages():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', LISTEN_PORT))
    while True:
        data, addr = sock.recvfrom(4096)
        message = json.loads(data.decode())
        handle_udp_message(message, addr)

# Function to handle incoming UDP messages
def handle_udp_message(message, addr):
    task = message.get('task')
    ip = message.get('ip')
    if task == 'STATUS':
        state = message.get('state')
        storage_remaining = message.get('storage_remaining_mb')
        sessions = message.get('sessions')
        camera_status[ip] = {
            'state': state,
            'last_seen': time.time(),
            'storage_remaining_mb': storage_remaining,
            'sessions': sessions
        }
        update_status_display()
    elif task == 'FILE_TRANSFER_COMPLETE':
        filename = message.get('file')
        checksum = message.get('checksum')
        # Verify checksum
        local_file = os.path.join(SESSIONS_DIR, filename)
        if os.path.exists(local_file):
            local_checksum = calculate_checksum(local_file)
            if local_checksum == checksum:
                log_event(f'File {filename} transferred successfully and checksum verified.')
            else:
                log_event(f'Checksum mismatch for file {filename}.')
        else:
            log_event(f'File {filename} not found for checksum verification.')
    elif task == 'STORAGE_INFO':
        storage_remaining = message.get('storage_remaining_mb')
        camera_status[ip]['storage_remaining_mb'] = storage_remaining
        update_status_display()
    elif task == 'SESSIONS_INFO':
        sessions = message.get('sessions')
        camera_status[ip]['sessions'] = sessions
        update_status_display()
    elif task == 'SETTINGS_UPDATED':
        log_event(f'Camera settings updated on {ip}.')
    # Handle additional tasks as needed

# Function to update the status display
def update_status_display():
    for child in status_tree.get_children():
        status_tree.delete(child)
    for camera in cameras:
        ip = camera['ip']
        status = camera_status.get(ip, {})
        state = status.get('state', 'Unknown')
        last_seen = status.get('last_seen', 0)
        storage = status.get('storage_remaining_mb', 'N/A')
        sessions = ', '.join(status.get('sessions', []))
        time_since_seen = time.time() - last_seen
        if time_since_seen > 10:
            state = 'Offline'
        status_tree.insert('', 'end', values=(camera['name'], ip, state, storage, sessions))

# Function to calculate MD5 checksum
def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def start_recording():
    session_name = session_entry.get()
    bitrate = bitrate_entry.get()
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
    send_broadcast_message(message)
    log_event('Sent REC_START command with scheduled start time.')


# Function to stop recording
def stop_recording():
    message = {'task': 'REC_STOP'}
    send_broadcast_message(message)
    log_event('Sent REC_STOP command.')

# Function to capture still images
def capture_stills():
    session_name = session_entry.get()
    compression_format = compression_format_var.get()
    compression = compression_entry.get()
    if not session_name:
        messagebox.showerror('Error', 'Please enter a session name.')
        return
    message = {
        'task': 'REC_STILL',
        'session_name': session_name,
        'compression_format': compression_format,
        'compression': compression
    }
    send_broadcast_message(message)
    log_event('Sent REC_STILL command.')

# Function to get storage info
def get_storage_info():
    message = {'task': 'GET_STORAGE'}
    send_broadcast_message(message)
    log_event('Requested storage info from all cameras.')

# Function to get sessions info
def get_sessions_info():
    message = {'task': 'GET_SESSIONS'}
    send_broadcast_message(message)
    log_event('Requested sessions info from all cameras.')

# Function to download sessions
def download_sessions():
    session_name = session_entry.get()
    if not session_name:
        messagebox.showerror('Error', 'Please enter a session name.')
        return
    # Create session directory
    session_dir = os.path.join(SESSIONS_DIR, session_name)
    if not os.path.exists(session_dir):
        os.makedirs(session_dir)
    # Send transmit commands to each camera one by one
    for camera in cameras:
        ip = camera['ip']
        port = camera['port']
        if session_name in camera_status.get(ip, {}).get('sessions', []):
            message = {
                'task': 'TRANSMIT_SESSION',
                'session_name': session_name
            }
            send_unicast_message(message, ip, port)
            log_event(f'Requested session {session_name} from {ip}.')
            # Wait or handle synchronization as needed
            time.sleep(1)  # Adjust as necessary

# Function to delete sessions
def delete_sessions():
    if messagebox.askyesno('Confirm', 'Are you sure you want to delete all sessions on all cameras?'):
        message = {'task': 'DELETE_SESSIONS'}
        send_broadcast_message(message)
        log_event('Sent DELETE_SESSIONS command.')

# Function to send camera settings
def send_camera_settings():
    settings_file = filedialog.askopenfilename(title='Select Camera Settings File', filetypes=[('JSON Files', '*.json')])
    if settings_file:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
        message = {
            'task': 'UPDATE_SETTINGS',
            'settings': settings
        }
        send_broadcast_message(message)
        log_event('Sent camera settings to all cameras.')

# Function to toggle debug mode
def toggle_debug():
    global debug_mode
    debug_mode = not debug_mode
    if debug_mode:
        log_event('Debug mode activated.')
    else:
        log_event('Debug mode deactivated.')

# GUI setup
root = tk.Tk()
root.title('Camera Control GUI')

# Session frame
session_frame = ttk.LabelFrame(root, text='Session Control')
session_frame.pack(fill='x', padx=5, pady=5)

ttk.Label(session_frame, text='Session Name:').grid(row=0, column=0, padx=5, pady=5)
session_entry = ttk.Entry(session_frame)
session_entry.grid(row=0, column=1, padx=5, pady=5)

ttk.Label(session_frame, text='Bitrate (Kbps):').grid(row=1, column=0, padx=5, pady=5)
bitrate_entry = ttk.Entry(session_frame)
bitrate_entry.insert(0, '15000')  # Default bitrate
bitrate_entry.grid(row=1, column=1, padx=5, pady=5)

start_button = ttk.Button(session_frame, text='Start Recording', command=start_recording)
start_button.grid(row=2, column=0, padx=5, pady=5)

stop_button = ttk.Button(session_frame, text='Stop Recording', command=stop_recording)
stop_button.grid(row=2, column=1, padx=5, pady=5)

# Still image frame
still_frame = ttk.LabelFrame(root, text='Still Image Control')
still_frame.pack(fill='x', padx=5, pady=5)

compression_format_var = tk.StringVar(value='jpeg')
compression_formats = ['jpeg', 'png', 'raw']
ttk.Label(still_frame, text='Format:').grid(row=0, column=0, padx=5, pady=5)
format_menu = ttk.OptionMenu(still_frame, compression_format_var, 'jpeg', *compression_formats)
format_menu.grid(row=0, column=1, padx=5, pady=5)

ttk.Label(still_frame, text='Compression (%):').grid(row=1, column=0, padx=5, pady=5)
compression_entry = ttk.Entry(still_frame)
compression_entry.insert(0, '100')  # Default compression
compression_entry.grid(row=1, column=1, padx=5, pady=5)

capture_button = ttk.Button(still_frame, text='Capture Still Image', command=capture_stills)
capture_button.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

# Status frame
status_frame = ttk.LabelFrame(root, text='Camera Status')
status_frame.pack(fill='both', expand=True, padx=5, pady=5)

columns = ('Name', 'IP', 'State', 'Storage Remaining (MB)', 'Sessions')
status_tree = ttk.Treeview(status_frame, columns=columns, show='headings')
for col in columns:
    status_tree.heading(col, text=col)
status_tree.pack(fill='both', expand=True)

# Control buttons
control_frame = ttk.Frame(root)
control_frame.pack(fill='x', padx=5, pady=5)

get_storage_button = ttk.Button(control_frame, text='Get Storage Info', command=get_storage_info)
get_storage_button.grid(row=0, column=0, padx=5, pady=5)

get_sessions_button = ttk.Button(control_frame, text='Get Sessions Info', command=get_sessions_info)
get_sessions_button.grid(row=0, column=1, padx=5, pady=5)

download_button = ttk.Button(control_frame, text='Download Sessions', command=download_sessions)
download_button.grid(row=0, column=2, padx=5, pady=5)

delete_button = ttk.Button(control_frame, text='Delete Sessions', command=delete_sessions)
delete_button.grid(row=0, column=3, padx=5, pady=5)

settings_button = ttk.Button(control_frame, text='Send Camera Settings', command=send_camera_settings)
settings_button.grid(row=0, column=4, padx=5, pady=5)

debug_button = ttk.Button(control_frame, text='Toggle Debug Mode', command=toggle_debug)
debug_button.grid(row=0, column=5, padx=5, pady=5)

# Start UDP receiver thread
udp_thread = threading.Thread(target=receive_udp_messages, daemon=True)
udp_thread.start()

# Start the GUI loop
root.mainloop()
