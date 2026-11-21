"""Design system (lumen/web/ui.css): contraste dos tokens de texto e nenhuma cor solta fora deles."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "lumen" / "web"


def tokens():
    root = re.search(r":root\s*\{(.*?)\n\}", (WEB / "ui.css").read_text("utf-8"), re.S).group(1)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", root))


def luminance(hex_color):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return .2126 * channel(r) + .7152 * channel(g) + .0722 * channel(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + .05) / (lo + .05)


class Tokens(unittest.TestCase):
    def setUp(self):
        self.t = tokens()
        self.surfaces = [self.t[k] for k in ("bg-base", "bg-elevated", "surface-1", "surface-2", "surface-3")]

    def test_text_is_readable_on_every_surface(self):
        # WCAG AA para texto normal (4,5:1), inclusive o terciário, o cinza que o vidro costuma apagar
        for name in ("text-primary", "text-secondary", "text-tertiary", "accent-text",
                     "success-text", "warning-text", "danger-text", "rec-text"):
            for bg in self.surfaces:
                self.assertGreaterEqual(contrast(self.t[name], bg), 4.5, f"--{name} sobre {bg}")

    def test_focus_ring_and_status_marks_stand_out(self):
        # elementos gráficos (anel de foco, ponto de status): 3:1
        for name in ("border-focus", "accent-strong", "success", "warning", "danger-dot", "rec", "obsidian"):
            for bg in self.surfaces:
                self.assertGreaterEqual(contrast(self.t[name], bg), 3, f"--{name} sobre {bg}")

    def test_white_label_on_primary_and_danger_buttons(self):
        self.assertGreaterEqual(contrast("#ffffff", self.t["accent"]), 4.5)
        self.assertGreaterEqual(contrast("#ffffff", self.t["danger"]), 4.5)

    def test_selected_pill_text(self):
        self.assertGreaterEqual(contrast(self.t["text-inverse"], "#e4e7ee"), 4.5)

    def test_no_loose_hex_colors_outside_the_tokens(self):
        # app.css e widget.css usam só var(--…); as cores moram em ui.css (os data: URI de ícone não contam)
        for name in ("app.css", "widget.css", "chat.css"):
            css = re.sub(r"url\([^)]*\)", "", (WEB / name).read_text("utf-8"))
            self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", css), [], name)

    def test_type_sizes_come_from_the_scale(self):
        # tamanho de fonte só pela escala de ui.css (--fs-*): nada de 13px, 17px ou 22px espalhados
        for name in ("app.css", "widget.css", "chat.css"):
            css = (WEB / name).read_text("utf-8")
            self.assertEqual(re.findall(r"font(?:-size)?:\s*[0-9.]+px", css), [], name)

    def test_selection_and_scrollbar_follow_the_tokens(self):
        # a seleção e a barra de rolagem usam os tokens (nada de azul fixo)
        css = (WEB / "ui.css").read_text("utf-8")
        self.assertIn("background: var(--selection)", css)
        self.assertIn("background: var(--scroll-thumb)", css)
        self.assertNotRegex(css, r"::selection\s*\{[^}]*rgba")


class Alignment(unittest.TestCase):
    """Texto curto e independente é centralizado por um token; quem escreve ou lê em coluna fica no início (docs/DESIGN.md)."""

    def setUp(self):
        self.css = {f: (WEB / f).read_text("utf-8") for f in ("ui.css", "app.css", "glass.css", "study.css", "widget.css", "chat.css", "protection.css")}

    def test_tokens_and_the_shared_rule_exist(self):
        root = re.search(r":root\s*\{(.*?)\n\}", self.css["ui.css"], re.S).group(1)
        self.assertRegex(root, r"--ta-short:\s*center;")
        self.assertRegex(root, r"--jc-short:\s*center;")
        rule = re.search(r"\n(\.t-center,[^{]*)\{([^}]*)\}", self.css["ui.css"])
        self.assertIsNotNone(rule, "a regra central com .t-center sumiu do ui.css")
        for sel in (".t-center", ".card-note", ".st-empty-small", ".protection-footnote", ".g-ev-note", ".pomo-msg", ".prefs-label"):
            self.assertIn(sel, [s.strip() for s in rule.group(1).split(",")])
        self.assertIn("text-align: var(--ta-short)", rule.group(2))
        self.assertIn("text-wrap: balance", rule.group(2))

    def test_glass_centres_the_working_hero_by_the_tokens_and_keeps_the_illustrated_one_at_the_start(self):
        g = self.css["glass.css"]
        self.assertRegex(g, r"\.hero-card:not\(:has\(> \.g-hero\)\) \{ text-align: var\(--ta-short\); align-items: var\(--jc-short\); \}")
        self.assertRegex(g, r"& \.hero-card :is\(\.hero-top, \.hero-title, \.hero-time, \.hero-sub, \.hero-actions\) \{ text-align: left;")
        # a barra de progresso do cartão não tem largura própria: sem isto some quando a coluna centraliza (valia para o Clássico desde antes)
        self.assertRegex(self.css["app.css"], r"\n\.hero-progress \{ align-self: stretch; \}")
        self.assertRegex(self.css["app.css"], r"\.hero-title \{\s*text-align: var\(--ta-short\);")

    def test_what_the_user_writes_or_reads_in_a_column_is_never_centred(self):
        for name, css in self.css.items():
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if re.search(r"text-align:\s*(center|var\(--ta-short\))", body):
                    for s in sel.split(","):
                        # o campo vazio do Cérebro (.st-composer textarea) é centralizado de propósito: campo curto no meio da tela
                        self.assertNotRegex(s, r"\.writing\b|#u-text|#mine-text|\.set-text\b|\.lib-title\b|\.segments\b|\bpre\b|\bcode\b|\btd\b", f"{name}: {s.strip()} não pode ser centralizado")

    def test_centring_is_never_forced_or_inlined(self):
        for name, css in self.css.items():
            self.assertNotRegex(css, r"text-align:\s*center\s*!important", name)
        for f in ("index.html", "widget.html", "note.html", "app.js", "widget.js", "note.js", "glass.js", "study.js"):
            self.assertNotRegex((WEB / f).read_text("utf-8"), r"text-align\s*:|textAlign\s*=", f"{f}: alinhamento em linha (a CSP barra e foge do token)")


if __name__ == "__main__":
    unittest.main()
