# master_controller.py (Kivy version)
import time
import json
import os
import hashlib
import zmq
import threading
import uuid
import statistics
import paramiko
from datetime import datetime
from pathlib import Path

# -- Kivy imports --
import kivy
kivy.require('2.0.0')  # or your minimum required version
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.core.window import Window

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent.parent,  'utils','camera_list.json') 
SESSIONS_DIR = 'sessions'
EVENT_LOG = 'event_log_master.txt'
MASTER_PC_IP = '0.0.0.0'  # Bind to all interfaces
MASTER_PC_PORT = 50005

LASTIME = time.time()
NO_RESPONSE_TIMEOUT = 2.0  # If no status in 2 seconds, show "NO RESPONSE"

def update_dist_time():
    """
    Demonstration function that sets the remote system time via SSH.
    Called once in the debug window creation in the original code.
    """
    try:
        current_time = datetime.now().strftime("%d %b %Y %H:%M:%S")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('10.50.100.5', username='voluman', password='xr')
        command = f'sudo date -s "{current_time}"'
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode('utf-8')
        errors = stderr.read().decode('utf-8')
        if output:
            print("Output:", output)
        if errors:
            print("Errors:", errors)
        client.close()
    except Exception as e:
        print(f"Error occurred: {e}")

class DebugWindow(Popup):
    """
    A Kivy Popup that mimics the Tkinter Toplevel debug window:
    Contains a large Text area (here replaced by a ScrollView + Label),
    plus buttons to clear/pause/resume messages.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = 'VolumanXR - Debug Window'
        self.size_hint = (0.8, 0.8)
        
        # Keep track if messages are paused
        self.paused = False
        
        # Call the original update_dist_time() from your code
        update_dist_time()
        
        # Main layout inside popup
        main_layout = BoxLayout(orientation='vertical', spacing=5, padding=5)
        
        # Scrollable area for messages
        self.message_label = Label(size_hint_y=None, text='')
        self.message_label.bind(texture_size=self._on_label_size_changed)
        
        scroll_view = ScrollView(size_hint=(1, 1))
        scroll_view.add_widget(self.message_label)
        
        main_layout.add_widget(scroll_view)
        
        # Button row
        btn_layout = BoxLayout(orientation='horizontal', size_hint=(1, None), height='40dp', spacing=5)
        
        clear_btn = Button(text='Clear Messages', on_release=self.clear_messages)
        pause_btn = Button(text='Pause Messages', on_release=self.pause_messages)
        resume_btn = Button(text='Resume Messages', on_release=self.resume_messages)
        
        btn_layout.add_widget(clear_btn)
        btn_layout.add_widget(pause_btn)
        btn_layout.add_widget(resume_btn)
        
        main_layout.add_widget(btn_layout)
        
        self.add_widget(main_layout)

    def _on_label_size_changed(self, *args):
        """
        Keep the label's height updated so scrolling works properly.
        """
        self.message_label.height = self.message_label.texture_size[1]
        self.message_label.texture_update()

    def insert_message(self, who, message):
        if not self.paused:
            # Append text
            old_text = self.message_label.text
            new_line = f"{who}: {message}\n"
            self.message_label.text = old_text + new_line

    def clear_messages(self, *args):
        self.message_label.text = ''

    def pause_messages(self, *args):
        self.paused = True

    def resume_messages(self, *args):
        self.paused = False


class MainWindow(BoxLayout):
    """
    This is your main UI container, analogous to the main Tk window in your original code.
    """
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        
        self.debug_window = None
        self.debug_mode = False
        
        self.cameras = []  # Loaded from camera_list.json
        self.camera_status = {}  # ip -> { 'state', 'last_seen', 'storage_remaining_mb', 'sessions', ... }
        self.load_camera_list()
        
        if not os.path.exists(SESSIONS_DIR):
            os.makedirs(SESSIONS_DIR)

        # ZMQ setup
        self.context = zmq.Context()
        self.router_socket = self.context.socket(zmq.ROUTER)
        self.router_socket.bind(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
        self.poller = zmq.Poller()
        self.poller.register(self.router_socket, zmq.POLLIN)

        self.connected_cameras = {}  # identity -> ip
        self.ip_to_identity = {}     # ip -> identity

        # Create sub-widgets
        self.create_widgets()

        # Initialize status for all cameras to "NO RESPONSE"
        for cam in self.cameras:
            ip = cam['ip']
            self.camera_status[ip] = {
                'state': 'NO RESPONSE',
                'last_seen': 0,
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }
        
        # Start threads
        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()


        ### Periodic status check temporarily disabled ###
        
        #self.status_check_thread = threading.Thread(target=self.periodic_status_check, daemon=True)
        #self.status_check_thread.start()
        
        # Schedule UI updates in Kivy main loop
        Clock.schedule_interval(self.update_camera_table, 1/2)  # update twice a second

    def load_camera_list(self):
        with open(CAMERA_LIST_FILE, 'r') as f:
            self.cameras = json.load(f)
            # Remove 'port' usage if present
            for c in self.cameras:
                if 'port' in c:
                    del c['port']

    def create_widgets(self):
        """
        Build the layout, replicating the 'Session Control', 'Still Image Control',
        'Camera Status', and a toggle debug button.
        """
        # -- Session Control --
        session_control = BoxLayout(orientation='horizontal', size_hint=(1, None), height='80dp', spacing=50, padding=50)
        
        session_control.add_widget(Label(text='Session Name:', size_hint=(None, 1), width=150))
        self.session_entry = TextInput(multiline=False, size_hint=(None, 1), width=300)
        session_control.add_widget(self.session_entry)
        
        session_control.add_widget(Label(text='Bitrate (Kbps):', size_hint=(None, 1), width=120))
        self.bitrate_entry = TextInput(multiline=False, size_hint=(None, 1), width=200, text='15000')
        session_control.add_widget(self.bitrate_entry)
        
        start_btn = Button(text='Start Recording', size_hint=(None, 1), width=250, on_release=self.start_recording)
        stop_btn = Button(text='Stop Recording', size_hint=(None, 1), width=250, on_release=self.stop_recording)
        
        session_control.add_widget(start_btn)
        session_control.add_widget(stop_btn)
        
        self.add_widget(session_control)
        
        # -- Still Image Control --
        still_control = BoxLayout(orientation='horizontal', size_hint=(1, None), height='80dp', spacing=50, padding=50)
        
        still_control.add_widget(Label(text='Session Name for Still:', size_hint=(None, 1), width=250))
        self.still_name_entry = TextInput(multiline=False, size_hint=(None, 1), width=300)
        still_control.add_widget(self.still_name_entry)
        
        capture_btn = Button(text='Capture Still Image', size_hint=(None, 1), width=300, on_release=self.capture_stills)
        still_control.add_widget(capture_btn)
        
        self.add_widget(still_control)

        # -- Camera Status --
        # We'll build a 6-column header: (Name, IP, State, Last Seen, Storage Rem., Sessions)
        header = BoxLayout(orientation='horizontal', size_hint=(1, None), height='90dp', padding=5, spacing=5)
        headers = ['Name', 'IP', 'State', 'Last Seen', 'Storage (MB)', 'Sessions']
        col_widths = [200, 300, 250, 200, 200, 1200]
        for h, w in zip(headers, col_widths):
            header.add_widget(Label(text=h, size_hint=(None, None), width=w, bold=True))
        self.add_widget(header)

        # This will be a scrollable area containing status rows
        self.status_layout = GridLayout(cols=6, spacing=5, size_hint_y=None)
        self.status_layout.bind(minimum_height=self.status_layout.setter('height'))

        # Put the status_layout inside a ScrollView
        status_scroll = ScrollView(size_hint=(1, 1))
        status_scroll.add_widget(self.status_layout)
        self.add_widget(status_scroll)

        # -- Debug Toggle --
        debug_layout = BoxLayout(orientation='horizontal', size_hint=(1, None), height='40dp', spacing=5, padding=5)
        debug_btn = Button(text='Toggle Debug Mode', on_release=self.toggle_debug)
        debug_layout.add_widget(debug_btn)
        self.add_widget(debug_layout)

    def update_camera_table(self, dt):
        """
        Periodically called on the Kivy main thread to refresh the camera status display.
        We'll rebuild the rows from self.camera_status.
        """
        self.status_layout.clear_widgets()
        headers = ['Name', 'IP', 'State', 'Last Seen', 'Storage (MB)', 'Sessions']
        col_widths = [200, 300, 250, 200, 200, 1200]

        for ip, status in self.camera_status.items():
            camera = next((c for c in self.cameras if c['ip'] == ip), None)
            name = camera['name'] if camera else 'Unknown'
            state = status.get('state', 'Unknown')
            last_seen = status.get('last_seen', 0)
            last_seen_str = time.strftime('%H:%M:%S', time.localtime(last_seen)) if last_seen > 0 else 'N/A'
            storage = status.get('storage_remaining_mb', 'N/A')
            sessions = ', '.join(status.get('sessions', []))

            row_values = [name, ip, state, last_seen_str, str(storage), sessions]
            for val, w in zip(row_values, col_widths):
                self.status_layout.add_widget(
                    Label(text=val, size_hint=(None, None), width=w, height=30)
                )

    def toggle_debug(self, *args):
        if self.debug_window and self.debug_window.open:  # If open, close it
            self.debug_window.dismiss()
            self.debug_window = None
            self.debug_mode = False
        else:
            self.debug_window = DebugWindow()
            self.debug_window.open()
            self.debug_mode = True

    def log_event(self, message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(EVENT_LOG, 'a') as log_file:
            log_file.write(f'[{timestamp}] {message}\n')
        
        if self.debug_mode and self.debug_window:
            self.debug_window.insert_message('MASTER', message)

    def periodic_status_check(self):
        """
        Background thread function that periodically checks each camera's 'last_seen' time.
        If older than NO_RESPONSE_TIMEOUT seconds, set state to 'NO RESPONSE'.
        """
        global LASTIME
        while self.running:
            current_time = time.time()
            if current_time - LASTIME > 1:
                for ip, status in self.camera_status.items():
                    last_seen = status.get('last_seen', 0)
                    if (current_time - last_seen) > NO_RESPONSE_TIMEOUT:
                        if status['state'] != 'NO RESPONSE':
                            self.camera_status[ip]['state'] = 'NO RESPONSE'
                LASTIME = current_time
            time.sleep(1)

    def receive_loop(self):
        """
        Background thread that listens for ZMQ messages.
        """
        while self.running:
            socks = dict(self.poller.poll(1000))
            if self.router_socket in socks and socks[self.router_socket] == zmq.POLLIN:
                frames = self.router_socket.recv_multipart()
                identity = frames[0]
                message = json.loads(frames[1].decode())
                self.handle_message(identity, message)

    def handle_message(self, identity, message):
        ip = message.get('ip', 'Unknown')
        task = message.get('task')
        
        # Register camera identity -> IP
        if task == 'REGISTER':
            self.connected_cameras[identity] = ip
            self.ip_to_identity[ip] = identity
            self.camera_status[ip] = {
                'state': 'STANDBY',
                'last_seen': time.time(),
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }
            self.log_event(f'Camera registered: {ip}')

        elif task == 'STATUS':
            state = message.get('state')
            storage_remaining = message.get('storage_remaining_mb')
            sessions = message.get('sessions', [])
            self.camera_status.setdefault(ip, {})
            self.camera_status[ip].update({
                'state': state,
                'last_seen': time.time(),
                'storage_remaining_mb': storage_remaining,
                'sessions': sessions
            })

        elif task == 'FILE_TRANSFER_COMPLETE':
            filename = message.get('file')
            checksum = message.get('checksum')
            local_file = os.path.join(SESSIONS_DIR, filename)
            if os.path.exists(local_file):
                local_checksum = self.calculate_checksum(local_file)
                if local_checksum == checksum:
                    self.log_event(f'File {filename} transferred and verified.')
                else:
                    self.log_event(f'Checksum mismatch for file {filename}.')
            else:
                self.log_event(f'File {filename} not found for checksum verification.')

        elif task == 'SETTINGS_UPDATED':
            self.log_event(f'Camera settings updated on {ip}.')

        elif task == 'REC_START_ACK':
            ack_time = message.get('start_time', 0)
            expected_state = self.camera_status[ip].get('pending_start_time', None)
            if expected_state is not None and abs(expected_state - ack_time) < 0.1:
                self.camera_status[ip]['state'] = 'PREPARING'
            else:
                self.camera_status[ip]['state'] = 'SYNC ISSUE'

        elif task == 'REC_STILL_ACK':
            ack_time = message.get('start_time', 0)
            expected_still_time = self.camera_status[ip].get('pending_still_time', None)
            if expected_still_time is not None and abs(expected_still_time - ack_time) < 0.1:
                self.camera_status[ip]['state'] = 'PREPARING_STILL'
            else:
                self.camera_status[ip]['state'] = 'SYNC ISSUE'

        if ip in self.camera_status:
            self.camera_status[ip]['last_seen'] = time.time()

    def send_message(self, ip, message_dict):
        identity = self.ip_to_identity.get(ip)
        if identity:
            self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])

    def broadcast_message(self, message_dict):
        for ip in self.ip_to_identity:
            self.send_message(ip, message_dict)

    def calculate_checksum(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_next_multiple_of_5_sec(self, min_gap=5):
        """
        Same logic as your original code for scheduling the next multiple of 5 seconds.
        """
        now = time.time()
        local_now = time.localtime(now)
        current_sec = local_now.tm_sec
        next_5 = (current_sec // 5 + 1) * 5

        if next_5 >= 60:
            next_5 -= 60
            base_minute = time.mktime((
                local_now.tm_year,
                local_now.tm_mon,
                local_now.tm_mday,
                local_now.tm_hour,
                local_now.tm_min + 1,
                0,  # second
                local_now.tm_wday,
                local_now.tm_yday,
                local_now.tm_isdst
            ))
            candidate_time = base_minute + next_5
        else:
            base_minute = time.mktime((
                local_now.tm_year,
                local_now.tm_mon,
                local_now.tm_mday,
                local_now.tm_hour,
                local_now.tm_min,
                0,
                local_now.tm_wday,
                local_now.tm_yday,
                local_now.tm_isdst
            ))
            candidate_time = base_minute + next_5

        if (candidate_time - now) < min_gap:
            next_5 += 5
            if next_5 >= 60:
                next_5 -= 60
                base_minute = time.mktime((
                    local_now.tm_year,
                    local_now.tm_mon,
                    local_now.tm_mday,
                    local_now.tm_hour,
                    local_now.tm_min + 1,
                    0,
                    local_now.tm_wday,
                    local_now.tm_yday,
                    local_now.tm_isdst
                ))
            candidate_time = base_minute + next_5
        return candidate_time

    def start_recording(self, *args):
        session_name = self.session_entry.text
        bitrate = self.bitrate_entry.text
        if not session_name:
            self.log_event('Error: Please enter a session name for recording.')
            return

        start_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.log_event(f"Scheduling recording at {time.strftime('%H:%M:%S', time.localtime(start_time))}")

        for ip in self.ip_to_identity:
            self.camera_status[ip]['pending_start_time'] = start_time

        for ip in self.ip_to_identity:
            msg = {
                'task': 'REC_START',
                'session_name': session_name,
                'bitrate': bitrate,
                'start_time': start_time
            }
            self.send_message(ip, msg)

    def stop_recording(self, *args):
        for ip in self.ip_to_identity:
            message = {'task': 'REC_STOP'}
            self.send_message(ip, message)
        self.log_event('Sent REC_STOP command.')

    def capture_stills(self, *args):
        session_name = self.still_name_entry.text
        if not session_name:
            self.log_event('Error: Please enter a session name for the still.')
            return
        
        capture_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.log_event(f"Scheduling still capture at {time.strftime('%H:%M:%S', time.localtime(capture_time))}")

        for ip in self.ip_to_identity:
            self.camera_status[ip]['pending_still_time'] = capture_time

        for ip in self.ip_to_identity:
            msg = {
                'task': 'REC_STILL',
                'session_name': session_name,
                'start_time': capture_time
            }
            self.send_message(ip, msg)

    def stop(self):
        """
        Custom cleanup method to stop threads before Kivy app closes.
        Kivy calls app.on_stop() eventually, where we can stop everything safely.
        """
        self.running = False

class MainApp(App):
    """
    The Kivy App class that builds and runs the UI.
    """
    def build(self):
        Window.size = (1200, 800)
        self.title = 'VolumanXR - Camera Control UI'
        self.main_window = MainWindow()
        return self.main_window

    def on_stop(self):
        # Called when the app is closing
        self.main_window.stop()

if __name__ == '__main__':
    MainApp().run()
