"""Cérebro: capturas de layout (Conversar, Estudar, Salvos, Fontes, ajustes) em 1440/1100/760/520 e checagem do eixo central.
  py -3.14 tests/study_layout_shots.py   [LUMEN_TEST_UI_STYLE=glass|classic]  [LUMEN_STUDY_ARTIFACTS=pasta]
Reaproveita o backend falso de tests/study_ui.py (BOOT) sem rodar a suíte inteira."""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STYLE = os.environ.get("LUMEN_TEST_UI_STYLE", "glass")
ART = Path(os.environ.get("LUMEN_STUDY_ARTIFACTS", ROOT / "tests/desktop-artifacts/study-layout")) / STYLE
ART.mkdir(parents=True, exist_ok=True)
SRC = (ROOT / "tests/study_ui.py").read_text("utf-8")
BOOT = re.search(r'BOOT = r"""(.*?)\n"""', SRC, re.S).group(1)
WIDTHS = (1440, 1100, 760, 520)
LONG = "Uma resposta longa sobre consolidação da memória e do sono profundo. " * 25
bad = []

with tempfile.TemporaryDirectory(prefix="study-shots-") as temp:
    vault = Path(temp) / "Cofre"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Atenção.md").write_text("# Atenção\nFoco seletivo.", "utf-8")
    from PIL import Image
    png = Path(temp) / "j.png"
    Image.new("RGB", (64, 36), "white").save(png)
    env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data"), "LUMEN_TEST_UI_STYLE": STYLE}
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c", BOOT, str(ROOT), str(vault), str(png)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            page = b.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator("#nav-study").click()
            study = page.locator("[data-study]")
            study.locator(".st-status-btn").wait_for(timeout=15000)
            def axis(label, w):
                """Títulos, abas e cabeçalhos de seção precisam ficar a ≤ 24 px do centro da coluna (o painel; no chat, a coluna da conversa)."""
                r = page.evaluate("""() => { const vis = (e) => e.getClientRects().length && !e.closest('[hidden]');
                    const box = (e) => { const r = e.getBoundingClientRect(); return r.left + r.width / 2; };
                    const v = document.querySelector('#view-study'); const cs = getComputedStyle(v);
                    const vc = (v.getBoundingClientRect().left + parseFloat(cs.paddingLeft) + v.getBoundingClientRect().right - parseFloat(cs.paddingRight)) / 2;
                    const out = [];
                    for (const e of document.querySelectorAll('[data-study] .st-title, [data-study] .st-tabs, [data-study] .st-section-head h2, [data-study] .st-lrn-head h2, [data-study] .st-settings'))
                      if (vis(e)) out.push([e.className || e.tagName, Math.round(box(e)), Math.round(vc)]);
                    const icons = [...document.querySelectorAll('[data-study] .st-section-head, [data-study] .st-lrn-head')].filter(vis)
                      .filter(e => getComputedStyle(e, '::before').gridRowStart !== 'mark' || getComputedStyle(e, '::after').gridRowStart !== 'mark' || getComputedStyle(e, '::after').position !== 'static').length;
                    const m = document.querySelector('[data-study] .st-main.is-empty');
                    if (m && vis(m)) { const t = m.querySelector('.st-hero-title'); if (t) out.push(['hero', Math.round(box(t)), Math.round(box(m))]); }
                    return { out, icons, over: document.documentElement.scrollWidth - document.documentElement.clientWidth }; }""")
                if r["over"] > 1:
                    bad.append(f"{label}@{w}: overflow {r['over']}px")
                if r["icons"]:
                    bad.append(f"{label}@{w}: section icon detached from its tile")
                for name, c, ref in r["out"]:
                    if abs(c - ref) > 24:
                        bad.append(f"{label}@{w}: {name} centro {c} vs eixo {ref}")

            def group(id):
                study.locator('[data-tab="learn"]').click()
                page.evaluate("window.lumenStudy.learnHome()")
                study.locator(f'.st-lrn-goal[data-nav="group:{id}"]').click()

            states = [("chat", lambda: study.locator('[data-tab="chat"]').click()),
                      ("estudar", lambda: study.locator('[data-tab="learn"]').click()),
                      ("revisar", lambda: group("review")),
                      ("praticar", lambda: group("practice")),
                      ("planejar", lambda: group("plan")),
                      ("visualizar", lambda: group("visual")),
                      ("salvos", lambda: study.locator('[data-tab="saved"]').click()),
                      ("fontes", lambda: study.locator('[data-tab="sources"]').click()),
                      ("ajustes", lambda: (study.locator('[data-tab="chat"]').click(), study.locator(".st-head-tools .icon-btn").click())),
                      ("chat-longo", lambda: long_chat())]
            def long_chat():
                if study.locator(".st-settings:not([hidden])").count():
                    study.get_by_role("button", name="Voltar ao Cérebro").click()
                study.locator('[data-tab="chat"]').click()
                if not study.locator(".st-answer").count():
                    ta = study.locator(".st-composer textarea"); ta.fill("Explique a memória"); ta.press("Enter")
                    study.locator(".st-answer").first.wait_for(timeout=30000)
                study.locator(".st-answer").last.evaluate("(e, t) => { e.textContent = t; }", LONG)

            for w in WIDTHS:
                page.set_viewport_size({"width": w, "height": 900})
                for name, go in states:
                    go()
                    page.wait_for_timeout(450)
                    page.mouse.move(0, 0)
                    page.screenshot(path=str(ART / f"{name}-{w}.png"))
                    axis(name, w)
    finally:
        proc.terminate()
print("\n".join(bad) or "eixo ok", f"\n{ART}")
sys.exit(1 if bad else 0)
