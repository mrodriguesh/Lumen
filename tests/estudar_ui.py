"""Aba Estudar do Cérebro: capturas e verificações da reorganização (headless, Playwright, dados isolados).

  py -3.14 tests/estudar_ui.py                 verificações e capturas da interface atual (D:/Lumen/estudar-20261108/ui/<execução>)
  LUMEN_ESTUDAR_MODE=before ...                só captura a interface ANTIGA (usada uma vez, com a árvore restaurada em LUMEN_UI_ROOT)
  LUMEN_UI_ROOT=<árvore>                       serve outra árvore de código (a do "antes")

Reaproveita a fixture de tests/study_ui.py (Ollama falso, Voice Studio falso, microfone simulado, LUMEN_DATA temporário):
é janela headless, NÃO a janela nativa WebView2. Os materiais são semeados por uma rota de teste, em dados temporários."""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SERVE = Path(os.environ.get("LUMEN_UI_ROOT", ROOT))
MODE = os.environ.get("LUMEN_ESTUDAR_MODE", "after")
RUN = os.environ.get("LUMEN_ESTUDAR_RUN") or time.strftime("%Y%m%d-%H%M%S")
OUT = Path(os.environ.get("LUMEN_ESTUDAR_SHOTS") or f"D:/Lumen/estudar-20261108/ui/{RUN}")
OUT.mkdir(parents=True, exist_ok=True)

tree = ast.parse((ROOT / "tests/study_ui.py").read_text("utf-8"))
BOOT = next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BOOT")

# Rota de semeadura (só na fixture): materiais de todos os tipos, cartões vencidos e assuntos para revisar, tudo em dados temporários.
SEED = r'''
def _seed(h):
    from lumen.study import learn, db, mastery
    b = h._json()
    if b.get("mode") == "empty":
        return {"ok": True}
    import datetime as _dt
    src = {"id": "n1", "source": "obsidian", "title": "Memória e sono", "path": "Memória e sono.md", "author": "user", "chunks": []}
    def cards(n):
        return [{"question": f"Pergunta {i + 1} sobre o assunto?", "answer": f"Resposta {i + 1}.", "explanation": "", "source": {"sid": "S1"}} for i in range(n)]
    out = []
    topics = ["Memória e sono", "Atenção seletiva", "Ciclo cardíaco", "Fotossíntese", "Leis de Newton", "Keyframes no Premiere"]
    for i, t in enumerate(topics[: int(b.get("decks", 6))]):
        it = learn.save("flashcards", "Flashcards: " + t, {"topic": t, "cards": cards(3), "sources": [src]})
        learn.add_cards(it["id"], cards(3))
        out.append(it["id"])
    learn.save("quiz", "Questionário: Memória e sono", {"topic": "Memória e sono", "questions": [
        {"kind": "multipla", "question": "Qual estágio do sono consolida a memória declarativa?", "options": ["Vigília", "Sono profundo", "Cochilo", "Insônia"], "answer": "Sono profundo", "explanation": "Ondas lentas.", "source": "S1"},
        {"kind": "aberta", "question": "Explique o papel do hipocampo.", "answer": "Codifica episódios.", "explanation": "", "source": "S1"}], "answers": {}, "sources": [src]})
    learn.save("plan", "Plano de estudos: Memória", {"topic": "Memória", "goal": "Dominar memória.", "prerequisites": [{"topic": "Atenção", "why": "Base.", "source": "S1"}],
        "steps": [{"title": "Base", "objective": "Ler resumo", "topics": ["Sono"], "sources": ["S1"], "minutes": 25}], "reviews": [{"after_days": 1, "focus": "Consolidação"}], "sources": [src]})
    learn.save("gaps", "O que falta: Memória", {"topic": "Memória", "known": [{"topic": "Sono", "source": "S1"}], "missing": [{"topic": "Hipocampo", "why": "Base da codificação.", "depends_on": ""}], "next": ["Ler sobre o hipocampo."], "sources": [src]})
    learn.save("map", "Mapa de conhecimento: Memória", {"topic": "Memória", "nodes": [{"id": "c1", "label": "Memória", "kind": "concept"}, {"id": "c2", "label": "Sono", "kind": "concept"}, {"id": "d1", "label": "Memória e sono", "kind": "doc", "source": "obsidian", "doc": "x"}],
        "edges": [{"from": "c1", "to": "c2", "label": "depende de"}, {"from": "c1", "to": "d1", "label": "em"}], "sources": [src]})
    learn.save("exercise", "Prática com correção: Memória e sono", {"topic": "Memória e sono", "task": "Monte uma revisão de memória com sono.", "deliverable": "Um roteiro de três passos.",
        "criteria": [{"name": "Sono", "expected": "Cita o sono profundo.", "source": "S1"}], "attempts": [], "sources": [src]})
    learn.save("action", "Plano de ação: curso de psicologia", {"topic": "Memória", "goal": "Aplicar o curso.", "application": "Preparar meu curso de psicologia", "focus_sessions": 0,
        "steps": [{"title": "Preparar revisão", "objective": "Listar tópicos", "deliverable": "Lista", "due": "2026-11-20", "minutes": 25, "source": "S1", "done": False}],
        "reviews": [{"due": "2026-11-01", "focus": "Revisar tópicos", "done": False}], "sources": [src]})
    for t in ("Claude Code", "Atenção seletiva"):
        mastery.record(t, False, "flashcard", None)
    for i in range(int(b.get("extra", 12))):
        learn.save("flashcards", f"Flashcards: Assunto de teste {i + 1}", {"topic": f"Assunto {i + 1}", "cards": [], "sources": []})
    return {"ok": True, "decks": out}
server.ROUTES[("POST", "/api/study/__seed")] = _seed
'''
BOOT_FULL = BOOT.replace("h = server.serve(); print(h.server_port", SEED + "\nh = server.serve(); print(h.server_port", 1)
assert "__seed" in BOOT_FULL

checks, errors = [], []
ok = checks.append


def run(scenario):
    """scenario(page, study, url, helpers): roda dentro do navegador, com o servidor da fixture no ar."""
    with tempfile.TemporaryDirectory(prefix="estudar-ui-") as temp:
        vault = Path(temp) / "Cofre de teste"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "Memória e sono.md").write_text("# Memória e sono\nA consolidação da memória depende do sono profundo.", "utf-8")
        from PIL import Image
        shot_png = Path(temp) / "janela.png"
        Image.new("RGB", (320, 180), "white").save(shot_png)
        env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data")}
        log = (OUT / "backend.log").open("w", encoding="utf-8")
        proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c", BOOT_FULL, str(SERVE), str(vault), str(shot_png)], cwd=SERVE, env=env,
                                stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            url = "http://127.0.0.1:" + proc.stdout.readline().strip()
            proc.stdout.readline()
            vs_url = proc.stdout.readline().strip()
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
                page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url.split('?')[0]}") if r.status >= 500 and r.url.startswith(url + "/") else None)
                shot = lambda name, full=False: (page.wait_for_timeout(350), page.screenshot(path=str(OUT / f"{name}.png"), full_page=full))  # noqa: E731
                scenario(page, url, shot, vs_url)
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()


def seed(page, mode="full", **kw):
    page.evaluate("async (b) => await window.lumenStudy.api('/api/study/__seed', b)", {"mode": mode, **kw})


def panel_metrics(page):
    """O quanto a aba Estudar mostra de uma vez: campos, botões, altura total e quantas dobras (altura da janela) ela ocupa."""
    return page.evaluate("""() => { const p = document.querySelector('#st-panel-learn'); const vis = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
      const q = (s) => [...p.querySelectorAll(s)].filter(vis).length;
      return { height: Math.round(p.scrollHeight), screens: +(p.scrollHeight / innerHeight).toFixed(2), fields: q('input:not([type=file]):not([type=radio]):not([type=checkbox]), textarea, select'),
               buttons: q('button, [role=button]'), headings: q('h2, h3, h4'), cards: q('.card') }; }""")


def before(page, url, shot, vs_url):
    study = page.locator("[data-study]")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.locator("#nav-study").click()
    expect(study).to_be_visible()
    study.get_by_role("tab", name="Estudar").click()
    expect(study.get_by_role("heading", name="Estudar", exact=True)).to_be_visible(timeout=15000)
    shot("antes-01-vazio-1440")
    metrics = {"vazio": panel_metrics(page)}
    seed(page, "full")
    study.get_by_role("tab", name="Conversar").click()
    study.get_by_role("tab", name="Estudar").click()
    page.wait_for_timeout(600)
    shot("antes-02-com-dados-1440")
    shot("antes-02-com-dados-1440-pagina", True)
    metrics["com_dados"] = panel_metrics(page)
    # percorre o que está abaixo da dobra: rola o contêiner que de fato rola
    scroller = page.evaluate("""() => { let e = document.querySelector('#st-panel-learn'); while (e && e !== document.body) { const s = getComputedStyle(e);
        if (/(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 4) { e.dataset.scrollerProbe = '1'; return e.className || e.tagName; } e = e.parentElement; } return 'janela'; }""")
    metrics["contêiner_que_rola"] = scroller
    for i, y in enumerate((800, 1600, 2400), 1):
        page.evaluate("y => { const e = document.querySelector('[data-scroller-probe]') || document.scrollingElement; e.scrollTo(0, y); }", y)
        shot(f"antes-02-rolagem-{i}")
    page.evaluate("() => { const e = document.querySelector('[data-scroller-probe]') || document.scrollingElement; e.scrollTo(0, 0); }")
    page.set_viewport_size({"width": 520, "height": 860})
    page.wait_for_timeout(300)
    shot("antes-03-com-dados-520")
    shot("antes-03-com-dados-520-pagina", True)
    metrics["com_dados_520"] = panel_metrics(page)
    page.set_viewport_size({"width": 760, "height": 860})
    shot("antes-03b-com-dados-760")
    page.set_viewport_size({"width": 1440, "height": 900})
    study.locator(".st-learn-item").first.click()
    page.wait_for_timeout(500)
    shot("antes-04-resultado-aberto")
    study.get_by_role("radio", name="Plano de ação", exact=True).click()
    study.get_by_role("button", name="Criar", exact=True).click()
    page.wait_for_timeout(500)
    shot("antes-05-erro-validacao")
    prac = study.locator(".st-practice")
    prac.scroll_into_view_if_needed()
    prac.get_by_label("Tema do treino").fill("persuasão")
    prac.get_by_role("button", name="Começar o treino").click()
    expect(prac.locator(".st-practice-character").first).to_be_visible(timeout=15000)
    shot("antes-06-treino-em-andamento")
    # o que acontece com um rascunho e uma sessão ao trocar de aba e voltar
    prac.get_by_label("Sua resposta").fill("Rascunho da minha resposta")
    study.get_by_role("tab", name="Conversar").click()
    study.get_by_role("tab", name="Estudar").click()
    page.wait_for_timeout(800)
    metrics["rascunho_sobrevive_a_troca_de_aba"] = page.locator(".st-practice textarea[aria-label='Sua resposta']").count() > 0 and \
        page.locator(".st-practice textarea[aria-label='Sua resposta']").input_value() == "Rascunho da minha resposta"
    metrics["flag_practicing_depois_da_troca"] = page.evaluate("window.lumenStudy.S.practicing === true")
    (OUT / "metricas-antes.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=1))


ACTS = [  # (objetivo, atividade, campos visíveis ao abrir, botão principal)
    ("Revisar", "Revisão de hoje", 0, None), ("Revisar", "Flashcards", 1, "Criar flashcards"), ("Revisar", "Revisão em áudio", 1, "Gerar a revisão"),
    ("Praticar", "Questionário", 1, "Criar questionário"), ("Praticar", "Prática com correção", 1, "Criar prática"),
    ("Praticar", "Explique com suas palavras", 2, "Avaliar a explicação"), ("Praticar", "Treino falado", 2, "Começar o treino"),
    ("Planejar", "Plano de estudos", 1, "Criar plano de estudos"), ("Planejar", "Plano de ação", 2, "Criar plano de ação"),
    ("Planejar", "O que falta estudar", 1, "Ver o que falta"), ("Visualizar", "Mapa mental", 1, "Criar mapa mental"),
    ("Visualizar", "Mapa de conhecimento", 1, "Criar mapa de conhecimento")]
GROUP_ROWS = {"Revisar": 3, "Praticar": 4, "Planejar": 3, "Visualizar": 2}
KIND_OF = {"Flashcards": "flashcards", "Revisão em áudio": "audio", "Questionário": "quiz", "Prática com correção": "exercise", "Plano de estudos": "plan",
           "Plano de ação": "action", "O que falta estudar": "gaps", "Mapa mental": "mindmap", "Mapa de conhecimento": "map"}
STUB = ("quiz", "plan", "map", "gaps")   # o Ollama falso não responde a estes: a criação devolve o material semeado (o pedido é conferido do mesmo jeito)
SHOT_NAME = {"Revisão de hoje": "revisao-de-hoje", "Flashcards": "flashcards", "Questionário": "questionario", "Plano de ação": "plano-de-acao",
             "Explique com suas palavras": "explique", "Treino falado": "treino-falado", "Mapa mental": "mapa-mental"}


def after(page, url, shot, vs_url):
    study = page.locator("[data-study]")
    panel = study.locator("#st-panel-learn")
    tab = study.get_by_role("tab", name=re.compile("^Estudar"))
    posts, gets, learn_posts = [], [], []
    page.on("request", lambda r: (gets if r.method == "GET" else posts).append((r.url.split("?")[0].replace(url, ""), r.post_data)) if "/api/study/" in r.url else None)
    metrics = {}

    def count(path, where=None):
        return sum(1 for p, _ in (where if where is not None else posts + gets) if p == path)

    def home():
        if panel.is_hidden():
            tab.click()
        if panel.locator('.st-lrn-screen[data-screen="home"]').is_hidden():
            tab.click()
        expect(panel.get_by_role("heading", name="Estudar", exact=True)).to_be_visible()

    def go(group, act=None):
        home()
        panel.get_by_role("button", name=re.compile(f"^{group}")).click()
        if act:
            panel.get_by_role("button", name=re.compile(f"^{act}")).click()
            return panel.locator(".st-lrn-act:not([hidden])")
        return panel.locator(".st-lrn-screen:not([hidden])")

    def visible_fields():
        """Campos que o estudante vê agora (os de um <details> fechado não contam)."""
        return len(page.evaluate("""() => [...document.querySelectorAll('#st-panel-learn input:not([type=file]):not([type=radio]):not([type=checkbox]), #st-panel-learn textarea, #st-panel-learn select')]
            .filter(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && !(e.closest('details') && !e.closest('details').open))
            .map(e => e.tagName + '#' + e.id)"""))

    def no_overflow(label):
        bad = page.evaluate("""() => { const w = document.documentElement.clientWidth; const root = document.querySelector('#st-panel-learn');
            const clipped = [...root.querySelectorAll('button, .btn, h2, h3, summary, label')].filter(e => e.getClientRects().length && e.scrollWidth > e.clientWidth + 1
              && getComputedStyle(e).overflow !== 'visible' && getComputedStyle(e).textOverflow !== 'ellipsis').map(e => e.tagName + '.' + e.className);
            const wide = [...root.querySelectorAll('*')].filter(e => e.getClientRects().length && e.getBoundingClientRect().right > w + 1).slice(0, 4).map(e => e.tagName + '.' + e.className);
            return { scroll: document.documentElement.scrollWidth > w + 1, clipped, wide }; }""")
        assert not bad["scroll"] and not bad["clipped"] and not bad["wide"], f"{label}: {bad}"

    def api_item(kind):
        return page.evaluate("async k => { const l = await window.lumenStudy.api('/api/study/items?kind=' + k); return await window.lumenStudy.api('/api/study/item?id=' + l.items[0].id); }", kind)

    def pace():
        page.wait_for_timeout(3000)   # o servidor aceita 4 criações a cada 10 s (limit("learn", 4)): espaça as chamadas reais ao modelo

    def blur():
        page.evaluate("document.activeElement && document.activeElement.blur()")

    # --- 1. Estado vazio ---------------------------------------------------------------------------------------------------
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.locator("#nav-study").click()
    expect(study).to_be_visible()
    tab.click()
    home()
    expect(panel.get_by_text("Nenhuma revisão pendente agora.")).to_be_visible(timeout=15000)
    expect(panel.get_by_text("Nada criado ainda. Escolha um objetivo para começar.")).to_be_visible()
    for name in ("Próxima atividade", "Escolha um objetivo", "Materiais recentes"):
        expect(panel.get_by_role("heading", name=name)).to_be_visible()
    goals = panel.locator(".st-lrn-goal")
    expect(goals).to_have_count(4)
    assert [g.splitlines()[0] for g in goals.all_inner_texts()] == ["Revisar", "Praticar", "Planejar", "Visualizar"], goals.all_inner_texts()
    metrics["vazio"] = panel_metrics(page)
    assert metrics["vazio"]["fields"] == 0 and metrics["vazio"]["cards"] == 0 and metrics["vazio"]["screens"] <= 1.0, metrics["vazio"]
    assert count("/api/study/practice", gets) == 0, "cenários do Treino falado não podem ser buscados só porque a aba abriu"
    shot("depois-01-vazio-1440")
    ok("início vazio: três blocos, quatro objetivos, nenhum campo, nenhum card, cabe numa tela; Treino falado não busca nada")

    # --- 2. Com dados ------------------------------------------------------------------------------------------------------
    # o cofre de teste (3 notas) é indexado como o estudante faria em Fontes → Sincronizar; as práticas e planos exigem fontes de verdade
    page.evaluate("window.lumenStudy.api('/api/study/sources', {action: 'sync', source: 'obsidian'})")
    for _ in range(100):
        if page.evaluate("async () => ((await window.lumenStudy.api('/api/study/state')).counts.obsidian || {}).documents || 0") >= 1:
            break
        page.wait_for_timeout(300)
    seed(page, "full")
    study.get_by_role("tab", name="Conversar").click()
    due_before = count("/api/study/due", gets)
    tab.click()
    expect(panel.locator(".st-learn-item")).to_have_count(5, timeout=15000)
    assert count("/api/study/due", gets) - due_before == 1, "abrir a aba busca a revisão pendente uma vez só"
    expect(panel.get_by_role("button", name="Começar revisão")).to_be_visible()
    expect(panel.get_by_text("18 cartões para revisar agora.")).to_be_visible()
    expect(panel.locator(".st-lrn-topics").get_by_role("button", name="Claude Code")).to_be_visible()
    page.evaluate("window.lumenStudy.refreshState()")
    expect(tab).to_have_attribute("aria-description", re.compile("18 cartões"), timeout=15000)   # o selo é visual; a contagem vai como descrição
    assert tab.get_attribute("aria-label") is None and study.get_by_role("tab", name="Estudar", exact=True).count() == 1, "o nome da aba continua só \"Estudar\""
    metrics["com_dados"] = panel_metrics(page)
    assert metrics["com_dados"]["fields"] == 0 and metrics["com_dados"]["cards"] == 0 and metrics["com_dados"]["screens"] <= 1.35, metrics["com_dados"]
    # contraste do texto do início (WCAG: 4,5 para texto); só mede onde o fundo é opaco (as camadas de cor são compostas de baixo para cima)
    ratios = page.evaluate("""() => {
        const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', {willReadFrequently: true});
        const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
        const over = (t, b) => { const a = t[3] + b[3] * (1 - t[3]); return a ? [0, 1, 2].map(i => (t[i] * t[3] + b[i] * b[3] * (1 - t[3])) / a).concat([a]) : [0, 0, 0, 0]; };
        const lum = (c) => { const f = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
        const sels = ['.st-lrn-head h2', '.st-lrn-hint', '.eyebrow', '.st-lrn-next strong', '.st-lrn-next-text p', '.st-lrn-goal strong', '.st-lrn-goal-hint', '.st-lrn-goal-list', '.st-learn-item .st-learn-title',
          '.st-learn-item small', '.st-lrn-topics > p', '.st-lrn-topics .btn', '.st-lrn-sec > .btn', '.st-lrn-next .btn.primary', '.badge'];
        const out = [];
        for (const sel of sels) for (const e of document.querySelectorAll('#st-panel-learn ' + sel)) {
          if (!e.getClientRects().length || !e.textContent.trim()) continue;
          const chain = []; for (let n = e; n; n = n.parentElement) chain.push(getComputedStyle(n).backgroundColor);
          let bg = [0, 0, 0, 0]; for (const c of chain.reverse()) bg = over(rgba(c), bg);
          if (bg[3] < .99) { out.push({ sel, ratio: null }); break; }
          const fg = over(rgba(getComputedStyle(e).color), bg), l1 = lum(fg), l2 = lum(bg);
          out.push({ sel, ratio: +((Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05)).toFixed(2) }); break;
        }
        return out; }""")
    metrics["contraste_inicio"] = ratios
    low = [r for r in ratios if r["ratio"] is not None and r["ratio"] < 4.5]
    assert not low, f"contraste abaixo de 4,5: {low}"
    shot("depois-02-com-dados-1440")
    shot("depois-02-com-dados-1440-pagina", True)
    n_requests = len(gets) + len(posts)
    panel.get_by_role("button", name=re.compile("^Ver todos")).click()
    expect(panel.locator(".st-learn-item")).to_have_count(24)
    expect(panel.get_by_role("button", name="Mostrar menos")).to_be_focused()
    shot("depois-02b-materiais-todos")
    panel.get_by_role("button", name="Mostrar menos").click()
    expect(panel.locator(".st-learn-item")).to_have_count(5)
    assert len(gets) + len(posts) == n_requests, "mostrar mais ou menos não busca nada de novo"
    ok("início com dados: revisão pendente em destaque com contagem, assuntos para rever, 5 materiais recentes e acesso aos demais (24) na mesma tela, sem novas requisições")

    # --- 3. Objetivos ------------------------------------------------------------------------------------------------------
    for group, rows in GROUP_ROWS.items():
        home()
        panel.get_by_role("button", name=re.compile(f"^{group}")).click()
        expect(panel.get_by_role("heading", name=group, exact=True)).to_be_focused()
        assert panel.locator('.st-lrn-screen[data-screen="group"]:not([hidden]) .st-lrn-row').count() == rows, group
        assert visible_fields() == 0
        expect(panel.get_by_role("button", name="Voltar para Estudar")).to_be_visible()
        shot(f"depois-03-{group.lower()}")
        panel.get_by_role("button", name="Voltar para Estudar").click()
        expect(panel.get_by_role("button", name=re.compile(f"^{group}"))).to_be_focused()
    ok("quatro objetivos: cada um lista só as suas funções (3, 4, 3, 2), com foco no título e, ao voltar, de volta ao botão que abriu")

    # --- 4. As 12 funções a dois cliques, uma por vez ----------------------------------------------------------------------
    for group, act, nfields, primary in ACTS:
        a = go(group, act)
        expect(a.get_by_role("heading", name=act, exact=True)).to_be_focused()
        assert panel.locator(".st-lrn-act:not([hidden])").count() == 1
        assert visible_fields() == nfields, (act, visible_fields())
        assert panel.locator(".card:visible").count() == 0, act
        if primary:
            button = a.get_by_role("button", name=primary, exact=True)
            expect(button).to_be_visible()
            assert page.evaluate("e => e.getBoundingClientRect().bottom <= innerHeight", button.element_handle()), f"{act}: o botão principal fica abaixo da dobra"
        if act in SHOT_NAME:
            shot("depois-04-" + SHOT_NAME[act])
    ok("as 12 funções abrem em dois cliques, uma atividade visível por vez, com os campos essenciais e o botão principal acima da dobra")

    # --- 5. Criação: dados enviados, validação, resultado --------------------------------------------------------------------
    stub = {k: api_item(k) for k in STUB}

    def learn_route(route):
        body = json.loads(route.request.post_data)
        learn_posts.append(body)
        if body["kind"] in STUB:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(stub[body["kind"]]))
        route.continue_()
    page.route("**/api/study/learn", learn_route)
    for group, act, nfields, primary in ACTS:
        kind = KIND_OF.get(act)
        if not kind:
            continue
        a = go(group, act)
        before_n = len(learn_posts)
        a.get_by_role("button", name=primary, exact=True).click()           # campo vazio: o erro aparece no campo, nada é enviado
        topic = a.get_by_role("textbox", name="Assunto", exact=True)
        expect(topic).to_be_focused()
        expect(topic).to_have_attribute("aria-invalid", "true")
        expect(a.get_by_role("alert").filter(has_text="Escreva o assunto.")).to_be_visible()
        assert len(learn_posts) == before_n, f"{act}: enviou com o assunto vazio"
        if kind == "exercise":
            shot("depois-05-erro-validacao")
        topic.fill("memória e sono")
        expect(a.get_by_role("alert")).to_have_count(0)                     # o erro some assim que o campo é corrigido
        if kind == "action":
            a.get_by_role("button", name=primary, exact=True).click()
            expect(a.get_by_role("textbox", name="Seu projeto")).to_have_attribute("aria-invalid", "true")
            a.get_by_role("textbox", name="Seu projeto").fill("Preparar meu curso de psicologia")
        if kind not in STUB:
            pace()
        a.get_by_role("button", name=primary, exact=True).click()
        try:
            expect(a.locator(".st-item")).to_be_visible(timeout=30000)
        except AssertionError:
            raise AssertionError(f"{act}: sem resultado; aviso na tela: {page.locator('#toast').inner_text()!r}") from None
        sent = learn_posts[-1]
        assert sent == {"kind": kind, "topic": "memória e sono", "level": "", "application": "Preparar meu curso de psicologia" if kind == "action" else "", "project_id": None}, sent
        assert a.locator(".st-item .st-item-head h3").inner_text().strip(), act
        expect(panel.locator(".st-lrn > .sr")).to_contain_text("Resultado aberto")   # leitor de tela: aviso curto, sem ler o resultado inteiro
        if kind in ("flashcards", "action", "quiz"):
            shot("depois-06-resultado-" + kind)
    ok("os nove tipos de criação enviam os mesmos campos de antes (kind, topic, level, application, project_id), validam no campo e abrem o resultado na própria atividade")

    # --- 6. Erro de criação: o texto fica e dá para tentar de novo -------------------------------------------------------------
    page.unroute("**/api/study/learn")
    failing = {"on": True}

    def flaky(route):
        if failing["on"]:
            return route.fulfill(status=400, content_type="application/json", body=json.dumps({"error": {"message": "Falha simulada do modelo.", "action": "Tente de novo."}}))
        route.continue_()
    page.route("**/api/study/learn", flaky)
    a = go("Revisar", "Flashcards")
    a.get_by_role("textbox", name="Assunto", exact=True).fill("assunto que falhou")
    a.get_by_role("button", name="Criar flashcards", exact=True).click()
    expect(a.get_by_text("Não foi possível criar agora.")).to_be_visible(timeout=10000)
    expect(a.get_by_role("textbox", name="Assunto", exact=True)).to_have_value("assunto que falhou")
    expect(a.get_by_role("button", name="Criar flashcards", exact=True)).to_be_enabled()
    shot("depois-07-erro-de-criacao")
    failing["on"] = False
    pace()
    a.get_by_role("button", name="Tentar de novo").click()
    expect(a.locator(".st-item")).to_contain_text("assunto que falhou", timeout=20000)
    page.unroute("**/api/study/learn")
    ok("falha na criação: mensagem ao lado do formulário, texto preservado, botão liberado e \"Tentar de novo\" cria com o mesmo texto")

    # --- 7. Resultado tardio não aparece na atividade errada ---------------------------------------------------------------------
    held = []
    page.route("**/api/study/learn", lambda route: held.append(route))
    a = go("Visualizar", "Mapa mental")
    a.get_by_role("textbox", name="Assunto", exact=True).fill("tema que demora")
    pace()
    a.get_by_role("button", name="Criar mapa mental", exact=True).click()
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, "o pedido de criação não saiu"
    go("Praticar", "Explique com suas palavras")
    held[0].continue_()
    toast = page.locator("#toast")
    expect(toast).to_contain_text("Pronto:", timeout=30000)
    assert panel.locator(".st-lrn-act:not([hidden]) .st-item").count() == 0, "o resultado não pode aparecer na atividade que está na tela"
    toast.get_by_role("button", name="Abrir").click()
    expect(panel.locator(".st-lrn-act:not([hidden])").get_by_role("heading", name="Mapa mental", exact=True)).to_be_visible()
    expect(panel.locator(".st-lrn-act:not([hidden]) .st-item")).to_be_visible()
    page.unroute("**/api/study/learn")
    ok("criação demorada: o aviso \"Pronto\" com \"Abrir\" leva ao resultado certo; a atividade em que o estudante está não é tocada")

    # --- 8. Rascunhos e resultados sobrevivem à navegação ----------------------------------------------------------------------
    a = go("Planejar", "Plano de estudos")
    a.get_by_role("textbox", name="Assunto", exact=True).fill("rascunho do plano")
    a = go("Praticar", "Explique com suas palavras")
    a.get_by_role("textbox", name="Assunto", exact=True).fill("fotossíntese")
    a.get_by_role("textbox", name="Sua explicação").fill("As plantas usam a luz para fazer açúcar a partir de gás carbônico e água.")
    study.get_by_role("tab", name="Conversar").click()
    study.get_by_role("tab", name="Salvos").click()
    tab.click()
    expect(panel.get_by_role("textbox", name="Sua explicação")).to_have_value("As plantas usam a luz para fazer açúcar a partir de gás carbônico e água.")
    home()
    expect(panel.locator(".st-lrn-goal").filter(has_text="Rascunho")).to_have_count(2)   # Praticar e Planejar avisam que há rascunho
    expect(panel.get_by_role("button", name=re.compile("^Praticar"))).to_contain_text("Rascunho")
    expect(panel.get_by_role("button", name=re.compile("^Planejar"))).to_contain_text("Rascunho")
    shot("depois-08-rascunho-no-inicio")
    a = go("Planejar", "Plano de estudos")
    expect(a.get_by_role("textbox", name="Assunto", exact=True)).to_have_value("rascunho do plano")
    ok("rascunhos (assunto, explicação) sobrevivem a trocar de objetivo, de atividade e de aba; o início sinaliza onde há rascunho (e não onde o formulário já foi enviado)")

    # --- 9. Explique com suas palavras: validação, texto e voz -----------------------------------------------------------------
    a = go("Praticar", "Explique com suas palavras")
    a.get_by_role("textbox", name="Sua explicação").fill("curto")
    a.get_by_role("button", name="Avaliar a explicação").click()
    expect(a.get_by_role("alert").filter(has_text="Explique com pelo menos uma frase.")).to_be_visible()
    a.get_by_role("textbox", name="Sua explicação").fill("As plantas usam a luz para fazer açúcar a partir de gás carbônico e água.")
    a.get_by_role("button", name="Avaliar a explicação").click()
    expect(a.locator(".st-feynman-out")).to_contain_text("Ainda não (60%)", timeout=15000)
    expect(a.locator(".st-feynman-list.warn")).to_contain_text("O papel do hipocampo.")
    expect(a.get_by_role("button", name="Apertar para falar")).to_be_visible()
    shot("depois-09-feynman-resultado")
    before_listen = count("/api/study/voice/listen", posts)
    go("Planejar", "Plano de estudos")
    blur()
    page.keyboard.down("Space")
    page.keyboard.up("Space")
    page.wait_for_timeout(300)
    assert count("/api/study/voice/listen", posts) == before_listen, "a barra de espaço abriu o microfone com a atividade de voz escondida"
    go("Praticar", "Explique com suas palavras")
    blur()
    page.keyboard.down("Space")
    page.wait_for_timeout(600)
    assert count("/api/study/voice/listen", posts) > before_listen, "a barra de espaço deveria abrir o microfone nesta atividade"
    page.keyboard.up("Space")
    page.wait_for_timeout(600)
    ok("Explique com suas palavras: erro no campo, avaliação por texto com fontes, e o microfone (barra de espaço) só responde quando a atividade está na tela")

    # --- 10. Quiz mantém respostas e correção -----------------------------------------------------------------------------------
    a = go("Praticar", "Questionário")
    a.locator(".st-learn-item").first.click()
    expect(a.locator(".st-quiz")).to_be_visible()
    a.locator(".st-q").first.get_by_label("Sono profundo").check()
    a.locator(".st-q").first.get_by_role("button", name="Responder").click()
    expect(a.locator(".st-q").first.locator(".st-feedback")).to_contain_text("Correto", timeout=10000)
    shot("depois-10-quiz-corrigido")
    go("Planejar", "O que falta estudar")
    go("Praticar", "Questionário")
    expect(panel.locator(".st-lrn-act:not([hidden]) .st-q").first.locator(".st-feedback")).to_contain_text("Correto")
    ok("Questionário: resposta, correção e feedback continuam na tela depois de navegar para outra atividade e voltar")

    # --- 11. Revisão em andamento ------------------------------------------------------------------------------------------------
    home()
    panel.get_by_role("button", name="Começar revisão").click()
    session = panel.locator(".st-session")
    expect(session).to_contain_text(re.compile(r"Cartão 1 de \d+"))
    posts_before = count("/api/study/review", posts)
    page.keyboard.press("Space")
    expect(session.locator(".st-grades")).to_be_visible()
    shot("depois-11a-revisao-resposta")
    page.keyboard.press("3")
    expect(session).to_contain_text(re.compile(r"Cartão 2 de \d+"))
    reviews = [json.loads(b) for p, b in posts if p == "/api/study/review"]
    assert reviews[-1]["grade"] == 2 and count("/api/study/review", posts) == posts_before + 1, reviews[-1]
    shot("depois-11-revisao-em-andamento")
    home()
    expect(panel.get_by_text("Revisão em andamento")).to_be_visible()
    expect(panel.get_by_role("button", name="Começar revisão")).to_have_count(0)
    shot("depois-11b-inicio-com-revisao-em-andamento")
    n_reviews = count("/api/study/review", posts)
    blur()
    page.keyboard.press("3")
    page.wait_for_timeout(300)
    assert count("/api/study/review", posts) == n_reviews, "a revisão escondida capturou o teclado"
    panel.get_by_role("button", name="Continuar").click()
    expect(session).to_contain_text(re.compile(r"Cartão 2 de \d+"))
    session.get_by_role("button", name="Parar por aqui").click()
    expect(session).to_have_count(0)
    expect(panel.get_by_role("button", name="Começar revisão")).to_be_visible()
    ok("Revisão: progresso e teclado (Espaço, 1 a 4) funcionam; ao sair o início mostra \"em andamento\", a sessão escondida não captura teclas e \"Continuar\" volta ao mesmo cartão")

    # --- 12. Treino falado -----------------------------------------------------------------------------------------------------------
    a = go("Praticar", "Treino falado")
    expect(a.get_by_label("Cenário", exact=True)).to_contain_text("Venda para um cliente cético", timeout=8000)
    assert count("/api/study/practice", gets) == 1, "cenários buscados na 1ª vez que a atividade abriu (passo 4) e nunca mais"
    a.get_by_label("Tema (opcional)").fill("persuasão")
    a.get_by_role("button", name="Começar o treino").click()
    expect(a.locator(".st-practice-character").first).to_contain_text("Por que eu confiaria em você?", timeout=15000)
    a.get_by_label("Sua resposta").fill("Tenho casos de clientes como você e garantia de 30 dias.")
    assert page.evaluate("window.lumenStudy.S.practicing === true")
    shot("depois-12-treino-em-andamento")
    go("Revisar", "Flashcards")
    home()
    expect(panel.get_by_text("Treino falado em andamento")).to_be_visible()
    panel.get_by_role("button", name="Continuar").click()
    expect(a.get_by_label("Sua resposta")).to_have_value("Tenho casos de clientes como você e garantia de 30 dias.")
    expect(a.locator(".st-practice-character")).to_have_count(1)
    a.get_by_role("button", name="Responder").click()
    expect(a.locator(".st-practice-student")).to_have_count(1)
    expect(a.locator(".st-practice-character")).to_have_count(2, timeout=15000)
    a.get_by_role("button", name="Terminar e avaliar").click()
    expect(a.locator(".st-feynman-out")).to_contain_text("Continue treinando (50%)", timeout=15000)
    expect(a.locator(".st-rubric li")).to_have_count(2)
    assert page.evaluate("window.lumenStudy.S.practicing === false")
    shot("depois-12b-treino-avaliado")
    assert count("/api/study/practice", gets) == 1
    ok("Treino falado: cenários só ao abrir, sessão, rascunho e conversa continuam ao navegar, início avisa \"em andamento\", avaliação por critérios e a marca de treino zera no fim")

    # --- 13. Plano de ação mantém o vínculo com o Pomodoro e os materiais anteriores ----------------------------------------------
    a = go("Planejar", "Plano de ação")
    expect(a.get_by_text("Criados antes")).to_be_visible()
    plan_ = a.locator(".st-action-plan")
    expect(plan_).to_contain_text("Preparar revisão")
    plan_.get_by_role("button", name="Focar nesta tarefa", exact=True).click()
    expect(plan_).to_contain_text("sessão(ões) de foco")
    page.keyboard.press("Escape")
    assert [b for p, b in posts if p == "/api/study/applied" and b and '"focus"' in b], "\"Focar nesta tarefa\" deveria registrar o foco no plano"
    ok("Plano de ação: tarefa ligada ao Pomodoro (registro do foco) e materiais anteriores do mesmo tipo listados na própria atividade")

    # --- 14. Materiais recentes abrem na atividade do tipo, e o voltar vai para onde o estudante estava ---------------------------
    home()
    panel.locator(".st-learn-item").first.click()
    expect(panel.locator(".st-lrn-act:not([hidden]) .st-item")).to_be_visible()
    back = panel.locator(".st-lrn-act:not([hidden])").get_by_role("button", name=re.compile("^Voltar"))
    assert back.inner_text().strip() == "Estudar", back.inner_text()
    back.click()
    expect(panel.get_by_role("heading", name="Escolha um objetivo")).to_be_visible()
    ok("material recente abre na atividade do tipo dele e \"Voltar\" leva ao início, de onde veio")

    # --- 15. Teclado, foco visível e movimento reduzido ----------------------------------------------------------------------------
    home()
    panel.locator(".st-lrn-goal").first.focus()
    page.keyboard.press("Tab")
    assert "st-lrn-goal" in page.evaluate("document.activeElement.className")
    page.keyboard.press("Enter")
    expect(panel.get_by_role("heading", name="Praticar", exact=True)).to_be_focused()
    page.keyboard.press("Tab")
    assert "st-lrn-row" in page.evaluate("document.activeElement.className"), page.evaluate("document.activeElement.className")
    assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none", "foco do teclado precisa ser visível"
    shot("depois-14-foco-visivel")
    page.emulate_media(reduced_motion="reduce")
    assert page.evaluate("document.getAnimations().filter(a => a.effect && a.effect.target && a.effect.target.closest('#st-panel-learn')).length") == 0
    page.emulate_media(reduced_motion="no-preference")
    ok("teclado: Tab/Enter percorrem os objetivos, o título da tela recebe o foco, o foco é visível e não há animações com movimento reduzido")

    # --- 16. Larguras ------------------------------------------------------------------------------------------------------------------
    for w, h_ in ((1100, 860), (760, 860), (520, 860)):
        page.set_viewport_size({"width": w, "height": h_})
        page.wait_for_timeout(200)
        home()
        no_overflow(f"início {w}")
        shot(f"depois-13-inicio-{w}")
        metrics[f"inicio_{w}"] = panel_metrics(page)
        go("Praticar", "Prática com correção")
        no_overflow(f"prática {w}")
        shot(f"depois-13-pratica-{w}")
        go("Planejar", "Plano de ação")
        no_overflow(f"plano de ação {w}")
        go("Praticar", "Treino falado")
        no_overflow(f"treino {w}")
        shot(f"depois-13-treino-{w}")
        panel.get_by_role("button", name="Voltar para Praticar").click()
        no_overflow(f"objetivo {w}")
        shot(f"depois-13-objetivo-{w}")
    page.set_viewport_size({"width": 1440, "height": 900})
    ok("1100, 760 e 520 px: início, objetivo e atividades sem rolagem horizontal, texto cortado ou botão fora da tela")

    (OUT / "metricas-depois.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if MODE == "before":
        run(before)
        assert not errors, errors
        print("antes ok", OUT)
        sys.exit(0)
    run(after)
    assert not errors, errors
    print(f"depois ok: {len(checks)} verificações", OUT)
    for c in checks:
        print(" -", c)
