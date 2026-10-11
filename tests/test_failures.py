"""Falhas durante a transcrição: o app informa e não fica preso (disco cheio, memória, erro do modelo, cancelamento)."""
import errno
import math
import os
import struct
import tempfile
import time
import unittest
import wave
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, jobs, store, transcribe
from tests.test_flow import wait


class Failures(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        fd, self.path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(self.path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 9))) for i in range(16000 * 2)))
        store.save_config({**store.DEFAULTS, "root_page_id": "x"})
        self.p = [mock.patch.object(store, "get_token", return_value="secret_test"),
                  mock.patch.object(transcribe, "speech_rate", return_value=2.2),
                  mock.patch.object(transcribe, "downloaded", return_value=True)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        os.unlink(self.path)

    def run_with(self, effect):
        with mock.patch.object(transcribe, "transcribe", side_effect=effect):
            jobs.start("process", jobs.process, {"kind": "file", "path": self.path, "speed": "auto"})
            return wait()

    def test_disk_full(self):
        j = self.run_with(OSError(errno.ENOSPC, "No space left on device"))
        self.assertEqual(j["status"], "error")
        self.assertIn("espaço", j["error"]["message"])

    def test_out_of_memory(self):
        j = self.run_with(MemoryError())
        self.assertIn("Memória insuficiente", j["error"]["message"])

    def test_model_error_is_reported(self):
        j = self.run_with(AppError("Memória insuficiente para transcrever.", "Escolha a qualidade “Rápido”."))
        self.assertEqual(j["status"], "error")
        self.assertIn("Rápido", j["error"]["action"])

    def test_unexpected_crash_does_not_hang(self):
        j = self.run_with(ValueError("conteúdo privado da aula"))
        self.assertEqual(j["status"], "error")
        self.assertNotIn("conteúdo privado", j["error"]["message"])  # mensagem genérica; nada da aula vaza

    def test_cancel_during_transcription(self):
        def slow(*a, **k):
            check = a[3]
            for _ in range(200):
                check()
                time.sleep(0.01)
        with mock.patch.object(transcribe, "transcribe", side_effect=slow):
            jobs.start("process", jobs.process, {"kind": "file", "path": self.path, "speed": "1"})
            time.sleep(0.2)
            jobs.cancel()
            self.assertEqual(wait()["status"], "cancelled")


class CudaFallback(unittest.TestCase):
    """Falha de CUDA antes do primeiro trecho (DLL ausente, VRAM cheia): tenta de novo na CPU."""

    def test_falls_back_to_cpu(self):
        import types
        import numpy as np
        calls = []

        class Model:
            def __init__(self, device):
                self.device = device

            def transcribe(self, samples, **kw):
                calls.append(self.device)
                if self.device == "cuda":
                    raise RuntimeError("CUDA failed with error out of memory")
                return iter([types.SimpleNamespace(start=0, end=1, text="ok", avg_logprob=-0.1)]), \
                    types.SimpleNamespace(language="pt", duration=1)
        # _vram: sem isso, a VRAM de verdade decide (com o Ollama ou um jogo usando a placa, ia direto para a CPU)
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "_vram", return_value=(12.0, 3.0)), \
                mock.patch.object(transcribe, "_model", side_effect=lambda name, device: Model(device)):
            out = transcribe._run(np.zeros(16000, dtype=np.float32), "large-v3-turbo", lambda *a: None, lambda: None,
                                  1.0, 1.0, 1.0, False)
        self.assertEqual(calls, ["cuda", "cpu"])
        self.assertEqual(out["device"], "cpu")


if __name__ == "__main__":
    unittest.main()


class AutoSpeed(unittest.TestCase):
    """Automático no large-v3: 1× e 2× dão a mesma transcrição, então a velocidade da fala sai dela (sem a passada extra
    de 120 s). Se faltar VRAM e o modelo for trocado por um sensível à velocidade, mede antes, como nos outros modos."""
    setUp, tearDown = Failures.setUp, Failures.tearDown

    def run_auto(self, fitted):
        store.save_config({**store.DEFAULTS, "root_page_id": "x", "quality": "maximo"})
        tr = {"segments": [{"start": 0.0, "end": 10.0, "text": " ".join(["palavra"] * 45)}], "language": "pt",
              "duration": 10.0, "device": "cuda", "second_opinion": False, "prep": 1.0, "compute": "int8_float16"}
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "make_room"), \
                mock.patch.object(transcribe, "fit_gpu", side_effect=lambda n: (n, None) if n == fitted else (fitted, "Pouca VRAM.")), \
                mock.patch.object(transcribe, "transcribe", return_value=tr) as t:
            jobs.start("process", jobs.process, {"kind": "file", "path": self.path, "speed": "auto"})
            return wait(), t

    def test_large_v3_measures_speech_in_its_own_transcript(self):
        j, t = self.run_auto("large-v3")
        transcribe.speech_rate.assert_not_called()
        self.assertEqual(t.call_args.args[1], "large-v3")
        self.assertEqual(t.call_args.kwargs["speed"], 1.0)
        self.assertEqual(j["result"]["speed"]["words_per_s"], 4.5)  # 45 palavras em 10 s de fala
        self.assertEqual(j["result"]["speed"]["used"], 2.0)         # sugere 2×; no large-v3 o resultado é o mesmo

    def test_swapped_model_measures_before(self):
        j, t = self.run_auto("large-v3-turbo")
        transcribe.speech_rate.assert_called_once()
        self.assertEqual(transcribe.speech_rate.call_args.args[1], "large-v3-turbo")
        self.assertEqual(t.call_args.args[1], "large-v3-turbo")
        self.assertEqual(j["result"]["speed"]["used"], 1.0)         # 2,2 palavras/s medidas antes
        self.assertIn("Pouca VRAM.", j["result"]["speed"]["warning"])
