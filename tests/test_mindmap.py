import struct
import unittest

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import cover, mindmap
from tests.test_llm import GOOD


class MindMap(unittest.TestCase):
    def test_data_cleans_and_falls_back_to_topics(self):
        m = mindmap.data({**GOOD, "mind_map": {"center": "  Foto  ", "branches": [
            {"label": "A", "emoji": "<b>", "children": ["x", "x", "", 3, "y" * 200]}, {"label": "", "children": []},
            {"label": "B", "emoji": "🌿", "children": []}]}})
        self.assertEqual(m["center"], "Foto")
        self.assertEqual(m["branches"][0]["emoji"], "")             # emoji inválido descartado
        self.assertEqual(m["branches"][0]["children"][:1], ["x"])   # repetidos e vazios fora
        self.assertTrue(m["branches"][0]["children"][1].endswith("…"))
        self.assertEqual([b["label"] for b in m["branches"]], ["A", "B"])
        old = mindmap.data(GOOD)                                    # aula salva antes do mapa existir
        self.assertEqual(old["center"], "Fotossíntese")
        self.assertEqual(old["branches"][0]["label"], "Fase clara")

    def test_html_escapes_text(self):
        page = mindmap.html({"center": "<script>x</script>", "branches": [{"label": "a&b", "emoji": "", "children": ["<i>"]}]})
        self.assertNotIn("<script>x", page)
        self.assertIn("a&amp;b", page)

    @unittest.skipUnless(cover.edge(), "Microsoft Edge não encontrado")
    def test_render_png_in_high_resolution(self):
        m = {"center": "Fotossíntese", "branches": [
            {"label": f"Ramo {i}", "emoji": "🌿", "children": ["Folha um", "Folha dois com um texto mais longo"]}
            for i in range(6)]}
        png = mindmap.render(m)
        self.assertTrue(png and png.startswith(b"\x89PNG"))
        w, h = struct.unpack(">II", png[16:24])
        self.assertEqual((w, h), (mindmap.W * 2, mindmap.height(m) * 2))
