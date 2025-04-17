# remote_capture_controller.py v11

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
from libcamera import controls as libcontrols

EVENT_LOG = 'event_log.txt'
STORAGE_PATH = 'Recordings'
CAMERA_SETTINGS_FILE = 'camera_settings.json'

def get_master_ip_address():
    if len(sys.argv) > 1:
        return sys.argv[1]
    return '10.50.100.2'

def get_custom_lens_position():
    if len(sys.argv) > 2:
        return sys.argv[2]
    return None

MASTER_PC_IP = get_master_ip_address()
CUSTOM_LENS_POSITION = get_custom_lens_position()

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

MASTER_PC_PORT = 50005

STANDBY = 'STANDBY'
PREPARING = 'PREPARING'
RECORDING = 'RECORDING'
PREPARING_STILL = 'PREPARING_STILL'

state = STANDBY
session_name = ''
recording_file = ''
timecode = '00:00:00:00'
fps = 25

if not os.path.exists(STORAGE_PATH):
    os.makedirs(STORAGE_PATH)

default_settings = {
    "width": 1920,
    "height": 1080,
    "frame_rate": 25,
    "shutter_angle": 20,
    "iso": 560,
    "brightness": 0,
    "contrast": 100,
    "saturation": 95,
    "sharpness": 129,
    "auto_exposure": False,
    "flicker_control": "Off",
    "flicker_period": 50,
    "white_balance": "Daylight",
    "red_gain": 1.1,
    "blue_gain": 2.5,
    "af_mode": "manual",
    "lens_position": 0.36
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

    width, _ = picam2.stream_configuration("main")["size"]
    if width > 1920:
        shutter_angle = shutter_angle * 2

    base_exposure_time = (
        (shutter_angle / 360.0) * (1.0 / frame_rate) * 1_000_000
    )
    iso_value = float(settings.get('iso', 100))

    controls["Brightness"] = float(settings.get('brightness', 0)) / 100.0
    controls["Contrast"] = float(settings.get('contrast', 100)) / 100.0
    controls["Saturation"] = float(settings.get('saturation', 100)) / 100.0
    controls["Sharpness"] = float(settings.get('sharpness', 100)) / 100.0

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
            exposure_time = int((1.0 / flicker_period) * 1_000_000)
        else:
            exposure_time = int(base_exposure_time)
        controls["ExposureTime"] = exposure_time
        controls["AnalogueGain"] = iso_value / 100.0

    wb_selection = settings.get('white_balance', 'Auto')
    if wb_selection and wb_selection in ['Manual', '3200K', '4400K', '5600K']:
        controls["AwbEnable"] = False
        if wb_selection == 'Manual':
            red_gain = float(settings.get('red_gain', 1.0))
            blue_gain = float(settings.get('blue_gain', 1.0))
            controls["ColourGains"] = (red_gain, blue_gain)
        else:
            if wb_selection == '3200K':
                controls["ColourGains"] = (1.2, 2.3)
            elif wb_selection == '4400K':
                controls["ColourGains"] = (1.5, 1.8)
            elif wb_selection == '5600K':
                controls["ColourGains"] = (1.8, 1.5)
    else:
        controls["AwbEnable"] = True
        controls["AwbMode"] = getattr(libcontrols.AwbModeEnum, wb_selection, 0) # 0 == Auto WhiteBalance

    if settings.get('af_mode', 'manual') == 'auto':
        controls["AfMode"] = 2
    else:
        controls["AfMode"] = 0

    if CUSTOM_LENS_POSITION is not None:
        controls["LensPosition"] = float(CUSTOM_LENS_POSITION)
        log_event(f"Using custom lens position: {controls['LensPosition']}")
    else:
        controls["LensPosition"] = settings.get('lens_position', 0.36)
        log_event(f"Using default lens position: {controls['LensPosition']}")

    try:
        picam2.set_controls(controls)
    except Exception as e:
        log_event(f"Error applying settings: {e}")

def configure_camera(custom_resolution=None):
    if custom_resolution is not None:
        if custom_resolution == 'FullHD':
            width = 1920
            height = 1080
        elif custom_resolution == 'HD':
            width = 1280
            height = 720
        elif custom_resolution == 'SD':
            width = 640
            height = 480
        elif custom_resolution == 'UHD':
            width = 3840
            height = 2160
        else:
            width = default_settings['width']
            height = default_settings['height']
    else:
        width = default_settings['width']
        height = default_settings['height']

    video_config = picam2.create_video_configuration(
        main={"size": (width, height)}
    )
    picam2.configure(video_config)
    picam2.start()
    picam2.options["quality"] = 100
    apply_settings(default_settings)

configure_camera()
log_event("Camera configured and started.")

def get_storage_remaining():
    statvfs = os.statvfs(STORAGE_PATH)
    remaining = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)
    return int(remaining)

def get_session_list():
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
        base = f.rsplit('_', 1)[0]
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
    try:
        result = subprocess.run(
            ['sudo', 'chronyc', 'makestep'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(result.stdout.decode())
    except subprocess.CalledProcessError as e:
        print(f"Error occurred: {e}")
        print(f"stderr: {e.stderr.decode()}")

def get_formatted_timecode(framerate, timecode_start_time):
    now = timecode_start_time
    frame_fraction = now.microsecond / 1_000_000
    ff = round(frame_fraction * framerate)
    timecode = now.strftime(f"%H:%M:%S:{ff:02d}")
    return timecode

def record_video(session_name, bitrate, start_time):
    controls = {}
    sync_with_ntp()

    global state, recording_file
    state = PREPARING
    log_event("Preparing to start recording.")

    picam2.stop()
    configure_camera()

    ack_msg = {
        'task': 'REC_START_ACK',
        'ip': my_ip,
        'start_time': start_time
    }
    send_message(ack_msg)

    ip_suffix = my_ip.split('.')[-1]
    recording_file = os.path.join(
        STORAGE_PATH, f'{session_name}_{ip_suffix}.h264'
    )
    picam2.stop()

    global fps
    fps = default_settings['frame_rate']

    local_encoder = H264Encoder(int(bitrate) * 1000000)

    picam2.start_encoder(local_encoder, recording_file)

    time.sleep(start_time - time.time())

    start = time.perf_counter()
    picam2.start()
    offset = time.perf_counter() - (start / 2)
    timecode_start_time = datetime.datetime.now()

    state = RECORDING
    log_event(f'Recording started: {recording_file}')

    frame_timestamps = {}
    missing_frames = []
    frame_number = 0

    while state == RECORDING:
        metadata = picam2.capture_metadata()

        if "SensorTimestamp" in metadata and metadata is not None:
            lastSensorTimestamp = frame_timestamps.get(frame_number - 1, None)
            if lastSensorTimestamp is None:
                frame_timestamps[frame_number] = metadata["SensorTimestamp"]
                frame_number = frame_number + 1
            else:
                frame_time = 1 / fps
                timestamp_interval = (
                    abs(lastSensorTimestamp - metadata["SensorTimestamp"])
                ) / 1e9

                if timestamp_interval < (frame_time * 1.1):
                    frame_timestamps[frame_number] = metadata["SensorTimestamp"]
                    frame_number = frame_number + 1
                else:
                    dropped_frames = round(timestamp_interval / frame_time)
                    missing_frames.extend(
                        range(frame_number, frame_number + dropped_frames)
                    )

                    frame_number = frame_number + dropped_frames

                    frame_timestamps[frame_number] = metadata["SensorTimestamp"]
                    frame_number = frame_number + 1

    picam2.stop_recording()

    for dropped_frame in missing_frames:
        frame_timestamps[dropped_frame] = 'dropped'

    frame_timestamps = dict(sorted(frame_timestamps.items()))

    metadata_file = os.path.splitext(recording_file)[0]
    metadata_file = metadata_file + '.json'

    with open(metadata_file, 'w') as f:
        json.dump(frame_timestamps, f)

    print(f"Metadata file saved: {metadata_file}")

    global timecode
    timecode = get_formatted_timecode(fps, timecode_start_time)

def ffmpeg_processing():
    global timecode, recording_file, fps
    recording_file_name = os.path.splitext(recording_file)[0]
    recording_file_name = recording_file_name + '.mp4'

    ffmpeg_cmd = [
        'ffmpeg',
        '-y',  # Overwrite output file if it exists
        '-f', 'h264',  # Input format
        '-r', str(fps),  # Output frame rate
        '-i', recording_file,  # Input from stdin
        '-c:v', 'copy',  # Copy codec (no re-encoding)
        '-timecode', timecode,  # Set starting timecode
        recording_file_name  # Output file
    ]

    try:
        result = subprocess.run(
            ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        log_event(f'FFmpeg processing complete: {recording_file_name}')
        os.remove(recording_file)
    except subprocess.CalledProcessError as e:
        log_event(f'Error processing with FFmpeg: {e}')
        log_event(f'stderr: {e.stderr.decode()}')

def postprocess_video():
    global state
    if state == RECORDING:
        state = STANDBY
        log_event('Recording stopped.')
        time.sleep(0.5)

        try:
            ffmpeg_processing()
            log_event(f'FFmpeg processing complete: {recording_file}')
        except Exception as e:
            log_event(f'Error processing with FFmpeg: {e}')

def record_still(session_name, start_time, session_resolution):
    sync_with_ntp()

    global state
    state = PREPARING_STILL
    log_event("Preparing to capture still.")

    ack_msg = {
        'task': 'REC_STILL_ACK',
        'ip': my_ip,
        'start_time': start_time
    }
    send_message(ack_msg)

    ip_suffix = my_ip.split('.')[-1]
    image_file = os.path.join(STORAGE_PATH, f"{session_name}_{ip_suffix}.jpg")

    picam2.stop()
    configure_camera(session_resolution)

    wait_time = start_time - time.time()
    if wait_time > 0:
        time.sleep(wait_time)

    picam2.capture_file(image_file)
    log_event(f"Still image captured: {image_file}")

    state = STANDBY

def handle_messages():
    global state
    while True:
        try:
            message = dealer_socket.recv_json()
            task = message.get('task')

            if task == 'REC_START':
                t = threading.Thread(
                    target=record_video,
                    args=(
                        message.get('session_name'),
                        message.get('bitrate', '15000'),
                        message.get('start_time', time.time() + 5)
                    ),
                    daemon=True
                )
                t.start()

            elif task == 'REC_STOP':
                postprocess_video()

            elif task == 'REC_STILL':
                t = threading.Thread(
                    target=record_still,
                    args=(
                        message.get('session_name'),
                        message.get('start_time', time.time() + 5),
                        message.get('resolution', 'FullHD')
                    ),
                    daemon=True
                )
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

        except:
            break

def status_update_loop():
    while True:
        send_status()
        time.sleep(1)

def sync_with_ntp_loop():
    while True:
        if state == STANDBY:
            sync_with_ntp()
        time.sleep(60 * 10)

def log_event(message):
    print(message)

def sigint_handler(signum, frame):
    log_event("SIGINT received. Shutting down gracefully.")
    cleanup_and_exit()

def cleanup_and_exit():
    log_event("Stopping threads and cleaning up resources...")
    picam2.close()
    log_event("Shutdown complete.")
    sys.exit(0)

sync_with_ntp()

signal.signal(signal.SIGINT, sigint_handler)

msg_thread = threading.Thread(target=handle_messages, daemon=True)
msg_thread.start()

status_thread = threading.Thread(target=status_update_loop, daemon=True)
status_thread.start()

try:
    log_event("Program started. Press Ctrl+C to exit.")
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log_event('KeyboardInterrupt detected. Shutting down.')
    cleanup_and_exit()
