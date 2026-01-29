# THIRD PARTY NOTICES

This repository depends on third-party open source software. This document provides attribution and direct links to the applicable license texts.

The license terms for each dependency govern that dependency only. This repository’s own license is provided in the root `LICENSE` file.

## Python dependencies

### Flask 3.1.2
- Project: https://pypi.org/project/Flask/
- License: BSD 3-Clause
- License text:
  - https://github.com/pallets/flask/blob/main/LICENSE.txt
  - https://flask.palletsprojects.com/en/stable/license/

### netifaces 0.11.0
- Project: https://pypi.org/project/netifaces/
- License: MIT
- License text:
  - https://github.com/al45tair/netifaces/blob/master/LICENSE

### paramiko 4.0.0
- Project: https://pypi.org/project/paramiko/
- License: LGPL 2.1 (or later, per upstream)
- License text:
  - https://github.com/paramiko/paramiko/blob/main/LICENSE
  - FSF LGPL 2.1 text: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt

### picamera2 0.3.33
- Project: https://pypi.org/project/picamera2/
- License: BSD 2-Clause
- License text:
  - https://github.com/raspberrypi/picamera2/blob/main/LICENSE

### Pillow 12.1.0
- Project: https://pypi.org/project/pillow/
- License: MIT-CMU
- License text:
  - https://github.com/python-pillow/Pillow/blob/main/LICENSE
  - SPDX MIT-CMU text: https://spdx.org/licenses/MIT-CMU.html

### psutil 7.2.2
- Project: https://pypi.org/project/psutil/
- License: BSD 3-Clause
- License text:
  - https://github.com/giampaolo/psutil/blob/master/LICENSE

### pygame 2.6.1
- Project: https://pypi.org/project/pygame/
- License: LGPL 2.1
- License text:
  - https://github.com/pygame/pygame/blob/main/docs/LGPL.txt
  - FSF LGPL 2.1 text: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt

### PyInstaller 6.18.0
- Project: https://pypi.org/project/pyinstaller/
- License: GPL 2.0 (or later) with PyInstaller bootloader exception; plus Apache 2.0 for certain files (see upstream)
- License terms and exception:
  - https://pyinstaller.org/en/stable/license.html
  - https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt
  - FSF GPL 2.0 text: https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt

### pyzmq 27.1.0
- Project: https://pypi.org/project/pyzmq/
- License: BSD 3-Clause
- License text:
  - https://github.com/zeromq/pyzmq/blob/main/LICENSE.md

### Requests 2.32.5
- Project: https://pypi.org/project/requests/
- License: Apache 2.0
- License text and notice:
  - https://github.com/psf/requests/blob/main/LICENSE
  - https://github.com/psf/requests/blob/main/NOTICE
  - Apache 2.0 text: https://www.apache.org/licenses/LICENSE-2.0.txt

### opencv-python 
- Project: https://pypi.org/project/opencv-python/
- Licensing summary (upstream packaging project):
  - opencv-python packaging scripts: MIT
  - OpenCV: Apache 2.0
  - Wheel-bundled third-party components: see LICENSE-3RD-PARTY
- License texts and third-party notices:
  - opencv-python (MIT): https://github.com/opencv/opencv-python/blob/4.x/LICENSE.txt
  - OpenCV (Apache 2.0): https://github.com/opencv/opencv/blob/4.x/LICENSE
  - opencv-python third-party notices: https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt

## Binary redistribution note (LGPL components)

If you redistribute this project in binary or “frozen” form and bundle LGPL-licensed components (for example, `paramiko`, `pygame`, and wheel-bundled components referenced by `opencv-python`), you must ensure your distribution meets the applicable LGPL requirements (including providing license texts/notices and allowing replacement or relinking, as applicable).
