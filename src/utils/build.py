import PyInstaller.__main__
import os
import shutil
from pathlib import Path
import zipfile
import platform

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.parent.resolve()
scripts = ['master_camera_controller.py', 'master_capture_controller.py', 'master_download_manager.py']
friendly_names = {
    'master_camera_controller': 'Camera Controller',
    'master_capture_controller': 'Capture Controller',
    'master_download_manager': 'Download Manager',
}

def build_scripts_windows():
    for script in scripts:
        basename = Path(script).stem
        PyInstaller.__main__.run([
            '--noconfirm',
            '--onedir',
            '--name', basename,
            '--icon', os.path.join(PROJECT_DIR, f"src/res/{basename}.ico"),
            '--add-data', os.path.join(PROJECT_DIR, "src/config") + ";config",
            '--add-data', os.path.join(PROJECT_DIR, "src/res") + ";res",
            os.path.join(PROJECT_DIR, 'src', script),
            '--distpath', os.path.join(PROJECT_DIR, 'dist'),
            '--workpath', os.path.join(PROJECT_DIR, 'build'),
            '--specpath', os.path.join(PROJECT_DIR, 'build'),
            '--contents-directory', '_core',
            '--noconsole',
        ])

def build_scripts_mac():
    for script in scripts:
        basename = Path(script).stem
        name = friendly_names.get(basename, basename)
        icon_path = os.path.join(PROJECT_DIR, f"src/res/{basename}.icns")
        PyInstaller.__main__.run([
            '--noconfirm',
            '--onedir',
            '--name', name,
            '--icon', icon_path,
            '--add-data', os.path.join(PROJECT_DIR, "src/config") + ":config",
            '--add-data', os.path.join(PROJECT_DIR, "src/res") + ":res",
            os.path.join(PROJECT_DIR, 'src', script),
            '--distpath', os.path.join(PROJECT_DIR, 'dist'),
            '--workpath', os.path.join(PROJECT_DIR, 'build'),
            '--specpath', os.path.join(PROJECT_DIR, 'build'),
            '--windowed',
        ])

def zip_folder(folder_path, output_path):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, start=folder_path)
                zipf.write(file_path, arcname)

def copy_new_files(source_folder: str, destination_folder: str) -> None:
    for root, dirs, files in os.walk(source_folder):
        relative_path = os.path.relpath(root, source_folder)
        destination_path = os.path.join(destination_folder, relative_path)
        os.makedirs(destination_path, exist_ok=True)
        for file in files:
            src_file = os.path.join(root, file)
            dest_file = os.path.join(destination_path, file)
            if not os.path.exists(dest_file):
                shutil.copy2(src_file, dest_file)

def create_bat(dist_folder):
    bat_content = """@echo off
start "" "%~dp0_core\\config"
"""
    bat_path = os.path.join(dist_folder, "Open Config.bat")
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)

def create_command(dist_folder):
    cmd_content = """#!/bin/bash
open "$(dirname "$0")/_core/config"
"""
    cmd_path = os.path.join(dist_folder, "Open Config.command")
    with open(cmd_path, 'w', encoding='utf-8') as f:
        f.write(cmd_content)
    os.chmod(cmd_path, 0o755)

def clean_up(dist_folder, zip_name):
    print("Cleaning up...")
    if os.path.exists(dist_folder):
        shutil.rmtree(dist_folder)
    os.makedirs(dist_folder)
    system = platform.system()
    if system == 'Windows':
        create_bat(dist_folder)
    elif system == 'Darwin':
        create_command(dist_folder)
    for script in scripts:
        basename = Path(script).stem
        if system == 'Windows':
            source = os.path.join(PROJECT_DIR, 'dist', basename)
        else:  # macOS
            source = os.path.join(PROJECT_DIR, 'dist', friendly_names.get(basename, basename) + '.app')
        copy_new_files(source, dist_folder)
    zip_folder(dist_folder, os.path.join(PROJECT_DIR, 'dist', zip_name))
    shutil.rmtree(dist_folder)

def main():
    system = platform.system()
    if system == 'Windows':
        build_scripts_windows()
        zip_name = 'VolumetricCaptureSystem Controls.zip'
    elif system == 'Darwin':
        build_scripts_mac()
        arch = platform.machine()
        arch_name = 'Apple Silicon' if arch == 'arm64' else 'Intel'
        zip_name = f'VolumetricCaptureSystem Controls macOS {arch_name}.zip'
    else:
        print(f"Unsupported platform: {system}")
        return
    dist_folder = os.path.join(PROJECT_DIR, 'dist', 'VolumetricCaptureSystem Controls')
    clean_up(dist_folder, zip_name)

if __name__ == "__main__":
    main()
