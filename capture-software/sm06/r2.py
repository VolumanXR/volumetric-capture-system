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

def get_ip_suffix():
    ip = get_ip_address()
    if ip != 'Unknown' and '.' in ip:
        return ip.split('.')[-1]
    return 'unknown'

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

def handle_zmq_messages():
    while True:
        try:
            message = dealer_socket.recv_json()
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
    if not task:
        return
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
    ip_suffix = get_ip_suffix()
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
    ip_suffix = get_ip_suffix()
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

def run_tcp_server():
    def send_json_response(conn, response_dict):
        # Encode response to JSON
        msg = json.dumps(response_dict).encode()
        # Send length of this JSON message (8 bytes, unsigned long long)
        conn.sendall(struct.pack('!Q', len(msg)))
        # Send the JSON message
        conn.sendall(msg)

    def handle_tcp_client(conn, addr):
        global state, session_name, recording_file
        try:
            # First receive the JSON request
            request_data = recvall(conn, 4096)
            if not request_data:
                conn.close()
                return
            request = json.loads(request_data.decode())
            task = request.get('task')
            if task == "GET_SESSIONS":
                sessions = get_session_list()
                response = {"sessions": sessions}
                send_json_response(conn, response)
            elif task == "GET_SESSION_INFO":
                session_name = request.get('session_name')
                file_path = get_session_file_path(session_name)
                if file_path and os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    response = {"status": "OK", "file_size": file_size}
                else:
                    response = {"status": "NOT_FOUND"}
                send_json_response(conn, response)
            elif task == "DELETE_SESSION":
                session_name = request.get('session_name')
                file_path = get_session_file_path(session_name)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        response = {"status": "OK"}
                        log_event(f"Deleted session '{session_name}' for {addr}")
                    except Exception as e:
                        response = {"status": "ERROR", "message": f"Failed to delete file: {str(e)}"}
                        log_event(f"Failed to delete session '{session_name}' for {addr}: {e}")
                else:
                    response = {"status": "ERROR", "message": "File not found"}
                    log_event(f"File for session '{session_name}' not found for {addr}")
                send_json_response(conn, response)
            elif task == "DOWNLOAD_SESSION":
                session_name = request.get('session_name')
                file_path = get_session_file_path(session_name)
                if file_path and os.path.exists(file_path):
                    try:
                        file_size = os.path.getsize(file_path)
                        response = {"status": "OK", "file_size": file_size}
                        send_json_response(conn, response)

                        # Now send the file data
                        with open(file_path, 'rb') as f:
                            while True:
                                data = f.read(4096)
                                if not data:
                                    break
                                conn.sendall(data)
                        log_event(f"File {os.path.basename(file_path)} sent to {addr}")
                    except Exception as e:
                        log_event(f"Error sending file: {e}")
                else:
                    response = {"status": "ERROR", "message": "File not found"}
                    send_json_response(conn, response)
                    log_event(f"File for session {session_name} not found for {addr}")
            else:
                log_event(f"Received unknown TCP task: {task} from {addr}")
        except Exception as e:
            log_event(f"Error handling TCP client {addr}: {e}")
        finally:
            conn.close()

    def get_session_file_path(session_name):
        file_to_send = f"{session_name}_{get_ip_suffix()}.h264"
        file_path = os.path.join(STORAGE_PATH, file_to_send)
        if os.path.exists(file_path):
            return file_path
        else:
            return None

    def get_ip_suffix():
        ip = get_ip_address()
        if ip != 'Unknown' and '.' in ip:
            return ip.split('.')[-1]
        return 'unknown'

    def recvall(conn, n):
        """Receive exactly n bytes or until EOF."""
        data = b''
        while len(data) < n:
            packet = conn.recv(n - len(data))
            if not packet:
                break
            data += packet
        return data

    # Start TCP server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(('', TCP_DOWNLOAD_PORT))  # Listen on all interfaces
        server.listen(5)
        log_event(f"TCP server started on port {TCP_DOWNLOAD_PORT}")
    except Exception as e:
        log_event(f"Failed to start TCP server: {e}")
        return

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()
        except Exception as e:
            log_event(f"Error accepting TCP connection: {e}")

def handle_zmq_messages():
    while True:
        try:
            message = dealer_socket.recv_json()
            handle_task(message)
        except zmq.ZMQError as e:
            logging.error(f"ZMQ Error: {e}")
            break
        except Exception as e:
            logging.error(f"Unexpected Error: {e}")
            break

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

def handle_task(message):
    global state, session_name, recording_file
    task = message.get('task')
    if not task:
        return
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
    ip_suffix = get_ip_suffix()
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
    ip_suffix = get_ip_suffix()
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

def run_tcp_server():
    def send_json_response(conn, response_dict):
        # Encode response to JSON
        msg = json.dumps(response_dict).encode()
        # Send length of this JSON message (8 bytes, unsigned long long)
        conn.sendall(struct.pack('!Q', len(msg)))
        # Send the JSON message
        conn.sendall(msg)

    def handle_tcp_client(conn, addr):
        global state, session_name, recording_file
        try:
            # First receive the JSON request
            request_data = recvall(conn, 4096)
            if not request_data:
                conn.close()
                return
            request = json.loads(request_data.decode())
            task = request.get('task')
            if task == "GET_SESSIONS":
                sessions = get_session_list()
                response = {"sessions": sessions}
                send_json_response(conn, response)
            elif task == "GET_SESSION_INFO":
                session_name = request.get('session_name')
                file_path = get_session_file_path(session_name)
                if file_path and os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    response = {"status": "OK", "file_size": file_size}
                else:
                    response = {"status": "NOT_FOUND"}
                send_json_response(conn, response)
            elif task == "DELETE_SESSION":
                session_name = request.get('session_name')
                file_path = get_session_file_path(session_name)
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        response = {"status": "OK"}
                        log_event(f"Deleted session '{session_name}' for {addr}")
                    except Exception as e:
                        response = {"status": "ERROR", "message": f"Failed to delete file: {str(e)}"}
                        log_event(f"Failed to delete session '{session_name}' for {addr}: {e}")
                else:
                    response = {"status": "ERROR", "message": "File not found"}
                    log_event(f"File for session '{session_name}' not found for {addr}")
                send_json_response(conn, response)
            elif task == "DOWNLOAD_SESSION":
                session_name = request.get('session_name')
                file_path = get_session_file_path(session_name)
                if file_path and os.path.exists(file_path):
                    try:
                        file_size = os.path.getsize(file_path)
                        response = {"status": "OK", "file_size": file_size}
                        send_json_response(conn, response)

                        # Now send the file data
                        with open(file_path, 'rb') as f:
                            while True:
                                data = f.read(4096)
                                if not data:
                                    break
                                conn.sendall(data)
                        log_event(f"File {os.path.basename(file_path)} sent to {addr}")
                    except Exception as e:
                        log_event(f"Error sending file: {e}")
                else:
                    response = {"status": "ERROR", "message": "File not found"}
                    send_json_response(conn, response)
                    log_event(f"File for session {session_name} not found for {addr}")
            else:
                log_event(f"Received unknown TCP task: {task} from {addr}")
        except Exception as e:
            log_event(f"Error handling TCP client {addr}: {e}")
        finally:
            conn.close()

    def get_session_file_path(session_name):
        file_to_send = f"{session_name}_{get_ip_suffix()}.h264"
        file_path = os.path.join(STORAGE_PATH, file_to_send)
        if os.path.exists(file_path):
            return file_path
        else:
            return None

    def get_ip_suffix():
        ip = get_ip_address()
        if ip != 'Unknown' and '.' in ip:
            return ip.split('.')[-1]
        return 'unknown'

    def recvall(conn, n):
        """Receive exactly n bytes or until EOF."""
        data = b''
        while len(data) < n:
            packet = conn.recv(n - len(data))
            if not packet:
                break
            data += packet
        return data

    # Start TCP server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(('', TCP_DOWNLOAD_PORT))  # Listen on all interfaces
        server.listen(5)
        log_event(f"TCP server started on port {TCP_DOWNLOAD_PORT}")
    except Exception as e:
        log_event(f"Failed to start TCP server: {e}")
        exit(1)

    def tcp_server_loop():
        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                log_event(f"Error accepting TCP connection: {e}")

    def zmq_listener():
        while True:
            try:
                message = dealer_socket.recv_json()
                handle_task(message)
            except zmq.ZMQError as e:
                logging.error(f"ZMQ Error: {e}")
                break
            except Exception as e:
                logging.error(f"Unexpected Error: {e}")
                break

    def send_status_periodically():
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

    def start_recording():
        # Placeholder for any additional logic if needed
        pass

    def stop_recording():
        # Placeholder for any additional logic if needed
        pass

    def capture_stills():
        # Placeholder for any additional logic if needed
        pass

    # Start TCP server in a separate thread
    tcp_thread = threading.Thread(target=tcp_server_loop, daemon=True)
    tcp_thread.start()

    # Start ZMQ listener in a separate thread
    zmq_thread = threading.Thread(target=zmq_listener, daemon=True)
    zmq_thread.start()

    # Start sending status updates in a separate thread
    status_thread = threading.Thread(target=send_status_periodically, daemon=True)
    status_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info('Shutting down remote controller.')
        dealer_socket.close()
        context.term()
        server.close()
        os._exit(0)
