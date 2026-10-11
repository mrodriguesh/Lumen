"""Logos de marcas nas capas: busca só por nome escrito igual, acervo conferido, capa e banner da aula."""
import base64
import hashlib
import io
import json
import shutil
import tarfile
import unittest
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, brands, cover, jobs, llm, notion, server, store

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
FAKE = [("Claude", "claude", "D97757", []), ("Claude Code", "claudecode", "D97757", []),
        ("Notion", "notion", "000000", []), ("Meta", "meta", "0467DF", []), ("Zoom", "zoom", "0B5CFF", []),
        ("Google Gemini", "googlegemini", "8E75B2", []), ("Next.js", "nextdotjs", "000000", []),
        ("Linear", "linear", "5E6AD2", []), ("TikTok", "tiktok", "000000", ["Tik Tok"])]


def install(items=FAKE):
    shutil.rmtree(brands.folder(), ignore_errors=True)
    (brands.folder() / "icons").mkdir(parents=True)
    for _, slug, _, _ in items:
        (brands.folder() / "icons" / f"{slug}.svg").write_bytes(SVG)
    (brands.folder() / "marcas.json").write_text(json.dumps(
        [{"title": t, "slug": s, "hex": h, "aka": a} for t, s, h, a in items]), "utf-8")


def names(found):
    return [b["name"] for b in found]


class Find(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(brands.user_folder(), ignore_errors=True)
        install()

    def tearDown(self):
        shutil.rmtree(brands.folder(), ignore_errors=True)
        shutil.rmtree(brands.user_folder(), ignore_errors=True)

    def test_title_names_the_brand(self):
        self.assertEqual(names(brands.find("Curso de Claude")), ["Claude"])
        self.assertEqual(names(brands.find("Como usar o Claude Code")), ["Claude Code"])  # o nome mais longo vence
        self.assertEqual(names(brands.find("Next.js para iniciantes")), ["Next.js"])
        self.assertEqual(names(brands.find("Tik Tok Shop")), ["TikTok"])
        self.assertEqual(names(brands.find("Gemini no dia a dia")), ["Google Gemini"])

    def test_no_fuzzy_match_and_no_brand_means_nothing(self):
        self.assertEqual(brands.find("Aula sobre Cláudia e a cloud"), [])
        self.assertEqual(brands.find("Dominando Adobe Premiere"), [])  # o acervo não tem: sem logo, sem chute

    def test_common_words_only_count_mid_sentence_in_the_title(self):
        self.assertEqual(brands.find("Meta de vendas do mês"), [])
        self.assertEqual(brands.find("Aula 3 - Meta de vendas"), [])
        self.assertEqual(names(brands.find("Marketing com Meta")), ["Meta"])
        self.assertEqual(brands.find("Aula", ["O Linear é uma função. Linear, linear, Linear."]), [])  # nunca no texto

    def test_text_needs_three_capitalised_mentions(self):
        text = "Hoje vamos ver o Notion. No Notion você cria páginas. Abra o Notion e clique."
        self.assertEqual(names(brands.find("Aula 3", [text])), ["Notion"])
        self.assertEqual(brands.find("Aula 3", ["Falei do Notion uma vez e do Notion outra."]), [])
        self.assertEqual(brands.find("Aula 3", ["notion notion notion notion"]), [])  # sem maiúscula

    def test_main_brand_first_and_a_weak_second_is_left_out(self):
        text = " ".join(["Claude"] * 10 + ["Notion"] * 3)
        self.assertEqual(names(brands.find("Aula", [text])), ["Claude"])
        both = " ".join(["Claude"] * 6 + ["Notion"] * 5)
        self.assertEqual(names(brands.find("Aula", [both])), ["Claude", "Notion"])

    def test_user_logos_fill_the_gaps_and_win(self):
        brands.user_folder().mkdir(parents=True)
        (brands.user_folder() / "adobe-premiere.svg").write_bytes(SVG)
        (brands.user_folder() / "Claude.png").write_bytes(b"\x89PNG fake")
        self.assertEqual(names(brands.find("Dominando Adobe Premiere 2.0")), ["Adobe Premiere"])
        mine = brands.find("Curso de Claude")[0]
        self.assertIsNotNone(mine["file"])
        logo = brands.logo(mine)
        self.assertTrue(logo["img"].startswith("data:image/png;base64,") and logo["mask"] is None)
        self.assertEqual(brands.info()["mine"], 2)

    def test_logo_is_an_image_never_inline_svg(self):
        logo = brands.logo(brands.find("Claude")[0])
        self.assertEqual(logo["hex"], "#D97757")
        self.assertTrue(logo["mask"].startswith("data:image/svg+xml;base64,"))
        self.assertIn(b"<svg", base64.b64decode(logo["mask"].split(",")[1]))


class Download(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(brands.folder(), ignore_errors=True)

    @staticmethod
    def tgz(count=1200, svg=SVG):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            def add(name, data):
                i = tarfile.TarInfo("package/" + name)
                i.size = len(data)
                t.addfile(i, io.BytesIO(data))
            add("data/simple-icons.json", json.dumps(
                [{"title": f"Marca {n}", "slug": f"marca{n}", "hex": "123456"} for n in range(count)]).encode())
            for n in range(count):
                add(f"icons/marca{n}.svg", svg)
            add("icons/../evil.svg", svg)  # não bate com o padrão: ignorado
            add("icons/Bad-Name.svg", svg)
        return buf.getvalue()

    def run_download(self, data, sha=None):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.headers = {"Content-Length": str(len(data))}
        chunks = [data, b""]
        resp.read.side_effect = lambda n=0: chunks.pop(0)
        with mock.patch.object(brands.urllib.request, "urlopen", return_value=resp), \
                mock.patch.object(brands, "SHA256", sha or hashlib.sha256(data).hexdigest()):
            brands.download(lambda p, left: None, lambda: None)

    def test_installs_only_the_expected_files(self):
        self.run_download(self.tgz())
        self.assertTrue(brands.ready())
        self.assertEqual(brands.info()["count"], 1200)
        self.assertEqual(len(list((brands.folder() / "icons").glob("*.svg"))), 1200)

    def test_a_different_file_installs_nothing(self):
        data = self.tgz()
        with self.assertRaises(AppError):
            self.run_download(data, sha="0" * 64)
        self.assertFalse(brands.ready())

    def test_an_incomplete_set_installs_nothing_and_keeps_the_old_one(self):
        install()
        with self.assertRaises(AppError):
            self.run_download(self.tgz(count=10))
        self.assertTrue(brands.ready())
        self.assertEqual(brands.info()["count"], len(FAKE))

    def test_non_svg_files_are_dropped(self):
        with self.assertRaises(AppError):  # nenhum ícone válido: acervo incompleto
            self.run_download(self.tgz(svg=b"<html>not an icon</html>"))


class Cover(unittest.TestCase):
    DECOR = {"emoji": "📘", "motifs": ["📚"], "palette": ["#4f46e5", "#0ea5e9", "#a855f7"]}

    def logo(self, hex_):
        return {"name": "X", "img": None, "mask": "data:image/svg+xml;base64,AAAA", "hex": hex_}

    def test_background_takes_the_brand_color(self):
        page = cover.html(self.DECOR, 1, [self.logo("#D97757")])
        self.assertIn("#d97757", page.lower())
        self.assertNotIn("#4f46e5", page)
        self.assertEqual(page.count('class="tile"'), 1)
        self.assertIn("mask:url(data:image/svg+xml;base64,AAAA)", page)

    def test_black_brand_gets_a_dark_background_and_light_brand_dark_ink(self):
        self.assertIn("#0d0d12", cover.html(self.DECOR, 1, [self.logo("#000000")]))
        self.assertIn("background:#111318", cover.html(self.DECOR, 1, [self.logo("#FFD21E")]))
        self.assertIn("background:#ffffff", cover.html(self.DECOR, 1, [self.logo("#D97757")]))

    def test_user_logo_keeps_its_colors_and_uses_the_theme(self):
        page = cover.html(self.DECOR, 1, [{"name": "X", "img": "data:image/png;base64,AAAA", "mask": None, "hex": None}])
        self.assertIn('<img class="mark" src="data:image/png;base64,AAAA">', page)
        self.assertIn("#4f46e5", page)

    def test_two_brands_two_tiles_and_no_brand_is_unchanged(self):
        self.assertEqual(cover.html(self.DECOR, 1, [self.logo("#112233")] * 2).count('class="tile"'), 2)
        self.assertNotIn('class="tile"', cover.html(self.DECOR, 1))

    def test_no_edge_returns_none(self):
        with mock.patch.object(cover, "edge", return_value=None):
            self.assertIsNone(cover.render(self.DECOR, 1, [self.logo("#112233")]))


class Pages(unittest.TestCase):
    def setUp(self):
        install()

    def tearDown(self):
        shutil.rmtree(brands.folder(), ignore_errors=True)

    def test_lesson_banner_goes_first_and_only_with_a_brand(self):
        from tests.test_llm import GOOD
        from tests.test_notion import META
        lesson, meta = llm.validate(GOOD, 75), META
        _, plain = notion.build_page(lesson, meta)
        _, banner = notion.build_page(lesson, {**meta, "banner_upload": "up-1"})
        self.assertEqual(len(banner), len(plain) + 1)
        self.assertEqual(banner[0]["image"]["file_upload"]["id"], "up-1")
        self.assertNotEqual(plain[0]["type"], "image")

    def test_banner_made_from_the_title_and_the_talk(self):
        cfg = {"brand_cover": True}
        with mock.patch.object(jobs.cover, "render", return_value=b"png") as render, \
                mock.patch.object(jobs, "_send", return_value="up-9") as send:
            self.assertEqual(jobs._banner("tok", cfg, "Curso | Claude Code em 14 minutos", ["fala"]), "up-9")
            self.assertEqual(render.call_args.kwargs["brands"][0]["name"], "Claude Code")
            send.assert_called_once()
            self.assertIsNone(jobs._banner("tok", cfg, "Aula | Sem marca", ["nada"]))
            self.assertIsNone(jobs._banner("tok", {"brand_cover": False}, "Claude", ["Claude"] * 9))
        with mock.patch.object(jobs.cover, "render", return_value=None):  # sem Edge: a página sai sem banner
            self.assertIsNone(jobs._banner("tok", cfg, "Claude", []))

    def test_cover_for_a_new_page_uses_the_logo_and_can_be_turned_off(self):
        cfg = {"brand_cover": True}
        self.assertEqual(names(brands.find("Curso de Claude")), ["Claude"])
        logos = server._logos("Curso de Claude", cfg)
        self.assertEqual([x["name"] for x in logos], ["Claude"])
        self.assertEqual(server._logos("Curso de Claude", cfg, off=True), [])
        self.assertEqual(server._logos("Curso de Claude", {"brand_cover": False}), [])
        with mock.patch.object(server.cover, "render", return_value=b"png") as render:
            self.assertEqual(server._cover_png({}, "t", 1, logos), (b"png", "marca"))
            self.assertEqual(render.call_args.kwargs["brands"], logos)

    def test_setting_is_saved_and_defaults_on(self):
        self.assertTrue(store.DEFAULTS["brand_cover"])
        cfg = server._apply_settings({"brand_cover": False})
        self.assertFalse(cfg["brand_cover"])
        self.assertTrue(server._apply_settings({"brand_cover": True})["brand_cover"])
        store.save_config(store.DEFAULTS)


if __name__ == "__main__":
    unittest.main()
