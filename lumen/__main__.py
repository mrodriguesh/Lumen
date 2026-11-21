"""Inicia o Lumen: servidor local + janela do Edge em modo aplicativo (ou o navegador padrão)."""
import logging
import os
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

from . import AppError, jobs, obsidian, pomodoro, protection, record, server, store


def _edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        exe = Path(base or "") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if base and exe.is_file():
            return exe
    return None


def _reviews():
    """Revisões marcadas nas notas do Obsidian → próxima data no frontmatter (obsidian.sync_reviews)."""
    try:
        n = obsidian.sync_reviews(store.load_config())
        if n:
            logging.info("revisões: %d nota(s) atualizada(s)", n)
    except (AppError, OSError, ValueError) as e:
        logging.warning("revisões: %s", type(e).__name__)
    # cor dos estudos no Graph View (uma vez por cofre); com o Obsidian aberto, tenta de novo até ele fechar
    while obsidian.graph_identity(store.load_config()) == "busy":
        time.sleep(300)


def main():
    store.DATA.mkdir(parents=True, exist_ok=True)
    store.purge_old_uploads()
    # Log mínimo: etapas e tipos de erro. Nunca tokens, transcrições ou conteúdo.
    logging.basicConfig(filename=store.DATA / "lumen.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    httpd = server.serve(int(os.environ.get("LUMEN_PORT", 0)))
    url = f"http://127.0.0.1:{httpd.server_port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    pomodoro.start()
    try:
        protection.start()
    except (AppError, OSError):
        logging.warning("Proteção não iniciada; confira a configuração e a chave nos Ajustes.")
    threading.Thread(target=_reviews, daemon=True).start()
    from .study import listen  # “Deixar a voz pronta ao abrir” (D54); desligado por padrão
    threading.Thread(target=listen.on_start, daemon=True, name="Lumen voice warm").start()
    logging.info("Lumen iniciado")

    edge = _edge()
    if edge and not os.environ.get("LUMEN_NO_WINDOW"):
        subprocess.Popen([str(edge), f"--app={url}", f"--user-data-dir={store.DATA / 'janela'}",
                          "--no-first-run", "--no-default-browser-check", "--window-size=1120,820"])
    elif not os.environ.get("LUMEN_NO_WINDOW"):
        webbrowser.open(url)
    print(f"Lumen rodando em {url} — feche a janela do aplicativo para sair.")

    # Encerra quando a janela fecha (beacon) ou após 15 min sem contato e sem tarefa rodando. Dentro do Lumen.exe
    # não: a janela pode ficar parada na bandeja por horas, e o Lumen.exe já encerra o Python ao fechar.
    native = bool(os.environ.get("LUMEN_NO_WINDOW"))
    from . import transcribe
    from .study import call
    while True:
        time.sleep(1)
        transcribe.release_idle()  # modelos de fala parados há 15 min saem da RAM e da VRAM
        call.release_idle()
        now = time.monotonic()
        closed = server.bye_at and now - server.bye_at > 4 and server.last_seen <= server.bye_at
        idle = not native and now - server.last_seen > 900 and not jobs.busy() and not record.status()["active"]
        if closed or idle:
            jobs.cancel()
            protection.stop()
            record._stop.set()
            from . import voicestudio
            voicestudio.BACKEND.stop()  # só o backend que o Lúmen subiu (o pipe fechado já o derrubaria)
            logging.info("Lumen encerrado")
            httpd.shutdown()
            return


if __name__ == "__main__":
    main()
