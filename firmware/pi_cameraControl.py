import socket
import time
import os
import subprocess
import signal
import hashlib

# UDP broadcast and unicast setup
UDP_PORT = 5005
BROADCAST_IP = '255.255.255.255'
UDP_IP = "0.0.0.0"  # Listen on all interfaces
HOST_IP = "192.168.179.9"  # Replace with actual host IP address for unicast messages
HOST_PORT = 51628

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Enable broadcast

# Set up socket for receiving broadcast and unicast
sock.bind((UDP_IP, UDP_PORT))

# States
STANDBY = "STANDBY"
RECORDING = "RECORDING"
READY_FOR_TRANSMIT = "READY_FOR_TRANSMIT"

# Global variables
state = STANDBY
video_filename = None
last_message_time = 0  # Track when the last message was sent
# TODO: Make message interval a random interval between 3 and 5 seconds to lighten potential network congestion
message_interval = 5   # Time interval between messages in seconds 
recording_process = None  # To track the recording process

# TODO: Optimize camera settings
# Resolution and framerate settings
resolution = (1920, 1080)  # Full HD resolution
framerate = 30  # 30 frames per second
video_duration = 0  # We'll manually handle recording stop via a command

# Function to send UDP state messages via unicast to the host
def send_udp_message(message):
    sock.sendto(message.encode(), (HOST_IP, HOST_PORT))  # Unicast to host

# Non-blocking function to send periodic UDP messages
def send_periodic_message(current_time, message):
    global last_message_time
    if current_time - last_message_time >= message_interval:
        send_udp_message(message)
        last_message_time = current_time

# Function to calculate checksum (MD5) of a file
def calculate_checksum(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except FileNotFoundError:
        return None

# Function to handle video recording with libcamera-vid
def start_recording():
    global recording_process, video_filename
    video_filename = "/home/pi/video.mp4"  # Path to save video as .mp4
    width, height = resolution

    # Command to start recording using libcamera-vid
    command = [
        'libcamera-vid',
        '--width', str(width),
        '--height', str(height),
        '--framerate', str(framerate),
        '--output', video_filename
    ]
    
    # Start the recording process using subprocess
    recording_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) # Popen opens subprocess in the background and allows python script to continue
    print("Recording started")

# Gracefully stop the recording by sending SIGINT (Ctrl+C equivalent)
def stop_recording():
    global recording_process
    if recording_process:
        recording_process.send_signal(signal.SIGINT)  # Send SIGINT to terminate gracefully
        recording_process.wait()  # Wait for the process to finalize
        recording_process = None
        print("Recording stopped and finalized")

# Function to transmit video using SCP
def transmit_file_via_scp(file_path, host_ip, remote_path):
    try:
        # scp command: scp <file_path> user@host_ip:<remote_path>
        scp_command = ["scp", file_path, f"pi@{host_ip}:{remote_path}"]
        subprocess.run(scp_command, check=True)
        print(f"File {file_path} transmitted successfully to {host_ip}")
        send_udp_message("TRANSMISSION FINISHED")
    except subprocess.CalledProcessError as e:
        print(f"Error during SCP: {e}")
        send_udp_message("TRANSMIT FAILED")

# Function to get remote checksum via SSH after SCP transfer
def get_remote_checksum(host_ip, remote_file_path):
    try:
        # SSH command to calculate checksum on the remote host
        ssh_command = f"ssh pi@{host_ip} 'md5sum {remote_file_path}'"
        result = subprocess.run(ssh_command, shell=True, capture_output=True, text=True, check=True)
        return result.stdout.split()[0]  # Return the checksum
    except subprocess.CalledProcessError as e:
        print(f"Error during remote checksum calculation: {e}")
        return None

# Transmit file and verify checksum
def transmit_video(file_path, remote_path):
    checksum_local = calculate_checksum(file_path)
    if not checksum_local:
        send_udp_message("TRANSMIT FAILED: File not found")
        return

    # Transmit the video via SCP
    transmit_file_via_scp(file_path, HOST_IP, remote_path)

    # Get remote checksum and compare with local checksum
    remote_checksum = get_remote_checksum(HOST_IP, remote_path)
    if remote_checksum and checksum_local == remote_checksum:
        send_udp_message("CHECKSUM MATCH: Transmission verified")
        print("Checksum verified. File transferred successfully.")
    else:
        send_udp_message("CHECKSUM MISMATCH: Transmission failed")
        print(f"Checksum mismatch! Local: {checksum_local}, Remote: {remote_checksum}")

# Handle the DISCARD command: Delete video file and reset to STANDBY state
def discard_video():
    global video_filename, state
    if video_filename and os.path.exists(video_filename):
        os.remove(video_filename)  # Delete the video file
        print(f"Video {video_filename} discarded.")
    state = STANDBY

# Function to handle UDP unicast commands for DISCARD and TRANSMIT
def handle_unicast_commands():
    global state
    try:
        data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
        command = data.decode().strip()
        print(f"Received unicast command: {command}")

        # Handle DISCARD and TRANSMIT commands
        if command == "DISCARD" and state == READY_FOR_TRANSMIT:
            discard_video()
        elif command == "TRANSMIT" and state == READY_FOR_TRANSMIT:
            transmit_video(video_filename, "/remote/path/to/save/video.mp4")
            discard_video()  # Optionally delete the video after transmission
    except socket.timeout:
        pass

# Function to handle UDP broadcast commands (REC START, REC STOP)
def handle_broadcast_commands():
    global state
    try:
        data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
        command = data.decode().strip()
        print(f"Received broadcast command: {command}")

        # Handle broadcasted commands (REC START, REC STOP)
        if command == "REC START" and state == STANDBY:
            start_recording()
            state = RECORDING
        elif command == "REC STOP" and state == RECORDING:
            stop_recording()
            state = READY_FOR_TRANSMIT
    except socket.timeout:
        pass

# Main loop (non-blocking)
if __name__ == "__main__":
    print("Starting Raspberry Pi UDP listener...")

    while True:
        current_time = time.time()

        # Handle UDP broadcast commands (REC START, REC STOP)
        handle_broadcast_commands()

        # Handle UDP unicast commands (DISCARD, TRANSMIT)
        handle_unicast_commands()

        # Periodic messages based on the current state
        if state == STANDBY:
            send_periodic_message(current_time, "STANDBY")
        elif state == RECORDING:
            send_periodic_message(current_time, "RECORDING")
        elif state == READY_FOR_TRANSMIT:
            send_periodic_message(current_time, "READY FOR TRANSMIT")

        # Do not use sleep to ensure non-blocking behavior
