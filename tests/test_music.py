"""Filtro de música externa (lumen/music.py, lumen/loopback.py): regras de decisão, falhas, cache, o pipeline com o
filtro desligado (igual ao antigo) e ligado, e a gravação sem o app de música. A qualidade da transcrição antes e
depois do filtro é medida em bench/music_bench.py (fala e música reais, WER)."""
import hashlib
import json
import math
import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import Cancelled, jobs, music, record, server, speaker, store, transcribe
from tests.test_flow import wait

HOP, SR = music.HOP, 16000


def scores(n, music_on=(), speech=0.0):
    """Saída falsa de music.detect: música nos quadros de `music_on`, fala constante."""
    m = np.zeros(n, np.float32)
    m[list(music_on)] = 0.9
    return {"speech": np.full(n, speech, np.float32), "sing": np.zeros(n, np.float32), "music": m,
            "emb": np.zeros((n, 4), np.float32), "rms": np.full(n, 0.1, np.float32)}


class Decision(unittest.TestCase):
    """music.clean com detector, separador e sonda simulados: só as regras."""

    def run_clean(self, n, music_on, p, mix_speech=0.0, sep_speech=0.9, mode=music.MODE, voice=0.2, sim=None,
                  voices=None):
        """sim: similaridade de cada quadro com o locutor da aula (None = sem referência de voz, como na v1)."""
        x = np.full(n * HOP, 0.8, np.float32)
        sep = np.full(n * HOP, voice, np.float32)  # “voz separada” reconhecível; 0,2 → música 9,5 dB acima da voz
        calls = iter([scores(n, music_on, mix_speech), scores(n, (), sep_speech)])
        ref = (None, 0) if sim is None else (np.asarray(sim, float), 1)
        with mock.patch.object(music, "detect", side_effect=lambda a: next(calls)), \
                mock.patch.object(music, "separate", side_effect=lambda a, check: sep[:len(a)]) as s, \
                mock.patch.object(music, "voices", side_effect=voices or (lambda *a: ref)), \
                mock.patch.object(music, "speech_probability", return_value=np.asarray(p, np.float32)):
            y, rep = music.clean(x, mode=mode)
        self.assertTrue(np.all(x == 0.8), "o áudio de entrada nunca é alterado")
        return x, y, rep, s

    def frame(self, y, j):
        return y[j * HOP + HOP // 2 + music.FADE:(j + 1) * HOP + HOP // 2 - music.FADE]

    def test_speech_only_silence_and_noise_are_untouched(self):  # testes 1, 8 e 9: sem música, nada muda
        x, y, rep, s = self.run_clean(20, (), np.ones(20))
        self.assertIs(y, x)
        self.assertFalse(rep["music_detected"] or rep["filtered"])
        s.assert_not_called()  # nem separa

    def test_speech_over_loud_music_uses_separated_voice(self):  # teste 4: fala sob música alta → voz sem instrumentos
        _, y, rep, _ = self.run_clean(30, range(5, 25), np.ones(30))
        self.assertTrue(np.allclose(self.frame(y, 12), 0.2))
        self.assertTrue(np.allclose(self.frame(y, 2), 0.8), "fora da música, o original")
        self.assertEqual(rep["removed_s"], 0)
        self.assertTrue(rep["separated"])

    def test_speech_over_quiet_music_keeps_original(self):  # teste 3: música baixa → o ASR já se vira com o original
        _, y, rep, _ = self.run_clean(30, range(5, 25), np.ones(30), voice=0.6)  # música 6 dB abaixo da voz
        self.assertTrue(np.allclose(self.frame(y, 12), 0.8))
        self.assertFalse(rep["separated"])
        self.assertEqual(rep["removed_s"], 0)

    def test_default_never_silences(self):  # na dúvida, preserva a fala: o modo padrão só marca
        p = np.ones(40)
        p[10:30] = 0.0
        _, y, rep, _ = self.run_clean(40, range(5, 35), p)
        self.assertEqual(rep["removed_s"], 0)
        self.assertGreater(rep["doubt_s"], 8)
        self.assertTrue(np.allclose(self.frame(y, 20), 0.8), "fica o original")

    def test_aggressive_removes_music_alone_and_drops_lyrics(self):  # teste 2 no modo agressivo
        p = np.ones(40)
        p[10:30] = 0.0
        _, y, rep, _ = self.run_clean(40, range(5, 35), p, mode="agressivo")
        self.assertTrue(np.allclose(self.frame(y, 20), 0.0))
        self.assertGreater(rep["removed_s"], 6)  # 9,6 s sem fala; a média em ±5 quadros encolhe as bordas
        a, b = rep["removed"][0]
        segs = [{"start": a + 1, "end": b - 1, "text": "baby I love you"}, {"start": 0.5, "end": 3.0, "text": "redes neurais"}]
        self.assertEqual([s["text"] for s in music.mark(segs, rep)], ["redes neurais"])

    def test_short_gap_between_phrases_is_not_removed(self):  # na dúvida, preserva a fala
        p = np.ones(40)
        p[18:21] = 0.0  # 1,4 s: pausa entre frases, não “só música”
        _, y, rep, _ = self.run_clean(40, range(5, 35), p, mode="agressivo")
        self.assertEqual(rep["removed_s"], 0)
        self.assertGreater(float(np.abs(self.frame(y, 19)).min()), 0.1)

    def test_doubt_keeps_original_and_marks_segments(self):  # teste 5: voz e música juntas sem certeza → marcado
        _, y, rep, _ = self.run_clean(30, range(5, 25), np.full(30, 0.45))
        self.assertTrue(np.allclose(self.frame(y, 12), 0.8), "na dúvida, o original (a voz isolada realçaria a letra)")
        # entre sep_keep e keep, com a música dominando: a voz separada entra, mas o trecho continua marcado
        _, y2, rep2, _ = self.run_clean(30, range(5, 25), np.full(30, 0.55))
        self.assertTrue(np.allclose(self.frame(y2, 12), 0.2))
        self.assertGreater(rep2["doubt_s"], 5)
        self.assertEqual(rep["removed_s"], 0)
        self.assertGreater(rep["doubt_s"], 5)
        a, b = rep["doubt"][0]
        seg = music.mark([{"start": a + 1, "end": a + 3, "text": "explicação"}], rep)[0]
        self.assertEqual(seg["text"], "explicação")
        self.assertTrue(seg["uncertain"] and seg["music"])
        self.assertIn("música ao fundo", jobs._flags(seg))

    def test_clear_speech_in_the_mix_is_never_replaced(self):  # validação: fala que se ouve bem fica como está
        x, y, rep, s = self.run_clean(30, range(5, 25), np.ones(30), mix_speech=0.9, sep_speech=0.1)
        self.assertIs(y, x)
        self.assertTrue(rep["music_detected"])
        self.assertFalse(rep["filtered"])
        s.assert_not_called()  # nem gasta CPU separando

    def test_music_starting_and_stopping_is_followed(self):  # teste 7
        on = [j for j in range(60) if (j // 10) % 2]
        _, y, rep, _ = self.run_clean(60, on, np.ones(60))
        self.assertTrue(np.allclose(self.frame(y, 15), 0.2))
        self.assertTrue(np.allclose(self.frame(y, 25), 0.8))
        self.assertTrue(np.allclose(self.frame(y, 35), 0.2))

    def test_run_on_the_last_partial_frame(self):  # áudio que não fecha em quadros de 0,48 s (achado no benchmark)
        y = np.ones(10 * HOP + 1000, np.float32)
        for a, b in ((10, 11), (9, 11), (0, 11)):
            music._splice(y, None, a, b)
        self.assertEqual(len(y), 10 * HOP + 1000)
        self.assertTrue(np.all(y[9 * HOP + HOP // 2 + music.FADE:] == 0))

    def test_conservative_mode_marks_more_and_removes_nothing(self):
        p = np.ones(60)
        p[10:50] = np.linspace(0, 0.8, 40)
        reps = [self.run_clean(60, range(5, 55), p, mode=m)[2] for m in ("conservador", "balanceado", "agressivo")]
        self.assertEqual([r["removed_s"] > 0 for r in reps], [False, False, True])
        self.assertGreater(reps[0]["doubt_s"], reps[1]["doubt_s"])

    def test_unknown_mode_falls_back_to_balanced(self):  # config.json editado à mão
        self.assertEqual(self.run_clean(30, range(5, 25), np.ones(30), mode="turbo")[2]["mode"], "balanceado")

    # ---- voz do professor (testes 1 a 6 do pedido; os de áudio real ficam em RealModels e no benchmark)

    def test_teacher_voice_is_protected_even_with_the_probe_in_doubt(self):  # teste 2: professor + instrumental
        p, sim = np.full(30, 0.3), np.full(30, 0.7)
        for mode in music.MODES:
            _, y, rep, _ = self.run_clean(30, range(5, 25), p, sim=sim, mode=mode)
            self.assertEqual(rep["removed_s"], 0, mode)
            self.assertEqual(rep["doubt_s"], 0, "voz do professor não é marcada como música")
            self.assertGreater(rep["teacher_s"], 5)
            self.assertTrue(np.allclose(self.frame(y, 12), 0.2), "a voz dele, sem os instrumentos")

    def test_other_voice_alone_never_removes(self):  # testes 3 e 4: cantor, rapper; e o 6: voz nova legítima
        p, sim = np.ones(30), np.full(30, 0.05)  # a sonda acha que é fala, mas a voz não parece a de quem ensina
        for mode in music.MODES:
            rep = self.run_clean(30, range(5, 25), p, sim=sim, mode=mode)[2]
            self.assertEqual(rep["removed_s"], 0, mode)
        self.assertEqual(self.run_clean(30, range(5, 25), p, sim=sim)[2]["doubt_s"], 0,
                         "no balanceado, voz diferente sozinha não marca (marcaria a fala do professor)")
        rep = self.run_clean(30, range(5, 25), p, sim=sim, mode="agressivo")[2]
        self.assertGreater(rep["doubt_s"], 5, "no agressivo, marca: não chega à IA como fato")
        self.assertGreater(rep["other_voice_s"], 5)

    def test_aggressive_silences_other_voice_only_when_the_probe_also_doubts(self):
        sim = np.full(40, 0.05)
        p = np.ones(40)
        p[10:30] = 0.4  # dúvida, voz diferente da do professor
        rep = self.run_clean(40, range(5, 35), p, sim=sim, mode="agressivo")[2]
        self.assertGreater(rep["removed_s"], 5)
        rep = self.run_clean(40, range(5, 35), np.ones(40), sim=sim, mode="agressivo")[2]
        self.assertEqual(rep["removed_s"], 0, "a sonda tem certeza de fala: voz nova legítima (teste 6) fica")

    def test_new_teacher_under_music_is_not_removed(self):  # teste 6: voz sem referência, sonda diz fala
        sim = np.full(40, np.nan)  # nunca falou sem música: não há como comparar
        for mode in music.MODES:
            rep = self.run_clean(40, range(5, 35), np.ones(40), sim=sim, mode=mode)[2]
            self.assertEqual(rep["removed_s"], 0, mode)

    def test_music_alone_is_not_removed_even_in_aggressive(self):  # professor tocando uma música para a turma
        rep = self.run_clean(40, range(5, 35), np.zeros(40), mode="agressivo")[2]
        self.assertEqual(rep["removed_s"], 0, "sem fala por baixo, a música é parte da aula: só marcada")
        self.assertGreater(rep["doubt_s"], 10)
        self.assertEqual(rep["background_s"], 0)

    def test_voice_reference_failure_decides_like_before(self):  # fail-safe
        def boom(*a):
            raise RuntimeError("modelo de voz")
        ref = self.run_clean(30, range(5, 25), np.full(30, 0.5))[2]
        rep = self.run_clean(30, range(5, 25), np.full(30, 0.5), voices=boom)[2]
        self.assertEqual((rep["doubt_s"], rep["removed_s"], rep["speakers"]), (ref["doubt_s"], ref["removed_s"], 0))

    def test_all_mode_parameters_live_in_one_table(self):
        self.assertEqual(set(music.MODES), {"conservador", "balanceado", "agressivo"})
        self.assertEqual(len({frozenset(m) for m in music.MODES.values()}), 1, "os três modos têm os mesmos parâmetros")
        self.assertEqual(music.MODE, "balanceado")
        c, b, a = (music.MODES[m] for m in ("conservador", "balanceado", "agressivo"))
        self.assertGreaterEqual(c["keep"], b["keep"])
        self.assertGreaterEqual(c["dominant_db"], b["dominant_db"])
        self.assertGreaterEqual(b["dominant_db"], a["dominant_db"])
        self.assertEqual((c["mute"], b["mute"]), (0, 0), "só o agressivo silencia")


class Speakers(unittest.TestCase):
    def test_two_teachers_give_two_speakers(self):  # teste 5: não assume um professor só
        rnd = np.random.default_rng(0)
        a, b = rnd.standard_normal(256), rnd.standard_normal(256)
        E = np.stack([v + 0.3 * rnd.standard_normal(256) for v in [a] * 5 + [b] * 4])
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        spk = speaker.cluster(E, np.ones(len(E)), speaker.CLUSTER_SIM)
        self.assertEqual([w for _, w in spk], [5.0, 4.0])
        self.assertGreater(speaker.similarity(b / np.linalg.norm(b), spk), 0.9, "os dois são locutores da aula")

    def test_fbank_shape(self):
        self.assertEqual(speaker.fbank(np.zeros(SR, np.float32) + 0.01).shape, (98, 80))

    def test_gpu_failure_mid_run_retries_on_cpu(self):  # fail-safe da GPU
        class S:
            def __init__(self, gpu):
                self.gpu = gpu

            def get_providers(self):
                return ["DmlExecutionProvider" if self.gpu else "CPUExecutionProvider"]

            def run(self, names, feeds):
                if self.gpu:
                    raise RuntimeError("dispositivo removido")
                return ["ok"]
        made = []

        def session(model):
            if model not in music._sessions:
                music._sessions[model] = S(gpu=not music._gpu_failed)
                made.append(music._sessions[model])
            return music._sessions[model]
        with mock.patch.object(music, "_session", side_effect=session), mock.patch.object(music, "_gpu_failed", False):
            self.assertEqual(music._run(music.SEPARATOR, {}), ["ok"])
            self.assertEqual([m.gpu for m in made], [True, False])
        music.release()


def write_wav(path, seconds=3):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 9))) for i in range(SR * seconds)))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Prepare(unittest.TestCase):
    """Original intacto, cache, e falha nunca impede a transcrição (cai no original e diz por quê)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="lumen-music-"))
        self.src = self.dir / "aula.wav"
        write_wav(self.src)
        self.before = digest(self.src)
        self.work = self.dir / "work"
        self.work.mkdir()
        self.ready = mock.patch.object(music, "_have", return_value=True)
        self.ready.start()

    def tearDown(self):
        self.ready.stop()
        self.assertEqual(digest(self.src), self.before, "o arquivo original nunca é alterado")
        self.assertEqual(list(self.work.glob("*.tmp")), [], "nenhum temporário esquecido")
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_filtered_audio_is_a_cached_copy(self):
        rep = {"filtered": True, "music_detected": True, "music_confidence": 0.9, "speech_confidence": 0.8,
               "separation_confidence": 0.9, "separated": True, "removed_s": 1.0, "separated_s": 2.0, "doubt_s": 0,
               "preserved_s": 0, "seconds": 0.1}
        with mock.patch.object(music, "clean", side_effect=lambda x, *a, **k: (x * 0.5, rep)) as c:
            path, got = music.prepare(self.src, self.work)
            self.assertNotEqual(Path(path), self.src)
            self.assertEqual(Path(path).parent, self.work)
            self.assertAlmostEqual(float(np.abs(music.audio.load(path)).max()), 0.122, delta=0.01)
            path2, got2 = music.prepare(self.src, self.work)
        self.assertEqual(c.call_count, 1, "o mesmo áudio não é processado de novo")
        self.assertEqual(path2, path)
        self.assertTrue(got2["cached"])

    def test_no_music_returns_original_without_writing(self):
        with mock.patch.object(music, "clean", side_effect=lambda x, *a, **k: (x, {"filtered": False, "music_detected": False,
                               "music_confidence": 0, "speech_confidence": None, "separation_confidence": None,
                               "separated": False, "removed_s": 0, "separated_s": 0, "doubt_s": 0, "preserved_s": 0})):
            path, rep = music.prepare(self.src, self.work)
        self.assertEqual(Path(path), self.src)
        self.assertEqual(list(self.work.glob("*.wav")), [])

    def test_any_failure_falls_back_to_original(self):  # detector, modelo, GPU, disco: tudo cai aqui
        for err in (RuntimeError("onnx"), MemoryError(), OSError(28, "disco cheio")):
            with mock.patch.object(music, "clean", side_effect=err):
                path, rep = music.prepare(self.src, self.work)
            self.assertEqual(Path(path), self.src)
            self.assertFalse(rep["filtered"])
            self.assertTrue(rep["error"], "a falha não é escondida")
        self.assertEqual(music._sessions, {}, "modelos soltos mesmo depois de falhar")

    def test_missing_models_fall_back_and_say_why(self):
        with mock.patch.object(music, "_have", return_value=False):
            path, rep = music.prepare(self.src, self.work)
        self.assertEqual(Path(path), self.src)
        self.assertIn("baixados", rep["error"])

    def test_cancel_still_cancels(self):
        with mock.patch.object(music, "clean", side_effect=Cancelled):
            with self.assertRaises(Cancelled):
                music.prepare(self.src, self.work)


class Pipeline(unittest.TestCase):
    """jobs.process com a transcrição simulada: desligado = pipeline antigo; ligado = áudio limpo antes do ASR."""

    def setUp(self):
        store.clear_local_data()
        fd, self.path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        write_wav(self.path, 4)
        self.p = [mock.patch.object(store, "get_token", return_value="secret_test"),
                  mock.patch.object(transcribe, "downloaded", return_value=True),
                  mock.patch.object(transcribe, "speech_rate", return_value=2.2)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        os.unlink(self.path)

    def process(self, on, segments, prepare=None):
        store.save_config({**store.DEFAULTS, "root_page_id": "x", "music_filter": on})
        seen = {}

        def fake(path, *a, **k):
            seen["path"] = path
            return {"segments": [dict(s) for s in segments], "language": "pt", "duration": 4.0, "device": "cpu",
                    "second_opinion": False, "prep": 1.0, "compute": "int8"}
        with mock.patch.object(transcribe, "transcribe", side_effect=fake), \
                mock.patch.object(music, "prepare", side_effect=prepare or AssertionError("filtro chamado")) as prep:
            jobs.start("process", jobs.process, {"kind": "file", "path": self.path, "speed": "1"})
            j = wait()
        return j, seen.get("path"), prep

    SEGS = [{"start": 0.0, "end": 1.5, "text": "Redes neurais funcionam assim.", "uncertain": False},
            {"start": 2.0, "end": 2.9, "text": "baby I love you", "uncertain": False},
            {"start": 3.0, "end": 3.9, "text": "com pesos e vieses.", "uncertain": False}]

    def test_off_is_the_old_pipeline(self):  # teste 11
        j, path, prep = self.process(False, self.SEGS)
        self.assertEqual(j["status"], "done", j.get("error"))
        prep.assert_not_called()
        self.assertEqual(path, self.path, "o ASR recebe o próprio arquivo")
        self.assertEqual(len(j["result"]["segments"]), 3)
        self.assertIsNone(j["result"]["music"])
        self.assertEqual(music._sessions, {}, "nenhum modelo do filtro carregado")
        tr = json.loads((jobs.work_dir(j["result"]["key"]) / "transcript.json").read_text("utf-8"))
        self.assertNotIn("music", tr)
        self.assertNotIn("Música externa", tr["origin"])

    def test_on_filters_before_asr_and_marks_after(self):  # teste 12
        clean = str(Path(tempfile.gettempdir()) / "lumen-limpo.wav")
        rep = {"filtered": True, "music_detected": True, "removed_s": 1.0, "separated_s": 2.0, "doubt_s": 1.0,
               "removed": [[1.9, 3.0]], "doubt": [[3.0, 4.0]], "error": None}
        j, path, prep = self.process(True, self.SEGS, prepare=lambda *a, **k: (clean, rep))
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(path, clean, "o ASR recebe o áudio filtrado")
        texts = [s["text"] for s in j["result"]["segments"]]
        self.assertNotIn("baby I love you", texts)  # letra dentro do trecho só de música: fora do conteúdo
        self.assertIn("música ao fundo", j["result"]["segments"][-1]["flags"])
        self.assertEqual(j["result"]["segments"][-1]["text"], "com pesos e vieses.", "o texto nunca é trocado")
        self.assertTrue(j["result"]["music"]["filtered"])
        tr = json.loads((jobs.work_dir(j["result"]["key"]) / "transcript.json").read_text("utf-8"))
        self.assertIn("Música externa filtrada", tr["origin"])

    def test_on_but_filter_failed_transcribes_original(self):
        j, path, _ = self.process(True, self.SEGS, prepare=lambda p, *a, **k: (str(p), {"filtered": False, "error": "falha no filtro"}))
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(path, self.path)
        self.assertEqual(len(j["result"]["segments"]), 3)
        self.assertEqual(j["result"]["music"]["error"], "falha no filtro")

    def test_only_music_explains_how_to_recover(self):
        rep = {"filtered": True, "removed_s": 4.0, "removed": [[0.0, 4.0]], "doubt": []}
        j, _, _ = self.process(True, self.SEGS[1:2], prepare=lambda *a, **k: ("x.wav", rep))
        self.assertEqual(j["status"], "error")
        self.assertIn("Filtrar música externa", j["error"]["action"])


class Settings(unittest.TestCase):
    def test_toggle_is_saved_and_defaults_off(self):
        store.clear_local_data()
        store.save_config(dict(store.DEFAULTS))
        self.assertFalse(store.load_config()["music_filter"])
        with store.LOCK:
            server._apply_settings({"music_filter": True})
        self.assertTrue(store.load_config()["music_filter"])
        with store.LOCK:
            server._apply_settings({"music_filter": "sim"})  # só True liga
        self.assertFalse(store.load_config()["music_filter"])

    def test_mode_is_saved_and_defaults_balanced(self):
        store.clear_local_data()
        store.save_config(dict(store.DEFAULTS))
        self.assertEqual(store.load_config()["music_mode"], "balanceado")
        with store.LOCK:
            server._apply_settings({"music_mode": "conservador"})
            server._apply_settings({"music_mode": "turbo"})  # inválido: ignorado
        self.assertEqual(store.load_config()["music_mode"], "conservador")

    def test_ui_has_the_toggle(self):
        html = (Path(server.WEB) / "index.html").read_text("utf-8")
        self.assertIn("Filtrar música externa", html)
        for m in music.MODES:
            self.assertIn(f'value="{m}"', html)
        self.assertIn("Detecta e reduz músicas externas que podem interferir na transcrição do conteúdo estudado.", html)


class FakeRec:
    entered = False

    def __enter__(self):
        self.entered = True
        return self


class Recording(unittest.TestCase):
    """Isolar a fonte: com o filtro, o app de música fica de fora; qualquer problema volta à gravação normal."""

    def setUp(self):
        self.normal = FakeRec()
        self.mic = mock.Mock()
        self.mic.recorder.return_value = self.normal
        record._state.clear()

    def open(self, on, app=("1234", "Spotify"), fails=False):
        store.save_config({**store.DEFAULTS, "music_filter": on})
        from lumen import loopback
        isolated = FakeRec()
        with mock.patch.object(record, "_open_loopback", return_value=self.mic), \
                mock.patch.object(loopback, "music_app", return_value=app), \
                mock.patch.object(loopback, "recorder", side_effect=OSError("Windows antigo") if fails else
                                  (lambda *a: isolated)) as lr:
            rec = record._open_recorder()
        return rec, isolated, lr

    def test_off_records_everything_as_before(self):
        rec, _, lr = self.open(False)
        self.assertIs(rec, self.normal)
        self.assertTrue(rec.entered)
        lr.assert_not_called()
        self.assertNotIn("music_filter", record._state)

    def test_on_leaves_the_music_app_out(self):
        rec, isolated, lr = self.open(True)
        self.assertIs(rec, isolated)
        self.assertTrue(rec.entered)
        self.assertEqual(lr.call_args[0][0], "1234")
        self.assertEqual(record._state.get("isolated"), "Spotify")

    def test_on_without_music_app_or_when_windows_refuses(self):
        for kw in ({"app": None}, {"fails": True}):
            record._state.clear()
            rec, _, _ = self.open(True, **kw)
            self.assertIs(rec, self.normal)
            self.assertTrue(record._state.get("music_filter"))
            self.assertNotIn("isolated", record._state)


BENCH = Path(__file__).parent.parent / "bench" / ".data"


@unittest.skipUnless(music.ready() and (BENCH / "manifest_full.json").exists() and (BENCH / "musdb7" / "npz").exists(),
                     "modelos do filtro ou dados do benchmark ausentes (bench/music_bench.py fetch/train)")
class RealModels(unittest.TestCase):
    """Detector, separador e sonda de verdade, sem o ASR (o ASR antes/depois fica no benchmark)."""

    @classmethod
    def setUpClass(cls):
        from bench import music_bench as mb
        cls.mb = mb
        man = json.loads((BENCH / "manifest_full.json").read_text("utf-8"))
        cls.speech = [music.audio.load(i["path"]) for i in man if i["set"] == "leitura"][60:63]
        test = sorted((BENCH / "musdb7" / "npz").glob("test__*.npy"))
        # faixa típica (cantada); rap e voz “falada” costumam ficar, na dúvida (bench/RESULTADOS_MUSICA.md)
        cls.song = np.load(next(p for p in test if "Nerve 9" in p.name))

    @classmethod
    def tearDownClass(cls):
        music.release()

    def test_speech_alone_is_not_touched(self):  # teste 1
        for s in self.speech:
            y, rep = music.clean(s)
            self.assertIs(y, s)
            self.assertFalse(rep["music_detected"])

    def test_song_alone_is_marked_not_removed(self):  # teste 2: marca; sem fala por baixo, nem o agressivo tira
        x = self.mb.loop(self.song[0], 20 * SR)
        for mode in music.MODES:
            y, rep = music.clean(x, mode=mode)
            self.assertEqual(rep["removed_s"], 0, mode)
            self.assertGreater(rep["doubt_s"], 12)
            self.assertFalse(rep["separated"], "a voz isolada de uma música realça a letra")

    @unittest.skipUnless((BENCH / "lessons" / "lessons.json").exists(), "aulas do benchmark ausentes")
    def test_teacher_reference_from_the_clean_part(self):  # teste 2 com voz de verdade
        s, _ = self.mb._speech(next(iter(self.mb._talks().values())), 60)
        inst = self.song[0] - self.song[4]
        x = s + self.mb._bed(inst, len(s), 30) * np.sqrt(self.mb.level(s) * 10 ** 0.5 / self.mb.level(inst))
        y, rep = music.clean(x.astype(np.float32))
        self.assertEqual(rep["speakers"], 1, "um professor")
        self.assertGreater(rep["teacher_s"], 5, "a voz dele é reconhecida sob a música")
        self.assertEqual(rep["removed_s"], 0)

    def test_speech_over_loud_instrumental_is_kept(self):  # teste 4
        s = self.speech[0]
        y, rep = music.clean(self.mb.mix(s, self.mb.loop(self.song[0] - self.song[4], len(s)), 10))
        self.assertTrue(rep["separated"])
        self.assertLess(rep["removed_s"], 0.15 * len(s) / SR)

    def test_silence_and_noise_are_not_music(self):  # testes 8 e 9
        rnd = np.random.default_rng(1)
        quiet = (rnd.standard_normal(10 * SR) * 1e-4).astype(np.float32)
        fan = self.mb._synth("fan", len(self.speech[1]), rnd)
        for x in (np.zeros(10 * SR, np.float32), quiet, self.mb.mix(self.speech[1], fan, -10)):
            self.assertFalse(music.clean(x)[1]["music_detected"])


if __name__ == "__main__":
    unittest.main()
