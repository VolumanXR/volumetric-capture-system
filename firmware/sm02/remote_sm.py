# raspberry_pi_camera_node.py
import socket
import time
import os
import threading
import json
import hashlib
import subprocess
import signal
from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder, MJPEGEncoder, Quality
from picamera2.outputs import FileOutput
import netifaces

# Configuration
MASTER_PC_IP = '192.168.179.9'  # This should be configurable
MASTER_PC_PORT = 50000
LISTEN_PORT = 50005  # Port to listen for UDP messages
STATUS_INTERVAL = 5  # Interval to send status messages
STORAGE_PATH = 'Recordings'  # Directory to store recordings
EVENT_LOG = 'event_log.txt'  # Event log file

# Initialize camera
picam2 = Picamera2()

# State machine states
STANDBY = 'STANDBY'
RECORDING = 'RECORDING'
TRANSMITTING = 'TRANSMITTING'

state = STANDBY
session_name = ''
recording_file = ''
last_status_time = 0
storage_capacity = 0  # To be updated with actual storage remaining

# Create storage directory if it doesn't exist
if not os.path.exists(STORAGE_PATH):
    os.makedirs(STORAGE_PATH)

# Load camera settings
CAMERA_SETTINGS_FILE = 'camera_settings.json'
with open(CAMERA_SETTINGS_FILE, 'r') as f:
    camera_settings = json.load(f)

# Function to log events
def log_event(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(EVENT_LOG, 'a') as log_file:
        log_file.write(f'[{timestamp}] {message}\n')
    print(f'[{timestamp}] {message}')

# Function to send UDP messages to the master PC
def send_udp_message(message_dict):
    message = json.dumps(message_dict)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(message.encode(), (MASTER_PC_IP, MASTER_PC_PORT))
    sock.close()

# Function to send status messages
def send_status():
    global last_status_time
    current_time = time.time()
    if current_time - last_status_time >= STATUS_INTERVAL:
        message = {
            'task': 'STATUS',
            'state': state,
            'ip': get_ip_address(),
            'storage_remaining_mb': get_storage_remaining(),
            'sessions': get_session_list()
        }
        send_udp_message(message)
        last_status_time = current_time

# Function to get the IP address of the Pi
def get_ip_address():
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        if interface == 'lo':
            continue
        addresses = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addresses:
            for addr_info in addresses[netifaces.AF_INET]:
                ip_addr = addr_info['addr']
                return ip_addr
    return 'Unknown'

# Function to get remaining storage in MB
def get_storage_remaining():
    statvfs = os.statvfs(STORAGE_PATH)
    remaining = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)  # Convert to MB
    return int(remaining)

# Function to get list of sessions
def get_session_list():
    sessions = set()
    for filename in os.listdir(STORAGE_PATH):
        if filename.endswith(('.h264', '.mp4', '.jpg', '.png', '.raw')):
            session = filename.split('_')[0]
            sessions.add(session)
    return list(sessions)

# Function to handle incoming UDP messages
def handle_udp_messages():
    global state, session_name, recording_file
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', LISTEN_PORT))
    while True:
        data, addr = sock.recvfrom(4096)
        message = json.loads(data.decode())
        task = message.get('task')
        if task == 'REC_START':
            if state == STANDBY:
                session_name = message.get('session_name')
                bitrate = int(message.get('bitrate', 15000))  # in Kbps
                start_recording(session_name, bitrate)
        elif task == 'REC_STOP':
            if state == RECORDING:
                stop_recording()
        elif task == 'REC_STILL':
            if state == STANDBY:
                session_name = message.get('session_name')
                compression_format = message.get('compression_format', 'jpeg')
                compression = int(message.get('compression', 100))
                capture_still(session_name, compression_format, compression)
        elif task == 'GET_STORAGE':
            send_storage_info()
        elif task == 'GET_SESSIONS':
            send_sessions_info()
        elif task == 'TRANSMIT_SESSION':
            requested_session = message.get('session_name')
            if requested_session in get_session_list():
                transmit_session(requested_session)
            else:
                log_event(f'Session {requested_session} not found for transmission.')
        elif task == 'DELETE_SESSIONS':
            delete_all_sessions()
        elif task == 'UPDATE_SETTINGS':
            new_settings = message.get('settings')
            if new_settings:
                update_camera_settings(new_settings)
                send_udp_message({'task': 'SETTINGS_UPDATED', 'ip': get_ip_address()})
        # Add additional command handling as needed

# Function to start recording
def start_recording(session_name, bitrate):
    global state, recording_file
    log_event('Starting recording...')
    state = RECORDING
    ip_suffix = get_ip_address().split('.')[-1]
    recording_file = f'{STORAGE_PATH}/{session_name}_{ip_suffix}.h264'
    video_config = picam2.create_video_configuration(
        main={"size": (camera_settings['width'], camera_settings['height'])}
    )
    picam2.configure(video_config)
    encoder = H264Encoder(bitrate * 1000)
    picam2.start_recording(encoder, recording_file)
    log_event(f'Recording started: {recording_file}')

# Function to stop recording
def stop_recording():
    global state
    log_event('Stopping recording...')
    picam2.stop_recording()
    state = STANDBY
    log_event('Recording stopped.')

# Function to capture still image
def capture_still(session_name, compression_format, compression):
    global state
    log_event('Capturing still image...')
    ip_suffix = get_ip_address().split('.')[-1]
    image_file = f'{STORAGE_PATH}/{session_name}_{ip_suffix}.{compression_format}'
    if compression_format.lower() == 'jpeg':
        encoder = MJPEGEncoder(Quality(compression))
    else:
        # Handle other formats as needed
        encoder = None  # Placeholder
    if encoder:
        still_config = picam2.create_still_configuration(
            main={"size": (camera_settings['width'], camera_settings['height'])}
        )
        picam2.configure(still_config)
        picam2.start()
        picam2.capture_file(image_file, encoder=encoder)
        picam2.stop()
        log_event(f'Still image captured: {image_file}')
    else:
        log_event(f'Unsupported image format: {compression_format}')

# Function to send storage info
def send_storage_info():
    message = {
        'task': 'STORAGE_INFO',
        'ip': get_ip_address(),
        'storage_remaining_mb': get_storage_remaining()
    }
    send_udp_message(message)

# Function to send sessions info
def send_sessions_info():
    message = {
        'task': 'SESSIONS_INFO',
        'ip': get_ip_address(),
        'sessions': get_session_list()
    }
    send_udp_message(message)

# Function to transmit session to master PC
def transmit_session(session_name):
    global state
    state = TRANSMITTING
    log_event(f'Transmitting session: {session_name}')
    files_to_transmit = [
        f for f in os.listdir(STORAGE_PATH) if f.startswith(session_name)
    ]
    for file in files_to_transmit:
        local_path = os.path.join(STORAGE_PATH, file)
        remote_path = f'sessions/{session_name}/{file}'
        checksum = calculate_checksum(local_path)
        send_file_to_master(local_path, remote_path, checksum)
    state = STANDBY

# Function to calculate MD5 checksum
def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# Function to send file to master PC (e.g., via SCP)
def send_file_to_master(local_path, remote_path, checksum):
    try:
        scp_command = [
            'scp', local_path, f'pi@{MASTER_PC_IP}:{remote_path}'
        ]
        subprocess.run(scp_command, check=True)
        # Send checksum verification message
        message = {
            'task': 'FILE_TRANSFER_COMPLETE',
            'file': os.path.basename(local_path),
            'checksum': checksum,
            'ip': get_ip_address()
        }
        send_udp_message(message)
        log_event(f'File {local_path} transmitted successfully.')
    except subprocess.CalledProcessError as e:
        log_event(f'Error transmitting file {local_path}: {e}')
        # Send error message
        message = {
            'task': 'FILE_TRANSFER_FAILED',
            'file': os.path.basename(local_path),
            'ip': get_ip_address()
        }
        send_udp_message(message)

# Function to delete all sessions
def delete_all_sessions():
    log_event('Deleting all sessions...')
    for filename in os.listdir(STORAGE_PATH):
        file_path = os.path.join(STORAGE_PATH, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)
    log_event('All sessions deleted.')

# Function to update camera settings
def update_camera_settings(new_settings):
    global camera_settings
    camera_settings.update(new_settings)
    with open(CAMERA_SETTINGS_FILE, 'w') as f:
        json.dump(camera_settings, f)
    log_event('Camera settings updated.')

# Function to periodically send status
def status_update_loop():
    while True:
        send_status()
        time.sleep(1)

# Start UDP listener and status update threads
udp_thread = threading.Thread(target=handle_udp_messages, daemon=True)
status_thread = threading.Thread(target=status_update_loop, daemon=True)

udp_thread.start()
status_thread.start()

# Keep the main thread alive
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log_event('Shutting down.')
