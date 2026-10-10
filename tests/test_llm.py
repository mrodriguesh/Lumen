import json
import unittest
from unittest import mock

from lumen import AppError, llm

GOOD = {
    "title": "Fotossíntese", "summary": "Plantas produzem glicose.", "simple_explanation": "A planta cozinha com luz.",
    "topics": [{"title": "Fase clara", "explanation": "Depende de luz.", "timestamp": "[00:40]"},
               {"title": "Inventado", "explanation": "x", "timestamp": "99:00"}],
    "glossary": [{"term": "Clorofila", "definition": "Pigmento verde."}, {"term": "", "definition": "vazio"}],
    "examples": [{"text": "Planta no escuro", "origin": "aula"}, {"text": "x", "origin": "outro"}],
    "steps": [], "review_questions": [{"question": "Onde ocorre?", "answer": "Nos cloroplastos."}],
    "key_moments": [{"timestamp": "01:05", "label": "Exemplo"}, {"timestamp": "", "label": "sem tempo"}],
    "caveats": [],
}


class Text(unittest.TestCase):
    def test_transcript_groups_and_marks(self):
        segs = [{"start": 0, "end": 10, "text": "a"}, {"start": 10, "end": 31, "text": "b", "uncertain": True},
                {"start": 31, "end": 40, "text": "c"}]
        self.assertEqual(llm.transcript_text(segs), "[00:00] a (?) b\n[00:31] c")

    def test_transcript_without_times(self):
        self.assertEqual(llm.transcript_text([{"start": None, "end": None, "text": "só texto"}]), "só texto")

    def test_chunks_respect_size(self):
        text = "\n".join("x" * 50 for _ in range(1000)) + "\n" + "y" * 50_000
        parts = llm.chunks(text, 2000)
        self.assertTrue(all(len(p) <= 2001 for p in parts))
        self.assertEqual("".join(parts).replace("\n", ""), text.replace("\n", ""))

    def test_time_helpers(self):
        self.assertEqual(llm.fmt_time(3723), "1:02:03")
        self.assertEqual(llm.parse_time("[01:05]"), 65)
        self.assertIsNone(llm.parse_time("ontem"))


class Validate(unittest.TestCase):
    def test_cleans(self):
        out = llm.validate(GOOD, duration=75)
        self.assertEqual([t["timestamp"] for t in out["topics"]], [40, None])  # 99:00 > duração → descartado
        self.assertEqual(len(out["glossary"]), 1)
        self.assertEqual(len(out["examples"]), 1)
        self.assertEqual(out["key_moments"], [{"timestamp": 65, "label": "Exemplo"}])

    def test_no_times_when_transcript_has_none(self):
        out = llm.validate(GOOD, has_times=False)
        self.assertEqual(out["key_moments"], [])
        self.assertIsNone(out["topics"][0]["timestamp"])

    def test_rejects_incomplete(self):
        for bad in [None, [], {**GOOD, "review_questions": []}, {**GOOD, "summary": "  "}, {**GOOD, "topics": "x"}]:
            with self.assertRaises(AppError):
                llm.validate(bad)


class Generate(unittest.TestCase):
    segs = [{"start": 0, "end": 75, "text": "aula"}]

    def test_retries_malformed_once(self):
        with mock.patch.object(llm, "_chat", side_effect=["{quebrado", json.dumps(GOOD)]) as chat:
            out = llm.generate(self.segs, 75, "m", "pt", lambda: None, lambda *a: None)
        self.assertEqual(out["title"], "Fotossíntese")
        self.assertEqual(chat.call_count, 2)

    def test_gives_up_after_two(self):
        with mock.patch.object(llm, "_chat", return_value='{"title": ""}'):
            with self.assertRaises(AppError):
                llm.generate(self.segs, 75, "m", "pt", lambda: None, lambda *a: None)

    def test_long_transcript_map_reduce(self):
        segs = [{"start": i * 40, "end": i * 40 + 40, "text": "palavra " * 120} for i in range(100)]
        calls = []

        def fake(model, system, user, check, tokens, schema=None, num_ctx=0, **kw):
            calls.append(schema is not None)
            return json.dumps(GOOD) if schema else "[00:40] notas curtas"
        with mock.patch.object(llm, "_chat", side_effect=fake):
            llm.generate(segs, 4000, "m", "original", lambda: None, lambda *a: None)
        self.assertGreater(calls.count(False), 1)  # partes resumidas
        self.assertEqual(calls[-1], True)          # passo final estruturado


if __name__ == "__main__":
    unittest.main()
