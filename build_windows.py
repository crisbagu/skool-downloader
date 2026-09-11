"""Genera skool-downloader.exe en Windows con PyInstaller.

Ejecútalo EN UNA MÁQUINA WINDOWS (no se puede compilar Windows desde macOS):

    python -m venv .venv
    .venv\\Scripts\\pip install -r requirements.txt pyinstaller
    .venv\\Scripts\\playwright install chrome
    .venv\\Scripts\\python build_windows.py

Requisitos en el equipo Windows:
  - Python 3.11+  - Google Chrome instalado  - ffmpeg en el PATH (https://www.gyan.dev/ffmpeg/builds/)

El .exe queda en dist/skool-downloader.exe. Es una herramienta de LÍNEA DE COMANDOS.
La interfaz con ventana (App.swift) es exclusiva de macOS.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    if sys.platform != 'win32':
        print('Este script produce un .exe y debe correr en Windows. En macOS usa build.py.')
        return 1
    cmd = [sys.executable, '-m', 'PyInstaller', '--onefile', '--console',
           '--name', 'skool-downloader',
           '--collect-all', 'playwright', '--collect-all', 'yt_dlp',
           '--add-data', f'{ROOT / "catalog.py"};.',
           str(ROOT / 'engine.py')]
    print('Ejecutando:', ' '.join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode

if __name__ == '__main__':
    raise SystemExit(main())
