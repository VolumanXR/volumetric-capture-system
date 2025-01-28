@echo off
REM Batch-Datei zur Umwandlung von .h264 zu .mp4 ohne Neukodierung

REM Überprüfen, ob FFmpeg verfügbar ist
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo FFmpeg wurde nicht gefunden. Bitte installiere FFmpeg und stelle sicher, dass es im PATH ist.
    pause
    exit /b
)

REM Durchsuche alle .h264-Dateien im aktuellen Verzeichnis
for %%f in (*.h264) do (
    echo Verarbeite %%f...
    ffmpeg -i "%%f" -c copy "%%~nf.mp4"
    if errorlevel 1 (
        echo Fehler beim Verarbeiten von %%f
    ) else (
        echo %%f erfolgreich in %%~nf.mp4 umgewandelt.
    )
)

echo Alle Dateien wurden verarbeitet.
pause
