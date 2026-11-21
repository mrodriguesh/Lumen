"""Executável oficial/WebView2, perfil isolado e reabertura; dados sintéticos, sem gerar fala nem usar credenciais."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    out = parser.parse_args().out.resolve()
    assert out.drive.upper() == "D:", "Use o D: para o perfil de teste"
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    profile = out / "profile"
    os.environ.update(LUMEN_DATA=str(profile), PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
                      LUMEN_VOICESTUDIO_URL="http://127.0.0.1:9")
    from lumen import store
    from lumen.study import applied, db, learn, settings, tools
    assert store.DATA == profile / "Lumen"
    assert db.MEDIA.is_relative_to(profile)
    store.save_config({**store.DEFAULTS, "widget": "off", "obsidian_vault": ""})
    settings.save({"search": {"notion": False, "obsidian": False, "files": False, "images": False, "hybrid": False},
                   "voice": {"vs_autostart": False, "vs_warm_on_open": False}, "privacy": {"external": False}})
    ctx = tools.Ctx()
    ctx.cite({"id": "controle", "source": "obsidian", "title": "Fonte sintética de teste", "chunks": [
        {"id": 1, "heading": "Revisão", "text": "Revisar após estudar ajuda a lembrar."}]})
    raw = {"task": "Planeje uma revisão.", "deliverable": "Horário e assunto.", "criteria": [
        {"name": "Revisão", "expected": "Informe quando vai revisar.", "source": "S1"}]}
    provider = SimpleNamespace(name="ollama", json=lambda *a, **kw: raw)
    practice = learn.generate("exercise", "Revisão de controle", provider, ctx)
    raw = {"criteria": [{"id": 0, "score": 1, "feedback": "Horário informado."}], "next": "Realize a revisão."}
    practice = applied.submit(practice["id"], "Vou revisar às 18h.", [], provider)
    raw = {"goal": "Aplicar a revisão ao curso.", "steps": [{"title": "Revisar o capítulo", "objective": "Lembrar o conteúdo",
           "deliverable": "Resumo próprio", "source": "S1", "minutes": 25, "after_days": 1}],
           "reviews": [{"focus": "Relembrar o capítulo", "after_days": 2}]}
    plan = learn.generate("action", "Revisão de controle", provider, ctx, application="Meu curso de teste")
    db.close()
    exe = root / "Lumen.exe"
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    report = {"exe_sha256": digest, "profile": str(profile), "generated": "serviço falso; fixture sintética",
              "native": [], "page_errors": [], "passed": False}
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as pw:
        for cycle in range(2):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={port}"}
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 1  # janela de teste interativa: o WebView2 precisa criar seu controlador visível
            proc = subprocess.Popen([str(exe)], cwd=root, env=env, startupinfo=startup)
            report["native"].append({"pid": proc.pid, "cycle": cycle + 1, "cdp_port": port})
            (out / "running.json").write_text(json.dumps(report, indent=2), "utf-8")
            browser, page = None, None
            try:
                for _ in range(60):
                    if proc.poll() is not None:
                        raise RuntimeError("O executável isolado saiu antes de abrir o WebView2")
                    try:
                        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=1000)
                        break
                    except Exception:
                        time.sleep(1)
                assert browser is not None, "WebView2 não expôs CDP no perfil isolado"
                context = browser.contexts[0]
                for _ in range(60):
                    page = next((p for p in context.pages if p.url.startswith("http://127.0.0.1:") and "/widget" not in p.url), None)
                    if page:
                        break
                    time.sleep(1)
                assert page is not None, "Página principal não carregou"
                actual_port = (store.DATA / "port.txt").read_text().strip()
                assert page.url.startswith(f"http://127.0.0.1:{actual_port}/"), "Conexão precisa ser da instância isolada"
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.on("console", lambda msg: report["page_errors"].append(msg.text) if msg.type == "error" and "Content Security Policy" in msg.text else None)
                assert page.evaluate("!!window.chrome?.webview"), "Este teste exige o host nativo"
                page.locator("#nav-study").click()
                study = page.locator("#view-study")
                study.get_by_role("tab", name="Estudar", exact=True).click()
                study.locator(".st-learn-item").filter(has_text="Prática com correção").first.click()
                expect(study.locator(".st-attempt")).to_contain_text("100%")
                page.screenshot(path=str(out / f"native-practice-{cycle + 1}.png"))
                study.locator(".st-learn-item").filter(has_text="Plano de ação").first.click()
                step = study.locator(".st-action-plan input[type=checkbox]").first
                if cycle == 0:
                    step.check()
                    page.wait_for_function("async id => (await window.lumenStudy.api('/api/study/item?id=' + id)).data.steps[0].done", arg=plan["id"])
                else:
                    expect(step).to_be_checked()
                page.screenshot(path=str(out / f"native-plan-{cycle + 1}.png"))
                page.evaluate("window.lumenStudy.openSettings('catalog')")
                expect(page.get_by_role("heading", name="Catálogo", exact=True)).to_be_visible(timeout=20000)
                page.screenshot(path=str(out / f"native-catalog-{cycle + 1}.png"))
                page.evaluate("window.lumenStudy.openSettings('evaluation')")
                expect(page.get_by_role("heading", name="Avaliação local", exact=True)).to_be_visible()
                page.keyboard.press("Tab")
                assert page.evaluate("document.activeElement.tagName") in ("BUTTON", "SUMMARY", "A")
                report["native"][-1].update(webview=True, reopened=cycle == 1, persisted=True, url=page.url)
            finally:
                # Mensagem normal de saída, só no endereço conferido acima; nunca /api/bye pessoal.
                if page and page.url.startswith(f"http://127.0.0.1:{(store.DATA / 'port.txt').read_text().strip()}/"):
                    page.evaluate("document.getElementById('desktop-exit').click()")
                    proc.wait(timeout=20)
                if browser:
                    browser.close()
                if proc.poll() is None:
                    proc.terminate()  # somente o filho que este teste criou, se a inicialização falhou
                    proc.wait(timeout=10)
                (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    assert not report["page_errors"], report["page_errors"]
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == digest
    report["passed"] = True
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"passed": True, "cycles": 2, "out": str(out)}))


if __name__ == "__main__":
    main()
