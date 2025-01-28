# remote_transfer.py v9.1

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

# We support both .h264 and .jpg for each "session"
SUPPORTED_EXTENSIONS = ('.h264', '.jpg', '.mp4')

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
    """
    Return the list of session names found in RECORDINGS_FOLDER.
    A session is identified by the portion before the final underscore + extension.
    E.g. 'Test_41.h264' => session name 'Test'.
         'Test_41.jpg'  => same session name 'Test'.
    """
    if not os.path.exists(RECORDINGS_FOLDER):
        return []
    files = os.listdir(RECORDINGS_FOLDER)
    sessions = set()
    for file in files:
        # Only consider supported extensions
        if file.lower().endswith(SUPPORTED_EXTENSIONS):
            base_name, ext = os.path.splitext(file)
            # Remove the suffix after the last underscore to get the session name
            if '_' in base_name:
                session_name = '_'.join(base_name.split('_')[:-1])
            else:
                session_name = base_name
            sessions.add(session_name)
    return list(sessions)

def get_session_files(session_name):
    """
    Returns all file paths belonging to the specified session_name on this Pi,
    i.e. session_name + SUFFIX + extension for each supported extension.
    """
    found_paths = []
    if not os.path.exists(RECORDINGS_FOLDER):
        return found_paths

    # We might have multiple .h264 / .jpg for the same session_name+suffix
    # if your code only writes one .h264 and one .jpg, you’ll only find up to two files below.
    for file in os.listdir(RECORDINGS_FOLDER):
        if file.lower().endswith(SUPPORTED_EXTENSIONS):
            base_name, ext = os.path.splitext(file)
            # Example file: "SessionABC_41.h264" => base_name="SessionABC_41", ext=".h264"
            if '_' in base_name:
                prefix = '_'.join(base_name.split('_')[:-1])
                suffix = base_name.split('_')[-1]
                # Check if prefix == session_name and suffix == our SUFFIX minus leading '_'
                # but simpler is just to see if prefix == session_name and the full file ends with our SUFFIX + ext
                # We'll do the matching as below:
                if prefix == session_name and base_name.endswith(SUFFIX):
                    full_path = os.path.join(RECORDINGS_FOLDER, file)
                    found_paths.append(full_path)

    return found_paths

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
        """
        Master calls this to ask if a Pi has that session. We sum the sizes of .h264 and .jpg for it.
        If none found, we respond NOT_FOUND.
        """
        session_name = request.get('session_name')
        files = get_session_files(session_name)
        if files:
            total_size = sum(os.path.getsize(fp) for fp in files)
            response = {"status": "OK", "file_size": total_size}
        else:
            response = {"status": "NOT_FOUND"}
        sock.sendto(json.dumps(response).encode(), addr)

    elif action == "DELETE_SESSION":
        """
        Master calls this to request removing the session’s files (both .h264 and .jpg).
        """
        session_name = request.get('session_name')
        files = get_session_files(session_name)
        if not files:
            response = {"status": "ERROR", "message": "File not found"}
            sock.sendto(json.dumps(response).encode(), addr)
            print(f"No files found for session '{session_name}' from {addr}")
        else:
            success = True
            errors = []
            for fp in files:
                try:
                    os.remove(fp)
                except Exception as e:
                    success = False
                    errors.append(str(e))
            if success:
                response = {"status": "OK"}
                print(f"Deleted session '{session_name}' for {addr}")
            else:
                msg = "Failed to delete some files: " + "; ".join(errors)
                response = {"status": "ERROR", "message": msg}
                print(msg)
            sock.sendto(json.dumps(response).encode(), addr)
        
    elif action == "DELETE_ALL_SESSIONS":
        """
        Master calls this to request removing all session files (both .h264 and .jpg).
        """
        files = []
        for session in get_session_names():
            files.extend(get_session_files(session))
        if not files:
            response = {"status": "ERROR", "message": "No files found"}
            sock.sendto(json.dumps(response).encode(), addr)
            print(f"No files found to delete from {addr}")
        else:
            success = True
            errors = []
            for fp in files:
                try:
                    os.remove(fp)
                except Exception as e:
                    success = False
                    errors.append(str(e))
            if success:
                response = {"status": "OK"}
                print(f"Deleted all sessions for {addr}")
            else:
                msg = "Failed to delete some files: " + "; ".join(errors)
                response = {"status": "ERROR", "message": msg}
                print(msg)
            sock.sendto(json.dumps(response).encode(), addr)
            
    else:
        print(f"Received unknown UDP action: {action} from {addr}")

def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print("UDP server is up and listening on port", UDP_PORT)
    while True:
        data, addr = sock.recvfrom(4096)
        handle_udp_request(data, addr, sock)

def send_json_response(conn, response_dict):
    # Encode response to JSON
    msg = json.dumps(response_dict).encode()
    # Send length of this JSON message (8 bytes, unsigned long long, big-endian)
    conn.sendall(struct.pack('!Q', len(msg)))
    # Send the JSON message
    conn.sendall(msg)

def handle_tcp_client(conn, addr):
    print(f"TCP connection established with {addr}")
    # First receive the JSON request (up to 4096 bytes)
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
        print(f"Client requested download for session: {session_name}")
        files = get_session_files(session_name)
        if not files:
            # No files => respond with ERROR
            response = {"status": "ERROR", "message": "File(s) not found"}
            send_json_response(conn, response)
            conn.close()
            return
        # Summarize them so master knows how many, sizes, names
        files_info = []
        for fp in files:
            size = os.path.getsize(fp)
            filename = os.path.basename(fp)
            files_info.append({"filename": filename, "size": size})

        # Send JSON header with status=OK, array of files
        response = {"status": "OK", "files": files_info}
        send_json_response(conn, response)

        # Now send each file in sequence
        for fp in files:
            size = os.path.getsize(fp)
            with open(fp, 'rb') as f:
                while True:
                    data = f.read(4096)
                    if not data:
                        break
                    conn.sendall(data)
            print(f"Sent file '{os.path.basename(fp)}' ({size} bytes) to {addr}")

    else:
        print(f"Received unknown TCP action: {action} from {addr}")

    conn.close()

def tcp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((TCP_IP, TCP_PORT))
    sock.listen(5)
    print("TCP server is up and listening on port", TCP_PORT)
    while True:
        conn, addr = sock.accept()
        threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    threading.Thread(target=udp_server, daemon=True).start()
    tcp_server()  # Run TCP server in the main thread
