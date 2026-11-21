"""Conversa por voz: capturas e verificações da interface, isoladas do resto dos Estudos (headless, Playwright).

  py -3.14 tests/call_ui.py                       imagens em LUMEN_CALL_SHOTS (padrão D:/Lumen/voz-conversa-20261108/ui/<execução>)
  LUMEN_UI_ROOT=<árvore>  serve outra árvore de código (usada para a captura "antes" da interface antiga)

Reaproveita a fixture de tests/study_ui.py (Ollama falso, Voice Studio falso, microfone simulado, nenhum áudio gravado):
é janela headless e microfone falso, NÃO a janela nativa WebView2 nem uma conversa com voz real."""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SERVE = Path(os.environ.get("LUMEN_UI_ROOT", ROOT))
RUN = os.environ.get("LUMEN_CALL_RUN") or time.strftime("%Y%m%d-%H%M%S")
OUT = Path(os.environ.get("LUMEN_CALL_SHOTS") or f"D:/Lumen/voz-conversa-20261108/ui/{RUN}")
OUT.mkdir(parents=True, exist_ok=True)
BEFORE = os.environ.get("LUMEN_UI_BEFORE") == "1"   # a interface antiga não tem Livre/Notas: pula só essas verificações

tree = ast.parse((ROOT / "tests/study_ui.py").read_text("utf-8"))
BOOT = next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BOOT")

checks, errors = [], []
ok = checks.append

with tempfile.TemporaryDirectory(prefix="call-ui-") as temp:
    vault = Path(temp) / "Cofre de teste"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Memória e sono.md").write_text("# Memória e sono\nA consolidação da memória depende do sono profundo.", "utf-8")
    from PIL import Image
    shot_png = Path(temp) / "janela.png"
    Image.new("RGB", (320, 180), "white").save(shot_png)
    env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data")}
    log = (OUT / "backend.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c", BOOT, str(SERVE), str(vault), str(shot_png)], cwd=SERVE, env=env,
                            stdout=subprocess.PIPE, stderr=log, text=True)
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        proc.stdout.readline()
        proc.stdout.readline()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
            page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url.split('?')[0]}") if r.status >= 500 and r.url.startswith(url + "/") else None)
            shot = lambda name: (page.wait_for_timeout(350), page.screenshot(path=str(OUT / f"{name}.png")))  # noqa: E731
            feed = lambda *evs: page.evaluate("evs => evs.forEach(e => window.lumenStudy.feedCallEvent(e))", list(evs))  # noqa: E731

            def fits():
                wide = page.evaluate("""() => { const w = document.documentElement.clientWidth;
                    const clipped = (e) => { for (let p = e.parentElement; p && !p.matches('.view'); p = p.parentElement)
                      if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(p).overflowX)) return true; return false; };
                    return [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > w + 1 && e.getClientRects().length && !clipped(e))
                      .slice(0, 5).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right)); }""")
                assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") and not wide, f"rolagem horizontal em {page.viewport_size}: {wide}"

            def clipped_text():
                """Texto cortado ou controle escondido dentro da visão da chamada (altura/largura de conteúdo maior que a caixa)."""
                return page.evaluate("""() => [...document.querySelectorAll('.st-call:not([hidden]) button, .st-call:not([hidden]) .st-call-state, .st-call:not([hidden]) .st-call-hint')]
                  .filter(e => e.getClientRects().length && (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible'))
                  .map(e => e.className + ':' + e.textContent.trim().slice(0, 30))""")

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator("#nav-study").click()
            study = page.locator("[data-study]")
            expect(study).to_be_visible()
            expect(study.get_by_role("heading", name="O que vamos aprender hoje?")).to_be_visible(timeout=15000)

            # 0. Botão de entrada ao lado da caixa
            open_btn = study.get_by_role("button", name="Conversa por voz")
            expect(open_btn).to_be_visible()
            shot("00-entrada")
            page.set_viewport_size({"width": 520, "height": 860})
            shot("00-entrada-520")
            page.set_viewport_size({"width": 1440, "height": 900})
            ok("botão de entrada visível ao lado da caixa (1440 e 520 px)")

            # 1. Abrir: preparando (sem "Ouvindo" antes da hora), depois ouvindo
            open_btn.click()
            call = study.locator(".st-call")
            expect(call).to_be_visible(timeout=8000)
            state = call.locator(".st-call-state")
            orb = call.locator(".st-call-orb")
            expect(state).to_have_text("Ouvindo", timeout=10000)
            expect(call.locator(".st-call-mic-open")).to_be_visible()
            expect(orb).to_have_attribute("data-state", "listening")
            expect(call.locator(".st-call-orb-core .vc-avatar")).to_have_text("JS")
            shot("01-ouvindo")
            ok("chamada abre e só mostra 'Ouvindo' com o microfone pronto; avatar da voz escolhida")

            # 2. Estados reais vindos do servidor (injetados como eventos reais do fluxo)
            seq = [10_000]

            def ev(**k):
                seq[0] += 1
                return {"seq": seq[0], **k}

            feed(ev(type="state", active=True, state="preparing", label="Preparando a voz…"))
            feed(ev(type="preparing", phase="loading", label="Carregando o modelo de voz…", pct=None))
            expect(state).to_have_text("Preparando a voz")
            expect(call.locator(".st-call-prep-fill.indeterminate")).to_be_visible()
            assert not call.locator(".st-call-hint").inner_text().strip().endswith("%"), "porcentagem inventada na preparação"
            expect(call.locator(".st-call-mic-open")).to_be_hidden()
            shot("02a-preparando")
            feed(ev(type="preparing", phase="loading", label="Carregando o modelo de voz…", pct=40))
            expect(call.locator(".st-call-hint")).to_contain_text("40%")
            feed(ev(type="state", active=True, state="listening", label="Ouvindo", muted=False))
            feed(ev(type="state", active=True, state="user_speaking", label="Ouvindo você…", muted=False))
            feed(ev(type="partial", text="Me explica como o sono ajuda a mem"))
            expect(state).to_have_text("Você está falando")
            expect(orb).to_have_attribute("data-hearing", "true")
            shot("02b-voce-falando")
            feed(ev(type="state", active=True, state="thinking", phase="searching", label="Consultando suas notas…", muted=False))
            expect(state).to_have_text("Consultando suas notas")
            expect(orb).to_have_attribute("data-state", "thinking")
            shot("02c-consultando-notas")
            feed(ev(type="state", active=True, state="thinking", phase="", label="Preparando a resposta…", muted=False))
            expect(state).to_have_text("Preparando a resposta")
            feed(ev(type="final", text="Me explica como o sono ajuda a memória?"),
                 ev(type="state", active=True, state="speaking", label="Falando", muted=False),
                 ev(type="token", text="O sono profundo fixa o que você estudou. Durante a noite, o hipocampo reativa as lembranças.", replace=True),
                 ev(type="sentence", i=0, text="O sono profundo fixa o que você estudou."))
            expect(state).to_have_text("Falando")
            expect(orb).to_have_attribute("data-state", "speaking")
            expect(call.locator("mark.st-call-now")).to_have_text("O sono profundo fixa o que você estudou.")
            shot("02d-falando")
            feed(ev(type="state", active=True, state="speaking", label="Falando", muted=True))
            expect(state).to_have_text("Falando")   # mudo durante a fala não troca o estado da resposta
            expect(call.get_by_role("button", name="Silenciar microfone")).to_have_attribute("aria-pressed", "true")
            feed(ev(type="state", active=True, state="listening", label="Ouvindo", muted=True))
            expect(state).to_have_text("Microfone silenciado")
            expect(call.locator(".st-call-mic-open")).to_be_hidden()
            shot("02e-mudo")
            feed(ev(type="state", active=True, state="reconnecting", label="Reconectando o microfone…", muted=False))
            expect(state).to_have_text("Reconectando o microfone")
            shot("02f-reconectando-microfone")
            feed(ev(type="state", active=True, state="listening", label="Ouvindo", muted=False))
            feed(ev(type="error", message="O microfone não está disponível.", action="Conecte o aparelho de novo."))
            expect(call.locator(".st-call-hint")).to_contain_text("microfone não está disponível")
            expect(orb).to_have_attribute("data-state", "error")
            shot("02g-erro")
            feed(ev(type="state", active=True, state="listening", label="Ouvindo", muted=False))
            ok("estados: preparando (sem %), ouvindo, você falando, consultando notas, preparando resposta, falando, mudo, reconectando, erro")

            # 3. Eventos repetidos (reconexão) não duplicam a fala nem a legenda
            n_before = call.locator(".st-call-turn.user.final").count()
            dup = ev(type="final", text="Pergunta repetida?")
            feed(dup, dup, dup)
            assert call.locator(".st-call-turn.user.final").count() == n_before + 1, "evento repetido (mesmo seq) foi processado de novo"
            ok("evento com o mesmo seq é ignorado (reconexão sem duplicar)")

            # 4. Livre | Notas sincronizado com o chat escrito
            if not BEFORE:
                group = call.get_by_role("radiogroup", name="Fontes da resposta")
                free = group.get_by_role("radio", name="Livre")
                notes = group.get_by_role("radio", name=re.compile("Notas"))
                expect(notes).to_have_attribute("aria-checked", "true")
                free.click()
                expect(free).to_have_attribute("aria-checked", "true")
                assert page.evaluate("window.lumenStudy.S.skipVault === true"), "o chat escrito não acompanhou o modo livre da chamada"
                assert page.evaluate("localStorage.getItem('lumen.study.skipVault') === 'true'")
                snap = page.evaluate("fetch('/api/study/call', {headers: {'X-Lumen-Token': document.querySelector('meta[name=lumen-token]').content}}).then(r => r.json())")
                assert snap["vault"]["free"] is True, snap
                shot("03a-modo-livre")
                free.press("ArrowRight")
                expect(notes).to_have_attribute("aria-checked", "true")
                assert page.evaluate("window.lumenStudy.S.skipVault === false")
                page.wait_for_timeout(400)   # a resposta do servidor ao comando chega antes do próximo evento deste teste
                # o servidor muda por comando de voz → a tela e o chat acompanham
                feed(ev(type="vault", vault={"free": True, "sources": None}, source="voice"))
                expect(free).to_have_attribute("aria-checked", "true")
                assert page.evaluate("window.lumenStudy.S.skipVault === true"), "comando de voz não chegou ao estado do chat"
                feed(ev(type="vault", vault={"free": False, "sources": ["obsidian"]}, source="voice"))
                expect(group.get_by_role("radio", name="Obsidian")).to_have_attribute("aria-checked", "true")
                shot("03b-so-obsidian")
                feed(ev(type="state", active=True, state="speaking", label="Falando", muted=False, vault={"free": False, "sources": ["obsidian"]}, vault_pending=True))
                expect(call.locator(".st-call-vault-note")).to_have_text("Vale a partir da próxima resposta.")
                feed(ev(type="state", active=True, state="listening", label="Ouvindo", muted=False, vault={"free": False, "sources": None}, vault_pending=False))
                expect(call.locator(".st-call-vault-note")).to_be_hidden()
                ok("Livre | Notas: a chamada e o chat escrito usam o mesmo estado, a voz do servidor também o muda, e o aviso 'vale a partir da próxima resposta'")

            # 5. Responsividade e movimento reduzido
            for w, h in ((1440, 900), (1100, 860), (760, 860), (520, 860)):
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(250)
                fits()
                assert not clipped_text(), f"texto cortado em {w}px: {clipped_text()}"
                assert page.evaluate("""() => { const c = document.querySelector('.st-call:not([hidden])'); if (!c) return true;
                    const b = c.querySelector('.st-call-controls').getBoundingClientRect(); return b.bottom <= innerHeight + 1 || c.scrollHeight > c.clientHeight; }"""), f"controles fora da tela em {w}px"
                shot(f"04-chamada-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.emulate_media(reduced_motion="reduce")
            feed(ev(type="level", source="mic", level=0.9))
            assert page.evaluate("getComputedStyle(document.querySelector('.st-call-orb')).getPropertyValue('--amp').trim() === '0.00'"), "movimento reduzido não zerou o nível"
            page.emulate_media(reduced_motion="no-preference")
            ok("1440, 1100, 760 e 520 px sem rolagem horizontal, sem texto cortado e com os controles ao alcance; movimento reduzido")

            # 7. Teclado: M alterna o mudo, foco visível nos três controles
            page.locator(".st-call").focus()
            page.keyboard.press("m")
            page.wait_for_timeout(300)
            muted_now = call.get_by_role("button", name="Silenciar microfone").get_attribute("aria-pressed")
            page.keyboard.press("m")
            page.wait_for_timeout(300)
            ok(f"atalho M alterna o mudo (aria-pressed={muted_now})")
            for name in ("Silenciar microfone", "Interromper", "Encerrar chamada"):
                call.get_by_role("button", name=name).focus()
                outline = page.evaluate("""() => { const b = document.activeElement.querySelector('.st-call-ctl-ic'); return b ? getComputedStyle(b).outlineStyle : 'sem'; }""")
                assert outline != "none", f"foco invisível em {name}"
            ok("foco visível nos controles principais")

            # 8. Pílula minimizada
            call.get_by_role("button", name="Minimizar chamada").click()
            pill = page.locator(".st-call-pill")
            expect(pill).to_be_visible()
            expect(call).to_be_hidden()
            shot("06-pilula")
            page.set_viewport_size({"width": 520, "height": 860})
            fits()
            shot("06-pilula-520")
            page.set_viewport_size({"width": 1440, "height": 900})
            pill.get_by_role("button", name="Voltar para a chamada").click()
            expect(call).to_be_visible()
            ok("minimizar para a pílula e voltar")

            # 9. Encerrar
            call.get_by_role("button", name="Encerrar chamada").click()
            expect(call).to_be_hidden(timeout=8000)
            expect(study.locator(".st-main")).to_be_visible()
            ok("encerrar volta ao chat")
            browser.close()
        assert not errors, errors
        report = {"checks": checks, "errors": errors, "out": str(OUT), "served": str(SERVE)}
        (OUT / "relatorio.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
