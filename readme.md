**EN** | [DE](README.de.md)

<p align="center">
  <img src="docs/assets/Logo_VCS.png" alt="Volumetric Capture System Logo" width="400"/>
</p>

# VolumanXR – Volumetric Capture System

This module is part of the **VolumanXR** project and implements a complete **synchronized volumetric video capture system** using Raspberry Pis and the Raspberry Pi Camera Module V3. The system enables real-time, multi-camera video acquisition for 4D Gaussian Splatting.

It includes:
- A scalable and customizable camera rig
- A decentralized control system with synchronized recording
- GUI tools for capture, calibration, and download
- Automation scripts and config management

---

## 📦 Repository Structure
```text
volumetric-capture-system/
├── readme.md
├── requirements.txt
├── cad/                           # 3D-printable camera holder models
├── dist/                          # Zipped and packaged master controls
├── img/                           # Link to external archive containing preformatted Raspberry Pi Images
├── src/
│   ├── master_camera_controller.py
│   ├── master_capture_controller.py
│   ├── master_download_manager.py
│   ├── config/                    # Device settings and camera parameters
│   ├── lib/                       # Shared configuration and SSH utilities
│   ├── remote/                    # Scripts executed on Raspberry Pis
│   ├── res/                       # Icons and sound files used by GUI tools
│   └── utils/                     # Utility scripts for setup and control
```

---

## 🔧 Hardware Context

- **Camera Rig**: Custom-built frame using aluminum extrusion profiles (not included in repo).
- **Cameras**: Raspberry Pi 4B (1GB) + Camera Module V3
- **Devices**: approx. 70 Raspberry Pi units
- **Mounts**: 3D-printable camera holders (provided in `cad/`)
- **Trigger**: Software-synchronized using NTP + ZeroMQ

> *The structural skeleton is specific to our use case and therefore excluded to encourage custom modifications. It is based on standard 20×20mm aluminum extrusions, and the included 3D-printable camera holders are fully compatible with this profile size. A full parts list for the frame construction can be provided upon request.*

---

## 🚀 Core Functionality

### 🎚️ Master Camera Controller (`master_camera_controller.py`)
- GUI tool for live preview and global camera calibration
- Modify ISO, shutter speed, white balance, resolution
- Save unified settings to `camera_settings.json`

### 📸 Master Capture Controller (`master_capture_controller.py`)
- GUI-based tool to control still or video capture
- Synchronizes all agents to a single start time
- Frame drop detection and timestamp logging
- Uses `camera_list.json` to identify and manage all configured camera devices on the network

### 🔄 Master Download Manager (`master_download_manager.py`)
- GUI tool to download sessions from all Pis
- Organizes files, checks completeness, enables conversion
- Supports offline mode for post-capture frame extraction

---

## 🧠 Remote Agents (Running on Raspberry Pis)

Remote-side scripts are located in `src/remote/` and are triggered via SSH by the master control GUIs. Each script is responsible for a core function during capture, calibration, or data transfer.

### Main Remote Modules

- `remote_camera_controller.py`  
  Handles calibration commands from the Master Camera Controller (`master_camera_controller.py`), such as adjusting focus or setting exposure.

- `remote_capture_controller.py`  
  Receives synchronized recording instructions from the Master Capture Controller (`master_capture_controller.py`), executes the capture locally, and logs metadata.

- `remote_download_manager.py`  
  Runs a simple file server on each Pi to make captured sessions available for download, coordinated by the Master Download Manager (`master_download_manager.py`).

### Remote Utilities (`src/remote/utils/`)

- `remote_set_cam_number.py` — Sets a unique hostname, ID (e.g. `CAM00`) and fixed IP  
- `remote_test_camera_settings.py` — Applies a series of camera configurations and captures test images for validation

---

## 🧰 General Utilities

Located in `src/utils/`, these tools support discovery, setup, and remote control:

- `launcher.py`  
  CLI for development, debugging, and deployment. Supports multithreaded SSH to start/stop/update remote scripts on all Pis.

- `search_devices.py`  
  Scans the local subnet using multithreaded pings to identify active devices. Attempts to resolve hostnames for each responsive IP.

- `set_up_chrony_via_ssh.py`  
  Configures time synchronization on all Pis using Chrony for frame-accurate triggering.

- `master_set_cam_number.py`  
  Assigns camera numbers and hostnames from the master side during setup.

- `build.py`
  Preconfigured build script for all three main programs

---

## ⚙️ Configuration Files

- `camera_list.json` — List of camera hostnames, IPs, and their custom focus offsets
- `camera_settings.json` — Default global exposure settings (shutter, ISO, etc.)

Each Pi is matched via hostname (e.g. `CAM00`, `CAM01`, ...) and receives a fixed IP address in the `10.x.x.x` range.  
The **last octet of the IP corresponds to the camera number**, starting at `.100` — for example:
- `CAM00` → `10.x.x.100`
- `CAM01` → `10.x.x.101`

---
## 🗂 File Naming Convention

Captured videos and still images follow the pattern:
```
<session_name>_<ip_suffix>.<extension>
```

Examples:
- `DanceA_103.mp4` — video from device with IP `10.x.x.103`
- `PoseTest_115.jpg` — still image from device with IP `10.x.x.115`

This format ensures files can easily be traced to their originating capture device.

---

## 🎛 Dependencies

Install dependencies for local tools:

```bash
pip install -r requirements.txt
```
Recommended environment:
- Python 3.10+
- Works on Windows/macOS (for GUI tools) and Raspberry Pi OS (for remote agents)

---

## 👥 Team Contributors

- **Kai Altwicker** — Rig design, synchronization, master control architecture  
- **Dennis Luca Amuser** — Remote agent design, firmware imaging, network & automation  
- **Support** — Makerspace TH Köln, Zentralwerkstatt Elektrotechnik, Prof. Dr.-Ing. Fuhrmann

---

## 📄 License

This repository is part of the VolumanXR project.  
Please refer to the root repository’s `LICENSE` file for full terms.

---

> ℹ️ For full project context, visit the [VolumanXR README](../README.md).





