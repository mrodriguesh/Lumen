"""Gráficos da aula: números conferidos junto do rótulo, fórmulas calculadas aqui, GIF animado e a seção na página."""
import io
import json
import unittest
from unittest import mock

import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import charts, jobs, llm, notion, sources, store, vision  # noqa: F401
from tests.fake_notion import Fake
from tests.test_flow import SPEC, full
from tests.test_llm import GOOD


def say(*lines, screens=()):
    """Unidades de uma aula: trechos da fala (8 s cada) e telas [(t, título, texto, valores)]."""
    segs = [{"start": i * 8.0, "end": i * 8.0 + 7, "text": t} for i, t in enumerate(lines)]
    notes = [{"t": t, "note": {"titulo": title, "texto": text, "tipo": "grafico", "valores": pairs}}
             for t, title, text, pairs in screens]
    return charts.units(segs, notes)


def bars(rows, kind="barras", unit="", series=("Valor",), msg=""):
    return {"graficos": [{"trecho": "", "tipo": kind, "titulo": "Gráfico", "mensagem": msg, "unidade": unit,
                          "eixo_x": "", "eixo_y": "", "series": list(series),
                          "dados": [{"rotulo": r, "valores": list(v)} for r, *v in rows],
                          "funcoes": [], "x_min": 0, "x_max": 0, "eventos": []}]}


def curve(*exprs, x=(0, 0)):
    return {"graficos": [{"trecho": "", "tipo": "funcao", "titulo": "Curvas", "mensagem": "", "unidade": "",
                          "eixo_x": "", "eixo_y": "", "series": [], "dados": [],
                          "funcoes": [{"nome": e, "expressao": e} for e in exprs], "x_min": x[0], "x_max": x[1],
                          "eventos": []}]}


class Numbers(unittest.TestCase):
    def test_reads_numbers_as_written_in_the_lesson(self):
        self.assertEqual(charts.numbers("levou 5.200 ms"), {5200.0})
        self.assertEqual(charts.numbers("it took 5,200 ms", comma=False), {5200.0})
        self.assertEqual(charts.numbers("1,5 litro e 3.14"), {1.5, 3.14})
        self.assertEqual(charts.numbers("1.234,5"), {1234.5})
        self.assertEqual(charts.numbers("cerca de 1 milhão"), {1.0, 1e6})
        self.assertEqual(charts.numbers("um milhão de números"), {1.0, 1e6})
        self.assertEqual(charts.numbers("cinco etapas"), {5.0})
        self.assertEqual(charts.numbers("fez -5 °C"), {5.0, -5.0})
        self.assertEqual(charts.numbers("uma aula"), set())  # artigo não é número
        self.assertEqual(charts.fmt(5200), "5.200")
        self.assertEqual(charts.fmt(84.4, "%"), "84,4%")
        self.assertEqual(charts.fmt(1.5, "ms"), "1,5 ms")


class Grounding(unittest.TestCase):
    """Cada valor precisa aparecer junto do seu rótulo na aula; senão o gráfico inteiro fica de fora."""

    def test_screen_pairs_are_accepted_and_swapped_values_are_not(self):
        # o modelo de visão escreveu os valores soltos e devolveu os pares lidos na imagem
        us = say("Vejam como o bubble sort fica muito atrás.", screens=[(57, "Tempo para ordenar", "5.200 ms\nBubble sort\n180 ms\nMerge sort\n150 ms\nQuicksort", [{"rotulo": "Bubble sort", "valor": "5.200 ms"}, {"rotulo": "Merge sort", "valor": "180 ms"}, {"rotulo": "Quicksort", "valor": "150 ms"}])])  # noqa: E501
        good = charts.validate(bars([("Bubble sort", 5200), ("Merge sort", 180), ("Quicksort", 150)], unit="ms"), us)
        self.assertEqual(good[0]["series"][0]["valores"], [5200, 180, 150])
        self.assertEqual(good[0]["t"], 57)
        # o par trocado (cada nome com o valor de baixo) está nas linhas vizinhas, mas não junto
        self.assertEqual(charts.validate(bars([("Bubble sort", 180), ("Merge sort", 150), ("Quicksort", 5200)]), us), [])

    def test_speech_pairs_follow_the_sentence(self):
        us = say("O ar seco tem 78% de nitrogênio, 21% de oxigênio e 1% de outros gases.")
        ok = charts.validate(bars([("Nitrogênio", 78), ("Oxigênio", 21), ("Outros gases", 1)], "rosca", "%"), us)
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0]["mensagem"], "Maior parte: Nitrogênio (78%)")  # tirado dos dados
        swapped = bars([("Nitrogênio", 21), ("Oxigênio", 78), ("Outros gases", 1)], "rosca", "%")
        self.assertEqual(charts.validate(swapped, us), [])
        us = say("O bubble sort levou 5.200 milissegundos e o merge sort, 180.")
        self.assertTrue(charts.validate(bars([("Bubble sort", 5200), ("Merge sort", 180)]), us))
        self.assertEqual(charts.validate(bars([("Bubble sort", 180), ("Merge sort", 5200)]), us), [])

    def test_invented_rounded_or_incoherent_data_is_dropped(self):
        us = say("Em 2015 a inflação foi de 10,7%.", "Em 2016 caiu para 6,3%.", "Em 2017 foi de 2,9%.")
        line = [("2015", 10.7), ("2016", 6.3), ("2017", 2.9)]
        self.assertEqual(len(charts.validate(bars(line, "linha", "%"), us)), 1)
        self.assertEqual(charts.validate(bars(line[:2] + [("2018", 3.7)], "linha", "%"), us), [])  # 2018 inventado
        self.assertEqual(charts.validate(bars([("2015", 11), ("2016", 6.3), ("2017", 2.9)], "linha"), us), [])  # 10,7 → 11
        us = say("Metade, 50% dos votos, foi para A e 30% para B.")
        self.assertEqual(charts.validate(bars([("A", 50), ("B", 30)], "rosca", "%"), us), [])  # não fecha 100%
        us = say("Em 2010 eram 30 alunos na turma A e 25 na turma B.")
        two = bars([("Turma A", 30, 1), ("Turma B", 25, 2)], series=("Alunos", "Professores"))
        self.assertEqual(charts.validate(two, us), [])  # série que a aula não citou

    def test_a_row_cannot_borrow_values_from_another_row(self):
        # revisão do Codex: Alpha usava os números do Beta no mesmo trecho
        us = say("Alpha 2024 10 2025 20; Beta 2024 20 2025 10")
        swapped = bars([("Alpha", 20, 10), ("Beta", 10, 20)], series=("2024", "2025"))
        self.assertEqual(charts.validate(swapped, us), [])
        right = bars([("Alpha", 10, 20), ("Beta", 20, 10)], series=("2024", "2025"))
        self.assertTrue(charts.validate(right, us))
        table = say(screens=[(5, "Vendas", "Produto 2024 2025\nAlpha 10 20\nBeta 20 10", [])])
        self.assertEqual(charts.validate(swapped, table), [])
        self.assertTrue(charts.validate(right, table))

    def test_each_value_must_be_in_its_own_column(self):
        # revisão do Codex: cada valor era conferido só com a sua linha; trocar as colunas passava
        us = say("Alpha 2024 10 2025 20; Beta 2024 30 2025 40")
        right = bars([("Alpha", 10, 20), ("Beta", 30, 40)], series=("2024", "2025"))
        self.assertEqual(charts.validate(right, us)[0]["series"][1]["valores"], [20, 40])
        swapped = bars([("Alpha", 20, 10), ("Beta", 40, 30)], series=("2024", "2025"))
        self.assertEqual(charts.validate(swapped, us), [])
        # tabela na tela: os valores na ordem do cabeçalho
        table = say(screens=[(10, "Vendas", "Produto | 2024 | 2025\nAlpha | 10 | 20\nBeta | 30 | 40", [])])
        self.assertEqual(len(charts.validate(right, table)), 1)
        self.assertEqual(charts.validate(swapped, table), [])
        self.assertEqual(charts.validate(bars([("Alpha", 10, 20), ("Beta", 30, 40)], series=("2025", "2024")),
                                         table), [])  # séries na ordem trocada
        # na fala, sem dizer de qual ano é cada número: não dá para saber
        vague = say("Em 2024 e 2025 o Alpha vendeu 10 e 20, e o Beta 30 e 40.")
        self.assertEqual(charts.validate(right, vague), [])

    def test_the_ai_conclusion_only_stays_if_the_lesson_said_it(self):
        us = say("O bubble sort levou 5.200 ms e o merge sort, 180.", "Vejam como o bubble sort fica muito atrás.")
        rows = [("Bubble sort", 5200), ("Merge sort", 180)]
        wrong = charts.validate(bars(rows, unit="ms", msg="O merge sort é o mais lento."), us)
        self.assertEqual(wrong[0]["mensagem"], "Maior: Bubble sort (5.200 ms) · menor: Merge sort (180 ms)")
        said = charts.validate(bars(rows, unit="ms", msg="Vejam como o bubble sort fica muito atrás"), us)
        self.assertEqual(said[0]["mensagem"], "Vejam como o bubble sort fica muito atrás")

    def test_timeline_years_go_with_their_events(self):
        us = say("Em 1808 a família real chegou ao Rio.", "A independência do Brasil foi em 1822.",
                 "Em 1888 a Lei Áurea aboliu a escravidão.", "E em 1889 foi proclamada a República.")
        ev = lambda *pairs: {"graficos": [{"tipo": "linha_do_tempo", "titulo": "Brasil", "mensagem": "",  # noqa: E731
                                           "eventos": [{"data": d, "texto": t} for d, t in pairs]}]}
        ok = charts.validate(ev(("1822", "Independência"), ("1808", "Família real no Rio"),
                                ("1888", "Lei Áurea"), ("1889", "República")), us)
        self.assertEqual([e["ano"] for e in ok[0]["eventos"]], [1808, 1822, 1888, 1889])  # em ordem
        self.assertEqual(charts.validate(ev(("1889", "Independência"), ("1808", "Família real no Rio"),
                                            ("1888", "Lei Áurea")), us), [])

    def test_code_on_screen_is_not_data(self):
        us = charts.units([], [{"t": 5, "note": {"titulo": "Busca", "texto": "inicio, fim = 0, len(lista) - 1",
                                                 "tipo": "codigo", "valores": []}}])
        self.assertEqual(us, [])


class Formulas(unittest.TestCase):
    def test_parser_computes_only_math(self):
        f, var, cx = charts.parse("O(n log n)")
        self.assertEqual((var, cx), ("n", True))
        self.assertAlmostEqual(f(np.array([8.0]))[0], 24.0)  # log na base 2 em complexidade
        f, var, _ = charts.parse("y = x² − 4x + 3")
        self.assertEqual(list(f(np.array([1.0, 2.0, 3.0]))), [0.0, -1.0, 0.0])
        self.assertAlmostEqual(charts.parse("2^n")[0](np.array([10.0]))[0], 1024)
        self.assertAlmostEqual(charts.parse("n!")[0](np.array([5.0]))[0], 120)
        self.assertAlmostEqual(charts.parse("s = 5 + 2t")[0](np.array([3.0]))[0], 11)
        self.assertAlmostEqual(charts.parse("sen(x)")[0](np.array([0.0]))[0], 0)
        for bad in ("__import__('os').system('x')", "x.real", "open(x)", "x + y", "lambda: 1", "[x]", "x if x else 1",
                    "1e999**x", "x // 2", "g * t"):
            self.assertIsNone(charts.parse(bad), bad)
        self.assertTrue(np.isnan(charts.parse("log x")[0](np.array([-1.0]))[0]))  # fora do domínio: sem ponto

    def test_formula_must_be_written_in_the_lesson(self):
        us = say("Considere a função f(x) = x² - 4x + 3.")
        ok = charts.validate(curve("x^2 - 4x + 3", x=(-1, 5)), us)
        self.assertEqual((ok[0]["x_min"], ok[0]["x_max"]), (-1.0, 5.0))
        self.assertEqual(charts.validate(curve("x^3 - 4x"), us), [])  # a aula não tem esta
        self.assertEqual(charts.validate(curve("x"), us), [])  # "x" está em qualquer texto, mas não é a fórmula
        self.assertTrue(charts.validate(curve("3 - 4x + x²"), us))  # escrita de outro jeito, mesma função

    def test_formula_structure_matters(self):
        # revisão do Codex: sem os parênteses, "x+1^2" passava por "(x+1)^2" e o gráfico mostrava x+1
        us = say("A parábola desta aula é y = (x+1)^2.")
        self.assertEqual(charts.validate(curve("x+1^2"), us), [])
        self.assertEqual(charts.validate(curve("x^2+1"), us), [])
        self.assertTrue(charts.validate(curve("(x+1)^2"), us))
        self.assertTrue(charts.validate(curve("x^2 + 2x + 1"), us))
        spoken = say("A função é y igual a x ao quadrado mais 1.")
        self.assertEqual(charts.validate(curve("(x+1)^2"), spoken), [])
        self.assertTrue(charts.validate(curve("x^2 + 1"), spoken))
        big_o = say("A busca binária é O(log n).")
        self.assertTrue(charts.validate(curve("log n"), big_o))
        self.assertEqual(charts.validate(curve("n log n"), big_o), [])

    def test_formula_is_checked_where_it_is_drawn(self):
        # revisão do Codex: os pontos de prova fixos ficavam todos abaixo de 8 e abaixo de 10
        us = say("O módulo é y = abs(x-8).")
        self.assertEqual(charts.validate(curve("8-x", x=(-10, 10)), us), [])
        self.assertTrue(charts.validate(curve("abs(x-8)", x=(-10, 10)), us))
        root = charts.validate(curve("sqrt(x-10)", x=(10, 20)), say("A raiz é y = sqrt(x-10)."))
        self.assertEqual((root[0]["x_min"], root[0]["x_max"]), (10.0, 20.0))
        # a fórmula mostrada e desenhada é a da aula, não a da IA
        ok = charts.validate(curve("3 - 4x + x²"), say("Considere f(x) = x² - 4x + 3."))
        self.assertEqual(ok[0]["funcoes"][0]["expressao"], "x² - 4x + 3")

    def test_complexities_are_charted_without_ai(self):
        us = say(screens=[(37, "Complexidade", "Quicksort | O(n log n) | O(n²)\nBubble sort | O(n) | O(n²)", []),
                          (75, "Resumo", "Busca binária: O(log n)", [])])
        c = charts.complexities(us)
        self.assertEqual([f["nome"] for f in c["funcoes"]], ["O(log n)", "O(n)", "O(n log n)", "O(n²)"])
        self.assertEqual(c["t"], 37)
        found, (x0, x1, y0, y1) = charts.curves(c)
        self.assertEqual((x0, x1, y0), (1.0, 32.0, 0.0))
        self.assertAlmostEqual(y1, 1024)
        self.assertIsNone(charts.complexities(say("Só O(n) aqui.")))

    def test_a_curve_that_explodes_leaves_through_the_top(self):
        us = say("Comparem O(n²) e O(2^n).")
        _, box = charts.curves(charts.complexities(us))
        self.assertAlmostEqual(box[3], 1024 * 1.6)  # 2^32 não achata o n²


class Extract(unittest.TestCase):
    def test_lesson_without_data_does_not_call_the_ai(self):
        with mock.patch.object(llm, "_chat") as chat:
            self.assertEqual(charts.extract([{"start": 0, "text": "A virtude é um meio-termo."}], [], {}, "m",
                                            lambda: None), [])
        chat.assert_not_called()

    def test_ai_proposals_are_checked_and_complexities_added(self):
        segs = [{"start": 0.0, "text": "O bubble sort levou 5.200 ms e o merge sort, 180."},
                {"start": 9.0, "text": "O bubble sort é O(n²) e o merge sort é O(n log n)."}]
        answer = {"graficos": [bars([("Bubble sort", 5200), ("Merge sort", 180)], unit="ms")["graficos"][0],
                               bars([("Bubble sort", 9), ("Merge sort", 1)])["graficos"][0],  # inventado
                               curve("n log n")["graficos"][0]]}  # some no das complexidades
        with mock.patch.object(llm, "_chat", return_value=json.dumps(answer)) as chat:
            out = charts.extract(segs, [], {"title": "Ordenação", "topics": []}, "m", lambda: None, language="pt")
        self.assertIn("O bubble sort levou 5.200 ms", chat.call_args.args[2])
        self.assertEqual([c["tipo"] for c in out], ["barras", "funcao"])
        self.assertEqual([f["nome"] for f in out[1]["funcoes"]], ["O(n log n)", "O(n²)"])


@unittest.skipUnless(charts.edge(), "sem Microsoft Edge")
class Render(unittest.TestCase):
    def test_animated_gif_for_each_kind(self):
        import av
        us = say("O ar seco tem 78% de nitrogênio, 21% de oxigênio e 1% de outros gases.",
                 "Em 1808 a família real chegou ao Rio.", "A independência do Brasil foi em 1822.",
                 "Em 1888 a Lei Áurea aboliu a escravidão.", "Comparem O(n) e O(n²).")
        found = charts.validate(bars([("Nitrogênio", 78), ("Oxigênio", 21), ("Outros gases", 1)], "rosca", "%"), us)
        found += charts.validate({"graficos": [{"tipo": "linha_do_tempo", "titulo": "Brasil", "eventos": [
            {"data": "1808", "texto": "Família real"}, {"data": "1822", "texto": "Independência"},
            {"data": "1888", "texto": "Lei Áurea"}]}]}, us)
        found.append(charts.complexities(us))
        for c in found:
            gif = charts.render(c)
            self.assertTrue(gif and gif[:6] == b"GIF89a", c["tipo"])
            self.assertLess(len(gif), charts.MAX_GIF)
            with av.open(io.BytesIO(gif)) as f:
                frames = [fr.to_ndarray(format="rgb24") for fr in f.decode(video=0)]
            self.assertEqual(len(frames), charts.FRAMES)
            self.assertEqual(frames[0].shape, (charts.H, charts.W, 3))
            moved = (np.abs(frames[-1].astype(int) - frames[2]).max(axis=2) > 40).mean()
            self.assertGreater(moved, 0.003, f"{c['tipo']} não anima")  # o desenho cresce


class Page(unittest.TestCase):
    def test_charts_section_after_topics_with_data_toggle(self):
        us = say("O bubble sort levou 5.200 ms e o merge sort, 180.")
        c = charts.validate(bars([("Bubble sort", 5200), ("Merge sort", 180)], unit="ms"), us)[0]
        meta = {"course": "C", "source": "x", "model": "m", "transcript_origin": "x", "yt_id": "dQw4w9WgXcQ",
                "charts": [{**c, "upload": "up1"}, {**c, "upload": None}]}
        _, blocks = notion.build_page(llm.validate(GOOD, 600), meta)
        heads = [b["heading_2"]["rich_text"][0]["text"]["content"].split(" ", 1)[-1] for b in blocks if b["type"] == "heading_2"]  # sem o emoji
        self.assertEqual(heads[heads.index("Tópicos principais") + 1], "Gráficos da aula")
        img = next(b for b in blocks if b["type"] == "image" and b["image"]["file_upload"]["id"] == "up1")
        self.assertIn("youtube.com/watch?v=dQw4w9WgXcQ&t=0s", json.dumps(img))  # link para o momento da aula
        toggle = blocks[blocks.index(img) + 1]
        table = toggle["toggle"]["children"][-1]["table"]
        cells = [[r["text"]["content"] for cell in row["table_row"]["cells"] for r in cell] for row in table["children"]]
        self.assertEqual(cells, [["", "Valor (ms)"], ["Bubble sort", "5.200"], ["Merge sort", "180"]])
        # sem a imagem (sem Edge ou o envio falhou): título e números
        i = next(i for i, b in enumerate(blocks)
                 if b["type"] == "heading_3" and "Gráfico" in json.dumps(b, ensure_ascii=False))
        self.assertEqual(blocks[i + 2]["type"], "table")
        self.assertIn("2 gráfico(s) feitos só com dados da aula", json.dumps(blocks, ensure_ascii=False))


class Flow(unittest.TestCase):
    CAPTIONS = ("0:00\nHoje vamos estudar a atmosfera.\n0:30\nO ar seco tem 78% de nitrogênio, 21% de oxigênio e "
                "1% de outros gases.\n1:05\nO oxigênio é o que respiramos.")
    ANSWER = bars([("Nitrogênio", 78), ("Oxigênio", 21), ("Outros gases", 1)], "rosca", "%")

    def setUp(self):
        store.clear_local_data()
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root})
        self.chart_calls = 0

        def chat(model, system, user, *a, **k):
            if system == charts.SYSTEM:
                self.chart_calls += 1
                if self.broken:
                    raise ValueError("resposta malformada")
                return json.dumps(self.ANSWER)
            return json.dumps(GOOD)
        self.broken = False
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(sources, "youtube_meta", return_value={"title": "Ar", "author": "Prof"}),
                        mock.patch.object(llm, "_chat", side_effect=chat),
                        mock.patch("lumen.mindmap.render", return_value=None),
                        mock.patch.object(charts, "render", return_value=b"GIF89a" + b"0" * 2000)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def test_page_gets_the_gif_and_retry_reuses_the_checked_charts(self):
        spec = {**SPEC, "captions": self.CAPTIONS, "course_id": self.root}
        j = full(spec)
        self.assertEqual(j["status"], "done", j.get("error"))
        gifs = [u for u in self.fake.uploads.values() if u["content_type"] == "image/gif"]
        self.assertEqual(len(gifs), 1)
        page = json.dumps(self.fake.pages[self.root]["blocks"], ensure_ascii=False)
        self.assertIn("Gráficos da aula", page)
        self.assertIn("Maior parte: Nitrogênio (78%)", page)
        saved = json.loads(next(store.WORK.glob("*/lesson.json")).read_text("utf-8"))
        self.assertEqual(saved["charts"][0]["series"][0]["valores"], [78, 21, 1])
        jobs.start("process", jobs.finish, {**spec, "mode": "replace"})  # “Atualizar”: mesma aula, mesmo material
        from tests.test_flow import wait
        self.assertEqual(wait()["status"], "done")
        self.assertEqual(self.chart_calls, 1)  # não perguntou de novo

    def test_chart_failure_never_blocks_the_page(self):
        self.broken = True
        with self.assertLogs("lumen", "ERROR") as logs:
            j = full({**SPEC, "captions": self.CAPTIONS, "course_id": self.root})
        self.assertIn("gráficos: falha ao procurar dados", logs.output[0])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertNotIn("Gráficos da aula", json.dumps(self.fake.pages[self.root]["blocks"], ensure_ascii=False))


class VisionPairs(unittest.TestCase):
    def test_chart_pairs_from_the_image_become_text_when_it_is_empty(self):
        n = vision.clean({"titulo": "Tempo", "texto": "", "descricao": "barras", "tipo": "grafico",
                          "conteudo_da_aula": True, "valores": [{"rotulo": "Bubble sort", "valor": "5.200 ms"},
                                                                {"rotulo": "", "valor": "1"}, "lixo"]})
        self.assertEqual(n["valores"], [{"rotulo": "Bubble sort", "valor": "5.200 ms"}])
        self.assertEqual(n["texto"], "Bubble sort: 5.200 ms")
        self.assertEqual(vision.clean({"titulo": "x", "texto": "y"})["valores"], [])  # anotação antiga


if __name__ == "__main__":
    unittest.main()
