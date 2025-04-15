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

def replace_script(hostname, username, password, local_script_path, remote_script_path):
    """Replace a script on the remote host."""
    try:
        if not os.path.exists(local_script_path):
            print(f"The local script {local_script_path} does not exist.")
            return
        transport = paramiko.Transport((hostname, 22))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(local_script_path, remote_script_path)
        print(f"Uploaded {local_script_path} to {hostname}:{remote_script_path}")
        sftp.close()
        transport.close()
    except Exception as e:
        print(f"An error occurred while uploading the script to {hostname}: {e}")

def main(action=None, update_filepath=None):
    """Main function to manage scripts on remote hosts."""
    # Load hosts from JSON file
    if not os.path.isfile(CAMERA_LIST):
        print(f"JSON file not found at {CAMERA_LIST}")
        return

    with open(CAMERA_LIST, "r") as file:
        hosts = json.load(file)

    # Identify the script to replace
    remote_script_name = None
    if update_filepath:
        local_script_name = os.path.basename(update_filepath)
        if local_script_name == REMOTE_TRANSFER_SCRIPT:
            remote_script_name = REMOTE_TRANSFER_SCRIPT
        elif local_script_name == REMOTE_SM_SCRIPT:
            remote_script_name = REMOTE_SM_SCRIPT
        else:
            print(f"Error: The script name '{local_script_name}' does not match '{REMOTE_TRANSFER_SCRIPT}' or '{REMOTE_SM_SCRIPT}'.")
            return
    elif action == "r":
        script_to_stop = REMOTE_TRANSFER_SCRIPT
        script_to_start = REMOTE_SM_SCRIPT
    elif action == "t":
        script_to_stop = REMOTE_SM_SCRIPT
        script_to_start = REMOTE_TRANSFER_SCRIPT
    elif action == "b":
        pass
    else:
        print("Invalid action specified!")
        return

    # Iterate over each host
    for host in hosts:
        hostname = host.get("name")
        ip_address = host.get("ip")
        if hostname and ip_address:
            if action == "b":
                command = f"sudo reboot"
                ssh_execute_command(ip_address, USERNAME, PASSWORD, command)
            elif update_filepath:
                stop_script(ip_address, USERNAME, PASSWORD, remote_script_name)
                replace_script(ip_address, USERNAME, PASSWORD, update_filepath, remote_script_name)
            else:
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
    parser.add_argument(
        "-u",
        metavar="FILE",
        help="Specify a local file to upload to all remote hosts",
    )
    parser.add_argument(
        "-b",
        action="store_true",
        help="Reboot system",
    )
    args = parser.parse_args()
    if args.r:
        main("r")
    elif args.t:
        main("t")
    elif args.u:
        # If -u is specified, only update scripts
        main(update_filepath=args.u)
    elif args.b:
        main("b")
    else:
        print("Please specify an action with -u.")