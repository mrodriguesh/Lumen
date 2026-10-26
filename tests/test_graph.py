"""Cor dos estudos no Graph View: o Color Group nativo é criado uma vez, sem mexer no resto do graph.json."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import graph, obsidian, store

CLOSED = lambda: False  # noqa: E731  (Obsidian fechado)
REAL = {  # o graph.json do cofre do usuário em 26/10/2026, com um grupo dele a mais
    "collapse-filter": True, "search": "", "showTags": False, "showAttachments": False, "hideUnresolved": False,
    "showOrphans": True, "colorGroups": [{"query": "path:\"B03 Resources\"", "color": {"a": 1, "rgb": 14701138}}],
    "centerStrength": 0.518713248970312, "repelStrength": 10, "linkStrength": 1, "linkDistance": 250,
    "scale": 0.2588386562181615, "close": False}


class Graph(unittest.TestCase):
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

    def groups(self):
        return json.loads(self.file.read_text("utf-8"))["colorGroups"]

    def test_merges_first_and_keeps_everything_else(self):
        self.put(REAL)
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "created")
        data = json.loads(self.file.read_text("utf-8"))
        self.assertEqual(data["colorGroups"][0], {"query": "[type:ai-study] OR [type:course]",
                                                  "color": {"a": 1, "rgb": 0x5B8CFF}})
        self.assertEqual(data["colorGroups"][1:], REAL["colorGroups"])  # o grupo do usuário fica, depois do nosso
        self.assertEqual({k: v for k, v in data.items() if k != "colorGroups"},
                         {k: v for k, v in REAL.items() if k != "colorGroups"})  # forças, filtros, órfãos: iguais
        self.assertEqual(json.loads((self.file.parent / "graph.json.lumen-backup").read_text("utf-8")), REAL)
        self.assertFalse(list(self.file.parent.glob(".graph.json.lumen-tmp")))

    def test_idempotent_and_installed_once(self):
        self.put(REAL)
        results = {graph.ensure(self.vault, running=CLOSED) for _ in range(100)}
        self.assertEqual(results, {"created", "installed"})
        self.assertEqual(sum(1 for g in self.groups() if "ai-study" in g["query"]), 1)
        # o usuário apagou o grupo no Obsidian: o Lumen não o traz de volta
        data = json.loads(self.file.read_text("utf-8"))
        data["colorGroups"] = REAL["colorGroups"]
        self.put(data)
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "installed")
        self.assertEqual(self.groups(), REAL["colorGroups"])

    def test_custom_color_and_existing_group_are_kept(self):
        mine = {**REAL, "colorGroups": [*REAL["colorGroups"], {"query": "[type:ai-study] OR [type:course]",
                                                                 "color": {"a": 1, "rgb": 0x22AA55}}]}
        self.put(mine)
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "present")
        self.assertEqual(json.loads(self.file.read_text("utf-8")), mine)  # nem a ordem nem a cor do usuário mudam
        self.assertFalse((self.file.parent / "graph.json.lumen-backup").exists())

    def test_missing_empty_and_no_obsidian_folder(self):
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "created")  # sem graph.json: só o grupo
        self.assertEqual(len(self.groups()), 1)
        (store.DATA / "catalog.json").unlink()
        self.put("")
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "created")
        shutil.rmtree(self.vault / ".obsidian")
        (store.DATA / "catalog.json").unlink()
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "no-config")

    def test_invalid_json_is_never_overwritten(self):
        for bad in ('{"colorGroups": [', '[1, 2]', '{"colorGroups": "x"}'):
            with self.subTest(bad):
                self.put(bad)
                self.assertEqual(graph.ensure(self.vault, running=CLOSED), "invalid")
                self.assertEqual(self.file.read_text("utf-8"), bad)

    def test_waits_while_obsidian_is_open(self):
        self.put(REAL)
        self.assertEqual(graph.ensure(self.vault, running=lambda: True), "busy")
        self.assertEqual(self.groups(), REAL["colorGroups"])
        self.assertEqual(graph.ensure(self.vault, running=CLOSED), "created")  # na próxima vez, com ele fechado

    def test_delivering_a_lesson_installs_it_once(self):
        from tests.test_obsidian import make_vault
        root = self.tmp / "Cérebro"
        root.mkdir()
        make_vault(root)
        (root / ".obsidian" / "graph.json").write_text(json.dumps(REAL), "utf-8")
        cfg = {**store.DEFAULTS, "destinations": "obsidian", "obsidian_vault": str(root)}
        with mock.patch.object(graph, "_obsidian_running", return_value=False):
            self.assertEqual(obsidian.graph_identity(cfg), "created")
            with mock.patch.object(graph.os, "replace", side_effect=AssertionError("regravou")):
                for _ in range(3):  # cada aula nova: nenhuma escrita no graph.json
                    self.assertEqual(obsidian.graph_identity(cfg), "installed")
        self.assertIsNone(obsidian.graph_identity({**cfg, "destinations": "notion"}))


if __name__ == "__main__":
    unittest.main()
