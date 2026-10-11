import math
import os
import struct
import tempfile
import unittest
import wave
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, sources


class YouTube(unittest.TestCase):
    def test_accepts_common_links(self):
        for url in ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s", "youtu.be/dQw4w9WgXcQ?si=x",
                    "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ",
                    "https://www.youtube.com/live/dQw4w9WgXcQ", "https://www.youtube.com/embed/dQw4w9WgXcQ"]:
            self.assertEqual(sources.youtube_id(url), "dQw4w9WgXcQ", url)

    def test_rejects_others(self):
        for url in ["", "https://evil.com/watch?v=dQw4w9WgXcQ", "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
                    "javascript:alert(1)", "https://www.youtube.com/watch?v=short", "file:///C:/x.mp4",
                    "https://www.youtube.com/@canal"]:
            with self.assertRaises(AppError, msg=url):
                sources.youtube_id(url)

    def test_timestamp_url(self):
        self.assertEqual(sources.youtube_url("dQw4w9WgXcQ", 75.9), "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=75s")

    def test_lesson_link_normalizes_youtube_and_preserves_other_links(self):
        self.assertEqual(sources.lesson_link(" youtu.be/dQw4w9WgXcQ?si=x "),
                         "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(sources.lesson_link("example.com/aula"), "https://example.com/aula")
        self.assertIsNone(sources.lesson_link("  "))

    def test_lesson_link_rejects_invalid_or_incomplete_urls(self):
        for link in ("https://youtu.be/x", "https://youtube.com/@canal", "javascript:alert(1)",
                     "https://[broken", "https://user:secret@example.com/aula", "https://example.com/a ula"):
            with self.subTest(link=link), self.assertRaises(AppError):
                sources.lesson_link(link)

    def test_optional_link_for_all_local_sources(self):
        with mock.patch.object(sources, "probe", return_value={"duration": 60}), \
                mock.patch.object(sources, "file_key", return_value="file:test"):
            for kind in ("recording", "file", "telegram"):
                src = sources.resolve({"kind": kind, "path": "aula.wav", "link": "youtu.be/dQw4w9WgXcQ"})
                self.assertEqual(src["link"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
                self.assertNotIn("yt_id", src)  # a gravação pode começar no meio da aula


class Captions(unittest.TestCase):
    def test_srt(self):
        segs = sources.parse_captions("1\n00:00:01,500 --> 00:00:03,000\nOlá <i>turma</i>\n\n2\n00:01:02,000 --> 00:01:04,000\nSegunda &amp; última\n")
        self.assertEqual(segs, [{"start": 1.5, "end": 3.0, "text": "Olá turma"},
                                {"start": 62.0, "end": 64.0, "text": "Segunda & última"}])

    def test_vtt_rolling_dedupe(self):
        vtt = ("WEBVTT\n\n00:00.000 --> 00:02.000\nlinha um\n\n00:02.000 --> 00:04.000\nlinha um\nlinha dois\n\n"
               "00:04.000 --> 00:06.000 align:start\nlinha dois\nlinha três\n")
        self.assertEqual([s["text"] for s in sources.parse_captions(vtt)], ["linha um", "linha dois", "linha três"])

    def test_youtube_panel_paste(self):
        segs = sources.parse_captions("0:00\nOlá pessoal\n0:05\nhoje vamos ver\nfunções\n1:02:03 fim da aula")
        self.assertEqual([(s["start"], s["text"]) for s in segs],
                         [(0, "Olá pessoal"), (5, "hoje vamos ver funções"), (3723, "fim da aula")])
        self.assertEqual(segs[0]["end"], 5)

    def test_plain_text(self):
        segs = sources.parse_captions("Só texto sem marcas.\nOutra linha.")
        self.assertEqual(segs, [{"start": None, "end": None, "text": "Só texto sem marcas. Outra linha."}])

    def test_empty(self):
        with self.assertRaises(AppError):
            sources.parse_captions("  \n ")


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _wav(self, name="a.wav", seconds=1):
        p = os.path.join(self.dir, name)
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 10))) for i in range(16000 * seconds)))
        return p

    def test_probe_wav(self):
        info = sources.probe(self._wav())
        self.assertAlmostEqual(info["duration"], 1, places=1)
        self.assertEqual(info["format"], "WAV (PCM)")

    def test_invalid_file(self):
        p = os.path.join(self.dir, "falso.mp4")
        with open(p, "w") as f:
            f.write("não é vídeo")
        with self.assertRaises(AppError) as e:
            sources.probe(p)
        self.assertIn("Não foi possível ler", str(e.exception))

    def test_unsupported_and_missing(self):
        p = os.path.join(self.dir, "x.avi")
        open(p, "w").close()
        with self.assertRaises(AppError):
            sources.probe(p)
        with self.assertRaises(AppError):
            sources.probe(os.path.join(self.dir, "nao_existe.mp4"))

    def test_key_ignores_name(self):
        a = self._wav("a.wav")
        b = os.path.join(self.dir, "b.wav")
        with open(a, "rb") as f, open(b, "wb") as g:
            g.write(f.read())
        self.assertEqual(sources.file_key(a), sources.file_key(b))


if __name__ == "__main__":
    unittest.main()
