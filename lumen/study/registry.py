"""Registro único do Lúmen Study AI: comandos de barra, skills (do sistema, do cofre e do usuário), ferramentas com o
nível de permissão, integrações e modelos por papel. Alimenta o menu "/" e, nas próximas fases, o modo Automático e o
catálogo das Configurações; nenhuma dessas listas existe em outro lugar.

- Skills do cofre: <cofre>/.claude/skills/*/SKILL.md, lidas do disco só para leitura, no formato do Claude Code
  (frontmatter com name, description e argument-hint; $ARGUMENTS no corpo).
- Skills do usuário: DATA/study/skills/*/SKILL.md, no mesmo formato.
Uma skill é só texto de instrução: roda com as mesmas ferramentas, limites e prévia de gravação de qualquer resposta.
Nenhum código de fora é carregado."""
import json
import hashlib
import os
import re
import urllib.request
from pathlib import Path

from .. import AppError, llm, store, vault
from . import db, policy, providers, settings, tools
from .sources import registry as sources

MAX_SKILLS, MAX_CHARS = 60, 40_000

# Os comandos que a tela executa (study.js). A ordem é a do menu.
COMMANDS = [
    ("ajuda", "", "Lista os comandos e as skills."),
    ("clear", "", "Começa uma conversa nova, com o mesmo projeto e o mesmo modo. A atual continua no histórico."),
    ("compact", "[foco]", "Resume as mensagens antigas para a IA, sem apagar nenhuma. O foco diz o que manter."),
    ("context", "", "Mostra o que ocupa o contexto da IA nesta conversa."),
    ("modo", "<nome>", "Troca o modo da resposta: automático, buscar, explicar, resumir, comparar ou encontrar."),
    ("esforco", "<nível>", "Troca o esforço: automático, rápido, equilibrado, profundo ou máximo."),
    ("perfil", "<nome>", "Escolhe o modelo da resposta nesta conversa: automático, principal ou adulto (perfil adulto ligado nas configurações)."),
    ("livre", "", "Alterna o Modo Livre: desativa a busca no Notion e Obsidian para responder só com raciocínio puro da IA."),
    ("notas", "", "Reativa a busca e conexões com suas notas do Notion e Obsidian."),
    ("buscar", "<termos>", "Busca nas suas notas, sem IA."),
    ("web", "<consulta>", "Pesquisa guiada no Edge: busca, lê fontes públicas e cita. Você pode pausar ou parar."),
    ("perplexity", "[pergunta]", "Abre o site do Perplexity num painel do Lúmen, com a sua conta de lá: só a pergunta vai a ele. Sem pergunta, cola aqui a resposta que você copiou de lá."),
    ("nota", "<pedido>", "Cria uma nota no Obsidian conforme sua permissão de escrita, com link e Desfazer."),
    ("pagina", "<pedido>", "Cria uma página nos Estudos do Notion conforme sua permissão, com link e Desfazer."),
    ("abrir", "<obsidian|notion|edge|vault|calculator>", "Abre um aplicativo da lista permitida."),
    ("tela", "[pergunta]", "A IA vê a janela que você usava antes do Lúmen (só quando você pede; nada é guardado)."),
    ("anexar", "", "Anexa um arquivo: texto, PDF, Office, imagem, áudio ou vídeo (ou arraste, ou cole um print)."),
    ("imagem", "[quadrada|paisagem|retrato|capa] <descrição>", "Gera uma ilustração no seu PC (gerador local, sem nuvem). Para texto e relações precisas, use /mapa-mental."),
    ("pdf", "[tipo] <assunto>", "Gera um PDF A4 com tema e fontes: apostila, revisao, cornell, exercicios, flashcards, plano, simulado, mapa ou explicacao."),
    ("elegrama", "3d <assunto>", "Gera uma visualização 3D esquemática, com aparência de holograma, na conversa: animação (GIF) com PNG de reserva, para baixar."),
    ("holograma", "3d <assunto>", "O mesmo que /elegrama 3d."),
    ("temp", "", "Liga ou desliga a conversa temporária (não entra no histórico)."),
    ("memoria", "", "Abre as memórias da IA."),
    ("exportar", "", "Baixa esta conversa em Markdown."),
]
# Skills do sistema: os modos do Lúmen (agent.MODES e learn.KINDS), com nome de comando em português.
SYSTEM = [
    ("explicar", "explain", "<assunto>", "Explica um conceito com base nas suas notas, em camadas pelo esforço, com diagrama, checagem e flashcards."),
    ("resumir", "summary", "<assunto>", "Resumo estruturado do que suas notas dizem."),
    ("comparar", "compare", "<assuntos>", "Semelhanças, diferenças e contradições entre o que você estudou."),
    ("encontrar", "find", "<assunto>", "Lista os materiais que você tem sobre o assunto."),
    ("flashcards", "flashcards", "<assunto>", "Cria flashcards com revisão espaçada."),
    ("quiz", "quiz", "<assunto>", "Questionário com correção."),
    ("mapa", "map", "<assunto>", "Mapa de conhecimento: conceitos e como se ligam."),
    ("mapa-mental", "mindmap", "<assunto>", "Mapa mental do assunto, com as suas notas: explore os ramos e exporte em PNG, para o Obsidian ou o Notion."),
    ("plano", "plan", "<assunto>", "Plano de estudos com pré-requisitos e revisões."),
    ("pratica", "exercise", "<assunto>", "Tarefa com rubrica das fontes: entregue texto ou anexo e receba uma correção por critério."),
    ("acao", "action", "<curso>", "Plano aplicado ao projeto selecionado, com tarefas, prazos e revisões."),
    ("lacunas", "gaps", "<assunto>", "O que você já tem e o que falta estudar."),
]
ORIGIN = {"cofre": "do cofre", "usuario": "sua"}
TOOL_MAP = ("Você está no Lúmen, não no Claude Code. Onde a skill citar Read, Grep, Glob ou busca no cofre, use search_knowledge "
            "e read_document; para links entre notas, follow_links; Write ou Edit viram prepare_note, que só prepara uma "
            "nota conforme a permissão de escrita do estudante; Task ou um agente: faça você mesmo, passo a passo, com essas ferramentas. "
            "WebFetch vira fetch_url; WebSearch vira research_web quando a internet foi solicitada. Bash não existe aqui.")


def _frontmatter(text):
    """(campos, corpo) do SKILL.md. Só name, description e argument-hint, inclusive os de várias linhas (> ou |)."""
    text = text.removeprefix("﻿")  # arquivo salvo com BOM pelo Bloco de Notas
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta, key = {}, None
    for line in text[3:end].splitlines():
        m = re.match(r"^([\w-]+):\s*(.*)$", line)
        if m:
            key, value = m[1], m[2].strip()
            meta[key] = "" if value in (">", "|", ">-", "|-") else value.strip("\"'")
        elif key and line.startswith((" ", "\t")):
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta, text[end + 4:].lstrip("\n")


def _folder(origin):
    if origin == "usuario":
        return db.HOME / "skills"
    raw = store.load_config()["obsidian_vault"]
    try:
        return vault.check(raw) / ".claude" / "skills" if raw else None
    except AppError:
        return None


def _skills(origin):
    folder = _folder(origin)
    if not folder or not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*/SKILL.md"))[:MAX_SKILLS]:
        if not path.resolve().is_relative_to(folder.resolve()):
            continue
        try:
            meta, _ = _frontmatter(path.read_text("utf-8", errors="replace")[:MAX_CHARS])
        except OSError:
            continue
        name = re.sub(r"[^\w-]+", "-", (meta.get("name") or path.parent.name).casefold()).strip("-")[:48]
        if name:
            out.append({"id": f"{origin}:{name}", "name": name, "kind": "skill", "origin": origin, "dir": path.parent.name,
                        "args": meta.get("argument-hint", "")[:120], "description": meta.get("description", "")[:300]})
    return out


def menu(include_disabled=False):
    """O menu "/": comandos, skills do sistema, do cofre e do usuário. Um nome só aparece uma vez (o primeiro vale)."""
    items = [{"id": f"cmd:{n}", "name": n, "kind": "command", "origin": "sistema", "args": a, "description": d} for n, a, d in COMMANDS]
    items += [{"id": f"sistema:{n}", "name": n, "kind": "skill", "origin": "sistema", "mode": mode, "args": a, "description": d}
              for n, mode, a, d in SYSTEM]
    seen = {x["name"] for x in items}
    for item in _skills("cofre") + _skills("usuario"):
        if item["name"] not in seen:
            seen.add(item["name"])
            items.append(item)
    disabled = settings.load()["catalog"]["disabled"]
    return [{**x, "enabled": x["id"] not in disabled} for x in items if include_disabled or x["id"] not in disabled]


def skill(sid, editing=False):
    """A skill do cofre ou do usuário pelo id ("cofre:nome"), com o corpo. Só lê dentro da pasta de skills."""
    origin = str(sid).partition(":")[0]
    item = next((x for x in _skills(origin) if x["id"] == sid), None) if origin in ORIGIN else None
    if not item:
        raise AppError("Skill não encontrada.", "Digite / para ver a lista.")
    if not editing and sid in settings.load()["catalog"]["disabled"]:
        raise AppError("Esta skill está desligada.", "Ligue no Catálogo das Configurações.")
    raw = (_folder(origin) / item["dir"] / "SKILL.md").read_bytes()
    _, body = _frontmatter(raw.decode("utf-8", errors="replace")[:MAX_CHARS])
    return {**item, "body": body, "revision": hashlib.sha256(raw).hexdigest()}


def enable(sid, enabled):
    if type(enabled) is not bool or not any(x["id"] == sid and x["kind"] == "skill" for x in menu(True)):
        raise AppError("Skill ou opção inválida.")
    with settings.LOCK:
        s = settings.load()
        disabled = [x for x in s["catalog"]["disabled"] if x != sid]
        if not enabled:
            disabled.append(sid)
        s["catalog"]["disabled"] = disabled
        settings.write(s)
    return {"ok": True}


def save_skill(name, description, args, body, revision=""):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", name) or re.fullmatch(r"con|prn|aux|nul|com\d|lpt\d", name):
        raise AppError("Use um nome curto com letras minúsculas, números e hífens.")
    if any(not isinstance(v, str) or len(v) > n for v, n in ((description, 300), (args, 120), (body, MAX_CHARS - 600))) or not body.strip():
        raise AppError("Preencha as instruções e respeite o limite de tamanho.")
    with settings.LOCK:
        existing = next((x for x in menu(True) if x["name"] == name), None)
        if existing and existing["origin"] != "usuario":
            raise AppError("Este nome já pertence a um comando ou skill do cofre.")
        folder = db.HOME / "skills"
        path = folder / (existing["dir"] if existing else name) / "SKILL.md"
        if not path.resolve().is_relative_to(folder.resolve()):
            raise AppError("A skill precisa ficar dentro da pasta do Lúmen.")
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != revision:
            raise AppError("Esta skill mudou desde que você abriu o editor.", "Reabra antes de salvar.")
        if not path.exists() and revision:
            raise AppError("A skill foi removida. Reabra o catálogo.")
        content = f"---\nname: {name}\ndescription: {' '.join(description.split())}\nargument-hint: {' '.join(args.split())}\n---\n{body.strip()}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not revision:
            try:
                with path.open("x", encoding="utf-8") as f:
                    f.write(content)
            except FileExistsError:
                raise AppError("Já existe uma skill com este nome.") from None
        else:
            tmp = path.with_name(db.new_id() + ".tmp")
            tmp.write_text(content, "utf-8")
            os.replace(tmp, path)
    return skill("usuario:" + name, editing=True)


def instructions(item, args):
    """O trecho do prompt do sistema que manda seguir a skill neste pedido."""
    body = item["body"].replace("$ARGUMENTS", args or "(sem argumentos)")
    return (f"\n\nSkill “{item['name']}” ({ORIGIN[item['origin']]}), pedida pelo estudante. Siga as instruções dela neste "
            f"pedido; as regras de fontes e de gravação acima continuam valendo.\n{TOOL_MAP}\n<skill>\n{body}\n</skill>")


# --- Ferramentas, integrações e modelos (para o catálogo) ----------------------------------------------------------

def permissions():
    return [{"name": n, "level": s["level"], "description": s["description"]} for n, s in tools.SPECS.items()]


def _ollama_version():
    try:
        with urllib.request.urlopen(llm.OLLAMA + "/api/version", timeout=3) as r:
            return json.load(r).get("version", "")
    except (OSError, ValueError):
        return ""


def integrations(s=None):
    s = s or settings.load()
    st = providers.status(s)
    out = [{"id": "ollama", "name": "Ollama (IA local)", "on": st["ollama"]["running"], "version": _ollama_version(),
            "access": "Roda os modelos no seu PC; nada sai dele."},
           {"id": "anthropic", "name": "Claude (Anthropic)", "on": False, "version": "",
            "access": "Bloqueado: " + policy.BLOCKED_PROVIDERS["anthropic"]}]
    labels = {"obsidian": ("Obsidian", "Lê o cofre; cria conforme a autonomia escolhida. Desfazer preserva notas editadas."),
              "notion": ("Notion", "Lê páginas compartilhadas; cria nos Estudos conforme sua permissão e confirma o conteúdo."),
              "files": ("Pastas autorizadas", "Lê só as pastas que você escolheu.")}
    for name, src in sources().items():
        label, access = labels[name]
        out.append({"id": name, "name": label, "on": s["search"].get(name, False) and src.status()["connected"], "version": "",
                    "access": access})
    out.append({"id": "web", "name": "Internet", "on": s["search"]["web"], "version": "",
                "access": "Pesquisa guiada no Edge e leitura de páginas públicas, também com IA local. A consulta vai ao buscador."})
    out.append({"id": "openai", "name": "OpenAI", "on": False, "version": "", "access": "Bloqueado: " + policy.BLOCKED_PROVIDERS["openai"]})
    from .. import voicestudio
    voice_state, voice_info = voicestudio.health()
    out.append({"id": "voice", "name": "Voice Studio", "on": voice_state == "ok", "version": voice_info.get("version", "") if isinstance(voice_info, dict) else "",
                "access": "Fala e transcrição locais; vozes e modelos são geridos na seção Voz. Microfone só ao ativar."})
    return out


def models(s=None):
    s = s or settings.load()
    from .. import vision
    return {"responder": settings.local_model(s), "rapido": settings.fast_model(s), "maximo": settings.max_model(s),
            "adulto": settings.adult_model(s) if s["adult"]["enabled"] else "",
            "embeddings": s["models"]["embed"], "visao": vision.MODEL, "claude": s["models"]["anthropic"]}


def model_roles(s):
    from .. import imagegen
    names = set(llm.models() or [])
    resolved = models(s)
    labels = {"responder": "Chat local", "rapido": "Rápido e roteador", "maximo": "Esforço máximo", "adulto": "Perfil adulto",
              "embeddings": "Embeddings", "visao": "Visão"}
    out = [{"role": label, "model": resolved[k] or "Desligado", "installed": providers._installed(resolved[k], names) if resolved[k] else None,
            "section": "adult" if k == "adulto" else "models",
            "location": os.environ.get("OLLAMA_MODELS", "Gerenciado pelo Ollama"), "size": None, "vram": None} for k, label in labels.items()]
    try:
        with urllib.request.urlopen(llm.OLLAMA + "/api/tags", timeout=3) as r:
            sizes = {m["name"]: m.get("size") for m in json.load(r).get("models", [])}
        with urllib.request.urlopen(llm.OLLAMA + "/api/ps", timeout=3) as r:
            vram = {m["name"]: m.get("size_vram") for m in json.load(r).get("models", [])}
        for row in out:
            row["size"] = sizes.get(row["model"])
            row["vram"] = vram.get(row["model"])
    except (OSError, ValueError, KeyError):
        pass
    out[0]["role"] = "Chat principal (local)"
    out += [{"role": "Fala para texto (chamada)", "model": s["voice"]["call_asr"], "section": "voice", "installed": None},
            {"role": "Texto para fala", "model": s["voice"]["engine"], "section": "voice", "installed": None},
            {"role": "Imagem", "model": imagegen.DEFAULT_ENGINE, "section": "models", "installed": imagegen.ready(), "location": str(imagegen.folder())},
            {"role": "Vídeo", "model": "Desativado (o Lúmen não gera vídeo)", "section": "models", "installed": None},
            {"role": "Diagramas e 3D", "model": "Renderizador do Lúmen na CPU (sem modelo de imagem; o /elegrama 3d usa o chat só para organizar os dados)", "section": "pdf", "installed": True},
            {"role": "Reranker", "model": "Não instalado; busca híbrida por RRF", "section": "search", "installed": False}]
    return out


def catalog():
    s = settings.load()
    docs = Path(__file__).resolve().parents[2] / "docs" / "implementation"
    installs, measurements = [], ""
    try:
        for line in (docs / "LUMEN_STUDY_AI_DECISIONS.md").read_text("utf-8").splitlines():
            cells = [x.strip() for x in line.strip("|").split("|")]
            if line.startswith("| ") and len(cells) == 7 and re.match(r"\d\d/\d\d/", cells[0]):
                installs.append(dict(zip(("date", "name", "version", "size", "location", "license", "reason"), cells)))
        report = (docs / "LUMEN_STUDY_AI_MODELS.md").read_text("utf-8")
        measurements = report.partition("## Resultados com o raciocínio desligado")[2].partition("### Com o raciocínio ligado")[0][:7000]
    except OSError:
        pass
    return {"menu": menu(True), "permissions": permissions(), "integrations": integrations(s), "models": models(s),
            "roles": model_roles(s), "installations": installs, "measurements": measurements,
            "skills_folder": str(db.HOME / "skills")}
