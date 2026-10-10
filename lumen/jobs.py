"""Uma tarefa por vez: preparar → transcrever → gerar → publicar. Guarda etapas concluídas para retomar."""
import errno
import hashlib
import json
import logging
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from . import AppError, Cancelled, llm, mindmap, notion, sources, store, transcribe

log = logging.getLogger("lumen")
_lock = threading.Lock()
_job = {"status": "idle"}
_cancel = threading.Event()


def snapshot():
    with _lock:
        return json.loads(json.dumps(_job))


def _set(**kw):
    with _lock:
        _job.update(kw)


def busy():
    return _job.get("status") == "running"


def check():
    if _cancel.is_set():
        raise Cancelled


def cancel():
    _cancel.set()


def start(kind, fn, *args, spec=None):
    with _lock:
        if _job.get("status") == "running":
            raise AppError("Já existe uma tarefa em andamento.", "Aguarde ou cancele a tarefa atual.")
        _cancel.clear()
        _job.clear()
        _job.update(status="running", kind=kind, stage="prepare", detail="Preparando…", progress=None, eta=None, spec=spec)

    def run():
        try:
            _set(status="done", result=fn(*args), progress=1, eta=None)
            log.info("%s concluído", kind)
        except Cancelled:
            log.info("%s cancelado", kind)
            _set(status="cancelled", eta=None)
        except AppError as e:
            log.warning("%s falhou: %s", kind, type(e).__name__)
            _set(status="error", error={"message": str(e), "action": e.action}, eta=None)
        except MemoryError:
            _set(status="error", eta=None, error={"message": "Memória insuficiente.",
                                                  "action": "Feche outros programas e tente de novo."})
        except OSError as e:
            log.warning("%s falhou: OSError errno=%s", kind, e.errno)
            full = e.errno == errno.ENOSPC
            _set(status="error", eta=None, error={
                "message": "Sem espaço em disco." if full else "Erro ao ler ou gravar um arquivo.",
                "action": "Libere espaço e tente de novo." if full else "Confira o arquivo e tente de novo."})
        except Exception as e:  # não registra mensagem: pode conter conteúdo da aula
            log.error("%s erro inesperado: %s", kind, type(e).__name__)
            _set(status="error", eta=None, error={"message": f"Erro inesperado ({type(e).__name__}).",
                                                  "action": "Tente de novo. O progresso já feito foi guardado."})

    threading.Thread(target=run, daemon=True).start()


def _progress(stage, detail):
    def cb(p, eta=None):
        _set(stage=stage, detail=detail, progress=p, eta=eta)
    return cb


def _load(path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def _drop_upload(src):
    """Apaga gravações e cópias de arquivos arrastados (só dentro de work/uploads; nunca arquivos do usuário)."""
    up = Path(src.get("path") or "").resolve()
    if src.get("path") and up.parent == (store.WORK / "uploads").resolve():
        try:
            up.unlink(missing_ok=True)
        except OSError:
            pass


def _cached_source(spec):
    """Retomada: a gravação pode já ter sido apagada após a transcrição; usa a fonte guardada com ela."""
    p = spec.get("path")
    if not p or Path(p).exists():
        return None
    for f in store.WORK.glob("*/source.json"):
        s = _load(f)
        if s and s.get("path") == p and (f.parent / "transcript.json").exists():
            if s["kind"] in sources.LABELS and "link" in spec:
                s["link"] = sources.lesson_link(spec["link"])
            return s
    return None


def work_dir(key):
    return store.WORK / hashlib.sha256(key.encode()).hexdigest()[:16]


def _need_notion():
    cfg, token = store.load_config(), store.get_token()
    if not token:
        raise AppError("O Notion ainda não foi conectado.", "Abra Configurações e conecte o Notion.")
    return cfg, token


_NAME = re.compile(r"(?<=[a-záéíóúâêôãõç,;:]\s)[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{2,}")


def _flags(seg):
    """Motivos honestos para revisar um trecho (sinais, não probabilidades)."""
    f = []
    if seg.get("uncertain"):
        f.append("trecho incerto")
    if seg.get("diverges"):
        f.append("modelos discordam")
    if re.search(r"\d", seg["text"]):
        f.append("número")
    if _NAME.search(seg["text"]):
        f.append("nome próprio")
    return f


def process(spec):
    """Fase 1: fonte → transcrição. Termina em “revisão”; nada vai para o Notion ainda."""
    cfg, _ = _need_notion()
    _set(stage="prepare", detail="Verificando a fonte…")
    src = _cached_source(spec) or sources.resolve(spec)
    work = work_dir(src["key"])
    work.mkdir(parents=True, exist_ok=True)
    _save(work / "source.json", src)
    if spec.get("retranscribe"):
        for f in ("transcript.json", "transcript_original.json", "lesson.json"):
            (work / f).unlink(missing_ok=True)

    tr = _load(work / "transcript.json")
    if src.get("captions"):
        cap = hashlib.sha256(json.dumps(src["captions"], ensure_ascii=False).encode()).hexdigest()
        if tr and tr.get("captions_hash") != cap:  # legenda nova colada/importada: começa do zero
            for f in ("transcript.json", "transcript_original.json", "lesson.json"):
                (work / f).unlink(missing_ok=True)
            tr = None
    if tr or src.get("captions"):
        _set(skipped=["transcribe"])
    if not tr:
        if src.get("captions"):
            tr = {"segments": src["captions"], "language": None, "duration": src["duration"], "speed": None,
                  "origin": "Transcrição importada pelo usuário (legenda ou texto do YouTube).", "captions_hash": cap}
        elif src.get("path"):
            if not Path(src["path"]).exists():
                raise AppError("A gravação ou o arquivo não está mais disponível.", "Escolha o arquivo ou grave de novo.")
            quality, m = transcribe.pick(cfg["quality"])
            transcribe.make_room(m["name"], llm.release_vram)
            detail = f"Transcrevendo no seu PC (modelo {m['label']})…"
            requested = str(spec.get("speed") or "auto")
            speed, estimate = (float(requested), None) if requested in ("1", "2", "4") else (None, None)
            if speed is None:
                _set(stage="transcribe", detail="Medindo a velocidade da fala…", progress=None)
                estimate = transcribe.speech_rate(src["path"], m["name"], check)
            speed, unsure, auto_note = (transcribe.suggest_speed(estimate) if speed is None
                                        else (speed, False, None))
            name, warning = transcribe.for_speed(m["name"], speed)
            name, vram_warning = transcribe.fit_gpu(name)
            warning = " ".join(w for w in (auto_note, warning, vram_warning) if w) or None
            _set(stage="transcribe", detail=detail, progress=0)
            tr = transcribe.transcribe(src["path"], name, _progress("transcribe", detail), check, speed=speed)
            if not tr["segments"]:
                raise AppError("Não foi detectada fala neste arquivo.", "Confira se o vídeo tem narração audível.")
            tr["model"] = name
            tr["speed"] = {"requested": requested, "used": speed, "words_per_s": estimate, "warning": warning,
                           "unsure": unsure}
            tr["origin"] = ("Áudio gravado do PC enquanto a aula tocava. " if src["kind"] == "recording" else "") + (
                f"Transcrição local ({name}, {'GPU' if tr['device'] == 'cuda' else 'CPU'} {tr.get('compute')}"
                + (f", fala acelerada {int(speed)}× tratada" if speed > 1 else "")
                + (", conferida por um segundo modelo" if tr.get("second_opinion") else "")
                + "); pode conter erros de reconhecimento.")
        else:
            raise AppError("Falta a transcrição deste vídeo.",
                           "Cole a transcrição do YouTube, importe um .srt/.vtt ou escolha uma cópia local autorizada.")
        for seg in tr["segments"]:
            seg["flags"] = _flags(seg)
        _save(work / "transcript.json", tr)
        _save(work / "transcript_original.json", tr)
    check()
    (work / "transcript_review.json").unlink(missing_ok=True)
    engine = (f"{tr['model']} na {'GPU (CUDA, ' if tr.get('device') == 'cuda' else 'CPU ('}{tr.get('compute')})"
              if tr.get("model") else None)
    return {"review": True, "key": src["key"], "title": src["title"], "segments": tr["segments"], "engine": engine,
            "speed": tr.get("speed"), "duration": tr.get("duration"), "language": tr.get("language"),
            "can_retranscribe": bool(src.get("path"))}


def finish(spec):
    """Fase 2: usa exatamente a transcrição revisada → material de estudo → página no Notion."""
    cfg, token = _need_notion()
    src = _cached_source(spec) or sources.resolve(spec)
    work = work_dir(src["key"])
    tr = _load(work / "transcript.json")
    if not tr:
        raise AppError("A transcrição desta aula não foi encontrada.", "Gere a transcrição de novo.")
    edits = {int(k): str(v).strip() for k, v in (spec.get("edits") or {}).items()}
    # Os índices das edições se referem à transcrição exibida na revisão. Ela fica guardada para que
    # “Tentar novamente” reaplique as mesmas edições sobre a mesma base (apagar trechos muda os índices).
    base = _load(work / "transcript_review.json")
    if base is None:
        base = tr
        _save(work / "transcript_review.json", base)
    if edits:
        tr = json.loads(json.dumps(base))
        for i, text in edits.items():
            if 0 <= i < len(tr["segments"]):
                tr["segments"][i]["text"] = text[:5000]
                tr["segments"][i]["edited"] = True
        tr["segments"] = [s for s in tr["segments"] if s["text"]]
        tr["reviewed"] = True
        _save(work / "transcript.json", tr)
    if not cfg["keep_temp"]:
        _drop_upload(src)  # revisão confirmada: a gravação/cópia não é mais necessária
    check()

    model, lang = cfg["ollama_model"], spec.get("language") or cfg["page_language"]
    digest = hashlib.sha256(json.dumps([s["text"] for s in tr["segments"]], ensure_ascii=False).encode()).hexdigest()
    redo = spec.get("mode") == "redo"  # “Refazer página”: material novo, versão anterior removida
    saved = _load(work / "lesson.json")
    if saved and not redo and saved.get("model") == model and saved.get("language") == lang and saved.get("transcript") == digest:
        lesson = saved["lesson"]
    else:
        _set(stage="generate", detail="Escrevendo o material de estudo…", progress=None, eta=None)
        lesson = llm.generate(tr["segments"], tr.get("duration"), model, lang, check,
                              lambda d, p: _set(stage="generate", detail=d, progress=p),
                              redo=redo, note=spec.get("redo_note") or "")
        _save(work / "lesson.json", {"model": model, "language": lang, "transcript": digest, "lesson": lesson})
    check()

    _set(stage="publish", detail="Desenhando o mapa mental…", progress=None)
    mind_png = mindmap.render(mindmap.data(lesson))
    check()
    _set(stage="publish", detail="Salvando na página escolhida do Notion…", progress=None)
    course_id = notion.course_for(token, cfg["root_page_id"], spec.get("course_id") or "__none__")
    course = spec.get("course_title") or notion.NO_COURSE
    edited = sum(1 for s in tr["segments"] if s.get("edited"))
    meta = {"course": course, "yt_id": src.get("yt_id"), "link": src.get("link"),
            "source": f"{src['label']} — {src['title']}", "duration": tr.get("duration"),
            "language": tr.get("language"), "model": model,
            "transcript_origin": tr["origin"] + (f" {edited} trecho(s) corrigido(s) pelo usuário." if edited else ""),
            "uncertain": sum(1 for s in tr["segments"] if s.get("uncertain") and not s.get("edited"))}
    if mind_png:
        try:
            meta["mind_map_upload"] = notion.upload_image(token, mind_png, "mapa-mental.png")
        except AppError:
            pass  # o mapa vai em tópicos (notion._mind_map)
    title, blocks = notion.build_page(lesson, meta)
    transcript = llm.transcript_text(tr["segments"]).split("\n") if spec.get("include_transcript") else None
    check()
    pid, url, block_ids = notion.publish(token, course_id, title, blocks, check, transcript=transcript)

    old = store.history().get(src["key"]) or {}
    note = None
    if spec.get("mode") in ("replace", "redo") and old:
        if old.get("block_ids") and (old.get("page_id") == pid or redo):  # refazer em outra página = mover
            if redo:
                note = ("Página refeita; a versão anterior foi removida." if old.get("page_id") == pid
                        else f"Aula movida para {course}; a versão anterior foi removida.")
            for bid in old["block_ids"]:
                try:
                    notion.request("DELETE", f"/blocks/{bid}", token)
                except AppError:
                    block_ids.append(bid)
                    note = "O material novo foi salvo, mas parte da versão anterior não pôde ser removida."
        else:
            note = "O material foi salvo no destino escolhido. A versão anterior foi preservada."
    store.remember(src["key"], {"page_id": pid, "block_ids": block_ids, "url": url, "title": title, "course": course,
                                "created": datetime.now().isoformat(timespec="minutes")})
    if not cfg["keep_temp"]:
        # Guarda só a transcrição da última aula publicada (para “Refazer página”); a anterior é apagada.
        for mark in store.WORK.glob("*/published"):
            if mark.parent != work:
                shutil.rmtree(mark.parent, ignore_errors=True)
        (work / "published").touch()
    return {"url": url, "title": title, "course": course, "note": note}


def download_whisper(name):
    _set(stage="download", detail="Baixando o modelo de transcrição…")
    transcribe.download(name)
    return {"downloaded": name}


def download_covers():
    from . import imagegen
    detail = f"Baixando o gerador de capas ({imagegen.ENGINES[imagegen.DEFAULT_ENGINE]['size']})…"
    _set(stage="download", detail=detail, progress=0)
    imagegen.download(imagegen.DEFAULT_ENGINE, _progress("download", detail), check)
    return {"downloaded": "covers"}


def download_ollama(model):
    _set(stage="download", detail=f"Baixando {model} pelo Ollama…", progress=0)
    llm.pull(model, _progress("download", f"Baixando {model} pelo Ollama…"), check)
    return {"downloaded": model}
