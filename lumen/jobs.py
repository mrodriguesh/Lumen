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

from . import AppError, Cancelled, charts, llm, mindmap, notion, sources, store, transcribe, vision

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
    if src["kind"] == "recording":  # telas capturadas junto com o som (“Assistir a tela junto”)
        vision.adopt(Path(src["path"]).with_suffix(".screens"), work)
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
            speed = float(requested) if requested in ("1", "2", "4") else None
            estimate, unsure, auto_note, vram_warning = None, False, None, None
            name = m["name"]
            # Automático: mede a fala antes só se a velocidade mudar a transcrição. No large-v3 não muda, e a medida
            # sai da própria transcrição. Se faltar VRAM e ele for trocado por outro modelo, mede antes como os demais.
            while True:
                if speed is None and not transcribe.same_at_2x(name):
                    _set(stage="transcribe", detail="Medindo a velocidade da fala…", progress=None)
                    estimate = transcribe.speech_rate(src["path"], name, check)
                    speed, unsure, auto_note = transcribe.suggest_speed(estimate)
                name, warning = transcribe.for_speed(name, speed or 1.0)
                transcribe.make_room(name, llm.release_vram)  # antes de decidir trocar de modelo por falta de VRAM
                name, w = transcribe.fit_gpu(name)
                vram_warning = w or vram_warning
                if speed is not None or transcribe.same_at_2x(name):
                    break
            _set(stage="transcribe", detail=detail, progress=0)
            tr = transcribe.transcribe(src["path"], name, _progress("transcribe", detail), check, speed=speed or 1.0,
                                       release=llm.release_vram)
            if speed is None:
                estimate = transcribe.rate(tr["segments"])
                speed, unsure, auto_note = transcribe.suggest_speed(estimate)
            warning = " ".join(w for w in (auto_note, warning, vram_warning) if w) or None
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
    screens = _screens(src, work, cfg)
    check()
    (work / "transcript_review.json").unlink(missing_ok=True)
    engine = (f"{tr['model']} na {'GPU (CUDA, ' if tr.get('device') == 'cuda' else 'CPU ('}{tr.get('compute')})"
              if tr.get("model") else None)
    return {"review": True, "key": src["key"], "title": src["title"], "segments": tr["segments"], "engine": engine,
            "speed": tr.get("speed"), "duration": tr.get("duration"), "language": tr.get("language"),
            "can_retranscribe": bool(src.get("path")), "screens": screens}


def _screens(src, work, cfg):
    """“Assistir a tela junto”: lê as telas da gravação que ainda faltam, ou assiste o vídeo do arquivo.

    Devolve o resumo para a revisão (telas escolhidas, com id e tempo) ou None se a opção não foi usada. Se o
    modelo de visão não puder ser usado, a aula segue só com a fala e a revisão avisa."""
    folder = work / "screens"
    watched = (folder / "index.json").exists() and (folder / "complete").exists()  # gravação ou vídeo já assistido
    video = cfg["watch_screen"] and src["kind"] != "recording" and src.get("path") and Path(src["path"]).exists()
    if not (watched or video):
        return None
    _set(screen=True, stage="screen", detail="Preparando a leitura da tela…", progress=None)
    status = lambda d, p: _set(stage="screen", detail=d, progress=p)  # noqa: E731
    warning = None
    try:
        if (not watched or vision.Shots(folder).pending()) and not vision.ready(vision.MODEL):
            raise AppError(f"o modelo de visão ({vision.MODEL}) não está instalado no Ollama ou o Ollama está fechado")
        if not watched:  # começa do zero: uma extração cancelada no meio não deixa telas pela metade
            shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True)
            if not vision.extract(src["path"], vision.Shots(folder), vision.MODEL, check, status):
                shutil.rmtree(folder, ignore_errors=True)
                return {"items": [], "seen": 0, "warning": "Este arquivo não tem imagem de vídeo: só a fala foi usada."}
            (folder / "complete").touch()
        vision.analyze(vision.Shots(folder), vision.MODEL, check, status)
    except AppError as e:
        left = len(vision.Shots(folder).pending())
        warning = (f"{left} tela(s) ficaram sem leitura" if left else "A tela não foi lida") + f": {str(e).rstrip('.')}."
    shots = vision.Shots(folder)
    items = [{"id": s["id"], "t": s["t"], "titulo": s["note"]["titulo"], "tipo": s["note"]["tipo"]}
             for s in vision.select(shots.items)]
    return {"items": items, "seen": len(shots.items), "warning": warning}


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

    shots = vision.Shots(work / "screens")  # “Assistir a tela junto”: as telas que o usuário manteve na revisão
    off = {int(i) for i in spec.get("screens_off") or []}
    screens = [s for s in vision.select(shots.items) if s["id"] not in off]
    lines, chosen = vision.screen_lines(screens), {s["id"] for s in screens}
    model, lang = cfg["ollama_model"], spec.get("language") or cfg["page_language"]
    digest = hashlib.sha256(json.dumps([s["text"] for s in tr["segments"]] + [x for _, x in lines],
                                       ensure_ascii=False).encode()).hexdigest()
    redo = spec.get("mode") == "redo"  # “Refazer página”: material novo, versão anterior removida
    saved = _load(work / "lesson.json")
    if saved and not redo and saved.get("model") == model and saved.get("language") == lang and saved.get("transcript") == digest:
        lesson, found = saved["lesson"], saved.get("charts")
    else:
        _set(stage="generate", detail="Escrevendo o material de estudo…", progress=None, eta=None)
        lesson = llm.generate(tr["segments"], tr.get("duration"), model, lang, check,
                              lambda d, p: _set(stage="generate", detail=d, progress=p),
                              redo=redo, note=spec.get("redo_note") or "", screens=lines)
        saved, found = {"model": model, "language": lang, "transcript": digest, "lesson": lesson}, None
        _save(work / "lesson.json", saved)
    check()
    if found is None:
        found = _find_charts(tr, screens, lesson, model)
        if found is not None:  # falha da IA não fica guardada: “Tentar novamente” procura de novo
            _save(work / "lesson.json", {**saved, "charts": found})
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
    if found:
        from concurrent.futures import ThreadPoolExecutor
        _set(stage="publish", detail="Desenhando os gráficos da aula…", progress=None)

        def draw(i, c):  # cada gráfico num Edge próprio, desenhado e enviado ao mesmo tempo que os outros
            gif = charts.render(c)
            return {**c, "upload": _send(token, gif, f"grafico-{i}.gif", "image/gif") if gif else None}
        with ThreadPoolExecutor(3) as ex:
            meta["charts"] = list(ex.map(draw, range(1, len(found) + 1), found))
        check()
    if screens:
        step = -(-len(screens) // MAX_SCREENS)  # aula com muitas telas: no máximo 40, espalhadas pela aula
        screens = screens[::step]
        _set(stage="publish", detail=f"Enviando as {len(screens)} telas da aula ao Notion…", progress=None)
        meta["screens"], meta["vision_model"] = _upload_screens(token, shots, screens), vision.MODEL
        check()
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
        shots.prune(chosen)  # só as imagens das telas escolhidas ficam (para “Refazer página”)
    return {"url": url, "title": title, "course": course, "note": note}


MAX_SCREENS = 40


def _find_charts(tr, screens, lesson, model):
    """Gráficos com os dados da aula (charts.extract), [] se a aula não tiver dados, None se a IA falhar. Nunca
    impede a página: sem gráficos, ela sai como antes."""
    _set(stage="generate", detail="Procurando dados da aula para gráficos…", progress=None)
    try:
        return charts.extract(tr["segments"], screens, lesson, model, check,
                              lambda d: _set(stage="generate", detail=d, progress=None), tr.get("language"))
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 — opcional: qualquer falha aqui só deixa a página sem gráficos
        log.exception("gráficos: falha ao procurar dados")
        return None


def _send(token, data, name, content_type):
    """Envia um arquivo ao Notion. Uma falha (o Notion limita pedidos por segundo) tenta de novo; se insistir, None
    (a página sai sem a imagem)."""
    import time
    for attempt in range(3):
        try:
            return notion.upload_image(token, data, name, content_type)
        except AppError:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return None


def _upload_screens(token, shots, screens):
    """Envia as telas, 3 por vez; a que não subir entra só com o texto."""
    from concurrent.futures import ThreadPoolExecutor

    def up(s):
        try:
            return _send(token, shots.image(s["id"]), f"tela-{s['id'] + 1}.jpg", "image/jpeg")
        except OSError:
            return None
    with ThreadPoolExecutor(3) as ex:
        ups = list(ex.map(up, screens))
    return [{**s["note"], "t": s["t"], "upload": u} for s, u in zip(screens, ups)]


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
