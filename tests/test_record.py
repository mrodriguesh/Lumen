import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, record, sources


def fake_soundcard(amplitude):
    class Rec:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def record(self, numframes):
            time.sleep(0.005)
            t = np.arange(numframes) / record.RATE
            return np.stack([amplitude * np.sin(2 * np.pi * 220 * t)] * 2, axis=1).astype("float32")

    mic = types.SimpleNamespace(recorder=lambda **k: Rec())
    return types.SimpleNamespace(default_speaker=lambda: types.SimpleNamespace(name="Alto-falantes"),
                                 get_microphone=lambda **k: mic)


def run(amplitude, seconds=4):
    with mock.patch.dict(sys.modules, {"soundcard": fake_soundcard(amplitude)}):
        record.start("Aula: 1/2")
        while record.status()["seconds"] < seconds:
            time.sleep(0.01)
        return record.stop()


class Record(unittest.TestCase):
    def test_concurrent_start_uses_one_recorder(self):
        import threading
        failures = []
        def click():
            try:
                record.start("simultanea")
            except AppError:
                failures.append(True)
        with mock.patch.dict(sys.modules, {"soundcard": fake_soundcard(.3)}):
            threads = [threading.Thread(target=click) for _ in range(2)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual(len(failures), 1)
            self.assertTrue(record.status()["active"])
            record.discard()

    def test_slow_driver_does_not_return_or_delete_unfinished_wav(self):
        with mock.patch.object(record, "_thread", mock.Mock(is_alive=lambda: True)):
            for fn in (record.stop, record.discard):
                with self.assertRaises(AppError) as error:
                    fn()
                self.assertIn("finalizado", str(error.exception))

    def test_records_playable_wav(self):
        r = run(0.3)
        self.assertEqual(r["name"], "Aula 12.wav")  # caracteres proibidos removidos
        info = sources.probe(r["path"])
        self.assertGreaterEqual(info["duration"], 4)
        self.assertEqual(sources.resolve({"kind": "recording", "path": r["path"], "link": "youtu.be/dQw4w9WgXcQ"})["title"], "Aula 12")
        Path(r["path"]).unlink()

    def test_silence_is_rejected_and_deleted(self):
        with self.assertRaises(AppError) as e:
            run(0.0)
        self.assertIn("Nenhum som", str(e.exception))
        self.assertEqual(list((record.store.WORK / "uploads").glob("*Aula*")), [])

    def test_bad_link_rejected(self):
        r = run(0.3)
        with self.assertRaises(AppError):
            sources.resolve({"kind": "recording", "path": r["path"], "link": "javascript:alert(1)"})
        Path(r["path"]).unlink()

    def test_discard(self):
        with mock.patch.dict(sys.modules, {"soundcard": fake_soundcard(0.3)}):
            record.start("descartar")
            time.sleep(0.1)
            record.discard()
        self.assertFalse(record.status()["active"])
        self.assertEqual(list((record.store.WORK / "uploads").glob("*descartar*")), [])



class RecordingFlow(unittest.TestCase):
    """A gravação é apagada logo após a transcrição; a retomada funciona sem ela."""

    def test_deleted_after_transcription_and_retry_works(self):
        import json
        from lumen import jobs, llm, notion, store, transcribe
        from tests.fake_notion import Fake
        from tests.test_flow import wait
        from tests.test_llm import GOOD
        r = run(0.3)
        fake = Fake()
        root = fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": root})
        tr = {"segments": [{"start": 0, "end": 4, "text": "aula"}], "language": "pt", "duration": 4, "device": "cpu"}
        spec = {"kind": "recording", "path": r["path"], "course_id": "__none__", "mode": "new"}
        with mock.patch.object(store, "get_token", return_value="secret_test"), \
                mock.patch.object(transcribe, "pick", return_value=("rapido", {"name": "small", "size": "", "label": "Rápido"})), \
                mock.patch.object(transcribe, "transcribe", return_value=tr) as t, \
                mock.patch.object(transcribe, "speech_rate", return_value=2.6), \
                mock.patch.object(llm, "_chat", return_value=json.dumps(GOOD)):
            with mock.patch.object(notion, "API", "http://127.0.0.1:9/v1"), mock.patch("lumen.notion.time", mock.Mock()):
                jobs.start("process", jobs.process, spec)
                self.assertTrue(wait()["result"]["review"])
                self.assertTrue(Path(r["path"]).exists())  # mantida durante a revisão (permite retranscrever)
                jobs.start("process", jobs.finish, spec)
                self.assertEqual(wait()["status"], "error")  # Notion fora do ar
            self.assertFalse(Path(r["path"]).exists())  # revisão confirmada: gravação apagada
            jobs.start("process", jobs.finish, spec)  # “Tentar novamente”
            j = wait()
            self.assertEqual(j["status"], "done", j.get("error"))
            self.assertEqual(t.call_count, 1)  # não transcreveu de novo
        self.assertEqual(fake.violations, [])
        fake.close()

    def test_purge_old_uploads(self):
        import os
        from lumen import store
        old, new = run(0.3), run(0.3)
        os.utime(old["path"], (0, 0))
        store.purge_old_uploads(days=7)
        self.assertFalse(Path(old["path"]).exists())
        self.assertTrue(Path(new["path"]).exists())
        Path(new["path"]).unlink()


@unittest.skipUnless(sys.platform == "win32", "loopback real só no Windows")
class RealDevice(unittest.TestCase):
    def test_start_twice_from_new_threads(self):
        """Regressão: cada clique chega numa thread nova; a 2ª gravação falhava com 0x800401f0/0x88890005."""
        import threading
        try:
            import soundcard  # noqa: F401
        except Exception:
            self.skipTest("sem dispositivo de áudio")
        for _ in range(2):
            th = threading.Thread(target=record.start, args=("regressao",))
            th.start()
            th.join()
            time.sleep(0.6)
            st = record.status()
            record.discard()
            self.assertTrue(st["active"], st)
            self.assertIsNone(st["error"])


if __name__ == "__main__":
    unittest.main()
