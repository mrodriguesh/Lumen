"""Painel visual (lumen/board.py): escolha das imagens, composição, atualização sem perder o que o usuário fez, e a
entrega no cofre junto com a nota e o mapa conceitual."""
import json
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np

from lumen import board, canvas, obsidian, package, vault
from tests.test_obsidian import LINKS, MINE, SRC, TR, Base, lesson


def jpeg(seed, w=1280, h=720, noise=0):
    """Um “slide” sintético: blocos de cor que mudam com a semente (noise: a mesma tela com ruído leve)."""
    import av
    from lumen import vision
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 245, np.uint8)
    for _ in range(9):
        x, y = rng.integers(0, w - 200), rng.integers(0, h - 120)
        img[y:y + rng.integers(60, 220), x:x + rng.integers(120, 420)] = rng.integers(0, 200, 3)
    if noise:
        img = np.clip(img.astype(int) + np.random.default_rng(seed + 999).integers(-noise, noise + 1, img.shape), 0, 255).astype(np.uint8)
    return vision._encode(av.VideoFrame.from_ndarray(img, format="rgb24"))


def screen(i, t, tipo, titulo, texto="", descricao="", manual=False):
    return {"id": i, "t": t, "manual": manual, "note": {"titulo": titulo, "tipo": tipo, "texto": texto, "descricao": descricao}}


SCREENS = [
    screen(0, 42, "diagrama", "Embeddings no espaço vetorial", "vetores sentido embeddings", "Diagrama de vetores em 2D."),
    screen(1, 90, "slide", "Agenda da aula", "agenda tópicos", "Lista de tópicos."),
    screen(2, 130, "tabela", "Comparação de bancos vetoriais", "banco vetorial busca latência", "Tabela comparando bancos."),
    screen(3, 200, "outro", "Professor falando", "", "Pessoa diante da câmera."),
    screen(4, 260, "codigo", "Busca por similaridade", "def busca vetores embeddings", "Código Python de busca."),
]


class Pkg(Base):
    def make(self, screens=SCREENS, les=None, mine=MINE, links=LINKS):
        p = package.build(SRC, TR, les or lesson(), dict(mine), screens=screens, links=json.loads(json.dumps(links)),
                          course="IA", model="qwen3:8b", intervals=self.cfg["review_intervals"], today=date(2026, 10, 23))
        return package.validate(p, [n["name"] for n in vault.index(self.root)])

    def avail(self, p, data=None):
        data = data or {}
        return [{"key": f"tela:{s['id']}", "source": "tela", "ref": s["id"], "file": f"Anexos/tela {s['id']}.jpg",
                 "data": data.get(s["id"]) or jpeg(s["id"] + 1)} for s in p["screens"]]


class Choice(Pkg):
    def test_image_size_from_the_header(self):
        self.assertEqual(board.dims(jpeg(1, 1280, 720)), (1280, 720))
        self.assertEqual(board.dims(b"GIF89a" + (640).to_bytes(2, "little") + (360).to_bytes(2, "little") + b"\0" * 20), (640, 360))
        self.assertEqual(board.dims(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (800).to_bytes(4, "big") + (600).to_bytes(4, "big")), (800, 600))
        self.assertIsNone(board.dims(b"nada disso"))

    def test_informative_screens_win_and_the_teacher_face_stays_out(self):
        p = self.make()
        pl = board.plan(p, self.avail(p))
        keys = [a["key"] for a in pl["assets"]]
        self.assertNotIn("tela:3", keys)                      # “outro” sem ligação com a aula: nem como detalhe
        self.assertEqual(pl["assets"][0]["key"], "tela:0")     # diagrama do conceito que o estudante escreveu
        self.assertEqual(pl["assets"][0]["role"], "hero")
        self.assertEqual(pl["assets"][0]["concept_title"], "Embeddings")
        self.assertEqual(pl, board.plan(p, self.avail(p)))     # determinístico

    def test_what_the_student_wrote_raises_the_image(self):
        about = [screen(0, 300, "slide", "Reranking dos trechos", "reranking ordem trechos"),
                 screen(1, 320, "slide", "Chunking dos documentos", "chunking tamanho trechos")]
        mine = {**MINE, "current_understanding": "O reranking reordena os trechos. Reranking é o que mais me confundiu.",
                "ai_analysis": {}}
        p = self.make(about, mine=mine)
        self.assertEqual(board.plan(p, self.avail(p))["assets"][0]["title"], "Reranking dos trechos")
        cap = [screen(0, 300, "slide", "Chunking dos documentos", "chunking tamanho trechos"),
               screen(1, None, "slide", "Minha anotação do quadro", "anotação", manual=True)]
        p = self.make(cap, mine={**MINE, "current_understanding": "Nada a ver.", "ai_analysis": {}})
        self.assertEqual(board.plan(p, self.avail(p))["assets"][0]["title"], "Minha anotação do quadro")

    def test_a_spoken_lesson_gets_no_board(self):
        p = self.make([screen(0, 10, "outro", "Professor", "", "Rosto."), screen(1, 20, "outro", "Câmera", "", "Sala.")])
        self.assertIsNone(board.plan(p, self.avail(p)))
        self.assertIsNone(board.plan(self.make([]), []))

    def test_density_caps_a_very_visual_lesson(self):
        many = [screen(i, 30 * i, "diagrama", f"Diagrama {i} de embeddings", f"embeddings vetores parte {i}") for i in range(30)]
        p = self.make(many)
        av = self.avail(p)
        for density, cap in board.DENSITY.items():
            self.assertLessEqual(len(board.plan(p, av, density)["assets"]), cap)
        self.assertEqual(len(board.plan(p, av, "visual")["assets"]), 15)

    def test_near_identical_screens_count_once(self):
        same = [screen(0, 40, "diagrama", "Embeddings 1", "embeddings vetores"),
                screen(1, 80, "diagrama", "Embeddings 2", "embeddings vetores"),
                screen(2, 120, "diagrama", "Banco vetorial", "banco vetorial")]
        p = self.make(same)
        data = {0: jpeg(7), 1: jpeg(7, noise=3), 2: jpeg(8)}
        keys = [a["key"] for a in board.plan(p, self.avail(p, data))["assets"]]
        self.assertEqual(len([k for k in keys if k in ("tela:0", "tela:1")]), 1)
        self.assertIn("tela:2", keys)


class Layout(Pkg):
    def board_for(self, n, **kw):
        many = [screen(i, 25 * i + 5, ("diagrama", "tabela", "slide", "codigo", "grafico")[i % 5], f"Tela {i} sobre embeddings",
                       f"embeddings vetores busca {i}") for i in range(n)]
        p = self.make(many, **kw)
        data = {i: jpeg(i + 1, *((720, 1000) if i % 4 == 3 else (1280, 720))) for i in range(n)}
        pl = board.plan(p, self.avail(p, data), "visual")
        return p, pl, board.build(pl, p, "2026-10-23 - RAG", "Mapa - RAG.canvas", {"Busca semântica": "x.md"})

    def test_compositions_without_overlap_with_a_clear_hierarchy(self):
        for n in (3, 6, 10, 15):
            with self.subTest(n=n):
                p, pl, (b, units) = self.board_for(n)
                self.assertEqual(board.check(b), [])
                files = [x for x in b["nodes"] if x["type"] == "file"]
                self.assertEqual(len(files), len(pl["assets"]))
                hero = next(a for a in pl["assets"] if a["role"] == "hero")
                area = {x["file"]: x["width"] * x["height"] for x in files}
                self.assertEqual(max(area, key=area.get), hero["file"])
                self.assertLessEqual(len(b["edges"]), 8)  # poucas linhas: sem espaguete
                for u in units:  # cada cartão colado na sua imagem
                    nodes = [x for x in b["nodes"] if x["id"] in u]
                    img = next((x for x in nodes if x["type"] == "file"), None)
                    for cap in (x for x in nodes if x["type"] == "text" and img):
                        gap = min(abs(cap["y"] - (img["y"] + img["height"])), abs(cap["x"] - (img["x"] + img["width"])))
                        self.assertLessEqual(gap, board.CAP_GAP + 10)
                xs = sorted({x["x"] for x in files})
                self.assertGreater(len(xs), 2)  # não é uma coluna nem uma grade de uma posição só
                self.assertEqual(b, self.board_for(n)[2][0])  # o mesmo pacote, o mesmo painel

    def test_header_links_the_note_and_the_map(self):
        _, _, (b, _) = self.board_for(4)
        head = next(x for x in b["nodes"] if x["id"] == board.head_id(self.make()["lumen_id"]))
        self.assertIn("[[2026-10-23 - RAG|Abrir a nota de estudo]]", head["text"])
        self.assertIn("[[Mapa - RAG.canvas|Mapa conceitual]]", head["text"])
        self.assertTrue(any("[[Busca semântica]]" in x.get("text", "") for x in b["nodes"]))

    def test_a_tutorial_becomes_a_sequence(self):
        p, pl, (b, _) = self.board_for(6, les=lesson(map_kind="tutorial"))
        self.assertEqual(pl["kind"]["name"], "sequencia")
        self.assertEqual(len(b["edges"]), len(pl["assets"]) - 1)
        self.assertEqual(board.check(b), [])

    def test_a_contrast_becomes_a_comparison(self):
        les = lesson(relations=[{"from": "Embeddings", "type": "contrasta com", "to": "Banco vetorial"}])
        two = [screen(0, 42, "diagrama", "Embeddings no espaço", "embeddings vetores"),
               screen(1, 160, "tabela", "Banco vetorial comparado", "banco vetorial"),
               screen(2, 220, "codigo", "Busca", "busca código")]
        p = self.make(two, les=les)
        pl = board.plan(p, self.avail(p))
        self.assertEqual(pl["kind"]["name"], "comparacao")
        b, _ = board.build(pl, p, "nota", None, {})
        self.assertTrue(any(e.get("label") == "contrasta com" for e in b["edges"]))
        self.assertEqual(board.check(b), [])


class Merge(Pkg):
    def test_manual_moves_and_additions_survive_reprocessing(self):
        p = self.make()
        pl = board.plan(p, self.avail(p))
        fresh, units = board.build(pl, p, "nota", None, {})
        last = board.layout(fresh)
        user = json.loads(json.dumps(fresh))
        imgs = [n for n in user["nodes"] if n["type"] == "file"]
        caps = [n for n in user["nodes"] if n["type"] == "text" and n["id"] != board.head_id(p["lumen_id"])]
        imgs[0]["x"] += 400
        imgs[1]["y"] -= 300
        caps[0]["x"] -= 250
        user["nodes"].append({"id": "meu-card", "type": "text", "x": 5000, "y": 5000, "width": 200, "height": 80, "text": "minha ideia"})
        user["edges"].append({"id": "minha-seta", "fromNode": "meu-card", "toNode": imgs[0]["id"]})
        moved = {n["id"]: (n["x"], n["y"]) for n in (imgs[0], imgs[1], caps[0])}
        # reprocessar: uma tela nova entra e uma das escolhidas antes (a que o usuário moveu) sai
        gone = next(a for a in pl["assets"] if a["file"] == imgs[1]["file"])
        screens = [s for s in SCREENS if f"tela:{s['id']}" != gone["key"]] + [
            screen(9, 300, "grafico", "Latência por tamanho de índice", "latência banco vetorial busca")]
        p2 = self.make(screens)
        fresh2, units2 = board.build(board.plan(p2, self.avail(p2)), p2, "nota", None, {})
        out, moved_ids = board.merge(user, fresh2, units2, last)
        self.assertEqual(moved_ids, set(moved))
        pos = {n["id"]: n for n in out["nodes"]}
        for i, xy in moved.items():
            self.assertEqual((pos[i]["x"], pos[i]["y"]), xy)   # movidos ficam onde o usuário pôs (até o que saiu)
        self.assertIn("meu-card", pos)
        self.assertTrue(any(e["id"] == "minha-seta" for e in out["edges"]))
        self.assertTrue(any(n.get("file") == "Anexos/tela 9.jpg" for n in out["nodes"]))  # o novo entra
        mexidos = set(moved) | {"meu-card"}  # o que o próprio usuário sobrepôs é escolha dele
        self.assertEqual([x for x in board.check(out) if "sobreposição" in x
                          and not set(x.split(": ", 1)[1].split(" × ")) <= mexidos], [])
        # um card do Lumen que saiu e o usuário não mexeu vai embora
        untouched = {n["id"] for n in fresh["nodes"]} - {n["id"] for n in fresh2["nodes"]} - set(moved)
        self.assertFalse(untouched & set(pos))
        # sem o manifesto (dados locais apagados), tudo o que está no arquivo conta como do usuário
        kept, _ = board.merge(user, fresh2, units2, None)
        self.assertTrue({n["id"] for n in user["nodes"]} <= {n["id"] for n in kept["nodes"]})


class Deliver(Pkg):
    def setUp(self):
        super().setUp()
        self.p = self.make()
        self.assets = {"screens": {s["id"]: jpeg(s["id"] + 1) for s in self.p["screens"]}, "charts": []}

    def folder(self):
        return self.root / "C04 Claude Obsidian" / "16 Lumen"

    def test_board_is_a_second_canvas_beside_the_map(self):
        r = self.deliver(self.p, assets=self.assets)
        self.assertTrue(r["board"].endswith("Painel - RAG busca + geração.canvas"), r["board"])
        self.assertTrue(r["canvas"].startswith(r["board"].rsplit("/", 1)[0]))
        self.assertGreaterEqual(r["board_images"], 3)
        b = json.loads(self.read(r["board"]))
        self.assertEqual(board.check(b), [])
        for n in b["nodes"]:
            if n["type"] == "file":
                f = (self.root / n["file"]).resolve()
                self.assertTrue(f.is_file() and self.folder().resolve() in f.parents, n["file"])
        note = self.read(r["note"])
        self.assertIn("## Mapas da aula", note)
        self.assertIn("![[Mapa - RAG busca + geração.canvas]]", note)
        self.assertIn("[[Painel - RAG busca + geração.canvas|Abrir o painel visual]]", note)
        m = json.loads(self.read(r["canvas"]))
        self.assertEqual(canvas.check(m), [])  # o mapa conceitual continua o mesmo de sempre
        self.assertFalse(any(n["type"] == "file" and n["file"].endswith(".jpg") for n in m["nodes"]))
        names = sorted(f.name for f in (self.folder() / "Anexos").iterdir())
        self.assertTrue(any(n.startswith("00m42 embeddings no espaço vetorial · ") for n in names), names)

    def test_reprocessing_keeps_one_board_and_is_idempotent(self):
        r1 = self.deliver(self.p, assets=self.assets)
        r2 = self.deliver(self.p, assets=self.assets, prev=r1)
        self.assertEqual(r1["board"], r2["board"])
        self.assertEqual(r2["state"], "unchanged")
        self.assertEqual(len(list(self.root.rglob("Painel - *.canvas"))), 1)
        # dias depois, sem as imagens no PC: o painel usa as que já estão no cofre
        r3 = self.deliver(self.p, assets={"screens": {}, "charts": []}, prev=r2)
        self.assertEqual(r3["board_images"], r2["board_images"])
        self.assertEqual(r3["state"], "unchanged")

    def test_without_attachments_there_is_no_board(self):
        self.cfg["obsidian_attachments"] = False
        r = self.deliver(self.p, assets=self.assets)
        self.assertEqual(r["board_skipped"], "anexos")
        self.assertNotIn("board", r)
        self.assertNotIn("Painel", self.read(r["note"]))
        self.assertTrue(r["canvas"])

    def test_spoken_lesson_skips_the_board_and_says_why(self):
        p = self.make([screen(0, 10, "outro", "Professor", "", "Rosto.")])
        r = self.deliver(p, assets={"screens": {0: jpeg(1)}, "charts": []})
        self.assertEqual(r["board_skipped"], "sem-imagens")
        self.assertNotIn("Abrir o painel visual", self.read(r["note"]))

    def test_a_board_failure_keeps_the_note_and_the_map(self):
        with mock.patch.object(board, "build", side_effect=ValueError("x")):
            r = self.deliver(self.p, assets=self.assets)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["board_error"])
        self.assertTrue(r["canvas"])
        self.assertNotIn("Painel -", self.read(r["note"]))

    def test_user_edits_on_the_board_survive_and_old_lumen_files_are_tidied(self):
        r1 = self.deliver(self.p, assets=self.assets)
        path = self.root / r1["board"]
        b = json.loads(path.read_text("utf-8"))
        img = next(n for n in b["nodes"] if n["type"] == "file")
        img["x"] += 777
        b["nodes"].append({"id": "meu", "type": "text", "x": 9000, "y": 9000, "width": 220, "height": 80, "text": "eu"})
        path.write_text(json.dumps(b, ensure_ascii=False), "utf-8")
        mine = self.folder() / "Anexos" / "minha foto.jpg"
        mine.write_bytes(jpeg(50))
        # a tela de código sai da aula: o anexo dela (gravado pelo Lumen) sai do cofre; o meu fica
        p2 = self.make([s for s in SCREENS if s["id"] != 4])
        code = next(k for k in r1["files"] if "busca por similaridade" in k)
        r2 = self.deliver(p2, assets={"screens": {s["id"]: jpeg(s["id"] + 1) for s in p2["screens"]}, "charts": []}, prev=r1)
        b2 = json.loads((self.root / r2["board"]).read_text("utf-8"))
        pos = {n["id"]: n for n in b2["nodes"]}
        self.assertEqual(pos[img["id"]]["x"], img["x"])
        self.assertIn("meu", pos)
        # mais uma vez, sem mexer no arquivo: o que o usuário moveu antes continua no lugar dele
        r3 = self.deliver(p2, assets={"screens": {s["id"]: jpeg(s["id"] + 1) for s in p2["screens"]}, "charts": []}, prev={**r1, **r2})
        b3 = {n["id"]: n for n in json.loads((self.root / r3["board"]).read_text("utf-8"))["nodes"]}
        self.assertEqual(b3[img["id"]]["x"], img["x"])
        self.assertIn("meu", b3)
        self.assertTrue(mine.exists())
        self.assertFalse((self.root / code).exists())
        self.assertEqual(r2["board"], r1["board"])

    def test_the_concept_map_keeps_user_moves_across_two_reprocessings(self):
        r1 = self.deliver(self.p, assets=self.assets)
        path = self.root / r1["canvas"]
        m = json.loads(path.read_text("utf-8"))
        card = next(n for n in m["nodes"] if n["type"] == "text")
        card["x"] += 555
        path.write_text(json.dumps(m, ensure_ascii=False), "utf-8")
        r2 = self.deliver(self.p, assets=self.assets, prev=r1)
        r3 = self.deliver(self.p, assets=self.assets, prev={**r1, **r2})  # o arquivo não mudou desde a fusão
        m3 = {n["id"]: n for n in json.loads(path.read_text("utf-8"))["nodes"]}
        self.assertEqual(m3[card["id"]]["x"], card["x"])
        self.assertIsNone(r2["canvas_hash"])

    def test_names_with_accents_and_long_titles_stay_inside_the_vault(self):
        les = lesson(title="Introdução à Programação Orientada a Objetos: herança, polimorfismo, encapsulamento e muito mais")
        shots = [screen(0, 3725, "diagrama", "Hierarquia de classes — Animal → Cão/Gato", "herança classes embeddings")]
        p = self.make(shots, les=les)
        r = self.deliver(p, assets={"screens": {0: jpeg(3)}, "charts": []})
        self.assertTrue(r.get("board"), r)
        for rel in [r["board"], *r["files"]]:
            f = (self.root / rel).resolve()
            self.assertTrue(f.is_file() and self.root.resolve() in f.parents)
            self.assertLess(len(str(f)), 260)
        self.assertTrue(any("62m05" in k for k in r["files"]))


class Write(unittest.TestCase):
    def test_new_files_are_created_in_place_and_old_ones_replaced_whole(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="lumen-write-"))
        try:
            f = d / "nova imagem · aula.jpg"
            with mock.patch.object(obsidian.os, "replace", side_effect=AssertionError("novo não usa temporário")):
                obsidian._write(f, b"abc", binary=True)  # o Obsidian aberto vê o arquivo nascer com o nome certo
            self.assertEqual(f.read_bytes(), b"abc")
            obsidian._write(f, b"abcd", binary=True)
            self.assertEqual(f.read_bytes(), b"abcd")
            self.assertFalse(list(d.glob(".*")))
            with mock.patch("builtins.open", mock.mock_open()) as m:
                m.return_value.write.side_effect = OSError(28, "disco cheio")
                with self.assertRaises(OSError):
                    obsidian._write(d / "parcial.jpg", b"x", binary=True)
            self.assertFalse((d / "parcial.jpg").exists())
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class Settings(unittest.TestCase):
    def test_density_and_switch_are_validated(self):
        from lumen import server, store
        with mock.patch.object(store, "load_config", side_effect=lambda: dict(store.DEFAULTS)), \
                mock.patch.object(store, "save_config") as save:
            server._apply_settings({"obsidian_board": False, "obsidian_board_density": "visual"})
            cfg = save.call_args[0][0]
            self.assertIs(cfg["obsidian_board"], False)
            self.assertEqual(cfg["obsidian_board_density"], "visual")
            server._apply_settings({"obsidian_board_density": "gigante"})
            self.assertEqual(save.call_args[0][0]["obsidian_board_density"], "equilibrado")


if __name__ == "__main__":
    unittest.main()
