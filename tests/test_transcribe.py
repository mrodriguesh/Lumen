import types
import unittest
from unittest import mock

import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import transcribe


def word(start, end, w):
    return types.SimpleNamespace(start=start, end=end, word=w)


class FakeSmall:
    """Segundo modelo: concorda no 1º trecho e ouve outra coisa no 2º."""

    def __init__(self, *a, **k):
        pass

    def transcribe(self, samples, **kw):
        assert kw["word_timestamps"]
        segs = [types.SimpleNamespace(words=[word(0.1, 0.5, " A"), word(0.5, 0.9, " aula"), word(0.9, 1.5, " começa")]),
                types.SimpleNamespace(words=[word(2.1, 2.6, " o"), word(2.6, 3.4, " Kubernetes"), word(3.4, 3.9, " escala")])]
        return iter(segs), None


class SecondOpinion(unittest.TestCase):
    def segs(self):
        return [{"start": 0.0, "end": 2.0, "text": "A aula começa."}, {"start": 2.0, "end": 4.0, "text": "O cubo de neto escala."}]

    def test_flags_divergence_without_replacing_text(self):
        segs = self.segs()
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "downloaded", return_value=True), \
                mock.patch.object(transcribe, "WhisperModel", FakeSmall), \
                mock.patch.object(transcribe, "BatchedInferencePipeline", lambda model: model):
            self.assertTrue(transcribe.second_opinion(np.zeros(16000 * 4, dtype=np.float32), 1.0, segs, "large-v3-turbo", lambda: None))
        self.assertNotIn("diverges", segs[0])
        self.assertTrue(segs[1]["diverges"])
        self.assertEqual(segs[1]["alt"], "o Kubernetes escala")
        self.assertEqual(segs[1]["text"], "O cubo de neto escala.")  # nunca troca sozinho

    def test_timestamps_scaled_for_2x(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "A aula começa."}]  # no arquivo 2x, o trecho 0–2 s vira 0–1 s
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "downloaded", return_value=True), \
                mock.patch.object(transcribe, "WhisperModel", FakeSmall), \
                mock.patch.object(transcribe, "BatchedInferencePipeline", lambda model: model):
            transcribe.second_opinion(np.zeros(16000 * 4, dtype=np.float32), 2.0, segs, "large-v3-turbo", lambda: None)
        self.assertNotIn("diverges", segs[0])

    def test_batch_fits_free_vram(self):  # lote 8: +1,2 GB; com pouca VRAM, lote 1 (+0,65 GB)
        for free, batch in ((9.0, 8), (1.2, 1)):
            seen = {}
            fake = lambda model: types.SimpleNamespace(transcribe=lambda x, **kw: (seen.update(kw), (iter([]), None))[1])
            with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                    mock.patch.object(transcribe, "downloaded", return_value=True), \
                    mock.patch.object(transcribe, "gpu_free_gb", return_value=free), \
                    mock.patch.object(transcribe, "WhisperModel", FakeSmall), \
                    mock.patch.object(transcribe, "BatchedInferencePipeline", fake):
                transcribe.second_opinion(np.zeros(10, dtype=np.float32), 1.0, self.segs(), "large-v3", lambda: None)
            self.assertEqual(seen["batch_size"], batch)

    def test_skipped_without_gpu_or_model(self):
        for gpu, have in ((False, True), (True, False)):
            with mock.patch.object(transcribe, "has_gpu", return_value=gpu), \
                    mock.patch.object(transcribe, "downloaded", return_value=have):
                self.assertFalse(transcribe.second_opinion(np.zeros(10, dtype=np.float32), 1.0, self.segs(), "large-v3-turbo", lambda: None))

    def test_disagreement(self):
        self.assertEqual(transcribe.disagreement("Olá, turma!", "olá turma"), 0)
        self.assertGreater(transcribe.disagreement("o cubo de neto", "o kubernetes"), transcribe.DIVERGENCE)



class Modes(unittest.TestCase):
    def test_hardware_mapping_and_legacy_values(self):
        with mock.patch.object(transcribe, "has_gpu", return_value=True):
            self.assertEqual({k: v["name"] for k, v in transcribe.models().items()},
                             {"rapido": "small", "equilibrado": "large-v3-turbo", "maximo": "large-v3"})
            for old in ("auto", "preciso", None):
                self.assertEqual(transcribe.pick(old)[0], "equilibrado")
        with mock.patch.object(transcribe, "has_gpu", return_value=False):
            self.assertEqual(transcribe.pick("equilibrado")[1]["name"], transcribe.PARAKEET)
            self.assertEqual(transcribe.pick("maximo")[1]["name"], "large-v3-turbo")

    def test_parakeet_adapter(self):
        class FakeOnnx:  # onnx-asr com VAD: segmentos sem confiança
            def recognize(self, samples, sample_rate):
                return iter([types.SimpleNamespace(start=0.5, end=2.0, text="Olá turma.")])
        out = list(transcribe._segments(FakeOnnx(), np.zeros(10, dtype=np.float32), lambda: None))
        seg, info = out[0]
        self.assertEqual((seg.start, seg.end, seg.text), (0.5, 2.0, "Olá turma."))
        self.assertGreater(seg.avg_logprob, transcribe.UNCERTAIN_LOGPROB)  # nunca marcado “incerto” sem sinal real
        self.assertIsNone(info.language)



class Vram(unittest.TestCase):
    def test_falls_back_when_vram_is_short(self):
        with mock.patch.object(transcribe, "has_gpu", return_value=True),                 mock.patch.object(transcribe, "downloaded", return_value=True):
            with mock.patch.object(transcribe, "gpu_free_gb", return_value=10.0):
                self.assertEqual(transcribe.fit_gpu("large-v3"), ("large-v3", None))
            with mock.patch.object(transcribe, "gpu_free_gb", return_value=3.0):
                name, warn = transcribe.fit_gpu("large-v3")
                self.assertEqual(name, "large-v3-turbo")
                self.assertIn("3.0 GB", warn)
            with mock.patch.object(transcribe, "gpu_free_gb", return_value=0.5):
                self.assertEqual(transcribe.fit_gpu("large-v3-turbo")[0], transcribe.PARAKEET)
            with mock.patch.object(transcribe, "gpu_free_gb", return_value=None):  # sem medição: tenta, com recuo p/ CPU
                self.assertEqual(transcribe.fit_gpu("large-v3"), ("large-v3", None))

    def test_max_precision_uses_int8_float16_on_gpu(self):  # bench/fast: mesma precisão, 1,7× mais rápido que float32
        with mock.patch.dict(transcribe._loaded, {}, clear=True):
            self.assertEqual(transcribe._loaded_compute("large-v3", "cuda"), "int8_float16")
            self.assertEqual(transcribe._loaded_compute("large-v3-turbo", "cuda"), "float16")
            self.assertEqual(transcribe._loaded_compute("large-v3", "cpu"), "int8")

    def test_loaded_model_needs_only_working_memory(self):
        """Bug real: com o large-v3 já carregado (1,4 GB livres), o app achava que ele não cabia e ia para a CPU."""
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "gpu_free_gb", return_value=1.4), \
                mock.patch.dict(transcribe._loaded, {("large-v3", "cuda"): object()}, clear=True):
            self.assertEqual(transcribe.fit_gpu("large-v3"), ("large-v3", None))
            self.assertEqual(transcribe._vram("large-v3"), (1.4, transcribe.WORK_GB["large-v3"]))
            self.assertIn(("large-v3", "cuda"), transcribe._loaded)  # cabe: continua carregado
        with mock.patch.object(transcribe, "gpu_free_gb", return_value=7.0), \
                mock.patch.dict(transcribe._loaded, {("small", "cuda"): object()}, clear=True):
            self.assertEqual(transcribe._vram("large-v3"), (7.0, transcribe.VRAM_NEED_GB["large-v3"]))
            self.assertEqual(transcribe._loaded, {})  # outro modelo do Lumen é liberado antes de medir

    def test_loaded_model_without_working_memory_releases_ollama(self):
        """Revisão do Codex: Whisper carregado e o Ollama ocupando a GPU (0,3 GB livres) não pode pular a checagem."""
        release = mock.Mock(return_value=True)
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "gpu_free_gb", side_effect=[0.3, 0.3, 0.3, 9.0]), \
                mock.patch.object(transcribe.time, "sleep"), \
                mock.patch.dict(transcribe._loaded, {("large-v3", "cuda"): object()}, clear=True):
            transcribe.make_room("large-v3", release)
            release.assert_called_once()
            self.assertEqual(transcribe._loaded, {})  # descarregado para medir o modelo inteiro de novo

    def test_make_room_releases_ollama_only_when_needed(self):
        release = mock.Mock(return_value=True)
        with mock.patch.object(transcribe, "has_gpu", return_value=True), mock.patch.dict(transcribe._loaded, {}, clear=True):
            with mock.patch.object(transcribe, "gpu_free_gb", return_value=8.0):
                transcribe.make_room("large-v3", release)
                release.assert_not_called()                          # cabe: não mexe no Ollama
            with mock.patch.object(transcribe, "gpu_free_gb", side_effect=[2.0, 2.0, 9.0]), \
                    mock.patch.object(transcribe.time, "sleep"):
                transcribe.make_room("large-v3", release)
                release.assert_called_once()                         # não cabia: libera e espera a VRAM voltar

    def test_no_change_without_gpu(self):
        with mock.patch.object(transcribe, "has_gpu", return_value=False):
            self.assertEqual(transcribe.fit_gpu("large-v3-turbo"), ("large-v3-turbo", None))



class MidRunOom(unittest.TestCase):
    """GPU encheu no meio: libera o Ollama e transcreve de novo do início. Revisão do Codex: o fim estimado do último
    trecho pode passar do fim real da fala; retomar dali perdia a fala seguinte."""

    def test_retry_keeps_all_speech_when_end_time_overshoots(self):
        from types import SimpleNamespace as N
        speech = [(0.0, 3.5, "Primeiro trecho aqui."), (4.0, 8.0, "Segundo trecho ali."), (8.2, 11.0, "Terceiro trecho final.")]
        offsets = []

        def fake_segments(model, samples, check, opts):  # o “áudio”: só a fala que está na fatia recebida
            offset = 12.0 - len(samples) / 16000
            offsets.append(offset)
            for k, (a, b, text) in enumerate(speech):
                if a < offset:
                    continue
                end = b + 1.0 if k == 1 else b  # o Whisper diz que o 2º trecho termina aos 9 s; a fala acaba aos 8 s
                yield N(start=a - offset, end=end - offset, text=text, avg_logprob=-0.2), N(language="pt")
                if len(offsets) == 1 and k == 1:
                    raise RuntimeError("CUDA failed with error out of memory")

        release = mock.Mock(return_value=True)
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "_vram", return_value=(9.0, 3.2)), \
                mock.patch.object(transcribe, "_model", return_value=object()), \
                mock.patch.object(transcribe, "_segments", new=fake_segments), \
                mock.patch.object(transcribe, "_loaded_compute", return_value="int8_float16"):
            r = transcribe._run([0.0] * (16000 * 12), "large-v3", lambda *a: None, lambda: None, 12.0, 1.0, 1.0, False,
                                release=release)
        release.assert_called_once()
        self.assertEqual(r["device"], "cuda")                    # continuou na GPU, não caiu para a CPU
        self.assertEqual(offsets, [0.0, 0.0])                    # a nova tentativa recebe o áudio inteiro
        self.assertEqual([s["text"] for s in r["segments"]],     # nada perdido, nada repetido
                         ["Primeiro trecho aqui.", "Segundo trecho ali.", "Terceiro trecho final."])


class RetryReleasesModel(unittest.TestCase):
    """Revisão do Codex: o modelo que falhou tem de sair da memória antes de o substituto ser criado (na RTX 3060,
    sem isto, a recarga começava com ~2 GB a menos de VRAM)."""

    def test_failed_model_is_released_before_replacement_loads(self):
        import weakref
        from types import SimpleNamespace as N

        class Model:  # o Whisper real segura VRAM enquanto existir uma referência
            pass

        made, alive_at_load = [], []

        def fake_model(name, device):
            alive_at_load.append([r() is not None for r in made])  # algum modelo anterior ainda vivo?
            if len(made) == 1:
                made.append(weakref.ref(Model()))
                raise RuntimeError("CUDA failed with error out of memory")  # a própria recarga falha
            m = Model()
            made.append(weakref.ref(m))
            return m

        def fake_segments(model, samples, check, opts):  # como o real: o gerador guarda o modelo no frame
            yield N(start=0.0, end=4.0, text="Antes da falha.", avg_logprob=-0.2), N(language="pt")
            if len(made) == 1:
                raise RuntimeError("CUDA failed with error out of memory")
            yield N(start=4.0, end=7.0, text="Depois da falha.", avg_logprob=-0.2), N(language="pt")

        samples = [0.0] * (16000 * 10)
        with mock.patch.object(transcribe, "has_gpu", return_value=True), \
                mock.patch.object(transcribe, "_vram", return_value=(9.0, 3.2)), \
                mock.patch.object(transcribe, "_model", new=fake_model), \
                mock.patch.object(transcribe, "_segments", new=fake_segments), \
                mock.patch.object(transcribe, "_loaded_compute", return_value="int8"):  # new=: um Mock guardaria o modelo
            r = transcribe._run(samples, "large-v3", lambda *a: None, lambda: None, 10.0, 1.0, 1.0, False,
                                release=lambda: True)
        self.assertEqual(alive_at_load, [[], [False], [False, False]])  # GPU → GPU (falha ao carregar) → CPU
        self.assertEqual(r["device"], "cpu")
        self.assertEqual([s["text"] for s in r["segments"]], ["Antes da falha.", "Depois da falha."])


class Speeds(unittest.TestCase):
    def test_4x_always_turbo_and_experimental(self):
        with mock.patch.object(transcribe, "downloaded", return_value=True):
            for m in ("small", "large-v3", transcribe.PARAKEET, "large-v3-turbo"):
                name, warn = transcribe.for_speed(m, 4)
                self.assertEqual(name, "large-v3-turbo")
                self.assertIn("experimental", warn)
        with mock.patch.object(transcribe, "downloaded", return_value=False):
            name, warn = transcribe.for_speed(transcribe.PARAKEET, 4)
            self.assertEqual(name, transcribe.PARAKEET)
            self.assertIn("Baixe", warn)

    def test_suggest_speed_never_claims_4x(self):
        self.assertEqual(transcribe.suggest_speed(2.1)[:2], (1.0, False))
        self.assertEqual(transcribe.suggest_speed(2.6)[:2], (1.0, True))      # perto do limite
        speed, unsure, note = transcribe.suggest_speed(5.0)
        self.assertEqual((speed, unsure), (2.0, True))
        self.assertIn("4×", note)
        for collapsed in (0.06, None):                                         # padrão observado em fala 4x
            speed, unsure, note = transcribe.suggest_speed(collapsed)
            self.assertTrue(unsure)
            self.assertIn("4×", note)

    def test_4x_uses_its_options(self):
        seen = {}

        class M:
            def transcribe(self, samples, **kw):
                seen.update(kw)
                return iter([]), types.SimpleNamespace(language="pt", duration=1)
        list(transcribe._segments(M(), np.zeros(10, dtype=np.float32), lambda: None, transcribe.SPEED_OPTIONS[4]))
        self.assertFalse(seen["condition_on_previous_text"])
        list(transcribe._segments(M(), np.zeros(10, dtype=np.float32), lambda: None))
        self.assertTrue(seen["condition_on_previous_text"])


if __name__ == "__main__":
    unittest.main()
