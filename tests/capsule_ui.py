"""Cápsula de gravação da barra flutuante (Gravar/Encerrar + Pausar/Retomar), na página real (Chrome headless, `chrome.webview` simulado) com o
servidor real só para os arquivos e a API de gravação SIMULADA dentro da página (tests/capsule_harness.py): nenhum áudio, nenhuma gravação
pessoal, nenhum dado do usuário.

  py -3.14 tests/capsule_ui.py          imagens em CAPSULE_ARTIFACTS (padrão: tests/desktop-artifacts/capsula)

Prova o comportamento e a geometria da PÁGINA; o tamanho/foco da JANELA nativa e o DPI real só se provam no WebView2 (tests/DesktopChecks.cs)."""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # (não importa o pacote tests: ele pede o keyring, que só o .venv tem)
from capsule_harness import page  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ART = Path(os.environ.get("CAPSULE_ARTIFACTS", ROOT / "tests/desktop-artifacts/capsula"))
ART.mkdir(parents=True, exist_ok=True)
EDGES = ("left", "right", "top", "bottom", "free")
NOTE = "sim.notes = [{key: 'aula-1', title: 'Aula 1', label: 'Curso', state: 'preparing', updated: '2026-11-09T10:00:00', at: 0, rev: 1, ready: {}}]"
SETTLED = "() => document.getAnimations().filter(a => a instanceof CSSTransition).length === 0"
CONTROLS = ("#open", "#action", "#pause", "#chat-btn", "#note-btn", "#settings")
report = {"artifacts": str(ART), "checks": []}
ok = lambda name: (report["checks"].append(name), print("  ok:", name, flush=True))  # noqa: E731


def near(r, expected, tol=1.0):
    """Medidas em px lógicos: a barra centra os controles, então alguns caem em meio pixel."""
    return all(abs(a - b) <= tol for a, b in zip(r, expected))


def overlap(a, b, tol=.5):
    return min(a[2], b[2]) - max(a[0], b[0]) > tol and min(a[3], b[3]) - max(a[1], b[1]) > tol


with page(ART) as H:
    w, S = H.w, H.sim
    shot = lambda name: w.screenshot(path=str(ART / f"{name}.png"), animations="disabled")  # noqa: E731
    w.mouse.move(100, 100)
    w.wait_for_function("() => document.body.dataset.expanded === 'true'")
    settle = lambda timeout=6000: w.wait_for_function(SETTLED, timeout=timeout)  # noqa: E731
    attr = lambda name: w.evaluate("n => document.body.dataset[n]", name)  # noqa: E731
    rec_on = lambda: attr("rec") == "on"  # noqa: E731
    live = lambda: (w.wait_for_timeout(120), w.locator("#rec-live").text_content())[1]  # noqa: E731  (o anúncio entra 30 ms depois da mudança)
    visible = lambda sel: w.locator(sel).evaluate("n => { const s = getComputedStyle(n); return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > .95 }")  # noqa: E731

    RENDER = "([rec, hold]) => { pending = true; render({recording: rec, job: {status: 'idle', review: false}, notes: window.__sim.notes}); pending = !!hold; }"
    show = lambda rec, hold=False: w.evaluate(RENDER, [rec, hold])  # noqa: E731  (desenha direto, sem esperar a leitura do servidor)

    def reset(edge="left", note=False):
        S("sim.offline = false; sim.widgetDelay = 0; sim.fail = {}; sim.failAlways = {}; sim.delay = {start: 0, stop: 0, pause: 0, resume: 0}; sim.calls = []; "
          "s.active = false; s.paused = false; s.seconds = 0; s.level = 0; s.heard = false; s.error = null; sim.session = 0; sim.pauses = 0; " + (NOTE if note else "sim.notes = []"))
        w.evaluate("() => { pending = false; errorUntil = 0; armedUntil = 0; setBusy(''); if (window.__sim.notes.length) Notes.setActive('aula-1'); else { noteKey = null; missed = 0; } }")
        show({"active": False})
        H.edge(edge)
        w.wait_for_timeout(120); settle()
        assert attr("note") == str(note).lower(), ("Minha compreensão", attr("note"))

    def rects(sels=CONTROLS):
        return w.evaluate("""sels => Object.fromEntries(sels.map(s => { const e = document.querySelector(s); const r = e.getBoundingClientRect(); const v = getComputedStyle(e);
            return [s, {r: [r.left, r.top, r.right, r.bottom], shown: v.visibility !== 'hidden' && v.display !== 'none' && +v.opacity > .05 && r.width > 0}]; }))""", list(sels))

    def check_layout(tag, size=(304, 252)):
        """Todos os controles visíveis dentro da janela, sem sobreposição entre si nem com a alça; a pílula dentro da barra; nada decorativo capta clique."""
        R = rects(CONTROLS + (".rec-pill",))
        grip = w.evaluate("(() => { const r = document.querySelector('.grip span').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
        shown = {k: v["r"] for k, v in R.items() if v["shown"] and k != ".rec-pill"}
        for k, r in shown.items():
            assert r[0] >= -.5 and r[1] >= -.5 and r[2] <= size[0] + .5 and r[3] <= size[1] + .5, (tag, k, r, "fora da janela")
            assert not overlap(r, grip), (tag, k, "encosta na alça")
        names = list(shown)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                assert not overlap(shown[a], shown[b]), (tag, a, b, shown[a], shown[b], "controles sobrepostos")
        rail = w.evaluate("(() => { const r = document.querySelector('.rail').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] })()")
        if R[".rec-pill"]["shown"]:
            p = R[".rec-pill"]["r"]
            assert p[0] >= rail[0] - .5 and p[1] >= rail[1] - .5 and p[2] <= rail[2] + .5 and p[3] <= rail[3] + .5, (tag, "pílula fora da barra", p, rail)
        # o clique chega ao controle e não a algo decorativo por cima
        for k, r in shown.items():
            hit = w.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); return e ? (e.closest('button')?.id || e.className || e.tagName) : null }", [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2])
            assert hit == k.lstrip("#"), (tag, k, "o clique vai para", hit)
        return R

    # ------------------------------------------------------------------------------------------------------------------------------
    # 1. Parado: a barra é a de antes; a pausa não existe para quem olha, para o teclado nem para o leitor de tela
    reset("left")
    assert attr("rec") == "off" and not visible("#pause")
    assert w.locator("#pause").evaluate("n => getComputedStyle(n).visibility") == "hidden" and w.locator("#pause").evaluate("n => getComputedStyle(n).pointerEvents") == "none"
    assert w.locator("#pause").is_hidden(), "oculta para o Playwright/acessibilidade"
    assert w.locator("#action").get_attribute("aria-label") == "Iniciar gravação"
    R = check_layout("parado/left")
    assert near(R["#action"]["r"], [7, 82, 47, 122]) and near(R["#chat-btn"]["r"], [9, 134, 45, 170]) and near(R["#settings"]["r"], [9, 182, 45, 218]), ("parado, a barra é exatamente a de antes", {k: [round(x) for x in v["r"]] for k, v in R.items()}, w.evaluate("[document.querySelector('.rail').getBoundingClientRect().left, document.querySelector('.notch').getBoundingClientRect().left, document.body.dataset.side, document.body.dataset.edge, innerWidth]"))
    assert w.locator("#rec-group").evaluate("n => { const r = n.getBoundingClientRect(); return [r.width, r.height] }") == [40, 40]
    shot("01-parado-left")
    ok("parado: pausa indisponível (oculta, sem foco, sem clique, fora da árvore de acessibilidade) e a barra idêntica à de antes (Gravar 40 × 40 no mesmo lugar)")

    # 2. Iniciar: resposta imediata de espera; a gravação só aparece como ativa depois da confirmação; cliques repetidos não duplicam
    S("sim.delay.start = 700")
    w.locator("#action").click()
    w.wait_for_function("() => document.querySelector('#action').getAttribute('aria-busy') === 'true'", timeout=1500)
    assert attr("busy") == "start" and w.locator("#action").get_attribute("aria-label") == "Iniciando gravação…" and w.locator("#status").inner_text() == "Iniciando…"
    assert w.locator("#action").evaluate("n => getComputedStyle(n.querySelector('.busy-ring')).animationName") == "spin", "o anel só gira com um comando de verdade pendente"
    assert w.locator("#action").get_attribute("aria-disabled") == "true" and w.locator("#pause").get_attribute("aria-disabled") == "true"
    for _ in range(3):
        w.locator("#action").click(force=True)
    assert attr("rec") == "off" and not visible("#pause"), "ainda sem confirmação: nada de gravação nem de pausa"
    w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000)
    assert H.calls() == ["start"], H.calls()
    assert attr("busy") == "" and w.locator("#action").get_attribute("aria-busy") is None and w.locator("#action").get_attribute("aria-label") == "Encerrar gravação"
    settle()
    assert visible("#pause") and w.locator("#pause").get_attribute("aria-label") is None and w.locator("#pause-label").inner_text() == "Pausar gravação"
    assert w.locator("#pause").evaluate("n => getComputedStyle(n).animationName") == "none"
    assert w.evaluate("document.querySelectorAll('#pause').length") == 1 and w.evaluate("document.querySelectorAll('[id=action]').length") == 1
    assert w.evaluate("window.__sim.session") == 1
    shot("02-gravando-left")
    ok("iniciar: espera visível imediata (anel, rótulo, status), cliques repetidos não duplicam (1 comando), só vira gravação depois da confirmação, a pausa aparece uma vez")

    # 3. A pausa nunca sai do mesmo lugar do botão vermelho: o Gravar/Encerrar não se mexeu
    assert near(rects()["#action"]["r"], [7, 82, 47, 122]), "o alvo de encerrar não muda de lugar"
    check_layout("gravando/left")

    # 4. Duplo clique logo depois de iniciar NÃO encerra a gravação que acabou de começar; depois do intervalo, encerrar funciona
    w.locator("#action").click()
    w.wait_for_timeout(150)
    assert H.calls() == ["start"] and rec_on(), "um clique logo após iniciar é ignorado (não encerra sem querer)"
    ok("o alvo de encerrar fica no mesmo lugar e um segundo clique logo após iniciar não encerra a gravação")

    # 5. Pausar e retomar: mesma sessão, ícone e rótulo trocam (não só a cor), estado real vem do servidor
    w.wait_for_timeout(700)
    S("sim.delay.pause = 500")
    w.locator("#pause").click()
    w.wait_for_function("() => document.querySelector('#pause').getAttribute('aria-busy') === 'true'", timeout=1500)
    assert attr("busy") == "pause" and w.locator("#pause").get_attribute("aria-disabled") == "true" and w.locator("#action").get_attribute("aria-disabled") == "true"
    w.locator("#pause").click(force=True); w.locator("#pause").click(force=True)
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'true'", timeout=4000)
    settle()
    assert H.calls() == ["start", "pause"], H.calls()
    assert w.locator("#pause svg use").get_attribute("href").endswith("#play") and w.locator("#pause-label").inner_text() == "Retomar gravação"
    assert attr("paused") == "true" and w.locator("#status").inner_text() == "Pausada" and "nada é gravado" in w.locator("#detail").inner_text()
    assert w.locator("#action").get_attribute("aria-label") == "Encerrar gravação", "encerrar continua disponível e com o mesmo nome"
    assert w.evaluate("window.__sim.session") == 1 and w.evaluate("window.__sim.pauses") == 1 and w.evaluate("window.__sim.s.seconds") == 1
    shot("03-pausado-left")
    S("sim.delay.resume = 0")
    w.locator("#pause").click()
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'false'", timeout=4000)
    settle()
    assert H.calls() == ["start", "pause", "resume"] and w.locator("#pause svg use").get_attribute("href").endswith("#pause")
    assert w.evaluate("window.__sim.session") == 1, "retomar continua a MESMA gravação (nenhum start novo)"
    assert w.locator("#pause-label").inner_text() == "Pausar gravação" and w.locator("#time").inner_text() == "00:01"
    ok("pausar/retomar: mesma sessão, o contador não reinicia, ícone e rótulo trocam (pausa ↔ retomar), cliques repetidos viram 1 comando")

    # 6. Encerrar: espera visível, a cápsula só recolhe depois da confirmação, o fluxo existente (record:ready) roda uma vez
    w.wait_for_timeout(700)
    S("sim.delay.stop = 700")
    w.locator("#action").click()
    w.wait_for_function("() => document.querySelector('#action').getAttribute('aria-busy') === 'true'", timeout=1500)
    assert attr("busy") == "stop" and w.locator("#action").get_attribute("aria-label") == "Encerrando gravação…"
    w.locator("#action").click(force=True)
    assert rec_on(), "encerrando: a cápsula continua até o servidor confirmar"
    w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=4000)
    settle()
    assert H.calls() == ["start", "pause", "resume", "stop"], H.calls()
    ready = [m for m in H.messages() if m.startswith("record:ready:")]
    assert len(ready) == 1 and json.loads(ready[0][13:])["file"]["name"] == "Aula.wav"
    assert not visible("#pause") and w.locator("#action").get_attribute("aria-label") == "Iniciar gravação" and attr("busy") == ""
    assert near(rects()["#chat-btn"]["r"], [9, 134, 45, 170]), "tudo volta ao lugar"
    check_layout("depois-de-parar/left")
    ok("encerrar: espera visível, a cápsula só recolhe após a confirmação, record:ready uma vez, controles de volta ao lugar de antes")

    # 7. Início recusado: nada de gravação falsa; a mensagem real aparece e dá para tentar de novo
    S("sim.fail.start = 'Saída de áudio indisponível.'")
    started_before = H.messages().count("record:started")
    w.locator("#action").click()
    w.wait_for_function("() => document.body.dataset.state === 'error'", timeout=4000)
    w.wait_for_timeout(1300)  # passa uma leitura do servidor: o aviso continua
    assert attr("rec") == "off" and not visible("#pause") and "Saída de áudio indisponível" in w.locator("#detail").inner_text()
    assert w.locator("#action").get_attribute("aria-disabled") == "false" and w.locator("#action").get_attribute("aria-busy") is None
    assert w.evaluate("window.__sim.s.active") is False and H.messages().count("record:started") == started_before
    shot("04-inicio-recusado")
    w.locator("#action").click()
    w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000); settle()
    assert visible("#pause")
    ok("início recusado: não fica gravando visualmente, mensagem real no painel, botão livre; a nova tentativa funciona")

    # 8. Falha de pausa e de encerramento: o estado mostrado é o do servidor, a gravação não se perde
    w.wait_for_timeout(800)
    S("sim.fail.pause = 'Não consegui pausar agora.'")
    w.locator("#pause").click()
    w.wait_for_function("() => document.querySelector('#status').textContent.startsWith('Não foi possível pausar')", timeout=4000)
    assert rec_on() and w.locator("#rec-group").get_attribute("data-paused") == "false" and visible("#pause")
    assert "Não consegui pausar agora." in w.locator("#detail").inner_text() and w.evaluate("window.__sim.s.paused") is False
    S("sim.fail.stop = 'Disco ocupado.'")
    w.wait_for_timeout(300)
    w.locator("#action").click()
    w.wait_for_function("() => document.body.dataset.state === 'error'", timeout=4000)
    w.wait_for_timeout(1300)
    assert rec_on() and w.evaluate("window.__sim.s.active") is True, "o encerramento falhou: a gravação continua, e a cápsula também"
    assert w.locator("#action").get_attribute("aria-disabled") == "false" and w.locator("#pause").get_attribute("aria-disabled") == "false"
    w.locator("#action").click()  # recuperação: tenta de novo e agora encerra
    w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=4000); settle()
    assert w.evaluate("window.__sim.s.active") is False
    ok("falhas de pausa e de encerramento: a cápsula continua refletindo o servidor (sem sucesso falso) e a recuperação funciona sem perder a gravação")

    # 9. Estado vindo de outra janela: a cápsula reage à MUDANÇA (não a cada leitura) e anuncia de forma discreta
    reset("left")
    w.evaluate("() => { window.__runs = 0; for (const s of ['#pause', '.rec-pill']) document.querySelector(s).addEventListener('transitionrun', () => window.__runs++); }")
    S("s.active = true; s.paused = false; s.seconds = 30; s.level = .3; s.heard = true")
    w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000)
    w.wait_for_function("() => document.getElementById('rec-live').textContent === 'Gravação iniciada.'", timeout=2000)
    settle()
    first_runs = w.evaluate("window.__runs")
    assert first_runs > 0 and visible("#pause")
    w.wait_for_timeout(2600)  # ~10 leituras do servidor com a gravação ativa
    assert w.evaluate("window.__runs") == first_runs, "leituras seguintes do servidor não reiniciam a animação"
    S("s.paused = true")
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'true'", timeout=3000)
    assert live() == "Gravação pausada." and w.locator("#pause svg use").get_attribute("href").endswith("#play")
    S("s.paused = false")
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'false'", timeout=3000)
    S("s.active = false; s.seconds = 0")
    w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=4000); settle()
    assert live() == "Gravação encerrada." and not visible("#pause")
    ok("gravação iniciada, pausada, retomada e encerrada por OUTRA janela: a cápsula acompanha, anuncia uma vez por mudança e não reinicia a animação a cada leitura")

    # 10. Iniciada em outra janela enquanto esta mostra "Gravar": o clique NÃO encerra o que a pessoa não viu gravando
    reset("left")
    S("s.active = true; s.seconds = 5; s.heard = true")  # outra janela começou; esta ainda não leu
    w.locator("#action").click()
    w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000)
    assert "stop" not in H.calls() and "start" not in H.calls() and w.evaluate("window.__sim.s.active") is True
    S("s.active = false")
    w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=4000); settle()
    ok("estado diferente do que a pessoa viu: mostra o real e não age (nunca encerra uma gravação por engano)")

    # 11. Trocar de painel, recolher e conversar não pausam nem encerram; a cápsula segue utilizável por cima de qualquer painel
    reset("left")
    w.locator("#action").click(); w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000); settle(); w.wait_for_timeout(800)
    for open_sel, panel in (("#chat-btn", "#chat-panel"), ("#settings", "#preferences")):
        w.locator(open_sel).click()
        expect(w.locator(panel)).to_be_visible()
        assert rec_on() and visible("#pause") and w.locator("#recording-panel").is_hidden()
        check_layout(f"painel-{panel}")
    w.locator("#settings").click()  # fecha ajustes
    w.locator("#chat-btn").click()
    expect(w.locator("#chat-panel")).to_be_visible()
    shot("05-gravando-com-conversa")
    S("sim.calls.length = 0")
    w.locator("#pause").click()  # pausar COM a conversa aberta, sem trocar o painel
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'true'", timeout=4000)
    assert H.calls() == ["pause"] and w.locator("#chat-panel").is_visible(), "a conversa continua aberta"
    w.evaluate("conceal()"); w.wait_for_timeout(200)  # recolher a barra
    w.evaluate("document.body.dataset.expanded = 'true'")
    assert H.calls() == ["pause"] and w.evaluate("window.__sim.s.active") is True and w.evaluate("window.__sim.s.paused") is True
    w.locator("#chat-btn").click() if w.locator("#chat-panel").is_visible() else None
    S("sim.calls.length = 0")
    w.locator("#pause").click(); w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'false'", timeout=4000)
    assert H.calls() == ["resume"]
    w.locator("#action").click(); w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=4000); settle()
    ok("conversa/ajustes/recolher não pausam nem encerram; a cápsula pausa e retoma por cima do chat sem trocar o painel")

    # 12. Quatro orientações + posição livre, com e sem Minha compreensão, parado/gravando/pausado, durante E depois da transição
    for note in (False, True):
        for edge in EDGES:
            reset(edge, note)
            tag = f"{edge}{'+nota' if note else ''}"
            check_layout(f"{tag}/parado")
            show({"active": True, "seconds": 65, "heard": True, "level": .3}, hold=True)
            S("s.active = true; s.seconds = 65; s.level = .3; s.heard = true")
            # quadros EXATOS: pausa as transições e posiciona cada uma em t ms
            w.evaluate("() => document.getAnimations().filter(a => a instanceof CSSTransition).forEach(a => a.pause())")
            for t in (0, 60, 120, 180, 240, 300, 340):
                w.evaluate("t => document.getAnimations().filter(a => a instanceof CSSTransition).forEach(a => { a.currentTime = t })", t)
                R = rects(CONTROLS)
                for k, v in R.items():
                    r = v["r"]
                    if v["shown"] or k == "#pause":
                        assert r[0] >= -.5 and r[1] >= -.5 and r[2] <= 304.5 and r[3] <= 252.5, (tag, t, k, r, "fora da janela durante a transição")
                for other in ("#chat-btn", "#settings", "#open", "#note-btn"):
                    if R[other]["shown"] or other == "#note-btn" and note:
                        assert not overlap(R["#pause"]["r"], R[other]["r"], 1.0), (tag, t, "a pausa invade", other)
            w.evaluate("() => { document.getAnimations().filter(a => a instanceof CSSTransition).forEach(a => a.finish()); pending = false; }")
            settle()
            check_layout(f"{tag}/gravando")
            S("s.paused = true")
            show({"active": True, "paused": True, "seconds": 65, "heard": True})
            settle()
            check_layout(f"{tag}/pausado")
            if not note and edge in ("left", "top"):
                shot(f"06-{edge}-pausado")
            show({"active": True, "seconds": 65, "heard": True, "level": .3})
            settle()
            if not note and edge in ("left", "right", "top", "bottom"):
                shot(f"07-{edge}-gravando")
    ok("cinco posições × com/sem Minha compreensão × parado/gravando/pausado: nada cortado nem sobreposto, pílula dentro da barra, nenhum clique capturado por algo decorativo; "
       "a pausa nunca invade Conversa/Ajustes/Lumen em nenhum quadro da transição")

    # 13. Escalas do navegador (100/125/150/200%): as medidas em px lógicos são as mesmas e continuam dentro da janela
    base = None
    for scale in (1, 1.25, 1.5, 2):
        ctx = H.browser.new_context(viewport={"width": 304, "height": 252}, device_scale_factor=scale)
        ctx.add_init_script("window.messages=[]; window.hostListeners=[]; window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,fn)=>hostListeners.push(fn)};")
        from capsule_harness import SIM  # noqa: E402
        ctx.add_init_script(SIM)
        q = ctx.new_page(); q.goto(H.url + "/widget"); q.wait_for_function("() => state !== null")
        q.mouse.move(100, 100); q.wait_for_function("() => document.body.dataset.expanded === 'true'")
        for edge in ("left", "top"):
            q.evaluate("e => { hostListeners.forEach(fn => fn({data: 'edge:' + e})); hostListeners.forEach(fn => fn({data: 'side:left'})) }", edge)
            q.evaluate("() => { pending = true; render({recording: {active: true, seconds: 9, heard: true}, job: {status: 'idle'}}); pending = false; }")
            q.wait_for_function(SETTLED)
            got = q.evaluate("""() => Object.fromEntries(['#open','#action','#pause','#chat-btn','#settings'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [s, [r.left, r.top, r.right, r.bottom].map(v => Math.round(v * 100) / 100)]; }))""")
            for k, r in got.items():
                assert r[0] >= 0 and r[1] >= 0 and r[2] <= 304 and r[3] <= 252, (scale, edge, k, r)
            base = base or {}
            if edge in base:
                assert base[edge] == got, (scale, edge, "as medidas lógicas mudaram com a escala", base[edge], got)
            base[edge] = got
        ctx.close()
    ok("escalas de 100%, 125%, 150% e 200% do navegador: as medidas lógicas da cápsula são idênticas e ficam dentro da janela (o DPI da janela nativa é provado no WebView2)")

    # 14. Teclado e foco: Tab passa por Gravar e depois Pausar; foco visível; atalho Ctrl+Alt+P; o foco não se perde quando a pausa sai de cena
    reset("left")
    w.locator("#action").focus()
    w.keyboard.press("Enter")
    w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000); settle(); w.wait_for_timeout(800)
    assert w.evaluate("document.activeElement.id") == "action", "o foco do teclado não se perdeu durante o comando"
    w.keyboard.press("Tab")
    assert w.evaluate("document.activeElement.id") == "pause", "ordem do teclado: Gravar/Encerrar e depois Pausar"
    assert w.evaluate("document.activeElement.matches(':focus-visible')") and w.locator("#pause").evaluate("n => getComputedStyle(n).outlineStyle") == "solid", "foco visível"
    w.keyboard.press("Space")
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'true'", timeout=4000)
    assert w.evaluate("document.activeElement.id") == "pause", "pausar pelo teclado mantém o foco na pausa (que agora retoma)"
    w.keyboard.press("Control+Alt+p")
    w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'false'", timeout=4000)
    w.keyboard.press("Tab")
    assert w.evaluate("document.activeElement.id") == "chat-btn"
    w.locator("#pause").focus()
    S("s.active = false")  # encerrada por outra interface com o foco na pausa
    w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=4000); settle()
    assert w.evaluate("document.activeElement.id") == "action", "a pausa saiu de cena: o foco vai para o Gravar, não se perde"
    assert not any(t for t in w.evaluate("[...document.querySelectorAll('[title]')].map(n => n.title)")), "sem title nativo"
    ok("teclado: ordem Gravar → Pausar, Enter/Espaço, atalho Ctrl+Alt+P, foco visível, o foco não se perde nem durante um comando nem quando a pausa some")

    # 15. Movimento reduzido: aparece no lugar, sem deslizar; os controles seguem acessíveis
    w.emulate_media(reduced_motion="reduce")
    reset("left")
    show({"active": True, "seconds": 9, "heard": True, "level": .3})
    props = w.evaluate("() => document.getAnimations().filter(a => a instanceof CSSTransition).map(a => a.transitionProperty)")
    assert "translate" not in props and "scale" not in props and "height" not in props and "width" not in props, props
    assert "opacity" in props
    w.wait_for_timeout(260); settle()
    assert visible("#pause")
    r = rects()
    assert near(r["#chat-btn"]["r"], [9, 164, 45, 200]), "os vizinhos já estão no lugar final, sem deslizar"
    check_layout("movimento-reduzido")
    shot("08-movimento-reduzido")
    show({"active": False})
    w.wait_for_timeout(260); settle()
    assert not visible("#pause")
    w.emulate_media(reduced_motion="no-preference")
    ok("movimento reduzido: a pausa aparece no lugar com um esmaecer curto, os vizinhos vão direto ao lugar final, tudo acessível")

    # 16. Recarga e reconexão: nunca um estado visual falso
    reset("left")
    S("s.active = true; s.paused = true; s.seconds = 40; s.heard = true")
    w.reload(); w.wait_for_function("() => state !== null")
    w.mouse.move(100, 100); w.wait_for_function("() => document.body.dataset.expanded === 'true'")
    w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000)
    assert w.evaluate("document.getAnimations().filter(a => a instanceof CSSTransition && ['translate','scale','height','width'].includes(a.transitionProperty)).length") == 0, "recarregada já gravando: aparece pronta, sem animar uma entrada falsa"
    w.wait_for_timeout(300)
    assert visible("#pause") and w.locator("#rec-group").get_attribute("data-paused") == "true" and w.locator("#pause svg use").get_attribute("href").endswith("#play")
    assert live() == "", "sem anúncio falso ao recarregar"
    S("sim.offline = true")  # perde a conexão
    w.wait_for_function("() => document.body.dataset.conn === 'lost'", timeout=4000)
    assert rec_on() and w.locator("#rec-group").evaluate("n => +getComputedStyle(n).opacity") < .7, "sem conexão: o último estado fica esmaecido, não afirmado"
    S("s.active = false; s.paused = false; sim.offline = false")  # volta, e a gravação terminou enquanto isso
    w.wait_for_function("() => document.body.dataset.conn === undefined && document.body.dataset.rec === 'off'", timeout=5000); settle()
    assert not visible("#pause") and w.locator("#rec-group").evaluate("n => +getComputedStyle(n).opacity") == 1
    w.reload(); w.wait_for_function("() => state !== null")
    w.mouse.move(100, 100); w.wait_for_timeout(600)
    assert attr("rec") == "off" and not visible("#pause")
    ok("recarga já gravando (pausada) abre pronta, sem animação nem anúncio falsos; sem conexão a cápsula fica esmaecida; ao voltar mostra o estado REAL; recarga parada abre parada")

    # 17. Resposta atrasada: uma leitura pedida ANTES do comando não desfaz o resultado dele
    reset("left")
    w.locator("#action").click(); w.wait_for_function("() => document.body.dataset.rec === 'on'", timeout=4000); settle(); w.wait_for_timeout(800)
    w.evaluate("() => { window.__log = []; new MutationObserver(() => window.__log.push(document.querySelector('#rec-group').dataset.paused)).observe(document.querySelector('#rec-group'), {attributes: true, attributeFilter: ['data-paused']}); }")
    S("sim.delays = [1100]")          # a PRÓXIMA leitura do servidor (a do poll) demora 1,1 s
    w.wait_for_function("() => window.__sim.delays.length === 0", timeout=3000)  # o poll a pegou e está esperando...
    w.locator("#pause").click()      # ...e a pausa termina antes de ela voltar
    w.wait_for_timeout(2500)
    log = w.evaluate("window.__log")
    assert log and log[-1] == "true" and "false" not in log[log.index("true"):], ("a leitura atrasada desfez a pausa por um instante", log)
    assert H.calls() == ["start", "pause"]
    w.locator("#pause").click(); w.wait_for_function("() => document.querySelector('#rec-group').dataset.paused === 'false'", timeout=5000)
    w.locator("#action").click(); w.wait_for_function("() => document.body.dataset.rec === 'off'", timeout=6000); settle()
    ok("resposta atrasada do servidor: uma leitura anterior ao comando é descartada, a cápsula não volta atrás nem pisca")

    # 18. Imagens de referência: parado, gravando e pausado nas quatro bordas; erros e consistência
    assert not H.errors, H.errors
    report["result"] = "OK"

(ART / "capsule-ui-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"OK: {len(report['checks'])} blocos de verificação da cápsula de gravação; imagens em {ART}")
