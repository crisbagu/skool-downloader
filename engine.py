"""Skool Downloader: authenticated browser discovery and resumable downloads."""
import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
PROFILE = Path.home() / 'Library/Application Support/Skool Downloader/browser'

def emit(event, **data):
    print(json.dumps({'event': event, **data}, ensure_ascii=False), flush=True)

def validate_lesson(value):
    value = value.strip()
    u = urlsplit(value)
    if u.scheme != 'https' or u.hostname not in ('skool.com', 'www.skool.com') or u.username or u.password or u.port not in (None, 443) or '/classroom/' not in u.path or not parse_qs(u.query).get('md'):
        raise ValueError('Pega el enlace de una lección de Skool: debe incluir /classroom/ y ?md=…')
    return value

def media_priority(url):
    u = urlsplit(url)
    if u.scheme not in ('https', 'http'):
        return 0
    if u.path.endswith('.m3u8'):
        return 100 if u.hostname == 'stream.video.skool.com' else (40 if 'rendition' in u.path else 80)
    if u.path.endswith(('.mpd', '.mp4', '.webm')):
        return 70
    if u.hostname in ('www.youtube.com', 'www.youtube-nocookie.com', 'youtube.com', 'youtu.be', 'player.vimeo.com', 'www.loom.com', 'loom.com', 'fast.wistia.net', 'fast.wistia.com') and re.search(r'/embed/|/video/|/share/|/medias/|/watch', u.path):
        return 60
    return 0

def format_selector(quality):
    if quality == 'best':
        return 'bv*+ba/b'
    if quality not in ('2160', '1440', '1080', '720', '480', '360'):
        raise ValueError('Calidad no válida')
    return f'bv*[height<={quality}]+ba/b[height<={quality}]'

class QuietLogger:
    def debug(self, message): pass
    def warning(self, message):
        emit('status', message=redact(str(message)))
    def error(self, message): pass

EXPIRED_LINK = re.compile(r'\b40[13]\b|\b410\b|forbidden|expired|caduc|token|cloudfront|request blocked|access denied', re.I)

def is_expired_link(exc):
    """A signed Mux/CloudFront link that has lapsed answers with a block page, not a clean 401."""
    return bool(EXPIRED_LINK.search(str(exc)))

import shutil as _shutil

def _ffmpeg_dir():
    """Carpeta de ffmpeg de forma portátil (Mac/Windows/Linux); vacío = que yt-dlp lo busque en PATH."""
    exe = _shutil.which('ffmpeg')
    if exe:
        return str(Path(exe).resolve().parent)
    for cand in ('/opt/homebrew/bin', '/usr/local/bin', '/usr/bin'):
        if (Path(cand) / 'ffmpeg').exists():
            return cand
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return str(Path(exe).resolve().parent)
    except Exception:
        pass
    return ''

def redact(message):
    if re.search(r'cloudfront|request could not be satisfied|request blocked', message, re.I):
        message = 'El enlace temporal del video caducó o el CDN lo bloqueó. Vuelve a analizar la lección e inténtalo de nuevo.'
    return re.sub(r'https?://\S+', '[enlace multimedia]', message)

def download_media(url, title, lesson, destination, quality='best', cookies=None, user_agent=None, media_key='', announce=True):
    import yt_dlp
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^\w .()\-]', '_', title, flags=re.UNICODE).strip(' .')[:130] or 'Video de Skool'
    identity = hashlib.sha256((lesson + ('#' + media_key if media_key else '')).encode()).hexdigest()[:10]
    name += f' [{identity}] [{quality}]'
    last = [0.0]
    def progress(d):
        if d['status'] == 'downloading' and time.monotonic() - last[0] > 0.4:
            last[0] = time.monotonic()
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            emit('progress', percent=100*d.get('downloaded_bytes', 0)/total if total else 0, message='Descargando video…')
        elif d['status'] == 'finished':
            emit('status', message='Uniendo audio y video…')
    headers = {'Referer': lesson}
    if user_agent:
        headers['User-Agent'] = user_agent
    options = {'format': format_selector(quality), 'outtmpl': str(destination / (name + '.%(ext)s')),
        'merge_output_format': 'mp4', 'continuedl': True, 'retries': 10, 'fragment_retries': 10,
        'socket_timeout': 30, 'concurrent_fragment_downloads': 4, 'noplaylist': True,
        'overwrites': False, 'quiet': True, 'no_warnings': False, 'logger': QuietLogger(),
        'progress_hooks': [progress], 'http_headers': headers, 'skip_unavailable_fragments': False,
        'postprocessors': [{'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}]}
    _ff = _ffmpeg_dir()
    if _ff:
        options['ffmpeg_location'] = _ff
    else:
        try:
            import imageio_ffmpeg
            options['ffmpeg_location'] = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    with yt_dlp.YoutubeDL(options) as ydl:
        # Keep cookie domains and paths: never forward a Skool Cookie header to an embed provider.
        for c in cookies or []:
            expires = int(c['expires']) if c.get('expires', -1) > 0 else None
            ydl.cookiejar.set_cookie(http.cookiejar.Cookie(0, c['name'], c['value'], None, False,
                c['domain'], True, c['domain'].startswith('.'), c.get('path', '/'), True,
                c.get('secure', True), expires, expires is None, None, None, {}, False))
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError('El proveedor no devolvió un video descargable.')
        target = Path(ydl.prepare_filename(info)).with_suffix('.mp4')
        if not target.is_file():
            target = Path(ydl.prepare_filename(info))
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError('La descarga no produjo un archivo completo.')
        if announce:
            emit('done', path=str(target), message='Descarga completa')
        return target

# Traverse open shadow roots as used by Skool\'s native player.
DOM_MEDIA = """() => { const items=[]; function walk(root){ for(const e of root.querySelectorAll('*')){ if(['VIDEO','SOURCE','IFRAME'].includes(e.tagName)){if(e.src)items.push(e.src);if(e.currentSrc)items.push(e.currentSrc);} if(e.shadowRoot)walk(e.shadowRoot); } } walk(document); return items; }"""

def discover(page, lesson, timeout=600):
    found = {}
    def observe(response):
        score = media_priority(response.url)
        if score and response.status < 400:
            found[response.url] = score
    page.on('response', observe)
    emit('status', message='Abriendo Skool. Inicia sesión si hace falta y pulsa Play en la lección.')
    page.goto(lesson, wait_until='domcontentloaded', timeout=60000)
    deadline = time.monotonic() + timeout
    first = None
    while time.monotonic() < deadline:
        if page.is_closed():
            raise RuntimeError('Se cerró el navegador antes de detectar el video.')
        current = urlsplit(page.url)
        wanted = urlsplit(lesson)
        same_lesson = current.path == wanted.path and parse_qs(current.query).get('md') == parse_qs(wanted.query).get('md')
        if same_lesson:
            for frame in page.frames:
                for url in frame.evaluate(DOM_MEDIA):
                    score = media_priority(url)
                    if score:
                        found[url] = score
            if found:
                if first is None:
                    first = time.monotonic()
                if max(found.values()) == 100 or time.monotonic() - first > 3:
                    title = page.title().split(' · ')[0]
                    return max(found, key=found.get), title
        else:
            found.clear()
            first = None
        page.wait_for_timeout(500)
    raise RuntimeError('No se detectó un video. Abre la lección, comprueba tu acceso y pulsa Play. Si el proveedor usa DRM, no se puede descargar con esta herramienta.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--quality', default='best')
    parser.add_argument('--output', default=str(Path.home() / 'Downloads/Skool'))
    parser.add_argument('--action', choices=['single','scan','batch','selfcheck'], default='single')
    parser.add_argument('--scope', choices=['all','courses','posts'], default='all')
    parser.add_argument('--catalog', default=str(PROFILE.parent / 'catalog.json'))
    parser.add_argument('--selection')
    args = parser.parse_args()
    if args.action == 'selfcheck':
        import yt_dlp, playwright
        print('selfcheck OK | ffmpeg=' + (_ffmpeg_dir() or 'PATH') + ' | yt_dlp=' + getattr(yt_dlp.version, '__version__', '?') + ' | playwright=' + getattr(playwright, '__version__', '?'))
        return 0
    from catalog import parse_target, SkoolSession, scan, load_catalog, run_batch, playback_url
    target = parse_target(args.url)
    lesson = target['url']
    format_selector(args.quality)
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(PROFILE, 0o700)
    import fcntl
    lock = (PROFILE.parent / 'engine.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Ya hay un análisis o descarga en marcha. Cancélalo antes de iniciar otro.')
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(str(PROFILE), channel='chrome', headless=False, accept_downloads=True)
        except Exception:
            # Sin Chrome del sistema: usa el Chromium que trae Playwright (binario autónomo).
            context = p.chromium.launch_persistent_context(str(PROFILE), headless=False, accept_downloads=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            session = SkoolSession(context, page)
            if args.action in ('scan','batch'):
                session.login(target['base'])
                if args.action == 'scan':
                    scan(session, target, args.scope, args.catalog)
                    return
                data = load_catalog(args.catalog)
                if data.get('target') != target['url']:
                    raise RuntimeError('El inventario pertenece a otro enlace. Analiza el enlace actual primero.')
                selected = json.loads(Path(args.selection).read_text()) if args.selection else [i['id'] for i in data['items'] if i.get('accessible',True)]
                if not selected:
                    raise ValueError('Selecciona al menos un video del inventario.')
                def one(item):
                    for attempt in range(2):
                        try:
                            props = session.read(item['url'])
                            media = playback_url(props, item['video_id']) if item.get('video_id') else item.get('media_hint')
                            if not media:
                                raise RuntimeError('Skool no proporcionó reproducción para este video. Comprueba tu acceso o vuelve a analizar.')
                            subfolder = re.sub(r'[^\w .()-]', '_', item['source']).strip(' .')[:90] or 'Videos'
                            return download_media(media, item['title'], item['url'], Path(args.output)/subfolder, args.quality, context.cookies(), page.evaluate('navigator.userAgent'), item['media_key'], False)
                        except Exception as exc:
                            if attempt == 0 and is_expired_link(exc):
                                emit('status', message='Renovando enlace temporal del video…')
                                continue
                            raise
                run_batch(data, selected, args.quality, one, args.catalog)
            else:
                for attempt in range(2):
                    # Re-discovering replays the lesson so Skool mints a fresh playback token.
                    media, title = discover(page, lesson, timeout=600 if attempt == 0 else 180)
                    emit('status', message='Video detectado: ' + title)
                    try:
                        download_media(media, title, lesson, args.output, args.quality, context.cookies(), page.evaluate('navigator.userAgent'))
                        break
                    except Exception as exc:
                        if attempt == 0 and is_expired_link(exc):
                            emit('status', message='El enlace temporal del video caducó. Renovándolo…')
                            continue
                        raise
        finally:
            context.close()

if __name__ == '__main__':
    os.setpgrp()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        emit('error', message=redact(str(exc)))
        sys.exit(1)
