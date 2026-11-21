"""Prática e plano aplicado: fontes, notas por critério, persistência, anexos e eventos reais do timer isolado."""
import copy
import io
import time
from datetime import date, timedelta
from unittest import mock

import tests  # noqa: F401
from lumen import AppError
from lumen.study import api, applied, attachments, chats, data, db, learn, mastery, registry, search, tools
from tests.test_study_index import Base

EXERCISE = {"task": "Monte uma revisão de memória com sono.", "deliverable": "Um roteiro de três passos.",
            "criteria": [{"name": "Sono", "expected": "Explica a consolidação durante o sono.", "source": "S1"},
                         {"name": "Aplicação", "expected": "Aplica o conceito à rotina de estudo.", "source": "S1"}]}
ACTION = {"goal": "Aplicar o curso ao projeto de estudo.", "steps": [
    {"title": "Preparar revisão", "objective": "Organizar o estudo.", "deliverable": "Roteiro com horários.", "source": "S1", "minutes": 25, "after_days": 2}],
    "reviews": [{"focus": "Relembrar o papel do sono.", "after_days": 1}]}
GRADE = {"criteria": [{"id": 1, "score": .4, "feedback": "Inclua um horário concreto na rotina."},
                      {"id": 0, "score": 1, "feedback": "Você explicou a consolidação durante o sono."}], "next": "Acrescente o horário da revisão."}


class Applied(Base):
    def setUp(self):
        super().setUp()
        self.ctx = tools.Ctx()
        self.ctx.cite({"id": "memory", "source": "obsidian", "title": "Memória e sono", "chunks": [
            {"id": 1, "text": "O sono profundo consolida a memória. Uma revisão após estudar ajuda a lembrar.", "heading": "Sono"}]})
        self.provider = mock.Mock(name="local", **{"json.side_effect": lambda *a, **kw: copy.deepcopy(EXERCISE)})
        self.provider.name = "ollama"
        self.patch_media = mock.patch.object(db, "MEDIA", self.tmp / "media")
        self.patch_media.start()

    def tearDown(self):
        attachments.drop(["item-" + r["id"] for r in db.rows("SELECT id FROM items")])
        self.patch_media.stop()
        super().tearDown()

    def make(self, kind="exercise"):
        self.provider.json.side_effect = lambda *a, **kw: copy.deepcopy(EXERCISE if kind == "exercise" else ACTION)
        return learn.generate(kind, "memória e sono", self.provider, self.ctx, application="Meu curso de psicologia")

    def grade(self):
        self.provider.json.side_effect = lambda *a, **kw: copy.deepcopy(GRADE)

    def attach(self, content=b"O sono consolida a memoria."):
        r = attachments.receive(io.BytesIO(content).read, len(content), "Entrega.txt")
        for _ in range(100):
            rec = attachments.get(r["id"])
            if rec["status"] != "reading":
                self.assertEqual(rec["status"], "ready")
                return rec
            time.sleep(.01)
        self.fail("Leitura do anexo não terminou")

    def test_source_rubric_submission_persists_and_updates_mastery_once(self):
        it = self.make()
        self.grade()
        result = applied.submit(it["id"], "O sono consolida a memória.", [], self.provider)
        attempt = result["data"]["attempts"][0]
        self.assertEqual(attempt["score"], .7)
        self.assertEqual([r["name"] for r in attempt["criteria"]], ["Sono", "Aplicação"])
        self.assertIn("<entrega>", self.provider.json.call_args.args[1])
        self.assertEqual(mastery.listing()[0]["origin"], {"exercise": 1})
        db.close()
        self.assertEqual(learn.item(it["id"])["data"]["attempts"][0], attempt)
        self.assertIn("Próximo passo", api._item_markdown(result))
        self.assertEqual(data.export()["items"][0]["data"]["attempts"][0], attempt)

    def test_missing_sources_invalid_citations_and_missing_project_do_not_save(self):
        with self.assertRaises(AppError):
            learn.generate("exercise", "sono", self.provider, tools.Ctx())
        with self.assertRaises(AppError):
            learn.generate("action", "sono", self.provider, self.ctx)
        invalid = copy.deepcopy(EXERCISE)
        invalid["criteria"][0]["source"] = "S999"
        self.provider.json.side_effect = None
        self.provider.json.return_value = invalid
        with self.assertRaises(AppError):
            learn.generate("exercise", "sono", self.provider, self.ctx)
        self.assertEqual(learn.items(), [])

    def test_bad_grade_and_provider_failure_preserve_delivery_and_mastery(self):
        it = self.make()
        for rows in ([GRADE["criteria"][0]], [GRADE["criteria"][0]] * 2,
                     [{"id": 0, "score": float("nan"), "feedback": "x"}, GRADE["criteria"][0]],
                     [{"id": 0, "score": True, "feedback": "x"}, GRADE["criteria"][0]]):
            self.provider.json.side_effect = None
            self.provider.json.return_value = {"criteria": rows, "next": "Tente."}
            with self.assertRaises(AppError):
                applied.submit(it["id"], "Minha resposta", [], self.provider)
        self.provider.json.side_effect = AppError("IA indisponível")
        rec = self.attach()
        with self.assertRaises(AppError):
            applied.submit(it["id"], "", [rec["id"]], self.provider)
        self.assertEqual(attachments.get(rec["id"])["conversation_id"], "")
        self.assertEqual(learn.item(it["id"])["data"]["attempts"], [])
        self.assertEqual(mastery.listing(), [])
        attachments.remove(rec["id"])

    def test_attachment_survives_conversation_cleanup_then_dies_with_item(self):
        it = self.make()
        rec = self.attach()
        self.grade()
        result = applied.submit(it["id"], "", [rec["id"]], self.provider)
        path = attachments.folder(rec["id"]) / "arquivo"
        self.assertIn("memoria", result["data"]["attempts"][0]["submission"])
        db.close()
        chats.delete_all()
        self.assertTrue(path.exists())
        self.assertEqual(attachments.get(rec["id"])["conversation_id"], "item-" + it["id"])
        with self.assertRaises(AppError):
            applied.submit(it["id"], "tentar usar anexo de novo", [rec["id"]], self.provider)
        learn.delete_item(it["id"])
        self.assertFalse(path.exists())
        self.assertEqual(db.value("SELECT COUNT(*) FROM attachments"), 0)

    def test_saved_category_deletes_practice_files_but_not_original_sources(self):
        original = self.note("sono.md", "Minha fonte original")
        it = self.make()
        rec = self.attach()
        self.grade()
        applied.submit(it["id"], "", [rec["id"]], self.provider)
        self.assertEqual(data.delete("saved"), 1)
        self.assertFalse(attachments.folder(rec["id"]).exists())
        self.assertEqual(original.read_text("utf-8"), "Minha fonte original")

    def test_long_or_empty_submission_is_rejected_before_generation(self):
        it = self.make()
        self.provider.json.reset_mock()
        for text, ids in (("", []), ("x" * 12001, []), ("x", "not-a-list")):
            with self.assertRaises(AppError):
                applied.submit(it["id"], text, ids, self.provider)
        self.provider.json.assert_not_called()

    def test_deletion_while_grading_cannot_resurrect_item_or_mastery(self):
        it = self.make()
        def remove(*a, **kw):
            learn.delete_item(it["id"])
            return copy.deepcopy(GRADE)
        self.provider.json.side_effect = remove
        with self.assertRaises(AppError):
            applied.submit(it["id"], "Entrega", [], self.provider)
        self.assertEqual(learn.items(), [])
        self.assertEqual(mastery.listing(), [])

    def test_failed_commit_restores_staged_attachments_and_never_leaves_half_an_attempt(self):
        it = self.make()
        rec = self.attach()
        self.grade()
        with mock.patch.object(mastery, "record", side_effect=AppError("Falha ao gravar")):
            with self.assertRaises(AppError):
                applied.submit(it["id"], "", [rec["id"]], self.provider)
        self.assertEqual(attachments.get(rec["id"])["conversation_id"], "")
        self.assertEqual(learn.item(it["id"])["data"]["attempts"], [])
        self.assertEqual(db.value("SELECT COUNT(*) FROM attachments"), 0)
        result = applied.submit(it["id"], "", [rec["id"]], self.provider)
        self.assertEqual(len(result["data"]["attempts"]), 1)

    def test_attachment_claimed_while_grading_does_not_take_the_other_staged_file(self):
        it = self.make()
        a, b = self.attach(), self.attach()
        conv = chats.create()
        def claim_elsewhere(*args, **kw):
            attachments.claim([b["id"]], conv["id"], False)
            return copy.deepcopy(GRADE)
        self.provider.json.side_effect = claim_elsewhere
        with self.assertRaises(AppError):
            applied.submit(it["id"], "", [a["id"], b["id"]], self.provider)
        self.assertEqual(attachments.get(a["id"])["conversation_id"], "")
        self.assertEqual(attachments.get(b["id"])["conversation_id"], conv["id"])
        attachments.remove(a["id"])
        chats.delete([conv["id"]])

    def test_action_dates_progress_and_pomodoro_event_are_idempotent(self):
        it = self.make("action")
        self.assertEqual(it["data"]["steps"][0]["due"], (date.today() + timedelta(days=2)).isoformat())
        with mock.patch.object(applied.pomodoro, "view", return_value={"event": {"id": 4, "ended": "focus"}}):
            applied.action(it["id"], "focus", 0)
            self.assertEqual(applied.action(it["id"], "event")["data"]["focus_sessions"], 0)
        with mock.patch.object(applied.pomodoro, "view", return_value={"event": {"id": 5, "ended": "focus"}}):
            applied.action(it["id"], "event")
            self.assertEqual(applied.action(it["id"], "event")["data"]["focus_sessions"], 1)
        result = applied.action(it["id"], "step", 0, True)
        self.assertTrue(result["data"]["steps"][0]["done"])
        self.assertEqual(mastery.listing(), [])
        self.assertIn("[x]", api._item_markdown(result))
        with self.assertRaises(AppError):
            applied.action(it["id"], "step", -1, True)

    def test_plan_reviews_are_due_and_disappear_after_completion(self):
        it = self.make("action")
        it["data"]["reviews"][0]["due"] = date.today().isoformat()
        with db.tx() as c:
            c.execute("UPDATE items SET data = ? WHERE id = ?", (db.dumps(it["data"]), it["id"]))
        self.assertEqual(learn.due()["plans"][0]["id"], it["id"])
        applied.action(it["id"], "review", 0, True)
        self.assertEqual(learn.due()["plans"], [])

    def test_commands_and_intents_reach_shared_generation(self):
        modes = {r["mode"] for r in registry.menu() if "mode" in r}
        self.assertTrue({"exercise", "action"} <= modes)
        self.assertEqual(search.heuristic("Prática com correção de memória")["intent"], "exercise")
        self.assertEqual(search.heuristic("Plano de ação do curso de memória")["intent"], "action")
