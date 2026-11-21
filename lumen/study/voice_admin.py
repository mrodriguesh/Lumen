"""A voz por dentro (fase 6, parte 2; D55 a D59): os modelos e motores do Voice Studio escolhidos pelo Lúmen, o painel
"Esta máquina", as pronúncias e as vozes por descrição.

Leitura é livre (GET). Toda escrita no Voice Studio vem de um POST com `action`, que só a tela manda depois do clique
do estudante, e passa por voicestudio.write() (fica no log). Baixar e remover pedem `confirm` e o tamanho; nenhum
download deixa o disco de destino abaixo de 10 GB livres (o mínimo do próprio Voice Studio)."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .. import AppError, llm, transcribe, voicestudio
from . import db, listen, settings

MOVE_TO = Path(r"D:\Lumen\voicestudio\models")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _body(h):
    b = h._json()
    if not isinstance(b, dict):
        raise AppError("Pedido inválido.")
    return b


def _running():
    return voicestudio.health()[0] == "ok"


# --- modelos, pacotes, motores e qualidade (D55, D56) -------------------------------------------------------------------

def lumen_asr():
    """O Whisper do próprio Lúmen (não o do Voice Studio): o do "apertar para falar" e o da conferência dos áudios."""
    from .. import store, voice
    ptt = transcribe.pick(store.load_config()["quality"])[1]["name"]
    loaded = {name for name, dev in transcribe._loaded if dev == "cuda"}
    rows = []
    for name, use in ((ptt, "Apertar para falar"), (voice.CHECKER, "Conferência dos áudios longos")):
        row = next((r for r in rows if r["name"] == name), None)
        if row:
            row["uses"].append(use)
            continue
        rows.append({"name": name, "uses": [use], "size": transcribe.SIZES.get(name, ""),
                     "vram_gb": transcribe.VRAM_NEED_GB.get(name), "loaded": name in loaded})
    return rows


def _models(h):
    s = settings.load()["voice"]
    rec = _record()
    out = {"running": _running(), "quality": {"chat": s["chat_quality"], "long": s["long_quality"]},
           "steps": listen.STEPS, "lumen_asr": lumen_asr(), "move": dict(MOVE), "move_to": str(MOVE_TO),
           "move_old": rec["src"] if rec and Path(rec["src"]).is_dir() else None}
    if not out["running"]:
        return out
    out["catalog"] = voicestudio.catalog()
    out["engines"] = {"tts": voicestudio.engines("tts"), "asr": voicestudio.engines("asr")}
    try:
        st = voicestudio.storage()
        cats = {c.get("id"): c for c in st.get("categories") or []}
        out["storage"] = {"models_bytes": (cats.get("hf_cache") or {}).get("bytes"),
                          "temp_bytes": (cats.get("temp") or {}).get("bytes"), "min_free_gb": st.get("min_free_gb")}
    except AppError:
        out["storage"] = None
    return out


def _dest_free_gb():
    eff = (voicestudio.models_dir() or {}).get("effective") or ""
    return voicestudio.disk_free_gb(eff) if eff else None


def _check_disk(size_gb):
    free = _dest_free_gb()
    if free is not None and free - float(size_gb or 0) < voicestudio.MIN_FREE_GB:
        raise AppError(f"Espaço insuficiente: depois de baixar ficariam {max(free - float(size_gb or 0), 0):.1f} GB livres no "
                       "disco dos modelos (o mínimo é 10 GB).", "Libere espaço ou mova a pasta dos modelos para o D:.")


def _model_action(h):
    """As ações da seção "Modelos de voz". Cada uma muda também no Voice Studio, e só acontece pelo clique."""
    b = _body(h)
    action = b.get("action")
    if action == "tier":
        tier = b.get("tier")
        if tier not in (*voicestudio.TIERS, "auto"):
            raise AppError("Nível desconhecido.")
        cat = voicestudio.catalog()
        missing = cat["packs"].get(tier if tier != "auto" else (cat.get("resolved") or "balanced"), {}).get("missing") or []
        size = sum(m["size_gb"] or 0 for m in cat["models"] if m["repo_id"] in missing)
        if missing and b.get("confirm") is not True:
            raise AppError("Confirme o download do pacote.", f"Baixa {size:.1f} GB.")
        if missing:
            _check_disk(size)
        voicestudio.write("PUT", "/api/settings/performance-profile", {"tier": tier, "family": None})
        for repo in missing:
            voicestudio.write("POST", "/models/install", {"repo_id": repo})
        return {"ok": True, "installing": missing}
    if action in ("install", "cancel", "remove"):
        repo = voicestudio._repo(b.get("repo"))
        if action == "install":
            row = next((m for m in voicestudio.catalog()["models"] if m["repo_id"] == repo), None)
            if not row:
                raise AppError("Modelo desconhecido para o Voice Studio.")
            if b.get("confirm") is not True:
                raise AppError("Confirme o download.", f"Baixa {row['size_gb']} GB.")
            _check_disk(row["size_gb"])
            return voicestudio.write("POST", "/models/install", {"repo_id": repo})
        if action == "cancel":
            return voicestudio.write("POST", "/models/install/cancel", {"repo_id": repo})
        if b.get("confirm") is not True:
            raise AppError("Confirme a remoção.")
        return voicestudio.write("DELETE", f"/models/{repo}", timeout=120)
    if action == "engine":
        fam, eid = b.get("family"), b.get("id")
        if fam not in ("tts", "asr") or not isinstance(eid, str) or not voicestudio.ID.fullmatch(eid):
            raise AppError("Motor inválido.")
        out = voicestudio.write("POST", "/engines/select", {"family": fam, "backend_id": eid})
        voicestudio._engine["at"] = -1e9  # o motor ativo mudou: a galeria lê de novo
        return out
    if action == "engine_install":
        eid = b.get("id")
        if not isinstance(eid, str) or not voicestudio.ID.fullmatch(eid) or b.get("confirm") is not True:
            raise AppError("Confirme a instalação do motor.")
        _check_disk(3)
        return voicestudio.write("POST", f"/engines/sidecar/{eid}/install", {}, timeout=60)
    if action == "temp_clear":
        if b.get("confirm") is not True:
            raise AppError("Confirme a limpeza.")
        return voicestudio.write("POST", "/api/settings/storage/temp/clear", {}, timeout=120)
    if action == "start":  # "Ligar a voz agora" (não é ajuste: sobe o backend e carrega o modelo)
        return listen.warm("hear")
    raise AppError("Ação desconhecida.")


# --- mover a pasta dos modelos para o D: (D55) --------------------------------------------------------------------------
# A rota do Voice Studio (PUT /api/settings/storage/models-dir) só aceita uma autorização que o próprio app emite quando
# o estudante escolhe a pasta na janela dele: o Lúmen não a imita. Por isso: o Lúmen copia e confere (tamanho e hash de
# cada arquivo); o estudante escolhe a pasta nova no Voice Studio (Configurações → Armazenamento); depois que o Voice
# Studio passa a usá-la, o Lúmen oferece apagar a cópia antiga, com confirmação.

MOVE = {"phase": "idle"}


def _record_file():
    from .. import store
    return store.DATA / "voicestudio-move.json"


def _record():
    """A cópia conferida, gravada em DATA: sobrevive a reiniciar o Lúmen (só ela autoriza apagar a pasta antiga)."""
    try:
        r = json.loads(_record_file().read_text("utf-8"))
        return r if isinstance(r, dict) and r.get("phase") == "copied" else None
    except (OSError, ValueError):
        return None


def _hash(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_models(src, dst, cancel=None):
    """Copia `src` para `dst` arquivo a arquivo (o que já está igual fica) e confere cada um pelo hash."""
    src, dst = Path(src), Path(dst)
    files = [p for p in src.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files) or 1
    done = 0
    MOVE.update(phase="copying", total=total, done=0, files=len(files), src=str(src), dst=str(dst))
    for p in files:
        if cancel and cancel.is_set():
            MOVE.update(phase="idle")
            return False
        q = dst / p.relative_to(src)
        q.parent.mkdir(parents=True, exist_ok=True)
        if not (q.exists() and q.stat().st_size == p.stat().st_size and _hash(q) == _hash(p)):
            tmp = q.with_name(q.name + ".lumen-part")
            shutil.copy2(p, tmp)
            if _hash(tmp) != _hash(p):
                tmp.unlink(missing_ok=True)
                MOVE.update(phase="failed", error=f"A cópia de {p.name} não conferiu.")
                return False
            tmp.replace(q)
        done += p.stat().st_size
        MOVE.update(done=done)
    MOVE.update(phase="copied")
    _record_file().parent.mkdir(parents=True, exist_ok=True)
    _record_file().write_text(json.dumps({"phase": "copied", "src": str(src.resolve()), "dst": str(dst.resolve()),
                                          "files": len(files), "bytes": total, "at": db.now()}), "utf-8")
    return True


def safe_to_delete(src, dst):
    """A pasta antiga só sai se: não é vazia nem a nova, parece um cache de modelos (models--*) e cada arquivo de modelo
    dela (os de models--*) existe na nova com o mesmo tamanho (os hashes foram conferidos na cópia). Os logs do
    downloader (`xet/logs`), que o Voice Studio grava a cada subida, não são modelo e não contam."""
    src, dst = Path(src), Path(dst)
    if not str(src).strip() or not src.is_absolute() or not src.is_dir() or src.resolve() == dst.resolve():
        return False
    if not any(p.name.startswith("models--") for p in src.iterdir()):
        return False
    for p in src.rglob("*"):
        if p.is_file() and p.relative_to(src).parts[0].startswith("models--"):
            q = dst / p.relative_to(src)
            if not q.is_file() or q.stat().st_size != p.stat().st_size:
                return False
    return True


def _move(h):
    if h.command == "GET":
        return _move_state()
    b = _body(h)
    action = b.get("action")
    st = _move_state()
    if action == "copy":
        if b.get("confirm") is not True:
            raise AppError("Confirme a cópia.")
        if not st.get("running"):
            raise AppError("Ligue a voz primeiro: o Lúmen pergunta ao Voice Studio onde estão os modelos.")
        if MOVE.get("phase") == "copying":
            raise AppError("A cópia já está em andamento.")
        if st.get("jobs"):
            raise AppError("Espere os downloads do Voice Studio terminarem.")
        src = Path(st["source"])
        if not src.is_dir():
            raise AppError("A pasta dos modelos não foi encontrada.")
        if (voicestudio.disk_free_gb(MOVE_TO.anchor) or 0) - st["size_gb"] < 10:
            raise AppError("O D: ficaria com menos de 10 GB livres.")

        def run():
            try:
                copy_models(src, MOVE_TO)
            except OSError as e:
                MOVE.update(phase="failed", error=str(e)[:200])
        threading.Thread(target=run, daemon=True, name="Lumen VS move").start()
        return _move_state()
    if action == "open_app":
        voicestudio.open_app()
        return {"ok": True}
    if action == "delete_old":
        if b.get("confirm") is not True:
            raise AppError("Confirme antes de apagar.")
        if not st.get("using_new"):
            raise AppError("O Voice Studio ainda não usa a pasta nova.", "Escolha a pasta nova no Voice Studio e reinicie o app.")
        rec = _record()  # só uma cópia conferida e gravada autoriza apagar
        if not rec or not safe_to_delete(rec["src"], rec["dst"]):
            raise AppError("Não há uma cópia conferida da pasta antiga.", "Nada foi apagado. Copie de novo antes de apagar.")
        shutil.rmtree(rec["src"])
        _record_file().unlink(missing_ok=True)
        MOVE.update(phase="done")
        return _move_state()
    raise AppError("Ação desconhecida.")


def _move_state():
    rec = _record()
    out = {**MOVE, "to": str(MOVE_TO), "free_d_gb": voicestudio.disk_free_gb(MOVE_TO.anchor),
           "old": rec["src"] if rec and Path(rec["src"]).is_dir() else None}
    if rec and MOVE.get("phase") == "idle":
        out["phase"] = "copied"  # a cópia conferida de antes de reiniciar o Lúmen
    if not _running():
        return {**out, "running": False}
    d = voicestudio.models_dir()
    src = d.get("effective") or ""
    out.update(running=True, source=src, configured=d.get("configured"), free_c_gb=voicestudio.disk_free_gb(src),
               using_new=bool(src) and Path(src).resolve() == MOVE_TO.resolve())
    try:
        cats = {c.get("id"): c for c in voicestudio.storage().get("categories") or []}
        out["size_gb"] = round(((cats.get("hf_cache") or {}).get("bytes") or 0) / 1e9, 1)
    except AppError:
        out["size_gb"] = 0
    out["jobs"] = [j for j in voicestudio._req("/models/install/status").get("jobs") or [] if j.get("state") == "downloading"]
    return out


# --- "Esta máquina" (D59) -----------------------------------------------------------------------------------------------

_gpu = {"at": -1e9, "value": None}


def gpu():
    """Nome, total, usada e livre (GB), pelo nvidia-smi, no máximo uma vez a cada 4 s (a tela pede a cada 5 s)."""
    if time.monotonic() - _gpu["at"] > 4:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                                 creationflags=NO_WINDOW).stdout.splitlines()[0].split(",")
            value = {"name": out[0].strip(), "total_gb": int(out[1]) / 1024, "used_gb": int(out[2]) / 1024,
                     "free_gb": int(out[3]) / 1024}
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            value = None
        _gpu.update(at=time.monotonic(), value=value)
    return _gpu["value"]


def ollama_vram_gb():
    try:
        import urllib.request
        with urllib.request.urlopen(llm.OLLAMA + "/api/ps", timeout=2) as r:
            return round(sum(m.get("size_vram") or 0 for m in json.load(r).get("models") or []) / 2**30, 2)
    except (OSError, ValueError):
        return None


def machine():
    g, ram = gpu(), listen.ram_free_gb()
    vs = None
    if _running():
        try:
            vs = round(sum(m.get("vram_mb") or 0 for m in voicestudio.loaded().get("models") or []) / 1024, 2)
        except AppError:
            vs = None
    lumen = round(sum(transcribe.VRAM_NEED_GB.get(n, 0) for n, dev in transcribe._loaded if dev == "cuda"), 2)
    disks = {d: voicestudio.disk_free_gb(d + "\\") for d in ("C:", "D:") if Path(d + "\\").exists()}
    st = voicestudio.status()
    advice = []
    if g and g["free_gb"] < 3:
        advice.append("Pouca VRAM livre: a voz vai esperar a resposta terminar e pedir ao Ollama para soltar a placa.")
    if ram and ram[0] < listen.WARM_MIN_RAM_GB:
        advice.append("Pouca RAM livre: a voz não é preparada com antecedência; a 1ª frase carrega o modelo.")
    if disks.get("C:") is not None and disks["C:"] < 15:
        advice.append("O C: está quase cheio: mova a pasta dos modelos do Voice Studio para o D:.")
    return {"gpu": g, "vram": {"ollama": ollama_vram_gb(), "voicestudio": vs, "lumen": lumen}, "ram": ram,
            "disks": disks, "backend": {"running": st["running"], "owner": st["owner"], "app_open": st["app_open"],
                                        "state": st["backend"], "model": st.get("model")},
            "last": listen.LAST, "advice": advice}


def _machine(h):
    return machine()


# --- pronúncias (D58) ---------------------------------------------------------------------------------------------------

TERM = re.compile(r"[\w][\w .+#&'-]{0,59}")


def _pron(h):
    if h.command == "GET":
        if not _running():
            return {"running": False, "entries": []}
        return {"running": True, "entries": voicestudio.pronunciations()}
    b = _body(h)
    action = b.get("action")
    if action == "add":
        term, rep = str(b.get("term") or "").strip(), str(b.get("replacement") or "").strip()[:120]
        if not TERM.fullmatch(term) or not rep:
            raise AppError("Escreva o termo e como ele deve soar.")
        lang = b.get("language") if b.get("language") in ("pt", "en", "*") else "*"
        out = voicestudio.write("POST", "/pronunciation", {"term": term, "replacement": rep, "type": "respelling",
                                                            "language": lang, "enabled": True})
        voicestudio._pron["at"] = -1e9
        return out
    if action == "delete":
        eid = b.get("id")
        if not isinstance(eid, str) or not re.fullmatch(r"[\w-]{1,40}", eid):
            raise AppError("Pronúncia inválida.")
        voicestudio._pron["at"] = -1e9
        return voicestudio.write("DELETE", f"/pronunciation/{eid}")
    if action == "test":
        text = str(b.get("text") or "").strip()[:400]
        if not text:
            raise AppError("Escreva uma frase para testar.")
        out = {"substituted": voicestudio.pronounce(text, settings.load()["voice"]["language"] or None)}
        if b.get("listen"):
            out.update(listen.test(text))
        return out
    if action == "import":
        entries = b.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > 500:
            raise AppError("Arquivo de pronúncias inválido.")
        clean = [{"term": str(e.get("term") or "")[:60], "replacement": str(e.get("replacement") or "")[:120],
                  "type": "respelling", "language": e.get("language") if e.get("language") in ("pt", "en", "*") else "*",
                  "enabled": e.get("enabled") is not False}
                 for e in entries if isinstance(e, dict) and TERM.fullmatch(str(e.get("term") or ""))]
        voicestudio._pron["at"] = -1e9
        return voicestudio.write("POST", "/pronunciation/import", {"entries": clean, "replace": False})
    if action == "export":
        return voicestudio._req("/pronunciation/export")
    if action == "suggest":
        return {"suggestions": suggest()}
    raise AppError("Ação desconhecida.")


ACRONYM = re.compile(r"\b[A-Z]{2,5}\b")
FOREIGN = re.compile(r"\b[A-Za-z]*(?:[kwy]|th|sh|ee|oo|ck|ght|ph)[A-Za-z]*\b")
STOP = {"PDF", "OK", "TV", "EUA", "USA", "ONG", "CEP", "CPF", "RG", "SP", "RJ", "MG"}
LETTERS = {"A": "á", "B": "bê", "C": "cê", "D": "dê", "E": "é", "F": "éfe", "G": "gê", "H": "agá", "I": "i", "J": "jota",
           "K": "cá", "L": "éle", "M": "ême", "N": "ene", "O": "ó", "P": "pê", "Q": "quê", "R": "érre", "S": "ésse",
           "T": "tê", "U": "u", "V": "vê", "W": "dáblio", "X": "xis", "Y": "ípsilon", "Z": "zê"}
SUGGEST = """Você ajuda uma voz sintética em português do Brasil a pronunciar termos de cursos (marketing, Premiere,
persuasão, negócios, inglês). Para cada termo da lista, diga se um leitor em português o pronunciaria errado. Se sim,
escreva a grafia em português que soa como a pronúncia correta (ex.: "keyframe" → "quíframe", "Premiere" → "Premiér",
"CTA" → "cê tê á", "ROI" → "érre ó i"). Termos que o leitor já diz bem ficam de fora. Responda só no JSON pedido."""


def candidates(limit=60):
    """Termos em inglês e siglas mais frequentes no índice do Lúmen (as notas do estudante), sem os que já têm pronúncia."""
    from collections import Counter
    have = set()
    try:
        have = {str(e.get("term") or "").lower() for e in voicestudio.pronunciations()}
    except AppError:
        pass
    count = Counter()
    for (text,) in db.connect().execute("SELECT text FROM chunks ORDER BY id DESC LIMIT 20000"):
        for m in ACRONYM.findall(text):
            if m not in STOP:
                count[m] += 1
        for m in FOREIGN.findall(text):
            if len(m) >= 3:
                count[m] += 1
    return [t for t, n in count.most_common(limit * 3) if n >= 3 and t.lower() not in have][:limit]


def suggest():
    """Sugestões para o estudante aceitar uma por uma: a IA local propõe a grafia falada; sem IA, só as siglas, letra
    por letra."""
    terms = candidates()
    if not terms:
        return []
    from . import providers
    chain, _ = providers.chain(None)  # só a IA local: as notas não saem do PC por isto
    if chain:
        schema = {"type": "object", "properties": {"items": {"type": "array", "maxItems": 20, "items": {
            "type": "object", "properties": {"term": {"type": "string", "enum": terms}, "spoken": {"type": "string"}},
            "required": ["term", "spoken"]}}}, "required": ["items"]}
        try:
            data = chain[0].json(SUGGEST, "Termos:\n" + "\n".join(terms), schema, lambda: None, max_tokens=1200)
            seen, out = set(), []
            for it in data.get("items") or []:
                t, sp = str(it.get("term") or ""), str(it.get("spoken") or "").strip()[:120]
                if t in terms and sp and sp.lower() != t.lower() and t not in seen:
                    seen.add(t)
                    out.append({"term": t, "replacement": sp})
            return out[:20]
        except AppError:
            pass
    return [{"term": t, "replacement": " ".join(LETTERS[c] for c in t)} for t in terms if ACRONYM.fullmatch(t)][:20]


# --- vozes por descrição (D58) ------------------------------------------------------------------------------------------

def _design(h):
    b = _body(h)
    action, text = b.get("action"), str(b.get("text") or "").strip()[:400]
    if action == "describe":
        if not text:
            raise AppError("Descreva a voz (ex.: cliente cético, homem, 40 anos).")
        return voicestudio.describe(text)
    if action == "preview":
        instruct = str(b.get("instruct") or "")[:300]
        if not settings.STYLE.fullmatch(instruct):
            raise AppError("Estilo inválido.")
        s = settings.load()["voice"]
        voicestudio.BACKEND.ensure(start=s["vs_autostart"])
        line = text or "Olá! Eu sou a voz deste personagem. Vamos treinar juntos?"
        lang = b.get("language") if b.get("language") in ("pt", "en") else "pt"
        wav = voicestudio.synth(line, "default", 1.0, lang, 42, instruct, listen.STEPS["balanced"])
        import base64
        return {"audio": base64.b64encode(wav).decode()}
    if action == "create":
        if b.get("confirm") is not True:
            raise AppError("Confirme a criação da voz.")
        instruct = str(b.get("instruct") or "")[:300]
        if not settings.STYLE.fullmatch(instruct):
            raise AppError("Estilo inválido.")
        lang = b.get("language") if b.get("language") in ("pt", "en") else "pt"
        try:  # com o modelo carregado, o Voice Studio grava a amostra da voz na hora (a identidade fica estável)
            voicestudio.BACKEND.warm(start=True)
        except AppError:
            pass  # sem o modelo, ele grava a amostra na primeira prévia
        out = voicestudio.create_design_voice(b.get("name"), instruct, b.get("attrs") or {}, lang)
        return {"voice": {k: out.get(k) for k in ("id", "name", "kind", "language")}}
    raise AppError("Ação desconhecida.")


ROUTES = {
    ("GET", "/api/study/voice/models"): _models,
    ("POST", "/api/study/voice/models"): _model_action,
    ("GET", "/api/study/voice/move"): _move,
    ("POST", "/api/study/voice/move"): _move,
    ("GET", "/api/study/voice/machine"): _machine,
    ("GET", "/api/study/voice/pron"): _pron,
    ("POST", "/api/study/voice/pron"): _pron,
    ("POST", "/api/study/voice/design"): _design,
}
