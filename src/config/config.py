import os
from pathlib import Path
import sys
import tempfile
import platform

def get_temp_dir():
    """Get the system temporary directory."""
    return Path(tempfile.gettempdir())

def get_app_data_dir(app_name: str = "VolumanXR"):
    """Get the user-specific app data directory, platform-aware."""
    system = platform.system()

    if system == 'Windows':
        base_dir = Path(os.getenv('APPDATA'))
    elif system == 'Darwin':  # macOS
        base_dir = Path.home() / 'Library' / 'Application Support'
    else:  # Linux and other Unix-like systems
        base_dir = Path.home() / '.config'

    app_data_dir = base_dir / app_name
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return app_data_dir

if getattr(sys, 'frozen', False):
    MAIN_DIR = Path(sys._MEIPASS)
else:
    MAIN_DIR = Path(__file__).resolve().parent.parent

USERNAME = "voluman"
PASSWORD = "xr"

UTILS_FOLDER = os.path.join(MAIN_DIR, 'utils')
CONFIG_FOLDER = os.path.join(MAIN_DIR, 'config')
RES_FOLDER = os.path.join(MAIN_DIR, 'res')
DEFAULT_SESSIONS_FOLDER = os.path.join(get_app_data_dir(), 'sessions')

CAMERA_LIST_FILE = os.path.join(CONFIG_FOLDER,'camera_list.json') 
MASTER_SETTINGS_FILE = os.path.join(CONFIG_FOLDER,'camera_settings.json')
TRANSFER_CONFIG_FILE = os.path.join(get_app_data_dir(),'transfer_config.json')
LOGO_PATH = os.path.join(RES_FOLDER, "Voluman_Logo.png")
ICON_PATH = os.path.join(RES_FOLDER, "Voluman_Icon.ico")