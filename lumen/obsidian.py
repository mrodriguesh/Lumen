"""Destino Obsidian: ObsidianRenderer (StudyPackage → Markdown, Canvas e anexos) e ObsidianWriter (grava no cofre
sem destruir nada do usuário).

Onde: a pasta configurada (padrão: a área da IA do cofre, ex. “C04 Claude Obsidian/16 Lumen”, vault.default_folder);
nada é escrito fora dela. A nota é material da IA (`type: ai-study`, `author: lumen-ai`, `status: review-required`):
nunca vira nota permanente sozinha; as ideias candidatas ficam marcáveis para o usuário escrever com as palavras dele.

Atualizar sem destruir. O Lumen só controla o que está entre `%% lumen:begin %%` e `%% lumen:end <hash> %%` e
algumas chaves do frontmatter; o resto da nota (as anotações do usuário, chaves que ele criou) fica byte a byte.
O hash no marcador final é o do bloco que o Lumen gravou: se o bloco foi editado à mão, nada é gravado (conflito)
até o usuário pedir “Substituir mesmo assim” (com backup em DATA/obsidian-backups). Marcar caixas (revisões, ideias
para notas permanentes) não é edição: as marcas são levadas para a versão nova.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
import urllib.parse
from datetime import date, datetime
from pathlib import Path

from . import AppError, canvas, store, vault
from .canvas import md
from .llm import fmt_time
from .package import QUESTION_KINDS, norm
from .sources import youtube_url

log = logging.getLogger("lumen")
BEGIN = "%% lumen:begin · bloco gerado pelo Lumen; o que você escrever fora dele nunca é alterado %%"
_BEGIN = re.compile(r"^%% lumen:begin\b.*%%[ \t]*$", re.M)
_END = re.compile(r"^%% lumen:end(?: ([0-9a-f]{12}))? %%[ \t]*$", re.M)
_CHECK = re.compile(r"(?m)^(\s*[-*] )\[[^\]]\]")
OWNED = {"source", "course", "duration", "updated", "open-questions", "permanent-candidates", "lumen-id",
         "lumen-version", "content-hash", "notion"}  # o Lumen atualiza; o resto só entra se faltar
UNION = {"topics", "related", "aliases"}            # listas: o que o usuário pôs fica, o que é novo entra
RECALL = ("recordacao", "compreensao", "relacao")    # “Perguntas de active recall”; o resto, “Teste de compreensão”
KIND_LABEL = {"recordacao": "Recordação", "compreensao": "Compreensão", "relacao": "Relação", "aplicacao": "Aplicação",
              "diagnostico": "Diagnóstico", "sintese": "Síntese"}
_BAD = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
_LINK = re.compile(r"(?<!\\)\[\[([^\]\n]+?)\]\]")
_FM_LINE = re.compile(r"^([\w-]+:( .*)?|\s+- .*|\s+\S.*|\s*)$")  # o mesmo do vault-check.mjs do cofre


# --- Nomes e caminhos ----------------------------------------------------------------------------------------

def clean(title, limit=100):
    """Nome de arquivo válido no Windows e que não quebra links do Obsidian, com os acentos de antes."""
    t = _BAD.sub(" ", unicodedata.normalize("NFC", str(title or "")))
    t = " ".join(t.split()).strip(" .")[:limit].rstrip(" .") or "Aula"
    return t + " (aula)" if t.split(".")[0].upper() in _RESERVED else t


def _taken(root):
    """Nomes de arquivo já usados no cofre (o Obsidian resolve [[nome]] pelo nome, em qualquer pasta)."""
    out = {}
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            out[unicodedata.normalize("NFC", f).casefold()] = Path(r) / f
    return out


def _free(name, ext, taken, mine, extras):
    """O nome, ou o nome com o curso (e só no fim um código curto) se outro arquivo do cofre já o usa."""
    for cand in [name, *extras]:
        hit = taken.get(unicodedata.normalize("NFC", cand + ext).casefold())
        if hit is None or (mine and hit == mine):
            return cand
    return extras[-1]


def _within(path, folder):
    p = path.resolve()
    if p != folder and folder not in p.parents:
        raise AppError("O Lumen tentou gravar fora da pasta escolhida no cofre.", "Confira a pasta em Integrações → Obsidian.")
    return p


def uri(path):
    return "obsidian://open?path=" + urllib.parse.quote(str(path), safe="")


def open_path(path):
    """Abre a nota/canvas no Obsidian. O endereço é montado aqui, a partir de um arquivo do cofre."""
    if sys.platform == "win32":
        os.startfile(uri(path))  # noqa: S606 — protocolo registrado pelo Obsidian; sem shell
    else:
        import webbrowser
        webbrowser.open(uri(path))


# --- Frontmatter ---------------------------------------------------------------------------------------------

def _yaml(key, v):
    if v is None or v == "" or v == []:
        return []
    if isinstance(v, list):
        return [f"{key}:"] + [f"  - {json.dumps(str(x), ensure_ascii=False)}" for x in v]
    if isinstance(v, bool):
        return [f"{key}: {'true' if v else 'false'}"]
    if isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}|[a-z][a-z-]*", v)):
        return [f"{key}: {v}"]  # como o resto do cofre: type: ai-study, created: 2026-10-23
    return [f"{key}: {json.dumps(str(v), ensure_ascii=False)}"]


def _blocks(lines):
    out = []
    for ln in lines:
        m = re.match(r"^([\w-]+):", ln)
        if m or not out:
            out.append([m[1] if m else None, [ln]])
        else:
            out[-1][1].append(ln)
    return out


def merge_fields(old, new, owned=OWNED, remove=()):
    """Frontmatter mesclado linha a linha: chaves do Lumen atualizadas, listas somadas, o resto como estava."""
    blocks = _blocks(old)
    keys = [k for k, _ in blocks]
    for key, v in new.items():
        lines = _yaml(key, v)
        if key in keys:
            i = keys.index(key)
            if key in owned and lines:
                blocks[i][1] = lines
            elif key in UNION and isinstance(v, list):
                have = vault.fields(blocks[i][1]).get(key)
                have = have if isinstance(have, list) else [have] if have else []
                add = [x for x in v if norm(x) not in {norm(h) for h in have}]
                if add:
                    blocks[i][1] = _yaml(key, have + add)
        elif lines:
            blocks.append([key, lines])
    return [ln for k, ls in blocks if k not in remove for ln in ls]


def fields(pkg, ctx):
    lesson, src = pkg["lesson"], pkg["source"]
    stage_dates = ctx.get("review_dates") or []
    return {
        "type": "ai-study", "author": "lumen-ai", "status": "review-required", "created": ctx["created"],
        "updated": date.today().isoformat(), "source": src.get("link") or "", "course": pkg.get("course") or "",
        "duration": _duration(src.get("duration")) or "",
        "topics": [f"[[{a}]]" for a in pkg["anchors"]], "related": [f"[[{c['note']}]]" for c in pkg["connections"]],
        "aliases": [clean(lesson["title"], 200)] if clean(lesson["title"], 200) != ctx["name"] else [],
        "review-stage": 0 if stage_dates else None, "next-review": stage_dates[0] if stage_dates else None,
        "open-questions": len(lesson.get("open_questions") or []) + len(lesson.get("caveats") or []),
        "permanent-candidates": len(lesson.get("permanent_ideas") or []),
        "lumen-id": pkg["lumen_id"], "lumen-version": pkg["processor_version"],
        "content-hash": pkg["content_hash"], "notion": ctx.get("notion") or "",
    }


def _duration(seconds):
    if not seconds:
        return None
    m = round(seconds / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{max(m, 1)} min"


# --- Renderer ------------------------------------------------------------------------------------------------

def _quote(text):
    return "\n".join("> " + ln if ln.strip() else ">" for ln in str(text).split("\n"))


def _callout(kind, title, body, fold="-"):
    return f"> [!{kind}]{fold} {md(title).replace(chr(10), ' ')}\n" + _quote(body)


def _paras(text):
    return "\n\n".join(md(p.strip()) for p in re.split(r"\n\s*\n", str(text or "")) if p.strip())


def _url(u):
    """Endereço seguro dentro de [texto](endereço): parênteses e sinais de tag não fecham o link."""
    return "".join({"(": "%28", ")": "%29", "<": "%3C", ">": "%3E", " ": "%20"}.get(c, c) for c in str(u))


def _when(t, yt):
    if t is None:
        return ""
    return f"[{fmt_time(t)}]({youtube_url(yt, t)})" if yt else f"`{fmt_time(t)}`"


def _day(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso and len(iso) >= 10 else "data desconhecida"


def _list(items):
    return "\n".join(f"- {md(x)}" for x in items)


def _understanding(u):
    a = u.get("ai_analysis") or {}
    out = ["## Minha compreensão",
           _callout("quote", "Minha nota original", md(u["original_understanding"]), fold=""),
           f"*Escrita por você em {_day(u.get('submitted'))}, antes da análise da IA. O Lumen não altera este texto.*"]
    cur = (u.get("current_understanding") or "").strip()
    if cur and cur != u["original_understanding"].strip():
        out.append(_callout("quote", "Minha versão atual (editada depois da análise)", md(cur)))
    if u.get("earlier"):
        out.append(_callout("quote", "Compreensões anteriores desta aula", "\n\n".join(
            f"*Escrita em {_day(e.get('at'))}*\n{md(e['text'])}" for e in u["earlier"][-10:])))
    if a:
        out.append(f"### Análise da IA sobre a minha compreensão\n*A IA local ({u.get('model') or 'Ollama'}) comparou "
                   "a minha nota com a aula. Complementa o que escrevi; não substitui.*")
        for kind, title, items in (("success", "O que compreendi corretamente", a.get("acertos")),
                                   ("note", "O que entendi em parte", a.get("parciais")),
                                   ("todo", "O que faltou", a.get("lacunas"))):
            if items:
                out.append(_callout(kind, title, _list(items)))
        if a.get("confusoes"):
            out.append(_callout("warning", "Possíveis confusões", "\n".join(
                f"- Escrevi: *“{md(c['trecho'])}”* · Na aula: {md(c['correcao'])}" for c in a["confusoes"])))
        for kind, title, items in (("info", "Complementos", a.get("complementos")),
                                   ("info", "Conexões que deixei passar", a.get("conexoes")),
                                   ("question", "Perguntas para aprofundar", a.get("perguntas"))):
            if items:
                out.append(_callout(kind, title, _list(items)))
    return out


def _chart(c, name):
    from .charts import fmt
    if c["tipo"] == "linha_do_tempo":
        rows = [["Ano", "Acontecimento"]] + [[e["data"], e["texto"]] for e in c["eventos"]]
    elif c["tipo"] == "funcao":
        rows = [["Curva", "Fórmula"]] + [[f["nome"], f["expressao"]] for f in c["funcoes"]]
    else:
        unit = f" ({c['unidade']})" if c.get("unidade") else ""
        rows = [[c["eixo_x"]] + [(s["nome"] or "Valor") + unit for s in c["series"]]]
        rows += [[lab] + [fmt(s["valores"][i]) for s in c["series"]] for i, lab in enumerate(c["rotulos"])]
    table = "\n".join("| " + " | ".join(md(x, table=True) for x in r) + " |" for r in rows[:1]) + "\n" + \
        "|" + "---|" * len(rows[0]) + "\n" + \
        "\n".join("| " + " | ".join(md(x, table=True) for x in r) + " |" for r in rows[1:])
    head = [f"### {md(c['titulo'])}"] + ([f"![[{name}]]"] if name else []) + ([md(c["mensagem"])] if c.get("mensagem") else [])
    return "\n\n".join(head + [table])


def render(pkg, ctx):
    """O bloco gerenciado da nota (Markdown). ctx: name, canvas (nome do .canvas ou None), files (nota conectada →
    caminho), images (id da tela → arquivo), charts (índice → arquivo), template (nome do template de nota
    permanente, se existir no cofre), review_dates, notion, transcript (linhas, opcional)."""
    lesson, src, yt = pkg["lesson"], pkg["source"], pkg["source"].get("yt_id")
    s = [f"# {md(lesson['title'])}"]

    info = [f"- **Aula original:** [Assistir ao material original]({_url(src['link'])})" if src.get("link") else "",
            f"- **Curso:** {md(pkg['course'])}" if pkg.get("course") else "",
            f"- **Duração:** {_duration(src.get('duration'))}" if src.get("duration") else "",
            f"- **Origem:** {md(src.get('label') or '')} · {md(src.get('title') or '')}",
            f"- **Transcrição:** {md(src.get('origin') or '')}" if src.get("origin") else ""]
    s.append("## Fonte\n" + "\n".join(x for x in info if x))
    s += _understanding(pkg["understanding"])

    summary = [p.strip() for p in re.split(r"\n\s*\n", lesson["summary"]) if p.strip()]
    s.append("## Visão geral\n" + _callout("abstract", "Ideia central", md(summary[0]), fold="")
             + ("\n\n" + _paras("\n\n".join(summary[1:])) if summary[1:] else ""))
    if ctx.get("canvas"):
        s.append(f"## Mapa mental\n![[{ctx['canvas']}]]")
    concepts = []
    for t in lesson["topics"]:
        when = _when(t.get("timestamp"), yt)
        concepts.append(f"### {md(t['title'])}\n" + (f"{when} · " if when else "") + md(t["explanation"])
                        + (f"\n\n**Por que importa:** {md(t['why'])}" if t.get("why") else ""))
    s.append("## Conceitos essenciais\n" + "\n\n".join(concepts))
    s.append("## Explicação\n*Escrita pela IA a partir da aula, em linguagem simples.*\n\n"
             + _paras(lesson["simple_explanation"]))
    if lesson.get("glossary"):
        s.append("## Glossário\n| Termo | Significado |\n|---|---|\n" + "\n".join(
            f"| **{md(g['term'], True)}** | {md(g['definition'], True)} |" for g in lesson["glossary"]))
    if lesson.get("examples"):
        s.append("## Exemplos\n" + "\n".join(
            f"- **{'Da aula' if e['origin'] == 'aula' else 'Analogia (IA)'}:** {md(e['text'])}" for e in lesson["examples"]))
    if lesson.get("steps"):
        s.append("## Passo a passo\n" + "\n".join(f"{i}. {md(x)}" for i, x in enumerate(lesson["steps"], 1)))
    if pkg.get("charts"):
        s.append("## Gráficos da aula\n*Feitos só com dados da aula, conferidos pelo Lumen.*\n\n" + "\n\n".join(
            _chart(c, (ctx.get("charts") or {}).get(i)) for i, c in enumerate(pkg["charts"])))
    if pkg.get("screens"):
        shots = []
        for sc in pkg["screens"]:
            when = "" if sc["manual"] else _when(sc.get("t"), yt)
            img = (ctx.get("images") or {}).get(sc["id"])
            body = "\n\n".join(x for x in (f"![[{img}]]" if img else "", md(sc["texto"]),
                                            f"*Figura: {md(sc['descricao'])}*" if sc.get("descricao") else "") if x)
            shots.append(f"### {(when + ' · ') if when else ''}{md(sc['titulo'] or 'Tela')}\n" + body)
        s.append("## O que apareceu na tela\n*Lido por um modelo de visão local: confira números e fórmulas na "
                 "imagem.*\n\n" + "\n\n".join(shots))

    qs = lesson.get("review_questions") or []
    recall = [q for q in qs if q.get("kind", "recordacao") in RECALL]
    deep = [q for q in qs if q.get("kind", "recordacao") not in RECALL]

    def ask(items):
        return "\n\n".join(_callout("question", q["question"],
                                    (f"*{KIND_LABEL[q['kind']]}* · " if q.get("kind") in KIND_LABEL else "")
                                    + md(q["answer"])) for q in items)
    if recall:
        s.append("## Perguntas de active recall\n*Responda antes de abrir cada pergunta.*\n\n" + ask(recall))
    if deep:
        s.append("## Teste de compreensão\n*Perguntas de aplicação, diagnóstico e síntese: exigem raciocínio, não "
                 "memória.*\n\n" + ask(deep))
    if pkg.get("flashcards"):
        s.append("## Flashcards\n" + "\n\n".join(_callout("example", c["front"], md(c["back"])) for c in pkg["flashcards"]))
    if lesson.get("mistakes"):
        s.append("## Erros comuns\n" + _list(lesson["mistakes"]))
    if lesson.get("applications"):
        s.append("## Aplicações práticas\n" + _list(lesson["applications"]))

    files = ctx.get("files") or {}
    links = [c for c in pkg["connections"] if c["note"] in files]
    conn = [f"- [[{c['note']}]] · *{md(c.get('relation') or 'relacionado')}* — {md(c['reason'])}" for c in links]
    anchors = [a for a in pkg["anchors"] if a in files]
    if anchors:
        conn.append("- **Anchor Topics:** " + ", ".join(f"[[{a}]]" for a in anchors))
    if pkg.get("anchor_suggestion") and not anchors:
        conn.append(_callout("tip", "Sugestão de Anchor Topic", f"{md(pkg['anchor_suggestion'])}. Nenhuma nota foi "
                             "criada: crie a sua em A02 se fizer sentido.", fold=""))
    if conn:
        s.append("## Conexões\n*Notas reais do cofre, escolhidas pela IA local entre as mais parecidas, com o "
                 "motivo de cada uma.*\n\n" + "\n".join(conn))
    if lesson.get("open_questions") or lesson.get("caveats"):
        s.append("## Perguntas em aberto\n" + _list(lesson.get("open_questions") or []) + (
            ("\n\n" if lesson.get("open_questions") else "")
            + _callout("warning", "Pontos de atenção", _list(lesson["caveats"])) if lesson.get("caveats") else ""))
    if pkg.get("timeline"):
        s.append("## Linha do tempo\n| Tempo | Momento |\n|---|---|\n" + "\n".join(
            f"| {_when(x['t'], yt)} | {md(x['label'], True)} |" for x in pkg["timeline"]))
    if ctx.get("review_dates"):
        s.append("## Revisões\n*Marque cada revisão feita: o Lumen atualiza a próxima data.*\n\n" + "\n".join(
            f"- [ ] Revisão {i} · {d}" for i, d in enumerate(ctx["review_dates"], 1)))
    if lesson.get("permanent_ideas"):
        how = f"usando [[{ctx['template']}]]" if ctx.get("template") else "como nota permanente"
        s.append("## Possíveis notas permanentes\n*Ideias desta aula que podem virar conhecimento seu. Escreva com "
                 f"as suas palavras, {how}; o Lumen nunca cria notas permanentes.*\n\n"
                 + "\n".join(f"- [ ] {md(x)}" for x in lesson["permanent_ideas"]))
    if ctx.get("transcript"):
        s.append(_callout("note", "Transcrição completa", md("\n".join(ctx["transcript"]))))
    meta = [f"ID: `{pkg['lumen_id']}`", f"Versão do processamento: {pkg['processor_version']}",
            f"Processado pela primeira vez em: {_day(ctx['created'])}", f"Hash do conteúdo: `{pkg['content_hash']}`",
            f"IA: {md(src.get('model') or '')}" + (f" · visão: {md(src['vision_model'])}" if src.get("vision_model") else "")]
    if src.get("uncertain"):
        meta.append(f"{src['uncertain']} trecho(s) da transcrição com baixa confiança")
    if ctx.get("notion"):
        meta.append(f"Notion: [abrir a página]({_url(ctx['notion'])})")
    s.append(_callout("note", "Metadados Lumen", "\n".join("- " + x for x in meta)))
    return "\n\n".join(s)


INFO = """> [!info]- Como usar esta nota
> Material de estudo processado pelo Lumen a partir da aula e da minha compreensão. Estude primeiro a visão geral e o mapa mental, responda às perguntas antes de abrir as respostas e use as Conexões para ligar o assunto ao resto do cofre. Marque cada revisão feita em Revisões; o Lumen atualiza a próxima data. Ideias que valem guardar viram nota permanente escrita por mim. O bloco do Lumen é refeito quando a aula é reprocessada; o que eu escrever em "Minhas anotações" nunca é alterado.

> [!warning] Conteúdo gerado por IA
> Este material foi produzido pela IA local do Lumen e ainda não representa necessariamente minhas conclusões. Deve ser revisado antes de entrar no meu conhecimento permanente. A seção "Minha compreensão" é o texto que eu escrevi, sem alteração."""
USER = "## Minhas anotações\n%% Área sua: o Lumen nunca altera nada daqui para baixo. %%\n"


def block_hash(block):
    """Hash do bloco do Lumen sem contar caixas marcadas (marcar uma revisão não é editar o material)."""
    t = _CHECK.sub(r"\1[ ]", block.replace("\r", ""))
    return hashlib.sha256("\n".join(ln.rstrip() for ln in t.strip("\n").split("\n")).encode()).hexdigest()[:12]


def parts(text):
    """(frontmatter, antes do bloco com o marcador, bloco, hash gravado, depois) ou None sem os dois marcadores."""
    fm, body = vault.split(text.replace("\r\n", "\n"))
    b, e = list(_BEGIN.finditer(body)), list(_END.finditer(body))
    if len(b) != 1 or len(e) != 1 or e[0].start() < b[0].end():
        return None
    return fm, body[:b[0].end()], body[b[0].end():e[0].start()], e[0].group(1), body[e[0].end():]


def compose(fm, before, block, after):
    return "---\n" + "\n".join(fm) + "\n---\n" + before + "\n\n" + block.strip("\n") + "\n\n" + \
        f"%% lumen:end {block_hash(block)} %%" + after


def new_file(fm, block):
    return compose(fm, "\n" + INFO + "\n\n" + BEGIN, block, "\n\n" + USER)


def update(text, fm_new, block, force=False):
    """Nota existente + material novo → texto novo (ou AppError de conflito). Fora do bloco, nada muda."""
    p = parts(text)
    if not p:
        if not force:
            raise AppError("A nota do Obsidian foi editada e perdeu as marcas do bloco do Lumen.",
                           "Use “Substituir mesmo assim” (uma cópia da nota atual é guardada) ou restaure as marcas.")
        fm, body = vault.split(text.replace("\r\n", "\n"))
        return new_file(merge_fields(fm, fm_new), block) + "\n" + _callout(
            "note", "Texto anterior da nota (guardado pelo Lumen ao substituir)", md(body))
    fm, before, old, saved, after = p
    if saved != block_hash(old) and not force:
        raise AppError("A nota do Obsidian foi editada dentro do bloco do Lumen desde a última vez.",
                       "Use “Substituir mesmo assim” (uma cópia da nota atual é guardada) ou mova suas mudanças "
                       "para “Minhas anotações”.")
    done = {norm(x) for x in re.findall(r"(?m)^\s*[-*] \[[xX]\] (.+)$", old)}
    block = re.sub(r"(?m)^(\s*[-*] )\[ \] (.+)$", lambda m: m[1] + ("[x] " if norm(m[2]) in done else "[ ] ") + m[2], block)
    return compose(merge_fields(fm, fm_new), before, block, after)


def check(text, known):
    """Problemas do arquivo antes de gravar ([] = ok): frontmatter, callout do topo, marcadores, links que não
    existem no cofre e segredos. known: nomes de arquivos do cofre (minúsculos, com e sem extensão)."""
    from .package import _SECRET
    probs = []
    fm, body = vault.split(text)
    for ln in fm:
        if not _FM_LINE.match(ln) or re.match(r"^[\w-]+:\s+(\{\{|\[\[)", ln):
            probs.append(f"frontmatter: {ln[:60]}")
    if not re.match(r"^\s*> \[!info\]- ", body):
        probs.append("falta o callout “Como usar esta nota” no topo")
    if not parts(text):
        probs.append("marcadores do bloco do Lumen")
    clean_text = re.sub(r"```.*?```|`[^`\n]*`|%%.*?%%", " ", text, flags=re.S)
    for raw in _LINK.findall(clean_text):
        target = raw.split("|")[0].split("#")[0].strip()
        if target and unicodedata.normalize("NFC", target).casefold() not in known:
            probs.append(f"link para nota inexistente: {target}")
    if _SECRET.search(text):
        probs.append("possível credencial no texto")
    return probs


# --- Writer --------------------------------------------------------------------------------------------------

def _write(path, data, binary=False):
    """Arquivo temporário oculto na mesma pasta (o Obsidian ignora nomes com ponto) e troca atômica."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".lumen-tmp")
    if binary:
        tmp.write_bytes(data)
    else:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
    os.replace(tmp, path)


def _backup(path, lid):
    """Cópia da versão anterior fora do cofre (DATA/obsidian-backups/<id>), as 10 últimas por aula."""
    folder = store.DATA / "obsidian-backups" / lid
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, folder / f"{datetime.now():%Y%m%d-%H%M%S} {path.name}")
    for old in sorted(folder.iterdir())[:-10]:
        old.unlink(missing_ok=True)


def folders(cfg):
    """(cofre, pasta das notas, pasta dos mapas), todos conferidos dentro do cofre."""
    root = vault.check(cfg["obsidian_vault"])
    notes = vault.inside(root, cfg["obsidian_folder"] or vault.default_folder(root))
    maps = vault.inside(root, cfg["obsidian_canvas_folder"]) if cfg["obsidian_canvas_folder"] else notes
    return root, notes, maps


def deliver(pkg, cfg, assets=None, prev=None, force=False, notion=None, transcript=None):
    """Grava a aula no cofre e devolve o que foi feito (para o manifesto e a tela). Canvas e painel têm status
    próprio: falha neles não desfaz a nota. AppError só quando a nota em si não pôde ser salva."""
    root, folder, maps = folders(cfg)
    assets, prev = assets or {}, prev or {}
    notes = vault.index(root)
    taken = _taken(root)
    lid, lesson = pkg["lumen_id"], pkg["lesson"]
    found = vault.find(notes, lid)
    path = (root / found["path"]) if found else None  # renomeada ou movida dentro da pasta do Lumen: atualiza lá
    if path and folder not in path.resolve().parents:
        raise AppError(f"A nota desta aula foi movida para fora da pasta do Lumen ({found['path']}) e não foi alterada.",
                       "Para o Lumen atualizá-la, mova a nota de volta para a pasta do Lumen.")
    created = pkg["date"]
    text = None
    if path:
        text = path.read_text("utf-8")
        created = str(vault.fields(vault.split(text)[0]).get("created") or created)
    title = clean(lesson["title"])
    course = clean(pkg["course"], 40) if pkg.get("course") else ""
    if not path:
        base = f"{pkg['date']} - {title}"
        while len(str(folder / base)) > 230 and len(title) > 20:
            title = title[:len(title) - 10].rstrip(" .")
            base = f"{pkg['date']} - {title}"
        name = _free(base, ".md", taken, None, [f"{base} ({course})" if course else base, f"{base} · {lid[3:9]}"])
        path = folder / f"{name}.md"
    name = path.stem
    _within(path, folder)

    from datetime import timedelta
    start = date.fromisoformat(created) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", created) else date.fromisoformat(pkg["date"])
    dates = [(start + timedelta(days=int(d))).isoformat() for d in cfg["review_intervals"]] if cfg["obsidian_review"] else []
    files = {n["name"]: n["path"] for n in reversed(notes)}
    template = next((n["name"] for n in notes if n["name"] == "Template - Nota Permanente"), None)
    known = set(taken) | {k.rsplit(".", 1)[0] for k in taken if "." in k} | {name.casefold(), (name + ".md").casefold()}

    # Tudo é calculado antes de gravar: uma nota em conflito não deixa canvas nem anexos pela metade.
    # Anexos: só as telas escolhidas e os gráficos desenhados; o vídeo nunca entra no cofre.
    images, charts, writes = {}, {}, []
    if cfg["obsidian_attachments"]:
        attach, slug = folder / "Anexos", clean(lesson["title"], 40).casefold()
        named = [(f"tela {int(k) + 1:02d}.jpg", k, v, images) for k, v in (assets.get("screens") or {}).items()]
        named += [(f"grafico {i + 1}.gif", i, v, charts) for i, v in enumerate(assets.get("charts") or [])]
        for suffix, k, data, into in named:
            if data:
                f = _within(attach / f"{pkg['date']} {slug} {suffix}", folder)
                if not (f.exists() and f.stat().st_size == len(data)):
                    writes.append((f, data))
                into[k] = f.name
        known |= {n.casefold() for n in [*images.values(), *charts.values()]}

    out = {"status": "ok", "vault": str(root), "connections": len([c for c in pkg["connections"] if c["note"] in files]),
           "questions": len(lesson.get("review_questions") or []), "attachments": len(images) + len(charts)}
    plan = None  # (caminho do canvas, JSON)
    if cfg["obsidian_canvas"]:
        try:
            cpath = _canvas_of(root, maps, lid, prev)
            if not cpath:
                cbase = f"Mapa - {title}"
                cname = _free(cbase, ".canvas", taken, None, [f"{cbase} ({course})" if course else cbase,
                                                              f"{cbase} · {lid[3:9]}"])
                cpath = maps / f"{cname}.canvas"
            _within(cpath, maps)
            fresh = canvas.build(pkg, path.relative_to(root).as_posix(), files)
            probs = canvas.check(fresh)
            if probs:
                raise AppError("O mapa mental não passou na verificação (" + probs[0] + ").", "Tente de novo.")
            final = fresh
            if cpath.exists():  # o que o usuário moveu ou criou no canvas fica (canvas.merge)
                raw = cpath.read_text("utf-8")
                try:
                    old = json.loads(raw)
                except ValueError:
                    old = None
                same = hashlib.sha256(raw.encode()).hexdigest()[:12] == prev.get("canvas_hash")
                final = fresh if same else canvas.merge(old, fresh)
                if canvas.check(final, layout=False):
                    final = fresh
            plan = (cpath, canvas.dumps(final))
        except (AppError, OSError, ValueError, KeyError, TypeError) as e:
            log.warning("obsidian: canvas não gerado: %s", type(e).__name__)
            out["canvas_error"] = str(e) if isinstance(e, AppError) else "Não foi possível gerar o mapa mental."

    def note(canvas_name):
        ctx = {"name": name, "canvas": canvas_name, "files": files, "images": images, "charts": charts,
               "template": template, "review_dates": dates, "created": created, "notion": notion,
               "transcript": transcript}
        fm, block = fields(pkg, ctx), render(pkg, ctx)
        if text is None:
            return new_file(merge_fields([], fm), block), "created"
        # as chaves de revisão já são da nota (sync_reviews): reprocessar não volta o estudo ao início
        p = parts(text)
        same = p and p[3] == block_hash(block)  # mesmo material: nem a data de atualização muda (idempotente)
        r = update(text, {k: v for k, v in fm.items() if k not in ("review-stage", "next-review")
                          and not (same and k == "updated")}, block, force)
        return r, "unchanged" if r == text.replace("\r\n", "\n") else "updated"

    result, state = note(plan[0].name if plan else None)  # conflito → AppError aqui, antes de gravar qualquer coisa
    probs = check(result, known | ({plan[0].name.casefold()} if plan else set()))
    if probs:
        log.warning("obsidian: nota recusada na validação: %s", probs[0].split(":")[0])  # sem nomes de notas
        raise AppError(f"O material para o Obsidian não passou na validação ({probs[0]}).", "Tente de novo.")
    for f, data in writes:
        _write(f, data, binary=True)
    if plan:
        cpath, data = plan
        try:
            if not cpath.exists() or cpath.read_text("utf-8") != data:
                if cpath.exists():
                    _backup(cpath, lid)
                _write(cpath, data)
            out.update(canvas=cpath.relative_to(root).as_posix(), canvas_hash=hashlib.sha256(data.encode()).hexdigest()[:12])
        except OSError as e:
            log.warning("obsidian: canvas não gravado: errno=%s", e.errno)
            out["canvas_error"] = "Não foi possível gravar o mapa mental no cofre."
            result, state = note(None)  # sem o mapa embutido: nenhum link quebrado
    if state != "unchanged":
        if text is not None:
            _backup(path, lid)
        _write(path, result)
    canvas_name = out.get("canvas")
    out.update(note=path.relative_to(root).as_posix(), state=state)
    log.info("obsidian: nota %s; canvas %s; %d conexões; %d anexos", state, "ok" if canvas_name else "não",
             out["connections"], out["attachments"])
    for step in (lambda: dashboard(root, folder), lambda: sync_reviews(cfg)):
        try:
            step()
        except (AppError, OSError, ValueError) as e:
            log.warning("obsidian: painel/revisões: %s", type(e).__name__)
    return out


def _canvas_of(root, maps, lid, prev):
    """O canvas desta aula: o do manifesto ou, sem ele (dados locais apagados, arquivo renomeado), o que tem o card
    central desta aula (o id é estável). Nunca um segundo canvas para a mesma aula."""
    if prev.get("canvas") and (root / prev["canvas"]).is_file():
        return root / prev["canvas"]
    center = canvas.center_id(lid)
    for f in sorted(maps.rglob("*.canvas")):
        try:
            if center in f.read_text("utf-8"):
                return f
        except OSError:
            continue
    return None


def set_fields(path, values):
    """Só o frontmatter (ex.: o link do Notion depois de publicar). O resto do arquivo fica igual."""
    text = path.read_text("utf-8").replace("\r\n", "\n")
    fm, body = vault.split(text)
    if not fm:
        return
    keep = {k: v for k, v in values.items() if v not in (None, "")}
    new = merge_fields(fm, keep, owned=set(values), remove=[k for k, v in values.items() if v in (None, "")])
    if new != fm:
        _write(path, "---\n" + "\n".join(new) + "\n---\n" + body)


# --- Revisões e painel ---------------------------------------------------------------------------------------

REVIEW_MARK = re.compile(r"(?m)^\s*[-*] \[([ xX])\] Revisão \d+ · (\d{4}-\d{2}-\d{2})")
_review_seen = {}  # nota → (mtime, estado): o Início lê a pasta a cada abertura, e só relê a nota que mudou


def _review_state(f):
    """Uma nota de estudo do Lumen e as revisões marcadas nela: (campos, quantas feitas, próxima data) ou None."""
    try:
        mtime = f.stat().st_mtime_ns
        hit = _review_seen.get(f)
        if hit and hit[0] == mtime:
            return hit[1]
        fm, body = vault.split(f.read_text("utf-8"))
    except (OSError, UnicodeDecodeError):  # sem permissão, apagada no meio ou noutra codificação: só ela fica de fora
        return None
    d, marks = vault.fields(fm), REVIEW_MARK.findall(body)
    out = (d, sum(1 for m, _ in marks if m != " "), next((day for m, day in marks if m == " "), None)) \
        if d.get("type") == "ai-study" and marks else None
    _review_seen[f] = (mtime, out)
    return out


def sync_reviews(cfg):
    """Revisões marcadas → `review-stage` (quantas) e `next-review` (a próxima data não marcada; some no fim).
    Só nas notas `ai-study` da pasta do Lumen, e só essas duas chaves."""
    if cfg["destinations"] == "notion" or not cfg["obsidian_review"]:
        return 0
    root, folder, _ = folders(cfg)
    changed = 0
    for f in folder.rglob("*.md"):
        st = _review_state(f)
        if not st:
            continue
        d, stage, nxt = st
        if str(d.get("review-stage")) != str(stage) or (d.get("next-review") or None) != nxt:
            set_fields(f, {"review-stage": stage, "next-review": nxt})
            changed += 1
    return changed


def due_reviews(cfg, today=None):
    """Para o Início do Lumen: as notas de estudo com revisão para hoje ou atrasada, as mais atrasadas primeiro. Vem
    das caixas marcadas na própria nota (vale na hora, sem esperar o sync_reviews da abertura); nada no cofre muda."""
    if cfg["destinations"] == "notion" or not cfg["obsidian_review"]:
        return []
    today = (today or date.today()).isoformat()
    _, folder, _ = folders(cfg)
    out = []
    for f in folder.rglob("*.md"):
        st = _review_state(f)
        if not st or not st[2] or st[2] > today:
            continue
        d, stage, nxt = st
        out.append({"title": re.sub(r"^\d{4}-\d{2}-\d{2} - ", "", f.stem), "lumen_id": d.get("lumen-id"),
                    "next_review": nxt, "stage": stage, "overdue": nxt < today})
    return sorted(out, key=lambda r: r["next_review"])


def dashboard(root, folder):
    """Painel dos estudos (Bases, plugin nativo do Obsidian): criado se faltar; o bloco do Lumen acompanha o modelo."""
    path = folder / "Lumen Dashboard.md"
    rel = folder.relative_to(root).as_posix()
    block = DASHBOARD.replace("{folder}", rel.replace('"', '\\"'))
    fm = ["type: system", "author: lumen-ai", "status: active", f"created: {date.today().isoformat()}"]
    if not path.exists():
        _write(path, compose(fm, "\n" + DASH_INFO + "\n\n" + BEGIN, block, "\n\n" + USER))
        return
    text = path.read_text("utf-8")
    p = parts(text)
    if p and p[3] == block_hash(p[2]) and block_hash(block) != p[3]:
        _write(path, compose(p[0], p[1], block, p[4]))


DASH_INFO = """> [!info]- Como usar esta nota
> Painel dos estudos processados pelo Lumen. "Para revisar" mostra o que vence hoje e o que está atrasado; as outras visões agrupam por curso, por Anchor Topic, por dúvidas e por ideias que podem virar nota permanente. As listas se atualizam sozinhas (Bases, plugin nativo). Ao marcar uma revisão numa nota, o Lumen atualiza a próxima data quando é aberto ou processa outra aula."""

_STUDY = """filters:
  and:
    - file.inFolder("{folder}")
    - 'type == "ai-study"'"""
DASHBOARD = f"""# Lumen Dashboard

## Para revisar
```base
{_STUDY}
views:
  - type: table
    name: Para revisar hoje
    filters:
      and:
        - 'note["next-review"] <= today()'
    order:
      - file.name
      - course
      - review-stage
      - next-review
    sort:
      - property: next-review
        direction: ASC
  - type: table
    name: Atrasados
    filters:
      and:
        - 'note["next-review"] < today()'
    order:
      - file.name
      - course
      - review-stage
      - next-review
    sort:
      - property: next-review
        direction: ASC
  - type: table
    name: Estudando agora
    filters:
      and:
        - 'note["review-stage"] > 0'
        - 'note["next-review"]'
    order:
      - file.name
      - course
      - review-stage
      - next-review
```

## Biblioteca de estudos
```base
{_STUDY}
views:
  - type: table
    name: Processados recentemente
    limit: 20
    order:
      - file.name
      - course
      - topics
      - created
    sort:
      - property: created
        direction: DESC
  - type: table
    name: Não revisados
    filters:
      and:
        - 'status == "review-required"'
    order:
      - file.name
      - course
      - created
  - type: table
    name: Por curso
    order:
      - file.name
      - course
      - created
    groupBy:
      property: course
      direction: ASC
  - type: table
    name: Por Anchor Topic
    order:
      - file.name
      - topics
      - course
    groupBy:
      property: topics
      direction: ASC
  - type: table
    name: Com dúvidas
    filters:
      and:
        - 'note["open-questions"] > 0'
    order:
      - file.name
      - open-questions
      - course
  - type: table
    name: Para virar nota permanente
    filters:
      and:
        - 'note["permanent-candidates"] > 0'
    order:
      - file.name
      - permanent-candidates
      - topics
```"""
