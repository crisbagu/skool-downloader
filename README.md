# Skool Downloader para Mac

Abre `build/Skool Downloader.app` con doble clic.

1. Pega el enlace de una **lección** de cualquier comunidad de Skool. Incluye `/classroom/` y `?md=`.
2. Elige la calidad máxima y la carpeta. «Mejor disponible» conserva la resolución más alta que ofrezca el proveedor.
3. Pulsa **Descargar video**. Se abre una ventana propia de Chrome.
4. La primera vez, inicia sesión en Skool. Si acabas en la página de inicio, pega de nuevo el enlace de la lección en ese navegador. Abre el video y pulsa **Play**.
5. La descarga empieza automáticamente. Al terminar, pulsa **Abrir video** o **Mostrar archivo**.

La sesión queda en `~/Library/Application Support/Skool Downloader/browser`, separada de tu Chrome habitual. Las credenciales no se envían a ningún servicio adicional. No abras dos descargas a la vez con este perfil.

## Compatibilidad y límites

- Detecta el HLS nativo de Skool y videos HTML, incluidos reproductores con shadow DOM. Reconoce embeds habituales de YouTube, Vimeo, Loom y Wistia mediante yt-dlp. Estos proveedores pueden exigir autenticación adicional o cambiar sus restricciones.
- Requiere tu acceso legítimo a la lección. No elimina DRM ni desbloquea cursos.
- La calidad elegida es un límite, no un escalado. Si el proveedor no ofrece un formato compatible dentro de ese límite, muestra un error: prueba «Mejor disponible».
- Cancela y repite con la misma lección, carpeta y calidad para reanudar los fragmentos disponibles. No declara éxito si faltan fragmentos. Los archivos completos existentes se reutilizan.
- Los enlaces multimedia temporales se detectan de nuevo en cada ejecución. No se guarda una lista de enlaces que vaya a caducar.
- Esta instalación utiliza Python de Homebrew, Chrome y FFmpeg instalados en este Mac. La app referencia esta carpeta: **no muevas ni borres `skool-downloader`**. No es un instalador portátil para otro ordenador.

## Comprobaciones realizadas

- Descarga real de «Cuenta Personal o Empresa»: 373,54 segundos, H.264 1920×1080 y audio AAC, MP4 de 77.105.121 bytes.
- Pruebas automáticas de validación, selección de medios, límite de calidad y flujo de detección/descarga con servidor de prueba y navegador real.
- App compilada y abierta; validación de enlace incorrecto y selector de calidad comprobados en la interfaz.

## Desarrollo

```sh
.venv/bin/python -m unittest discover -s tests -v
python3 build.py
.venv/bin/python engine.py 'https://www.skool.com/comunidad/classroom/curso?md=leccion' --quality 1080
```

Dependencias en `requirements.txt`. Los errores y URLs sensibles se filtran antes de mostrarse en la app.

## Uso por línea de comandos (multiplataforma: Windows / Linux / Mac)

El motor `engine.py` funciona en Windows, Linux y macOS. Requiere Python 3.11+, Google Chrome y ffmpeg en el PATH.

```sh
python -m venv .venv
# Windows:  .venv\Scripts\pip install -r requirements.txt
# Mac/Linux: .venv/bin/pip install -r requirements.txt
python -m playwright install chrome

# Analizar una comunidad (genera catalog.json):
python engine.py "https://www.skool.com/comunidad/classroom" --action scan --catalog catalog.json

# Descargar una lección suelta:
python engine.py "https://www.skool.com/comunidad/classroom/curso?md=leccion" --quality 1080 --output ./descargas
```

Al ejecutarse se abre una ventana de Chrome para que inicies sesión en Skool. La sesión y las cookies quedan solo en tu equipo.

### Generar el .exe de Windows

Ejecuta **en un equipo Windows** (no se puede compilar Windows desde macOS):

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\playwright install chrome
.venv\Scripts\python build_windows.py
```

El resultado es `dist/skool-downloader.exe` (herramienta de línea de comandos). La app con ventana solo existe para macOS.

## Privacidad y datos sensibles

- Las cookies y la sesión de Skool quedan **solo en tu equipo** (`~/Library/Application Support/Skool Downloader/browser` en Mac; carpeta de perfil local en Windows). Nunca se suben al repositorio ni a ningún servicio.
- El repositorio ignora (`.gitignore`) los datos de usuario: `catalog.json`, `selection.json`, el perfil `browser/`, los vídeos descargados y los artefactos de build.
- Los mensajes de error se filtran (`redact`) para no mostrar URLs firmadas ni tokens temporales.
- Requiere tu acceso legítimo al contenido. No elimina DRM ni desbloquea cursos a los que tu cuenta no tenga derecho.
