"""Capturas de tela enviadas pelo usuário: aba “Capturas”, “Adicionar capturas” na revisão e a página no Notion."""
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

import av
import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, jobs, llm, server, sources, store, vision
from tests.fake_notion import Fake
from tests.test_flow import wait
from tests.test_llm import GOOD, understood
from tests.test_notion import flat


def png(path, shade, size=(640, 360)):
    """Imagem de teste (um degradê com a intensidade `shade`), escrita como PNG de verdade."""
    img = np.full((size[1], size[0], 3), shade, np.uint8)
    img[::40] = 255 - shade
    frame = av.VideoFrame.from_ndarray(img, format="rgb24")
    with av.open(str(path), "w") as o:
        s = o.add_stream("png")
        s.width, s.height, s.pix_fmt = size[0], size[1], "rgb24"
        for p in s.encode(frame):
            o.mux(p)
        for p in s.encode():
            o.mux(p)
    return str(path)


NOTES = [
    {"titulo": "Preços do plano", "texto": "Plano | Preço\nBásico | R$ 29\nPro | R$ 79", "descricao": "", "tipo": "tabela",
     "valores": []},
    {"titulo": "Função soma", "texto": "def soma(a, b):\n    return a + b", "descricao": "", "tipo": "codigo", "valores": []},
    {"titulo": "Foto do quadro", "texto": "", "descricao": "Um quadro branco com um diagrama de setas.", "tipo": "quadro",
     "valores": []},
]


def reader():
    """vision.read falso: devolve as anotações na ordem das imagens, passando pelo mesmo clean() de verdade."""
    calls = []

    def fake(jpeg, model, check=None, keep_alive="3m", window=None, manual=False):
        calls.append(manual)
        return vision.clean({**NOTES[(len(calls) - 1) % len(NOTES)], "conteudo_da_aula": False}, manual)
    return fake, calls


class Source(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        self.up = store.WORK / "uploads"
        self.up.mkdir(parents=True)

    def test_validates_the_files(self):
        with self.assertRaises(AppError):
            sources.captures({"paths": []})
        with self.assertRaises(AppError):
            sources.captures({"paths": [str(self.up / "nao-existe.png")]})
        txt = self.up / "a.txt"
        txt.write_text("x")
        with self.assertRaises(AppError) as e:
            sources.captures({"paths": [str(txt)]})
        self.assertIn("imagem", str(e.exception))
        many = [png(self.up / f"{i}.png", 10 + i) for i in range(sources.MAX_CAPTURES + 1)]
        with self.assertRaises(AppError):
            sources.captures({"paths": many})

    def test_key_follows_the_content_and_title_defaults(self):
        a, b = png(self.up / "a.png", 30), png(self.up / "b.png", 90)
        one = sources.resolve({"kind": "captures", "paths": [a, b]})
        again = sources.resolve({"kind": "captures", "paths": [b, a]})
        self.assertEqual(one["title"], "Capturas de tela (2)")
        self.assertTrue(one["key"].startswith("caps:"))
        self.assertNotEqual(one["key"], again["key"])  # a ordem das imagens é a ordem da página
        self.assertEqual(sources.resolve({"kind": "captures", "paths": [a, b], "title": "  Meu   estudo "})["title"], "Meu estudo")
        self.assertEqual(sources.resolve({"kind": "captures", "paths": [a], "link": "https://exemplo.com.br/aula"})["link"],
                         "https://exemplo.com.br/aula")

    def test_a_manual_capture_is_kept_whatever_the_model_thinks_of_it(self):
        site = {"titulo": "Blog", "texto": "Como funciona o cache\nO cache guarda cópias.", "descricao": "", "tipo": "pessoa",
                "conteudo_da_aula": False, "valores": []}
        self.assertFalse(vision.clean(site)["keep"])             # tela de aula: o filtro de sempre
        self.assertTrue(vision.clean(site, manual=True)["keep"])  # captura escolhida pelo usuário: fica
        self.assertFalse(vision.clean({"titulo": "x", "texto": "", "descricao": "", "tipo": "outro"}, manual=True)["keep"])

    def test_image_is_converted_to_jpeg(self):
        data = vision.image_jpeg(png(self.up / "a.png", 120, (1920, 1080)))
        self.assertTrue(data.startswith(b"\xff\xd8"))
        with self.assertRaises(AppError):
            bad = self.up / "quebrada.png"
            bad.write_bytes(b"isto nao e uma imagem")
            vision.image_jpeg(bad)


class Flow(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        self.up = store.WORK / "uploads"
        self.up.mkdir(parents=True)
        self.files = [png(self.up / f"{i}_captura.png", 40 + i * 50) for i in range(3)]
        self.read, self.read_calls = reader()
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(vision, "ready", return_value=True),
                        mock.patch.object(vision, "read", side_effect=self.read),
                        mock.patch.object(llm, "_chat", return_value=json.dumps(GOOD)),
                        mock.patch("lumen.mindmap.render", return_value=None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def spec(self, **extra):
        return {"kind": "captures", "paths": self.files, "title": "Meu estudo", "mode": "new", "language": "pt",
                "course_id": self.root, **extra}

    def heads(self, blocks):
        return [b["heading_2"]["rich_text"][0]["text"]["content"] for b in blocks if b["type"] == "heading_2"]

    def test_captures_become_a_page_with_a_captures_section(self):
        jobs.start("process", jobs.process, self.spec())
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        review = j["result"]
        self.assertEqual(review["title"], "Meu estudo")
        self.assertFalse(review["can_retranscribe"])
        self.assertEqual([s["text"] for s in review["segments"]],
                         ["Captura 1: Preços do plano", "Captura 2: Função soma", "Captura 3: Foto do quadro"])
        self.assertEqual([(s["titulo"], s["manual"]) for s in review["screens"]["items"]],
                         [("Preços do plano", True), ("Função soma", True), ("Foto do quadro", True)])
        self.assertEqual(self.read_calls, [True] * 3)  # leitura própria para capturas escolhidas
        understood(review["key"])
        jobs.start("process", jobs.finish, self.spec(screens_off=[review["screens"]["items"][2]["id"]]))
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        prompt = next(c.args[2] for c in llm._chat.call_args_list if "Transcrição da aula" in c.args[2])
        self.assertIn("(na tela) Preços do plano: Plano | Preço / Básico | R$ 29 / Pro | R$ 79", prompt)
        self.assertIn("(na tela) Função soma: def soma(a, b): / return a + b", prompt)
        self.assertFalse(any("diagrama de setas" in c.args[2] for c in llm._chat.call_args_list))
        blocks = self.fake.pages[self.root]["blocks"]
        self.assertIn("📸 Capturas de tela", self.heads(blocks))
        self.assertNotIn("🖥️ O que apareceu na tela", self.heads(blocks))
        gallery = [b for b in blocks if b["type"] == "column_list"
                   and b["column_list"]["children"][0]["column"]["children"][0]["type"] == "image"]
        imgs = [c["column"]["children"][0] for c in gallery[0]["column_list"]["children"]]
        self.assertEqual(len(imgs), 2)
        captions = [i["image"]["caption"][0]["text"]["content"] for i in imgs]
        self.assertEqual(captions, ["📊 Preços do plano", "💻 Função soma"])  # sem horário: não há vídeo
        self.assertTrue(all(self.fake.uploads[i["image"]["file_upload"]["id"]]["status"] == "uploaded" for i in imgs))
        toggles = {b["toggle"]["rich_text"][0]["text"]["content"]: b for b in blocks if b["type"] == "toggle"}
        table = toggles["📊 Preços do plano"]["toggle"]["children"][0]
        self.assertEqual(table["type"], "table")
        self.assertNotIn("⏱", json.dumps(toggles["📊 Preços do plano"], ensure_ascii=False))
        self.assertFalse([b for b in flat(blocks) if b["type"] == "to_do"])  # sem checklist de estudo
        self.assertTrue(all(not p.exists() for p in map(__import__("pathlib").Path, self.files)))  # sem sobras

    def test_retry_after_the_images_were_removed_still_works(self):
        jobs.start("process", jobs.process, self.spec())
        j = wait()
        self.assertEqual(j["status"], "done")
        understood(j["result"]["key"])
        jobs.start("process", jobs.finish, self.spec())
        self.assertEqual(wait()["status"], "done")
        jobs.start("process", jobs.finish, self.spec(mode="replace"))  # “Tentar de novo”: as imagens já foram apagadas
        j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))

    def test_missing_vision_model_is_an_error_not_an_empty_page(self):
        vision.ready.return_value = False
        jobs.start("process", jobs.process, self.spec())
        j = wait()
        self.assertEqual(j["status"], "error")
        self.assertIn("modelo de visão", j["error"]["message"])

    def test_unreadable_captures_do_not_make_an_empty_lesson(self):
        with mock.patch.object(vision, "read", return_value=vision.clean({}, True)):
            jobs.start("process", jobs.process, self.spec())
            j = wait()
        self.assertEqual(j["status"], "error")
        self.assertIn("nada", j["error"]["message"])

    def test_add_captures_to_a_lesson_in_review(self):
        yt = {"kind": "youtube", "url": "https://youtu.be/aaaaaaaaaaa", "captions": "0:00 A fotossíntese usa luz.\n0:20 E água.",
              "mode": "new", "language": "pt", "course_id": self.root}
        with mock.patch.object(sources, "youtube_meta", return_value={"title": "Fotossíntese", "author": "Prof"}):
            jobs.start("process", jobs.process, yt)
            j = wait()
            self.assertEqual(j["status"], "done", j.get("error"))
            key = j["result"]["key"]
            self.assertIsNone(j["result"]["screens"])
            with self.assertRaises(AppError):  # antes da compreensão, nada da aula volta para a interface
                jobs.add_captures(key, self.files[:2])
            understood(key)
            out = jobs.add_captures(key, self.files[:2])
            self.assertEqual([(s["titulo"], s["manual"]) for s in out["items"]],
                             [("Preços do plano", True), ("Função soma", True)])
            self.assertGreater(out["items"][0]["t"], 20)  # depois do que a aula já tem; só serve para ordenar
            more = jobs.add_captures(key, self.files[2:])  # de novo, na mesma aula
            self.assertEqual(len(more["items"]), 3)
            jobs.start("process", jobs.finish, yt)
            j = wait()
            self.assertEqual(j["status"], "done", j.get("error"))
        blocks = self.fake.pages[self.root]["blocks"]
        self.assertIn("📸 Capturas de tela", self.heads(blocks))
        self.assertTrue(any(b["type"] == "video" for b in blocks))  # o que já funcionava continua: o player do YouTube
        prompt = next(c.args[2] for c in llm._chat.call_args_list if "Transcrição da aula" in c.args[2])
        self.assertIn("A fotossíntese usa luz.", prompt)
        self.assertIn("(na tela) Preços do plano", prompt)
        self.assertNotIn("] (na tela)", prompt)  # sem horário inventado para as capturas
        self.assertIn("[00:00] A fotossíntese", prompt)  # o que a aula já tinha continua com os seus

    def test_add_captures_errors(self):
        with self.assertRaises(AppError) as e:
            jobs.add_captures("caps:inexistente", self.files[:1])
        self.assertIn("revisão", str(e.exception))
        with self.assertRaises(AppError):
            jobs.add_captures("x", [])
        with self.assertRaises(AppError):
            jobs.add_captures("x", self.files * 5)  # 15 > 12
        jobs.start("process", jobs.process, self.spec())
        key = wait()["result"]["key"]
        understood(key)
        vision.ready.return_value = False
        with self.assertRaises(AppError) as e:
            jobs.add_captures(key, self.files[:1])
        self.assertIn("modelo de visão", str(e.exception))


class Http(unittest.TestCase):
    """Os endpoints novos pela porta HTTP de verdade (um deles lia o corpo do pedido duas vezes e nunca respondia)."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def post(self, path, body=None, data=None):
        r = urllib.request.Request(self.url + path, data=data if data is not None else json.dumps(body).encode(),
                                   headers={"X-Lumen-Token": server.TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    def test_add_captures_answers(self):
        with mock.patch.object(jobs, "add_captures", return_value={"items": [], "seen": 0, "warning": None}) as add:
            out = self.post("/api/captures/add", {"key": "caps:x", "paths": ["a.png"]})
        add.assert_called_once_with("caps:x", ["a.png"])
        self.assertEqual(out["seen"], 0)

    def test_upload_thumbnail_and_state(self):
        store.clear_local_data()
        up = store.WORK / "uploads"
        up.mkdir(parents=True)
        img = png(up / "ab12cd34_print.png", 100)
        out = self.post("/api/upload?name=colada.png", data=(up / "ab12cd34_print.png").read_bytes())
        self.assertTrue(out["path"].endswith("_colada.png"))
        for path in (out["path"], img):
            r = urllib.request.Request(self.url + "/api/capture?path=" + urllib.parse.quote(path) + "&t=" + server.TOKEN)
            with urllib.request.urlopen(r, timeout=10) as resp:
                self.assertEqual(resp.read()[:2], bytes([255, 216]))  # miniatura em JPEG
        outside = up.parent / "fora.png"
        png(outside, 50)
        with self.assertRaises(urllib.error.HTTPError):  # só serve arquivos da pasta de uploads do Lumen
            urllib.request.urlopen(urllib.request.Request(
                self.url + "/api/capture?path=" + urllib.parse.quote(str(outside)) + "&t=" + server.TOKEN), timeout=10)
        with self.assertRaises(urllib.error.HTTPError):
            self.post("/api/upload?name=virus.exe", data=b"x")
        state = json.loads(urllib.request.urlopen(urllib.request.Request(
            self.url + "/api/state", headers={"X-Lumen-Token": server.TOKEN}), timeout=10).read())
        self.assertEqual(state["sources"]["captures"]["id"], "compativel")
        self.assertIn(".png", state["images"])


if __name__ == "__main__":
    unittest.main()
