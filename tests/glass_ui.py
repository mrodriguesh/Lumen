r"""Lúmen Glass 2026 no navegador (Playwright + Chrome sem GPU, como o WebView2), com dados isolados.

Na raiz do projeto (o Playwright está no Python do sistema):
  py -3.14 tests\glass_ui.py            todas as verificações
  py -3.14 tests\glass_ui.py --shots    também salva capturas em tests\desktop-artifacts\glass\

Parte 1 (servidor REAL isolado, tests/ui_harness.py): o estilo abre como Clássico, troca para o Glass em Ajustes sem recarregar e sem
perder o que estava sendo digitado, fica salvo ao reabrir, e volta ao Clássico com cada elemento no lugar e na ordem de antes.
Parte 2 (mundo simulado, tests/ui_shots.py): navegação, fontes da Nova aula, gravação, recuperação (cancelar não apaga), Pomodoro,
Ações rápidas, Biblioteca, jornada, controles de janela e a disposição em vários tamanhos (sem rolagem horizontal nem controle cortado).
É teste de NAVEGADOR: a janela nativa (moldura, DPI, Snap) é conferida no Lumen.exe (docs/DESIGN.md → Lúmen Glass 2026).
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "desktop-artifacts" / "glass"
SHOTS = "--shots" in sys.argv


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = load("ui_harness", ROOT / "tests" / "ui_harness.py")  # por caminho: o pacote tests trocaria o LUMEN_DATA
U = load("ui_shots", ROOT / "tests" / "ui_shots.py")
from playwright.sync_api import sync_playwright  # noqa: E402

ok, bad = [], []


def check(cond, what):
    (ok if cond else bad).append(what)
    print(("  ok   " if cond else "  FALHA ") + what)


REAL = ("/api/study/", "/api/voicestudio", "/api/protection", "/api/hardware", "/api/diagnostics")


def set_style(url, style):
    """O estilo vale no servidor (é ele que marca o <html>): grava pela mesma rota de Ajustes."""
    import re
    import urllib.request
    tok = re.search(r'name="lumen-token" content="([^"]+)"', urllib.request.urlopen(url + "/widget").read().decode()).group(1)
    req = urllib.request.Request(url + "/api/settings?view=settings", data=json.dumps({"ui_style": style}).encode(),
                                 headers={"X-Lumen-Token": tok, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())["config"]["ui_style"]


def mocked(browser, url, size=(1568, 1003), patch=None, style="glass"):
    set_style(url, style)
    W = U.world()
    W["config"]["ui_style"] = style
    if patch:
        patch(W)
    log = []
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
    ctx.add_init_script(U.HOST)
    inner = U.router(W, log)
    ctx.route("**/api/**", lambda r: r.continue_() if any(k in r.request.url for k in REAL) else inner(r))
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(url + "/?frame=1")
    page.wait_for_function("() => typeof S !== 'undefined' && S !== null && typeof historyItems !== 'undefined' && historyItems !== null", timeout=15000)
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(300)
    return ctx, page, W, log, errs


def shot(page, name):
    if SHOTS:
        OUT.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT / f"{name}.png"))


SET_ORDER = "() => [...document.querySelectorAll('#view-settings .set-panel')].map(p => [...p.children].map(c => c.tagName + '#' + c.id + '.' + c.className).join('|'))"
# o resultado de uma aula (Nova aula › Salvar), desenhado pela função de sempre a partir de uma tarefa concluída de mentira
RUN = "(job) => { showView('new'); lastUrl = '/api/finish'; lastSpec = { kind: 'recording' }; showStep('run'); renderJob(job); renderStatus(); }"
_VIS = {**U.VIS, "kind": "png", "file": "0123456789abcdef.png", "describe": "Sistema · 3 componentes da aula e 1 relação"}
DONE_VIS = {**U.DONE, "result": {**U.DONE["result"], "visual": _VIS}}
DONE_NT_FAIL = {**U.DONE, "result": {**U.DONE["result"], "visual": {**_VIS, "notion": "upload-failed"},
                                     "notion": {"status": "error", "error": "O Notion não respondeu a tempo.", "action": "Confira a internet e tente de novo."}}}


def act_rows(n=47):
    """Registros de mentira no formato de lumen/study/activity.py (nenhum dado do usuário): hoje, ontem e dias anteriores."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(microsecond=0)
    base = [("envio-externo", "", "modelo-de-teste", "ok", "envio externo", "anthropic", "1 842 caracteres de fontes"),
            ("testar-fonte", "", "Obsidian", "O cofre não foi encontrado.", "", "", ""),
            ("ferramenta", "buscar_notas", "fotossíntese fase clara", "ok", "nível 1 · leitura", "", "6 trechos"),
            ("ferramenta", "abrir_pagina", "", "erro: tempo esgotado ao abrir a página", "nível 1 · leitura", "", ""),
            ("preparar-gravacao", "obsidian", "Estudos/Biologia/Fotossíntese — um resumo de nome bem comprido para testar o corte.md", "aguardando confirmação", "nível 2", "", ""),
            ("cancelar-gravacao", "", "a-102", "cancelada pelo usuário", "nível 2", "", ""),
            ("chamada-turno", "", "parakeet", "1240 ms", "", "local", "asr 310 · llm 620 · tts 310"),
            ("migracao-gemini", "", "integração Gemini retirada", "4 ajustes realizados", "automática", "", "")]
    rows = []
    for i in range(n):
        a, tool, target, result, perm, prov, detail = base[i % len(base)]
        at = now - timedelta(minutes=7 * i, days=0 if i < 3 else (i - 3) // 6 + 1)
        rows.append({"id": 1000 - i, "at": at.isoformat(), "action": a, "tool": tool, "target": target, "result": result, "permission": perm,
                     "provider": prov, "conversation_id": "", "detail": detail})
    return rows


def fake_activity(ctx, rows):
    calls = []
    ctx.route("**/api/study/activity**", lambda r: (calls.append(r.request.url), r.fulfill(json={"activity": rows})))
    return calls


OPEN_SET = """async (sec) => { showView('study'); for (let i = 0; i < 60 && !window.lumenStudy?.openSettings; i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 500)); document.querySelector('.st-set-panel')?.replaceChildren(); window.lumenStudy.openSettings(sec);
  for (let i = 0; i < 60 && !document.querySelector('.st-set-panel .st-set-card'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 250)); }"""
OPEN_ACT = "async () => { await (" + OPEN_SET + ")('activity'); }"


def part1(browser, S):
    print("Parte 1 · troca de estilo com o servidor real isolado")
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    ctx.add_init_script(U.HOST)  # como dentro do Lumen.exe (moldura própria): chrome.webview registra as mensagens
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(S.url + "/?frame=1")
    page.wait_for_function("() => typeof showView === 'function' && typeof Glass === 'object'")
    H.settle(page, 700)
    check(page.evaluate("document.documentElement.dataset.ui") == "classic", "abre no Clássico quando nunca foi escolhido")
    check(page.evaluate("[...document.querySelectorAll('.g-only')].every(e => getComputedStyle(e).display === 'none')"),
          "no Clássico, nenhuma peça exclusiva do Glass aparece")
    original = page.evaluate("""() => ({ home: [...document.querySelector('.home-grid').children].map(e => e.id),
      lib: [...document.querySelector('#view-library').children].map(e => e.id || e.className),
      pomo: document.querySelector('#u-pomo').parentElement.className, pomoNext: document.querySelector('#u-pomo').nextElementSibling?.className || '' })""")
    set_before = page.evaluate(SET_ORDER)
    # a barra flutuante aberta ao mesmo tempo (outra janela): ela acompanha a troca pela leitura que já faz a cada segundo
    bar = ctx.new_page()
    bar.goto(S.url + "/widget")
    bar.wait_for_function("() => typeof state !== 'undefined' && state !== null")
    check(bar.evaluate("document.documentElement.dataset.ui") == "classic", "barra flutuante: abre marcada como Clássico")
    # algo digitado e o estado da página não podem se perder na troca
    page.evaluate("showView('library')")
    page.fill("#lib-search", "redes")
    page.evaluate("window.__semRecarregar = 42; goSettings('appearance')")
    H.settle(page, 400)
    page.click("label.ui-style-opt:has(input[value=glass])")
    page.wait_for_function("() => document.documentElement.dataset.ui === 'glass'")
    page.wait_for_timeout(300)
    check(page.evaluate("window.__semRecarregar") == 42, "troca para o Glass sem recarregar a página")
    check(page.input_value("#lib-search") == "redes", "o texto digitado na busca da Biblioteca continua")
    check(S.call("/api/state")["config"]["ui_style"] == "glass", "a escolha fica no config.json (ui_style = glass)")
    check("aplicado" in page.inner_text("#ui-style-state"), "a tela confirma a troca e diz como voltar")
    check(page.evaluate("!!document.querySelector('.g-pomo-lane #u-pomo') && document.querySelectorAll('.home-grid > .g-home-col').length === 2"),
          "Glass: Pomodoro no topo da área de trabalho e o Início em duas colunas")
    check(page.evaluate("getComputedStyle(document.querySelector('.g-winctl')).display") == "flex", "Glass: controles de janela do Windows à direita")
    check(page.evaluate("getComputedStyle(document.querySelector('.lights')).display") == "none", "Glass: os botões coloridos do Mac não aparecem")
    check(page.evaluate("document.querySelectorAll('#view-settings .set-panel > .g-sec-head').length >= 8 && document.querySelectorAll('#view-settings .g-group').length >= 8"),
          "Glass: cada painel de Ajustes ganha cabeçalho de seção e um cartão por grupo")
    shot(page, "1-ajustes-glass")
    try:
        bar.wait_for_function("() => document.documentElement.dataset.ui === 'glass'", timeout=6000)
    except Exception:
        pass
    check(bar.evaluate("document.documentElement.dataset.ui") == "glass", "barra flutuante: passa ao Glass sozinha, sem recarregar (a mesma leitura do tema)")
    for path in ("/widget", "/note"):
        html = S.call(path, raw=True)[1].decode()
        check('<html lang="pt-BR" data-ui="glass">' in html and "{{" not in html.split("</head>")[0].replace("{{TOKEN}}", ""), f"{path}: o HTML entregue já traz data-ui=\"glass\"")
    # reabrir: o servidor já entrega a página no Glass (sem piscar o Clássico)
    page.reload()
    page.wait_for_function("() => typeof showView === 'function' && typeof Glass === 'object'")
    first = page.evaluate("document.documentElement.getAttribute('data-ui')")
    check(first == "glass", "ao reabrir, a página já vem marcada como Glass pelo servidor")
    html = S.call("/", raw=True)[1].decode()
    check('data-ui="glass"' in html and "{{UI_STYLE}}" not in html, "o HTML entregue já traz data-ui=\"glass\"")
    # voltar ao Clássico: tudo no lugar e na ordem de antes
    page.evaluate("goSettings('appearance')")
    H.settle(page, 400)
    page.click("label.ui-style-opt:has(input[value=classic])")
    page.wait_for_function("() => document.documentElement.dataset.ui === 'classic'")
    page.wait_for_timeout(300)
    now = page.evaluate("""() => ({ home: [...document.querySelector('.home-grid').children].map(e => e.id),
      lib: [...document.querySelector('#view-library').children].map(e => e.id || e.className),
      pomo: document.querySelector('#u-pomo').parentElement.className, pomoNext: document.querySelector('#u-pomo').nextElementSibling?.className || '' })""")
    check(now == original, "de volta ao Clássico: Início, Biblioteca e Pomodoro na mesma ordem e lugar de antes")
    check(page.evaluate(SET_ORDER) == set_before, "de volta ao Clássico: cada painel de Ajustes com os mesmos elementos, na mesma ordem")
    check(not page.evaluate("!!document.querySelector('.g-pomo-lane, .g-home-col, .g-lib-body, #g-lib-stats, #view-settings .g-group, #view-settings .g-sec-head')"), "nenhum contêiner do Glass sobra no Clássico")
    check(S.call("/api/state")["config"]["ui_style"] == "classic", "a volta também fica salva")
    try:
        bar.wait_for_function("() => document.documentElement.dataset.ui === 'classic'", timeout=6000)
    except Exception:
        pass
    check(bar.evaluate("document.documentElement.dataset.ui") == "classic", "barra flutuante: volta ao Clássico junto com a janela principal")
    check(not errs, "sem erro de JavaScript na troca" + (f": {errs[:2]}" if errs else ""))
    ctx.close()


def part2(browser, url):
    print("Parte 2 · telas e funções no Glass (mundo simulado)")
    ctx, page, W, log, errs = mocked(browser, url)
    posted = lambda: page.evaluate("window.messages || []")
    # navegação pela barra lateral
    for v in ["new", "library", "study", "integrations", "home"]:
        page.click(f"#nav-{v}")
        page.wait_for_timeout(150)
        check(page.evaluate(f"!document.getElementById('view-{v}').hidden && document.getElementById('nav-{v}').getAttribute('aria-current') === 'page'"),
              f"barra lateral abre {v} e marca o item")
    check(page.evaluate("document.querySelector('#home-hero .hero-title').textContent") == "Comece uma nova aula", "Início: cartão “Comece uma nova aula”")
    check(page.evaluate("document.querySelector('#g-journey-steps [data-s=deepen]').dataset.on") == "now",
          "jornada: a aula pendente com compreensão escrita está em Aprofundar")
    check(page.evaluate("document.querySelectorAll('#pending-list .lib-row').length") == 3, "Continue de onde parou: as 3 aulas em andamento (nenhuma some no cartão principal)")
    check(page.evaluate("document.getElementById('sys-overall').textContent").strip() == "Tudo pronto", "Sistema: selo “Tudo pronto” contado das linhas reais")
    shot(page, "2-inicio")
    # ações rápidas
    page.click("[data-g-quick=organize]")
    page.wait_for_timeout(200)
    check(page.evaluate("!document.getElementById('view-library').hidden && document.querySelector('#lib-filter [data-f=inbox]').getAttribute('aria-pressed') === 'true'"),
          "Ação rápida “Organizar materiais” abre a Biblioteca em A organizar")
    page.click("#nav-home")
    page.click("[data-g-quick=search]")
    page.wait_for_timeout(200)
    check(page.evaluate("document.getElementById('palette').open"), "Ação rápida “Buscar conteúdo” abre a busca (Ctrl+K)")
    page.keyboard.press("Escape")
    # Nova aula: as três fontes reais
    page.click("#nav-new")
    for kind in ["file", "captures", "recording"]:
        page.click(f"[data-g-src={kind}]")
        page.wait_for_timeout(120)
        check(page.evaluate(f"document.getElementById('tab-{kind}').getAttribute('aria-selected') === 'true' && !document.getElementById('panel-{kind}').hidden && document.querySelector('[data-g-src={kind}]').getAttribute('aria-pressed') === 'true'"),
              f"Nova aula: o cartão “{kind}” seleciona a fonte de verdade")
    check(page.evaluate("getComputedStyle(document.querySelector('#rec-start .core')).backgroundImage.includes('240, 74, 79')"), "o botão de gravar continua vermelho coral")
    check(page.evaluate("getComputedStyle(document.querySelector('.recorder[data-state=idle] .rec-main .core')).animationName") == "none",
          "em repouso, o botão de gravar não pulsa")
    page.click("#rec-start")
    page.wait_for_function("() => document.getElementById('recorder').dataset.state === 'live'", timeout=5000)
    check(True, "gravar: o botão inicia a captura (estado ao vivo)")
    shot(page, "3-nova-aula-gravando")
    page.click("#rec-start")
    page.wait_for_function("() => document.getElementById('recorder').dataset.state !== 'live'", timeout=5000)
    check(any(p == "/api/record/stop" for _, p, _ in log), "gravar de novo: para a captura (mesma rota de sempre)")
    try:  # o botão habilita quando a resposta do "parar" chega e o estado é relido: espera por isso em vez de ler no mesmo instante
        page.wait_for_function("() => !document.getElementById('go').disabled", timeout=4000)
    except Exception:
        pass
    check(page.evaluate("document.getElementById('go').disabled") is False, "com a gravação pronta, “Continuar” habilita como antes")
    ctx.close()

    # recuperação: cancelar o descarte não apaga nada
    ctx, page, W, log, errs2 = mocked(browser, url, patch=U.patch(recording={"active": False, "seconds": 0, "recovered": {"seconds": 25}}))
    page.click("#nav-new")
    page.wait_for_timeout(300)
    check(page.is_visible("#rec-recover"), "recuperação: o aviso da gravação interrompida aparece")
    page.click("#rec-recover-drop")
    page.wait_for_selector("dialog[open]")
    check("apagada" in page.inner_text("dialog[open]"), "descartar pede confirmação (apagar é permanente)")
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    check(page.is_visible("#rec-recover") and not any(p == "/api/record/recover" for _, p, _ in log), "cancelar o descarte não apaga a gravação")
    shot(page, "4-recuperacao")
    ctx.close()

    # Pomodoro em cartão
    ctx, page, W, log, errs3 = mocked(browser, url)
    lane = ".g-pomo-lane"
    check(page.evaluate(f"document.querySelector('{lane} .pomo-total').textContent") == "/ 25:00", "Pomodoro: mostra o tempo total da etapa")
    page.click(f"{lane} .pomo-play")
    page.wait_for_timeout(200)
    check(any(p == "/api/pomodoro" and b.get("action") == "pause" for _, p, b in log), "Pomodoro: pausar usa a ação de sempre")
    page.click(f"{lane} .pomo-play")
    page.wait_for_timeout(200)
    check(any(p == "/api/pomodoro" and b.get("action") == "play" for _, p, b in log), "Pomodoro: retomar")
    page.click(f"{lane} .pomo-stop")
    page.wait_for_timeout(200)
    check(any(p == "/api/pomodoro" and b.get("action") == "reset" for _, p, b in log), "Pomodoro: Parar = reiniciar a etapa (a ação que já existia)")
    page.click(f"{lane} .pomo-expand")
    page.wait_for_timeout(250)
    check(page.is_visible(f"{lane} .pomo-sheet"), "Pomodoro: a seta abre o painel completo")
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    check(not page.is_visible(f"{lane} .pomo-sheet"), "Pomodoro: Esc fecha o painel")
    page.click("#nav-library")
    page.wait_for_timeout(200)
    check(page.is_visible(f"{lane} .pomo"), "Pomodoro continua visível ao trocar de tela")
    # Biblioteca: números e estrutura
    stats = page.evaluate("[...document.querySelectorAll('#g-lib-stats .g-stat strong')].map(e => e.textContent)")
    check(stats[:2] == ["6", "3"], f"Biblioteca: números contados das listas reais ({stats})")
    page.click("#g-lib-tree [data-course=c-ia]")
    page.wait_for_timeout(250)
    check(page.is_visible("#lib-crumbs") and "Inteligência Artificial" in page.inner_text("#lib-crumbs"), "Biblioteca: a estrutura abre o curso")
    page.click("#g-lib-stats [data-f=pending]")
    page.wait_for_timeout(200)
    check(page.evaluate("document.querySelector('#lib-filter [data-f=pending]').getAttribute('aria-pressed')") == "true", "Biblioteca: o número “Em andamento” filtra a lista")
    page.click("#g-lib-stats [data-f=all]")
    page.fill("#lib-search", "gradiente")
    page.wait_for_timeout(250)
    titles = page.evaluate("[...document.querySelectorAll('#library-list .lib-title')].map(e => e.textContent)")
    check(titles == ["Gradiente descendente na prática"], f"Biblioteca: a busca filtra a lista ({titles})")
    page.fill("#lib-search", "")
    shot(page, "5-biblioteca")
    # Integrações: mudar uma preferência geral vai ao servidor pela rota de sempre, e a escolha fica marcada
    page.click("#nav-integrations")
    page.wait_for_timeout(250)
    page.click("#dest-mode label:has(input[value=obsidian])")
    page.wait_for_timeout(400)
    check(any(p == "/api/settings" and b.get("destinations") == "obsidian" for _, p, b in log) and page.is_checked("#dest-mode input[value=obsidian]"),
          "Integrações: “Só Obsidian” é salvo pela rota de ajustes de sempre e fica marcado")
    page.click("#dest-mode label:has(input[value=both])")
    page.wait_for_timeout(300)
    # Integrações › Notion: Capas e Desconectar compactos (o flex-basis em coluna já virou ~300px de vazio) e “Criar capa” abre o fluxo comum
    hs = page.evaluate("[document.querySelector('#notion-cov-h').parentElement, document.querySelector('#notion-foot')].map(e => Math.round(e.getBoundingClientRect().height))")
    check(hs[0] < 200 and hs[1] < 120, f"Integrações › Notion: Capas e Desconectar sem vazio (alturas {hs})")
    page.focus("[data-cover-open]")
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    check(page.is_visible("#view-settings") and page.is_visible("#cov-box") and page.evaluate("!!document.activeElement.closest('#cov-box')"),
          "Integrações › Notion: “Criar capa” abre o fluxo comum (Ajustes › Capas) com o foco dentro dele")
    page.click("#nav-integrations")
    page.wait_for_timeout(250)
    # controles de janela (moldura própria do Lumen.exe): mandam as mesmas mensagens dos botões de antes
    page.click(".g-win[data-g-window=minimize]")
    page.click("#g-win-max")
    msgs = posted()
    check("window:minimize" in msgs and "window:maximize" in msgs, "controles de janela mandam window:minimize / window:maximize ao Lumen.exe")
    ctx.close()

    # sem nenhuma aula: a jornada não marca etapa nenhuma (nada inventado)
    ctx, page, W, log, errs4 = mocked(browser, url, patch=U.no_data)
    check(page.evaluate("[...document.querySelectorAll('#g-journey-steps li')].every(li => !li.dataset.on)"), "sem aula em andamento, a jornada fica neutra")
    check("Nenhuma aula em andamento" in page.inner_text("#g-journey"), "e diz que não há aula em andamento")
    ctx.close()

    # gravando: o cartão principal é a gravação (não “Comece uma nova aula”)
    ctx, page, W, log, errs5 = mocked(browser, url, patch=U.patch(recording=U.REC))
    check("Gravando agora" in page.inner_text("#home-hero"), "gravando: o Início mostra a gravação no cartão principal")
    check(page.evaluate("document.querySelector('#g-journey-steps [data-s=capture]').dataset.on") == "now", "gravando: a jornada está em Capturar")
    ctx.close()

    # Nova aula › Salvar: o resultado em cartões por destino (R05), com os mesmos fatos e as mesmas ações do Clássico
    ctx, page, W, log, errs6 = mocked(browser, url)
    page.evaluate(RUN, DONE_VIS)
    page.wait_for_timeout(500)
    check(page.is_visible("#result .g-result") and page.evaluate("[...document.querySelectorAll('#result > :not(.g-result)')].every(e => getComputedStyle(e).display === 'none')"),
          "resultado: os cartões do Glass aparecem e as linhas do Clássico ficam ocultas (sem texto repetido)")
    check(page.inner_text("#run-h") == "Material processado com sucesso" and page.is_visible("#g-run-sub") and not page.is_visible("#stages"),
          "resultado: título “Material processado com sucesso”, subtítulo, e as etapas concluídas saem de cena")
    nt, ob = page.inner_text(".g-dest:has([data-dest=notion])"), page.inner_text(".g-dest:has([data-dest=obsidian])")
    check("Salvo" in nt and "Complexidade de algoritmos" in nt and "Estudos › Inteligência Artificial" in nt and "Minha compreensão" in nt,
          "resultado: cartão do Notion com o título, a organização e a subpágina reais")
    check("Salvo" in ob and all(t in ob for t in ("Nota criada", "Mapa conceitual", "Painel visual (8 imagens)", "4 conexões com o cofre", "12 perguntas de revisão")),
          "resultado: cartão do Obsidian lista o que o Clássico diz numa linha (nota, mapa, painel, conexões, perguntas)")
    vis = page.inner_text(".g-vis")
    check("Imagem estática (PNG)" in vis and "3 componentes" in vis and page.evaluate("document.querySelector('.g-vis img').alt.startsWith('Visualização 3D gerada pelo Lumen')"),
          "resultado: a visualização 3D com o tipo, a descrição e o texto alternativo de sempre")
    check(page.evaluate("document.activeElement?.closest('.g-dest') && document.getElementById('content').scrollTop === 0"),
          "resultado: o foco fica na ação do primeiro destino e o título continua à vista (sem rolar para o rodapé)")
    rows = page.evaluate("""() => { const top = (t) => [...new Set([...document.querySelectorAll(`#run-actions [data-tier="${t}"]`)].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().top)))];
        return [top(1), top(2)]; }""")
    check(len(rows[0]) == 1 and len(rows[1]) == 1 and rows[0][0] < rows[1][0], f"resultado: ações em duas fileiras, destinos em cima ({rows})")
    check("null" not in page.inner_text("#run"), "resultado: nenhum “null” na tela")
    page.click(".g-dest:has([data-dest=obsidian]) > .btn")
    page.wait_for_timeout(300)
    check(any(p == "/api/open" and b.get("key") == "k2" and b.get("what") == "note" for _, p, b in log), "resultado: “Abrir no Obsidian” do cartão usa a rota de sempre (/api/open)")
    # de volta ao Clássico sem recarregar: as linhas de antes, o título de antes, nenhum cartão do Glass à vista
    page.evaluate("Glass.apply('classic')")
    check(not page.is_visible("#result .g-result") and page.is_visible("#result .dest-line") and page.is_visible("#stages") and page.inner_text("#run-h") == "Material salvo"
          and not page.is_visible("#g-run-sub"), "resultado no Clássico: linhas, etapas e título “Material salvo” como antes; nenhum cartão do Glass")
    page.evaluate("Glass.apply('glass')")
    # um destino falhou: o cartão dele diz o erro e traz o “tentar de novo” (a mesma rota); o destino salvo não se repete no rodapé
    page.evaluate(RUN, DONE_NT_FAIL)
    page.wait_for_timeout(400)
    nt = page.inner_text(".g-dest:has([data-dest=notion])")
    check("Pendente" in nt and "não respondeu" in nt and page.inner_text("#run-h") == "Material salvo, com uma pendência" and not page.is_visible("#g-run-sub"),
          "falha num destino: o cartão mostra “Pendente” e o erro; o título não diz sucesso")
    check(page.evaluate("[...document.querySelectorAll('#run-actions [data-tier=retry], #run-actions [data-tier=\"1\"]')].every(e => !e.offsetParent)"),
          "falha num destino: o rodapé não repete o “tentar de novo” nem o único destino aberto (estão nos cartões)")
    page.click(".g-dest:has([data-dest=notion]) > .btn")
    page.wait_for_timeout(400)
    check(any(p == "/api/deliver" and b.get("only") == ["notion"] and b.get("key") == "k2" for _, p, b in log), "falha num destino: “Tentar de novo só o Notion” usa /api/deliver só com o Notion")
    ctx.close()
    # Ajustes › Capas do Notion (R27): a trilha dos três passos espelha o estado do fluxo (página escolhida, prévia gerada)
    ctx, page, W, log, errs8 = mocked(browser, url)
    NOW = "() => [...document.querySelectorAll('.g-cov-steps li')].map(li => getComputedStyle(li).fontWeight >= 600 ? 'agora' : getComputedStyle(li.querySelector('span')).fontSize === '0px' ? 'feito' : 'depois')"
    page.evaluate("async () => { await covOpen(); }")
    page.wait_for_timeout(400)
    check(page.evaluate(NOW) == ["agora", "depois", "depois"] and page.is_visible(".g-cov-how") and page.is_visible(".g-cov-head"),
          "Capas: sem página escolhida, a trilha está no passo 1 e o “Como funciona” aparece")
    check(page.evaluate("document.querySelector('#cov-q').labels[0]?.textContent.includes('Qual página?') && document.querySelector('.g-cov-steps').getAttribute('aria-hidden') === 'true'"),
          "Capas: o campo continua se chamando “Qual página?” para o leitor de tela; a trilha é só visual")
    page.evaluate("async () => { await covPickRef('pg-orc'); }")
    page.wait_for_timeout(300)
    check(page.evaluate(NOW) == ["feito", "agora", "depois"], "Capas: com a página escolhida, o passo 1 fica concluído e o 2 vira o atual")
    page.evaluate("async () => { await covGen(); }")
    page.wait_for_timeout(400)
    check(page.evaluate(NOW) == ["feito", "feito", "agora"] and page.inner_text("#cov-main") == "Aplicar capa", "Capas: com a prévia pronta, a trilha chega em “Aplicar no Notion” e o botão é “Aplicar capa”")
    page.evaluate("Glass.apply('classic')")
    check(page.evaluate("[...document.querySelectorAll('.cov-panel :is(.g-cov-steps, .g-cov-how, .g-cov-head)')].every(e => getComputedStyle(e).display === 'none') && getComputedStyle(document.querySelector('.cov-panel > .field-hint')).display !== 'none'"),
          "Capas no Clássico: sem trilha nem “Como funciona”; a frase de sempre volta")
    page.evaluate("Glass.apply('glass')")
    # Diagnóstico (R33): o ladrilho do cabeçalho entra e sai com o estilo; o botão continua sendo o mesmo
    page.evaluate("goSettings('diagnostics')")
    page.wait_for_timeout(300)
    check(page.evaluate("document.querySelectorAll('.diag-header > .g-sec-ico').length") == 1 and page.is_visible("#diag-run-btn"), "Diagnóstico: cabeçalho com o ladrilho e o botão de verificar")
    page.evaluate("Glass.apply('classic')")
    check(page.evaluate("document.querySelectorAll('.diag-header > .g-sec-ico').length") == 0, "Diagnóstico no Clássico: o ladrilho sai")
    page.evaluate("Glass.apply('glass')")
    check(page.evaluate("document.querySelectorAll('.diag-header > .g-sec-ico').length") == 1, "Diagnóstico: de volta ao Glass, um ladrilho só (não duplica)")
    ctx.close()
    errs5 = errs5 + errs8
    # Configurações da IA › Atividades (R23): a tabela vira linha do tempo por dia, com os MESMOS registros; o Clássico continua com a tabela
    ctx, page, W, log, errs9 = mocked(browser, url)
    rows = act_rows()
    calls = fake_activity(ctx, rows)
    page.evaluate(OPEN_ACT)
    TL = "() => ({ items: document.querySelectorAll('.g-tl-item').length, days: document.querySelectorAll('.g-tl-date').length, more: !!document.querySelector('.g-tl-load'), " \
         "table: getComputedStyle(document.querySelector('.st-set-card > .st-table')).display, tl: getComputedStyle(document.querySelector('.g-tl')).display, " \
         "blocks: document.querySelectorAll('.g-tl').length, trs: document.querySelectorAll('.st-activity tbody tr').length })"
    t = page.evaluate(TL)
    check(t["items"] == 30 and t["days"] >= 3 and t["more"] and t["table"] == "none" and t["tl"] != "none" and t["trs"] == 47,
          f"Atividades: linha do tempo no lugar da tabela, 30 registros no primeiro lote, agrupados por dia ({t['days']} dias), com “Carregar mais atividades”")
    check(page.evaluate("document.querySelector('.g-tl-date').textContent.startsWith('Hoje · ') && /^às \\d\\d:\\d\\d$/.test(document.querySelector('.g-tl-what small').textContent)"),
          "Atividades: o dia fica na pílula (“Hoje · …”) e a hora em cada registro")
    tones = page.evaluate("() => [...document.querySelectorAll('.g-tl-card')].slice(0, 7).map(c => [c.querySelector('.badge').dataset.tone || '', c.querySelector('.badge').textContent.trim()])")
    check([x[0] for x in tones] == ["ok", "error", "ok", "error", "accent", "warn", ""] and tones[0][1] == "Concluído" and tones[6][1] == "1240 ms",
          f"Atividades: o selo vem do resultado real (ok → Concluído; erro, espera e cancelamento com tom; o resto neutro) → {tones}")
    page.focus(".g-tl-card > summary")
    page.keyboard.press("Enter")
    check(page.evaluate("() => { const c = document.querySelector('.g-tl-card'); return c.open && [...c.querySelectorAll('dt')].map(d => d.textContent).join() === 'Quando,Alvo,Resultado,Detalhe,Permissão,Provedor' && c.querySelector('.g-tl-more').getBoundingClientRect().height > 60; }"),
          "Atividades: Enter no registro abre o detalhe (quando, alvo, resultado, detalhe, permissão, provedor)")
    shot(page, "9-atividades")
    before = len(calls)
    page.click(".g-tl-load")
    t = page.evaluate(TL)
    check(t["items"] == 47 and not t["more"] and page.evaluate("document.activeElement === document.querySelectorAll('.g-tl-card > summary')[30]"),
          "Atividades: “Carregar mais” mostra os 47 sem nova chamada, o botão some e o foco vai para o primeiro registro novo")
    check(before >= 1 and len(calls) == before and page.evaluate(
          "() => { const a = [...document.querySelectorAll('.g-tl-what strong')].map(e => e.textContent), b = [...document.querySelectorAll('.st-activity tbody tr')].map(r => r.cells[1].textContent); return a.length === 47 && a.join('|') === b.join('|'); }"),
          "Atividades: os registros da linha do tempo são os mesmos da tabela, na mesma ordem")
    check(page.evaluate("() => { const b = [...document.querySelectorAll('.g-tl-fact b')].find(e => e.textContent.includes('nome bem comprido')); return !!b && b.scrollWidth > b.clientWidth && b.getBoundingClientRect().right <= b.closest('summary').getBoundingClientRect().right; }")
          and page.evaluate("() => { const c = document.getElementById('content'); return c.scrollWidth <= c.clientWidth + 1; }"),
          "Atividades: alvo comprido é cortado com reticências dentro do cartão (por inteiro no detalhe), sem rolagem horizontal")
    page.evaluate("Glass.apply('classic')")
    t = page.evaluate(TL)
    check(t["tl"] == "none" and t["table"] != "none" and page.is_visible(".st-activity"), "Atividades no Clássico: a tabela de sempre; a linha do tempo não aparece")
    page.evaluate("Glass.apply('glass')")
    t = page.evaluate(TL)
    check(t["blocks"] == 1 and t["items"] == 47 and t["table"] == "none", "Atividades: de volta ao Glass, a mesma linha do tempo (não duplica)")
    ctx.close()
    # sem registros (servidor isolado de verdade): nenhuma linha do tempo, a frase de sempre
    ctx, page, W, log, errs10 = mocked(browser, url)
    page.evaluate(OPEN_ACT)
    check(page.evaluate("!document.querySelector('.g-tl') && document.querySelector('.st-set-card > .faint')?.textContent === 'Nada registrado ainda.'"),
          "Atividades sem registros: “Nada registrado ainda.”, sem linha do tempo")
    # Avaliação local (R15), vazia: contador 0, estado vazio, trilha de três passos; as explicações e os botões são os de sempre
    page.evaluate(OPEN_SET, "evaluation")
    EV = "() => { const c = document.querySelector('.st-set-card'), vis = (s) => { const e = c.querySelector(s); return !!e && getComputedStyle(e).display !== 'none'; }; return { " \
         "count: c.querySelector('.g-ev-count')?.textContent, empty: vis('.g-ev-empty'), steps: [...c.querySelectorAll('.g-ev-trail li strong')].map(e => e.textContent).join(), " \
         "line: vis(':scope > p:not([class])'), details: c.querySelectorAll(':scope > details').length, list: vis(':scope > .st-list'), back: c.querySelectorAll('.g-ev-back').length, " \
         "text: c.innerText }; }"
    e = page.evaluate(EV)
    check(e["count"] == "0casos registrados" and e["empty"] and e["steps"] == "Avaliar,Registrar,Comparar" and not e["line"] and e["details"] == 2 and e["back"] == 1,
          "Avaliação vazia: contador “0 casos registrados”, estado vazio e a trilha Avaliar → Registrar → Comparar")
    check("false" not in e["text"] and "null" not in e["text"] and "undefined" not in e["text"] and "acompanham a exportação" in e["text"],
          "Avaliação: nenhum texto solto (“false”, “null”) e a frase das fontes continua na tela")
    page.focus(".st-set-card > details > summary")
    page.keyboard.press("Enter")
    check(page.evaluate("document.querySelector('.st-set-card > details').open && document.querySelector('.st-set-card > details > p').getBoundingClientRect().height > 20"),
          "Avaliação: Enter abre “O que o Automático aprendeu com suas escolhas”")
    with page.expect_download() as dl:
        page.click(".st-set-card > .btn.primary")
    check(dl.value.suggested_filename == "lumen-avaliacao.json", "Avaliação: “Exportar conjunto de avaliação” baixa o mesmo arquivo de sempre")
    page.evaluate("Glass.apply('classic')")
    e = page.evaluate(EV)
    check(e["line"] and not e["empty"] and page.evaluate("[...document.querySelectorAll('.st-set-card :is(.g-ev-back, .g-ev-count, .g-ev-trail, .g-ev-note, summary > .i)')].every(x => getComputedStyle(x).display === 'none')")
          and page.evaluate("getComputedStyle(document.querySelector('.st-set-card')).gridTemplateColumns.split(' ').length") == 1,
          "Avaliação no Clássico: a frase “0 caso(s)…” de sempre, sem contador, trilha nem ícones nas explicações")
    page.evaluate("Glass.apply('glass')")
    page.click(".st-set-card > .btn.ghost")
    page.wait_for_timeout(700)
    check(page.evaluate("document.querySelector('.st-set-nav [aria-current=true]')?.textContent.trim()") == "Seus dados no Lúmen", "Avaliação: “Gerenciar estes dados” leva a “Seus dados no Lúmen”")
    ctx.close()
    # com casos: o contador acompanha e a lista toma o lugar do estado vazio
    ctx, page, W, log, errs11 = mocked(browser, url)
    ctx.route("**/api/study/evaluation**", lambda r: r.fulfill(json={"format": "lumen-study-eval-1", "exported": "2026-11-12T12:00:00+00:00", "routing": [], "scope": "", "cases": [
        {"id": 1, "question": "Qual a diferença entre a fase clara e a fase escura?", "reference": "A fase clara produz ATP e NADPH.", "rating": 1, "correction": "", "mode": "find", "sources": []}]}))
    page.evaluate(OPEN_SET, "evaluation")
    e = page.evaluate(EV)
    check(e["count"] == "1caso registrado" and not e["empty"] and e["list"] and "Boa · Qual a diferença" in e["text"], "Avaliação com um caso: “1 caso registrado” e a lista de casos no lugar do estado vazio")
    # PDFs e imagens (R21) e Personalização (R26): um cartão do Clássico desenhado em vários, com os mesmos controles e textos
    page.evaluate(OPEN_SET, "pdf")
    SP = "() => { const c = document.querySelector('.st-set-card'), box = (e) => e.getBoundingClientRect(), backs = [...c.querySelectorAll(':scope > .g-sp-back')].map(box); " \
         "const inside = (e) => { const r = box(e); return backs.findIndex(b => r.top >= b.top - 1 && r.bottom <= b.bottom + 1 && r.left >= b.left - 1 && r.right <= b.right + 1); }; return { " \
         "backs: backs.length, heads: [...c.querySelectorAll(':scope > .g-sp-head strong')].map(e => e.textContent), headIn: [...c.querySelectorAll(':scope > .g-sp-head')].map(inside), " \
         "rows: [...c.querySelectorAll(':scope > .set-row')].map(inside), fields: [...c.querySelectorAll(':scope > .field')].map(inside), " \
         "gaps: backs.slice(1).map((b, i) => Math.round(b.top - backs[i].bottom)), h3: box(c.querySelector(':scope > h3')).width, text: c.innerText }; }"
    s = page.evaluate(SP)
    check(s["backs"] == 4 and s["heads"] == ["Documentos PDF", "Imagens dos materiais", "Comandos rápidos", "Tipos, proporções e armazenamento"] and s["headIn"] == [0, 1, 2, 3]
          and s["rows"] == [0, 1] and all(g == 16 for g in s["gaps"]) and s["h3"] <= 1,
          f"PDFs: quatro cartões (documentos, imagens, comandos, tipos), cada interruptor no cartão dele, 16 px entre cartões → {s['rows']} {s['gaps']}")
    check(all(t in s["text"] for t in ("/pdf [tipo] [assunto]", "/imagem [proporção] [descrição]", "/mapa-mental", "apostila, revisao, cornell", "quadrada, paisagem, retrato e capa", "são apagados com a conversa"))
          and page.evaluate("document.querySelector('.st-set-card > h3').textContent.trim() === 'PDFs e imagens' && [...document.querySelectorAll('.st-set-card > .muted')].every(p => getComputedStyle(p).display === 'none')"),
          "PDFs: comandos, tipos, proporções e armazenamento com os mesmos valores do Clássico; o título do cartão continua para o leitor de tela")
    was = page.evaluate("document.querySelector('.st-set-card [role=switch]').checked")
    page.click(".st-set-card .set-row .st-switch")
    page.wait_for_timeout(500)
    check(page.evaluate("document.querySelector('.st-set-card [role=switch]').checked") != was, "PDFs: o interruptor “PDF com fundo escuro” continua gravando")
    page.click(".st-set-card .set-row .st-switch")
    page.wait_for_timeout(400)
    page.evaluate("Glass.apply('classic')")
    check(page.evaluate("[...document.querySelectorAll('.st-set-card :is(.g-sp-back, .g-sp-head, .g-sp-cmds, .g-sp-facts)')].every(e => getComputedStyle(e).display === 'none') && "
                        "[...document.querySelectorAll('.st-set-card > .muted')].every(p => getComputedStyle(p).display !== 'none') && document.querySelector('.st-set-card > h3').getBoundingClientRect().width > 100"),
          "PDFs no Clássico: um cartão só, com o título e as três frases de sempre")
    page.evaluate("Glass.apply('glass')")
    page.evaluate(OPEN_SET, "personal")
    s = page.evaluate(SP)
    check(s["backs"] == 3 and s["heads"] == ["Instruções personalizadas", "Estilo das respostas", "Preferências de estudo"] and s["headIn"] == [0, 1, 2]
          and s["fields"] == [0, 2] and s["rows"] == [1, 1, 1, 1] and all(g == 16 for g in s["gaps"]),
          f"Personalização: três cartões (instruções, estilo, preferências), com cada campo no cartão dele → {s['fields']} {s['rows']}")
    page.get_by_label("Instruções personalizadas").fill("Explique com analogias.")
    page.get_by_label("Instruções personalizadas").blur()
    page.wait_for_timeout(500)
    page.evaluate(OPEN_SET, "personal")
    check(page.get_by_label("Instruções personalizadas").input_value() == "Explique com analogias." and page.get_by_label("Preferências de estudo").is_visible()
          and "continuam valendo sempre" in page.inner_text(".st-set-card"),
          "Personalização: os campos continuam com o nome de sempre (rótulo acessível), gravam ao sair e a regra das fontes segue visível")
    page.get_by_label("Instruções personalizadas").fill("")
    page.get_by_label("Instruções personalizadas").blur()
    page.wait_for_timeout(400)
    # Catálogo (R11): skills em linhas com ladrilho; o estado escrito acompanha o interruptor de verdade
    page.evaluate(OPEN_SET, "catalog")
    c = page.evaluate("() => { const a = [...document.querySelectorAll('.st-catalog-skill')]; return { n: a.length, tiles: a.filter(x => x.querySelector(':scope > .g-tile-ico')).length, "
                      "state: a.slice(0, 3).map(x => [getComputedStyle(x.querySelector('.st-switch'), '::before').content, x.querySelector('[role=switch]').checked]), "
                      "sum: getComputedStyle(document.querySelector('.st-set-card > details > summary'), '::after').borderRightWidth, test: a[0].querySelector('.btn.ghost').textContent.trim() }; }")
    check(c["n"] >= 5 and c["tiles"] == c["n"] and all((s == '"Ativa"') == on for s, on in c["state"]) and c["sum"] != "0px" and c["test"].startswith("Testar /"),
          f"Catálogo: {c['n']} skills em linhas com ladrilho, “Ativa/Inativa” igual ao interruptor e as explicações em linhas com seta")
    ctx.close()
    errs5 = errs5 + errs9 + errs10 + errs11
    # Clássico, resultado sem visualização: nada de “null” (defeito antigo corrigido nesta etapa)
    set_style(url, "classic")
    ctx, page, W, log, errs7 = mocked(browser, url, style="classic")
    page.evaluate(RUN, U.DONE)
    page.wait_for_timeout(300)
    check("null" not in page.inner_text("#run") and page.is_visible("#result .dest-line"), "Clássico: resultado sem visualização não mostra “null”")
    ctx.close()
    set_style(url, "glass")
    errs5 = errs5 + errs6 + errs7
    all_errs = [e for e in errs + errs2 + errs3 + errs4 + errs5 if "favicon" not in e]
    check(not all_errs, "sem erro de JavaScript nas telas" + (f": {all_errs[:2]}" if all_errs else ""))


def part3(browser, url):
    print("Parte 3 · disposição nos tamanhos de janela pedidos")
    for size in [(1100, 870), (1280, 800), (1366, 768), (1600, 1000), (1920, 1080), (760, 860), (520, 560)]:
        ctx, page, W, log, errs = mocked(browser, url, size=size)
        found = []
        for v in ["home", "new", "library", "study", "integrations", "settings"]:
            page.evaluate(f"(v) => v === 'settings' ? goSettings('appearance') : showView(v)", v)
            if v == "study":
                try:
                    page.wait_for_function("() => /Todos os projetos/.test(document.body.innerText)", timeout=6000)
                except Exception:
                    pass
            page.wait_for_timeout(250)
            found += [f"{v}: {p}" for p in page.evaluate(U.CHECKS, 1)]
            # o Pomodoro nunca cobre o título nem os controles do cabeçalho
            over = page.evaluate("""() => { const p = document.querySelector('.g-pomo-lane .pomo')?.getBoundingClientRect(); if (!p || !p.width) return [];
              const view = [...document.querySelectorAll('.view')].find(x => !x.hidden);
              return [...view.querySelectorAll('h1, .page-head .lead, .stepper li, .st-tabs, .st-head-tools, .g-lib-stats > *')].filter(e => {
                const r = e.getBoundingClientRect(); return r.width && r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top; }).map(e => e.tagName + '.' + e.className); }""")
            found += [f"{v}: Pomodoro sobre {o}" for o in over]
            # cada controle-chave que está inteiro na janela recebe o clique (nada por cima dele): o centro é ele mesmo
            blocked = page.evaluate("""() => { const sel = '.rail-item, .g-win, .g-pomo-lane button, .st-tabs [role=tab], .st-head-tools button, .g-src-opt, ' +
                '#rec-start, .lib-view, .g-stat, #g-lib-tree button, .g-tile, #home-hero .btn, .integ-tab, .settings-nav button, #go';
              const out = [];
              for (const e of document.querySelectorAll(sel)) {
                const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                if (!r.width || s.visibility === 'hidden' || e.closest('[hidden]') || r.left < 0 || r.top < 0 || r.right > innerWidth || r.bottom > innerHeight) continue;
                const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                if (hit && !e.contains(hit) && !hit.closest('.action-bar') && !hit.closest('.st-dock')) out.push((e.id || e.className || e.tagName) + ' coberto por ' + (hit.id || hit.className?.baseVal || hit.className || hit.tagName));
              }
              return out; }""")
            found += [f"{v}: {b}" for b in blocked]
        # Ajustes › Capas, Proteção e Diagnóstico (R27, R30, R33): cabem em cada tamanho e o título não fica sob o Pomodoro
        for cat, sel in (("covers", ".cov-panel .g-sec-head h2"), ("protection", ".protection-panel > h2"), ("diagnostics", ".diag-title-area")):
            page.evaluate("(c) => goSettings(c)", cat)
            page.wait_for_timeout(450)
            found += [f"ajustes/{cat}: {p}" for p in page.evaluate(U.CHECKS, 1)]
            under = page.evaluate("""(sel) => { const p = document.querySelector('.g-pomo-lane .pomo')?.getBoundingClientRect(), e = document.querySelector(sel);
              if (!p || !p.width || !e) return e ? '' : 'sem ' + sel;
              const rg = document.createRange(); rg.selectNodeContents(e);
              return [...rg.getClientRects()].some(r => r.width && r.left < p.right && r.right > p.left && r.top < p.bottom && r.bottom > p.top) ? 'título sob o Pomodoro' : ''; }""", sel)
            if under:
                found.append(f"ajustes/{cat}: {under}")
        # o resultado em cartões (R05) também cabe: sem rolagem horizontal, texto cortado nem botão para fora do cartão
        page.evaluate(RUN, DONE_VIS)
        page.wait_for_timeout(450)
        found += [f"resultado: {p}" for p in page.evaluate(U.CHECKS, 1)]
        found += [f"resultado: {p}" for p in page.evaluate("""() => { const card = document.getElementById('run').getBoundingClientRect(), out = [];
            for (const e of document.querySelectorAll('#run .g-dest, #run .g-vis, #run-actions .btn')) { const r = e.getBoundingClientRect();
              if (r.width && (r.left < card.left - 1 || r.right > card.right + 1)) out.push((e.className || e.tagName) + ' para fora do cartão'); }
            return out; }""")]
        # Atividades em linha do tempo (R23), com registros: cabe em cada tamanho e nada sai do cartão
        fake_activity(ctx, act_rows(12))
        page.evaluate(OPEN_ACT)
        found += [f"atividades: {p}" for p in page.evaluate(U.CHECKS, 1)]
        found += [f"atividades: {p}" for p in page.evaluate("""() => { const out = [], n = document.querySelectorAll('.g-tl-item').length; if (n !== 12) out.push('linha do tempo com ' + n + ' registros');
            for (const s of document.querySelectorAll('.g-tl-card > summary')) { const c = s.getBoundingClientRect();
              for (const e of s.children) { const r = e.getBoundingClientRect(); if (r.width && (r.left < c.left - 1 || r.right > c.right + 1)) out.push((e.className.baseVal ?? e.className) + ' para fora do registro'); } }
            return [...new Set(out)]; }""")]
        # Avaliação (R15): contador, estado vazio, trilha e botões cabem; nada sai da largura do painel
        page.evaluate(OPEN_SET, "evaluation")
        found += [f"avaliação: {p}" for p in page.evaluate(U.CHECKS, 1)]
        found += [f"avaliação: {p}" for p in page.evaluate("""() => { const c = document.querySelector('.st-set-card').getBoundingClientRect(), out = [];
            for (const e of document.querySelectorAll('.st-set-card > *, .g-ev-trail li')) { const r = e.getBoundingClientRect();
              if (r.width && (r.left < c.left - 1 || r.right > c.right + 1)) out.push((e.className || e.tagName) + ' para fora do painel'); }
            const n = document.querySelector('.g-ev-count')?.getBoundingClientRect(), h = document.querySelector('.st-set-card > h3')?.getBoundingClientRect();
            if (n && h && n.left < h.right && n.right > h.left && n.top < h.bottom && n.bottom > h.top) out.push('contador sobre o título');
            return out; }""")]
        # PDFs, Personalização (cartões divididos) e Catálogo: cabem e nada sai do cartão
        for sec in ("pdf", "personal", "catalog"):
            page.evaluate(OPEN_SET, sec)
            found += [f"{sec}: {p}" for p in page.evaluate(U.CHECKS, 1)]
            found += [f"{sec}: {p}" for p in page.evaluate("""() => { const out = [];
                for (const c of document.querySelectorAll('.st-set-card')) { const b = c.getBoundingClientRect();
                  for (const e of c.querySelectorAll(':scope > *, .g-sp-cmds li, .g-sp-cmds code, .st-catalog-skill > *')) { const r = e.getBoundingClientRect();
                    if (r.width > 2 && (r.left < b.left - 1 || r.right > b.right + 1)) out.push((e.className || e.tagName) + ' para fora do cartão'); } }
                return [...new Set(out)]; }""")]
        check(not found, f"{size[0]}×{size[1]}: sem rolagem horizontal, corte, sobreposição ou controle coberto" + (f" → {found[:4]}" if found else ""))
        if SHOTS:
            page.evaluate("showView('home')")
            shot(page, f"6-inicio-{size[0]}x{size[1]}")
        ctx.close()
    # redimensionamento contínuo: de 1920 a 520 px (e de volta), em cada tela, sem rolagem horizontal nem erro de página
    ctx, page, W, log, errs = mocked(browser, url, size=(1920, 1000))
    wide = []
    for v in ["home", "new", "library", "study", "integrations"]:
        page.evaluate("(v) => showView(v)", v)
        page.wait_for_timeout(200)
        for w in list(range(1920, 519, -40)) + list(range(560, 1921, 120)):
            page.set_viewport_size({"width": w, "height": 900})
            over = page.evaluate("() => { const c = document.getElementById('content'); return [document.scrollingElement, c].some(e => e.scrollWidth > e.clientWidth + 1); }")
            if over:
                wide.append(f"{v}@{w}")
    check(not wide and not errs, "redimensionamento contínuo 1920 → 520 → 1920 px nas cinco telas: sem rolagem horizontal nem erro" + (f" → {wide[:6]} {errs[:2]}" if wide or errs else ""))
    ctx.close()


def part4(browser, url):
    print("Parte 4 · barra flutuante no Glass (mundo simulado, tamanho real 304 × 252)")
    TILE = """() => [...document.querySelectorAll('.prefs-menu button')].map(b => { const s = getComputedStyle(b), t = b.querySelector('span');
        return { name: t.textContent, border: parseFloat(s.borderTopWidth), cut: t.scrollWidth > t.clientWidth + 1 || b.scrollWidth > b.clientWidth + 1,
                 inside: b.getBoundingClientRect().bottom <= document.querySelector('.prefs-content').getBoundingClientRect().bottom + 1 }; })"""
    res = {}
    for style in ("glass", "classic"):
        set_style(url, style)
        h = U.Harness(browser, url, OUT)
        ctx, page, W, log, errs = h.open("widget", 304, 252, patch=lambda Wd, st=style: Wd["config"].update(ui_style=st))
        page.evaluate("""async () => { document.body.dataset.expanded = "true"; hostListeners.forEach(f => f({ data: "edge:top" })); await openPreferences(); }""")
        page.wait_for_timeout(350)
        res[style] = (page.evaluate("document.documentElement.dataset.ui"), page.evaluate(TILE))
        if style == "glass":
            shot(page, "7-barra-ajustes")
            page.click(".prefs-menu button:has-text('Barra flutuante')")
            page.wait_for_timeout(300)
            check("Posição na tela" in page.inner_text("#preferences"), "barra no Glass: o ladrilho abre a categoria como antes")
        ctx.close()
    ui, tiles = res["glass"]
    check(ui == "glass" and len(tiles) == 7 and all(t["border"] >= 1 for t in tiles), "barra no Glass: as 7 categorias dos Ajustes viram ladrilhos (R35)")
    check(not [t["name"] for t in tiles if t["cut"]] and all(t["inside"] for t in tiles),
          "barra no Glass: nenhum nome cortado e os 7 ladrilhos cabem sem rolar" + (f" → {[t['name'] for t in tiles if t['cut']]}" if any(t["cut"] for t in tiles) else ""))
    ui, tiles = res["classic"]
    check(ui == "classic" and all(t["border"] == 0 for t in tiles), "barra no Clássico: o menu continua sem ladrilhos, como antes")
    set_style(url, "glass")


SAVED = [{"id": i, "kind": k, "title": t, "updated": f"2026-11-{i:02d}T18:30:00+00:00"} for i, (k, t) in enumerate([
    ("map", "Mapa de conhecimento · redes convolucionais"), ("flashcards", "Flashcards · fotossíntese"), ("plan", "Plano de estudos · semana de provas"),
    ("mindmap", "Mapa mental · " + "complexidade de algoritmos e a notação O, do pior caso ao caso médio " * 3)], 1)]
MONITOR = {"cpu": {"name": "CPU de teste", "cores_label": "6C / 12T", "ghz": 2.6, "system_pct": 27, "app_pct": 6.5},
           "ram": {"total_gb": 15.8, "used_gb": 9.4, "system_pct": 60, "app_mb": 322, "app_pct": 2},
           "gpu": {"name": "GPU de teste", "gpu_pct": 17, "temp_c": 38, "vram_total_mb": 12288, "vram_used_mb": 2662, "vram_pct": 21.7, "models": [{"name": "modelo-de-teste"}]},
           "engines": [{"name": "Transcrição", "tech": "Parakeet · CUDA (GPU)", "active": True}, {"name": "Raciocínio IA", "tech": "Ollama · GPU", "active": True},
                       {"name": "Filtro de Voz", "tech": "DeepFilterNet · GPU", "active": True}, {"name": "Proteção", "tech": "restic · Criptografia local", "active": False}]}


def part5(browser, url):
    print("Parte 5 · Análise (R02), Salvos (R08), Monitor (R25) e menu de modo (R36) no Glass (mundo simulado)")
    BOX = """(s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(), c = getComputedStyle(e);
        return { w: r.width, top: r.top, bottom: r.bottom, left: r.left, right: r.right, border: parseFloat(c.borderTopWidth), align: c.textAlign,
                 scrolls: e.scrollHeight > e.clientHeight + 1 }; }"""
    CLIPPED = "(s) => [...document.querySelectorAll(s)].filter(e => e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1).length"
    got = {}
    for style in ("glass", "classic"):
        ctx, page, W, log, errs = mocked(browser, url, style=style)
        ctx.route("**/api/study/items**", lambda r: r.fulfill(json={"items": SAVED}) if r.request.method == "GET" else r.continue_())
        ctx.route("**/api/monitor", lambda r: r.fulfill(json=MONITOR))
        g = got[style] = {}
        page.evaluate("async () => { showView('new'); await openUnderstanding('k2'); }")
        page.wait_for_selector("#review #dest-card", timeout=8000)
        page.wait_for_timeout(300)
        g["col"], g["card"] = page.evaluate(BOX, "#review"), page.evaluate(BOX, "#review #dest-card")
        g["cut"] = page.evaluate(CLIPPED, "#review .dest-path, #review .dest-top strong, #review .side-h")
        if style == "glass":
            shot(page, "8-analise")
        page.evaluate("""async () => { showView('study'); for (let i = 0; i < 60 && !window.lumenStudy?.setTab; i++) await new Promise(r => setTimeout(r, 100));
            await new Promise(r => setTimeout(r, 500)); window.lumenStudy.setTab('saved'); }""")
        page.wait_for_selector(".st-saved-item", timeout=8000)
        g["saved"] = page.evaluate("""() => [...document.querySelectorAll('.st-saved-item')].map(e => ({ border: parseFloat(getComputedStyle(e).borderTopWidth),
            tile: e.querySelector('.st-saved-icon').getBoundingClientRect().width, over: e.scrollWidth > e.clientWidth + 1,
            open: !!e.querySelector('.st-saved-actions .btn'), more: !!e.querySelector('.st-saved-actions .icon-btn') }))""")
        if style == "glass":
            shot(page, "8-salvos")
            page.click(".st-saved-item:first-child .st-saved-actions .icon-btn")
            page.wait_for_timeout(300)
            check("Exportar Markdown" in page.inner_text("body"), "Salvos no Glass: o menu de ações de um item abre como antes")
            page.keyboard.press("Escape")
        page.evaluate("document.getElementById('open-monitor').click()")
        page.wait_for_selector(".sys-stat-card", timeout=8000)
        page.wait_for_timeout(300)
        g["mon"], g["mon_clip"] = page.evaluate(BOX, "#sys-monitor-pop"), page.evaluate(CLIPPED, ".sys-stat-card, .sys-engine-badge")
        g["mon_text"] = page.inner_text("#sys-monitor-pop")
        if style == "glass":
            shot(page, "8-monitor")
            page.set_viewport_size({"width": 1100, "height": 560})
            page.wait_for_timeout(300)
            g["mon_low"], g["mon_low_clip"] = page.evaluate(BOX, "#sys-monitor-pop"), page.evaluate(CLIPPED, ".sys-stat-card, .sys-engine-badge")
            page.set_viewport_size({"width": 1568, "height": 1003})
        page.click("#close-monitor-btn")
        g["mon_closed"] = page.evaluate("document.getElementById('sys-monitor-pop').hidden")
        page.evaluate("async () => { window.lumenStudy.setTab('chat'); await new Promise(r => setTimeout(r, 600)); }")
        page.click(".st-mode")
        page.wait_for_selector(".st-mode-card", timeout=8000)
        page.wait_for_timeout(350)
        g["menu"] = page.evaluate("""() => { const b = (e) => e.getBoundingClientRect(), hd = document.querySelector('.st-mode-header'), m = document.querySelector('.st-menu');
            return { titleLeft: b(hd.querySelector('.eyebrow')).right <= b(hd.querySelector('.st-effort-tag')).left, top: b(m).top, bottom: b(m).bottom, vh: innerHeight,
                     desc: getComputedStyle(document.querySelector('.st-mode-card-desc')).textAlign, tile: b(document.querySelector('.st-mode-card-title-row > .i')).width,
                     chips: document.querySelectorAll('.st-effort-metric').length, tiles: document.querySelectorAll('.st-mode-tile').length }; }""")
        if style == "glass":
            shot(page, "8-menu-modo")
        g["errs"] = list(errs)
        ctx.close()
    G, C = got["glass"], got["classic"]
    check(G["col"]["w"] >= 380 and G["card"]["border"] == 0 and not G["cut"], f"Análise no Glass: coluna Salvar larga, destinos sem moldura dupla e nada cortado → {G['col']['w']:.0f} px, {G['cut']} cortado(s)")
    check(C["col"]["w"] == 340, f"Análise no Clássico: a coluna continua com 340 px → {C['col']['w']:.0f}")
    check(len(G["saved"]) == len(SAVED) and all(r["border"] == 1 and r["tile"] == 46 and r["open"] and r["more"] and not r["over"] for r in G["saved"]),
          "Salvos no Glass: cada item é uma faixa de vidro com ladrilho, Abrir e menu; título comprido não estoura a linha")
    check(all(r["border"] == 0 and r["tile"] == 36 for r in C["saved"]), "Salvos no Clássico: a lista continua como antes")
    check(G["mon"]["w"] == 420 and G["mon"]["top"] >= 0 and G["mon"]["bottom"] <= 1003 and not G["mon_clip"] and not G["mon"]["scrolls"],
          f"Monitor no Glass: cabe na janela e nenhum cartão corta o conteúdo → {G['mon_clip']} cortado(s)")
    check(all(t in G["mon_text"] for t in ("27%", "9.4 / 15.8 GB", "Lúmen: 322 MB", "modelo-de-teste", "Proteção", "Liberar VRAM")), "Monitor no Glass: os mesmos dados do Clássico")
    check(G["mon_low"]["top"] >= 0 and G["mon_low"]["scrolls"] and not G["mon_low_clip"], "Monitor no Glass com a janela baixa (560 px): o painel rola em vez de espremer os cartões")
    check(G["mon_closed"] and C["mon_closed"] and C["mon"]["w"] == 350, "Monitor: fecha pelo botão nos dois estilos; no Clássico continua com 350 px")
    m = G["menu"]
    check(m["titleLeft"] and m["desc"] == "left" and m["tile"] == 40 and m["top"] >= 0 and m["bottom"] <= m["vh"] and m["tiles"] == 6 and m["chips"] >= 1,
          f"menu de modo no Glass: título à esquerda do selo, descrição com ladrilho e o menu inteiro dentro da janela → {m}")
    check(C["menu"]["desc"] == "center" and C["menu"]["tiles"] == 6, "menu de modo no Clássico: descrição centralizada, como antes")
    check(not G["errs"] and not C["errs"], f"Parte 5 sem erros de script → {G['errs'] + C['errs']}")
    set_style(url, "glass")


def part6(browser, url):
    print("Parte 6 · texto curto e independente centralizado pelo token --ta-short; exceções no início (nos dois estilos)")
    M = """(sel) => { const c = [...document.querySelectorAll(sel)].find(e => e.getClientRects().length); if (!c) return null; const s = getComputedStyle(c), b = c.getBoundingClientRect();
        const L = b.left + parseFloat(s.paddingLeft) + parseFloat(s.borderLeftWidth), R = b.right - parseFloat(s.paddingRight) - parseFloat(s.borderRightWidth);
        const r = document.createRange(); r.selectNodeContents(c); const cr = r.getBoundingClientRect(), p = c.closest('.card, .pomo-sheet, nav, section') || c.parentElement, pb = p.getBoundingClientRect();
        return { ta: s.textAlign, delta: (cr.left + cr.right) / 2 - (L + R) / 2, slack: (R - L) - cr.width, w: b.width, inside: cr.left >= pb.left - 1 && cr.right <= pb.right + 1,
                 over: p.scrollWidth > p.clientWidth + 1, tnum: /tabular/.test(s.fontVariantNumeric) }; }"""
    mid = lambda m: bool(m) and m["ta"] == "center" and (abs(m["delta"]) <= 2.5 or m["slack"] < 6)
    JOBHOME = "async () => { lastUrl = '/api/finish'; showView('home'); poll(); await new Promise(r => setTimeout(r, 700)); }"
    WORST = "Semquebraalgumaumtitulomuitocompridoquenaotemespacosparaquebrarnalinhaeprecisacaberdentrodocartao 研究ノート 🧠 " + "palavra " * 30
    for style in ("glass", "classic"):
        ctx, page, W, log, errs = mocked(browser, url, style=style, patch=U.patch(job={**U.JOB, "title": "Redes neurais convolucionais"}))
        page.evaluate(JOBHOME)
        t, s, bar = page.evaluate(M, "#home-hero .hero-title"), page.evaluate(M, "#home-hero .hero-sub"), page.evaluate(M, "#home-hero .hero-progress")
        check(mid(t) and mid(s) and bar and bar["w"] > 200, f"{style}: aula em processamento no Início — título e detalhe no centro, barra de progresso com largura → {bar and round(bar['w'])} px")
        note = page.evaluate(M, "#home-reviews .card-note")
        check(mid(note), f"{style}: nota de rodapé do cartão de Revisões no centro")
        page.evaluate("document.documentElement.style.setProperty('--ta-short', 'start')")
        check(page.evaluate(M, "#home-hero .hero-title")["ta"] == "start" and page.evaluate(M, "#home-reviews .card-note")["ta"] == "start",
              f"{style}: o token --ta-short comanda o alinhamento (start devolve o texto ao início)")
        page.evaluate("document.documentElement.style.removeProperty('--ta-short')")
        page.click("#u-pomo .pomo-time")
        page.wait_for_timeout(350)
        check(mid(page.evaluate(M, ".pomo-sheet .pomo-msg")), f"{style}: mensagem do painel do Pomodoro no centro")
        page.keyboard.press("Escape")
        page.evaluate("async () => { showView('study'); for (let i = 0; i < 60 && !document.querySelector('.st-empty-small'); i++) await new Promise(r => setTimeout(r, 100)); }")
        check(mid(page.evaluate(M, ".st-empty-small")), f"{style}: estado vazio da lista de conversas no centro")
        # exceções: quem escreve, lê em coluna ou tem controle ao lado continua no início
        page.evaluate("async () => { showView('new'); await openUnderstanding('k1'); }")
        page.wait_for_timeout(300)
        ex = page.evaluate("() => ['#u-text', '#view-settings .set-text strong', '.lib-title', '#lesson-link'].map(s => { const e = document.querySelector(s); return e ? getComputedStyle(e).textAlign : 'ausente'; })")
        check(all(a in ("start", "left") for a in ex), f"{style}: campo de escrita, rótulo com controle, linha da Biblioteca e campo de link continuam no início → {ex}")
        check(not errs, f"{style}: sem erros de script → {errs}")
        ctx.close()
        # pior caso: título sem quebra, não latino, emoji e muito longo; e um caractere só
        for name, title in (("enorme", WORST), ("de 1 caractere", "A")):
            ctx, page, W, log, errs = mocked(browser, url, style=style, size=(1100, 760), patch=U.patch(job={**U.JOB, "title": title}))
            page.evaluate(JOBHOME)
            t = page.evaluate(M, "#home-hero .hero-title")
            check(t and t["ta"] == "center" and t["inside"] and not t["over"] and not errs, f"{style}: título {name} centralizado sem estourar o cartão (1100 × 760)")
            if SHOTS and style == "glass":
                shot(page, f"9-hero-{'pior' if title is WORST else 'um'}")
            ctx.close()
        ctx, page, W, log, errs = mocked(browser, url, style=style, patch=U.patch(recording=U.REC))
        page.evaluate("showView('home')")
        page.wait_for_timeout(400)
        tm = page.evaluate(M, "#home-hero .hero-time")
        check(mid(tm) and tm["tnum"], f"{style}: tempo de gravação no centro, com algarismos tabulares (não treme ao contar)")
        ctx.close()
    # Glass: o convite com a ilustração ao lado é linha com ícone à esquerda (fica no início); sem a ilustração (janela estreita) centraliza
    ctx, page, W, log, errs = mocked(browser, url)
    wide = page.evaluate(M, "#home-hero .g-hero .hero-title")
    page.set_viewport_size({"width": 1000, "height": 760})
    page.wait_for_timeout(300)
    narrow, art = page.evaluate(M, "#home-hero .g-hero .hero-title"), page.evaluate("getComputedStyle(document.querySelector('.g-hero-art')).display")
    # 15/11/2026, a pedido do usuário: o convite centraliza também com a ilustração ao lado (texto e botões no centro da coluna da direita)
    check(wide["ta"] == "center" and art == "none" and mid(narrow), f"Glass: convite centralizado com a ilustração e sem ela (1000 px) → {wide['ta']} / {narrow['ta']}")
    ctx.close()
    h = U.Harness(browser, url, OUT)
    for style in ("glass", "classic"):
        set_style(url, style)
        ctx, page, W, log, errs = h.open("widget", 304, 252, patch=lambda Wd, st=style: Wd["config"].update(ui_style=st))
        page.evaluate("""async () => { document.body.dataset.expanded = "true"; hostListeners.forEach(f => f({ data: "edge:top" })); await openPreferences(); await openCategory("desktop"); }""")
        page.wait_for_timeout(350)
        lab = page.evaluate(M, ".prefs-label")  # (h.open anota também requisições canceladas ao fechar: aqui só interessa o alinhamento)
        check(mid(lab), f"barra no {style}: rótulo 'Posição na tela' no centro, acima do controle centralizado → {lab}")
        ctx.close()
    set_style(url, "glass")


data = Path(tempfile.mkdtemp(prefix="lumen-glass-ui-", dir="D:/Lumen/t" if Path("D:/Lumen/t").is_dir() else None))
t0 = time.time()
try:
    with H.serve(ROOT, data) as S, sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
        part1(b, S)
        b.close()
    proc, url = U.serve()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            part2(b, url)
            part3(b, url)
            part4(b, url)
            part5(b, url)
            part6(b, url)
            b.close()
    finally:
        proc.kill()
        proc.wait(timeout=10)
        shutil.rmtree(proc.data, ignore_errors=True)
finally:
    shutil.rmtree(data, ignore_errors=True)
print(f"\n{len(ok)} verificações ok, {len(bad)} falha(s) em {time.time() - t0:.0f} s")
for x in bad:
    print("  FALHA:", x)
sys.exit(1 if bad else 0)
