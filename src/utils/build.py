import PyInstaller.__main__
import os
import shutil
import sys
import platform
from pathlib import Path
import zipfile

SCRIPT_DIR  = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.parent.resolve()

# Mapping von Skript-Datei → gewünschter App-Name
script_map = {
    'master_camera_controller.py':  'Camera Controller',
    'master_capture_controller.py': 'Capture Controller',
    'master_download_manager.py':   'Download Manager',
}

def build_scripts():
    is_mac = sys.platform == 'darwin'
    for script_file, friendly_name in script_map.items():
        stem = Path(script_file).stem
        icon_ext     = '.icns' if is_mac else '.ico'
        sep          = ':'    if is_mac else ';'
        console_flag = '--windowed' if is_mac else '--noconsole'

        icon_path = PROJECT_DIR / 'src' / 'res' / f"{stem}{icon_ext}"
        config_src = PROJECT_DIR / 'src' / 'config'
        res_src    = PROJECT_DIR / 'src' / 'res'
        src_script = PROJECT_DIR / 'src' / script_file

        PyInstaller.__main__.run([
            '--noconfirm',
            '--onedir',
            '--name', friendly_name,
            console_flag,
            '--icon', str(icon_path),
            '--add-data', f"{config_src}{sep}config",
            '--add-data', f"{res_src}{sep}res",
            str(src_script),
            '--distpath', str(PROJECT_DIR / 'dist'),
            '--workpath', str(PROJECT_DIR / 'build'),
            '--specpath', str(PROJECT_DIR / 'build'),
            '--contents-directory', '_core',
        ])

def clean_up():
    is_mac = sys.platform == 'darwin'
    dist_dir = PROJECT_DIR / 'dist'
    bundle_dir = dist_dir / 'VolumetricCaptureSystem Controls'

    # Zielordner neu anlegen
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    # Hilfs-Skript
    if is_mac:
        create_command(bundle_dir)
    else:
        create_bat(bundle_dir)

    # .app-Bundles bzw. Windows-Ordner kopieren
    for _, friendly_name in script_map.items():
        if is_mac:
            src_app  = dist_dir / f"{friendly_name}.app"
            dst_app  = bundle_dir / f"{friendly_name}.app"
            if src_app.exists():
                shutil.copytree(src_app, dst_app)
        else:
            src_dir = dist_dir / friendly_name
            if src_dir.exists():
                copy_new_files(str(src_dir), str(bundle_dir))

    # ZIP-Name unter macOS mit Architektur-Suffix
    if is_mac:
        arch = platform.machine()
        platform_suffix = 'macOS Apple Silicon' if arch == 'arm64' else 'macOS Intel'
        zip_name = f"VolumetricCaptureSystem Controls - {platform_suffix}.zip"
    else:
        zip_name = "VolumetricCaptureSystem Controls.zip"

    zip_path = dist_dir / zip_name
    zip_folder(str(bundle_dir), str(zip_path))

    # Aufräumen
    shutil.rmtree(bundle_dir)

def zip_folder(folder_path, output_path):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(folder_path):
            for f in files:
                full = os.path.join(root, f)
                arc  = os.path.relpath(full, start=folder_path)
                z.write(full, arc)

def copy_new_files(source_folder: str, destination_folder: str) -> None:
    for root, dirs, files in os.walk(source_folder):
        rel_path = os.path.relpath(root, source_folder)
        dest_dir = os.path.join(destination_folder, rel_path)
        os.makedirs(dest_dir, exist_ok=True)
        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_dir, file)
            if not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)

def create_bat(dist_folder):
    bat_content = """@echo off
start "" "%~dp0_core\\config"
"""
    with open(os.path.join(dist_folder, "Open Config.bat"), 'w', encoding='utf-8') as f:
        f.write(bat_content)

def create_command(dist_folder):
    cmd = """#!/bin/bash
open "$(dirname "$0")/_core/config"
"""
    path = os.path.join(dist_folder, "Open Config.command")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cmd)
    os.chmod(path, 0o755)

def main():
    build_scripts()
    clean_up()

if __name__ == "__main__":
    main()
