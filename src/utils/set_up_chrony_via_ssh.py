#!/usr/bin/env python3

import sys
import paramiko
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from config import config as cfg
from lib.ssh_utils import ssh_command

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

def update_pi(host):
    """Connect to a single Pi via SSH and perform all the required actions."""
    print(f"\n=== Connecting to {host} ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(hostname=host, username=cfg.USERNAME, password=cfg.PASSWORD, timeout=5)
        print(f"Connected to {host}.")

        print("Updating apt...")
        out, err = ssh_command(ssh, "sudo apt update -y")
        if err:
            print(f"ERROR during apt update on {host}:\n{err}")

        print("Installing chrony...")
        out, err = ssh_command(ssh, "sudo apt install chrony -y")
        if err:
            print(f"ERROR during chrony install on {host}:\n{err}")

        print("Replacing /etc/chrony/chrony.conf...")
        sftp = ssh.open_sftp()
        with sftp.open("/tmp/chrony.conf", 'w') as f:
            f.write(CHRONY_CONF_CONTENT)
        sftp.close()

        move_cmd = "sudo mv /tmp/chrony.conf /etc/chrony/chrony.conf"
        out, err = ssh_command(ssh, move_cmd)
        if err:
            print(f"ERROR placing chrony.conf on {host}:\n{err}")

        print("Restarting chrony...")
        out, err = ssh_command(ssh, "sudo systemctl restart chrony")
        if err:
            print(f"ERROR restarting chrony on {host}:\n{err}")

        print("Enabling chrony...")
        out, err = ssh_command(ssh, "sudo systemctl enable chrony")
        if err:
            print(f"ERROR enabling chrony on {host}:\n{err}")

        print("Rebooting.")
        out, err = ssh_command(ssh, "sudo reboot")
        if err:
            print(f"ERROR rebooting on {host}:\n{err}")

        ssh.close()
        print(f"Done with {host}.")

    except Exception as e:
        print(f"Failed to connect to {host} or execute commands: {e}")

def main():
    """Main entry point to parse arguments and update devices."""
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <start_cam> <end_cam>")
        sys.exit(1)

    start_cam = int(sys.argv[1])
    end_cam = int(sys.argv[2])

    for i in range(start_cam, end_cam + 1):
        last_octet = 100 + i
        host_ip = f"10.50.100.{last_octet}"
        camera_label = f"cam{i:02d}"
        print(f"Processing {camera_label} at IP: {host_ip}")
        update_pi(host_ip)

if __name__ == "__main__":
    main()
