"""A janela depois da retirada do Gemini: backend real e isolado (dados temporários em D:, Ollama falso, cofre em memória, rede externa
bloqueada) e Chrome headless (Playwright). O arquivo de ajustes começa como o do Lúmen anterior (Gemini como principal) e a chave dele
está no cofre falso: a migração roda ao abrir o servidor.
  py -3.14 tests/local_ai_ui.py        imagens e relatório em LUMEN_UI_ARTIFACTS (padrão D:/Lumen/remover-gemini-20261109/ui)
Prova na tela: nada do Gemini é oferecido (Modelos, Privacidade, Projetos, Integrações, menus, busca), a IA local responde, o Google Drive
da Proteção segue configurável, as rotas antigas não existem e nenhuma requisição saiu do 127.0.0.1."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("LUMEN_UI_BASE", "D:/Lumen/remover-gemini-20261109"))
ART = Path(os.environ.get("LUMEN_UI_ARTIFACTS", str(BASE / "ui")))
ART.mkdir(parents=True, exist_ok=True)
(BASE / "tmp").mkdir(parents=True, exist_ok=True)

BOOT = r"""
import sys, json, socket, urllib.request
sys.path.insert(0, sys.argv[1])
import tests                                    # isola LUMEN_DATA (no TEMP apontado para o D:) e instala o cofre em memória
from tests.fake_ollama import FakeOllama
fake = FakeOllama()
fake.models.append("qwen3.5:4b")
from lumen import server, store
from lumen.study import settings
store.get_token = lambda: ""
cfg = store.load_config(); cfg["obsidian_vault"] = sys.argv[2]; store.save_config(cfg)
OLD = json.loads(sys.argv[3])
settings._file().parent.mkdir(parents=True, exist_ok=True)
settings._file().write_text(json.dumps(OLD, ensure_ascii=False, indent=1), "utf-8")
tests.VAULT.items[(store.APP, "google-api-key")] = "AQ.chave-falsa-so-para-o-teste-0123456789"
tests.VAULT.items[(store.APP, "google-drive")] = json.dumps({"client_id": "1.apps.googleusercontent.com"})
EXTERNAL = []
real_open, real_dns = urllib.request.urlopen, socket.getaddrinfo
def spy_open(req, *a, **k):
    url = req if isinstance(req, str) else req.full_url
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        EXTERNAL.append(url.split("?")[0]); raise OSError("rede externa bloqueada no teste")
    return real_open(req, *a, **k)
def spy_dns(host, *a, **k):
    if host not in ("127.0.0.1", "localhost", None, ""):
        EXTERNAL.append("dns:" + str(host)); raise OSError("rede externa bloqueada no teste")
    return real_dns(host, *a, **k)
urllib.request.urlopen, socket.getaddrinfo = spy_open, spy_dns
server.ROUTES[("GET", "/api/study/__probe")] = lambda h: {
    "external": EXTERNAL, "vault": sorted(k[1] for k in tests.VAULT.items), "file": json.loads(settings._file().read_text("utf-8")),
    "bak": [p.name for p in settings._file().parent.glob("*.bak")]}
h = server.serve(); print(h.server_port, flush=True); h.serve_forever()
"""

OLD = {"gemini": {"accept_quotas": True, "accept_data_use": True, "key_epoch": 2, "confirmed_epoch": 2, "confirmed_at": "2026-11-09T10:00:00",
                  "locked_epoch": -1, "locked_reason": "", "migrated": "2026-11-09"},
       "models": {"provider": "google", "fallback": "google", "local": "qwen3:8b", "google": "gemini-3.8-flash", "image_provider": "google",
                  "image_google": "gemini-2.5-flash-image", "video_provider": "google", "temperature": 0.5},
       "privacy": {"external": True, "open_windows": True}, "search": {"web": True}}


def main():
    report = {"artifacts": str(ART), "checks": []}
    ok = report["checks"].append
    temp = tempfile.mkdtemp(prefix="lumen-local-ui-", dir=str(BASE / "tmp"))
    vault = Path(temp) / "cofre"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Sono.md").write_text("# Sono\nO sono consolida a memória.", "utf-8")
    env = {**os.environ, "TEMP": str(BASE / "tmp"), "TMP": str(BASE / "tmp")}
    log = (ART / "backend.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c", BOOT, str(ROOT), str(vault), json.dumps(OLD)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=log, text=True)
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors, requested = [], []
            page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" and "favicon" not in m.text else None)
            page.on("request", lambda r: requested.append(r.url.split("?")[0]) if r.url.startswith(url) else errors.append("fora do 127.0.0.1: " + r.url[:80]) if not r.url.startswith(("data:", "blob:")) else None)
            page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url.split('?')[0]}") if r.status >= 500 and r.url.startswith(url + "/") else None)
            shot = lambda name: (page.wait_for_timeout(400), page.screenshot(path=str(ART / f"{name}.png"), full_page=True))  # noqa: E731
            api = lambda path, body=None: page.evaluate("async ([p, b]) => await window.lumenStudy.api(p, b)", [path, body])  # noqa: E731
            probe = lambda: page.evaluate("async () => await window.lumenStudy.api('/api/study/__probe')")  # noqa: E731
            study = page.locator("[data-study]")

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator("#nav-study").click()
            expect(study).to_be_visible()

            # 1. A migração rodou ao abrir o servidor: ajustes locais, cópia do original, chave do Gemini fora do cofre, o resto do cofre intacto
            p0 = probe()
            m = p0["file"]["models"]
            assert (m["provider"], m["fallback"], m["image_provider"], m["video_provider"]) == ("ollama", "none", "local", "none"), m
            assert m["local"] == "qwen3:8b" and m["temperature"] == 0.5 and p0["file"]["search"]["web"] is True, p0["file"]
            assert "gemini" not in p0["file"] and "google" not in m and "image_google" not in m and "external" not in p0["file"]["privacy"], p0["file"]
            assert p0["bak"] == ["settings.json.antes-remocao-gemini-20261109.bak"], p0["bak"]
            assert "google-api-key" not in p0["vault"] and "google-drive" in p0["vault"], p0["vault"]
            ok("migração ao abrir: provedor local, cópia .bak, campos do Gemini fora do arquivo, só a chave do Gemini saiu do cofre (Drive intacto)")

            # 2. Estudos → Configurações → Modelos: nada do Gemini; a IA local aparece como o provedor
            study.get_by_role("button", name="Configurações da IA").click()
            expect(page.get_by_role("heading", name="Configurações da IA")).to_be_visible()
            page.get_by_role("button", name="Modelos", exact=True).click()
            panel = page.locator(".st-set-panel")
            expect(panel).to_contain_text("IA local (Ollama)")
            expect(panel).to_contain_text("Nenhuma IA em nuvem faz parte do Lúmen")
            text = panel.inner_text().lower()
            for forbidden in ("gemini", "google", "cotas oficiais", "plano gratuito", "chave de api", "openai", "claude", "chatgpt", "aistudio"):
                assert forbidden not in text, forbidden
            assert panel.locator("input[type=password]").count() == 0, "ainda há campo de chave"
            assert panel.get_by_label("Provedor principal").count() == 0 and panel.get_by_label("Provedor alternativo").count() == 0
            local = panel.get_by_label("Modelo para responder")
            assert "qwen3:8b" in local.locator("option").all_inner_texts(), local.locator("option").all_inner_texts()
            shot("01-modelos")
            ok("Modelos: provedor fixo na IA local, sem chave, sem aceites, sem cotas, sem Gemini, Claude ou OpenAI")

            page.get_by_role("button", name="Privacidade e permissões", exact=True).click()
            priv = page.locator(".st-set-panel")
            expect(priv).to_contain_text("A IA pode abrir páginas e notas sozinha")
            assert "provedores externos" not in priv.inner_text().lower() and "gemini" not in priv.inner_text().lower()
            shot("02-privacidade")
            page.get_by_role("button", name="Projetos", exact=True).click()
            page.get_by_role("button", name="Novo projeto").click()
            dialog = page.locator("dialog[open], [role=dialog]").last
            assert "externo" not in dialog.inner_text().lower() and "gemini" not in dialog.inner_text().lower(), dialog.inner_text()
            shot("03-projeto")
            page.keyboard.press("Escape")
            ok("Privacidade e Projetos: sem o interruptor de envio externo e sem 'Provedor externo (Gemini)'")

            # 3. A IA local responde, e nada saiu do 127.0.0.1
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            reply = page.evaluate("""async () => { const r = await fetch('/api/study/turn', {method: 'POST', headers: {'Content-Type': 'application/json',
                'X-Lumen-Token': document.querySelector('meta[name=lumen-token]').content}, body: JSON.stringify({text: 'Como o sono ajuda a memória?',
                provider: 'google', model: 'gemini-3.8-flash'})}); return await r.text(); }""")
            assert '"type": "done"' in reply or '"type":"done"' in reply, reply[:300]
            assert '"provider": "ollama"' in reply or '"provider":"ollama"' in reply, reply[-400:]
            assert "gemini" not in reply.lower(), reply[:300]
            assert probe()["external"] == [], probe()["external"]
            ok("uma conversa (pedindo o provedor removido de propósito) foi respondida pelo Ollama; nenhuma requisição externa")

            # 4. Integrações: Notion, Obsidian, Google Drive e Voice Studio; o Drive da Proteção segue configurável
            page.locator("#nav-integrations").click()
            tabs = [t.strip() for t in page.locator("#integ-tabs .integ-tab-name").all_inner_texts()]
            assert tabs == ["Notion", "Obsidian", "Google Drive", "Voice Studio"], tabs
            view = page.locator("#view-integrations")
            assert "gemini" not in view.inner_text().lower() and "notebook" not in view.inner_text().lower()
            page.locator("#itab-drive").click()
            drive = page.locator("#integ-drive")
            expect(drive).to_be_visible()
            expect(page.locator("#drive-status")).to_contain_text("Falta entrar com a sua conta")  # o cofre falso já tem o cliente OAuth
            expect(page.locator("#drive-actions").get_by_role("button", name="Entrar com Google", exact=True)).to_be_visible()
            expect(page.locator("#drive-actions").get_by_role("button", name="Trocar o arquivo do cliente")).to_be_visible()
            assert "gemini" not in drive.inner_text().lower()
            shot("04-integracoes-drive")
            ok("Integrações sem Gemini Notebook; o cartão do Google Drive (Proteção) mostra o estado e a ação certa")

            # 5. Nenhum rastro nas outras telas e nos menus
            for nav in ("#nav-home", "#nav-new", "#nav-library"):
                page.locator(nav).click()
                page.wait_for_timeout(500)
                body = page.locator("body").inner_text().lower()
                assert "gemini notebook" not in body and "notebooklm" not in body, nav
            page.keyboard.press("Control+K")
            for query in ("gemini", "caderno", "estudar esta aula"):  # os comandos antigos da busca não existem mais
                page.locator("#pal-input").fill(query)
                page.wait_for_timeout(300)
                texts = page.locator("#pal-list li").all_inner_texts()
                assert not any(t.strip().startswith(("Estudar esta aula no Gemini Notebook", "Abrir Gemini Notebook")) for t in texts), (query, texts)
            page.keyboard.press("Escape")
            catalog = api("/api/study/registry?full=1")
            ids = [x["id"] for x in catalog["integrations"]]
            assert "google" not in ids and "ollama" in ids, ids
            live = {k: catalog[k] for k in ("menu", "permissions", "integrations", "models", "roles")}  # medições e instalações são história
            live["roles"] = [{k: v for k, v in x.items() if k != "location"} for x in live["roles"]]  # o caminho dos dados de teste cita a pasta da tarefa
            blob = json.dumps(live, ensure_ascii=False)
            assert "gemini" not in blob.lower(), "o catálogo ativo ainda cita o Gemini: " + blob[max(0, blob.lower().index("gemini") - 120):][:260]
            ok("Início, Nova aula, Biblioteca, busca (Ctrl+K) e catálogo sem o Gemini")

            # 6. As rotas retiradas não existem e nada foi executado
            n0 = len(errors)  # os 404 do navegador abaixo são o resultado esperado destas chamadas, não erros da página
            statuses = page.evaluate("""async () => { const out = {}; const t = document.querySelector('meta[name=lumen-token]').content;
              for (const [m, p] of [['POST','/api/study/key'],['POST','/api/study/gemini'],['GET','/api/notebook'],['POST','/api/notebook/link'],
                                    ['POST','/api/notebook/drive/login'],['POST','/api/notebook/export'],['GET','/api/notebook/lesson?key=x']]) {
                const r = await fetch(p, {method: m, headers: {'Content-Type': 'application/json', 'X-Lumen-Token': t}, body: m === 'POST' ? '{}' : undefined});
                out[m + ' ' + p] = r.status; } return out; }""")
            assert set(statuses.values()) == {404}, statuses
            errors[n0:] = [e for e in errors[n0:] if "404 (Not Found)" not in e]
            after = probe()
            assert "google-api-key" not in after["vault"] and after["external"] == [], after
            ok("as 7 rotas retiradas testadas respondem 404; nada externo foi tocado")

            assert not errors, errors
            browser.close()
        report["ok"] = True
    finally:
        proc.terminate()
        log.close()
        (ART / "relatorio.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
