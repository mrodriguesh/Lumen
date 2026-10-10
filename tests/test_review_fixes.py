"""Problemas apontados na revisão do Codex (10/10/2026): cada teste falha se a correção for desfeita."""
import json
import os
import threading
import time
import unittest
from unittest import mock

from lumen import __main__ as app_main
from lumen import jobs, llm, server, sources, store
from tests.fake_notion import Fake
from tests.test_flow import CAPTIONS, SPEC, wait
from tests.test_llm import GOOD


def _texts(blocks):
    for b in blocks:
        body = b[b["type"]]
        yield "".join(rt["text"]["content"] for rt in body.get("rich_text", []))
        yield from _texts(body.get("children", []))


class Review(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(sources, "youtube_meta", return_value={"title": "Fotossíntese", "author": "P"}),
                        mock.patch.object(llm, "_chat", return_value=json.dumps(GOOD)),
                        mock.patch("lumen.mindmap.render", return_value=None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.fake.close()

    def process(self, spec):
        jobs.start("process", jobs.process, spec)
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        return j["result"]["segments"]

    def test_retry_reapplies_deletion_to_the_same_segments(self):
        segs = self.process(SPEC)
        self.assertTrue(segs[0]["text"].startswith("Hoje vamos"))
        spec = {**SPEC, "course_id": self.root, "include_transcript": True, "edits": {"0": ""}}  # apaga o 1º trecho
        self.fake.fail_append = True
        jobs.start("process", jobs.finish, spec)
        self.assertEqual(wait()["status"], "error")
        self.fake.fail_append = False
        jobs.start("process", jobs.finish, spec)  # “Tentar novamente”, mesmas edições
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        text = "\n".join(_texts(self.fake.pages[self.root]["blocks"]))
        self.assertNotIn("Hoje vamos", text)
        self.assertIn("A fase clara depende de luz.", text)  # antes da correção, este sumia na 2ª tentativa
        self.assertIn("planta no escuro", text)

    def test_new_captions_replace_cached_transcript(self):
        self.process(SPEC)
        segs = self.process({**SPEC, "captions": "0:00\nLegenda nova sobre respiração celular."})
        self.assertEqual([s["text"] for s in segs], ["Legenda nova sobre respiração celular."])
        segs = self.process(SPEC)  # e voltar à legenda anterior também vale
        self.assertTrue(segs[0]["text"].startswith("Hoje vamos"))
        self.assertIn("planta no escuro", CAPTIONS)


class Settings(unittest.TestCase):
    def test_slow_token_save_does_not_undo_other_settings(self):
        store.save_config(dict(store.DEFAULTS))

        class H:
            def __init__(self, body):
                self.body = body

            def _json(self):
                return self.body

            def _query(self):
                return {"view": "settings"}

        gate = threading.Event()

        def slow_check(tok):
            gate.wait(5)  # validação do token pela rede, demorada

        with mock.patch("lumen.notion.search_pages", side_effect=slow_check), mock.patch.object(store, "set_token"), \
                mock.patch.object(store, "get_token", return_value="x"):
            t = threading.Thread(target=server._settings, args=(H({"notion_token": "ntn_x", "keep_temp": True}),))
            t.start()
            time.sleep(0.1)
            server._settings(H({"quality": "rapido"}))  # outro pedido termina enquanto o token é validado
            gate.set()
            t.join(5)
        cfg = store.load_config()
        self.assertEqual((cfg["quality"], cfg["keep_temp"]), ("rapido", True))


class Lifetime(unittest.TestCase):
    def run_main(self, native):
        httpd = mock.Mock(server_port=1)
        ticks = iter(range(5))
        sleep = mock.Mock(side_effect=lambda s: next(ticks))  # StopIteration após 5 voltas = continuou vivo
        env = {"LUMEN_NO_WINDOW": "1"} if native else {"LUMEN_NO_WINDOW": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(server, "serve", return_value=httpd), \
                mock.patch.object(app_main, "_edge", return_value=None), mock.patch("webbrowser.open"), \
                mock.patch("threading.Thread"), mock.patch("time.sleep", sleep), \
                mock.patch("time.monotonic", return_value=10_000.0), mock.patch.object(server, "last_seen", 0), \
                mock.patch.object(server, "bye_at", 0), mock.patch("builtins.print"), \
                mock.patch("logging.basicConfig"):
            try:
                app_main.main()
            except (StopIteration, RuntimeError):
                pass
        return httpd.shutdown.called

    def test_native_window_is_not_shut_down_when_idle(self):
        self.assertFalse(self.run_main(native=True))
        self.assertTrue(self.run_main(native=False))  # navegador comum: continua encerrando após 15 min


if __name__ == "__main__":
    unittest.main()
