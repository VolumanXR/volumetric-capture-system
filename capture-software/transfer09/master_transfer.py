# master_transfer.py v9.1
import tkinter as tk
from tkinter import ttk, messagebox
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
MAX_SIMULTANEOUS_DOWNLOADS = 10

SCRIPTNAME = 'remote_transfer.py'
USERNAME = 'voluman'
PASSWORD = 'xr'

class SessionDownloaderApp:
    def __init__(self, master, on_close_callback=None):
        start_remote_hosts()
        self.master = master
        self.master.title("Download Manager (Threaded Session Query)")

        self.on_close_callback = on_close_callback  # Store the callback

        self.sessions = []           # list of session names
        self.session_info = {}       # {session_name: {"clip_sizes": {camera_name: size_or_none}}}

        self.total_bytes = 0
        self.total_received = 0
        self.download_start_time = 0
        self.download_lock = threading.Lock()

        self.create_widgets()
        os.makedirs(SESSIONS_FOLDER, exist_ok=True)

        # Kick off initial retrieval
        self.get_sessions()
        self.schedule_refresh()

    def _handle_close(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

    def create_widgets(self):
        # Frame
        frame = ttk.LabelFrame(self.master, text="Session Controls")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Buttons
        self.refresh_button = ttk.Button(frame, text="Refresh", command=self.get_sessions)
        self.refresh_button.grid(row=0, column=0, padx=5, pady=5, sticky="w")

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
        action_frame.grid(row=2, column=0, columnspan=4, pady=5)

        btn_download = ttk.Button(action_frame, text="Download Session", command=self.download_session)
        btn_download.pack(side="left", padx=5)

        btn_delete_local = ttk.Button(action_frame, text="Delete Session (Local)", command=self.delete_session_local)
        btn_delete_local.pack(side="left", padx=5)

        btn_delete_remote = ttk.Button(action_frame, text="Delete Session (Remote)", command=self.delete_session_remote)
        btn_delete_remote.pack(side="left", padx=5)
        
        btn_delete_all_remote = ttk.Button(action_frame, text="Delete All (Remote)", command=self.delete_all_sessions_remote)
        btn_delete_all_remote.pack(side="left", padx=5)

        btn_open_folder = ttk.Button(action_frame, text="Open Local Folder", command=self.open_local_sessions_folder)
        btn_open_folder.pack(side="left", padx=5)

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
    # Load the camera list
    cameras = load_camera_list(CAMERA_LIST_FILE)

    # Start the script on each camera
    with ThreadPoolExecutor(max_workers=10) as executor:
        for cam in cameras:
            host_ip = cam["ip"]
            executor.submit(start_script, host_ip)
            
def show_stopping_alert():
    alert = tk.Toplevel()
    alert.title("Stopping Scripts")  # Fenstertitel setzen

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

    # Start the script on each camera
    with ThreadPoolExecutor(max_workers=10) as executor:
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
