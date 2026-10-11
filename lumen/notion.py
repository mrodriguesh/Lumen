"""API REST oficial do Notion (https://developers.notion.com), versão 2026-03-11."""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date

from . import AppError
from .llm import fmt_time
from .sources import youtube_id, youtube_url

API = "https://api.notion.com/v1"
VERSION = "2026-03-11"
NO_COURSE = "Sem curso"


def _error(status, code):
    if status == 401:
        return AppError("O token do Notion é inválido ou foi revogado.", "Cole um token novo em Configurações.")
    if status in (403, 404):
        return AppError("A integração não tem acesso a esta página do Notion.",
                        "No Notion, abra a página raiz → ••• → Conexões → adicione sua integração.")
    if status == 429:
        return AppError("O Notion limitou o número de pedidos.", "Aguarde um minuto e tente de novo.")
    if status == 400:
        return AppError(f"O Notion recusou o conteúdo ({code}).", "Tente de novo. Se persistir, informe este código.")
    return AppError(f"O Notion está indisponível (HTTP {status}).", "Tente de novo em alguns minutos.")


def request(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    append = method == "PATCH" and path.endswith("/children")
    for attempt in range(4):
        req = urllib.request.Request(API + path, data, method=method, headers={
            "Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            retry = e.code == 429 or (e.code >= 500 and not append)
            if retry and attempt < 3:
                delay = min(float(e.headers.get("Retry-After") or 2 ** attempt), 30)
                e.close()
                time.sleep(delay)
                continue
            try:
                code = json.load(e).get("code", "")
            except ValueError:
                code = ""
            finally:
                e.close()
            if append and e.code >= 500:
                raise AppError("Não foi possível confirmar o envio ao Notion.",
                               "Confira a página antes de tentar novamente; o último lote pode ter sido salvo.") from None
            raise _error(e.code, code) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if append:  # Repetir um append sem resposta pode duplicar o conteúdo já recebido pelo Notion.
                raise AppError("Não foi possível confirmar o envio ao Notion.",
                               "Confira a página antes de tentar novamente; o último lote pode ter sido salvo.") from None
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise AppError("Sem conexão com o Notion.", "Verifique a internet e tente de novo.") from None


def page_id(value):
    """Aceita link ou ID de página e devolve o ID com hífens."""
    m = re.search(r"([0-9a-f]{32})(?:[?#]|$)", (value or "").replace("-", "").strip().lower())
    if not m:
        raise AppError("Não reconheci o link da página do Notion.", "Copie o link pelo menu ••• → Copiar link.")
    h = m[1]
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _title(page):
    for p in page.get("properties", {}).values():
        if p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in p["title"]).strip() or "Sem título"
    return "Sem título"


def search_pages(token):
    d = request("POST", "/search", token, {"filter": {"property": "object", "value": "page"}, "page_size": 50})
    return [{"id": p["id"], "title": _title(p)} for p in d.get("results", []) if not p.get("in_trash")]


def list_pages(token):
    """Páginas compartilhadas com a integração, com o caminho (ex.: “Cursos › Claude”).

    Linhas de banco de dados (e o que está dentro delas) ficam de fora: são registros (treinos, livros, hábitos…),
    não lugares para guardar aulas, e num workspace real chegam a centenas de itens repetidos na busca."""
    pages, cursor = {}, None
    while True:
        d = request("POST", "/search", token, {"filter": {"property": "object", "value": "page"}, "page_size": 100,
                                                **({"start_cursor": cursor} if cursor else {})})
        for p in d.get("results", []):
            if not p.get("in_trash"):
                par = p.get("parent") or {}
                pages[p["id"]] = {"id": p["id"], "title": _title(p), "parent": par.get("page_id"),
                                  "top": par.get("type") == "workspace",
                                  "row": par.get("type") in ("database_id", "data_source_id"),
                                  "icon": (p.get("icon") or {}).get("emoji")}
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]

    def path(p, seen=()):
        parent = pages.get(p["parent"])
        if not parent or parent["id"] in seen:  # pai fora do alcance da integração (ou ciclo)
            return p["title"]
        return path(parent, seen + (p["id"],)) + " › " + p["title"]
    def in_db(p, seen=()):
        parent = pages.get(p["parent"])
        return p["row"] or bool(parent and parent["id"] not in seen and in_db(parent, seen + (p["id"],)))
    out = [{"id": p["id"], "title": p["title"], "path": path(p), "top": p["top"],
            "parent": p["parent"] if p["parent"] in pages else None, "icon": p["icon"]}
           for p in pages.values() if not in_db(p)]
    return sorted(out, key=lambda p: p["path"].casefold())


def list_courses(token, root):
    out, cursor = [], None
    while True:
        q = "?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        d = request("GET", f"/blocks/{root}/children{q}", token)
        out += [{"id": b["id"], "title": b["child_page"]["title"] or "Sem título"}
                for b in d.get("results", []) if b.get("type") == "child_page"]
        if not d.get("has_more"):
            return out
        cursor = d["next_cursor"]


def upload_image(token, data, filename="capa.png", content_type="image/png"):
    """File Upload API oficial: cria o upload, envia o arquivo (multipart) e devolve o id para usar como capa."""
    up = request("POST", "/file_uploads", token, {"filename": filename, "content_type": content_type})
    boundary = "lumen" + os.urandom(12).hex()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/file_uploads/{up['id']}/send", body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Notion-Version": VERSION,
        "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            json.load(r)
    except urllib.error.HTTPError as e:
        e.close()
        raise _error(e.code, "upload") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        raise AppError("Sem conexão com o Notion.", "Verifique a internet e tente de novo.") from None
    return up["id"]


def create_course(token, root, title, decor=None, cover_png=None):
    """Cria uma página (curso, módulo…). Com `decor` (ver llm.decorate): ícone, capa do Notion, destaque e “Aulas”."""
    title = (title or "").strip()[:200]
    if not title:
        raise AppError("Dê um nome ao curso.", "Digite o nome e tente de novo.")
    body = {"parent": {"page_id": root}, "icon": {"type": "emoji", "emoji": (decor or {}).get("emoji") or "📚"},
            "properties": {"title": {"title": _rt(title)}}}
    if decor:
        body["cover"] = {"type": "external",
                         "external": {"url": f"https://www.notion.so/images/page-cover/{decor['cover']}.png"}}
        if cover_png:  # capa desenhada para o tema; se o upload falhar, fica a capa reserva do Notion
            try:
                body["cover"] = {"type": "file_upload", "file_upload": {"id": upload_image(token, cover_png)}}
            except AppError as e:
                body["_aviso"] = f"O envio da capa desenhada falhou ({e}); foi usada uma capa de cor do Notion."
        else:
            body["_aviso"] = "Não foi possível desenhar a capa neste PC; foi usada uma capa de cor do Notion."
        children = []
        if decor.get("subtitle"):
            children.append(_b("callout", _rt(decor["subtitle"]), icon={"type": "emoji", "emoji": decor["emoji"]},
                               color=decor["color"]))
        children += [{"object": "block", "type": "divider", "divider": {}}, _h2("Aulas")]
        body["children"] = children  # as aulas criadas depois entram logo abaixo de “Aulas”
    aviso = body.pop("_aviso", None)
    p = request("POST", "/pages", token, body)
    return {"id": p["id"], "title": title, **({"cover_note": aviso} if aviso else {})}


def course_for(token, root, course_id):
    """Resolve o destino; '__none__' usa (ou cria) a página “Sem curso”."""
    if course_id != "__none__":
        return course_id
    if not root:
        raise AppError("Escolha onde salvar a aula.", "Escolha uma página do Notion ou defina a página raiz em Ajustes.")
    for c in list_courses(token, root):
        if c["title"] == NO_COURSE:
            return c["id"]
    return create_course(token, root, NO_COURSE)["id"]


def page_url(token, pid):
    """URL da página se ainda existir fora da lixeira; senão None."""
    try:
        p = request("GET", f"/pages/{pid}", token)
    except AppError:
        return None
    return None if p.get("in_trash") else p.get("url")


def trash(token, pid):
    request("PATCH", f"/pages/{pid}", token, {"in_trash": True})


# --- Blocos ----------------------------------------------------------------

def _rt(text, bold=False, italic=False, color="default", link=None):
    text = str(text)
    return [{"type": "text", "text": {"content": text[i:i + 2000], **({"link": {"url": link}} if link else {})},
             "annotations": {"bold": bold, "italic": italic, "color": color}}
            for i in range(0, max(len(text), 1), 2000)]


def _b(kind, rich, **extra):
    return {"object": "block", "type": kind, kind: {"rich_text": rich, **extra}}


def _paras(text, terms=()):
    return [_b("paragraph", _marked(p.strip(), terms)) for p in re.split(r"\n\s*\n", text) if p.strip()]


def _marked(text, terms=()):
    """Texto com os termos do glossário em negrito onde a aula os usa (até 40 marcas: o Notion aceita 100 pedaços
    de texto por bloco)."""
    words = sorted({t for t in terms if len(t) >= 3}, key=len, reverse=True)
    hits = list(re.finditer(r"(?<!\w)(" + "|".join(map(re.escape, words)) + r")(?!\w)", text, re.I)) if words else []
    if not hits or len(hits) > 40:
        return _rt(text)
    out, at = [], 0
    for m in hits:
        out += (_rt(text[at:m.start()]) if m.start() > at else []) + _rt(m.group(), bold=True)
        at = m.end()
    return out + (_rt(text[at:]) if at < len(text) else [])


def _h2(text):
    return _b("heading_2", _rt(text))


def _callout(rich, emoji, color="gray_background", children=None):
    return _b("callout", rich, icon={"type": "emoji", "emoji": emoji}, color=color,
              **({"children": children} if children else {}))


def _table(rows, row_header=False):
    """Tabela do Notion; a 1ª linha é o cabeçalho. Células: texto ou rich text pronto."""
    cell = lambda c: c if isinstance(c, list) else (_rt(c) if str(c) else [])  # noqa: E731
    return {"object": "block", "type": "table", "table": {
        "table_width": len(rows[0]), "has_column_header": True, "has_row_header": row_header,
        "children": [{"object": "block", "type": "table_row", "table_row": {"cells": [cell(c) for c in r]}}
                     for r in rows]}}


def _columns(*cols):
    return {"object": "block", "type": "column_list", "column_list": {"children": [_column(c) for c in cols]}}


_KEYCAPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def _cards(lesson, yt, terms):
    """Tópicos em cartões numerados, em duas colunas (no celular, uma embaixo da outra)."""
    cards = [_callout(_rt(t["title"], bold=True) + _rt("\n") + _marked(t["explanation"], terms)
                      + _stamp(t["timestamp"], yt), _KEYCAPS[i] if i < len(_KEYCAPS) else "🔹")
             for i, t in enumerate(lesson["topics"])]
    if len(cards) < 2:
        return cards
    half = (len(cards) + 1) // 2
    return [_columns(cards[:half], cards[half:])]


def _stamp(seconds, yt_id):
    if seconds is None:
        return []
    return _rt(f"  ⏱ {fmt_time(seconds)}", color="gray", link=youtube_url(yt_id, seconds) if yt_id else None)


def _duration(seconds):
    if not seconds:
        return None
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{max(m, 1)} min"


def _mind_map(lesson, upload_id):
    """Imagem do mapa mental; sem imagem (sem Edge ou envio falhou), o mesmo mapa em tópicos aninhados."""
    from .mindmap import data
    m = data(lesson)
    if not m["branches"]:
        return []
    if upload_id:
        return [_h2("🧠 Mapa mental"), {"object": "block", "type": "image", "image": {
            "type": "file_upload", "file_upload": {"id": upload_id},
            "caption": _rt("Gerado pela IA a partir da aula · clique para ampliar", color="gray")}}]
    return [_h2("🧠 Mapa mental"), _b("callout", _rt(m["center"], bold=True), icon={"type": "emoji", "emoji": "🧠"},
                                       color="purple_background"),
            *[_b("bulleted_list_item", _rt(f"{b['emoji']} {b['label']}".strip(), bold=True),
                 children=[_b("bulleted_list_item", _rt(k)) for k in b["children"]]) for b in m["branches"]]]


def _column(children):
    return {"object": "block", "type": "column", "column": {"children": children}}


def _screen_text(s):
    """Texto de uma tela: código em bloco de código, tabela como tabela do Notion, o resto em parágrafos."""
    text = s["texto"].strip("\n")
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if lines and lines[0].casefold() == s["titulo"].casefold():  # o título já está no cabeçalho do bloco
        lines = lines[1:]
        text = text.split("\n", 1)[1] if "\n" in text else ""
    # colunas separadas por " | " (o pedido) ou por tabulação (às vezes o modelo usa); "| a | b |" também vale
    cut = lambda ln: re.split(r"\t+|\|", ln[1:-1] if len(ln) > 1 and ln[0] == ln[-1] == "|" else ln)  # noqa: E731
    rows = [[c.strip() for c in cut(ln)] for ln in lines if "|" in ln or "\t" in ln]
    out = []
    if s["tipo"] == "codigo" and lines:
        out.append({"object": "block", "type": "code", "code": {"rich_text": _rt(text), "language": "plain text"}})
    elif s["tipo"] == "tabela" and 2 <= len(rows) <= 99 and 2 <= len(rows[0]) <= 10 \
            and all(len(r) == len(rows[0]) for r in rows):
        out += [_b("paragraph", _rt(ln)) for ln in lines if "|" not in ln and "\t" not in ln][:10]  # legenda
        out.append({"object": "block", "type": "table", "table": {
            "table_width": len(rows[0]), "has_column_header": True, "has_row_header": False,
            "children": [{"object": "block", "type": "table_row", "table_row": {"cells": [_rt(c) if c else [] for c in r]}}
                         for r in rows]}})
    else:
        out += [_b("paragraph", _rt(ln)) for ln in lines[:80]]
    if s["descricao"]:
        out.append(_b("paragraph", _rt("Figura: " + s["descricao"], italic=True, color="gray")))
    return out or [_b("paragraph", _rt(s["titulo"]))]


def _screens(screens, yt):
    """“O que apareceu na tela”: galeria das telas (2 por linha, clique para ampliar) e o texto de cada uma
    recolhido, para buscar e copiar."""
    from .vision import KINDS
    if not screens:
        return []
    label = lambda s: f"{KINDS.get(s['tipo'], '🖥️')} {s['titulo'] or 'Tela'}"  # noqa: E731
    out = [_h2("🖥️ O que apareceu na tela"),
           _b("paragraph", _rt("Slides, quadro e código lidos pelo Lumen enquanto assistia com você. "
                               "Clique numa imagem para ampliar.", italic=True, color="gray"))]
    imgs = [s for s in screens if s.get("upload")]
    for i in range(0, len(imgs), 2):
        cols = [_column([{"object": "block", "type": "image", "image": {
            "type": "file_upload", "file_upload": {"id": s["upload"]},
            "caption": _rt(f"{fmt_time(s['t'])} · {label(s)}", color="gray")}}]) for s in imgs[i:i + 2]]
        if len(cols) == 1:  # última linha com uma tela só: mantém o mesmo tamanho das outras
            cols.append(_column([_b("paragraph", [])]))
        out.append({"object": "block", "type": "column_list", "column_list": {"children": cols}})
    out.append(_b("heading_3", _rt("Texto das telas")))
    out += [_b("toggle", _rt(label(s), bold=True) + _stamp(s["t"], yt), children=_screen_text(s)) for s in screens]
    return out


def _chart_data(c):
    """Os números do gráfico numa tabela do Notion (para conferir, buscar e copiar)."""
    from .charts import fmt
    row = lambda cells: {"object": "block", "type": "table_row", "table_row": {"cells": [_rt(x) for x in cells]}}  # noqa
    if c["tipo"] == "linha_do_tempo":
        rows = [["Ano", "Acontecimento"]] + [[e["data"], e["texto"]] for e in c["eventos"]]
    elif c["tipo"] == "funcao":
        rows = [["Curva", "Fórmula"]] + [[f["nome"], f["expressao"]] for f in c["funcoes"]]
    else:
        unit = f" ({c['unidade']})" if c["unidade"] else ""
        rows = [[c["eixo_x"]] + [(s["nome"] or "Valor") + unit for s in c["series"]]]
        rows += [[lab] + [fmt(s["valores"][i]) for s in c["series"]] for i, lab in enumerate(c["rotulos"])]
    out = [_b("paragraph", _rt(c["mensagem"]))] if c["mensagem"] else []
    out.append({"object": "block", "type": "table", "table": {
        "table_width": len(rows[0]), "has_column_header": True, "has_row_header": False,
        "children": [row(r) for r in rows]}})
    if c["tipo"] == "funcao":
        var = "n" if c.get("complexidade") else "x"
        out.append(_b("paragraph", _rt(f"Curvas calculadas pelo Lumen para {var} de {fmt(c['x_min'])} a "
                                       f"{fmt(c['x_max'])}.", italic=True, color="gray")))
    if c.get("estrutura"):
        how = ("do início de cada tópico ao início do seguinte, pelos tempos da aula" if c["unidade"] in ("min", "s")
               else "quantas vezes cada termo aparece na transcrição")
        out.append(_b("paragraph", _rt(f"Calculado pelo Lumen: {how}.", italic=True, color="gray")))
    return out


def _charts(charts, yt):
    """“Gráficos da aula”: GIF animado (clique para ampliar) e, recolhidos, os números de cada um."""
    if not charts:
        return []
    said = ["os números, datas e fórmulas da aula, cada valor conferido na transcrição ou nas telas"
            ] if any(not c.get("estrutura") for c in charts) else []
    said += ["o tempo e os termos da própria aula, contados pelo Lumen"] if any(c.get("estrutura") for c in charts) else []
    out = [_h2("📊 Gráficos da aula"),
           _b("paragraph", _rt("Feitos só com " + " e com ".join(said) + ".", italic=True, color="gray"))]
    for c in charts:
        if c.get("upload"):
            out += [{"object": "block", "type": "image", "image": {
                "type": "file_upload", "file_upload": {"id": c["upload"]},
                "caption": _rt(c["titulo"], color="gray") + _stamp(c.get("t"), yt)}},
                _b("toggle", _rt("Ver os dados", color="gray"), children=_chart_data(c))]
        else:  # sem Edge ou o envio falhou: os números, sem o desenho
            out += [_b("heading_3", _rt(c["titulo"]) + _stamp(c.get("t"), yt)), *_chart_data(c)]
    return out


def build_page(lesson, meta):
    """Monta título e blocos. As respostas ficam dentro de toggles (recolhidos ao abrir a página)."""
    yt = meta.get("yt_id")
    info = [("Curso", meta["course"]), ("Criada em", date.today().strftime("%d/%m/%Y")),
            ("Fonte", meta["source"]), ("Duração", _duration(meta.get("duration"))),
            ("Idioma da aula", meta.get("language")), ("Link original", meta.get("link"))]
    rich = []
    for label, value in info:
        if value:
            rich += (_rt("\n") if rich else []) + _rt(f"{label}: ", bold=True) + _rt(
                value, link=value if label == "Link original" else None)
    terms = [g["term"] for g in lesson["glossary"]]
    many = lambda n, one, more: f"{n} {one if n == 1 else more}"  # noqa: E731
    count = [many(len(lesson["topics"]), "tópico", "tópicos"),
             many(len(lesson["review_questions"]), "pergunta", "perguntas")]
    count += [many(len(terms), "termo", "termos")] if terms else []
    count += [many(len(meta["charts"]), "gráfico", "gráficos")] if meta.get("charts") else []
    todo = lambda text: {"object": "block", "type": "to_do", "to_do": {"rich_text": _rt(text), "checked": False}}  # noqa
    plan = [_callout(_rt("Nesta aula", bold=True) + _rt("\n" + " · ".join(count), color="gray"), "📌", "blue_background"),
            todo("Assistir à aula"), todo("Ler o resumo e o mapa mental"),
            todo("Responder às perguntas de revisão"), todo("Revisar de novo em 7 dias")]
    blocks = [_columns([_callout(rich, "🎓")], plan)]
    if meta.get("banner_upload"):  # a aula entra numa página existente: o banner vai no topo dela, a capa da página fica
        blocks.insert(0, {"object": "block", "type": "image",
                          "image": {"type": "file_upload", "file_upload": {"id": meta["banner_upload"]}}})
    try:
        video_url = youtube_url(youtube_id(meta.get("link")))
    except AppError:
        video_url = None
    if video_url:
        blocks += [_h2("▶️ Assistir à aula"),
                   {"object": "block", "type": "video", "video": {
                       "type": "external", "external": {"url": video_url},
                       "caption": _rt("Aula original · YouTube", color="gray")}},
                   {"object": "block", "type": "divider", "divider": {}}]
    summary = [p.strip() for p in re.split(r"\n\s*\n", lesson["summary"]) if p.strip()]
    blocks += [{"object": "block", "type": "table_of_contents", "table_of_contents": {"color": "gray"}},
               _h2("📝 Resumo"),
               _callout(_rt("Ideia central", bold=True) + _rt("\n") + _marked(summary[0], terms), "💡", "yellow_background"),
               *_paras("\n\n".join(summary[1:]), terms),
               *_mind_map(lesson, meta.get("mind_map_upload")),
               _h2("🌱 Explicação simples"),
               _b("paragraph", _rt("Escrita pela IA a partir da aula, para quem está começando.", italic=True,
                                   color="gray"))]
    simple = [p.strip() for p in re.split(r"\n\s*\n", lesson["simple_explanation"]) if p.strip()]
    rest = _paras("\n\n".join(simple[1:]), terms)  # o Notion aceita 100 filhos por bloco; o resto vem logo depois
    blocks += [_callout(_marked(simple[0], terms), "🌱", "green_background", children=rest[:100]), *rest[100:]]
    blocks += [_h2("🎯 Tópicos principais"), *_cards(lesson, yt, terms)]
    blocks += _charts(meta.get("charts"), yt)
    blocks += _screens(meta.get("screens"), yt)
    if lesson["glossary"]:
        blocks += [_h2("📖 Glossário"),
                   _table([["Termo", "Significado"]] + [[_rt(g["term"], bold=True), g["definition"]]
                                                        for g in lesson["glossary"]], row_header=True)]
    if lesson["examples"]:
        blocks.append(_h2("🧩 Exemplos e analogias"))
        blocks += [_callout(_rt("Da aula" if e["origin"] == "aula" else "Analogia didática (IA)", bold=True,
                                color="gray") + _rt("\n") + _marked(e["text"], terms),
                            "🎬" if e["origin"] == "aula" else "💭",
                            "gray_background" if e["origin"] == "aula" else "purple_background")
                   for e in lesson["examples"]]
    if lesson["steps"]:
        blocks.append(_h2("🪜 Passo a passo"))
        blocks += [_b("numbered_list_item", _marked(s, terms)) for s in lesson["steps"]]
    blocks += [_h2("❓ Perguntas de revisão"),
               _b("paragraph", _rt("Tente responder antes de abrir cada pergunta.", italic=True, color="gray"))]
    blocks += [_b("toggle", _rt(q["question"], bold=True),
                  children=[_callout(_rt(q["answer"]), "✅", "green_background")])
               for q in lesson["review_questions"]]
    if lesson["key_moments"]:
        blocks += [_h2("⏱️ Momentos da aula"),
                   _table([["Tempo", "Momento"]] + [[_rt(fmt_time(m["timestamp"]), bold=True,
                                                        link=youtube_url(yt, m["timestamp"]) if yt else None),
                                                    m["label"]] for m in lesson["key_moments"]])]
    notes = [f"Conteúdo gerado localmente por IA ({meta['model']}) a partir da transcrição. "
             "Confira informações importantes na aula original.",
             meta["transcript_origin"]]
    if meta.get("uncertain"):
        notes.append(f"{meta['uncertain']} trecho(s) da transcrição tiveram baixa confiança.")
    if meta.get("charts"):
        notes.append(f"{len(meta['charts'])} gráfico(s) feitos só com dados da aula: cada valor foi conferido na "
                     "transcrição ou nas telas; curvas, tempos e contagens foram calculados pelo Lumen.")
    if meta.get("screens"):
        notes.append(f"{len(meta['screens'])} tela(s) da aula lidas por um modelo de visão local ({meta['vision_model']}); "
                     "confira números e fórmulas nas imagens.")
    blocks += [{"object": "block", "type": "divider", "divider": {}}, _b("heading_3", _rt("Sobre esta página"))]
    if lesson["caveats"]:  # o que a aula não deixou claro: à vista, em destaque
        blocks.append(_callout(_rt("Pontos de atenção", bold=True), "⚠️", "orange_background",
                               children=[_b("bulleted_list_item", _rt(c)) for c in lesson["caveats"]]))
    blocks.append(_callout(_rt("\n".join(notes), color="gray"), "🔎"))
    return lesson["title"], blocks


def transcript_section(lines):
    """Título recolhível “Transcrição completa” (fechado ao abrir a página) com um parágrafo por trecho."""
    paras = [_b("paragraph", _rt(ln)) for ln in lines if ln.strip()]
    head = _b("heading_3", _rt("Transcrição completa"), is_toggleable=True, color="default")
    return head, paras


MAX_BLOCKS, MAX_BYTES = 1000, 500_000  # por requisição, contando os blocos internos (developers.notion.com/
#                                        reference/request-limits); 100 por lista vale em cada nível


def _count(block):
    return 1 + sum(_count(c) for c in block[block["type"]].get("children", []))


def batches(blocks):
    """Lotes que respeitam os três limites: 100 blocos no nível de cima, 1000 no total e 500 KB (com folga para o
    envelope do pedido). Uma galeria de telas cheias de texto tem poucos blocos em cima e muitos dentro."""
    out, cur, n, size = [], [], 0, 0
    for b in blocks:
        c, s = _count(b), len(json.dumps(b))  # o mesmo json.dumps de request(): é o tamanho que vai pela rede
        if cur and (len(cur) == 100 or n + c > MAX_BLOCKS or size + s > MAX_BYTES - 10_000):
            out.append(cur)
            cur, n, size = [], 0, 0
        cur.append(b)
        n, size = n + c, size + s
    return out + ([cur] if cur else [])


def publish(token, parent, title, blocks, check, transcript=None):
    """Acrescenta a aula à página escolhida, preservando seus enfeites e conteúdo.

    `transcript` (opcional): linhas “[mm:ss] texto”; vão dentro de um título recolhível, em lotes de 100
    (limite de filhos por requisição da API)."""
    parent = page_id(parent)
    check()
    page = request("GET", f"/pages/{parent}", token)
    if page.get("in_trash") or page.get("archived"):
        raise AppError("A página escolhida está na lixeira do Notion.", "Restaure a página ou escolha outra.")
    added = []
    blocks = [_b("heading_1", _rt(title)), *blocks]
    try:
        for batch in batches(blocks):
            check()
            res = request("PATCH", f"/blocks/{parent}/children", token, {"children": batch})
            added.extend(b["id"] for b in res["results"])
        if transcript:
            head, paras = transcript_section(transcript)
            first, *more = batches(paras) or [[]]  # o 1º lote vai junto do título, também dentro dos limites
            check()
            res = request("PATCH", f"/blocks/{parent}/children", token,
                          {"children": [{**head, "heading_3": {**head["heading_3"], "children": first}}]})
            added.extend(b["id"] for b in res["results"])
            toggle_id = res["results"][-1]["id"]
            for batch in more:
                check()
                request("PATCH", f"/blocks/{toggle_id}/children", token, {"children": batch})
        check()
    except BaseException:
        incomplete = False
        for bid in added:
            try:
                request("DELETE", f"/blocks/{bid}", token)
            except AppError:
                incomplete = True
        if incomplete:
            raise AppError("O envio falhou e parte do material pode ter ficado na página escolhida.",
                           "Confira a página no Notion antes de tentar novamente; o conteúdo anterior foi preservado.") from None
        raise
    return parent, page["url"], added
