import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
import os
import hashlib
import zmq
import pygame
from enum import Enum
from lib import config as cfg
from lib import ssh_utils as su

EVENT_LOG = 'event_log_master.txt'
MASTER_PC_IP = '0.0.0.0'
MASTER_PC_PORT = 50005

LASTIME = time.time()

NO_RESPONSE_TIMEOUT = 2.0

class State(Enum):
    STILL_RECORDING = 1	
    VIDEO_RECORDING = 2
    STANDBY = 3

class DebugWindow(tk.Toplevel):
    def __init__(self, master, on_close_callback=None):
        super().__init__(master)
        self.title('VolumanXR - Debug Window')
        self.on_close_callback = on_close_callback
        self.geometry('1790x300')
        self.geometry('+0+700')

        if os.path.exists(cfg.ICON_PATH):
            self.iconbitmap(cfg.ICON_PATH)

        self.create_widgets()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

    def _handle_close(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

    def create_widgets(self):
        self.text = tk.Text(self)
        self.text.pack(fill='both', expand=True)

        control_frame = ttk.Frame(self)
        control_frame.pack(fill='x', padx=5, pady=5)

        clear_messages_button = ttk.Button(control_frame, text='Clear Messages', command=self.clear_messages)
        clear_messages_button.grid(row=0, column=0, padx=5, pady=5)

        pause_messages_button = ttk.Button(control_frame, text='Pause Messages', command=self.pause_messages)
        pause_messages_button.grid(row=0, column=1, padx=5, pady=5)

        resume_messages_button = ttk.Button(control_frame, text='Resume Messages', command=self.resume_messages)
        resume_messages_button.grid(row=0, column=2, padx=5, pady=5)

    def insert_message(self, who, message):
        self.text.config(state='normal')
        self.text.insert('end', f'{who}: {message}\n')
        self.text.see('end')

    def clear_messages(self):
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        
    def pause_messages(self):
        self.text.config(state='disabled')
        
    def resume_messages(self):
        self.text.config(state='normal')


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title('VolumanXR - Capture Controller')
        self.debug_window = None
        self.debug_mode = False
        self.current_state = State.STANDBY
        
        if os.path.exists(cfg.ICON_PATH):
            root.iconbitmap(cfg.ICON_PATH)

        self.cameras = []
        self.camera_status = {}
        self.cameras = load_camera_list(cfg.CAMERA_LIST_FILE)

        self.context = zmq.Context()
        self.router_socket = self.context.socket(zmq.ROUTER)
        self.router_socket.bind(f"tcp://{MASTER_PC_IP}:{MASTER_PC_PORT}")
        self.poller = zmq.Poller()
        self.poller.register(self.router_socket, zmq.POLLIN)

        self.connected_cameras = {}
        self.ip_to_identity = {}

        pygame.mixer.init()
        self.sound_still_trigger = pygame.mixer.Sound(os.path.join(cfg.RES_FOLDER,'202741__preilly11__eos-shutter-1.wav'))
        self.sound_still_triggered = False

        self.sound_video_preroll = pygame.mixer.Sound(os.path.join(cfg.RES_FOLDER,'short_beep.wav'))

        self.sound_video_preroll_triggerd_3 = False
        self.sound_video_preroll_triggerd_2 = False
        self.sound_video_preroll_triggerd_1 = False

        self.sound_video_trigger = pygame.mixer.Sound(os.path.join(cfg.RES_FOLDER,'long_beep.wav'))
        self.sound_video_triggered = False

        self.create_widgets()
        self.start_up()

        for cam in self.cameras:
            ip = cam['ip']
            self.camera_status[ip] = {
                'state': 'NO RESPONSE',
                'last_seen': 0,
                'storage_remaining_mb': 'N/A',
                'sessions': []
            }

        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_loop, daemon=True)
        self.receive_thread.start()

        self.update_status_tree_loop()
        self.status_check_loop()

    def create_widgets(self):
        session_frame = ttk.LabelFrame(self.root, text='Session Control')
        session_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(session_frame, text='Session Name:').grid(row=0, column=0, padx=5, pady=5)
        self.session_entry = ttk.Entry(session_frame)
        self.session_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(session_frame, text='Bitrate (Mbps):').grid(row=1, column=0, padx=5, pady=5)
        self.bitrate_entry = ttk.Entry(session_frame)
        self.bitrate_entry.insert(0, '15')
        self.bitrate_entry.grid(row=1, column=1, padx=5, pady=5)

        start_button = ttk.Button(session_frame, text='Start Recording', command=self.start_video_recording)
        start_button.grid(row=2, column=0, padx=5, pady=5)

        stop_button = ttk.Button(session_frame, text='Stop Recording', command=self.stop_video_recording)
        stop_button.grid(row=2, column=1, padx=5, pady=5)

        still_frame = ttk.LabelFrame(self.root, text='Still Image Control')
        still_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(still_frame, text='Session Name for Still:').grid(row=0, column=0, padx=5, pady=5)
        self.still_name_entry = ttk.Entry(still_frame)
        self.still_name_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(still_frame, text='Resolution:').grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.resolution_still = tk.StringVar()
        self.resolution_still.set('FullHD')
        resolution_still_menu = ttk.OptionMenu(still_frame, self.resolution_still, 'FullHD', 'SD', 'HD', 'FullHD', 'UHD')
        resolution_still_menu.grid(row=1, column=1, padx=5, pady=5, sticky='ew')

        capture_button = ttk.Button(still_frame, text='Capture Still Image', command=self.capture_stills)
        capture_button.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='w')
        
        session_info_frame = ttk.LabelFrame(self.root, text='Session Info')
        session_info_frame.pack(fill='x', padx=5, pady=5)
        
        ttk.Label(session_info_frame, text='Start Time:').grid(row=0, column=0, padx=5, pady=5)
        self.start_time_label = ttk.Label(session_info_frame, text='N/A')
        self.start_time_label.grid(row=0, column=1, padx=5, pady=5)
        
        self.countdown_label = ttk.Label(session_info_frame, text='Countdown:')
        self.countdown_label.grid(row=1, column=0, padx=5, pady=5)
        self.countdown_value = ttk.Label(session_info_frame, text='N/A')
        self.countdown_value.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(session_info_frame, text='Status:').grid(row=2, column=0, padx=5, pady=5)
        self.status_label = ttk.Label(session_info_frame, text='N/A')
        self.status_label.grid(row=2, column=1, padx=5, pady=5)
        
        self.status_color = tk.Canvas(session_info_frame, width=20, height=20)
        self.status_color.grid(row=2, column=2, padx=5, pady=5)
        self.status_color.create_rectangle(0, 0, 40, 40, fill='green')
        
        status_frame = ttk.LabelFrame(self.root, text='Camera Status')
        status_frame.pack(fill='both', expand=True, padx=5, pady=5)

        columns = ('Name', 'IP', 'State', 'Last Seen', 'Storage Remaining (MB)', 'Sessions')
        self.status_tree = ttk.Treeview(status_frame, columns=columns, show='headings')
        for col in columns:
            self.status_tree.heading(col, text=col)
        self.status_tree.pack(fill='both', expand=True)

        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=5, pady=5)

        debug_button = ttk.Button(control_frame, text='Toggle Debug Mode', command=self.toggle_debug)
        debug_button.grid(row=0, column=0, padx=5, pady=5)
        
        self.connected_label = ttk.Label(control_frame, text='Connected 0 / 0')
        self.connected_label.grid(row=0, column=1, padx=5, pady=5)

    def toggle_debug(self):
        if self.debug_window:
            self.debug_window.destroy()
            self.debug_window = None
            self.debug_mode = False
        else:
            self.debug_window = DebugWindow(self.root, on_close_callback=self._debug_window_closed)
            self.debug_mode = True

    def _debug_window_closed(self):
        self.debug_window = None
        self.debug_mode = False

    def log_event(self, message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(EVENT_LOG, 'a') as log_file:
            log_file.write(f'[{timestamp}] {message}\n')
        try:
            if self.debug_mode and self.debug_window:
                self.debug_window.insert_message('MASTER', message)
        except:
            pass

    def periodic_status_check(self):
        current_time = time.time()
        for ip, status in self.camera_status.items():
            last_seen = status.get('last_seen', 0)
            if (current_time - last_seen) > NO_RESPONSE_TIMEOUT:
                if status['state'] != 'NO RESPONSE':
                    self.camera_status[ip]['state'] = 'NO RESPONSE'

    def status_check_loop(self):
        self.periodic_status_check()
        self.root.after(2000, self.status_check_loop)

    def receive_loop(self):
        lasttime2 = time.perf_counter()
        while self.running:
            socks = dict(self.poller.poll(500))
            if self.router_socket in socks and socks[self.router_socket] == zmq.POLLIN:
                frames = self.router_socket.recv_multipart()
                identity = frames[0]
                message = json.loads(frames[1].decode())
                self.handle_message(identity, message)

    def handle_message(self, identity, message):
        task = message.get('task')
        ip = message.get('ip', 'Unknown')

        self.log_event(f"Incoming message from {ip}: {message}")

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

    def update_connected_label(self):
        for identity, ip in list(self.connected_cameras.items()):
            if self.camera_status[ip]['state'] == 'NO RESPONSE':
                self.connected_cameras.pop(identity)
           
        connected = len(self.connected_cameras)
        total = len(self.cameras)
        self.connected_label.config(text=f'Connected {connected} / {total}')
        
    def compute_overall_status(self):
        is_recording = any(
            status.get('state') == 'RECORDING'
            for status in self.camera_status.values()
        )
        if is_recording:
            return 'RECORDING'
        
        is_preparing = any(
            status.get('state') in ('PREPARING', 'PREPARING_STILL', 'SYNC ISSUE')
            for status in self.camera_status.values()
        )
        if is_preparing:
            return 'PREPARING'
        
        return 'STANDBY'

    def update_status_color(self, overall_status):
        color_map = {
            'STANDBY': 'green',
            'PREPARING': 'yellow',
            'RECORDING': 'red'
        }
        color = color_map.get(overall_status, 'gray')
        self.status_color.delete("all")
        self.status_color.create_rectangle(0, 0, 40, 40, fill=color)

    def update_session_info_labels(self):
        if hasattr(self, 'current_session_start_time') and self.current_session_start_time and self.current_state != State.STANDBY:
            self.start_time_label.config(
                text=time.strftime('%H:%M:%S', time.localtime(self.current_session_start_time))
            )
            
            now = time.time()
            remaining =  now - self.current_session_start_time
            if remaining < 0:
                remaining_second = round(remaining, 1)
                self.countdown_value.config(text=f"{remaining_second} s")
                self.sound_still_triggered = False
                self.sound_video_triggered = False

                if self.current_state == State.VIDEO_RECORDING:
                    if remaining_second > -3 and not self.sound_video_preroll_triggerd_3:
                        self.sound_video_preroll.play()
                        self.sound_video_preroll_triggerd_3 = True
                    if remaining_second > -2 and not self.sound_video_preroll_triggerd_2:
                        self.sound_video_preroll.play()
                        self.sound_video_preroll_triggerd_2 = True
                    if remaining_second > -1 and not self.sound_video_preroll_triggerd_1:
                        self.sound_video_preroll.play()
                        self.sound_video_preroll_triggerd_1 = True
            else:
                if self.current_state == State.STILL_RECORDING:
                    self.countdown_value.config(text="0 s")
                    if not self.sound_still_triggered:
                        self.sound_still_trigger.play()
                        self.sound_still_triggered = True
                        self.current_state = State.STANDBY
                elif self.current_state == State.VIDEO_RECORDING:
                    self.countdown_label.config(text='Duration:')
                    self.countdown_value.config(text=round(remaining, 1))
                    if not self.sound_video_triggered:
                        self.sound_video_trigger.play()
                        self.sound_video_triggered = True

        else:
            self.countdown_label.config(text='Countdown:')
            self.start_time_label.config(text='N/A')
            self.countdown_value.config(text='N/A')
            self.sound_video_preroll_triggerd_3 = False
            self.sound_video_preroll_triggerd_2 = False
            self.sound_video_preroll_triggerd_1 = False
        
        overall_status = self.compute_overall_status()
        self.status_label.config(text=overall_status)
        self.update_status_color(overall_status)

    def update_status_tree(self, ip):
        camera = next((c for c in self.cameras if c['ip'] == ip), None)
        if camera:
            name = camera['name']
        else:
            name = 'Unknown'

        status = self.camera_status.get(ip, {})
        state = status.get('state', 'Unknown')
        last_seen = status.get('last_seen', 0)
        last_seen_str = time.strftime('%H:%M:%S', time.localtime(last_seen)) if last_seen > 0 else 'N/A'
        storage = status.get('storage_remaining_mb', 'N/A')
        sessions = ', '.join(status.get('sessions', []))

        found = False
        for item in self.status_tree.get_children():
            values = self.status_tree.item(item, 'values')
            if values[1] == ip:
                self.status_tree.item(item, values=(name, ip, state, last_seen_str, storage, sessions))
                found = True
                break
        if not found:
            self.status_tree.insert('', 'end', values=(name, ip, state, last_seen_str, storage, sessions))

    def update_status_tree_all(self):
        for ip in self.camera_status:
            self.update_status_tree(ip)

    def update_status_tree_loop(self):
        self.update_status_tree_all()
        self.update_connected_label()
        self.update_session_info_labels()
        self.root.after(100, self.update_status_tree_loop) 

    def send_message(self, ip, message_dict):
        identity = self.ip_to_identity.get(ip)
        if identity:
            self.router_socket.send_multipart([identity, json.dumps(message_dict).encode()])

    def broadcast_message(self, message_dict):
        for ip in self.ip_to_identity:
            self.send_message(ip, message_dict)

    def get_next_multiple_of_5_sec(self, min_gap=5):
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
                0,
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

    def start_video_recording(self):
        self.current_state = State.VIDEO_RECORDING
        session_name = self.session_entry.get()
        bitrate = self.bitrate_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name.')
            return
        start_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.current_session_start_time = start_time
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

    def stop_video_recording(self):
        for ip in self.ip_to_identity:
            message = {'task': 'REC_STOP'}
            self.send_message(ip, message)
        self.log_event('Sent REC_STOP command.')
        self.current_state = State.STANDBY
        self.sound_video_preroll_triggerd_3 = False
        self.sound_video_preroll_triggerd_2 = False
        self.sound_video_preroll_triggerd_1 = False

    def capture_stills(self):
        self.current_state = State.STILL_RECORDING
        session_name = self.still_name_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Please enter a session name for the still.')
            return
        
        still_resolution = self.resolution_still.get()
        capture_time = self.get_next_multiple_of_5_sec(min_gap=5)
        self.current_session_start_time = capture_time
        self.log_event(f"Scheduling still capture at {time.strftime('%H:%M:%S', time.localtime(capture_time))}")

        for ip in self.ip_to_identity:
            self.camera_status[ip]['pending_still_time'] = capture_time

        for ip in self.ip_to_identity:
            msg = {
                'task': 'REC_STILL',
                'session_name': session_name,
                'start_time': capture_time,
                'resolution': still_resolution
            }
            self.send_message(ip, msg)

    def start_up(self):
        su.update_dist_time()
        su.start_remote_hosts(self.root, su.RemoteScript.CAPTURECONTROLLER)
        self.root.deiconify()

    def on_close(self):
        su.stop_remote_hosts(su.RemoteScript.CAPTURECONTROLLER)
        self.running = False
        self.root.destroy()
    

def load_camera_list(json_path):
    with open(json_path, 'r') as f:
        return json.load(f)

if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    app = MainWindow(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
