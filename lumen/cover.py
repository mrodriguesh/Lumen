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


def html(decor, seed=0):
    """HTML da capa. Todos os valores vêm validados por llm.decorate (cores #rrggbb, emojis sem ASCII)."""
    rnd = random.Random(seed)
    c1, c2, c3 = decor["palette"]
    deep = _mix(c1, "#0b0b14", 0.2)
    motifs = decor["motifs"] or [decor["emoji"]]
    blobs = "".join(
        f'<i class="blob" style="left:{rnd.randint(-10, 85)}%;top:{rnd.randint(-40, 60)}%;width:{rnd.randint(380, 620)}px;'
        f'height:{rnd.randint(380, 620)}px;background:{c};opacity:{rnd.uniform(.45, .7):.2f}"></i>'
        for c in (c1, c2, c3, c2))
    # emoji principal à direita, secundários em volta (posições que ficam visíveis mesmo com o corte do Notion)
    spots = [(70, 50, 230, 0, 1.0, 0)]
    for k, (x, y) in enumerate([(52, 34), (86, 26), (88, 74), (56, 70), (38, 52)][:len(motifs)]):
        spots.append((x + rnd.uniform(-3, 3), y + rnd.uniform(-5, 5), rnd.randint(86, 128), rnd.randint(-16, 16),
                      rnd.uniform(.82, .95), 0))
    far = [(rnd.uniform(5, 45), rnd.uniform(15, 85), rnd.randint(54, 80), rnd.randint(-25, 25), .32, 3) for _ in range(5)]
    chips = []
    for i, (x, y, size, rot, op, blur) in enumerate(spots + far):
        e = decor["emoji"] if i == 0 else motifs[(i - 1) % len(motifs)]
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
</style><body>{blobs}<div class="glass"></div>{''.join(chips)}
<svg width="{W}" height="{H}"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2"/></filter>
<rect width="100%" height="100%" filter="url(#n)"/></svg></body>"""


def render(decor, seed=0):
    """PNG da capa (bytes) ou None se não houver Edge disponível / falhar."""
    exe = edge()
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="lumen-capa-", ignore_cleanup_errors=True) as tmp:
        page, out = Path(tmp) / "capa.html", Path(tmp) / "capa.png"
        page.write_text(html(decor, seed), "utf-8")
        try:
            subprocess.run([str(exe), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={Path(tmp) / 'perfil'}", f"--window-size={W},{H}",
                            "--default-background-color=00000000", f"--screenshot={out}", page.as_uri()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        return out.read_bytes() if out.exists() and out.stat().st_size > 1000 else None
