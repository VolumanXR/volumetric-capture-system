import PyInstaller.__main__
import os
import shutil
import sys
import platform
from pathlib import Path
import zipfile

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.parent.resolve()
# map source scripts to their user-friendly names
scripts = {
    'master_camera_controller.py':    'Camera Controller',
    'master_capture_controller.py':   'Capture Controller',
    'master_download_manager.py':     'Download Manager',
}

# base name for the final program folder
PROGRAM_NAME = 'VolumetricCaptureSystem Controls'

def build_scripts():
    is_windows = sys.platform == 'win32'
    add_data_sep = ';' if is_windows else ':'
    for src, nice_name in scripts.items():
        base = Path(src).stem  # e.g. "master_camera_controller"
        # pick correct icon extension
        icon_ext = 'ico' if is_windows else 'icns'
        icon_path = PROJECT_DIR / f"src/res/{base}.{icon_ext}"

        PyInstaller.__main__.run([
            '--noconfirm',
            '--onedir',
            '--name', nice_name,
            '--icon', str(icon_path),
            # share config and res into a folder named "config" and "res" inside _core
            '--add-data', str(PROJECT_DIR / "src/config") + f"{add_data_sep}config",
            '--add-data', str(PROJECT_DIR / "src/res")    + f"{add_data_sep}res",
            str(PROJECT_DIR / 'src' / src),
            '--distpath', str(PROJECT_DIR / 'dist' ),
            '--workpath', str(PROJECT_DIR / 'build'),
            '--specpath', str(PROJECT_DIR / 'build'),
            '--contents-directory', '_core',
            '--noconsole'
        ])

def clean_up():
    print("Cleaning up...")
    dist_root = PROJECT_DIR / 'dist'
    complete_dir = dist_root / PROGRAM_NAME

    # prepare clean folder
    if complete_dir.exists():
        shutil.rmtree(complete_dir)
    complete_dir.mkdir()

    # add the Windows .bat to open config (will harmlessly sit in mac builds)
    create_bat(complete_dir)

    # copy each built app next to the shared _core folder
    for src, nice_name in scripts.items():
        src_folder = dist_root / nice_name
        copy_new_files(str(src_folder), str(complete_dir))

    # if on Windows, zip up with a platform-tagged name and then remove the temp folder
    if sys.platform == 'win32':
        zip_name = f"{PROGRAM_NAME} Windows.zip"
        zip_path = dist_root / zip_name
        zip_folder(str(complete_dir), str(zip_path))
        shutil.rmtree(complete_dir)

def zip_folder(folder_path: str, output_path: str):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname  = os.path.relpath(file_path, start=folder_path)
                zipf.write(file_path, arcname)

def copy_new_files(source_folder: str, destination_folder: str) -> None:
    for root, dirs, files in os.walk(source_folder):
        rel = os.path.relpath(root, source_folder)
        dest_path = os.path.join(destination_folder, rel) if rel != '.' else destination_folder

        if not os.path.exists(dest_path):
            os.makedirs(dest_path)

        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_path, file)
            if not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)

def create_bat(dist_folder: Path):
    """
    Creates a 'Open Config Folder.bat' file next to the packaged app(s).
    """
    bat_content = """@echo off
start "" "%~dp0_core\\config"
"""
    bat_path = dist_folder / "Open Config.bat"
    bat_path.write_text(bat_content, encoding='utf-8')

def main():
    build_scripts()
    clean_up()

if __name__ == "__main__":
    main()
