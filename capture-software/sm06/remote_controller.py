# remote_controller.py
import zmq
import json
import threading
import uuid
import os
import time
import hashlib
import logging
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, MJPEGEncoder, Quality
import netifaces
import socket
import struct

# Configure logging
logging.basicConfig(filename='remote_controller.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# Configuration
MASTER_PC_IP = '192.168.179.9'  # Set the Master PC IP here
MASTER_PC_PORT = 50005
TCP_DOWNLOAD_PORT = 50006  # Fixed TCP port for downloads
EVENT_LOG = 'event_log.txt'
STORAGE_PATH = 'Recordings'

# Initialize ZMQ Context and DEALER Socket
context = zmq.Context()
dealer_socket = context.socket(zmq.DEALER)
identity = str(uuid.uuid4()).encode()
dealer_socket.setsockopt(zmq.IDENTITY, identity)
dealer_socket.connect(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")

# State machine states
STANDBY = 'STANDBY'
RECORDING = 'RECORDING'
TRANSMITTING = 'TRANSMITTING'

state = STANDBY
session_name = ''
recording_file = ''

# Ensure storage path exists
if not os.path.exists(STORAGE_PATH):
    os.makedirs(STORAGE_PATH)

# Load camera settings
CAMERA_SETTINGS_FILE = 'camera_settings.json'
default_settings = {
    'width': 1920,
    'height': 1080,
    'frame_rate': 25,
    'shutter_angle': 180,
    'iso': 2145,
    'brightness': 0,
    'contrast': 100,
    'saturation': 100,
    'sharpness': 100,
    'auto_exposure': False,
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

# Initialize camera
picam2 = Picamera2()

def log_event(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(EVENT_LOG, 'a') as log_file:
        log_file.write(f'[{timestamp}] {message}\n')
    logging.info(message)

def apply_settings(settings):
    controls = {}
    try:
        frame_rate = float(settings.get('frame_rate', 25))
        controls["FrameRate"] = frame_rate
        shutter_angle = float(settings.get('shutter_angle', 180))
        base_exposure_time = (shutter_angle / 360.0) * (1.0 / frame_rate) * 1_000_000
        iso_value = float(settings.get('iso', 100))

        controls["Brightness"] = float(settings.get('brightness', 0))/100.0
        controls["Contrast"] = float(settings.get('contrast', 100))/100.0
        controls["Saturation"] = float(settings.get('saturation', 100))/100.0
        controls["Sharpness"] = float(settings.get('sharpness', 100))/100.0

        flicker_selection = settings.get('flicker_control', 'Off')
        if flicker_selection == 'Off':
            controls["AeEnable"] = settings.get('auto_exposure', True)
            if not settings.get('auto_exposure', True):
                controls["ExposureTime"] = int(base_exposure_time)
                controls["AnalogueGain"] = iso_value / 100.0
        else:
            controls["AeEnable"] = False
            if flicker_selection == '50Hz':
                exposure_time = int(20000)
            elif flicker_selection == '60Hz':
                exposure_time = int(16667)
            elif flicker_selection == 'Manual':
                flicker_period = float(settings.get('flicker_period', 50))
                exposure_time = int((1.0/flicker_period)*1_000_000)
            else:
                exposure_time = int(base_exposure_time)
            controls["ExposureTime"] = exposure_time
            controls["AnalogueGain"] = iso_value / 100.0

        wb_selection = settings.get('white_balance', 'Auto')
        if wb_selection == 'Auto':
            controls["AwbEnable"] = True
        else:
            controls["AwbEnable"] = False
            if wb_selection == 'Manual':
                red_gain = float(settings.get('red_gain', 1.0))
                blue_gain = float(settings.get('blue_gain', 1.0))
                controls["ColourGains"] = (red_gain, blue_gain)
            else:
                if wb_selection == '3200K':
                    controls["ColourGains"] = (2.3, 1.3)
                elif wb_selection == '4400K':
                    controls["ColourGains"] = (1.8, 1.5)
                elif wb_selection == '5600K':
                    controls["ColourGains"] = (1.5, 1.8)

        picam2.set_controls(controls)
    except Exception as e:
        log_event(f"Failed to apply settings: {e}")

def configure_camera():
    try:
        width = default_settings['width']
        height = default_settings['height']
        video_config = picam2.create_video_configuration(main={"size": (width, height)})
        picam2.configure(video_config)
        picam2.start()
        apply_settings(default_settings)
        log_event("Camera configured and started.")
    except Exception as e:
        log_event(f"Failed to configure and start camera: {e}")
        exit(1)

configure_camera()

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

def get_storage_remaining():
    statvfs = os.statvfs(STORAGE_PATH)
    remaining = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)
    return int(remaining)

def get_session_list():
    sessions = set()
    for filename in os.listdir(STORAGE_PATH):
        if filename.endswith(('.h264', '.mp4', '.jpg', '.png', '.raw')):
            session = filename.split('_')[0]
            sessions.add(session)
    return list(sessions)

def send_status():
    while True:
        msg = {
            'task': 'STATUS',
            'state': state,
            'ip': get_ip_address(),
            'storage_remaining_mb': get_storage_remaining(),
            'sessions': get_session_list()
        }
        try:
            dealer_socket.send_json(msg)
        except zmq.ZMQError as e:
            log_event(f"Failed to send status: {e}")
        time.sleep(5)

def handle_messages():
    while True:
        try:
            message = dealer_socket.recv_json()
            task = message.get('task')
            if task:
                handle_task(message)
        except zmq.ZMQError as e:
            logging.error(f"ZMQ Error: {e}")
            break
        except Exception as e:
            logging.error(f"Unexpected Error: {e}")
            break

def handle_task(message):
    global state, session_name, recording_file
    task = message.get('task')
    if task == 'REC_START':
        s_name = message.get('session_name')
        bitrate = message.get('bitrate', '15000')
        start_t = message.get('start_time', time.time()+5)
        threading.Thread(target=start_recording_func, args=(s_name, bitrate, start_t), daemon=True).start()
    elif task == 'REC_STOP':
        stop_recording_func()
    elif task == 'REC_STILL':
        s_name = message.get('session_name')
        c_format = message.get('compression_format', 'jpeg')
        comp = message.get('compression', '100')
        still_n = message.get('still_name', 'Still')
        start_t = message.get('start_time', time.time()+5)
        threading.Thread(target=capture_still_func, args=(s_name, c_format, comp, still_n, start_t), daemon=True).start()
    elif task == 'SYNC_REQUEST':
        master_send_time = message.get('master_send_time')
        pi_receive_time = time.time()
        resp = {
            'task': 'SYNC_RESPONSE',
            'ip': get_ip_address(),
            'master_send_time': master_send_time,
            'pi_receive_time': pi_receive_time
        }
        try:
            dealer_socket.send_json(resp)
        except zmq.ZMQError as e:
            log_event(f"Failed to send SYNC_RESPONSE: {e}")
    elif task == 'UPDATE_SETTINGS':
        new_settings = message.get('settings', {})
        update_camera_settings(new_settings)
        # Send confirmation
        confirmation = {
            'task': 'SETTINGS_UPDATED',
            'ip': get_ip_address()
        }
        try:
            dealer_socket.send_json(confirmation)
        except zmq.ZMQError as e:
            log_event(f"Failed to send SETTINGS_UPDATED confirmation: {e}")
    # Add more task handlers as needed

def update_camera_settings(new_settings):
    global default_settings
    default_settings.update(new_settings)
    apply_settings(default_settings)
    log_event('Camera settings updated.')

def start_recording_func(s_name, bitrate, start_t):
    global state, recording_file
    state = 'PREPARING'
    ip_suffix = get_ip_address().split('.')[-1]
    recording_file = f'{STORAGE_PATH}/{s_name}_{ip_suffix}.h264'
    wait_time = start_t - time.time()
    if wait_time > 0:
        time.sleep(wait_time)
    try:
        encoder = H264Encoder(int(bitrate)*1000)
        picam2.stop_recording()
        video_config = picam2.create_video_configuration(main={"size": (default_settings['width'], default_settings['height'])})
        picam2.configure(video_config)
        picam2.start_recording(encoder, recording_file)
        apply_settings(default_settings)
        state = RECORDING
        log_event(f'Recording started: {recording_file}')
    except Exception as e:
        log_event(f"Failed to start recording: {e}")

def stop_recording_func():
    global state
    if state == RECORDING:
        try:
            picam2.stop_recording()
            video_config = picam2.create_video_configuration(main={"size": (default_settings['width'], default_settings['height'])})
            picam2.configure(video_config)
            picam2.start_recording()
            apply_settings(default_settings)
            state = STANDBY
            log_event('Recording stopped.')
        except Exception as e:
            log_event(f"Failed to stop recording: {e}")

def capture_still_func(s_name, c_format, comp, still_n, start_t):
    ip_suffix = get_ip_address().split('.')[-1]
    image_file = f'{STORAGE_PATH}/{still_n}_{ip_suffix}.{c_format}'
    wait_time = start_t - time.time()
    if wait_time > 0:
        time.sleep(wait_time)
    try:
        picam2.stop_recording()
        still_config = picam2.create_still_configuration(main={"size": (default_settings['width'], default_settings['height'])})
        picam2.configure(still_config)
        picam2.start()
        apply_settings(default_settings)
        if c_format.lower() == 'jpeg':
            encoder = MJPEGEncoder(Quality(int(comp)))
        elif c_format.lower() == 'png':
            encoder = MJPEGEncoder(Quality(int(comp)))  # Picamera2 does not have PNG encoder; use MJPEG and convert if needed
        else:
            encoder = MJPEGEncoder(Quality(int(comp)))
        picam2.capture_file(image_file, encoder=encoder)
        picam2.stop()
        picam2.configure(picam2.create_video_configuration(main={"size": (default_settings['width'], default_settings['height'])}))
        picam2.start_recording()
        apply_settings(default_settings)
        log_event(f'Still image captured: {image_file}')
    except Exception as e:
        log_event(f"Failed to capture still image: {e}")

def run_status_updater():
    while True:
        try:
            msg = {
                'task': 'STATUS',
                'state': state,
                'ip': get_ip_address(),
                'storage_remaining_mb': get_storage_remaining(),
                'sessions': get_session_list()
            }
            dealer_socket.send_json(msg)
        except zmq.ZMQError as e:
            log_event(f"Failed to send status: {e}")
        time.sleep(5)

if __name__ == '__main__':
    # Start threads for handling messages and sending status
    threading.Thread(target=handle_messages, daemon=True).start()
    threading.Thread(target=send_status, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log_event('Shutting down remote controller.')
        dealer_socket.close()
        context.term()
