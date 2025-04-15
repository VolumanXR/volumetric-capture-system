#!/usr/bin/env python3

import os
import sys
import json
import paramiko
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime

# ----------------------------------------------------
# Configuration
# ----------------------------------------------------
USERNAME = "voluman"
PASSWORD = "xr"
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST_JSON = os.path.join(SCRIPT_DIR, 'camera_list.json') 

# ----------------------------------------------------
# Optional: only import tkinter if needed
# ----------------------------------------------------
def choose_local_file():
    """
    Opens a GUI file dialog (if display available) to let the user select a file.
    Returns the selected filepath or None if canceled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("tkinter is not installed, please install it or provide a file path explicitly.")
        return None

    root = tk.Tk()
    root.withdraw()  # Hide the main tkinter window

    # Show open file dialog
    file_path = filedialog.askopenfilename()
    return file_path if file_path else None

# ----------------------------------------------------
# Helper Functions
# ----------------------------------------------------
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

# ----------------------------------------------------
# Operations
# ----------------------------------------------------
def start_script(host, script_name):
    """
    Start the script on the Pi in the background (nohup).
    """
    ssh = None
    try:
        ssh = connect_ssh(host)
        cmd = (
            f"nohup python3 /home/voluman/{script_name} "
            f"> /home/voluman/{script_name}.log 2>&1 &"
        )
        _, err = ssh_command(ssh, cmd)
        if err:
            print(f"[{host}] Error starting {script_name}: {err}")
        else:
            print(f"[{host}] Started {script_name}.")
    except Exception as e:
        print(f"[{host}] Failed to start {script_name}: {e}")
    finally:
        if ssh:
            ssh.close()

def stop_script(host, script_name):
    """
    Stop (kill) the given script on the Pi by process name.
    """
    ssh = None
    try:
        ssh = connect_ssh(host)
        cmd = f"pkill -f {script_name}"
        _, err = ssh_command(ssh, cmd)
        # pkill doesn't necessarily return anything on stderr unless there's a problem
        if err:
            print(f"[{host}] Possible error stopping {script_name}: {err}")
        else:
            print(f"[{host}] Stopped {script_name}.")
    except Exception as e:
        print(f"[{host}] Failed to stop {script_name}: {e}")
    finally:
        if ssh:
            ssh.close()

def reboot_pi(host):
    """
    Reboot the Pi.
    """
    ssh = None
    try:
        ssh = connect_ssh(host)
        _, err = ssh_command(ssh, "sudo reboot")
        if err:
            print(f"[{host}] Error during reboot: {err}")
        else:
            print(f"[{host}] Reboot command issued.")
    except Exception as e:
        print(f"[{host}] Failed to reboot: {e}")
    finally:
        if ssh:
            ssh.close()

def upload_script(host, local_script_path):
    """
    Upload (replace) the local script to /home/voluman on the Pi.
    """
    ssh = None
    sftp = None
    try:
        script_basename = os.path.basename(local_script_path)
        ssh = connect_ssh(host)
        sftp = ssh.open_sftp()
        remote_path = f"/home/voluman/{script_basename}"

        # Put the file to the Pi (this overwrites if it exists)
        sftp.put(local_script_path, remote_path)
        print(f"[{host}] Uploaded {script_basename} to {remote_path}")
    except Exception as e:
        print(f"[{host}] Failed to upload script {local_script_path}: {e}")
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()

# ----------------------------------------------------
# Main
# ----------------------------------------------------
def main():
    # print executed time
    print("Launcher executed at: ", datetime.datetime.now())
    """
    Possible commands:
      - start <script_name>
      - stop <script_name>
      - reboot
      - upload [<local_script_path>]
        If <local_script_path> is not given, show file explorer.
    """
    if len(sys.argv) < 2:
        print("Usage:\n"
              f"  {sys.argv[0]} start <script_name>\n"
              f"  {sys.argv[0]} stop <script_name>\n"
              f"  {sys.argv[0]} reboot\n"
              f"  {sys.argv[0]} upload [<local_script_path>]\n")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command not in ["start", "stop", "reboot", "upload"]:
        print("Unknown command. Must be one of: start, stop, reboot, upload.")
        sys.exit(1)

    # If the command needs a script name or path, handle that
    script_arg = None
    if command in ["start", "stop"]:
        # These commands require a script_name
        if len(sys.argv) < 3:
            print(f"Error: '{command}' command requires a script name.")
            sys.exit(1)
        script_arg = sys.argv[2]
    elif command == "upload":
        # If user did not provide a file path, open file explorer
        if len(sys.argv) < 3:
            selected_file = choose_local_file()
            if not selected_file:
                print("No file selected. Exiting.")
                sys.exit(0)
            script_arg = selected_file
        else:
            # Use the file path from CLI
            script_arg = sys.argv[2]

    # Load camera_list
    try:
        camera_list = load_camera_list(CAMERA_LIST_JSON)
    except Exception as e:
        print(f"Failed to load camera list from {CAMERA_LIST_JSON}: {e}")
        sys.exit(1)
    
    cpu_cores = os.cpu_count()
    workers = cpu_cores * 2

    # Iterate over all cameras
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for cam in camera_list:
            host_ip = cam["ip"]

            if command == "start":
                executor.submit(start_script, host_ip, script_arg)
            elif command == "stop":
                executor.submit(stop_script, host_ip, script_arg)
            elif command == "reboot":
                executor.submit(reboot_pi, host_ip)
            elif command == "upload":
                executor.submit(upload_script, host_ip, script_arg)

if __name__ == "__main__":
    main()
