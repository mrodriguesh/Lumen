"""“Minha compreensão”: a IA só trabalha depois que o estudante escreve o que entendeu (os 10 casos do pedido)."""
import http.client
import json
import threading
import time
import unittest
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, jobs, llm, server, sources, store, understanding
from tests.fake_notion import Fake
from tests.test_flow import SPEC, wait
from tests.test_llm import GOOD, NOTE

KEY = "yt:dQw4w9WgXcQ"
# Nota com um erro de conceito (a aula não diz que a fase clara faz glicose) e uma lacuna (a clorofila), escrita
# com espaços e linhas em branco: tudo tem de voltar exatamente assim.
WRONG = ("  Entendi que a fotossíntese acontece nas folhas e que a fase clara usa a luz para produzir a glicose.\n\n"
         "Depois a planta guarda essa glicose e solta oxigênio pelo ar, então no escuro ela morre na hora.  \n")
FOUND = {"acertos": ["Você lembrou que a fase clara depende de luz."],
         "parciais": ["Você citou o oxigênio, mas não disse de onde ele vem."],
         "lacunas": ["A clorofila, o pigmento verde que absorve a luz."],
         "confusoes": [{"trecho": "a fase clara usa a luz para produzir a glicose",
                        "correcao": "A aula diz que a fase clara depende de luz; a glicose não aparece nela."}],
         "complementos": ["O exemplo da planta no escuro mostra a dependência da luz."],
         "conexoes": ["Luz e fase clara: sem uma, não há a outra."],
         "perguntas": ["O que a aula diz que acontece com a planta no escuro?"]}


def chat(model, system, user, *a, **k):
    """IA simulada: a análise da compreensão ou o material da aula, conforme o pedido."""
    return json.dumps(FOUND if system.startswith("Você é um assistente de aprendizagem") else GOOD)


def text(blocks, kind):
    return ["".join(t["text"]["content"] for t in b[kind]["rich_text"]) for b in blocks if b["type"] == kind]


class Rule(unittest.TestCase):
    def test_note_must_be_real_writing(self):  # casos 3 e 9
        mash = "bcd fgh jkl mnp qrs tvw xzb cdf ghj klm npq rst vwx zbc dfg hjk lmn pqr stv wxz"
        for bad in ("", "   \n ", "ok, entendi tudo", "teste " * 40, mash):
            self.assertIsNotNone(understanding.problem(bad), bad[:20])
        self.assertIn("faltam", understanding.problem("A fotossíntese usa a luz do sol"))
        self.assertIsNone(understanding.problem(NOTE))
        self.assertIsNone(understanding.problem(WRONG))

    def test_ai_functions_refuse_without_a_note_even_when_called_directly(self):  # casos 1 e 9
        segs = [{"start": 0, "end": 30, "text": "Hoje vamos estudar fotossíntese."}]
        with mock.patch.object(llm, "_chat") as ai:
            for note in ("", "curta demais", "teste " * 30):
                with self.assertRaises(AppError):
                    llm.generate(segs, 30, "m", "pt", lambda: None, lambda *a: None, understanding=note)
                with self.assertRaises(AppError):
                    llm.analyze(segs, "m", "pt", note, lambda: None, lambda *a: None)
            with self.assertRaises(AppError):
                llm.generate(segs, 30, "m", "pt", lambda: None, lambda *a: None)  # sem a nota
        ai.assert_not_called()

    def test_analysis_is_checked_before_it_is_kept(self):
        with self.assertRaises(AppError):  # nada a dizer ao estudante
            llm.validate_analysis({k: [] for k in FOUND})
        out = llm.validate_analysis({**FOUND, "acertos": ["  ", 3, None, "ok"],
                                     "confusoes": [{"trecho": "", "correcao": "x"}, "solto", *FOUND["confusoes"]]})
        self.assertEqual(out["acertos"], ["3", "ok"])
        self.assertEqual(out["confusoes"], FOUND["confusoes"])


class Flow(unittest.TestCase):
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
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(sources, "youtube_meta", return_value={"title": "Fotossíntese", "author": "P"}),
                        mock.patch.object(llm, "_chat", side_effect=chat),
                        mock.patch("lumen.mindmap.render", return_value=None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def api(self, method, path, body=None, beacon=False):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
        try:
            if beacon:  # sendBeacon: texto puro, token na URL, sem o cabeçalho do token
                c.request(method, path + "?t=" + server.TOKEN, body=json.dumps(body),
                          headers={"Content-Type": "text/plain;charset=UTF-8"})
            else:
                c.request(method, path, body=None if body is None else json.dumps(body),
                          headers={"X-Lumen-Token": server.TOKEN, "Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        finally:
            c.close()

    def prepare(self, **extra):
        jobs.start("process", jobs.process, {**SPEC, "course_id": self.root, **extra})
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))

    def submit(self, note):
        status, out = self.api("POST", "/api/understanding/submit", {"key": KEY, "text": note})
        self.assertEqual(status, 200, out)
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))

    def publish(self, **extra):
        jobs.start("process", jobs.finish, {**SPEC, "course_id": self.root, **extra})
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        return j["result"]

    def subpages(self):
        return [p for p in self.fake.pages.values() if p["title"] == "Minha compreensão" and not p["in_trash"]]

    def test_nothing_is_generated_or_shown_before_the_note(self):  # casos 1 e 9
        self.prepare()
        self.assertEqual(understanding.get(KEY)["state"], "waiting_for_understanding")
        # a interface recebe que a aula está pronta, mas não a transcrição (seria cola)
        _, job = self.api("GET", "/api/job")
        self.assertTrue(job["result"]["review"])
        self.assertNotIn("Hoje vamos", json.dumps(job, ensure_ascii=False))
        self.assertNotIn("Hoje vamos", json.dumps(self.api("GET", "/api/state")[1], ensure_ascii=False))
        self.assertEqual(self.api("GET", f"/api/review?key={KEY}")[0], 400)
        self.assertEqual(self.api("GET", f"/api/screen?key={KEY}&id=0&t={server.TOKEN}")[0], 400)
        # nem enviar uma nota vazia ou de mentira, nem chamar a análise ou o Notion por fora da interface
        for fake_note in ("", "ok", "teste " * 30):
            self.assertEqual(self.api("POST", "/api/understanding/submit", {"key": KEY, "text": fake_note})[0], 400)
        jobs.start("analyze", jobs.analyze, KEY)
        self.assertIn("compreensão", wait()["error"]["message"])
        jobs.start("process", jobs.finish, {**SPEC, "course_id": self.root})
        self.assertIn("compreensão", wait()["error"]["message"])
        self.api("POST", "/api/understanding/draft", {"key": KEY, "text": NOTE})  # escrita, mas ainda não enviada
        jobs.start("process", jobs.finish, {**SPEC, "course_id": self.root})
        self.assertEqual(wait()["status"], "error")
        llm._chat.assert_not_called()
        self.assertEqual(self.fake.pages[self.root]["blocks"], [])
        self.assertEqual(len(self.fake.pages), 1)

    def test_draft_survives_closing_the_app(self):  # caso 2
        self.prepare()
        _, out = self.api("POST", "/api/understanding/draft", {"key": KEY, "text": "Primeira ideia", "at": 1000})
        self.assertIn("faltam", out["problem"])
        self.assertEqual(self.api("POST", "/api/understanding/draft", {"key": KEY, "text": NOTE, "at": 2000},
                                  beacon=True)[0], 200)  # a janela fechou: o resto foi por sendBeacon
        self.api("POST", "/api/understanding/draft", {"key": KEY, "text": "pedido atrasado", "at": 1500})  # ignorado
        on_disk = json.loads(understanding._path(KEY).read_text("utf-8"))  # “reabrir o Lumen”: só o disco
        self.assertEqual(on_disk["current_understanding"], NOTE)
        self.assertFalse(list(understanding._path(KEY).parent.glob("*.tmp")))  # gravação atômica, sem sobras
        view = self.api("GET", f"/api/understanding?key={KEY}")[1]
        self.assertEqual((view["text"], view["state"], view["problem"]), (NOTE, "understanding_written", None))  # caso 3
        self.assertNotIn("captions", view["spec"])  # nem a transcrição colada volta por aqui
        self.assertEqual([(p["key"], p["state"]) for p in self.api("GET", "/api/state")[1]["pending"]],
                         [(KEY, "understanding_written")])  # “Continuar aprendendo”

    def test_note_then_analysis_then_notion(self):  # casos 4, 5, 6, 7 e 8
        self.prepare()
        self.submit(WRONG)
        system, user = llm._chat.call_args[0][1:3]
        self.assertIn("assistente de aprendizagem", system)
        self.assertIn("Hoje vamos estudar fotossíntese.", user)  # caso 4: o conteúdo original…
        self.assertIn(WRONG, user)                               # …e a nota, como foi escrita
        rec = understanding.load(KEY)
        self.assertEqual((rec["original_understanding"], rec["current_understanding"]), (WRONG, WRONG))  # caso 5
        view = understanding.get(KEY)
        self.assertEqual(view["state"], "completed")
        self.assertEqual(view["analysis"]["confusoes"], FOUND["confusoes"])  # caso 7: o erro, à parte da nota
        self.assertEqual(view["analysis"]["lacunas"], FOUND["lacunas"])      # caso 8: o que faltou
        status, review = self.api("GET", f"/api/review?key={KEY}")  # a transcrição só agora
        self.assertEqual(status, 200)
        self.assertIn("Hoje vamos", review["segments"][0]["text"])

        result = self.publish()  # caso 6
        self.assertIn(WRONG, next(c.args[2] for c in llm._chat.call_args_list if "Transcrição da aula" in c.args[2]))
        [sub] = self.subpages()
        self.assertEqual(sub["parent"], self.root)  # dentro da página da aula
        self.assertIn(sub["id"].replace("-", ""), result["understanding_url"])
        kinds, heads = [b["type"] for b in sub["blocks"]], text(sub["blocks"], "heading_2")
        self.assertEqual(heads, ["✍️ Minha nota original", "✅ O que eu compreendi corretamente", "🌓 O que entendi em parte",
                                 "🧩 O que faltou", "⚠️ Possíveis confusões", "➕ Complementos", "🔗 Conexões",
                                 "❓ Perguntas para aprofundar"])
        self.assertEqual(text(sub["blocks"], "quote"), [WRONG])  # a nota, exatamente como foi escrita, primeiro
        self.assertLess(kinds.index("quote"), kinds.index("divider"))
        self.assertIn("análise da IA local", text(sub["blocks"], "callout")[0])  # o que é da IA vem rotulado
        self.assertIn("“a fase clara usa a luz para produzir a glicose”", text(sub["blocks"], "callout")[1])
        self.assertIn("subpágina “Minha compreensão”", json.dumps(self.fake.pages[self.root]["blocks"], ensure_ascii=False))
        self.assertEqual(understanding.get(KEY)["state"], "synced_to_notion")
        self.assertEqual(understanding.load(KEY)["original_understanding"], WRONG)  # caso 5, depois de tudo
        self.assertEqual(self.api("GET", "/api/state")[1]["pending"], [])

    def test_editing_after_the_analysis_keeps_the_original(self):  # caso 10
        self.prepare()
        self.submit(WRONG)
        edited = WRONG.strip() + " Revendo a aula: a glicose não aparece na fase clara."
        self.api("POST", "/api/understanding/draft", {"key": KEY, "text": edited, "at": time.time() * 1000 + 5000})
        rec = understanding.load(KEY)
        self.assertEqual((rec["original_understanding"], rec["current_understanding"]), (WRONG, edited))
        self.submit(edited)  # “Analisar de novo”: a nova versão é analisada, a original não muda
        rec = understanding.load(KEY)
        self.assertEqual((rec["original_understanding"], rec["analyzed_text"]), (WRONG, edited))
        self.publish()
        [sub] = self.subpages()
        self.assertEqual(text(sub["blocks"], "quote"), [WRONG, edited])
        self.assertIn("Minha versão atual (editada depois da análise)", text(sub["blocks"], "heading_3"))

    def test_studying_again_keeps_the_earlier_understanding(self):
        self.prepare()
        self.submit(WRONG)
        self.publish()
        self.prepare(mode="replace")  # estudou a mesma aula de novo
        view = understanding.get(KEY)
        self.assertEqual((view["state"], view["text"]), ("waiting_for_understanding", ""))
        self.submit(NOTE)
        self.publish(mode="replace")
        [sub] = self.subpages()  # a anterior saiu com a versão antiga do material…
        self.assertEqual(text(sub["blocks"], "quote")[0], NOTE)
        older = next(b for b in sub["blocks"] if b["type"] == "toggle")  # …mas a nota antiga veio junto
        self.assertEqual(text(older["toggle"]["children"], "quote"), [WRONG])

    def test_floating_and_side_editors_get_the_same_note(self):
        # a janela flutuante e a barra lateral são páginas do mesmo servidor, com o mesmo componente da nota
        for path in ("/note?key=" + KEY, "/understanding-editor.js", "/note.js", "/widget"):
            c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port)
            c.request("GET", path)
            body = c.getresponse().read().decode()
            c.close()
            self.assertNotIn("{{TOKEN}}", body)
            if path.startswith(("/note?", "/widget")):
                self.assertIn(server.TOKEN, body)
                self.assertIn("/understanding-editor.js", body)
        self.prepare()
        notes = lambda: [(n["key"], n["state"]) for n in self.api("GET", "/api/widget")[1]["notes"]]  # noqa: E731
        self.assertEqual(notes(), [(KEY, "waiting_for_understanding")])  # a barra lateral oferece a nota
        self.api("POST", "/api/understanding/draft", {"key": KEY, "text": NOTE})
        self.assertEqual(notes(), [(KEY, "understanding_written")])
        self.submit(NOTE)
        # analisada: a nota continua na barra (com o estado, para ela mostrar “Análise concluída”), mas a análise em si,
        # a transcrição e as telas nunca vão para lá
        self.assertEqual(notes(), [(KEY, "completed")])
        payload = json.dumps(self.api("GET", "/api/widget")[1], ensure_ascii=False)
        for secret in (FOUND["acertos"][0], FOUND["lacunas"][0], "clorofila"):
            self.assertNotIn(secret, payload)

    def test_failures_never_lose_the_note(self):
        self.prepare()
        with mock.patch.object(llm, "_chat", return_value='{"acertos": []}'):  # análise inútil, duas vezes
            status, _ = self.api("POST", "/api/understanding/submit", {"key": KEY, "text": WRONG})
            self.assertEqual(wait()["status"], "error")
        view = understanding.get(KEY)
        self.assertEqual((view["state"], view["original"], view["analysis"]), ("understanding_written", WRONG, None))
        self.submit(WRONG)
        route = self.fake.route

        def no_subpage(method, path, body):
            return (400, {"code": "validation_error"}) if (method, path) == ("POST", "/pages") else route(method, path, body)
        with mock.patch.object(self.fake, "route", side_effect=no_subpage):
            jobs.start("process", jobs.finish, {**SPEC, "course_id": self.root})
            self.assertEqual(wait()["status"], "error")
        self.assertEqual(self.fake.pages[self.root]["blocks"], [])  # o material da aula foi desfeito junto
        self.assertEqual(understanding.get(KEY)["state"], "completed")  # tudo guardado para tentar de novo
        self.publish()
        self.assertEqual(len(self.subpages()), 1)


if __name__ == "__main__":
    unittest.main()
