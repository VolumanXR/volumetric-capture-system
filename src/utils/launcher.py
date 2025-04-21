#!/usr/bin/env python3

import os
import sys
from concurrent.futures import ThreadPoolExecutor
import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from lib import config as cfg
from lib.ssh_utils import ssh_command, connect_ssh, load_camera_list

def choose_local_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("tkinter is not installed, please install it or provide a file path explicitly.")
        return None

    root = tk.Tk()
    root.withdraw()

    file_path = filedialog.askopenfilename()
    return file_path if file_path else None

def execute_ssh_command(host, command, success_message, error_message):
    ssh = None
    try:
        ssh = connect_ssh(host)
        _, err = ssh_command(ssh, command)
        if err:
            print(f"[{host}] {error_message}: {err}")
        else:
            print(f"[{host}] {success_message}.")
    except Exception as e:
        print(f"[{host}] {error_message}: {e}")
    finally:
        if ssh:
            ssh.close()

def start_script(host, script_name):
    command = (
        f"nohup python3 /home/voluman/{script_name} > /home/voluman/{script_name}.log 2>&1 &"
    )
    execute_ssh_command(host, command, f"Started {script_name}", f"Failed to start {script_name}")

def stop_script(host, script_name):
    command = f"pkill -f {script_name}"
    execute_ssh_command(host, command, f"Stopped {script_name}", f"Failed to stop {script_name}")

def delete_script(host, script_name):
    command = f"rm /home/voluman/{script_name}"
    execute_ssh_command(host, command, f"Deleted {script_name}", f"Failed to delete {script_name}")

def reboot_pi(host):
    command = "sudo reboot"
    execute_ssh_command(host, command, "Reboot command issued", "Failed to reboot")

def upload_script(host, local_script_path):
    ssh = None
    sftp = None
    try:
        script_basename = os.path.basename(local_script_path)
        ssh = connect_ssh(host)
        sftp = ssh.open_sftp()
        remote_path = f"/home/voluman/{script_basename}"
        sftp.put(local_script_path, remote_path)
        print(f"[{host}] Uploaded {script_basename} to {remote_path}")
    except Exception as e:
        print(f"[{host}] Failed to upload script {local_script_path}: {e}")
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()

def main():
    print("Launcher executed at:", datetime.datetime.now())

    if len(sys.argv) < 2:
        print("Usage:\n"
              f"  {sys.argv[0]} start <script_name>\n"
              f"  {sys.argv[0]} stop <script_name>\n"
              f"  {sys.argv[0]} delete <script_name>\n"
              f"  {sys.argv[0]} reboot\n"
              f"  {sys.argv[0]} upload [<local_script_path>]\n")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command not in ["start", "stop", "reboot", "upload", "delete"]:
        print("Unknown command. Must be one of: start, stop, reboot, upload.")
        sys.exit(1)

    script_arg = None
    if command in ["start", "stop", "delete"]:
        if len(sys.argv) < 3:
            print(f"Error: '{command}' command requires a script name.")
            sys.exit(1)
        script_arg = sys.argv[2]
    elif command == "upload":
        if len(sys.argv) < 3:
            selected_file = choose_local_file()
            if not selected_file:
                print("No file selected. Exiting.")
                sys.exit(0)
            script_arg = selected_file
        else:
            script_arg = sys.argv[2]

    try:
        camera_list = load_camera_list(cfg.CAMERA_LIST_FILE)
    except Exception as e:
        print(f"Failed to load camera list from {cfg.CAMERA_LIST_FILE}: {e}")
        sys.exit(1)

    workers = os.cpu_count() * 2

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
            elif command == "delete":
                executor.submit(delete_script, host_ip, script_arg)

if __name__ == "__main__":
    main()
