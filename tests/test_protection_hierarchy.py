import copy
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from tests import test_protection as base
from lumen import AppError, protection as p, protection_notion as pn


class Hierarchy(unittest.TestCase):
    setUp = base.Protection.setUp
    tearDown = base.Protection.tearDown

    def fixture(self):
        self.source = self.home / "capture/notion"
        self.source.mkdir(parents=True)
        self.manifest = {"items": {}, "pending": []}
        self.add("a", "Pessoal", None, "[Filha](b.md)\n![Foto](attachments/image.bin)")
        self.add("b", "Sub página", "a", "[Voltar](a.md)")
        self.add("c", "Estudos", None, "Estudos")
        media = self.source / "attachments/image.bin"
        media.parent.mkdir(); media.write_bytes(bytes(range(256)))
        self.manifest["items"]["a"]["files"]["attachments/image.bin"] = p.digest(media)
        self.dest = self.vault / "Lumen - Backup do Notion"

    def add(self, iid, title, parent, body, kind="page_id"):
        par = {"type": kind, kind: parent} if parent is not None else {"type": "workspace", "workspace": True}
        raw = {"object": {"id": iid, "parent": par}, "blocks": []}
        p.write(self.source / (iid + ".json"), raw)
        (self.source / (iid + ".md")).write_text(body, "utf-8")
        self.manifest["items"][iid] = {"title": title, "parent": par,
            "files": {iid + ext: p.digest(self.source / (iid + ext)) for ext in (".json", ".md")}}

    def mirror(self):
        pn.mirror_to_vault(self.vault, self.manifest, self.source)

    def test_tree_links_media_and_original_bytes_three_cycles(self):
        self.fixture()
        original = {f: p.digest(self.source / f) for x in self.manifest["items"].values() for f in x["files"]}
        counts = []
        for _ in range(3):
            self.mirror()
            counts.append(len(list(self.dest.rglob("*.*"))))
        self.assertEqual(len(set(counts)), 1)
        parent = self.dest / "Particular/Pessoal.md"
        child = self.dest / "Particular/Pessoal/Sub página.md"
        self.assertIn("](Pessoal/Sub%20p%C3%A1gina.md)", parent.read_text("utf-8"))
        self.assertIn("](../Anexos/image.bin)", parent.read_text("utf-8"))
        self.assertIn("](../Pessoal.md)", child.read_text("utf-8"))
        self.assertEqual((self.dest / "Anexos/image.bin").read_bytes(), bytes(range(256)))
        self.assertTrue((self.dest / "Dados originais/a.json").exists())
        self.assertEqual(original, {f: p.digest(self.source / f) for f in original})
        self.assertFalse(p.capture_vault(self.vault, self.home / "capture/obsidian")["items"])

    def change(self, iid, body):
        (self.source / (iid + ".md")).write_text(body, "utf-8")
        self.manifest["items"][iid]["files"][iid + ".md"] = p.digest(self.source / (iid + ".md"))

    def test_stop_after_a_write_is_not_mistaken_for_a_user_edit(self):
        self.fixture(); self.mirror()
        self.change("a", "Versão 2 [Filha](b.md)")
        real = os.replace
        def stop_after(src, dst):
            real(src, dst)
            if str(dst).endswith("Pessoal.md"):
                raise OSError("Lúmen fechado antes do recibo")
        with mock.patch.object(os, "replace", stop_after), self.assertRaises(OSError):
            self.mirror()
        self.change("a", "Versão 3 [Filha](b.md)")  # the next reading moved on before the mirror ran again
        self.mirror()
        self.assertEqual(p.state()["notion_obsidian"]["status"], "confirmed")
        self.assertIn("Versão 3", (self.dest / "Particular/Pessoal.md").read_text("utf-8"))
        self.assertNotIn("writing", p.read(self.dest / p.MARKER))

    def test_interrupted_reading_mirrors_the_last_snapshot_and_writes_nothing_half_new(self):
        self.fixture(); self.mirror()
        p.write(self.source / "manifest.json", self.manifest)
        snapshot = self.root / "snapshot"
        shutil.copytree(self.source, snapshot / "notion")
        self.change("c", "Estudos lidos pela metade")
        (self.source / "b.md").write_text("Lido pela metade", "utf-8")  # manifest.json still lists the old bytes
        stale = copy.deepcopy(self.manifest)
        stale["items"]["c"]["files"]["c.md"] = p.read(self.source / "manifest.json")["items"]["c"]["files"]["c.md"]
        with self.assertRaises(pn.CaptureChanged):
            pn.mirror_to_vault(self.vault, stale, self.source)
        self.assertNotIn("metade", (self.dest / "Particular/Estudos.md").read_text("utf-8"))
        p.status_of("notion", snapshot="s1")
        restores = []
        def restore(repo, *args, **kw):
            restores.append(args)
            shutil.copytree(snapshot, Path(args[-1]), dirs_exist_ok=True)
        controller = p.Controller()
        with mock.patch.object(p, "run_restic", side_effect=restore):
            controller.vault_mirror_cycle(); controller.vault_mirror_cycle()
        self.assertEqual(len(restores), 1)  # the restored snapshot is reused while it is the newest
        self.assertIn("Voltar", (self.dest / "Particular/Pessoal/Sub página.md").read_text("utf-8"))
        self.assertEqual(p.state()["notion_obsidian"]["source_snapshot"], "s1")
        self.assertEqual(p.state()["notion_obsidian"]["status"], "confirmed")

    def test_automatic_pass_skips_a_snapshot_already_copied_to_this_vault(self):
        self.fixture()
        p.write(self.source / "manifest.json", self.manifest)
        p.status_of("notion", snapshot="s1")
        controller = p.Controller()
        with mock.patch.object(pn, "mirror_to_vault", wraps=pn.mirror_to_vault) as mirror:
            controller.vault_mirror_cycle(); controller.vault_mirror_cycle()
            self.assertEqual(mirror.call_count, 1)
            p.status_of("notion", snapshot="s2")
            controller.vault_mirror_cycle()
            self.assertEqual(mirror.call_count, 2)
            other = self.root / "outro cofre"; other.mkdir()
            p.configure(vault=str(other))
            controller.vault_mirror_cycle()
            self.assertEqual(mirror.call_count, 3)
        self.assertTrue((other / "Lumen - Backup do Notion/Particular/Pessoal.md").is_file())

    def test_flat_migration_removes_only_owned_unchanged_and_preserves_edits(self):
        self.fixture(); self.dest.mkdir()
        owned = {}
        for item in self.manifest["items"].values():
            for rel, sha in item["files"].items():
                out = self.dest / rel; out.parent.mkdir(exist_ok=True)
                out.write_bytes((self.source / rel).read_bytes()); owned[rel] = sha
        p.write(self.dest / p.MARKER, {"owner": "a" * 32, "kind": "notion-mirror", "files": owned})
        (self.dest / "b.md").write_text("Minha edição", "utf-8")
        (self.dest / "personal.txt").write_text("keep")
        self.mirror(); self.mirror()
        self.assertFalse((self.dest / "a.md").exists())
        self.assertEqual((self.dest / "b.md").read_text("utf-8"), "Minha edição")
        self.assertFalse((self.dest / "Particular/Pessoal/Sub página.md").exists())
        self.assertIn("](../b.md)", (self.dest / "Particular/Pessoal.md").read_text("utf-8"))
        self.assertEqual((self.dest / "personal.txt").read_text(), "keep")
        self.assertEqual(p.state()["notion_obsidian"]["status"], "conflict")

    def test_move_rename_updates_paths_and_links_without_duplicates(self):
        self.fixture(); self.mirror()
        self.manifest["items"]["a"]["title"] = "Vida pessoal"
        self.manifest["items"]["b"]["parent"] = {"type": "page_id", "page_id": "c"}
        self.mirror()
        self.assertFalse((self.dest / "Particular/Pessoal.md").exists())
        self.assertFalse((self.dest / "Particular/Pessoal").exists())
        self.assertTrue((self.dest / "Particular/Estudos/Sub página.md").is_file())
        self.assertIn("](Estudos/Sub%20p%C3%A1gina.md)", (self.dest / "Particular/Vida pessoal.md").read_text("utf-8"))
        self.assertEqual(len(list((self.dest / "Particular").rglob("*.md"))), 3)

    def test_safe_names_collisions_cycle_and_missing_parent(self):
        self.fixture()
        for iid, title in (("d", "pessoal"), ("e", "Pessoal.md"), ("f", "../CON: *?"), ("g", "CON")):
            self.add(iid, title, None, "safe")
        self.add("x", "No parent", "absent", "safe")
        self.add("y", "Cycle 1", "z", "safe"); self.add("z", "Cycle 2", "y", "safe")
        paths, pending = pn.vault_layout(self.manifest, self.source)
        self.assertEqual(len(paths), len(set(x.casefold() for x in paths.values())))
        self.assertEqual(set(pending), {"x", "y", "z"})
        for rel in paths.values(): p.safe_rel(rel)
        self.mirror()
        self.assertEqual(p.state()["notion_obsidian"]["status"], "partial")
        self.assertTrue((self.dest / paths["g"]).exists())

    def test_page_inside_toggle_and_database_hierarchy(self):
        self.fixture()
        raw = p.read(self.source / "a.json")
        raw["blocks"] = [{"object": "block", "type": "toggle", "id": "toggle"}]
        p.write(self.source / "a.json", raw)
        self.manifest["items"]["a"]["files"]["a.json"] = p.digest(self.source / "a.json")
        self.add("db", "Agenda", "toggle", "database", kind="block_id")
        self.add("ds", "Eventos", "db", "source", kind="database_id")
        self.add("event", "Reunião", "ds", "event", kind="data_source_id")
        self.mirror()
        self.assertTrue((self.dest / "Particular/Pessoal/Agenda/Eventos/Reunião.md").exists())

    def test_missing_ancestor_keeps_known_subtree(self):
        self.fixture()
        self.manifest["items"]["a"]["parent"] = {"type": "page_id", "page_id": "unavailable"}
        self.mirror()
        self.assertTrue((self.dest / "Estrutura a conferir/Pessoal/Sub página.md").exists())
        self.assertEqual(set(p.state()["notion_obsidian"]["structure_pending"]), {"a", "b"})

    def test_renamed_page_keeps_user_edit_and_incoming_links(self):
        self.fixture(); self.mirror()
        edited = self.dest / "Particular/Pessoal/Sub página.md"
        edited.write_text("Minha edição", "utf-8")
        self.manifest["items"]["b"]["title"] = "Novo nome"
        self.mirror()
        self.assertEqual(edited.read_text("utf-8"), "Minha edição")
        self.assertFalse((edited.parent / "Novo nome.md").exists())
        self.assertIn("](Pessoal/Sub%20p%C3%A1gina.md)", (self.dest / "Particular/Pessoal.md").read_text("utf-8"))

    def test_interruption_retry_and_corrupt_capture(self):
        self.fixture()
        original = p.write
        writes = []
        def interrupted(path, value):
            if path.name == p.MARKER:
                writes.append(path)
                if len(writes) == 2: raise OSError("interrupted before receipts")
            original(path, value)
        with mock.patch.object(p, "write", side_effect=interrupted), self.assertRaises(OSError):
            self.mirror()
        self.mirror()
        self.assertEqual(p.state()["notion_obsidian"]["status"], "confirmed")
        (self.source / "b.md").write_text("corrupt")
        before = (self.dest / "Particular/Pessoal/Sub página.md").read_bytes()
        with self.assertRaises(AppError): self.mirror()
        self.assertEqual((self.dest / "Particular/Pessoal/Sub página.md").read_bytes(), before)

    def test_updated_bytes_before_receipt_are_reconciled_without_calling_them_edits(self):
        self.fixture(); self.mirror()
        self.add("b", "Sub página", "a", "New capture")
        # Simulate interruption after the new file was written but before its receipt.
        (self.dest / "Particular/Pessoal/Sub página.md").write_text("New capture", "utf-8")
        self.mirror()
        self.assertEqual(p.state()["notion_obsidian"]["conflicts"], [])
        (self.dest / "Particular/Pessoal/Sub página.md").write_text("A real edit", "utf-8")
        self.mirror()
        self.assertTrue(p.state()["notion_obsidian"]["conflicts"])
        self.assertEqual((self.dest / "Particular/Pessoal/Sub página.md").read_text(), "A real edit")

    def test_cache_does_not_hide_changed_parent_when_timestamp_unchanged(self):
        self.fixture()
        obj = {"object": "page", "id": "a", "parent": {"type": "page_id", "page_id": "c"},
               "last_edited_time": "same", "properties": {}}
        old = copy.deepcopy(self.manifest["items"]["a"])
        old.update(edited="same", pending=[])
        with mock.patch.object(pn.notion, "page_id", side_effect=lambda x:x), mock.patch.object(pn.notion, "request", return_value=obj), mock.patch.object(pn, "tree", return_value=[]):
            result = pn.capture("test", ["a"], self.source, {"items": {"a": old}}, discover=False)
        self.assertEqual(result["items"]["a"]["parent"], obj["parent"])

    def test_parent_is_taken_from_final_stable_read(self):
        self.fixture()
        first = {"object": "page", "id": "a", "parent": {"type": "workspace", "workspace": True},
                 "last_edited_time": "before", "properties": {}}
        final = {**first, "parent": {"type": "page_id", "page_id": "c"}, "last_edited_time": "after"}
        with mock.patch.object(pn.notion, "page_id", side_effect=lambda x:x), mock.patch.object(pn.notion, "request", side_effect=[first, final, final]), mock.patch.object(pn, "tree", return_value=[]):
            result = pn.capture("test", ["a"], self.source, discover=False)
        self.assertEqual(result["items"]["a"]["parent"], final["parent"])


if __name__ == "__main__": unittest.main()
