# remote_sm.py v8.4

import os
import time
import json
import hashlib
import subprocess
import threading
import zmq
import uuid

from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

EVENT_LOG = 'event_log.txt'
STORAGE_PATH = 'Recordings'
CAMERA_SETTINGS_FILE = 'camera_settings.json'

# Decide MASTER_PC_IP based on our IP
def get_ip_address():
    import netifaces
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        if interface == 'lo':
            continue
        addresses = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addresses:
            for addr_info in addresses[netifaces.AF_INET]:
                return addr_info['addr']
    return 'Unknown'

my_ip = get_ip_address()
if my_ip.startswith("192.168.179."):
    MASTER_PC_IP = "192.168.179.9"
elif my_ip.startswith("10.50.100."):
    MASTER_PC_IP = "10.50.100.2"
else:
    # Fallback if you have more subnets
    MASTER_PC_IP = "192.168.179.9"

MASTER_PC_PORT = 50005

# State machine states
STANDBY = 'STANDBY'
PREPARING = 'PREPARING'
RECORDING = 'RECORDING'
PREPARING_STILL = 'PREPARING_STILL'
TRANSMITTING = 'TRANSMITTING'  # Not used here, but left for completeness

state = STANDBY
session_name = ''
recording_file = ''

if not os.path.exists(STORAGE_PATH):
    os.makedirs(STORAGE_PATH)

default_settings = {
    'width': 1920,
    'height': 1080,
    'frame_rate': 25,
    # Additional exposure/ISO settings omitted for brevity, or set to defaults:
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
    'red_gain': 1.1,
    'blue_gain': 2.5
}
if os.path.exists(CAMERA_SETTINGS_FILE):
    with open(CAMERA_SETTINGS_FILE, 'r') as f:
        saved_settings = json.load(f)
        default_settings.update(saved_settings)

def log_event(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(EVENT_LOG, 'a') as log_file:
        log_file.write(f'[{timestamp}] {message}\n')

picam2 = Picamera2()
encoder = None

def apply_settings(settings):
    """
    Simple example that sets some controls. 
    You can expand it as needed to handle manual exposure, white balance, etc.
    """
    controls = {
        "FrameRate": float(settings.get('frame_rate', 25))
    }
    try:
        picam2.set_controls(controls)
    except Exception as e:
        log_event(f"Error applying settings: {e}")

def configure_camera():
    width = default_settings['width']
    height = default_settings['height']
    video_config = picam2.create_video_configuration(main={"size": (width, height)})
    picam2.configure(video_config)
    picam2.start()
    apply_settings(default_settings)

configure_camera()
log_event("Camera configured and started.")

def get_storage_remaining():
    statvfs = os.statvfs(STORAGE_PATH)
    remaining = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)
    return int(remaining)

def get_session_list():
    sessions = set()
    for filename in os.listdir(STORAGE_PATH):
        if filename.endswith(('.h264', '.mp4', '.jpg', '.jpeg', '.png')):
            session = filename.split('_')[0]
            sessions.add(session)
    return list(sessions)

def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

context = zmq.Context()
dealer_socket = context.socket(zmq.DEALER)
identity_str = str(uuid.uuid4())
dealer_socket.setsockopt(zmq.IDENTITY, identity_str.encode())
dealer_socket.connect(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")

def send_message(message_dict):
    dealer_socket.send_json(message_dict)

# Register with the master
reg_msg = {
    'task': 'REGISTER',
    'ip': my_ip
}
send_message(reg_msg)

def send_status():
    msg = {
        'task': 'STATUS',
        'state': state,
        'ip': my_ip,
        'storage_remaining_mb': get_storage_remaining(),
        'sessions': get_session_list()
    }
    send_message(msg)

def sync_with_ntp():
        # Force synch with NTP server
    try:
        # Running the 'sudo chronyc makestep' command
        result = subprocess.run(['sudo', 'chronyc', 'makestep'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(result.stdout.decode())  # Print the standard output of the command
    except subprocess.CalledProcessError as e:
        print(f"Error occurred: {e}")
        print(f"stderr: {e.stderr.decode()}")  # Print the standard error output if any

def recording_starter(session_name, bitrate, start_time):
    """
    At start_time, begin recording with the specified settings.
    """
    sync_with_ntp()

    global state, recording_file
    state = PREPARING
    log_event("Preparing to start recording.")

    # Acknowledge to Master that we received the start_time correctly
    ack_msg = {
        'task': 'REC_START_ACK',
        'ip': my_ip,
        'start_time': start_time
    }
    send_message(ack_msg)

    # wait_time = start_time - time.time()
    # if wait_time > 0:
    #    time.sleep(wait_time)
    
    
    # Actual start of recording
    ip_suffix = my_ip.split('.')[-1]
    recording_file = os.path.join(STORAGE_PATH, f'{session_name}_{ip_suffix}.h264')
    picam2.stop()
    width = default_settings['width']
    height = default_settings['height']
    video_config = picam2.create_video_configuration(main={"size": (width, height)})
    picam2.configure(video_config)

    picam2.start()
    apply_settings(default_settings)

    # We can set a new encoder
    local_encoder = H264Encoder(int(bitrate) * 1000)

    while time.time() < start_time:
        time.sleep(0.015)

    picam2.start_recording(local_encoder, recording_file)
    
    state = RECORDING
    log_event(f'Recording started: {recording_file}')

def stop_recording_func():
    """
    Stop the recording if we are in RECORDING state.
    """
    global state
    if state == RECORDING:
        picam2.stop_recording()
        # Reconfigure camera in a default video mode
        configure_camera()
        state = STANDBY
        log_event('Recording stopped.')

def still_starter(session_name, start_time):
    """
    At start_time, capture a single still image (JPEG).
    """
    global state
    state = PREPARING_STILL
    log_event("Preparing to capture still.")

    # Acknowledge to Master
    ack_msg = {
        'task': 'REC_STILL_ACK',
        'ip': my_ip,
        'start_time': start_time
    }
    send_message(ack_msg)

    wait_time = start_time - time.time()
    if wait_time > 0:
        time.sleep(wait_time)

    # Just capture a file in the current running config
    ip_suffix = my_ip.split('.')[-1]
    image_file = os.path.join(STORAGE_PATH, f"{session_name}_{ip_suffix}.jpg")

    # We can do this on the live video config
    picam2.capture_file(image_file)
    log_event(f"Still image captured: {image_file}")

    # Return to STANDBY
    state = STANDBY

def handle_messages():
    global state
    while True:
        try:
            message = dealer_socket.recv_json()
            task = message.get('task')

            if task == 'REC_START':
                s_name = message.get('session_name')
                bitrate = message.get('bitrate', '15000')
                start_t = message.get('start_time', time.time()+5)
                t = threading.Thread(target=recording_starter, args=(s_name, bitrate, start_t), daemon=True)
                t.start()

            elif task == 'REC_STOP':
                stop_recording_func()

            elif task == 'REC_STILL':
                s_name = message.get('session_name')
                start_t = message.get('start_time', time.time()+5)
                t = threading.Thread(target=still_starter, args=(s_name, start_t), daemon=True)
                t.start()

            elif task == 'UPDATE_SETTINGS':
                new_settings = message.get('settings', {})
                default_settings.update(new_settings)
                apply_settings(default_settings)
                resp = {
                    'task': 'SETTINGS_UPDATED',
                    'ip': my_ip
                }
                send_message(resp)

            # We do not need the old SYNC_REQUEST logic anymore, 
            # because we assume NTP is active. So we remove it.

        except:
            break

def status_update_loop():
    """
    Periodically send status to the master.
    """
    while True:
        send_status()
        time.sleep(1)

def sync_with_ntp_loop():
    """
    Periodically sync with NTP server.
    """
    while True:
        if state == STANDBY:
            sync_with_ntp()
        time.sleep(60*5)

# Start threads
msg_thread = threading.Thread(target=handle_messages, daemon=True)
msg_thread.start()

status_thread = threading.Thread(target=status_update_loop, daemon=True)
status_thread.start()

ntp_thread = threading.Thread(target=sync_with_ntp_loop, daemon=True)
ntp_thread.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log_event('Shutting down.')
