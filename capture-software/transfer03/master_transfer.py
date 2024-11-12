import tkinter as tk
from tkinter import ttk, messagebox
import socket
import threading
import os
import time
import struct

# Configuration
RASPBERRY_PI_IPS = ["192.168.179.46", "192.168.179.38"]  # Add all Raspberry Pi IPs here
UDP_PORT = 50005
TCP_PORT = 50006
SESSIONS_FOLDER = "Sessions"  # Folder where sessions will be stored

class SessionDownloaderApp:
    def __init__(self, master):
        self.master = master
        master.title("Session Downloader")

        self.get_sessions_button = tk.Button(master, text="Get Sessions", command=self.get_sessions)
        self.get_sessions_button.pack(pady=10)

        self.sessions_listbox = tk.Listbox(master, width=50)
        self.sessions_listbox.pack(pady=10)

        self.download_button = tk.Button(master, text="Download Session", command=self.download_session)
        self.download_button.pack(pady=10)

        # Progress Bars and Labels
        self.current_file_label = tk.Label(master, text="Current File: N/A")
        self.current_file_label.pack(pady=(20, 0))

        self.current_file_info_label = tk.Label(master, text="IP: N/A, File: N/A")
        self.current_file_info_label.pack()

        self.current_progress = ttk.Progressbar(master, length=400, mode='determinate')
        self.current_progress.pack(pady=5)

        self.current_eta_label = tk.Label(master, text="ETA: N/A")
        self.current_eta_label.pack()

        self.overall_progress_label = tk.Label(master, text="Overall Progress")
        self.overall_progress_label.pack(pady=(20, 0))

        self.overall_progress = ttk.Progressbar(master, length=400, mode='determinate')
        self.overall_progress.pack(pady=5)

        self.overall_eta_label = tk.Label(master, text="ETA: N/A")
        self.overall_eta_label.pack()

        # Store sessions and their source Raspberry Pis
        self.sessions = set()
        self.session_sources = {}  # session_name -> list of Raspberry Pi IPs

    def get_sessions(self):
        self.sessions.clear()
        self.session_sources.clear()
        threads = []
        for ip in RASPBERRY_PI_IPS:
            t = threading.Thread(target=self.get_sessions_from_pi, args=(ip,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        # Update the listbox
        self.sessions_listbox.delete(0, tk.END)
        for session in sorted(self.sessions):
            self.sessions_listbox.insert(tk.END, session)
        messagebox.showinfo("Info", "Session list updated.")

    def get_sessions_from_pi(self, ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.sendto(b"GET_SESSIONS", (ip, UDP_PORT))
            data, addr = sock.recvfrom(4096)
            sessions = data.decode().split(',')
            for session in sessions:
                self.sessions.add(session)
                self.session_sources.setdefault(session, []).append(ip)
            print(f"Received sessions from {ip}: {sessions}")
        except Exception as e:
            print(f"Failed to get sessions from {ip}: {e}")

    def download_session(self):
        selected_indices = self.sessions_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_name = self.sessions_listbox.get(selected_indices[0])
        threading.Thread(target=self.download_session_thread, args=(session_name,)).start()

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
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((ip, TCP_PORT))
                sock.sendall(session_name.encode())

                # Receive the first 8 bytes (file size or error message)
                first_data = self.recvall(sock, 8)
                if not first_data:
                    raise Exception("Failed to receive data.")

                # Check if it's an error message
                if first_data.startswith(b"ERROR"):
                    # Receive the rest of the error message
                    error_message = first_data + sock.recv(1024)
                    messagebox.showerror("Error", f"From {ip}: {error_message.decode()}")
                    sock.close()
                    continue

                # Try to unpack the file size
                try:
                    file_size = struct.unpack('!Q', first_data)[0]
                except struct.error:
                    # If unpacking fails, it's likely an error message
                    error_message = first_data + sock.recv(1024)
                    messagebox.showerror("Error", f"From {ip}: {error_message.decode()}")
                    sock.close()
                    continue

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
                sock.close()
                completed_files += 1
            except Exception as e:
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
                return None
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
        if start_time is None:
            eta_formatted = "Calculating..."
        else:
            elapsed_time = time.time() - start_time
            total_percentage = percentage
            eta = (100 - total_percentage) * (elapsed_time / total_percentage) if total_percentage > 0 else float('inf')
            eta_formatted = self.format_eta(eta)

        def update():
            self.overall_progress['value'] = percentage
            self.overall_eta_label.config(text=f"ETA: {eta_formatted}")
        self.master.after(0, update)

    def format_eta(self, eta_seconds):
        if eta_seconds == float('inf'):
            return "Calculating..."
        minutes, seconds = divmod(int(eta_seconds), 60)
        return f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

if __name__ == "__main__":
    root = tk.Tk()
    app = SessionDownloaderApp(root)
    root.mainloop()
