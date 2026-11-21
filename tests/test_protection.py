import contextlib
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import tests  # isolated application data, before importing lumen
from lumen import AppError, gdrive, notion, store
from lumen import protection as p, protection_drive as pd, protection_notion as pn


class Protection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="protection-check-")
        self.root = Path(self.temp.name)
        self.home = self.root / "app"
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.dest = self.root / "destination"
        self.dest.mkdir()
        self.secret = "isolated-test-key-never-a-real-credential-12345"
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(p, "HOME", self.home))
        self.stack.enter_context(mock.patch.object(p, "TEMP_ROOT", self.root / "system-temp"))
        self.stack.enter_context(mock.patch.object(p, "password", return_value=self.secret))
        self.stack.enter_context(mock.patch.object(p.keyring, "get_password", return_value=None))
        p.configure(vault=str(self.vault), roots=[], set_id="a" * 32)

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def capture(self, previous=None):
        return p.capture_vault(self.vault, self.home / "capture" / "obsidian", previous)

    def test_persisted_sources_are_used_without_selection_ui(self):
        roots = ["a" * 32, "b" * 32]
        p.configure(roots=roots, discover=False)
        configured = (p.HOME / "config.json").read_bytes()
        defaults = {**store.load_config(), "obsidian_vault": "other-vault", "root_page_id": "c" * 32, "notion_free_page_id": ""}
        note = self.vault / "nota.md"
        note.write_text("Minha nota já configurada", "utf-8")
        controller = p.Controller()
        with mock.patch.object(store, "load_config", return_value=defaults), mock.patch.object(p, "commit_capture") as commit:
            controller.vault_cycle()
            self.assertEqual((p.HOME / "capture/obsidian/files/nota.md").read_bytes(), note.read_bytes())
            self.assertEqual(commit.call_args.args[0], "obsidian")
            with mock.patch.object(store, "get_token", return_value="fixture"), mock.patch.object(pn, "capture", return_value={}) as capture:
                controller.notion_cycle()
                self.assertEqual(capture.call_args.args[1], roots)
                self.assertFalse(capture.call_args.kwargs["discover"])
            self.assertEqual(p.configuration()["vault"], str(self.vault))
        self.assertEqual((p.HOME / "config.json").read_bytes(), configured)

    def test_bytes_names_unicode_rename_and_incremental(self):
        for rel in ("Pessoal backup/nota.md", "Outra/nota.md", ".obsidian/plugins/test/main.js", "coração.canvas", "coração.base", "arquivo.bin"):
            file = self.vault / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"original\x00\xff" if file.suffix == ".bin" else "Conteúdo original ç".encode())
        first = self.capture()
        self.assertEqual(len(first["items"]), 6)
        (self.vault / "Outra/nota.md").rename(self.vault / "Outra/mudou.md")
        second = self.capture(first)
        self.assertEqual(first["items"]["Outra/nota.md"]["id"], second["items"]["Outra/mudou.md"]["id"])
        self.assertEqual(second["deleted"], ["Outra/nota.md"])
        self.assertFalse((self.home / "capture/obsidian/files/Outra/nota.md").exists())
        self.assertEqual(first["items"]["arquivo.bin"]["sha256"], second["items"]["arquivo.bin"]["sha256"])

    def test_owned_area_moved_and_individual_note_do_not_cycle(self):
        area = self.vault / "arbitrary name"
        area.mkdir()
        p.write(area / p.MARKER, {"owner": "a" * 32, "kind": "notion-mirror"})
        (area / "note.md").write_text("Notion", "utf-8")
        (self.vault / "moved.md").write_text("---\nlumen-protection-origin: notion\n---\nNotion", "utf-8")
        (self.vault / "personal backup.md").write_text("personal", "utf-8")
        for _ in range(3):
            result = self.capture()
            self.assertEqual(list(result["items"]), ["personal backup.md"])

    def test_mass_disappearance_keeps_previous_and_locked_file_is_stale(self):
        for n in range(8):
            (self.vault / f"{n}.md").write_text(str(n), "utf-8")
        first = self.capture()
        for n in range(7):
            (self.vault / f"{n}.md").unlink()
        (self.vault / "7.md").write_text("changed", "utf-8")
        with mock.patch.object(p, "stable_copy", side_effect=PermissionError):
            second = self.capture(first)
        self.assertEqual(len(second["items"]), 8)
        self.assertTrue(second["pending"])
        self.assertEqual(second["items"]["7.md"]["sha256"], first["items"]["7.md"]["sha256"])

    def test_destination_overlaps_identity_and_existing_personal_content(self):
        with self.assertRaises(AppError):
            p.check_destination(self.vault)
        with self.assertRaises(AppError):
            p.check_destination(self.vault.parent)
        (self.dest / "personal.txt").write_text("keep", "utf-8")
        p.choose_local(self.dest)
        self.assertEqual((self.dest / "personal.txt").read_text(), "keep")
        c = p.configuration()
        p.configure(identity=[0, 0])
        with self.assertRaises(AppError):
            p.local_folder()
        p.configure(identity=c["identity"])
        self.assertTrue(p.local_folder().exists())

    def test_unsafe_paths(self):
        for name in ("../x", "/x", "C:/x", "a/../../x", "a\\x", "CON", "x/NUL.txt", "a./file", "a//b", "a:b", "a/..", "a\x00b"):
            with self.subTest(name=name), self.assertRaises(AppError):
                p.safe_rel(name)
        self.assertEqual(str(p.safe_rel("研究/ações.md")), "研究/ações.md")

    def test_disk_full_preserves_previous_bytes(self):
        source = self.vault / "a.md"
        source.write_text("old", "utf-8")
        first = self.capture()
        source.write_text("new", "utf-8")
        with mock.patch.object(p.shutil, "disk_usage", return_value=mock.Mock(free=0)):
            second = self.capture(first)
        self.assertTrue(second["pending"])
        self.assertEqual((self.home / "capture/obsidian/files/a.md").read_text(), "old")

    def test_real_restic_increment_versions_delete_and_restore(self):
        (self.vault / "ação.md").write_text("versão 1", "utf-8")
        (self.vault / "img.bin").write_bytes(bytes(range(256)))
        m = self.capture()
        sid = p.commit_capture("obsidian", m)
        self.assertTrue(sid)
        self.assertIsNone(p.commit_capture("obsidian", self.capture(m)))
        (self.vault / "ação.md").write_text("versão 2", "utf-8")
        second = self.capture(m)
        p.commit_capture("obsidian", second)
        (self.vault / "ação.md").unlink()
        p.commit_capture("obsidian", self.capture(second))
        self.assertEqual(len(p.snapshots()), 3)
        p.choose_local(self.dest)
        p.deliver_local()
        self.assertEqual((p.local_folder() / "Atual/obsidian/files/img.bin").read_bytes(), bytes(range(256)))
        self.assertFalse((p.local_folder() / "Atual/obsidian/files/ação.md").exists())
        self.assertEqual(p.read(p.local_folder() / "current-obsidian.json")["snapshot"], p.state()["versions"][-1]["id"])
        target = self.root / "restore"
        target.mkdir()
        result = p.restore(self.home / "repository", sid, target)
        self.assertEqual((Path(result["path"]) / "obsidian/files/ação.md").read_text("utf-8"), "versão 1")
        self.assertEqual(result["files"], 2)
        with self.assertRaises(AppError):
            p.run_restic(self.home / "repository", "check", secret="wrong key")
        self.assertTrue(all(v["local"] for v in p.state()["versions"]))
        confirmed = p.state()["local"]["confirmed"]
        written = (self.home / "state.json").stat().st_mtime_ns
        p.deliver_local()
        self.assertEqual(p.state()["local"]["confirmed"], confirmed)
        self.assertEqual((self.home / "state.json").stat().st_mtime_ns, written)  # nothing new: nothing rewritten every 5 s
        versions = p.state()["versions"]
        p.update(versions=versions[1:])
        p.reconcile_snapshots()
        self.assertEqual({v["id"] for v in p.state()["versions"]}, {v["id"] for v in versions})
        p.update(versions=versions[:-1], obsidian={})
        p.reconcile_snapshots()
        self.assertIsNone(p.commit_capture("obsidian", self.capture(p.read(self.home / "capture/obsidian/manifest.json"))))
        old_destination = p.local_folder()
        new_destination = self.root / "second-destination"
        new_destination.mkdir()
        p.choose_local(new_destination)
        p.deliver_local()
        self.assertEqual(len(p.snapshots(old_destination / "repository")), 3)
        self.assertEqual(len(p.snapshots(p.local_folder() / "repository")), 3)
        with mock.patch.object(pn, "mirror_to_notion") as mirror:
            p.Controller().mirror_cycle()
        self.assertEqual(mirror.call_args.args[3], self.home / "mirror-snapshot/obsidian")
        p.status_of("obsidian_notion", status="confirmed", confirmed=p.now())
        with mock.patch.object(pn, "mirror_to_notion") as mirror:
            p.Controller().mirror_cycle()  # same snapshot, same parent page: no Notion requests
            mirror.assert_not_called()
            p.Controller().mirror_cycle(p.state()["obsidian_notion"]["source_snapshot"])  # a manual request always runs
            mirror.assert_called_once()

    def test_snapshot_failure_retries_without_source_change(self):
        (self.vault / "a.md").write_text("data", "utf-8")
        m = self.capture()
        with mock.patch.object(p, "init_repo", side_effect=AppError("disk disconnected")):
            with self.assertRaises(AppError):
                p.commit_capture("obsidian", m)
        self.assertIsNotNone(p.commit_capture("obsidian", self.capture(m)))

    def test_same_size_and_timestamp_change_is_captured(self):
        path = self.vault / "a.md"
        path.write_bytes(b"before")
        first = self.capture()
        old_stat = path.stat()
        path.write_bytes(b"after!")
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        second = self.capture(first)
        self.assertNotEqual(first["items"]["a.md"]["sha256"], second["items"]["a.md"]["sha256"])

    def test_file_changes_during_copy_preserves_previous(self):
        source = self.vault / "a.md"
        source.write_bytes(b"old")
        first = self.capture()
        source.write_bytes(b"new")
        def mutate():
            source.write_bytes(b"different size")
        with mock.patch.object(p, "background_yield", side_effect=mutate):
            second = self.capture(first)
        self.assertTrue(second["pending"])
        self.assertEqual((self.home / "capture/obsidian/files/a.md").read_bytes(), b"old")

    @unittest.skipUnless(os.name == "nt", "Windows junction")
    def test_junction_is_never_followed(self):
        import _winapi
        junction = self.vault / "redirect"
        _winapi.CreateJunction(str(self.dest), str(junction))
        try:
            self.assertTrue(self.capture()["pending"])
            with self.assertRaises(AppError):
                p.target(self.vault, "redirect/data")
        finally:
            junction.rmdir()

    def test_permission_error_and_disconnection_preserve_destination(self):
        with mock.patch.object(p.tempfile, "TemporaryFile", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                p.choose_local(self.dest)
        p.choose_local(self.dest)
        folder = p.local_folder()
        disconnected = folder.with_name("disconnected")
        folder.rename(disconnected)
        with self.assertRaises(AppError):
            p.local_folder()
        self.assertFalse(folder.exists())
        disconnected.rename(folder)
        self.assertEqual(p.local_folder(), folder)

    def test_capture_continues_busy_and_heavy_work_waits_at_most_30_seconds(self):
        p.configure(enabled=True, drive_enabled=True)
        for name, expected in (("notion", 1), ("drive", 31)):
            controller = p.Controller()
            moments = [0]
            def tick(_):
                moments[0] += 1
                return moments[0] > 35
            controller.stop_event.wait = tick
            calls = []
            with mock.patch.object(p, "foreground_busy", return_value=True), mock.patch.object(p.time, "monotonic", side_effect=lambda: moments[0]):
                controller.loop(name, lambda: calls.append(moments[0]), 60)
            self.assertEqual(calls, [expected])

    def test_notion_idle_interval_never_exceeds_60_seconds(self):
        controller = p.Controller()
        with mock.patch.object(store, "get_token", return_value="fixture"), mock.patch.object(pn, "capture", return_value={}), mock.patch.object(p, "commit_capture", return_value=None):
            for _ in range(12):
                controller.notion_cycle()
        self.assertEqual(p.state()["notion"]["poll_seconds"], 60)

    def test_startup_recovery_retries_and_unlocks_the_selected_local_repository(self):
        p.choose_local(self.dest)
        repos = [self.home / "repository", self.home / "cloud-repository", p.local_folder() / "repository"]
        for repo in repos:
            repo.mkdir(parents=True); (repo / "config").write_bytes(b"fixture")
        controller = p.Controller()
        with mock.patch.object(p, "run_restic", side_effect=AppError("temporarily unavailable")):
            with self.assertRaises(AppError): controller.recover()
        self.assertFalse(controller.recovered)
        with mock.patch.object(p, "run_restic") as restic, mock.patch.object(p, "reconcile_snapshots"):
            controller.recover(); controller.recover()
        self.assertEqual(restic.call_args_list, [mock.call(repo, "unlock") for repo in repos])

    def test_second_controller_cannot_use_the_same_profile(self):
        first, second = p.Controller(), p.Controller()
        with mock.patch.object(p.threading.Thread, "start"), mock.patch.object(p.threading.Thread, "join"), mock.patch.object(notion, "backup_rate_enabled", False):
            first.start()
            try:
                with self.assertRaises(AppError): second.start()
            finally: first.stop()

    def test_notion_missing_access_keeps_previous(self):
        iid = "12345678-1234-1234-1234-123456789abc"
        previous = {"items": {iid: {"id": iid, "sha256": "old"}}}
        err = AppError("forbidden"); err.status = 403
        with mock.patch.object(notion, "request", side_effect=err):
            result = pn.capture("fixture", [iid], self.dest, previous, discover=False)
        self.assertTrue(result["items"][iid]["stale"])
        self.assertTrue(result["pending"])

    def test_external_attachment_refreshes_at_same_url(self):
        raw = {"type": "external", "external": {"url": "https://example.com/file.png"}}
        def download(url, path):
            path.parent.mkdir(exist_ok=True); path.write_bytes(payload[0]); return p.digest(path)
        payload = [b"before"]
        with mock.patch.object(pn, "fetch_file", side_effect=download) as fetch:
            first, _ = pn.attachments(raw, self.dest)
            payload[0] = b"after"
            second, _ = pn.attachments(raw, self.dest, first)
        self.assertEqual(fetch.call_count, 2)
        self.assertNotEqual(next(iter(first.values()))["sha256"], next(iter(second.values()))["sha256"])

    def test_drive_lost_response_resumes_missing_bytes_with_same_id(self):
        path = self.dest / "object"; path.write_bytes(b"0123456789")
        entry = {"id": "fixture-id", "session": "https://www.googleapis.com/session"}
        remote = {"size": 10, "md5Checksum": p.digest(path, "md5")}
        with mock.patch.object(pd, "metadata", side_effect=[None, remote]), mock.patch.object(pd, "request", side_effect=[(308, {"Range": "bytes=0-3"}, b""), (200, {}, b"")]) as request:
            result = pd.upload(path, "object", "parent", entry, lambda: None)
        self.assertEqual(result["id"], "fixture-id")
        self.assertEqual(request.call_args_list[1].args[2], b"456789")
        with mock.patch.object(pd, "metadata", return_value=remote), mock.patch.object(pd, "request") as request:
            pd.upload(path, "object", "parent", entry, lambda: None)
            request.assert_not_called()
        with mock.patch.object(pd, "metadata", return_value={**remote, "md5Checksum": "wrong"}):
            with self.assertRaises(AppError):
                pd.upload(path, "object", "parent", entry, lambda: None)

    def test_drive_catalog_not_published_if_object_fails(self):
        repo = self.home / "cloud-repository"; repo.mkdir(parents=True)
        (repo / "config").write_bytes(b"encrypted")
        with mock.patch.object(pd, "folder", return_value="parent"), mock.patch.object(p, "copy_snapshot", return_value="a" * 64), mock.patch.object(pd, "upload", side_effect=AppError("network")) as upload:
            with self.assertRaises(AppError):
                pd.publish("b" * 64, "obsidian")
        self.assertEqual(upload.call_count, 1)
        self.assertFalse((self.home / "cloud-catalogs").exists())

    def test_drive_recovery_does_not_require_original_repository(self):
        from lumen import server
        handler = mock.Mock(); handler._json.return_value = {"action": "recover", "drive_id": "fixture-id"}
        with mock.patch.object(server, "_protection_folder", return_value=str(self.dest)), mock.patch.object(pd, "download_repository", return_value=(self.dest, {"snapshot": "a" * 64})), mock.patch.object(p, "run_restic"), mock.patch.object(p, "restore", return_value={"verified": True}):
            self.assertTrue(server._protection_action(handler)["verified"])

    def test_mirror_preserves_user_edit_after_rename(self):
        source = self.home / "capture/notion"
        source.mkdir(parents=True)
        (source / "id.md").write_text("original", "utf-8")
        manifest = {"items": {"id": {"files": {"id.md": p.digest(source / "id.md")}}}}
        pn.mirror_to_vault(self.vault, manifest)
        dest = self.vault / "Lumen - Backup do Notion"
        moved = self.vault / "Renamed"
        dest.rename(moved)
        (moved / "Particular/id.md").write_text("user edit", "utf-8")
        pn.mirror_to_vault(self.vault, manifest)
        self.assertEqual((moved / "Particular/id.md").read_text(), "user edit")
        self.assertEqual(p.state()["notion_obsidian"]["status"], "conflict")
        self.assertFalse(dest.exists())

    def test_clear_preserves_protection_state(self):
        p.update(versions=[{"id": "abc"}], operation={"id": "keep", "status": "running"})
        store.clear_local_data()
        self.assertEqual(p.state()["versions"], [{"id": "abc"}])
        self.assertEqual(p.state()["operation"], {"id": "keep", "status": "running"})

    def test_retry_after_is_never_truncated(self):
        self.assertEqual(notion.retry_after({"Retry-After": "3600"}, 0), 3600)
        e = mock.Mock(headers={"Retry-After": "7200"})
        self.assertEqual(gdrive._after(e, 0), 7200)

    def test_shared_rate_wait_rechecks_a_later_retry_after(self):
        clock = [0.0]; waits = []
        def sleep(delay):
            waits.append(delay); clock[0] += delay
            if len(waits) == 1:
                notion._rate_blocked = 10.0
        with mock.patch.object(notion, "backup_rate_enabled", True), mock.patch.object(notion, "_rate_next", 1.0), mock.patch.object(notion, "_rate_blocked", 0.0), mock.patch.object(notion.time, "monotonic", side_effect=lambda: clock[0]), mock.patch.object(notion.time, "sleep", side_effect=sleep):
            notion.rate_wait()
        self.assertEqual(waits, [1.0, 9.0])

    def test_wrong_imported_key_cannot_replace_current_key(self):
        from lumen import server
        repo = self.home / "repository"; repo.mkdir(parents=True); (repo / "config").write_bytes(b"config")
        key = self.dest / "key.json"
        p.write(key, {"format": "lumen-recovery-key-1", "set_id": "a" * 32, "password": "wrong-but-valid-length-password"})
        h = mock.Mock(); h._json.return_value = {"action": "import-key"}
        with mock.patch.object(server, "_protection_dialog", return_value=str(key)), mock.patch.object(p, "snapshots", side_effect=AppError("wrong key")), mock.patch.object(p.keyring, "set_password") as setter:
            with self.assertRaises(AppError): server._protection_action(h)
            setter.assert_not_called()
        label = p.recovery_label()
        with mock.patch.object(p, "HOME", self.root / "different-profile"):
            self.assertNotEqual(label, p.recovery_label())

    def test_missing_cloud_object_fails_revalidation(self):
        catalog = {"format": "lumen-restic-1", "objects": [{"id": "fixture", "size": 1, "md5": "abc"}]}
        def download(fid, out): p.write(out, catalog)
        with mock.patch.object(pd, "download", side_effect=download), mock.patch.object(pd, "metadata", return_value=None):
            with self.assertRaises(AppError): pd.verify_catalog({"id": "catalog-fixture"})

    def test_public_download_rejects_private_urls_before_connection(self):
        for url in ("http://example.com/file", "file:///secret", "https://user:secret@example.com/file", "https://localhost/file", "https://127.0.0.1/file"):
            with self.subTest(url=url), self.assertRaises(AppError):
                pn.fetch_file(url, self.dest / "file")

    def test_pagination_and_incomplete_cursor(self):
        with mock.patch.object(notion, "request", side_effect=[{"results": [1], "has_more": True, "next_cursor": "x"}, {"results": [2]}]):
            self.assertEqual(list(pn.pages("token", "/search", {})), [1, 2])
        with mock.patch.object(notion, "request", return_value={"results": [], "has_more": True}):
            with self.assertRaises(AppError):
                list(pn.pages("token", "/search", {}))

    def test_independent_drive_assembly_and_corruption(self):
        spec = importlib.util.spec_from_file_location("recovery", Path(__file__).parents[1] / "docs/recuperar-drive.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = self.dest / "object"
        source.write_bytes(b"encrypted example")
        sha = p.digest(source)
        source.rename(self.dest / ("object-" + sha + ".bin"))
        catalog = self.dest / "catalog.json"
        p.write(catalog, {"format": "lumen-restic-1", "snapshot": "abc", "objects": [{"path": "data/ab/abcdef", "size": 17, "sha256": sha}]})
        self.assertEqual(module.assemble(catalog, self.dest, self.root / "assembled"), "abc")
        (self.dest / ("object-" + sha + ".bin")).write_bytes(b"corrupted example")
        with self.assertRaises(ValueError):
            module.assemble(catalog, self.dest, self.root / "bad")


if __name__ == "__main__":
    unittest.main()
