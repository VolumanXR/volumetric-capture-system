import tkinter as tk
from tkinter import messagebox
import socket
import threading
import os

# Configuration
RASPBERRY_PI_IPS = ["192.168.179.83"]  # Add all Raspberry Pi IPs here
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
        for ip in ips:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((ip, TCP_PORT))
                sock.sendall(session_name.encode())
                # Receive the file
                file_data = b''
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    if data.startswith(b"ERROR:"):
                        error_message = data.decode()
                        messagebox.showerror("Error", f"From {ip}: {error_message}")
                        break
                    file_data += data
                sock.close()
                if file_data.startswith(b"ERROR:"):
                    continue
                # Determine suffix from IP address
                suffix = '_' + ip.split('.')[-1]
                file_name = f"{session_name}{suffix}.h264"
                file_path = os.path.join(session_folder, file_name)
                with open(file_path, 'wb') as f:
                    f.write(file_data)
                print(f"Session '{session_name}' downloaded from {ip}.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to download session from {ip}: {e}")
        messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully from all available Raspberry Pis.")

if __name__ == "__main__":
    root = tk.Tk()
    app = SessionDownloaderApp(root)
    root.mainloop()
