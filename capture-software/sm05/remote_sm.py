# remote_sm.py
import os
import time
import json
import hashlib
import subprocess
import threading
import zmq
import uuid
from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder, MJPEGEncoder, Quality
from picamera2.outputs import FileOutput

EVENT_LOG = 'event_log.txt'
STORAGE_PATH = 'Recordings'
MASTER_PC_IP = '192.168.179.9'  # Set the master PC IP here
MASTER_PC_PORT = 50005

# State machine states
STANDBY = 'STANDBY'
RECORDING = 'RECORDING'
TRANSMITTING = 'TRANSMITTING'

state = STANDBY
session_name = ''
recording_file = ''

if not os.path.exists(STORAGE_PATH):
    os.makedirs(STORAGE_PATH)

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

def log_event(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(EVENT_LOG, 'a') as log_file:
        log_file.write(f'[{timestamp}] {message}\n')

picam2 = Picamera2()

def apply_settings(settings):
    controls = {}
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

    try:
        picam2.set_controls(controls)
    except:
        pass

def configure_camera():
    width = default_settings['width']
    height = default_settings['height']
    video_config = picam2.create_video_configuration(main={"size": (width, height)})
    picam2.configure(video_config)
    picam2.start()
    apply_settings(default_settings)

configure_camera()
log_event("Camera configured and started.")

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

def send_message(socket, message_dict):
    socket.send_json(message_dict)

def start_recording_func(session_name, bitrate, start_time):
    global state, recording_file
    state = 'PREPARING'
    ip_suffix = get_ip_address().split('.')[-1]
    recording_file = f'{STORAGE_PATH}/{session_name}_{ip_suffix}.h264'
    wait_time = start_time - time.time()
    if wait_time > 0:
        time.sleep(wait_time)
    encoder = H264Encoder(int(bitrate)*1000)
    picam2.stop()
    width = default_settings['width']
    height = default_settings['height']
    video_config = picam2.create_video_configuration(main={"size": (width, height)})
    picam2.configure(video_config)
    picam2.start_recording(encoder, recording_file)
    apply_settings(default_settings)
    state = RECORDING
    log_event(f'Recording started: {recording_file}')

def stop_recording_func():
    global state
    if state == RECORDING:
        picam2.stop_recording()
        picam2.start()
        apply_settings(default_settings)
        state = STANDBY
        log_event('Recording stopped.')

def capture_still_func(session_name, compression_format, compression, still_name, start_time):
    ip_suffix = get_ip_address().split('.')[-1]
    image_file = f'{STORAGE_PATH}/{still_name}_{ip_suffix}.{compression_format}'
    wait_time = start_time - time.time()
    if wait_time > 0:
        time.sleep(wait_time)
    picam2.stop()
    width = default_settings['width']
    height = default_settings['height']
    still_config = picam2.create_still_configuration(main={"size": (width, height)})
    picam2.configure(still_config)
    picam2.start()
    apply_settings(default_settings)
    if compression_format.lower() == 'jpeg':
        encoder = MJPEGEncoder(Quality(int(compression)))
    elif compression_format.lower() == 'png':
        encoder = MJPEGEncoder(Quality(int(compression)))  # Picamera2 does not have PNG encoder; use MJPEG and convert if needed
    else:
        encoder = MJPEGEncoder(Quality(int(compression)))
    picam2.capture_file(image_file, encoder=encoder)
    picam2.stop()
    picam2.configure(picam2.create_video_configuration(main={"size": (width, height)}))
    picam2.start()
    apply_settings(default_settings)
    log_event(f'Still image captured: {image_file}')

def send_status(socket):
    msg = {
        'task': 'STATUS',
        'state': state,
        'ip': get_ip_address(),
        'storage_remaining_mb': get_storage_remaining(),
        'sessions': get_session_list()
    }
    send_message(socket, msg)

def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

context = zmq.Context()
dealer_socket = context.socket(zmq.DEALER)
identity = str(uuid.uuid4()).encode()
dealer_socket.setsockopt(zmq.IDENTITY, identity)
dealer_socket.connect(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")

reg_msg = {
    'task': 'REGISTER',
    'ip': get_ip_address()
}
send_message(dealer_socket, reg_msg)

def handle_messages():
    global state, session_name
    while True:
        try:
            message = dealer_socket.recv_json()
            task = message.get('task')
            if task == 'REC_START':
                s_name = message.get('session_name')
                bitrate = message.get('bitrate', '15000')
                start_t = message.get('start_time', time.time()+5)
                t = threading.Thread(target=start_recording_func, args=(s_name, bitrate, start_t))
                t.start()
            elif task == 'REC_STOP':
                stop_recording_func()
            elif task == 'REC_STILL':
                s_name = message.get('session_name')
                c_format = message.get('compression_format', 'jpeg')
                comp = message.get('compression', '100')
                still_n = message.get('still_name', 'Still')
                start_t = message.get('start_time', time.time()+5)
                t = threading.Thread(target=capture_still_func, args=(s_name, c_format, comp, still_n, start_t))
                t.start()
            elif task == 'SYNC_REQUEST':
                master_send_time = message.get('master_send_time')
                pi_receive_time = time.time()
                resp = {
                    'task': 'SYNC_RESPONSE',
                    'ip': get_ip_address(),
                    'master_send_time': master_send_time,
                    'pi_receive_time': pi_receive_time
                }
                send_message(dealer_socket, resp)
            elif task == 'UPDATE_SETTINGS':
                new_settings = message.get('settings', {})
                default_settings.update(new_settings)
                apply_settings(default_settings)
                resp = {
                    'task': 'SETTINGS_UPDATED',
                    'ip': get_ip_address()
                }
                send_message(dealer_socket, resp)
        except:
            break

def status_update_loop():
    while True:
        send_status(dealer_socket)
        time.sleep(5)

msg_thread = threading.Thread(target=handle_messages, daemon=True)
msg_thread.start()

status_thread = threading.Thread(target=status_update_loop, daemon=True)
status_thread.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log_event('Shutting down.')
