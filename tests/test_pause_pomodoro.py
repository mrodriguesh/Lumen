"""Pausar captura (lumen/record.py, vision.Watch) e Pomodoro (lumen/pomodoro.py): cada um sozinho e os dois juntos."""
import json
import shutil
import sys
import threading
import time
import types
import unittest
import urllib.request
import wave
from pathlib import Path
from unittest import mock

import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen)
from lumen import AppError, pomodoro, record, sources, store, understanding, vision

PAUSED_DC = 0.77  # o som “do intervalo”: se aparecer no WAV, a pausa vazou


class Sound:
    """soundcard falso: devolve um nível constante (o teste troca o nível durante a pausa)."""

    def __init__(self):
        self.level, self.reads = 0.3, 0

    def module(self):
        snd = self

        class Rec:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def record(self, numframes):
                time.sleep(0.004)
                snd.reads += 1
                return np.full((numframes, 2), snd.level, "float32")

        mic = types.SimpleNamespace(recorder=lambda **k: Rec())
        return types.SimpleNamespace(default_speaker=lambda: types.SimpleNamespace(name="Alto-falantes"),
                                     get_microphone=lambda **k: mic)


def until(cond, timeout=10):
    end = time.time() + timeout
    while not cond():
        if time.time() > end:
            raise AssertionError("tempo esgotado")
        time.sleep(0.005)


def samples(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32767, w.getnframes() / w.getframerate()


class CapturePause(unittest.TestCase):
    def setUp(self):
        self.snd = Sound()
        self.mods = mock.patch.dict(sys.modules, {"soundcard": self.snd.module()})
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.addCleanup(lambda: record.status()["active"] and record.discard())

    def pause_once(self, hold_s=0.4):
        record.pause()
        self.snd.level = PAUSED_DC
        frozen = record.status()["seconds"]
        reads = self.snd.reads
        time.sleep(hold_s)
        st = record.status()
        self.assertEqual(st["seconds"], frozen)  # nada foi gravado
        self.assertTrue(st["paused"])
        self.assertEqual(st["level"], 0.0)
        self.assertGreater(self.snd.reads, reads)  # o som segue sendo lido (e descartado): o driver não acumula
        self.snd.level = 0.3
        record.resume()

    def test_pause_stops_audio_and_resume_continues_same_file(self):  # testes 1 e 3
        record.start("pausa")
        until(lambda: record.status()["seconds"] >= 1)
        path = record._state["path"]
        self.pause_once()
        until(lambda: record.status()["seconds"] >= 3.2)
        self.assertEqual(record._state["path"], path)  # a mesma sessão, o mesmo arquivo
        r = record.stop()
        x, dur = samples(r["path"])
        self.assertFalse((np.abs(x - PAUSED_DC) < 0.01).any(), "som do intervalo entrou na gravação")
        self.assertAlmostEqual(dur, sources.probe(r["path"])["duration"], places=1)
        Path(r["path"]).unlink()

    def test_many_pauses_no_duplication_and_no_silence(self):  # testes 4 e 5
        record.start("muitas pausas")
        until(lambda: record.status()["seconds"] >= 0.5)
        clicks = []

        def spam(fn):
            try:
                fn()
            except AppError:
                clicks.append("erro")
        for _ in range(6):  # cliques rápidos, de janelas diferentes ao mesmo tempo
            ts = [threading.Thread(target=spam, args=(record.pause,)) for _ in range(3)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.snd.level = PAUSED_DC
            time.sleep(0.15)
            self.snd.level = 0.3
            ts = [threading.Thread(target=spam, args=(record.resume,)) for _ in range(3)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            time.sleep(0.15)
        self.assertEqual(clicks, [])
        st = record.status()
        self.assertEqual(st["pause_count"], 6)  # cliques repetidos não criaram pausas a mais
        paused = sum(p["to"] - p["from"] for p in record._state["pauses"])
        self.assertGreater(paused, 6 * 0.15 * 0.8)  # as pausas ficam marcadas (tempo real = gravado + pausas)
        self.assertGreater(st["elapsed"], paused)
        until(lambda: record.status()["seconds"] >= 3)
        r = record.stop()
        x, dur = samples(r["path"])
        self.assertFalse((np.abs(x - PAUSED_DC) < 0.01).any())
        self.assertLess(abs(dur - record._state["seconds"]), 0.3)  # o arquivo tem só o tempo gravado
        self.assertTrue((np.abs(x - 0.3) < 0.01).all())  # nem silêncio no lugar das pausas
        Path(r["path"]).unlink()

    def test_stop_while_paused(self):  # teste 6
        record.start("parar pausada")
        until(lambda: record.status()["seconds"] >= 3.2)
        record.pause()
        r = record.stop()
        st = record.status()
        self.assertFalse(st["active"])
        self.assertFalse(st["paused"])
        self.assertIsNotNone(record._state["pauses"][-1]["to"])
        self.assertIsNone(st["recovered"])  # terminou direito: nada a recuperar
        self.assertGreaterEqual(sources.probe(r["path"])["duration"], 3)
        Path(r["path"]).unlink()
        with self.assertRaises(AppError):
            record.pause()  # sem gravação, pausar não faz nada escondido

    def test_music_filter_on_and_off(self):  # testes 7 e 8
        for on in (True, False):
            store.save_config({**store.DEFAULTS, "music_filter": on})
            with mock.patch("lumen.loopback.music_app", return_value=None):
                record.start("filtro")
                until(lambda: record.status()["seconds"] >= 1.6)
                self.pause_once(0.2)
                until(lambda: record.status()["seconds"] >= 3.2)
                self.assertEqual(bool(record.status().get("music_filter")), on)
                r = record.stop()
            x, _ = samples(r["path"])
            self.assertFalse((np.abs(x - PAUSED_DC) < 0.01).any())
            Path(r["path"]).unlink()
        store.save_config(dict(store.DEFAULTS))

    def test_writing_understanding_while_paused(self):  # teste 9
        understanding.start("aula-pausa", "Aula", "Curso", {"kind": "recording"})
        record.start("nota")
        until(lambda: record.status()["seconds"] >= 0.3)
        record.pause()
        v = understanding.save_draft("aula-pausa", "Escrevendo durante a pausa da captura.", time.time() * 1000)
        self.assertEqual(v["text"], "Escrevendo durante a pausa da captura.")
        self.assertTrue(record.status()["paused"])  # escrever não muda a captura
        record.discard()

    def test_crash_while_paused_is_recovered(self):  # teste 10
        record.start("queda")
        until(lambda: record.status()["seconds"] >= 3.5)
        record.pause()
        path = record._state["path"]
        crash = Path(store.DATA) / "crash"
        crash.mkdir(exist_ok=True)
        # o que fica no disco se o app fechar agora (o WAV aberto e a sessão)
        shutil.copy(path, crash / path.name)
        shutil.copy(path.with_suffix(".session"), crash / "x.session")
        with open(crash / path.name, "ab") as f:
            f.write(b"\x01")  # meio trecho: o processo morreu no meio de uma escrita
        record.discard()
        shutil.copy(crash / path.name, path)
        shutil.copy(crash / "x.session", path.with_suffix(".session"))
        lost = record.status()["recovered"]
        self.assertEqual(lost["pauses"], 1)
        self.assertGreaterEqual(lost["seconds"], 3.4)
        r = record.recover(True)
        self.assertEqual(r["path"], str(path))
        self.assertGreaterEqual(sources.probe(r["path"])["duration"], 3.4)  # WAV válido
        self.assertIsNone(record.status()["recovered"])
        Path(r["path"]).unlink()

    def test_exit_keeps_recording_for_next_start(self):
        record.start("saindo")
        until(lambda: record.status()["seconds"] >= 3.2)
        record.pause()
        r = record.stop(keep=True)  # “Sair do Lumen” com a gravação pausada
        self.assertIsNotNone(record.status()["recovered"])
        record.start("outra")  # a próxima gravação não apaga a guardada
        with self.assertRaises(AppError):
            record.recover(True)  # com outra gravação em andamento, não mistura
        record.discard()
        self.assertEqual(record.status()["recovered"]["name"], "saindo.wav")
        self.assertIsNone(record.recover(False))
        self.assertFalse(Path(r["path"]).exists())
        self.assertIsNone(record.status()["recovered"])

    def test_orphan_or_broken_session_file(self):
        up = store.WORK / "uploads"
        up.mkdir(parents=True, exist_ok=True)
        (up / "sem_wav.session").write_text("{}", "utf-8")
        self.assertIsNone(record.status()["recovered"])
        self.assertFalse((up / "sem_wav.session").exists())  # a gravação já não existe: o .session sai
        (up / "abc_meio.wav").write_bytes(b"RIFF" + bytes(40) + bytes(16000 * 2 * 4))
        (up / "abc_meio.session").write_text('{"pauses": [', "utf-8")  # o app caiu gravando o .session
        self.assertEqual(record.status()["recovered"]["name"], "meio.wav")
        with self.assertRaises(AppError):
            record.recover(True)  # cabeçalho que não é de WAV: avisa, não usa
        self.assertFalse((up / "abc_meio.wav").exists())

    def test_screen_watch_gets_the_pause(self):
        made = {}
        store.save_config({**store.DEFAULTS, "watch_screen": True})
        with mock.patch.object(vision, "Watch", side_effect=lambda *a, **k: made.update(k) or mock.Mock()):
            record.start("tela")
            self.assertFalse(made["hold"]())
            record.pause()
            self.assertTrue(made["hold"]())
            record.resume()
            self.assertFalse(made["hold"]())
            record.discard()
        store.save_config(dict(store.DEFAULTS))


class ScreenHold(unittest.TestCase):
    def test_no_screen_copies_while_paused(self):  # teste 2 (e volta no teste 3)
        held = threading.Event()
        grabs = []
        rng = np.random.default_rng(0)

        class Grabber:
            def grab(self):
                grabs.append(time.monotonic())
                return rng.integers(0, 255, (360, 640, 4), dtype=np.uint8), None, (0, 0)

        folder = Path(store.DATA) / "hold.screens"
        with mock.patch.object(vision, "INTERVAL_S", 0.02):
            w = vision.Watch(folder, lambda: 1.0, vision.MODEL, live=False, grabber=Grabber(), hold=held.is_set)
            until(lambda: len(grabs) >= 5)
            held.set()
            time.sleep(0.1)
            n = len(grabs)
            time.sleep(0.4)
            self.assertLessEqual(len(grabs) - n, 0)  # nenhuma cópia durante a pausa
            self.assertIsNone(w.picker.scenes.prev)  # ao voltar, compara do zero (não junta antes e depois)
            held.clear()
            until(lambda: len(grabs) >= n + 5)
            w.stop()


class Pomodoro(unittest.TestCase):
    T0 = 1_800_000_000.0

    def setUp(self):
        pomodoro._s = None
        (store.DATA / "pomodoro.json").unlink(missing_ok=True)

    def test_timer_pause_resume_reset(self):  # testes 1 a 4
        t = self.T0
        v = pomodoro.act("play", now=t)
        self.assertTrue(v["running"])
        self.assertEqual(pomodoro.view(t + 60)["left"], 25 * 60 - 60)
        pomodoro.act("pause", now=t + 60)
        self.assertEqual(pomodoro.view(t + 900)["left"], 1440)  # pausado: parado
        pomodoro.act("play", now=t + 900)
        self.assertEqual(pomodoro.view(t + 960)["left"], 1380)  # continua do mesmo ponto
        v = pomodoro.act("reset", now=t + 961)
        self.assertEqual((v["left"], v["running"], v["phase"]), (1500, False, "focus"))

    def test_skip_cycles_and_long_break(self):  # teste 5
        t = self.T0
        phases = [pomodoro.act("skip", now=t + i)["phase"] for i in range(8)]
        self.assertEqual(phases, ["short", "focus", "short", "focus", "short", "focus", "long", "focus"])
        self.assertEqual(pomodoro.view(t + 9)["done"], 0)
        pomodoro.act("skip", now=t + 10)
        pomodoro.act("skip", now=t + 11)
        v = pomodoro.act("reset", now=t + 12)  # já no início: a sequência recomeça pelo foco
        v = pomodoro.act("reset", now=t + 12)
        self.assertEqual((v["phase"], v["done"]), ("focus", 0))
        self.assertIsNone(v["event"])  # pular não avisa: só o fim natural de uma etapa

    def test_change_to_50_minutes(self):  # teste 6
        t = self.T0
        v = pomodoro.act("settings", {"focus": 50, "short": 10, "long": 20}, now=t)
        self.assertEqual(v["left"], 3000)  # etapa ainda não começada: já vale
        pomodoro.act("play", now=t)
        pomodoro.act("settings", {"focus": 25}, now=t + 60)
        self.assertEqual(pomodoro.view(t + 60)["left"], 2940)  # a etapa em andamento não muda
        pomodoro.act("settings", {"focus": 50}, now=t + 61)
        pomodoro.act("skip", now=t + 62)
        v = pomodoro.act("skip", now=t + 63)
        self.assertEqual((v["phase"], v["left"]), ("focus", 3000))  # o ciclo novo usa 50 min

    def test_minimized_or_suspended_uses_real_time(self):  # testes 7 e 10
        t = self.T0
        pomodoro.act("play", now=t)
        v = pomodoro.view(t + 26 * 60)  # nenhum tick nesse tempo (janela minimizada, PC suspenso)
        self.assertEqual((v["phase"], v["running"], v["left"]), ("short", False, 300))
        self.assertEqual((v["event"]["ended"], v["event"]["at"]), ("focus", t + 1500))
        pomodoro.act("settings", {"auto": True}, now=t + 26 * 60)
        pomodoro.act("play", now=t + 26 * 60)
        v = pomodoro.view(t + 26 * 60 + 5 * 60 + 25 * 60 + 2 * 60)  # pausa curta, foco inteiro e 2 min da pausa
        self.assertEqual((v["phase"], v["running"], v["done"]), ("short", True, 2))
        self.assertAlmostEqual(v["left"], 180)

    def test_state_survives_closing_windows_and_restart(self):  # testes 8 e 9
        t = self.T0
        a = pomodoro.act("play", now=t)
        pomodoro._s = None  # outra janela / o app abriu de novo: lê do disco
        b = pomodoro.view(t + 30)
        self.assertEqual((b["ends_at"], b["left"]), (a["ends_at"], 1470))

    def test_bad_file_and_settings(self):
        (store.DATA / "pomodoro.json").write_text('{"phase": "x", "running": true, "remaining": -5, "done": "a"}', "utf-8")
        pomodoro._s = None
        v = pomodoro.view(self.T0)
        self.assertEqual((v["phase"], v["running"], v["left"]), ("focus", False, 1500))
        v = pomodoro.act("settings", {"focus": 0, "short": 999, "cycles": True, "sound": "sim"}, now=self.T0)
        self.assertEqual((v["settings"]["focus"], v["settings"]["short"], v["settings"]["cycles"], v["settings"]["sound"]),
                         (1, 60, 4, True))
        with self.assertRaises(AppError):
            pomodoro.act("explodir", now=self.T0)

    def test_sound_never_goes_into_the_recording(self):
        snd = mock.Mock(SND_MEMORY=4)
        with mock.patch.dict(sys.modules, {"winsound": snd}), mock.patch.object(pomodoro.os, "name", "nt"), \
                mock.patch("threading.Thread") as th:
            for st, plays in (({"active": True, "paused": False}, False), ({"active": True, "paused": True}, True),
                              ({"active": False}, True)):
                th.reset_mock()
                with mock.patch.object(record, "status", return_value=st):
                    pomodoro._chime()
                self.assertEqual(th.called, plays, st)


class Independent(unittest.TestCase):
    """Testes 11 a 13 e concorrência: pausar um nunca pausa o outro."""

    def setUp(self):
        pomodoro._s = None
        (store.DATA / "pomodoro.json").unlink(missing_ok=True)
        self.snd = Sound()
        self.mods = mock.patch.dict(sys.modules, {"soundcard": self.snd.module()})
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.addCleanup(lambda: record.status()["active"] and record.discard())

    def test_states_are_independent(self):
        record.start("juntos")
        pomodoro.act("play")
        pomodoro.act("pause")  # teste 11: Pomodoro pausado, captura gravando
        s = record.status()["seconds"]
        until(lambda: record.status()["seconds"] > s + 0.3)
        self.assertFalse(record.status()["paused"])
        pomodoro.act("play")
        record.pause()  # teste 12: captura pausada, Pomodoro rodando
        self.assertTrue(pomodoro.view()["running"])
        pomodoro.act("pause")  # teste 13: os dois pausados
        record.resume()
        self.assertFalse(pomodoro.view()["running"])
        self.assertFalse(record.status()["paused"])
        pomodoro.act("play")
        record.pause()
        record.resume()
        self.assertTrue(pomodoro.view()["running"])

    def test_stress_both_at_once(self):
        record.start("stress")
        errors = []

        def hammer(fn, n):
            for i in range(n):
                try:
                    fn(i)
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
        cap = threading.Thread(target=hammer, args=(lambda i: (record.pause if i % 2 == 0 else record.resume)(), 60))
        pom = threading.Thread(target=hammer, args=(lambda i: pomodoro.act(["play", "pause", "skip", "reset"][i % 4]), 200))
        cap.start(); pom.start(); cap.join(); pom.join()
        self.assertEqual(errors, [])
        self.assertFalse(record.status()["paused"])  # 60 cliques: termina retomada
        self.assertEqual(record.status()["pause_count"], 30)
        self.assertEqual(threading.active_count() < 50, True)  # nenhuma thread esquecida
        r = record.stop() if record.status()["heard"] and record.status()["seconds"] >= 3 else None
        if r:
            Path(r["path"]).unlink()


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lumen import server
        cls.server = server
        cls.httpd = server.serve()
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, path, body=None):
        r = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                                   headers={"X-Lumen-Token": self.server.TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())

    def test_routes(self):
        pomodoro._s = None
        v = self.call("/api/pomodoro", {"action": "play"})
        self.assertTrue(v["running"])
        self.assertTrue(self.call("/api/widget")["pomodoro"]["running"])  # a barra vê o mesmo timer
        self.assertFalse(self.call("/api/pomodoro", {"action": "pause"})["running"])
        with self.assertRaises(urllib.error.HTTPError):
            self.call("/api/record/pause", {})  # sem gravação
        self.assertIsNone(self.call("/api/record")["recovered"])
        for name in ("/pomodoro.js",):
            with urllib.request.urlopen(self.url + name, timeout=10) as resp:
                self.assertIn(b"Pomodoro", resp.read())


if __name__ == "__main__":
    unittest.main()
