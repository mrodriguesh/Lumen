"""Modo escuta (lumen/listening.py): falas → texto → Notion e Obsidian iguais, sem perder nem repetir trechos quando um
destino falha por um tempo. Som, VAD e transcrição são simulados; o Notion é o servidor falso dos outros testes."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import tests  # noqa: F401 — dados do app isolados
from lumen import listening, store
from lumen.study.call import EnergyVAD
from tests.fake_notion import Fake


def tone(seconds, amp=0.3):
    t = np.arange(int(48000 * seconds)) / 48000
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class Script:
    """Um aparelho de som de mentira: entrega o roteiro em blocos e depois silêncio, até a escuta parar."""

    def __init__(self, pieces):
        self.audio = np.concatenate(pieces)

    def __call__(self):
        return self

    def __enter__(self):
        self.at = 0
        return self

    def __exit__(self, *a):
        return False

    def record(self, numframes):
        time.sleep(0.001)
        out = self.audio[self.at:self.at + numframes]
        self.at += numframes
        return out if out.size == numframes else np.zeros(numframes, np.float32)


class Segments(unittest.TestCase):
    def test_speech_between_silences_becomes_one_utterance_with_its_start(self):
        seg, out, t = listening.Segmenter(EnergyVAD()), [], 0.0
        x = np.concatenate([np.zeros(16000), tone(1.5)[::3], np.zeros(16000)])
        for i in range(0, len(x) - 511, 512):
            t += 512 / 16000
            r = seg.feed(x[i:i + 512], t)
            if r:
                out.append(r)
        self.assertEqual(len(out), 1)
        t0, audio = out[0]
        self.assertAlmostEqual(t0, 1.0 - listening.PREROLL * 512 / 16000, delta=0.1)
        self.assertGreater(len(audio) / 16000, 1.5)

    def test_noise_shorter_than_a_word_is_dropped(self):
        seg, t = listening.Segmenter(EnergyVAD()), 0.0
        x = np.concatenate([np.zeros(8000), tone(0.15)[::3], np.zeros(32000)])
        hits = []
        for i in range(0, len(x) - 511, 512):
            t += 512 / 16000
            hits.append(seg.feed(x[i:i + 512], t))
        self.assertFalse(any(hits))


class Session(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.root = self.fake.add_page("Cursos")
        self.vault = Path(tempfile.mkdtemp(prefix="cofre-"))
        (self.vault / ".obsidian").mkdir()
        cfg = store.load_config()
        self.old_cfg = dict(cfg)
        store.save_config({**cfg, "root_page_id": self.root, "obsidian_vault": str(self.vault)})
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test")]
        for p in self.patches:
            p.start()
        listening._hidden_file().unlink(missing_ok=True)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        store.save_config(self.old_cfg)
        self.fake.close()

    def run_call(self, mic, system, transcriber, before_stop=None):
        s = listening.Session(sources={"mic": Script(mic), "system": Script(system)}, transcriber=transcriber,
                              vad_factory=EnergyVAD)
        s.start()
        deadline = time.monotonic() + 20
        want = sum(1 for p in mic + system if p.any()) // 1
        while time.monotonic() < deadline and len(s.segments) < want:
            time.sleep(.05)
        if before_stop:
            before_stop(s)
        s.stop()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not s.finished():
            time.sleep(.05)
        self.assertTrue(s.finished(), s.view())
        return s

    def notion_lines(self, s):
        page = self.fake.pages[s.sinks["notion"].page]
        return [listening._plain(b) for b in page["blocks"]][1:]  # o 1º bloco é a linha de apresentação

    def obsidian_lines(self, s):
        text = s.sinks["obsidian"].path.read_text("utf-8").split("*Transcrição ao vivo pelo Lúmen: microfone e som do PC.*", 1)[1]
        return [x.strip() for x in text.split("\n") if x.strip() and x.strip() != "---"]

    def test_both_sides_reach_notion_and_obsidian_identically_despite_failures(self):
        said = iter(f"Frase {i}" for i in range(1, 20))
        texts = lambda audio, lang: (next(said), "pt")
        gap = np.zeros(int(48000 * 1.2), np.float32)
        mic = [gap, tone(1.0), gap, tone(1.2), gap]
        system = [gap, gap, tone(0.9, .25), gap, tone(1.1, .25), gap]
        self.fake.lose_reply = 1  # o 1º envio é gravado, mas a resposta se perde: não pode repetir o trecho
        real_push, fails = listening.ObsidianSink.push, [2]

        def flaky(sink, batch):  # a nota fica presa (ex.: antivírus ou sincronização) duas vezes
            if fails[0]:
                fails[0] -= 1
                raise OSError("arquivo em uso")
            return real_push(sink, batch)

        def outage(s):  # o Notion recusa por um tempo; as falas esperam no diário
            self.fake.fail_append = True
            time.sleep(1.5)
            self.fake.fail_append = False

        with mock.patch.object(listening.ObsidianSink, "push", flaky):
            s = self.run_call(mic, system, texts, before_stop=outage)
        expected = [listening.line(x) for x in s.segments]
        self.assertEqual(len([x for x in s.segments if not x.get("end")]), 4)
        self.assertEqual({x["who"] for x in s.segments if not x.get("end")}, {"mic", "system"})
        self.assertEqual(self.notion_lines(s), expected)
        obs = [x.replace("**", "").replace("*", "").rstrip(".") for x in self.obsidian_lines(s)]
        self.assertEqual([x.replace("  ", " ") for x in obs], [x.replace("  ", " ") for x in expected])
        self.assertTrue(expected[-1].startswith("Fim da escuta"))
        self.assertEqual(self.fake.violations, [])
        # a página da chamada fica dentro de “Chamadas”, e “Chamadas” não aparece como curso
        from lumen import notion
        parent = self.fake.pages[s.sinks["notion"].page]["parent"]
        self.assertEqual(self.fake.pages[parent]["title"], "Chamadas")
        self.assertNotIn("Chamadas", [c["title"] for c in notion.list_courses("secret_test", self.root)])

    def test_echo_of_the_other_side_on_the_microphone_is_written_once(self):
        gap = np.zeros(int(48000 * 1.2), np.float32)
        same = lambda audio, lang: ("Bom dia, tudo certo com o projeto?", "pt")
        s = self.run_call([gap, tone(1.0, .2), gap], [gap, tone(1.0), gap], same)
        self.assertEqual(len([x for x in s.segments if not x.get("end")]), 1)

    def test_no_audio_device_fails_to_start_and_creates_nothing(self):
        class Broken:
            def __enter__(self):
                raise OSError("sem aparelho")

            def __exit__(self, *a):
                return False

        s = listening.Session(sources={"mic": Broken, "system": Broken}, transcriber=lambda a, l: ("x", None),
                              vad_factory=EnergyVAD)
        with self.assertRaises(listening.AppError):
            s.start()
        time.sleep(.3)
        self.assertEqual([p for p in self.fake.pages.values() if p["title"] != "Cursos"], [])
        self.assertFalse((self.vault / "Chamadas").exists())


if __name__ == "__main__":
    unittest.main()
