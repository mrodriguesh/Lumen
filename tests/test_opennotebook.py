"""Open Notebook: conexão, caderno de destino e envio único da transcrição, contra um servidor falso (nada aqui fala com um
Open Notebook de verdade; a conferência com a API instalada é manual e está no README)."""
import json
import threading
import unittest
from datetime import datetime, timezone
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from pathlib import Path

import keyring

import tests  # noqa: F401  (isola LUMEN_DATA e o cofre antes do lumen)
from lumen import AppError, jobs, opennotebook as on, store


class Fake(ThreadingHTTPServer):
    """O bastante da API 1.15.1: cadernos, fontes de texto assíncronas, status e reprocessamento."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.password, self.embedding, self.drop_after_create, self.db = None, None, False, "online"
        self.notebooks, self.sources, self.posts, self.retries = [], {}, [], []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self, method):
        s, path = self.server, self.path.split("?")[0]
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path != "/api/config" and s.password and self.headers.get("Authorization") != "Bearer " + s.password:
            return self._reply(401, {"detail": "Missing authorization header"})
        if (method, path) == ("GET", "/api/config"):
            return self._reply(200, {"version": "1.15.1", "dbStatus": s.db})
        if (method, path) == ("GET", "/api/notebooks"):
            return self._reply(200, s.notebooks)
        if (method, path) == ("POST", "/api/notebooks"):
            book = {"id": f"notebook:n{len(s.notebooks)}", "archived": False, "source_count": 0, **json.loads(raw)}
            s.notebooks.append(book)
            return self._reply(200, book)
        if (method, path) == ("GET", "/api/models/defaults"):
            return self._reply(200, {"default_embedding_model": s.embedding})
        if (method, path) == ("GET", "/api/sources"):
            return self._reply(200, [{k: v for k, v in x.items() if k != "full_text"} for x in s.sources.values()])
        if (method, path) == ("POST", "/api/sources"):
            msg = message_from_bytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + raw)
            form = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True).decode() for p in msg.get_payload()}
            s.posts.append(form)
            src = {"id": f"source:s{len(s.posts)}", "title": form["title"], "full_text": None, "status": "new",
                   "created": datetime.now(timezone.utc).isoformat(), "command_id": "command:c1"}
            s.sources[src["id"]] = src
            if s.drop_after_create:  # a fonte foi criada, mas a resposta nunca chega
                self.close_connection = True
                return None
            return self._reply(200, src)
        sid = path.split("/")[3] if path.startswith("/api/sources/") else ""
        sid = sid.replace("%3A", ":")
        if sid not in s.sources:
            return self._reply(404, {"detail": "Source not found"})
        if method == "GET" and path.endswith("/status"):
            st = s.sources[sid]["status"]
            return self._reply(200, {"status": st, "message": "x", "processing_info": {"error": "sem modelo"} if st == "failed" else None})
        if method == "POST" and path.endswith("/retry"):
            s.retries.append(sid)
            s.sources[sid]["status"] = "queued"
            return self._reply(200, s.sources[sid])
        return self._reply(200, s.sources[sid])

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


class OpenNotebook(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)  # as limpezas rodam de trás para a frente: para de servir e só então fecha
        store.save_config(dict(store.DEFAULTS))
        on._forget_password()
        self.key = f"aula-{self.id()}"
        store.remember(self.key, {"title": "Aula de teste", "classification": {"type": "course", "course": "Física", "module": "Ondas"}})
        work = jobs.work_dir(self.key)
        work.mkdir(parents=True, exist_ok=True)
        jobs._save(work / "transcript.json", {"language": "pt", "segments": [{"start": 0, "end": 4, "text": "Uma onda transporta energia."}]})

    def connect(self, **kw):
        view = on.connect({"url": self.fake.url, **kw})
        return on.choose({"create": True}) if view["state"] == "connected" else view

    def entry(self):
        return store.history()[self.key]["opennotebook"]

    def test_states_and_password_stays_in_the_vault(self):
        self.assertEqual(on.view()["state"], "off")
        self.fake.password = "segredo"
        self.assertEqual(on.connect({"url": self.fake.url})["state"], "password")
        with self.assertRaises(AppError):
            on.connect({"url": self.fake.url, "password": "errada"})
        self.assertIsNone(keyring.get_password(store.APP, "opennotebook"))  # senha recusada não é guardada
        view = on.connect({"url": self.fake.url, "password": "segredo"})
        self.assertEqual((view["state"], view["version"], view["has_password"]), ("connected", "1.15.1", True))
        self.assertNotIn("segredo", json.dumps(view) + (store.DATA / "config.json").read_text("utf-8"))
        self.assertFalse(on.connect({"url": "http://127.0.0.1:9"})["has_password"])  # endereço novo não herda a senha
        self.assertEqual(on.view()["state"], "unavailable")
        self.assertEqual(on.disconnect()["state"], "off")
        for bad in ("ftp://x", "http://user:pw@host", "javascript:alert(1)", "http://host/?a=1"):
            with self.assertRaises(AppError):
                on.address(bad)

    def test_lumen_notebook_is_created_once_and_others_are_untouched(self):
        self.fake.notebooks.append({"id": "notebook:meu", "name": "Meu caderno", "archived": False, "source_count": 3})
        before = dict(self.fake.notebooks[0])
        self.connect()
        view = on.choose({"create": True})
        self.assertEqual([n["name"] for n in self.fake.notebooks], ["Meu caderno", on.NOTEBOOK])
        self.assertEqual(self.fake.notebooks[0], before)
        self.assertEqual(view["opennotebook_notebook_name"], on.NOTEBOOK)
        self.assertEqual(on.choose({"id": "notebook:meu"})["opennotebook_notebook"], "notebook:meu")
        with self.assertRaises(AppError):
            on.choose({"id": "notebook:sumiu"})

    def test_ui_probe_is_a_warning_not_a_lock(self):
        """API pronta + endereço da interface válido, mas a sonda não reconhece a resposta: a visão diz o porquê (ui_state) em
        vez de só “não”, e endereços inseguros continuam recusados."""
        from lumen import onlocal
        view = on.connect({"url": self.fake.url, "ui": self.fake.url})
        self.assertEqual(view["state"], "connected")
        self.assertEqual((view["ui_state"], view["ui_ok"]), ("other", False))  # escuta, mas /config não é o do Open Notebook
        with mock.patch.object(onlocal, "_json", return_value={"apiUrl": self.fake.url}):  # a rota /config devolvendo o esperado
            self.assertEqual(on.view()["ui_state"], "ok")
        down = on.connect({"url": self.fake.url, "ui": "http://127.0.0.1:9"})
        self.assertEqual((down["ui_state"], down["ui_ok"]), ("down", False))
        self.assertEqual(down["state"], "connected")  # a API pronta não depende da interface
        for bad in ("ftp://x", "javascript:alert(1)", "http://u:p@127.0.0.1:3000", "http://127.0.0.1:3000/?a=1"):
            with self.assertRaises(AppError):
                on.connect({"url": self.fake.url, "ui": bad})

    def test_wrong_server_on_ui_port_is_not_the_notebook_page(self):
        """Regressão do 404: outro Next.js na porta da interface (HyperbookLM em :3000) responde 404 em /config e em
        /notebooks/<id>; só o que devolve apiUrl é a interface, e o botão só abre nesse caso."""
        import http.server
        import threading
        from lumen import onlocal

        def serve(config):
            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    ok = config is not None and self.path == "/config"
                    body = (config or b"404").decode() if ok else "404"
                    self.send_response(200 if ok else 404)
                    self.end_headers()
                    self.wfile.write(body.encode())

                def log_message(self, *a):
                    pass
            srv = http.server.HTTPServer(("127.0.0.1", 0), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            return f"http://127.0.0.1:{srv.server_port}"

        self.assertEqual(onlocal.ui_state(serve(None)), "other")  # servidor errado: 404
        api = "http://127.0.0.1:5055"
        right = serve(json.dumps({"apiUrl": api}).encode())
        self.assertEqual(onlocal.ui_state(right, api), "ok")
        self.assertEqual(onlocal.ui_state(serve(b'{"apiUrl": ""}'), api), "other")  # apiUrl vazio não prova nada
        self.assertEqual(onlocal.ui_state(serve(b'{"apiUrl": "http://127.0.0.1:9999"}'), api), "other")  # outra API
        self.assertEqual(onlocal.ui_state(serve(b'{"apiUrl": "http://localhost:5055/"}'), api), "ok")  # localhost = 127.0.0.1
        self.assertEqual(on.notebook_url({"opennotebook_ui": right}, "notebook:abc"), f"{right}/notebooks/notebook%3Aabc")
        js = (Path(__file__).resolve().parents[1] / "lumen" / "web" / "opennotebook.js").read_text("utf-8")
        self.assertIn('if (v.ui_state === "other") return toast(', js)  # servidor errado: avisa e não navega

    def test_view_finds_the_real_ui_on_another_port_and_saves_it(self):
        """Outro Next.js em :3000 (HyperbookLM) e o Open Notebook numa porta vizinha: o endereço real é descoberto, conferido
        pelo apiUrl e guardado; sem nenhuma interface válida, nada é marcado como válido nem aberto."""
        import http.server
        import threading
        from lumen import onlocal

        def serve(config):
            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    ok = config is not None and self.path == "/config"
                    self.send_response(200 if ok else 404)
                    self.end_headers()
                    self.wfile.write((config or "404").encode())

                def log_message(self, *a):
                    pass
            srv = http.server.HTTPServer(("127.0.0.1", 0), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            return srv.server_port

        other = serve(None)
        good = serve(json.dumps({"apiUrl": self.fake.url}))
        url = lambda p: f"http://127.0.0.1:{p}"  # noqa: E731
        self.connect()
        on.connect({"url": self.fake.url, "ui": url(other)})
        with mock.patch.object(onlocal, "UI_PORTS", (other,)):
            view = on.view()
        self.assertEqual((view["ui_state"], view["ui_ok"]), ("other", False))  # nenhuma interface válida: nada é aberto
        self.assertEqual(store.load_config()["opennotebook_ui"], url(other))
        with mock.patch.object(onlocal, "UI_PORTS", (other, good)):
            view = on.view()
        self.assertEqual((view["ui_state"], view["ui_ok"], view["opennotebook_ui"]), ("ok", True, url(good)))
        self.assertTrue(view["open_url"].startswith(url(good)))
        self.assertEqual(store.load_config()["opennotebook_ui"], url(good))

    def test_sends_text_once(self):
        with self.assertRaises(AppError):
            on.send(self.key)  # desconectado: nada sai
        self.connect()
        self.assertEqual(on.send(self.key)["state"], "queued")
        form = self.fake.posts[0]
        self.assertEqual((form["type"], form["title"], form["embed"], form["async_processing"]), ("text", "Aula de teste", "false", "true"))
        self.assertEqual(json.loads(form["notebooks"]), ["notebook:n0"])
        for part in ("Uma onda transporta energia.", "Física", "Ondas", "Idioma: pt", "[00:00]"):
            self.assertIn(part, form["content"])
        self.assertNotIn("file", form)  # nem áudio nem vídeo
        on.send(self.key)
        self.assertEqual(len(self.fake.posts), 1)  # repetir o clique não cria outra fonte
        self.fake.sources["source:s1"]["status"] = "running"
        self.assertEqual(on.status(self.key, True)["state"], "processing")
        self.fake.sources["source:s1"]["status"] = "completed"
        self.assertEqual(on.status(self.key, True)["state"], "completed")
        self.fake.embedding = "model:e1"
        del self.fake.sources["source:s1"]  # apagada lá: aí sim vai de novo, e indexada porque agora há modelo
        self.assertEqual(on.send(self.key)["state"], "queued")
        self.assertEqual((len(self.fake.posts), self.fake.posts[1]["embed"]), (2, "true"))

    def test_unanswered_send_is_verified_not_repeated(self):
        self.connect()
        self.fake.drop_after_create = True
        with self.assertRaises(on.Unavailable):
            on.send(self.key)
        self.assertEqual((self.entry()["state"], self.entry()["source"]), ("unconfirmed", None))
        self.fake.drop_after_create = False
        self.assertEqual(on.send(self.key)["state"], "queued")
        self.assertEqual((len(self.fake.posts), self.entry()["source"]), (1, "source:s1"))  # achou a que já existia

    def test_refused_connection_fails_and_remote_failure_retries_in_place(self):
        self.connect()
        cfg = store.load_config()
        store.save_config({**cfg, "opennotebook_url": "http://127.0.0.1:9"})
        self.assertEqual(on.status(self.key, True)["state"], "none")
        with self.assertRaises(on.Unavailable):
            on.send(self.key)
        store.save_config(cfg)
        self.assertEqual(on.send(self.key)["state"], "queued")
        self.fake.sources["source:s1"]["status"] = "failed"
        self.assertEqual((on.status(self.key, True)["state"], self.entry()["error"]), ("failed", "sem modelo"))
        self.assertEqual(on.send(self.key)["state"], "queued")
        self.assertEqual((self.fake.retries, len(self.fake.posts)), (["source:s1"], 1))
        store.save_config({**cfg, "opennotebook_url": "http://127.0.0.1:9"})
        offline = on.status(self.key, True)  # fora do ar: o último estado e o aviso, sem erro
        self.assertEqual(offline["state"], "queued")
        self.assertIn("não respondeu", offline["offline"])

    def test_auto_send_is_off_by_default_and_never_raises(self):
        self.connect()
        with mock.patch.object(on.threading, "Thread") as thread:
            on.auto(self.key)
            thread.assert_not_called()
            store.save_config({**store.load_config(), "opennotebook_auto": True, "opennotebook_url": "http://127.0.0.1:9"})
            on.auto(self.key)
        thread.call_args.kwargs["target"]()  # com o serviço fora do ar: só registra
        self.assertEqual(self.fake.posts, [])
        self.assertFalse(on.has_transcript("outra-aula"))
        with self.assertRaises(AppError):
            on.send("outra-aula")


if __name__ == "__main__":
    unittest.main()
