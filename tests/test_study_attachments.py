"""Study AI 2.0, fase 4: anexos do chat (tipo real pelos bytes, tetos, leitura por tipo, fonte S#, apagar com a
conversa, índice), /tela e imagens das notas (cofre e Notion). Ollama e Notion falsos; dados isolados."""
import io
import json
import os
import struct
import time
import types
import zipfile
import zlib
from unittest import mock

from PIL import Image, ImageDraw

import tests  # noqa: F401
from lumen import AppError, transcribe, vision
from lumen.study import attachments, chats, db, images, index, search, settings
from lumen.study import api as study_api
from lumen.study.sources import web
from tests import test_study_core as core, test_study_index as idx

run_turn = core.run_turn

SEEN = {"titulo": "Funil de vendas", "texto": "Topo: atrair\nMeio: nutrir\nFundo: converter",
        "descricao": "Um funil dividido em três faixas", "tipo": "slide", "conteudo_da_aula": True, "valores": []}


def png(color="white"):
    img = Image.new("RGB", (640, 360), color)
    ImageDraw.Draw(img).rectangle((100, 80, 540, 280), outline="black", width=6)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def pdf_text(text):
    """PDF mínimo de verdade, com uma página de texto (sem reportlab)."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def pdf_scanned():
    out = io.BytesIO()
    Image.open(io.BytesIO(png())).save(out, "PDF")
    return out.getvalue()


def png_header(w, h):
    """Só o cabeçalho de um PNG enorme: o arquivo é minúsculo, a imagem decodificada teria GBs."""
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b"")


def office(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
DOCX = office({"[Content_Types].xml": "<Types/>", "word/document.xml":
               f'<w:document {W}><w:body><w:p><w:pPr><w:pStyle w:val="Ttulo1"/></w:pPr><w:r><w:t>Persuasão</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>Prova social </w:t></w:r><w:r><w:t>convence.</w:t></w:r></w:p></w:body></w:document>'})
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
PPTX = office({"[Content_Types].xml": "<Types/>",
               "ppt/slides/slide2.xml": f"<p:sld {A} xmlns:p='p'><a:p><a:r><a:t>Corte em J</a:t></a:r></a:p></p:sld>",
               "ppt/slides/slide10.xml": f"<p:sld {A} xmlns:p='p'><a:p><a:r><a:t>Exportar</a:t></a:r></a:p></p:sld>",
               "ppt/slides/slide1.xml": f"<p:sld {A} xmlns:p='p'><a:p><a:r><a:t>Premiere: timeline</a:t></a:r></a:p></p:sld>"})
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
XLSX = office({"[Content_Types].xml": "<Types/>",
               "xl/workbook.xml": f'<workbook {S}><sheets><sheet name="Campanhas" sheetId="1"/></sheets></workbook>',
               "xl/sharedStrings.xml": f"<sst {S}><si><t>Canal</t></si><si><t>Instagram</t></si></sst>",
               "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row><c t="s"><v>0</v></c><c t="inlineStr"><is><t>CPC</t></is></c></row>'
                                           '<row><c t="s"><v>1</v></c><c><v>0.42</v></c></row></sheetData></worksheet>'})
ODT = office({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml":
              '<office:document-content xmlns:office="o" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
              "<text:h>Inglês</text:h><text:p>Present perfect: have + particípio.</text:p></office:document-content>"})
EPUB = office({"mimetype": "application/epub+zip",
               "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                                         '<rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
               "OEBPS/book.opf": '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="c1" href="cap%201.xhtml"/>'
                                 '<item id="c2" href="cap2.xhtml"/></manifest><spine><itemref idref="c2"/><itemref idref="c1"/></spine></package>',
               "OEBPS/cap 1.xhtml": "<html><body><p>Capítulo um: negociação.</p></body></html>",
               "OEBPS/cap2.xhtml": "<html><body><p>Prefácio do livro.</p></body></html>"})


def wait(aid, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        rec = attachments.get(aid)
        if rec["status"] != "reading":
            return rec
        time.sleep(0.05)
    raise AssertionError("o anexo não terminou de ser lido")


class Attach(core.Core):
    def setUp(self):
        super().setUp()
        self.ollama.models.append(vision.MODEL)
        self.ollama.json_replies["Você lê uma captura de tela"] = SEEN
        p = mock.patch.object(db, "MEDIA", self.tmp / "media")
        p.start()
        self.stack.append(p)

    def tearDown(self):
        chats.delete_all()  # apaga os anexos ainda na memória (conversas temporárias)
        with attachments._lock:
            attachments._live.clear()
        super().tearDown()

    def send(self, data, name):
        return attachments.receive(io.BytesIO(data).read, len(data), name)

    def read(self, data, name):
        return wait(self.send(data, name)["id"])


class Types(Attach):
    def test_type_comes_from_bytes_not_from_the_name(self):
        self.assertEqual(attachments.sniff(png()), "image")
        self.assertEqual(attachments.sniff(b"%PDF-1.7\n"), "pdf")
        self.assertEqual(attachments.sniff(b"RIFF\x24\x00\x00\x00WAVEfmt "), "audio")
        self.assertEqual(attachments.sniff(b"\x00\x00\x00\x18ftypisom"), "video")
        self.assertEqual(attachments.sniff(b"\x00\x00\x00\x18ftypM4A "), "audio")
        self.assertEqual(attachments.sniff("Olá, ação\n".encode("utf-8")), "text")
        self.assertEqual(attachments.sniff("Olá".encode("cp1252")), "text")
        self.assertIsNone(attachments.sniff(b"MZ\x90\x00\x03\x00\x00\x00"))  # executável
        rec = self.read(png(), "slides.pdf")                                   # extensão trocada: é imagem
        self.assertEqual((rec["kind"], rec["status"]), ("image", "ready"))
        self.assertIn("Topo: atrair", rec["text"])
        self.assertTrue((attachments.folder(rec["id"]) / "miniatura.jpg").is_file())
        with self.assertRaises(AppError) as e:
            self.send(b"MZ\x90\x00" + b"\x00" * 100, "nota.txt")
        self.assertIn("não sabe ler", str(e.exception))
        self.assertEqual(sorted(p.name for p in (db.MEDIA / "anexos").iterdir()), [rec["id"]])  # nada foi guardado

    def test_size_limit_per_type_refuses_before_saving(self):
        big = b"%PDF-1.4\n"
        with mock.patch.dict(attachments.LIMIT, {"pdf": 1000}):
            with self.assertRaises(AppError) as e:
                attachments.receive(io.BytesIO(big).read, 5000, "grande.pdf")
        self.assertIn("grande demais", str(e.exception))
        self.assertFalse((db.MEDIA / "anexos").exists() and any((db.MEDIA / "anexos").iterdir()))

    def test_route_drains_the_body_when_it_refuses(self):
        data = b"MZ" + b"\x00" * 300_000
        h = types.SimpleNamespace(headers={"Content-Length": str(len(data))}, rfile=io.BytesIO(data), _query=lambda: {"name": "a.exe"})
        with self.assertRaises(AppError):
            study_api._attach(h)
        self.assertEqual(h.rfile.read(), b"")  # leu tudo antes de responder (senão o Windows derruba a conexão)

    def test_office_documents_with_the_standard_library(self):
        self.assertIn("# Persuasão\n\nProva social convence.", self.read(DOCX, "aula.docx")["text"])
        slides = self.read(PPTX, "premiere.pptx")["text"]
        self.assertLess(slides.index("timeline"), slides.index("Corte em J"))
        self.assertLess(slides.index("Corte em J"), slides.index("Exportar"))  # slide10 depois do slide2
        self.assertIn("## Campanhas\nCanal | CPC\nInstagram | 0.42", self.read(XLSX, "custos.xlsx")["text"])
        self.assertIn("# Inglês\n\nPresent perfect", self.read(ODT, "ingles.odt")["text"])
        book = self.read(EPUB, "livro.epub")["text"]
        self.assertLess(book.index("Prefácio"), book.index("negociação"))  # ordem da lombada (spine)
        bomb = office({"word/document.xml": "<!DOCTYPE x [<!ENTITY a 'aaaa'>]><x>&a;</x>"})
        rec = self.read(bomb, "suspeito.docx")
        self.assertEqual(rec["status"], "error")
        self.assertIn("suspeita", rec["message"])
        self.assertEqual(self.read(office({"x.txt": "oi"}), "pasta.zip")["status"], "error")

    def test_pdf_text_and_scanned_pages_through_vision(self):
        rec = self.read(pdf_text("Funil de vendas e trafego pago"), "slides.pdf")
        self.assertIn("## Página 1\nFunil de vendas e trafego pago", rec["text"])
        rec = self.read(pdf_scanned(), "escaneado.pdf")
        self.assertEqual(rec["status"], "ready", rec["message"])
        self.assertIn("Meio: nutrir", rec["text"])
        self.assertEqual(rec["meta"]["scanned"], 1)

    def test_audio_is_transcribed_with_timestamps(self):
        tr = {"segments": [{"start": 2, "end": 5, "text": "Hoje: keyframes."}, {"start": 75, "end": 80, "text": "Agora a curva."}],
              "duration": 81.0}
        with mock.patch.object(transcribe, "downloaded", return_value=True), \
                mock.patch.object(transcribe, "transcribe", return_value=tr) as run:
            rec = self.read(b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64, "aula.wav")
        self.assertEqual(rec["text"], "[00:02] Hoje: keyframes.\n[01:15] Agora a curva.")
        self.assertFalse(run.call_args.kwargs["second"])
        with mock.patch.object(transcribe, "downloaded", return_value=False):
            rec = self.read(b"ID3\x04" + b"\x00" * 64, "aula.mp3")
        self.assertIn("transcrição ainda não foi baixado", rec["message"])


class Hardening(Attach):
    """Achados da conferência independente da fase 4."""

    def test_text_html_csv_and_refusals(self):
        page = self.read(b"<!doctype html><html><body><h1>Persuasao</h1><p>Gatilho de escassez.</p><script>roubar()</script></body></html>",
                         "pagina.html")
        self.assertIn("Gatilho de escassez.", page["text"])
        self.assertNotIn("roubar", page["text"])
        self.assertIn("Canal;CPC", self.read("Canal;CPC\nInstagram;0,42\n".encode(), "custos.csv")["text"])
        for data, name, why in ((b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40, "foto.heic", "não sabe ler"), (b"", "vazio.txt", "vazio")):
            with self.assertRaises(AppError) as e:
                self.send(data, name)
            self.assertIn(why, str(e.exception))
        big = self.read(png_header(10000, 5000), "gigante.png")  # 50 milhões de pixels num arquivo de 70 bytes
        self.assertEqual(big["status"], "error")
        self.assertIn("pixels demais", big["message"])
        with mock.patch.object(attachments, "ZIP_TOTAL", 100):
            self.assertIn("se expande demais", self.read(DOCX, "inflado.docx")["message"])

    def test_pdf_read_in_part_says_so(self):
        from pypdf import PdfWriter
        w, out = PdfWriter(), io.BytesIO()
        for t in ("Primeira pagina", "Segunda pagina"):
            w.append(io.BytesIO(pdf_text(t)))
        w.write(out)
        with mock.patch.object(attachments, "PDF_PAGES", 1):
            rec = self.read(out.getvalue(), "longo.pdf")
        self.assertEqual(rec["status"], "ready")
        self.assertIn("Lidas as primeiras 1 de 2 páginas.", rec["message"])

    def test_video_keyframes_use_the_chat_window_and_keep_the_time(self):
        def frames(path, shots, model, check, status, num_ctx):
            shots.add(30, b"\xff\xd8quadro")
            shots.done(0, vision.clean(SEEN, manual=True))
            return True
        tr = {"segments": [{"start": 5, "end": 9, "text": "Abra a timeline."}], "duration": 60.0}
        with mock.patch.object(transcribe, "downloaded", return_value=True), mock.patch.object(transcribe, "transcribe", return_value=tr), \
                mock.patch.object(vision, "extract", side_effect=frames) as run:
            rec = self.read(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64, "aula.mp4")
        self.assertEqual(run.call_args.kwargs["num_ctx"], 32768)  # D38: o mesmo modelo do chat, sem recarregar
        self.assertEqual(rec["text"].splitlines()[0], "[00:05] Abra a timeline.")
        self.assertTrue(rec["text"].splitlines()[1].startswith("[00:30] (na tela) Funil de vendas:"))

    def test_reading_cut_by_closing_the_app_is_marked_on_the_next_start(self):
        with db.tx() as c:
            c.execute("INSERT INTO attachments(id, conversation_id, name, kind, created, status) VALUES (?, ?, ?, ?, ?, ?)",
                      ("a" * 32, "conversa", "aula.mp4", "video", db.now(), "reading"))
        attachments._swept.clear()
        attachments.sweep()
        row = db.one("SELECT status, message FROM attachments WHERE id = ?", "a" * 32)
        self.assertEqual(row["status"], "error")
        self.assertIn("interrompida", row["message"])

    def test_note_image_found_by_name_never_leaves_the_vault(self):
        outside = self.tmp / "fora.png"
        outside.write_bytes(png("red"))
        try:
            os.symlink(outside, self.vault / "fora.png")
        except OSError:
            self.skipTest("este Windows não deixa criar link simbólico")
        self.note("Nota.md", "![[fora.png]]")
        index.sync("obsidian")
        self.assertEqual(db.value("SELECT COUNT(*) FROM images"), 0)


class InChat(Attach):
    def test_attachment_is_a_cited_source_and_goes_away_with_the_conversation(self):
        self.ollama.answer = "O PDF fala de funil [S1]."
        aid = self.read(pdf_text("Funil de vendas: topo meio e fundo"), "funil.pdf")["id"]
        events = run_turn({"text": "Explique o funil do PDF", "attachments": [aid, "inexistente"]})
        user = next(e for e in events if e["type"] == "user")["message"]
        self.assertEqual(user["meta"]["attachments"], [{"id": aid, "name": "funil.pdf", "kind": "pdf"}])
        done = next(e for e in events if e["type"] == "done")["message"]
        first = done["sources"][0]
        self.assertEqual((first["sid"], first["source"], first["title"], first["cited"]), ("S1", "anexo", "funil.pdf", True))
        chats_sent = [b for path, b in self.ollama.requests if path == "/api/chat" and not b.get("format")]
        prompt = chats_sent[-1]["messages"][-1]["content"]
        self.assertIn('<documento id="S1" origem="Anexo" titulo="funil.pdf"', prompt)  # dado, embrulhado como as notas
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertEqual(db.value("SELECT conversation_id FROM attachments WHERE id = ?", aid), cid)
        # a pergunta seguinte da mesma conversa continua vendo o anexo
        again = run_turn({"conversation_id": cid, "text": "E o fundo do funil?"})
        self.assertEqual(next(e for e in again if e["type"] == "done")["message"]["sources"][0]["source"], "anexo")
        self.assertEqual(attachments.claim([aid], "outra", False), [])  # não muda de conversa
        chats.delete([cid])
        self.assertFalse(attachments.folder(aid).exists())
        self.assertIsNone(db.one("SELECT id FROM attachments WHERE id = ?", aid))

    def test_temporary_conversation_keeps_attachments_only_in_memory(self):
        aid = self.read(DOCX, "aula.docx")["id"]
        events = run_turn({"text": "Resuma o anexo", "attachments": [aid], "temporary": True})
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertTrue(cid.startswith("tmp-"))
        self.assertIsNone(db.one("SELECT id FROM attachments WHERE id = ?", aid))
        self.assertEqual([r["id"] for r in attachments.listing(cid)], [aid])
        chats.delete([cid])
        self.assertFalse(attachments.folder(aid).exists())
        self.assertEqual(attachments.listing(cid), [])

    def test_unsent_attachment_can_be_removed_and_leftovers_are_swept(self):
        aid = self.read(DOCX, "aula.docx")["id"]
        attachments.remove(aid)
        self.assertFalse(attachments.folder(aid).exists())
        with self.assertRaises(AppError):
            attachments.remove("../../study")  # id desconhecido nunca vira caminho
        orphan = db.MEDIA / "anexos" / "sobra-de-antes"
        orphan.mkdir(parents=True)
        kept = self.read(DOCX, "aula.docx")["id"]
        run_turn({"text": "Resuma", "attachments": [kept]})
        attachments._swept.clear()
        attachments.sweep()
        self.assertFalse(orphan.exists())
        self.assertTrue(attachments.folder(kept).exists())

    def test_add_to_index_survives_folder_sync_and_is_found_later(self):
        aid = self.read(XLSX, "custos.xlsx")["id"]
        run_turn({"text": "Leia a planilha", "attachments": [aid]})
        out = attachments.add_to_index(aid)
        self.assertEqual(out["doc_id"], "files:anexo:" + aid)
        index.sync("files")  # nenhuma pasta autorizada: a sincronização das pastas não tira o anexo
        found = search.search("Instagram CPC")["results"]
        self.assertEqual(found[0]["title"], "custos")
        self.assertEqual(found[0]["source"], "files")

    def test_screen_is_read_in_memory_and_not_stored(self):
        self.ollama.answer = "Na sua tela há um funil [S1]."
        with mock.patch.object(vision, "window_jpeg", return_value=(b"\xff\xd8fake", "Premiere — Adobe Premiere Pro.exe")), \
                mock.patch.object(vision, "read", return_value=vision.clean(SEEN, manual=True)) as see:
            events = run_turn({"text": "O que tem na minha tela?", "screen": True})
        self.assertEqual(see.call_args.kwargs["num_ctx"], 32768)  # a janela do chat: o modelo não recarrega
        self.assertIn({"type": "screen", "window": "Premiere — Adobe Premiere Pro.exe"}, events)
        live = next(e for e in events if e["type"] == "sources")["items"][0]
        self.assertEqual((live["source"], live["title"]), ("tela", "Tela: Premiere — Adobe Premiere Pro.exe"))
        self.assertIn("Meio: nutrir", live["chunks"][0]["text"])
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertEqual(done["sources"][0]["chunks"], [])  # o que a IA viu não fica guardado nas fontes
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertTrue(chats.get(cid)["messages"][0]["meta"]["screen"])
        self.assertFalse((db.MEDIA / "anexos").exists() and any((db.MEDIA / "anexos").iterdir()))


class NoteImages(Attach):
    def test_vault_images_become_searchable_text_in_their_section(self):
        img = self.vault / "B02 Estudos" / "anexos" / "funil.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(png())
        (self.tmp / "fora.png").write_bytes(png("red"))
        self.note("B02 Estudos/Marketing.md", "# Marketing\n## Funil\nVeja o esquema:\n![[funil.png|300]]\n\n![x](../../../fora.png)\n"
                                             "![x](https://site.com/a.png)")
        index.sync("obsidian")
        doc = db.one("SELECT * FROM documents WHERE title = 'Marketing'")
        self.assertEqual(db.value("SELECT COUNT(*) FROM images"), 1)  # a de fora do cofre e a da internet ficam de fora
        text = "\n".join(r["text"] for r in db.rows("SELECT text FROM chunks WHERE doc_id = ?", doc["id"]))
        self.assertIn("[Imagem: funil.png]", text)
        self.assertEqual(images.read_pending(lambda: None, 10), 1)
        self.assertEqual(db.value("SELECT version FROM documents WHERE id = ?", doc["id"]), "")  # relida na próxima
        index.sync("obsidian")
        row = db.one("SELECT heading, text FROM chunks WHERE doc_id = ? AND text LIKE '%nutrir%'", doc["id"])
        self.assertEqual(row["heading"], "Marketing › Funil")  # ligada à seção onde aparece
        self.assertIn("[Imagem “funil.png”: Funil de vendas", row["text"])
        index.embed_missing()
        hit = search.search("nutrir converter")["results"][0]
        self.assertEqual(hit["title"], "Marketing")
        self.assertEqual(len(hit["images"]), 1)
        self.assertTrue(images.path(hit["images"][0][2:]).is_file())
        self.assertEqual(images.read_pending(lambda: None, 10), 0)  # a mesma imagem não é lida de novo

    def test_images_off_keeps_the_note_as_it_was(self):
        (self.vault / "x.png").write_bytes(png())
        settings.save({"search": {"images": False}})
        self.note("Nota.md", "Antes ![[x.png]] depois")
        index.sync("obsidian")
        self.assertEqual(db.value("SELECT COUNT(*) FROM images"), 0)
        self.assertIn("![[x.png]]", db.value("SELECT text FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE d.title = 'Nota'"))


class NotionImages(idx.Base):
    block, rich = idx.NotionIndex.block, idx.NotionIndex.rich  # os auxiliares, sem herdar (e repetir) os testes de lá

    def setUp(self):
        super().setUp()
        self.fake = idx.Fake()
        for p in (mock.patch.object(idx.store, "get_token", return_value="secret_test"), mock.patch.object(db, "MEDIA", self.tmp / "media")):
            p.start()
            self.stack.append(p)

    def tearDown(self):
        self.fake.close()
        super().tearDown()

    def test_notion_images_are_downloaded_at_sync_and_read_later(self):
        from tests.fake_ollama import FakeOllama
        fake = FakeOllama(models=(vision.MODEL, "qwen3-embedding:0.6b"))
        fake.json_replies["Você lê uma captura de tela"] = SEEN
        try:
            url = "https://prod-files-secure.s3.us-west-2.amazonaws.com/a/funil.png?X-Amz-Expires=3600"
            page = self.fake.add_page("Tráfego pago")
            self.fake.pages[page]["blocks"] = [self.block("heading_2", "Funil"),
                                               {"id": "img1", "object": "block", "type": "image", "has_children": False,
                                                "image": {"type": "file", "file": {"url": url}, "caption": self.rich("Esquema do funil")}},
                                               {"id": "img2", "object": "block", "type": "image", "has_children": False,
                                                "image": {"type": "external", "external": {"url": "https://site.com/b.png"}, "caption": []}}]
            with mock.patch.object(web, "_get", return_value=(200, "image/png", png(), url)) as get:
                index.sync("notion")
            self.assertEqual([c.args[0] for c in get.call_args_list], [url])  # só a enviada ao Notion (a de fora fica)
            self.assertEqual(db.value("SELECT source FROM images"), "notion")
            self.assertEqual(images.read_pending(lambda: None, 5), 1)
            with mock.patch.object(web, "_get", return_value=(200, "image/png", png(), url)):
                index.sync("notion")
            text = db.value("SELECT text FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE d.title = 'Tráfego pago' AND c.text LIKE '%Imagem%'")
            self.assertIn("[Imagem “Esquema do funil”: Funil de vendas", text)
            meta = json.loads(db.value("SELECT meta FROM documents WHERE title = 'Tráfego pago'"))
            self.assertEqual(meta["images"][0]["name"], "Esquema do funil")
        finally:
            fake.close()
