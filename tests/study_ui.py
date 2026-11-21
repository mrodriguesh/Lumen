"""Lúmen Study AI na janela: backend real e isolado (LUMEN_DATA temporário, cofre de teste, Ollama falso no mesmo
processo, sem token do Notion nem chave da Anthropic do usuário) e Chrome headless (Playwright).
  py -3.14 tests/study_ui.py        imagens em tests/desktop-artifacts/study-ai-20261031 (ou LUMEN_STUDY_ARTIFACTS)
  LUMEN_TEST_UI_STYLE=glass         roda tudo no estilo Lúmen Glass 2026 (Ajustes → Aparência → Estilo da interface)
"""
import base64
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
ART = Path(os.environ.get("LUMEN_STUDY_ARTIFACTS", ROOT / "tests/desktop-artifacts/study-ai-redesign-20261031"))
ART.mkdir(parents=True, exist_ok=True)

BOOT = r"""
import sys
sys.path.insert(0, sys.argv[1])
from tests.fake_ollama import FakeOllama
fake = FakeOllama()
from tests.test_study_pdf import DOC, DECOR, png
from lumen import imagegen, llm
imagegen.ready = lambda *a: True
imagegen.generate = png
llm.release_vram = lambda: True
fake.json_replies.update({"PDF:": DOC, "Você decora páginas": DECOR})
from tests.test_study_applied import EXERCISE, ACTION, GRADE
fake.json_replies.update({"PRÁTICA:": EXERCISE, "AÇÃO:": ACTION, "Você corrige uma PRÁTICA": GRADE})
from lumen import visual3d
from tests import REAL_VISUAL
visual3d.W, visual3d.H, visual3d.ATTEMPTS = REAL_VISUAL["W"], REAL_VISUAL["H"], REAL_VISUAL["ATTEMPTS"]  # o holograma do chat, no tamanho real
_part = lambda label, detail: {"label": label, "detail": detail, "parent": -1}
fake.json_replies["DADOS de uma visualização 3D"] = {"concept": "Computador", "sources": [], "diagram": {"family": "sistema", "title": "Computador e seus componentes",
    "nodes": [_part("Processador (CPU)", "Executa as instruções dos programas."), _part("Memória RAM", "Guarda o que está em uso agora."),
              _part("Placa-mãe", "Liga e alimenta todos os componentes."), _part("Armazenamento (SSD)", "Guarda arquivos e programas."),
              _part("Placa de vídeo (GPU)", "Desenha imagens e acelera cálculos."), _part("Fonte de energia", "Converte a tomada na tensão de cada peça.")],
    "relations": [{"from": 0, "to": 1, "kind": "depende de"}, {"from": 0, "to": 3, "kind": "depende de"}, {"from": 4, "to": 0, "kind": "depende de"}]}}
fake.models.append("qwen3.5:4b")      # o recomendado pela medição da fase 2: o Automático o escolhe
fake.models.append("perfil-adulto-x:1")  # modelo dedicado do perfil adulto (D92); os ajustes só o usam se o estudante ligar
from lumen import server, store
import logging
class _ApiTrace(logging.Filter):
    def filter(self, record):
        if record.levelno >= logging.ERROR and sys.exc_info()[0]:
            record.exc_info = sys.exc_info()  # só a fixture sintética registra detalhes de exceções
        return True
server.log.addFilter(_ApiTrace())
from lumen.study import settings
store.get_token = lambda: ""          # nunca o token real do Notion (o keyring do Windows é compartilhado)
settings.api_key = lambda *a, **kw: "" # nem as chaves reais dos provedores externos
cfg = store.load_config(); cfg["obsidian_vault"] = sys.argv[2]
cfg["ui_style"] = __import__("os").environ.get("LUMEN_TEST_UI_STYLE", "classic")  # LUMEN_TEST_UI_STYLE=glass: a mesma suíte no estilo Lúmen Glass 2026
store.save_config(cfg)
# Fase 4: a visão falsa lê os anexos de imagem e o /tela, que nunca captura uma janela real deste PC
fake.json_replies["Você lê uma captura de tela"] = {"titulo": "Funil de vendas", "texto": "Topo: atrair\nMeio: nutrir",
    "descricao": "Um funil em três faixas", "tipo": "slide", "conteudo_da_aula": True, "valores": []}
# Fase 5: o material da explicação (diagrama e checagem), o mapa mental e a correção da checagem (errada)
fake.json_replies["Você prepara o material que acompanha uma explicação"] = {"diagram": {"family": "processo",
    "title": "Como o sono consolida a memória", "relations": [{"from": 0, "to": 2, "kind": "leva a"}], "nodes": [
    {"label": "Codificação", "detail": "O hipocampo grava o que você viveu.", "parent": -1},
    {"label": "Sono profundo", "detail": "As ondas lentas reativam a lembrança.", "parent": -1},
    {"label": "Neocórtex", "detail": "A lembrança passa a ficar no córtex.", "parent": -1}]},
    "check": {"question": "Por que dormir depois de estudar ajuda a lembrar?", "answer": "O sono profundo consolida a memória."}}
fake.json_replies["Monte um mapa mental"] = {"center": "Memória", "sources": ["S1"], "branches": [
    {"label": "Tipos", "detail": "Curto e longo prazo.", "children": [{"label": "Trabalho", "detail": "Segura o agora."}, {"label": "Longo prazo", "detail": "Dura anos."}]},
    {"label": "Sono", "detail": "Consolida o que foi estudado.", "children": [{"label": "Ondas lentas", "detail": ""}]},
    {"label": "Atenção", "detail": "Escolhe o que entra.", "children": [{"label": "Foco", "detail": ""}]}]}
fake.json_replies["Você corrige respostas"] = {"correct": False, "score": 0.3, "feedback": "Faltou dizer o porquê."}
from lumen import vision
vision.window_jpeg = lambda: (vision.image_jpeg(sys.argv[3]), "Janela de teste — teste.exe")
from lumen.study import db  # tests/__init__ troca o LUMEN_DATA por outra pasta temporária: a mídia é a dele
# Fase 6: o Voice Studio falso (o real do estudante nunca é chamado) e o microfone simulado (nada é gravado)
import os
from tests.fake_voicestudio import Fake as FakeVS
vs = FakeVS(); os.environ["LUMEN_VOICESTUDIO_URL"] = vs.url
from lumen import voicestudio
voicestudio.app_open = lambda: True   # o "app aberto" do teste não depende do VoiceStudio.exe real deste PC
from lumen.study import listen
settings.save({"voice": {"verify_long": False}})
class Mic:
    on = False
    def busy(self): return self.on
    def start(self): self.on = True
    def state(self): return {"listening": self.on, "level": 0.4 if self.on else 0, "seconds": 1.0}
    def stop(self):
        import numpy as np
        self.on = False
        return np.ones(16000, np.float32) * 0.1
listen.MIC = Mic()
listen.MIC.cb = None
listen.MIC.start_continuous = lambda on_frame, mic_id="", open_mic=None: (setattr(listen.MIC, "on", True), setattr(listen.MIC, "cb", on_frame))
listen.MIC.preroll_audio = lambda: __import__("numpy").zeros(512 * 3, __import__("numpy").float32)
listen.heard = lambda audio: "Explique keyframes no Premiere"
from lumen import loopback
loopback.microphones = lambda: [{"id": "mic-sim", "name": "Microfone Simulado USB", "default": True}]
class _NoopSpk:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def play(self, c): pass
    def flush(self): pass
from lumen.study import call as study_call
study_call.CALL._custom_speaker = _NoopSpk
study_call.CALL._custom_vad = study_call.EnergyVAD
_call_queue = ["Cria um mapa mental de memória"]
study_call.CALL._custom_asr = lambda a, c="auto": ((_call_queue.pop(0) if len(_call_queue) > 1 else _call_queue[0]).rstrip(".?!") + ".", 14.0, "parakeet")  # o Parakeet fecha a frase com pontuação
study_call.CALL._warm_fn = lambda s, emit: listen.who("call", s)
def _sim_call(h):
    import numpy as np
    b = h._json()
    if b.get("text"): _call_queue[:] = [b["text"]]
    cb = listen.MIC.cb
    if cb:
        for _ in range(10): cb(np.full(512, 0.2, np.float32), 0.2)
        for _ in range(25): cb(np.zeros(512, np.float32), 0.0)
    return {"ok": True}
server.ROUTES[("POST", "/api/study/__call_sim")] = _sim_call
def _agent_sim(h):
    from lumen.study import browser as guided
    from lumen import cdp
    import time
    page = cdp._page
    guided.search_results = lambda q, c: [{"title": "Memória e sono", "url": "https://example.org/memoria", "description": "Fonte pública simulada"}]
    guided.select_sources = lambda *a: (time.sleep(2), [0])[1]
    original_fetch = guided.web.fetch
    def fetch(url, *args, **kwargs):
        if url == "https://example.org/memoria":
            time.sleep(2)
            return {"url": url, "title": "Memória e sono", "text": "O sono profundo consolida a memória. Fonte simulada para o teste de interface.", "links": []}
        return original_fetch(url, *args, **kwargs)
    guided.web.fetch = fetch
    def headless(*args, **kwargs):
        kwargs["visible"] = False
        return page(*args, **kwargs)
    cdp._page = headless
    return {"ok": True}
server.ROUTES[("POST", "/api/study/__agent_sim")] = _agent_sim
fake.json_replies["Monte o roteiro de uma revisão em áudio"] = {"title": "Memória e sono", "intro": "Vamos lembrar o que você estudou.",
    "outro": "Fim da revisão.", "chapters": [{"title": "Sono", "items": [{"question": "O que o sono profundo faz?", "answer": "Consolida a memória.", "source": "S1"}]},
    {"title": "Atenção", "items": [{"question": "O que é foco seletivo?", "answer": "Escolher o que entra.", "source": "geral"}]}]}
fake.json_replies["técnica de\nFeynman"] = {"right": [{"point": "O sono consolida a memória.", "source": "S1"}],
    "missing": [{"point": "O papel do hipocampo.", "source": "geral"}], "wrong": [], "score": 0.6, "feedback": "Bom começo: faltou o hipocampo."}
fake.json_replies["Você está num treino falado"] = {"line": "Já fui enganado antes. Por que eu confiaria em você?", "end": False}
fake.json_replies["Avalie o desempenho do ESTUDANTE"] = {"criteria": [{"name": "Tratamento de objeções", "score": 0.7, "comment": "Usou a garantia."},
    {"name": "Próximo passo combinado", "score": 0.3, "comment": "Não propôs um próximo passo."}], "overall": 0.55,
    "feedback": "Boa resposta à objeção; faltou fechar.", "next": "Proponha um próximo passo concreto."}
h = server.serve(); print(h.server_port, flush=True); print(db.MEDIA / "anexos", flush=True); print(vs.url, flush=True); h.serve_forever()
"""


def pdf_text(text):
    """PDF mínimo de verdade, com uma página de texto (o mesmo de tests/test_study_attachments.py)."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def note(vault, rel, text):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


with tempfile.TemporaryDirectory(prefix="study-ui-") as temp:
    vault = Path(temp) / "Cofre de teste"
    (vault / ".obsidian").mkdir(parents=True)
    note(vault, "B02 Estudos/Memória e sono.md", "---\ntype: permanent\ntags: [psicologia]\n---\n# Memória e sono\nA consolidação da memória depende do sono profundo. Ver [[Atenção]].")
    note(vault, "Atenção.md", "# Atenção\nFoco seletivo e memória de trabalho.")
    note(vault, "Behaviorismo.md", "# Behaviorismo\nCondicionamento operante e reforço, segundo Skinner.")
    note(vault, "C04 Claude Obsidian/01 Outputs/.keep.md", "")
    note(vault, ".claude/skills/buscar-cerebro/SKILL.md", "---\nname: buscar-cerebro\ndescription: Busca no cérebro e resume\n"
         "argument-hint: <assunto>\n---\nBusque tudo sobre $ARGUMENTS.")
    from PIL import Image, ImageDraw
    shot_png = Path(temp) / "janela.png"
    pic = Image.new("RGB", (640, 360), "white")
    ImageDraw.Draw(pic).rectangle((100, 80, 540, 280), outline="black", width=6)
    pic.save(shot_png)
    env = {**os.environ, "LUMEN_DATA": str(Path(temp) / "data")}
    backend_log = (ART / "backend.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c", BOOT, str(ROOT), str(vault), str(shot_png)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=backend_log, text=True)
    report = {"screenshots": str(ART), "checks": []}
    ok = lambda name: report["checks"].append(name)  # noqa: E731
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        media = Path(proc.stdout.readline().strip())
        vs_url = proc.stdout.readline().strip()  # o Voice Studio falso (fase 6)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True, permissions=["clipboard-read", "clipboard-write"])
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
            page.on("response", lambda r: errors.append(f"HTTP {r.status}: {r.url.split('?')[0]}") if r.status >= 500 and r.url.startswith(url + "/") else None)
            shot = lambda name: (page.wait_for_timeout(400), page.screenshot(path=str(ART / f"{name}.png")))  # noqa: E731  (espera as animações de entrada)
            study = page.locator("[data-study]")

            def learn_go(group, act):
                """Estudar → objetivo → atividade (dois cliques a partir do início). Clicar na aba já aberta volta ao início, sem perder rascunhos."""
                tab = study.get_by_role("tab", name=re.compile("^Estudar"))
                tab.click()
                if study.locator('.st-lrn-screen[data-screen="home"]').is_hidden():
                    tab.click()
                study.get_by_role("button", name=re.compile(f"^{group}")).click()
                study.get_by_role("button", name=re.compile(f"^{act}")).click()
                return study.locator(".st-lrn-act:not([hidden])")

            def fits():
                wide = page.evaluate("""() => { const w = document.documentElement.clientWidth;
                    const clipped = (e) => { for (let p = e.parentElement; p && !p.matches('.view'); p = p.parentElement)
                      if (['auto', 'scroll', 'hidden'].includes(getComputedStyle(p).overflowX)) return true; return false; };
                    return [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > w + 1 && e.getClientRects().length && !clipped(e))
                      .slice(0, 5).map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right)); }""")
                assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") and not wide, f"rolagem horizontal em {page.viewport_size}: {wide}"

            # 1. Aba no rail; cabeçalho enxuto com um único indicador, e o estado real num painel que só abre quando pedido
            startup = []
            page.route("**/api/state", lambda r: startup.append(r))
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.locator("#nav-study").click()
            expect(study).to_be_visible()
            assert startup, "A resposta inicial precisa estar suspensa para provar a navegação durante a abertura"
            for request in startup:
                request.continue_()
            page.unroute("**/api/state")
            expect(page.locator("#formats")).to_contain_text("Formatos testados:")
            expect(study).to_be_visible()
            ok("navegação escolhida durante a abertura preservada após carregar o estado inicial")
            expect(page.get_by_role("heading", name=re.compile(r"Cérebro|Estudos"), exact=True)).to_be_visible()
            status = study.locator(".st-status-btn")
            expect(status).to_contain_text("IA local", timeout=10000)
            expect(study.locator(".st-pill.ai")).to_be_hidden()
            expect(study.locator(".st-sources-panel")).to_be_hidden()  # nenhuma coluna de fontes sem fontes
            expect(page.get_by_role("heading", name="O que vamos aprender hoje?")).to_be_visible()
            expect(study.locator(".st-chip")).to_have_count(6)
            shot("01-inicio")
            status.click()
            expect(study.locator(".st-pill.ai")).to_contain_text("IA local pronta")
            expect(study.locator(".st-pill.ai")).to_contain_text("Ollama")
            expect(study.locator(".st-pill.notion")).to_contain_text("Não conectado")
            shot("01b-estado")
            page.keyboard.press("Escape")
            expect(study.locator(".st-pill.ai")).to_be_hidden()
            ok("aba Estudos no rail, cabeçalho limpo, estado real da IA e das fontes sob pedido, sugestões")

            # 2. Fontes: sincronizar o Obsidian
            study.get_by_role("tab", name="Fontes").click()
            obs = study.locator('.st-source-card[data-source="obsidian"]')
            expect(obs).to_contain_text("falta sincronizar")
            expect(study.locator('.st-source-card[data-source="notion"]')).to_contain_text("Não conectado")
            expect(study.locator('.st-source-card[data-source="notion"] .st-howto')).to_have_attribute("open", "")
            obs.get_by_role("button", name="Sincronizar agora").click()
            expect(obs.locator(".st-source-facts dd").first).to_have_text("3", timeout=20000)
            expect(study.locator(".st-embed")).to_contain_text("Ativa")
            expect(obs.locator(".st-source-facts dd").nth(1)).to_have_text("3 de 3", timeout=20000)
            shot("02-fontes")
            ok("Fontes: Notion sem conexão com instruções; Obsidian sincronizado com contagens reais e vetores")

            # 3. Só buscar: resultados editoriais com motivo e relevância
            study.get_by_role("tab", name="Conversar").click()
            study.locator(".st-mode").click()
            page.get_by_role("menuitemradio", name="Só buscar", exact=True).click()
            box = study.get_by_label("Pergunta para o Lumen")
            box.fill("hipocampo e consolidação")
            box.press("Enter")
            first = study.locator(".st-results .st-result").first
            expect(first.locator(".st-result-title")).to_have_text("Memória e sono", timeout=10000)
            expect(first.locator(".st-reasons")).to_contain_text("Significado parecido")
            expect(first.locator(".st-rel")).to_contain_text("100%")
            expect(study.locator(".st-results-how")).to_contain_text("palavras e por significado")
            shot("03-busca")
            ok("busca híbrida na tela: título, origem, trecho, motivo real e relevância calculada")

            # 4. Conversa com streaming, citação clicável e fontes
            study.locator(".st-mode").click()
            page.get_by_role("menuitemradio", name="Automático", exact=True).click()
            box.fill("Como o sono ajuda a memória? Prefiro exemplos práticos.")
            box.press("Enter")
            answer = study.locator(".st-msg.bot").last
            expect(answer.locator(".st-answer-foot")).to_be_visible(timeout=20000)
            expect(answer.locator(".st-cite")).to_have_count(1)
            expect(answer).to_contain_text("removeu 1 referência")
            expect(answer).not_to_contain_text("qwen3")  # detalhe técnico fica no menu, não na resposta
            expect(answer.locator(".st-ref").first).to_contain_text("Memória e sono")
            expect(study.locator(".st-sources-panel")).to_be_hidden()
            shot("04-conversa")
            answer.locator(".st-cite").first.click()
            panel = study.locator(".st-sources-panel")
            expect(panel).to_be_visible()
            expect(panel.locator(".st-result").first).to_contain_text("Memória e sono")
            expect(panel.locator('.st-result[data-sid="S1"]')).to_have_class("st-result flash")
            shot("04b-fontes")
            panel.get_by_role("button", name="Fechar fontes").click()
            expect(panel).to_be_hidden()
            answer.locator(".st-ref").first.click()
            expect(panel.locator('.st-result[data-sid="S1"]')).to_have_class("st-result flash")
            answer.get_by_role("button", name="Copiar").click()
            expect(answer.get_by_role("button", name="Copiado")).to_be_visible()
            assert "consolidação" in page.evaluate("navigator.clipboard.readText()")
            answer.get_by_role("button", name="Mais opções").click()
            expect(page.get_by_role("menuitem", name="Aprofundar")).to_be_visible()
            page.get_by_role("menuitem", name="Informações da resposta").click()
            info = page.locator(".st-info")
            expect(info).to_contain_text("IA local (Ollama)")
            expect(info).to_contain_text("1 citada(s) de")
            expect(info).to_contain_text("1 sem fonte correspondente")
            page.keyboard.press("Escape")
            expect(info).to_have_count(0)
            ok("conversa em streaming: citação e referência abaixo da resposta abrem o painel de fontes (fechado por padrão), "
               "copiar com retorno, detalhes técnicos em Mais opções")

            # 5. Histórico: aparece, renomeia, fixa, pesquisa
            item = study.locator(".st-conv").first
            expect(item).to_be_visible(timeout=10000)
            item.hover()
            item.locator(".st-conv-more").click()
            page.get_by_role("menuitem", name="Renomear").click()
            page.locator("dialog[open] input").fill("Sono e memória (renomeada)")
            page.locator("dialog[open]").get_by_role("button", name="Salvar").click()
            expect(study.locator(".st-conv-title").first).to_contain_text("renomeada", timeout=5000)
            study.get_by_label("Pesquisar conversas").fill("behaviorismo")
            expect(study.locator(".st-conv")).to_have_count(0, timeout=5000)
            study.get_by_label("Pesquisar conversas").fill("")
            expect(study.locator(".st-conv")).to_have_count(1, timeout=5000)
            ok("histórico: renomear e pesquisar conversas")

            # 6. Salvar no Obsidian: prévia, nada gravado antes de confirmar
            answer.get_by_role("button", name="Salvar").click()
            page.get_by_role("menuitem", name="Criar nota no Obsidian…").click()
            page.locator("dialog[open] input").fill("Sono e memória")
            page.locator("dialog[open]").get_by_role("button", name="Ver prévia").click()
            dlg = page.locator("dialog[open]")
            expect(dlg).to_contain_text("nada foi gravado")
            expect(dlg).to_contain_text("C04 Claude Obsidian/01 Outputs/")
            outputs = vault / "C04 Claude Obsidian/01 Outputs"
            assert not [f for f in outputs.iterdir() if f.name != ".keep.md"], "gravou antes de confirmar"
            shot("05-previa")
            dlg.get_by_role("button", name="Confirmar e salvar").click()
            expect(page.locator("#toast")).to_contain_text("Nota criada", timeout=8000)
            saved = [f for f in outputs.iterdir() if f.name != ".keep.md"]
            assert len(saved) == 1 and "author: lumen-ai" in saved[0].read_text("utf-8"), saved
            ok("gravação no Obsidian só depois da prévia e da confirmação, no formato Output IA")

            # 7. Estudar: flashcards e revisão espaçada
            act = learn_go("Revisar", "Flashcards")
            act.get_by_label("Assunto", exact=True).fill("memória e sono")
            act.get_by_role("button", name="Criar flashcards", exact=True).click()
            expect(act.locator(".st-item")).to_contain_text("O que consolida a memória?", timeout=15000)
            expect(act.locator(".st-item .st-src-chip").first).to_contain_text("Memória e sono")
            shot("06-flashcards")
            study.get_by_role("button", name="Revisar 2 agora").click()
            study.get_by_role("button", name="Mostrar resposta").click()
            page.keyboard.press("3")
            study.get_by_role("button", name="Mostrar resposta").click()
            study.get_by_role("button", name="Errei").click()
            expect(study.locator(".st-session-end")).to_contain_text("Revisão concluída")
            ok("Estudar: flashcards com origem real e revisão espaçada pelo teclado")

            # 7b. Contexto e comandos (Study AI 2.0, fase 3)
            study.get_by_role("tab", name="Conversar").click()
            meter = study.locator(".st-ctx")
            expect(meter).to_contain_text("/ 32 mil")  # uso medido no passo 4; o Automático (qwen3.5:4b) usa 32k (D24)
            for n, q in ((2, "E o hipocampo?"), (3, "E o sono REM?")):
                box.fill(q)
                box.press("Enter")
                expect(study.locator(".st-msg.bot .st-answer-foot")).to_have_count(n, timeout=20000)
            box.fill("/")
            slash = study.locator("#st-slash")
            expect(slash).to_be_visible()
            for text in ("/clear", "/compact [foco]", "/context", "/explicar <assunto>", "/buscar-cerebro <assunto>", "skill do seu cofre"):
                expect(slash).to_contain_text(text)
            shot("07b-menu-barra")
            box.fill("/comp")
            expect(slash.get_by_role("option")).to_have_count(2)  # /compact e /comparar
            box.press("ArrowDown")
            box.press("ArrowUp")
            box.press("Enter")  # escolhe /compact: tem argumento opcional, então só preenche
            expect(box).to_have_value("/compact ")
            box.press("Enter")
            expect(page.locator("#toast")).to_contain_text("Conversa compactada: 2 mensagem(ns)", timeout=15000)
            expect(study.locator(".st-summary-mark")).to_be_visible()
            expect(meter).to_contain_text("≈")
            meter.click()
            ctxp = page.locator(".st-ctx-panel")
            for text in ("Contexto desta conversa", "Fontes", "Histórico da conversa", "O resumo cobre 2 mensagem(ns)", "Nenhuma é apagada"):
                expect(ctxp).to_contain_text(text)
            shot("07c-contexto")
            page.keyboard.press("Escape")
            last = study.locator(".st-msg.bot").last
            last.get_by_role("button", name="Mais opções").click()
            page.get_by_role("menuitem", name="Fixar no contexto").click()
            expect(last.locator(".st-pin-badge")).to_be_visible()
            page.keyboard.press("Control+Shift+K")  # atalho: depois de compactar, só sobram as duas últimas trocas
            expect(page.locator("#toast")).to_contain_text("Ainda não há mensagens antigas", timeout=8000)
            box.fill("/modo explicar")
            box.press("Enter")
            expect(study.locator(".st-mode")).to_contain_text("Explicar")
            box.fill("/modo conversar")  # "conversar" é sinônimo de Automático
            box.press("Enter")
            expect(study.locator(".st-mode")).to_contain_text("Automático")
            box.fill("/clear")
            box.press("Enter")
            expect(study.locator(".st-msg")).to_have_count(0)
            expect(page.locator("#toast")).to_contain_text("A anterior continua no histórico")
            page.locator("#toast").get_by_role("button", name="Desfazer").click()
            expect(study.locator(".st-msg.bot")).to_have_count(3, timeout=8000)
            expect(study.locator(".st-summary-mark")).to_be_visible()
            expect(study.locator(".st-msg.bot").last.locator(".st-pin-badge")).to_be_visible()
            shot("07d-desfazer")
            ok("contexto: medidor com o uso medido, menu / com comandos e skills do cofre pelo teclado, /compact sem apagar "
               "nada, /context com as partes, fixar, Ctrl+Shift+K e /clear com Desfazer")

            # 7c. Função inteligente e esforço (fase 3, itens 4 e 5)
            chip = study.locator(".st-mode")
            expect(chip).to_contain_text("Automático · Explicar")  # o que o Automático decidiu na última resposta
            expect(chip).to_have_attribute("data-tip", "Escolha automática: quer entender um mecanismo")  # o motivo do roteador
            chip.click()
            expect(page.get_by_role("menuitemradio", name="Automático", exact=True)).to_have_attribute("aria-checked", "true")
            expect(page.locator(".st-chip-menu")).to_contain_text("Esforço")
            shot("07e-chip")
            page.get_by_role("menuitemradio", name="Profundo").click()
            expect(chip).to_contain_text("Profundo")
            box.fill("Como o sono profundo ajuda a memória?")
            box.press("Enter")
            expect(study.locator(".st-msg.bot .st-answer-foot")).to_have_count(4, timeout=20000)
            last = study.locator(".st-msg.bot").last
            last.get_by_role("button", name="Mais opções").click()
            page.get_by_role("menuitem", name="Informações da resposta").click()
            expect(page.locator(".st-info")).to_contain_text("Profundo")
            page.keyboard.press("Escape")
            box.fill("/esforco rápido")
            box.press("Enter")
            expect(chip).to_contain_text("Rápido")
            box.fill("/esforco automático")
            box.press("Enter")
            expect(chip).not_to_contain_text("Rápido")
            ok("Função inteligente: o chip mostra o modo e o esforço escolhidos e o motivo; trocar pelo chip ou por /esforco "
               "muda a resposta (Profundo nas informações)")

            # 7d. Anexos e /tela (fase 4): clipe, print colado, fichas, fonte citada, apagar a conversa apaga os arquivos
            box.fill("/clear")
            box.press("Enter")
            expect(study.locator(".st-msg")).to_have_count(0)
            study.locator(".st-composer input[type=file]").set_input_files(
                files=[{"name": "funil.pdf", "mimeType": "application/pdf", "buffer": pdf_text("Funil de vendas: topo, meio e fundo")}])
            page.evaluate("""(b64) => { const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)), dt = new DataTransfer();
                dt.items.add(new File([bytes], "", { type: "image/png" }));
                document.querySelector('[aria-label="Pergunta para o Lumen"]').dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true })); }""",
                          base64.b64encode(shot_png.read_bytes()).decode())
            page.evaluate("""() => { const dt = new DataTransfer(), main = document.querySelector(".st-main");
                dt.items.add(new File(["Roteiro: gancho, promessa e prova."], "roteiro.txt", { type: "text/plain" }));
                main.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
                main.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); }""")
            chips = study.locator(".st-attach-row .st-attach-chip")
            expect(chips).to_have_count(3)
            expect(chips.nth(2)).to_contain_text("Texto", timeout=15000)
            expect(chips.nth(0)).to_contain_text("PDF", timeout=15000)
            expect(chips.nth(1)).to_contain_text("Imagem", timeout=15000)
            expect(chips.nth(1)).to_contain_text("print-")  # print colado sem nome ganha um
            expect(chips.nth(1).locator("img")).to_be_visible()
            shot("07f-anexos")
            box.press("Enter")  # sem texto: a pergunta padrão sobre os anexos
            expect(study.locator(".st-msg.bot .st-answer-foot")).to_have_count(1, timeout=20000)
            expect(chips).to_have_count(0)
            user = study.locator(".st-msg.user").last
            expect(user.locator(".st-attach-chip")).to_have_count(3)
            expect(user).to_contain_text("O que estes anexos trazem de importante")
            answer = study.locator(".st-msg.bot").last
            expect(answer.locator(".st-ref").first).to_contain_text("funil.pdf")
            answer.locator(".st-ref").first.click()
            panel = study.locator(".st-sources-panel")
            expect(panel.locator('.st-result[data-source="anexo"]')).to_have_count(3)
            expect(panel.locator(".st-thumbs img")).to_be_visible()
            expect(panel.locator('.st-result[data-source="anexo"]').get_by_role("button", name="Abrir original")).to_have_count(0)
            assert page.evaluate("[...document.querySelectorAll('.st-thumbs img')].every((i) => i.naturalWidth > 0)"), "miniatura não carregou"
            shot("07g-anexo-citado")
            panel.get_by_role("button", name="Fechar fontes").click()
            box.fill("/tela o que é isso?")
            box.press("Enter")
            expect(page.locator("#toast")).to_contain_text("A IA viu a janela “Janela de teste — teste.exe”", timeout=20000)
            expect(study.locator(".st-msg.bot .st-answer-foot")).to_have_count(2, timeout=20000)
            expect(study.locator(".st-msg.user").last).to_contain_text("Tela vista nesta pergunta")
            shot("07h-tela")
            assert len(list(media.iterdir())) == 3, list(media.iterdir())  # só os três anexos; a tela não foi para o disco
            active = study.locator(".st-conv.active")
            active.hover()
            active.locator(".st-conv-more").click()
            page.get_by_role("menuitem", name="Apagar").click()
            page.locator("dialog[open]").get_by_role("button", name="Apagar").click()
            expect(page.locator("#toast")).to_contain_text("Conversa apagada", timeout=8000)
            assert not list(media.iterdir()), "os anexos ficaram depois de apagar a conversa"
            study.locator(".st-conv").first.click()  # volta à conversa dos passos anteriores (com fontes, para o passo 9)
            expect(study.locator(".st-msg.bot")).to_have_count(4, timeout=8000)
            ok("anexos: clipe, print colado (Ctrl+V) e arquivo solto na conversa, com o tipo conferido, fichas com o andamento e miniatura, pergunta padrão, "
               "anexo citado como fonte S1 com miniatura, /tela com aviso e nada no disco, apagar a conversa apaga os arquivos")

            # 7e. Explicação com diagrama e checagem, e mapa mental no chat (fase 5), na largura mínima da janela
            page.set_viewport_size({"width": 520, "height": 860})
            box.fill("/clear")
            box.press("Enter")
            expect(study.locator(".st-msg")).to_have_count(0)
            box.fill("/esforco equilibrado")
            box.press("Enter")
            box.fill("/explicar como o sono consolida a memória")
            box.press("Enter")
            first = study.locator(".st-msg.bot").nth(0)
            dg = first.locator(".st-dg")
            expect(dg).to_be_visible(timeout=20000)
            expect(dg.locator(".st-dg-kicker")).to_have_text("Processo")
            parts = dg.locator(".st-dg-node")
            expect(parts).to_have_count(3)
            fits()
            dg.get_by_role("button", name="Passo a passo").click()  # os passos acendem em ordem, sozinhos
            expect(parts.nth(0)).to_have_class(re.compile(r"\blit\b"))
            expect(parts.nth(2)).not_to_have_class(re.compile(r"\blit\b"))
            expect(parts.nth(2)).to_have_class(re.compile(r"\blit\b"), timeout=6000)
            expect(dg.locator(".st-dg-detail")).to_contain_text("A lembrança passa a ficar no córtex.")
            parts.nth(0).focus()  # teclado: seta para a próxima parte e Enter abre a explicação dela
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            expect(parts.nth(1)).to_have_attribute("aria-pressed", "true")
            expect(dg.locator(".st-dg-detail")).to_contain_text("As ondas lentas reativam a lembrança.")
            dg.locator(".st-dg-list summary").click()  # a alternativa em texto
            expect(dg.locator(".st-dg-list")).to_contain_text("Codificação — O hipocampo grava o que você viveu.")
            expect(dg.locator(".st-dg-list")).to_contain_text("Codificação leva a Neocórtex")
            assert page.evaluate("""() => [...document.querySelectorAll('.st-dg-svg')].every((svg) => { const b = svg.getBoundingClientRect();
                return [...svg.querySelectorAll('.st-dg-node, .st-dg-link')].every((e) => { const r = e.getBoundingClientRect(); return r.right <= b.right + 1 && r.left >= b.left - 1; }); })"""), "parte do diagrama cortada na borda"
            dg.scroll_into_view_if_needed()
            shot("07i-diagrama-520")
            with page.expect_download() as dl:
                dg.get_by_role("button", name="Baixar PNG").click()
            assert Path(dl.value.path()).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and dl.value.suggested_filename.endswith(".png")
            page.emulate_media(reduced_motion="reduce")  # movimento reduzido: um passo por clique, nada anda sozinho
            dg.get_by_role("button", name="Ver de novo").click()
            expect(dg.get_by_role("button", name="Próximo passo (2 de 3)")).to_be_visible()
            page.wait_for_timeout(2000)
            expect(parts.nth(1)).not_to_have_class(re.compile(r"\blit\b"))
            dg.get_by_role("button", name="Próximo passo (2 de 3)").click()
            expect(parts.nth(1)).to_have_class(re.compile(r"\blit\b"))
            page.emulate_media(reduced_motion="no-preference")
            expect(first.locator(".st-explain-more")).to_contain_text("Mais simples")
            check = first.locator(".st-check")
            expect(check).to_contain_text("Por que dormir depois de estudar ajuda a lembrar?")
            check.locator("textarea").fill("Não sei")
            check.get_by_role("button", name="Responder").click()
            expect(check).to_contain_text("Faltou dizer o porquê.", timeout=15000)  # errou: a IA explica de outro jeito
            expect(study.locator(".st-msg.user").last).to_contain_text("Errei a checagem")
            expect(study.locator(".st-msg.bot .st-answer-foot")).to_have_count(2, timeout=20000)
            box.fill("/mapa-mental memória")
            box.press("Enter")
            mm = study.locator('.st-thread .st-dg[data-family="mapa"]')
            expect(mm).to_be_visible(timeout=20000)
            expect(mm.locator(".st-dg-node.center")).to_contain_text("Memória")
            expect(mm.locator(".st-dg-node:not(.center)")).to_have_count(7)
            fits()
            mm.scroll_into_view_if_needed()
            shot("07j-mapa-mental-520")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(400)
            expect(mm.locator(".st-dg-node:not(.center)")).to_have_count(7)  # redesenhado na largura nova (ramos dos dois lados)
            assert page.evaluate("""() => { const svg = document.querySelector('.st-dg[data-family="mapa"] .st-dg-svg'), c = svg.querySelector('.center').getBoundingClientRect();
                const xs = [...svg.querySelectorAll('.st-dg-node:not(.center)')].map((g) => g.getBoundingClientRect());
                return xs.some((r) => r.right < c.left) && xs.some((r) => r.left > c.right); }"""), "o mapa largo não pôs ramos dos dois lados do centro"
            mm.scroll_into_view_if_needed()
            shot("07k-mapa-mental-largo")
            active = study.locator(".st-conv.active")
            active.hover()
            active.locator(".st-conv-more").click()
            page.get_by_role("menuitem", name="Apagar").click()
            page.locator("dialog[open]").get_by_role("button", name="Apagar").click()
            expect(page.locator("#toast")).to_contain_text("Conversa apagada", timeout=8000)
            box.fill("/esforco automático")
            box.press("Enter")
            study.locator(".st-conv").first.click()
            expect(study.locator(".st-msg.bot")).to_have_count(4, timeout=8000)
            ok("explicação (fase 5): diagrama 2D em 520 px com os passos acendendo em ordem, parte aberta pelo teclado, lista em texto, PNG, "
               "movimento reduzido passo a passo, checagem errada volta à IA, /mapa-mental no chat e redesenhado na largura")

            # 8. Configurações: memória automática visível e administrável
            study.get_by_role("button", name="Configurações da IA").click()
            expect(page.get_by_role("heading", name="Configurações da IA")).to_be_visible()
            for label in ("Modelo para responder", "Modelo rápido"):  # Automático = o modelo medido (fase 2), trocável
                sel = study.get_by_label(label)
                expect(sel).to_have_value("")
                expect(sel.locator("option:checked")).to_have_text("Automático (qwen3.5:4b)")
            shot("07a-modelos")
            study.get_by_label("Modelo para responder").select_option("qwen3:8b")  # trocar: o rápido acompanha
            expect(study.get_by_label("Modelo rápido").locator("option:checked")).to_have_text("Automático (qwen3:8b)", timeout=8000)
            study.get_by_label("Modelo para responder").select_option("")
            expect(study.get_by_label("Modelo rápido").locator("option:checked")).to_have_text("Automático (qwen3.5:4b)", timeout=8000)
            ok("Modelos: o Automático mostra o modelo escolhido pela medição (qwen3.5:4b); trocar o de responder muda o rápido junto, e voltar ao Automático desfaz")
            study.get_by_role("button", name="Memória").click()
            mem = study.locator(".st-mem")
            expect(mem.filter(has_text="Prefere explicações com exemplos práticos.")).to_have_count(1, timeout=8000)
            expect(mem.filter(has_text="Sugestão: aprovar?")).to_have_count(1)
            shot("07-memorias")
            study.get_by_role("button", name="Limpar todas as memórias").click()
            confirm = page.locator("dialog[open]").get_by_role("button", name="Apagar todas")
            expect(confirm).to_be_disabled()
            page.locator("dialog[open]").get_by_label("Digite APAGAR para confirmar").fill("APAGAR")
            confirm.click()
            expect(study.locator(".st-mem")).to_have_count(0, timeout=5000)
            ok("memória: criada pela conversa, sugestão para aprovar, limpeza total com confirmação digitada")
            study.get_by_role("button", name="Seus dados no Lúmen").click()
            expect(study.locator(".st-data-row").filter(has_text="Conversas")).to_contain_text("1")
            expect(study.locator(".st-data-row").filter(has_text="O que o Lúmen sabe que você domina")).to_contain_text("1")
            study.locator(".st-mastery summary").click()  # o modelo do estudante, visível: a checagem errada da fase 5
            expect(study.locator(".st-mastery")).to_contain_text("memória e sono — com dificuldade (1 acerto(s), 2 erro(s))")  # os flashcards do passo 7 e a checagem do 7e
            expect(study).to_contain_text("Nenhum: tudo foi processado pela IA local.")
            shot("08-dados")
            ok("Seus dados: inventário real e nenhum envio externo")
            study.get_by_role("button", name="Voltar ao Cérebro").click()
            study.get_by_role("tab", name=re.compile("^Estudar")).click()  # o modelo do estudante sugere o que revisar (no início da aba)
            if study.locator('.st-lrn-screen[data-screen="home"]').is_hidden():
                study.get_by_role("tab", name=re.compile("^Estudar")).click()
            study.locator(".st-lrn-topics").get_by_role("button", name="memória e sono").click()
            expect(box).to_have_value("Explique memória e sono")
            box.fill("")

            # 9. Tamanhos menores sem rolagem horizontal; histórico e fontes viram painéis por cima
            study.get_by_role("tab", name="Conversar").click()
            side = study.locator(".st-side")
            expect(side).to_be_visible()
            study.get_by_role("button", name="Histórico de conversas").click()  # recolher: a conversa ocupa a largura
            expect(side).to_be_hidden()
            study.get_by_role("button", name="Histórico de conversas").click()
            expect(side).to_be_visible()
            for w in (1100, 760, 520):  # 520 px: a largura mínima da janela principal (launcher/Lumen.cs)
                page.set_viewport_size({"width": w, "height": 860})
                for tab in ("Fontes", "Salvos", "Estudar", "Conversar"):
                    study.get_by_role("tab", name=tab).click()
                    page.wait_for_timeout(250)
                    fits()
                shot(f"09-largura-{w}")
                if w <= 900:
                    expect(side).to_be_hidden()
                    study.get_by_role("button", name="Histórico de conversas").click()
                    expect(side).to_be_visible()
                    fits()
                    shot(f"09-largura-{w}-historico")
                    page.keyboard.press("Escape")
                    expect(side).to_be_hidden()
                study.locator(".st-src-toggle").click()
                expect(study.locator(".st-sources-panel")).to_be_visible()
                fits()
                shot(f"09-largura-{w}-fontes")
                page.keyboard.press("Escape")
                expect(study.locator(".st-sources-panel")).to_be_hidden()
            ok("1100, 760 e 520 px (mínimo da janela) sem rolagem horizontal nas quatro abas; histórico e fontes abrem por cima e fecham com Esc")

            # 10. Voz (fase 6): Integrações → Voice Studio, Configurações → Voz, Ouvir, apertar para falar e o player
            page.set_viewport_size({"width": 1440, "height": 900})
            page.locator("#nav-integrations").click()
            page.locator("#itab-voicestudio").click()
            vsp = page.locator("#integ-voicestudio")
            expect(vsp.locator(".vc-status .badge")).to_contain_text("Pronto (o app está aberto)", timeout=10000)
            expect(page.locator("#vs-badge")).to_contain_text("Pronto")
            expect(vsp.locator(".vc-status-meta")).to_contain_text("v0.5.7")
            rows = vsp.locator(".vc-voice")
            expect(rows).to_have_count(2)
            expect(rows.filter(has_text="Jhonny Sirverhand")).to_contain_text("Padrão")
            expect(rows.filter(has_text="Jhonny Sirverhand")).to_contain_text("Clonada")
            expect(rows.filter(has_text="Jhonny Sirverhand").locator(".vc-avatar")).to_have_text("JS")
            expect(vsp.get_by_role("button", name="Excluir")).to_have_count(0)  # o Lúmen não apaga vozes do estudante
            demo = rows.filter(has_text="Demo Voice")
            demo.get_by_role("button", name="Testar").click()
            expect(demo.get_by_role("button", name="Testar")).to_be_enabled(timeout=10000)
            shot("10a-voicestudio")
            demo.get_by_role("button", name="Usar como padrão").click()
            expect(rows.filter(has_text="Demo Voice")).to_contain_text("Padrão", timeout=8000)
            rows.filter(has_text="Jhonny Sirverhand").get_by_role("button", name="Usar como padrão").click()
            expect(rows.filter(has_text="Jhonny Sirverhand")).to_contain_text("Padrão", timeout=8000)
            for w in (1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 860})
                page.wait_for_timeout(250)
                fits()
                shot(f"10a-voicestudio-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            ok("Integrações → Voice Studio: estado real (Pronto, versão, GPU), galeria com avatar, selo Clonada e Padrão, Testar, "
               "Usar como padrão e sem Excluir, em 1100, 760 e 520 px")
            page.locator("#nav-study").click()
            study.get_by_role("button", name="Configurações da IA").click()
            study.get_by_role("button", name="Voz", exact=True).click()
            expect(study.get_by_label("Motor de voz")).to_have_value("voicestudio")
            expect(study.locator(".st-set-panel .vc-voice")).to_contain_text("Jhonny Sirverhand")
            expect(study.get_by_label("Velocidade da fala")).to_be_visible()
            study.get_by_label("Conversa (Ouvir e voz no chat)").select_option("demo0001")
            expect(page.locator("#toast")).to_contain_text("Voz salva", timeout=8000)
            study.get_by_label("Conversa (Ouvir e voz no chat)").select_option("")
            study.get_by_role("button", name="Testar a voz").click()
            expect(study.locator(".vc-test .t-caption")).to_contain_text("Jhonny Sirverhand", timeout=10000)
            shot("10b-config-voz")
            for w in (760, 520):
                page.set_viewport_size({"width": w, "height": 860})
                page.wait_for_timeout(250)
                fits()
                shot(f"10b-config-voz-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            study.get_by_role("button", name="Voltar ao Cérebro").click()
            ok("Configurações → Voz: motor, voz padrão com o mesmo componente, uma voz por uso, velocidade e Testar a voz")
            study.get_by_role("tab", name="Conversar").click()
            last = study.locator(".st-msg.bot").last
            last.get_by_role("button", name="Ouvir").click()
            bar = study.locator(".vc-bar")
            expect(bar).to_be_visible(timeout=10000)
            expect(bar).to_contain_text("Jhonny")
            expect(bar.locator(".vc-bar-count")).to_contain_text("frase", timeout=10000)
            expect(bar.get_by_role("status")).to_contain_text("falando")
            shot("10c-falando")
            bar.get_by_role("button", name="Pausar").click()
            expect(bar.get_by_role("status")).to_contain_text("pausado")
            bar.get_by_role("button", name="Parar a fala").click()
            expect(bar).to_have_count(0)
            talk = study.get_by_role("button", name="Apertar para falar")
            talk.hover()
            page.mouse.down()
            expect(talk).to_have_attribute("aria-pressed", "true", timeout=5000)
            page.mouse.up()
            expect(box).to_have_value("Explique keyframes no Premiere", timeout=8000)
            box.fill("")
            ok("Ouvir: a barra de fala com o avatar, frase X de N, pausar e parar; apertar para falar põe o texto transcrito na caixa")
            dg = study.locator(".st-thread .st-dg").first
            dg.scroll_into_view_if_needed()
            dg.get_by_role("button", name="Tour narrado").click()
            expect(dg.locator(".st-dg-node.now")).to_have_count(1, timeout=10000)  # a parte falada acende junto
            expect(study.locator(".vc-bar")).to_be_visible()
            shot("10c-tour-narrado")
            study.locator(".vc-bar").get_by_role("button", name="Parar a fala").click()
            expect(dg.get_by_role("button", name="Tour narrado")).to_have_attribute("aria-pressed", "false")
            ok("tour narrado do diagrama: a voz lê cada parte e a parte falada acende (light) junto")
            act = learn_go("Revisar", "Revisão em áudio")
            act.get_by_label("Assunto", exact=True).fill("memória e sono")
            act.get_by_role("button", name="Gerar a revisão", exact=True).click()
            player = study.locator(".vc-player")
            expect(player).to_be_visible(timeout=30000)
            expect(player.locator(".vc-chapter")).to_have_count(3)  # introdução + 2 capítulos
            player.locator(".vc-chapter").nth(1).click()
            page.wait_for_function("() => { const p = document.querySelector('.vc-player'); return p && p.vcAudio.currentTime > 0; }", timeout=8000)
            expect(player.locator('.vc-chapter[aria-current]')).to_have_count(1)
            shot("10d-player")
            page.set_viewport_size({"width": 520, "height": 860})
            page.wait_for_timeout(250)
            fits()
            shot("10d-player-520")
            page.set_viewport_size({"width": 1440, "height": 900})
            ok("revisão em áudio: roteiro com tetos, gerada pela fila, player com capítulos clicáveis (Range) em 1440 e 520 px")
            learn_go("Praticar", "Explique com suas palavras")
            fey = study.locator(".st-feynman")
            fey.get_by_label("Assunto", exact=True).fill("memória e sono")
            fey.get_by_label("Sua explicação").fill("Dormir depois de estudar ajuda o cérebro a guardar o que eu aprendi no dia.")
            fey.get_by_role("button", name="Avaliar a explicação").click()
            expect(fey.locator(".st-feynman-out")).to_contain_text("Ainda não (60%)", timeout=15000)
            expect(fey.locator(".st-feynman-list.warn")).to_contain_text("O papel do hipocampo.")
            expect(fey.get_by_role("button", name="Apertar para falar")).to_be_visible()
            fey.scroll_into_view_if_needed()
            shot("10e-feynman")
            ok("Feynman: explicar com as próprias palavras (texto ou microfone), retorno com o certo, o que faltou e as fontes")
            # 11. Fase 6, parte 2: Treino falado, Modelos de voz, Esta máquina, qualidade, voz por descrição e pronúncias
            learn_go("Praticar", "Treino falado")
            prac = study.locator(".st-practice")
            expect(prac.get_by_label("Cenário", exact=True)).to_contain_text("Venda para um cliente cético", timeout=8000)
            prac.get_by_label("Tema (opcional)").fill("persuasão")
            prac.get_by_role("button", name="Começar o treino").click()
            expect(prac.locator(".st-practice-character").first).to_contain_text("Por que eu confiaria em você?", timeout=15000)
            expect(page.locator(".vc-bar.floating")).to_be_visible(timeout=10000)  # o personagem fala com a voz dele (fora do chat, a barra flutua)
            expect(prac.get_by_role("button", name="Apertar para falar")).to_be_visible()  # responder falando
            prac.get_by_label("Sua resposta").fill("Tenho casos de clientes como você e garantia de 30 dias.")
            prac.get_by_role("button", name="Responder").click()
            expect(prac.locator(".st-practice-student")).to_have_count(1)
            expect(prac.locator(".st-practice-character")).to_have_count(2, timeout=15000)
            prac.get_by_role("button", name="Terminar e avaliar").click()
            # a nota geral é a média dos critérios (0,7 e 0,3), não o 0,55 que o modelo escreveu
            expect(prac.locator(".st-feynman-out")).to_contain_text("Continue treinando (50%)", timeout=15000)
            expect(prac.locator(".st-rubric li")).to_have_count(2)
            page.locator(".vc-bar").get_by_role("button", name="Parar a fala").click() if page.locator(".vc-bar").count() else None
            shot("11a-treino-falado")
            for w in (1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 860})
                page.wait_for_timeout(250)
                fits()
                shot(f"11a-treino-falado-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            ok("Treino falado: o personagem fala com a voz dele, o estudante responde, rubrica com tetos no fim, em 1440, 1100, 760 e 520 px")
            page.locator("#nav-integrations").click()
            page.locator("#itab-voicestudio").click()
            models = vsp.locator(".vc-models")
            seg = models.get_by_role("radiogroup", name="Pacote de modelos")
            expect(seg.get_by_role("radio")).to_have_count(5, timeout=10000)
            expect(seg.get_by_role("radio", name="Máximo")).to_have_attribute("aria-checked", "true")
            seg.get_by_role("radio", name="Equilibrado").click()
            expect(models.get_by_role("button", name=re.compile("Instalar pacote Equilibrado"))).to_contain_text("2,2 GB")
            expect(models.locator(".vc-model")).to_have_count(4)
            expect(models.locator(".vc-model.is-installed")).to_have_count(2)
            seg.get_by_role("radio", name="Rápido").click()
            expect(models.get_by_role("button", name="Usar pacote Rápido")).to_be_enabled()
            expect(vsp.get_by_label("Motor de voz")).to_have_value("omnivoice")
            expect(vsp.get_by_label("Fala do chat")).to_contain_text("Equilibrado (12 passos)")
            mach = vsp.locator(".vc-machine")
            expect(mach.get_by_role("meter").first).to_be_visible(timeout=10000)
            expect(mach).to_contain_text("livres")
            for empty in ("null", "undefined", "NaN"):  # nenhum valor vazio vira texto na tela
                expect(vsp.locator(".vc-models")).not_to_contain_text(empty)
                expect(mach).not_to_contain_text(empty)
            vsp.get_by_role("button", name="Criar voz para personagem").click()
            dlg = page.get_by_role("dialog", name="Criar voz para personagem")
            dlg.get_by_label("Nome").fill("Cliente cético")
            dlg.get_by_label("Descrição").fill("cliente cético, homem, 40 anos")
            dlg.get_by_role("button", name="Entender a descrição").click()
            expect(dlg).to_contain_text("male, middle-aged", timeout=8000)
            shot("11b-criar-voz")
            dlg.get_by_role("button", name="Fechar").click()
            vsp.get_by_role("button", name="Mover para o D:").click()
            mv = page.get_by_role("dialog", name="Mover os modelos do Voice Studio para o D:")
            expect(mv).to_contain_text("Copiar e conferir", timeout=10000)
            expect(mv.get_by_role("button", name="Apagar a cópia antiga")).to_be_disabled()  # só com o app usando a pasta nova
            shot("11b-mover")
            mv.get_by_role("button", name="Fechar").click()
            shot("11c-modelos")
            for w in (1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 860})
                page.wait_for_timeout(300)
                fits()
                shot(f"11c-modelos-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            ok("Modelos de voz: pacotes como no Voice Studio (o que falta baixar), motores, qualidade por uso, Esta máquina e "
               "Criar voz para personagem, em 1440, 1100, 760 e 520 px")
            import urllib.request
            with urllib.request.urlopen(vs_url + "/__writes") as r:
                writes = json.load(r)
            assert not writes, writes
            ok("nenhuma escrita no Voice Studio sem o clique (telas abertas, treino, prévia e sondagens)")
            # agora, de propósito, dois cliques que escrevem: só eles aparecem no registro
            models.get_by_role("button", name="Usar pacote Rápido").click()
            page.locator("dialog.confirm").get_by_role("button", name="Usar", exact=True).click()
            expect(page.locator("#toast")).to_contain_text("Pacote Rápido escolhido", timeout=8000)
            page.locator("#nav-study").click()
            study.get_by_role("button", name="Configurações da IA").click()
            study.get_by_role("button", name="Voz", exact=True).click()
            pron = study.locator(".st-set-card", has=page.get_by_role("heading", name="Pronúncias"))
            expect(pron).to_contain_text("Nenhuma pronúncia ainda", timeout=10000)
            pron.get_by_label("Termo").fill("CTA")
            pron.get_by_label("Como deve soar").fill("cê tê á")
            pron.get_by_role("button", name="Adicionar").click()
            expect(pron.locator(".vc-model-row")).to_contain_text("CTA", timeout=8000)
            pron.get_by_role("button", name="Ouvir").click()
            expect(pron).to_contain_text("A voz recebe: “Crie um keyframe no Premiere e defina o cê tê á.”", timeout=10000)
            expect(study.get_by_label("Ligar o Voice Studio sozinho")).to_be_checked()
            shot("11d-pronuncias")
            for w in (760, 520):
                page.set_viewport_size({"width": w, "height": 860})
                page.wait_for_timeout(250)
                fits()
                shot(f"11d-pronuncias-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            with urllib.request.urlopen(vs_url + "/__writes") as r:
                writes = json.load(r)
            assert writes == [["PUT", "/api/settings/performance-profile"], ["POST", "/pronunciation"]], writes
            ok("Pronúncias: adicionar e ouvir como a voz recebe; só os dois cliques (pacote e pronúncia) escreveram no Voice Studio")

            # 12. Fase 6, parte 3: Conversa por voz em tempo real (ajustes, Ctrl+K, orbe nos estados, legenda parcial/final,
            #     cartão ao vivo, interromper, mudo, pílula minimizada, encerrar e voltar ao chat com o texto, nas 4 larguras)
            call_cfg = study.locator(".st-set-card", has=page.get_by_role("heading", name="Conversa por voz"))
            expect(call_cfg).to_be_visible()
            expect(call_cfg).to_contain_text("Microfone Simulado USB")
            expect(call_cfg.get_by_label("Modo")).to_have_value("handsfree")
            expect(call_cfg.get_by_label("Fim da fala")).to_have_value("normal")
            call_cfg.get_by_label("Tamanho das respostas").select_option("chat")
            expect(page.locator("#toast")).to_contain_text("Salvo", timeout=8000)
            call_cfg.get_by_label("Tamanho das respostas").select_option("short")
            shot("12a-config-chamada")
            study.get_by_role("button", name="Voltar ao Cérebro").click()
            study.get_by_role("tab", name="Conversar").click()

            # Destino no Ctrl+K + botão "Conversa por voz" ao lado da caixa de mensagem
            page.keyboard.press("Control+k")
            pal = page.locator("#palette")
            expect(pal).to_be_visible()
            pal.locator("input").fill("Conversa por voz")
            expect(pal.get_by_role("option", name=re.compile("Conversa por voz"))).to_be_visible()
            page.keyboard.press("Escape")
            expect(pal).to_be_hidden()

            box.fill("/clear")
            box.press("Enter")
            expect(study.locator(".st-msg")).to_have_count(0)
            open_call_btn = study.get_by_role("button", name="Conversa por voz")
            expect(open_call_btn).to_be_visible()
            open_call_btn.click()

            call_view = study.locator(".st-call")
            orb = call_view.locator(".st-call-orb")
            mic_open = call_view.locator(".st-call-mic-open")
            expect(call_view).to_be_visible(timeout=8000)
            expect(study.locator(".st-main")).to_be_hidden()
            expect(call_view.locator(".st-call-orb-core .vc-avatar")).to_have_text("JS")
            expect(call_view.locator(".st-call-state")).to_have_text("Ouvindo", timeout=8000)
            expect(mic_open).to_be_visible()
            expect(orb).to_have_attribute("data-state", "listening")

            # Estados do orbe, movimento reduzido, legenda parcial -> final, frase destacada e interrupção
            page.evaluate("""() => {
                const F = window.lumenStudy.feedCallEvent;
                F({ type: "partial", text: "Explica a consolida…" });
            }""")
            expect(call_view.locator(".st-call-turn.user.partial")).to_have_text("Explica a consolida…")

            page.emulate_media(reduced_motion="reduce")
            page.evaluate("""() => window.lumenStudy.feedCallEvent({ type: "level", source: "mic", level: 0.9 })""")
            assert page.evaluate("""() => getComputedStyle(document.querySelector('.st-call-orb')).getPropertyValue('--amp').trim() === '0.00'"""), "prefers-reduced-motion não zerou --amp"
            page.emulate_media(reduced_motion="no-preference")

            page.evaluate("""() => window.lumenStudy.feedCallEvent({ type: "state", active: true, state: "end_of_speech", label: "Entendi" })""")
            expect(orb).to_have_attribute("data-state", "understood")
            page.wait_for_timeout(320)
            page.evaluate("""() => window.lumenStudy.feedCallEvent({ type: "state", active: true, state: "thinking", label: "Pensando…" })""")
            expect(orb).to_have_attribute("data-state", "thinking")
            page.evaluate("""() => {
                const F = window.lumenStudy.feedCallEvent;
                F({ type: "final", text: "Explica a consolidação da memória" });
                F({ type: "state", active: true, state: "speaking", label: "Falando" });
                F({ type: "token", text: "O hipocampo registra o episódio. Depois o sono profundo fixa no córtex.", replace: true });
                F({ type: "sentence", i: 0, text: "O hipocampo registra o episódio." });
            }""")
            expect(orb).to_have_attribute("data-state", "speaking")
            expect(call_view.locator(".st-call-turn.user.final").first).to_have_text("Explica a consolidação da memória")
            expect(call_view.locator("mark.st-call-now")).to_have_text("O hipocampo registra o episódio.")
            shot("12b-chamada-falando")

            call_view.get_by_role("button", name="Interromper").click()
            page.evaluate("""() => window.lumenStudy.feedCallEvent({ type: "interrupted", text: "O hipocampo registra…" })""")
            expect(call_view.locator(".st-call-cut")).to_have_text("interrompida")
            expect(call_view.locator(".st-call-state")).to_have_text("Ouvindo", timeout=5000)

            # Mudo: esconde "Microfone aberto" e mostra de novo ao tirar do mudo
            call_view.get_by_role("button", name="Silenciar microfone").click()
            expect(mic_open).to_be_hidden(timeout=5000)
            expect(call_view.locator(".st-call-state")).to_have_text("Microfone silenciado")
            call_view.get_by_role("button", name="Silenciar microfone").click()
            expect(mic_open).to_be_visible(timeout=5000)

            # Turno real no servidor simulado -> gera cartão real de mapa mental na chamada e grava na conversa
            page.evaluate("""() => window.lumenStudy.api("/api/study/__call_sim", { text: "Cria um mapa mental de memória" })""")
            call_mm = call_view.locator('.st-call-card .st-dg[data-family="mapa"]')
            expect(call_mm).to_be_visible(timeout=15000)
            expect(call_mm.locator(".st-dg-node.center")).to_contain_text("Memória")
            expect(call_view.locator(".st-call-state")).to_have_text("Ouvindo", timeout=10000)
            shot("12c-chamada-cartao")

            # Responsividade da chamada nas quatro larguras (1440, 1100, 760 e 520 px)
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 860})
                page.wait_for_timeout(250)
                fits()
                shot(f"12d-chamada-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})

            # Minimizar para pílula flutuante enquanto navega pelo app, e reabrir
            call_view.get_by_role("button", name="Minimizar chamada").click()
            pill = page.locator(".st-call-pill")
            expect(pill).to_be_visible()
            expect(call_view).to_be_hidden()
            page.locator("#nav-home").click()
            expect(pill).to_be_visible()
            fits()
            shot("12e-pilula-flutuante")
            pill.get_by_role("button", name="Voltar para a chamada").click()
            expect(call_view).to_be_visible()
            expect(pill).to_be_hidden()

            # Encerrar -> volta ao chat normal com a fala e o cartão salvos no histórico
            call_view.get_by_role("button", name="Encerrar chamada").click()
            expect(call_view).to_be_hidden(timeout=8000)
            expect(study.locator(".st-main")).to_be_visible()
            expect(study.locator(".st-msg.user").last).to_contain_text("Cria um mapa mental de memória", timeout=8000)
            expect(study.locator('.st-thread .st-dg[data-family="mapa"]')).to_be_visible(timeout=8000)
            shot("12f-pos-chamada-chat")

            with urllib.request.urlopen(vs_url + "/__writes") as r:
                writes = json.load(r)
            assert writes == [["PUT", "/api/settings/performance-profile"], ["POST", "/pronunciation"]], writes
            ok("Conversa por voz (fase 6, parte 3): ajustes, Ctrl+K, orbe nos estados e sem movimento reduzido, legenda parcial e final, "
               "frase destacada, cartão de mapa mental ao vivo, interromper, mudo, pílula flutuante e retorno ao chat com o histórico em 1440, 1100, 760 e 520 px")
            assert not errors, errors
            # 13. Fase 7: produtos reais do backend, imagem simulada e PDF pelo Edge real.
            page.evaluate("window.lumenStudy.newConversation()")
            box = page.get_by_role("textbox", name="Pergunta para o Lumen", exact=True)
            box.fill("/imagem paisagem lua")
            box.press("Enter")
            product = study.locator(".st-artifact")
            expect(product).to_have_count(1, timeout=20000)
            expect(product.locator("img")).to_be_visible()
            expect(product).to_contain_text("Gerada por IA, pode conter erros")
            box.fill("/pdf revisao memória")
            box.press("Enter")
            expect(product).to_have_count(2, timeout=60000)
            expect(product.last).to_contain_text("1 página(s)")
            with page.expect_download() as dl:
                product.last.get_by_role("link", name="Baixar PDF").click()
            downloaded = dl.value
            downloaded.save_as(str(ART / "13-revisao.pdf"))
            assert (ART / "13-revisao.pdf").read_bytes().startswith(b"%PDF-")
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900})
                fits()
                shot(f"13-produtos-{w}")
            cid = page.evaluate("window.lumenStudy.S.conv.id")
            page.reload()
            page.locator("#nav-study").click()
            page.evaluate("cid => window.lumenStudy.openConversation(cid)", cid)
            expect(study.locator(".st-artifact")).to_have_count(2, timeout=10000)
            box.fill("/explicar memória e sono")
            box.press("Enter")
            print_btn = study.get_by_role("button", name="Gerar PDF", exact=True)
            expect(print_btn).to_be_visible(timeout=20000)
            print_btn.click()
            expect(study.locator(".st-artifact")).to_have_count(3, timeout=60000)
            page.evaluate("window.lumenStudy.openSettings('pdf')")
            expect(page.get_by_role("heading", name="PDFs e imagens", exact=True)).to_be_visible()
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900})
                fits()
                shot(f"13-configuracoes-{w}")
            ok("Fase 7: /imagem, /pdf, download do PDF real, persistência e reabertura nas quatro larguras")
            # 14. Fase 8: criação real no cofre temporário, desfazer e pesquisa no Edge com fontes simuladas.
            page.evaluate("""async () => {
                await window.lumenStudy.api('/api/study/settings', {privacy: {organize: 'ai', open_windows: true}, search: {web: true}});
                await window.lumenStudy.api('/api/study/__agent_sim', {});
                window.lumenStudy.show(); window.lumenStudy.newConversation();
            }""")
            page.get_by_role("button", name="Voltar ao Cérebro", exact=True).click()
            box.fill("/nota resumo sobre memória e sono")
            box.press("Enter")
            created = study.locator(".st-created")
            expect(created).to_have_count(1, timeout=20000)
            expect(created.get_by_role("link", name="Abrir criação")).to_have_attribute("href", re.compile("^obsidian://"))
            note_files = list((vault / "C04 Claude Obsidian/01 Outputs").glob("*.md"))
            assert any("author: lumen-ai" in f.read_text("utf-8") for f in note_files)
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"14-criacao-{w}")
            cid = page.evaluate("window.lumenStudy.S.conv.id")
            page.evaluate("cid => window.lumenStudy.openConversation(cid)", cid)
            expect(created.get_by_role("button", name="Desfazer criação")).to_be_visible()
            created.get_by_role("button", name="Desfazer criação").click()
            expect(created).to_contain_text("Criação desfeita", timeout=8000)
            assert list((vault / ".trash").glob("lumen-*.md"))
            page.evaluate("""async () => {await window.lumenStudy.api('/api/study/settings', {privacy: {organize: 'ask'}}); window.lumenStudy.newConversation();}""")
            box.fill("/nota outra revisão de memória")
            box.press("Enter")
            expect(study.locator(".st-pending")).to_be_visible(timeout=20000)
            study.locator(".st-pending").get_by_role("button", name="Cancelar", exact=True).click()
            expect(study.locator(".st-pending")).to_have_count(0)
            page.evaluate("window.lumenStudy.newConversation()")
            box.fill("/web memória e sono")
            box.press("Enter")
            guided = study.locator(".st-browser")
            expect(guided).to_be_visible(timeout=15000)
            guided.get_by_role("button", name="Pausar pesquisa").click()
            expect(guided).to_contain_text("Pesquisa pausada", timeout=8000)
            shot("14-pesquisa-pausada")
            guided.get_by_role("button", name="Retomar pesquisa").click()
            expect(guided).to_contain_text("Pesquisa concluída", timeout=25000)
            expect(study.locator(".st-msg.bot").last).to_be_visible(timeout=10000)
            sources = page.evaluate("window.lumenStudy.S.conv.messages.at(-1).sources")
            assert any(s.get("url") == "https://example.org/memoria" for s in sources), sources
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"14-pesquisa-{w}")
            page.evaluate("window.lumenStudy.openSettings('privacy')")
            expect(page.get_by_role("heading", name="Aplicativos permitidos", exact=True)).to_be_visible()
            expect(page.get_by_role("combobox", name="Criar notas e páginas (nível 2)")).to_have_value("ask")
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"14-permissoes-{w}")
            ok("Fase 8: /nota com criação, link, persistência e desfazer real no cofre temporário; prévia e cancelamento; /web com Edge, miniatura, pausar, retomar e fontes; permissões nas quatro larguras")
            # 15. Fase 9: rubrica, entrega por arquivo, plano, catálogo, skills e avaliação persistida.
            page.get_by_role("button", name="Voltar ao Cérebro", exact=True).click()
            act = learn_go("Praticar", "Prática com correção")
            act.get_by_role("textbox", name="Assunto", exact=True).fill("memória e sono")
            act.get_by_role("button", name="Criar prática", exact=True).click()
            exercise = study.locator(".st-exercise")
            expect(exercise).to_contain_text("Sono", timeout=20000)
            exercise.get_by_role("textbox", name="Sua entrega", exact=True).fill("O sono consolida a memória.")
            exercise.locator('input[type="file"]').set_input_files({"name": "Minha entrega.txt", "mimeType": "text/plain", "buffer": b"Vou revisar antes de dormir."})
            expect(exercise.locator(".st-attach-chip")).to_contain_text("Pronto", timeout=10000)
            exercise.get_by_role("button", name="Corrigir entrega", exact=True).click()
            expect(exercise.locator(".st-attempt")).to_contain_text("70%", timeout=20000)
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900})
                study.locator(".st-lrn-act:not([hidden]) .st-item-head").scroll_into_view_if_needed()
                assert study.locator(".st-item-head > .btn").evaluate_all("els => els.every(el => el.scrollWidth <= el.clientWidth + 1)"), "Ações do item não podem ter texto cortado"
                fits(); shot(f"15-pratica-{w}")
            item_id = page.evaluate("async () => (await window.lumenStudy.api('/api/study/items?kind=exercise')).items[0].id")
            page.reload()
            page.locator("#nav-study").click()
            study.get_by_role("tab", name=re.compile("^Estudar")).click()  # recarregou: abre no início, com os materiais recentes
            study.locator(".st-learn-item").filter(has_text="Prática com correção").first.click()
            expect(study.locator(".st-attempt")).to_contain_text("70%")
            saved = page.evaluate("async id => await window.lumenStudy.api('/api/study/item?id=' + id)", item_id)
            assert saved["data"]["attempts"][0]["attachments"][0]["name"] == "Minha entrega.txt"
            act = learn_go("Planejar", "Plano de ação")
            act.get_by_role("textbox", name="Assunto", exact=True).fill("memória e sono")
            act.get_by_role("textbox", name="Seu projeto").fill("Preparar meu curso de psicologia")
            act.get_by_role("button", name="Criar plano de ação", exact=True).click()
            plan = study.locator(".st-action-plan")
            expect(plan).to_contain_text("Preparar revisão", timeout=20000)
            plan.get_by_role("checkbox", name="Preparar revisão", exact=True).check()
            expect(plan.get_by_role("checkbox", name="Preparar revisão", exact=True)).to_be_checked()
            plan.get_by_role("button", name="Focar nesta tarefa", exact=True).click()
            expect(plan).to_contain_text("sessão(ões) de foco")
            page.keyboard.press("Escape")
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"15-plano-{w}")
            page.evaluate("window.lumenStudy.openSettings('catalog')")
            expect(page.get_by_role("heading", name="Catálogo", exact=True)).to_be_visible(timeout=15000)
            page.get_by_role("button", name="Criar skill", exact=True).click()
            editor = page.get_by_role("dialog", name="Criar sua skill", exact=True)
            editor.get_by_label(re.compile("^Nome do comando")).fill("meu-teste")
            editor.get_by_label("Descrição", exact=True).fill("Revisar uma aula")
            editor.get_by_label("Argumentos", exact=True).fill("<assunto>")
            editor.get_by_label("Instruções", exact=True).fill("Resuma $ARGUMENTS usando as fontes.")
            editor.get_by_role("button", name="Salvar skill", exact=True).click()
            expect(page.get_by_role("button", name="Editar /meu-teste", exact=True)).to_be_visible(timeout=15000)
            page.get_by_role("switch", name="Ativar /meu-teste", exact=True).uncheck()
            expect(page.get_by_role("button", name="Testar /meu-teste", exact=True)).to_be_disabled(timeout=15000)
            menu = page.evaluate("async () => (await window.lumenStudy.api('/api/study/registry')).menu")
            assert not any(x["name"] == "meu-teste" for x in menu)
            page.get_by_role("switch", name="Ativar /meu-teste", exact=True).check()
            expect(page.get_by_role("button", name="Testar /meu-teste", exact=True)).to_be_enabled(timeout=15000)
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"15-catalogo-{w}")
            page.get_by_role("button", name="Testar /meu-teste", exact=True).click()
            test_skill = page.get_by_role("dialog", name="Testar /meu-teste", exact=True)
            test_skill.get_by_label("Assunto para testar", exact=True).fill("memória e sono")
            test_skill.get_by_role("button", name="Testar", exact=True).click()
            expect(study.locator(".st-msg.bot").last).to_be_visible(timeout=20000)
            page.wait_for_function("() => !window.lumenStudy.S.stream")
            page.evaluate("async () => {const m = window.lumenStudy.S.conv.messages.at(-1); await window.lumenStudy.api('/api/study/feedback', {message_id:m.id,value:1});}")
            page.evaluate("window.lumenStudy.openSettings('evaluation')")
            expect(page.get_by_role("heading", name="Avaliação local", exact=True)).to_be_visible(timeout=15000)
            with page.expect_download() as dl:
                page.get_by_role("button", name="Exportar conjunto de avaliação", exact=True).click()
            dl.value.save_as(str(ART / "15-avaliacao.json"))
            assert json.loads((ART / "15-avaliacao.json").read_text("utf-8"))["cases"]
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"15-avaliacao-{w}")
            # 16. Perfil adulto (D92): seção própria e persistida, lista de chat sem embeddings, escolha manual na conversa
            page.evaluate("window.lumenStudy.openSettings('models')")
            expect(page.get_by_role("heading", name="IA local", exact=True)).to_be_visible(timeout=15000)
            options = page.get_by_role("combobox", name="Modelo para responder", exact=True).locator("option").all_inner_texts()
            assert not any("embed" in o for o in options), options  # modelo de embeddings não é modelo de chat
            page.evaluate("window.lumenStudy.openSettings('adult')")
            expect(page.get_by_role("heading", name="Perfil adulto", exact=True)).to_be_visible(timeout=15000)
            assert page.evaluate("async () => (await window.lumenStudy.api('/api/study/state')).settings.adult.enabled") is False
            page.get_by_role("switch", name="Usar o perfil adulto", exact=True).check()
            expect(page.get_by_role("switch", name="Usar o perfil adulto", exact=True)).to_be_checked(timeout=10000)
            page.get_by_role("combobox", name="Modelo do perfil", exact=True).select_option("perfil-adulto-x:1")
            expect(page.get_by_text("Pronto: perfil-adulto-x:1")).to_be_visible(timeout=10000)
            style = page.get_by_role("textbox", name="Instruções de estilo do perfil", exact=True)
            style.fill("Tom de conversa, direto.")
            style.press("Tab")
            temperature = page.get_by_role("spinbutton", name="Temperatura do perfil", exact=True)
            temperature.fill("1.1")
            temperature.press("Tab")
            page.wait_for_timeout(600)
            saved = page.evaluate("async () => (await window.lumenStudy.api('/api/study/state')).settings")
            assert saved["adult"] == {"enabled": True, "mode": "auto", "model": "perfil-adulto-x:1", "instructions": "Tom de conversa, direto.", "temperature": 1.1}, saved["adult"]
            assert saved["models"]["temperature"] == 0.3 and saved["resolved"]["adult"] == "perfil-adulto-x:1", saved["models"]  # o principal não mudou
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"16-perfil-adulto-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.reload()
            page.locator("#nav-study").click()
            page.evaluate("window.lumenStudy.openSettings('adult')")
            expect(page.get_by_role("switch", name="Usar o perfil adulto", exact=True)).to_be_checked(timeout=15000)  # persistiu após reabrir
            expect(page.get_by_role("textbox", name="Instruções de estilo do perfil", exact=True)).to_have_value("Tom de conversa, direto.")
            page.get_by_role("button", name="Voltar ao Cérebro", exact=True).click()
            page.evaluate("window.lumenStudy.setTab('chat'); window.lumenStudy.newConversation()")
            box = page.get_by_role("textbox", name="Pergunta para o Lumen", exact=True)
            chip = study.locator(".st-mode")
            chip.click()
            expect(page.locator(".st-chip-menu")).to_contain_text("Modelo da resposta")
            page.get_by_role("menuitemradio", name="Perfil adulto", exact=True).click()
            expect(chip).to_contain_text("Perfil adulto")
            box.fill("Como o sono ajuda a memória?")
            box.press("Enter")
            page.wait_for_function("() => !window.lumenStudy.S.stream && window.lumenStudy.S.conv.messages.at(-1)?.role === 'assistant'", timeout=30000)
            meta = page.evaluate("window.lumenStudy.S.conv.messages.at(-1).meta")
            assert meta["profile"] == {"used": "adult", "by": "manual", "model": "perfil-adulto-x:1"} and meta["model"] == "perfil-adulto-x:1", meta
            box.fill("/perfil principal")
            box.press("Enter")
            expect(chip).to_contain_text("Principal")
            box.fill("E o hipocampo?")
            box.press("Enter")
            page.wait_for_function("() => !window.lumenStudy.S.stream && window.lumenStudy.S.conv.messages.at(-1)?.role === 'assistant' && window.lumenStudy.S.conv.messages.length >= 4", timeout=30000)
            meta = page.evaluate("window.lumenStudy.S.conv.messages.at(-1).meta")
            assert meta["profile"]["used"] == "main" and meta["profile"]["by"] == "manual" and meta["model"] != "perfil-adulto-x:1", meta
            page.evaluate("window.lumenStudy.openConversation(window.lumenStudy.S.conv.id)")  # a escolha manual acompanha a conversa ao reabrir
            expect(chip).to_contain_text("Principal", timeout=10000)
            for w in (1440, 1100, 760, 520):
                page.set_viewport_size({"width": w, "height": 900}); fits(); shot(f"16-perfil-chip-{w}")
            page.set_viewport_size({"width": 1440, "height": 900})
            ok("Fase 16 (D92): seção Perfil adulto com liga/desliga, modo, modelo, estilo e temperatura próprios gravados e relidos após reabrir; lista de chat sem modelo de embeddings; chip da conversa e /perfil escolhem o modelo; o principal não mudou; quatro larguras")
            # 17. Holograma 3D no chat (/elegrama 3d): comando e autocomplete, estados reais, cartão com a animação de verdade, PNG de
            # reserva, downloads, movimento reduzido, Ampliar, alternativa estática, salvar no Obsidian e reabertura
            page.evaluate("window.lumenStudy.newConversation()")
            box = page.get_by_role("textbox", name="Pergunta para o Lumen", exact=True)
            box.fill("/eleg")
            expect(page.locator(".st-slash-item").filter(has_text="/elegrama")).to_be_visible(timeout=10000)
            expect(page.locator(".st-slash-item").filter(has_text="3d <assunto>")).to_be_visible()
            box.fill("/holo")
            expect(page.locator(".st-slash-item").filter(has_text="/holograma")).to_be_visible(timeout=10000)
            box.press("Tab")  # escolher pelo menu escreve o comando e a palavra fixa; nada é enviado
            assert box.input_value() == "/holograma 3d ", box.input_value()
            box.fill("/elegrama 3d")  # sem assunto: só o exemplo, nenhum pedido sai
            sent = page.evaluate("window.lumenStudy.S.conv?.messages?.length || 0")
            box.press("Enter")
            expect(page.locator("#toast")).to_contain_text("/elegrama 3d do sistema solar", timeout=8000)
            assert box.input_value() == "/elegrama 3d" and page.evaluate("window.lumenStudy.S.conv?.messages?.length || 0") == sent
            assert study.locator(".st-holo").count() == 0 and not page.evaluate("window.lumenStudy.S.stream")
            box.fill("/ELEGRAMA 3D  de um computador e seus componentes")
            box.press("Enter")
            seen = set()
            for _ in range(120):  # os estados reais da fila enquanto ela trabalha (sem porcentagem)
                text = page.evaluate("document.querySelector('.st-stage-text')?.textContent || ''")
                if text:
                    seen.add(text)
                if study.locator(".st-holo").count():
                    break
                page.wait_for_timeout(200)
            assert seen and not any("%" in t for t in seen) and any(w in " ".join(seen) for w in ("Preparando", "Montando", "Renderizando", "Conferindo")), seen
            card = study.locator(".st-holo")
            expect(card).to_have_count(1, timeout=90000)
            img = card.locator("img")
            expect(img).to_be_visible()
            page.wait_for_function("() => { const i = document.querySelector('.st-holo img'); return i && i.complete && i.naturalWidth === 960 && i.naturalHeight === 540; }", timeout=20000)
            assert "Computador" in img.get_attribute("alt") and "esquemática" in img.get_attribute("alt")
            expect(study.locator(".st-msg.bot").last).to_contain_text("Representação esquemática gerada pelo Lumen")
            expect(card).to_contain_text("Animação (GIF) · 960×540 · 4 s · 48 quadros")
            expect(card).to_contain_text("representação esquemática gerada pelo Lumen")
            box_ = img.bounding_box()
            assert abs(box_["width"] / box_["height"] - 16 / 9) < 0.02, box_
            from io import BytesIO
            from PIL import Image as PILImage, ImageSequence
            src = img.get_attribute("src")
            assert "variant=poster" not in src
            raw = page.request.get(url + src)
            assert raw.headers["content-type"] == "image/gif", raw.headers
            frames17 = [f.convert("RGB").tobytes() for f in ImageSequence.Iterator(PILImage.open(BytesIO(raw.body())))]
            assert len(frames17) == 48 and len(set(frames17)) >= 47, (len(frames17), len(set(frames17)))  # animação de verdade
            poster_raw = page.request.get(url + src + "&variant=poster")
            assert poster_raw.headers["content-type"] == "image/png" and poster_raw.body()[:8] == b"\x89PNG\r\n\x1a\n"
            with page.expect_download() as dl:
                card.get_by_role("link", name="Baixar animação (GIF)").click()
            dl.value.save_as(str(ART / "17-holograma.gif"))
            gif_file = (ART / "17-holograma.gif").read_bytes()
            assert gif_file[:6] == b"GIF89a" and dl.value.suggested_filename.endswith(".gif") and PILImage.open(BytesIO(gif_file)).n_frames == 48
            with page.expect_download() as dl:
                card.get_by_role("link", name="Baixar PNG").click()
            dl.value.save_as(str(ART / "17-holograma.png"))
            assert (ART / "17-holograma.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and dl.value.suggested_filename.endswith(".png")
            card.get_by_role("button", name="Pausar animação").click()  # parar a animação mostra o PNG de reserva
            assert "variant=poster" in img.get_attribute("src")
            expect(card.get_by_role("button", name="Reproduzir animação")).to_have_attribute("aria-pressed", "false")
            card.get_by_role("button", name="Reproduzir animação").click()
            assert "variant=poster" not in img.get_attribute("src")
            for w in (1440, 1100, 760, 520):  # a imagem cabe na largura da conversa, sem rolagem horizontal da página
                page.set_viewport_size({"width": w, "height": 900})
                fits()
                shot_ = img.bounding_box()
                assert shot_["x"] >= 0 and shot_["x"] + shot_["width"] <= w + 1 and abs(shot_["width"] / shot_["height"] - 16 / 9) < 0.02, (w, shot_)
                shot(f"17-holograma-{w}")
            frame = card.locator(".st-holo-frame")
            card.get_by_role("button", name="Ampliar").click()  # tamanho original, com rolagem só dentro do cartão
            assert frame.evaluate("e => e.scrollWidth > e.clientWidth") and frame.evaluate("e => e.getBoundingClientRect().right <= document.documentElement.clientWidth")
            fits()
            shot("17-holograma-ampliado-520")
            card.get_by_role("button", name="Ajustar à largura").click()
            assert frame.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            page.set_viewport_size({"width": 1440, "height": 900})
            cid17 = page.evaluate("window.lumenStudy.S.conv.id")  # reabrir a conversa traz o mesmo artefato; com movimento reduzido, o PNG parado
            page.emulate_media(reduced_motion="reduce")
            page.evaluate("cid => window.lumenStudy.openConversation(cid)", cid17)
            card = study.locator(".st-holo")
            expect(card).to_have_count(1, timeout=10000)
            expect(card.get_by_role("button", name="Reproduzir animação")).to_be_visible()
            assert "variant=poster" in card.locator("img").get_attribute("src")
            card.get_by_role("button", name="Reproduzir animação").click()  # inicia por ação do usuário
            assert "variant=poster" not in card.locator("img").get_attribute("src")
            shot("17-holograma-movimento-reduzido")
            page.emulate_media(reduced_motion="no-preference")
            page.evaluate("""() => { const L = window.lumenStudy, last = L.S.conv.messages.at(-1);
                const a = { ...last.meta.artifact, animated: false, poster: false, format: 'png', state: 'static-fallback', reason: 'peso', name: 'Holograma 3D · alternativa.png' };
                const view = L.messageView({ role: 'assistant', id: 'x-static', content: 'A animação não coube; entreguei a imagem estática (PNG).', meta: { artifact: a }, sources: [] });
                view.id = 'synthetic-static'; document.querySelector('.st-msg.bot').parentElement.append(view); }""")
            fallback = page.locator("#synthetic-static")
            expect(fallback).to_contain_text("Imagem estática (PNG) · 960×540")
            expect(fallback).to_contain_text("A animação não coube no limite; esta é a alternativa estática.")
            expect(fallback.get_by_role("button", name="Pausar animação")).to_have_count(0)
            expect(fallback.get_by_role("button", name="Reproduzir animação")).to_have_count(0)
            expect(fallback.get_by_role("link", name="Baixar animação (GIF)")).to_have_count(0)
            expect(fallback.get_by_role("link", name="Baixar PNG")).to_be_visible()
            page.evaluate("document.getElementById('synthetic-static').scrollIntoView({ block: 'center' })")
            shot("17-holograma-alternativa-estatica")
            page.evaluate("document.getElementById('synthetic-static').remove()")
            real = study.locator(".st-holo").first  # salvar no Obsidian reaproveita a prévia: nada é gravado antes de confirmar
            real.get_by_role("button", name="Salvar no Obsidian…").click()
            page.locator("dialog[open]").get_by_role("button", name="Ver prévia").click()
            dlg = page.locator("dialog[open]")
            expect(dlg).to_contain_text("nada foi gravado")
            expect(dlg).to_contain_text(".gif")
            outputs17 = vault / "C04 Claude Obsidian/01 Outputs"
            before17 = sorted(p.name for p in vault.rglob("*") if p.is_file())
            assert not any(n.endswith(".gif") for n in before17), before17
            dlg.get_by_role("button", name="Confirmar e salvar").click()
            expect(page.locator("#toast")).to_contain_text("Nota criada", timeout=8000)
            gifs = [p for p in vault.rglob("lumen-*.gif")]
            assert len(gifs) == 1 and gifs[0].read_bytes()[:6] == b"GIF89a" and PILImage.open(BytesIO(gifs[0].read_bytes())).n_frames == 48, gifs
            ok("Fase 17: /elegrama 3d e /holograma 3d (menu, Tab, uso incompleto sem envio, caixa e espaços), estados reais, cartão com GIF de 48 quadros distintos em 960×540, PNG de reserva, downloads conferidos, pausar/reproduzir, movimento reduzido, Ampliar com rolagem só no cartão, alternativa estática sem botão de animação, salvar no Obsidian com o GIF e reabertura, nas quatro larguras")
            page.emulate_media(reduced_motion="reduce")
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.tagName") in ("BUTTON", "SUMMARY", "A")
            assert page.evaluate("document.activeElement.matches(':focus-visible') && getComputedStyle(document.activeElement).outlineStyle !== 'none' && parseFloat(getComputedStyle(document.activeElement).outlineWidth) > 0"), "Foco do teclado precisa ficar visível"
            assert page.locator(".btn.primary").evaluate_all("els => els.every(el => getComputedStyle(el).animationName === 'none')"), "Movimento reduzido deve desligar a animação dos botões"
            ok("Fase 9: prática por texto/anexo, correção por critério e reabertura; plano aplicado com prazo/progresso/Pomodoro; catálogo e skill criada, desligada e testada; avaliações exportadas nas quatro larguras, com teclado e movimento reduzido")
            browser.close()
            assert not errors, errors
            ok("nenhum erro de página, bloqueio de CSP ou resposta HTTP 5xx")
        report["passed"] = True
        sys.stdout.reconfigure(encoding="utf-8", errors="replace"); print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        backend_log.close()
