"""Fase 5 do Study AI 2.0: spec do diagrama (validação, tetos, rótulos, a mesma spec no SVG e no GIF/PNG), modelo do
estudante (flashcards, questionário e checagem mudam o nível; aparece e se apaga em Seus dados), explicação por nível
de esforço e mapa mental no chat. Dados isolados; Ollama falso."""
import threading
import time
import unittest
from unittest import mock

import tests  # noqa: F401
from lumen import visual3d
from lumen.study import agent, api, chats, data, db, diagram, explain, index, learn, mastery, registry, search, settings
from tests import test_study_index as idx
from tests.fake_ollama import FakeOllama

STEPS = {"family": "processo", "title": "Como o sono consolida a memória",
         "nodes": [{"label": "Codificação", "detail": "O hipocampo grava o que você viveu.", "parent": -1},
                   {"label": "Sono profundo", "detail": "As ondas lentas reativam a lembrança.", "parent": -1},
                   {"label": "Neocórtex", "detail": "A lembrança passa a ficar no córtex.", "parent": -1}],
         "relations": [{"from": 0, "to": 2, "kind": "leva a"}]}
EXTRAS = {"diagram": STEPS, "check": {"question": "Por que dormir depois de estudar ajuda a lembrar?",
                                      "answer": "Porque o sono profundo reativa e consolida a memória."},
          "cards": [{"question": "O que consolida a memória?", "answer": "O sono profundo.", "explanation": "Ondas lentas.", "source": "S1"},
                    {"question": "Onde a lembrança fica depois?", "answer": "No neocórtex.", "explanation": "", "source": "geral"}],
          "summary": ["O hipocampo grava.", "O sono reativa.", "O córtex guarda."]}
MIND = {"center": "Memória", "branches": [
    {"label": "Tipos", "detail": "Curto e longo prazo.", "children": [{"label": "Trabalho", "detail": "Segura o agora."},
                                                                       {"label": "Longo prazo", "detail": "Dura anos."}]},
    {"label": "Sono", "detail": "Consolida o que foi estudado.", "children": []},
    {"label": "Atenção", "detail": "Escolhe o que entra.", "children": [{"label": "Foco", "detail": ""}]}], "sources": ["S1", "S7"]}


def run_turn(payload):
    events = list(agent.turn(payload, "turn-" + str(time.monotonic_ns())))
    for t in threading.enumerate():
        if t.name == "Lumen study after":
            t.join(10)
    return events


class Spec(unittest.TestCase):
    def test_every_family_builds_and_passes_the_hologram_check(self):
        cases = {
            "processo": STEPS,
            "linha": {**STEPS, "family": "linha"},
            "ciclo": {**STEPS, "family": "ciclo"},
            "estrutura": {**STEPS, "family": "estrutura"},
            "conceitos": {**STEPS, "family": "conceitos"},
            "sistema": {**STEPS, "family": "sistema"},
            "comparacao": {"family": "comparacao", "title": "Behaviorismo × cognitivismo", "relations": [],
                           "nodes": [{"label": "Behaviorismo", "detail": "", "parent": -1}, {"label": "Cognitivismo", "detail": "", "parent": -1},
                                     {"label": "Reforço", "detail": "", "parent": 0}, {"label": "Sem lado", "detail": "", "parent": 7},
                                     {"label": "Memória", "detail": "", "parent": 1}]},
        }
        for fam, raw in cases.items():
            with self.subTest(fam):
                d = diagram.build(raw, "memória e sono", ["S1", "S99x", "geral"])
                self.assertEqual(d["family"], fam)
                self.assertEqual(set(d), visual3d._KEYS)  # os mesmos campos da spec do holograma
                self.assertEqual(d["evidence"], ["S1", "geral"])
                visual3d.validate(diagram.to_visual(d))
        ring = diagram.build({**STEPS, "family": "ciclo"}, "x")
        self.assertIn({"a": 2, "b": 0, "kind": "sequencia"}, ring["links"])  # o ciclo volta ao começo
        cmp = diagram.build(cases["comparacao"], "teorias")
        self.assertEqual([(n["label"], n["role"], n["parent"]) for n in cmp["nodes"]],
                         [("Behaviorismo", "a", -1), ("Cognitivismo", "b", -1), ("Reforço", "a", 0), ("Memória", "b", 1)])
        self.assertIn({"a": 0, "b": 2, "kind": "leva a"}, diagram.build(STEPS, "x")["links"])

    def test_caps_and_clean_labels(self):
        raw = {"family": "conceitos", "title": "t" * 300, "relations": [],
               "nodes": [{"label": f"Parte {i} " + "muito longa " * 10, "detail": "x" * 900 + "\x07", "parent": -1} for i in range(40)]}
        d = diagram.build(raw, "assunto 🙂")
        self.assertEqual(len(d["nodes"]), diagram.MAX_NODES)
        self.assertEqual(d["more"], 40 - diagram.MAX_NODES)
        self.assertTrue(all(len(n["label"]) <= visual3d.MAX_LABEL and n["label"].endswith("…") for n in d["nodes"]))
        self.assertTrue(all(len(n["detail"]) <= diagram.MAX_DETAIL and "\x07" not in n["detail"] for n in d["nodes"]))
        self.assertEqual(d["concept"], "assunto")  # sem emoji
        self.assertLessEqual(len(d["title"]), visual3d.MAX_TITLE)
        v = diagram.to_visual(d)
        self.assertEqual(len(v["nodes"]), visual3d.MAX_NODES)  # o holograma mostra só o que cabe na cena
        self.assertEqual(v["more"], 40 - visual3d.MAX_NODES)
        sch = diagram.schema()
        self.assertEqual(sch["properties"]["nodes"]["maxItems"], 8)  # todo array tem teto (D18)
        self.assertEqual(sch["properties"]["nodes"]["minItems"], 3)  # medido: sem piso, o 4b mandou um processo de 1 parte
        numbered = {**STEPS, "nodes": [{**n, "label": f"{i + 1}. {n['label']}"} for i, n in enumerate(STEPS["nodes"])]}
        self.assertEqual([n["label"] for n in diagram.build(numbered, "x")["nodes"]], ["Codificação", "Sono profundo", "Neocórtex"])
        self.assertTrue(all("maxItems" in x for x in (sch["properties"]["relations"], diagram.mind_schema(["S1"])["properties"]["branches"])))

    def test_validate_refuses_anything_else(self):
        good = diagram.build(STEPS, "memória")
        bad = [
            lambda d: d.update(code="alert(1)"),
            lambda d: d.update(family="holograma"),
            lambda d: d["nodes"][1].update(parent=1),  # parte que aponta para si (ou para depois): ciclo de pais
            lambda d: d["nodes"][0].update(label="x" * 80),
            lambda d: d["nodes"][0].update(detail=7),
            lambda d: d["links"].append({"a": 0, "b": 9, "kind": "hub"}),
            lambda d: d["links"].append({"a": 0, "b": 1, "kind": "explode"}),
            lambda d: d.update(evidence=["S1", "../segredo"]),
            lambda d: d["nodes"][0].update(role="item"),
        ]
        for i, change in enumerate(bad):
            with self.subTest(i):
                d = {**good, "nodes": [dict(n) for n in good["nodes"]], "links": [dict(x) for x in good["links"]]}
                change(d)
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    diagram.validate(d)
        deep = diagram.from_mind(MIND, "memória", {"S1": {}})
        deep["nodes"][1]["parent"] = 0
        deep["nodes"][2]["parent"] = 1  # neto: o mapa mental tem só ramos e filhos
        with self.assertRaises(ValueError):
            diagram.validate(deep)

    def test_mind_map_spec_and_png(self):
        d = diagram.from_mind(MIND, "memória", {"S1": {}})
        self.assertEqual(d["family"], "mapa")
        self.assertEqual(d["evidence"], ["S1"])  # S7 não foi recuperada
        self.assertEqual([(n["label"], n["parent"]) for n in d["nodes"]],
                         [("Tipos", -1), ("Trabalho", 0), ("Longo prazo", 0), ("Sono", -1), ("Atenção", -1), ("Foco", 4)])
        self.assertEqual(diagram.to_mind(d)["branches"][0], {"label": "Tipos", "emoji": "", "children": ["Trabalho", "Longo prazo"]})
        with mock.patch("lumen.mindmap.render", return_value=b"\x89PNG mapa") as render:
            self.assertEqual(diagram.image(d), (b"\x89PNG mapa", "image/png"))  # mapa mental: o PNG do mindmap (Edge)
        self.assertEqual(render.call_args[0][0]["center"], "Memória")
        with mock.patch("lumen.mindmap.render", return_value=None):  # sem Edge: a cena do holograma
            png, kind = diagram.image(d)
        self.assertTrue(png.startswith(b"\x89PNG") and kind == "image/png")

    def test_same_spec_makes_the_gif(self):
        d = diagram.build(STEPS, "memória e sono")
        with mock.patch.object(visual3d, "ATTEMPTS", ((480, 270, 8),)):
            gif, kind = diagram.image(d, "gif")
        self.assertEqual(kind, "image/gif")
        self.assertTrue(gif.startswith(b"GIF89a"))
        png, kind = diagram.image(d, "png")
        self.assertTrue(png.startswith(b"\x89PNG"))


class Core(idx.Base):
    def setUp(self):
        super().setUp()
        self.ollama = FakeOllama()
        self.note("B02 Estudos/Memória e sono.md", "---\ntype: permanent\n---\n# Memória e sono\nA consolidação da memória depende do sono profundo.")
        index.sync("obsidian")
        index.embed_missing()
        temp = set(chats.TEMP)  # a conversa temporária vive no processo: não pode vazar para outros testes
        self.addCleanup(lambda: [chats.TEMP.pop(k, None) for k in set(chats.TEMP) - temp])

    def tearDown(self):
        self.ollama.close()
        super().tearDown()


class Mastery(Core):
    def deck(self, topic="memória e sono"):
        it = learn.save("flashcards", f"Flashcards · {topic}", {"cards": [], "topic": topic, "sources": []})
        learn.add_cards(it["id"], [{"question": "O que consolida?", "answer": "O sono.", "source": {"sid": "geral"}}])
        return db.value("SELECT id FROM flashcards WHERE deck = ?", it["id"])

    def test_flashcards_and_quiz_change_the_level(self):
        self.assertIn("ainda não praticou", mastery.prompt("sono e memória"))
        card = self.deck()
        for _ in range(3):
            learn.review(card, 2)  # Bom
        m = mastery.find("Memória e Sono")
        self.assertEqual((m["correct"], m["wrong"], m["level"]), (3, 0, "domina"))
        self.assertGreater(m["next_review"], db.now())  # a próxima revisão vem do SM-2
        self.assertIn("domina", mastery.prompt("como o sono ajuda a memória"))
        self.assertEqual(learn.due()["topics"], [])  # domina e a revisão não chegou: nada a sugerir
        learn.review(card, 0)  # Errei
        quiz = learn.save("quiz", "Questionário · memória e sono", {"topic": "memória e sono", "sources": [], "questions": [
            {"kind": "vf", "question": "Sono consolida?", "options": ["Verdadeiro", "Falso"], "answer": "Verdadeiro", "explanation": ""}]})
        learn.answer(quiz["id"], 0, "Falso")
        m = mastery.find("memória e sono")
        self.assertEqual((m["correct"], m["wrong"], m["level"]), (3, 2, "aprendendo"))
        self.assertEqual(db.loads(m["origin"]), {"flashcard": 4, "quiz": 1})
        self.assertIn("aprendendo", mastery.prompt("memória e sono"))
        self.assertIsNone(mastery.find("behaviorismo de Skinner"))  # assunto sem palavras em comum

    def test_check_grades_and_records(self):
        self.ollama.json_replies["Você corrige respostas"] = {"correct": False, "score": 0.2, "feedback": "Faltou o porquê."}
        meta = {"explain": {"topic": "memória e sono", "check": {"question": "Por quê?", "answer": "Porque o sono consolida."}}}
        prov = agent.providers.chain()[0][0]
        r = explain.grade(meta, "Não sei", prov)
        self.assertEqual((r["correct"], r["expected"]), (False, "Porque o sono consolida."))
        self.assertEqual(mastery.find("memória e sono")["wrong"], 1)
        self.assertEqual(learn.due()["topics"], [{"label": "memória e sono", "level": "dificuldade", "due": False}])  # sugere revisar
        with self.assertRaises(agent.AppError):
            explain.grade({"explain": {"topic": "x"}}, "resposta", prov)  # sem checagem

    def test_visible_and_erasable_in_your_data(self):
        mastery.record("memória e sono", True, "check")
        inv = data.inventory()
        cat = next(c for c in inv["categories"] if c["key"] == "mastery")
        self.assertEqual((cat["label"], cat["count"]), ("O que o Lúmen sabe que você domina", 1))
        self.assertEqual(inv["mastery"][0]["label"], "memória e sono")
        self.assertEqual(data.export()["mastery"][0]["correct"], 1)
        self.assertEqual(data.delete("mastery"), 1)
        self.assertEqual(db.value("SELECT COUNT(*) FROM mastery"), 0)
        p = chats.save_project({"name": "Inglês"})
        mastery.record("phrasal verbs", True, "quiz", p["id"])
        chats.delete_project(p["id"])  # o projeto apagado leva o domínio dele
        self.assertEqual(db.value("SELECT COUNT(*) FROM mastery"), 0)

    def test_hard_is_not_a_hit_and_similar_topics_share_a_row(self):
        card = self.deck()
        learn.review(card, 1)  # Difícil: não conta como acerto (D42)
        self.assertEqual((mastery.find("memória e sono")["correct"], mastery.find("memória e sono")["wrong"]), (0, 1))
        mastery.record("sono e memória", True, "check")  # as mesmas palavras em outra ordem: a mesma linha
        self.assertEqual(db.value("SELECT COUNT(*) FROM mastery"), 1)
        mastery.record("memória", True, "quiz")
        self.assertIsNone(mastery.find("memória de longo prazo, hipocampo e sono"))  # uma palavra só não casa com tudo


class Explain(Core):
    def setUp(self):
        super().setUp()
        self.ollama.models.append("qwen3.5:4b")
        self.ollama.answer = "## Intuição\nO sono arquiva o dia [S1]."
        self.ollama.json_replies["Você prepara o material que acompanha uma explicação"] = EXTRAS

    def test_each_level_brings_its_parts(self):
        got = {}
        for effort in ("rapido", "equilibrado", "profundo", "maximo"):
            events = run_turn({"text": "Explique como o sono consolida a memória", "mode": "explain", "effort": effort})
            done = next(e for e in events if e["type"] == "done")["message"]
            got[effort] = done["meta"].get("explain")
            if effort != "rapido":
                self.assertIn("visual", [e.get("stage") for e in events if e["type"] == "status"])
        self.assertIsNone(got["rapido"])  # Rápido: só o texto
        eq = got["equilibrado"]
        self.assertEqual(eq["diagram"]["family"], "processo")
        self.assertEqual(eq["diagram"]["evidence"], ["S1"])  # as fontes citadas na explicação
        self.assertEqual(eq["check"]["question"], EXTRAS["check"]["question"])
        self.assertNotIn("deck", eq)
        deck = got["profundo"]["deck"]
        self.assertEqual(deck["count"], 2)
        self.assertEqual(db.value("SELECT COUNT(*) FROM flashcards WHERE deck = ?", deck["id"]), 2)  # no baralho SM-2
        self.assertNotIn("summary", got["profundo"])
        mx = got["maximo"]
        self.assertEqual(mx["summary"], EXTRAS["summary"])
        self.assertTrue(mx["next_review"] > db.now())
        self.assertEqual(mastery.find(mx["topic"])["next_review"], mx["next_review"])  # a revisão marcada

    def test_prompt_layers_and_starting_point(self):
        s = settings.load()
        quick = agent.system_prompt(s, None, (), "explain", "", "rapido", "memória e sono")
        deep = agent.system_prompt(s, None, (), "explain", "", "profundo", "memória e sono")
        self.assertIn("intuição", quick)
        self.assertNotIn("contraexemplo", quick)
        self.assertIn("contraexemplo", deep)
        self.assertIn("não escreva perguntas de checagem", deep)
        mastery.record("memória e sono", False, "check")
        self.assertIn("tem dificuldade", agent.system_prompt(s, None, (), "explain", "", "equilibrado", "sono e memória"))

    def test_prompt_without_notes_does_not_ask_to_cite_notes(self):
        """Sem nenhuma nota recuperada (ou no Modo Livre) a explicação não manda usar as notas como base nem citar [S#]:
        a tarefa contradizia o aviso do Modo Livre. Com notas, o texto de antes fica igual."""
        s = settings.load()
        with_notes = agent.system_prompt(s, None, (), "explain", "", "equilibrado", "memória e sono")
        self.assertIn("usando as notas como base e citando-as", with_notes)
        self.assertIn("Antes, vale saber", with_notes)
        without = agent.system_prompt(s, None, (), "explain", "", "equilibrado", "memória e sono", has_sources=False)
        self.assertNotIn("usando as notas como base", without)
        self.assertNotIn("Antes, vale saber", without)
        self.assertIn("intuição", without)                       # as camadas e o que o Lúmen mostra depois continuam
        self.assertIn("não escreva perguntas de checagem", without)

    def test_temporary_conversation_writes_nothing(self):
        mastery.record("memória e sono", False, "check")
        events = run_turn({"text": "Explique como o sono consolida a memória", "mode": "explain", "effort": "maximo", "temporary": True})
        done = next(e for e in events if e["type"] == "done")["message"]
        ex = done["meta"]["explain"]
        self.assertTrue(ex["check"] and ex["diagram"])
        self.assertNotIn("deck", ex)  # sem baralho e sem revisão marcada no disco (D13)
        self.assertNotIn("next_review", ex)
        self.assertEqual(db.value("SELECT COUNT(*) FROM flashcards"), 0)
        system = next(b for path, b in self.ollama.requests if path == "/api/chat" and not b.get("format"))["messages"][0]["content"]
        self.assertNotIn("Ponto de partida", system)  # temporária com privacidade: sem o modelo do estudante
        self.ollama.json_replies["Você corrige respostas"] = {"correct": True, "score": 1, "feedback": "Isso."}
        before = mastery.find("memória e sono")["correct"]
        explain.grade(done["meta"], "O sono consolida.", agent.providers.chain()[0][0], record=False)
        self.assertEqual(mastery.find("memória e sono")["correct"], before)

    def test_junk_outside_the_schema_does_not_break_the_answer(self):
        self.ollama.json_replies["Você prepara o material que acompanha uma explicação"] = {
            "diagram": "desenho", "check": "?", "summary": "uma linha",
            "cards": [{"question": 5, "answer": ["a"], "source": ["S1"]}, "texto", {"question": "Q?", "answer": "R.", "source": {"x": 1}}]}
        events = run_turn({"text": "Explique o sono", "mode": "explain", "effort": "maximo"})
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertIn("O sono arquiva o dia", done["content"])
        ex = done["meta"]["explain"]
        self.assertEqual(ex["deck"]["count"], 2)  # o que dá para aproveitar vira texto; o resto sai
        self.assertNotIn("summary", ex)
        self.assertNotIn("diagram", ex)
        m = diagram.from_mind({"branches": [{"label": "A", "detail": "", "children": 3}, {"label": "B", "detail": "", "children": []}],
                               "sources": [["S1"], "S1"]}, "x", {"S1": {}})
        self.assertEqual((len(m["nodes"]), m["evidence"]), (2, ["S1"]))

    def test_extras_fail_softly(self):
        self.ollama.json_replies["Você prepara o material que acompanha uma explicação"] = {"diagram": {"family": "processo", "nodes": []}}
        events = run_turn({"text": "Explique o sono", "mode": "explain", "effort": "equilibrado"})
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertIn("O sono arquiva o dia", done["content"])  # a explicação sai mesmo sem diagrama
        self.assertNotIn("diagram", done["meta"]["explain"])


class MindMap(Core):
    def test_command_router_and_export(self):
        self.ollama.json_replies["Monte um mapa mental"] = MIND
        self.assertIn(("mapa-mental", "mindmap"), [(x["name"], x.get("mode")) for x in registry.menu()])
        self.assertEqual(search.heuristic("faça um mapa mental sobre memória")["intent"], "mindmap")
        self.assertEqual(search.heuristic("mapa de conhecimento de memória")["intent"], "map")
        events = run_turn({"text": "memória", "mode": "mindmap"})
        it = next(e for e in events if e["type"] == "item")["item"]
        self.assertEqual((it["kind"], it["data"]["diagram"]["family"]), ("mindmap", "mapa"))
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertIn("com 3 ramos", done["content"])
        md = api._item_markdown(learn.item(it["id"]))
        self.assertIn("- **Tipos**: Curto e longo prazo.", md)
        self.assertIn("    - Trabalho: Segura o agora.", md)


if __name__ == "__main__":
    unittest.main()
