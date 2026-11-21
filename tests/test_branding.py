import io
import threading
import unittest
import urllib.request
from pathlib import Path

from PIL import Image

import tests  # noqa: F401
from lumen import server


class Branding(unittest.TestCase):
    def test_windows_icons_preserve_transparency_and_sizes(self):
        root = Path(__file__).resolve().parent.parent
        icon = root / "launcher/lumen.ico"
        self.assertEqual(icon.read_bytes(), (server.WEB / "favicon.ico").read_bytes())
        with Image.open(icon) as image:
            sizes = {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)}
            self.assertEqual(image.ico.sizes(), sizes)
            for size in sizes:
                frame = image.ico.getimage(size).convert("RGBA")
                self.assertEqual(frame.getchannel("A").getextrema(), (0, 255))
        with Image.open(root / "launcher/lumen-256.png") as image:
            self.assertEqual(image.size, (256, 256))

    def test_all_pages_and_brand_images_are_served(self):
        httpd = server.serve()
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_port}"
            for path in ("/", "/widget", "/note", "/design"):
                with urllib.request.urlopen(base + path) as response:
                    html = response.read().decode()
                self.assertIn('rel="icon" href="/favicon.ico"', html)
                self.assertNotIn("data:image/svg+xml", html)
                if path in ("/", "/widget"):
                    self.assertIn('src="/lumen.png"', html)
                    self.assertNotIn("icons.svg#lumen", html)
            for path, content_type in (("/lumen.png", "image/png"), ("/favicon.ico", "image/x-icon")):
                with urllib.request.urlopen(base + path) as response:
                    self.assertEqual(response.headers.get_content_type(), content_type)
                    body = response.read()
                self.assertEqual(body, (server.WEB / path[1:]).read_bytes())
                with Image.open(io.BytesIO(body)) as image:
                    image.load()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
