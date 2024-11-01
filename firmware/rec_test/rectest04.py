import cv2
import os
import time
import glob
from tqdm import tqdm

# Konstanten
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
INPUT_FPS = 60   # Eingangs-Frame-Rate
OUTPUT_FPS = 30  # Gewünschte Ausgabe-Frame-Rate
DURATION = 10    # Dauer jeder Aufnahme in Sekunden
BITRATES_Mbps = [1, 2, 4, 8]  # Bitraten in Mbps

# Aufnahmeordner erstellen, falls nicht vorhanden
RECORDINGS_DIR = 'recordings'
os.makedirs(RECORDINGS_DIR, exist_ok=True)

def get_next_recording_filename(bitrate_mbps):
    """Generiert einen neuen eindeutigen Dateinamen basierend auf vorhandenen Dateien."""
    files = glob.glob(f"{RECORDINGS_DIR}/rec*_br{bitrate_mbps}Mbps.mp4")
    if not files:
        return f"{RECORDINGS_DIR}/rec1_br{bitrate_mbps}Mbps.mp4"
    # Höchste Aufnahmenummer ermitteln und inkrementieren
    latest_recording = max([int(f.split('rec')[-1].split('_br')[0]) for f in files])
    return f"{RECORDINGS_DIR}/rec{latest_recording + 1}_br{bitrate_mbps}Mbps.mp4"

def record_video_for_bitrate(bitrate_mbps):
    """Nimmt ein Video mit der angegebenen Bitrate auf."""
    cap = cv2.VideoCapture(4)  # Kamera öffnen (Index anpassen falls nötig)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, INPUT_FPS)

    if not cap.isOpened():
        print("Fehler: Konnte die Kamera nicht öffnen.")
        return

    # Tatsächliche Eingangs-FPS ermitteln
    actual_input_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"Tatsächliche Eingangs-FPS: {actual_input_fps}")

    # Videocodec und VideoWriter-Objekt definieren
    filename = get_next_recording_filename(bitrate_mbps)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 'mp4v' für MP4-Dateien

    # VideoWriter mit gewünschter Bitrate konfigurieren (funktioniert je nach OpenCV-Version)
    out = cv2.VideoWriter(
        filename, fourcc, OUTPUT_FPS, (VIDEO_WIDTH, VIDEO_HEIGHT), params=[
            cv2.VIDEOWRITER_PROP_QUALITY, bitrate_mbps
        ]
    )

    if not out.isOpened():
        print("Fehler: Konnte VideoWriter nicht initialisieren.")
        cap.release()
        return

    total_frames = int(DURATION * OUTPUT_FPS)
    frames_to_skip = int(INPUT_FPS / OUTPUT_FPS)
    frame_count = 0

    print(f"Aufnahme mit Bitrate {bitrate_mbps} Mbps gestartet...")

    # Fortschrittsbalken initialisieren
    with tqdm(total=total_frames, desc=f"Aufnahme bei {bitrate_mbps} Mbps") as pbar:
        start_time = time.time()
        while frame_count < total_frames:
            ret, frame = cap.read()
            if not ret:
                print("Fehler beim Erfassen des Frames. Beende...")
                break

            if frame_count % frames_to_skip == 0:
                out.write(frame)
                pbar.update(1)

            frame_count += 1

            elapsed_time = time.time() - start_time
            if elapsed_time >= DURATION:
                print(f"Aufnahme mit Bitrate {bitrate_mbps} Mbps abgeschlossen.")
                break

    # Ressourcen freigeben
    cap.release()
    out.release()

    print(f"Aufnahme gespeichert als {filename}")

if __name__ == "__main__":
    # Für jede Bitrate ein Video aufnehmen
    for bitrate_mbps in BITRATES_Mbps:
        record_video_for_bitrate(bitrate_mbps)