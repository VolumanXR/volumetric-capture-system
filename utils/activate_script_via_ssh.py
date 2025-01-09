import json
import paramiko
import os
import argparse
from pathlib import Path

# Directory setup
SCRIPT_DIR = Path(__file__).resolve().parent
CAMERA_LIST = os.path.join(SCRIPT_DIR,'camera_list.json')  # Adjusts to a sister directory

# Replace with your actual username and password
USERNAME = "voluman"
PASSWORD = "xr"

# Python script names
REMOTE_TRANSFER_SCRIPT = "remote_transfer.py"
REMOTE_SM_SCRIPT = "remote_sm.py"

def ssh_execute_command(hostname, username, password, command):
    """Connect to the host and execute a command via SSH."""
    try:
        # Create an SSH client
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Connect to the host
        print(f"Connecting to {hostname}...")
        client.connect(hostname, username=username, password=password)

        print(f"Executing command on {hostname}: {command}")
        stdin, stdout, stderr = client.exec_command(command)
        print(f"Output:\n{stdout.read().decode()}")
        print(f"Error:\n{stderr.read().decode()}")

        # Close the SSH connection
        client.close()

    except Exception as e:
        print(f"An error occurred while connecting to {hostname}: {e}")

def stop_script(hostname, username, password, script_to_stop):
    """Stop a script on the remote host."""
    stop_command = f"kill -2 $(pgrep -f {script_to_stop})"
    print(f"Stopping script {script_to_stop} on {hostname}...")
    ssh_execute_command(hostname, username, password, stop_command)

def start_script(hostname, username, password, script_to_start):
    """Start a script on the remote host."""
    start_command = f"nohup python3 {script_to_start} > /dev/null 2>&1 &"
    print(f"Starting script {script_to_start} on {hostname}...")
    ssh_execute_command(hostname, username, password, start_command)

def main(action):
    # Determine which scripts to stop/start based on the action
    if action == "r":
        script_to_stop = REMOTE_TRANSFER_SCRIPT
        script_to_start = REMOTE_SM_SCRIPT
    elif action == "t":
        script_to_stop = REMOTE_SM_SCRIPT
        script_to_start = REMOTE_TRANSFER_SCRIPT
    else:
        print("Invalid action specified!")
        return

    # Load hosts from JSON file
    if not os.path.isfile(CAMERA_LIST):
        print(f"JSON file not found at {CAMERA_LIST}")
        return

    with open(CAMERA_LIST, "r") as file:
        hosts = json.load(file)

    # Iterate over each host
    for host in hosts:
        hostname = host.get("name")
        ip_address = host.get("ip")
        if hostname and ip_address:
            # Stop the specified script
            stop_script(ip_address, USERNAME, PASSWORD, script_to_stop)

            # Start the specified script
            start_script(ip_address, USERNAME, PASSWORD, script_to_start)
        else:
            print(f"Invalid entry in JSON: {host}")

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Manage remote Python scripts.")
    parser.add_argument(
        "-r",
        action="store_true",
        help="Stop remote_transfer.py and start remote_sm.py",
    )
    parser.add_argument(
        "-t",
        action="store_true",
        help="Stop remote_sm.py and start remote_transfer.py",
    )
    args = parser.parse_args()

    if args.r:
        main("r")
    elif args.t:
        main("t")
    else:
        print("Please specify an action with -r or -t.")
