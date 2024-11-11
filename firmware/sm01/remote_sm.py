#!/usr/bin/env python3

import socket
import time
import os
import subprocess
import threading
import json
import hashlib
import logging
from datetime import datetime

# Configuration
UDP_PORT = 50005
UDP_BROADCAST_IP = '255.255.255.255'
MASTER_PC_IP = '192.168.179.9'  # Configurable
MASTER_PC_PORT = 50000  # Port to send status updates to
STATUS_INTERVAL = 5  # Seconds
RECORDINGS_FOLDER = 'Recordings'
CAMERA_SETTINGS_FILE = 'camera_settings.json'
EVENT_LOG_FILE = 'event_log.txt'
USE_NTP = True  # Set to False to disable NTP synchronization

# Initialize logging
logging.basicConfig(filename=EVENT_LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize UDP Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', UDP_PORT))

# Get Pi's IP Address
def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

PI_IP_ADDRESS = get_ip_address()
PI_IP_LAST_OCTET = PI_IP_ADDRESS.split('.')[-1]

# States
STANDBY = 'STANDBY'
RECORDING = 'RECORDING'
TRANSMITTING = 'TRANSMITTING'
READY_FOR_TRANSMIT = 'READY_FOR_TRANSMIT'

state = STANDBY
last_status_time = 0
session_name = ''
recording_process = None

# Ensure Recordings folder exists
if not os.path.exists(RECORDINGS_FOLDER):
    os.makedirs(RECORDINGS_FOLDER)

# Load camera settings
with open(CAMERA_SETTINGS_FILE, 'r') as f:
    camera_settings = json.load(f)

# Function to send status to master PC
def send_status():
    global last_status_time
    if time.time() - last_status_time >= STATUS_INTERVAL:
        message = {'status': state, 'ip': PI_IP_ADDRESS}
        sock.sendto(json.dumps(message).encode(), (MASTER_PC_IP, MASTER_PC_PORT))
        last_status_time = time.time()

# Function to handle incoming messages
def handle_message(data, addr):
    global state, session_name, recording_process
    try:
        message = json.loads(data.decode())
        task = message.get('task')
        if task == 'REC_START':
            if state == STANDBY:
                session_name = message.get('session_name', 'Session')
                bitrate = message.get('bitrate', '10000')  # Default to 10 Mbps
                compression_format = message.get('compression_format', 'H.264')
                # Synchronization logic
                start_time = message.get('start_time', None)
                if USE_NTP and start_time:
                    delay = start_time - time.time()
                    if delay > 0:
                        threading.Timer(delay, start_recording, [bitrate]).start()
                else:
                    start_recording(bitrate)
            else:
                logging.warning('Received REC_START while not in STANDBY')
        elif task == 'REC_STOP':
            if state == RECORDING:
                stop_recording()
            else:
                logging.warning('Received REC_STOP while not RECORDING')
        elif task == 'REC_STILL':
            if state == STANDBY:
                session_name = message.get('session_name', 'Session')
                compression_format = message.get('compression_format', 'jpeg')
                compression = message.get('compression', '100')
                take_still_image(compression_format, compression)
            else:
                logging.warning('Received REC_STILL while not in STANDBY')
        elif task == 'GET_STORAGE':
            report_storage()
        elif task == 'GET_SESSIONS':
            report_sessions()
        elif task == 'DELETE_RECORDINGS':
            delete_recordings()
        elif task == 'UPDATE_SETTINGS':
            update_settings(message.get('settings'))
        elif task == 'START_TRANSFER':
            transfer_session = message.get('session_name')
            transfer_file(transfer_session)
        else:
            logging.warning(f'Unknown task received: {task}')
    except json.JSONDecodeError:
        logging.error('Failed to decode incoming message')

# Function to start recording
def start_recording(bitrate):
    global state, recording_process
    state = RECORDING
    video_filename = f"{session_name}_{PI_IP_LAST_OCTET}.h264"
    video_filepath = os.path.join(RECORDINGS_FOLDER, video_filename)
    width = camera_settings.get('width', 1920)
    height = camera_settings.get('height', 1080)
    framerate = camera_settings.get('frame_rate', 30)
    # Start recording using libcamera-vid
    command = [
        'libcamera-vid',
        '--width', str(width),
        '--height', str(height),
        '--framerate', str(framerate),
        '--bitrate', str(int(bitrate) * 1000),
        '--output', video_filepath
    ]
    recording_process = subprocess.Popen(command)
    logging.info(f'Recording started: {video_filepath}')

# Function to stop recording
def stop_recording():
    global state, recording_process
    if recording_process:
        recording_process.send_signal(signal.SIGINT)
        recording_process.wait()
        recording_process = None
        state = READY_FOR_TRANSMIT
        logging.info('Recording stopped')
    else:
        logging.error('No recording process to stop')

# Function to take still image
def take_still_image(format, quality):
    global state
    image_filename = f"{session_name}_{PI_IP_LAST_OCTET}.{format}"
    image_filepath = os.path.join(RECORDINGS_FOLDER, image_filename)
    width = camera_settings.get('width', 1920)
    height = camera_settings.get('height', 1080)
    command = [
        'libcamera-still',
        '--width', str(width),
        '--height', str(height),
        '--quality', quality,
        '--output', image_filepath
    ]
    subprocess.run(command)
    logging.info(f'Still image captured: {image_filepath}')
    state = READY_FOR_TRANSMIT

# Function to report storage
def report_storage():
    statvfs = os.statvfs(RECORDINGS_FOLDER)
    free_space = statvfs.f_frsize * statvfs.f_bavail / (1024 * 1024)  # in MB
    message = {'storage': free_space, 'ip': PI_IP_ADDRESS}
    sock.sendto(json.dumps(message).encode(), (MASTER_PC_IP, MASTER_PC_PORT))
    logging.info(f'Reported storage: {free_space} MB')

# Function to report sessions
def report_sessions():
    sessions = set()
    for filename in os.listdir(RECORDINGS_FOLDER):
        if os.path.isfile(os.path.join(RECORDINGS_FOLDER, filename)):
            session = filename.rsplit('_', 1)[0]
            sessions.add(session)
    message = {'sessions': list(sessions), 'ip': PI_IP_ADDRESS}
    sock.sendto(json.dumps(message).encode(), (MASTER_PC_IP, MASTER_PC_PORT))
    logging.info(f'Reported sessions: {sessions}')

# Function to delete recordings
def delete_recordings():
    for filename in os.listdir(RECORDINGS_FOLDER):
        file_path = os.path.join(RECORDINGS_FOLDER, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)
            logging.info(f'Deleted recording: {file_path}')
    logging.info('All recordings deleted')

# Function to update camera settings
def update_settings(new_settings):
    global camera_settings
    camera_settings.update(new_settings)
    with open(CAMERA_SETTINGS_FILE, 'w') as f:
        json.dump(camera_settings, f)
    logging.info('Camera settings updated')

# Function to transfer file
def transfer_file(session):
    global state
    state = TRANSMITTING
    filename = f"{session}_{PI_IP_LAST_OCTET}.h264"
    filepath = os.path.join(RECORDINGS_FOLDER, filename)
    if not os.path.exists(filepath):
        logging.error(f'File not found: {filepath}')
        state = READY_FOR_TRANSMIT
        return
    # Calculate checksum
    checksum = calculate_checksum(filepath)
    # Transfer file via SCP
    scp_command = ['scp', filepath, f'pi@{MASTER_PC_IP}:/path/to/sessions/{session}/']
    try:
        subprocess.run(scp_command, check=True)
        # Send checksum
        message = {'checksum': checksum, 'session': session, 'ip': PI_IP_ADDRESS}
        sock.sendto(json.dumps(message).encode(), (MASTER_PC_IP, MASTER_PC_PORT))
        logging.info(f'File transferred: {filepath}')
    except subprocess.CalledProcessError as e:
        logging.error(f'SCP failed: {e}')
    state = READY_FOR_TRANSMIT

# Function to calculate checksum
def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except FileNotFoundError:
        return None

# Main loop
def main():
    global state
    sock.setblocking(0)
    logging.info('Raspberry Pi script started')
    while True:
        send_status()
        try:
            data, addr = sock.recvfrom(4096)
            if addr[0] == MASTER_PC_IP or addr[0].startswith('192.168.'):
                handle_message(data, addr)
        except socket.error:
            pass
        time.sleep(0.1)

if __name__ == '__main__':
    main()
