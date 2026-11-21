r"""Screenshots e checagens de todas as telas do Lumen com a API simulada (Playwright + Chrome sem GPU, como o WebView2).

Na raiz do projeto (o Playwright está no Python do sistema, não no .venv):
  py -3.14 tests\ui_shots.py                 todas as telas, 1120×860
  py -3.14 tests\ui_shots.py home run        só os cenários cujo nome contém "home" ou "run"
  py -3.14 tests\ui_shots.py --sizes         também 520×560, 900×700, 1600×1000 e 1920×1040
  py -3.14 tests\ui_shots.py --zoom          também 80, 90, 110 e 120% (1120×860)
  py -3.14 tests\ui_shots.py --perf          mede carga, troca de tela e quadros ao rolar
Imagens em tests\desktop-artifacts\ui\. Falha (código 1) com erro de página, rolagem horizontal, controle fora da janela
ou alvo de clique menor que 24 px. Dados isolados: LUMEN_DATA temporário e nenhuma chamada real ao Notion/Ollama/cofre.
"""
import base64
import copy
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("LUMEN_UI_OUT", ROOT / "tests" / "desktop-artifacts" / "ui"))
NOW = time.time()


def iso(days=0, hours=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - days * 86400 - hours * 3600))


def png(w=320, h=180, rgb=(38, 48, 86)):
    """Uma "tela da aula" de mentira: gradiente com faixas, para as galerias terem o que mostrar."""
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            k = 1 - y / h * .5
            band = 30 if 30 < y < 44 and 24 < x < 220 else 18 if (60 < y < 66 or 80 < y < 86 or 100 < y < 106) and 24 < x < 280 else 0
            row += bytes(min(255, int(c * k) + band * 3) for c in rgb)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


SHOT = png()
COVER = png(768, 320, (64, 58, 140))  # capa de mentira na proporção real (1536 × 640), em metade do tamanho
NOTE = ("A convolução passa um filtro pequeno pela imagem e soma os produtos, então cada neurônio só olha uma região "
        "local. Isso reduz muito os parâmetros em relação a uma rede densa. O pooling diminui a resolução e deixa a rede "
        "mais tolerante a pequenos deslocamentos. Camadas mais profundas combinam bordas em formas e depois em objetos.")


def world():
    """O estado do Lumen que a interface vê. Cada cenário parte de uma cópia e muda só o que precisa."""
    cfg = dict(root_page_id="root-1", root_page_title="Estudos", quality="equilibrado", ollama_model="qwen3:8b",
               page_language="pt", keep_temp=False, watch_screen=True, music_filter=False, music_mode="balanceado",
               widget="left", autostart=True, destinations="both", study_level="balanceado",
               obsidian_vault=r"C:\Users\Estudante\Cérebro", obsidian_folder="B02 Estudos",
               notion_free_page_id="p-free", notion_free_page_title="Estudos › Conteúdo gratuito", obsidian_canvas=True, obsidian_board=True, obsidian_board_density="equilibrado", obsidian_connections=True, obsidian_review=True,
               obsidian_attachments=True, obsidian_open=False, review_intervals=[1, 3, 7, 14, 30, 60])
    ready = lambda phase, label, tone="wait", detail="": {"phase": phase, "label": label, "detail": detail, "tone": tone, "blocked": tone != "ok"}
    pending = [
        {"key": "k1", "title": "Redes neurais convolucionais", "label": "Gravação", "state": "understanding_written",
         "updated": iso(hours=2), "at": 1, "rev": 3, "ready": ready("ready", "Pronto para analisar", "ok")},
        {"key": "k2", "title": "Complexidade de algoritmos e notação O", "label": "Arquivo local", "state": "completed",
         "updated": iso(days=1), "at": 1, "rev": 5, "ready": ready("completed", "Análise concluída", "ok")},
        {"key": "k3", "title": "Kant: Crítica da razão pura, introdução", "label": "Gravação", "state": "waiting_for_understanding",
         "updated": iso(days=3), "at": 0, "rev": 0, "ready": ready("writing", "Escreva sua compreensão para continuar")},
    ]
    doc = lambda key, title, state, text, analysis=None: {
        "key": key, "title": title, "label": "Gravação", "state": state, "text": text, "at": 1, "original": text if analysis else None,
        "submitted": iso(hours=1) if analysis else None, "analysis": analysis, "analyzed_text": text if analysis else None,
        "model": "qwen3:8b" if analysis else None, "final_knowledge": None, "problem": "", "spec": {"kind": "recording", "path": "C:/aula.wav"},
        "updated": iso(hours=1), "rev": 3, "analyzed_rev": 3 if analysis else None,
        "ready": ready("completed", "Análise concluída", "ok") if analysis else ready("ready", "Pronto para analisar", "ok")}
    analysis = {
        "acertos": ["A convolução aplica um filtro local e compartilha os pesos pela imagem inteira.",
                    "O pooling reduz a resolução e dá tolerância a pequenos deslocamentos."],
        "parciais": ["As camadas profundas combinam padrões, mas a aula mostra que isso depende do campo receptivo, que cresce a cada camada."],
        "lacunas": ["O papel do passo (stride) e do preenchimento (padding) no tamanho da saída.", "Por que a ReLU entra depois de cada convolução."],
        "confusoes": [{"trecho": "cada neurônio só olha uma região local", "correcao": "Vale para a camada; o campo receptivo efetivo cresce com a profundidade."}],
        "complementos": ["Normalização em lote (batch norm) estabiliza o treino de redes profundas."],
        "conexoes": ["Filtros de borda (Sobel) da visão computacional clássica."],
        "perguntas": ["Como o tamanho do filtro muda o número de parâmetros?", "O que acontece com a saída se o stride dobrar?"],
    }
    courses = [
        {"id": "c-ia", "name": "Inteligência Artificial", "platform": "Hotmart", "url": "", "created": "2026-10-01", "notion_page_id": "p-ia",
         "modules": [{"id": "m-fund", "name": "Fundamentos", "order": 1, "notion_page_id": None},
                     {"id": "m-dl", "name": "Deep Learning", "order": 2, "notion_page_id": "p-dl"}]},
        {"id": "c-mat", "name": "Matemática", "platform": "", "url": "", "created": "2026-10-02", "notion_page_id": "p-mat", "modules": []},
    ]
    C = lambda t, **kv: {"type": t, **kv}  # noqa: E731  (a classificação, como o servidor devolve)
    history = [
        {"key": "h1", "lumen_id": "L1", "title": "Transformers e atenção", "course": "Estudos › Inteligência Artificial",
         "created": iso(days=2), "url": "https://www.notion.so/h1",
         "obsidian": {"status": "ok", "note": "16 Lumen/2026-10-22 - Transformers e atenção.md", "canvas": "16 Lumen/Mapa - Transformers.canvas", "board": "16 Lumen/Painel - Transformers.canvas",
                      "connections": 4, "questions": 12, "state": "created", "at": iso(days=2)}},
        {"key": "h2", "lumen_id": "L2", "title": "Gradiente descendente na prática", "course": "Estudos › Inteligência Artificial",
         "created": iso(days=6), "url": "https://www.notion.so/h2", "obsidian": {"status": "ok", "note": "n.md", "canvas": None, "connections": 2, "questions": 9, "state": "created", "at": iso(days=6)}},
        {"key": "h3", "lumen_id": "L3", "title": "Revolução Francesa: causas econômicas", "course": "Estudos › História",
         "created": iso(days=9), "url": "https://www.notion.so/h3"},
        {"key": "h4", "lumen_id": "L4", "title": "Estruturas de dados: árvores B", "spec": {"course_title": "Banco de dados"},
         "obsidian": {"status": "ok", "note": "b.md", "canvas": "c.canvas", "connections": 6, "questions": 14, "state": "created", "at": iso(days=12)}},
        {"key": "h5", "lumen_id": "L5", "title": "Cálculo II: integrais por partes", "course": "Estudos › Matemática",
         "created": iso(days=20), "url": "https://www.notion.so/h5"},
        {"key": "h6", "lumen_id": "L6", "title": "Introdução à economia comportamental", "course": "Estudos › Economia",
         "created": iso(days=31), "url": "https://www.notion.so/h6"},
    ]
    org = {"h1": (C("course", course_id="c-ia", course="Inteligência Artificial", module_id="m-dl", module="Deep Learning", lesson=3),
                  ["Cursos", "Inteligência Artificial", "Deep Learning · Aula 03"], {"next": iso(days=0)[:10], "stage": "2", "status": "review-required"}),
           "h2": (C("course", course_id="c-ia", course="Inteligência Artificial", module_id="m-fund", module="Fundamentos", lesson=1),
                  ["Cursos", "Inteligência Artificial", "Fundamentos · Aula 01"], {"next": iso(days=-5)[:10], "stage": "1", "status": "completed"}),
           "h3": (C("free", category="História"), ["Conteúdo gratuito", "História"], None),
           "h4": (C("inbox"), ["A organizar"], {"next": iso(days=2)[:10], "stage": "1", "status": "review-required"}),
           "h5": (C("course", course_id="c-mat", course="Matemática"), ["Cursos", "Matemática"], None),
           "h6": (C("single", category="Economia"), ["Aulas avulsas", "Economia"], None)}
    for it in history:
        cls, crumbs, review = org[it["key"]]
        it.update(classification=cls, crumbs=crumbs, review=review, concepts=["atenção", "derivada", "árvore B"])
    pages = [
        {"id": "root-1", "title": "Estudos", "path": "Estudos", "top": True, "parent": None, "icon": "📚"},
        {"id": "p-ia", "title": "Inteligência Artificial", "path": "Estudos › Inteligência Artificial", "top": False, "parent": "root-1", "icon": "🤖"},
        {"id": "p-hist", "title": "História", "path": "Estudos › História", "top": False, "parent": "root-1", "icon": "🏛️"},
        {"id": "p-mat", "title": "Matemática", "path": "Estudos › Matemática", "top": False, "parent": "root-1", "icon": None},
        {"id": "p-free", "title": "Conteúdo gratuito", "path": "Estudos › Conteúdo gratuito", "top": False, "parent": "root-1", "icon": "🌍"},
        {"id": "p-dl", "title": "Deep Learning", "path": "Estudos › Inteligência Artificial › Deep Learning", "top": False, "parent": "p-ia", "icon": None},
    ]
    review = {"review": True, "key": "k2", "title": "Complexidade de algoritmos e notação O", "engine": "large-v3-turbo na GPU (CUDA, float16)",
              "speed": {"requested": "auto", "used": 1, "words_per_s": 2.6}, "duration": 1840, "language": "pt", "can_retranscribe": True,
              "music": None, "segments": [
                  {"start": 0, "text": "Hoje a gente vai falar de complexidade de algoritmos, começando pela notação O grande.", "flags": []},
                  {"start": 14.2, "text": "Quando o algoritmo percorre a lista uma vez, dizemos que ele é linear, O de n.", "flags": []},
                  {"start": 31.8, "text": "O merge sort divide a lista ao meio e junta, então ele fica em n log n.", "flags": ["modelos discordam"], "alt": "O merge sort divide a lista ao meio e junta, então fica n log n."},
                  {"start": 52.5, "text": "No teste, o bubble sort levou 5.200 milissegundos com dez mil itens.", "flags": ["número"]},
                  {"start": 71.0, "text": "Isso explica por que o Knuth recomenda medir antes de otimizar.", "flags": ["nome próprio", "trecho incerto"]},
              ], "screens": {"seen": 9, "items": [{"id": f"s{i}", "t": 60 * i + 12, "titulo": t, "manual": False}
                                                 for i, t in enumerate(["Notação O grande", "Comparação de algoritmos de ordenação", "Gráfico n log n", "Código do merge sort"])]}}
    return {
        "config": cfg, "has_token": True, "gpu": True,
        "whisper": {"active": "equilibrado", "models": {
            "rapido": {"label": "Rápido", "name": "small", "size": "0,48 GB", "downloaded": True},
            "equilibrado": {"label": "Equilibrado", "name": "large-v3-turbo", "size": "1,6 GB", "downloaded": True},
            "maximo": {"label": "Maior precisão", "name": "large-v3", "size": "3,1 GB", "downloaded": False}}},
        "ollama": {"running": True, "installed": True, "models": ["qwen3:8b", "qwen3.5:4b"]},
        "sources": {k: {"id": "compativel", "label": "Compatível"} for k in ("recording", "file", "youtube", "telegram", "captures")},
        "formats": {".mp4": "MP4", ".mkv": "MKV", ".webm": "WebM", ".mov": "MOV", ".mp3": "MP3", ".m4a": "M4A", ".wav": "WAV"},
        "images": [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
        "covers": {"ready": False, "label": "Z-Image-Turbo", "size": "6,7 GB", "license": "Apache 2.0 (Alibaba Tongyi)",
                   "folder": "C:/Users/Estudante/AppData/Local/Lumen/imagem"},
        "vision": {"model": "qwen3.5:4b", "size": "3,3 GB", "installed": True},
        "music": {"ready": False, "size": "72 MB"},
        "obsidian": {"vaults": [{"path": cfg["obsidian_vault"], "name": "Cérebro", "open": True, "ok": True, "folder": cfg["obsidian_folder"]}],
                     "folder": cfg["obsidian_folder"], "error": None},
        "recording": {"active": False, "seconds": 0, "level": 0, "heard": False, "paused": False},
        "job": {"status": "idle"},
        "pending": pending, "history": history, "pages": pages, "review": review, "courses": courses,
        "migration": {"lessons": [], "folders": []},
        "reviews": [{"key": "h1", "title": "Transformers e atenção", "next_review": iso(days=0)[:10], "stage": 2, "overdue": False},
                    {"key": "h4", "title": "Estruturas de dados: árvores B", "next_review": iso(days=2)[:10], "stage": 1, "overdue": True}],
        "docs": {"k1": doc("k1", "Redes neurais convolucionais", "understanding_written", NOTE),
                 "k2": doc("k2", "Complexidade de algoritmos e notação O", "completed", NOTE, analysis),
                 "k3": doc("k3", "Kant: Crítica da razão pura, introdução", "waiting_for_understanding", "")},
        "found": {"title": "Redes neurais convolucionais", "label": "Gravação", "duration": 2712, "needs_transcription": True,
                  "whisper_ready": True, "estimate": 140, "info": {"format": "WAV · 48 kHz"}},
        "pomodoro": {"phase": "focus", "running": True, "left": 1122, "total": 1500, "done": 1, "event": None,
                     "settings": {"focus": 25, "short": 5, "long": 15, "cycles": 4, "auto": False, "sound": True}},
        **drive_world(),
        # Capas do Notion: páginas como /api/notion/search devolve (lumen/notion._summary)
        "cov_pages": [
            {"id": "pg-orc", "title": "Orçamento doméstico 2026", "url": "https://www.notion.so/Orcamento-pgorc", "icon": "💰",
             "where": "No topo do workspace", "edited": iso(hours=2), "cover": None},
            {"id": "pg-notas-1", "title": "Notas", "url": "https://www.notion.so/Notas-1", "icon": None,
             "where": "Subpágina de “Pessoal”", "edited": iso(days=1), "cover": None},
            {"id": "pg-notas-2", "title": "Notas", "url": "https://www.notion.so/Notas-2", "icon": "🗂️",
             "where": "Subpágina de “Trabalho”", "edited": iso(days=3), "cover": "file:prod-files-secure.s3.amazonaws.com/ws/a1/capa.png"},
            {"id": "pg-luz", "title": "Conta de luz — outubro", "url": "https://www.notion.so/Conta-de-luz-pgluz", "icon": "💡",
             "where": "Registro em “Contas da casa”", "edited": iso(days=4), "cover": None},
            {"id": "p-ia", "title": "Inteligência Artificial", "url": "https://www.notion.so/Inteligencia-Artificial-pia", "icon": "🤖",
             "where": "Subpágina de “Cursos”", "edited": iso(days=6), "cover": "external:https://www.notion.so/images/page-cover/gradients_5.png"},
            {"id": "p-dl", "title": "Deep Learning", "url": "https://www.notion.so/Deep-Learning-pdl", "icon": "🧠",
             "where": "Subpágina de “Inteligência Artificial”", "edited": iso(days=2), "cover": "file:prod-files-secure.s3.amazonaws.com/ws/b2/capa.png"},
            {"id": "pg-longo", "title": "Planejamento do semestre de Engenharia de Computação, com metas, provas, trabalhos e leituras obrigatórias",
             "url": "https://www.notion.so/Planejamento-pglongo", "icon": None, "where": "Subpágina de “Faculdade › 2026-2 › Organização geral”",
             "edited": iso(days=9), "cover": None},
        ],
    }


def drive_world():
    """O cartão Google Drive de Integrações: o formato de gdrive.status() (a conta da cópia de segurança da Proteção)."""
    return {"drive": {"client": False, "connected": False, "email": "", "login": "idle", "error": "", "expired": False}}


def drive_card(drive=None):
    def f(W):
        W["drive"].update(drive or {})
    return f


def state_of(w):
    keys = ("config", "has_token", "gpu", "whisper", "ollama", "sources", "formats", "images", "covers", "vision", "music",
            "obsidian", "recording", "job", "pending")
    return {k: w[k] for k in keys}


def preview(W, cls, title):
    """Os destinos em palavras (o mesmo formato de server._organize_preview)."""
    c = next((x for x in W["courses"] if x["id"] == cls.get("course_id")), None)
    m = next((x for x in (c or {}).get("modules", []) if x["id"] == cls.get("module_id")), None)
    t = cls.get("type") or "inbox"
    label = {"course": "Cursos", "free": "Conteúdo gratuito", "single": "Aulas avulsas", "inbox": "A organizar"}[t]
    crumbs = [label] + ([c["name"]] + ([m["name"]] if m else []) if t == "course" and c else [cls["category"]] if cls.get("category") else [])
    if cls.get("lesson"): crumbs[-1] += f" · Aula {int(cls['lesson']):02d}"
    notion = (" › ".join(["Estudos", c["name"]] + ([m["name"]] if m else [])) if t == "course" and c
              else f"Estudos › Conteúdo gratuito › {title or 'página do material'}" if t == "free" else "Estudos › Sem curso")
    folder = {"course": "01 - Cursos", "free": "02 - Conteúdo gratuito", "single": "03 - Aulas avulsas", "inbox": "90 - A organizar"}[t]
    return {"classification": cls, "crumbs": crumbs, "notion": notion, "notion_ready": True,
            "obsidian": " / ".join(["Estudos", crumbs[0]] + [x.split(" · Aula")[0] for x in crumbs[1:]]),
            "obsidian_path": f"B02 Estudos/{folder}"}


def router(W, log):
    def route(r):
        u = urlsplit(r.request.url)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        body = r.request.post_data_json if r.request.method == "POST" and r.request.post_data else {}
        log.append((r.request.method, path, body))
        code, data = 200, {}
        if path in ("/api/screen", "/api/capture", "/api/visual"):
            return r.fulfill(status=200, content_type="image/png", body=SHOT)
        if path == "/api/state": data = state_of(W)
        elif path == "/api/job": data = W["job"]
        elif path == "/api/record": data = W["recording"]
        elif path == "/api/widget":
            if q.get("view") == "settings": data = {"config": W["config"], "has_token": W["has_token"]}
            else:
                j = W["job"]
                data = {"job": {**{k: j.get(k) for k in ("status", "kind", "stage", "detail", "progress", "eta", "eta_total", "error")},
                                "title": j.get("title", ""), "url": "", "review": False},
                        "recording": W["recording"], "watch": W["config"]["watch_screen"], "music": W["config"]["music_filter"],
                        "notes": W["pending"], "pomodoro": {**W["pomodoro"], "now": time.time(), "ends_at": time.time() + W["pomodoro"]["left"]}}
        elif path == "/api/pomodoro":
            if body.get("action") in ("play", "pause"):
                W["pomodoro"]["running"] = body["action"] == "play"
            data = {**W["pomodoro"], "now": time.time(), "ends_at": time.time() + W["pomodoro"]["left"]}
        elif path == "/api/history": data = {"items": W["history"], "courses": W["courses"], "categories": ["História", "Economia"]}
        # Google Drive (lumen/gdrive.py): o cartão de Integrações
        elif path == "/api/drive": data = W["drive"]
        elif path == "/api/drive/login":
            W["drive"].update(login="waiting")
            data = W["drive"]
        elif path == "/api/catalog":
            data = {"courses": W["courses"], "categories": ["História", "Economia"], "last": W.get("last")}
            if q.get("notion"): data.update(notion=[] if q.get("course_id") else [{"id": "p-hist", "title": "História"}], root_ok=True)
        elif path == "/api/organize/preview": data = preview(W, body.get("classification") or {}, body.get("title") or "")
        elif path == "/api/organize":
            it = next(x for x in W["history"] if x["key"] == body["key"])
            it.update(classification=body["classification"], crumbs=preview(W, body["classification"], "")["crumbs"])
            W["job"] = {"status": "done", "kind": "organize", "result": {"key": it["key"], "classification": body["classification"],
                                                                          "notion": {"status": "ok", "note": None}, "obsidian": {"status": "ok"}}}
            data = W["job"]
        elif path == "/api/decor/preview":  # a prévia da capa (lumen/server._preview): local, sem o Notion
            if W.get("cover_fail"):
                code, data = 400, {"error": {"message": "O Ollama não está rodando.", "action": "Abra o Ollama e tente de novo."}}
            else:
                kind = W.get("cover_kind", "ia")
                data = {"preview_id": f"pv{body.get('variant') or 0}", "kind": kind, "seconds": 34, "title": body["title"], "parent": "Estudos",
                        "note": {"ia": "", "emojis": "O gerador de capas com IA não está instalado; esta é a capa alternativa, desenhada com emojis.",
                                 "notion": "A ilustração com IA não ficou pronta neste PC e o desenho com emojis também falhou; a página vai usar uma capa de cor do Notion, com o ícone e a frase da prévia."}[kind],
                        "decor": {"emoji": "🧠", "subtitle": "Redes neurais do perceptron às convoluções, com exemplos práticos."},
                        "image": None if kind == "notion" else "data:image/png;base64," + base64.b64encode(COVER).decode()}
        elif path == "/api/notion/search":  # Capas do Notion: 4 por vez, para o “Carregar mais” aparecer
            if W.get("cov_search_fail"):
                code, data = 400, {"error": {"message": "Sem conexão com o Notion.", "action": "Verifique a internet e tente de novo."}}
            else:
                hits = [x for x in W["cov_pages"] if q.get("q", "").casefold() in x["title"].casefold()]
                at = int(q.get("cursor") or 0)
                data = {"pages": hits[at:at + 4], "next_cursor": str(at + 4) if at + 4 < len(hits) else None}
        elif path == "/api/notion/page":
            hit = next((x for x in W["cov_pages"] if x["id"] in q.get("ref", "")), None)
            code, data = (200, hit) if hit else (400, {"error": {"message": "O Lumen não tem acesso a esta página (ou ela foi apagada).",
                                                                 "action": "No Notion, abra a página → ••• → Conexões → adicione a integração do Lumen."}})
        elif path == "/api/cover/preview":  # a prévia da capa de uma página (lumen/server._page_preview): local
            if W.get("cover_fail"):
                code, data = 400, {"error": {"message": "O Ollama não está rodando.", "action": "Abra o Ollama e tente de novo."}}
            else:
                kind = W.get("cover_kind", "ia")
                data = {"preview_id": f"cp{body.get('variant') or 0}", "kind": kind, "seconds": 41, "theme": " ".join((body.get("theme") or "").split()),
                        "note": "" if kind == "ia" else "O gerador de capas com IA não está instalado; esta é a capa alternativa, desenhada com emojis.",
                        "image": "data:image/png;base64," + base64.b64encode(COVER).decode()}
        elif path == "/api/cover/apply":
            page, st = next(x for x in W["cov_pages"] if x["id"] == body["page_id"]), W.get("cov_apply", "confirmed")
            data = ({"changed": True, "page": {**page, "cover": "external:https://www.notion.so/images/page-cover/woodcuts_1.jpg"}} if st == "changed"
                    else {"state": st, "page": {**page, "cover": "file:prod-files-secure.s3.amazonaws.com/ws/novo/capa.png"} if st == "confirmed" else page})
        elif path == "/api/catalog/course":
            c = {"id": "c-new", "name": body["name"], "platform": body.get("platform") or "", "url": "",
                 "notion_page_id": "p-new" if body.get("decorate") else None, "modules": []}
            W["courses"].append(c)
            data = {"course": c, "note": None, "cover": {"kind": W.get("cover_kind", "ia"), "confirmed": True} if body.get("decorate") else None}
        elif path == "/api/catalog/module":
            c = next(x for x in W["courses"] if x["id"] == body["course_id"])
            m = {"id": "m-new", "name": body["name"], "order": int(body["order"]) if body.get("order") else None, "notion_page_id": None}
            c["modules"].append(m)
            data = {"module": m, "note": None}
        elif path == "/api/migration":
            if r.request.method == "POST":
                W["job"] = {"status": "done", "kind": "migrate", "result": {"migration": {"moved": len(W["migration"]["lessons"])}}}
                W["migration"] = {"lessons": [], "folders": []}
                data = W["job"]
            else: data = W["migration"]
        elif path == "/api/reviews": data = {"items": W["reviews"]}
        elif path == "/api/courses": data = {"courses": W["pages"], "root_ok": True, "root": W["config"]["root_page_id"]}
        elif path == "/api/notion/pages": data = {"pages": W["pages"]}
        elif path == "/api/inspect": data = W["found"]
        elif path == "/api/understanding": data = W["docs"].get(q.get("key"), W["docs"]["k1"])
        elif path == "/api/understanding/draft":
            d = W["docs"].get(body.get("key"))
            if d: d.update(text=body.get("text", ""), at=body.get("at", 0))
            data = d or {}
        elif path == "/api/review": data = {**W["review"], "key": q.get("key", W["review"]["key"])}
        # o fluxo de uma aula, com estado (para o percurso de ponta a ponta)
        elif path == "/api/record/start":
            W["recording"] = {"active": True, "seconds": 0, "level": .3, "heard": True, "paused": False, "screens": {"seen": 0}}
            data = W["recording"]
        elif path in ("/api/record/pause", "/api/record/resume"):
            W["recording"].update(paused=path.endswith("pause"), paused_for=0)
            data = W["recording"]
        elif path == "/api/record/stop":
            W["recording"] = {"active": False, "seconds": 0, "level": 0, "heard": False, "paused": False}
            data = {"path": "C:/Lumen/aula.wav", "name": "Aula de 24-10.wav", "warning": None}
        elif path == "/api/start":  # a preparação termina na hora: a aula k1 espera a compreensão
            W["job"] = {"status": "done", "kind": "process", "key": "k1", "result": {"review": True, "key": "k1", "title": W["docs"]["k1"]["title"]}}
            data = W["job"]
        elif path == "/api/understanding/submit":  # a IA analisa na hora
            k = body["key"]
            W["docs"][k].update(state="completed", analysis=W["docs"]["k2"]["analysis"], analyzed_text=body["text"], original=body["text"],
                                submitted=iso(), model="qwen3:8b", ready={"phase": "completed", "label": "Análise concluída", "tone": "ok", "detail": ""})
            W["job"] = {"status": "done", "kind": "analyze", "spec": {"key": k}, "result": {"analysis": True, "key": k}}
            data = {}
        elif path == "/api/finish":
            W["job"] = {**copy.deepcopy(globals()["DONE"]), "result": {**DONE["result"], "key": body.get("key") or "k1"}}
            data = W["job"]
        elif path == "/api/settings" and W.get("settings_fail"):  # o ajuste não foi salvo: a tela volta ao que vale
            code, data = 400, {"error": {"message": "Não foi possível salvar o ajuste.", "action": "Tente de novo."}}
        elif path == "/api/settings":
            W["config"].update({k: v for k, v in body.items() if k in W["config"]})
            data = {"config": W["config"], "has_token": W["has_token"]} if q.get("view") == "settings" else state_of(W)
        r.fulfill(status=code, content_type="application/json", body=json.dumps(data))
    return route


HOST = ("window.messages=[];window.hostListeners=[];window.chrome=window.chrome||{};"
        "window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,f)=>hostListeners.push(f)};")

# Problemas que a tela não pode ter, conferidos em cada captura.
CHECKS = r"""(z) => {
  const out = [], vw = innerWidth, vh = innerHeight;
  const seen = (e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05 && s.clipPath === "none" && !e.closest("[hidden],[inert],.sr"); };
  const name = (e) => (e.id ? "#" + e.id : e.tagName.toLowerCase() + (e.className && typeof e.className === "string" ? "." + e.className.split(" ").filter(Boolean).join(".") : ""))
    + (e.textContent.trim() ? ` “${e.textContent.trim().slice(0, 24)}”` : "");
  for (const el of [document.scrollingElement, ...document.querySelectorAll(".content, .view, main")])
    if (el && el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "hidden") out.push(`rolagem horizontal em ${name(el)} (${el.scrollWidth} > ${el.clientWidth})`);
  const scroller = (e) => { for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowY; if (o === "auto" || o === "scroll") return p; } return null; };
  for (const e of document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=tab], [role=switch]")) {
    if (!seen(e) || e.matches("#peek")) continue;  // a alça recolhida (12×84) é a própria janela: o hover nela abre a barra
    const r = e.getBoundingClientRect(), box = scroller(e)?.getBoundingClientRect();
    const inline = e.matches(".link-btn, .crumb") || getComputedStyle(e).display === "inline";
    if (!inline && (r.width / z < 23.5 || r.height / z < 19.5) && !e.matches("input[type=checkbox], input[type=radio]")) out.push(`alvo pequeno ${Math.round(r.width / z)}×${Math.round(r.height / z)}: ${name(e)}`);
    const clipL = box ? Math.max(0, box.left) : 0, clipR = box ? Math.min(vw, box.right) : vw;
    if (r.right > clipR + 1 && r.left < clipR - 1) out.push(`cortado à direita: ${name(e)}`);
    if (r.left < clipL - 1 && r.right > clipL) out.push(`cortado à esquerda: ${name(e)}`);
  }
  for (const e of document.querySelectorAll("h1, h2, h3, .btn, .badge, .rail-item span, .stepper li")) {
    if (!seen(e)) continue;
    const s = getComputedStyle(e);
    if (e.scrollWidth > e.clientWidth + 1 && s.textOverflow !== "ellipsis" && s.overflow !== "visible") out.push(`texto cortado: ${name(e)}`);
  }
  return out;
}"""


class Harness:
    def __init__(self, browser, url, out, zoom=1.0):
        self.browser, self.url, self.out, self.zoom = browser, url, out, zoom
        self.problems, self.shots, self.errors = {}, [], []

    def open(self, kind, w, h, patch=None, query=""):
        W = world()
        if patch: patch(W)
        log = []
        ctx = self.browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, reduced_motion="no-preference")
        ctx.add_init_script(HOST)
        ctx.route("**/api/**", router(W, log))
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("requestfailed", lambda r: errs.append(f"falhou {r.url}"))
        path = {"main": "/?frame=1", "widget": "/widget", "note": "/note?key=k1", "design": "/design"}[kind] + query
        page.goto(self.url + path)
        page.wait_for_load_state("load")  # networkidle nunca chega com a gravação ativa (o Lumen consulta a cada 220 ms)
        ready = {"main": "() => typeof S !== 'undefined' && S !== null && typeof historyItems !== 'undefined'",
                 "widget": "() => typeof state !== 'undefined' && state !== null"}.get(kind)
        if ready:
            page.wait_for_function(ready, timeout=10000)
        if self.zoom != 1 and kind == "main":  # zoom da página (Ctrl + roda); a barra e a nota têm tamanho físico fixo (DPI no C#)
            page.evaluate(f"document.documentElement.style.zoom = {self.zoom}")
        page.wait_for_timeout(300)
        page.evaluate("document.fonts.ready")
        return ctx, page, W, log, errs

    def shot(self, name, kind, w, h, setup="", patch=None, query=""):
        ctx, page, W, log, errs = self.open(kind, w, h, patch, query)
        try:
            if setup:
                page.evaluate(f"async () => {{ {setup} }}")
            page.wait_for_timeout(450)
            tag = f"{name}-{w}x{h}" + (f"@{int(self.zoom * 100)}" if self.zoom != 1 else "")
            file = self.out / f"{tag}.png"
            page.screenshot(path=str(file), animations="disabled")
            found = page.evaluate(CHECKS, self.zoom if kind == "main" else 1) + [f"erro de página: {e}" for e in errs if "favicon" not in e]
            if found: self.problems[tag] = found
            self.shots.append(file)
            return page
        finally:
            ctx.close()


def serve():
    data = tempfile.mkdtemp(prefix="lumen-ui-shots-")
    env = {**os.environ, "LUMEN_DATA": data,
           "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c",
                             "from lumen import server; h=server.serve(); print(h.server_port, flush=True); h.serve_forever()"],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
    proc.data = data  # apagada ao terminar (o C: costuma estar cheio)
    return proc, "http://127.0.0.1:" + proc.stdout.readline().strip()


def run(scenarios, filters=(), sizes=((1120, 860),), zooms=(1.0,), out=OUT):
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    proc, url = serve()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            total = {}
            for zoom in zooms:
                h = Harness(browser, url, out, zoom)
                for name, kind, setup, patch, own in scenarios:
                    if filters and not any(f in name for f in filters) or zoom != 1 and kind != "main":
                        continue
                    for w, hh in ([own] if own else sizes):
                        try:
                            h.shot(name, kind, w, hh, setup, patch)
                        except Exception as e:  # um cenário quebrado não esconde os outros
                            h.problems[f"{name}-{w}x{hh}"] = [f"falhou: {str(e).splitlines()[0]}"]
                total.update(h.problems)
                print(f"zoom {int(zoom * 100)}%: {len(h.shots)} capturas")
            browser.close()
    finally:
        proc.kill()
        proc.wait(timeout=10)
        shutil.rmtree(proc.data, ignore_errors=True)
    for tag, found in total.items():
        print(f"\n{tag}:")
        for f in dict.fromkeys(found):
            print("  -", f)
    print(f"\n{len(total)} capturas com problema" if total else "\nnenhum problema encontrado")
    return 1 if total else 0


# ---------------------------------------------------------------------------------------------------------------
# Cenários: (nome, página, JS de preparo, mudança no estado simulado, tamanho fixo ou None = todos os tamanhos)
POMO = {"phase": "focus", "running": True, "left": 1122, "total": 1500, "done": 1, "event": None,
        "settings": {"focus": 25, "short": 5, "long": 15, "cycles": 4, "auto": False, "sound": True}}
REC = {"active": True, "seconds": 754, "level": .28, "heard": True, "paused": False, "screens": {"seen": 6, "read": 4, "kept": 3}}
JOB = {"status": "running", "kind": "process", "stage": "generate", "detail": "Escrevendo o material a partir da sua compreensão",
       "progress": .42, "eta_total": 95, "dests": ["obsidian", "notion"], "skipped": ["transcribe"], "title": "Redes neurais convolucionais", "key": "k1"}
DONE = {"status": "done", "kind": "process", "dests": ["obsidian", "notion"], "result": {
    "key": "k2", "title": "Complexidade de algoritmos e notação O", "course": "Estudos › Inteligência Artificial",
    "notion": {"status": "ok", "url": "https://notion.so/x", "understanding_url": "https://notion.so/y"},
    "obsidian": {"status": "ok", "note": "n.md", "canvas": "c.canvas", "board": "p.canvas", "board_images": 8, "connections": 4,
                 "questions": 12, "state": "created"}}}


VIS = {"state": "ok", "mode": "animated", "kind": "gif", "file": "0123456789abcdef.gif", "png": "0123456789abcdef.png",
       "describe": "Sistema · 5 componentes da aula e 3 relações", "notion": "confirmed",
       "obsidian": {"file": "Estudos/x/Anexos/visualização 3d · x.gif"}}
DONE_VIS = {**DONE, "result": {**DONE["result"], "visual": VIS}}
DONE_VIS_PNG = {**DONE, "result": {**DONE["result"], "visual": {**VIS, "kind": "png", "file": "0123456789abcdef.png",
                                                                    "state": "static-fallback", "reason": "peso"}}}
DONE_VIS_FAIL = {**DONE, "result": {**DONE["result"], "visual": {"state": "failed", "mode": "animated",
                                                                     "reason": "o desenho falhou (RuntimeError)"}}}
VCHK = (' const f = $("#result .v3d-preview"), img = f && f.querySelector("img"), src = f && f.querySelector("source");'
        ' if (!img || !img.alt.startsWith("Visualização 3D gerada pelo Lumen") || !src || src.media !== "(prefers-reduced-motion: reduce)"'
        ' || !src.srcset.includes("kind=png") || !f.textContent.includes("Animação (GIF)")'
        ' || Math.abs(img.getBoundingClientRect().width / img.getBoundingClientRect().height - 16 / 9) > 0.05'
        ' || (f.getBoundingClientRect().width > 700 && img.getBoundingClientRect().width > f.getBoundingClientRect().width * 0.5))'
        ' throw new Error("prévia da visualização 3D fora do esperado: " + JSON.stringify({img: !!img, alt: img && img.alt.slice(0, 30), media: src && src.media, srcset: src && src.srcset.slice(0, 40), w: img && img.getBoundingClientRect().width, txt: f && f.textContent.slice(0, 60)}));')


def run_js(job, url="/api/finish"):
    return f'showView("new"); lastUrl="{url}"; lastSpec={{kind:"recording"}}; showStep("run"); renderJob({json.dumps(job)}); renderStatus();'


def patch(**kv):
    return lambda W: W.update(copy.deepcopy(kv))


def no_data(W):
    W.update(pending=[], history=[], reviews=[])


def first_use(W):
    no_data(W)
    W.update(has_token=False)
    W["config"].update(root_page_id="", root_page_title="", obsidian_vault="")
    W["ollama"]["installed"] = False
    W["obsidian"].update(folder="")


def dest(cfg=None, obsidian=None, **kv):  # estados dos Destinos do estudo
    def f(W):
        W["config"].update(cfg or {})
        W["obsidian"].update(obsidian or {})
        W.update(kv)
    return f


def long_path(W):
    W["config"].update(obsidian_vault=r"C:\Users\Estudante\Documents\Segundo Cérebro da Faculdade de Engenharia",
                       obsidian_folder="B03 Resources/Estudos/Engenharia de Computação/Semestre 2026-2/Lumen")
    W["obsidian"].update(vaults=[{"path": W["config"]["obsidian_vault"], "name": "Segundo Cérebro da Faculdade de Engenharia", "open": True, "ok": True}],
                         folder=W["config"]["obsidian_folder"])


def notion_fail(W):
    W["job"] = copy.deepcopy(DONE)
    W["job"]["result"]["notion"] = {"status": "error", "error": "O Notion recusou o pedido (limite de envio).", "action": "Tente de novo em 1 minuto."}


UNDER = 'showView("new"); await openUnderstanding("k1");'
WOPEN = 'document.body.dataset.expanded="true";'
# Revisões espaçadas: ligadas, os intervalos e onde as datas aparecem; desligadas, só o switch e o aviso das notas antigas
REV_ON = (' const iv = $("#review-intervals").closest(".field"); if ($("#obs-review").closest(".set-row").querySelector("strong").textContent !== "Incluir revisões espaçadas"'
          ' || !$("#obs-review").checked || !$("#obs-quick [data-cfg=obsidian_review]").checked || getComputedStyle(iv).display === "none" || $("#review-intervals").disabled'
          ' || $("#review-intervals").value !== "1, 3, 7, 14, 30, 60" || !$("#review-intervals-hint").textContent.includes("Revisões")) throw new Error("revisões ligadas sem os intervalos");')
REV_OFF = (' if ($("#obs-review").checked || $("#obs-quick [data-cfg=obsidian_review]").checked || getComputedStyle($("#review-intervals").closest(".field")).display !== "none"'
           ' || getComputedStyle($("#review-intervals-hint")).display !== "none" || !$("#obs-review-scope").textContent.includes("As notas existentes permanecem")'
           ' || $("#review-intervals").value !== "1, 3, 7, 14, 30, 60") throw new Error("revisões desligadas mostrando intervalos (ou perdendo-os)");')
# Nova aula → botão Capa do cartão do Notion
QCHK = (' $("#dest-notion").scrollIntoView({block: "center"}); await new Promise(r=>setTimeout(r,100)); const b = $("#dest-notion-cover"), card = $("#dest-notion").getBoundingClientRect(), r = b.getBoundingClientRect(), path = $("#dest-path").getBoundingClientRect(), badge = $("#dest-notion-badge").getBoundingClientRect();'
        ' if (!b.closest("#dest-notion .dest-line2") || r.right > card.right + 1 || badge.right > card.right + 1 || (path.width && path.right > r.left + 1) || b.getAttribute("aria-haspopup") !== "dialog")'
        ' throw new Error("o botão Capa fora do lugar, sobre o caminho ou o selo");')
QOPEN = ('showView("new"); await loadCatalog(); $("#yt-url").value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"; setOrg(ORG);'
         ' await new Promise(r=>setTimeout(r,300)); $("#dest-notion").scrollIntoView(); const top0 = $("#content").scrollTop, calls = [], real = api; api = (u, b) => (calls.push(u), real(u, b));'
         ' $("#dest-notion-cover").click(); await new Promise(r=>setTimeout(r,300)); if (!covDlg.open || view !== "new") throw new Error("o diálogo não abriu na Nova aula");')
SCENARIOS = [
    ("home", "main", "", None, None),
    ("home-first", "main", "", first_use, None),
    ("home-rec", "main", "", patch(recording=REC), None),
    ("home-job", "main", 'lastUrl="/api/finish"; showView("home"); poll();', patch(job=JOB), None),
    ("new-compose", "main", 'showView("new");', None, None),
    ("new-ready", "main", 'showView("new"); picked.recording={path:"C:/aula.wav",name:"Aula.wav"}; setRecState("done","Gravar de novo"); await inspect();', None, None),
    ("new-recording", "main", 'showView("new");', patch(recording=REC), None),
    ("new-paused", "main", 'showView("new");', patch(recording={**REC, "paused": True, "paused_for": 42}), None),
    ("new-recover", "main", 'showView("new");', patch(recording={"active": False, "seconds": 0, "recovered": {"seconds": 1234}}), None),
    ("new-file", "main", 'showView("new"); $("#tab-file").click();', None, None),
    ("new-captures", "main", 'showView("new"); $("#tab-captures").click(); await addCaps([{path:"C:/a.png",name:"slide 1.png"},{path:"C:/b.png",name:"código.png"},{path:"C:/c.png",name:"tabela.png"}]);', None, None),
    ("new-org-course", "main", 'showView("new"); await loadCatalog(); setOrg({type:"course",course_id:"c-ia",module_id:"m-dl",lesson:7}); await new Promise(r=>setTimeout(r,300));', None, None),
    ("new-org-suggest", "main", 'showView("new"); await loadCatalog(); await new Promise(r=>setTimeout(r,300));', patch(last={"type": "course", "course_id": "c-ia", "module_id": "m-dl", "lesson": 7, "at": "2099-01-01T00:00:00"}), None),
    ("new-org-dialog", "main", 'showView("new"); await loadCatalog(); openOrg({type:"course",course_id:"c-ia",module_id:"m-dl",lesson:7}); await new Promise(r=>setTimeout(r,400));', None, None),
    ("new-org-newcourse", "main", 'showView("new"); await loadCatalog(); openOrg({type:"course"}); $("#org-new-course").click(); const n=$("#org-course-name"); n.value="inteligencia artificial"; n.dispatchEvent(new Event("input")); await new Promise(r=>setTimeout(r,300));', None, None),
    # Capa no Notion (novo curso): desligada, pronta para gerar, gerando, prévia pronta (IA ou alternativa), nome mudado e erro
    *[(f"new-org-cover{n}", "main", 'showView("new"); await loadCatalog(); openOrg({type:"course"}); $("#org-new-course").click();'
       ' const n=$("#org-course-name"); n.value="Redes neurais convolucionais"; n.dispatchEvent(new Event("input"));' + js, p, None) for n, js, p in (
        ("", '', None),
        ("-on", ' $("#org-decorate").click();', None),
        ("-busy", ' $("#org-decorate").click(); const real = api; api = (u, b) => u === "/api/decor/preview" ? new Promise(() => {}) : real(u, b); genCover();'
                  ' await new Promise(r=>setTimeout(r,100)); if (!$("#org-course-create").disabled || !$("#org-cover-gen").disabled) throw new Error("dá para criar ou gerar durante a geração");', None),
        ("-ready", ' $("#org-decorate").click(); await genCover(); if ($("#org-course-create").disabled || $("#org-cover-pic").hidden || !$("#org-cover-pic").naturalWidth || !$("#org-cover-pic").alt.includes("Redes neurais")) throw new Error("prévia sem criar ou sem texto alternativo");', None),
        ("-emojis", ' $("#org-decorate").click(); await genCover();', patch(cover_kind="emojis")),
        # nem IA nem emojis: sem imagem, e a prévia diz que vai a capa de cor do Notion (nenhuma imagem antiga fica à vista)
        ("-noimage", ' $("#org-decorate").click(); await genCover(); if (!$("#org-cover-pic").hidden || !$("#org-cover-wait").textContent.includes("capa de cor do Notion")) throw new Error("prévia sem imagem parece ter imagem");',
         patch(cover_kind="notion")),
        ("-stale", ' $("#org-decorate").click(); await genCover(); n.value="Redes neurais recorrentes"; n.dispatchEvent(new Event("input"));'
                   ' if (!$("#org-course-create").disabled) throw new Error("a prévia de outro nome ainda cria");', None),
        ("-error", ' $("#org-decorate").click(); await genCover(); const real = api; api = (u, b) => u === "/api/decor/preview" ? Promise.reject(Object.assign(new Error("O Ollama não está rodando."), {action: "Abra o Ollama e tente de novo."})) : real(u, b);'
                   ' await genCover(); if ($("#org-cover-pic").hidden || $("#org-course-create").disabled || !$("#org-cover-state").textContent.includes("anterior continua")) throw new Error("a falha apagou a prévia válida");', None))],
    ("new-org-free", "main", 'showView("new"); await loadCatalog(); openOrg({type:"free",category:"História"}); await new Promise(r=>setTimeout(r,400));', None, None),
    ("new-dest-quick", "main", 'showView("new"); $("#dest-obs-change").click();', None, None),
    ("new-dest-novault", "main", 'showView("new");', dest({"obsidian_vault": ""}, {"folder": ""}), None),
    ("new-dest-vaulterr", "main", 'showView("new");', dest(obsidian={"error": "A pasta do cofre não foi encontrada: C:\\Users\\Estudante\\Cérebro. Escolha o cofre de novo em Integrações."}), None),
    ("new-dest-notoken", "main", 'showView("new");', dest(has_token=False), None),
    ("new-dest-none", "main", 'showView("new");', first_use, None),
    ("new-dest-notion", "main", 'showView("new");', dest({"destinations": "notion"}), None),
    ("new-dest-obsidian", "main", 'showView("new");', dest({"destinations": "obsidian"}), None),
    ("new-dest-nocanvas", "main", 'showView("new");', dest({"obsidian_canvas": False}), None),
    ("new-dest-long", "main", 'showView("new");', long_path, None),
    ("understand", "main", UNDER, None, None),
    ("understand-rec", "main", UNDER, patch(recording=REC), None),
    ("understand-prep", "main", UNDER + ' U.state="studying"; renderUStatus({status:"running",kind:"process",key:"k1",stage:"transcribe",detail:"Transcrevendo (3 de 9 min)",progress:.33});', None, None),
    ("understand-ai", "main", UNDER + ' U.state="processing_with_ai"; renderUnderstanding(); renderUStatus({status:"running",kind:"analyze",key:"k1",spec:{key:"k1"},detail:"Lendo a aula por partes (1 de 3)",eta_total:42});', None, None),
    ("analysis", "main", 'showView("new"); await openUnderstanding("k2");', None, None),
    ("analysis-review", "main", 'showView("new"); await openUnderstanding("k2"); $("#review-more").open=true;', None, None),
    ("run-prep", "main", run_js({**JOB, "stage": "transcribe", "detail": "Transcrevendo no PC (12 de 45 min)", "progress": .27, "skipped": []}, "/api/start"), None, None),
    ("run", "main", run_js(JOB), None, None),
    ("run-indeterminate", "main", run_js({**JOB, "stage": "publish", "detail": "Enviando ao Notion", "progress": None}), None, None),
    ("run-done", "main", run_js(DONE), None, None),
    ("run-done-visual", "main", run_js(DONE_VIS) + VCHK, None, None),
    ("run-done-visual-png", "main", run_js(DONE_VIS_PNG) + ' if ($("#result .v3d-preview source") || !$("#result").textContent.includes("Imagem estática (PNG)")) throw new Error("reserva estática sem aviso");', None, None),
    ("run-done-visual-failed", "main", run_js(DONE_VIS_FAIL) + ' if ($("#result .v3d-preview") || !$("#result").textContent.includes("não saiu")) throw new Error("falha do visual sem aviso");', None, None),
    ("run-partial", "main", 'showView("new"); lastUrl="/api/finish"; lastSpec={kind:"recording"}; showStep("run"); renderJob(await api("/api/job"));', notion_fail, None),
    ("run-error", "main", run_js({"status": "error", "kind": "process", "stage": "generate", "error": {"message": "A IA local não respondeu.", "action": "Abra o Ollama e tente de novo."}}), None, None),
    ("run-cancel", "main", run_js({"status": "cancelled", "kind": "process", "stage": "generate"}), None, None),
    ("library", "main", 'showView("library");', None, None),
    ("library-empty", "main", 'showView("library");', no_data, None),
    ("library-loading", "main", 'loadHistory = () => new Promise(() => {}); historyItems = null; showView("library");', None, None),  # lista ainda chegando
    ("library-none", "main", 'showView("library"); const s=$("#lib-search"); s.value="quântica"; s.dispatchEvent(new Event("input"));', None, None),
    ("library-courses", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); $("#lib-filter [data-f=course]").click();', None, None),
    ("library-course", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); openCourse("c-ia");', None, None),
    ("library-inbox", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); $("#lib-filter [data-f=inbox]").click();', None, None),
    ("library-review", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); $("#lib-filter [data-f=review]").click();', None, None),
    ("library-filters", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); $("#lib-more").click();', None, None),
    ("library-organize", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); const it=historyItems.find(x=>x.key==="h4"); openOrg(it.classification, it); await new Promise(r=>setTimeout(r,400));', None, None),
    ("integrations", "main", 'showView("integrations");'
     ' if (!$("#v3d-mode input[value=animated]").checked || $("#v3d-mode").closest(".v3d-set").querySelector("details").open) throw new Error("Visualização 3D: padrão Animada, detalhes recolhidos");', None, None),
    ("integrations-v3d-static", "main", 'showView("integrations"); $(".v3d-tech").open = true;'
     ' if (!$("#v3d-mode input[value=static]").checked) throw new Error("Visualização 3D estática não marcada");', dest({"visual_3d": "static"}), None),
    ("integrations-off", "main", 'showView("integrations");', first_use, None),
    ("integrations-obsidian", "main", 'goIntegrations("obsidian");', None, None),
    ("integrations-obsidian-off", "main", 'goIntegrations("obsidian");', first_use, None),
    ("integrations-obsidian-noboard", "main", 'goIntegrations("obsidian");', dest({"obsidian_attachments": False, "obsidian_review": False}), None),
    # Revisões espaçadas opcionais: um switch só (Integrações e ajuste rápido), intervalos guardados, nada cobrado desligado
    ("rev-on", "main", 'goIntegrations("obsidian"); $("#obs-review").scrollIntoView({block: "center"});' + REV_ON, None, None),
    ("rev-off", "main", 'goIntegrations("obsidian"); $("#obs-review").scrollIntoView({block: "center"});' + REV_OFF, dest({"obsidian_review": False}), None),
    ("rev-toggle", "main", 'goIntegrations("obsidian"); $("#obs-review").scrollIntoView({block: "center"}); $("#obs-review").click(); await new Promise(r=>setTimeout(r,300));'
     ' if (S.config.obsidian_review || JSON.stringify(S.config.review_intervals) !== "[1,3,7,14,30,60]" || $$("[data-cfg=obsidian_review]").some(i => i.checked)) throw new Error("desligar não salvou, perdeu os intervalos ou deixou um switch ligado");'
     ' $("#obs-review").click(); await new Promise(r=>setTimeout(r,300));' + REV_ON, None, None),
    ("rev-fail", "main", 'goIntegrations("obsidian"); $("#obs-review").scrollIntoView({block: "center"}); $("#obs-review").click(); await new Promise(r=>setTimeout(r,400));'
     ' if (!$("#obs-review").checked || !S.config.obsidian_review || getComputedStyle($("#review-intervals").closest(".field")).display === "none") throw new Error("a tela mostra uma preferência que não foi salva");'
     ' $$(".toast").forEach(t => t.remove());', patch(settings_fail=True), None),
    ("rev-quick-off", "main", 'showView("new"); $("#dest-obs-change").click(); await new Promise(r=>setTimeout(r,200));'
     ' const q = $("#obs-quick [data-cfg=obsidian_review]"); if (q.closest(".set-row").textContent.trim() !== "Incluir revisões espaçadas") throw new Error("rótulo do ajuste rápido");'
     ' q.click(); await new Promise(r=>setTimeout(r,300)); if (S.config.obsidian_review || $("#obs-review").checked || q.checked || $("#dest-obs-help").dataset.tip.includes("revisão")) throw new Error("ajuste rápido e Integrações fora de sincronia");'
     ' $("#dest-obs-change").scrollIntoView({block: "center"});', None, None),
    ("rev-library-off", "main", 'showView("library"); await new Promise(r=>setTimeout(r,200)); $("#lib-more").click();'
     ' if (!$("#lib-filter [data-f=review]").hidden || !$("#lf-review").closest(".field").hidden || historyItems.some(isDue) || /revisão (hoje|atrasada)/.test($("#library-list").textContent))'
     ' throw new Error("a Biblioteca ainda cobra revisões desligadas");', dest({"obsidian_review": False}), None),
    ("rev-home-off", "main", 'showView("home"); await new Promise(r=>setTimeout(r,300)); if (!$("#home-reviews").hidden) throw new Error("cartão de revisões com a função desligada");',
     dest({"obsidian_review": False}), None),
    ("integrations-notion-only-obsidian", "main", 'goIntegrations("notion");', dest({"destinations": "obsidian"}), None),
    ("integrations-migration", "main", 'goIntegrations("obsidian"); await new Promise(r=>setTimeout(r,400));',
     patch(migration={"area": "B02 Estudos", "folders": ["C04 Claude Obsidian/16 Lumen"], "dashboards": [], "lessons": [
         {"title": "Criando Vídeos 3D Automatizados com Cloud e IA", "target": "B02 Estudos/90 - A organizar/Criando Vídeos 3D", "canvas": True, "board": False, "attachments": 3, "shared": 0},
         {"title": "Edição de Vídeos com IA Guia Prático e Personalizado", "target": "B02 Estudos/90 - A organizar/Edição de Vídeos", "canvas": True, "board": True, "attachments": 6, "shared": 0}]}), None),
    # Google Drive: o cartão de Integrações (cada estado da conta da Proteção)
    *[(f"drive-card{n}", "main", 'goIntegrations("drive"); await new Promise(r=>setTimeout(r,300));' + js, p, None) for n, js, p in (
        ("", "", None), ("-client", "", drive_card({"client": True})),
        ("-waiting", "", drive_card({"client": True, "login": "waiting"})),
        # a consulta a cada 2 s do login continua e não trava a tela
        ("-waiting-poll", ' const real = api; window.polls = 0; api = (p, b) => { if (p === "/api/drive") polls++; return real(p, b); };'
                          ' await new Promise(r => setTimeout(r, 4600)); if (polls < 2) throw new Error(`a consulta não repetiu (${polls})`);',
         drive_card({"client": True, "login": "waiting"})),
        ("-error", "", drive_card({"client": True, "login": "error", "error": "Sem resposta do Google. Confira a internet e tente de novo."})),
        ("-expired", "", drive_card({"client": True, "expired": True, "login": "idle"})),
        ("-connected", "", drive_card({"client": True, "connected": True, "login": "ok", "email": "estudante@gmail.com"})),
        ("-loading", ' DRV = null; renderDriveCard();', None),
        ("-load-error", ' DRV = { error: { message: "Não foi possível ler o estado do Drive.", action: "Tente de novo." } }; renderDriveCard();', None))],
    # Capas do Notion: escolher a página (busca, link), gerar, aplicar; cada estado com a sua única ação principal
    *[(f"covers{n}", "main", 'await covOpen(); await new Promise(r=>setTimeout(r,200));' + js, p, None) for n, js, p in (
        ("-start", ' if (!$("#cov-list [role=option]") || $("#cov-more").hidden) throw new Error("sem as páginas recentes ou sem Carregar mais");', None),
        ("-more", ' $("#cov-more").click(); await new Promise(r=>setTimeout(r,200)); if ($$("#cov-list [role=option]").length !== 7) throw new Error("Carregar mais não juntou a 2ª leva");', None),
        ("-search", ' const q=$("#cov-q"); q.value="notas"; q.dispatchEvent(new Event("input")); await new Promise(r=>setTimeout(r,500));'
                    ' const t=$("#cov-list").textContent; if (!t.includes("Pessoal") || !t.includes("Trabalho")) throw new Error("nomes iguais sem a mãe");', None),
        ("-empty", ' const q=$("#cov-q"); q.value="xyz"; q.dispatchEvent(new Event("input")); await new Promise(r=>setTimeout(r,500));'
                   ' if (!$("#cov-list-msg").textContent.includes("Nenhuma página")) throw new Error("lista vazia sem aviso");', None),
        ("-searchfail", ' if ($("#cov-retry").hidden) throw new Error("erro sem Tentar de novo");', patch(cov_search_fail=True)),
        ("-noaccess", ' const q=$("#cov-q"); q.value="https://www.notion.so/Privada-0123456789abcdef0123456789abcdef"; q.dispatchEvent(new Event("input")); await new Promise(r=>setTimeout(r,300));'
                      ' if (!$("#cov-list-msg").textContent.includes("Conexões") || cv.page) throw new Error("página sem acesso sem explicação");', None),
        ("-nocover", ' await covPickRef("pg-orc"); if ($("#cov-gen").textContent !== "Gerar capa" || !$("#cov-gen").classList.contains("primary") || !$("#cov-main").hidden) throw new Error("ação principal errada");', None),
        ("-hascover", ' await covPickRef("pg-notas-2"); if (!$("#cov-page-badge").textContent.includes("Tem capa")) throw new Error("sem indicar a capa atual");', None),
        ("-row", ' await covPickRef("pg-luz");', None),
        ("-long", ' await covPickRef("pg-longo");', None),
        ("-busy", ' await covPickRef("pg-orc"); const real = api; api = (u, b) => u === "/api/cover/preview" ? new Promise(() => {}) : real(u, b); covGen();'
                  ' await new Promise(r=>setTimeout(r,100)); if (!$("#cov-gen").disabled || $("#cov-progress").hidden || !$("#cov-main").hidden) throw new Error("dá para agir durante a geração");', None),
        ("-ready", ' await covPickRef("pg-orc"); await covGen(); if ($("#cov-main").textContent !== "Aplicar capa" || $("#cov-pic").hidden || !$("#cov-pic").naturalWidth || !$("#cov-pic").alt.includes("Orçamento")) throw new Error("prévia sem Aplicar ou sem texto alternativo");', None),
        ("-emojis", ' await covPickRef("pg-orc"); await covGen();', patch(cover_kind="emojis")),
        ("-replace", ' await covPickRef("pg-notas-2"); await covGen(); if ($("#cov-main").textContent !== "Substituir capa") throw new Error("a substituição não está explícita");', None),
        ("-stale", ' await covPickRef("pg-orc"); await covGen(); const t=$("#cov-theme"); t.value="Uma ilustração de um cofrinho"; t.dispatchEvent(new Event("input"));'
                   ' if (!$("#cov-main").hidden || !$("#cov-gen").classList.contains("primary")) throw new Error("a prévia de outro tema ainda aplica");', None),
        ("-fail", ' await covPickRef("pg-orc"); await covGen(); if ($("#cov-gen").textContent !== "Tentar de novo" || !$("#cov-main").hidden) throw new Error("falha sem Tentar de novo");', patch(cover_fail=True)),
        ("-failkeeps", ' await covPickRef("pg-orc"); await covGen(); const real = api; api = (u, b) => u === "/api/cover/preview" ? Promise.reject(Object.assign(new Error("O Ollama não está rodando."), {action: "Abra o Ollama e tente de novo."})) : real(u, b);'
                       ' await covGen(); if ($("#cov-pic").hidden || $("#cov-main").hidden || !$("#cov-state").textContent.includes("anterior continua")) throw new Error("a falha apagou a prévia válida");', None),
        ("-done", ' const before = JSON.stringify(org), calls = [], real = api; api = (u, b) => (calls.push(u), real(u, b));'
                  ' await covPickRef("pg-orc"); await covGen(); await covApply();'
                  ' if (!$("#cov-state").textContent.includes("Capa aplicada em “Orçamento doméstico 2026”") || $("#cov-main").textContent !== "Abrir no Notion") throw new Error("sucesso sem confirmação ou sem Abrir no Notion");'
                  ' if (JSON.stringify(org) !== before || calls.some(u => /catalog|organize|finish|start/.test(u))) throw new Error("mexeu na aula ou criou curso: " + calls.join(" "));', None),
        ("-unconfirmed", ' await covPickRef("pg-orc"); await covGen(); await covApply(); if (!$("#cov-state").textContent.includes("Não foi possível confirmar") || $("#cov-main").textContent !== "Tentar de novo") throw new Error("incerto sem Tentar de novo");', patch(cov_apply="unconfirmed")),
        ("-mismatch", ' await covPickRef("pg-orc"); await covGen(); await covApply(); if ($("#cov-state").dataset.tone !== "error") throw new Error("capa antiga virou sucesso");', patch(cov_apply="mismatch")),
        ("-changed", ' await covPickRef("pg-orc"); await covGen(); await covApply(); if ($("#cov-main").textContent !== "Substituir capa" || !$("#cov-page-badge").textContent.includes("Tem capa")) throw new Error("a mudança da capa não foi mostrada");', patch(cov_apply="changed")),
        ("-off", ' if ($("#cov-off").hidden) throw new Error("sem token e sem o aviso");', patch(has_token=False)),
        # a resposta atrasada da página anterior não vira a prévia desta; o texto digitado fica nas atualizações
        ("-late", ' await covPickRef("pg-orc"); const real = api; api = (u, b) => u === "/api/cover/preview" ? new Promise(r => setTimeout(() => r(real(u, b)), 300)) : real(u, b);'
                  ' covGen(); await new Promise(r=>setTimeout(r,50)); $("#cov-page-change").click(); await covPickRef("pg-luz"); const t=$("#cov-theme"); t.value="Lâmpada acesa";'
                  ' await new Promise(r=>setTimeout(r,500)); renderSettings(); if (cv.pv || cv.page.id !== "pg-luz" || !$("#cov-pic").hidden || t.value !== "Lâmpada acesa") throw new Error("a prévia atrasada caiu na outra página");', None),
        ("-keyboard", ' const before = JSON.stringify(org), q=$("#cov-q"); q.focus(); q.value="conta"; q.dispatchEvent(new Event("input")); await new Promise(r=>setTimeout(r,500));'
                      ' q.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true})); if (q.getAttribute("aria-activedescendant") !== "cov-opt-0" || q.getAttribute("aria-expanded") !== "true") throw new Error("setas sem opção ativa");'
                      ' q.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true})); await new Promise(r=>setTimeout(r,100));'
                      ' if (cv.page?.id !== "pg-luz" || document.activeElement !== $("#cov-theme") || JSON.stringify(org) !== before) throw new Error("Enter não escolheu ou o foco se perdeu");', None))],
    # Nova aula → Destinos do estudo → Notion → Capa: o mesmo fluxo num diálogo, com a página real do destino (por ID)
    ("new-dest-cover", "main", 'showView("new"); await loadCatalog(); await new Promise(r=>setTimeout(r,300));' + QCHK, None, None),
    ("new-dest-cover-long", "main", 'showView("new"); await loadCatalog(); setOrg({type:"course",course_id:"c-ia",module_id:"m-dl"}); await new Promise(r=>setTimeout(r,400));' + QCHK,
     lambda W: W["courses"][0].update(name="Inteligência Artificial Generativa Aplicada a Negócios e Educação Corporativa"), None),
    ("new-dest-cover-off", "main", 'showView("new"); await new Promise(r=>setTimeout(r,300));' + QCHK, patch(has_token=False), None),
    *[(f"cover-quick{n}", "main", QOPEN.replace("ORG", org) + js, p, None) for n, org, js, p in (
        ("", '{type:"course",course_id:"c-ia"}', ' if (view !== "new" || cv.page?.id !== "p-ia" || document.activeElement !== $("#cov-gen") || calls.some(u => /catalog[/]|organize|settings/.test(u)))'
                                                 ' throw new Error("não abriu na Nova aula com a página do curso (ou mexeu na organização)");', None),
        ("-module", '{type:"course",course_id:"c-ia",module_id:"m-dl"}', ' if (cv.page?.id !== "p-dl" || !$("#cov-page-badge").textContent.includes("Tem capa")) throw new Error("a página do módulo não veio pelo ID");', None),
        ("-modnopage", '{type:"course",course_id:"c-ia",module_id:"m-fund"}', ' if (cv.page || !$("#cov-why-text").textContent.includes("módulo") || $("#cov-pick").hidden) throw new Error("módulo sem página virou a página do curso");', None),
        ("-free", '{type:"free",category:"História"}', ' if (cv.page || !$("#cov-why-text").textContent.includes("ainda não existe")) throw new Error("conteúdo gratuito sem a página certa");', None),
        ("-inbox", '{type:"inbox"}', ' if (cv.page || !$("#cov-why-text").textContent.includes("identificada")) throw new Error("A organizar adivinhou uma página");', None),
        ("-off", '{type:"course",course_id:"c-ia"}', ' if ($("#cov-off").hidden || !covDlg.open) throw new Error("sem conexão e sem o aviso no diálogo");', patch(has_token=False)),
        ("-busy", '{type:"course",course_id:"c-ia"}', ' const r2 = api; api = (u, b) => u === "/api/cover/preview" ? new Promise(() => {}) : r2(u, b); covGen(); await new Promise(r=>setTimeout(r,100));'
                  ' if (!$("#cov-gen").disabled || $("#cov-progress").hidden) throw new Error("dá para agir durante a geração");', None),
        ("-ready", '{type:"course",course_id:"c-ia",module_id:"m-dl"}', ' await covGen(); if ($("#cov-main").textContent !== "Substituir capa" || !$("#cov-state").textContent.includes("substitui a capa atual de “Deep Learning”")) throw new Error("a substituição não está explícita");', None),
        ("-error", '{type:"course",course_id:"c-ia"}', ' await covGen(); if ($("#cov-gen").textContent !== "Tentar de novo") throw new Error("falha sem Tentar de novo");', patch(cover_fail=True)),
        ("-done", '{type:"course",course_id:"c-ia"}', ' await covGen(); await covApply(); if (!$("#cov-state").textContent.includes("Capa aplicada em “Inteligência Artificial”") || $("#cov-main").textContent !== "Abrir no Notion") throw new Error("sucesso sem confirmação");', None),
        ("-unconfirmed", '{type:"course",course_id:"c-ia"}', ' await covGen(); await covApply(); if (!$("#cov-state").textContent.includes("Não foi possível confirmar")) throw new Error("incerto virou sucesso");', patch(cov_apply="unconfirmed")),
        # trocar a página da capa não muda a organização da aula, a configuração nem o destino do material
        ("-swap", '{type:"course",course_id:"c-ia"}', ' const o = JSON.stringify(org), cf = JSON.stringify(S.config); $("#cov-page-change").click(); await covPickRef("pg-orc"); await covGen(); await covApply();'
                  ' if (cv.page.id !== "pg-orc" || JSON.stringify(org) !== o || JSON.stringify(S.config) !== cf || calls.some(u => /catalog[/]|organize|settings|drive/.test(u))) throw new Error("trocar a página da capa mexeu na aula");', None),
        # fechar volta para a Nova aula como estava: link, gravação, rolagem e o foco no botão Capa
        ("-preserve", '{type:"course",course_id:"c-ia"}', ' await covGen(); await covApply(); covDlg.close(); await new Promise(r=>setTimeout(r,100));'
                      ' if (covDlg.open || view !== "new" || $("#yt-url").value !== "https://www.youtube.com/watch?v=dQw4w9WgXcQ" || $("#content").scrollTop !== top0 || document.activeElement !== $("#dest-notion-cover")'
                      ' || !$("#cov-home").contains($("#cov-box")) || !S.recording.active || calls.some(u => /record[/]|start|finish/.test(u))) throw new Error("fechar não devolveu a aula como estava");', patch(recording=REC)),
        # abrir e fechar várias vezes não duplica eventos; clique duplo gera uma vez só
        ("-repeat", '{type:"course",course_id:"c-ia"}', ' for (let i = 0; i < 3; i++) { covDlg.close(); await covQuick(); } $("#cov-gen").click(); $("#cov-gen").click(); await new Promise(r=>setTimeout(r,300));'
                    ' if (calls.filter(u => u === "/api/cover/preview").length !== 1 || document.querySelectorAll("#cov-box").length !== 1) throw new Error("eventos duplicados");', None),
        # reaberto durante a geração depois de mudar a organização: a operação não é redirecionada para outra página
        ("-late", '{type:"course",course_id:"c-ia"}', ' const r2 = api; api = (u, b) => u === "/api/cover/preview" ? new Promise(r => setTimeout(() => r(r2(u, b)), 300)) : r2(u, b); covGen(); covDlg.close();'
                  ' setOrg({type:"course",course_id:"c-ia",module_id:"m-dl"}); await covQuick(); if (cv.page.id !== "p-ia") throw new Error("a geração em andamento mudou de página");'
                  ' await new Promise(r=>setTimeout(r,500)); if (cv.page.id !== "p-ia" || !cv.pv) throw new Error("a prévia caiu em outra página");', None))],
    # os outros acessos abrem a mesma tela: Integrações → Notion, Ctrl+K e o curso da Biblioteca (com a página dele)
    ("covers-from-integ", "main", 'goIntegrations("notion"); document.querySelector("[data-cover-open]").click(); await new Promise(r=>setTimeout(r,200));'
                                  ' if (view !== "settings" || $("#cov-flow").hidden) throw new Error("Criar capa não abriu Capas do Notion");', None, None),
    ("covers-from-palette", "main", 'openPalette(); palIn.value="criar capa"; palIn.dispatchEvent(new Event("input")); palIn.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter"}));'
                                    ' await new Promise(r=>setTimeout(r,200)); if (view !== "settings" || settingsCat !== "covers") throw new Error("Ctrl+K não abriu Capas do Notion");', None, None),
    ("covers-from-course", "main", 'showView("library"); await loadLibrary(); openCourse("c-ia"); await new Promise(r=>setTimeout(r,200));'
                                   ' [...document.querySelectorAll(".course-actions .btn")].find(b => b.textContent.includes("Criar capa")).click(); await new Promise(r=>setTimeout(r,300));'
                                   ' if (cv.page?.id !== "p-ia" || $("#cov-page-change").disabled) throw new Error("o curso não abriu a página dele (ou não dá para trocar)");', None, None),
    ("settings-covers-ready", "main", 'goSettings("covers"); document.querySelector("[data-cat=covers] details").open = true;', lambda W: W["covers"].update(ready=True), None),
    *[(f"settings-{c}", "main", f'goSettings("{c}");', None, None) for c in ("general", "capture", "pomodoro", "transcription", "ai", "covers", "privacy")],
    # Pomodoro: cada estado no chip da barra e no painel aberto (o mesmo timer em todas as telas)
    *[(f"pomo-{n}", "main", 'await new Promise(r => setTimeout(r, 300)); Pomodoro.open();', patch(pomodoro={**POMO, **kv}), None) for n, kv in (
        ("ready", {"running": False, "left": 1500, "done": 0}), ("focus", {}), ("paused", {"running": False}),
        ("short", {"phase": "short", "left": 252, "total": 300, "done": 2}), ("long", {"phase": "long", "left": 754, "total": 900, "done": 4}),
        ("focusdone", {"phase": "short", "running": False, "left": 300, "total": 300, "done": 2}),
        ("breakdone", {"phase": "focus", "running": False, "left": 1500, "done": 2}))],
    ("pomo-understand", "main", UNDER + ' await new Promise(r => setTimeout(r, 300)); Pomodoro.open();', None, None),
    ("pomo-run", "main", run_js(JOB) + ' await new Promise(r => setTimeout(r, 300)); Pomodoro.open();', None, None),
    ("palette", "main", 'openPalette();', None, None),
    ("palette-typed", "main", 'openPalette(); palIn.value="kant"; palIn.dispatchEvent(new Event("input"));', None, None),
    ("confirm", "main", 'showView("settings"); ui.confirm("Apaga o histórico de aulas e as notas de compreensão deste PC.",{title:"Limpar os dados locais?",ok:"Apagar dados locais",danger:true});', None, None),
    ("toast-error", "main", 'toast("O Lumen parou de responder. Abra o aplicativo de novo.", true);', None, None),
    ("toast-ok", "main", 'toast("Notion conectado.");', None, None),
    ("design", "design", "", None, (1120, 860)),
    # barra flutuante (no tamanho real da janela) e janela flutuante da nota
    ("widget-idle", "widget", WOPEN, None, (304, 252)),
    ("widget-live", "widget", WOPEN, patch(recording=REC), (304, 252)),
    ("widget-paused", "widget", WOPEN, patch(recording={**REC, "paused": True, "paused_for": 42}), (304, 252)),
    ("widget-error", "widget", WOPEN, patch(recording={"active": False, "seconds": 0, "error": "A saída de áudio foi desconectada. Confira o fone ou alto-falante e tente de novo."}), (304, 252)),
    ("widget-job", "widget", WOPEN, patch(job=JOB), (304, 252)),
    ("widget-pomo-break", "widget", WOPEN, patch(recording=REC, pomodoro={**POMO, "phase": "short", "left": 252, "total": 300, "done": 2}), (304, 252)),
    ("widget-pomo-paused", "widget", WOPEN, patch(pomodoro={**POMO, "running": False}), (304, 252)),
    ("widget-note", "widget", WOPEN + ' Notes.setActive("k1"); await new Promise(r=>setTimeout(r,1300)); showNote(true);', None, (360, 440)),
    ("widget-prefs", "widget", WOPEN + ' await openPreferences();', None, (304, 252)),
    ("widget-prefs-desktop", "widget", WOPEN + ' await openPreferences(); await openCategory("desktop");', None, (304, 252)),
    ("widget-prefs-transcription", "widget", WOPEN + ' await openPreferences(); await openCategory("transcription");', None, (304, 252)),
    ("widget-top", "widget", WOPEN + ' hostListeners.forEach(f=>f({data:"edge:top"}));', patch(recording=REC), (304, 252)),
    ("widget-peek", "widget", 'document.body.dataset.expanded="false";', patch(recording=REC), (12, 84)),
    ("note", "note", "", None, (420, 520)),
    ("note-rec", "note", "", patch(recording=REC), (420, 520)),
    ("note-compact", "note", 'compact(true);', patch(recording={**REC, "paused": True, "paused_for": 30}), (420, 46)),
    ("note-min", "note", "", patch(recording=REC), (300, 240)),  # o menor tamanho da janela (NoteForm.Least)
]


def walk(out=OUT / "percurso"):
    """O uso de ponta a ponta, clicando nos botões de verdade: Início → Nova aula → gravar → pausar → retomar → Pomodoro
    → parar → Minha compreensão (com a barra e a janela da nota juntas) → processar → análise → salvar → resultado →
    Biblioteca → Integrações → Ajustes (um ajuste seguro) → Início. Uma imagem por etapa; falha no primeiro passo errado."""
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    proc, url = serve()
    W, log, fails = world(), [], []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            ctx = b.new_context(viewport={"width": 1120, "height": 860})
            ctx.add_init_script(HOST)
            ctx.route("**/api/**", router(W, log))
            m = ctx.new_page()
            errs = []
            m.on("pageerror", lambda e: errs.append(str(e)))
            n = [0]

            def shot(page, name):
                n[0] += 1
                page.wait_for_timeout(350)
                page.screenshot(path=str(out / f"{n[0]:02d}-{name}.png"), animations="disabled")

            def step(name, ok, page=m):
                print(("ok   " if ok else "FALHA ") + name)
                if not ok:
                    fails.append(name)
                shot(page, name)

            def until(js, page=m, ms=6000):
                try:
                    page.wait_for_function(js, timeout=ms)
                    return True
                except Exception:  # noqa: BLE001
                    return False

            m.goto(url + "/?frame=1")
            step("inicio", until("() => typeof S !== 'undefined' && S && !document.querySelector('#view-home').hidden"))
            m.click("#nav-new")
            step("nova-aula", until("() => !document.querySelector('#view-new').hidden && step === 'compose'"
                                    " && $('#dest-feats').textContent.includes('Cérebro') && !$('#dest-both').hidden"
                                    " && $('#org-type').textContent === 'A organizar' && $('#dest-path').textContent.includes('Sem curso')"))
            m.click("#org-change")  # Organização: um seletor só para o Notion e o Obsidian
            step("organizar-aberto", until("() => $('#org-dlg').open && $('#org-course-fields').hidden"))
            m.click("#org-types label:has-text('Curso')")
            m.select_option("#org-course", "c-ia")
            step("curso-escolhido", until("() => !$('#org-course-fields').hidden && [...$('#org-module').options].some(o => o.textContent === '02 - Deep Learning')"))
            m.click("#org-new-module")
            m.fill("#org-module-name", "Visão computacional")
            m.fill("#org-module-order", "3")
            m.click("#org-module-create")
            step("modulo-criado", until("() => $('#org-module').value === 'm-new' && $('#org-preview').textContent.includes('Estudos › Inteligência Artificial › Visão computacional')"
                                        " && $('#org-preview').textContent.includes('Estudos / Cursos / Inteligência Artificial / Visão computacional')"))
            m.fill("#org-lesson", "4")
            m.click("#org-save")
            step("organizacao-escolhida", until("() => !$('#org-dlg').open && $('#org-type').textContent === 'Curso'"
                                                " && $('#org-path').textContent.includes('Visão computacional · Aula 04')"
                                                " && $('#dest-path').textContent.includes('Visão computacional')"
                                                " && $('#dest-vault').textContent.includes('Visão computacional')"))
            m.click("#dest-obs-change")  # configuração rápida do cofre: a mesma chave de Integrações
            step("destino-obsidian", until("() => !$('#obs-quick').hidden && $('#dest-obs-change').textContent === 'Pronto'"))
            m.click("#obs-quick .set-row:has-text('Painel visual')")  # a mesma chave de Integrações
            step("sem-painel", until("() => $('#dest-feats').textContent.startsWith('Nota + Canvas') && !$('#obs-board').checked"))
            m.click("#obs-quick .set-row:has-text('Painel visual')")
            m.keyboard.press("Escape")
            step("com-painel", until("() => $('#obs-quick').hidden && $('#dest-feats').textContent.startsWith('Nota + 2 Canvas') && $('#obs-board').checked"))
            m.click("#rec-start")
            step("gravando", until("() => recorder.dataset.state === 'live' && document.querySelector('#global-status').dataset.tone === 'rec'"))
            w = ctx.new_page()
            w.set_viewport_size({"width": 304, "height": 252})
            w.goto(url + "/widget")
            until("() => typeof state !== 'undefined' && state && state.recording.active", w)
            w.evaluate('document.body.dataset.expanded = "true"')
            step("barra-gravando", until("() => document.body.dataset.state === 'live' && document.body.dataset.rec === 'on'", w), w)
            m.click("#rec-pause")
            step("pausado", until("() => recorder.dataset.paused === 'true' && document.querySelector('#global-status').dataset.tone === 'paused'"
                                  " && document.querySelector('#rec-pause-label').textContent === 'Retomar'"))
            step("barra-pausada", until("() => document.body.dataset.paused === 'true' && document.querySelector('#pause-label').textContent.startsWith('Retomar')", w), w)
            m.click("#rec-pause")
            step("retomado", until("() => recorder.dataset.paused === 'false' && document.querySelector('#rec-pause-label').textContent === 'Pausar'"))
            m.click("#u-pomo .pomo-time")
            m.wait_for_timeout(200)
            m.click("#u-pomo [data-act=toggle]")
            step("pomodoro", until("() => !document.querySelector('#u-pomo .pomo-sheet').hidden && document.querySelector('#u-pomo .pomo').dataset.running === 'false'"
                                   " && document.querySelector('#u-pomo .pomo').dataset.state === 'paused' && document.querySelector('#u-pomo .pomo-label').textContent === 'Pausado'"))
            m.click("#u-pomo [data-act=toggle]")  # retoma; o mesmo estado em todas as telas e na barra flutuante
            m.keyboard.press("Escape")
            for nav in ("#nav-library", "#open-settings", "#nav-new"):
                m.click(nav)
            step("pomodoro-global", until("() => { const p = document.querySelector('#u-pomo .pomo'); return p.dataset.state === 'focus'"
                                          " && getComputedStyle(p).display !== 'none' && document.querySelector('#u-pomo .pomo-sheet').hidden; }")
                 and until("() => document.querySelector('#pomo-main .pomo').dataset.state === 'focus'"
                           " && document.querySelector('#pomo-main .pomo-short').textContent === 'Foco'", w))
            m.click("#rec-start")
            step("gravacao-pronta", until("() => recorder.dataset.state === 'done' && found && !document.querySelector('#go').disabled"
                                          " && document.querySelector('#global-status').dataset.tone !== 'rec'"))
            m.click("#go")
            step("minha-compreensao", until("() => step === 'understand' && U && U.key === 'k1' && document.querySelector('#u-text').value.length > 50"))
            nw = ctx.new_page()
            nw.set_viewport_size({"width": 420, "height": 520})
            nw.goto(url + "/note?key=k1")
            m.click("#u-text")
            m.keyboard.press("End")
            m.keyboard.type(" O padding mantém o tamanho da saída.")
            step("nota-flutuante-sincronizada", until("() => document.querySelector('#nw-text').value.endsWith('tamanho da saída.')", nw), nw)
            step("compreensao-salva", until("() => document.querySelector('#u-save').textContent === 'Salvo' && !document.querySelector('#u-go').disabled"))
            m.click("#u-go")
            step("analise", until("() => step === 'analysis' && !document.querySelector('#review').hidden && document.querySelectorAll('#ai .ai-sec').length > 3"))
            m.click("#review-go")
            step("resultado", until("() => document.querySelector('#result').classList.contains('ok')"
                                    " && [...document.querySelectorAll('#run-actions .btn')].some(b => b.textContent.includes('Abrir no Notion'))"
                                    " && [...document.querySelectorAll('#run-actions .btn')].some(b => b.textContent.includes('Abrir no Obsidian'))"))
            sent = [b for meth, pth, b in log if pth in ("/api/start", "/api/finish")]
            step("organizacao-enviada", all(b.get("classification") == {"type": "course", "course_id": "c-ia", "module_id": "m-new", "lesson": 4}
                                             for b in sent) and len(sent) == 2 and not any("course_id" in b for b in sent))
            # o Gemini Notebook foi retirado: nenhum botão dele no resultado
            step("sem-gemini-notebook", m.locator("#run-actions button:has-text('Gemini Notebook')").count() == 0
                 and m.locator("[data-nb]").count() == 0 and m.locator("#nb-dlg").count() == 0)
            m.click("#nav-library")
            step("biblioteca", until("() => !document.querySelector('#view-library').hidden && document.querySelectorAll('#library-list .lib-title').length > 3"))
            m.click("#lib-filter [data-f=course]")
            step("biblioteca-cursos", until("() => !$('#course-grid').hidden && $$('#course-grid .course-card').length === 2"))
            m.click("#course-grid .course-card:has-text('Inteligência Artificial')")
            step("biblioteca-curso", until("() => !$('#lib-crumbs').hidden && $('#library-list').textContent.includes('02 - Deep Learning')"
                                             " && $('#library-list').textContent.includes('Transformers e atenção')"))
            m.click("#lib-filter [data-f=inbox]")
            m.click("#library-list [aria-label^='Organizar: Estruturas']")
            step("organizar-aula", until("() => $('#org-dlg').open && $('#org-save').textContent === 'Mover para cá'"))
            m.click("#org-types label:has-text('Conteúdo gratuito')")
            m.fill("#org-category", "Computação")
            m.click("#org-save")
            step("aula-organizada", until("() => !$('#org-dlg').open && $('#library-list').textContent.includes('Nada para organizar')"))
            m.click("#nav-integrations")
            step("integracoes", until("() => document.querySelector('#notion-badge').dataset.tone === 'ok' && document.querySelector('#obsidian-badge').dataset.tone === 'ok'"
                                      " && !$('#integ-notion').hidden && $('#integ-obsidian').hidden && $('#integ-drive').hidden"))
            # trocar de integração: o que está sendo digitado e as seções abertas ficam; nada é salvo nem enviado
            n_posts = len([x for x in log if x[0] == "POST"])
            m.fill("#token", "ntn_ainda_digitando")
            m.click("#integ-notion summary:has-text('Como conectar')")
            m.click("#itab-obsidian")
            ok = until("() => !$('#integ-obsidian').hidden && $('#integ-notion').hidden && $('#itab-obsidian').getAttribute('aria-selected') === 'true'"
                       " && $('#where-sub').textContent === 'Obsidian'")
            m.keyboard.press("ArrowRight")  # setas na faixa: vai para o Google Drive, com o foco junto
            ok = ok and until("() => !$('#integ-drive').hidden && document.activeElement === $('#itab-drive')")
            step("integracoes-google-drive", ok and until("() => $('#drive-status').textContent.includes('Não configurado')"
                                                         " && $('#drive-actions').textContent.includes('Escolher o arquivo do cliente')"))
            m.click("#itab-notion")
            ok = until("() => $('#token').value === 'ntn_ainda_digitando' && $('#integ-notion details.disclosure').open")
            m.click("#itab-drive")
            posts = [x[1] for x in log if x[0] == "POST"][n_posts:]
            step("integracoes-trocar-preserva", ok and until("() => !$('#integ-drive').hidden") and posts == [])  # nada é salvo nem enviado ao trocar
            m.evaluate("$('#token').value = ''")  # o token digitado nunca foi salvo
            m.click("#open-settings")
            m.click("#settings-nav [data-cat=privacy]")
            m.click("label:has(#keep)")
            step("ajuste-salvo", until("() => S.config.keep_temp === true") and W["config"]["keep_temp"] is True)
            m.click("#nav-home")
            step("inicio-de-novo", until("() => !document.querySelector('#view-home').hidden && document.querySelector('#nav-home').getAttribute('aria-current') === 'page'"))
            if errs:
                fails.append(f"erros de página: {errs}")
            b.close()
    finally:
        proc.kill()
        proc.wait(timeout=10)
        shutil.rmtree(proc.data, ignore_errors=True)
    print(f"\n{n[0]} etapas em {out}" + (f"\nFALHAS: {fails}" if fails else "\npercurso completo sem falhas"))
    return 1 if fails else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--walk" in args:
        sys.exit(walk())
    sizes = ((1120, 860),) + (((520, 560), (900, 700), (1600, 1000), (1920, 1040)) if "--sizes" in args else ())
    zooms = (1.0,) + ((.8, .9, 1.1, 1.2) if "--zoom" in args else ())
    sys.exit(run(SCENARIOS, [a for a in args if not a.startswith("--")], sizes, zooms))
