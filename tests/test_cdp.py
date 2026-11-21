"""HTML → PNG e HTML → PDF pelo Edge sem janela (lumen/cdp.py): tamanho, escala, texto, links e marcadores."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from pypdf import PdfReader

import tests  # noqa: F401
from lumen import cdp


@unittest.skipUnless(cdp.edge(), "sem Microsoft Edge")
class Cdp(unittest.TestCase):
    def test_png_has_the_size_scale_and_colors_of_the_page(self):
        b = cdp.png("<body style='margin:0;background:#123456'>", 320, 120, scale=2)
        img = Image.open(io.BytesIO(b)).convert("RGB")
        self.assertEqual(img.size, (640, 240))
        self.assertEqual(img.getpixel((5, 5)), (0x12, 0x34, 0x56))

    def test_pdf_keeps_text_links_pages_and_outline(self):
        b = cdp.pdf("<style>@page{size:A4;margin:2cm}</style><h1>Ciclo de estudo</h1>"
                    "<p>Veja <a href='https://example.com/fonte'>a fonte</a>.</p><h1 style='break-before:page'>Revisão</h1>")
        r = PdfReader(io.BytesIO(b))
        self.assertEqual(len(r.pages), 2)
        self.assertIn("Ciclo de estudo", r.pages[0].extract_text())
        self.assertIn("Revisão", r.pages[1].extract_text())
        links = [a.get_object()["/A"].get("/URI") for a in r.pages[0].get("/Annots", [])]
        self.assertIn("https://example.com/fonte", links)
        self.assertEqual([o.title for o in r.outline], ["Ciclo de estudo", "Revisão"])

    def test_leaves_no_profile_behind(self):
        before = set(Path(tempfile.gettempdir()).glob("lumen-cdp-*"))
        original, blocked = Path.read_text, []
        def read(path, *args, **kwargs):
            if path.name == "DevToolsActivePort" and not blocked:
                blocked.append(True)
                raise PermissionError("o Edge ainda está gravando")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "read_text", read):
            self.assertTrue(cdp.png("<p>oi</p>", 100, 50))
        self.assertTrue(blocked)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("lumen-cdp-*")), before)


class NoEdge(unittest.TestCase):
    def test_without_edge_returns_none(self):
        with mock.patch.object(cdp, "edge", return_value=None):
            self.assertIsNone(cdp.png("<p>oi</p>", 10, 10))
            self.assertIsNone(cdp.pdf("<p>oi</p>"))
