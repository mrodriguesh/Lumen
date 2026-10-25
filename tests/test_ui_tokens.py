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
        for name in ("border-focus", "accent-strong", "success", "warning", "danger-dot", "rec"):
            for bg in self.surfaces:
                self.assertGreaterEqual(contrast(self.t[name], bg), 3, f"--{name} sobre {bg}")

    def test_white_label_on_primary_and_danger_buttons(self):
        self.assertGreaterEqual(contrast("#ffffff", self.t["accent"]), 4.5)
        self.assertGreaterEqual(contrast("#ffffff", self.t["danger"]), 4.5)

    def test_selected_pill_text(self):
        self.assertGreaterEqual(contrast(self.t["text-inverse"], "#e4e7ee"), 4.5)

    def test_no_loose_hex_colors_outside_the_tokens(self):
        # app.css e widget.css usam só var(--…); as cores moram em ui.css (os data: URI de ícone não contam)
        for name in ("app.css", "widget.css"):
            css = re.sub(r"url\([^)]*\)", "", (WEB / name).read_text("utf-8"))
            self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", css), [], name)

    def test_type_sizes_come_from_the_scale(self):
        # tamanho de fonte só pela escala de ui.css (--fs-*): nada de 13px, 17px ou 22px espalhados
        for name in ("app.css", "widget.css"):
            css = (WEB / name).read_text("utf-8")
            self.assertEqual(re.findall(r"font(?:-size)?:\s*[0-9.]+px", css), [], name)


if __name__ == "__main__":
    unittest.main()
