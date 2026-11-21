"""Conversa rápida: ajustes próprios, modelo rápido e temporário discreto, na página real (Chrome headless, `chrome.webview` simulado) contra o
backend REAL e isolado de tests/chat_harness.py (LUMEN_DATA temporário, Ollama falso que transmite, sem Notion nem chaves do usuário).

  py -3.14 tests/quick_settings_ui.py        imagens em QUICK_ARTIFACTS (padrão: tests/desktop-artifacts/conversa-rapida-ajustes)

Prova o comportamento da PÁGINA e do armazenamento do navegador; o tamanho/foco da JANELA nativa só se prova no WebView2."""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # (não importa o pacote tests: ele pede o keyring, que só o .venv tem)
from chat_harness import LONG, serve  # noqa: E402

ART = Path(os.environ.get("QUICK_ARTIFACTS", ROOT / "tests/desktop-artifacts/conversa-rapida-ajustes"))
ART.mkdir(parents=True, exist_ok=True)
MODELS = ["qwen3:8b", "qwen3-embedding:0.6b", "qwen3.5:4b", "gemma3:4b"]
CANARY = "CANARIO-TEMP-91c2"
errors, turns = [], []

with serve(ROOT, ART) as H:
    call, fakectl, url = H.call, H.fakectl, H.url
    report = {"artifacts": str(ART), "checks": []}
    ok = lambda name: (report["checks"].append(name), print("  ok:", name, flush=True))  # noqa: E731
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
        context = browser.new_context(viewport={"width": 304, "height": 252}, screen={"width": 1920, "height": 1080}, device_scale_factor=2)
        context.add_init_script("window.messages=[]; window.hostListeners=[]; window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,fn)=>hostListeners.push(fn)};")
        context.on("request", lambda r: turns.append(r.post_data_json) if r.url.endswith("/api/study/turn") else None)
        context.on("page", lambda pg: pg.on("pageerror", lambda e: errors.append(str(e))))
        w = context.new_page()
        w.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
        w.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url.split('?')[0]}") if r.status >= 500 and r.url.startswith(url + "/") else None)
        shot = lambda name: w.screenshot(path=str(ART / f"{name}.png"), animations="disabled")  # noqa: E731
        w.goto(url + "/widget")
        w.wait_for_function("() => state !== null")
        w.evaluate("localStorage.clear(); sessionStorage.clear()")
        w.reload(); w.wait_for_function("() => state !== null")
        fakectl(models=MODELS, reset=True, answer="Resposta curta [S1].")
        S = lambda: w.evaluate("QuickChat.state()")  # noqa: E731
        msgs = lambda: w.evaluate("messages.slice()")  # noqa: E731
        orb = w.locator("#chat-btn")
        panel_h = lambda: w.evaluate("document.querySelector('#chat-panel').clientHeight")  # noqa: E731

        def idle(timeout=30000):
            w.wait_for_function("() => { const s = QuickChat.state(); return !s.streaming && !s.cancelling }", timeout=timeout)

        def box(sel):
            return w.locator(sel).bounding_box()

        def inside(sel, width=304, height=252, scroll=False):
            if scroll:
                w.locator(sel).scroll_into_view_if_needed()
            b = box(sel)
            assert b and b["x"] >= -0.5 and b["y"] >= -0.5 and b["x"] + b["width"] <= width + 0.5 and b["y"] + b["height"] <= height + 0.5, (sel, b)

        def no_hscroll():
            bad = w.evaluate("""() => ['html', 'body', '.notch', '#chat-thread', '#chat-panel', '#chat-set-body'].map(s => [s, document.querySelector(s)])
                .filter(([s, e]) => e && e.offsetParent !== null && e.scrollWidth > e.clientWidth + 1).map(([s, e]) => s + ' ' + e.scrollWidth + '>' + e.clientWidth)""")
            assert not bad, "rolagem horizontal: " + str(bad)

        def menu(item):
            w.locator("#chat-more").click()
            w.locator(item).click()

        def storage():
            return w.evaluate("JSON.stringify({l: Object.fromEntries(Object.entries(localStorage)), s: Object.fromEntries(Object.entries(sessionStorage)), c: document.cookie})")

        def stored(name):
            return w.evaluate("n => sessionStorage.getItem(n)", name)

        def conv_meta(cid):
            return call("/api/study/conversation?id=" + cid)["messages"][-1]["meta"]

        def send(text):
            w.locator("#chat-input").fill(text)
            w.keyboard.press("Enter")
            idle()

        orb.click()
        expect(w.locator("#chat-panel")).to_be_visible()

        # 1. O padrão real: nada salvo → Rápido do Lumen; os ajustes abrem pelo menu, dentro do painel, com Voltar à vista
        view = call("/api/study/quick")
        assert view["settings"] == {"model": "", "new_chat": "normal"} and view["resolved"]["source"] == "fast", view
        fast = view["fast"]
        w.locator("#chat-more").click()
        items = w.locator(".chat-menu button").all_inner_texts()
        assert any("Ajustes desta conversa" in t for t in items), items
        shot("00-menu-compacto")
        for sel in (".chat-menu", ".chat-menu button:last-child"):
            inside(sel)
        mb = box(".chat-menu")
        assert mb["height"] <= panel_h() + 1
        w.locator("#chat-menu-settings").click()
        expect(w.locator("#chat-set")).to_be_visible()
        assert w.locator("#chat-thread").is_hidden() and w.locator("#chat-form").is_hidden(), "o painel de ajustes substitui a conversa"
        assert w.evaluate("document.activeElement.id") == "chat-set-back", "o foco vai para Voltar"
        assert w.locator("#chat-set-back").inner_text().strip() == "Voltar"
        first = w.locator("#set-model [role=radio]").first
        assert first.get_attribute("aria-checked") == "true" and "Rápido do Lumen" in first.inner_text() and "padrão" in first.inner_text() and fast in first.inner_text()
        assert w.locator("#set-new [aria-checked=true]").inner_text() == "Normal" and w.locator("#set-size [aria-checked=true]").inner_text() == "Compacto"
        assert w.locator("#set-model [role=radio]").count() == 1 + 3, "padrão + os 3 modelos de chat instalados (sem embeddings)"
        assert "embedding" not in w.locator("#set-model").inner_text()
        assert f"Responde com {fast}" in w.locator("#set-model-note").inner_text()
        for sel in ("#chat-set-back", "#chat-set-title", "#set-model", "#set-new", "#set-size"):
            inside(sel, scroll=True)
        inside("#set-reset", scroll=True); no_hscroll()
        assert w.evaluate("document.querySelector('#chat-set-body').scrollHeight > document.querySelector('#chat-set-body').clientHeight"), "no painel compacto o corpo rola por dentro"
        w.evaluate("document.querySelector('#chat-set-body').scrollTop = 0")
        shot("01-ajustes-padrao")
        ok("ajustes pelo menu: painel interno compacto, Voltar com foco, padrão Rápido do Lumen (modelo resolvido), Normal, Compacto, só modelos de chat; corpo rola por dentro")

        # 2. Escolher outro modelo: grava no servidor, sem reenviar, sem apagar o rascunho, sem mexer em models.fast
        w.locator("#set-new [role=radio]").first.focus()  # só para ter um foco; o rascunho vem depois
        w.locator("#chat-set-back").click()
        w.locator("#chat-input").fill("rascunho normal que não pode sumir")
        w.wait_for_timeout(400)
        n_turns = len(turns)
        before_settings = call("/api/study/state")["settings"]
        menu("#chat-menu-settings")
        w.locator('#set-model [data-value="gemma3:4b"]').click()
        w.wait_for_function("() => document.querySelector('#chat-set-status').textContent.includes('Modelo salvo')")
        assert "próxima resposta" in w.locator("#chat-set-status").inner_text()
        assert call("/api/study/quick")["settings"]["model"] == "gemma3:4b"
        assert w.locator('#set-model [data-value="gemma3:4b"]').get_attribute("aria-checked") == "true"
        assert "Responde com gemma3:4b" in w.locator("#set-model-note").inner_text()
        after = call("/api/study/state")["settings"]
        assert after["models"] == before_settings["models"], "models.* (inclusive models.fast) intacto"
        w.locator("#chat-set-back").click()
        assert w.locator("#chat-input").input_value() == "rascunho normal que não pode sumir" and len(turns) == n_turns, "sem reenviar e sem apagar o rascunho"
        send("Como o sono ajuda a memória?")
        cid = S()["conv"]["id"]
        meta = conv_meta(cid)
        assert meta["model"] == "gemma3:4b" and meta["quick"] == {"source": "chosen", "requested": "gemma3:4b", "fallback": False}, meta
        assert turns[-1].get("surface") == "quick" and "model" not in turns[-1] and "provider" not in turns[-1], turns[-1]
        ok("escolha local gravada no servidor, validada; não reenvia nem apaga o rascunho; a resposta seguinte usa o modelo escolhido (meta.model); o pedido da tela não leva modelo")

        # 3. Persistência e Rápido de volta: recarregar a página mantém; "Rápido do Lumen" volta ao padrão resolvido
        w.reload(); w.wait_for_function("() => state !== null")
        orb.click()
        menu("#chat-menu-settings")
        w.wait_for_function("() => document.querySelector('#set-model [aria-checked=true]')?.dataset.value === 'gemma3:4b'")
        w.locator('#set-model [data-value=""]').click()
        w.wait_for_function("() => document.querySelector('#chat-set-status').textContent.includes('Modelo salvo')")
        assert call("/api/study/quick")["settings"]["model"] == ""
        w.locator("#chat-set-back").click()
        send("E o hipocampo?")
        assert conv_meta(S()["conv"]["id"])["quick"]["source"] == "fast" and conv_meta(S()["conv"]["id"])["model"] == fast
        ok("a escolha persiste ao recarregar; voltar ao Rápido do Lumen volta ao modelo rápido resolvido")

        # 4. Mudar um ajuste NO MEIO de uma resposta não a interrompe nem a reenvia; vale na próxima
        fakectl(answer=LONG, delay=0.03, hold=40)
        w.locator("#chat-input").fill("Pergunta longa para eu mexer nos ajustes no meio")
        w.keyboard.press("Enter")
        w.wait_for_function("() => QuickChat.state().streaming")
        w.wait_for_function("() => document.querySelector('.chat-msg.bot.live .chat-answer')?.textContent.length > 20", timeout=20000)
        n_turns = len(turns)
        menu("#chat-menu-settings")
        expect(w.locator("#chat-set")).to_be_visible()
        w.locator('#set-model [data-value="gemma3:4b"]').click()
        w.wait_for_function("() => document.querySelector('#chat-set-status').textContent.includes('Modelo salvo')")
        assert "continua como está" in w.locator("#chat-set-status").inner_text(), w.locator("#chat-set-status").inner_text()
        w.locator("#set-new [data-value=temporary]").click()
        w.wait_for_function("() => QuickChat.state().pref.new_chat === 'temporary'")
        assert S()["streaming"] and len(turns) == n_turns
        w.locator("#chat-set-back").click()
        assert S()["streaming"] and S()["conv"]["temporary"] is False, "a conversa em andamento segue normal e a resposta segue"
        fakectl(release=True)
        idle(60000)
        cid = S()["conv"]["id"]
        assert not cid.startswith("tmp-") and conv_meta(cid)["model"] == fast, "a resposta em andamento terminou com o modelo de antes"
        assert len(turns) == n_turns, "nada foi reenviado"
        fakectl(reset=True, answer="Agora com o outro modelo.")
        send("E agora?")
        assert conv_meta(cid)["model"] == "gemma3:4b", "o próximo envio usa o novo ajuste"
        ok("ajuste no meio da resposta: a geração segue, nada é reenviado, a conversa existente não vira temporária; vale da próxima resposta")

        # 5. Modo temporário: indicador pequeno e legível; sem alerta; o rascunho normal e o temporário são separados e nunca vão ao navegador
        w.locator("#chat-input").fill("rascunho NORMAL guardado")
        w.wait_for_timeout(400)
        assert stored("lumen.quick.draft") == "rascunho NORMAL guardado"
        menu("#chat-menu-new")  # com o ajuste "Temporária" vigente, a saída explícita é uma conversa normal; aqui só zera para provar o estado vazio
        assert S()["temporary"] is False and w.locator("#chat-temp").is_hidden() and w.locator("#chat-input").input_value() == "rascunho NORMAL guardado"
        w.locator("#chat-input").fill("")
        w.evaluate("QuickChat.closeSettings(false)")
        # sem escolha explícita no menu, o ajuste "Novas conversas = Temporária" vale: reabrir o painel vazio mostra o indicador
        w.evaluate("localStorage.removeItem('lumen.quick.conv')"); w.reload(); w.wait_for_function("() => state !== null")
        orb.click()
        w.wait_for_function("() => QuickChat.state().pref.new_chat === 'temporary'")
        expect(w.locator("#chat-temp")).to_be_visible()
        chip = w.locator("#chat-temp")
        assert chip.inner_text().strip() == "Temporária" and chip.locator("svg use").get_attribute("href").endswith("#clock")
        cs = chip.evaluate("n => { const c = getComputedStyle(n); return {anim: c.animationName, color: c.color, bg: c.backgroundColor, h: n.getBoundingClientRect().height} }")
        assert cs["anim"] == "none" and cs["h"] <= 22, cs
        assert "Temporária:" in w.locator("#chat-empty-hint").inner_text()
        for sel in ("#chat-temp", "#chat-mode", "#chat-more", "#chat-collapse", "#chat-input", "#chat-send"):
            inside(sel)
        mode_b, temp_b = box("#chat-mode"), box("#chat-temp")
        assert mode_b["x"] + mode_b["width"] <= temp_b["x"] + .5, "o indicador não empurra nem cobre Livre/Notas"
        assert w.locator("#chat-input").input_value() == "", "o rascunho normal ficou guardado à parte"
        shot("02-temporaria-vazia")
        w.locator("#chat-input").fill(f"rascunho {CANARY}-rascunho")
        w.wait_for_timeout(500)
        assert CANARY not in storage(), "rascunho temporário NUNCA no armazenamento do navegador"
        send(f"Pergunta temporária {CANARY}-pergunta")
        tid = S()["conv"]["id"]
        assert tid.startswith("tmp-") and S()["temporary"] is True and "temporary" not in turns[-1], turns[-1]  # o servidor seguiu o ajuste
        assert CANARY not in storage() and tid not in storage(), "mensagem, rascunho e ponteiro temporários fora do localStorage/sessionStorage"
        assert w.evaluate("localStorage.getItem('lumen.quick.conv')") in (None, "") or "tmp-" not in w.evaluate("localStorage.getItem('lumen.quick.conv')")
        assert call("/api/study/conversation?id=" + tid)["temporary"] is True
        listed = [c for c in call("/api/study/conversations")["conversations"] if c["id"] == tid]
        assert listed and listed[0]["temporary"] is True
        shot("03-temporaria-com-resposta")
        ok("temporária: chip pequeno e neutro (relógio + texto, sem pulso), não empurra controles; ajuste 'Novas conversas' aplicado pelo servidor; mensagem, rascunho e ponteiro fora do navegador")

        # 6. Menu na temporária: saída explícita "Nova conversa normal" cria outra conversa e preserva a temporária; rascunhos não se misturam
        w.locator("#chat-input").fill(f"rascunho temp {CANARY}-2")
        w.locator("#chat-more").click()
        labels = w.locator(".chat-menu button").all_inner_texts()
        assert any("Nova conversa normal" in t for t in labels) and any("Nova conversa temporária" in t for t in labels), labels
        shot("04-menu-temporaria")
        w.locator("#chat-menu-new").click()
        assert S()["conv"] is None and S()["temporary"] is False and w.locator("#chat-temp").is_hidden()
        assert w.locator("#chat-input").input_value() == "rascunho NORMAL guardado", "o campo traz o rascunho NORMAL (guardado à parte); o temporário não passa para a conversa normal"
        w.wait_for_timeout(400)
        assert CANARY not in storage()
        w.locator("#chat-input").fill("texto da normal")
        send("Pergunta da normal")
        nid = S()["conv"]["id"]
        assert not nid.startswith("tmp-") and json.loads(w.evaluate("localStorage.getItem('lumen.quick.conv')"))["id"] == nid
        assert call("/api/study/conversation?id=" + tid)["temporary"] is True, "a temporária anterior foi preservada, ainda temporária"
        assert [m["content"] for m in call("/api/study/conversation?id=" + nid)["messages"] if m["role"] == "user"] == ["Pergunta da normal"], "nada da temporária na normal"
        assert CANARY not in json.dumps(call("/api/study/conversation?id=" + nid))
        # voltar ao temporário: o rascunho temporário continua na memória da página (não no navegador)
        menu("#chat-menu-temp")
        assert S()["temporary"] is True and w.locator("#chat-temp").is_visible()
        assert w.locator("#chat-input").input_value() == f"rascunho temp {CANARY}-2", "o rascunho temporário voltou da memória da página"
        w.locator("#chat-input").fill("")
        ok("Nova conversa normal / temporária criam conversas novas e preservam a anterior; rascunho normal e temporário são espaços separados (o temporário só na memória)")

        # 7. Recolher e reabrir: a conversa temporária continua (em memória); fechar os ajustes não apaga nada; Continuar no Cérebro leva o MESMO id
        send(f"Mais uma temporária {CANARY}-3")
        tid2 = S()["conv"]["id"]
        n_msgs = S()["messages"]
        w.evaluate("conceal(); host.postMessage('widget:collapse')")
        w.evaluate("document.body.dataset.expanded = 'true'")
        orb.click()
        assert S()["conv"]["id"] == tid2 and S()["messages"] == n_msgs and w.locator("#chat-temp").is_visible()
        menu("#chat-menu-settings")
        w.locator("#chat-set-back").click()
        assert S()["conv"]["id"] == tid2 and w.locator(".chat-msg.bot").count() >= 1
        menu("#chat-menu-settings")
        w.evaluate("conceal()")  # recolher com os ajustes abertos: ao reabrir, a conversa
        w.evaluate("document.body.dataset.expanded = 'true'")
        orb.click()
        assert S()["view"] is None and w.locator("#chat-set").is_hidden() and S()["conv"]["id"] == tid2
        n = len(msgs())
        w.locator("#chat-more").click(); w.locator("#chat-brain").click()
        assert f"chat:open:{tid2}" in msgs()[n:]
        assert call("/api/study/conversation?id=" + tid2)["temporary"] is True
        assert CANARY not in storage()
        ok("recolher/reabrir e fechar os ajustes preservam a conversa temporária em memória; Continuar no Cérebro envia o mesmo id e a conversa segue temporária")

        # 8. Tentar de novo na temporária: mesmo id, mesma privacidade, sem duplicar a pergunta; modelo ausente → recuperação local ou erro claro
        fakectl(models=["qwen3:8b", "qwen3-embedding:0.6b", "qwen3.5:4b"])  # o modelo escolhido (gemma3:4b) saiu do Ollama
        w.locator("#chat-input").fill(f"Pergunta com modelo ausente {CANARY}-4")
        w.keyboard.press("Enter")
        idle()
        last = w.locator(".chat-msg.bot").last
        last.locator(".chat-more").click()
        details = last.locator(".chat-details").inner_text()
        assert "gemma3:4b" in details and "não estava instalado" in details and S()["conv"]["id"] == tid2, details
        assert conv_meta(tid2)["quick"]["fallback"] is True and conv_meta(tid2)["model"] == fast
        menu("#chat-menu-settings")
        w.wait_for_function("""() => document.querySelector('#set-model [data-value="gemma3:4b"]')?.textContent.includes('não instalado')""")  # a lista é relida ao abrir
        assert "não está instalado" in w.locator("#set-model-note").inner_text() and fast in w.locator("#set-model-note").inner_text()
        shot("05-ajustes-modelo-ausente")
        w.locator("#chat-set-back").click()
        fakectl(models=[])
        w.locator("#chat-input").fill(f"Sem nenhum modelo {CANARY}-5")
        w.keyboard.press("Enter")
        expect(w.locator(".chat-note[data-tone=error]")).to_contain_text("não está instalado", timeout=20000)
        assert w.locator("#chat-input").input_value() == "", "confirmada pelo servidor: o campo limpa; o texto está na conversa"
        users = [m["content"] for m in call("/api/study/conversation?id=" + tid2)["messages"] if m["role"] == "user"]
        fakectl(models=MODELS)
        w.locator(".chat-note-btn", has_text="Tentar de novo").click()
        idle()
        conv = call("/api/study/conversation?id=" + tid2)
        assert conv["temporary"] is True and conv["id"] == tid2 and [m["content"] for m in conv["messages"] if m["role"] == "user"] == users, "mesma conversa temporária, sem pergunta duplicada"
        assert conv["messages"][-1]["role"] == "assistant" and CANARY not in storage()
        assert call("/api/study/quick")["settings"]["model"] == "gemma3:4b", "o ajuste não foi reescrito em silêncio"
        ok("modelo ausente: recuperação local identificada (detalhes e ajustes dizem qual respondeu); sem nenhum modelo: erro claro; Tentar de novo na temporária mantém id, privacidade e a pergunta")

        # 9. Restaurar: só os ajustes desta conversa; conversas, notas e modelos intactos; a barra volta ao tamanho compacto
        total_before = len(call("/api/study/conversations")["conversations"])
        w.evaluate("QuickChat.setWide(true)")
        n0 = len(msgs())
        menu("#chat-menu-settings")
        assert w.locator("#set-size [aria-checked=true]").inner_text() == "Ampliado"
        w.locator("#set-reset").click()
        w.wait_for_function("() => document.querySelector('#chat-set-status').textContent.includes('restaurados')")
        view = call("/api/study/quick")
        assert view["settings"] == {"model": "", "new_chat": "normal"} and S()["pref"] == {"model": "", "new_chat": "normal"}, (view["settings"], S()["pref"])
        assert w.locator("#set-size [aria-checked=true]").inner_text() == "Compacto" and "widget:panel:chat" in msgs()[n0:]
        assert len(call("/api/study/conversations")["conversations"]) == total_before and set(MODELS) <= set(call("/api/study/models")["local"]) | {"qwen3-embedding:0.6b"}
        assert S()["conv"]["id"] == tid2, "a conversa aberta continua"
        shot("06-ajustes-restaurados")
        w.locator("#chat-set-back").click()
        ok("restaurar: só modelo, novas conversas e tamanho; conversas, notas e modelos não mudam; a conversa aberta continua")

        # 9b. O servidor valida de novo: um modelo que saiu do Ollama depois de a lista aparecer é recusado, com mensagem clara, e a tela volta ao que está salvo
        menu("#chat-menu-settings")
        w.wait_for_function("() => document.querySelector('#set-model [data-value=\"qwen3:8b\"]')")
        w.wait_for_timeout(600)  # a leitura feita ao abrir já terminou: a lista na tela é a "velha"
        fakectl(models=["qwen3-embedding:0.6b", "qwen3.5:4b", "gemma3:4b"])  # qwen3:8b sumiu; a tela ainda o oferece
        w.locator('#set-model [data-value="qwen3:8b"]').click()
        w.wait_for_function("() => document.querySelector('#chat-set-status').dataset.tone === 'error'")
        assert "não está instalado" in w.locator("#chat-set-status").inner_text()
        assert call("/api/study/quick")["settings"]["model"] == "" and S()["pref"]["model"] == ""
        w.wait_for_function("() => !document.querySelector('#set-model [data-value=\"qwen3:8b\"]')")  # a lista foi relida
        assert w.locator('#set-model [aria-checked=true]').get_attribute("data-value") == ""
        fakectl(models=MODELS)
        w.locator("#chat-set-back").click()
        ok("modelo que saiu do Ollama depois de a lista aparecer: o servidor recusa, a tela mostra o erro e volta ao que está salvo")

        # 9c. Servidor de uma versão anterior (sem /api/study/quick): a tela explica, não quebra, e a conversa segue funcionando
        w.route("**/api/study/quick", lambda r: r.fulfill(status=404, content_type="application/json", body=json.dumps({"error": {"message": "Rota não encontrada."}})))
        w.reload(); w.wait_for_function("() => state !== null")  # página nova: nada foi lido ainda (como com o servidor anterior desde o começo)
        orb.click()
        menu("#chat-menu-settings")
        w.wait_for_function("() => document.querySelector('#chat-set-status').dataset.tone === 'error'")
        assert "reabra o Lumen" in w.locator("#chat-set-status").inner_text() and w.locator("#set-model [role=radio]").count() >= 1
        w.locator("#chat-set-back").click()
        send("Segue funcionando com o servidor antigo")
        turn = turns[-1]
        assert turn["surface"] == "quick" and S()["conv"] is not None and w.locator(".chat-msg.bot").count() >= 1
        w.unroute("**/api/study/quick")
        menu("#chat-menu-settings")
        w.wait_for_function("() => document.querySelector('#chat-set-status').dataset.tone !== 'error'")
        assert w.locator("#chat-set-status").inner_text() == "", "a leitura voltou: o aviso de falha sai da tela"
        w.locator("#chat-set-back").click()
        ok("sem a rota de ajustes (servidor anterior): aviso claro na tela de ajustes, conversa segue funcionando, aviso some quando a leitura volta")

        # 10. Teclado, foco e Esc: grupos de rádios com setas; Esc volta (menu → ajustes → recolher); foco visível; movimento reduzido
        menu("#chat-menu-settings")
        w.locator('#set-model [aria-checked=true]').focus()
        w.keyboard.press("ArrowDown")
        w.wait_for_function("() => document.querySelector('#chat-set-status').textContent.includes('Modelo salvo')")
        sel_val = w.evaluate("document.querySelector('#set-model [aria-checked=true]').dataset.value")
        assert sel_val and w.evaluate("document.activeElement.dataset.value") == sel_val, "a seta move o foco E escolhe"
        assert call("/api/study/quick")["settings"]["model"] == sel_val
        w.keyboard.press("Home")
        w.wait_for_function("() => document.querySelector('#set-model [aria-checked=true]').dataset.value === ''")
        w.locator('#set-new [aria-checked=true]').focus()
        w.keyboard.press("ArrowRight")
        w.wait_for_function("() => QuickChat.state().pref.new_chat === 'temporary'")
        w.keyboard.press("ArrowLeft")
        w.wait_for_function("() => QuickChat.state().pref.new_chat === 'normal'")
        w.locator("#chat-set-back").focus()
        outline = w.locator("#chat-set-back").evaluate("n => getComputedStyle(n).outlineStyle + ' ' + getComputedStyle(n).outlineWidth")
        assert outline.startswith("solid") or w.evaluate("document.activeElement.matches(':focus-visible')"), outline
        n = len(msgs())
        w.keyboard.press("Escape")
        assert w.locator("#chat-set").is_hidden() and w.locator("#chat-panel").is_visible() and "widget:collapse" not in msgs()[n:], "o primeiro Esc volta dos ajustes"
        assert w.evaluate("document.activeElement.id") == "chat-more"
        w.keyboard.press("Escape")
        assert w.locator("#chat-panel").is_hidden() and "widget:collapse" in msgs()[n:], "o segundo Esc recolhe a barra"
        w.evaluate("document.body.dataset.expanded = 'true'"); orb.click()
        w.emulate_media(reduced_motion="reduce")
        menu("#chat-menu-settings")
        assert w.locator("#chat-panel").evaluate("n => getComputedStyle(n).animationName") == "none"
        w.emulate_media(reduced_motion="no-preference")
        assert w.locator("#chat-set-back").get_attribute("data-tip") is None, "o Voltar já diz o que faz: sem dica por cima do título"
        w.locator("#set-new [data-value=temporary]").click()  # muda um ajuste COM o campo oculto: a dica do campo não pode ficar com o texto longo ao voltar
        w.wait_for_function("() => QuickChat.state().pref.new_chat === 'temporary'")
        w.locator("#chat-set-back").click()
        assert w.locator("#chat-input").get_attribute("placeholder") == "Pergunte…", w.locator("#chat-input").get_attribute("placeholder")
        assert w.evaluate("(() => { const t = document.querySelector('#chat-input'); return t.scrollHeight <= t.clientHeight + 1 })()"), "o campo vazio não ganha barra de rolagem"
        menu("#chat-menu-settings"); w.locator("#set-new [data-value=normal]").click()
        w.wait_for_function("() => QuickChat.state().pref.new_chat === 'normal'"); w.locator("#chat-set-back").click()
        ok("grupos de rádios por teclado (seta move e escolhe, Home), Esc volta dos ajustes e depois recolhe, foco visível, movimento reduzido")

        # 11. Quatro orientações e a janela ampliada: tudo dentro do painel; a conversa e os ajustes cabem; nenhuma rolagem horizontal
        for edge, size in (("left", (304, 252)), ("right", (304, 252)), ("top", (304, 252)), ("bottom", (304, 252)), ("left", (360, 480))):
            w.evaluate("edge => { hostListeners.forEach(fn => fn({data: 'edge:' + edge})); hostListeners.forEach(fn => fn({data: 'side:' + (edge === 'right' ? 'right' : 'left')})) }", edge)
            w.set_viewport_size({"width": size[0], "height": size[1]})
            w.wait_for_timeout(200)
            for sel in ("#chat-temp", "#chat-mode", "#chat-more", "#chat-collapse", "#chat-input", "#chat-send"):
                if w.locator(sel).is_visible():
                    inside(sel, *size)
            menu("#chat-menu-settings")
            for sel in ("#chat-set-back", "#chat-set-title", "#set-model", "#set-new", "#set-size", "#set-reset"):
                inside(sel, *size, scroll=True)
            no_hscroll()
            w.locator("#chat-set-back").click()
            w.locator("#chat-more").click()
            inside(".chat-menu", *size)
            assert w.evaluate("(() => { const m = document.querySelector('.chat-menu'); return m.scrollHeight <= m.clientHeight + 1 })()"), (edge, size, "as 5 ações cabem no menu sem rolar")
            assert w.locator(".chat-menu button").count() == 5
            for b in w.locator(".chat-menu button").all():
                b.scroll_into_view_if_needed()
            w.keyboard.press("Escape")
            no_hscroll()
        w.set_viewport_size({"width": 304, "height": 252})
        w.evaluate("hostListeners.forEach(fn => fn({data: 'edge:left'})); hostListeners.forEach(fn => fn({data: 'side:left'}))")
        ok("conversa, indicador, menu e ajustes cabem nas quatro bordas (304×252) e na janela ampliada (360×480); sem rolagem horizontal; sem transform/zoom")

        # 12. Imagens de referência no compacto: conversa normal, conversa temporária, ajustes, menu aberto
        w.evaluate("QuickChat.newConversation(false)")
        w.locator("#chat-input").fill("")
        send("Como o sono ajuda a memória?")
        shot("10-conversa-normal")
        w.locator("#chat-more").click()
        shot("11-menu-aberto-compacto")
        w.keyboard.press("Escape")
        w.evaluate("QuickChat.newConversation(true)")
        send("Isto fica só na memória do Lumen")
        shot("12-conversa-temporaria")
        menu("#chat-menu-settings")
        w.locator('#set-model [data-value="gemma3:4b"]').scroll_into_view_if_needed()
        w.evaluate("document.querySelector('#chat-set-body').scrollTop = 0")
        shot("13-ajustes")
        w.evaluate("document.querySelector('#chat-set-body').scrollTop = 9999")
        shot("14-ajustes-rolado")
        w.locator("#chat-set-back").click()
        ok("capturas: conversa normal, temporária, ajustes (topo e rolado) e menu aberto no tamanho compacto")

        assert not errors, errors
        browser.close()
    report["result"] = "OK"
    (ART / "quick-settings-ui-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"OK: {len(report['checks'])} blocos de verificação dos ajustes da Conversa rápida; imagens em {ART}")
