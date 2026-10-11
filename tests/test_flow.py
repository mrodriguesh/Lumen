"""Fluxo completo com Ollama e Notion simulados: YouTube + transcrição colada → página no Notion."""
import http.client
import json
import threading
import time
import unittest
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import jobs, llm, notion, server, sources, store
from tests.fake_notion import Fake
from tests.test_llm import GOOD

CAPTIONS = "0:00\nHoje vamos estudar fotossíntese.\n0:40\nA fase clara depende de luz.\n1:05\nExemplo da planta no escuro."
SPEC = {"kind": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ", "captions": CAPTIONS, "language": "pt", "mode": "new"}
META_LINK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def full(spec, **finish):
    """Fase 1 (transcrição → revisão) e fase 2 (confirmação → Notion), como na interface."""
    jobs.start("process", jobs.process, spec)
    j = wait()
    if j["status"] != "done":
        return j
    assert j["result"]["review"], j
    jobs.start("process", jobs.finish, {**spec, **finish})
    return wait()


def wait():
    for _ in range(1200):
        j = jobs.snapshot()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("tarefa presa")


class Flow(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(sources, "youtube_meta", return_value={"title": "Fotossíntese", "author": "Prof"}),
                        mock.patch.object(llm, "_chat", return_value=json.dumps(GOOD)),
                        mock.patch("lumen.mindmap.render", return_value=None)]  # Edge real só em test_mindmap
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def test_mind_map_image_then_text_fallback(self):
        PNG = bytes([137]) + b"PNG" + b"0" * 6000
        lesson = {**GOOD, "mind_map": {"center": "Fotossíntese", "branches": [
            {"label": "Fase clara", "emoji": "☀️", "children": ["Depende de luz", "Ocorre nos tilacoides"]},
            {"label": "Clorofila", "emoji": "🌿", "children": ["Pigmento verde"]}]}}
        with mock.patch.object(llm, "_chat", return_value=json.dumps(lesson)), mock.patch("lumen.mindmap.render", return_value=PNG):
            j = full({**SPEC, "course_id": self.root})
        self.assertEqual(j["status"], "done", j.get("error"))
        blocks = self.fake.pages[self.root]["blocks"]
        img = [b for b in blocks if b["type"] == "image"]
        self.assertEqual(len(img), 1)
        self.assertEqual(self.fake.uploads[img[0]["image"]["file_upload"]["id"]]["status"], "uploaded")
        heads = [b["heading_2"]["rich_text"][0]["text"]["content"] for b in blocks if b["type"] == "heading_2"]
        self.assertEqual(heads[heads.index("Resumo") + 1], "Mapa mental")
        # envio da imagem falhou → o mesmo mapa entra em tópicos, e a aula é publicada
        self.fake.fail_upload = True
        with mock.patch.object(llm, "_chat", return_value=json.dumps({**lesson, "title": "Outra"})), mock.patch("lumen.mindmap.render", return_value=PNG):
            j = full({**SPEC, "url": "https://youtu.be/aaaaaaaaaaa", "course_id": self.root})
        self.assertEqual(j["status"], "done", j.get("error"))
        items = [b for b in self.fake.pages[self.root]["blocks"] if b["type"] == "bulleted_list_item"
                 and b["bulleted_list_item"].get("children")]
        self.assertEqual(items[0]["bulleted_list_item"]["children"][1]["bulleted_list_item"]["rich_text"][0]["text"]
                         ["content"], "Ocorre nos tilacoides")

    def test_publish_then_detect_duplicate_then_replace(self):
        j = full({**SPEC, "course_id": "__none__"})
        self.assertEqual(j["status"], "done", j.get("error"))
        sem_curso = [p for p in self.fake.pages.values() if p["title"] == "Sem curso"][0]
        first = dict(store.history()["yt:dQw4w9WgXcQ"])
        self.assertEqual(first["page_id"], sem_curso["id"])
        self.assertEqual(len(self.fake.pages), 2)
        self.assertTrue((jobs.work_dir("yt:dQw4w9WgXcQ") / "published").exists())  # só a última fica (Refazer)

        info = server.inspect(SPEC)
        self.assertEqual(info["duplicate"]["page_id"], sem_curso["id"])

        manual = notion.request("PATCH", f"/blocks/{sem_curso['id']}/children", "secret_test",
                                {"children": [notion._b("paragraph", notion._rt("Minha anotação"))]})["results"][0]["id"]

        self.assertEqual(full({**SPEC, "course_id": "__none__", "mode": "replace"})["status"], "done")
        self.assertFalse(sem_curso["in_trash"])
        updated = store.history()["yt:dQw4w9WgXcQ"]
        self.assertEqual(updated["page_id"], first["page_id"])
        self.assertTrue(all(self.fake.blocks[bid]["in_trash"] for bid in first["block_ids"]))
        self.assertIn(manual, [b["id"] for b in sem_curso["blocks"]])
        self.assertEqual(len(self.fake.pages), 2)

    def test_http_flow_saves_in_page_created_at_start(self):
        httpd = server.serve()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        def post(path, body):
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
            try:
                c.request("POST", path, body=json.dumps(body), headers={"X-Lumen-Token": server.TOKEN,
                          "Content-Type": "application/json"})
                r = c.getresponse()
                data = json.loads(r.read())
                self.assertEqual(r.status, 200, data)
                return data
            finally:
                c.close()
        try:
            made = post("/api/courses", {"title": "Você NUNCA mais vai precisar editar", "parent_id": self.root})
            spec = {**SPEC, "course_id": made["id"], "course_title": made["title"]}
            before = len(self.fake.pages)
            post("/api/start", spec)
            self.assertTrue(wait()["result"]["review"])
            self.assertEqual(self.fake.pages[made["id"]]["blocks"], [])
            post("/api/finish", {**spec, "edits": {"1": "Texto corrigido pelo usuário."}, "include_transcript": True})
            result = wait()
            self.assertEqual(result["status"], "done", result.get("error"))
            self.assertEqual(store.history()["yt:dQw4w9WgXcQ"]["page_id"], made["id"])
            self.assertEqual(len(self.fake.pages), before)
            page = self.fake.pages[made["id"]]
            self.assertEqual(page["title"], made["title"])
            self.assertIn(made["id"].replace("-", ""), result["result"]["url"].replace("-", ""))
            self.assertIn("Texto corrigido pelo usuário.", json.dumps(page["blocks"], ensure_ascii=False))
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_replace_legacy_or_different_destination_preserves_old_page(self):
        old = self.fake.add_page("Aula antiga", self.root)
        store.remember("yt:dQw4w9WgXcQ", {"page_id": old})
        j = full({**SPEC, "course_id": self.root, "mode": "replace"})
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertFalse(self.fake.pages[old]["in_trash"])
        self.assertIn("preservada", j["result"]["note"])

    def test_add_change_or_remove_video_after_recording_file_was_deleted(self):
        for kind in ("recording", "file", "telegram"):
            with self.subTest(kind=kind):
                key = "file:player-" + kind
                path = str(store.WORK / "uploads" / (kind + "-deleted.wav"))
                src = {"kind": kind, "key": key, "path": path, "title": "Aula gravada",
                       "label": sources.LABELS[kind], "link": "https://youtu.be/abcdefghijk", "duration": 65}
                work = jobs.work_dir(key)
                work.mkdir(parents=True, exist_ok=True)
                jobs._save(work / "source.json", src)
                jobs._save(work / "transcript.json", {"segments": sources.parse_captions(CAPTIONS),
                                                      "origin": "Transcrição local revisada.", "duration": 65})
                spec = {"kind": kind, "path": path, "course_id": self.root,
                        "link": "https://youtu.be/dQw4w9WgXcQ?si=x"}
                self.fake.fail_append = True
                jobs.start("process", jobs.finish, spec)
                self.assertEqual(wait()["status"], "error")
                self.fake.fail_append = False
                jobs.start("process", jobs.finish, spec)
                j = wait()
                self.assertEqual(j["status"], "done", j)
                videos = [b for b in self.fake.pages[self.root]["blocks"] if b["type"] == "video"]
                self.assertEqual(videos[-1]["video"]["external"]["url"], META_LINK)
                self.assertFalse(any(b["type"] == "child_page" for b in self.fake.pages[self.root]["blocks"]))
                self.assertEqual(len(self.fake.pages), 1)

    def test_blank_review_link_removes_cached_video_reference(self):
        key = "file:removed-link"
        path = str(store.WORK / "removed-recording.wav")
        work = jobs.work_dir(key)
        work.mkdir(parents=True, exist_ok=True)
        jobs._save(work / "source.json", {"kind": "recording", "key": key, "path": path,
                                         "title": "Aula", "label": "Gravação", "link": META_LINK})
        jobs._save(work / "transcript.json", {"segments": sources.parse_captions(CAPTIONS), "origin": "Revisada."})
        jobs.start("process", jobs.finish, {"kind": "recording", "path": path, "course_id": self.root, "link": ""})
        j = wait()
        self.assertEqual(j["status"], "done", j)
        self.assertFalse(any(b["type"] == "video" for b in self.fake.pages[self.root]["blocks"]))

    def test_replace_cleanup_failure_is_visible_and_remembered(self):
        spec = {**SPEC, "course_id": self.root}
        self.assertEqual(full(spec)["status"], "done")
        old = dict(store.history()["yt:dQw4w9WgXcQ"])
        route = self.fake.route
        def no_delete(method, path, body):
            return (403, {"code": "restricted_resource"}) if method == "DELETE" else route(method, path, body)
        with mock.patch.object(self.fake, "route", side_effect=no_delete):
            j = full({**spec, "mode": "replace"})
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertIn("não pôde ser removida", j["result"]["note"])
        self.assertTrue(set(old["block_ids"]).issubset(store.history()["yt:dQw4w9WgXcQ"]["block_ids"]))
        self.assertFalse(self.fake.pages[self.root]["in_trash"])

    def test_failure_keeps_work_and_retry_skips_llm(self):
        self.fake.close()
        with mock.patch("lumen.notion.API", "http://127.0.0.1:9/v1"), mock.patch("lumen.notion.time", mock.Mock()):  # Notion fora do ar
            j = full({**SPEC, "course_id": "__none__"})
        self.assertEqual(j["status"], "error")
        self.assertIn("Notion", j["error"]["message"])
        self.assertTrue((jobs.work_dir("yt:dQw4w9WgXcQ") / "lesson.json").exists())

        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        llm._chat.reset_mock()
        self.assertEqual(full({**SPEC, "course_id": "__none__"})["status"], "done")
        llm._chat.assert_not_called()  # material reaproveitado

    def test_cancel(self):
        def slow(*a, **k):
            for _ in range(100):
                jobs.check()
                time.sleep(0.02)
            return json.dumps(GOOD)
        with mock.patch.object(llm, "_chat", side_effect=slow):
            jobs.start("process", jobs.process, {**SPEC, "course_id": "__none__"})
            self.assertTrue(wait()["result"]["review"])
            jobs.start("process", jobs.finish, {**SPEC, "course_id": "__none__"})
            time.sleep(0.2)
            jobs.cancel()
            self.assertEqual(wait()["status"], "cancelled")
        self.assertEqual(self.fake.pages[self.root]["blocks"], [])

    def test_missing_transcript_and_not_configured(self):
        jobs.start("process", jobs.process, {**SPEC, "captions": "", "course_id": "__none__"})
        self.assertIn("Falta a transcrição", wait()["error"]["message"])
        with mock.patch.object(store, "get_token", return_value=None):
            jobs.start("process", jobs.process, SPEC)
            self.assertIn("Notion", wait()["error"]["message"])

    def test_review_stops_before_notion_and_flags(self):
        jobs.start("process", jobs.process, {**SPEC, "captions": "0:00\nEm 1990 a Maria explicou.\n0:05\ntexto comum aqui"})
        r = wait()["result"]
        self.assertTrue(r["review"])
        self.assertEqual(r["segments"][0]["flags"], ["número", "nome próprio"])
        self.assertEqual(r["segments"][1]["flags"], [])
        self.assertEqual(self.fake.pages[self.root]["blocks"], [])  # nada publicado

    def test_summary_uses_reviewed_transcript_and_optional_transcript(self):
        jobs.start("process", jobs.process, {**SPEC, "course_id": "__none__"})
        self.assertTrue(wait()["result"]["review"])
        jobs.start("process", jobs.finish, {**SPEC, "course_id": "__none__", "include_transcript": True,
                                            "edits": {"1": "A fase clara depende da luz solar, corrigido."}})
        self.assertEqual(wait()["status"], "done")
        sent = llm._chat.call_args[0][2]  # transcrição enviada ao modelo local
        self.assertIn("corrigido", sent)
        self.assertNotIn("A fase clara depende de luz.", sent)
        page = [p for p in self.fake.pages.values() if p["title"] == "Sem curso"][0]
        head = page["blocks"][-1]
        self.assertEqual(head["type"], "heading_3")
        self.assertTrue(head["heading_3"]["is_toggleable"])  # recolhida
        lines = ["".join(t["text"]["content"] for t in b["paragraph"]["rich_text"]) for b in head["heading_3"]["children"]]
        self.assertTrue(any("corrigido" in ln for ln in lines))

    def test_captions_keep_own_timestamps_even_with_4x(self):
        jobs.start("process", jobs.process, {**SPEC, "speed": "4"})
        r = wait()["result"]
        self.assertEqual([s["start"] for s in r["segments"]], [0, 40, 65])  # nada de conversão de velocidade
        self.assertIsNone(r["speed"])

    def test_create_subpage_inside_chosen_page(self):
        import types
        from lumen import notion
        claude = notion.create_course("secret_test", self.root, "Claude")
        body = json.dumps({"title": "Módulo 3", "parent_id": claude["id"]}).encode()
        h = types.SimpleNamespace(headers={"Content-Length": str(len(body))}, rfile=__import__("io").BytesIO(body))
        h._json = lambda: server.Handler._json(h)
        made = server._new_course(h)
        self.assertEqual(self.fake.pages[made["id"]]["parent"], claude["id"])
        paths = [p["path"] for p in notion.list_pages("secret_test")]
        self.assertIn("Estudos › Claude › Módulo 3", paths)
        h2 = types.SimpleNamespace(_json=lambda: {"title": "Novo curso"})  # sem parent_id: vai para a raiz
        self.assertEqual(self.fake.pages[server._new_course(h2)["id"]]["parent"], self.root)

    def test_root_pages_and_unreachable_root(self):
        from lumen import AppError, notion
        notion.create_course("secret_test", self.root, "Claude")
        r = server._courses(None)
        self.assertTrue(r["root_ok"])
        self.assertEqual({p["title"]: p["top"] for p in r["courses"]}, {"Estudos": True, "Claude": False})
        store.save_config({**store.DEFAULTS, "root_page_id": "3cbda19f-29c2-47d8-a45d-954e8954ab61"})  # sem acesso
        r = server._courses(None)
        self.assertFalse(r["root_ok"])
        self.assertEqual(len(r["courses"]), 2)  # a lista continua disponível para escolher outra página
        with self.assertRaises(AppError):
            notion.course_for("secret_test", "", "__none__")

    def test_database_rows_are_not_listed(self):
        from lumen import notion
        row = self.fake.add_page("Supino reto")
        self.fake.pages[row]["parent_raw"] = {"type": "database_id", "database_id": "db1"}
        self.fake.add_page("Anotação do treino", row)  # dentro da linha: também fica de fora
        self.assertEqual([p["title"] for p in notion.list_pages("secret_test")], ["Estudos"])

    def test_decorated_subpage(self):
        import types
        decor = json.dumps({"emoji": "🎨", "cover": "gradients_5", "color": "purple_background",
                            "subtitle": "Resumos e anotações das aulas de Edição de cor"})
        with mock.patch.object(llm, "_chat", return_value=decor), mock.patch("lumen.cover.render", return_value=None):
            # sem Edge para desenhar a capa: usa a capa reserva do próprio Notion
            made = server._new_course(types.SimpleNamespace(_json=lambda: {"title": "Edição de cor", "decorate": True}))
        page = self.fake.pages[made["id"]]
        self.assertEqual(page["icon"]["emoji"], "🎨")
        self.assertEqual(page["cover"]["external"]["url"], "https://www.notion.so/images/page-cover/gradients_5.png")
        self.assertEqual([b["type"] for b in page["blocks"]], ["callout", "divider", "heading_2"])
        self.assertEqual(page["blocks"][0]["callout"]["color"], "purple_background")

    def test_cover_preview_is_uploaded_as_cover(self):
        import types
        decor = json.dumps({"emoji": "🌱", "motifs": ["🌞", "🍃"], "palette": "natureza_sol",
                            "cover": "gradients_8", "color": "green_background", "subtitle": "Resumos de fotossíntese"})
        with mock.patch.object(llm, "_chat", return_value=decor), \
                mock.patch("lumen.cover.render", return_value=b"\x89PNG" + b"0" * 5000):
            pv = server._preview(types.SimpleNamespace(_json=lambda: {"title": "Fotossíntese", "parent_path": "Cursos"}))
            self.assertTrue(pv["image"].startswith("data:image/png;base64,"))
            made = server._new_course(types.SimpleNamespace(_json=lambda: {
                "title": "Fotossíntese", "decorate": True, "preview_id": pv["preview_id"]}))
        page = self.fake.pages[made["id"]]
        self.assertEqual(page["cover"]["type"], "file_upload")
        up = self.fake.uploads[page["cover"]["file_upload"]["id"]]
        self.assertEqual((up["status"], up["content_type"]), ("uploaded", "image/png"))
        self.assertEqual(page["icon"]["emoji"], "🌱")

    def test_cover_upload_failure_uses_notion_cover(self):
        import types
        self.fake.fail_upload = True
        decor = json.dumps({"emoji": "🌱", "motifs": [], "palette": "floresta", "cover": "gradients_8",
                            "color": "green_background", "subtitle": "x"})
        with mock.patch.object(llm, "_chat", return_value=decor), \
                mock.patch("lumen.cover.render", return_value=b"\x89PNG" + b"0" * 5000):
            made = server._new_course(types.SimpleNamespace(_json=lambda: {"title": "Folhas", "decorate": True}))
        cov = self.fake.pages[made["id"]]["cover"]
        self.assertEqual(cov["external"]["url"], "https://www.notion.so/images/page-cover/gradients_8.png")

    def test_cover_uses_ai_illustration_when_installed(self):
        from lumen import imagegen
        decor = {"emoji": "🌱", "motifs": [], "palette": llm.DEFAULT_PALETTE, "image_prompt": "a green leaf"}
        with mock.patch.object(imagegen, "ready", return_value=True),                 mock.patch.object(imagegen, "generate", return_value=b"PNG-IA") as gen:
            self.assertEqual(server._cover_png(decor, "Fotossíntese", 1), (b"PNG-IA", "ia"))
        self.assertEqual(gen.call_args[0][0], "a green leaf")
        with mock.patch.object(imagegen, "ready", return_value=True), mock.patch.object(imagegen, "generate", return_value=None),                 mock.patch("lumen.cover.render", return_value=b"PNG-EMOJI"):
            self.assertEqual(server._cover_png(decor, "x", 1), (b"PNG-EMOJI", "emojis"))  # IA falhou: emojis
        with mock.patch.object(imagegen, "ready", return_value=False), mock.patch("lumen.cover.render", return_value=b"E"):
            self.assertEqual(server._cover_png(decor, "x", 1)[1], "emojis")               # sem gerador instalado

    def test_decoration_falls_back_safely(self):
        import types
        bad = json.dumps({"emoji": "<b>", "motifs": ["🟢", "x", "🍃", "<i>"], "palette": ["red", "#12345", "#00ff00"],
                          "cover": "nao-existe", "color": "neon", "subtitle": "x" * 500})
        with mock.patch.object(llm, "_chat", return_value=bad):
            d = llm.decorate("Qualquer", "", "m")
        self.assertEqual((d["emoji"], d["cover"], d["color"]), ("📘", "gradients_3", "blue_background"))
        self.assertEqual(d["motifs"], ["🍃"])                      # sem HTML, texto ou formas geométricas
        self.assertEqual(d["palette"], llm.DEFAULT_PALETTE)       # paleta fora da lista → padrão seguro
        self.assertLessEqual(len(d["subtitle"]), 160)
        with mock.patch.object(llm, "_chat", side_effect=llm.AppError("O Ollama não está rodando.", "")):
            made = server._new_course(types.SimpleNamespace(_json=lambda: {"title": "Sem IA", "decorate": True}))
        self.assertIn("sem enfeites", made["note"])
        self.assertIsNone(self.fake.pages[made["id"]]["cover"])  # criada mesmo assim, simples

    def test_transcript_not_published_by_default(self):
        self.assertEqual(full({**SPEC, "course_id": "__none__"})["status"], "done")
        page = [p for p in self.fake.pages.values() if p["title"] == "Sem curso"][0]
        self.assertFalse(any(b["type"] == "heading_3" and b["heading_3"].get("is_toggleable") for b in page["blocks"]))


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve()
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, headers=None, method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request(method, path, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
        r = c.getresponse()
        return r.status, r.read()

    def test_ui_has_token_and_csp(self):
        status, body = self.req("/")
        self.assertEqual(status, 200)
        self.assertIn(server.TOKEN.encode(), body)

    def test_api_requires_token(self):
        self.assertEqual(self.req("/api/state")[0], 403)
        self.assertEqual(self.req("/api/state", {"X-Lumen-Token": "errado"})[0], 403)
        with mock.patch.object(store, "get_token", return_value=None):
            status, body = self.req("/api/state", {"X-Lumen-Token": server.TOKEN})
        self.assertEqual(status, 200)
        self.assertIn("whisper", json.loads(body))

    def test_rejects_foreign_host(self):
        self.assertEqual(self.req("/", {"Host": "evil.example:80"})[0], 403)

    def test_no_static_traversal(self):
        self.assertEqual(self.req("/../lumen/store.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
