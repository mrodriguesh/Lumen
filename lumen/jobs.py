"""Uma tarefa por vez: preparar → transcrever → (o estudante escreve a compreensão) → analisar → gerar → publicar.
Guarda etapas concluídas para retomar. Nada de IA sobre o conteúdo antes da nota (lumen/understanding.py)."""
import errno
import hashlib
import json
import logging
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from . import (AppError, Cancelled, charts, eta, llm, mindmap, notion, obsidian, package, sources, store, transcribe,
               understanding, vault, vision)
from . import music as _music  # só rótulos e regras; nenhum modelo é carregado sem o filtro ligado

log = logging.getLogger("lumen")
_lock = threading.Lock()
_job = {"status": "idle"}
_cancel = threading.Event()


def snapshot():
    with _lock:
        out = json.loads(json.dumps(_job))
    plan = eta.current
    if plan and out.get("status") == "running":
        out["eta_total"] = round(plan.left())  # até a revisão (transcrição) ou até a página pronta
    return out


def _set(**kw):
    with _lock:
        _job.update(kw)


def busy():
    return _job.get("status") == "running"


def running_info():
    """O que a tarefa atual diz sobre si, sem o resultado (que pode trazer a transcrição inteira): para o status."""
    with _lock:
        key = _job.get("key") or (_job.get("spec") or {}).get("key")
        return {"running": _job.get("status") == "running", "kind": _job.get("kind"), "key": key,
                "detail": _job.get("detail"), "progress": _job.get("progress")}


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
        eta.current = None

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
            name = f" ({Path(e.filename).name})" if e.filename else ""
            _set(status="error", eta=None, error={
                "message": "Sem espaço em disco." if full else f"Erro ao ler ou gravar um arquivo{name}.",
                "action": "Libere espaço e tente de novo." if full else "Confira o arquivo e tente de novo."})
        except Exception as e:  # não registra mensagem: pode conter conteúdo da aula
            log.error("%s erro inesperado: %s", kind, type(e).__name__)
            _set(status="error", eta=None, error={"message": f"Erro inesperado ({type(e).__name__}).",
                                                  "action": "Tente de novo. O progresso já feito foi guardado."})
        finally:
            eta.current = None

    threading.Thread(target=run, daemon=True).start()


def _progress(stage, detail):
    def cb(p, left=None):
        _set(stage=stage, detail=detail, progress=p, eta=left)
        if eta.current and left is not None:
            eta.current.update(left)
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
    for raw in [src.get("path"), *(src.get("paths") or [])]:
        up = Path(raw or "").resolve()
        if raw and up.parent == (store.WORK / "uploads").resolve():
            try:
                up.unlink(missing_ok=True)
            except OSError:
                pass


def _cached_source(spec):
    """Retomada: a gravação pode já ter sido apagada após a transcrição; usa a fonte guardada com ela."""
    p = spec.get("path") or (spec.get("paths") or [None])[0]
    if not p or Path(p).exists():
        return None
    for f in store.WORK.glob("*/source.json"):
        s = _load(f)
        if s and p in (s.get("path"), (s.get("paths") or [None])[0]) and (f.parent / "transcript.json").exists():
            if s["kind"] in sources.LABELS and "link" in spec:
                s["link"] = sources.lesson_link(spec["link"])
            return s
    return None


def work_dir(key):
    return store.WORK / hashlib.sha256(key.encode()).hexdigest()[:16]


_NAME = re.compile(r"(?<=[a-záéíóúâêôãõç,;:]\s)[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{2,}")


def _flags(seg):
    """Motivos honestos para revisar um trecho (sinais, não probabilidades)."""
    f = []
    if seg.get("uncertain"):
        f.append("trecho incerto")
    if seg.get("diverges"):
        f.append("modelos discordam")
    if seg.get("music"):
        f.append("música ao fundo")
    if re.search(r"\d", seg["text"]):
        f.append("número")
    if _NAME.search(seg["text"]):
        f.append("nome próprio")
    return f


def process(spec):
    """Fase 1: fonte → transcrição (preparação técnica, sem IA de texto). Termina esperando a compreensão do
    estudante; nada vai para o Notion e nenhum material é escrito ainda."""
    cfg = store.load_config()
    _destinations(cfg)  # sem destino pronto, nem começa (a mensagem diz o que falta)
    _set(stage="prepare", detail="Verificando a fonte…")
    src = _cached_source(spec) or sources.resolve(spec)
    understanding.start(src["key"], src["title"], src["label"], spec)
    _set(key=src["key"], title=src["title"])  # a interface já abre “Minha compreensão” enquanto isto continua
    work = work_dir(src["key"])
    work.mkdir(parents=True, exist_ok=True)
    _save(work / "source.json", src)
    if src["kind"] == "recording":  # telas capturadas junto com o som (“Assistir a tela junto”)
        vision.adopt(Path(src["path"]).with_suffix(".screens"), work)
    if src["kind"] == "captures":  # imagens enviadas pelo estudante: viram as “telas” da aula, lidas logo abaixo
        if not vision.ready(vision.MODEL):
            raise AppError(f"O modelo de visão ({vision.MODEL}) não está instalado ou o Ollama está fechado.",
                           "Abra o Ollama e baixe o modelo de visão em Ajustes → Captura.")
        _make_shots(src, work)
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
    if tr or src.get("captions") or src["kind"] == "captures":
        _set(skipped=["transcribe"])
    dur = src.get("duration") or 0
    steps = []
    if not tr and not src.get("captions") and src.get("path"):
        if cfg["music_filter"]:
            steps.append(("music", dur * eta.value("music_rtf")))
        steps.append(("transcribe", eta.transcribe_seconds(dur, transcribe.pick(cfg["quality"])[1]["name"])))
    screen_s = _screens_estimate(src, work, cfg)
    if screen_s is not None:
        steps.append(("screens", screen_s))
    eta.current = eta.Plan(steps) if steps else None
    if not tr:
        if src.get("captions"):
            tr = {"segments": src["captions"], "language": None, "duration": src["duration"], "speed": None,
                  "origin": "Transcrição importada pelo usuário (legenda ou texto do YouTube).", "captions_hash": cap}
        elif src["kind"] == "captures":  # sem fala: os trechos são preenchidos com as capturas lidas (abaixo)
            tr = {"segments": [], "language": None, "duration": None, "speed": None,
                  "origin": "Capturas de tela enviadas pelo usuário; o texto foi lido por IA de visão local e pode "
                            "conter erros de leitura."}
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
            # Filtro de música (opcional): o ASR recebe um áudio derivado; o arquivo da aula não é tocado
            asr_path, music = _filter_music(src["path"], work, dur, cfg["music_mode"]) if cfg["music_filter"] else (src["path"], None)
            if eta.current:
                eta.current.at("transcribe")
            # Automático: mede a fala antes só se a velocidade mudar a transcrição. No large-v3 não muda, e a medida
            # sai da própria transcrição. Se faltar VRAM e ele for trocado por outro modelo, mede antes como os demais.
            while True:
                if speed is None and not transcribe.same_at_2x(name):
                    _set(stage="transcribe", detail="Medindo a velocidade da fala…", progress=None)
                    estimate = transcribe.speech_rate(asr_path, name, check)
                    speed, unsure, auto_note = transcribe.suggest_speed(estimate)
                name, warning = transcribe.for_speed(name, speed or 1.0)
                transcribe.make_room(name, llm.release_vram)  # antes de decidir trocar de modelo por falta de VRAM
                name, w = transcribe.fit_gpu(name)
                vram_warning = w or vram_warning
                if speed is not None or transcribe.same_at_2x(name):
                    break
            _set(stage="transcribe", detail=detail, progress=0)
            tr = transcribe.transcribe(asr_path, name, _progress("transcribe", detail), check, speed=speed or 1.0,
                                       release=llm.release_vram)
            if music is not None:
                n = len(tr["segments"])
                tr["segments"] = _music.mark(tr["segments"], music)
                log.info("filtro de música: %d trechos do ASR, %d de letra descartados, %d com música ao fundo, "
                         "%d incertos (asrConfidence baixa)", n, n - len(tr["segments"]),
                         sum(1 for s in tr["segments"] if s.get("music")),
                         sum(1 for s in tr["segments"] if s.get("uncertain")))
                tr["music"] = {k: music.get(k) for k in ("filtered", "music_detected", "removed_s", "separated_s",
                                                         "doubt_s", "error")}
            if eta.current and dur > 20:
                eta.learn("transcribe_rtf", eta.current.elapsed() / dur, m["name"])
            if speed is None:
                estimate = transcribe.rate(tr["segments"])
                speed, unsure, auto_note = transcribe.suggest_speed(estimate)
            warning = " ".join(w for w in (auto_note, warning, vram_warning) if w) or None
            if not tr["segments"] and music and music.get("removed_s"):
                raise AppError("Só foi encontrada música neste arquivo: o filtro de música não achou fala da aula.",
                               "Se havia fala, desligue “Filtrar música externa” em Ajustes → Captura e transcreva de novo.")
            if not tr["segments"]:
                raise AppError("Não foi detectada fala neste arquivo.", "Confira se o vídeo tem narração audível.")
            tr["model"] = name
            tr["speed"] = {"requested": requested, "used": speed, "words_per_s": estimate, "warning": warning,
                           "unsure": unsure}
            tr["origin"] = ("Áudio gravado do PC enquanto a aula tocava. " if src["kind"] == "recording" else "") + (
                f"Transcrição local ({name}, {'GPU' if tr['device'] == 'cuda' else 'CPU'} {tr.get('compute')}"
                + (f", fala acelerada {int(speed)}× tratada" if speed > 1 else "")
                + (", conferida por um segundo modelo" if tr.get("second_opinion") else "")
                + "); pode conter erros de reconhecimento."
                + (" Música externa filtrada antes da transcrição." if music and music.get("filtered") else ""))
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
    if src["kind"] == "captures":  # um trecho por captura lida: é o que a revisão mostra e a IA de texto recebe
        tr["segments"] = [{"start": None, "end": None, "text": f"Captura {n}: {s['titulo'] or 'sem título'}", "flags": []}
                          for n, s in enumerate(screens["items"], 1)]
        if not tr["segments"]:
            raise AppError("Não consegui ler nada nestas capturas.",
                           "Confira se as imagens mostram texto ou figuras legíveis e tente de novo.")
        _save(work / "transcript.json", tr)
        _save(work / "transcript_original.json", tr)
    (work / "transcript_review.json").unlink(missing_ok=True)
    understanding.prepared(src["key"])
    return _review(src, tr, screens)


def _review(src, tr, screens):
    """O que a revisão mostra. A interface só recebe transcrição e telas depois da nota (understanding.guard)."""
    engine = (f"{tr['model']} na {'GPU (CUDA, ' if tr.get('device') == 'cuda' else 'CPU ('}{tr.get('compute')})"
              if tr.get("model") else None)
    return {"review": True, "key": src["key"], "title": src["title"], "segments": tr["segments"], "engine": engine,
            "speed": tr.get("speed"), "duration": tr.get("duration"), "language": tr.get("language"),
            "can_retranscribe": bool(src.get("path")), "screens": screens, "music": tr.get("music")}


def review(key):
    """A revisão (transcrição e telas) de uma aula já preparada, lida do disco; só depois da compreensão enviada."""
    understanding.reveal(key)
    work = work_dir(key)
    src, tr = _load(work / "source.json"), _load(work / "transcript.json")
    if not (src and tr):
        raise AppError("A transcrição desta aula não foi encontrada.", "Escolha a aula de novo para prepará-la.")
    folder = work / "screens"
    (work / "transcript_review.json").unlink(missing_ok=True)  # como em process: as edições valem sobre esta versão
    return _review(src, tr, _summary(folder) if (folder / "index.json").exists() else None)


def analyze(key):
    """“Processar minha compreensão”: a IA compara a nota do estudante com a aula (o conteúdo original + a nota;
    a nota tem prioridade). A nota não é tocada: a análise é guardada à parte."""
    understanding.begin_analysis(key)  # já marcada pelo servidor ao receber o pedido; aqui vale para quem chama direto
    try:
        rec = understanding.require(key)
        work = work_dir(key)
        tr = _load(work / "transcript.json")
        if not tr:
            raise AppError("A transcrição desta aula não foi encontrada.", "Escolha a aula de novo para prepará-la.")
        cfg = store.load_config()
        model, lang = cfg["ollama_model"], (rec.get("spec") or {}).get("language") or cfg["page_language"]
        note = rec["current_understanding"]  # a versão enviada: edições posteriores ficam para outra análise
        lines = vision.screen_lines(vision.select(vision.Shots(work / "screens").items))
        eta.current = eta.Plan([(k, eta.llm_seconds(model, n, k))
                                for k, n in llm.calls(tr["segments"], model, lines, "analysis", len(note))])
        _set(stage="analyze", detail="Lendo sua compreensão…", progress=None)
        result = llm.analyze(tr["segments"], model, lang, note, check,
                             lambda d, p: _set(stage="analyze", detail=d, progress=p), screens=lines)
    finally:
        understanding.end_analysis()  # qualquer saída (erro, cancelamento) solta a nota; nunca fica travada
    understanding.save_analysis(key, result, note, model)
    log.info("compreensão analisada")
    return {"analysis": True, "key": key}


def _filter_music(path, work, dur, mode):
    """“Filtrar música externa”: (áudio para o ASR, relatório). Qualquer falha cai no áudio original (music.prepare)."""
    detail = "Filtrando música externa…"
    _set(stage="transcribe", detail=detail, progress=None)
    plan = eta.current
    if plan:
        plan.at("music")

    def status(p):
        _set(stage="transcribe", detail=detail, progress=p)
        if plan:
            plan.progress(p)
    asr_path, rep = _music.prepare(path, work, check, status, mode)
    if plan and dur > 20 and not rep.get("error") and not rep.get("cached"):
        eta.learn("music_rtf", plan.elapsed() / dur)
    return asr_path, rep


def _make_shots(src, work):
    """Capturas enviadas → pasta de telas da aula (a mesma das telas capturadas na gravação), prontas para leitura."""
    folder = work / "screens"
    if (folder / "index.json").exists() and (folder / "complete").exists():
        return
    shutil.rmtree(folder, ignore_errors=True)
    shots = vision.Shots(folder)
    vision.add_captures(shots, src["paths"])
    shots.close()


MAX_ADD = 12                  # capturas por vez na revisão (a leitura acontece enquanto o usuário espera)
_adding = threading.Lock()


def add_captures(key, paths):
    """Revisão: junta capturas de tela escolhidas pelo usuário à aula (gravação, YouTube, arquivo ou outras capturas),
    lê com a IA de visão e devolve as telas da aula, no mesmo formato da revisão. Entram no fim, sem tempo."""
    if len(paths or []) > MAX_ADD:
        raise AppError(f"Adicione até {MAX_ADD} capturas por vez.", "Envie o resto em seguida.")
    files = sources.captures({"paths": paths})["paths"]
    work = work_dir(str(key))
    if not (work / "transcript.json").exists():
        raise AppError("Esta aula não está mais na revisão.", "Gere a transcrição de novo.")
    understanding.reveal(str(key))  # devolve o que as telas mostram: só depois da compreensão
    if busy() or not _adding.acquire(blocking=False):
        raise AppError("Já existe uma tarefa em andamento.", "Aguarde terminar para adicionar capturas.")
    try:
        if not vision.ready(vision.MODEL):
            raise AppError(f"O modelo de visão ({vision.MODEL}) não está instalado ou o Ollama está fechado.",
                           "Abra o Ollama e baixe o modelo de visão em Ajustes → Captura.")
        folder = work / "screens"
        shots = vision.Shots(folder)
        tr = _load(work / "transcript.json") or {}
        last = max([s["t"] for s in shots.items] + [tr.get("duration") or 0])
        vision.add_captures(shots, files, last + 1)
        (folder / "complete").touch()
        warning = None
        try:
            vision.analyze(vision.Shots(folder), vision.MODEL, lambda: None, lambda d, p: None)
        except AppError as e:
            left = len(vision.Shots(folder).pending())
            warning = f"{left} captura(s) ficaram sem leitura: {str(e).rstrip('.')}."
        _drop_upload({"paths": files})  # as imagens já estão (em JPEG) na pasta das telas da aula
        logging.getLogger("lumen").info("capturas adicionadas à aula: %d", len(files))
        return _summary(folder, warning)
    finally:
        _adding.release()


def _screens_estimate(src, work, cfg):
    """Segundos para ler as telas (as mesmas condições de _screens), ou None se a opção não for usada."""
    folder = work / "screens"
    if (folder / "index.json").exists() and (folder / "complete").exists():
        return len(vision.Shots(folder).pending()) * eta.value("screen_s")
    if cfg["watch_screen"] and src["kind"] != "recording" and src.get("path") and Path(src["path"]).exists():
        return (src.get("duration") or 0) * eta.value("scan_rtf")
    return None


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
    plan = eta.current
    if plan:
        plan.at("screens")

    def status(d, p):
        _set(stage="screen", detail=d, progress=p)
        if plan:
            plan.progress(p)
    todo = len(vision.Shots(folder).pending()) if watched else 0
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
        if plan and not watched and src.get("duration"):
            eta.learn("scan_rtf", plan.elapsed() / src["duration"])
        elif plan and todo:
            eta.learn("screen_s", plan.elapsed() / todo)
    except AppError as e:
        left = len(vision.Shots(folder).pending())
        warning = (f"{left} tela(s) ficaram sem leitura" if left else "A tela não foi lida") + f": {str(e).rstrip('.')}."
    return _summary(folder, warning, watched)


def _summary(folder, warning=None, watched=True):
    """As telas escolhidas para a revisão (com id e tempo), as vistas e o aviso, se houver."""
    shots = vision.Shots(folder)
    items = [{"id": s["id"], "t": s["t"], "titulo": s["note"]["titulo"], "tipo": s["note"]["tipo"],
              "manual": bool(s.get("manual"))} for s in vision.select(shots.items)]
    if watched and not shots.items and not warning:  # captura sem nenhuma tela: não é o mesmo que “sem conteúdo”
        why = max(shots.refused, key=shots.refused.get) if shots.refused else None
        warning = "Nenhuma tela foi guardada durante a gravação" + (f" ({why})" if why else "") + "."
    logging.getLogger("lumen").info("telas da aula: %d guardada(s), %d para a página", len(shots.items), len(items))
    return {"items": items, "seen": len(shots.items), "warning": warning}


def finish(spec):
    """Fase 2: compreensão analisada + transcrição revisada → StudyPackage (a IA trabalha UMA vez) → o mesmo pacote
    para cada destino ligado (Obsidian e Notion; _deliver). Sem a nota do estudante (e a análise dela), nada é
    gerado nem salvo."""
    cfg = store.load_config()
    dests, token = _destinations(cfg)
    src = _cached_source(spec) or sources.resolve(spec)
    mine = understanding.require(src["key"], analyzed=True)
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
        for f in work.glob("music-*.wav"):  # nem o áudio derivado do filtro de música (o original é do usuário)
            f.unlink(missing_ok=True)
    check()
    _set(dests=dests)

    shots = vision.Shots(work / "screens")  # “Assistir a tela junto”: as telas que o usuário manteve na revisão
    off = {int(i) for i in spec.get("screens_off") or []}
    screens = [s for s in vision.select(shots.items) if s["id"] not in off]
    lines, chosen = vision.screen_lines(screens), {s["id"] for s in screens}
    model, lang = cfg["ollama_model"], spec.get("language") or cfg["page_language"]
    note = mine["current_understanding"]
    digest = hashlib.sha256(json.dumps([s["text"] for s in tr["segments"]] + [x for _, x in lines] + [note],
                                       ensure_ascii=False).encode()).hexdigest()
    redo = spec.get("mode") == "redo"  # “Refazer página”: material novo, versão anterior removida
    deep = cfg["study_level"] == "profundo"
    linking = "obsidian" in dests and cfg["obsidian_connections"] and cfg["study_level"] != "rapido"
    saved = _load(work / "lesson.json")
    cached = saved and not redo and saved.get("model") == model and saved.get("language") == lang \
        and saved.get("transcript") == digest and bool(saved.get("deep")) == deep
    eta.current = eta.Plan(_page_steps(tr, screens, lines, model, cached, saved, spec, len(note), dests, deep, linking))
    if cached:
        lesson, found = saved["lesson"], saved.get("charts")
    else:
        _set(stage="generate", detail="Estruturando o conteúdo a partir da sua compreensão…", progress=None, eta=None)
        lesson = llm.generate(tr["segments"], tr.get("duration"), model, lang, check,
                              lambda d, p: _set(stage="generate", detail=d, progress=p),
                              redo=redo, note=spec.get("redo_note") or "", screens=lines, understanding=note, deep=deep)
        saved, found = {"model": model, "language": lang, "transcript": digest, "deep": deep, "lesson": lesson}, None
        _save(work / "lesson.json", saved)
    check()
    if found is None:
        found, ok = _find_charts(tr, screens, lesson, model)
        if ok:  # falha da IA não fica guardada: “Tentar novamente” procura de novo
            saved = {**saved, "charts": found}
            _save(work / "lesson.json", saved)
    check()
    links = saved.get("links") if linking else None
    if linking and links is None:
        links, ok = _find_links(lesson, cfg, model, lang, package.lumen_id(src["key"]))
        if ok:
            saved = {**saved, "links": links}
            _save(work / "lesson.json", saved)
    check()

    _set(stage="generate", detail="Validando o material…", progress=None)
    step = -(-len(screens) // MAX_SCREENS) or 1  # aula com muitas telas: no máximo 40, espalhadas pela aula
    pkg = package.build(src, tr, lesson, mine, screens[::step], found, links, spec.get("course_title") or "", model,
                        vision.MODEL, cfg["review_intervals"] if cfg["obsidian_review"] else ())
    pkg = package.validate(pkg, _vault_names(cfg) if "obsidian" in dests else None)
    package.save(pkg)
    log.info("pacote de estudo criado: versão %s, %d tópicos, %d perguntas, %d relações, %d conexões, %d telas",
             pkg["processor_version"], len(lesson["topics"]), len(lesson["review_questions"]),
             len(lesson.get("relations") or []), len(pkg["connections"]), len(pkg["screens"]))
    out = _deliver(pkg, dests, spec, cfg, token, shots)
    if not cfg["keep_temp"]:
        # Guarda só a transcrição da última aula publicada (para “Refazer página”); a anterior é apagada.
        for mark in store.WORK.glob("*/published"):
            if mark.parent != work:
                shutil.rmtree(mark.parent, ignore_errors=True)
        (work / "published").touch()
        shots.prune(chosen)  # só as imagens das telas escolhidas ficam (para “Refazer página”)
    return out


def deliver(spec):
    """“Tentar de novo só o Obsidian/Notion” e “Salvar no Obsidian” (Biblioteca): o pacote guardado vai de novo aos
    destinos pedidos, sem chamar a IA. force: substituir a nota editada à mão (com backup)."""
    entry = store.history().get(str(spec.get("key"))) or {}
    pkg = package.load(entry.get("lumen_id") or package.lumen_id(str(spec.get("key"))))
    only = [d for d in ("obsidian", "notion") if d in (spec.get("only") or [])]
    if not only:
        raise AppError("Escolha o destino para salvar de novo.", "")
    cfg = store.load_config()
    dests, token = _destinations({**cfg, "destinations": "both" if len(only) == 2 else only[0]})
    _set(dests=dests, key=pkg["key"], title=pkg["lesson"]["title"])
    eta.current = eta.Plan([("obsidian", 1.5)] * ("obsidian" in dests) + [("publish", 10)] * ("notion" in dests))
    log.info("nova tentativa: %s", "+".join(dests))
    return _deliver(pkg, dests, {**(entry.get("spec") or {}), **spec}, cfg, token,
                    vision.Shots(work_dir(pkg["key"]) / "screens"), force=spec.get("force") is True)


def _destinations(cfg):
    """Os destinos ligados, conferidos antes de qualquer trabalho: o Notion pede o token; o Obsidian, um cofre válido
    (com a mensagem do que falta). Ordem de entrega: Obsidian (local) e depois Notion."""
    dests = {"notion": ["notion"], "obsidian": ["obsidian"]}.get(cfg["destinations"], ["obsidian", "notion"])
    token = None
    if "notion" in dests:
        token = store.get_token()
        if not token:
            raise AppError("O Notion ainda não foi conectado.", "Abra Integrações e conecte o Notion, ou escolha "
                                                                "“Só Obsidian” em Destinos do material.")
    if "obsidian" in dests:
        obsidian.folders(cfg)
    return dests, token


def _vault_names(cfg):
    root, _, _ = obsidian.folders(cfg)
    return [n["name"] for n in vault.index(root)]


def _find_links(lesson, cfg, model, lang, lid):
    """(conexões, guardar?): notas do cofre parecidas com a aula (busca local) e, entre elas, as que a IA local vê
    como relação real. Falha → sem conexões e nada guardado (“Tentar novamente” procura de novo); nunca impede."""
    _set(stage="connect", detail="Encontrando conexões no seu cofre…", progress=None)
    try:
        root, _, _ = obsidian.folders(cfg)
        notes = vault.index(root)
        m = lesson.get("mind_map") or {}
        query = [(lesson["title"], 2), (str(m.get("center") or ""), 2)]
        query += [(str(b.get("label") or ""), 2) for b in m.get("branches") or [] if isinstance(b, dict)]
        query += [(t["title"], 1) for t in lesson["topics"]] + [(g["term"], 1) for g in lesson.get("glossary") or []]
        cands = [n for n in vault.search(notes, query, 12, exclude=lid) if n["type"] != "anchor"]
        card = lambda n: {"name": n["name"], "kind": vault.KINDS.get(n["type"], "Nota"), "excerpt": vault.excerpt(n)}  # noqa: E731
        out = llm.connect(lesson, [card(n) for n in cands], [card(n) for n in vault.anchors(notes)], model, lang, check,
                          lambda d, p: _set(stage="connect", detail=d, progress=p))
        log.info("conexões: %d candidatas, %d escolhidas, %d Anchor Topics", len(cands), len(out["links"]),
                 len(out["anchors"]))
        return out, True
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 — opcional: sem conexões a nota sai do mesmo jeito
        log.warning("conexões: falha (%s)", type(e).__name__)
        return {"links": [], "anchors": [], "anchor_suggestion": ""}, False


def _deliver(pkg, dests, spec, cfg, token, shots, force=False):
    """Destination Router: o mesmo pacote para cada destino, um de cada vez. Obsidian primeiro (local, atômico e
    idempotente pelo lumen_id: repetir não duplica), depois o Notion (que desfaz o envio em falha ou cancelamento).
    A falha de um não desfaz o outro: cada um tem o seu status no manifesto e “Tentar de novo” refaz só o que falhou."""
    key, plan, t0 = pkg["key"], eta.current, time.monotonic()
    prev = store.history().get(key) or {}
    res = {"key": key, "lumen_id": pkg["lumen_id"], "title": pkg["lesson"]["title"],
           "course": pkg["course"] or notion.NO_COURSE, "dests": dests}
    store.remember(key, {"lumen_id": pkg["lumen_id"], "content_hash": pkg["content_hash"], "title": res["title"],
                         "processor_version": pkg["processor_version"], "spec": _spec(spec)})
    gifs = _draw(pkg["charts"], plan) if "notion" in dests or cfg["obsidian_attachments"] else []
    if "obsidian" in dests:
        if plan:
            plan.at("obsidian")
        _set(stage="obsidian", detail="Salvando no Obsidian (nota, mapas e conexões)…", progress=None)
        assets = {"charts": gifs, "screens": {}}
        if cfg["obsidian_attachments"]:
            for s in pkg["screens"]:
                try:
                    assets["screens"][s["id"]] = shots.image(s["id"])
                except (OSError, ValueError, KeyError):
                    pass  # imagem já apagada (tentar de novo dias depois): a tela entra só com o texto
        try:
            ob = obsidian.deliver(pkg, cfg, assets, prev.get("obsidian"), force, notion=prev.get("url"),
                                  transcript=_transcript(key, spec))
            res["obsidian"] = {**ob, "status": "ok"}
        except AppError as e:
            log.warning("obsidian: não salvo (%s)", "conflito" if "editada" in str(e) else "erro")
            res["obsidian"] = {"status": "error", "error": str(e), "action": e.action, "conflict": "editada" in str(e)}
        except OSError as e:
            log.warning("obsidian: erro de arquivo errno=%s", e.errno)
            res["obsidian"] = {"status": "error", "error": "Não foi possível gravar no cofre do Obsidian "
                               f"({e.strerror or 'erro de arquivo'}).", "action": "Confira se a pasta do cofre existe e "
                               "não está somente leitura, e tente de novo."}
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 — a falha de um destino nunca derruba o outro
            log.error("obsidian: erro inesperado %s", type(e).__name__)
            res["obsidian"] = {"status": "error", "error": f"Erro inesperado ao salvar no Obsidian ({type(e).__name__}).",
                               "action": "Tente de novo só o Obsidian; o material já está guardado."}
        # mescla com o que já havia: um erro agora não apaga onde estão a nota e o canvas desta aula
        store.remember(key, {"obsidian": {**(prev.get("obsidian") or {}), "error": None,
                                          **{k: v for k, v in res["obsidian"].items() if k != "action"},
                                          "at": datetime.now().isoformat(timespec="seconds")}})
    if "notion" in dests:
        check()  # cancelar aqui: o Obsidian já está salvo e “Retomar” não o duplica
        try:
            res["notion"] = {"status": "ok", **_notion(pkg, spec, token, gifs, shots, plan)}
        except AppError as e:
            res["notion"] = {"status": "error", "error": str(e), "action": e.action}
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 — idem: o Obsidian já salvo continua salvo
            log.error("notion: erro inesperado %s", type(e).__name__)
            res["notion"] = {"status": "error", "error": f"Erro inesperado ao salvar no Notion ({type(e).__name__}).",
                             "action": "Confira a página no Notion e tente de novo só o Notion."}
        store.remember(key, {"notion_status": {k: v for k, v in res["notion"].items() if k in ("status", "error")}
                             | {"at": datetime.now().isoformat(timespec="seconds")}})
    ok = [d for d in dests if res[d]["status"] == "ok"]
    if not ok:
        errs = [res[d] for d in dests]
        if len(errs) == 1:
            raise AppError(errs[0]["error"], errs[0].get("action") or "")
        raise AppError("Nada foi salvo. Notion: " + errs[1]["error"].rstrip(".") + ". Obsidian: "
                       + errs[0]["error"].rstrip(".") + ".", "Corrija e tente de novo; o material já gerado foi guardado.")
    url = (res.get("notion") or {}).get("url")
    if url and (res.get("obsidian") or {}).get("status") == "ok":
        try:  # a nota passa a apontar para a página do Notion (só o frontmatter muda)
            obsidian.set_fields(Path(res["obsidian"]["vault"]) / res["obsidian"]["note"], {"notion": url})
        except OSError:
            pass
    ob = res.get("obsidian") or {}
    understanding.synced(key, {"url": url or (res.get("notion") or {}).get("url"),
                               "understanding_url": (res.get("notion") or {}).get("understanding_url"),
                               "obsidian": ob.get("note") if ob.get("status") == "ok" else None,
                               "title": res["title"], "course": res["course"]})
    res["url"], res["understanding_url"] = url, (res.get("notion") or {}).get("understanding_url")
    res["note"] = (res.get("notion") or {}).get("note")
    log.info("entrega: %s em %.1f s", ", ".join(f"{d}={res[d]['status']}" for d in dests), time.monotonic() - t0)
    if ob.get("status") == "ok" and cfg["obsidian_open"]:
        try:
            obsidian.open_path(Path(ob["vault"]) / ob["note"])
        except OSError:
            pass
    return res


def _spec(spec):
    """O que “Tentar de novo só o Notion” precisa saber do pedido original (sem transcrição nem edições)."""
    return {k: spec.get(k) for k in ("course_id", "course_title", "mode", "include_transcript", "language") if k in spec}


def _transcript(key, spec):
    """Linhas “[mm:ss] texto” se o usuário pediu a transcrição completa no material (fica no PC até então)."""
    if not spec.get("include_transcript"):
        return None
    tr = _load(work_dir(key) / "transcript.json")
    return llm.transcript_text(tr["segments"]).split("\n") if tr else None


def _draw(found, plan):
    """GIF de cada gráfico, desenhado uma vez e usado pelos dois destinos (cada um num Edge, 3 ao mesmo tempo)."""
    if plan:
        plan.at("draw")
    if not found:
        return []
    from concurrent.futures import ThreadPoolExecutor
    _set(stage="generate", detail="Desenhando os gráficos da aula…", progress=None)
    def one(c):  # opcional: um gráfico que não desenha nunca impede o material (sai a tabela dos dados)
        try:
            return charts.render(c)
        except Exception as e:  # noqa: BLE001
            log.warning("gráfico: desenho falhou (%s)", type(e).__name__)
            return None
    with ThreadPoolExecutor(3) as ex:
        gifs = list(ex.map(one, found))
    if plan:
        eta.learn("chart_s", plan.elapsed() / -(-len(found) // 3))
    check()
    return gifs


def _notion(pkg, spec, token, gifs, shots, plan):
    """NotionRenderer + envio: a página da aula e a subpágina “Minha compreensão”, a partir do pacote."""
    key, lesson, src = pkg["key"], pkg["lesson"], pkg["source"]
    if plan:
        plan.at("mindmap")
    _set(stage="publish", detail="Desenhando o mapa mental…", progress=None)
    mind_png = mindmap.render(pkg["map"])
    check()
    _set(stage="publish", detail="Salvando na página escolhida do Notion…", progress=None)
    course_id = notion.course_for(token, store.load_config()["root_page_id"], spec.get("course_id") or "__none__")
    course = pkg["course"] or notion.NO_COURSE
    meta = {"course": course, "yt_id": src.get("yt_id"), "link": src.get("link"), "captures": src["kind"] == "captures",
            "source": f"{src['label']} — {src['title']}", "duration": src.get("duration"),
            "language": src.get("language"), "model": src.get("model"), "transcript_origin": src.get("origin") or "",
            "uncertain": src.get("uncertain"), "understanding": True}
    if mind_png:
        try:
            meta["mind_map_upload"] = notion.upload_image(token, mind_png, "mapa-mental.png")
        except AppError:
            pass  # o mapa vai em tópicos (notion._mind_map)
    if plan:
        eta.learn("mindmap_s", plan.elapsed())
    if pkg["charts"]:
        from concurrent.futures import ThreadPoolExecutor
        _set(stage="publish", detail="Enviando os gráficos da aula ao Notion…", progress=None)
        with ThreadPoolExecutor(3) as ex:
            ups = list(ex.map(lambda ig: _send(token, ig[1], f"grafico-{ig[0]}.gif", "image/gif") if ig[1] else None,
                              enumerate(gifs + [None] * (len(pkg["charts"]) - len(gifs)), 1)))
        meta["charts"] = [{**c, "upload": u} for c, u in zip(pkg["charts"], ups)]
        check()
    if plan:
        plan.at("screens")
    if pkg["screens"]:
        _set(stage="publish", detail=f"Enviando as {len(pkg['screens'])} telas da aula ao Notion…", progress=None)
        meta["screens"], meta["vision_model"] = _upload_screens(token, shots, pkg["screens"]), src.get("vision_model")
        if plan:
            eta.learn("upload_s", plan.elapsed() / -(-len(pkg["screens"]) // 3))
        check()
    title, blocks = notion.build_page(lesson, meta)
    transcript = _transcript(key, spec)
    check()
    sub = notion.understanding_page(pkg["understanding"], title)
    requests = _requests(blocks, transcript) + len(notion.batches(sub))
    if plan:
        plan.at("publish", requests * eta.value("request_s"))
    pid, url, block_ids = notion.publish(token, course_id, title, blocks, check, transcript=transcript, subpage=sub)
    if plan:
        eta.learn("request_s", plan.elapsed() / requests)
    mine_url = "https://www.notion.so/" + block_ids[-1].replace("-", "")  # a subpágina é o último bloco publicado
    shown = meta.get("screens") or []
    log.info("página publicada: %d bloco(s); telas: %d na página (%d sem imagem)", len(block_ids), len(shown),
             sum(1 for s in shown if not s.get("upload")))

    old = store.history().get(key) or {}
    redo, note = spec.get("mode") == "redo", None
    if spec.get("mode") in ("replace", "redo") and old.get("page_id"):
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
    store.remember(key, {"page_id": pid, "block_ids": block_ids, "url": url, "title": title, "course": course,
                         "created": datetime.now().isoformat(timespec="minutes")})
    return {"url": url, "understanding_url": mine_url, "note": note}


MAX_SCREENS = 40


def _requests(blocks, transcript):
    """Pedidos ao Notion para publicar: os lotes da página, os da transcrição e o da página escolhida."""
    lines = len(transcript or [])
    return 1 + len(notion.batches(blocks)) + (len(notion.batches([notion._b("paragraph", notion._rt(x))
                                                                 for x in transcript])) if lines else 0)


def _page_steps(tr, screens, lines, model, cached, saved, spec, extra=0, dests=("notion",), deep=False, linking=False):
    """As etapas do material com a estimativa de cada uma, antes de começar (extra: tamanho da nota)."""
    calls = [] if cached else llm.calls(tr["segments"], model, lines, extra=extra)
    steps = [(k, eta.llm_seconds(model, n, k)) for k, n in calls]
    if deep and calls:
        steps.append(("refine", eta.llm_seconds(model, calls[-1][1] * 1.3, "refine")))
    if not (cached and saved.get("charts") is not None):
        ctx = len(charts.context(charts.units(tr["segments"], screens)))
        steps.append(("charts", eta.llm_seconds(model, ctx + len(charts.SYSTEM) + 700, "charts") if ctx else 0.3))
    if linking and not (cached and saved.get("links") is not None):
        steps.append(("connect", eta.llm_seconds(model, 5000, "connect")))
    steps.append(("draw", eta.value("chart_s") if not cached or saved.get("charts") else 0))
    if "obsidian" in dests:
        steps.append(("obsidian", 1.5))
    if "notion" in dests:
        shown = min(len(screens), MAX_SCREENS)
        lines_out = len(llm.transcript_text(tr["segments"]).split("\n")) if spec.get("include_transcript") else 0
        steps += [("mindmap", eta.value("mindmap_s")), ("screens", -(-shown // 3) * eta.value("upload_s")),
                  ("publish", (3 + -(-lines_out // 100)) * eta.value("request_s"))]
    return steps


def _find_charts(tr, screens, lesson, model):
    """(gráficos, guardar?): os da aula (charts.extract). Se a IA falhar, só o da estrutura da aula, que não depende
    dela, e nada guardado (“Tentar novamente” procura de novo). Nunca impede a página."""
    _set(stage="generate", detail="Procurando dados da aula para gráficos…", progress=None)
    try:
        return charts.extract(tr["segments"], screens, lesson, model, check,
                              lambda d: _set(stage="generate", detail=d, progress=None), tr.get("language")), True
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 — opcional: qualquer falha aqui só deixa a página sem os gráficos da IA
        log.exception("gráficos: falha ao procurar dados")
        try:
            extra = charts.structure(tr["segments"], lesson)
        except Exception:  # noqa: BLE001
            log.exception("gráficos: falha no gráfico da estrutura")
            extra = None
        return [extra] if extra else [], False


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
        except (OSError, ValueError, KeyError):
            return None
    with ThreadPoolExecutor(3) as ex:
        ups = list(ex.map(up, screens))
    return [{**s, "upload": u} for s, u in zip(screens, ups)]


def download_whisper(name):
    _set(stage="download", detail="Baixando o modelo de transcrição…")
    transcribe.download(name)
    return {"downloaded": name}


def download_music():
    _set(stage="download", detail=f"Baixando o filtro de música ({_music.SIZE})…")
    _music.download()
    return {"downloaded": "music"}


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
