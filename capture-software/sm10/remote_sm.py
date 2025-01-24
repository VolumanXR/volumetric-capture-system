# remote_sm.py v10.4

import os
import time
import json
import hashlib
import subprocess
import threading
import zmq
import uuid
import sys
import signal
import datetime

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
timecode = '00:00:00:00'

if not os.path.exists(STORAGE_PATH):
    os.makedirs(STORAGE_PATH)

default_settings = {
    "width": 1920,
    "height": 1080,
    "frame_rate": 25,
    "shutter_angle": 20,
    "iso": 864,
    "brightness": 0,
    "contrast": 100,
    "saturation": 95,
    "sharpness": 129,
    "auto_exposure": False,
    "flicker_control": "Off",
    "flicker_period": 50,
    "white_balance": "Auto",
    "red_gain": 1.1,
    "blue_gain": 2.5,
    "af_mode": "manual",
    "lens_position": 0.58
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
    
    if settings.get('af_mode', 'manual') == 'auto':
        controls["AfMode"] = 2
    else:
        controls["AfMode"] = 0
    controls["LensPosition"] = settings.get('lens_position', 0.58)

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
    
    # sessions = set()
    # for filename in os.listdir(STORAGE_PATH):
    #     if filename.endswith(('.h264', '.mp4', '.jpg', '.jpeg', '.png')):
    #         session = filename.split('_')[0]
    #         sessions.add(session)
    # return list(sessions)
    
    files = [
        f for f in os.listdir(STORAGE_PATH)
        if f.endswith(('.mp4', '.jpg'))
    ]
    files_with_mtime = [
        (f, os.path.getmtime(os.path.join(STORAGE_PATH, f)))
        for f in files
    ]
    sorted_files = sorted(files_with_mtime, key=lambda x: x[1], reverse=True)
    latest_files = []
    for f, _ in sorted_files[:3]:
        base = f.split('_')[0]
        if f.endswith('.jpg'):
            base = f"[I] {base}"
        elif f.endswith('.mp4'):
            base = f"[V] {base}"
        latest_files.append(base)
    if len(sorted_files) > 3:
        latest_files.append("...")
    return latest_files

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

def get_current_timecode(framerate, timecode_start_time):
    """
    Returns the current system time formatted as a timecode string.
    Format: HH:MM:SS:FF where FF is the frame number within the current second.
    """
    now = datetime.datetime.now()
    frame_fraction = now.microsecond / 1_000_000  # Fraction of the current second
    ff = round(frame_fraction * framerate)
    timecode = now.strftime(f"%H:%M:%S:{ff:02d}")
    return timecode

def recording_starter(session_name, bitrate, start_time):
    controls = {}
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
    
    ### Doppelt 
    # width = default_settings['width']
    # height = default_settings['height']
    fps = default_settings['frame_rate']
    # video_config = picam2.create_video_configuration(main={"size": (width, height)})
    # picam2.configure(video_config)

    # # picam2.start()
    # apply_settings(default_settings)

    # We can set a new encoder
    local_encoder = H264Encoder(int(bitrate) * 1000000)

    # while time.time() < start_time:
    #     time.sleep(0.015)
    
    picam2.start_encoder(local_encoder, recording_file)
    
    time.sleep(start_time - time.time())
    
    start = time.perf_counter()
    picam2.start()
    offset = time.perf_counter() - (start / 2)
    timecode_start_time = datetime.datetime.now()
    # timecode_start_time = timecode_start_time - datetime.timedelta(seconds=offset)
    
    state = RECORDING
    log_event(f'Recording started: {recording_file}')
    global timecode
    timecode = get_current_timecode(fps, timecode_start_time)

def ffmpeg_processing():
    global timecode, recording_file
    recording_file_name = os.path.splitext(recording_file)[0]
    recording_file_name = recording_file_name + '.mp4'
    
        # Define the FFmpeg command
    ffmpeg_cmd = [
        'ffmpeg',
        '-y',  # Overwrite output file if it exists
        '-f', 'h264',  # Input format
        '-i', recording_file,  # Input from stdin
        '-c', 'copy',  # Copy codec (no re-encoding)
        '-timecode', timecode,  # Set starting timecode
        recording_file_name  # Output file
    ]
    
    # Run the FFmpeg command
    try:
        result = subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log_event(f'FFmpeg processing complete: {recording_file_name}')
        # Delete the original .h264 file
        os.remove(recording_file)
    except subprocess.CalledProcessError as e:
        log_event(f'Error processing with FFmpeg: {e}')
        log_event(f'stderr: {e.stderr.decode()}')
        
        

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
    
        # Add FFmpeg processing
        try:
            ffmpeg_processing()
            log_event(f'FFmpeg processing complete: {recording_file}')
        except Exception as e:
            log_event(f'Error processing with FFmpeg: {e}')

def still_starter(session_name, start_time):
    """
    At start_time, capture a single still image (JPEG).
    """
    # Force sync with NTP server
    sync_with_ntp()
    
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
        time.sleep(60*10)

# Function to log events
def log_event(message):
    print(message)  # Replace with your actual logging mechanism

# Function to handle SIGINT
def sigint_handler(signum, frame):
    log_event("SIGINT received. Shutting down gracefully.")
    # Perform cleanup here
    cleanup_and_exit()

# Cleanup function
def cleanup_and_exit():
    log_event("Stopping threads and cleaning up resources...")
    # If you have any specific cleanup logic, add it here.
    # Threads with `daemon=True` will exit automatically when the main program exits.
    picam2.close()
    log_event("Shutdown complete.")
    sys.exit(0)

# update ntp time at start
sync_with_ntp()

# Register SIGINT handler
signal.signal(signal.SIGINT, sigint_handler)

# Start threads
msg_thread = threading.Thread(target=handle_messages, daemon=True)
msg_thread.start()

status_thread = threading.Thread(target=status_update_loop, daemon=True)
status_thread.start()

# ntp_thread = threading.Thread(target=sync_with_ntp_loop, daemon=True)
# ntp_thread.start()

try:
    log_event("Program started. Press Ctrl+C to exit.")
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log_event('KeyboardInterrupt detected. Shutting down.')
    cleanup_and_exit()
