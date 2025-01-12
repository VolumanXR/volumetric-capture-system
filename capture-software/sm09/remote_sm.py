# remote_sm.py v0.9

import os
import time
import json
import hashlib
import subprocess
import threading
import uuid
import socket
import struct

import netifaces  # This was used in your get_ip_address() method
import zmq

from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

EVENT_LOG = 'event_log.txt'
STORAGE_PATH = 'Recordings'
CAMERA_SETTINGS_FILE = 'camera_settings.json'

# --------------------
# CONFIGURATION
# --------------------
# Decide how we want to receive commands from the Master:
COMM_MODE = "ZMQ"   # or "TCP" or "UDP"
# Master IP detection logic
def get_ip_address():
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
    # fallback
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
    Simple example that sets some camera controls. 
    Expand or revise as needed (ISO, exposure time, etc.).
    """
    controls = {"FrameRate": float(settings.get('frame_rate', 25))}
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
        if filename.lower().endswith(('.h264', '.mp4', '.jpg', '.jpeg', '.png')):
            session = filename.split('_')[0]
            sessions.add(session)
    return list(sessions)

def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# ---------------
# ZMQ Setup
# ---------------
context = zmq.Context()
dealer_socket = context.socket(zmq.DEALER)
identity_str = str(uuid.uuid4())
dealer_socket.setsockopt(zmq.IDENTITY, identity_str.encode())

def send_message_zmq(message_dict):
    dealer_socket.send_json(message_dict)

def register_with_master_zmq():
    reg_msg = {
        'task': 'REGISTER',
        'ip': my_ip
    }
    send_message_zmq(reg_msg)

def send_status_zmq():
    msg = {
        'task': 'STATUS',
        'state': state,
        'ip': my_ip,
        'storage_remaining_mb': get_storage_remaining(),
        'sessions': get_session_list()
    }
    send_message_zmq(msg)

# ---------------
# Common command handlers
# ---------------
def recording_starter(session_name, bitrate, start_time):
    global state, recording_file
    state = PREPARING
    log_event("Preparing to start recording.")

    # Acknowledge (for ZMQ)
    if COMM_MODE == "ZMQ":
        ack_msg = {
            'task': 'REC_START_ACK',
            'ip': my_ip,
            'start_time': start_time
        }
        send_message_zmq(ack_msg)

    ip_suffix = my_ip.split('.')[-1]
    recording_file = os.path.join(STORAGE_PATH, f'{session_name}_{ip_suffix}.h264')
    picam2.stop()
    width = default_settings['width']
    height = default_settings['height']
    video_config = picam2.create_video_configuration(main={"size": (width, height)})
    picam2.configure(video_config)

    picam2.start()
    apply_settings(default_settings)

    local_encoder = H264Encoder(int(bitrate) * 1000)

    # Wait spin
    while time.time() < start_time:
        time.sleep(0.01)

    picam2.start_recording(local_encoder, recording_file)
    state = RECORDING
    log_event(f'Recording started: {recording_file}')

def stop_recording_func():
    global state
    if state == RECORDING:
        picam2.stop_recording()
        configure_camera()
        state = STANDBY
        log_event('Recording stopped.')

def still_starter(session_name, start_time):
    global state
    state = PREPARING_STILL
    log_event("Preparing to capture still.")

    # Acknowledge (for ZMQ)
    if COMM_MODE == "ZMQ":
        ack_msg = {
            'task': 'REC_STILL_ACK',
            'ip': my_ip,
            'start_time': start_time
        }
        send_message_zmq(ack_msg)

    wait_time = start_time - time.time()
    if wait_time > 0:
        time.sleep(wait_time)

    ip_suffix = my_ip.split('.')[-1]
    image_file = os.path.join(STORAGE_PATH, f"{session_name}_{ip_suffix}.jpg")
    picam2.capture_file(image_file)
    log_event(f"Still image captured: {image_file}")
    state = STANDBY

def apply_updated_settings(new_settings):
    default_settings.update(new_settings)
    apply_settings(default_settings)
    if COMM_MODE == "ZMQ":
        resp = {'task': 'SETTINGS_UPDATED','ip': my_ip}
        send_message_zmq(resp)

def handle_command(cmd):
    """
    Single place to handle tasks, whether received from ZMQ, TCP, or UDP.
    """
    global state
    task = cmd.get('task')
    if task == 'REC_START':
        s_name = cmd.get('session_name')
        bitrate = cmd.get('bitrate', '15000')
        start_t = cmd.get('start_time', time.time() + 5)
        t = threading.Thread(target=recording_starter, args=(s_name, bitrate, start_t), daemon=True)
        t.start()

    elif task == 'REC_STOP':
        stop_recording_func()

    elif task == 'REC_STILL':
        s_name = cmd.get('session_name')
        start_t = cmd.get('start_time', time.time() + 5)
        t = threading.Thread(target=still_starter, args=(s_name, start_t), daemon=True)
        t.start()

    elif task == 'UPDATE_SETTINGS':
        new_settings = cmd.get('settings', {})
        apply_updated_settings(new_settings)

# ---------------
# ZMQ handlers
# ---------------
def handle_messages_zmq():
    while True:
        try:
            message = dealer_socket.recv_json()
            handle_command(message)
        except:
            break

def status_update_loop_zmq():
    while True:
        send_status_zmq()
        time.sleep(1)

# ---------------
# TCP approach
# ---------------
def tcp_server():
    """
    Listens on MASTER_PC_PORT for incoming JSON commands over TCP.
    E.g. master_controller could connect() and send the JSON commands.
    """
    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("0.0.0.0", MASTER_PC_PORT))
    srv_sock.listen(5)
    log_event(f"TCP server listening on 0.0.0.0:{MASTER_PC_PORT}")
    while True:
        conn, addr = srv_sock.accept()
        threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()

def handle_tcp_client(conn, addr):
    try:
        data = conn.recv(4096)
        if not data:
            conn.close()
            return
        try:
            message = json.loads(data.decode('utf-8'))
            handle_command(message)
        except json.JSONDecodeError:
            pass
    except Exception as e:
        log_event(f"Error in handle_tcp_client from {addr}: {e}")
    finally:
        conn.close()

# ---------------
# UDP approach
# ---------------
def udp_server():
    """
    Listens on MASTER_PC_PORT for incoming JSON commands over UDP.
    """
    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv_sock.bind(("0.0.0.0", MASTER_PC_PORT))
    log_event(f"UDP server listening on 0.0.0.0:{MASTER_PC_PORT}")
    while True:
        data, addr = srv_sock.recvfrom(4096)
        try:
            message = json.loads(data.decode('utf-8'))
            handle_command(message)
        except Exception as e:
            log_event(f"Error in handle_udp_server from {addr}: {e}")

# ---------------
# Main entry
# ---------------
if __name__ == "__main__":

    # If using ZMQ for status + registration
    if COMM_MODE == "ZMQ":
        dealer_socket.connect(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
        register_with_master_zmq()

        msg_thread = threading.Thread(target=handle_messages_zmq, daemon=True)
        msg_thread.start()

        status_thread = threading.Thread(target=status_update_loop_zmq, daemon=True)
        status_thread.start()

    # If using TCP or UDP, we might not do an explicit "register" unless 
    # the master polls or you want to replicate that logic. 
    # We'll just open the server side for commands:
    elif COMM_MODE == "TCP":
        # Could add a background thread that sends status somewhere,
        # or you rely on master polling or a different approach.
        threading.Thread(target=tcp_server, daemon=True).start()

    elif COMM_MODE == "UDP":
        # same approach
        threading.Thread(target=udp_server, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log_event('Shutting down.')
