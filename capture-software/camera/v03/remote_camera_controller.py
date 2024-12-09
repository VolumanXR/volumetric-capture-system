# remote_camera_controller.py

import os
import json
import logging
import asyncio
import websockets
from flask import Flask, Response, request, jsonify
from picamera2 import Picamera2
import cv2
import time
from aiortc import RTCPeerConnection, VideoStreamTrack, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder
from aiortc.contrib.signaling import BYPASS_SIGNALLING
from aiortc.contrib.signaling import object_to_string, string_to_object

# Configure Logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize Picamera2
try:
    picam2 = Picamera2()
except Exception as e:
    logger.error(f"Failed to initialize Picamera2: {e}")
    exit(1)

# Default settings
default_settings = {
    'width': 1280,
    'height': 720,
    'frame_rate': 25,
    'shutter_angle': 180,
    'iso': 100,
    'brightness': 0,
    'contrast': 100,
    'saturation': 100,
    'sharpness': 100,
    'auto_exposure': True,
    'flicker_control': 'Off',
    'flicker_period': 50,
    'white_balance': 'Auto',
    'red_gain': 1.0,
    'blue_gain': 1.0
}

# Load settings from camera_settings.json if it exists
if os.path.exists('camera_settings.json'):
    try:
        with open('camera_settings.json', 'r') as f:
            saved_settings = json.load(f)
            default_settings.update(saved_settings)
            logger.debug("Loaded settings from camera_settings.json")
    except Exception as e:
        logger.error(f"Failed to load camera_settings.json: {e}")

def apply_settings(settings):
    controls = {}
    frame_rate = float(settings.get('frame_rate', 25))
    controls["FrameRate"] = frame_rate

    shutter_angle = float(settings.get('shutter_angle', 180))
    base_exposure_time = (shutter_angle / 360.0) * (1.0 / frame_rate) * 1_000_000  # in microseconds

    iso_value = float(settings.get('iso', 100))

    controls["Brightness"] = float(settings.get('brightness', 0)) / 100.0
    controls["Contrast"] = float(settings.get('contrast', 100)) / 100.0
    controls["Saturation"] = float(settings.get('saturation', 100)) / 100.0
    controls["Sharpness"] = float(settings.get('sharpness', 100)) / 100.0

    # Handle Flicker Control
    flicker_selection = settings.get('flicker_control', 'Off')
    if flicker_selection == 'Off':
        # Use Auto Exposure setting
        controls["AeEnable"] = settings.get('auto_exposure', True)
        if not settings.get('auto_exposure', True):
            controls["ExposureTime"] = int(base_exposure_time)
            controls["AnalogueGain"] = iso_value / 100.0
    else:
        # Disable Auto Exposure for flicker control
        controls["AeEnable"] = False
        if flicker_selection == '50Hz':
            # Set exposure time to multiple of 20ms (50Hz period)
            exposure_time = int(20_000)  # 20ms in microseconds
        elif flicker_selection == '60Hz':
            # Set exposure time to multiple of 16.67ms (60Hz period)
            exposure_time = int(16_667)  # Approximate 16.67ms
        elif flicker_selection == 'Manual':
            # Use the flicker period from the settings
            flicker_period = float(settings.get('flicker_period', 50))  # in Hz
            exposure_time = int((1.0 / flicker_period) * 1_000_000)  # Convert Hz to microseconds
        else:
            # Default exposure time
            exposure_time = int(base_exposure_time)

        controls["ExposureTime"] = exposure_time
        controls["AnalogueGain"] = iso_value / 100.0

    # Handle White Balance
    wb_selection = settings.get('white_balance', 'Auto')
    if wb_selection == 'Auto':
        controls["AwbEnable"] = True
    else:
        controls["AwbEnable"] = False
        if wb_selection == 'Manual':
            red_gain = float(settings.get('red_gain', 1.0))
            blue_gain = float(settings.get('blue_gain', 1.0))
            controls["ColourGains"] = (red_gain, blue_gain)
        else:
            # Set 'ColourGains' based on selected white balance
            if wb_selection == '3200K':
                controls["ColourGains"] = (2.3, 1.3)
            elif wb_selection == '4400K':
                controls["ColourGains"] = (1.8, 1.5)
            elif wb_selection == '5600K':
                controls["ColourGains"] = (1.5, 1.8)

    try:
        picam2.set_controls(controls)
        logger.debug(f"Applied settings: {controls}")
    except Exception as e:
        logger.error(f"Failed to apply settings: {e}")

def configure_camera():
    try:
        width = default_settings['width']
        height = default_settings['height']
        config = picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (width, height)},
            controls={
                "FrameRate": float(default_settings['frame_rate']),
                "Brightness": float(default_settings['brightness']) / 100.0,
                "Contrast": float(default_settings['contrast']) / 100.0,
                "Saturation": float(default_settings['saturation']) / 100.0,
                "Sharpness": float(default_settings['sharpness']) / 100.0,
                "AwbEnable": default_settings['white_balance'] == 'Auto',
                "AeEnable": False if default_settings['flicker_control'] != 'Off' else default_settings['auto_exposure'],
            }
        )
        picam2.configure(config)
        picam2.start()
        apply_settings(default_settings)
        logger.debug("Camera configured and started.")
    except Exception as e:
        logger.error(f"Failed to configure and start camera: {e}")
        exit(1)

configure_camera()
logger.info("Camera successfully configured and started.")

@app.route('/controls', methods=['POST'])
def update_controls_route():
    try:
        settings = request.json
        if not settings:
            logger.warning("No settings provided in /controls POST request.")
            return jsonify({"error": "No settings provided"}), 400

        # Update default_settings with new settings
        default_settings.update(settings)
        logger.debug(f"Received settings update: {settings}")

        # Apply settings to the camera
        apply_settings(default_settings)

        return jsonify({"status": "Settings updated successfully"}), 200
    except Exception as e:
        logger.error(f"Error in /controls endpoint: {e}")
        return jsonify({"error": str(e)}), 500

def generate_video_stream():
    while True:
        try:
            frame = picam2.capture_array()
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                logger.warning("Failed to encode frame.")
                continue
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(1 / default_settings['frame_rate'])
        except Exception as e:
            logger.error(f"Error generating video stream: {e}")
            break

@app.route('/video_feed')
def video_feed():
    return Response(generate_video_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/save_settings', methods=['POST'])
def save_settings_route():
    try:
        settings = request.json
        if not settings:
            logger.warning("No settings provided in /save_settings POST request.")
            return jsonify({"error": "No settings provided"}), 400

        with open('camera_settings.json', 'w') as f:
            json.dump(settings, f)
        logger.debug("Settings saved to camera_settings.json")
        return jsonify({"status": "Settings saved successfully"}), 200
    except Exception as e:
        logger.error(f"Error in /save_settings endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/load_settings', methods=['GET'])
def load_settings_route():
    try:
        if os.path.exists('camera_settings.json'):
            with open('camera_settings.json', 'r') as f:
                saved_settings = json.load(f)
            logger.debug("Loaded settings from camera_settings.json")
            return jsonify(saved_settings), 200
        else:
            logger.debug("camera_settings.json not found. Returning default settings.")
            return jsonify(default_settings), 200
    except Exception as e:
        logger.error(f"Error in /load_settings endpoint: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------------------
# WebRTC Signaling via WebSockets
# -------------------------------

connected_peers = set()

class VideoStreamTrackCustom(VideoStreamTrack):
    """
    A custom video stream track that reads from Picamera2 and sends frames via WebRTC.
    """
    kind = "video"

    def __init__(self):
        super().__init__()  # don't forget this!
        self.running = True

    async def recv(self):
        while self.running:
            frame = picam2.capture_array()
            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            # Decode JPEG to get RGB frame
            frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            # Convert to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Convert to PIL Image
            img = Image.fromarray(frame)
            # Yield the frame
            return img

async def signaling(websocket, path):
    peer_connection = RTCPeerConnection()
    connected_peers.add(peer_connection)
    logger.info("New WebRTC peer connected.")

    @peer_connection.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        logger.info(f"ICE connection state: {peer_connection.iceConnectionState}")
        if peer_connection.iceConnectionState == "failed":
            await peer_connection.close()
            connected_peers.remove(peer_connection)

    # Receive offer from client
    offer = await websocket.recv()
    offer = RTCSessionDescription(sdp=offer['sdp'], type=offer['type'])
    await peer_connection.setRemoteDescription(offer)

    # Add media (video) to peer connection
    video_track = VideoStreamTrackCustom()
    peer_connection.addTrack(video_track)

    # Create answer
    answer = await peer_connection.createAnswer()
    await peer_connection.setLocalDescription(answer)

    # Send answer back to client
    await websocket.send(json.dumps({
        'sdp': peer_connection.localDescription.sdp,
        'type': peer_connection.localDescription.type
    }))

    try:
        async for message in websocket:
            data = json.loads(message)
            if data['type'] == 'icecandidate':
                candidate = data['candidate']
                await peer_connection.addIceCandidate(candidate)
    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket connection closed.")
    finally:
        await peer_connection.close()
        connected_peers.remove(peer_connection)

@app.route('/webrtc')
def webrtc():
    # Placeholder route for WebRTC; actual WebRTC handled via WebSockets
    return "WebRTC signaling server running."

async def main():
    async with websockets.serve(signaling, "0.0.0.0", 8765):
        logger.info("WebRTC signaling server started on ws://0.0.0.0:8765")
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    # Start Flask server and WebRTC signaling server concurrently
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(main())
    try:
        logger.info("Starting Flask server...")
        app.run(host='0.0.0.0', port=5000, threaded=True, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Failed to start Flask server: {e}")
        picam2.stop()
        logger.info("Shutting down camera due to Flask server failure.")
