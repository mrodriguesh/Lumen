import contextlib
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, record, server, store


class Widget(unittest.TestCase):
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

    def setUp(self):
        store.save_config(store.DEFAULTS)

    def request(self, path, body=None, token=server.TOKEN):
        r = urllib.request.Request(self.url + path, headers={"X-Lumen-Token": token})
        if body is not None:
            r.data = json.dumps(body).encode()
        with urllib.request.urlopen(r) as response:
            return response.read()

    def test_widget_assets_and_token(self):
        html = self.request("/widget").decode()
        self.assertIn(server.TOKEN, html)
        self.assertNotIn("{{TOKEN}}", html)
        for name in ("widget.css", "widget.js"):
            self.assertTrue(self.request("/" + name))

    def test_closed_widget_connection_does_not_raise(self):
        handler = server.Handler.__new__(server.Handler)
        for name in ("send_response", "send_header", "end_headers"):
            setattr(handler, name, mock.Mock())
        handler.wfile = mock.Mock()
        for failure in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            handler.wfile.write.side_effect = failure
            handler._send(200, {"recording": {"active": False}})

    def test_default_left_and_settings_preserve_existing(self):
        store.save_config({**store.DEFAULTS, "ollama_model": "meu-modelo"})
        with mock.patch.object(server, "state", side_effect=lambda: {"config": store.load_config()}):
            self.assertEqual(store.load_config()["widget"], "left")
            for mode in ("right", "top", "bottom", "free", "off", "left"):
                cfg = json.loads(self.request("/api/settings", {"widget": mode}))["config"]
                self.assertEqual(cfg["widget"], mode)
                self.assertEqual(cfg["ollama_model"], "meu-modelo")
            self.request("/api/settings", {"widget": "invalid"})
            self.assertEqual(store.load_config()["widget"], "left")

    def test_widget_settings_are_lightweight_and_preserve_config(self):
        store.save_config({**store.DEFAULTS, "ollama_model": "meu-modelo", "root_page_title": "Meu curso"})
        with mock.patch.object(server, "state") as full_state, mock.patch.object(server, "set_autostart") as startup, mock.patch.object(store,"get_token",return_value="secret"):
            cfg = json.loads(self.request("/api/widget?view=settings"))["config"]
            self.assertEqual(cfg, store.load_config())
            result = json.loads(self.request("/api/settings?view=settings", {"widget": "top", "autostart": True,"keep_temp":True,"page_language":"original","quality":"maximo"}))
            saved = result["config"]
            self.assertEqual(saved, store.load_config())
            self.assertEqual((saved["widget"],saved["autostart"],saved["quality"],saved["page_language"],saved["keep_temp"]),("top",True,"maximo","original",True))
            self.assertTrue(result["has_token"])
            self.assertNotIn("secret",json.dumps(result))
            startup.assert_called_once_with(True)
            full_state.assert_not_called()
            self.assertEqual(store.load_config()["ollama_model"], "meu-modelo")
            self.assertEqual(store.load_config()["root_page_title"], "Meu curso")
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/api/widget?view=settings", token="bad")
        self.assertEqual(e.exception.code, 403)

    def test_clear_preserves_data_during_recording(self):
        with mock.patch.object(record,"status",return_value={"active":True}), mock.patch.object(store,"clear_local_data") as clear, mock.patch.object(store,"delete_token") as forget:
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.request("/api/clear",{"forget_token":True})
            self.assertEqual(e.exception.code,400)
            clear.assert_not_called()
            forget.assert_not_called()

    def test_autostart_error_does_not_save_success(self):
        with mock.patch.object(server, "set_autostart", side_effect=AppError("Permissão negada.", "Tente de novo.")):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.request("/api/settings", {"autostart": True})
            self.assertEqual(e.exception.code, 400)
            self.assertFalse(store.load_config()["autostart"])

    def test_autostart_rejects_non_boolean(self):
        with mock.patch.object(server, "set_autostart") as set_run:
            with self.assertRaises(urllib.error.HTTPError):
                self.request("/api/settings", {"autostart": "false"})
            set_run.assert_not_called()

    def test_registry_command_quoted_and_disable_idempotent(self):
        import winreg
        with mock.patch.object(winreg, "CreateKeyEx", return_value=contextlib.nullcontext("key")), \
             mock.patch.object(winreg, "SetValueEx") as write, \
             mock.patch.object(winreg, "DeleteValue", side_effect=FileNotFoundError):
            server.set_autostart(True)
            args = write.call_args.args
            self.assertEqual(args[:4], ("key", "Lumen", 0, winreg.REG_SZ))
            self.assertTrue(args[4].startswith('"'))
            self.assertTrue(args[4].endswith('Lumen.exe" --background'))
            server.set_autostart(False)

    def test_widget_uses_same_recorder_and_denies_bad_token(self):
        with mock.patch.object(record, "status", return_value={"active": True, "seconds": 12, "level": .3}):
            data = json.loads(self.request("/api/widget"))
            self.assertTrue(data["recording"]["active"])
            self.assertEqual(data["recording"]["seconds"], 12)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.request("/api/widget", token="bad")
        self.assertEqual(e.exception.code, 403)

    def test_widget_reports_download_error(self):
        error = {"message":"Download interrompido.","action":"Tente novamente."}
        with mock.patch.object(server.jobs,"snapshot",return_value={"status":"error","kind":"download","error":error}):
            self.assertEqual(json.loads(self.request("/api/widget"))["job"]["error"],error)


if __name__ == "__main__":
    unittest.main()
