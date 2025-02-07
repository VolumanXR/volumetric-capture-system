# master_transfer.py v9.2
import tkinter as tk
from tkinter import ttk, messagebox, Menu
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

SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_FILE = os.path.join(SCRIPT_DIR.parent.parent,  'utils','camera_list.json') 
if not os.path.exists(CAMERA_LIST_FILE):
    raise FileNotFoundError(f"{CAMERA_LIST_FILE} not found.")

with open(CAMERA_LIST_FILE, 'r') as f:
    CAMERA_LIST = json.load(f)
UDP_PORT = 50005
TCP_PORT = 50006
SESSIONS_FOLDER = "Sessions"
REFRESH_INTERVAL_MS = 60000
cpu_cores = os.cpu_count()
MAX_SIMULTANEOUS_DOWNLOADS = cpu_cores * 2
# MAX_SIMULTANEOUS_DOWNLOADS = 10

SCRIPTNAME = 'remote_transfer.py'
USERNAME = 'voluman'
PASSWORD = 'xr'

class SessionDownloaderApp:
    def __init__(self, master, on_close_callback=None):
        self.master = master
        self.master.title("VolumanXR - Download Manager")

        self.on_close_callback = on_close_callback  # Store the callback

        self.sessions = []           # list of session names
        self.session_info = {}       # {session_name: {"clip_sizes": {camera_name: size_or_none}}}

        self.total_bytes = 0
        self.total_received = 0
        self.download_start_time = 0
        self.download_lock = threading.Lock()

        self.create_widgets()
        self.create_menubar()  # <-- Add the menubar to the main window

        start_remote_hosts()
        os.makedirs(SESSIONS_FOLDER, exist_ok=True)

        # Kick off initial retrieval
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

        # Configure the master to display the menubar
        self.master.config(menu=menubar)

    def show_about(self):
        """Display an 'About' message."""
        messagebox.showinfo("About", "Session Downloader App v1.0\nDownload sessions easily!")

    def create_widgets(self):
        # Frame
        frame = ttk.LabelFrame(self.master, text="Session Controls")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Buttons
        self.refresh_button = ttk.Button(frame, text="Refresh", command=self.get_sessions)
        self.refresh_button.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        
        # insert loading indicator while refreshing

        self.session_tree = ttk.Treeview(
            frame,
            columns=("Name", "Clip Size", "Session Size", "Not found on", "Status"),
            show='headings'
        )
        self.session_tree.heading("Name", text="Name")
        self.session_tree.heading("Clip Size", text="Clip Size")
        self.session_tree.heading("Session Size", text="Session Size")
        self.session_tree.heading("Not found on", text="Not found on")
        self.session_tree.heading("Status", text="Status")

        self.session_tree.column("Name", width=150, anchor="w")
        self.session_tree.column("Clip Size", width=100, anchor="e")
        self.session_tree.column("Session Size", width=100, anchor="e")
        self.session_tree.column("Not found on", width=200, anchor="w")
        self.session_tree.column("Status", width=120, anchor="w")
        self.session_tree.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=5, pady=5)

        # Action buttons row
        action_frame = ttk.Frame(frame)
        action_frame.grid(row=2, column=0, columnspan=4, pady=5, sticky='ew')

        # Download Button - spans 2 rows
        btn_download = ttk.Button(action_frame, text="Download Session", command=self.download_session)
        btn_download.grid(row=0, column=0, rowspan=2, padx=5, pady=2, sticky="ns")

        # Delete Session (Local) and Delete Session (Remote) in one column
        btn_delete_local = ttk.Button(action_frame, text="Delete Session (Local)", command=self.delete_session_local)
        btn_delete_local.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        btn_delete_remote = ttk.Button(action_frame, text="Delete Session (Remote)", command=self.delete_session_remote)
        btn_delete_remote.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

        # Delete All (Remote) button
        btn_delete_all_remote = ttk.Button(action_frame, text="Delete All (Remote)", command=self.delete_all_sessions_remote)
        btn_delete_all_remote.grid(row=0, column=2, rowspan=2, padx=5, pady=2, sticky="ns")

        # Convert into Frames (Local) and Open Local Folder in one column
        btn_convert_into_frames_local = ttk.Button(action_frame, text="Convert into Frames (Local)", command=self.convert_into_frames_local)
        btn_convert_into_frames_local.grid(row=0, column=3, padx=5, pady=2, sticky="ew")

        btn_open_folder = ttk.Button(action_frame, text="Open Local Folder", command=self.open_local_sessions_folder)
        btn_open_folder.grid(row=1, column=3, padx=5, pady=2, sticky="ew")

        # Progress Frame
        progress_frame = ttk.LabelFrame(self.master, text="Progress")
        progress_frame.pack(fill="x", padx=10, pady=10)

        self.progress_label = ttk.Label(progress_frame, text="Overall Progress:")
        self.progress_label.pack(anchor="w")

        self.progress_bar = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.progress_bar.pack(fill="x", padx=5, pady=2)

        self.eta_label = ttk.Label(progress_frame, text="ETA: N/A")
        self.eta_label.pack(anchor="w")

        # Grid config
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)


    # ---------------------------------------------------------------------
    # Session Retrieval in Background
    # ---------------------------------------------------------------------
    def get_sessions(self):
        """Spawn a background thread to query all cameras so we don't block the GUI."""
        # Disable the refresh button (optionally) so the user doesn't spam
        self.refresh_button.config(state="disabled")

        t = threading.Thread(target=self.get_sessions_thread, daemon=True)
        t.start()

    def get_sessions_thread(self):
        with ThreadPoolExecutor(max_workers=10) as executor:
            # gather sessions in parallel
            future_sessions = {executor.submit(self.query_sessions_udp, cam["ip"]): cam for cam in CAMERA_LIST}
            all_sessions = set()
            for fut in future_sessions:
                cam_sessions = fut.result()
                for s in cam_sessions:
                    all_sessions.add(s)

        sorted_sessions = sorted(all_sessions)

        # next, also parallelize the size queries if you like:
        new_session_info = {}
        for s in sorted_sessions:
            # for each session, gather sizes from cameras
            new_session_info[s] = {"clip_sizes": {}}
            with ThreadPoolExecutor(max_workers=5) as executor2:
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

        # Re-enable refresh
        self.refresh_button.config(state="normal")

    def query_sessions_udp(self, ip):
        """Blocking call in a background thread is safe; returns a list of sessions."""
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
        """Blocking call in a background thread; returns the size or None."""
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
        """Auto-refresh every REFRESH_INTERVAL_MS."""
        self.master.after(REFRESH_INTERVAL_MS, self.get_sessions)

    # ---------------------------------------------------------------------
    # Session Tree Update
    # ---------------------------------------------------------------------
    def update_session_tree(self):
        # Clear existing
        self.session_tree.delete(*self.session_tree.get_children())

        # Insert rows
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

            self.session_tree.insert(
                "",
                "end",
                values=(
                    session_name,
                    self.human_size(first_found_size),
                    self.human_size(session_size),
                    not_found_str,
                    status
                )
            )

    def determine_session_status(self, session_name, clip_sizes):
        """Simple local/remote/incomplete check."""
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        if not os.path.exists(session_folder):
            return "remote"

        # cameras that actually have data
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
        """Sum the sizes of local files that match session_name + last octet."""
        if not ip:
            return 0
        octet = ip.split('.')[-1]
        folder = os.path.join(SESSIONS_FOLDER, session_name)
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
    # Download (Parallel)
    # ---------------------------------------------------------------------
    def download_session(self):
        sel = self.session_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a session.")
            return
        session_name = self.session_tree.item(sel[0], "values")[0]

        # Which cameras have data?
        clip_sizes = self.session_info[session_name]["clip_sizes"]
        cams_with_data = [(cam, sz) for cam, sz in clip_sizes.items() if sz is not None and sz > 0]
        if not cams_with_data:
            messagebox.showerror("Error", f"No camera has session '{session_name}'.")
            return

        # Sum total size
        self.total_bytes = sum(sz for _, sz in cams_with_data)
        self.total_received = 0
        self.progress_bar['value'] = 0
        self.eta_label.config(text="ETA: ...")
        self.download_start_time = time.time()

        # Ensure folder
        folder = os.path.join(SESSIONS_FOLDER, session_name)
        os.makedirs(folder, exist_ok=True)

        def do_downloads():
            with ThreadPoolExecutor(max_workers=MAX_SIMULTANEOUS_DOWNLOADS) as executor:
                futures = []
                for (cam, sz) in cams_with_data:
                    ip = self.get_ip_from_camera_name(cam)
                    futures.append(executor.submit(self.download_from_camera, session_name, ip))
                for f in futures:
                    f.result()  # raise exceptions

            # Done
            self.master.after(0, lambda: self.download_complete(session_name))

        threading.Thread(target=do_downloads, daemon=True).start()

    def download_from_camera(self, session_name, ip):
        if not ip:
            return
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, TCP_PORT))

            req = {"action": "DOWNLOAD_SESSION", "session_name": session_name}
            sock.sendall(json.dumps(req).encode())

            # Read 8 bytes for JSON length
            length_data = self.recvall(sock, 8)
            if len(length_data) < 8:
                return
            import struct
            (msg_len,) = struct.unpack('!Q', length_data)

            # Read JSON
            data = self.recvall(sock, msg_len)
            resp = json.loads(data.decode())
            if resp.get("status") != "OK":
                return

            files_info = resp.get("files", [])
            session_folder = os.path.join(SESSIONS_FOLDER, session_name)

            for fi in files_info:
                fname = fi["filename"]
                fsize = fi["size"]
                out_path = os.path.join(session_folder, fname)

                received = 0
                with open(out_path, "wb") as fp:
                    while received < fsize:
                        chunk = sock.recv(min(4096, fsize - received))
                        if not chunk:
                            break
                        fp.write(chunk)
                        received += len(chunk)

                        # Update progress
                        with self.download_lock:
                            self.total_received += len(chunk)
                            self.update_progress()

        except Exception as e:
            print(f"Error downloading from {ip}: {e}")
        finally:
            if sock:
                sock.close()

    def download_complete(self, session_name):
        """Called once all parallel tasks are done."""
        self.update_progress(force=100)
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded.")
        self.update_session_tree()

    def update_progress(self, force=None):
        """Compute progress % and ETA, schedule a GUI update."""
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

        folder_path = os.path.join(SESSIONS_FOLDER, session_name)
        if not os.path.exists(folder_path):
            messagebox.showinfo("Info", "Session not found locally.")
            return
        confirm = messagebox.askyesno("Confirm", f"Delete local session '{session_name}'?")
        if confirm:
            import shutil
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

        confirm = messagebox.askyesno(
            "Confirm",
            f"Delete session '{session_name}' on all cameras?"
        )
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
        # Optionally refresh
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
        # Optionally refresh
        self.master.after(1000, self.get_sessions)
        
    # ---------------------------------------------------------------------
    # Conversion
    # ---------------------------------------------------------------------
            
    # together with every .mp4 file in the session folder is a .json file with the same name. In there are the frames counting up. Sometimes a frame number has the attribute "dropped" like: "1024": "dropped" Therefore there is no frame. However in the videofile, the video is continous and skips the dropped frames. The detectet dropped frames need to be respected by the sorting algorithm.
    # The goal is to create a folder "Frames" inside of a local sessions folder. In there there are folders per each frame like: Frame00001, Frame00002, ... Please make the digits be as long as negessary to cover the maximum amout of frames from each .mp4. In each Frame Folder the frames of the session are stored as .jpg files. The Suffix of the original .mp4 file for a video contains the camera number like: DavidRec02_114.mp4 for camera 14 and DavidRec02_115.mp4 for camera 15. 
    # The frames of the session are stored in the .json file with the same name as the .mp4 file. The frames are stored in the .json file in the order of the cameras.
    # If a frame is dropped, the .jpg file is not created.
    # Remame the files into cam01.jpg for camera 01, cam02.jpg for camera 02, ... in each frame folder.
    # Sort the frames of each camera into the Frame Folders
    # Use ffpmeg in subprocesses to convert the videos into frames and don't use OpenCV
    
    
    def convert_into_frames_local(self):
        """
        Triggered from the UI. Asks which session to convert.
        """
        sel = self.session_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a session.")
            return

        session_name = self.session_tree.item(sel[0], "values")[0]
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        if not os.path.exists(session_folder):
            messagebox.showinfo("Info", "Session not found locally.")
            return

        confirm = messagebox.askyesno(
            "Confirm",
            f"Convert session '{session_name}' into frames?"
        )
        if not confirm:
            return

        self.convert_session_into_frames(session_name)


    def convert_session_into_frames(self, session_name):
        """
        1) Find the global maximum frame index across all JSONs in this session,
           so we can determine the zero-padding for FrameXXXX directories.
        2) Convert each .mp4 → frames (skipping 'dropped').
        """
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        frames_folder = os.path.join(session_folder, "Frames")
        os.makedirs(frames_folder, exist_ok=True)

        # ------------------------------
        # 1) Gather global maximum frame index across all JSON
        # ------------------------------
        global_max_frame_index = 0
        for file in os.listdir(session_folder):
            if file.lower().endswith(".json"):
                json_path = os.path.join(session_folder, file)
                with open(json_path, 'r') as jf:
                    frames_dict = json.load(jf)
                # frames_dict is like {"0": "...", "1": "dropped", etc.}
                for k, v in frames_dict.items():
                    if v != "dropped":
                        frame_idx = int(k)
                        if frame_idx > global_max_frame_index:
                            global_max_frame_index = frame_idx

        # Determine how many digits we need for zero‐padding
        # e.g. max frame index=12345 => 5 digits
        global_digits = len(str(global_max_frame_index))

        # ------------------------------
        # 2) Convert each .mp4 file by:
        #    a) Single ffmpeg extraction to a temp folder
        #    b) Renaming frames into FrameXXXX subfolders
        # ------------------------------
        for file in os.listdir(session_folder):
            if file.lower().endswith(".mp4"):
                self.convert_video_into_frames(
                    session_name=session_name,
                    video_file=file,
                    global_digits=global_digits
                )


    def convert_video_into_frames(self, session_name, video_file, global_digits):
        """
        Extract all frames in one go using ffmpeg. Then move/rename them
        into `Frames/Frame000xx` subfolders, skipping dropped frames.
        """
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        video_path = os.path.join(session_folder, video_file)

        # The matching JSON
        json_file = video_file.replace(".mp4", ".json")
        json_path = os.path.join(session_folder, json_file)
        if not os.path.exists(json_path):
            messagebox.showinfo("Info", f"JSON file for '{video_file}' not found.")
            return

        # Load frame info from JSON
        with open(json_path, 'r') as f:
            frames_dict = json.load(f)

        # Gather all valid (non-dropped) frames in ascending order
        valid_frames = [
            int(k) for k,v in frames_dict.items() 
            if v != "dropped"
        ]
        valid_frames.sort()

        if not valid_frames:
            messagebox.showinfo("Info", f"No valid frames in '{json_file}'.")
            return

        # TEMP folder to hold raw ffmpeg‐extracted images
        temp_folder = os.path.join(session_folder, "temp_extraction_" + video_file.replace(".mp4", ""))
        if os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)
        os.makedirs(temp_folder)

        # Single ffmpeg call to extract *all* frames
        # We'll get (1) ... (N) frames as frame_000001.jpg, frame_000002.jpg, ...
        output_pattern = os.path.join(temp_folder, "frame_%06d.jpg")
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", video_path,
            "-q:v", "2",   # quality
            output_pattern
        ]
        try:
            subprocess.run(ffmpeg_cmd, check=True)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("FFmpeg Error", str(e))
            return

        # Figure out how many images ffmpeg actually extracted
        extracted_frames = sorted(
            f for f in os.listdir(temp_folder) 
            if f.lower().endswith(".jpg") and f.startswith("frame_")
        )
        extracted_count = len(extracted_frames)

        # Parse out the camera number from e.g. "DavidRec02_114.mp4" → camera=14
        # Adjust the logic to match your naming convention:
        camera_raw = video_file.split("_")[-1].replace(".mp4", "")  # e.g. "114"
        camera_id = int(camera_raw) - 100  # Example offset if that is consistent
        # Or if you prefer directly using '114':
        # camera_id = int(camera_raw)

        # The folder where final frames go
        frames_folder = os.path.join(session_folder, "Frames")

        # Move/rename only as many frames as we have valid_frames for
        # i.e. if the video is unexpectedly short or long, handle gracefully
        move_count = min(len(valid_frames), extracted_count)

        for i in range(move_count):
            json_frame_index = valid_frames[i]  # e.g. 100, 101, ...
            # The i-th extracted image is frame_%06d where %06d = i+1
            extracted_name = f"frame_{(i+1):06d}.jpg"
            extracted_path = os.path.join(temp_folder, extracted_name)
            if not os.path.isfile(extracted_path):
                # If for some reason the file doesn't exist, skip
                continue

            # Build the "FrameXXXXX" folder name, zero‐padded
            # according to the *global* digit count
            frame_folder_name = f"Frame{json_frame_index:0{global_digits}d}"
            frame_folder_path = os.path.join(frames_folder, frame_folder_name)
            os.makedirs(frame_folder_path, exist_ok=True)

            # e.g. cam14.jpg
            cam_name = f"cam{camera_id:02d}.jpg"
            final_path = os.path.join(frame_folder_path, cam_name)

            # Move or rename the file
            shutil.move(extracted_path, final_path)

        # Cleanup: remove the temporary extraction folder
        shutil.rmtree(temp_folder)

    
            
            
    
        
        
    
    

    # ---------------------------------------------------------------------
    # Misc
    # ---------------------------------------------------------------------
    def open_local_sessions_folder(self):
        folder = os.path.abspath(SESSIONS_FOLDER)
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

def start_remote_hosts():
    alert_window = show_starting_alert()
    # Load the camera list
    cameras = load_camera_list(CAMERA_LIST_FILE)
    cpu_cores = os.cpu_count()
    workers = cpu_cores * 2

    # Start the script on each camera
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for cam in cameras:
            host_ip = cam["ip"]
            executor.submit(start_script, host_ip)

    alert_window.destroy()
            
def show_starting_alert():
    alert = tk.Toplevel()
    alert.title("Starting Scripts")  # Fenstertitel setzen
    alert.attributes("-topmost", True)

    window_width = 300
    window_height = 60

    # Bildschirmgröße ermitteln
    screen_width = alert.winfo_screenwidth()
    screen_height = alert.winfo_screenheight()

    # Position berechnen, um das Fenster zu zentrieren
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    alert.geometry(f"{window_width}x{window_height}+{x}+{y}")  # Größe und Position setzen

    label = tk.Label(alert, text="Starting Scripts on Raspberry Pi's...")
    label.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
    alert.update()
    return alert
            
def show_stopping_alert():
    alert = tk.Toplevel()
    alert.title("Stopping Scripts")  # Fenstertitel setzen
    alert.attributes("-topmost", True)

    window_width = 300
    window_height = 60

    # Bildschirmgröße ermitteln
    screen_width = alert.winfo_screenwidth()
    screen_height = alert.winfo_screenheight()

    # Position berechnen, um das Fenster zu zentrieren
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    alert.geometry(f"{window_width}x{window_height}+{x}+{y}")  # Größe und Position setzen

    label = tk.Label(alert, text="Stopping Scripts on Raspberry Pi's...")
    label.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
    alert.update()
    return alert

def stop_remote_hosts():
    alert_window = show_stopping_alert()
    # Load the camera list
    cameras = load_camera_list(CAMERA_LIST_FILE)
    cpu_cores = os.cpu_count()
    workers = cpu_cores * 2

    # Start the script on each camera
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for cam in cameras:
            host_ip = cam["ip"]
            executor.submit(stop_script, host_ip)
            
    alert_window.destroy()

def load_camera_list(json_path):
    """
    Load the list of Raspberry Pis (camera IPs) from the specified JSON file.
    Expects format like:
    [
        {"name": "CAM00", "ip": "10.50.100.100"},
        {"name": "CAM01", "ip": "10.50.100.101"},
        ...
    ]
    """
    with open(json_path, 'r') as f:
        return json.load(f)

def ssh_command(ssh_client, command):
    """
    Executes a command over SSH and returns (stdout, stderr) as strings.
    """
    stdin, stdout, stderr = ssh_client.exec_command(command)
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    return out, err

def connect_ssh(host):
    """
    Creates an SSH connection to the specified host. Returns the SSHClient object.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=host, username=USERNAME, password=PASSWORD, timeout=5)
    return ssh

def start_script(host):

    """
    Start the script on the Pi in the background (nohup).
    """
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
    """
    Stop (kill) the given script on the Pi by process name.
    """
    ssh = None
    try:
        ssh = connect_ssh(host)
        cmd = f"pkill -f {SCRIPTNAME}"
        _, err = ssh_command(ssh, cmd)
        # pkill doesn't necessarily return anything on stderr unless there's a problem
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
    app = SessionDownloaderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
