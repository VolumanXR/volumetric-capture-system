import csv
import os
import argparse
import subprocess

filepath_hostname = os.path.join("/etc", "hostname")
filepath_hosts = os.path.join("/etc","hosts")


def configure_hostname(cam_number):
    hostname = f"cam{cam_number}"
    # Read the current contents of /etc/hosts
    with open(filepath_hosts, "r") as file:
        lines = file.readlines()

    # Modify only the last line
    if lines and "127.0.1.1" in lines[-1]:
        lines[-1] = f"127.0.1.1 {hostname}\n"

    # Write the changes back to /etc/hosts
    with open(filepath_hosts, "w") as file:
        file.writelines(lines)

    # Change /etc/hostname
    subprocess.run(["sudo", "sh", "-c", f"echo {hostname} > {filepath_hosts}"], check=True)
    subprocess.run(["sudo", "sh", "-c", f"echo {hostname} > {filepath_hostname}"], check=True)


def configure_ip_address(cam_number):
    ip_address = f"10.50.100.{int(cam_number)+100}"

    nmcli_command = [
    "sudo", "nmcli", "connection", "modify", " preconfigured",
    "ipv4.addresses", ip_address,
    "ipv4.gateway", "10.50.100.2",
    "ipv4.dns", "10.50.100.2",
    "ipv4.method", "Manual",
    "ipv4.ignore-auto-dns", "yes"
]

def parse_arguments():
    parser = argparse.ArgumentParser(description="Specify camera number")
    parser.add_argument("cam_number", help="Number of camera that should be configured")
    return parser.parse_args()

def main():
    args = parse_arguments()
    cam_number = args.cam_number

    configure_hostname(cam_number)
    configure_ip_address(cam_number)

if __name__ == "__main__":
    main()
