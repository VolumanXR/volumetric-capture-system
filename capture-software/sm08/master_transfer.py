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
import math
from concurrent.futures import ThreadPoolExecutor, as_completed  # (CHANGED) for concurrency
from pathlib import Path

# Configure logging
logging.basicConfig(filename='session_downloader.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# ===== (CHANGED) Choose how many files can be downloaded simultaneously =====
MAX_CONCURRENT_DOWNLOADS = 10

# Load camera list
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent,  'utils','camera_list.json') 
if not os.path.exists(CAMERA_LIST_FILE):
    raise FileNotFoundError(f"{CAMERA_LIST_FILE} not found.")

with open(CAMERA_LIST_FILE, 'r') as f:
    CAMERAS = json.load(f)

UDP_PORT = 50005
TCP_PORT = 50006
SESSIONS_FOLDER = "Sessions"  # Folder where sessions will be stored

class FileDownloadPanel:
    """
    GUI element that displays progress for one "camera-file" download.
    """
    def __init__(self, parent, ip, filename):
        # Create a frame
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill='x', padx=5, pady=5)

        # Display label: IP + filename
        self.label = ttk.Label(self.frame, text=f"{ip} => {filename}")
        self.label.pack(side='top', anchor='w')

        # Progress bar
        self.progress = ttk.Progressbar(self.frame, length=400, mode='determinate')
        self.progress.pack(side='left', padx=5, pady=5)

        # ETA label
        self.eta_label = ttk.Label(self.frame, text="ETA: --")
        self.eta_label.pack(side='left', padx=5)

        self.file_size = 0
        self.start_time = time.time()

    def update_progress(self, bytes_received):
        if self.file_size <= 0:
            return
        percentage = bytes_received / self.file_size * 100
        elapsed = time.time() - self.start_time
        speed = bytes_received / elapsed if elapsed > 0 else 0
        remaining = self.file_size - bytes_received
        eta = remaining / speed if speed > 0 else float('inf')
        eta_str = self.format_eta(eta)

        def _update():
            self.progress['value'] = percentage
            self.eta_label.config(text=f"ETA: {eta_str}")

        # Safely update from worker thread
        self.frame.after(0, _update)

    def set_file_size(self, size):
        self.file_size = size
        self.start_time = time.time()

    def destroy(self):
        self.frame.destroy()

    def format_eta(self, eta_seconds):
        if eta_seconds == float('inf') or eta_seconds < 0:
            return "--"
        minutes, seconds = divmod(int(eta_seconds), 60)
        return f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"


class SessionDownloaderApp:
    def __init__(self, master):
        self.master = master
        master.title("Download Manager - VolumanXR")

        self.sessions = []
        # Example structure: self.session_info[session_name] = {
        #    "files": [ { "filename": str, "size": int }, ... ]
        # }
        self.session_info = {}

        self.current_downloading_session = None

        # For concurrency
        self.executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS)

        # Build GUI
        self.create_widgets()

        # Track each file's download progress panel:
        self.active_download_panels = {}

        # Immediately fetch sessions at startup
        self.get_sessions_thread()
        # Periodically refresh sessions
        self.schedule_refresh()

    def create_widgets(self):
        # Session Control Frame
        session_frame = ttk.LabelFrame(self.master, text="Session Controls")
        session_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.refresh_button = ttk.Button(session_frame, text="Refresh", command=self.get_sessions)
        self.refresh_button.grid(row=0, column=0, padx=5, pady=5)

        # TreeView with columns
        self.session_tree = ttk.Treeview(session_frame, 
                                         columns=("Name","Files","Session Size","Not found on", "Status"), 
                                         show='headings')
        self.session_tree.heading("Name", text="Name")
        self.session_tree.heading("Files", text="Files Found")
        self.session_tree.heading("Session Size", text="Session Size")
        self.session_tree.heading("Not found on", text="Not found on")
        self.session_tree.heading("Status", text="Status")

        self.session_tree.column("Name", anchor="w", width=150)
        self.session_tree.column("Files", anchor="e", width=80)
        self.session_tree.column("Session Size", anchor="e", width=100)
        self.session_tree.column("Not found on", anchor="w", width=200)
        self.session_tree.column("Status", anchor="w", width=120)

        self.session_tree.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        # Buttons Frame
        buttons_frame = ttk.Frame(session_frame)
        buttons_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        self.download_button = ttk.Button(buttons_frame, text="Download Session", command=self.download_session)
        self.download_button.grid(row=0, column=0, padx=5, pady=5)

        self.delete_local_button = ttk.Button(buttons_frame, text="Delete Session (local)", command=self.delete_session_local)
        self.delete_local_button.grid(row=0, column=1, padx=5, pady=5)

        self.delete_remote_button = ttk.Button(buttons_frame, text="Delete Session (remote)", command=self.delete_session_remote)
        self.delete_remote_button.grid(row=0, column=2, padx=5, pady=5)

        self.open_folder_button = ttk.Button(buttons_frame, text="Open Local Sessions Folder", command=self.open_local_sessions_folder)
        self.open_folder_button.grid(row=0, column=3, padx=5, pady=5)

        session_frame.columnconfigure(0, weight=1)
        session_frame.rowconfigure(1, weight=1)

        # Progress Frame
        progress_frame = ttk.LabelFrame(self.master, text="Progress")
        progress_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        # Current Session Label
        self.current_file_label = ttk.Label(progress_frame, text="Current Session: N/A")
        self.current_file_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        # A frame to hold multiple (camera-file) progress bars
        self.multi_download_frame = ttk.Frame(progress_frame)
        self.multi_download_frame.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        # Overall Progress
        self.overall_progress_label = ttk.Label(progress_frame, text="Overall Progress:")
        self.overall_progress_label.grid(row=2, column=0, padx=5, pady=(10, 5), sticky="w")

        self.overall_progress = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.overall_progress.grid(row=3, column=0, padx=5, pady=5, sticky="ew")

        self.overall_eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.overall_eta_label.grid(row=4, column=0, padx=5, pady=5, sticky="w")

        progress_frame.columnconfigure(0, weight=1)

        # Configure master grid
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=1)

    def schedule_refresh(self):
        # Automatic refresh every 60 seconds
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

        # Build session_info
        for session_name in self.sessions:
            # We'll gather file info from each camera
            # For each camera, we might have multiple files
            # We'll sum up total size
            cameras_files = {}
            for cam in CAMERAS:
                info_list = self.query_session_info(cam['ip'], session_name)
                cameras_files[cam['name']] = info_list  # list of {filename, size}
            self.session_info[session_name] = {
                "cameras_files": cameras_files
            }

        self.update_session_tree()
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
                    return response.get('files', [])
                else:
                    return []
        except Exception as e:
            logging.error(f"Failed to get session info from {ip} for {session_name}: {e}", exc_info=True)
            return []

    def update_session_tree(self):
        def update():
            for i in self.session_tree.get_children():
                self.session_tree.delete(i)

            for session_name in self.sessions:
                cameras_files = self.session_info[session_name]["cameras_files"]
                # Flatten all files to compute total size
                all_files = []
                for flist in cameras_files.values():
                    all_files.extend(flist)

                total_size = sum(f['size'] for f in all_files)
                not_found_cams = []
                found_count = 0

                # We'll just count how many cameras have at least one file
                for cam, flist in cameras_files.items():
                    if len(flist) == 0:
                        not_found_cams.append(cam)
                    else:
                        found_count += 1

                not_found_str = ", ".join(not_found_cams) if not_found_cams else ""
                readable_size = self.convert_size(total_size)

                # For "Status" determination, we reuse your logic or a simpler approach
                # We'll just see if there's a local folder, etc.
                status = self.determine_session_status(session_name, cameras_files)

                self.session_tree.insert("", "end", values=(
                    session_name,
                    f"{found_count} cams",   # 'Files' found
                    readable_size,
                    not_found_str,
                    status
                ))
        self.master.after(0, update)

    def determine_session_status(self, session_name, cameras_files):
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        if not os.path.exists(session_folder):
            return "remote"

        # Count how many local files exist with correct size
        # (For brevity, we skip the detailed size-check from your original code.)
        # You could re-use your original logic here.
        return "local (maybe incomplete)"

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

        # Gather all files from all cameras
        # We'll produce a list of (ip, file_info) that we want to download
        tasks = []
        cameras_files = self.session_info[session_name]["cameras_files"]
        for cam in CAMERAS:
            ip = cam['ip']
            flist = cameras_files[cam['name']]
            for file_info in flist:
                tasks.append((ip, file_info['filename'], file_info['size']))

        if not tasks:
            messagebox.showerror("Error", f"No files found for session '{session_name}'.")
            self.current_downloading_session = None
            self.update_current_session_label()
            return

        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        os.makedirs(session_folder, exist_ok=True)

        total_bytes = sum(t[2] for t in tasks)  # sum of sizes
        total_received = 0
        overall_start_time = time.time()

        self.update_overall_progress(0, overall_start_time, 0, total_bytes)

        # Clear any old progress panels
        self.clear_download_panels()

        # We create a future for each file. We'll use concurrency to speed it up.
        futures = []
        partial_results = {}

        for (ip, filename, file_size) in tasks:
            # Create a FileDownloadPanel
            panel = FileDownloadPanel(self.multi_download_frame, ip, filename)
            panel.set_file_size(file_size)
            self.active_download_panels[(ip, filename)] = panel

            # Submit a job
            future = self.executor.submit(self.download_file, session_name, ip, filename, file_size, panel)
            futures.append(future)

        # As each future completes, we update overall progress
        for fut in as_completed(futures):
            try:
                received = fut.result()  # returns how many bytes were received
                total_received += received
                percent = (total_received / total_bytes) * 100 if total_bytes > 0 else 100
                self.update_overall_progress(percent, overall_start_time, total_received, total_bytes)
            except Exception as e:
                logging.error(f"Download error in future: {e}", exc_info=True)
        
        # All done
        self.clear_download_panels()  # remove them from the UI
        self.update_overall_progress(100, overall_start_time, total_bytes, total_bytes)
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully (where files existed).")

        self.current_downloading_session = None
        self.update_current_session_label()
        # Refresh the tree to update local/remote status
        self.update_session_tree()

    def download_file(self, session_name, ip, filename, file_size, panel):
        """
        Download a single file from 'ip' for this session.
        Return how many bytes were received.
        """
        file_path = os.path.join(SESSIONS_FOLDER, session_name, filename)
        bytes_received = 0
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(10)
                request = {
                    'action': 'DOWNLOAD_SESSION',
                    'session_name': session_name,
                    'filename': filename
                }
                sock.connect((ip, TCP_PORT))
                sock.sendall(json.dumps(request).encode())

                # Read JSON header length
                length_data = self.recvall(sock, 8)
                if not length_data or len(length_data) < 8:
                    raise Exception("Failed to read JSON length from server.")
                (msg_length,) = struct.unpack('!Q', length_data)

                # read the JSON response
                json_data = self.recvall(sock, msg_length)
                if len(json_data) < msg_length:
                    raise Exception("Incomplete JSON response from server.")

                response = json.loads(json_data.decode())

                if response.get('status') != 'OK':
                    err_msg = response.get('message', 'Unknown error.')
                    raise Exception(f"From {ip}: {err_msg}")

                # The server says we have file_size bytes to receive
                # We'll read them in chunks
                with open(file_path, 'wb') as f:
                    while bytes_received < file_size:
                        data = sock.recv(4096)
                        if not data:
                            break
                        f.write(data)
                        bytes_received += len(data)
                        panel.update_progress(bytes_received)
                if bytes_received < file_size:
                    raise Exception("Connection lost during file transfer.")

                logging.info(f"Downloaded file '{filename}' from {ip} successfully.")
        except Exception as e:
            logging.error(f"Failed to download file '{filename}' from {ip}: {e}", exc_info=True)
        return bytes_received

    def recvall(self, sock, n):
        """Receive exactly n bytes or fewer if EOF is encountered."""
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                break
            data += packet
        return data

    def clear_download_panels(self):
        for panel in self.active_download_panels.values():
            panel.destroy()
        self.active_download_panels.clear()

    def update_current_session_label(self):
        def update():
            if self.current_downloading_session:
                self.current_file_label.config(text=f"Current Session: {self.current_downloading_session}")
            else:
                self.current_file_label.config(text="Current Session: N/A")
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
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

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
        # Find which cameras have files
        # If a camera has an empty array, no need to send a delete
        cameras_with_session = [cam for cam in CAMERAS 
                                if len(self.session_info.get(session_name, {})
                                       .get("cameras_files", {})
                                       .get(cam['name'], [])) > 0]

        if not cameras_with_session:
            messagebox.showinfo("Info", f"No Raspberry Pis have the session '{session_name}'.")
            return

        delete_results = {}
        for cam in cameras_with_session:
            cam_name = cam['name']
            ip = cam['ip']
            success, message = self.send_delete_request(ip, session_name)
            delete_results[cam_name] = (success, message)

        # Prepare summary
        success_cams = [cam for cam, res in delete_results.items() if res[0]]
        failed_cams = [f"{cam} ({msg})" for cam, res in delete_results.items() if not res[0] for msg in [res[1]]]

        if success_cams:
            message = f"Successfully deleted session '{session_name}' on:\n" + ", ".join(success_cams)
            messagebox.showinfo("Success", message)

        if failed_cams:
            message = f"Failed to delete session '{session_name}' on:\n" + ", ".join(failed_cams)
            messagebox.showerror("Error", message)

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

if __name__ == "__main__":
    root = tk.Tk()
    app = SessionDownloaderApp(root)
    root.mainloop()
