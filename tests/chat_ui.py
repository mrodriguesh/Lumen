"""Conversa rápida da barra flutuante: backend REAL e isolado (LUMEN_DATA temporário, cofre de teste, Ollama falso que transmite
de verdade, sem Notion nem chaves do usuário) e Chrome headless (Playwright) com o `chrome.webview` simulado.

  py -3.14 tests/chat_ui.py          imagens em CHAT_ARTIFACTS (padrão: tests/desktop-artifacts/conversa-rapida)

Prova o comportamento da página; o tamanho/foco da JANELA nativa só se prova no WebView2 (tests/DesktopChecks.cs)."""
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
ART = Path(os.environ.get("CHAT_ARTIFACTS", ROOT / "tests/desktop-artifacts/conversa-rapida"))
ART.mkdir(parents=True, exist_ok=True)

BOOT = r"""
import sys, threading
sys.path.insert(0, sys.argv[1])
from tests.fake_ollama import FakeOllama
fake = FakeOllama()
fake.models.append("qwen3.5:4b")
from lumen import server, store, obsidian
store.get_token = lambda: ""           # nunca o token real do Notion
from lumen.study import settings
settings.api_key = lambda *a, **kw: ""  # nem as chaves reais dos provedores externos
cfg = store.load_config(); cfg["obsidian_vault"] = sys.argv[2]; store.save_config(cfg)
OPENED = []
obsidian.open_path = lambda p: OPENED.append(str(p))   # o Obsidian de verdade nunca é aberto pelo teste
def _fake(h):
    b = h._json()
    if "answer" in b: fake.answer = b["answer"]
    if "delay" in b: fake.delay = float(b["delay"])
    if "models" in b: fake.models[:] = b["models"]
    if b.get("hold") is not None:
        fake.gate = threading.Event(); fake.hold_after = int(b["hold"])
    if b.get("release") and fake.gate is not None:
        fake.gate.set()
    if b.get("reset"):
        fake.gate = None; fake.delay = 0.0
    if b.get("opened"): return {"opened": OPENED}
    chats = [r for r in fake.requests if r[0] == "/api/chat" and not r[1].get("format")]
    return {"ok": True, "chat_requests": len(chats), "last_system": (chats[-1][1]["messages"][0]["content"][:4000] if chats else ""), "opened": OPENED}
server.ROUTES[("POST", "/api/study/__fake")] = _fake
h = server.serve(); print(h.server_port, flush=True); h.serve_forever()
"""

LONG = ("## Como o sono ajuda a memória\n\nDurante o **sono profundo** o hipocampo reativa o que você viveu [S1]. Veja também a "
        "[página do tema](https://example.org/sono).\n\n- Codificação: o cérebro grava o novo\n- Consolidação: as ondas lentas reativam\n"
        "- Evocação: a lembrança fica no córtex\n\n```python\ndef consolidar(memoria, sono):\n    return memoria if sono >= 7 else None  # uma linha bem comprida para provar a rolagem horizontal do bloco\n```\n\n"
        "| Fase | Papel |\n| --- | --- |\n| N3 | consolida |\n| REM | integra |\n\n> Dormir bem depois de estudar vale mais que mais uma hora de revisão.\n\n"
        + " ".join(f"palavra{n}" for n in range(220)))


def note(vault, rel, text):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


errors, turns = [], []
with tempfile.TemporaryDirectory(prefix="chat-ui-") as temp:
    vault = Path(temp) / "Cofre de teste"
    (vault / ".obsidian").mkdir(parents=True)
    note(vault, "B02 Estudos/Memória e sono.md", "---\ntype: permanent\ntags: [psicologia]\n---\n# Memória e sono\nA consolidação da memória depende do sono profundo. Ver [[Atenção]].")
    note(vault, "Atenção.md", "# Atenção\nFoco seletivo e memória de trabalho.")
    note(vault, "Behaviorismo.md", "# Behaviorismo\nCondicionamento operante e reforço, segundo Skinner.")
    env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    backend_log = (ART / "backend.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c", BOOT, str(ROOT), str(vault)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=backend_log, text=True)
    report = {"artifacts": str(ART), "checks": []}
    ok = lambda name: (report["checks"].append(name), print("  ok:", name, flush=True))  # noqa: E731
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        page_token = {"v": None}

        def call(path, body=None, token=None):
            """Chamada direta ao servidor (como outra janela faria)."""
            if page_token["v"] is None:
                html = urllib.request.urlopen(url + "/widget").read().decode()
                page_token["v"] = re.search(r'name="lumen-token" content="([^"]+)"', html).group(1)
            req = urllib.request.Request(url + path, headers={"X-Lumen-Token": token or page_token["v"], "Content-Type": "application/json"})
            if body is not None:
                req.data = json.dumps(body).encode()
            return json.loads(urllib.request.urlopen(req).read() or b"{}")

        fakectl = lambda **kw: call("/api/study/__fake", kw)  # noqa: E731
        # Índice do cofre de teste (Obsidian): o modo Notas precisa de fontes de verdade
        call("/api/study/sources", {"action": "sync", "source": "obsidian"})
        for _ in range(120):
            st = call("/api/study/state")
            if not st["index"]["running"] and st["counts"].get("documents", st["counts"].get("docs", 1)):
                break
            time.sleep(0.5)
        time.sleep(1.0)

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            context = browser.new_context(viewport={"width": 304, "height": 252}, screen={"width": 1920, "height": 1080}, device_scale_factor=2, permissions=["clipboard-read", "clipboard-write"])
            context.add_init_script("window.messages=[]; window.hostListeners=[]; window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,fn)=>hostListeners.push(fn)};")
            context.on("request", lambda r: turns.append(r.post_data_json) if r.url.endswith("/api/study/turn") else None)
            context.on("page", lambda pg: pg.on("pageerror", lambda e: errors.append(str(e))))
            w = context.new_page()
            w.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
            w.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url.split('?')[0]}") if r.status >= 500 and r.url.startswith(url + "/") else None)
            shot = lambda name, page=None: (page or w).screenshot(path=str(ART / f"{name}.png"), animations="disabled")  # noqa: E731
            w.goto(url + "/widget")
            w.wait_for_function("() => state !== null")
            w.evaluate("localStorage.clear(); sessionStorage.clear()")
            w.reload(); w.wait_for_function("() => state !== null")
            S = lambda: w.evaluate("QuickChat.state()")  # noqa: E731
            msgs = lambda: w.evaluate("messages.slice()")  # noqa: E731

            def idle(timeout=30000):
                w.wait_for_function("() => { const s = QuickChat.state(); return !s.streaming && !s.cancelling }", timeout=timeout)

            def box(sel):
                return w.locator(sel).bounding_box()

            def inside(sel, width=304, height=252):
                b = box(sel)
                assert b and b["x"] >= -0.5 and b["y"] >= -0.5 and b["x"] + b["width"] <= width + 0.5 and b["y"] + b["height"] <= height + 0.5, (sel, b)

            def no_hscroll():
                bad = w.evaluate("""() => ['html', 'body', '.notch', '#chat-thread', '#chat-panel'].map(s => [s, document.querySelector(s)])
                    .filter(([s, e]) => e.scrollWidth > e.clientWidth + 1).map(([s, e]) => s + ' ' + e.scrollWidth + '>' + e.clientWidth)""")
                assert not bad, "rolagem horizontal: " + str(bad)

            # 1. Acesso em um clique: ícone na barra, nome, tooltip, estado selecionado; abrir cresce a janela e foca o campo
            orb = w.locator("#chat-btn")
            assert orb.get_attribute("aria-label") == "Conversa rápida" and orb.get_attribute("data-tip") == "Conversa rápida" and orb.get_attribute("aria-expanded") == "false"
            assert w.locator("#chat-btn svg use").get_attribute("href").endswith("#chat")
            for sel in ("#open", "#action", "#chat-btn", "#settings", "#drag"):
                inside(sel, 304, 252)
            shot("00-barra-com-conversa")
            # Com “Minha compreensão” a trilha tem cinco controles (compacta): tudo dentro do painel de 304×252, sem encostar nem na alça
            w.set_viewport_size({"width": 304, "height": 252})  # o painel da gravação, como a janela nativa o deixa
            for edge in ("left", "right", "top", "bottom"):
                w.evaluate("edge => { hostListeners.forEach(fn => fn({data: 'edge:' + edge})); hostListeners.forEach(fn => fn({data: 'side:' + (edge === 'right' ? 'right' : 'left')})); document.body.dataset.note = 'true'; document.querySelector('#note-btn').hidden = false; }", edge)
                w.wait_for_timeout(100)
                sels = ("#open", "#action", "#chat-btn", "#note-btn", "#settings")
                boxes = {s: box(s) for s in sels}
                grip = box(".grip span")
                for s, b in boxes.items():
                    assert b and b["x"] >= 0 and b["y"] >= 0 and b["x"] + b["width"] <= 304 and b["y"] + b["height"] <= 252, (edge, s, b)
                    assert not (b["x"] < grip["x"] + grip["width"] and grip["x"] < b["x"] + b["width"] and b["y"] < grip["y"] + grip["height"] and grip["y"] < b["y"] + b["height"]), (edge, s, "encosta na alça")
                for i, a in enumerate(sels):
                    for c in sels[i + 1:]:
                        A, C = boxes[a], boxes[c]
                        assert A["x"] + A["width"] <= C["x"] + .5 or C["x"] + C["width"] <= A["x"] + .5 or A["y"] + A["height"] <= C["y"] + .5 or C["y"] + C["height"] <= A["y"] + .5, (edge, a, c, "sobrepostos")
                if edge in ("left", "top"): shot(f"00-barra-com-compreensao-{edge}")
            w.evaluate("document.body.dataset.note = ''; document.querySelector('#note-btn').hidden = true; hostListeners.forEach(fn => fn({data: 'edge:left'})); hostListeners.forEach(fn => fn({data: 'side:left'}))")
            ok("trilha com cinco controles (Minha compreensão + Conversa rápida) cabe nas quatro orientações, sem sobreposição nem encostar na alça")
            orb.click()
            expect(w.locator("#chat-panel")).to_be_visible()
            assert orb.get_attribute("aria-expanded") == "true" and "widget:panel:chat" in msgs()
            assert w.evaluate("document.activeElement.id") == "chat-input", "o campo fica pronto para digitar"
            assert w.evaluate("document.body.dataset.panel") == "chat" and w.locator("#recording-panel").is_hidden()
            nb = box(".notch")
            assert (nb["width"], nb["height"]) == (304, 252), nb  # a conversa abre na janela compacta de sempre e o painel ocupa a janela inteira
            expect(w.locator("#chat-empty")).to_be_visible()
            assert w.locator("#chat-empty-title").inner_text() == "O que você quer saber?"
            shot("01-vazio")
            for sel in ("#chat-title", "#chat-more", "#chat-collapse", "#chat-mode", "#chat-input", "#chat-send"):
                inside(sel)
            no_hscroll()
            ok("acesso em um clique, estado selecionado, janela compacta 304×252 (sem crescer), campo focado, estado vazio simples")

            # 2. Livre/Notas: mesmo estado do Cérebro (localStorage), teclado e rótulos
            notes_btn, free_btn = w.locator('#chat-mode [data-mode=notes]'), w.locator('#chat-mode [data-mode=free]')
            assert notes_btn.get_attribute("aria-checked") == "true" and free_btn.get_attribute("aria-checked") == "false"
            free_btn.click()
            assert w.evaluate("localStorage.getItem('lumen.study.skipVault')") == "true" and free_btn.get_attribute("aria-checked") == "true"
            assert "sem consultar suas notas" in w.locator("#chat-empty-hint").inner_text()
            w.locator("#chat-mode [aria-checked=true]").focus()
            w.keyboard.press("ArrowLeft")
            assert notes_btn.get_attribute("aria-checked") == "true" and w.evaluate("localStorage.getItem('lumen.study.skipVault')") == "false"
            w.evaluate("localStorage.setItem('lumen.study.vaultSources', JSON.stringify(['obsidian']))")
            w.evaluate("window.dispatchEvent(new StorageEvent('storage', {key: 'lumen.study.vaultSources'}))")
            assert w.locator("#chat-scope").inner_text() == "Só o Obsidian"
            w.evaluate("localStorage.removeItem('lumen.study.vaultSources'); window.dispatchEvent(new StorageEvent('storage', {key: 'lumen.study.vaultSources'}))")
            expect(w.locator("#chat-scope")).to_be_hidden()
            ok("Livre/Notas: radiogroup, setas, chaves compartilhadas com o Cérebro, seleção de fonte única preservada")

            # 3. Enter, Shift+Enter e IME: só o Enter puro envia
            before = len(turns)
            w.locator("#chat-input").fill("")
            w.locator("#chat-input").press("Enter")
            assert len(turns) == before, "campo vazio não envia"
            w.locator("#chat-input").fill("linha 1")
            w.keyboard.press("Shift+Enter")
            w.keyboard.type("linha 2")
            assert w.locator("#chat-input").input_value() == "linha 1\nlinha 2" and len(turns) == before
            assert w.evaluate("document.querySelector('#chat-input').clientHeight") > 30, "o campo cresce com a segunda linha"
            ime = w.evaluate("""() => { const t = document.querySelector('#chat-input'); const e = new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, keyCode: 229, bubbles: true, cancelable: true});
                t.dispatchEvent(e); return e.defaultPrevented }""")
            assert not ime and len(turns) == before, "o Enter que confirma uma composição (IME) não envia"
            ok("Enter envia, Shift+Enter quebra a linha, IME não envia, campo vazio não envia")

            # 4. Streaming de verdade no modo Notas: etapas reais, texto aparecendo, botão vira Interromper, sem envio duplicado
            fakectl(answer=LONG, delay=0.03, hold=40)
            w.locator("#chat-input").fill("Como o sono ajuda a memória?")
            w.keyboard.press("Enter"); w.keyboard.press("Enter")  # o segundo Enter não pode gerar um segundo envio
            w.wait_for_function("() => QuickChat.state().streaming")
            assert w.locator("#chat-send").get_attribute("data-mode") == "stop" and w.locator("#chat-send").get_attribute("aria-label") == "Interromper a resposta"
            expect(w.locator(".chat-msg.user")).to_have_count(1)
            w.wait_for_function("() => document.querySelector('.chat-msg.bot.live .chat-answer')?.textContent.length > 20", timeout=20000)
            assert w.locator("#chat-thread").get_attribute("aria-busy") == "true"
            assert w.locator("#chat-input").input_value() == "", "o texto sai do campo depois que o servidor confirma a pergunta"
            shot("02-respondendo")
            assert len(turns) - before == 1, f"envio duplicado: {len(turns) - before}"
            ok("streaming real, uma só geração, botão vira Interromper, texto limpo só depois da confirmação")

            # 5. Recolher e reabrir durante a resposta: nada se perde, nada é cancelado; ponto de novidade no ícone
            w.evaluate("conceal(); host.postMessage('widget:collapse')")
            assert w.locator("#chat-panel").is_hidden() and S()["streaming"] and "widget:panel:main" in msgs()
            assert orb.get_attribute("data-attn") == "busy" and "respondendo" in orb.get_attribute("aria-label")
            w.evaluate("document.body.dataset.expanded = 'false'")  # a janela encolheu
            w.wait_for_timeout(400)
            fakectl(release=True)
            idle()
            w.evaluate("document.body.dataset.expanded = 'true'")
            assert orb.get_attribute("data-attn") == "done" and "nova" in orb.get_attribute("aria-label")
            orb.click()
            expect(w.locator(".chat-msg.bot")).to_have_count(1)
            assert orb.get_attribute("data-attn") is None
            ok("recolher não cancela a resposta; novidade sinalizada no ícone; reabrir mostra a conversa completa")

            # 6. Resposta final: Markdown seguro, código com rolagem própria, link seguro, fontes reais, copiar
            ans = w.locator(".chat-msg.bot .chat-answer")
            assert ans.locator("h3").count() == 1 and ans.locator("ul li").count() == 3 and ans.locator("table").count() == 1 and ans.locator("blockquote").count() == 1
            assert w.locator(".chat-code").count() == 1 and w.locator(".chat-code pre").evaluate("n => n.scrollWidth > n.clientWidth"), "o bloco de código rola por dentro"
            no_hscroll()
            w.locator(".chat-answer a").click()
            assert "window:external:https://example.org/sono" in msgs(), "link sai pelo Lumen.exe"
            more = w.locator(".chat-more")
            assert more.inner_text().startswith("Fontes") and more.get_attribute("aria-expanded") == "false"
            expect(w.locator(".chat-sources")).to_be_hidden()
            more.click()
            expect(w.locator(".chat-sources")).to_be_visible()
            assert w.locator(".chat-src").count() >= 1 and "Memória e sono" in w.locator(".chat-src-title").first.inner_text()
            assert "Obsidian" in w.locator(".chat-src-meta").first.inner_text()
            shot("03-fontes")
            w.locator(".chat-src-open").first.click()
            expect(w.locator(".chat-src-status").first).to_contain_text("Obsidian")
            assert fakectl()["opened"] and fakectl()["opened"][0].endswith("Memória e sono.md"), "abriu o arquivo real do cofre"
            w.locator(".chat-cite").first.click()
            expect(w.locator(".chat-sources")).to_be_visible()
            w.locator(".chat-actions .chat-act", has_text="Copiar").first.click()
            expect(w.locator(".chat-actions .chat-act", has_text="Copiado").first).to_be_visible()
            copied = w.evaluate("navigator.clipboard.readText()")
            assert copied.startswith("## Como o sono ajuda") and "palavra219" in copied, "copiou a resposta inteira"
            ok("Markdown seguro, código rola por dentro, link pelo host, fontes reais (abrir confirma pelo servidor), citação abre a lista, copiar")

            # 7. A mesma conversa existe no servidor, com UMA pergunta e UMA resposta; o ponteiro aponta para ela
            cid = S()["conv"]["id"]
            conv = call("/api/study/conversation?id=" + cid)
            assert [m["role"] for m in conv["messages"]] == ["user", "assistant"], [m["role"] for m in conv["messages"]]
            assert conv["messages"][1]["sources"] and not conv["messages"][1]["meta"].get("free_mode")
            assert json.loads(w.evaluate("localStorage.getItem('lumen.quick.conv')"))["id"] == cid
            assert "skip_vault" in turns[-1] and turns[-1]["skip_vault"] is False and turns[-1]["conversation_id"] is None
            ok("a conversa mora em /api/study (1 pergunta, 1 resposta com fontes); o modo Notas foi enviado como skip_vault=false")

            # 8. Livre tem efeito real: o servidor não consulta o cofre e a resposta não tem fontes
            fakectl(reset=True, answer="Resposta direta, sem notas.")
            free_btn.click()
            w.locator("#chat-input").fill("Explique de outro jeito")
            w.keyboard.press("Enter")
            idle()
            assert turns[-1]["skip_vault"] is True and turns[-1]["conversation_id"] == cid, turns[-1]
            conv = call("/api/study/conversation?id=" + cid)
            last = conv["messages"][-1]
            assert last["meta"].get("free_mode") is True and last["sources"] == [], last
            bots = w.locator(".chat-msg.bot")
            expect(bots).to_have_count(2)
            assert bots.nth(1).locator(".chat-more").inner_text() == "Detalhes" and bots.nth(1).locator(".chat-tag").inner_text() == "Livre"
            assert call("/api/study/conversation?id=" + cid + "&brief=1")["generating"] is False
            ok("Livre: skip_vault=true chega ao agente, a resposta não tem fontes e vem marcada como Livre; mesma conversa continuada")

            # 9. Interromper no meio: parcial marcado, sem duplicar pergunta, espera o servidor liberar, tentar de novo reaproveita a pergunta
            notes_btn.click()
            fakectl(answer=LONG, delay=0.05, hold=30)
            w.locator("#chat-input").fill("Resuma de novo, com mais detalhes")
            w.keyboard.press("Enter")
            w.wait_for_function("() => document.querySelector('.chat-msg.bot.live .chat-answer')?.textContent.length > 20", timeout=20000)
            w.locator("#chat-send").click()
            assert w.locator("#chat-send").get_attribute("data-mode") in ("wait", "send")
            idle()
            assert w.locator(".chat-msg.bot.partial").count() == 1 and "não foi concluída" in w.locator(".chat-partial-tag").inner_text()
            assert w.locator(".chat-msg.bot").count() == 3 and w.locator(".chat-msg.bot:not(.partial)").count() == 2, "parcial não vira resposta concluída"
            fakectl(release=True)
            shot("04-interrompida")
            retry = w.locator(".chat-note-btn", has_text="Tentar de novo")
            retry.click()
            fakectl(reset=True, answer="Agora completa, sem notas." if False else "Agora completa [S1].")
            idle(60000)
            conv = call("/api/study/conversation?id=" + cid)
            users = [m for m in conv["messages"] if m["role"] == "user"]
            assert [m["content"] for m in users].count("Resuma de novo, com mais detalhes") == 1, "tentar de novo não duplica a pergunta"
            assert conv["messages"][-1]["role"] == "assistant" and w.locator(".chat-msg.bot.partial").count() == 0
            ok("interromper: parcial rotulado, servidor libera a conversa, tentar de novo usa a mesma pergunta (sem duplicar)")

            # 10. Falha ANTES da confirmação: o texto fica no campo, nada de bolha órfã; depois de confirmada: Tentar de novo sem duplicar
            w.route("**/api/study/turn", lambda r: r.abort())
            w.locator("#chat-input").fill("Esta não sai")
            w.keyboard.press("Enter")
            expect(w.locator(".chat-note[data-tone=error]")).to_be_visible()
            assert w.locator("#chat-input").input_value() == "Esta não sai" and w.locator(".chat-msg.user[data-state=sending]").count() == 0
            assert "Seu texto continua no campo" in w.locator(".chat-note[data-tone=error]").inner_text()
            assert w.locator("#chat-send").is_enabled()
            w.unroute("**/api/study/turn")
            fakectl(models=[])  # sem modelo: o servidor confirma a pergunta e só então não acha IA
            w.keyboard.press("Enter")
            expect(w.locator(".chat-note[data-tone=error]")).to_contain_text("não está instalado", timeout=20000)  # Rápido sem nenhum modelo local: erro claro (antes: "Nenhuma IA disponível")
            assert w.locator("#chat-input").input_value() == "", "confirmada pelo servidor: o campo limpa"
            n_users = len([m for m in call("/api/study/conversation?id=" + cid)["messages"] if m["role"] == "user"])
            fakectl(models=["qwen3:8b", "qwen3-embedding:0.6b", "qwen3.5:4b"], answer="Voltou a funcionar.")
            w.locator(".chat-note-btn", has_text="Tentar de novo").click()
            idle()
            conv = call("/api/study/conversation?id=" + cid)
            assert len([m for m in conv["messages"] if m["role"] == "user"]) == n_users, "tentar de novo não duplica a pergunta"
            assert conv["messages"][-1]["content"].startswith("Voltou"), conv["messages"][-1]["content"]
            ok("falha antes da confirmação preserva o texto; falha depois oferece Tentar de novo sem duplicar a pergunta nem a resposta")

            # 11. Rascunho: sobrevive a trocar de painel, recolher, reabrir e recarregar a página; nunca em localStorage
            w.locator("#chat-input").fill("rascunho que não pode sumir")
            w.locator("#settings").click()
            w.wait_for_function("() => !settingsBusy && preferences !== null")
            assert w.locator("#chat-panel").is_hidden() and w.locator("#preferences").is_visible()
            w.locator("#prefs-back").click()
            orb.click()
            assert w.locator("#chat-input").input_value() == "rascunho que não pode sumir"
            w.evaluate("conceal()"); orb.click()
            assert w.locator("#chat-input").input_value() == "rascunho que não pode sumir"
            w.wait_for_timeout(400)
            assert w.evaluate("sessionStorage.getItem('lumen.quick.draft')") == "rascunho que não pode sumir"
            assert "rascunho" not in json.dumps(w.evaluate("Object.fromEntries(Object.entries(localStorage))")), "texto pessoal fora do localStorage"
            w.reload(); w.wait_for_function("() => state !== null")
            w.locator("#chat-btn").click()
            assert w.locator("#chat-input").input_value() == "rascunho que não pode sumir"
            expect(w.locator(".chat-msg.bot").last).to_contain_text("Voltou a funcionar", timeout=15000)  # a conversa anterior continua disponível
            assert S()["conv"]["id"] == cid
            w.locator("#chat-input").fill("")
            ok("rascunho sobrevive a painel/recolher/recarga (sessionStorage); conversa anterior reabre sob demanda")

            # 12. Esc: primeiro o menu, depois recolhe a barra; nunca encerra o Lumen, interrompe a gravação nem a resposta
            w.locator("#chat-more").click()
            expect(w.locator(".chat-menu")).to_be_visible()
            n = len(msgs())
            w.keyboard.press("Escape")
            expect(w.locator(".chat-menu")).to_have_count(0)
            assert w.locator("#chat-panel").is_visible() and "widget:collapse" not in msgs()[n:] and "widget:panel:main" not in msgs()[n:], "o primeiro Esc só fechou o menu"
            w.keyboard.press("Escape")
            assert w.locator("#chat-panel").is_hidden() and "widget:collapse" in msgs()
            assert not [m for m in msgs() if m in ("window:exit",) or m.startswith("record:")]
            w.evaluate("document.body.dataset.expanded='true'")
            orb.click()
            ok("Esc fecha o menu e, depois, recolhe a barra; nunca sai do Lumen nem mexe na gravação")

            # 13. Nova conversa (histórico intacto) e temporária; "Abrir no Cérebro" leva o MESMO identificador
            brain = lambda: (w.locator("#chat-more").click(), w.locator("#chat-brain").click())  # noqa: E731  (Cérebro e nova conversa moram no menu "mais opções")
            brain()
            assert f"chat:open:{cid}" in msgs()
            w.locator("#chat-more").click()
            w.locator(".chat-menu button", has_text="Nova conversa temporária").click()
            assert S()["conv"] is None and w.locator("#chat-temp").is_visible() and w.locator("#chat-more").get_attribute("aria-expanded") == "false"
            assert call("/api/study/conversation?id=" + cid)["id"] == cid, "a anterior continua no histórico"
            fakectl(answer="Anotado, só aqui.")
            w.locator("#chat-input").fill("pergunta temporária")
            w.keyboard.press("Enter")
            idle()
            tid = S()["conv"]["id"]
            assert tid.startswith("tmp-") and turns[-1]["temporary"] is True
            ids = [c["id"] for c in call("/api/study/conversations")["conversations"]]
            assert tid in ids and not any(c["id"] == tid and not c.get("temporary") for c in call("/api/study/conversations")["conversations"])
            brain()
            assert f"chat:open:{tid}" in msgs()
            ok("nova conversa não apaga o histórico; temporária fica temporária; Abrir no Cérebro envia o mesmo id")

            # 14. Cérebro: abre a MESMA conversa (id, mensagens, modo) sem reenviar nada; temporária continua temporária
            main = context.new_page(); main.set_viewport_size({"width": 1120, "height": 860})
            main.goto(url + "/?frame=1")
            main.wait_for_function("() => S !== null")
            sent_before = len(turns)
            main.evaluate("""id => hostListeners.forEach(fn => fn({data: 'desktop:chat:' + id}))""", cid)
            main.wait_for_function("() => document.querySelector('[data-study] .st-msg')", timeout=10000)
            main.wait_for_function("id => window.lumenStudy.S.conv?.id === id", arg=cid)
            assert not main.locator("#view-study").is_hidden() and main.locator("[data-study] .st-msg.user").count() >= 3
            assert main.evaluate("window.lumenStudy.vault.get().free") is False
            main.evaluate("""id => hostListeners.forEach(fn => fn({data: 'desktop:chat:' + id}))""", tid)
            main.wait_for_function("id => window.lumenStudy.S.conv?.id === id", arg=tid)
            assert main.evaluate("window.lumenStudy.S.conv.temporary") is True and len(turns) == sent_before, "abrir não reenvia a pergunta"
            main.evaluate("""() => hostListeners.forEach(fn => fn({data: 'desktop:chat:../../etc'}))""")
            main.wait_for_timeout(300)
            assert main.evaluate("window.lumenStudy.S.conv.id") == tid, "id inválido é ignorado"
            shot("05-cerebro-mesma-conversa", main)
            # o modo muda no Cérebro e a barra acompanha (mesmas chaves, evento storage)
            main.evaluate("window.lumenStudy.vault.set(true, null)")
            w.wait_for_function("() => QuickChat.state().vault.free === true")
            main.evaluate("window.lumenStudy.vault.set(false, null)")
            w.wait_for_function("() => QuickChat.state().vault.free === false")
            ok("Cérebro abre o mesmo id (permanente e temporária), sem reenviar, ignora id inválido; o modo Livre/Notas é um só nas duas janelas")

            # 15. Uma geração por conversa, em qualquer janela: a barra espera; o servidor recusa a segunda
            fakectl(answer=LONG, delay=0.05, hold=25)
            import threading
            second = {}

            def other_window():
                req = urllib.request.Request(url + "/api/study/turn", data=json.dumps({"text": "pergunta feita no Cérebro", "conversation_id": cid, "turn_id": "outrajanela0001"}).encode(),
                                             headers={"X-Lumen-Token": page_token["v"], "Content-Type": "application/json"})
                with urllib.request.urlopen(req) as r:
                    second["events"] = [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]
            t = threading.Thread(target=other_window); t.start()
            for _ in range(100):
                if call("/api/study/conversation?brief=1&id=" + cid)["generating"]:
                    break
                time.sleep(0.1)
            assert call("/api/study/conversation?brief=1&id=" + cid)["generating"] is True
            dup = call_turn = urllib.request.Request(url + "/api/study/turn", data=json.dumps({"text": "segunda ao mesmo tempo", "conversation_id": cid}).encode(),
                                                     headers={"X-Lumen-Token": page_token["v"], "Content-Type": "application/json"})
            events = [json.loads(line) for line in urllib.request.urlopen(dup).read().decode().splitlines() if line.strip()]
            assert events and events[0]["type"] == "error" and events[0]["code"] == "conversation_busy", events
            # a barra volta a abrir (como depois de reiniciar o Lumen) na conversa que está respondendo em outra janela
            w.evaluate("id => localStorage.setItem('lumen.quick.conv', JSON.stringify({id}))", cid)
            w.reload(); w.wait_for_function("() => state !== null")
            w.locator("#chat-btn").click()
            w.wait_for_function("() => QuickChat.state().elsewhere", timeout=15000)
            assert w.locator("#chat-send").is_disabled() and "outra janela" in w.locator("#chat-input").get_attribute("placeholder")
            assert w.locator(".chat-stage.elsewhere").is_visible()
            w.locator("#chat-more").click()
            assert w.locator("#chat-menu-new").is_disabled() and w.locator("#chat-menu-temp").is_disabled() and w.locator("#chat-brain").is_enabled(), "esperando a outra janela: só o Cérebro segue livre"
            w.keyboard.press("Escape")
            shot("06-respondendo-em-outra-janela")
            fakectl(release=True)
            t.join(60)
            w.wait_for_function("() => !QuickChat.state().elsewhere", timeout=15000)
            expect(w.locator(".chat-msg.user").last).to_contain_text("pergunta feita no Cérebro")
            expect(w.locator(".chat-msg.bot").last).to_be_visible()
            ok("duas gerações na mesma conversa são recusadas pelo servidor; a barra espera a outra janela e relê o resultado")
            fakectl(reset=True, answer="ok")

            # 16. Conversa apagada em outra janela: aviso claro, texto preservado
            call("/api/study/conversations", {"action": "delete", "id": cid})
            w.locator("#chat-input").fill("mensagem depois de apagada")
            w.keyboard.press("Enter")
            expect(w.locator(".chat-note[data-tone=warn]")).to_contain_text("apagada em outra janela", timeout=15000)
            assert w.locator("#chat-input").input_value() == "mensagem depois de apagada" and S()["conv"] is None
            w.keyboard.press("Enter")
            idle()
            assert S()["conv"]["id"] != cid and len(call("/api/study/conversation?id=" + S()["conv"]["id"])["messages"]) == 2
            ok("conversa apagada em outra janela: aviso, texto mantido e a próxima mensagem abre uma conversa nova")

            # 17. Comandos "/" não saem como texto (têm confirmações próprias no Cérebro)
            n = len(turns)
            w.locator("#chat-input").fill("/imagem um gato")
            w.keyboard.press("Enter")
            assert len(turns) == n and "funcionam no Cérebro" in w.locator(".chat-note").last.inner_text() and w.locator("#chat-input").input_value() == "/imagem um gato"
            w.locator("#chat-input").fill("")
            ok('comandos "/" não são enviados como texto (o envio externo e o custo têm confirmação só no Cérebro)')

            # 18. Rolagem: durante uma resposta longa, quem subiu para ler não é puxado para baixo
            fakectl(answer=LONG + " " + LONG, delay=0.02, hold=140)
            w.locator("#chat-input").fill("Faça um texto bem longo para eu ler")
            w.keyboard.press("Enter")
            w.wait_for_function("() => { const t = document.querySelector('#chat-thread'); return t.scrollHeight > t.clientHeight + 200 && document.querySelector('.chat-msg.bot.live') }", timeout=20000)
            w.evaluate("document.querySelector('#chat-thread').scrollTop = 0")
            w.wait_for_timeout(300)
            top_before = w.evaluate("document.querySelector('#chat-thread').scrollTop")
            fakectl(release=True)
            w.wait_for_timeout(1500)
            assert w.evaluate("document.querySelector('#chat-thread').scrollTop") <= top_before + 2, "a resposta não puxou a rolagem de quem subiu"
            assert w.locator("#chat-bottom").is_visible()
            w.locator("#chat-bottom").click()
            idle(60000)
            assert w.evaluate("(() => { const t = document.querySelector('#chat-thread'); return t.scrollHeight - t.scrollTop - t.clientHeight <= 4 })()")
            no_hscroll()
            shot("07-resposta-longa")
            ok("rolagem automática só perto do fim; botão para voltar ao fim; sem rolagem horizontal")
            fakectl(reset=True, answer="ok")

            # 19. Gravação: o indicador discreto aparece com a gravação ativa (e some sem ela); a barra de gravar continua à mão
            w.evaluate("QuickChat.recording({active: true, seconds: 75, paused: false})")
            expect(w.locator("#chat-rec")).to_be_visible()
            assert w.locator("#chat-rec-text").inner_text() == "01:15" and w.locator("#chat-rec").get_attribute("aria-label") == "Gravação em andamento"
            for sel in ("#chat-title", "#chat-more", "#chat-collapse", "#chat-rec"):
                inside(sel)
            shot("08-durante-gravacao")
            w.evaluate("QuickChat.recording({active: true, seconds: 80, paused: true})")
            assert w.locator("#chat-rec-text").inner_text() == "Pausada"
            w.evaluate("QuickChat.recording({active: false})")
            expect(w.locator("#chat-rec")).to_be_hidden()
            assert w.locator("#action").is_visible() and w.locator("#action").is_enabled(), "gravar continua à mão com a conversa aberta"
            ok("indicador de gravação discreto no cabeçalho; botão de gravar continua disponível")

            # 19b. Foco e mouse: com a conversa aberta e o foco na barra, o mouse sair NÃO recolhe (nem escrevendo); só clicar em outro programa
            n = len(msgs())
            w.locator("#chat-input").focus()
            w.locator("#chat-input").fill("estou escrevendo")
            w.mouse.move(2000, 2000)
            w.evaluate("document.documentElement.dispatchEvent(new PointerEvent('pointerleave'))")
            w.wait_for_timeout(1000)
            assert "widget:collapse" not in msgs()[n:] and w.locator("#chat-panel").is_visible(), "escrevendo, o mouse sair não recolhe"
            w.locator("#chat-input").fill("")
            w.locator("#chat-thread").focus()
            w.evaluate("document.documentElement.dispatchEvent(new PointerEvent('pointerleave'))")
            w.wait_for_timeout(1000)
            assert "widget:collapse" not in msgs()[n:], "conversando com o foco na barra, o mouse sair não recolhe"
            w.evaluate("window.__hasFocus = document.hasFocus.bind(document); document.hasFocus = () => false; window.dispatchEvent(new Event('blur'))")
            w.wait_for_function("n => messages.slice(n).includes('widget:collapse')", arg=n, timeout=4000)
            assert w.locator("#chat-panel").is_hidden(), "clicar em outro programa recolhe a barra"
            w.evaluate("document.hasFocus = window.__hasFocus; document.body.dataset.expanded = 'true'")
            orb.click()
            expect(w.locator("#chat-panel")).to_be_visible()
            ok("mouse fora não recolhe a conversa com foco (nem escrevendo); perder o foco para outro programa recolhe")

            # 19c. Recarga do WebView2 no meio da resposta: a pergunta confirmada aparece sem resposta, tentar de novo não duplica
            fakectl(reset=True)
            fakectl(answer=LONG, delay=0.05, hold=20)
            w.locator("#chat-input").fill("Pergunta cortada pela recarga")
            w.keyboard.press("Enter")
            w.wait_for_function("() => document.querySelector('.chat-msg.bot.live .chat-answer')?.textContent.length > 10", timeout=20000)
            cid2 = S()["conv"]["id"]
            w.reload()  # o processo da página morreu e foi recarregado (WidgetForm.Recover): a conexão da resposta cai
            w.wait_for_function("() => state !== null")
            fakectl(release=True)
            w.locator("#chat-btn").click()
            expect(w.locator(".chat-note", has_text="ficou sem resposta")).to_be_visible(timeout=30000)
            assert S()["conv"]["id"] == cid2 and not S()["streaming"]
            fakectl(reset=True, answer="Resposta depois da recarga.")
            w.locator(".chat-note-btn", has_text="Tentar de novo").click()
            idle(30000)
            conv = call("/api/study/conversation?id=" + cid2)
            assert [m["content"] for m in conv["messages"] if m["role"] == "user"].count("Pergunta cortada pela recarga") == 1 and conv["messages"][-1]["content"].startswith("Resposta depois")
            ok("recarga do WebView2 no meio da resposta: a pergunta volta sem resposta, tentar de novo reaproveita-a sem duplicar")

            # 20. Movimento reduzido, quatro bordas e janela pequena
            w.emulate_media(reduced_motion="reduce")
            assert w.locator(".chat-panel").evaluate("n => getComputedStyle(n).animationName") == "none"
            assert w.locator("#chat-rec i").evaluate("n => getComputedStyle(n).animationName") == "none"
            w.emulate_media(reduced_motion="no-preference")
            for edge, size in (("left", (304, 252)), ("right", (304, 252)), ("top", (304, 252)), ("bottom", (304, 252)), ("left", (360, 480))):
                w.evaluate("edge => { hostListeners.forEach(fn => fn({data: 'edge:' + edge})); hostListeners.forEach(fn => fn({data: 'side:' + (edge === 'right' ? 'right' : 'left')})) }", edge)
                w.set_viewport_size({"width": size[0], "height": size[1]})
                w.wait_for_timeout(250)
                for sel in ("#chat-title", "#chat-more", "#chat-collapse", "#chat-mode", "#chat-input", "#chat-send", "#chat-btn"):
                    inside(sel, *size)
                nb = box(".notch")
                assert abs(nb["width"] - size[0]) <= 1 and abs(nb["height"] - size[1]) <= 1, (edge, size, nb)  # o painel é a janela, não um tamanho próprio
                no_hscroll()
                if size == (304, 252): shot(f"09-borda-{edge}")
                else: shot("10-janela-ampliada-menor-que-540")
            w.set_viewport_size({"width": 304, "height": 252})
            ok("quatro bordas na janela compacta e uma janela ampliada limitada pela tela: o painel acompanha a janela; movimento reduzido sem animação")

            # 21. Custo de redesenhar a resposta em escrita (o que acontece ~11 vezes por segundo): mede o pior caso, o texto inteiro a cada vez
            cost = w.evaluate("""() => {
                const out = {};
                for (const words of [150, 800, 2500]) {
                    const text = ('## Título\\n\\n' + 'Parágrafo com **negrito**, `código` e [S1] citada. '.repeat(8) + '\\n\\n- item\\n- item\\n\\n').repeat(Math.ceil(words / 70));
                    const t = []; for (let i = 0; i < 15; i++) { const a = performance.now(); document.createElement('div').replaceChildren(LumenMd.md(text, { cite: (s) => document.createTextNode(s) })); t.push(performance.now() - a); }
                    t.sort((x, y) => x - y); out[words] = Math.round(t[7] * 10) / 10;
                }
                return out; }""")
            report["custo_redesenho_ms_mediana"] = cost
            print("  medida: redesenhar a resposta inteira (mediana, ms):", cost)
            assert cost["800"] < 40, f"redesenho de 800 palavras lento demais: {cost}"
            ok("custo de redesenhar a resposta em escrita medido (ver relatório)")

            assert not errors, errors
            browser.close()
        report["result"] = "OK"
    finally:
        if errors:
            print("ERROS DA PÁGINA:", *errors[:10], sep="\n  ")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        (ART / "chat-ui-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {len(report['checks'])} blocos de verificação da Conversa rápida; imagens em {ART}")
