"""Readable evidence, destination safety and completion semantics (isolated data)."""
import hashlib
from unittest import TestCase, mock

from tests import test_protection as base
from lumen import AppError, protection as p, protection_notion as pn, server


class Attention(TestCase):
    setUp = base.Protection.setUp
    tearDown = base.Protection.tearDown

    def fixture(self):
        self.source = self.home / "capture/notion"
        self.source.mkdir(parents=True)
        self.mirror = self.vault / "Lumen - Backup do Notion"
        self.mirror.mkdir()
        p.write(self.mirror / p.MARKER, {"owner": "a" * 32, "kind": "notion-mirror", "pages": {"a": "a.md"}})
        self.raw = "---\nlumen-protection-origin: notion\nlumen-protection-id: a\n---\n\n# Nota\n\nOrigem: Notion · Captura: 2026-01-01\n\nConteúdo intacto"
        (self.source / "a.md").write_text(self.raw, "utf-8")
        (self.mirror / "a.md").write_text(self.raw.replace("2026-01-01", "2026-01-02"), "utf-8")
        p.write(self.source / "a.json", {"object": {"icon": {"type": "external", "external": {"url": "✦"}}}})
        p.write(self.source / "manifest.json", {"items": {"a": {"title": "Nota com acentuação", "files": {"a.md": p.digest(self.source / "a.md")}}}})
        p.status_of("notion_obsidian", path=str(self.mirror), conflicts=["a.md"])

    def test_timestamp_difference_is_not_called_user_edit_and_changes_nothing(self):
        self.fixture()
        before = (self.mirror / "a.md").read_bytes()
        item = p.attention_details()["items"][0]
        self.assertEqual(item["title"], "Nota com acentuação")
        self.assertEqual(item["reason"], "capture_time_only")
        self.assertEqual((self.mirror / "a.md").read_bytes(), before)
        (self.mirror / "a.md").write_bytes(before + b" ")
        self.assertEqual(p.attention_details()["items"][0]["reason"], "unconfirmed")

    def test_invalid_icon_and_unsupported_block_have_distinct_explanations(self):
        self.fixture()
        name = hashlib.sha256("✦".encode()).hexdigest()[:32]
        p.status_of("notion", pending=["a: Anexo não capturado: " + name, "a: Bloco sem representação legível: unsupported"])
        items = p.attention_details()["items"]
        self.assertEqual([x["cause"] for x in items[:2]], ["icon", "unsupported"])
        self.assertIn("ícone", items[0]["headline"])
        self.assertEqual(items[0]["summary"], "O texto da página foi lido. Só o ícone ficou de fora.")
        self.assertIn("parte desta página", items[1]["headline"])
        self.assertEqual((items[0]["page"], items[0]["action"], items[0]["tone"]), ("a", "notion-page", "review"))
        # Permanent API limitations never suggest that a retry fixes them, and never claim more than the data shows.
        for item in items[:2]:
            text = " ".join([item["headline"], item["summary"], *item["details"]])
            self.assertIn("Repetir o backup não muda", text)
            self.assertNotIn("perda", text)
        # The same notice twice (same page, same cause) is shown once; other pages stay separate.
        p.status_of("notion", pending=["a: Bloco sem representação legível: unsupported"] * 2 + ["b: Bloco sem representação legível: unsupported"])
        self.assertEqual(len([x for x in p.attention_details()["items"] if x["cause"] == "unsupported"]), 2)

    def test_notices_are_grouped_by_tone_and_the_key_follows_real_changes(self):
        self.fixture()
        p.write(self.mirror / p.MARKER, {**p.read(self.mirror / p.MARKER), "preserved_copies": [{"title": "Versão antiga", "path": "Versões preservadas/x.md"}]})
        items = p.attention_details()["items"]
        self.assertEqual({x["cause"]: x["tone"] for x in items}, {"difference": "review", "preserved": "info"})
        self.assertEqual(items[0]["action"], "locate")
        self.assertIn("sem sobrescrever", items[0]["summary"])
        self.assertEqual(items[1]["summary"], "Nenhuma ação necessária.")
        with mock.patch.object(p.gdrive, "status", return_value={"connected": True}):
            first = p.view()["attention_key"]
            p.status_of("notion", pending=["a: Bloco sem representação legível: unsupported"])
            appeared = p.view()["attention_key"]
            p.status_of("notion", pending=[])
            self.assertNotEqual(first, appeared)
            self.assertEqual(p.view()["attention_key"], first)  # resolved again: same as before

    def test_open_uses_recorded_mirror_and_rejects_arbitrary_paths(self):
        self.fixture()
        (self.mirror / "Particular").mkdir()
        with mock.patch.object(p.os, "startfile") as opened:
            p.open_destination("notion_obsidian")
            opened.assert_called_once_with(str(self.mirror / "Particular"))
        with self.assertRaises(AppError): p.open_destination("notion_obsidian", "../../secret")
        p.write(self.mirror / p.MARKER, {"owner": "someone-else"})
        with self.assertRaises(AppError): p.open_destination("notion_obsidian")

    def test_saved_partial_snapshot_is_distinct_from_current_and_disconnected(self):
        p.update(versions=[{"source": "notion", "id": "n", "partial": True, "local": {"path": "", "confirmed": p.now()}, "drive": {"confirmed": p.now()}}])
        value = p.view()
        self.assertEqual(value["saved"]["drive"], ["notion"])
        self.assertFalse(value["current"]["drive"])
        self.assertFalse(value["local_available"])

    def test_no_change_requires_all_steps_and_same_versions(self):
        p.update(versions=[{"id": name, "source": name} for name in ("notion", "obsidian")])
        with mock.patch.object(p, "controller", mock.Mock(started=True)):
            op = p.backup_now()["state"]["operation"]
        for name in p.WORKERS:
            p.status_of(name, status="confirmed", snapshot=name)
            p.finish_step(op["id"], name)
        self.assertEqual(p.state()["operation"]["outcome"], "unchanged")

    def test_new_actions_dispatch_without_mutating_configuration(self):
        handler = mock.Mock()
        handler._json.return_value = {"action": "attention"}
        with mock.patch.object(p, "attention_details", return_value={"items": []}) as details:
            self.assertEqual(server._protection_action(handler), {"items": []})
        details.assert_called_once()

    def test_versions_use_chosen_local_repository_and_explain_cache_fallback(self):
        local = self.dest / "repository"; local.mkdir(); (local / "config").write_text("test")
        handler = mock.Mock(); handler._json.return_value = {"action": "versions"}
        with mock.patch.object(p, "local_folder", return_value=self.dest), mock.patch.object(p, "snapshots", return_value=[]) as snapshots:
            result = server._protection_action(handler)
            snapshots.assert_called_once_with(local, None)
            self.assertEqual(result["location"], "Pasta de backup escolhida")
        with mock.patch.object(p, "local_folder", side_effect=AppError("offline")), mock.patch.object(p, "snapshots", return_value=[]) as snapshots:
            result = server._protection_action(handler)
            self.assertIn("neste Windows", result["location"])

    def test_metadata_repair_archives_bytes_and_multiple_cycles_do_not_duplicate(self):
        from bench.protection_reconcile_metadata import reconcile
        self.fixture()
        m = p.read(self.source / "manifest.json")
        m["items"]["a"]["parent"] = {"type": "workspace"}
        p.write(self.source / "manifest.json", m)
        original = (self.mirror / "a.md").read_bytes()
        # Reproduce the inherited receipt: it points at the other generated timestamp.
        mark = p.read(self.mirror / p.MARKER)
        mark["files"] = {"a.md": p.digest(self.source / "a.md")}
        p.write(self.mirror / p.MARKER, mark)
        records = reconcile()
        self.assertEqual((self.mirror / records[0]["path"]).read_bytes(), original)
        counts = []
        for _ in range(3):
            pn.mirror_to_vault(self.vault, m, self.source)
            counts.append(len(list(self.mirror.rglob("*.md"))))
        self.assertEqual(counts, [2, 2, 2])
        self.assertEqual(p.state()["notion_obsidian"]["conflicts"], [])
        self.assertEqual(p.attention_details()["items"][0]["cause"], "preserved")
