import socket
import threading
import os

# Configuration
UDP_IP = "0.0.0.0"  # Listen on all interfaces
UDP_PORT = 50005
TCP_IP = "0.0.0.0"  # Listen on all interfaces
TCP_PORT = 50006
RECORDINGS_FOLDER = "Recordings"  # Update this path

def get_suffix():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Use a dummy address to get the outgoing IP
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    suffix = '_' + IP.split('.')[-1]
    return suffix

SUFFIX = get_suffix()
print(f"Raspberry Pi suffix: {SUFFIX}")

def get_session_names():
    files = os.listdir(RECORDINGS_FOLDER)
    sessions = set()
    for file in files:
        if file.endswith('.h264'):
            base_name = os.path.splitext(file)[0]
            # Remove the suffix after the last underscore
            if '_' in base_name:
                session_name = '_'.join(base_name.split('_')[:-1])
            else:
                session_name = base_name
            sessions.add(session_name)
    return list(sessions)

def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print("UDP server is up and listening...")
    while True:
        data, addr = sock.recvfrom(1024)
        message = data.decode()
        if message == "GET_SESSIONS":
            sessions = get_session_names()
            response = ','.join(sessions)
            sock.sendto(response.encode(), addr)
            print(f"Sent session list to {addr}")
        else:
            print(f"Received unknown message: {message} from {addr}")

def handle_tcp_client(conn, addr):
    print(f"TCP connection established with {addr}")
    session_name = conn.recv(1024).decode()
    print(f"Client requested session: {session_name}")
    # Construct the filename with suffix
    file_to_send = f"{session_name}{SUFFIX}.h264"
    file_path = os.path.join(RECORDINGS_FOLDER, file_to_send)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                conn.sendall(f.read())
            print(f"File {file_to_send} sent to {addr}")
        except Exception as e:
            print(f"Error sending file: {e}")
    else:
        conn.sendall(b"ERROR: File not found")
        print(f"File for session {session_name} not found")
    conn.close()

def tcp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((TCP_IP, TCP_PORT))
    sock.listen(5)
    print("TCP server is up and listening...")
    while True:
        conn, addr = sock.accept()
        threading.Thread(target=handle_tcp_client, args=(conn, addr)).start()

if __name__ == "__main__":
    threading.Thread(target=udp_server).start()
    threading.Thread(target=tcp_server).start()
