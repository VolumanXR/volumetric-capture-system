import tkinter as tk
from tkinter import messagebox
import socket
import threading
import os

# Configuration
UDP_IP = "192.168.179.83"  # Raspberry Pi IP
UDP_PORT = 50005
TCP_IP = "192.168.179.83"
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

    def get_sessions(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.sendto(b"GET_SESSIONS", (UDP_IP, UDP_PORT))
            data, addr = sock.recvfrom(4096)
            sessions = data.decode().split(',')
            self.sessions_listbox.delete(0, tk.END)
            for session in sessions:
                self.sessions_listbox.insert(tk.END, session)
            messagebox.showinfo("Info", "Session list updated.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to get sessions: {e}")

    def download_session(self):
        selected_indices = self.sessions_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Warning", "No session selected.")
            return
        session_name = self.sessions_listbox.get(selected_indices[0])
        threading.Thread(target=self.download_session_thread, args=(session_name,)).start()

    def download_session_thread(self, session_name):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((TCP_IP, TCP_PORT))
            sock.sendall(session_name.encode())
            # Create session folder
            session_folder = os.path.join(SESSIONS_FOLDER, session_name)
            os.makedirs(session_folder, exist_ok=True)
            # Receive the file
            file_path = os.path.join(session_folder, session_name + ".h264")
            with open(file_path, 'wb') as f:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    if data.startswith(b"ERROR:"):
                        error_message = data.decode()
                        messagebox.showerror("Error", error_message)
                        os.remove(file_path)  # Remove incomplete file
                        return
                    f.write(data)
            sock.close()
            messagebox.showinfo("Success", f"Session '{session_name}' downloaded successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to download session: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SessionDownloaderApp(root)
    root.mainloop()
