"""Conversa rápida: a conversa cabe na janela COMPACTA da barra (304×252) e acompanha a área que a janela entrega.

Regressão do corte (09/11/2026): com o executável antigo aberto, a janela ficava em 304×252 (ele não conhece widget:panel:chat) e a página
desenhava um painel de 420×620 deslocado para dentro e para cima da janela: o campo saía pela lateral, o cabeçalho e o seletor ficavam fora.
O teste emula a janela nativa pelo viewport e confere, em cada cenário:

  - o .notch coincide com a janela (nada de tamanho próprio do painel);
  - cabeçalho, menu, Livre/Notas, mensagens, campo e enviar existem, estão visíveis, DENTRO da janela e dos recortes (overflow) de todos os
    ancestrais, e recebem clique (elementFromPoint em 5 pontos + clique de teste do Playwright);
  - nenhum elemento ultrapassa a largura do painel (código e tabela rolam no próprio bloco) e o painel/a lista não têm overflow oculto;
  - a lista de mensagens mantém uma altura mínima; o campo cresce só até uma fração do painel e depois rola por dentro.

  py -3.14 tests/chat_compact.py                       código atual
  CHAT_LEGACY=1  janela que ignora o pedido de tamanho (executável antigo)
  CHAT_COMMON_ONLY=1 CHAT_ROOT=<outra cópia>  roda contra o código antigo para provar que o teste FALHA com ele

Provas de device_scale_factor aqui NÃO provam o DPI da janela WinForms/WebView2 (isso é de tests/DesktopChecks.cs)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from chat_harness import LONG, serve  # noqa: E402

ROOT = Path(os.environ.get("CHAT_ROOT", Path(__file__).resolve().parents[1]))
ART = Path(os.environ.get("CHAT_ARTIFACTS", ROOT / "tests/desktop-artifacts/conversa-compacta"))
ART.mkdir(parents=True, exist_ok=True)
LEGACY = os.environ.get("CHAT_LEGACY") == "1"
COMMON_ONLY = os.environ.get("CHAT_COMMON_ONLY") == "1"
TAG = os.environ.get("CHAT_TAG", "")

HOST = "window.messages=[]; window.hostListeners=[]; window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(t,fn)=>hostListeners.push(fn)};"
SIZES = {"widget:panel:main": (304, 252), "widget:panel:chat": (304, 252), "widget:panel:chat-wide": (360, 540)}
COMMON = ["#chat-title", "#chat-collapse", "#chat-mode", "#chat-input", "#chat-send", "#chat-thread", "#chat-form"]
ESSENTIAL = COMMON + ([] if COMMON_ONLY else ["#chat-more"])
RAIL = ["#open", "#action", "#chat-btn", "#settings", "#drag"]

CHECK = r"""([essentials, minThread, rail]) => {
  const out = [];
  const vw = innerWidth, vh = innerHeight, R = (e) => e.getBoundingClientRect(), q = (s) => document.querySelector(s);
  const round = (n) => Math.round(n);
  const notch = R(q('.notch'));
  if (Math.abs(notch.left) > 1.5 || Math.abs(notch.top) > 1.5 || Math.abs(notch.width - vw) > 1.5 || Math.abs(notch.height - vh) > 1.5)
    out.push(`.notch ${round(notch.left)},${round(notch.top)} ${round(notch.width)}x${round(notch.height)} não coincide com a janela ${vw}x${vh}`);
  const panel = q('#chat-panel');
  if (panel.hidden) return out.concat('painel da conversa oculto');
  const pr = R(panel);
  if (pr.left < -0.5 || pr.top < -0.5 || pr.right > vw + 0.5 || pr.bottom > vh + 0.5)
    out.push(`painel fora da janela: ${[pr.left, pr.top, pr.right, pr.bottom].map(round)} em ${vw}x${vh}`);
  const clipOf = (el) => {
    let c = { l: 0, t: 0, r: vw, b: vh };
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.overflowX !== 'visible' || s.overflowY !== 'visible') { const b = R(p); c = { l: Math.max(c.l, b.left), t: Math.max(c.t, b.top), r: Math.min(c.r, b.right), b: Math.min(c.b, b.bottom) }; }
    }
    return c;
  };
  const reach = (sel, el) => {
    const cs = getComputedStyle(el), r = R(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || r.width < 4 || r.height < 4) { out.push(`${sel}: invisível`); return; }
    const c = clipOf(el);
    if (r.left < c.l - .5 || r.top < c.t - .5 || r.right > c.r + .5 || r.bottom > c.b + .5)
      out.push(`${sel}: cortado ou fora (${[r.left, r.top, r.right, r.bottom].map(round)} em ${[c.l, c.t, c.r, c.b].map(round)})`);
    const i = Math.min(9, r.width / 4, r.height / 4);
    const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + i, r.top + i], [r.right - i, r.top + i], [r.left + i, r.bottom - i], [r.right - i, r.bottom - i]];
    const bad = pts.filter(([x, y]) => { if (x < 0 || y < 0 || x >= vw || y >= vh) return true; const t = document.elementFromPoint(x, y); return !(t && (el === t || el.contains(t) || (sel === '#chat-thread' && t.closest('.chat-bottom')))); });  // o "ir para o fim" é um controle visível sobre o canto da lista
    if (bad.length) out.push(`${sel}: ${bad.length}/5 pontos não recebem clique`);
  };
  for (const sel of essentials) { const el = q(sel); if (!el) out.push(`${sel}: não existe`); else reach(sel, el); }
  for (const sel of rail) { const el = q(sel); if (el && !el.hidden) reach(sel, el); }
  // largura: nada passa do painel, a não ser dentro de um bloco que rola (código, tabela)
  for (const el of panel.querySelectorAll('*')) {
    if (el.closest('svg') && el.tagName !== 'svg') continue;
    if (el.parentElement.closest('pre, .st-table')) continue;
    const cs = getComputedStyle(el), r = R(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || (!r.width && !r.height)) continue;
    if (r.left < pr.left - .5 || r.right > pr.right + .5) out.push(`${el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0]} passa da largura do painel (${round(r.left)}..${round(r.right)} em ${round(pr.left)}..${round(pr.right)})`);
  }
  if (panel.scrollWidth > panel.clientWidth + 1) out.push(`painel com overflow horizontal ${panel.scrollWidth}>${panel.clientWidth}`);
  if (panel.scrollHeight > panel.clientHeight + 1) out.push(`painel com overflow vertical ${panel.scrollHeight}>${panel.clientHeight}`);
  const ta = q('#chat-input');
  if (ta && !ta.value && ta.scrollHeight > ta.clientHeight + 1) out.push(`campo vazio com rolagem (a dica "${ta.placeholder}" quebrou de linha: ${ta.scrollHeight}>${ta.clientHeight})`);
  const th = q('#chat-thread');
  if (th.scrollWidth > th.clientWidth + 1) out.push(`lista de mensagens com overflow horizontal oculto ${th.scrollWidth}>${th.clientWidth}`);
  const head = q('.chat-head'), mode = q('.chat-modebar'), form = q('#chat-form');
  if (head && mode && form) {
    const hb = R(head), mb = R(mode), tb = R(th), fb = R(form);
    if (hb.bottom > mb.top + 1 || mb.bottom > tb.top + 1 || tb.bottom > fb.top + 1) out.push('blocos sobrepostos (cabeçalho, modo, mensagens, campo)');
    if (tb.height < minThread) out.push(`lista de mensagens com só ${round(tb.height)}px (mínimo ${minThread})`);
    if (fb.height > pr.height * 0.34 + 16) out.push(`campo ocupa ${round(fb.height)}px de ${round(pr.height)}px do painel`);
  }
  return out;
}"""

FAILS = []
REPORT = {"tag": TAG, "legacy_host": LEGACY, "root": str(ROOT), "scenarios": []}


def soft(name):
    """Decorador: roda o cenário, registra falha (sem parar) e segue."""
    def wrap(fn):
        def run(*a, **kw):
            try:
                fn(*a, **kw)
                REPORT["scenarios"].append({"nome": name, "ok": True})
                print("  ok:", name, flush=True)
            except Exception as e:  # noqa: BLE001
                msg = f"{name}: {type(e).__name__}: {str(e).splitlines()[0][:600] if str(e) else ''}"
                FAILS.append(msg)
                REPORT["scenarios"].append({"nome": name, "ok": False, "erro": str(e)[:1500]})
                print("  FALHOU:", msg, flush=True)
        return run
    return wrap


def main():
    with serve(ROOT, ART) as H, sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
        errors = []

        def new_ctx(dsf=2, reduced=None, vw=304, vh=252):
            ctx = browser.new_context(viewport={"width": vw, "height": vh}, screen={"width": 1920, "height": 1080}, device_scale_factor=dsf,
                                      reduced_motion=reduced, permissions=["clipboard-read", "clipboard-write"])
            ctx.add_init_script(HOST)
            ctx.on("page", lambda pg: pg.on("pageerror", lambda e: errors.append(str(e))))
            return ctx

        def open_page(ctx, edge="left", clear=True):
            pg = ctx.new_page()
            pg.goto(H.url + "/widget")
            pg.wait_for_function("() => state !== null")
            if clear:
                pg.evaluate("localStorage.clear(); sessionStorage.clear()")
                pg.reload(); pg.wait_for_function("() => state !== null")
            set_edge(pg, edge)
            return pg

        def set_edge(pg, edge):
            side = "right" if edge in ("right", "free-right") else "left"
            pg.evaluate("([e, s]) => { hostListeners.forEach(fn => fn({data: 'side:' + s})); hostListeners.forEach(fn => fn({data: 'edge:' + e}));  }", [edge.replace("-right", "").replace("-left", ""), side])
            pg.wait_for_timeout(60)

        def last_panel_msg(pg):
            return pg.evaluate("messages.filter(m => m.startsWith('widget:panel:')).slice(-1)[0] || null")

        def settle(pg):
            pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            pg.wait_for_timeout(260)  # o painel termina de entrar (fade-in) antes de medir o clique

        def follow(pg, request=None):
            """A janela nativa obedece ao último pedido de tamanho (o executável antigo não conhece o pedido: a janela fica como estava)."""
            msg = request or last_panel_msg(pg)
            if msg in SIZES and not LEGACY:
                pg.set_viewport_size({"width": SIZES[msg][0], "height": SIZES[msg][1]})
            settle(pg)

        def open_chat(pg):
            pg.locator("#chat-btn").click()
            expect(pg.locator("#chat-panel")).to_be_visible()
            follow(pg)

        def check(pg, label, minthread=60, extra=()):
            problems = pg.evaluate(CHECK, [ESSENTIAL + list(extra), minthread, RAIL])
            assert not problems, f"{label}: " + " | ".join(problems)

        def clickable(pg, label, sels):
            bad = []
            for s in sels:
                try:
                    pg.locator(s).first.click(trial=True, timeout=2500)
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{s} ({type(e).__name__})")
            assert not bad, f"{label}: sem clique de teste: " + ", ".join(bad)

        def shot(pg, name):
            pg.screenshot(path=str(ART / f"{TAG + '-' if TAG else ''}{name}.png"), animations="disabled")

        # ---------- A. estado vazio nas quatro bordas e em posição livre ----------
        @soft("A. estado vazio: janela 304×252, esquerda/direita/em cima/embaixo/livre — controles dentro, visíveis e clicáveis")
        def scenario_a():
            ctx = new_ctx()
            for edge in ("left", "right", "top", "bottom", "free-left", "free-right"):
                pg = open_page(ctx, edge)
                open_chat(pg)
                assert pg.evaluate("[innerWidth, innerHeight]") == [304, 252], pg.evaluate("[innerWidth, innerHeight]")
                min_thread = 56 if edge in ("top", "bottom") else 90
                check(pg, f"vazio/{edge}", min_thread)
                clickable(pg, f"vazio/{edge}", ["#chat-collapse", "#chat-input", "#chat-mode [data-mode=free]", "#chat-mode [data-mode=notes]"] + ([] if COMMON_ONLY else ["#chat-more"]))
                if edge in ("left", "right", "top", "bottom"):
                    shot(pg, f"01-vazio-{edge}")
                pg.close()
            ctx.close()

        scenario_a()

        # ---------- B. conversa de verdade (Notas, fontes, código, tabela, URL longa) nas quatro bordas ----------
        @soft("B. conversa real no modo Notas: mensagens, código, tabela, URL longa e fontes não alargam nem cortam o painel")
        def scenario_b():
            ctx = new_ctx()
            pg = open_page(ctx, "left")
            open_chat(pg)
            H.fakectl(answer=LONG)
            pg.locator("#chat-input").fill("Como o sono ajuda a memória?")
            pg.keyboard.press("Enter")
            pg.wait_for_function("() => { const s = QuickChat.state(); return !s.streaming && !s.cancelling && s.messages >= 2 }", timeout=40000)
            H.fakectl(reset=True)
            H.fakectl(answer="Anotado [S1].")
            pg.locator("#chat-input").fill("https://example.org/" + "um-trecho-sem-espaco-" * 12 + "fim")
            pg.keyboard.press("Enter")
            pg.wait_for_function("() => { const s = QuickChat.state(); return !s.streaming && !s.cancelling && s.messages >= 4 }", timeout=40000)
            settle(pg)
            shot(pg, "02-conversa-esquerda")
            for edge in ("left", "right", "top", "bottom"):
                set_edge(pg, edge); settle(pg)
                min_thread = 56 if edge in ("top", "bottom") else 90
                pg.evaluate("document.querySelector('#chat-thread').scrollTop = 0"); settle(pg)
                check(pg, f"conversa/{edge} (topo)", min_thread)
                pg.evaluate("document.querySelector('#chat-thread').scrollTop = 1e6"); settle(pg)
                check(pg, f"conversa/{edge} (fim)", min_thread)
                assert pg.evaluate("[...document.querySelectorAll('.chat-code pre')].every(n => n.scrollWidth > n.clientWidth)"), "o código deve rolar por dentro do próprio bloco"
                assert pg.evaluate("document.querySelector('.st-table').scrollWidth >= document.querySelector('.st-table').clientWidth")
                if edge == "right": shot(pg, "03-conversa-direita")
            set_edge(pg, "left"); settle(pg)
            # fontes (Notas): a lista abre dentro do painel e "Abrir" é clicável
            first = pg.locator(".chat-msg.bot .chat-more").first
            first.scroll_into_view_if_needed(); first.click(); settle(pg)
            pg.locator(".chat-sources").first.scroll_into_view_if_needed(); settle(pg)
            sr = pg.locator(".chat-sources").first.bounding_box()
            assert sr and sr["x"] >= 0 and sr["x"] + sr["width"] <= 304, sr
            pg.locator(".chat-src-open").first.click(trial=True, timeout=2500)
            check(pg, "conversa com fontes abertas", 90)
            shot(pg, "04-notas-com-fontes")
            ctx.close()

        scenario_b()

        # ---------- C. campo com várias linhas ----------
        @soft("C. campo com várias linhas: cresce só até a fração do painel e rola por dentro; enviar sempre à vista")
        def scenario_c():
            ctx = new_ctx()
            for edge in ("left", "top"):
                pg = open_page(ctx, edge)
                open_chat(pg)
                one = pg.locator("#chat-form").bounding_box()["height"]
                pg.locator("#chat-input").fill("\n".join(f"linha {n} da pergunta comprida" for n in range(1, 15)))
                settle(pg)
                form = pg.locator("#chat-form").bounding_box()
                assert form["height"] > one + 15, "o campo cresce"
                assert pg.evaluate("(() => { const t = document.querySelector('#chat-input'); return t.scrollHeight > t.clientHeight + 2 })()"), "ao atingir o limite, rola por dentro"
                check(pg, f"várias linhas/{edge}", 40 if edge == "top" else 56)
                clickable(pg, f"várias linhas/{edge}", ["#chat-send", "#chat-input", "#chat-collapse"])
                if edge == "left": shot(pg, "05-campo-varias-linhas")
                pg.locator("#chat-input").fill("")
                settle(pg)
                assert abs(pg.locator("#chat-form").bounding_box()["height"] - one) < 2, "esvaziado, volta a uma linha"
                pg.close()
            ctx.close()

        scenario_c()

        # ---------- E. menu ----------
        @soft("E. menu: cabe no painel, todas as ações alcançáveis, Esc fecha o menu antes de recolher")
        def scenario_e():
            if COMMON_ONLY:
                raise AssertionError("sem menu na versão antiga")
            ctx = new_ctx()
            for edge in ("left", "right", "top", "bottom"):
                pg = open_page(ctx, edge)
                open_chat(pg)
                pg.locator("#chat-more").click()
                expect(pg.locator(".chat-menu")).to_be_visible()
                settle(pg)
                mb = pg.locator(".chat-menu").bounding_box(); panel = pg.locator("#chat-panel").bounding_box()
                assert mb["x"] >= panel["x"] - .5 and mb["x"] + mb["width"] <= panel["x"] + panel["width"] + .5 and mb["y"] >= panel["y"] - .5 and mb["y"] + mb["height"] <= panel["y"] + panel["height"] + .5, (edge, mb, panel)
                assert pg.locator(".chat-menu button").count() == 5  # + "Ajustes desta conversa"
                for item in ("#chat-menu-new", "#chat-menu-temp", "#chat-brain", "#chat-size", "#chat-menu-settings"):
                    pg.locator(item).scroll_into_view_if_needed()
                    pg.locator(item).click(trial=True, timeout=2500)
                collapses = lambda: pg.evaluate("messages.filter(m => m === 'widget:collapse').length")  # noqa: E731
                pg.keyboard.press("Escape")
                expect(pg.locator(".chat-menu")).to_have_count(0)
                assert collapses() == 0, "o primeiro Esc só fecha o menu (não recolhe a barra)"
                assert pg.evaluate("document.activeElement.id") == "chat-more", "o foco volta ao botão que abriu o menu"
                pg.keyboard.press("Escape")
                assert collapses() == 1, "o segundo Esc recolhe a barra"
                if edge == "left":
                    open_chat(pg) if pg.locator("#chat-panel").is_hidden() else None
                    pg.locator("#chat-more").click(); settle(pg); shot(pg, "06-menu")
                pg.close()
            ctx.close()

        scenario_e()

        # ---------- F. streaming e erro ----------
        @soft("F. resposta em andamento (Interromper) e erro dentro do painel compacto")
        def scenario_f():
            ctx = new_ctx()
            pg = open_page(ctx, "left")
            open_chat(pg)
            H.fakectl(answer=LONG, delay=0.03)
            H.fakectl(hold=30)
            pg.locator("#chat-input").fill("Explique com detalhes")
            pg.keyboard.press("Enter")
            pg.wait_for_function("() => QuickChat.state().streaming")
            pg.wait_for_function("() => document.querySelector('.chat-msg.bot.live .chat-answer')?.textContent.length > 20", timeout=20000)
            settle(pg)
            assert pg.locator("#chat-send").get_attribute("data-mode") == "stop"
            check(pg, "streaming", 60)
            clickable(pg, "streaming", ["#chat-send"])
            shot(pg, "07-respondendo")
            H.fakectl(release=True)
            pg.wait_for_function("() => { const s = QuickChat.state(); return !s.streaming && !s.cancelling }", timeout=40000)
            H.fakectl(reset=True)
            pg.route("**/api/study/turn", lambda r: r.abort())
            pg.locator("#chat-input").fill("Esta não sai")
            pg.keyboard.press("Enter")
            expect(pg.locator(".chat-note[data-tone=error]")).to_be_visible()
            settle(pg)
            check(pg, "erro", 60)
            shot(pg, "08-erro")
            pg.unroute("**/api/study/turn")
            ctx.close()

        scenario_f()

        # ---------- G. abrir/recolher repetidamente ----------
        @soft("G. abrir/recolher 24 vezes (inclusive cliques rápidos): painel e janela sempre coerentes, nada preso")
        def scenario_g():
            ctx = new_ctx()
            pg = open_page(ctx, "left")
            for i in range(24):
                pg.locator("#chat-btn").click()
                if i % 3 == 0:
                    pg.locator("#chat-btn").click(); pg.locator("#chat-btn").click()  # clique rápido: abre, fecha, abre
                follow(pg)
                panel = pg.evaluate("document.body.dataset.panel")
                last = last_panel_msg(pg)
                assert panel == "chat" and last in ("widget:panel:chat",), (i, panel, last)
                check(pg, f"ciclo {i}", 90)
                pg.locator("#chat-collapse").click()
                assert pg.evaluate("document.body.dataset.panel") != "chat" and last_panel_msg(pg) == "widget:panel:main", (i, last_panel_msg(pg))
                pg.evaluate("document.body.dataset.expanded = 'true'")  # a barra volta a aparecer (hover)
                follow(pg)
                pg.locator("#action").click(trial=True, timeout=2500)  # painel da gravação sem nada invisível por cima
            ctx.close()

        scenario_g()

        # ---------- H. ampliar / reduzir, com a janela crescendo aos poucos ----------
        @soft("H. ampliar e reduzir: a janela cresce em passos e nenhum controle essencial fica cortado em nenhum passo")
        def scenario_h():
            if COMMON_ONLY:
                raise AssertionError("sem Ampliar na versão antiga")
            ctx = new_ctx()
            for edge in ("left", "right", "top", "bottom"):
                pg = open_page(ctx, edge)
                open_chat(pg)
                pg.locator("#chat-more").click()
                pg.locator("#chat-size").click()
                assert last_panel_msg(pg) == "widget:panel:chat-wide" and pg.evaluate("document.body.dataset.chatSize") == "wide"
                steps = 8
                for i in range(1, steps + 1):
                    t = i / steps
                    pg.set_viewport_size({"width": round(304 + 56 * t), "height": round(252 + 288 * t)})
                    pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                    check(pg, f"ampliando/{edge} passo {i}", 40)
                settle(pg)
                check(pg, f"ampliada/{edge}", 200)
                if edge == "left": shot(pg, "09-ampliada")
                pg.locator("#chat-more").click()
                assert pg.locator("#chat-size").inner_text().startswith("Reduzir")
                pg.locator("#chat-size").click()
                assert last_panel_msg(pg) == "widget:panel:chat" and pg.evaluate("document.body.dataset.chatSize") == "compact"
                for i in range(steps - 1, -1, -1):
                    t = i / steps
                    pg.set_viewport_size({"width": round(304 + 56 * t), "height": round(252 + 288 * t)})
                    pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
                    check(pg, f"reduzindo/{edge} passo {i}", 40)
                settle(pg)
                check(pg, f"reduzida/{edge}", 56 if edge in ("top", "bottom") else 90)
                pg.close()
            ctx.close()

        scenario_h()

        @soft("H2. pedido de ampliar com a janela que NÃO cresce (executável sem a mensagem, área útil menor): nada é cortado")
        def scenario_h2():
            if COMMON_ONLY:
                raise AssertionError("sem Ampliar na versão antiga")
            ctx = new_ctx()
            pg = open_page(ctx, "right")
            open_chat(pg)
            pg.locator("#chat-more").click(); pg.locator("#chat-size").click()
            pg.set_viewport_size({"width": 304, "height": 252}); settle(pg)  # a janela ignorou o pedido
            check(pg, "ampliada, janela compacta", 90)
            ctx.close()

        scenario_h2()

        # ---------- I. áreas úteis menores e maiores que o padrão ----------
        @soft("I. área útil reduzida (a ampliada limitada pela tela) e janelas maiores (420×620 do código antigo): o painel só acompanha a janela")
        def scenario_i():
            ctx = new_ctx()
            for vw, vh, mt in ((360, 480, 150), (360, 400, 90), (330, 360, 90), (420, 620, 250), (800, 700, 300)):
                pg = open_page(ctx, "left")
                open_chat(pg)
                pg.set_viewport_size({"width": vw, "height": vh}); settle(pg)
                check(pg, f"janela {vw}x{vh}", mt)
                pg.close()
            ctx.close()

        scenario_i()

        # ---------- J. escalas (CSS px iguais; o DPI da janela WinForms é do teste nativo) ----------
        @soft("J. escalas 100%, 125%, 150% e 200% do navegador: o mesmo painel compacto (não prova o DPI da janela nativa)")
        def scenario_j():
            for dsf in (1, 1.25, 1.5, 2):
                ctx = new_ctx(dsf=dsf)
                pg = open_page(ctx, "left")
                open_chat(pg)
                check(pg, f"dsf {dsf}", 90)
                ctx.close()

        scenario_j()

        # ---------- K. movimento reduzido ----------
        @soft("K. prefers-reduced-motion: sem animação de entrada nem pulso")
        def scenario_k():
            ctx = new_ctx(reduced="reduce")
            pg = open_page(ctx, "left")
            open_chat(pg)
            assert pg.locator("#chat-panel").evaluate("n => getComputedStyle(n).animationName") == "none"
            assert pg.locator("#chat-rec i").evaluate("n => getComputedStyle(n).animationName") == "none"
            ctx.close()

        scenario_k()

        if errors:
            FAILS.append("erros de página: " + "; ".join(errors[:5]))
        browser.close()

    REPORT["falhas"] = FAILS
    (ART / f"{TAG + '-' if TAG else ''}chat-compact-report.json").write_text(json.dumps(REPORT, indent=1, ensure_ascii=False), encoding="utf-8")
    if FAILS:
        print(f"\n{len(FAILS)} cenário(s) FALHARAM:")
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print(f"\nOK: {len(REPORT['scenarios'])} cenários, janela {'antiga (ignora o tamanho)' if LEGACY else 'obedece ao tamanho'}")


if __name__ == "__main__":
    main()
