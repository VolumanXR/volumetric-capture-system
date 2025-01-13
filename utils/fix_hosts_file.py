import paramiko
import json
import os
from pathlib import Path

# Load JSON with Pi details
def load_hosts(json_file):
    with open(json_file, 'r') as f:
        return json.load(f)

# Update /etc/hosts on a remote Raspberry Pi
def update_hosts_file(ip, username, password, hostname):
    try:
        # Connect via SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=username, password=password)

        # Backup /etc/hosts
        # backup_cmd = 'sudo cp /etc/hosts /etc/hosts.bak'
        # ssh.exec_command(backup_cmd)

        # Prepare the new hosts content
        update_cmd = f"sudo sed -i 's/^makestep.*/makestep 0.02 3/' /etc/chrony/chrony.conf"
        ssh.exec_command(update_cmd)

        print(f"Updated /etc/hosts on {hostname} ({ip}) successfully.")

        ssh.close()
    except Exception as e:
        print(f"Failed to update /etc/hosts on {hostname} ({ip}): {e}")

# Main function
def main():
    SCRIPT_DIR = Path(__file__).resolve().parent
    json_file = os.path.join(SCRIPT_DIR,'camera_list.json')  # Replace with your JSON filename
    username = "voluman"             # Replace with your Pi username
    password = "xr"      # Replace with your Pi password

    # Load Pi host details
    pi_hosts = load_hosts(json_file)

    # Iterate through each Pi and update its /etc/hosts
    for pi in pi_hosts:
        ip = pi['ip']
        hostname = pi['name']
        update_hosts_file(ip, username, password, hostname)

if __name__ == "__main__":
    main()
