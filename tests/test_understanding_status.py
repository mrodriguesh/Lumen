"""“Minha compreensão”: uma regra de prontidão (o que bloqueia “Processar” e por quê), versões e a trava da análise."""
import http.client
import json
import threading
import time
import unittest
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen)
from lumen import AppError, jobs, record, server, store, understanding
from tests.test_llm import NOTE

KEY = "aula-status"
IDLE = {"recording": False, "job": {"running": False}}


def ctx(recording=False, job=None):
    return {"recording": recording, "job": {"running": bool(job), **(job or {})}}


class Readiness(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        understanding.end_analysis()
        understanding.start(KEY, "Aula", "Gravação", {"kind": "recording"})

    def phase(self, c=IDLE):
        return understanding.readiness(understanding.load(KEY), c)

    def test_preparing_then_failed(self):  # teste 2 do status: “Preparando conteúdo…”
        r = self.phase(ctx(job={"kind": "process", "key": KEY, "detail": "Transcrevendo"}))
        self.assertEqual((r["phase"], r["blocked"], r["tone"]), ("preparing", True, "busy"))
        self.assertIn("Preparando", r["label"])
        r = self.phase()  # nenhuma tarefa mexe nesta aula e ela não ficou pronta
        self.assertEqual((r["phase"], r["blocked"]), ("prep_failed", True))
        r = self.phase(ctx(job={"kind": "process", "key": "outra-aula"}))  # a preparação em andamento é de outra aula
        self.assertEqual(r["phase"], "prep_failed")

    def test_recording_blocks_and_says_why(self):  # teste 1
        understanding.prepared(KEY)
        r = self.phase(ctx(recording=True))
        self.assertEqual((r["phase"], r["blocked"]), ("recording", True))
        self.assertIn("gravação", r["label"])

    def test_other_job_blocks(self):
        understanding.prepared(KEY)
        r = self.phase(ctx(job={"kind": "process", "key": "outra", "detail": "Escrevendo a página"}))
        self.assertEqual((r["phase"], r["detail"]), ("busy", "Escrevendo a página"))

    def test_empty_short_and_ready(self):  # testes 3 e 5
        understanding.prepared(KEY)
        r = self.phase()
        self.assertEqual((r["phase"], r["blocked"], r["label"]), ("writing", True, "Escreva sua compreensão para continuar"))
        understanding.save_draft(KEY, "só um pouco")
        r = self.phase()
        self.assertTrue(r["blocked"])
        self.assertIn("faltam", r["label"])
        understanding.save_draft(KEY, NOTE)
        r = self.phase()
        self.assertEqual((r["phase"], r["blocked"], r["label"]), ("ready", False, "Pronto para analisar"))

    def test_processing_then_completed_then_interrupted(self):  # testes 6 e 7 e erro
        understanding.prepared(KEY)
        understanding.save_draft(KEY, NOTE)
        understanding.submit(KEY, NOTE)
        understanding.begin_analysis(KEY)
        r = self.phase(ctx(job={"kind": "analyze", "key": KEY, "detail": "Lendo a aula por partes (1 de 4)"}))
        self.assertEqual((r["phase"], r["detail"]), ("processing", "Lendo a aula por partes (1 de 4)"))
        understanding.end_analysis()
        # a análise não terminou (erro, cancelada ou o app fechou): fica recuperável, com a nota intacta
        r = self.phase()
        self.assertEqual((r["phase"], r["blocked"], r["tone"]), ("interrupted", False, "error"))
        self.assertEqual(understanding.load(KEY)["current_understanding"], NOTE)
        understanding.save_analysis(KEY, {"acertos": ["x"]}, NOTE, "m")
        self.assertEqual(self.phase()["phase"], "completed")
        understanding.synced(KEY, {"url": "u"})
        self.assertEqual(self.phase()["phase"], "synced")

    def test_view_carries_ready_and_revision(self):
        understanding.prepared(KEY)
        v = understanding.save_draft(KEY, NOTE)
        self.assertEqual(v["ready"]["phase"], "ready")
        self.assertGreater(v["rev"], 0)
        self.assertTrue(any(n["ready"]["phase"] == "ready" for n in understanding.pending()))


class Versions(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        understanding.end_analysis()
        understanding.start(KEY, "Aula", "Gravação", {"kind": "recording"})
        understanding.prepared(KEY)

    def test_late_autosave_never_overwrites_a_newer_version(self):  # teste 8 da sincronização
        t = int(time.time() * 1000)
        v15 = understanding.save_draft(KEY, "versão 15 escrita na janela principal", t + 15)
        late = understanding.save_draft(KEY, "versão 14 atrasada da janela flutuante", t + 14)
        self.assertTrue(late["stale"])
        self.assertEqual(late["text"], "versão 15 escrita na janela principal")  # quem pediu recebe a mais nova
        self.assertEqual(understanding.load(KEY)["current_understanding"], "versão 15 escrita na janela principal")
        self.assertEqual(late["rev"], v15["rev"])  # o pedido atrasado não cria revisão
        newer = understanding.save_draft(KEY, "versão 16", t + 16)
        self.assertEqual((newer["stale"], newer["rev"]), (False, v15["rev"] + 1))

    def test_submit_refuses_an_older_version_than_the_server_has(self):  # teste 20
        t = int(time.time() * 1000)
        understanding.save_draft(KEY, NOTE, t + 1000)
        with self.assertRaises(AppError) as e:
            understanding.submit(KEY, NOTE, at=t)
        self.assertIn("outra janela", str(e.exception))
        self.assertIsNone(understanding.load(KEY).get("processing_since"))  # nada começou
        understanding.submit(KEY, NOTE, at=t + 1000)
        rec = understanding.load(KEY)
        self.assertEqual(rec["submitted_rev"], rec["rev"])  # a análise usa exatamente esta revisão
        self.assertEqual(rec["original_understanding"], NOTE)

    def test_analysis_records_the_revision_it_read(self):  # teste 21
        understanding.submit(KEY, NOTE)
        rev = understanding.load(KEY)["submitted_rev"]
        understanding.begin_analysis(KEY)
        with self.assertRaises(AppError):  # editar durante a análise não muda o que está sendo lido
            understanding.save_draft(KEY, NOTE + " edição no meio da análise")
        understanding.end_analysis()
        understanding.save_analysis(KEY, {"acertos": ["x"]}, NOTE, "m")
        rec = understanding.load(KEY)
        self.assertEqual((rec["analyzed_rev"], rec["current_understanding"], rec["analyzed_text"]), (rev, NOTE, NOTE))
        understanding.save_draft(KEY, NOTE + " depois da análise")  # depois dela a edição vale (e dá para analisar de novo)
        self.assertGreater(understanding.load(KEY)["rev"], rec["analyzed_rev"])

    def test_two_lessons_keep_their_own_notes(self):  # teste 9
        understanding.start("aula-b", "Outra", "Gravação", {"kind": "recording"})
        understanding.prepared("aula-b")
        understanding.save_draft(KEY, "texto da aula A")
        understanding.save_draft("aula-b", "texto da aula B")
        understanding.save_draft(KEY, "texto da aula A, de novo")
        self.assertEqual(understanding.get("aula-b")["text"], "texto da aula B")
        self.assertEqual(understanding.get(KEY)["text"], "texto da aula A, de novo")


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve()
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        store.clear_local_data()
        understanding.end_analysis()
        understanding.start(KEY, "Aula", "Gravação", {"kind": "recording"})
        understanding.prepared(KEY)
        understanding.save_draft(KEY, NOTE)

    def post(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        try:
            c.request("POST", path, body=json.dumps(body), headers={"X-Lumen-Token": server.TOKEN, "Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        finally:
            c.close()

    def test_submit_refused_while_recording_with_the_reason(self):  # teste 1
        with mock.patch.object(record, "active", return_value=True), mock.patch.object(jobs, "start") as start:
            status, out = self.post("/api/understanding/submit", {"key": KEY, "text": NOTE})
        self.assertEqual(status, 400)
        self.assertIn("gravação", out["error"]["message"])
        start.assert_not_called()
        self.assertEqual(understanding.load(KEY)["current_understanding"], NOTE)  # a nota continua guardada
        self.assertIsNone(understanding.load(KEY).get("original_understanding"))

    def test_submit_refused_while_the_lesson_is_not_prepared(self):  # teste 2
        understanding.start("nova", "Nova", "Gravação", {"kind": "recording"})
        with mock.patch.object(jobs, "running_info", return_value={"running": True, "kind": "process", "key": "nova"}):
            status, out = self.post("/api/understanding/submit", {"key": "nova", "text": NOTE})
        self.assertEqual(status, 400)
        self.assertIn("Preparando", out["error"]["message"])

    def test_job_that_fails_to_start_does_not_leave_the_note_locked(self):
        with mock.patch.object(jobs, "start", side_effect=AppError("Já existe uma tarefa em andamento.", "")):
            status, _ = self.post("/api/understanding/submit", {"key": KEY, "text": NOTE})
        self.assertEqual(status, 400)
        self.assertIsNone(understanding.analyzing)
        understanding.save_draft(KEY, NOTE + " ainda dá para editar")  # sem AppError

    def test_note_is_locked_the_moment_the_request_is_accepted(self):  # concorrência: digitar logo após clicar
        with mock.patch.object(jobs, "start"):
            status, _ = self.post("/api/understanding/submit", {"key": KEY, "text": NOTE})
        self.assertEqual(status, 200)
        self.assertEqual(understanding.analyzing, KEY)  # antes mesmo de o job existir
        status, out = self.post("/api/understanding/draft", {"key": KEY, "text": NOTE + " mais", "at": int(time.time() * 1000)})
        self.assertEqual(status, 400)
        understanding.end_analysis()

    def test_analyze_releases_the_lock_on_any_failure(self):
        understanding.submit(KEY, NOTE)
        with self.assertRaises(AppError):  # sem transcrição no disco
            jobs.analyze(KEY)
        self.assertIsNone(understanding.analyzing)
        self.assertEqual(understanding.readiness(understanding.load(KEY), IDLE)["phase"], "interrupted")

    def test_widget_lists_the_note_with_its_status_through_analysis(self):  # a barra não perde a nota ao analisar
        understanding.submit(KEY, NOTE)
        understanding.begin_analysis(KEY)
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        c.request("GET", "/api/widget", headers={"X-Lumen-Token": server.TOKEN})
        notes = json.loads(c.getresponse().read())["notes"]
        c.close()
        mine = [n for n in notes if n["key"] == KEY]
        self.assertEqual(mine[0]["ready"]["phase"], "processing")
        understanding.end_analysis()


if __name__ == "__main__":
    unittest.main()
