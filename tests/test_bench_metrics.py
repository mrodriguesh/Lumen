import unittest

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from bench import metrics


class Metrics(unittest.TestCase):
    def test_numbers(self):
        for n, w in [(0, "zero"), (21, "vinte e um"), (100, "cem"), (101, "cento e um"), (1990, "mil novecentos e noventa"),
                     (2000, "dois mil"), (2024, "dois mil e vinte e quatro"), (1500, "mil e quinhentos"),
                     (1_000_000, "um milhão"), (3_200_005, "três milhões duzentos mil e cinco")]:
            self.assertEqual(metrics.number_words(n), w, n)

    def test_normalize(self):
        self.assertEqual(metrics.normalize("Em 1990, ahn, o PIB cresceu 5%!"),
                         ["em", "mil", "novecentos", "e", "noventa", "o", "pib", "cresceu", "cinco", "por", "cento"])
        self.assertEqual(metrics.normalize("1.000 pessoas"), ["mil", "pessoas"])

    def test_counts(self):
        s = metrics.score("o gato subiu no telhado", "o rato subiu no telhado azul agora")
        self.assertEqual((s["S"], s["D"], s["I"], s["N"]), (1, 0, 2, 5))
        s = metrics.score("a aula começa agora", "a aula agora")
        self.assertEqual((s["S"], s["D"], s["I"]), (0, 1, 0))
        self.assertEqual(metrics.score("igual", "Igual.")["S"] + metrics.score("igual", "Igual.")["D"], 0)

    def test_aggregate(self):
        agg = metrics.aggregate([metrics.score("a b c d", "a b c d"), metrics.score("a b", "")])
        self.assertAlmostEqual(agg["WER"], 2 / 6)
        self.assertEqual(agg["D"], 2)


if __name__ == "__main__":
    unittest.main()
