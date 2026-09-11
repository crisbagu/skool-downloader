import contextlib
import functools
import http.server
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from playwright.sync_api import sync_playwright
import engine

class IntegrationTests(unittest.TestCase):
    def test_shadow_player_download_produces_complete_audio_video_and_reuses_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=640x360:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','2','-c:v','libx264','-c:a','aac','-shortest',str(root/'clip.mp4')],check=True)
            subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-i',str(root/'clip.mp4'),'-c','copy','-hls_time','1','-hls_playlist_type','vod','-master_pl_name','master.m3u8',str(root/'rendition.m3u8')],check=True)
            lesson_path = root/'a/classroom/b'
            lesson_path.parent.mkdir(parents=True)
            lesson_path.write_text('<html><title>Shadow video fixture</title><body><div id="player"></div><script>document.querySelector("#player").attachShadow({mode:"open"}).innerHTML=\'<video src="/master.m3u8" controls></video>\';</script></body></html>')
            class Handler(http.server.SimpleHTTPRequestHandler):
                def log_message(self,*args): pass
                def guess_type(self, path):
                    return 'text/html' if path.endswith('/b') else super().guess_type(path)
            server = http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=tmp))
            worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
            try:
                lesson=f'http://127.0.0.1:{server.server_port}/a/classroom/b?md=fixture'
                with sync_playwright() as p:
                    browser=p.chromium.launch(channel='chrome',headless=True)
                    page=browser.new_page()
                    media,title=engine.discover(page,lesson,timeout=15)
                    self.assertEqual(title,'Shadow video fixture')
                    self.assertTrue(media.endswith('/master.m3u8'))
                    browser.close()
                with contextlib.redirect_stdout(io.StringIO()):
                    output=engine.download_media(media,title,lesson,root/'out','720')
                    before=output.stat().st_mtime_ns
                    again=engine.download_media(media,title,lesson,root/'out','720')
                self.assertEqual(output,again)
                self.assertEqual(before,again.stat().st_mtime_ns)
                info=json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(output)]))
                self.assertEqual({s['codec_type'] for s in info['streams']},{'audio','video'})
                self.assertAlmostEqual(float(info['format']['duration']),2,delta=.2)
                self.assertLessEqual(next(s['height'] for s in info['streams'] if s['codec_type']=='video'),720)
            finally:
                server.shutdown();server.server_close();worker.join()
