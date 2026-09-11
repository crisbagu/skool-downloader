import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine

class EngineTests(unittest.TestCase):
    def test_rejects_non_skool_and_missing_lesson(self):
        for url in ['https://skool.com.evil.org/a/classroom/b?md=c', 'file:///etc/passwd', 'https://www.skool.com/a/about']:
            with self.assertRaises(ValueError):
                engine.validate_lesson(url)

    def test_accepts_lesson(self):
        self.assertEqual(engine.validate_lesson(' https://www.skool.com/a/classroom/b?md=c '), 'https://www.skool.com/a/classroom/b?md=c')

    def test_recognizes_master_not_fragment_or_thumbnail(self):
        self.assertEqual(engine.media_priority('https://stream.video.skool.com/id.m3u8?token=x'), 100)
        self.assertEqual(engine.media_priority('https://cdn.test/a.ts'), 0)
        self.assertEqual(engine.media_priority('https://cdn.test/image.jpg'), 0)
        self.assertGreater(engine.media_priority('https://player.vimeo.com/video/123'), 0)

    def test_quality_never_falls_back_above_limit(self):
        value = engine.format_selector('720')
        self.assertIn('height<=720', value)
        self.assertNotIn('/best', value)
        with self.assertRaises(ValueError):
            engine.format_selector('garbage')

if __name__ == '__main__':
    unittest.main()
