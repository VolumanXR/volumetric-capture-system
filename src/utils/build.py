import PyInstaller.__main__
import os
import shutil
from pathlib import Path
import zipfile

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.parent.resolve()
scripts = ['master_camera_controller.py', 'master_capture_controller.py', 'master_download_manager.py']

def build_scripts():
    for script in scripts:
        scriptname = script.split('.')[0]
        PyInstaller.__main__.run([
                '--noconfirm', '--onedir', '--name', scriptname,
                '--icon', os.path.join(PROJECT_DIR, f"src/res/{scriptname}.ico"),
                '--add-data', os.path.join(PROJECT_DIR, "src/config") +";config", 
                '--add-data', os.path.join(PROJECT_DIR, "src/res") +";res", 
                os.path.join(PROJECT_DIR, 'src', script),
                '--distpath', os.path.join(PROJECT_DIR, 'dist'),
                '--workpath', os.path.join(PROJECT_DIR, 'build'),
                '--specpath', os.path.join(PROJECT_DIR, 'build'),
                '--contents-directory', '_core',
                '--noconsole'
            ])

def clean_up():
    print("Cleaning up...")
    complete_program_dir = os.path.join(PROJECT_DIR, 'dist', 'VolumetricCaptureSystem Controls')

    if os.path.exists(complete_program_dir):    
        shutil.rmtree(complete_program_dir)

    os.mkdir(complete_program_dir)
    create_bat(complete_program_dir)

    for script in scripts:
        # move exe to complete_program_dir
        scriptname = script.split('.')[0]   
        copy_new_files(os.path.join(PROJECT_DIR, 'dist',scriptname), complete_program_dir)
    
    zip_folder(complete_program_dir, os.path.join(PROJECT_DIR, 'dist', 'VolumetricCaptureSystem Controls.zip'))
    shutil.rmtree(complete_program_dir)

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

        if not os.path.exists(destination_path):
            os.makedirs(destination_path)

        for file in files:
            source_file = os.path.join(root, file)
            destination_file = os.path.join(destination_path, file)

            if not os.path.exists(destination_file):
                shutil.copy2(source_file, destination_file)

def create_bat(dist_folder):
    """
    Creates a 'Open Config Folder.bat' file next to the packaged exe.
    
    Args:
        dist_folder (str): Path to the output folder containing the .exe
    """
    bat_content = """@echo off
start "" "%~dp0_core\\config"
"""

    bat_path = os.path.join(dist_folder, "Open Config.bat")

    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)

def main():
    build_scripts()
    clean_up()

if __name__ == "__main__":
    main()