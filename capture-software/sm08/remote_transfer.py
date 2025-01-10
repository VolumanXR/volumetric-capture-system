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
RECORDINGS_FOLDER = "Recordings"  # Update this path as needed

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

def get_session_files(session_name):
    """
    Return a list of full paths to all files belonging to 'session_name'
    within RECORDINGS_FOLDER. A 'session_name' might have:
      session_name_<suffix>.h264
      session_name_<suffix>.jpg
      etc.
    """
    if not os.path.exists(RECORDINGS_FOLDER):
        return []
    
    all_files = []
    for file in os.listdir(RECORDINGS_FOLDER):
        if file.startswith(session_name + "_"):  # must start with session_name_
            # So we consider .h264 or .jpg or possibly other.
            full_path = os.path.join(RECORDINGS_FOLDER, file)
            if os.path.isfile(full_path):
                all_files.append(full_path)
    return all_files

def get_session_names():
    """
    Return a list of "session_name" found by removing the suffix
    from any *.h264 or *.jpg in the folder.
    """
    if not os.path.exists(RECORDINGS_FOLDER):
        return []
    files = os.listdir(RECORDINGS_FOLDER)
    sessions = set()
    for file in files:
        if file.endswith('.h264') or file.endswith('.jpg'):  # (CHANGED) also support jpg
            base_name = os.path.splitext(file)[0]
            # base_name might be something like: "MySession_41"
            # Remove the suffix after the last underscore
            if '_' in base_name:
                session_name = '_'.join(base_name.split('_')[:-1])
            else:
                session_name = base_name
            sessions.add(session_name)
    return list(sessions)

def handle_udp_request(data, addr, sock):
    """
    Handle incoming UDP requests (GET_SESSIONS, GET_SESSION_INFO, DELETE_SESSION).
    """
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
        # Master wants info about a single 'session_name':
        # We now return all files for that session (both .h264 and .jpg).
        session_name = request.get('session_name')
        files_for_session = get_session_files(session_name)
        if not files_for_session:
            response = {"status": "NOT_FOUND", "files": []}
        else:
            # Return each file's size
            file_info = []
            for path in files_for_session:
                file_info.append({
                    "filename": os.path.basename(path),
                    "size": os.path.getsize(path)
                })
            response = {"status": "OK", "files": file_info}
        sock.sendto(json.dumps(response).encode(), addr)

    elif action == "DELETE_SESSION":
        # Delete all files that belong to this session
        session_name = request.get('session_name')
        files_for_session = get_session_files(session_name)
        if not files_for_session:
            response = {"status": "ERROR", "message": "File not found"}
            print(f"File for session '{session_name}' not found for {addr}")
        else:
            success = True
            msg = ""
            for path in files_for_session:
                try:
                    os.remove(path)
                except Exception as e:
                    success = False
                    msg = f"Failed to delete file {path}: {str(e)}"
                    print(msg)
                    break
            if success:
                response = {"status": "OK"}
                print(f"Deleted session '{session_name}' for {addr}")
            else:
                response = {"status": "ERROR", "message": msg}
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
    # First receive the JSON request
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
        """
        Master can request a single file from a session.
          request = {
             "action": "DOWNLOAD_SESSION",
             "session_name": <str>,
             "filename": <str>   <-- which .h264 or .jpg do we want?
          }
        """
        session_name = request.get('session_name')
        filename = request.get('filename')  # e.g. MySession_41.h264 or MySession_41.jpg
        print(f"Client requested session '{session_name}' file '{filename}'")

        file_path = os.path.join(RECORDINGS_FOLDER, filename)
        if not os.path.exists(file_path):
            response = {"status": "ERROR", "message": "File not found"}
            send_json_response(conn, response)
            print(f"File {filename} not found for {addr}")
        else:
            try:
                file_size = os.path.getsize(file_path)
                response = {"status": "OK", "file_size": file_size}
                send_json_response(conn, response)

                # Now send the file data
                with open(file_path, 'rb') as f:
                    while True:
                        data = f.read(4096)
                        if not data:
                            break
                        conn.sendall(data)
                print(f"File {os.path.basename(file_path)} sent to {addr}")
            except Exception as e:
                print(f"Error sending file {filename}: {e}")
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
    tcp_server()  # Run TCP server in main thread
