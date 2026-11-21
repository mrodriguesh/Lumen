"""Per-destination states shown in the main view: derived only from persisted receipts (isolated data)."""
import hashlib
import io
from pathlib import Path
from unittest import TestCase, mock

from tests import test_protection as base
from lumen import AppError, protection as p, protection_drive as pd

T0, T1, T2, T3 = "2026-10-29T20:00:00+00:00", "2026-10-30T16:00:00+00:00", "2026-10-31T01:00:00+00:00", "2026-10-31T02:00:00+00:00"


def version(vid, source, captured, local=None, drive=None, partial=False):
    return {"id": vid, "source": source, "captured": captured, "partial": partial, "item_versions": {},
            "local": {"path": "chosen", "confirmed": local} if local else None, "drive": {"confirmed": drive} if drive else None}


class Overview(TestCase):
    setUp = base.Protection.setUp
    tearDown = base.Protection.tearDown

    def codes(self, s, local_available=True, drive=True, notion=True, activity=None, **config):
        c = {**p.configuration(), "local": "chosen", "drive_enabled": True, **config}
        r = p.places(s, c, local_available, drive, notion, activity or {})
        return {k: v["state"] for k, v in r["places"].items()}, r

    def current(self):
        """Both origins copied everywhere at their newest versions; the Notion capture has two limitations."""
        return {"versions": [version("o1", "obsidian", T0, T0, T0), version("n1", "notion", T1, T1, T1, partial=True)],
                "obsidian": {"captured": T2, "snapshot": "o1", "snapshot_created": T0, "detected": T0},
                "notion": {"captured": T2, "snapshot": "n1", "snapshot_created": T1, "detected": T1, "pending": ["a: x", "b: y"]},
                "local": {"status": "partial", "confirmed": T1, "source_versions": {"obsidian": "o1", "notion": "n1"}},
                "drive": {"status": "partial", "confirmed": T1},
                "notion_obsidian": {"status": "partial", "confirmed": T1, "source_snapshot": "n1", "items": 479, "layout": "notion-hierarchy-1"},
                "obsidian_notion": {"status": "confirmed", "confirmed": T1, "source_snapshot": "o1", "items": 136,
                                    "url": "https://www.notion.so/" + "a" * 32}}

    def test_first_copy_and_incomplete_configuration(self):
        codes, r = self.codes({}, drive=False, notion=False, local="", vault="")
        self.assertEqual(codes, dict.fromkeys(codes, "setup"))
        self.assertFalse(any(x["link"] for x in r["places"].values()))
        codes, _ = self.codes({})
        self.assertEqual(codes, dict.fromkeys(codes, "first"))

    def test_capture_limitations_do_not_hide_confirmed_copies_or_become_failures(self):
        codes, r = self.codes(self.current())
        self.assertEqual(codes, dict.fromkeys(codes, "ok"))
        self.assertEqual(r["sources"]["notion"]["pending"], 2)
        self.assertTrue(r["places"]["local"]["held"]["notion"]["partial"])
        self.assertTrue(r["places"]["notion_obsidian"]["organized"])

    def test_newer_capture_not_copied_keeps_the_previous_copy_visible(self):
        s = self.current()
        s["versions"].append(version("n2", "notion", T2))
        codes, r = self.codes(s)
        self.assertEqual(codes, {"local": "behind", "drive": "behind", "notion_obsidian": "behind", "obsidian_notion": "ok"})
        held = r["places"]["local"]["held"]
        self.assertEqual((held["obsidian"]["newest"], held["notion"]["newest"]), (True, False))
        self.assertEqual(held["notion"]["version"], T1)
        self.assertEqual(r["sources"]["notion"]["version"], T2)

    def test_only_one_origin_saved_says_which_one(self):
        s = self.current()
        s["versions"][1].update(local=None, drive=None)
        codes, r = self.codes(s)
        self.assertEqual((codes["local"], codes["drive"]), ("behind", "behind"))
        self.assertEqual(list(r["places"]["local"]["held"]), ["obsidian"])

    def test_drive_failure_keeps_local_confirmation_and_previous_drive_copy(self):
        s = self.current()
        s["drive"].update(status="pending", message="Sessão de envio interrompida.", failed=T3)
        codes, r = self.codes(s)
        self.assertEqual((codes["local"], codes["drive"]), ("ok", "attention"))
        self.assertEqual(set(r["places"]["drive"]["held"]), {"obsidian", "notion"})
        self.assertIn("interrompida", r["places"]["drive"]["message"])
        s["drive"].update(status="confirmed", confirmed="2026-10-31T03:00:00+00:00")
        self.assertEqual(self.codes(s)[0]["drive"], "ok")

    def test_unavailable_destinations_keep_what_they_hold(self):
        codes, r = self.codes(self.current(), local_available=False, drive=False, notion=False)
        self.assertEqual(codes, dict.fromkeys(codes, "unavailable"))
        self.assertEqual(set(r["places"]["drive"]["held"]), {"obsidian", "notion"})
        self.assertFalse(r["places"]["local"]["link"])

    def test_work_in_progress_request_and_conflicts(self):
        s = self.current()
        codes, _ = self.codes(s, activity={"local": {"stage": "checking"}, "drive": {"stage": "uploading"}})
        self.assertEqual((codes["local"], codes["drive"]), ("checking", "copying"))
        s["operation"] = {"id": "r", "status": "running", "steps": {"obsidian": {"status": "done"}}}
        codes, _ = self.codes(s)
        self.assertEqual(set(codes.values()), {"queued"})
        s["operation"]["status"] = "partial"
        s["notion_obsidian"].update(status="conflict", conflicts=["a.md"])
        codes, r = self.codes(s)
        self.assertEqual(codes["notion_obsidian"], "attention")
        self.assertEqual(r["places"]["notion_obsidian"]["conflicts"], 1)

    def test_unsaved_reading_changed_pages_and_interrupted_upload_are_not_ok(self):
        s = self.current()
        s["obsidian"]["detected"] = T3
        self.assertEqual(self.codes(s)[0]["local"], "behind")
        s = self.current()
        s["notion"]["captured_roots"] = ["old"]
        codes, _ = self.codes(s, roots=["new"])
        self.assertEqual((codes["local"], codes["notion_obsidian"], codes["obsidian_notion"]), ("behind", "behind", "ok"))
        s = self.current()
        s["drive"]["status"] = "uploading"
        self.assertEqual(self.codes(s)[0]["drive"], "unknown")

    def test_view_is_read_only_and_saved_lists_older_versions(self):
        s = self.current()
        s["versions"].append(version("n2", "notion", T2))
        p.update(**s)
        p.configure(local="chosen", drive_enabled=True)
        files = [self.home / "state.json", self.home / "config.json"]
        before = [hashlib.sha256(f.read_bytes()).hexdigest() for f in files]
        with mock.patch.object(p.gdrive, "status", return_value={"connected": True}):
            value = p.view()
        self.assertEqual([hashlib.sha256(f.read_bytes()).hexdigest() for f in files], before)
        self.assertEqual(value["saved"]["drive"], ["obsidian", "notion"])
        self.assertEqual(value["places"]["drive"]["state"], "behind")
        self.assertFalse(value["current"]["drive"])
        self.assertEqual(p.view()["places"]["drive"]["state"], "unavailable")  # disconnected: copies remain listed

    def test_screen_gets_versions_without_item_receipts_and_reads_the_newest_state(self):
        """The screen refreshes every 5 s: per-item receipts (most of a large state.json) stay in the server, and the
        cached reading (peek) follows every write, even two writes with the same size."""
        s = self.current()
        s["versions"][0]["item_versions"] = {"item": "sha"}
        p.update(**s)
        with mock.patch.object(p.gdrive, "status", return_value={"connected": True}):
            value = p.view()
        self.assertEqual([v["id"] for v in value["state"]["versions"]], ["o1", "n1"])
        self.assertFalse(any("item_versions" in v for v in value["state"]["versions"]))
        self.assertEqual(p.state()["versions"][0]["item_versions"], {"item": "sha"})  # the file keeps them
        for status in ("aaaa", "bbbb"):  # same size, back to back
            p.status_of("local", status=status)
            self.assertEqual(p.peek()["local"]["status"], status)

    def test_loop_failure_is_recorded_without_erasing_the_previous_confirmation(self):
        p.configure(enabled=True, drive_enabled=True)
        p.status_of("drive", status="confirmed", confirmed=T1)
        controller = p.Controller()
        controller.recovered = True
        controller.stop_event.wait = mock.Mock(side_effect=[False, True])
        with mock.patch.object(p, "foreground_busy", return_value=False):
            controller.loop("drive", mock.Mock(side_effect=AppError("Sem internet.")), 10)
        st = p.state()["drive"]
        self.assertEqual((st["status"], st["confirmed"]), ("pending", T1))
        self.assertTrue(p._after(st["failed"], st["confirmed"]))

    def test_real_local_copy_receipts_drive_the_state(self):
        (self.vault / "nota.md").write_text("versão 1", "utf-8")
        m = self.capture()
        p.commit_capture("obsidian", m)
        p.choose_local(self.dest)
        p.deliver_local()
        value = p.view()
        local = value["places"]["local"]
        self.assertEqual(list(local["held"]), ["obsidian"])
        self.assertTrue(local["held"]["obsidian"]["newest"])
        self.assertEqual(local["state"], "behind")  # the Notion origin was never saved
        (self.vault / "nota.md").write_text("versão 2", "utf-8")
        p.commit_capture("obsidian", self.capture(m))
        self.assertFalse(p.view()["places"]["local"]["held"]["obsidian"]["newest"])
        folder = p.local_folder()
        folder.rename(folder.with_name("offline"))
        try:
            value = p.view()
            self.assertEqual(value["places"]["local"]["state"], "unavailable")
            self.assertEqual(value["saved"]["local"], ["obsidian"])
        finally:
            folder.with_name("offline").rename(folder)
        with mock.patch.object(p.shutil, "disk_usage", return_value=mock.Mock(free=0)):
            with self.assertRaises(OSError):
                p.deliver_local()
        self.assertEqual(p.view()["saved"]["local"], ["obsidian"])

    def test_both_origins_recover_from_local_and_drive_with_matching_hashes(self):
        """Real Restic; Drive objects kept in memory but downloaded through the real size/SHA-256 checks."""
        (self.vault / "nota.md").write_text("conteúdo ç", "utf-8")
        (self.vault / "img.bin").write_bytes(bytes(range(256)))
        p.commit_capture("obsidian", self.capture())
        notion = self.home / "capture" / "notion"
        notion.mkdir(parents=True)
        (notion / "page.md").write_text("# Página\n\ntexto", "utf-8")
        (notion / "anexo.png").write_bytes(b"\x89PNG\r\n\x1a\n imagem")
        files = {name: p.digest(notion / name) for name in ("page.md", "anexo.png")}
        p.commit_capture("notion", {"source": "notion", "items": {"page": {"id": "page", "title": "Página", "sha256": files["page.md"], "files": files}},
                                    "pending": [], "started": p.now(), "finished": p.now(), "roots": []})
        expected = {"obsidian/files/nota.md": p.digest(self.vault / "nota.md"), "obsidian/files/img.bin": p.digest(self.vault / "img.bin"),
                    **{"notion/" + name: sha for name, sha in files.items()}}
        p.choose_local(self.dest)
        p.deliver_local()
        cloud = {}
        def upload(path, name, parent, entry, save):
            data = Path(path).read_bytes()
            fid = "object" + hashlib.sha256(data).hexdigest()[:24]
            cloud[fid] = data
            return {"id": fid, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "md5": hashlib.md5(data).hexdigest()}
        opener = mock.Mock()
        opener.open.side_effect = lambda req, timeout: io.BytesIO(cloud[req.full_url.split("/files/")[1].split("?")[0]])
        with mock.patch.object(pd, "folder", return_value="parent"), mock.patch.object(pd, "upload", side_effect=upload):
            receipts = {v["source"]: (v, pd.publish(v["id"], v["source"])) for v in p.state()["versions"]}
        for source, (version, receipt) in receipts.items():
            local = self.root / ("local-" + source); local.mkdir()
            restored = [Path(p.restore(p.local_folder() / "repository", version["local"]["snapshot"], local)["path"])]
            drive = self.root / ("drive-" + source); drive.mkdir()
            with mock.patch.object(pd.gdrive, "_token", return_value="test"), mock.patch.object(pd.urllib.request, "build_opener", return_value=opener):
                root, manifest = pd.download_repository(receipt["id"], drive)
            restored.append(Path(p.restore(root / "repository", manifest["snapshot"], drive)["path"]))
            for folder in restored:
                for rel, sha in expected.items():
                    if rel.startswith(source + "/"):
                        self.assertEqual(p.digest(folder / rel), sha, (folder, rel))
        cloud[next(iter(cloud))] += b"!"  # a corrupted object is refused, never restored
        with mock.patch.object(pd.gdrive, "_token", return_value="test"), mock.patch.object(pd.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(AppError):
                bad = self.root / "corrupted"; bad.mkdir()
                for _, receipt in receipts.values():
                    pd.download_repository(receipt["id"], bad)

    def test_view_always_carries_the_drive_status(self):
        with mock.patch.object(p.gdrive, "status", return_value={"connected": True, "email": "a@b.c"}):
            self.assertEqual(p.view()["drive"]["connected"], True)

    def test_drive_is_off_by_default_and_stays_on_where_a_copy_was_already_confirmed(self):
        self.assertFalse(p.configuration()["drive_enabled"])
        legacy = p.read(self.home / "config.json")
        legacy.pop("drive_enabled")  # a config.json written before the option existed
        p.write(self.home / "config.json", legacy)
        p.status_of("drive", status="confirmed", confirmed=T1)
        self.assertTrue(p.configuration()["drive_enabled"])  # migration: not chosen yet, but already in use
        p.configure(drive_enabled=False)
        self.assertFalse(p.configuration()["drive_enabled"])  # the saved choice always wins

    def test_disabled_drive_is_not_a_problem_and_keeps_what_it_holds(self):
        s = self.current()
        codes, r = self.codes(s, drive_enabled=False)
        self.assertEqual(codes["drive"], "disabled")
        self.assertEqual(codes["local"], "ok")
        self.assertEqual(set(r["places"]["drive"]["held"]), {"obsidian", "notion"})
        s["drive"].update(status="pending", message="Sem internet.", failed=T3)
        self.assertEqual(self.codes(s, drive_enabled=False)[0]["drive"], "disabled")  # no alarm for a copy the person turned off
        s["versions"][0]["drive"]["objects"] = 12
        self.assertEqual(self.codes(s)[1]["places"]["drive"]["held"]["obsidian"]["objects"], 12)

    def test_disabled_drive_uploads_nothing_but_a_requested_backup_still_finishes(self):
        p.update(versions=[version("o1", "obsidian", T0, T0), version("n1", "notion", T1, T1)])
        controller = p.Controller()
        with mock.patch.object(pd, "publish") as publish:
            p.configure(drive_enabled=False)
            controller.drive_cycle()
            publish.assert_not_called()
            p.configure(drive_enabled=True)
            publish.return_value = {"confirmed": T3}
            with mock.patch.object(p, "mark_version"):
                controller.drive_cycle()
            self.assertEqual(publish.call_count, 2)
        p.configure(drive_enabled=False)
        p.update(operation={"id": "r1", "status": "running", "started": T0, "targets": {"obsidian": "o1", "notion": "n1"}, "steps": {
            name: {"status": "done"} for name in p.WORKERS if name != "drive"}})
        controller.stop_event.wait = mock.Mock(side_effect=[False, True])
        controller.recovered = True
        with mock.patch.object(p, "foreground_busy", return_value=False), mock.patch.object(pd, "publish") as publish:
            controller.loop("drive", controller.drive_cycle, 10)
            publish.assert_not_called()
        op = p.state()["operation"]
        self.assertEqual((op["status"], op["steps"]["drive"]["status"]), ("completed", "done"))

    def test_automatic_drive_cycle_reports_activity_only_while_enabled(self):
        seen = []

        def cycle():
            seen.append(dict(p.ACTIVITY.get("drive") or {}))
        for enabled in (True, False):
            p.configure(enabled=True, drive_enabled=enabled)
            controller = p.Controller()
            controller.recovered = True
            controller.stop_event.wait = mock.Mock(side_effect=[False, True])
            with mock.patch.object(p, "foreground_busy", return_value=False):
                controller.loop("drive", cycle, 10)
            self.assertNotIn("drive", p.ACTIVITY)  # cleared when the cycle ends
        self.assertEqual(seen, [{"stage": "copying"}])  # the second loop (Drive off) never ran the cycle

    def capture(self, previous=None):
        return p.capture_vault(self.vault, self.home / "capture" / "obsidian", previous)
