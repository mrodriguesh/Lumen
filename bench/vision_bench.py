"""“Assistir junto”: qual modelo de visão local lê a tela da aula com precisão, rápido e sem pegar o que não é aula.

    python -m bench.vision_bench make                 # desenha as telas de teste (Edge headless) em bench/.data/vision
    python -m bench.vision_bench run MODELO [LARGURA]  # roda um modelo do Ollama nas telas (LARGURA padrão 1280)
    python -m bench.vision_bench report               # tabela com todos os resultados

Telas sintéticas com gabarito: slides, tabela, código, diagrama, fórmula, quadro escrito à mão, slide com câmera do
professor, slide em inglês, e duas telas do YouTube no navegador (uma com aula, com recomendações e notificação
ao lado; outra com anúncio). Métricas:
- recall: fração das palavras do gabarito que aparecem no texto extraído (normalizado);
- ruído: textos que NÃO podiam aparecer (recomendações, notificação, comentários, anúncio);
- relevância: acertou se a tela é conteúdo da aula;
- área: IoU da região da aula apontada pelo modelo com a região real (telas do navegador).
"""
import base64
import json
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

from bench.asr_bench import DATA, RES

OUT = DATA / "vision"
W, H = 1920, 1080

CSS = """*{box-sizing:border-box}html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
body{font-family:"Segoe UI",sans-serif}
.slide{position:absolute;inset:0;padding:90px 120px;background:linear-gradient(160deg,#f8fafc,#e2e8f0);color:#0f172a}
.slide h1{font-size:64px;margin:0 0 40px;color:#1e3a8a}
.slide li{font-size:40px;margin:18px 0;line-height:1.3}
.foot{position:absolute;left:120px;right:120px;bottom:40px;display:flex;justify-content:space-between;font-size:24px;color:#64748b}
.box{display:inline-block;margin-top:30px;padding:24px 40px;border-radius:18px;background:#1e3a8a;color:#fff;font-size:44px}
table{border-collapse:collapse;font-size:36px;margin-top:10px}td,th{border:2px solid #94a3b8;padding:16px 34px;text-align:left}
th{background:#1e3a8a;color:#fff}
"""


def _slide(title, items, foot="", extra=""):
    lis = "".join(f"<li>{i}</li>" for i in items)
    return (f'<div class="slide"><h1>{title}</h1><ul>{lis}</ul>{extra}'
            f'<div class="foot"><span>{foot}</span><span>Prof. Lumen</span></div></div>')


def _person(x, y, s=1.0, bg="#334155"):
    return (f'<div style="position:absolute;left:{x}px;top:{y}px;width:{420 * s}px;height:{420 * s}px;border-radius:50%;'
            f'overflow:hidden;background:{bg};border:6px solid #fff;box-shadow:0 10px 30px rgba(0,0,0,.4)">'
            f'<div style="position:absolute;left:{135 * s}px;top:{70 * s}px;width:{150 * s}px;height:{170 * s}px;'
            f'border-radius:50%;background:#e0b48c"></div><div style="position:absolute;left:{60 * s}px;top:{250 * s}px;'
            f'width:{300 * s}px;height:{260 * s}px;border-radius:50% 50% 0 0;background:#2563eb"></div></div>')


def _browser(player_html, title, side, toast):
    """Tela inteira do Windows com o YouTube no navegador. Player em (24, 150)–(1304, 870) → caixa conhecida."""
    recs = "".join(f'<div style="display:flex;gap:14px;margin-bottom:18px"><div style="width:168px;height:94px;'
                   f'background:#{c};border-radius:8px"></div><div><b style="font-size:17px">{t}</b><br>'
                   f'<span style="font-size:14px;color:#aaa">{ch} · {v} visualizações</span></div></div>'
                   for t, ch, v, c in side)
    return f"""<div style="position:absolute;inset:0;background:#0f0f0f;color:#f1f1f1">
<div style="height:44px;background:#202124;display:flex;align-items:center;gap:10px;padding:0 14px;font-size:15px">
 <span style="background:#35363a;padding:8px 18px;border-radius:8px 8px 0 0">▶ {title} - YouTube</span>
 <span style="color:#aaa">Gmail (3)</span></div>
<div style="height:40px;background:#35363a;display:flex;align-items:center;padding:0 18px;font-size:16px;color:#ddd">
 youtube.com/watch?v=dQw4w9WgXcQ</div>
<div style="position:absolute;left:24px;top:150px;width:1280px;height:720px;background:#000;overflow:hidden">
 <div style="position:absolute;left:0;top:0;width:1920px;height:1080px;transform:scale(.6667);transform-origin:0 0">
 {player_html}</div>
 <div style="position:absolute;left:0;right:0;bottom:0;height:5px;background:#555"><div style="width:38%;height:5px;background:red"></div></div>
</div>
<div style="position:absolute;left:24px;top:886px;width:1280px;font-size:24px;font-weight:600">{title}</div>
<div style="position:absolute;left:24px;top:930px;font-size:16px;color:#aaa">Canal Estude Mais · 1,2 mi de visualizações · há 2 anos</div>
<div style="position:absolute;left:24px;top:965px;font-size:15px;color:#ccc">@ana_23 Melhor professor! Me salvou na prova kkk</div>
<div style="position:absolute;left:1340px;top:110px;width:560px">{recs}</div>
<div style="position:absolute;right:20px;bottom:70px;width:380px;padding:16px 18px;background:#2b2b2b;border-radius:10px;
 box-shadow:0 8px 24px rgba(0,0,0,.6);font-size:16px">{toast}</div>
<div style="position:absolute;left:0;right:0;bottom:0;height:48px;background:#1c1c1c;display:flex;align-items:center;
 justify-content:flex-end;padding:0 18px;font-size:15px;color:#ddd">14:32<br>10/10/2026</div></div>"""


SIDE = [("10 curiosidades sobre gatos", "Bichos TV", "3 mi", "7c3aed"),
        ("Como ganhar dinheiro rápido em 2026", "Grana Fácil", "800 mil", "16a34a"),
        ("Receita de bolo de cenoura fofinho", "Cozinha da Vó", "5 mi", "ea580c"),
        ("Melhores momentos do clássico", "Esporte Agora", "2 mi", "0284c7")]
SIDE_NOISE = ["gatos", "ganhar dinheiro", "bolo de cenoura", "clássico", "Bichos TV", "Grana Fácil", "Cozinha da Vó"]

DENSO = ('<div class="slide"><h1>Glossário de redes</h1><div style="font-size:26px;line-height:1.7">'
         "<b>Latência:</b> tempo que um pacote leva para ir e voltar<br><b>Largura de banda:</b> quantidade máxima "
         "de dados transmitidos por segundo<br><b>DNS:</b> traduz nomes de domínio em endereços IP<br><b>TCP:</b> "
         "entrega confiável e ordenada dos pacotes<br><b>UDP:</b> envio rápido, sem garantia de entrega<br>"
         "<b>Roteador:</b> encaminha pacotes entre redes diferentes</div></div>")

EDITOR = ("""<div style="position:absolute;inset:0;background:#1e1e1e;color:#d4d4d4;font:15px 'Segoe UI'">
<div style="position:absolute;left:0;top:0;bottom:24px;width:48px;background:#333"></div>
<div style="position:absolute;left:48px;top:0;bottom:24px;width:260px;background:#252526;padding:10px 14px;line-height:1.9">
EXPLORER<br>▾ MEU-PROJETO<br>&nbsp;&nbsp;main.py<br>&nbsp;&nbsp;baixar.py<br>&nbsp;&nbsp;notas.md<br>&nbsp;&nbsp;.env</div>
<div style="position:absolute;left:308px;top:0;right:0;height:36px;background:#2d2d2d;padding:9px 16px">main.py ×&nbsp;&nbsp;&nbsp; baixar.py</div>
<pre style="position:absolute;left:330px;top:50px;margin:0;font:22px/1.6 Consolas,monospace;color:#9cdcfe">import requests
from pathlib import Path

API_KEY = "sk-minha-chave-secreta"

def baixar(url, destino):
    r = requests.get(url, timeout=10)
    Path(destino).write_bytes(r.content)
    return len(r.content)

if __name__ == "__main__":
    print(baixar("https://exemplo.com/a.pdf", "a.pdf"))</pre>
<div style="position:absolute;left:0;right:0;bottom:0;height:24px;background:#007acc;color:#fff;padding:3px 12px;font-size:13px">
main  Python 3.14  Ln 7, Col 21  UTF-8</div></div>""")

NOTES = ("""<div style="position:absolute;inset:0;background:#fff;color:#37352f;font:16px 'Segoe UI'">
<div style="position:absolute;left:0;top:0;bottom:0;width:250px;background:#f7f6f3;padding:16px;line-height:2;color:#5f5e5b">
Meu espaço<br>📚 Estudos<br>&nbsp;&nbsp;Biologia<br>&nbsp;&nbsp;História<br>🗓️ Agenda<br>💡 Ideias</div>
<div style="position:absolute;left:330px;top:80px;right:200px;line-height:1.8;font-size:22px">
<div style="font-size:40px;font-weight:700;margin-bottom:20px">Minhas anotações – Biologia</div>
• fotossíntese acontece no cloroplasto<br>• fase clara precisa de luz, fase escura não<br>
• perguntar pro professor sobre o ciclo de Calvin<br>• revisar para a prova de quinta</div></div>""")

WINDOW = "Aula - YouTube — msedge.exe"  # a gravação manda o título e o programa da janela capturada

FRAMES = [
    {"id": "fotossintese", "relevant": True,
     "html": _slide("Fotossíntese: fase clara e fase escura",
                    ["Ocorre nos cloroplastos das células vegetais", "Fase clara: tilacoides, produz ATP e NADPH",
                     "Fase escura (Ciclo de Calvin): estroma, fixa CO₂"], "Biologia · Aula 7 · 12/30",
                    '<div class="box">6 CO₂ + 6 H₂O → C₆H₁₂O₆ + 6 O₂</div>'),
     "must": ["Fotossíntese: fase clara e fase escura", "Ocorre nos cloroplastos das células vegetais",
              "Fase clara: tilacoides, produz ATP e NADPH", "Fase escura (Ciclo de Calvin): estroma, fixa CO2",
              "6 CO2 + 6 H2O → C6H12O6 + 6 O2"]},
    {"id": "tabela", "relevant": True,
     "html": '<div class="slide"><h1>Complexidade dos algoritmos de ordenação</h1><table><tr><th>Algoritmo</th>'
             '<th>Melhor caso</th><th>Pior caso</th><th>Estável</th></tr><tr><td>Quicksort</td><td>O(n log n)</td>'
             '<td>O(n²)</td><td>Não</td></tr><tr><td>Merge sort</td><td>O(n log n)</td><td>O(n log n)</td><td>Sim</td>'
             '</tr><tr><td>Insertion sort</td><td>O(n)</td><td>O(n²)</td><td>Sim</td></tr></table></div>',
     "must": ["Complexidade dos algoritmos de ordenação", "Quicksort O(n log n) O(n2) Não",
              "Merge sort O(n log n) O(n log n) Sim", "Insertion sort O(n) O(n2) Sim", "Melhor caso Pior caso Estável"]},
    {"id": "codigo", "relevant": True,
     "html": '<div class="slide" style="background:#0d1117;color:#e6edf3"><h1 style="color:#79c0ff">Busca binária em '
             'Python</h1><pre style="font:34px/1.45 Consolas,monospace;margin:0">def busca_binaria(lista, alvo):\n'
             '    inicio, fim = 0, len(lista) - 1\n    while inicio &lt;= fim:\n        meio = (inicio + fim) // 2\n'
             '        if lista[meio] == alvo:\n            return meio\n        if lista[meio] &lt; alvo:\n'
             '            inicio = meio + 1\n        else:\n            fim = meio - 1\n    return -1</pre></div>',
     "must": ["Busca binária em Python", "def busca_binaria(lista, alvo):", "inicio, fim = 0, len(lista) - 1",
              "while inicio <= fim:", "meio = (inicio + fim) // 2", "if lista[meio] == alvo:", "return meio",
              "inicio = meio + 1", "fim = meio - 1", "return -1"]},
    {"id": "diagrama", "relevant": True,
     "html": '<div class="slide"><h1>Ciclo da água</h1>' + "".join(
         f'<div style="position:absolute;left:{x}px;top:{y}px;width:360px;padding:30px;border-radius:24px;'
         f'background:{c};color:#fff;font-size:40px;text-align:center">{t}</div>'
         for t, x, y, c in [("Evaporação", 300, 300, "#0284c7"), ("Condensação", 1250, 300, "#6366f1"),
                            ("Precipitação", 1250, 720, "#0d9488"), ("Infiltração", 300, 720, "#a16207")])
         + "".join(f'<div style="position:absolute;left:{x}px;top:{y}px;font-size:90px;color:#475569">{a}</div>'
                   for a, x, y in [("→", 870, 290), ("↓", 1400, 470), ("←", 870, 710), ("↑", 450, 470)]) + "</div>",
     "must": ["Ciclo da água", "Evaporação", "Condensação", "Precipitação", "Infiltração"]},
    {"id": "formula", "relevant": True,
     "html": _slide("Teorema de Pitágoras", ["Vale apenas para triângulos retângulos",
                                             "Exemplo: catetos 3 e 4 → hipotenusa 5"], "Matemática · Geometria",
                    '<div class="box" style="font-size:72px">a² + b² = c²</div>'),
     "must": ["Teorema de Pitágoras", "a2 + b2 = c2", "Vale apenas para triângulos retângulos",
              "Exemplo: catetos 3 e 4 → hipotenusa 5"]},
    {"id": "denso", "relevant": True, "html": DENSO,
     "must": ["Glossário de redes", "Latência: tempo que um pacote leva para ir e voltar",
              "Largura de banda: quantidade máxima de dados transmitidos por segundo",
              "DNS: traduz nomes de domínio em endereços IP", "TCP: entrega confiável e ordenada dos pacotes",
              "UDP: envio rápido, sem garantia de entrega", "Roteador: encaminha pacotes entre redes diferentes"]},
    {"id": "rosto", "relevant": False,
     "html": '<div style="position:absolute;inset:0;background:linear-gradient(120deg,#78350f,#a16207 40%,#57534e)">'
             '<div style="position:absolute;left:1300px;top:120px;width:300px;height:500px;background:#44403c"></div>'
             + _person(660, 200, 1.6, "transparent") +
             '<div style="position:absolute;left:80px;bottom:90px;padding:14px 26px;background:rgba(0,0,0,.6);'
             'color:#fff;font-size:30px;border-left:8px solid #f59e0b">Prof. Marina Souza</div></div>',
     "must": [], "noise": []},
    {"id": "youtube_aula", "relevant": True, "box": [24 / W, 150 / H, 1304 / W, 870 / H],
     "html": _browser(_slide("Revolução Francesa (1789)", ["Queda da Bastilha: 14 de julho de 1789",
                                                           "Lema: Liberdade, Igualdade, Fraternidade",
                                                           "Fim do Antigo Regime e dos privilégios do clero"],
                             "História · Aula 3"),
                      "Revolução Francesa — Aula completa | História", SIDE,
                      "<b>WhatsApp</b><br>João: vamos almoçar amanhã?"),
     "must": ["Revolução Francesa (1789)", "Queda da Bastilha: 14 de julho de 1789",
              "Lema: Liberdade, Igualdade, Fraternidade", "Fim do Antigo Regime e dos privilégios do clero"],
     "noise": SIDE_NOISE + ["João", "almoçar", "Me salvou na prova", "Gmail"]},
    {"id": "camera", "relevant": True,
     "html": _slide("Lei de Ohm", ["V = R · I", "V: tensão (volts)", "R: resistência (ohms, Ω)",
                                   "I: corrente (ampères)", "Exemplo: R = 10 Ω e I = 2 A → V = 20 V"],
                    "Física · Eletricidade") + _person(1440, 600, 0.95),
     "must": ["Lei de Ohm", "V = R · I", "V: tensão (volts)", "R: resistência (ohms, Ω)", "I: corrente (ampères)",
              "Exemplo: R = 10 Ω e I = 2 A → V = 20 V"]},
    {"id": "quadro", "relevant": True,
     "html": '<div style="position:absolute;inset:0;background:#fdfdf8;padding:110px 150px;font:64px/1.6 '
             '\'Ink Free\',\'Segoe Print\',cursive;color:#1d4ed8"><u>Derivada</u><br>f(x) = x³ → f\'(x) = 3x²<br>'
             '<span style="color:#b91c1c">regra do tombo: desce o expoente</span></div>',
     "must": ["Derivada", "f(x) = x3 → f'(x) = 3x2", "regra do tombo: desce o expoente"]},
    {"id": "ingles", "relevant": True,
     "html": _slide("Supply and Demand", ["When price rises, demand falls", "When price rises, supply rises",
                                          "Equilibrium: supply = demand"], "Economics 101 · Week 2"),
     "must": ["Supply and Demand", "When price rises, demand falls", "When price rises, supply rises",
              "Equilibrium: supply = demand"]},
    {"id": "youtube_anuncio", "relevant": False, "box": [24 / W, 150 / H, 1304 / W, 870 / H],
     "html": _browser('<div style="position:absolute;inset:0;background:linear-gradient(135deg,#be123c,#f97316);'
                      'color:#fff;padding:140px;font-size:90px;font-weight:800">Curso de inglês<br>com 50% de desconto'
                      '<div style="position:absolute;right:0;bottom:120px;background:rgba(0,0,0,.7);font-size:40px;'
                      'padding:20px 40px;font-weight:400">Pular anúncio ▸</div><div style="position:absolute;left:40px;'
                      'bottom:40px;font-size:34px;font-weight:400">Patrocinado · Saiba mais</div></div>',
                      "Revolução Francesa — Aula completa | História", SIDE,
                      "<b>Windows</b><br>Atualizações prontas para instalar"),
     "must": [], "noise": SIDE_NOISE + ["Atualizações"]},
    {"id": "youtube_denso", "relevant": True, "box": [24 / W, 150 / H, 1304 / W, 870 / H],
     "html": _browser(DENSO, "Redes de computadores — Aula 2", SIDE, "<b>Discord</b><br>Lucas: bora jogar hoje?"),
     "must": ["Glossário de redes", "Latência: tempo que um pacote leva para ir e voltar",
              "Largura de banda: quantidade máxima de dados transmitidos por segundo",
              "DNS: traduz nomes de domínio em endereços IP", "TCP: entrega confiável e ordenada dos pacotes",
              "UDP: envio rápido, sem garantia de entrega", "Roteador: encaminha pacotes entre redes diferentes"],
     "noise": SIDE_NOISE + ["Lucas", "jogar"]},
    {"id": "grafico", "relevant": True,
     "html": '<div class="slide"><h1>Vendas por trimestre (2025)</h1><div style="display:flex;align-items:flex-end;'
             'gap:90px;height:620px;margin-left:120px;border-left:4px solid #334155;border-bottom:4px solid #334155;'
             'padding:0 60px">' + "".join(
                 f'<div style="text-align:center;font-size:34px"><b>{v} mil</b><div style="width:170px;height:{v * 2.6}px;'
                 f'background:#2563eb;border-radius:12px 12px 0 0;margin-top:8px"></div><div style="margin-top:14px">{q}'
                 '</div></div>' for q, v in [("T1", 120), ("T2", 150), ("T3", 90), ("T4", 200)]) + "</div></div>",
     "must": ["Vendas por trimestre (2025)", "120 mil", "150 mil", "90 mil", "200 mil", "T1", "T2", "T3", "T4"]},
    # o mesmo editor: na janela do VS Code do aluno não é aula; dentro do vídeo da aula (navegador), é
    {"id": "editor_do_aluno", "relevant": False, "window": "main.py - meu-projeto - Visual Studio Code — Code.exe",
     "html": EDITOR, "must": []},
    {"id": "editor_na_aula", "relevant": True, "window": "Aula 3: baixando arquivos com requests - YouTube — msedge.exe",
     "html": EDITOR, "must": ["import requests", "def baixar(url, destino):", "r = requests.get(url, timeout=10)"]},
    {"id": "anotacoes_do_aluno", "relevant": False, "window": "Minhas anotações – Biologia - Notion — Notion.exe",
     "html": NOTES, "must": []},
    {"id": "rosto_sem_nome", "relevant": False,
     "html": '<div style="position:absolute;inset:0;background:radial-gradient(circle at 30% 30%,#475569,#0f172a)">'
             + _person(700, 160, 1.7, "transparent") + "</div>", "must": [], "noise": []},
]

# --- pedido ao modelo (o mesmo que o app usa: lumen/vision.py importa daqui se mudar) -----------------------------

from lumen.vision import SCHEMA, SYSTEM, clean  # noqa: E402  (o mesmo pedido e o mesmo filtro do app)
from lumen.vision import ask as vision_ask, student_app  # noqa: E402

# --- métricas ---------------------------------------------------------------------------------------------------

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")


def norm(text):
    t = unicodedata.normalize("NFKC", str(text).translate(_SUB)).lower()
    t = t.replace("^", "").replace("·", " ").replace("×", "x").replace("’", "'").replace("−", "-")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+|[^\sa-z0-9]", t)


def recall(must, text):
    have = norm(text)
    want = [w for m in must for w in norm(m)]
    if not want:
        return None
    pool = {}
    for w in have:
        pool[w] = pool.get(w, 0) + 1
    hit = 0
    for w in want:
        if pool.get(w):
            pool[w] -= 1
            hit += 1
    return hit / len(want)


def noise_hits(noise, text):
    t = " ".join(norm(text))
    return [n for n in noise if " ".join(norm(n)) in t]


# --- comandos ---------------------------------------------------------------------------------------------------

def make():
    from lumen.cover import edge
    OUT.mkdir(parents=True, exist_ok=True)
    exe = edge()
    for f in FRAMES:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.html"
            page.write_text(f'<!doctype html><meta charset="utf-8"><style>{CSS}</style><body>{f["html"]}', "utf-8")
            subprocess.run([str(exe), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            f"--user-data-dir={Path(tmp) / 'u'}", f"--window-size={W},{H}",
                            f"--screenshot={OUT / (f['id'] + '.png')}", page.as_uri()], capture_output=True, timeout=60)
        print(f["id"], (OUT / (f["id"] + ".png")).stat().st_size)


def _jpeg(png_path, width):
    """PNG → JPEG na largura pedida (PyAV, como o app faz)."""
    import av
    with av.open(str(png_path)) as c:
        frame = next(c.decode(video=0))
    h = round(frame.height * width / frame.width / 2) * 2
    frame = frame.reformat(width=width, height=h, format="yuvj420p", interpolation="AREA")
    enc = av.CodecContext.create("mjpeg", "w")
    enc.width, enc.height, enc.pix_fmt = width, h, "yuvj420p"
    enc.time_base = __import__("fractions").Fraction(1, 1)
    enc.options = {"qmin": "3", "qmax": "3"}  # qualidade alta fixa (≈ 50 KB numa tela 1280×720)
    return b"".join(bytes(p) for p in enc.encode(frame)) + b"".join(bytes(p) for p in enc.encode(None))


OPTIONS = {}  # extra (ex.: {"presence_penalty": 0}); ver run()


def ask(model, jpeg, num_ctx=8192, window=None):
    import urllib.request
    body = {"model": model, "stream": False, "think": False, "keep_alive": "5m", "format": SCHEMA,
            "options": {"temperature": 0, "num_ctx": num_ctx, **OPTIONS},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": vision_ask(window),
                          "images": [base64.b64encode(jpeg).decode()]}]}
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    return d


def _vram_used():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.split()[0]) / 1024


def run(model, width=1280):
    rows = []
    ask(model, _jpeg(OUT / "rosto.png", 640))  # aquece (carga do modelo fora da medida)
    vram = _vram_used()
    for f in FRAMES:
        jpeg = _jpeg(OUT / (f["id"] + ".png"), width)
        t = time.perf_counter()
        window = f.get("window", WINDOW)
        if student_app(window):  # o app nem chama o modelo para programas do estudante
            d, ans = {}, {"conteudo_da_aula": False, "titulo": "", "texto": "", "descricao": "", "tipo": "outro"}
        else:
            d = ask(model, jpeg, window=window)
            try:
                ans = json.loads(d["message"]["content"])
            except ValueError:
                ans = {}
        dt = time.perf_counter() - t
        text = " ".join(str(ans.get(k, "")) for k in ("titulo", "texto", "descricao"))
        row = {"id": f["id"], "s": round(dt, 2), "prompt_tokens": d.get("prompt_eval_count"),
               "out_tokens": d.get("eval_count"), "relevant_ok": ans.get("conteudo_da_aula") == f["relevant"],
               "keep_ok": clean(ans)["keep"] == f["relevant"],
               "recall": recall(f["must"], text), "noise": noise_hits(f.get("noise", []), text),
               "answer": ans}
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "answer"}, ensure_ascii=False), flush=True)
    rec = [r["recall"] for r in rows if r["recall"] is not None]
    summary = {"model": model, "width": width, "recall": round(sum(rec) / len(rec), 3),
               "recall_min": round(min(rec), 3), "relevance": sum(r["relevant_ok"] for r in rows),
               "keep": sum(r["keep_ok"] for r in rows),
               "frames": len(rows), "noise": sum(len(r["noise"]) for r in rows),
               "s_mean": round(sum(r["s"] for r in rows) / len(rows), 2), "s_max": max(r["s"] for r in rows),
               "vram_gb_total": round(vram, 2)}
    print(json.dumps({**summary, "options": OPTIONS}, ensure_ascii=False))
    RES.mkdir(exist_ok=True)
    out = RES / "vision.json"
    allr = json.loads(out.read_text("utf-8")) if out.exists() else {}
    allr[f"{model}@{width}" + (json.dumps(OPTIONS) if OPTIONS else "")] = {"summary": {**summary, "options": OPTIONS},
                                                                             "rows": rows}
    out.write_text(json.dumps(allr, ensure_ascii=False, indent=1), "utf-8")


def report():
    allr = json.loads((RES / "vision.json").read_text("utf-8"))
    print("| modelo | largura | recall | pior tela | relevância | guardada certo | ruído | IoU área | s/tela | s máx | VRAM total |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for k, v in allr.items():
        s = v["summary"]
        print(f"| {s['model']}{' ' + json.dumps(s['options']) if s.get('options') else ''} | {s['width']} | {s['recall']:.1%} | {s['recall_min']:.1%} | {s['relevance']}/{s['frames']} | {s.get('keep', '–')}{'/' + str(s['frames']) if 'keep' in s else ''}"
              f" | {s['noise']} | {', '.join(f'{x:.2f}' for x in s.get('iou', [])) or '–'} | {s['s_mean']} | {s['s_max']} | "
              f"{s['vram_gb_total']} |")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "make":
        make()
    elif cmd == "run":
        if len(sys.argv) > 4:  # opções do Ollama em JSON, ex.: '{"presence_penalty": 0}'
            OPTIONS.update(json.loads(sys.argv[4]))
        run(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1280)
    elif cmd == "report":
        report()
