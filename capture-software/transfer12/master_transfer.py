# master_transfer.py v12 (with ZeroMQ integration)
import tkinter as tk
from tkinter import ttk, messagebox, Menu, filedialog
import socket
import json
import os
import time
import math
import struct
import threading
from pathlib import Path
import paramiko
from concurrent.futures import ThreadPoolExecutor
import subprocess
import shutil
import sys
from PIL import Image, ImageTk
import zmq   # <-- New import for ZeroMQ

# Determine the directory of the script
SCRIPT_DIR = Path(__file__).resolve().parent
UTILS_FOLDER = os.path.join(SCRIPT_DIR.parent.parent, 'utils')

# The camera list file is located two directories up, under "utils"
CAMERA_LIST_FILE = os.path.join(UTILS_FOLDER, 'camera_list.json')
if not os.path.exists(CAMERA_LIST_FILE):
    raise FileNotFoundError(f"{CAMERA_LIST_FILE} not found.")

with open(CAMERA_LIST_FILE, 'r') as f:
    CAMERA_LIST = json.load(f)
    
ICON_PATH = os.path.join(UTILS_FOLDER, "Voluman_Icon.ico")


UDP_PORT = 50005
TCP_PORT = 50006  # This port is now used by the zmq REP server on the remote side

# Default sessions folder and configuration file.
DEFAULT_SESSIONS_FOLDER = os.path.join(SCRIPT_DIR, "Sessions")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

REFRESH_INTERVAL_MS = 60000
cpu_cores = os.cpu_count()
MAX_NORMAL_WORKERS = cpu_cores * 2
MAX_DOWNLOAD_WORKERS = 5
# MAX_SIMULTANEOUS_DOWNLOADS = 10

SCRIPTNAME = 'remote_transfer.py'
USERNAME = 'voluman'
PASSWORD = 'xr'


def load_config():
    """Load configuration from CONFIG_FILE if available, otherwise return an empty dict."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as cf:
            return json.load(cf)
    return {}


def save_config(config):
    """Save the provided config dictionary into CONFIG_FILE."""
    with open(CONFIG_FILE, 'w') as cf:
        json.dump(config, cf)


class SessionDownloaderApp:
    def __init__(self, master, on_close_callback=None):
        self.master = master
        self.master.title("VolumanXR - Download Manager")

        self.on_close_callback = on_close_callback  # Store the callback

        # Load configuration for the sessions folder.
        self.config = load_config()
        self.sessions_folder = self.config.get("sessions_folder", DEFAULT_SESSIONS_FOLDER)
        # Make sure the sessions folder is an absolute path.
        self.sessions_folder = os.path.abspath(self.sessions_folder)
        os.makedirs(self.sessions_folder, exist_ok=True)

        self.sessions = []           # list of session names
        self.session_info = {}       # {session_name: {"clip_sizes": {camera_name: size_or_none}}}

        self.total_bytes = 0
        self.total_received = 0
        self.download_start_time = 0
        self.download_lock = threading.Lock()

        # self.create_menubar()  # Create the menu bar
        self.create_widgets()  # Create all the UI widgets

        start_remote_hosts(self.master)

        # Kick off initial session retrieval and schedule refresh
        self.get_sessions()
        self.schedule_refresh()

    def open_git_repository(self):
        import webbrowser
        webbrowser.open('https://github.com/tallAldi/VolumanXR')

    def create_menubar(self):
        """Creates a menubar with File and Help menus."""
        menubar = tk.Menu(self.master)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Git Repository", command=self.open_git_repository)
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # Help Menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.master.config(menu=menubar)

    def show_about(self):
        """Display an 'About' message."""
        messagebox.showinfo("About", "Session Downloader App v1.0\nDownload sessions easily!")

    def create_widgets(self):
        # --- New: Local Session Download Location Frame ---
        location_frame = ttk.LabelFrame(self.master, text="Download Location")
        location_frame.pack(fill="x", padx=10, pady=10)

        # Display the current (absolute) sessions folder
        self.location_label = ttk.Label(location_frame, text=self.sessions_folder)
        self.location_label.pack(side="left", padx=5, pady=5)

        # Button to change the location via a file dialog
        btn_change_location = ttk.Button(location_frame, text="Change Location", command=self.change_location)
        btn_change_location.pack(side="right", padx=5, pady=5)

        # --- Existing Session Controls Frame ---
        frame = ttk.LabelFrame(self.master, text="Session Controls")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_button = ttk.Button(frame, text="Refresh", command=self.get_sessions)
        self.refresh_button.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        # ---------------------------------------------------------------------
        # <<-- Modified: Add new column "First Dropped" to the Treeview -->> 
        self.session_tree = ttk.Treeview(
            frame,
            columns=("Name", "Clip Size", "Session Size", "Not found on", "Status", "First Dropped"),
            show='headings'
        )
        self.session_tree.heading("Name", text="Name")
        self.session_tree.heading("Clip Size", text="Clip Size")
        self.session_tree.heading("Session Size", text="Session Size")
        self.session_tree.heading("Not found on", text="Not found on")
        self.session_tree.heading("Status", text="Status")
        self.session_tree.heading("First Dropped", text="First Dropped")
        self.session_tree.column("Name", width=150, anchor="w")
        self.session_tree.column("Clip Size", width=100, anchor="e")
        self.session_tree.column("Session Size", width=100, anchor="e")
        self.session_tree.column("Not found on", width=200, anchor="w")
        self.session_tree.column("Status", width=120, anchor="w")
        self.session_tree.column("First Dropped", width=120, anchor="center")
        # ---------------------------------------------------------------------

        self.session_tree.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=5, pady=5)

        # Action buttons row
        action_frame = ttk.Frame(frame)
        action_frame.grid(row=2, column=0, columnspan=4, pady=5, sticky='ew')

        btn_download = ttk.Button(action_frame, text="Download Session", command=self.download_session)
        btn_download.grid(row=0, column=0, rowspan=2, padx=5, pady=2, sticky="ns")

        btn_delete_local = ttk.Button(action_frame, text="Delete Session (Local)", command=self.delete_session_local)
        btn_delete_local.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        btn_delete_remote = ttk.Button(action_frame, text="Delete Session (Remote)", command=self.delete_session_remote)
        btn_delete_remote.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

        btn_delete_all_remote = ttk.Button(action_frame, text="Delete All (Remote)", command=self.delete_all_sessions_remote)
        btn_delete_all_remote.grid(row=0, column=2, rowspan=2, padx=5, pady=2, sticky="ns")

        btn_convert_into_frames_local = ttk.Button(action_frame, text="Convert into Frames (Local)", command=self.convert_into_frames_local)
        btn_convert_into_frames_local.grid(row=0, column=3, padx=5, pady=2, sticky="ew")

        btn_open_folder = ttk.Button(action_frame, text="Open Local Folder", command=self.open_local_sessions_folder)
        btn_open_folder.grid(row=1, column=3, padx=5, pady=2, sticky="ew")

        progress_frame = ttk.LabelFrame(self.master, text="Progress")
        progress_frame.pack(fill="x", padx=10, pady=10)

        self.progress_label = ttk.Label(progress_frame, text="Overall Progress:")
        self.progress_label.pack(anchor="w")

        self.progress_bar = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.progress_bar.pack(fill="x", padx=5, pady=2)

        self.eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.eta_label.pack(anchor="w")

        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

    def change_location(self):
        """Opens a dialog to select a new folder, updates the label, saves to config, and ensures the folder exists."""
        new_location = filedialog.askdirectory(title="Select new download location")
        if new_location:
            self.sessions_folder = os.path.abspath(new_location)
            self.location_label.config(text=self.sessions_folder)
            self.config["sessions_folder"] = self.sessions_folder
            save_config(self.config)
            os.makedirs(self.sessions_folder, exist_ok=True)
            messagebox.showinfo("Location Changed", f"New download location set to:\n{self.sessions_folder}")

        # ---------------------------------------------------------------------
    # New helper: Compute the overall first dropped frame for a session,
    # including the camera name in brackets.
    # ---------------------------------------------------------------------
    def get_first_dropped_for_session(self, session_name):
        """
        For a given session, look at all JSON files (which indicate dropped frames)
        and return the earliest dropped frame number along with the camera name
        (extracted from the JSON file name) in the format:
             "<frame> (<cam name>)"
        If no dropped frame is found, returns "none".
        """
        session_folder = os.path.join(self.sessions_folder, session_name)
        if not os.path.exists(session_folder):
            return ""
        json_files = [f for f in os.listdir(session_folder) if f.lower().endswith(".json")]
        earliest = None
        earliest_cam = None
        for jf in json_files:
            try:
                json_path = os.path.join(session_folder, jf)
                with open(json_path, 'r') as fp:
                    data = json.load(fp)
            except Exception:
                continue
            # Sort the frame keys numerically
            keys = sorted(data.keys(), key=lambda x: int(x))
            for key in keys:
                if data[key] == "dropped":
                    dropped_frame = int(key)
                    # Extract camera name from the JSON file name.
                    # Assumes the JSON file is named as: sessionName_XXX.json
                    parts = jf.split("_")
                    if len(parts) > 1:
                        camera_raw = parts[-1].replace(".json", "")
                        try:
                            # Adjust the logic as needed: here we subtract 100 to get a camera index.
                            camera_id = int(camera_raw) - 100
                            cam_name = f"cam{camera_id:02d}"
                        except:
                            cam_name = camera_raw
                    else:
                        cam_name = ""
                    if earliest is None or dropped_frame < earliest:
                        earliest = dropped_frame
                        earliest_cam = cam_name
                    break  # Move to the next JSON file after finding its first dropped frame
        if earliest is None:
            return "none"
        return f"{earliest} ({earliest_cam})" if earliest_cam else str(earliest)



    # ---------------------------------------------------------------------
    # Session Retrieval in Background
    # ---------------------------------------------------------------------
    def get_sessions(self):
        """Spawn a background thread to query all cameras so we don't block the GUI."""
        self.refresh_button.config(state="disabled")
        t = threading.Thread(target=self.get_sessions_thread, daemon=True)
        t.start()

    def get_sessions_thread(self):
        with ThreadPoolExecutor(max_workers=MAX_NORMAL_WORKERS) as executor:
            future_sessions = {executor.submit(self.query_sessions_udp, cam["ip"]): cam for cam in CAMERA_LIST}
            all_sessions = set()
            for fut in future_sessions:
                cam_sessions = fut.result()
                for s in cam_sessions:
                    all_sessions.add(s)

        sorted_sessions = sorted(all_sessions)

        new_session_info = {}
        for s in sorted_sessions:
            new_session_info[s] = {"clip_sizes": {}}
            with ThreadPoolExecutor(max_workers=MAX_NORMAL_WORKERS) as executor2:
                size_futures = {executor2.submit(self.query_session_size, cam["ip"], s): cam for cam in CAMERA_LIST}
                for fut in size_futures:
                    cam = size_futures[fut]
                    new_session_info[s]["clip_sizes"][cam["name"]] = fut.result()

        self.master.after(100, self.finish_sessions_update, sorted_sessions, new_session_info)

    def finish_sessions_update(self, sorted_sessions, new_session_info):
        """Runs in main thread to store results and refresh the treeview."""
        self.sessions = sorted_sessions
        self.session_info = new_session_info
        self.update_session_tree()
        self.refresh_button.config(state="normal")

    def query_sessions_udp(self, ip):
        request = {"action": "GET_SESSIONS"}
        result = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(2.0)
                sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
                data, _ = sock.recvfrom(4096)
                resp = json.loads(data.decode())
                result = resp.get("sessions", [])
        except:
            pass
        return result

    def query_session_size(self, ip, session_name):
        request = {"action": "GET_SESSION_INFO", "session_name": session_name}
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(2.0)
                sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
                data, _ = sock.recvfrom(4096)
                resp = json.loads(data.decode())
                if resp.get("status") == "OK":
                    return resp.get("file_size", None)
        except:
            pass
        return None

    def schedule_refresh(self):
        self.master.after(REFRESH_INTERVAL_MS, self.get_sessions)

    # ---------------------------------------------------------------------
    # Session Tree Update
    # ---------------------------------------------------------------------
    def update_session_tree(self):
        self.session_tree.delete(*self.session_tree.get_children())
        for session_name in self.sessions:
            clip_sizes = self.session_info[session_name]["clip_sizes"]
            found_sizes = [sz for sz in clip_sizes.values() if sz is not None]
            if found_sizes:
                first_found_size = found_sizes[0]
                session_size = sum(found_sizes)
            else:
                first_found_size = 0
                session_size = 0

            not_found_cams = [cam for cam, sz in clip_sizes.items() if sz is None]
            not_found_str = ", ".join(not_found_cams) if not_found_cams else ""
            status = self.determine_session_status(session_name, clip_sizes)
            # <<-- New: Get first dropped frame info (if available locally) -->> 
            first_dropped = self.get_first_dropped_for_session(session_name)

            self.session_tree.insert(
                "",
                "end",
                values=(
                    session_name,
                    self.human_size(first_found_size),
                    self.human_size(session_size),
                    not_found_str,
                    status,
                    first_dropped
                )
            )

    def determine_session_status(self, session_name, clip_sizes):
        session_folder = os.path.join(self.sessions_folder, session_name)
        if not os.path.exists(session_folder):
            return "remote"
        valid_cams = [(c, sz) for c, sz in clip_sizes.items() if sz is not None]
        if not valid_cams:
            return "remote"
        fully_downloaded = 0
        for cam_name, remote_sz in valid_cams:
            ip = self.get_ip_from_camera_name(cam_name)
            local_sz = self.local_session_size_for_ip(session_name, ip)
            if abs(local_sz - remote_sz) < 2:
                fully_downloaded += 1
        if fully_downloaded == 0:
            return "remote"
        elif fully_downloaded < len(valid_cams):
            return "local (incomplete)"
        else:
            return "local"

    def local_session_size_for_ip(self, session_name, ip):
        if not ip:
            return 0
        octet = ip.split('.')[-1]
        folder = os.path.join(self.sessions_folder, session_name)
        if not os.path.exists(folder):
            return 0
        total = 0
        for f in os.listdir(folder):
            if f.startswith(f"{session_name}_{octet}"):
                fp = os.path.join(folder, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        return total

    def get_ip_from_camera_name(self, cam_name):
        for c in CAMERA_LIST:
            if c["name"] == cam_name:
                return c["ip"]
        return None

    # ---------------------------------------------------------------------
    # Download (Parallel) – Modified to use ZeroMQ for file transfer
    # ---------------------------------------------------------------------
    def download_session(self):
        sel = self.session_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a session.")
            return
        session_name = self.session_tree.item(sel[0], "values")[0]

        clip_sizes = self.session_info[session_name]["clip_sizes"]
        cams_with_data = [(cam, sz) for cam, sz in clip_sizes.items() if sz is not None and sz > 0]
        if not cams_with_data:
            messagebox.showerror("Error", f"No camera has session '{session_name}'.")
            return

        self.total_bytes = sum(sz for _, sz in cams_with_data)
        self.total_received = 0
        self.progress_bar['value'] = 0
        self.eta_label.config(text="ETA: ...")
        self.download_start_time = time.time()

        folder = os.path.join(self.sessions_folder, session_name)
        os.makedirs(folder, exist_ok=True)

        def do_downloads():
            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
                futures = []
                for (cam, sz) in cams_with_data:
                    ip = self.get_ip_from_camera_name(cam)
                    futures.append(executor.submit(self.download_from_camera, session_name, ip))
                for f in futures:
                    f.result()
            self.master.after(0, lambda: self.download_complete(session_name))

        threading.Thread(target=do_downloads, daemon=True).start()

    def download_from_camera(self, session_name, ip):
        """
        Replaces the plain TCP socket with a ZeroMQ REQ socket.
        The REQ sends a JSON request and waits for a multipart reply.
        The first frame is a JSON header; subsequent frames are file contents.
        """
        try:
            # Create (or reuse) the ZeroMQ context and REQ socket.
            context = zmq.Context.instance()
            socket = context.socket(zmq.REQ)
            socket.connect(f"tcp://{ip}:{TCP_PORT}")

            req = {"action": "DOWNLOAD_SESSION", "session_name": session_name}
            socket.send_json(req)
            
            # Receive multipart reply: first frame is header, subsequent frames are file data.
            reply_parts = socket.recv_multipart()
            header = json.loads(reply_parts[0].decode())
            if header.get("status") != "OK":
                print(f"Error from {ip}: {header.get('error')}")
                return

            files_info = header.get("files", [])
            session_folder = os.path.join(self.sessions_folder, session_name)

            # Expect one frame per file (in the same order as in header)
            for i, fi in enumerate(files_info):
                fname = fi["filename"]
                fsize = fi["size"]
                file_data = reply_parts[i+1]
                out_path = os.path.join(session_folder, fname)
                with open(out_path, "wb") as fp:
                    fp.write(file_data)
                with self.download_lock:
                    self.total_received += len(file_data)
                    self.update_progress()
        except Exception as e:
            print(f"Error downloading from {ip}: {e}")
        finally:
            socket.close()


    def download_complete(self, session_name):
        self.update_progress(force=100)
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded.")
        self.update_session_tree()

    def update_progress(self, force=None):
        if force is not None:
            pct = force
            eta_str = "0s"
        else:
            if self.total_bytes <= 0:
                return
            pct = (self.total_received / self.total_bytes) * 100
            elapsed = time.time() - self.download_start_time
            speed = self.total_received / elapsed if elapsed > 0 else 0
            remain = self.total_bytes - self.total_received
            eta = remain / speed if speed > 0 else float('inf')
            eta_str = self.format_eta(eta)

        def update_ui():
            self.progress_bar['value'] = pct
            self.eta_label.config(text=f"ETA: {eta_str}")

        self.master.after(100, update_ui)

    def recvall(self, sock, n):
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def format_eta(self, secs):
        if secs == float('inf') or secs < 0:
            return "Calculating..."
        m, s = divmod(int(secs), 60)
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    # ---------------------------------------------------------------------
    # Deletion
    # ---------------------------------------------------------------------
    def delete_session_local(self):
        sel = self.session_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a session.")
            return
        session_name = self.session_tree.item(sel[0], "values")[0]
        folder_path = os.path.join(self.sessions_folder, session_name)
        if not os.path.exists(folder_path):
            messagebox.showinfo("Info", "Session not found locally.")
            return
        confirm = messagebox.askyesno("Confirm", f"Delete local session '{session_name}'?")
        if confirm:
            try:
                shutil.rmtree(folder_path)
                messagebox.showinfo("Deleted", f"Session '{session_name}' removed locally.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete locally:\n{e}")
            self.update_session_tree()

    def delete_session_remote(self):
        sel = self.session_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a session.")
            return
        session_name = self.session_tree.item(sel[0], "values")[0]
        confirm = messagebox.askyesno("Confirm", f"Delete session '{session_name}' on all cameras?")
        if not confirm:
            return
        request = {"action": "DELETE_SESSION", "session_name": session_name}
        for cam in CAMERA_LIST:
            ip = cam["ip"]
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(2)
                    sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
            except:
                pass
        messagebox.showinfo("Done", f"Requested deletion of '{session_name}' from all cameras.")
        self.master.after(1000, self.get_sessions)

    def delete_all_sessions_remote(self):
        confirm = messagebox.askyesno("Confirm", "Delete all sessions on all cameras?")
        if not confirm:
            return
        request = {"action": "DELETE_ALL_SESSIONS"}
        for cam in CAMERA_LIST:
            ip = cam["ip"]
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(2)
                    sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
            except:
                pass
        messagebox.showinfo("Done", "Requested deletion of all sessions from all cameras.")
        self.master.after(1000, self.get_sessions)

    # ---------------------------------------------------------------------
    # Conversion
    # ---------------------------------------------------------------------
    def convert_into_frames_local(self):
        sel = self.session_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a session.")
            return
        session_name = self.session_tree.item(sel[0], "values")[0]
        session_folder = os.path.join(self.sessions_folder, session_name)
        if not os.path.exists(session_folder):
            messagebox.showinfo("Info", "Session not found locally.")
            return
        confirm = messagebox.askyesno("Confirm", f"Convert session '{session_name}' into frames?")
        if not confirm:
            return
        self.convert_session_into_frames(session_name)

    def convert_session_into_frames(self, session_name):
        session_folder = os.path.join(self.sessions_folder, session_name)
        frames_folder = os.path.join(session_folder, "Frames")
        os.makedirs(frames_folder, exist_ok=True)

        global_max_frame_index = 0
        for file in os.listdir(session_folder):
            if file.lower().endswith(".json"):
                json_path = os.path.join(session_folder, file)
                with open(json_path, 'r') as jf:
                    frames_dict = json.load(jf)
                for k, v in frames_dict.items():
                    if v != "dropped":
                        frame_idx = int(k)
                        if frame_idx > global_max_frame_index:
                            global_max_frame_index = frame_idx

        global_digits = len(str(global_max_frame_index))

        for file in os.listdir(session_folder):
            if file.lower().endswith(".mp4"):
                self.convert_video_into_frames(
                    session_name=session_name,
                    video_file=file,
                    global_digits=global_digits
                )

    def convert_video_into_frames(self, session_name, video_file, global_digits):
        session_folder = os.path.join(self.sessions_folder, session_name)
        video_path = os.path.join(session_folder, video_file)

        json_file = video_file.replace(".mp4", ".json")
        json_path = os.path.join(session_folder, json_file)
        if not os.path.exists(json_path):
            messagebox.showinfo("Info", f"JSON file for '{video_file}' not found.")
            return

        with open(json_path, 'r') as f:
            frames_dict = json.load(f)

        valid_frames = [int(k) for k, v in frames_dict.items() if v != "dropped"]
        valid_frames.sort()
        if not valid_frames:
            messagebox.showinfo("Info", f"No valid frames in '{json_file}'.")
            return

        temp_folder = os.path.join(session_folder, "temp_extraction_" + video_file.replace(".mp4", ""))
        if os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)
        os.makedirs(temp_folder)

        output_pattern = os.path.join(temp_folder, "frame_%06d.jpg")
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", video_path,
            "-q:v", "2",
            output_pattern
        ]
        try:
            subprocess.run(ffmpeg_cmd, check=True)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("FFmpeg Error", str(e))
            return

        extracted_frames = sorted(
            f for f in os.listdir(temp_folder)
            if f.lower().endswith(".jpg") and f.startswith("frame_")
        )
        extracted_count = len(extracted_frames)

        camera_raw = video_file.split("_")[-1].replace(".mp4", "")
        camera_id = int(camera_raw) - 100  # Adjust this logic as needed

        frames_folder = os.path.join(session_folder, "Frames")
        move_count = min(len(valid_frames), extracted_count)

        for i in range(move_count):
            json_frame_index = valid_frames[i]
            extracted_name = f"frame_{(i+1):06d}.jpg"
            extracted_path = os.path.join(temp_folder, extracted_name)
            if not os.path.isfile(extracted_path):
                continue

            frame_folder_name = f"Frame{json_frame_index:0{global_digits}d}"
            frame_folder_path = os.path.join(frames_folder, frame_folder_name)
            os.makedirs(frame_folder_path, exist_ok=True)

            cam_name = f"cam{camera_id:02d}.jpg"
            final_path = os.path.join(frame_folder_path, cam_name)

            shutil.move(extracted_path, final_path)

        shutil.rmtree(temp_folder)

    # ---------------------------------------------------------------------
    # Misc
    # ---------------------------------------------------------------------
    def open_local_sessions_folder(self):
        folder = os.path.abspath(self.sessions_folder)
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open folder:\n{e}")

    def on_close(self):
        stop_remote_hosts()
        self.running = False
        self.master.destroy()

    @staticmethod
    def human_size(size_bytes):
        if not size_bytes or size_bytes < 1:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"


def start_remote_hosts(master):
    alert_window = show_starting_alert()
    cameras = load_camera_list(CAMERA_LIST_FILE)
    with ThreadPoolExecutor(max_workers=MAX_NORMAL_WORKERS) as executor:
        for cam in cameras:
            host_ip = cam["ip"]
            executor.submit(start_script, host_ip)
    alert_window.destroy()
    master.lift()
    master.focus_force()


def show_starting_alert():
    alert = tk.Toplevel()
    alert.overrideredirect(True)
    alert.title("Starting Scripts")
    alert.attributes("-topmost", True)
    
    # Set background color of the alert window
    background_color = "#EEEEEE"  # Light blue; change as desired
    alert.configure(bg=background_color)
    
    # Set the window icon if available.
    if os.path.exists(ICON_PATH):
        alert.iconbitmap(ICON_PATH)
    
    # Increase window height to accommodate the logo and text.
    window_width = 300
    window_height = 400
    screen_width = alert.winfo_screenwidth()
    screen_height = alert.winfo_screenheight()
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    alert.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    logo_path = os.path.join(UTILS_FOLDER, "Voluman_Logo.png")
    
    if os.path.exists(logo_path):
        # Open the image using Pillow
        img = Image.open(logo_path)
        # Calculate maximum dimensions for the logo.
        # Here we allow the logo to use up to 80% of the window's width and 60% of its height.
        max_logo_width = int(window_width * 0.8)
        max_logo_height = int(window_height * 0.8)
        img.thumbnail((max_logo_width, max_logo_height), Image.Resampling.LANCZOS)
        logo_img = ImageTk.PhotoImage(img)
        logo_label = tk.Label(alert, image=logo_img)
        logo_label.image = logo_img  # Keep a reference to avoid garbage collection.
        logo_label.pack(side="top", pady=10)
    else:
        # If no logo is available, add a spacer.
        tk.Label(alert, text="").pack(side="top", pady=10)
    
    # Create the alert text label and pack it beneath the logo.
    label = tk.Label(alert, text="Starting Scripts on Raspberry Pi's...")
    label.pack(side="bottom", expand=True, fill=tk.BOTH, padx=20, pady=10)
    
    alert.update()
    return alert


def show_stopping_alert():
    alert = tk.Toplevel()
    alert.overrideredirect(True)
    alert.title("Stopping Scripts")
    alert.attributes("-topmost", True)
    
    # Set background color of the alert window
    background_color = "#EEEEEE"  # Light blue; change as desired
    alert.configure(bg=background_color)
    
    # Set the window icon if available.
    if os.path.exists(ICON_PATH):
        alert.iconbitmap(ICON_PATH)
    
    # Increase window height to accommodate the logo and text.
    window_width = 300
    window_height = 400
    screen_width = alert.winfo_screenwidth()
    screen_height = alert.winfo_screenheight()
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    alert.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    logo_path = os.path.join(UTILS_FOLDER, "Voluman_Logo.png")
    
    if os.path.exists(logo_path):
        # Open the image using Pillow
        img = Image.open(logo_path)
        # Calculate maximum dimensions for the logo.
        # Here we allow the logo to use up to 80% of the window's width and 60% of its height.
        max_logo_width = int(window_width * 0.8)
        max_logo_height = int(window_height * 0.8)
        img.thumbnail((max_logo_width, max_logo_height), Image.Resampling.LANCZOS)
        logo_img = ImageTk.PhotoImage(img)
        logo_label = tk.Label(alert, image=logo_img)
        logo_label.image = logo_img  # Keep a reference to avoid garbage collection.
        logo_label.pack(side="top", pady=10)
    else:
        # If no logo is available, add a spacer.
        tk.Label(alert, text="").pack(side="top", pady=10)
    
    # Create the alert text label and pack it beneath the logo.
    label = tk.Label(alert, text="Stopping Scripts on Raspberry Pi's...")
    label.pack(side="bottom", expand=True, fill=tk.BOTH, padx=20, pady=10)
    
    alert.update()
    return alert


def stop_remote_hosts():
    alert_window = show_stopping_alert()
    cameras = load_camera_list(CAMERA_LIST_FILE)
    with ThreadPoolExecutor(max_workers=MAX_NORMAL_WORKERS) as executor:
        for cam in cameras:
            host_ip = cam["ip"]
            executor.submit(stop_script, host_ip)
    alert_window.destroy()


def load_camera_list(json_path):
    with open(json_path, 'r') as f:
        return json.load(f)


def ssh_command(ssh_client, command):
    stdin, stdout, stderr = ssh_client.exec_command(command)
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    return out, err


def connect_ssh(host):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=host, username=USERNAME, password=PASSWORD, timeout=5)
    return ssh


def start_script(host):
    ssh = None
    try:
        ssh = connect_ssh(host)
        cmd = (
            f"nohup python3 /home/voluman/{SCRIPTNAME} "
            f"> /home/voluman/{SCRIPTNAME}.log 2>&1 &"
        )
        _, err = ssh_command(ssh, cmd)
        if err:
            print(f"[{host}] Error starting {SCRIPTNAME}: {err}")
        else:
            print(f"[{host}] Started {SCRIPTNAME}.")
    except Exception as e:
        print(f"[{host}] Failed to start {SCRIPTNAME}: {e}")
    finally:
        if ssh:
            ssh.close()


def stop_script(host):
    ssh = None
    try:
        ssh = connect_ssh(host)
        cmd = f"pkill -f {SCRIPTNAME}"
        _, err = ssh_command(ssh, cmd)
        if err:
            print(f"[{host}] Possible error stopping {SCRIPTNAME}: {err}")
        else:
            print(f"[{host}] Stopped {SCRIPTNAME}.")
    except Exception as e:
        print(f"[{host}] Failed to stop {SCRIPTNAME}: {e}")
    finally:
        if ssh:
            ssh.close()


def main():
    root = tk.Tk()
    if os.path.exists(ICON_PATH):
        root.iconbitmap(ICON_PATH)
    app = SessionDownloaderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()