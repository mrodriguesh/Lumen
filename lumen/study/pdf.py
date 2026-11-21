"""PDFs de estudo: dados limitados → HTML fixo → o mesmo CDP das capas.

Nenhum HTML, caminho, imagem remota ou código vindo do modelo é executado.
"""
import base64
import copy
import html as markup
import io
import re
import time
from urllib.parse import urlsplit

from .. import AppError, cdp, charts, cover, jobs, llm, mindmap, obsidian, store, vault
from . import attachments, chats, diagram, images, learn, providers, search, settings, tools

TYPES = {"revisao": "Folha de revisão", "apostila": "Apostila", "cornell": "Cornell",
         "exercicios": "Exercícios", "flashcards": "Flashcards para recortar", "plano": "Plano de estudos",
         "simulado": "Simulado", "mapa": "Mapa mental", "explicacao": "Explicação avançada"}
TASK = {
    "revisao": "Uma folha de revisão de uma página: até 6 conceitos essenciais, texto de até 250 caracteres por bloco.",
    "apostila": "Uma apostila organizada: definições, mecanismos, exemplos, aplicação e erros comuns.",
    "cornell": "Anotações Cornell: question é a pergunta da margem e text são as notas que a respondem.",
    "exercicios": "Exercícios abertos: question é o enunciado sem resposta; answer é o gabarito comentado. text vazio.",
    "flashcards": "Flashcards: question é a frente, answer é o verso (até 260 caracteres). text vazio.",
    "plano": "Plano de estudos: cada bloco é uma sessão, com objetivo, tempo, tarefa prática e revisão espaçada em text.",
    "simulado": "Simulado de questões abertas: question é o enunciado sem resposta, answer é o gabarito comentado; text vazio.",
    "explicacao": "Explicação em camadas: intuição, mecanismo, precisão, exemplo, contraexemplo, erros e aplicação.",
}
CHART_SCHEMA = copy.deepcopy(charts.SCHEMA)
CHART_SCHEMA["properties"]["graficos"]["maxItems"] = 1
_chart = CHART_SCHEMA["properties"]["graficos"]["items"]["properties"]
for _key, _max in (("series", 3), ("dados", 12), ("funcoes", 3), ("eventos", 10)):
    _chart[_key]["maxItems"] = _max
_chart["dados"]["items"]["properties"]["valores"]["maxItems"] = 3


def schema(ids, count=8):
    s = {"type": "string"}
    block = {"type": "object", "properties": {"heading": s, "text": s, "question": s, "answer": s,
             "source": {"type": "string", "enum": [*ids, "geral"]}},
             "required": ["heading", "text", "question", "answer", "source"]}
    return {"type": "object", "properties": {"title": s, "summary": s,
            "blocks": {"type": "array", "minItems": 1, "maxItems": count, "items": block}},
            "required": ["title", "summary", "blocks"]}


def clean(raw, form, ids):
    if not isinstance(raw, dict) or not isinstance(raw.get("blocks"), list):
        raise AppError("A IA não devolveu um documento válido.")
    def cut(v, n):
        text = " ".join(str(v or "").split())
        if len(text) <= n:
            return text
        return text[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    blocks = []
    for b in learn._dedupe(raw["blocks"])[:6 if form == "revisao" else 12]:
        if not isinstance(b, dict):
            continue
        item = {"heading": cut(b.get("heading"), 90), "text": cut(b.get("text"), 300 if form == "revisao" else 1200),
                "question": cut(b.get("question"), 260 if form == "flashcards" else 500),
                "answer": cut(b.get("answer"), 260 if form == "flashcards" else 800),
                "source": b.get("source") if b.get("source") in ids else "geral"}
        if form in ("exercicios", "simulado", "flashcards"):
            if not item["question"] or not item["answer"]:
                continue
        elif not item["text"]:
            continue
        blocks.append(item)
    if not blocks:
        raise AppError("O documento ficou sem conteúdo válido.", "Tente um assunto mais específico.")
    return {"title": cut(raw.get("title"), 100) or TYPES[form], "summary": cut(raw.get("summary"), 250), "blocks": blocks}


def jpeg(blob, width=1500):
    from PIL import Image  # Pillow e pypdf só carregam quando um documento é gerado
    with Image.open(io.BytesIO(blob)) as im:
        im = im.convert("RGB")
        im.thumbnail((width, width))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def source_url(source):
    url = source.get("url") or ""
    if urlsplit(url).scheme.lower() in ("https", "http", "obsidian"):
        return url
    if source.get("source") == "obsidian" and source.get("path"):
        try:
            root = vault.check(store.load_config()["obsidian_vault"])
            return obsidian.uri(vault.inside(root, source["path"]))
        except AppError:
            pass
    return ""


def material(ctx, budget):
    """PDF precisa do conteúdo das notas, além dos trechos que fizeram o documento aparecer na busca."""
    parts, used = [], 0
    for sid in list(ctx.sources)[:tools.MAX_CALLS]:
        ctx.check()
        text, error = tools.run(ctx, "read_document", {"id": sid})
        if error:
            continue
        if parts and used + len(text) > budget:
            break
        parts.append(text)  # uma nota inteira é limitada por tools.READ_CHARS
        used += len(text)
    return '<material>\n' + ('\n\n'.join(parts) or '(nenhum documento encontrado nas fontes)') + '\n</material>'


def source_images(ctx):
    assets = []
    for sid, item in ctx.sources.items():
        for query in item.get("images", []):
            try:
                if query.startswith("h=") and images.HASH.fullmatch(query[2:]):
                    path = images.path(query[2:])
                elif query.startswith("a="):
                    rec = attachments.get(query[2:])
                    if rec["meta"].get("generated"):
                        continue
                    path = attachments.folder(rec["id"]) / "miniatura.jpg"
                else:
                    continue
                assets.append((item["title"], jpeg(path.read_bytes()), sid))
            except (OSError, AppError):
                continue
            if len(assets) == 2:
                return assets
    return assets


def chart(ctx, provider, model=None):
    if not ctx.sources:
        return []
    sid = next(iter(ctx.sources))
    text = tools._read(ctx, {"id": sid})[0]
    raw = provider.json(charts.SYSTEM, text, CHART_SCHEMA, jobs.check, max_tokens=2400, model=model)
    found = charts.validate(raw, [(None, text, True)])[:1]
    if not found:
        return []  # números ou relações não conferidos nunca viram desenho
    png = cdp.png(charts.html(found[0], static=True), charts.W, charts.H)
    if not png:
        raise AppError("O gráfico do PDF não pôde ser desenhado.")
    return [(found[0]["titulo"], jpeg(png), sid)]


def html(doc, form, decor, sources, *, dark=False, cover_src="", illustration=False, map_src="", assets=()):
    e = lambda s: markup.escape(str(s), quote=True)
    colors = llm.valid_decor(decor)["palette"]
    accent = cover._mix(colors[0], "#ffffff" if dark else "#000000", .38)
    bg, fg, muted, line = ("#14141c", "#f2f2f7", "#bfc2cf", "#545461") if dark else ("#ffffff", "#20212b", "#545765", "#c9cbd4")
    def ref(sid):
        return '<small>Conhecimento geral</small>' if sid == "geral" else f'<a class="ref" href="#fonte-{e(sid)}">[{e(sid)}]</a>'
    def paragraphs(text):
        out = []
        for line in str(text).splitlines():
            if not line.strip():
                continue
            heading = re.match(r"^#{1,6}\s+(.+)", line)
            safe = e(heading[1] if heading else line)
            safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
            safe = re.sub(r"\[(S\d+)\]", lambda m: ref(m[1]) if any(s["sid"] == m[1] for s in sources) else "", safe)
            out.append(f'<h2>{safe}</h2>' if heading else f'<p>{safe}</p>')
        return "".join(out)
    used = {b["source"] for b in doc["blocks"]} | set(doc.get("source_ids", [])) | {sid for _, _, sid in assets}
    refs = []
    for s in sources:
        url = source_url(s)
        label = f'{e(s["sid"])} · {e(s["title"])}'
        if s["sid"] not in used:
            label += ' (consultada, sem trecho atribuído)'
        refs.append(f'<li id="fonte-{e(s["sid"])}">' + (f'<a href="{e(url)}">{label}</a>' if url else label) + '</li>')
    source_block = '<section class="sources"><h2>Fontes</h2><ul>' + "".join(refs) + '</ul>'
    if "geral" in used or not refs:
        source_block += '<p>Conhecimento geral: conteúdo complementar da IA, sem fonte nas suas notas.</p>'
    source_block += '</section>'
    if assets:
        source_block = ''.join(f'<section><h2>{e(title)}</h2><img class="cover" style="height:auto;max-height:150mm;object-fit:contain" src="{e(src)}" alt="{e(title)}"><p>{ref(sid)}</p></section>' for title, src, sid in assets) + source_block
    head = f'<header><p class="eyebrow">LÚMEN · {e(TYPES[form])}</p><h1>{e(doc["title"])}</h1></header>'
    blocks = doc["blocks"]
    body = head
    if form == "apostila":
        if cover_src:
            body += f'<img class="cover" src="{e(cover_src)}" alt="Ilustração temática">'
            if illustration:
                body += '<p class="caption">Gerada por IA, pode conter erros.</p>'
        body += paragraphs(doc["summary"]) + '<nav><h2>Sumário</h2><ol>'
        body += "".join(f'<li><a href="#parte-{i}">{e(b["heading"])}</a></li>' for i, b in enumerate(blocks)) + '</ol></nav><div class="pagebreak"></div>'
    elif form not in ("exercicios", "simulado", "flashcards"):
        body += paragraphs(doc["summary"])
    if form == "flashcards":
        body = ""
        for start in range(0, len(blocks), 6):
            cards = blocks[start:start + 6]
            cards += [None] * (6 - len(cards))
            for back in (False, True):
                body += '<section class="cardpage">' + head + '<p>Frente e verso pela borda longa, tamanho real. Recorte nas linhas.</p><h2>' + ('Versos' if back else 'Frentes') + '</h2><div class="cards">'
                order = [1, 0, 3, 2, 5, 4] if back else range(6)
                for i in order:
                    b = cards[i]
                    body += '<div class="cutcard">' + (f'<small>Cartão {start+i+1}</small><p>{e(b["answer"] if back else b["question"])}</p>' + (ref(b["source"]) if back else '') if b else '') + '</div>'
                body += '</div></section>'
        body += '<section class="pagebreak">' + source_block + '</section>'
    elif form in ("exercicios", "simulado"):
        body += '<p>Responda antes de consultar o gabarito ao final.</p>'
        for i, b in enumerate(blocks, 1):
            body += f'<section class="question"><h2>Questão {i}</h2><p>{e(b["question"])}</p><div class="writing"></div></section>'
        body += '<section class="pagebreak"><h1>Gabarito</h1>'
        for i, b in enumerate(blocks, 1):
            body += f'<section><h2>{i}. {e(b["heading"])}</h2><p>{e(b["answer"])} {ref(b["source"])}</p></section>'
        body += source_block + '</section>'
    elif form == "mapa":
        if map_src:
            body += f'<img class="map" src="{e(map_src)}" alt="Mapa mental do assunto">'
        body += '<section class="pagebreak"><h2>Mapa em texto</h2>'
        for b in blocks:
            body += f'<h3>{e(b["heading"])}</h3><p>{e(b["text"])} {ref(b["source"])}</p>'
        body += source_block + '</section>'
    elif doc.get("printed_answer"):
        body += paragraphs(doc["printed_answer"])
        if map_src:
            body += f'<img class="map" src="{e(map_src)}" alt="Diagrama da explicação">'
        body += source_block
    else:
        for i, b in enumerate(blocks):
            if form == "cornell":
                body += f'<section class="cornell"><aside>{e(b["question"] or b["heading"])}</aside><div><h2>{e(b["heading"])}</h2>{paragraphs(b["text"])}{ref(b["source"])}</div></section>'
            else:
                body += f'<section id="parte-{i}"><h2>{e(b["heading"])}</h2>{paragraphs(b["text"])}{ref(b["source"])}</section>'
        if form == "cornell":
            body += '<section><h2>Resumo final</h2>' + paragraphs(doc["summary"]) + '</section>'
        body += source_block
    # Usa a família já instalada no Windows; nenhum download de fonte durante a impressão.
    return f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src file:"><title>{e(doc['title'])}</title>
<style>@page{{size:A4;margin:16mm 17mm 18mm}}*{{box-sizing:border-box}}html{{background:{bg};color:{fg}}}body{{margin:0;font:11pt/1.5 "Segoe UI",sans-serif;overflow-wrap:anywhere}}h1{{font-size:27pt;line-height:1.15;margin:4mm 0 8mm}}h2{{font-size:15pt;line-height:1.25;color:{accent};margin:7mm 0 3mm;break-after:avoid}}h3{{break-after:avoid}}p{{margin:2mm 0 4mm;orphans:3;widows:3}}a{{color:{accent};text-decoration:underline}}small,.caption{{font-size:8.5pt;color:{muted}}}.eyebrow{{font-size:9pt;letter-spacing:1.3px;color:{accent};font-weight:700}}header{{border-top:2mm solid {accent};padding-top:6mm}}section{{break-inside:avoid}}.pagebreak{{break-before:page}}.cover{{width:100%;height:65mm;object-fit:cover;border-radius:3mm}}nav{{padding:3mm 6mm;border:1px solid {line}}}nav li{{margin:2mm 0}}.sources{{font-size:9pt;border-top:1px solid {line};margin-top:8mm}}.sources h2{{font-size:12pt}}.sources li{{margin:2mm 0}}.ref{{font-size:9pt}}section.cornell{{display:grid;grid-template-columns:29% 1fr;border-bottom:1px solid {line};gap:6mm;padding-bottom:5mm}}aside{{border-right:1px solid {line};padding:7mm 4mm 0 0;font-weight:600}}.question{{padding-bottom:5mm}}.writing{{height:20mm;border-bottom:1px solid {line}}}.cards{{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:repeat(3,60mm)}}.cutcard{{padding:6mm;border:1px dashed {line};display:flex;flex-direction:column;justify-content:center}}.cutcard p{{font-size:11pt}}.cardpage{{break-before:page;height:250mm}}.cardpage:first-child{{break-before:auto}}.map{{display:block;width:100%;height:190mm;object-fit:contain}}.revisao{{font-size:10pt;line-height:1.35}}.revisao h1{{font-size:22pt;margin-bottom:4mm}}.revisao h2{{font-size:12pt;margin-top:4mm}}.revisao .sources{{margin-top:4mm}}.revisao header{{padding-top:3mm}}.revisao section{{margin-bottom:3mm}}</style><body class="{e(form)}">{body}</body></html>'''


def render(doc, form, decor, sources, **options):
    jobs.check()
    jobs._set(stage="artifact", detail="Imprimindo o PDF A4…", progress=None)
    page = html(doc, form, decor, sources, **options)
    from pypdf import PdfReader
    for scale in ((1, .9) if form == "revisao" else (1,)):
        blob = cdp.pdf(page, scale=scale, displayHeaderFooter=True, headerTemplate='<span></span>',
                       footerTemplate='<div style="width:100%;text-align:center;font:9px Segoe UI;color:#666">Lúmen · Gerado por IA, revise antes de usar · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        jobs.check()
        if not blob:
            raise AppError("O Edge não conseguiu imprimir o PDF.", "Tente novamente.")
        reader = PdfReader(io.BytesIO(blob))
        if form != "revisao" or len(reader.pages) == 1:
            break
        jobs._set(detail="Ajustando a revisão para uma página…")
    if not reader.pages or len(reader.pages) > 30 or any(not p.extract_text().strip() for p in reader.pages):
        raise AppError("O PDF ficou vazio ou passou do limite de 30 páginas.")
    if form == "revisao" and len(reader.pages) != 1:
        raise AppError("A revisão não coube em uma página.", "Peça um assunto mais específico.")
    return blob, len(reader.pages)


def make(spec, conv, payload):
    from . import agent, artifacts
    t0 = time.monotonic()
    s = settings.load()
    project = chats.project(conv["project_id"]) if conv.get("project_id") else None
    effort = payload.get("effort") if payload.get("effort") in agent.EFFORT else "equilibrado"
    chain, reasons = providers.chain(s)
    if not chain:
        raise AppError("Nenhuma IA disponível. " + " ".join(reasons))
    provider = chain[0]
    form, topic = spec["form"], spec["topic"]
    ctx = tools.Ctx(conv["id"], project, provider.name, jobs.check)
    jobs._set(stage="artifact", detail="Buscando as fontes do PDF…", progress=None)
    previous = None
    if payload.get("pdf_message"):
        previous = next((m for m in chats.get(conv["id"])["messages"] if str(m["id"]) == str(payload["pdf_message"]) and m["role"] == "assistant"), None)
        if not previous or previous.get("meta", {}).get("mode") != "explain":
            raise AppError("A explicação não foi encontrada nesta conversa.")
    if previous:
        for src in previous["sources"]:
            ctx.sources[src["sid"]] = src
    else:
        for rec in attachments.listing(conv["id"]):
            if rec["status"] == "ready":
                ctx.cite(attachments.item(rec, topic))
        for item in search.search(topic, project=project, limit=agent._sources(effort, s))["results"]:
            ctx.cite(item)
    sources = tools.public_sources(ctx)
    jobs.check()
    jobs._set(detail="Organizando o conteúdo e conferindo as citações…")
    model = (settings.max_model(s) if effort == "maximo" else settings.fast_model(s) if effort == "rapido" else None) if provider.name == "ollama" else None
    block = material(ctx, int(s["models"]["context_chars"] * agent.EFFORT[effort]["budget"])) if not previous else ""
    assets = source_images(ctx) if form in ("apostila", "explicacao", "cornell", "plano") else []
    if form in ("apostila", "explicacao", "cornell", "plano") and re.search(r"\b(gr[aá]fico|tabela|n[uú]meros|fun[cç][aã]o)\b", topic, re.I):
        jobs._set(detail="Conferindo os dados e desenhando o gráfico…")
        plotted = chart(ctx, provider, model)
        if not plotted:
            raise AppError("Não há dados conferidos suficientes para o gráfico solicitado.",
                           "Escolha uma fonte com os valores e rótulos, ou peça o PDF sem o gráfico.")
        assets += plotted
    map_src = ""
    if previous:
        text, cited, _ = agent.validate(previous["content"], ctx)
        doc = {"title": topic[:100], "summary": "", "blocks": [], "printed_answer": text, "source_ids": cited}
        if previous.get("meta", {}).get("explain", {}).get("diagram"):
            map_src = jpeg(diagram.image(previous["meta"]["explain"]["diagram"])[0])
    elif form == "mapa":
        raw = provider.json(learn.INTRO, block + '\n' + learn.TASKS['mindmap'].format(topic=topic, level=""),
                            diagram.mind_schema([*ctx.sources, "geral"]), jobs.check, max_tokens=4000, model=model)
        d = diagram.from_mind(raw, topic, ctx.sources)
        map_html = mindmap.html(diagram.to_mind(d)).replace('</style>', '''
body{background:#fff;color:#20212b}.leaf{background:#f5f6fa;border-color:#c9cbd4;font-size:19px}
#map{gap:32px}.grp{gap:24px}.br{max-width:200px}.center{max-width:250px}.mark{color:#545765}
</style>''')
        map_png = cdp.png(map_html, 1100, 900, scale=2)
        if not map_png:
            raise AppError("O mapa mental do PDF não pôde ser desenhado.", "Tente novamente.")
        map_src = jpeg(map_png, 1800)
        doc = {"title": d["title"], "summary": "", "blocks": [{"heading": b["label"], "text": b["detail"] or b["label"],
               "question": "", "answer": "", "source": d["evidence"][0] if d["evidence"] else "geral"} for b in d["nodes"]], "source_ids": d.get("evidence", [])}
    else:
        count = 6 if form == "revisao" or effort == "rapido" else 12 if effort in ("profundo", "maximo") else 8
        prompt = block + f'\nPDF: {TASK[form]}\nAssunto: {topic}\nEsforço: {effort}. Sem HTML. Extraia o conteúdo pertinente das notas; evite um panorama genérico. No campo source, cite o S# que sustenta cada bloco. Use geral só para complementos ausentes no material.'
        try:
            raw = provider.json(learn.INTRO, prompt, schema(ctx.sources, count), jobs.check, max_tokens=6000, model=model)
        except providers.Truncated:
            raw = provider.json(learn.INTRO, prompt + learn.LEAN, schema(ctx.sources, max(2, count // 2)), jobs.check, max_tokens=6000, model=model)
        doc = clean(raw, form, ctx.sources)
        for b in doc["blocks"]:
            for key in ("text", "question", "answer"):
                b[key] = agent.validate(b[key], ctx)[0]
    jobs.check()
    jobs._set(detail="Escolhendo o tema do assunto…")
    theme_system = llm.DECOR_SYSTEM.format(covers='; '.join(llm.COVERS), palettes='; '.join(llm.PALETTES))
    raw = provider.json(theme_system, f'Título: {doc["title"]}', llm.DECOR_SCHEMA, jobs.check, max_tokens=1200)
    decor = llm.valid_decor(raw) or llm.valid_decor({})
    cover_src, illustration = "", False
    if form == "apostila":
        jobs._set(detail="Desenhando a capa…")
        blob = None
        if s["pdf"]["cover_image"]:
            jobs.check()
            previous_images = [r for r in attachments.listing(conv["id"]) if r["kind"] == "image" and r["status"] == "generated"]
            if previous_images:
                blob = artifacts.file(previous_images[-1]["id"])[0].read_bytes()
            else:
                blob = artifacts.image_blob(str(raw.get("image_prompt") or topic)[:1500], 1536, 640,
                                            check=jobs.check, missing_ok=True)
            illustration = bool(blob)
        if not blob:
            blob = cover.render(decor)
        if blob:
            cover_src = jpeg(blob)
    blob, pages = render(doc, form, decor, sources, dark=s["pdf"]["dark"], cover_src=cover_src, illustration=illustration, map_src=map_src, assets=assets)
    jobs.check()
    used = {b["source"] for b in doc["blocks"]} | set(doc.get("source_ids", [])) | {sid for _, _, sid in assets}
    sources = [{**src, "cited": src["sid"] in used} for src in sources]
    return artifacts.save(conv["id"], "pdf", doc["title"], f'{TYPES[form]} pronta · {pages} página(s). Revise o conteúdo antes de usar.', sources,
                          {"generated": True, "form": form, "pages": pages, "seconds": round(time.monotonic() - t0, 2)}, blob)
