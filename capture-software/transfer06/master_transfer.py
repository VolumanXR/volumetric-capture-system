import tkinter as tk
from tkinter import ttk, messagebox
import socket
import threading
import os
import time
import json
import logging
import struct
import sys
import subprocess

# Configure logging
logging.basicConfig(filename='session_downloader.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# Load camera list
CAMERA_LIST_FILE = "camera_list.json"
if not os.path.exists(CAMERA_LIST_FILE):
    raise FileNotFoundError(f"{CAMERA_LIST_FILE} not found.")

with open(CAMERA_LIST_FILE, 'r') as f:
    CAMERAS = json.load(f)

UDP_PORT = 50005
TCP_PORT = 50006
SESSIONS_FOLDER = "Sessions"  # Folder where sessions will be stored

class SessionDownloaderApp:
    def __init__(self, master):
        self.master = master
        master.title("Download Manager - VolumanXR")  # Renamed Window Title

        # If you want to apply a theme, you can do so here:
        # style = ttk.Style()
        # style.theme_use("clam")  # Example

        self.sessions = []
        self.session_info = {}  # session_name -> {"clip_sizes": {camera_name: size or None}}

        self.current_downloading_session = None

        # Build GUI
        self.create_widgets()

        # Immediately fetch sessions at startup
        self.get_sessions_thread()
        # Periodically refresh sessions (e.g., every 60 seconds)
        self.schedule_refresh()

    def create_widgets(self):
        # Session Control Frame
        session_frame = ttk.LabelFrame(self.master, text="Session Controls")
        session_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.refresh_button = ttk.Button(session_frame, text="Refresh", command=self.get_sessions)  # Renamed Button
        self.refresh_button.grid(row=0, column=0, padx=5, pady=5)

        # Use a Treeview instead of a Listbox
        self.session_tree = ttk.Treeview(session_frame, columns=("Name","Clip Size","Session Size","Not found on", "Status"), show='headings')
        self.session_tree.heading("Name", text="Name")
        self.session_tree.heading("Clip Size", text="Clip Size")
        self.session_tree.heading("Session Size", text="Session Size")
        self.session_tree.heading("Not found on", text="Not found on")
        self.session_tree.heading("Status", text="Status")

        self.session_tree.column("Name", anchor="w", width=150)
        self.session_tree.column("Clip Size", anchor="e", width=100)
        self.session_tree.column("Session Size", anchor="e", width=100)
        self.session_tree.column("Not found on", anchor="w", width=200)
        self.session_tree.column("Status", anchor="w", width=120)

        self.session_tree.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        # Buttons Frame
        buttons_frame = ttk.Frame(session_frame)
        buttons_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        self.download_button = ttk.Button(buttons_frame, text="Download Session", command=self.download_session)
        self.download_button.grid(row=0, column=0, padx=5, pady=5)

        self.delete_local_button = ttk.Button(buttons_frame, text="Delete Session (local)", command=self.delete_session_local)  # Renamed Button
        self.delete_local_button.grid(row=0, column=1, padx=5, pady=5)

        self.delete_remote_button = ttk.Button(buttons_frame, text="Delete Session (remote)", command=self.delete_session_remote)  # New Button
        self.delete_remote_button.grid(row=0, column=2, padx=5, pady=5)

        self.open_folder_button = ttk.Button(buttons_frame, text="Open Local Sessions Folder", command=self.open_local_sessions_folder)
        self.open_folder_button.grid(row=0, column=3, padx=5, pady=5)

        session_frame.columnconfigure(0, weight=1)
        session_frame.rowconfigure(1, weight=1)

        # Progress Frame
        progress_frame = ttk.LabelFrame(self.master, text="Progress")
        progress_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        # Current Session Progress
        self.current_file_label = ttk.Label(progress_frame, text="Current Session: N/A")  # Renamed Label
        self.current_file_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.current_file_info_label = ttk.Label(progress_frame, text="IP: N/A, File: N/A")
        self.current_file_info_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        self.current_progress = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.current_progress.grid(row=2, column=0, padx=5, pady=5, sticky="ew")

        self.current_eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.current_eta_label.grid(row=3, column=0, padx=5, pady=5, sticky="w")

        # Overall Progress
        self.overall_progress_label = ttk.Label(progress_frame, text="Overall Progress:")
        self.overall_progress_label.grid(row=4, column=0, padx=5, pady=(20, 5), sticky="w")

        self.overall_progress = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.overall_progress.grid(row=5, column=0, padx=5, pady=5, sticky="ew")

        self.overall_eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.overall_eta_label.grid(row=6, column=0, padx=5, pady=5, sticky="w")

        progress_frame.columnconfigure(0, weight=1)

        # Configure master grid weights
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=1)

    def schedule_refresh(self):
        # Schedule automatic refresh every 60 seconds
        self.master.after(60000, self.get_sessions_thread)

    def get_sessions(self):
        threading.Thread(target=self.get_sessions_thread, daemon=True).start()

    def get_sessions_thread(self):
        self.sessions.clear()
        self.session_info.clear()

        all_sessions = set()
        for cam in CAMERAS:
            ip = cam['ip']
            sessions = self.query_sessions(ip)
            for s in sessions:
                all_sessions.add(s)

        self.sessions = sorted(all_sessions)

        for session_name in self.sessions:
            self.session_info[session_name] = {
                "clip_sizes": {},
            }
            for cam in CAMERAS:
                info = self.query_session_info(cam['ip'], session_name)
                self.session_info[session_name]["clip_sizes"][cam['name']] = info

        self.update_session_tree()
        # Show message only if triggered by button
        # If automatic, don't show message. We can differentiate by checking if called from get_sessions button?
        # We won't show the message if it's automatic to avoid spam.
        # If you prefer always show message, uncomment next line.
        # messagebox.showinfo("Info", "Session list updated.")
        # Reschedule the refresh
        self.schedule_refresh()

    def query_sessions(self, ip):
        request = {"action": "GET_SESSIONS"}
        sessions = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(5)
                sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
                data, _ = sock.recvfrom(4096)
                response = json.loads(data.decode())
                sessions = response.get('sessions', [])
                logging.info(f"Received sessions from {ip}: {sessions}")
        except Exception as e:
            logging.error(f"Failed to get sessions from {ip}: {e}", exc_info=True)
        return sessions

    def query_session_info(self, ip, session_name):
        request = {"action": "GET_SESSION_INFO", "session_name": session_name}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(5)
                sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
                data, _ = sock.recvfrom(4096)
                response = json.loads(data.decode())
                if response.get('status') == 'OK':
                    return response.get('file_size', None)
                else:
                    return None
        except Exception as e:
            logging.error(f"Failed to get session info from {ip} for {session_name}: {e}", exc_info=True)
            return None

    def update_session_tree(self):
        def update():
            for i in self.session_tree.get_children():
                self.session_tree.delete(i)

            for session_name in self.sessions:
                clip_sizes = self.session_info[session_name]["clip_sizes"]
                found_sizes = [sz for sz in clip_sizes.values() if sz is not None]

                if found_sizes:
                    first_found_size = found_sizes[0]
                    session_size = sum(found_sizes)
                else:
                    first_found_size = 0
                    session_size = 0

                not_found_cams = [cam_name for cam_name, sz in clip_sizes.items() if sz is None]
                not_found_str = ", ".join(not_found_cams) if not_found_cams else ""

                # Determine Status
                status = self.determine_session_status(session_name, clip_sizes)

                # Convert sizes to a human-readable format
                readable_first_size = self.convert_size(first_found_size)
                readable_session_size = self.convert_size(session_size)

                self.session_tree.insert("", "end", values=(
                    session_name,
                    readable_first_size,
                    readable_session_size,
                    not_found_str,
                    status
                ))
        self.master.after(0, update)

    def determine_session_status(self, session_name, clip_sizes):
        # Status determination:
        # "remote": no local files from cameras that have this session
        # "local": all files for cameras that have it are present
        # "local (incomplete)": some but not all files are present
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        cameras_with_clips = [(cam, sz) for cam, sz in clip_sizes.items() if sz is not None]

        if not os.path.exists(session_folder):
            # no local folder at all
            return "remote"

        # folder exists, check files
        available_count = 0
        expected_count = len(cameras_with_clips)
        for cam, sz in cameras_with_clips:
            # We know file name pattern: session_name + '_' + ip_last_octet + '.h264'
            # We must find which camera this is to get ip last octet:
            ip = None
            for c in CAMERAS:
                if c['name'] == cam:
                    ip = c['ip']
                    break
            if not ip:
                continue  # should not happen, but just skip if cam not found
            suffix = '_' + ip.split('.')[-1]
            file_name = f"{session_name}{suffix}.h264"
            file_path = os.path.join(session_folder, file_name)
            if os.path.exists(file_path) and os.path.getsize(file_path) == sz:
                available_count += 1

        if available_count == 0:
            return "remote"
        elif available_count < expected_count:
            return "local (incomplete)"
        else:
            return "local"

    def download_session(self):
        selection = self.session_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.session_tree.item(session_item, "values")
        session_name = session_values[0]
        threading.Thread(target=self.download_session_thread, args=(session_name,), daemon=True).start()

    def download_session_thread(self, session_name):
        self.current_downloading_session = session_name
        self.update_current_session_label()

        clip_sizes = self.session_info[session_name]["clip_sizes"]
        cameras_with_session = [(c['name'], c['ip'], sz) for c in CAMERAS if (sz := clip_sizes[c['name']]) is not None]

        if not cameras_with_session:
            messagebox.showerror("Error", f"No Raspberry Pis have the session '{session_name}'.")
            self.current_downloading_session = None
            self.update_current_session_label()
            return

        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        os.makedirs(session_folder, exist_ok=True)

        total_bytes = sum(sz for _, _, sz in cameras_with_session)
        total_received = 0
        overall_start_time = time.time()

        self.update_overall_progress(0, overall_start_time, total_received, total_bytes)

        for cam_name, ip, file_size in cameras_with_session:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)
                    request = {'action': 'DOWNLOAD_SESSION', 'session_name': session_name}
                    sock.connect((ip, TCP_PORT))
                    sock.sendall(json.dumps(request).encode())

                    # First, read the length of the JSON response
                    length_data = self.recvall(sock, 8)
                    if not length_data or len(length_data) < 8:
                        raise Exception("Failed to read JSON length from server.")
                    (msg_length,) = struct.unpack('!Q', length_data)

                    # Now read exactly msg_length bytes for the JSON response
                    json_data = self.recvall(sock, msg_length)
                    if len(json_data) < msg_length:
                        raise Exception("Incomplete JSON response from server.")

                    response = json.loads(json_data.decode())

                    if response.get('status') != 'OK':
                        error_message = response.get('message', 'Unknown error.')
                        messagebox.showerror("Error", f"From {ip}: {error_message}")
                        continue

                    suffix = '_' + ip.split('.')[-1]
                    file_name = f"{session_name}{suffix}.h264"
                    file_path = os.path.join(session_folder, file_name)

                    self.update_current_file_info(ip, file_name)

                    bytes_received = 0
                    start_time = time.time()
                    with open(file_path, 'wb') as f:
                        while bytes_received < file_size:
                            data = sock.recv(4096)
                            if not data:
                                break
                            f.write(data)
                            bytes_received += len(data)
                            total_received += len(data)
                            self.update_current_progress(bytes_received, file_size, start_time)
                            self.update_overall_progress((total_received / total_bytes) * 100, overall_start_time, total_received, total_bytes)

                    if bytes_received < file_size:
                        raise Exception("Connection lost during file transfer.")
                    logging.info(f"Downloaded session {session_name} from {ip} successfully.")

            except Exception as e:
                logging.error(f"Failed to download session from {ip}: {e}", exc_info=True)
                messagebox.showerror("Error", f"Failed to download session from {ip}: {e}")

        self.update_current_file_info("N/A", "N/A")
        self.update_current_progress(0, 1, 0)
        self.update_overall_progress(100, overall_start_time, total_bytes, total_bytes)
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully from all available Raspberry Pis.")

        self.current_downloading_session = None
        self.update_current_session_label()
        # Refresh the tree to update status
        self.update_session_tree()

    def delete_session_local(self):
        selection = self.session_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.session_tree.item(session_item, "values")
        session_name = session_values[0]

        confirm = messagebox.askyesno("Delete Session (local)", f"Are you sure you want to delete the session '{session_name}' locally?")
        if confirm:
            session_folder = os.path.join(SESSIONS_FOLDER, session_name)
            if os.path.exists(session_folder):
                try:
                    # Delete folder and contents
                    for root, dirs, files in os.walk(session_folder, topdown=False):
                        for file in files:
                            os.remove(os.path.join(root, file))
                        for d in dirs:
                            os.rmdir(os.path.join(root, d))
                    os.rmdir(session_folder)
                    messagebox.showinfo("Info", f"Session '{session_name}' deleted locally.")
                except Exception as e:
                    logging.error(f"Failed to delete session '{session_name}' locally: {e}", exc_info=True)
                    messagebox.showerror("Error", f"Failed to delete session '{session_name}' locally: {e}")
            else:
                messagebox.showinfo("Info", f"Session '{session_name}' not found locally.")
            self.update_session_tree()

    def delete_session_remote(self):
        selection = self.session_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_item = selection[0]
        session_values = self.session_tree.item(session_item, "values")
        session_name = session_values[0]

        confirm = messagebox.askyesno("Delete Session (remote)", f"Are you sure you want to delete the session '{session_name}' on all Raspberry Pis?")
        if confirm:
            threading.Thread(target=self.delete_session_remote_thread, args=(session_name,), daemon=True).start()

    def delete_session_remote_thread(self, session_name):
        cameras_with_session = [cam for cam in CAMERAS if self.session_info.get(session_name, {}).get("clip_sizes", {}).get(cam['name'], None) is not None]

        if not cameras_with_session:
            messagebox.showinfo("Info", f"No Raspberry Pis have the session '{session_name}'.")
            return

        delete_results = {}
        for cam in cameras_with_session:
            cam_name = cam['name']
            ip = cam['ip']
            success, message = self.send_delete_request(ip, session_name)
            delete_results[cam_name] = (success, message)

        # Prepare summary message
        success_cams = [cam for cam, res in delete_results.items() if res[0]]
        failed_cams = [f"{cam} ({msg})" for cam, res in delete_results.items() if not res[0] for msg in [res[1]]]

        if success_cams:
            message = f"Successfully deleted session '{session_name}' on the following cameras:\n" + ", ".join(success_cams)
            messagebox.showinfo("Success", message)

        if failed_cams:
            message = f"Failed to delete session '{session_name}' on the following cameras:\n" + ", ".join(failed_cams)
            messagebox.showerror("Error", message)

        # Refresh the session list after deletion
        self.get_sessions_thread()

    def send_delete_request(self, ip, session_name):
        request = {"action": "DELETE_SESSION", "session_name": session_name}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(5)
                sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
                data, _ = sock.recvfrom(4096)
                response = json.loads(data.decode())
                if response.get('status') == 'OK':
                    return True, "Deleted successfully."
                else:
                    return False, response.get('message', 'Unknown error.')
        except Exception as e:
            logging.error(f"Failed to send delete request to {ip}: {e}", exc_info=True)
            return False, str(e)

    def open_local_sessions_folder(self):
        # Open the local sessions folder in the file explorer
        if not os.path.exists(SESSIONS_FOLDER):
            os.makedirs(SESSIONS_FOLDER, exist_ok=True)
        try:
            if os.name == 'nt':  # Windows
                os.startfile(os.path.abspath(SESSIONS_FOLDER))
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(["open", os.path.abspath(SESSIONS_FOLDER)])
            else:  # Linux and others
                subprocess.Popen(["xdg-open", os.path.abspath(SESSIONS_FOLDER)])
        except Exception as e:
            logging.error(f"Failed to open sessions folder: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to open sessions folder: {e}")

    def recvall(self, sock, n):
        """Receive exactly n bytes or fewer if EOF is encountered."""
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                break
            data += packet
        return data

    def update_current_file_info(self, ip, file_name):
        def update():
            self.current_file_info_label.config(text=f"IP: {ip}, File: {file_name}")
        self.master.after(0, update)

    def update_current_session_label(self):
        def update():
            if self.current_downloading_session:
                self.current_file_label.config(text=f"Current Session: {self.current_downloading_session}")
            else:
                self.current_file_label.config(text="Current Session: N/A")
        self.master.after(0, update)

    def update_current_progress(self, bytes_received, file_size, start_time):
        percentage = bytes_received / file_size * 100 if file_size > 0 else 0
        elapsed_time = time.time() - start_time
        speed = bytes_received / elapsed_time if elapsed_time > 0 else 0
        eta = (file_size - bytes_received) / speed if speed > 0 else float('inf')
        eta_formatted = self.format_eta(eta)

        def update():
            self.current_progress['value'] = percentage
            self.current_eta_label.config(text=f"ETA: {eta_formatted}")
        self.master.after(0, update)

    def update_overall_progress(self, percentage, start_time, total_received, total_bytes):
        if start_time is None or percentage == 0:
            eta_formatted = "Calculating..."
        else:
            elapsed_time = time.time() - start_time
            speed = total_received / elapsed_time if elapsed_time > 0 else 0
            remaining = total_bytes - total_received
            eta = remaining / speed if speed > 0 else float('inf')
            eta_formatted = self.format_eta(eta)

        def update():
            self.overall_progress['value'] = percentage
            self.overall_eta_label.config(text=f"ETA: {eta_formatted}")
        self.master.after(0, update)

    def format_eta(self, eta_seconds):
        if eta_seconds == float('inf') or eta_seconds < 0:
            return "Calculating..."
        minutes, seconds = divmod(int(eta_seconds), 60)
        return f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    def convert_size(self, size_bytes):
        # Helper function to convert bytes to a human-readable format
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

import math  # Add this import at the top

if __name__ == "__main__":
    root = tk.Tk()
    app = SessionDownloaderApp(root)
    root.mainloop()
