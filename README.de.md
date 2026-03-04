[EN](/readme.md) | **DE** 

<p align="center">
  <img src="https://github.com/VolumanXR/.github/blob/main/docs/assets/Logo_VCS.png" alt="Volumetric Capture System Logo" width="400"/>
</p>

# VolumanXR – Volumetric Capture System

Dieses Modul ist Teil des **VolumanXR** Projekts und implementiert ein vollständiges **synchronisiertes volumetrisches Videoaufnahmesystem** auf Basis von Raspberry Pis mit der Camera Module V3. Es ermöglicht die Echtzeitaufnahme mit mehreren Kameras für 4D Gaussian Splatting.

Es beinhaltet:
- Ein skalierbares und individualisierbares Kamerarig
- Ein dezentrales Steuersystem mit synchroner Aufnahme
- GUI-Tools zur Kalibrierung, Aufnahme und zum Download
- Automatisierungsskripte und Konfigurationsverwaltung

> **Wartungshinweis**\
>Dieses Repository dient primär als Dokumentations- und Referenzplattform für Volumetric Capture System des VolumanXR-Forschungsprojekt. Weiterentwicklungen erfolgen nur gelegentlich und nicht kontinuierlich. Repositories können sporadisch aktualisiert werden, eine regelmäßige Pflege oder langfristiger Support ist nicht vorgesehen.

---

## 📦 Projektstruktur
```text
volumetric-capture-system/
├── readme.md
├── requirements.txt
├── cad/                           # 3D-druckbare Kamerahalterungen
├── src/
│   ├── master_camera_controller.py
│   ├── master_capture_controller.py
│   ├── master_download_manager.py
│   ├── config/                    # Geräteeinstellungen und Kameraparameter
│   ├── lib/                       # Gemeinsame Konfig- und SSH-Funktionen
│   ├── remote/                    # Auf Raspberry Pis ausgeführte Skripte
│   ├── res/                       # Icons und Sounds für GUI-Tools
│   └── utils/                     # Hilfsskripte für Setup und Steuerung
```
## 🔧 Hardware-Kontext
<p align="center">
  <img src="https://github.com/VolumanXR/.github/blob/main/docs/assets/VCS_teaser_image.png" alt="Volumetric Capture System Overview Image" width="100%"/>
</p>

- **Kamerarig**: Eigenbau-Rahmen aus Aluminiumprofilen (nicht im Repository enthalten)
- **Kameras**: Raspberry Pi 4B (1GB) + Camera Module V3
- **Geräteanzahl**: ca. 70 Einheiten
- **Halterungen**: 3D-druckbare Modelle (`cad/`)
- **Trigger**: Software-synchronisiert mit NTP + ZeroMQ

> *Der mechanische Aufbau ist speziell an unseren Anwendungsfall angepasst und wurde daher bewusst ausgeschlossen, um individuelle Anpassungen zu ermöglichen. Es basiert auf standardisierten 20×20mm Aluminiumprofilen und die beiliegenden 3D-druckbaren Kamerahalter sind vollständig mit diesem Profilmaß kompatibel. Eine vollständige Stückliste für den Rahmenaufbau kann auf Anfrage bereitgestellt werden.*

---

## 🚀 Hauptfunktionen

### 🎚️ Master Camera Controller (`master_camera_controller.py`)
- GUI für Live-Vorschau und globale Kalibrierung
- ISO, Belichtungszeit, Weißabgleich, Auflösung anpassen
- Einstellungen speichern in `camera_settings.json`

### 📸 Master Capture Controller (`master_capture_controller.py`)
- GUI zur Aufnhame von Fotos und Videos
- Synchronisation aller Agents auf einen Startzeitpunkt
- Framedrop-Erkennung und Timestamp-Protokoll
- Verwendet `camera_list.json` zur Netzwerkverwaltung

### 🔄 Master Download Manager (`master_download_manager.py`)
- GUI für den zentralen Download von Sessions
- Organisiert Dateien, prüft Vollständigkeit, unterstützt Konvertierung
- Offline-Modus zur Bild-Extraktion nach der Aufnahme

---

## 🧠 Remote-Agenten (ausgeführt auf Raspberry Pis)

Die Skripte auf der Remote-Seite befinden sich in `src/remote/` und werden über SSH automatisiert von den Master-Control-GUIs gestartet/gestoppt. Jedes Skript ist für eine zentrale Funktion während der Kalibrierung, Aufnahme oder Datenübertragung verantwortlich.

### Haupt-Remote-Module

- `remote_camera_controller.py`  
  Verarbeitet Kalibrierungsbefehle vom Master Camera Controller (`master_camera_controller.py`), z. B. Fokusanpassung oder Belichtungseinstellungen.

- `remote_capture_controller.py`  
  Empfängt synchronisierte Aufnahmebefehle vom Master Capture Controller (`master_capture_controller.py`), führt die Aufnahme lokal auf den Agenten aus und protokolliert Metadaten.

- `remote_download_manager.py`  
  Führt auf jedem Pi einen einfachen Dateiserver aus, um aufgenommene Sitzungen zum Download bereitzustellen – koordiniert durch den Master Download Manager (`master_download_manager.py`).

### Remote-Hilfsprogramme (`src/remote/utils/`)

- `remote_set_cam_number.py` — Vergibt einen eindeutigen Hostnamen, eine ID (z. B. `CAM00`) und eine feste IP-Adresse  
- `remote_test_camera_settings.py` — Wendet eine Reihe von Kameraeinstellungen an und erstellt Testaufnahmen zur Validierung

---

## 🧰 Allgemeine Hilfsprogramme

Diese Tools befinden sich in `src/utils/` und unterstützen Einrichtung und Fernsteuerung:

- `launcher.py`  
  CLI für Entwicklung, Debugging und Deployment. Unterstützt multithreaded SSH zum Starten/Stoppen/Aktualisieren der Remote-Skripte auf allen Pis.

- `search_devices.py`  
  Durchsucht das lokale Subnetz mithilfe multithreaded Pings nach aktiven Geräten. Versucht, die Hostnamen für jede antwortende IP aufzulösen.

- `set_up_chrony_via_ssh.py`  
  Richtet die Zeit-Synchronisierung auf allen Pis mittels Chrony ein, um eine frame-genaue Auslösung zu ermöglichen.

- `master_set_cam_number.py`  
  Vergibt während der Einrichtung von der Master-Seite aus Kameranummern und Hostnamen.

- `build.py`
  Vorkonfiguriertes Build-Skript für alle drei Hauptprogramme

---

## ⚙️ Konfigurationsdateien

- `camera_list.json` — Liste der Kamera-Hostnamen, IP-Adressen und ihrer individuellen Fokus-Offsets  
- `camera_settings.json` — Globale Standardbelichtungseinstellungen (Verschlusszeit, ISO usw.)

Jeder Pi wird über seinen Hostnamen zugeordnet (z. B. `CAM00`, `CAM01`, ...) und erhält eine feste IP-Adresse im Bereich `10.x.x.x`.  
Das **letzte Oktett der IP-Adresse entspricht der Kameranummer**, beginnend bei `.100`, zum Beispiel:
- `CAM00` → `10.x.x.100`
- `CAM01` → `10.x.x.101`

---

## 🗂 Dateinamen-Konvention

Aufgenommene Dateien folgen diesem Muster:
```
<sitzungsname>_<ip_oktett>.dat
```
Beispiele:
- `DanceA_103.mp4` — Video von Kamera mit IP `10.x.x.103` (`CAM03`)
- `PoseTest_115.jpg` — Foto von Kamera mit IP `10.x.x.115` (`CAM15`)

So lässt sich jede Datei eindeutig der Quellkamera zuordnen.

---

## 🎛 Abhängigkeiten

Installation:
```bash
pip install -r requirements.txt
```
Empfohlene Umgebung: 
- Python 3.10 oder höher  
- Funktioniert unter Windows/macOS (für Master-Skripte) sowie Raspberry Pi OS (für Remote-Agenten)

---

## 👥 Contributions
### Code Contributors

- **Kai Altwicker** — Rig-Design, Synchronisation, Architektur der Hauptsteuerung
- **Dennis Luca Amuser** — Design der Remote-Agenten, Firmware-Programmierung, Netzwerk & Automatisierung

### Veröffentlichungen
- **[IEEE VR26 Poster](https://doi.org/10.13140/RG.2.2.16244.62083) (Preprint)**\
[Steffen Stein](https://www.linkedin.com/in/steffen-sascha-stein/), [Dennis Luca Amuser](https://github.com/dooonnis), [Kai Altwicker](https://github.com/tallAldi), David Mertens, Matthias Bullert Alisa Rüge, David Martin Karf, Kristoffer Waldow, [Arnulph Fuhrmann](https://www.linkedin.com/in/arnulph-fuhrmann-291420279/)
```bibtex
@misc{stein2026scalable,
  author       = {Steffen-Sascha Stein and Dennis Amuser and Kai Altwicker and  David Mertens and Matthias Bullert and Alisa Ruge and David Martin Karg and Kristoffer Waldow and Arnulph Fuhrmann},
  title        = {A Scalable and Cost-Effective Multi-View Capture System for Photorealistic Dynamic Human Reconstruction},
  year         = {2026},
  month        = {February},
  note         = {Preprint. To appear in IEEE VR 2026 Poster Track},
  doi          = {10.13140/RG.2.2.16244.62083},
  url          = {https://doi.org/10.13140/RG.2.2.16244.62083}
}
```

### Unterstützung
- Prof. Dr.-Ing. Fuhrmann
- GatewayTHK
- Makerspace TH Köln 
- Zentralwerkstatt Elektrotechnik, 

---

## 📄 Lizenz


Bitte beachten Sie die [`LICENSE`](/LICENSE)-Datei für die vollständigen Lizenzbedingungen.

Hinweise zu Lizenzen von Drittanbietern finden Sie unter [`THIRD_PARTY_NOTICES.md`](/NOTICE-THIRD-PARTY.md).
---

> ℹ️ Dieses Repository ist Teil des VolumanXR-Projekts.  \
> Den vollständigen Projektkontext finden Sie auf der [VolumanXR](https://github.com/VolumanXR)-Seite.
