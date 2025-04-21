import paramiko
import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from lib import config as cfg
from lib.ssh_utils import ssh_command, connect_ssh

def set_camera_number(ssh_client, cam_number):
    try:
        set_cam_command = f"sudo -S python3 remote_set_cam_number.py {cam_number}"
        out, err = ssh_command(ssh_client, set_cam_command)
        print("Output (set cam number):")
        print(out)
        if "unable to resolve host" in err:
            err = err.replace("unable to resolve host", "")  # Remove non-critical error message
        print("Errors (set cam number):")
        print(err)
    except Exception as e:
        print(f"An error occurred while setting the camera number: {e}")

def reboot_system(ssh_client):
    try:
        reboot_command = "sudo reboot"
        out, err = ssh_command(ssh_client, reboot_command)
        print("Output (reboot):")
        print(out)
        print("Errors (reboot):")
        print(err)
    except Exception as e:
        print(f"An error occurred while rebooting the system: {e}")

def run_remote_script(host, cam_number):
    try:
        ssh_client = connect_ssh(host)
        print(f"Connected to {host}")

        set_camera_number(ssh_client, cam_number)
        reboot_system(ssh_client)

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        if 'ssh_client' in locals():
            ssh_client.close()
            print("Connection closed.")

def main():
    host = '10.50.100.200'  # Default IP address of uninitialized camera

    cam_number = input("Please enter the cam number: ")
    run_remote_script(host, cam_number)

if __name__ == "__main__":
    main()
