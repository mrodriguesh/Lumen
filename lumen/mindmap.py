"""Mapa mental da aula: estrutura vinda da IA (llm.generate) desenhada localmente como PNG em alta resolução.

Mesmo caminho da capa (cover.py): HTML → Microsoft Edge headless → screenshot. O navegador faz a quebra de texto
e um script mede as caixas, liga tudo com curvas e encolhe o mapa para caber na imagem. Sem Edge → None, e a
página recebe o mapa em tópicos aninhados.
"""
import html as _html
import json
import subprocess
import tempfile
from pathlib import Path

from .cover import edge

COLORS = ["#f97316", "#3b82f6", "#22c55e", "#a855f7", "#ec4899", "#eab308", "#06b6d4", "#ef4444"]
W = 1800  # largura da página; a altura acompanha o tamanho do mapa


def _clip(v, n):
    v = " ".join(str(v or "").split())
    return v if len(v) <= n else v[:n - 1].rstrip(" ,.;:") + "…"


def data(lesson):
    """Mapa limpo a partir da aula. Aula antiga (sem mind_map) ou ramos insuficientes → tópicos principais."""
    from .llm import _emoji
    mm = lesson.get("mind_map") if isinstance(lesson.get("mind_map"), dict) else {}
    branches = []
    for b in mm.get("branches") or []:
        if isinstance(b, dict) and _clip(b.get("label"), 60):
            kids = [_clip(k, 90) for k in (b.get("children") or []) if isinstance(k, str) and _clip(k, 90)]
            branches.append({"label": _clip(b.get("label"), 60), "emoji": _emoji(b.get("emoji"), ""),
                             "children": list(dict.fromkeys(kids))[:5]})
    if len(branches) < 2:
        branches = [{"label": _clip(t["title"], 60), "emoji": "", "children": []} for t in lesson.get("topics", [])]
    return {"center": _clip(mm.get("center") or lesson.get("title"), 70), "branches": branches[:8]}


def html(m):
    e = _html.escape
    n = len(m["branches"])
    groups = [(b, COLORS[i % len(COLORS)]) for i, b in enumerate(m["branches"])]
    right, left = groups[:(n + 1) // 2], groups[(n + 1) // 2:][::-1]  # sentido horário, como no papel

    def side(items, cls):
        out = []
        for b, c in items:
            kids = "".join(f'<div class="leaf">{e(k)}</div>' for k in b["children"])
            emo = f'<span class="emo">{e(b["emoji"])}</span>' if b["emoji"] else ""
            out.append(f'<div class="grp" style="--c:{c}"><div class="br">{emo}{e(b["label"])}</div>'
                       f'<div class="kids">{kids}</div></div>')
        return f'<div class="side {cls}">{"".join(out)}</div>'

    return f"""<!doctype html><meta charset="utf-8"><style>
*{{box-sizing:border-box}}
html,body{{margin:0;width:100%;height:100%;overflow:hidden}}
body{{background:radial-gradient(1200px 800px at 50% 45%,#1c2140 0%,#0d1022 60%,#080a16 100%);
  font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;color:#e8ebf7}}
#map{{position:absolute;left:50%;top:50%;width:max-content;transform:translate(-50%,-50%);display:flex;align-items:center;gap:96px;
  padding:24px}}
svg{{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}}
.side{{display:flex;flex-direction:column;gap:26px;position:relative;z-index:1}}
.grp{{display:flex;align-items:center;gap:56px}}
.left .grp{{flex-direction:row-reverse}}
.kids{{display:flex;flex-direction:column;gap:10px}}
.left .kids{{align-items:flex-end}}
.center{{position:relative;z-index:1;max-width:320px;padding:26px 34px;border-radius:28px;text-align:center;
  font:700 31px/1.2 "Segoe UI Variable Display","Segoe UI",sans-serif;color:#fff;
  background:linear-gradient(135deg,#6366f1,#8b5cf6 55%,#d946ef);
  box-shadow:0 0 0 6px rgba(139,92,246,.18),0 18px 60px rgba(124,58,237,.45)}}
.br{{max-width:250px;padding:13px 18px;border-radius:16px;background:var(--c);color:#fff;
  font:650 20px/1.25 "Segoe UI Variable Display","Segoe UI",sans-serif;
  box-shadow:0 10px 28px color-mix(in srgb,var(--c) 45%,transparent);text-shadow:0 1px 2px rgba(0,0,0,.25)}}
.emo{{margin-right:8px;font-family:"Segoe UI Emoji",sans-serif}}
.leaf{{max-width:310px;padding:8px 14px;border-radius:11px;font-size:16.5px;line-height:1.35;
  background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.08);border-left:3px solid var(--c)}}
.left .leaf{{border-left:1px solid rgba(255,255,255,.08);border-right:3px solid var(--c);text-align:right}}
.mark{{position:absolute;right:22px;bottom:16px;font-size:14px;color:rgba(232,235,247,.35)}}
</style><body><div id="map">{side(left, "left")}<div class="center">{e(m["center"])}</div>{side(right, "right")}</div>
<div class="mark">Mapa mental · Lumen</div>
<script>
const map=document.getElementById("map"),R=map.getBoundingClientRect(),NS="http://www.w3.org/2000/svg";
const svg=document.createElementNS(NS,"svg");svg.setAttribute("width",R.width);svg.setAttribute("height",R.height);
const box=el=>{{const r=el.getBoundingClientRect();return{{l:r.left-R.left,r:r.right-R.left,y:r.top-R.top+r.height/2}}}};
function curve(a,b,c,w,o){{const p=document.createElementNS(NS,"path"),m=(a[0]+b[0])/2;
  p.setAttribute("d",`M${{a[0]}} ${{a[1]}} C${{m}} ${{a[1]}},${{m}} ${{b[1]}},${{b[0]}} ${{b[1]}}`);
  p.setAttribute("fill","none");p.setAttribute("stroke",c);p.setAttribute("stroke-width",w);
  p.setAttribute("stroke-linecap","round");p.setAttribute("opacity",o);svg.appendChild(p)}}
const ce=box(document.querySelector(".center"));
document.querySelectorAll(".grp").forEach(g=>{{
  const L=g.closest(".left"),c=getComputedStyle(g).getPropertyValue("--c").trim(),b=box(g.querySelector(".br"));
  curve([L?ce.l+6:ce.r-6,ce.y],[L?b.r:b.l,b.y],c,5,.95);
  g.querySelectorAll(".leaf").forEach(k=>{{const q=box(k);curve([L?b.l:b.r,b.y],[L?q.r:q.l,q.y],c,2.5,.75)}});
}});
map.prepend(svg);
const s=Math.min(1,(innerWidth-60)/R.width,(innerHeight-70)/R.height);
map.style.transform=`translate(-50%,-50%) scale(${{s}})`;
</script></body>"""


def height(m):
    """Altura estimada da imagem: a coluna mais cheia manda (o script ainda encolhe o mapa se precisar)."""
    n = len(m["branches"])
    rows = lambda bs: sum(max(1, len(b["children"])) * 52 + 26 for b in bs)
    return max(560, 140 + max(rows(m["branches"][:(n + 1) // 2]), rows(m["branches"][(n + 1) // 2:])))


def render(m):
    """PNG (2× para ficar nítido ao ampliar no Notion) ou None sem Edge / em caso de falha."""
    exe = edge()
    if not exe or not m["branches"]:
        return None
    with tempfile.TemporaryDirectory(prefix="lumen-mapa-", ignore_cleanup_errors=True) as tmp:
        page, out = Path(tmp) / "mapa.html", Path(tmp) / "mapa.png"
        page.write_text(html(m), "utf-8")
        try:
            subprocess.run([str(exe), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--force-device-scale-factor=2", f"--user-data-dir={Path(tmp) / 'perfil'}",
                            f"--window-size={W},{height(m)}", f"--screenshot={out}", page.as_uri()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=40, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        return out.read_bytes() if out.exists() and out.stat().st_size > 5000 else None


if __name__ == "__main__":  # python -m lumen.mindmap aula.json saida.png — prévia rápida
    import sys
    d = data(json.loads(Path(sys.argv[1]).read_text("utf-8")))
    Path(sys.argv[2]).write_bytes(render(d) or b"")
