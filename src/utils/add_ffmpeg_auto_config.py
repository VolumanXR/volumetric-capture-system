#!/usr/bin/env python3

import sys
import paramiko

# Credentials
USERNAME = "voluman"
PASSWORD = "xr"



def ssh_command(ssh, command):
    """
    Executes a command over SSH and returns stdout, stderr.
    """
    stdin, stdout, stderr = ssh.exec_command(command)
    # If you need to supply a password for sudo, uncomment the lines below:
    # stdin.write(PASSWORD + '\n')
    # stdin.flush()
    out = stdout.read().decode('utf-8')
    err = stderr.read().decode('utf-8')
    return out, err

def update_pi(host):
    """
    Connect to a single Pi via SSH and perform all the required actions.
    """
    print(f"\n=== Connecting to {host} ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(hostname=host, username=USERNAME, password=PASSWORD, timeout=5)
        print(f"Connected to {host}.")

        # 1) sudo apt update
        print("Updating apt...")
        out, err = ssh_command(ssh, "sudo apt update -y")
        if err:
            print(f"ERROR during apt update on {host}:\n{err}")

        # 2) sudo apt install ffmpeg -y
        print("Installing chrony...")
        out, err = ssh_command(ssh, "sudo apt install ffmpeg -y")
        if err:
            print(f"ERROR during chrony install on {host}:\n{err}")
            
        # 6) sudo reboot
        print("Rebooting.")
        out, err = ssh_command(ssh, "sudo reboot")
        if err:
            print(f"ERROR rebooting on {host}:\n{err}")

        ssh.close()
        print(f"Done with {host}.")

    except Exception as e:
        print(f"Failed to connect to {host} or execute commands: {e}")

def main():
    """
    Main entry point:
    - Parse command-line arguments for first and last camera index
    - Loop over range, build IP, skip cameras 16 and 17
    - Call update_pi for each host
    """
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <start_cam> <end_cam>")
        sys.exit(1)

    start_cam = int(sys.argv[1])
    end_cam = int(sys.argv[2])

    # Example: cam01 => 10.50.100.100, cam64 => 10.50.100.164
    # We'll assume IP = 10.50.100.(99 + i) or 10.50.100.(100 + i - 1)
    # to align with the "cam01 => 10.50.100.100" statement.

    for i in range(start_cam, end_cam + 1):
        

        # Build the IP:
        # If cam1 => 10.50.100.100, that implies 100 = 99 + 1
        # So IP last octet = 99 + i
        # Check that for cam64 => 99 + 64 = 163 (the user said 164, but we'll trust the offset approach).
        # If you absolutely need cam64 => 10.50.100.164, use 100 + i instead.
        last_octet = 100 + i
        host_ip = f"10.50.100.{last_octet}"

        # Optional: If you want cam64 => 10.50.100.164, uncomment this line instead:
        # last_octet = 100 + (i - 1)

        # Format camera label just for printing/logging
        camera_label = f"cam{i:02d}"
        print(f"Processing {camera_label} at IP: {host_ip}")

        # Call function to update the Pi
        update_pi(host_ip)

if __name__ == "__main__":
    main()
