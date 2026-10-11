"""Capa desenhada para o tema da página (paleta e emojis escolhidos pela IA), renderizada localmente.

Usa o Microsoft Edge em modo headless (já vem no Windows) para transformar um HTML em PNG 1500×600.
Sem Edge, devolve None e o app usa uma capa do próprio Notion.
"""
import os
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

W, H = 1500, 600


def edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        exe = Path(base or "") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if base and exe.is_file():
            return exe
    return shutil.which("msedge") or shutil.which("microsoft-edge")


def _mix(hex_a, hex_b, t):
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _lum(hex_):
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return .2126 * r + .7152 * g + .0722 * b


def _brand_palette(brands, palette):
    """Cores da capa a partir da cor oficial da marca: preta vira um fundo escuro elegante; sem cor (logo do
    usuário) ou quase branca, a do tema."""
    base = next((b["hex"] for b in brands if b.get("hex") and _lum(b["hex"]) < .85), None)
    if not base:
        return list(palette)
    if _lum(base) < .06:
        return ["#3a3a46", "#0d0d12", "#4b4b5c"]
    return [base, _mix(base, "#0b0b14", .28), _mix(base, "#ffffff", .3)]


def _tiles(brands):
    """Um cartão de vidro por logo, no centro (o Notion corta as bordas da capa). A logo de um traço só (mask)
    ganha a cor que contrasta com o fundo; a do usuário (img) vai com as próprias cores. SVG vai como imagem, nunca
    em linha: não executa nada."""
    n = len(brands)
    size = 300 if n == 1 else 250
    out = []
    for i, b in enumerate(brands):
        x = 50 if n == 1 else (36, 64)[i]
        ink = "#111318" if b.get("hex") and _lum(b["hex"]) > .6 else "#ffffff"
        inner = (f'<i class="mark" style="background:{ink};-webkit-mask:url({b["mask"]}) center/contain no-repeat"></i>'
                 if b.get("mask") else f'<img class="mark" src="{b["img"]}">')
        out.append(f'<div class="tile" style="left:{x}%;width:{size}px;height:{size}px;border-radius:{size // 4}px">{inner}</div>')
    return "".join(out)


def html(decor, seed=0, brands=None):
    """HTML da capa. Todos os valores vêm validados por llm.decorate (cores #rrggbb, emojis sem ASCII).

    brands: logos (ver brands.logo) no centro, sobre um fundo na cor oficial da marca."""
    rnd = random.Random(seed)
    c1, c2, c3 = _brand_palette(brands, decor["palette"]) if brands else decor["palette"]
    deep = _mix(c1, "#0b0b14", 0.2)
    motifs = decor["motifs"] or [decor["emoji"]]
    blobs = "".join(
        f'<i class="blob" style="left:{rnd.randint(-10, 85)}%;top:{rnd.randint(-40, 60)}%;width:{rnd.randint(380, 620)}px;'
        f'height:{rnd.randint(380, 620)}px;background:{c};opacity:{rnd.uniform(.45, .7):.2f}"></i>'
        for c in (c1, c2, c3, c2))
    # emoji principal à direita, secundários em volta (posições que ficam visíveis mesmo com o corte do Notion)
    spots = [] if brands else [(70, 50, 230, 0, 1.0, 0)]
    edge = [(10, 28), (91, 30), (8, 74), (92, 72), (22, 50)]  # com logo no centro, os emojis ficam nas bordas
    for k, (x, y) in enumerate((edge if brands else [(52, 34), (86, 26), (88, 74), (56, 70), (38, 52)])[:len(motifs)]):
        spots.append((x + rnd.uniform(-3, 3), y + rnd.uniform(-5, 5), rnd.randint(70, 100) if brands else rnd.randint(86, 128),
                      rnd.randint(-16, 16), rnd.uniform(.7, .85) if brands else rnd.uniform(.82, .95), 0))
    far = [(rnd.uniform(5, 45), rnd.uniform(15, 85), rnd.randint(54, 80), rnd.randint(-25, 25), .32, 3) for _ in range(5)]
    chips = []
    for i, (x, y, size, rot, op, blur) in enumerate(spots + far):
        e = decor["emoji"] if i == 0 and not brands else motifs[(i - (0 if brands else 1)) % len(motifs)]
        chips.append(f'<span class="e" style="left:{x:.1f}%;top:{y:.1f}%;font-size:{size}px;'
                     f'transform:translate(-50%,-50%) rotate({rot}deg);opacity:{op:.2f};filter:blur({blur}px) '
                     f'drop-shadow(0 {size // 14}px {size // 6}px rgba(0,0,0,.28))">{e}</span>')
    return f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden}}
body{{position:relative;background:linear-gradient(120deg,{deep} 0%,{c2} 55%,{_mix(c3, '#0b0b14', .15)} 100%)}}
.blob{{position:absolute;border-radius:50%;filter:blur(90px)}}
.glass{{position:absolute;inset:0;background:radial-gradient(120% 90% at 20% 0%,rgba(255,255,255,.25),transparent 55%),
  radial-gradient(90% 80% at 100% 100%,rgba(0,0,0,.18),transparent 60%)}}
.e{{position:absolute;line-height:1;font-family:"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif}}
svg{{position:absolute;inset:0;opacity:.06;mix-blend-mode:overlay}}
.tile{{position:absolute;top:50%;transform:translate(-50%,-50%);background:linear-gradient(145deg,rgba(255,255,255,.3),rgba(255,255,255,.08));
  border:1.5px solid rgba(255,255,255,.38);box-shadow:0 30px 80px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.55);
  backdrop-filter:blur(26px)}}
.mark{{position:absolute;inset:26%;display:block;width:48%;height:48%;object-fit:contain;filter:drop-shadow(0 6px 14px rgba(0,0,0,.25))}}
</style><body>{blobs}<div class="glass"></div>{''.join(chips)}{_tiles(brands) if brands else ""}
<svg width="{W}" height="{H}"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2"/></filter>
<rect width="100%" height="100%" filter="url(#n)"/></svg></body>"""


def render(decor, seed=0, brands=None):
    """PNG da capa (bytes) ou None se não houver Edge disponível / falhar."""
    exe = edge()
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="lumen-capa-") as tmp:
        page, out = Path(tmp) / "capa.html", Path(tmp) / "capa.png"
        page.write_text(html(decor, seed, brands), "utf-8")
        try:
            subprocess.run([str(exe), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={Path(tmp) / 'perfil'}", f"--window-size={W},{H}",
                            "--default-background-color=00000000", f"--screenshot={out}", page.as_uri()],
                           capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        return out.read_bytes() if out.exists() and out.stat().st_size > 1000 else None
