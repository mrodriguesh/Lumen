import math
import os
import struct
import tempfile
import types
import unittest
import wave
from unittest import mock

import numpy as np

from lumen import audio, transcribe


def tone(seconds, hz=220):
    t = np.arange(int(audio.SR * seconds)) / audio.SR
    return (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def peak_hz(x):
    spec = np.abs(np.fft.rfft(x[: audio.SR]))
    return int(np.argmax(spec) * audio.SR / (2 * (len(spec) - 1)))


class Tempo(unittest.TestCase):
    def test_duration_and_pitch(self):
        x = tone(4)
        for f in (2.0, 0.5):
            y = audio.tempo(x, f)
            self.assertAlmostEqual(len(y) / audio.SR, 4 / f, delta=0.15)
            self.assertAlmostEqual(peak_hz(y[audio.SR // 2:]), 220, delta=3)  # tom preservado

    def test_identity_and_empty(self):
        x = tone(1)
        self.assertIs(audio.tempo(x, 1), x)
        self.assertEqual(len(audio.tempo(np.zeros(0, dtype=np.float32), 0.5)), 0)


class SpeedTimestamps(unittest.TestCase):
    """Modo 2x: o modelo recebe o áudio desacelerado e os tempos voltam para a linha do tempo do arquivo."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(self.path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.SR)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 7))) for i in range(audio.SR * 10)))

    def tearDown(self):
        os.unlink(self.path)

    def run_with(self, speed):
        seen = {}

        class FakeModel:
            def transcribe(self, samples, **kw):
                seen["len"] = len(samples) / audio.SR
                d = seen["len"]  # começo, meio e fim do áudio que o modelo recebeu
                segs = [types.SimpleNamespace(start=a, end=b, text=t, avg_logprob=-0.2)
                        for a, b, t in ((0.0, 2.0, "início"), (d / 2 - 1, d / 2 + 1, "meio"), (d - 2, d, "fim"))]
                return iter(segs), types.SimpleNamespace(language="pt", duration=d)

        with mock.patch.object(transcribe, "downloaded", return_value=True), \
                mock.patch.object(transcribe, "_model", return_value=FakeModel()):
            out = transcribe.transcribe(self.path, "small", lambda *a: None, lambda: None, speed=speed)
        return seen["len"], out

    def test_normal(self):
        n, out = self.run_with(1.0)
        self.assertAlmostEqual(n, 10, delta=0.05)
        self.assertEqual([(s["start"], s["end"]) for s in out["segments"]], [(0, 2), (4, 6), (8, 10)])

    def test_2x_default_is_direct(self):
        n, out = self.run_with(2.0)  # benchmark: transcrever direto foi melhor que desacelerar
        self.assertAlmostEqual(n, 10, delta=0.05)
        self.assertEqual([(s["start"], s["end"]) for s in out["segments"]], [(0, 2), (4, 6), (8, 10)])

    def test_4x_natural_speed_maps_back(self):
        """4x preparado a 0,25x: o modelo recebe 40 s; começo, meio e fim voltam para 0–10 s do arquivo."""
        with mock.patch.object(transcribe, "PREP", {("small", 4): 0.25}):
            n, out = self.run_with(4.0)
        self.assertAlmostEqual(n, 40, delta=0.6)
        got = [(s["start"], s["end"]) for s in out["segments"]]
        for (a, b), (wa, wb) in zip(got, [(0, 0.5), (n / 8 - 0.25, n / 8 + 0.25), (10 - 0.5, 10)]):
            self.assertAlmostEqual(a, wa, delta=0.05)
            self.assertAlmostEqual(b, wb, delta=0.05)
        self.assertLessEqual(max(b for _, b in got), 10.01)  # nada passa do fim do arquivo

    def test_times_never_pass_file_end(self):
        class Over:
            def transcribe(self, samples, **kw):
                d = len(samples) / audio.SR
                return iter([types.SimpleNamespace(start=d - 1, end=d + 1.8, text="fim", avg_logprob=-0.1)]),                     types.SimpleNamespace(language="pt", duration=d)
        with mock.patch.object(transcribe, "downloaded", return_value=True),                 mock.patch.object(transcribe, "_model", return_value=Over()):
            out = transcribe.transcribe(self.path, "small", lambda *a: None, lambda: None, second=False)
        self.assertLessEqual(out["segments"][0]["end"], out["duration"] + 0.01)

    def test_2x_maps_back(self):
        with mock.patch.object(transcribe, "PREP", {("small", 2): 0.5}):
            n, out = self.run_with(2.0)
        self.assertAlmostEqual(n, 20, delta=0.3)  # desacelerado 0,5x
        starts = [s["start"] for s in out["segments"]]
        ends = [s["end"] for s in out["segments"]]
        for got, want in zip(starts + ends, [0, 4.5, 9, 1, 5.5, 10]):  # (9–11 s desacelerado) = (4,5–5,5 s no arquivo)
            self.assertAlmostEqual(got, want, delta=0.2)
        self.assertAlmostEqual(out["duration"], 10, delta=0.05)  # duração do arquivo, não do áudio processado


if __name__ == "__main__":
    unittest.main()
