"""HyperbookLM: conexão, pareamento e envio único da transcrição, contra uma ponte falsa com o mesmo contrato da de verdade
(app/api/lumen, no repositório do HyperbookLM). Nada aqui fala com um HyperbookLM real nem com serviços de IA."""
import hashlib
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import keyring

import tests  # noqa: F401  (isola LUMEN_DATA e o cofre antes do lumen)
from lumen import AppError, hyperbooklm as hb, jobs, store


class Fake(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.token, self.app, self.delay, self.limit = "", "hyperbooklm", 0, 50
        self.sources, self.posts = [], []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def handle_error(self, *a):  # o Lúmen desistiu de esperar (teste do tempo esgotado): sem rastro no console
        pass

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
        auth = self.headers.get("Authorization")
        about = {"app": s.app, "bridge": 1, "paired": bool(s.token)}
        if auth is None and (method, path) == ("GET", "/api/lumen"):
            return self._reply(200, about)
        if not s.token:
            return self._reply(503, {"error": "bridge_not_paired"})
        if auth != "Bearer " + s.token:
            return self._reply(401, {"error": "unauthorized"})
        if (method, path) == ("GET", "/api/lumen"):
            return self._reply(200, {**about, "features": {"text": True, "slides": False}, "sources": len(s.sources)})
        if (method, path) == ("GET", "/api/lumen/sources"):
            return self._reply(200, {"sources": [{"id": x["id"], "title": x["title"]} for x in s.sources]})
        if (method, path) == ("POST", "/api/lumen/sources"):
            body = json.loads(raw)
            s.posts.append(body)
            sid = "lumen-" + hashlib.sha256(f"{body['title']}\n{body['text']}".encode()).hexdigest()[:32]
            dup = any(x["id"] == sid for x in s.sources)
            if not dup and len(s.sources) >= s.limit:
                return self._reply(409, {"error": "source_limit"})
            if not dup:
                s.sources.append({"id": sid, **body})
            time.sleep(s.delay)  # guardou, mas a resposta demora mais do que o Lúmen espera
            return self._reply(200 if dup else 201, {"id": sid, "duplicate": dup})
        return self._reply(404, {"error": "not_found"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


class HyperbookLM(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        store.save_config(dict(store.DEFAULTS))
        hb._forget_token()
        self.ports = hb.PORTS
        hb.PORTS = ()  # nenhum teste sonda as portas de verdade deste PC
        self.addCleanup(setattr, hb, "PORTS", self.ports)
        self.key = f"aula-{self.id()}"
        store.remember(self.key, {"title": "Aula de teste", "understanding": "nota particular", "source_path": "C:/aulas/a.mp4"})
        work = jobs.work_dir(self.key)
        work.mkdir(parents=True, exist_ok=True)
        jobs._save(work / "transcript.json", {"language": "pt", "segments": [{"start": 0, "end": 4, "text": "Uma onda transporta energia."}]})

    def pair(self):
        """Conecta e pareia: o código gerado pelo Lúmen passa a ser o da ponte."""
        hb.connect({"url": self.fake.url})
        self.fake.token = hb.pair()["line"].split("=", 1)[1]
        return hb.view()

    def entry(self):
        return store.history()[self.key]["hyperbooklm"]

    def test_connection_states_and_the_code_stays_in_the_vault(self):
        self.assertEqual(hb.view()["state"], "off")
        self.assertEqual(hb.connect({"url": "http://127.0.0.1:9"})["state"], "unavailable")  # ninguém na porta
        self.assertEqual(hb.connect({"url": self.fake.url})["state"], "pairing")  # servidor de pé, sem pareamento
        paired = hb.pair()
        token = paired["line"].split("=", 1)[1]
        self.assertTrue(paired["line"].startswith("LUMEN_BRIDGE_TOKEN=") and len(token) >= 32)
        self.assertEqual((paired["state"], paired["has_token"]), ("pairing", True))  # a ponte ainda não tem o código
        self.assertEqual(keyring.get_password(store.APP, "hyperbooklm"), token)
        self.fake.token = token
        view = hb.view()
        self.assertEqual((view["state"], view["features"], view["sources"]), ("connected", {"text": True, "slides": False}, 0))
        self.assertNotIn(token, json.dumps(view) + (store.DATA / "config.json").read_text("utf-8"))
        self.fake.token = "outro-codigo-qualquer-com-mais-de-32-caracteres"
        self.assertEqual(hb.view()["state"], "unauthorized")
        self.fake.app = "outra-coisa"
        hb._forget_token()
        self.assertEqual(hb.view()["state"], "notfound")
        self.assertEqual(hb.disconnect()["state"], "off")
        self.assertIsNone(keyring.get_password(store.APP, "hyperbooklm"))

    def test_only_addresses_of_this_pc_are_accepted(self):
        for bad in ("http://192.168.0.10:3000", "https://127.0.0.1:3000", "http://exemplo.com:3000", "http://user:pw@127.0.0.1:3000",
                    "http://127.0.0.1:3000/x", "http://127.0.0.1:3000/?a=1", "http://127.0.0.1", "javascript:alert(1)"):
            with self.assertRaises(AppError, msg=bad):
                hb.address(bad)
        self.assertEqual(hb.address(" http://localhost:3001/ "), "http://localhost:3001")

    def test_detects_the_port_when_the_address_is_stale(self):
        hb.PORTS = (9, self.fake.server_port)
        view = hb.connect({"url": "http://127.0.0.1:9"})
        self.assertEqual((view["detected"], view["hyperbooklm_url"], view["state"]), (True, self.fake.url, "pairing"))
        self.assertEqual(store.load_config()["hyperbooklm_url"], self.fake.url)

    def test_sends_only_title_and_transcript_once(self):
        self.pair()
        first = hb.send(self.key)
        self.assertEqual((first["state"], first["duplicate"]), ("sent", False))
        self.assertEqual(list(self.fake.posts[0]), ["title", "text"])
        self.assertEqual(self.fake.posts[0]["title"], "Aula de teste")
        self.assertIn("Uma onda transporta energia.", self.fake.posts[0]["text"])
        self.assertNotIn("nota particular", json.dumps(self.fake.posts))
        self.assertNotIn("a.mp4", json.dumps(self.fake.posts))
        again = hb.send(self.key)  # repetir o clique não reenvia nem duplica
        self.assertEqual((again["state"], again["duplicate"], len(self.fake.posts), len(self.fake.sources)), ("sent", True, 1, 1))
        self.fake.sources.clear()  # removida no HyperbookLM: o Lúmen percebe e deixa enviar de novo
        self.assertEqual(hb.status(self.key, check=True)["state"], "missing")
        self.assertEqual((hb.send(self.key)["state"], len(self.fake.sources)), ("sent", 1))

    def test_timeout_is_unconfirmed_and_the_retry_does_not_duplicate(self):
        self.pair()
        self.fake.delay = 1.5
        real = hb._call
        hb._call = lambda *a, **k: real(*a, **{**k, "timeout": 0.5})
        self.addCleanup(setattr, hb, "_call", real)
        with self.assertRaises(AppError):
            hb.send(self.key)
        self.assertEqual(self.entry()["state"], "unconfirmed")
        self.assertTrue(self.entry()["error"])
        hb._call, self.fake.delay = real, 0
        time.sleep(1.2)  # o pedido lento termina de ser atendido
        retry = hb.send(self.key)
        self.assertEqual((retry["state"], retry["duplicate"], len(self.fake.sources)), ("sent", True, 1))

    def test_refusals_are_recorded_and_retryable(self):
        self.pair()
        good, self.fake.token = self.fake.token, "codigo-trocado-no-hyperbooklm-com-32-caracteres"
        with self.assertRaises(AppError) as unauthorized:
            hb.send(self.key)
        self.assertIn("código de pareamento", str(unauthorized.exception))
        self.assertEqual((self.entry()["state"], self.fake.posts), ("failed", []))
        self.fake.token, self.fake.limit = good, 0
        with self.assertRaises(AppError):
            hb.send(self.key)  # a ponte está cheia
        self.assertEqual(self.entry()["state"], "failed")
        self.fake.limit = 50
        self.assertEqual(hb.send(self.key)["state"], "sent")  # “Tentar de novo” funciona
        self.fake.shutdown()
        self.fake.server_close()
        offline = hb.status(self.key, check=True)  # fora do ar: o último estado guardado e o aviso
        self.assertEqual((offline["state"], bool(offline["offline"])), ("sent", True))

    def test_oversized_transcript_is_refused_before_anything_is_sent(self):
        self.pair()
        limit, hb.MAX_TEXT = hb.MAX_TEXT, 10
        self.addCleanup(setattr, hb, "MAX_TEXT", limit)
        with self.assertRaises(AppError) as big:
            hb.send(self.key)
        self.assertIn("grande demais", str(big.exception))
        self.assertEqual(self.fake.posts, [])

    def test_needs_connection_and_a_stored_transcript(self):
        with self.assertRaises(AppError):
            hb.send(self.key)  # desligado
        self.pair()
        (jobs.work_dir(self.key) / "transcript.json").unlink()
        with self.assertRaises(AppError):
            hb.send(self.key)
        self.assertEqual((hb.lesson(self.key)["state"], hb.lesson(self.key)["transcript"]), ("none", False))


if __name__ == "__main__":
    unittest.main()
