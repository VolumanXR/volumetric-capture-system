#!/usr/bin/env python3
# remote_transfer.py v12

import socket
import threading
import os
import json
import struct
import zmq

# Configuration
UDP_IP = "0.0.0.0"       # Listen on all interfaces for UDP
UDP_PORT = 50005
TCP_PORT = 50006         # ZeroMQ server will bind here (replacing the old TCP server)
RECORDINGS_FOLDER = "Recordings"  # Update this path as needed

# Supported file extensions for a session.
SUPPORTED_EXTENSIONS = ('.h264', '.jpg', '.mp4', '.json')

def get_suffix():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Use a dummy address to get the outgoing IP.
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
    For example:
      'Test_41.h264'  => session name 'Test'
      'Test_41.jpg'   => session name 'Test'
    """
    if not os.path.exists(RECORDINGS_FOLDER):
        return []
    files = os.listdir(RECORDINGS_FOLDER)
    sessions = set()
    for file in files:
        if file.lower().endswith(SUPPORTED_EXTENSIONS):
            base_name, ext = os.path.splitext(file)
            if '_' in base_name:
                session_name = '_'.join(base_name.split('_')[:-1])
            else:
                session_name = base_name
            sessions.add(session_name)
    return list(sessions)

def get_session_files(session_name):
    """
    Returns all file paths belonging to the specified session_name on this Pi.
    Files are identified as those whose filename equals session_name + SUFFIX + extension.
    """
    found_paths = []
    if not os.path.exists(RECORDINGS_FOLDER):
        return found_paths

    for file in os.listdir(RECORDINGS_FOLDER):
        if file.lower().endswith(SUPPORTED_EXTENSIONS):
            base_name, ext = os.path.splitext(file)
            if '_' in base_name:
                prefix = '_'.join(base_name.split('_')[:-1])
                # Check if the prefix matches the session name and that the file ends with our SUFFIX.
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
        # Master asks if this Pi has the session.
        session_name = request.get('session_name')
        files = get_session_files(session_name)
        if files:
            total_size = sum(os.path.getsize(fp) for fp in files)
            response = {"status": "OK", "file_size": total_size}
        else:
            response = {"status": "NOT_FOUND"}
        sock.sendto(json.dumps(response).encode(), addr)

    elif action == "DELETE_SESSION":
        # Master requests deletion of this session's files.
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
        # Master requests deletion of all sessions.
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

def zmq_download_session_server():
    """
    ZeroMQ REP server to handle DOWNLOAD_SESSION requests.
    When a request is received, it replies with a multipart message:
      - Frame 0: a JSON header containing a "status" and a list of file info.
      - Frames 1..n: the complete binary data of each file (in order).
    """
    context = zmq.Context.instance()
    socket_zmq = context.socket(zmq.REP)
    socket_zmq.bind(f"tcp://*:{TCP_PORT}")
    print("ZeroMQ server is up and listening on port", TCP_PORT)
    
    while True:
        try:
            # Wait for the JSON request from the master.
            req = socket_zmq.recv_json()
            action = req.get("action")
            if action == "DOWNLOAD_SESSION":
                session_name = req.get("session_name")
                print(f"Received download request for session: {session_name}")
                files = get_session_files(session_name)
                if not files:
                    header = {"status": "ERROR", "error": f"Session '{session_name}' not found"}
                    socket_zmq.send_json(header)
                    continue
                
                files_info = []
                file_frames = []
                for fp in files:
                    size = os.path.getsize(fp)
                    filename = os.path.basename(fp)
                    files_info.append({"filename": filename, "size": size})
                    with open(fp, "rb") as f:
                        data = f.read()
                    file_frames.append(data)
                
                header = {"status": "OK", "files": files_info}
                # Send the multipart message: first frame is the JSON header, then one frame per file.
                frames = [json.dumps(header).encode()] + file_frames
                socket_zmq.send_multipart(frames)
                print(f"Sent {len(files)} file(s) for session '{session_name}'")
            else:
                header = {"status": "ERROR", "error": "Invalid action"}
                socket_zmq.send_json(header)
        except Exception as e:
            error_header = {"status": "ERROR", "error": str(e)}
            try:
                socket_zmq.send_json(error_header)
            except Exception:
                pass

if __name__ == "__main__":
    # Start the UDP server (for GET_SESSIONS, GET_SESSION_INFO, deletion commands) in a separate thread.
    threading.Thread(target=udp_server, daemon=True).start()
    # Start the ZeroMQ REP server (for DOWNLOAD_SESSION) in the main thread.
    zmq_download_session_server()
