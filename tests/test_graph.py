"""Cores no Graph View: os Color Groups nativos dos estudos e dos Canvas, criados uma vez, sem mexer no resto."""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import catalog, graph, obsidian, store

CLOSED = lambda: False  # noqa: E731  (Obsidian fechado)
AREA = "B02 Estudos"
STUDY = "[type:ai-study] OR [type:course]"
CANVAS = r"path:/^B02 Estudos\// file:/\.canvas$/"  # a consulta conferida no Obsidian 1.14
OURS = [{"query": CANVAS, "color": {"a": 1, "rgb": 0xA78BFA}}, {"query": STUDY, "color": {"a": 1, "rgb": 0x5B8CFF}}]
THEIRS = [{"query": "path:\"B01 Projects\"", "color": {"a": 1, "rgb": 0x40C060}},
          {"query": "path:\"B03 Resources\"", "color": {"a": 1, "rgb": 14701138}}]
REAL = {  # o graph.json do cofre do usuário em 26/10/2026, com grupos dele a mais
    "collapse-filter": True, "search": "", "showTags": False, "showAttachments": False, "hideUnresolved": False,
    "showOrphans": True, "colorGroups": THEIRS, "centerStrength": 0.518713248970312, "repelStrength": 10,
    "linkStrength": 1, "linkDistance": 250, "scale": 0.2588386562181615, "close": False}


class Graph(unittest.TestCase):
    def test_process_check_ignores_localized_output_and_waits_on_command_failure(self):
        from subprocess import CompletedProcess
        with mock.patch.object(graph.sys, "platform", "win32"), mock.patch.object(graph.subprocess, "run") as run:
            for code, output, expected in ((0, b"INFORMA\x80\xe5ES: nenhuma tarefa", False), (0, b"Obsidian.exe 123", True), (1, b"", True)):
                run.return_value = CompletedProcess([], code, stdout=output)
                self.assertEqual(graph._obsidian_running(), expected)
                self.assertNotIn("text", run.call_args.kwargs)

    def setUp(self):
        (store.DATA / "catalog.json").unlink(missing_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="lumen-graph-"))
        self.vault = self.tmp / "Cofre"
        (self.vault / ".obsidian").mkdir(parents=True)
        self.file = self.vault / ".obsidian" / "graph.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, data):
        self.file.write_text(json.dumps(data) if not isinstance(data, str) else data, "utf-8")

    def data(self):
        return json.loads(self.file.read_text("utf-8"))

    def ensure(self, running=CLOSED):
        return graph.ensure(self.vault, AREA, running=running)

    def test_merges_first_and_keeps_everything_else(self):
        self.put(REAL)
        self.assertEqual(self.ensure(), "created")
        data = self.data()
        self.assertEqual(data["colorGroups"], OURS + THEIRS)  # os do usuário ficam, depois dos nossos
        self.assertEqual(data["colorGroups"][0]["color"]["rgb"], int("A78BFA", 16))  # violeta, não outro azul
        self.assertEqual({k: v for k, v in data.items() if k != "colorGroups"},
                         {k: v for k, v in REAL.items() if k != "colorGroups"})  # forças, filtros, anexos: iguais
        self.assertEqual(json.loads((self.file.parent / "graph.json.lumen-backup").read_text("utf-8")), REAL)
        self.assertFalse(list(self.file.parent.glob(".graph.json.lumen-tmp")))

    def test_canvas_query_only_takes_canvas_inside_the_area(self):
        rx = re.compile(r"path:/(.*)/ file:/(.*)/").fullmatch(graph.canvas_query(AREA))
        take = lambda p: bool(re.search(rx[1], p) and re.search(rx[2], p.rsplit("/", 1)[-1]))  # noqa: E731
        self.assertTrue(take("B02 Estudos/01 - Cursos/C/01 - M/Aula/Mapa - Aula.canvas"))
        self.assertTrue(take("B02 Estudos/90 - A organizar/Aula/Meu esboço.canvas"))  # Canvas do usuário na aula
        self.assertFalse(take("B01 Projects/Arquitetura do Lumen.canvas"))
        self.assertFalse(take("B04 Archives/B02 Estudos antigo/Velho.canvas"))
        self.assertFalse(take("B02 Estudos/Ideias.canvas.md"))
        self.assertEqual(graph.canvas_query("Estudos (2026)"), r"path:/^Estudos \(2026\)\// file:/\.canvas$/")

    def test_idempotent_and_installed_once(self):
        self.put(REAL)
        results = {self.ensure() for _ in range(50)}
        self.assertEqual(results, {"created", "installed"})
        self.assertEqual(self.data()["colorGroups"], OURS + THEIRS)  # um de cada, nunca repetido
        # o usuário apagou os dois grupos no Obsidian: o Lumen não os traz de volta
        self.put(REAL)
        self.assertEqual(self.ensure(), "installed")
        self.assertEqual(self.data()["colorGroups"], THEIRS)

    def test_study_group_from_before_gets_only_the_canvas_group(self):
        # o cofre do usuário: o grupo azul instalado antes (marca antiga, só o cofre), com uma cor que ele escolheu
        mine = {**REAL, "colorGroups": [{"query": STUDY, "color": {"a": 1, "rgb": 0x22AA55}}, *THEIRS]}
        self.put(mine)
        cat = catalog.load()
        cat["meta"]["graph_installed"] = [os.path.normcase(str(self.vault))]
        catalog.save(cat)
        self.assertEqual(self.ensure(), "created")
        self.assertEqual(self.data()["colorGroups"], [OURS[0], *mine["colorGroups"]])  # o azul dele fica como está
        self.assertEqual(self.ensure(), "installed")
        # e se ele tivesse apagado o grupo azul, a marca antiga também impede de recriar
        self.put(REAL)
        self.assertEqual(self.ensure(), "installed")

    def test_custom_colors_and_existing_groups_are_kept(self):
        mine = {**REAL, "colorGroups": [*THEIRS, {"query": STUDY, "color": {"a": 1, "rgb": 0x22AA55}},
                                        {"query": CANVAS + "  ", "color": {"a": 1, "rgb": 0xC084FC}},
                                        {"query": CANVAS, "color": {"a": 1, "rgb": 0xC084FC}}, {"query": None}]}
        self.put(mine)
        self.assertEqual(self.ensure(), "present")
        self.assertEqual(self.data(), mine)  # nem a ordem, nem as cores, nem o grupo repetido dele mudam
        self.assertFalse((self.file.parent / "graph.json.lumen-backup").exists())

    def test_missing_empty_and_no_obsidian_folder(self):
        self.assertEqual(self.ensure(), "created")  # sem graph.json: só os grupos
        self.assertEqual(self.data(), {"colorGroups": OURS})
        (store.DATA / "catalog.json").unlink()
        self.put("")
        self.assertEqual(self.ensure(), "created")
        shutil.rmtree(self.vault / ".obsidian")
        (store.DATA / "catalog.json").unlink()
        self.assertEqual(self.ensure(), "no-config")

    def test_invalid_json_is_never_overwritten(self):
        for bad in ('{"colorGroups": [', '[1, 2]', '{"colorGroups": "x"}'):
            with self.subTest(bad):
                self.put(bad)
                self.assertEqual(self.ensure(), "invalid")
                self.assertEqual(self.file.read_text("utf-8"), bad)

    def test_waits_while_obsidian_is_open(self):
        self.put(REAL)
        self.assertEqual(self.ensure(running=lambda: True), "busy")
        self.assertEqual(self.data()["colorGroups"], THEIRS)
        self.assertEqual(self.ensure(), "created")  # na próxima vez, com ele fechado

    def test_delivering_a_lesson_installs_it_once(self):
        from tests.test_obsidian import make_vault
        root = self.tmp / "Cérebro"
        root.mkdir()
        make_vault(root)
        (root / ".obsidian" / "graph.json").write_text(json.dumps(REAL), "utf-8")
        cfg = {**store.DEFAULTS, "destinations": "obsidian", "obsidian_vault": str(root), "obsidian_folder": AREA}
        with mock.patch.object(graph, "_obsidian_running", return_value=False):
            self.assertEqual(obsidian.graph_identity(cfg), "created")
            with mock.patch.object(graph.os, "replace", side_effect=AssertionError("regravou")):
                for _ in range(3):  # cada aula nova: nenhuma escrita no graph.json
                    self.assertEqual(obsidian.graph_identity(cfg), "installed")
        self.assertEqual(json.loads((root / ".obsidian" / "graph.json").read_text("utf-8"))["colorGroups"][:2], OURS)
        self.assertIsNone(obsidian.graph_identity({**cfg, "destinations": "notion"}))


if __name__ == "__main__":
    unittest.main()
