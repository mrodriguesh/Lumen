"""Fase 7: serviços falsos, Edge real, arquivos e destinos isolados."""
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase, mock

import tests  # noqa: F401
from PIL import Image
from pypdf import PdfReader, PdfWriter

from lumen import AppError, Cancelled, cdp, imagegen, jobs, llm, store
from lumen.study import agent, artifacts, attachments, chats, db, images, index, pdf, providers, search, settings, tools, writes
from tests.fake_notion import Fake
from tests.fake_ollama import FakeOllama
from tests.test_study_index import Base

DOC = {"title": "Memória e sono", "summary": "Revisão de consolidação da memória.", "blocks": [
    {"heading": f"Conceito {i}", "text": "O sono profundo consolida a memória. Pratique a recuperação antes de reler as notas.",
     "question": f"Pergunta {i}: o que consolida a memória?", "answer": f"Resposta {i}: o sono profundo.",
     "source": "S1" if i % 2 else "geral"} for i in range(1, 7)]}
DECOR = {"emoji": "🧠", "motifs": ["🌙", "📚", "💤"], "palette": "ocean", "cover": "gradients_3",
         "color": "blue_background", "subtitle": "Memória e sono", "image_prompt": "A moon and a brain"}
MIND = {"center": "Memória", "sources": ["S1"], "branches": [
    {"label": "Sono", "detail": "Consolida a memória.", "children": [{"label": "Profundo", "detail": "Consolidação."}]},
    {"label": "Prática", "detail": "Recuperar antes de reler.", "children": [{"label": "Revisão", "detail": "Com intervalos."}]}]}


def png(*args, width=1024, height=1024, **kwargs):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "#5070a0").save(out, "PNG")
    return out.getvalue()


class Images(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(jobs._cancel.clear)
        jobs._cancel.clear()

    def test_config_roundtrip_and_input_limits(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(store, "DATA", Path(temp)):
            # O Base troca load_config; testa o arquivo gravado e os defaults que controlam o carregamento.
            cfg = {**store.DEFAULTS, "image_dir": str(Path(temp) / "images")}
            store.save_config(cfg)
            self.assertEqual(store._read("config.json", {}), cfg)
        for text in ("/imagem", "/imagem " + "x" * 1501, "/pdf revisao"):
            with self.assertRaises(AppError):
                artifacts.request(text)
        self.assertEqual(artifacts.request("/imagem retrato planeta")["shape"], "retrato")
        for width, height in ((0, 512), (True, 512), (4096, 4096), (1023, 768)):
            with self.assertRaises(AppError):
                imagegen.generate("lua", width=width, height=height)

    def test_image_persists_reopens_is_not_source_and_is_deleted(self):
        with mock.patch.object(imagegen, "ready", return_value=True), mock.patch.object(imagegen, "generate", side_effect=png), \
                mock.patch.object(llm, "release_vram", return_value=True) as release:
            ev = list(agent.turn({"text": "/imagem paisagem lua"}, "image-test"))
        self.assertNotIn("error", [e["type"] for e in ev], ev)
        message = ev[-1]["message"]
        aid = message["meta"]["artifact"]["id"]
        cid = next(e["conversation"]["id"] for e in ev if e["type"] == "conversation")
        self.assertEqual(message["sources"], [])
        self.assertIn(artifacts.LABEL, message["content"])
        release.assert_called_once()
        db.close()
        self.assertEqual(chats.get(cid)["messages"][-1]["meta"]["artifact"]["id"], aid)
        rec = artifacts.get(aid)
        for fn in (lambda: attachments.add_to_index(aid), lambda: attachments.item(rec, "lua"), lambda: attachments.text("anexo:" + aid)):
            with self.assertRaises(AppError):
                fn()
        path, mime = artifacts.file(aid)
        self.assertEqual(mime, "image/png")
        self.assertIsNone(images.register(path.read_bytes(), "renomeada.png", "obsidian"))
        with self.assertRaises(AppError):
            attachments._image(path, rec, lambda: None)
        chats.delete([cid])
        self.assertFalse(path.exists())

    def test_temporary_does_not_persist_and_cleanup_removes_file(self):
        cid = chats.create(temporary=True)["id"]
        msg = artifacts.save(cid, "image", "Lua", artifacts.LABEL, [], {}, png())
        aid = msg["meta"]["artifact"]["id"]
        self.assertIsNone(db.one("SELECT id FROM attachments WHERE id=?", aid))
        path, _ = artifacts.file(aid)
        chats.delete([cid])
        self.assertFalse(path.exists())

    def test_failure_and_cancel_leave_no_result_or_file(self):
        for error in (None, Cancelled()):
            before = db.value("SELECT COUNT(*) FROM attachments")
            with mock.patch.object(imagegen, "ready", return_value=True), \
                    mock.patch.object(imagegen, "generate", return_value=None, side_effect=error), \
                    mock.patch.object(llm, "release_vram", return_value=True):
                ev = list(agent.turn({"text": "/imagem lua"}, "image-error"))
            self.assertIn(ev[-1]["type"], ("error", "cancelled"))
            self.assertEqual(before, db.value("SELECT COUNT(*) FROM attachments"))

    def test_cancels_only_owned_diffusion_process(self):
        original = subprocess.Popen
        spawned = []
        def launch(*args, **kwargs):
            p = original([sys.executable, "-c", "import time; time.sleep(30)"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            spawned.append(p)
            return p
        start = time.monotonic()
        def check():
            if time.monotonic() - start > .4:
                raise Cancelled()
        with mock.patch.object(imagegen, "folder", return_value=self.tmp), mock.patch.object(imagegen.subprocess, "Popen", launch):
            with self.assertRaises(Cancelled):
                imagegen._generate("lua", "z-image", 1024, 1024, 1, 10, check)
        self.assertIsNotNone(spawned[0].poll())
        self.assertLess(time.monotonic() - start, 3)
        self.assertFalse(list(self.tmp.glob("lumen-img-*")))

    def test_busy_queue_is_not_cancelled_by_new_request(self):
        gate = threading.Event()
        jobs.start("test-owned", lambda: gate.wait(3), spec={"key": "other"})
        try:
            ev = list(agent.turn({"text": "/imagem lua"}, "image-busy"))
            self.assertEqual(ev[-1]["type"], "error")
            self.assertFalse(jobs._cancel.is_set())
        finally:
            gate.set()
            while jobs.busy():
                time.sleep(.01)


class Documents(Base):
    def setUp(self):
        super().setUp()
        jobs._cancel.clear()
        self.fake = FakeOllama()
        self.fake.json_replies.update({"PDF:": DOC, "Você decora páginas": DECOR, "Monte um mapa mental": MIND})
        self.note("Memória.md", "# Memória\nO sono profundo consolida a memória.")
        index.sync("obsidian")
        settings.save({"pdf": {"cover_image": False}})

    def tearDown(self):
        self.fake.close()
        super().tearDown()

    def test_schema_limits_and_html_escaping(self):
        self.assertEqual(pdf.schema(["S1"])["properties"]["blocks"]["maxItems"], 8)
        bad = {"title": "<script>bad</script>", "blocks": [{**DOC["blocks"][0], "source": "S999", "text": "<img src=https://example.com>"}] * 50}
        doc = pdf.clean(bad, "revisao", ["S1"])
        self.assertEqual(doc["blocks"][0]["source"], "geral")
        source = {"sid": "S999", "title": "x", "url": "javascript:alert(1)"}
        self.assertEqual(pdf.source_url(source), "")
        html = pdf.html(doc, "revisao", {}, [source])
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=https", html)
        self.assertIn("Conhecimento geral", html)
        long = pdf.clean({**DOC, "summary": "palavra " * 100}, "revisao", ["S1"])["summary"]
        self.assertLessEqual(len(long), 250)
        self.assertTrue(long.endswith("…"))
        with self.assertRaises(AppError):
            pdf.clean({"blocks": []}, "cornell", [])

    def test_notion_url_survives_search_and_pdf_source_conversion(self):
        from lumen.study.sources import Doc
        url = "https://www.notion.so/" + "a" * 32
        index.upsert(Doc(source="notion", source_id="a" * 32, title="Astronomia", text="Astronomia estuda planetas.", url=url))
        settings.save({"search": {"hybrid": False}})
        result = search.search("Astronomia")["results"][0]
        ctx = tools.Ctx(); ctx.cite(result)
        self.assertEqual(pdf.source_url(tools.public_sources(ctx)[0]), url)

    def test_pdf_reads_content_when_search_only_found_note_structure(self):
        row = db.one("SELECT id FROM documents WHERE title = 'Memória'")
        ctx = tools.Ctx()
        ctx.cite({"id": row["id"], "title": "Memória", "source": "obsidian", "chunks": [{"id": 0, "text": "Minhas anotações"}]})
        text = pdf.material(ctx, 16000)
        self.assertIn("O sono profundo consolida a memória.", text)
        self.assertIn('id="S1"', text)
        self.assertEqual(ctx.trace[-1]["tool"], "read_document")

    def test_review_fits_once_without_regenerating_or_hiding_content(self):
        from tests.test_study_attachments import pdf_text
        one = pdf_text("Conteudo completo")
        writer, out = PdfWriter(), io.BytesIO()
        writer.append(io.BytesIO(one)); writer.append(io.BytesIO(one)); writer.write(out)
        with mock.patch.object(cdp, "pdf", side_effect=[out.getvalue(), one]) as render:
            blob, pages = pdf.render(pdf.clean(DOC, "revisao", ["S1"]), "revisao", {}, [])
        self.assertEqual(pages, 1)
        self.assertEqual(render.call_count, 2)
        self.assertEqual(render.call_args.kwargs["scale"], .9)
        self.assertIn("Conteudo completo", PdfReader(io.BytesIO(blob)).pages[0].extract_text())

    def test_source_image_and_precise_chart_reuse_existing_renderers(self):
        from tests.test_charts import bars
        self.note("Valores.md", "Alpha vendeu 10 unidades. Beta vendeu 20 unidades.")
        index.sync("obsidian")
        row = db.one("SELECT id FROM documents WHERE title='Valores'")
        h = images.register(png(width=400, height=250), "foto.png", "obsidian")
        ctx = tools.Ctx()
        ctx.cite({"id": row["id"], "title": "Valores", "source": "obsidian", "path": "Valores.md", "images": ["h="+h]})
        assets = pdf.source_images(ctx)
        self.assertEqual(len(assets), 1)
        self.fake.json_replies["Você cria gráficos"] = bars([("Alpha", 10), ("Beta", 20)])
        assets += pdf.chart(ctx, providers.Ollama(settings.load()))
        self.assertEqual(len(assets), 2)
        blob, pages = pdf.render(pdf.clean(DOC, "apostila", ["S1"]), "apostila", {}, tools.public_sources(ctx), assets=assets)
        reader = PdfReader(io.BytesIO(blob))
        self.assertTrue(all(p.extract_text().strip() for p in reader.pages))
        out = os.environ.get("LUMEN_PDF_ARTIFACTS")
        if out:
            (Path(out) / 'grafico-e-imagem.pdf').write_bytes(blob)
        self.fake.json_replies["Você cria gráficos"] = bars([("Alpha", 999), ("Beta", 20)])
        with mock.patch.object(cdp, "png") as draw:
            self.assertEqual(pdf.chart(ctx, providers.Ollama(settings.load())), [])
        draw.assert_not_called()
        events = list(agent.turn({"text": "/pdf apostila gráfico Alpha Beta"}, "chart-invalid"))
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("dados conferidos", events[-1]["message"])

    def test_prints_existing_explanation_and_dark_document(self):
        cid = chats.create()["id"]
        text = "## Ideia central\nO sono consolida a **memória**. [S1]\n\nTrecho exato para imprimir."
        source = {"sid": "S1", "id": "nota", "title": "Memória", "source": "web", "url": "https://example.com/fonte"}
        msg = chats.add_message(cid, "assistant", text, [source], {"mode": "explain"})
        settings.save({"pdf": {"dark": True}})
        ev = list(agent.turn({"conversation_id": cid, "text": "/pdf explicacao sono", "pdf_message": msg["id"]}, "pdf-print"))
        self.assertEqual(ev[-1]["type"], "done", ev)
        path, _ = artifacts.file(ev[-1]["message"]["meta"]["artifact"]["id"])
        content = "\n".join(p.extract_text() for p in PdfReader(path).pages)
        self.assertIn("Trecho exato para imprimir.", content)
        self.assertNotIn("**", content)
        self.assertFalse(any("PDF:" in req[1].get("messages", [{}])[-1].get("content", "") for req in self.fake.requests))
        self.assertIn('background:#14141c', pdf.html(pdf.clean(DOC, "revisao", ["S1"]), "revisao", {}, [source], dark=True))

    def test_all_formats_real_pdf_text_links_and_pages(self):
        if not cdp.edge():
            self.skipTest("sem Edge")
        out = os.environ.get("LUMEN_PDF_ARTIFACTS")
        for form in pdf.TYPES:
            with self.subTest(form=form):
                ev = list(agent.turn({"text": f"/pdf {form} memória"}, "pdf-" + form))
                self.assertEqual(ev[-1]["type"], "done", ev)
                msg = ev[-1]["message"]
                path, _ = artifacts.file(msg["meta"]["artifact"]["id"])
                reader = PdfReader(path)
                texts = [p.extract_text() for p in reader.pages]
                self.assertTrue(all(t.strip() for t in texts))
                self.assertIn("Fontes", "\n".join(texts))
                self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.28, delta=1)
                links = [a.get_object().get("/A", {}).get("/URI", "") for p in reader.pages for a in p.get("/Annots", [])]
                self.assertTrue(any(u.startswith("obsidian:") for u in links), links)
                self.assertTrue(all(p.get("/Resources", {}).get("/Font") for p in reader.pages))
                if form == "revisao":
                    self.assertEqual(len(texts), 1)
                if form in ("exercicios", "simulado"):
                    keypage = next(i for i, t in enumerate(texts) if "Gabarito" in t)
                    self.assertGreater(keypage, 0)
                    self.assertNotIn("Resposta 1:", "\n".join(texts[:keypage]))
                if form == "flashcards":
                    front = next(t for t in texts if "Frentes" in t)
                    back = next(t for t in texts if "Versos" in t)
                    self.assertLess(front.index("Cartão 1"), front.index("Cartão 2"))
                    self.assertLess(back.index("Cartão 2"), back.index("Cartão 1"))
                if out:
                    dest = Path(out); dest.mkdir(parents=True, exist_ok=True)
                    (dest / f"{form}.pdf").write_bytes(path.read_bytes())

    def test_external_preview_then_real_isolated_file_and_fake_notion(self):
        cid = chats.create()["id"]
        msg = artifacts.save(cid, "image", "Lua", artifacts.LABEL, [], {}, png())
        aid = msg["meta"]["artifact"]["id"]
        preview = artifacts.prepare(aid, "obsidian", "Lua")
        self.assertFalse(list(self.vault.glob("**/*.png")))
        writes.confirm(preview["id"])
        copies = list(self.vault.glob("**/*.png"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), artifacts.file(aid)[0].read_bytes())
        fake = Fake()
        parent = fake.add_page("Estudos")
        try:
            settings.save({"connectors": {"notion_parent": parent}})
            with mock.patch.object(store, "get_token", return_value="secret_test"):
                preview = artifacts.prepare(aid, "notion", "Lua")
                self.assertFalse(fake.uploads)
                try:
                    result = writes.confirm(preview["id"])
                except AppError as e:
                    self.fail(f"{e}: {fake.violations}")
                self.assertIn("page", result)
                self.assertTrue(fake.uploads)
                preview = artifacts.prepare(aid, "notion", "Lua sem confirmação")
                with mock.patch.object(writes.notion, "media_is", return_value=None):
                    with self.assertRaises(AppError):
                        writes.confirm(preview["id"])
                row = db.one("SELECT status FROM pending_actions WHERE id=?", preview["id"])
                self.assertEqual(row["status"], "unconfirmed")
        finally:
            fake.close()

    def test_pdf_upload_is_read_back_and_uses_pdf_block(self):
        from tests.test_study_attachments import pdf_text
        blob = pdf_text("Documento de teste")
        cid = chats.create()["id"]
        msg = artifacts.save(cid, "pdf", "Revisão", "PDF", [], {}, blob)
        fake = Fake()
        parent = fake.add_page("Estudos")
        try:
            settings.save({"connectors": {"notion_parent": parent}})
            with mock.patch.object(store, "get_token", return_value="secret_test"):
                action = artifacts.prepare(msg["meta"]["artifact"]["id"], "notion", "PDF")
                self.assertFalse(fake.uploads)
                result = writes.confirm(action["id"])
                media = [b for b in writes.notion.children("secret_test", result["page"]) if b["type"] == "pdf"]
                self.assertEqual(len(media), 1)
                self.assertTrue(writes.notion.media_is("secret_test", media[0]["id"], blob))
        finally:
            fake.close()
