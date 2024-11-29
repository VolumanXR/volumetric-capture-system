import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import socket
import threading
import os
import time
import json
import logging

# Configure logging
logging.basicConfig(filename='session_downloader.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s:%(message)s')

# Configuration
RASPBERRY_PI_IPS = ["192.168.179.46", "192.168.179.38"]  # Add all Raspberry Pi IPs here
UDP_PORT = 50005
TCP_PORT = 50006
SESSIONS_FOLDER = "Sessions"  # Folder where sessions will be stored


class SessionDownloaderApp:
    def __init__(self, master):
        self.master = master
        master.title("Session Downloader")

        # Store sessions and their source Raspberry Pis
        self.sessions = set()
        self.session_sources = {}  # session_name -> list of Raspberry Pi IPs

        # Build GUI
        self.create_widgets()

    def create_widgets(self):
        # Session Control Frame
        session_frame = ttk.LabelFrame(self.master, text="Session Controls")
        session_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.get_sessions_button = ttk.Button(session_frame, text="Get Sessions", command=self.get_sessions)
        self.get_sessions_button.grid(row=0, column=0, padx=5, pady=5)

        self.sessions_listbox = tk.Listbox(session_frame, width=50, height=10)
        self.sessions_listbox.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        self.download_button = ttk.Button(session_frame, text="Download Session", command=self.download_session)
        self.download_button.grid(row=2, column=0, padx=5, pady=5)

        session_frame.columnconfigure(0, weight=1)
        session_frame.rowconfigure(1, weight=1)

        # Progress Frame
        progress_frame = ttk.LabelFrame(self.master, text="Progress")
        progress_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        # Current File Progress
        self.current_file_label = ttk.Label(progress_frame, text="Current File:")
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

    def get_sessions(self):
        threading.Thread(target=self.get_sessions_thread, daemon=True).start()

    def get_sessions_thread(self):
        self.sessions.clear()
        self.session_sources.clear()
        threads = []
        for ip in RASPBERRY_PI_IPS:
            t = threading.Thread(target=self.get_sessions_from_pi, args=(ip,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        # Update the listbox
        self.update_sessions_listbox()
        messagebox.showinfo("Info", "Session list updated.")

    def get_sessions_from_pi(self, ip):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(5)
                request = {'action': 'GET_SESSIONS'}
                sock.sendto(json.dumps(request).encode(), (ip, UDP_PORT))
                data, _ = sock.recvfrom(4096)
                response = json.loads(data.decode())
                sessions = response.get('sessions', [])
                for session in sessions:
                    self.sessions.add(session)
                    self.session_sources.setdefault(session, []).append(ip)
                logging.info(f"Received sessions from {ip}: {sessions}")
        except Exception as e:
            logging.error(f"Failed to get sessions from {ip}: {e}", exc_info=True)

    def update_sessions_listbox(self):
        def update():
            self.sessions_listbox.delete(0, tk.END)
            for session in sorted(self.sessions):
                self.sessions_listbox.insert(tk.END, session)
        self.master.after(0, update)

    def download_session(self):
        selected_indices = self.sessions_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_name = self.sessions_listbox.get(selected_indices[0])
        threading.Thread(target=self.download_session_thread, args=(session_name,), daemon=True).start()

    def download_session_thread(self, session_name):
        ips = self.session_sources.get(session_name, [])
        if not ips:
            messagebox.showerror("Error", f"No Raspberry Pis have the session '{session_name}'.")
            return
        # Create session folder
        session_folder = os.path.join(SESSIONS_FOLDER, session_name)
        os.makedirs(session_folder, exist_ok=True)

        total_files = len(ips)
        completed_files = 0
        total_bytes = 0
        total_received = 0
        overall_start_time = None  # Initialize as None
        self.update_overall_progress(0, overall_start_time)  # Pass None for start_time

        for ip in ips:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10)
                    sock.connect((ip, TCP_PORT))
                    request = {'action': 'DOWNLOAD_SESSION', 'session_name': session_name}
                    sock.sendall(json.dumps(request).encode())

                    # Receive the response
                    response_data = self.recvall(sock, 1024)
                    if not response_data:
                        raise Exception("Failed to receive data.")
                    response = json.loads(response_data.decode())

                    if response.get('status') != 'OK':
                        error_message = response.get('message', 'Unknown error.')
                        messagebox.showerror("Error", f"From {ip}: {error_message}")
                        continue

                    file_size = response.get('file_size', 0)
                    total_bytes += file_size

                    # Start the overall timer when we start downloading the first file
                    if overall_start_time is None:
                        overall_start_time = time.time()

                    # Determine suffix from IP address
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
                            # Update progress bars
                            if total_bytes > 0:
                                overall_percentage = total_received / total_bytes * 100
                            else:
                                overall_percentage = 0
                            self.update_current_progress(bytes_received, file_size, start_time)
                            self.update_overall_progress(overall_percentage, overall_start_time)
                    if bytes_received < file_size:
                        raise Exception("Connection lost during file transfer.")
                    completed_files += 1
                    logging.info(f"Downloaded session from {ip} successfully.")
            except Exception as e:
                logging.error(f"Failed to download session from {ip}: {e}", exc_info=True)
                messagebox.showerror("Error", f"Failed to download session from {ip}: {e}")

        self.update_current_file_info("N/A", "N/A")
        self.update_current_progress(0, 1, 0)
        if overall_start_time is not None:
            self.update_overall_progress(100, overall_start_time)
        else:
            self.update_overall_progress(100, time.time())
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully from all available Raspberry Pis.")

    def recvall(self, sock, n):
        """Helper function to receive n bytes or return None if EOF is hit"""
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return data  # Return what we have so far
            data += packet
        return data

    def update_current_file_info(self, ip, file_name):
        def update():
            self.current_file_info_label.config(text=f"IP: {ip}, File: {file_name}")
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

    def update_overall_progress(self, percentage, start_time):
        if start_time is None or percentage == 0:
            eta_formatted = "Calculating..."
        else:
            elapsed_time = time.time() - start_time
            eta = (100 - percentage) * (elapsed_time / percentage) if percentage > 0 else float('inf')
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


if __name__ == "__main__":
    root = tk.Tk()
    app = SessionDownloaderApp(root)
    root.mainloop()
