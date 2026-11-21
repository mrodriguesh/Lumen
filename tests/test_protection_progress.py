"""Request identity, finite completion, truthful receipts and preserved settings."""
import concurrent.futures
import unittest
from unittest import mock

from tests import test_protection
from lumen import AppError, protection as p, server


class Progress(unittest.TestCase):
    setUp = test_protection.Protection.setUp
    tearDown = test_protection.Protection.tearDown

    def request(self):
        with mock.patch.object(p, "controller", mock.Mock(started=True)):
            return p.backup_now()["state"]["operation"]

    def test_accepted_is_running_and_does_not_change_settings_or_pause(self):
        before = p.configuration()
        op = self.request()
        self.assertEqual(op["status"], "running")
        self.assertEqual(op["steps"], {})
        self.assertNotIn("finished", op)
        self.assertEqual(p.configuration(), before)

    def test_concurrent_clicks_return_the_same_request(self):
        with mock.patch.object(p, "controller", mock.Mock(started=True)), mock.patch.object(p, "password", return_value=self.secret) as password:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(lambda _: p.backup_now()["state"]["operation"]["id"], range(20)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(password.call_count, 1)

    def test_success_requires_all_six_current_steps(self):
        op = self.request()
        for i, name in enumerate(p.WORKERS):
            p.status_of(name, status="confirmed", snapshot=name + "-copy")
            p.finish_step(op["id"], name)
            self.assertEqual(p.state()["operation"]["status"], "completed" if i == 5 else "running")
        self.assertEqual(p.state()["operation"]["targets"], {source: source + "-copy" for source in ("obsidian", "notion")})

    def test_failure_preserves_other_receipts_and_partial_is_not_success(self):
        op = self.request()
        receipt = {"path": "chosen", "confirmed": p.now()}
        p.update(versions=[{"id": "old", "source": "obsidian", "local": receipt, "drive": None}])
        for name in p.WORKERS:
            p.status_of(name, status="confirmed")
            p.finish_step(op["id"], name, "Conecte o Drive." if name == "drive" else None)
        self.assertEqual(p.state()["operation"]["status"], "partial")
        self.assertEqual(p.state()["versions"][0]["local"], receipt)
        self.assertFalse(p.configuration()["enabled"])
        oldid = op["id"]
        self.assertNotEqual(self.request()["id"], oldid)

    def test_previous_success_cannot_finish_a_new_request(self):
        for name in p.WORKERS: p.status_of(name, status="confirmed", confirmed="2020-01-01")
        op = self.request()
        self.assertEqual(op["status"], "running")
        p.finish_step("wrong-request", "drive")
        self.assertEqual(p.state()["operation"]["steps"], {})

    def test_later_automatic_change_does_not_extend_the_request(self):
        p.update(versions=[{"id": "old", "source": "obsidian"}, {"id": "target", "source": "notion"}, {"id": "later", "source": "obsidian"}])
        op = {"targets": {"obsidian": "old", "notion": "target"}}
        controller = p.Controller()
        with mock.patch.object(p, "deliver_local") as local, mock.patch.object(controller, "drive_cycle") as drive, mock.patch.object(controller, "mirror_cycle") as mirror, mock.patch.object(controller, "vault_mirror_cycle") as vault:
            for name in ("local", "drive", "obsidian_notion", "notion_obsidian"): controller.request_step(name, op)
        self.assertEqual([v["id"] for v in local.call_args.args[0]], ["old", "target"])
        self.assertEqual([v["id"] for v in drive.call_args.args[0]], ["old", "target"])
        mirror.assert_called_once_with("old")
        vault.assert_called_once_with("target")

    def test_restarted_controller_resumes_the_persisted_request_while_paused(self):
        op = self.request()
        controller = p.Controller(); controller.recovered = True
        controller.stop_event.wait = mock.Mock(side_effect=[False, True])
        def capture(): p.status_of("notion", status="captured", snapshot="saved")
        controller.loop("notion", capture, 30)
        self.assertEqual(p.state()["operation"]["id"], op["id"])
        self.assertEqual(p.state()["operation"]["targets"]["notion"], "saved")
        self.assertFalse(p.configuration()["enabled"])
        controller = p.Controller(); controller.stop_event.wait = mock.Mock(side_effect=[False, True])
        fn = mock.Mock()
        controller.loop("notion", fn, 30)
        fn.assert_not_called()

    def test_destinations_wait_for_source_attempts(self):
        self.request()
        controller = p.Controller(); controller.stop_event.wait = mock.Mock(side_effect=[False, True])
        with mock.patch.object(controller, "request_step") as step:
            controller.loop("drive", lambda: None, 10)
        step.assert_not_called()

    def test_no_sources_cannot_be_a_completed_backup(self):
        with self.assertRaises(AppError): p.Controller().request_step("local", {"targets": {}})
        checks = p.copies_current({}, p.configuration())
        self.assertFalse(any(checks.values()))

    def test_current_requires_latest_versions_and_readable_local_confirmation(self):
        c = p.configuration(); c["local"] = "chosen"
        s = {"versions": [{"id": source, "source": source, "partial": False, "local": {"path": "chosen", "confirmed": "2026-01-02"}, "drive": {"confirmed": "2026-01-02"}} for source in ("obsidian", "notion")], "local": {"status": "confirmed", "confirmed": "2026-01-03"}, "drive": {"status": "confirmed"}, "obsidian_notion": {"status": "confirmed", "source_snapshot": "obsidian"}, "notion_obsidian": {"status": "confirmed", "source_snapshot": "notion"}}
        s["local"]["source_versions"] = {source:source for source in ("obsidian", "notion")}
        self.assertTrue(all(p.copies_current(s, c).values()))
        s["local"]["confirmed"] = "2026-01-01"
        self.assertFalse(p.copies_current(s, c)["local"])
        self.assertTrue(p.copies_current(s, c)["drive"])
        s["versions"].append({"id": "new", "source": "notion", "partial": False, "local": None, "drive": None})
        checks = p.copies_current(s, c)
        self.assertFalse(checks["drive"])
        self.assertFalse(checks["notion_obsidian"])
        self.assertTrue(checks["obsidian_notion"])
        c["roots"] = ["newly-added-page"]
        self.assertFalse(p.copies_current(s, c)["notion_obsidian"])

    def test_changing_pages_marks_the_not_yet_read_selection_as_pending(self):
        h = mock.Mock(); h._json.return_value = {"action": "roots", "roots": ["12345678123412341234123456789abc"]}
        server._protection_action(h)
        self.assertEqual(p.state()["notion"]["status"], "pending")
        self.assertFalse(p.configuration()["enabled"])

    def test_cancelled_dialogs_are_explicit_and_preserve_configuration(self):
        before = p.configuration()
        for action in ("choose", "export-key", "import-key", "recover", "rebuild-notion"):
            h = mock.Mock(); h._json.return_value = {"action": action}
            with mock.patch.object(server, "_protection_dialog", return_value=""), mock.patch.object(server, "_protection_folder", return_value=""):
                self.assertTrue(server._protection_action(h)["cancelled"], action)
        self.assertEqual(p.configuration(), before)

    def test_page_titles_hide_ids_and_do_not_remove_inaccessible_pages(self):
        roots = ["a" * 32, "b" * 32]; p.configure(roots=roots)
        error = AppError("No access"); error.status = 403
        h = mock.Mock(); h._json.return_value = {"action": "page-titles"}
        page = {"properties": {"Title": {"type": "title", "title": [{"plain_text": "My notes"}]}}}
        with mock.patch.object(server, "_need_token", return_value=("fixture", {})), mock.patch.object(server.notion, "request", side_effect=[page, error]):
            result = server._protection_action(h)["page_titles"]
        self.assertEqual(result[roots[0]]["title"], "My notes")
        self.assertFalse(result[roots[1]]["accessible"])
        self.assertEqual(p.configuration()["roots"], roots)
