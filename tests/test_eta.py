"""Estimativa do tempo que falta: aprende com as medidas deste PC e corrige durante cada etapa."""
import unittest
from unittest import mock

import json

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import eta, llm, store
from tests.test_llm import GOOD


class Learn(unittest.TestCase):
    def setUp(self):
        (store.DATA / "tempos.json").unlink(missing_ok=True)

    def test_median_of_what_this_pc_measured(self):
        self.assertEqual(eta.value("chart_s"), eta.PRIOR["chart_s"])
        for v in (4.0, 50.0, 6.0):  # uma medida fora do comum não puxa a estimativa
            eta.learn("chart_s", v)
        self.assertEqual(eta.value("chart_s"), 6.0)
        for v in range(1, 30):
            eta.learn("chart_s", v)
        self.assertEqual(eta.value("chart_s"), 22)  # só as últimas 15 medidas

    def test_llm_speed_comes_from_ollama_itself(self):
        eta.learn_llm("m", "lesson", {"prompt_eval_count": 1000, "prompt_eval_duration": 0.5e9, "eval_count": 2000,
                                      "eval_duration": 40e9, "load_duration": 3e9}, chars=3000)
        self.assertEqual((eta.value("llm_prompt_tps", "m"), eta.value("llm_gen_tps", "m"),
                          eta.value("chars_per_token", "m")), (2000, 50, 3))
        self.assertAlmostEqual(eta.value("out_lesson", "m"), 2000 / (1300 + 0.25 * 1000), places=3)  # este PC × a forma
        self.assertAlmostEqual(eta.out_tokens("m", "lesson", 1000), 2000, delta=1)
        self.assertAlmostEqual(eta.llm_seconds("m", 3000, "lesson"), 1.5 + 0.5 + 40, delta=0.1)
        self.assertGreater(eta.out_tokens("m", "lesson", 9000), eta.out_tokens("m", "lesson", 1000))  # aula maior
        self.assertEqual(eta.out_tokens("m", "lesson", 10 ** 6), llm.MAX_OUT["lesson"])  # nunca além do teto
        self.assertEqual(eta.value("llm_gen_tps", "outro"), eta.PRIOR["llm_gen_tps"])  # cada modelo, o seu

    def test_each_answer_has_a_ceiling_and_feeds_the_estimate(self):
        # notas de uma aula longa passaram de 9 min numa só parte: sem teto, a IA repetia até encher o contexto
        sent = []

        def stream(path, body, check):
            sent.append(body)
            yield {"message": {"content": "{}"}}
            yield {"done": True, "eval_count": 300, "eval_duration": 6e9, "prompt_eval_count": 100,
                   "prompt_eval_duration": 1e8}
        plan = eta.current = eta.Plan([("notes", 10), ("lesson", 20)])
        try:
            with mock.patch.object(llm, "_stream", stream):
                self.assertEqual(llm._chat("m", "s", "u", lambda: None, lambda n: None, kind="notes"), "{}")
                llm._chat("m", "s", "u", lambda: None, lambda n: None)
                llm._chat("m", "s", "u", lambda: None, lambda n: None, limit=50)
        finally:
            eta.current = None
        self.assertEqual([b["options"].get("num_predict") for b in sent], [llm.MAX_OUT["notes"], None, 50])
        self.assertEqual(plan.name(), "notes")  # a resposta avançou a estimativa para a sua etapa
        self.assertEqual((round(eta.out_tokens("m", "notes", 100)), eta.value("llm_gen_tps", "m")), (300, 50))

    def test_calls_predict_the_rounds_the_summary_will_need(self):
        # revisão do Codex: o fator de correção virava “tokens”: 200 mil caracteres previam 11 chamadas, e eram 15
        segs = [{"start": i, "text": "palavra " * 60} for i in range(420)]  # ~200 mil caracteres
        eta.learn("chars_per_token", 3, "m")
        made = []

        def fake(model, system, user, check, tokens, schema=None, num_ctx=0, **kw):
            if schema:
                made.append("lesson")
                return json.dumps(GOOD)
            made.append("notes")
            # notas do tamanho que a estimativa espera de cada parte (a IA escrevendo o que se prevê dela)
            return "n" * int(eta.out_tokens("m", "notes", (len(user) + len(llm.NOTES)) / 3) * 3)
        with mock.patch.object(llm, "_chat", side_effect=fake):
            llm.generate(segs, 400, "m", "pt", lambda: None, lambda *a: None)
        self.assertEqual([k for k, _ in llm.calls(segs, "m")], made)
        self.assertGreater(made.count("notes"), 10)
        self.assertEqual(len(llm.calls(segs[:40], "m")), 1)

    def test_long_lesson_is_read_in_parts(self):
        segs = [{"start": i, "text": "palavra " * 50} for i in range(200)]  # ~80 mil caracteres
        self.assertEqual([k for k, _ in llm.calls(segs, "m")], ["notes"] * 5 + ["lesson"])
        self.assertEqual([k for k, _ in llm.calls(segs[:10], "m")], ["lesson"])


class Plan(unittest.TestCase):
    def test_counts_down_and_corrects_itself(self):
        clock = [100.0]
        with mock.patch("time.monotonic", lambda: clock[0]):
            p = eta.Plan([("notes", 30), ("notes", 30), ("lesson", 40), ("publish", 5)])
            self.assertEqual(p.left(), 105)
            p.at("notes")
            clock[0] += 10
            self.assertEqual(p.left(), 95)
            p.at("notes")  # a 2ª parte, não a 1ª de novo
            self.assertEqual(p.left(), 75)
            clock[0] += 60  # passou da estimativa: ainda falta um pouco, nunca 0 enquanto não termina
            self.assertEqual(p.left(), 4.5 + 45)
            p.at("lesson")
            p.update(12)  # a própria etapa sabe quanto falta (tokens escritos, progresso)
            clock[0] += 2
            self.assertEqual(p.left(), 10 + 5)
            p.at("lesson")  # 2ª tentativa da IA: a mesma etapa de novo
            self.assertEqual(p.left(), 45)
            p.progress(0.5)  # na metade depois de 0 s: o ritmo diz que falta o mesmo tanto
            self.assertEqual(p.left(), 5)


if __name__ == "__main__":
    unittest.main()
