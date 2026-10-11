import json
import unittest
import urllib.error
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, Cancelled, llm, notion
from tests.fake_notion import Fake
from tests.test_llm import GOOD

META = {"course": "Biologia", "yt_id": "dQw4w9WgXcQ", "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "source": "YouTube — Fotossíntese", "duration": 75, "language": "pt", "model": "qwen3:8b",
        "transcript_origin": "Transcrição importada.", "uncertain": 2}


def flat(blocks):
    """Todos os blocos, com os de dentro (colunas, tabelas, toggles, callouts)."""
    for b in blocks:
        yield b
        yield from flat(b[b["type"]].get("children", []))


def rich(blocks):
    for b in blocks:
        yield from b[b["type"]].get("rich_text", [])
        for cell in b[b["type"]].get("cells", []):
            yield from cell


def texts(blocks):
    return "".join(rt["text"]["content"] for rt in rich(blocks))


def heads(blocks, kind="heading_2"):
    return [texts([b]).split(" ", 1)[-1] for b in blocks if b["type"] == kind]  # sem o emoji


class Build(unittest.TestCase):
    def setUp(self):
        self.lesson = llm.validate(GOOD, 75)
        self.title, self.blocks = notion.build_page(self.lesson, META)

    def test_answers_hidden_in_toggles(self):
        toggles = [b for b in self.blocks if b["type"] == "toggle"]
        self.assertEqual(len(toggles), 1)
        self.assertEqual(texts(toggles), "Onde ocorre?")  # pergunta visível
        self.assertEqual(texts(toggles[0]["toggle"]["children"]), "Nos cloroplastos.")
        outside = [b for b in flat(self.blocks) if b not in list(flat(toggles))]
        self.assertNotIn("Nos cloroplastos.", texts(outside))  # resposta só dentro do toggle

    def test_sections_and_links(self):
        headings = heads(self.blocks)
        for h in ["Resumo", "Explicação simples", "Tópicos principais", "Perguntas de revisão", "Momentos da aula"]:
            self.assertIn(h, headings)
        links = [(rt["text"].get("link") or {}).get("url") for rt in rich(flat(self.blocks))]
        self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=40s", links)  # tópico
        self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=65s", links)  # momento, na tabela
        self.assertIn("2 trecho(s)", texts(flat(self.blocks)))

    def test_rich_layout(self):
        kinds = [b["type"] for b in self.blocks]
        self.assertEqual(kinds[0], "column_list")  # ficha da aula | “Nesta aula” e o checklist de estudo
        head = list(flat(self.blocks[:1]))
        self.assertEqual(len([b for b in head if b["type"] == "to_do"]), 4)
        self.assertIn("2 tópicos · 1 pergunta · 1 termo", texts(head))
        callouts = {b["callout"]["icon"]["emoji"]: texts([b]) for b in flat(self.blocks) if b["type"] == "callout"}
        self.assertEqual(callouts["💡"], "Ideia central\nPlantas produzem glicose.")
        self.assertIn("Fase clara\nDepende de luz.", callouts["1️⃣"])  # tópico em cartão
        self.assertEqual(callouts["✅"], "Nos cloroplastos.")  # resposta em destaque, dentro do toggle
        tables = [b for b in self.blocks if b["type"] == "table"]
        self.assertEqual(texts(tables[0]["table"]["children"]), "TermoSignificadoClorofilaPigmento verde.")
        self.assertEqual(texts(tables[1]["table"]["children"]), "TempoMomento01:05Exemplo")
        # termos do glossário em negrito no texto; aula com ressalvas: “Pontos de atenção” à vista
        lesson = {**self.lesson, "summary": "A clorofila capta luz.\n\nSem clorofila, nada.", "caveats": ["Trecho confuso"]}
        _, blocks = notion.build_page(lesson, META)
        bold = [rt["text"]["content"] for rt in rich(flat(blocks)) if rt["annotations"]["bold"]]
        self.assertIn("clorofila", bold)
        self.assertIn("Clorofila", bold)
        warn = next(b for b in flat(blocks) if b["type"] == "callout" and b["callout"]["icon"]["emoji"] == "⚠️")
        self.assertEqual(texts(warn["callout"]["children"]), "Trecho confuso")

    def test_long_text_split(self):
        _, blocks = notion.build_page({**self.lesson, "summary": "a" * 4500}, META)
        sizes = [len(rt["text"]["content"]) for b in blocks for rt in b[b["type"]].get("rich_text", [])]
        self.assertLessEqual(max(sizes), 2000)

    def test_youtube_player_before_summary(self):
        for link in (META["link"], "https://youtu.be/dQw4w9WgXcQ?si=share",
                     "https://www.youtube.com/shorts/dQw4w9WgXcQ"):
            _, blocks = notion.build_page(self.lesson, {**META, "link": link})
            videos = [b for b in blocks if b["type"] == "video"]
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0]["video"]["external"]["url"], META["link"])
            self.assertEqual(videos[0]["video"]["caption"][0]["text"]["content"], "Aula original · YouTube")
            index = blocks.index(videos[0])
            self.assertEqual(heads([blocks[index - 1]]), ["Assistir à aula"])
            self.assertEqual(blocks[index + 1]["type"], "divider")
            self.assertLess(index, next(i for i, b in enumerate(blocks) if heads([b]) == ["Resumo"]))

    def test_non_youtube_reference_has_no_player(self):
        for link in (None, "https://example.com/aula", "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ"):
            _, blocks = notion.build_page(self.lesson, {**META, "link": link, "yt_id": None})
            self.assertFalse(any(b["type"] == "video" for b in blocks))
            if link:
                self.assertIn(link, texts(flat(blocks)))

    def test_long_transcript_line_is_not_truncated(self):
        line = "[00:00] " + "texto corrigido " * 300
        _, blocks = notion.transcript_section([line])
        self.assertEqual(texts(blocks), line)
        self.assertTrue(all(len(rt["text"]["content"]) <= 2000 for rt in blocks[0]["paragraph"]["rich_text"]))

    def test_page_id(self):
        self.assertEqual(notion.page_id("https://www.notion.so/Estudos-0123456789abcdef0123456789abcdef?pvs=4"),
                         "01234567-89ab-cdef-0123-456789abcdef")
        with self.assertRaises(AppError):
            notion.page_id("https://www.notion.so/sem-id")


class Api(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")

    def tearDown(self):
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def test_courses_and_no_course(self):
        c = notion.create_course("secret_test", self.root, "Biologia")
        self.assertEqual(notion.list_courses("secret_test", self.root), [c])
        nid = notion.course_for("secret_test", self.root, "__none__")
        self.assertEqual(notion.course_for("secret_test", self.root, "__none__"), nid)  # não duplica
        self.assertEqual(len(notion.list_courses("secret_test", self.root)), 2)

    def test_list_pages_with_paths(self):
        claude = notion.create_course("secret_test", self.root, "claude")
        notion.create_course("secret_test", claude["id"], "Módulo 1")
        apagada = notion.create_course("secret_test", self.root, "Apagada")
        notion.trash("secret_test", apagada["id"])
        self.assertEqual([p["path"] for p in notion.list_pages("secret_test")],
                         ["Estudos", "Estudos › claude", "Estudos › claude › Módulo 1"])

    def test_publish_many_blocks(self):
        blocks = [notion._b("paragraph", notion._rt(f"p{i}")) for i in range(230)]
        pid, url, ids = notion.publish("secret_test", self.root, "Aula", blocks, lambda: None)
        self.assertEqual(pid, self.root)
        self.assertEqual(len(self.fake.pages), 1)
        self.assertEqual(len(self.fake.pages[pid]["blocks"]), 231)
        self.assertEqual(len(ids), 231)
        self.assertEqual(self.fake.calls.count(("PATCH", f"/blocks/{pid}/children")), 3)
        self.assertEqual(notion.page_url("secret_test", pid), f"https://www.notion.so/{pid}")

    def test_failed_append_removes_only_new_blocks(self):
        notion.publish("secret_test", self.root, "Anterior", [], lambda: None)
        original = list(self.fake.pages[self.root]["blocks"])
        route = self.fake.route
        calls = 0
        def fail_second(method, path, body):
            nonlocal calls
            if method == "PATCH":
                calls += 1
                if calls == 2:
                    return 400, {"code": "validation_error"}
            return route(method, path, body)
        blocks = [notion._b("paragraph", notion._rt("x"))] * 150
        with mock.patch.object(self.fake, "route", side_effect=fail_second), self.assertRaises(AppError):
            notion.publish("secret_test", self.root, "Aula", blocks, lambda: None)
        self.assertEqual(self.fake.pages[self.root]["blocks"], original)
        self.assertFalse(self.fake.pages[self.root]["in_trash"])
        self.assertEqual(len(self.fake.pages), 1)

    def test_cancel_removes_only_new_blocks(self):
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise Cancelled
        with self.assertRaises(Cancelled):
            notion.publish("secret_test", self.root, "Aula", [notion._b("paragraph", notion._rt("x"))] * 150, check)
        self.assertEqual(self.fake.pages[self.root]["blocks"], [])
        self.assertFalse(self.fake.pages[self.root]["in_trash"])

    def test_long_transcript_appended_in_batches(self):
        pid, _, ids = notion.publish("secret_test", self.root, "Aula", [], lambda: None,
                                    transcript=[f"[00:00] trecho {i}" for i in range(230)])
        head = self.fake.pages[pid]["blocks"][-1]
        self.assertEqual(len(head["heading_3"]["children"]), 230)
        self.assertEqual(len(ids), 2)

    def test_missing_or_trashed_destination_is_not_modified(self):
        for pid in ("01234567-89ab-cdef-0123-456789abcdef", self.root):
            self.fake.pages[self.root]["in_trash"] = True
            with self.assertRaises(AppError):
                notion.publish("secret_test", pid, "Aula", [], lambda: None)
        self.assertFalse(any(method == "PATCH" for method, path in self.fake.calls))

    def test_cleanup_failure_reports_partial_content(self):
        def check():
            if self.fake.pages[self.root]["blocks"]:
                self.fake.fail_append = True
        route = self.fake.route
        def fail_delete(method, path, body):
            return (403, {"code": "restricted_resource"}) if method == "DELETE" else route(method, path, body)
        with mock.patch.object(self.fake, "route", side_effect=fail_delete), self.assertRaises(AppError) as e:
            notion.publish("secret_test", self.root, "Aula", [notion._b("paragraph", notion._rt("x"))] * 150, check)
        self.assertIn("parte do material", str(e.exception))
        self.assertFalse(self.fake.pages[self.root]["in_trash"])

    def test_errors(self):
        with self.assertRaises(AppError) as e:
            notion.request("GET", "/pages/nao-existe", "secret_test")
        self.assertIn("Conexões", e.exception.action)

    def test_append_does_not_retry_when_response_is_lost(self):
        with mock.patch.object(notion.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")) as send:
            with self.assertRaises(AppError) as e:
                notion.request("PATCH", f"/blocks/{self.root}/children", "secret_test", {"children": []})
        self.assertEqual(send.call_count, 1)
        self.assertIn("Confira a página", e.exception.action)

    def test_real_page_shape(self):
        title, blocks = notion.build_page(llm.validate(GOOD, 75), META)
        self.fake.pages[self.root]["icon"] = {"emoji": "🤖"}
        self.fake.pages[self.root]["cover"] = {"external": {"url": "https://example.com/capa.png"}}
        pid, _, _ = notion.publish("secret_test", self.root, title, blocks, lambda: None)
        self.assertEqual(self.fake.pages[pid]["title"], "Estudos")
        self.assertEqual(texts(self.fake.pages[pid]["blocks"][:1]), "Fotossíntese")
        self.assertEqual(self.fake.pages[pid]["icon"]["emoji"], "🤖")
        self.assertEqual(self.fake.pages[pid]["cover"]["external"]["url"], "https://example.com/capa.png")
        json.dumps(self.fake.pages[pid]["blocks"])  # serializável


if __name__ == "__main__":
    unittest.main()
