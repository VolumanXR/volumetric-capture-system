#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk, messagebox
import socket
import json
import threading
import time
import os
import logging

# Configuration
UDP_PORT = 50005  # Port to send commands to Pis
UDP_RECEIVE_PORT = 50000  # Port to receive status updates
BROADCAST_IP = '192.168.179.255'
CAMERA_LIST_FILE = 'camera_list.json'
EVENT_LOG_FILE = 'master_event_log.txt'

# Initialize logging
logging.basicConfig(filename=EVENT_LOG_FILE, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load camera list
with open(CAMERA_LIST_FILE, 'r') as f:
    camera_list = json.load(f)

# Initialize UDP Socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.bind(('', UDP_RECEIVE_PORT))

# GUI Application
class MasterApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Master Control Panel')
        self.create_widgets()
        self.pis_status = {}
        self.last_status_time = {}
        self.debug_window = None
        self.debug_mode = False
        self.running = True
        threading.Thread(target=self.receive_messages, daemon=True).start()
        threading.Thread(target=self.monitor_pis, daemon=True).start()

    def create_widgets(self):
        # Session Frame
        session_frame = ttk.LabelFrame(self.root, text='Session Control')
        session_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(session_frame, text='Session Name:').grid(row=0, column=0, padx=5, pady=5)
        self.session_name_entry = ttk.Entry(session_frame)
        self.session_name_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(session_frame, text='Recording Type:').grid(row=1, column=0, padx=5, pady=5)
        self.rec_type_var = tk.StringVar(value='Video')
        rec_type_menu = ttk.OptionMenu(session_frame, self.rec_type_var, 'Video', 'Video', 'Still Image')
        rec_type_menu.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(session_frame, text='Bitrate (kbps):').grid(row=2, column=0, padx=5, pady=5)
        self.bitrate_entry = ttk.Entry(session_frame)
        self.bitrate_entry.grid(row=2, column=1, padx=5, pady=5)
        self.bitrate_entry.insert(0, '15000')  # Default 15 Mbps

        ttk.Label(session_frame, text='Compression Format:').grid(row=3, column=0, padx=5, pady=5)
        self.compression_format_var = tk.StringVar(value='H.264')
        compression_menu = ttk.OptionMenu(session_frame, self.compression_format_var, 'H.264', 'H.264', 'jpeg', 'png')
        compression_menu.grid(row=3, column=1, padx=5, pady=5)

        start_button = ttk.Button(session_frame, text='Start Recording', command=self.start_recording)
        start_button.grid(row=4, column=0, padx=5, pady=5)

        stop_button = ttk.Button(session_frame, text='Stop Recording', command=self.stop_recording)
        stop_button.grid(row=4, column=1, padx=5, pady=5)

        # Pi Status Frame
        status_frame = ttk.LabelFrame(self.root, text='Raspberry Pis Status')
        status_frame.pack(fill='both', expand=True, padx=5, pady=5)

        self.status_tree = ttk.Treeview(status_frame, columns=('IP', 'Status', 'Last Seen'), show='headings')
        self.status_tree.heading('IP', text='IP')
        self.status_tree.heading('Status', text='Status')
        self.status_tree.heading('Last Seen', text='Last Seen')
        self.status_tree.pack(fill='both', expand=True)

        # Actions Frame
        actions_frame = ttk.LabelFrame(self.root, text='Actions')
        actions_frame.pack(fill='x', padx=5, pady=5)

        storage_button = ttk.Button(actions_frame, text='Check Storage', command=self.check_storage)
        storage_button.grid(row=0, column=0, padx=5, pady=5)

        sessions_button = ttk.Button(actions_frame, text='Get Sessions', command=self.get_sessions)
        sessions_button.grid(row=0, column=1, padx=5, pady=5)

        download_button = ttk.Button(actions_frame, text='Download Session', command=self.download_session)
        download_button.grid(row=0, column=2, padx=5, pady=5)

        delete_button = ttk.Button(actions_frame, text='Delete Recordings', command=self.delete_recordings)
        delete_button.grid(row=0, column=3, padx=5, pady=5)

        debug_button = ttk.Button(actions_frame, text='Toggle Debug Window', command=self.toggle_debug)
        debug_button.grid(row=0, column=4, padx=5, pady=5)

    def start_recording(self):
        session_name = self.session_name_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Session name is required')
            return
        rec_type = self.rec_type_var.get()
        bitrate = self.bitrate_entry.get()
        compression_format = self.compression_format_var.get()

        if rec_type == 'Video':
            task = 'REC_START'
        else:
            task = 'REC_STILL'

        message = {
            'task': task,
            'session_name': session_name,
            'bitrate': bitrate,
            'compression_format': compression_format,
            # Optionally include start_time for synchronization
        }
        self.broadcast_message(message)
        logging.info(f'Sent {task} command')

    def stop_recording(self):
        message = {'task': 'REC_STOP'}
        self.broadcast_message(message)
        logging.info('Sent REC_STOP command')

    def check_storage(self):
        message = {'task': 'GET_STORAGE'}
        self.broadcast_message(message)
        logging.info('Sent GET_STORAGE command')

    def get_sessions(self):
        message = {'task': 'GET_SESSIONS'}
        self.broadcast_message(message)
        logging.info('Sent GET_SESSIONS command')

    def delete_recordings(self):
        if messagebox.askyesno('Confirm', 'Are you sure you want to delete all recordings on all Pis?'):
            message = {'task': 'DELETE_RECORDINGS'}
            self.broadcast_message(message)
            logging.info('Sent DELETE_RECORDINGS command')

    def download_session(self):
        session_name = self.session_name_entry.get()
        if not session_name:
            messagebox.showerror('Error', 'Session name is required')
            return
        # Create session folder
        session_folder = os.path.join('sessions', session_name)
        os.makedirs(session_folder, exist_ok=True)
        # Start file transfers one by one
        threading.Thread(target=self.transfer_files, args=(session_name,)).start()

    def transfer_files(self, session_name):
        for pi in camera_list['cameras']:
            ip = pi['ip']
            message = {'task': 'START_TRANSFER', 'session_name': session_name}
            sock.sendto(json.dumps(message).encode(), (ip, UDP_PORT))
            logging.info(f'Started transfer from {ip}')
            # Wait for checksum verification before proceeding
            # Implement checksum handling here
            time.sleep(1)  # Adjust based on file size

    def broadcast_message(self, message):
        sock.sendto(json.dumps(message).encode(), (BROADCAST_IP, UDP_PORT))

    def receive_messages(self):
        while self.running:
            try:
                data, addr = sock.recvfrom(4096)
                message = json.loads(data.decode())
                ip = message.get('ip')
                if ip:
                    self.pis_status[ip] = message
                    self.last_status_time[ip] = time.time()
                if self.debug_mode and self.debug_window:
                    self.debug_window.insert_message(ip, message)
            except socket.error:
                pass
            except json.JSONDecodeError:
                pass
            time.sleep(0.1)

    def monitor_pis(self):
        while self.running:
            now = time.time()
            for pi in camera_list['cameras']:
                ip = pi['ip']
                last_seen = self.last_status_time.get(ip, 0)
                status = self.pis_status.get(ip, {}).get('status', 'Unknown')
                if now - last_seen > 10:
                    status = 'No Response'
                self.update_status_tree(ip, status, last_seen)
            time.sleep(1)

    def update_status_tree(self, ip, status, last_seen):
        for item in self.status_tree.get_children():
            if self.status_tree.item(item, 'values')[0] == ip:
                self.status_tree.item(item, values=(ip, status, time.strftime('%H:%M:%S', time.localtime(last_seen))))
                return
        self.status_tree.insert('', 'end', values=(ip, status, time.strftime('%H:%M:%S', time.localtime(last_seen))))

    def toggle_debug(self):
        if self.debug_window:
            self.debug_window.destroy()
            self.debug_window = None
            self.debug_mode = False
        else:
            self.debug_window = DebugWindow(self.root)
            self.debug_mode = True

    def on_close(self):
        self.running = False
        self.root.destroy()

class DebugWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title('Debug Window')
        self.create_widgets()

    def create_widgets(self):
        self.text = tk.Text(self)
        self.text.pack(fill='both', expand=True)

    def insert_message(self, ip, message):
        self.text.insert('end', f'{ip}: {message}\n')
        self.text.see('end')

def main():
    root = tk.Tk()
    app = MasterApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == '__main__':
    main()
