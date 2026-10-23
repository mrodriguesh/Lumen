import json
import unittest
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, llm, understanding

# Nota de compreensão de um estudante (válida) e uma análise da IA já conferida (llm.validate_analysis).
NOTE = ("A fotossíntese é o processo em que a planta usa a luz do sol para transformar água e gás carbônico em "
        "glicose. A fase clara depende de luz e acontece dentro dos cloroplastos, liberando oxigênio no ar.")
ANALYSIS = {"acertos": ["Você explicou bem que a fase clara depende de luz."], "parciais": [],
            "lacunas": ["A clorofila, o pigmento verde que absorve a luz."], "confusoes": [], "complementos": [],
            "conexoes": [], "perguntas": ["O que acontece com a planta no escuro?"]}


def understood(key, text=NOTE):
    """Atalho dos testes do fluxo: o estudante escreveu a compreensão desta aula e a IA já a analisou."""
    if not understanding.load(key):
        understanding.start(key, "Aula", "Teste", {})
    understanding.prepared(key)
    understanding.submit(key, text)
    understanding.save_analysis(key, ANALYSIS, text, "m")


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
            out = llm.generate(self.segs, 75, "m", "pt", lambda: None, lambda *a: None, understanding=NOTE)
        self.assertEqual(out["title"], "Fotossíntese")
        self.assertEqual(chat.call_count, 2)

    def test_gives_up_after_two(self):
        with mock.patch.object(llm, "_chat", return_value='{"title": ""}'):
            with self.assertRaises(AppError):
                llm.generate(self.segs, 75, "m", "pt", lambda: None, lambda *a: None, understanding=NOTE)

    def test_long_transcript_map_reduce(self):
        segs = [{"start": i * 40, "end": i * 40 + 40, "text": "palavra " * 120} for i in range(100)]
        calls = []

        def fake(model, system, user, check, tokens, schema=None, num_ctx=0, **kw):
            calls.append(schema is not None)
            return json.dumps(GOOD) if schema else "[00:40] notas curtas"
        with mock.patch.object(llm, "_chat", side_effect=fake):
            llm.generate(segs, 4000, "m", "original", lambda: None, lambda *a: None, understanding=NOTE)
        self.assertGreater(calls.count(False), 1)  # partes resumidas
        self.assertEqual(calls[-1], True)          # passo final estruturado

    def test_notes_cut_at_the_ceiling_are_read_again_in_smaller_pieces(self):
        # revisão do Codex: uma resposta cortada no teto entrava como notas completas
        segs = [{"start": i * 40, "end": i * 40 + 40, "text": "palavra " * 120} for i in range(100)]
        sizes = []

        def fake(model, system, user, check, tokens, schema=None, num_ctx=0, on_cut=None, **kw):
            if schema:
                return json.dumps(GOOD)
            sizes.append(len(user))
            if on_cut and len(sizes) == 1:  # a 1ª parte não coube no teto
                on_cut()
            return "[00:40] notas"
        with mock.patch.object(llm, "_chat", side_effect=fake):
            lesson = llm.generate(segs, 4000, "m", "pt", lambda: None, lambda *a: None, understanding=NOTE)
        self.assertEqual(lesson["caveats"], [])  # lida de novo em pedaços menores: nada ficou de fora
        self.assertLess(sizes[1], sizes[0] * 0.6)  # a parte foi relida em pedaços menores

        made = []

        def always_cut(model, system, user, check, tokens, schema=None, num_ctx=0, on_cut=None, **kw):
            if schema:
                return json.dumps(GOOD)
            made.append(1)
            on_cut()
            return "[00:40] notas pela metade"
        with mock.patch.object(llm, "_chat", side_effect=always_cut):
            lesson = llm.generate(segs, 4000, "m", "pt", lambda: None, lambda *a: None, understanding=NOTE)
        self.assertIn("lida de forma incompleta", lesson["caveats"][0])  # avisa na página, não em silêncio
        # a IA se repetindo corta todas as partes: só MAX_SPLITS releituras (2 chamadas a mais cada), nunca 7× mais
        parts = len(llm.chunks(llm.transcript_text(segs)))
        self.assertLessEqual(len(made), parts + 2 * llm.MAX_SPLITS)

    def test_chat_reports_a_stream_that_stopped_at_the_ceiling(self):
        def stream(path, body, check):
            self.assertEqual(body["options"]["num_predict"], llm.MAX_OUT["notes"])
            yield {"message": {"content": "parte"}}
            yield {"done": True, "done_reason": "length"}
        cut = []
        with mock.patch.object(llm, "_stream", stream):
            llm._chat("m", "s", "u", lambda: None, lambda n: None, kind="notes", on_cut=lambda: cut.append(1))
        self.assertEqual(cut, [1])


if __name__ == "__main__":
    unittest.main()
