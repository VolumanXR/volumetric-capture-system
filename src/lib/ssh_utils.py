from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import socket
import subprocess
import ipaddress
import paramiko
import tkinter as tk
import sys
from PIL import Image, ImageTk
from enum import Enum, auto
from datetime import datetime

if getattr(sys, 'frozen', False):
    # Running in a bundle
    project_root = os.path.dirname(sys.executable)
else:
    # Running in normal Python
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

if project_root not in sys.path:
    sys.path.append(project_root)

from config import config as cfg

class RemoteScript(Enum):
    CAMERACONTROLLER = 'remote_camera_controller.py'
    CAPTURECONTROLLER = 'remote_capture_controller.py'
    DOWNLOADMANAGER = 'remote_transfer.py'

def get_ip_address_in_network(target_network="10.50.100.0/24"):
    """
    Gibt die aktuelle IP-Adresse des Hosts zurück, die Teil des angegebenen Netzwerks ist.
    
    :param target_network: Das Zielnetzwerk im CIDR-Format. Standardmäßig "10.50.100.0/24".
    :return: Die IP-Adresse als String oder None, wenn keine passende IP gefunden wurde.
    """
    try:
        # Versuche, die IP über eine Socket-Verbindung zu ermitteln
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Verbinde zu einem externen Server (hier Google DNS)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        
        # Prüfe, ob die IP im Zielnetzwerk liegt
        if ipaddress.ip_address(ip) in ipaddress.ip_network(target_network):
            return ip
    except Exception:
        pass
    
    # Fallback: Verwende 'ipconfig' und parse die Ausgabe
    try:
        output = subprocess.check_output("ipconfig", encoding='utf-8')
        # Suche nach IPv4-Adressen
        ipv4_addresses = re.findall(r'IPv4-Adresse[.\s]*: ([\d.]+)', output)
        for ip in ipv4_addresses:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(target_network):
                return ip
    except Exception as e:
        print(f"Fehler beim Abrufen der IP-Adresse: {e}")
    
    return None

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
    ssh.connect(hostname=host, username=cfg.USERNAME, password=cfg.PASSWORD, timeout=5)
    return ssh

def update_dist_time():
    """
    Updates the system time on a remote host via SSH.
    """
    try:
        # Get the current system time
        current_time = datetime.now().strftime("%d %b %Y %H:%M:%S")
        command = f'sudo date -s "{current_time}"'

        # Establish SSH connection
        ssh_client = connect_ssh(cfg.NTP_DIST_IP)

        # Execute the command over SSH
        output, errors = ssh_command(ssh_client, command)

        # Print output and errors if any
        if output:
            print("Output:", output)
        if errors:
            print("Errors:", errors)

        # Close the SSH connection
        ssh_client.close()

    except Exception as e:
        print(f"Error occurred: {e}")

def start_remote_hosts(root, script_to_start):

    alert_window = show_starting_alert()
    # Load the camera list
    cameras = load_camera_list(cfg.CAMERA_LIST_FILE)
    master_voluman_net_ip = get_ip_address_in_network()
    cpu_cores = os.cpu_count()
    workers = cpu_cores * 2

    # Start the script on each camera
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for cam in cameras:
            host_ip = cam.get("ip")
            custom_lens_position = cam.get("lens_position", None)
            executor.submit(start_script, host_ip, script_to_start, master_voluman_net_ip, custom_lens_position)
            
    alert_window.destroy()
    root.lift()
    root.focus_force()

def start_script(host, script_to_start, master_voluman_net_ip, custom_lens_position):

    """
    Start the script on the Pi in the background (nohup).
    """
    ssh = None
    try:
        ssh = connect_ssh(host)
        if script_to_start is RemoteScript.CAPTURECONTROLLER:
            cmd = (
            f"nohup python3 /home/voluman/{script_to_start.value} {master_voluman_net_ip} {custom_lens_position}"
            f"> /home/voluman/{script_to_start.value}.log 2>&1 &"
            )
        elif script_to_start is RemoteScript.DOWNLOADMANAGER or script_to_start is RemoteScript.CAMERACONTROLLER:
            cmd = (
            f"nohup python3 /home/voluman/{script_to_start.value} "
            f"> /home/voluman/{script_to_start.value}.log 2>&1 &"
            )
        else:
            cmd = (
            f"nohup python3 /home/voluman/{script_to_start} "
            f"> /home/voluman/{script_to_start}.log 2>&1 &"
            )
        _, err = ssh_command(ssh, cmd)
        if err:
            print(f"[{host}] Error starting {script_to_start.value}: {err}")
        else:
            print(f"[{host}] Started {script_to_start.value}.")
    except Exception as e:
        print(f"[{host}] Failed to start {script_to_start.value}: {e}")
    finally:
        if ssh:
            ssh.close()

def stop_remote_hosts(script_to_stop):
    alert_window = show_stopping_alert()
    
    # Load the camera list
    cameras = load_camera_list(cfg.CAMERA_LIST_FILE)
    cpu_cores = os.cpu_count()
    workers = cpu_cores * 2

    # Start the script on each camera
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for cam in cameras:
            host_ip = cam["ip"]
            executor.submit(stop_script, host_ip, script_to_stop)
    
    alert_window.destroy()

def stop_script(host, script_stop):
    """
    Stop (kill) the given script on the Pi by process name.
    """
    ssh = None
    try:
        ssh = connect_ssh(host)
        cmd = f"pkill -f {script_stop.value}"
        _, err = ssh_command(ssh, cmd)
        # pkill doesn't necessarily return anything on stderr unless there's a problem
        if err:
            print(f"[{host}] Possible error stopping {script_stop.value}: {err}")
        else:
            print(f"[{host}] Stopped {script_stop.value}.")
    except Exception as e:
        print(f"[{host}] Failed to stop {script_stop.value}: {e}")
    finally:
        if ssh:
            ssh.close()

def show_starting_alert():
    alert = tk.Toplevel()
    alert.overrideredirect(True)
    alert.title("Starting Scripts")
    alert.attributes("-topmost", True)
    
    # Set background color of the alert window
    background_color = "#EEEEEE"  # Light blue; change as desired
    alert.configure(bg=background_color)
    
    # Set the window icon if available.
    if os.path.exists(cfg.ICON_PATH):
        alert.iconbitmap(cfg.ICON_PATH)
    
    # Increase window height to accommodate the logo and text.
    window_width = 300
    window_height = 400
    screen_width = alert.winfo_screenwidth()
    screen_height = alert.winfo_screenheight()
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    alert.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    if os.path.exists(cfg.LOGO_PATH):
        # Open the image using Pillow
        img = Image.open(cfg.LOGO_PATH)
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
    if os.path.exists(cfg.ICON_PATH):
        alert.iconbitmap(cfg.ICON_PATH)
    
    # Increase window height to accommodate the logo and text.
    window_width = 300
    window_height = 400
    screen_width = alert.winfo_screenwidth()
    screen_height = alert.winfo_screenheight()
    x = (screen_width // 2) - (window_width // 2)
    y = (screen_height // 2) - (window_height // 2)
    alert.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    if os.path.exists(cfg.LOGO_PATH):
        # Open the image using Pillow
        img = Image.open(cfg.LOGO_PATH)
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
