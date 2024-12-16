import socket
import threading
import os
import json
import struct

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

def get_session_file_path(session_name):
    file_to_send = f"{session_name}{SUFFIX}.h264"
    file_path = os.path.join(RECORDINGS_FOLDER, file_to_send)
    if os.path.exists(file_path):
        return file_path
    else:
        return None

def handle_udp_request(data, addr, sock):
    try:
        request = json.loads(data.decode())
    except json.JSONDecodeError:
        return

    action = request.get('action')
    if action == "GET_SESSIONS":
        sessions = get_session_names()
        response = {"sessions": sessions}
        sock.sendto(json.dumps(response).encode(), addr)
        print(f"Sent session list to {addr}")
    elif action == "GET_SESSION_INFO":
        session_name = request.get('session_name')
        file_path = get_session_file_path(session_name)
        if file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            response = {"status": "OK", "file_size": file_size}
        else:
            response = {"status": "NOT_FOUND"}
        sock.sendto(json.dumps(response).encode(), addr)
    else:
        print(f"Received unknown UDP action: {action} from {addr}")

def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print("UDP server is up and listening...")
    while True:
        data, addr = sock.recvfrom(4096)
        handle_udp_request(data, addr, sock)

def send_json_response(conn, response_dict):
    # Encode response to JSON
    msg = json.dumps(response_dict).encode()
    # Send length of this JSON message (8 bytes, unsigned long long)
    conn.sendall(struct.pack('!Q', len(msg)))
    # Send the JSON message
    conn.sendall(msg)

def handle_tcp_client(conn, addr):
    print(f"TCP connection established with {addr}")
    request_data = conn.recv(4096)
    if not request_data:
        conn.close()
        return
    try:
        request = json.loads(request_data.decode())
    except json.JSONDecodeError:
        conn.close()
        return

    action = request.get('action')
    if action == "DOWNLOAD_SESSION":
        session_name = request.get('session_name')
        print(f"Client requested session: {session_name}")
        file_path = get_session_file_path(session_name)
        if file_path and os.path.exists(file_path):
            try:
                file_size = os.path.getsize(file_path)
                response = {"status": "OK", "file_size": file_size}
                send_json_response(conn, response)

                # Send the file data
                with open(file_path, 'rb') as f:
                    while True:
                        data = f.read(4096)
                        if not data:
                            break
                        conn.sendall(data)
                print(f"File {os.path.basename(file_path)} sent to {addr}")
            except Exception as e:
                print(f"Error sending file: {e}")
        else:
            response = {"status": "ERROR", "message": "File not found"}
            send_json_response(conn, response)
            print(f"File for session {session_name} not found")
    else:
        print(f"Received unknown TCP action: {action} from {addr}")

    conn.close()

def tcp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((TCP_IP, TCP_PORT))
    sock.listen(5)
    print("TCP server is up and listening...")
    while True:
        conn, addr = sock.accept()
        threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=udp_server, daemon=True).start()
    tcp_server()
