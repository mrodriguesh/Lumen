"""Estilo da interface Lúmen Glass 2026 (Ajustes → Aparência): preferência, entrega sem piscar e as regras de glass.css.

O que se garante aqui (o resto — telas, troca sem recarregar, Clássico idêntico — está em tests/glass_ui.py):
  - a escolha é só `ui_style` no config.json de sempre (classic | glass; ausente = classic) e nada além disso é aceito;
  - o servidor marca <html data-ui=…> antes do primeiro quadro, só com valor fixo;
  - glass.css não vaza para o Clássico: TODA regra está sob :root[data-ui="glass"];
  - cores só na paleta, tamanhos de fonte só pela escala, movimento dentro das regras da casa;
  - a paleta Glass passa nos mesmos contrastes que o padrão (WCAG 2: texto 4,5:1, marcas 3:1).
"""
import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen)
from lumen import AppError, server, store
from tests.test_ui_tokens import contrast, tokens as default_tokens

WEB = Path(__file__).resolve().parent.parent / "lumen" / "web"
CSS = (WEB / "glass.css").read_text("utf-8")
SCOPE = ':root[data-ui="glass"]'


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def top_level_blocks(css):
    """(prelúdio, corpo) de cada bloco de primeiro nível (respeita chaves aninhadas)."""
    out, depth, start, head = [], 0, 0, 0
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                head, start = css[head:i].strip(), i + 1
                prelude = head
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append((prelude, css[start:i]))
                head = i + 1
    return out


def palette():
    block = re.search(r':root\[data-ui="glass"\]\s*\{(.*?)\}', CSS, re.S).group(1)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", block))


class Preference(unittest.TestCase):
    def setUp(self):
        (store.DATA / "config.json").unlink(missing_ok=True)

    def test_default_is_classic_and_old_configs_stay_classic(self):
        self.assertEqual(store.DEFAULTS["ui_style"], "classic")
        self.assertEqual(store.UI_STYLES, ("classic", "glass"))
        store.DATA.mkdir(parents=True, exist_ok=True)
        (store.DATA / "config.json").write_text(json.dumps({"quality": "rapido"}), "utf-8")  # um config.json de antes da tarefa
        self.assertEqual(store.load_config()["ui_style"], "classic")

    def test_settings_accept_only_the_two_styles_and_keep_everything_else(self):
        before = store.load_config()
        self.assertEqual(server._apply_settings({"ui_style": "glass"})["ui_style"], "glass")
        self.assertEqual(store.load_config()["ui_style"], "glass")
        for bad in ("Glass", "liquid", "", None, 1, ["glass"], "glass;", "../glass"):
            with self.assertRaises(AppError, msg=repr(bad)):
                server._apply_settings({"ui_style": bad})
        self.assertEqual(store.load_config()["ui_style"], "glass")  # recusado: nada muda
        after = store.load_config()
        self.assertEqual({k: v for k, v in after.items() if k != "ui_style"}, {k: v for k, v in before.items() if k != "ui_style"})
        self.assertEqual(server._apply_settings({"ui_style": "classic"})["ui_style"], "classic")

    def test_other_settings_do_not_touch_the_style(self):
        server._apply_settings({"ui_style": "glass"})
        server._apply_settings({"page_language": "original"})
        self.assertEqual(store.load_config()["ui_style"], "glass")


class PageMarks(unittest.TestCase):
    PAGE = b'<html lang="pt-BR" data-ui="{{UI_STYLE}}"><meta name="lumen-token" content="x">'

    def setUp(self):
        (store.DATA / "config.json").unlink(missing_ok=True)

    def test_marks_follow_the_config_with_fixed_values_only(self):
        body, etag = server._page_marks(self.PAGE)
        self.assertIn(b'data-ui="classic"', body)
        server._apply_settings({"ui_style": "glass"})
        body2, etag2 = server._page_marks(self.PAGE)
        self.assertIn(b'data-ui="glass"', body2)
        self.assertNotEqual(etag, etag2)  # a página muda de versão: o navegador não reaproveita a do outro estilo

    def test_unknown_value_in_the_file_falls_back_to_classic(self):
        store.DATA.mkdir(parents=True, exist_ok=True)
        (store.DATA / "config.json").write_text(json.dumps({"ui_style": '"><script>x</script>'}), "utf-8")
        body, _ = server._page_marks(self.PAGE)
        self.assertIn(b'data-ui="classic"', body)
        self.assertNotIn(b"<script>", body)

    def test_index_has_the_marks_and_loads_glass_last(self):
        html = (WEB / "index.html").read_text("utf-8")
        self.assertIn('<html lang="pt-BR" data-ui="{{UI_STYLE}}">', html)
        head = html.split("</head>")[0]
        self.assertGreater(head.index('href="/glass.css"'), head.index('href="/study.css"'))   # por último: sobrepõe sem !important
        self.assertGreater(head.index('src="/glass.js"'), head.index('src="/app.js"'))         # depois do app.js (usa as funções dele)
        for path in ("/glass.css", "/glass.js"):
            self.assertIn(path, server.STATIC)
            self.assertTrue((WEB / server.STATIC[path][0]).is_file())


    def test_bar_and_note_carry_the_style_mark_too(self):
        for name in ("widget.html", "note.html"):
            html = (WEB / name).read_text("utf-8")
            self.assertIn('<html lang="pt-BR" data-ui="{{UI_STYLE}}">', html, name)
            server._apply_settings({"ui_style": "glass"})
            self.assertIn(b'<html lang="pt-BR" data-ui="glass">', server._page_marks(html.encode("utf-8"))[0], name)
            server._apply_settings({"ui_style": "classic"})
            self.assertIn(b'<html lang="pt-BR" data-ui="classic">', server._page_marks(html.encode("utf-8"))[0], name)
        # a barra e a nota acompanham a troca pela leitura que já fazem (o mesmo caminho do tema)
        for name in ("widget.js", "note.js"):
            self.assertIn('document.documentElement.dataset.ui = d.ui', (WEB / name).read_text("utf-8"), name)

    def test_bar_glass_rules_are_scoped(self):
        """No widget.css, o que é do Glass começa em :root[data-ui="glass"]: no Clássico a barra não muda."""
        css = (WEB / "widget.css").read_text("utf-8")
        block = css.split("Lúmen Glass 2026", 1)[1].split("/* Minha compreensão na barra lateral", 1)[0]
        rules = [r.strip() for r in re.findall(r"(?m)^([^{}/\s][^{}]*)\{", block)]
        self.assertGreaterEqual(len(rules), 6)
        for sel in rules:
            self.assertTrue(sel.startswith(':root[data-ui="glass"]'), sel)


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, body=None, headers=None):
        r = urllib.request.Request(self.url + path, headers={"X-Lumen-Token": server.TOKEN, **(headers or {})})
        if body is not None:
            r.data = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def test_switching_style_changes_the_page_and_its_etag(self):
        self.req("/api/settings?view=settings", {"ui_style": "classic"})
        s1, page1, h1 = self.req("/")
        self.assertIn(b'data-ui="classic"', page1)
        status, body, _ = self.req("/api/settings?view=settings", {"ui_style": "glass"})
        self.assertEqual((status, json.loads(body)["config"]["ui_style"]), (200, "glass"))
        s2, page2, h2 = self.req("/", headers={"If-None-Match": h1["ETag"]})
        self.assertEqual(s2, 200)  # o ETag de antes não serve mais
        self.assertIn(b'data-ui="glass"', page2)
        s3, _, _ = self.req("/", headers={"If-None-Match": h2["ETag"]})
        self.assertEqual(s3, 304)
        status, body, _ = self.req("/api/settings?view=settings", {"ui_style": "neon"})
        self.assertEqual(status, 400)
        self.assertIn("Estilo da interface", json.loads(body)["error"]["message"])
        self.req("/api/settings?view=settings", {"ui_style": "classic"})

    def test_glass_files_are_served_with_the_static_policy(self):
        for path, ctype in (("/glass.css", "text/css"), ("/glass.js", "text/javascript")):
            status, body, headers = self.req(path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(ctype))
            self.assertIn("style-src 'self'", headers["Content-Security-Policy"])


class GlassCss(unittest.TestCase):
    def test_every_rule_is_scoped_to_the_glass_style(self):
        css = strip_comments(CSS)
        for prelude, body in top_level_blocks(css):
            if prelude.startswith("@keyframes"):
                continue
            if prelude.startswith("@media"):
                for inner, _ in top_level_blocks(body):
                    self.assertTrue(inner.startswith(SCOPE), f"regra sem o escopo Glass dentro de {prelude}: {inner[:80]}")
                continue
            self.assertTrue(prelude.startswith(SCOPE), f"regra sem o escopo Glass: {prelude[:80]}")

    def test_colors_live_only_in_the_palette(self):
        css = strip_comments(re.sub(r"url\([^)]*\)", "", CSS))
        pal = re.search(r':root\[data-ui="glass"\]\s*\{.*?\}', css, re.S).group(0)
        rest = css.replace(pal, "")
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", rest), [])
        self.assertGreaterEqual(len(palette()), 12)

    def test_font_sizes_come_from_the_scale(self):
        css = strip_comments(CSS)
        self.assertEqual(re.findall(r"(?<!-)font(?:-size)?:\s*[0-9.]+px", css), [])

    def test_motion_follows_the_house_rules(self):
        css = strip_comments(CSS)
        self.assertNotRegex(css, r"transition:\s*all\b")
        self.assertNotRegex(css, r"scale\(0\)")
        self.assertNotRegex(css, r"\bease-in\b(?!-out)")
        for name, dur in re.findall(r"animation:\s*([\w-]+)\s+([0-9.]+m?s)", css):  # animações curtas, salvo o aviso de fim do Pomodoro
            ms = float(dur[:-2]) if dur.endswith("ms") else float(dur[:-1]) * 1000
            self.assertTrue(ms <= 300 or name == "g-pomo-ended", f"{name} {dur}")
        self.assertNotRegex(css, r"animation:[^;]*infinite")  # nada infinito no Glass
        for blur in re.findall(r"blur\(([0-9.]+)px\)", css):
            self.assertLessEqual(float(blur), 20)

    def test_backdrop_filter_only_on_small_floating_surfaces(self):
        css = strip_comments(CSS)
        for m in re.finditer(r"([^{};]+)\{[^{}]*backdrop-filter:\s*blur", css):
            sel = m.group(1)
            self.assertNotRegex(sel, r"\.card\b|\.content\b|\.rail\b|\.view\b|\.action-bar|body", sel.strip()[:90])

    def test_reduced_motion_transparency_and_contrast_variants_exist(self):
        for q in ("prefers-reduced-motion: reduce", "prefers-reduced-transparency: reduce", "prefers-contrast: more"):
            self.assertIn(q, CSS)

    def test_glass_palette_is_readable(self):
        t = {**default_tokens(), **palette()}
        surfaces = [t[k] for k in ("bg-base", "bg-elevated", "surface-1", "surface-2", "surface-3")]
        for name in ("text-primary", "text-secondary", "text-tertiary", "accent-text", "success-text", "warning-text", "danger-text", "rec-text"):
            for bg in surfaces:
                self.assertGreaterEqual(contrast(t[name], bg), 4.5, f"--{name} sobre {bg}")
        for name in ("border-focus", "accent-strong", "success", "warning", "danger-dot", "rec", "obsidian"):
            for bg in surfaces:
                self.assertGreaterEqual(contrast(t[name], bg), 3, f"--{name} sobre {bg}")
        self.assertGreaterEqual(contrast("#ffffff", t["accent"]), 4.5)
        self.assertGreaterEqual(contrast("#ffffff", t["accent-grad-to"]), 4.5)

    def test_classic_hides_the_glass_only_pieces(self):
        app = (WEB / "app.css").read_text("utf-8")
        self.assertIn(':root:not([data-ui="glass"]) :is(.g-only, .pomo-ico, .pomo-total, .pomo-stop, .pomo-expand) { display: none !important; }', app)
        self.assertIn(".c-only { display: none !important; }", CSS)

    def test_glass_script_has_no_colors_and_only_static_markup(self):
        js = (WEB / "glass.js").read_text("utf-8")
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", js), [])
        for m in re.finditer(r"(innerHTML\s*=|insertAdjacentHTML\()([^;]*)", js):
            self.assertNotRegex(m.group(2), r"\$\{|\+\s*[a-zA-Z_]", "HTML montado com dado: use el()/textContent")

    def test_ai_settings_hooks_exist_on_both_sides(self):
        """As Configurações da IA chamam o Glass por ganchos opcionais (window.Glass?.x): cada um existe no glass.js e é exportado."""
        js = (WEB / "glass.js").read_text("utf-8")
        settings = (WEB / "study-settings.js").read_text("utf-8")
        exported = re.search(r"window\.Glass = \{([^}]*)\}", js).group(1)
        for hook in ("aiSection", "activity", "evaluation", "pdf", "personal"):
            self.assertIn(f"window.Glass?.{hook}(", settings)
            self.assertRegex(js, rf"function {hook}\(")
            self.assertIn(hook, [x.strip() for x in exported.split(",")])

    def test_new_glass_pieces_are_glass_only_and_never_inline_styled(self):
        """Peça criada pelo glass.js para as Configurações da IA é .g-only (o Clássico esconde) e não usa estilo em linha (CSP)."""
        js = (WEB / "glass.js").read_text("utf-8")
        for cls in ("g-tl", "g-ev-back", "g-ev-count", "g-ev-empty", "g-ev-trail", "g-ev-note", "g-sp-back", "g-sp-head", "g-sp-cmds", "g-sp-facts"):
            self.assertRegex(js, rf'class: "{cls} g-only"', cls)
        self.assertNotRegex(js, r"\.style\.|setAttribute\(\"style\"|(?<![A-Za-z])style: \"")

    def test_icons_used_by_the_glass_script_exist(self):
        js = (WEB / "glass.js").read_text("utf-8")
        have = set(re.findall(r'<symbol id="([a-z0-9-]+)"', (WEB / "icons.svg").read_text("utf-8")))
        used = set(re.findall(r'icon\("([a-z0-9-]+)"', js)) | set(re.findall(r'(?:: |\[)"([a-z][a-z0-9-]*)"(?=[,\]}] ?)', "\n".join(
            re.findall(r"const (?:ACT_ICO|SKILL_ICO|CARD_ICO|ROW_ICO) = \{(.*?)\};", js, re.S))))
        self.assertTrue({"thumb", "bars"} <= have)
        self.assertEqual(sorted(used - have), [])


if __name__ == "__main__":
    unittest.main()
