#!/usr/bin/env python3

import sys
import paramiko

# Credentials
USERNAME = "voluman"
PASSWORD = "xr"

# The content we want to put into /etc/chrony/chrony.conf
CHRONY_CONF_CONTENT = """# Welcome to the chrony configuration file. See chrony.conf(5) for more
# information about usable directives.

# Include configuration files found in /etc/chrony/conf.d.
confdir /etc/chrony/conf.d

# Use Debian vendor zone.
# pool 2.debian.pool.ntp.org iburst

server 10.50.100.5 iburst minpoll 2 maxpoll 2

# Use time sources from DHCP.
sourcedir /run/chrony-dhcp

# Use NTP sources found in /etc/chrony/sources.d.
sourcedir /etc/chrony/sources.d

# This directive specify the location of the file containing ID/key pairs for
# NTP authentication.
keyfile /etc/chrony/chrony.keys

# This directive specify the file into which chronyd will store the rate
# information.
driftfile /var/lib/chrony/chrony.drift

# Save NTS keys and cookies.
ntsdumpdir /var/lib/chrony

# Uncomment the following line to turn logging on.
#log tracking measurements statistics

# Log files location.
logdir /var/log/chrony

# Stop bad estimates upsetting machine clock.
maxupdateskew 100.0

# This directive enables kernel synchronisation (every 11 minutes) of the
# real-time clock. Note that it can't be used along with the 'rtcfile' directive.
rtcsync

# Step the system clock instead of slewing it if the adjustment is larger than
# one second, but only in the first three clock updates.
makestep 0.02 3

# Get TAI-UTC offset and leap seconds from the system tz database.
# This directive must be commented out when using time sources serving
# leap-smeared time.
leapsectz right/UTC
"""

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

        # 2) sudo apt install chrony -y
        print("Installing chrony...")
        out, err = ssh_command(ssh, "sudo apt install chrony -y")
        if err:
            print(f"ERROR during chrony install on {host}:\n{err}")

        # 3) Replace the content of /etc/chrony/chrony.conf
        print("Replacing /etc/chrony/chrony.conf...")
        sftp = ssh.open_sftp()
        with sftp.open("/tmp/chrony.conf", 'w') as f:
            f.write(CHRONY_CONF_CONTENT)
        sftp.close()

        # Move file into place with sudo
        # (We do this separate step because direct writes to /etc might need sudo.)
        move_cmd = "sudo mv /tmp/chrony.conf /etc/chrony/chrony.conf"
        out, err = ssh_command(ssh, move_cmd)
        if err:
            print(f"ERROR placing chrony.conf on {host}:\n{err}")

        # 4) sudo systemctl restart chrony
        print("Restarting chrony...")
        out, err = ssh_command(ssh, "sudo systemctl restart chrony")
        if err:
            print(f"ERROR restarting chrony on {host}:\n{err}")

        # 5) sudo systemctl enable chrony
        print("Enabling chrony...")
        out, err = ssh_command(ssh, "sudo systemctl enable chrony")
        if err:
            print(f"ERROR enabling chrony on {host}:\n{err}")
            
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
