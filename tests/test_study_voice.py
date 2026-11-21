"""Fase 6 (D46 a D52): a voz dos Estudos com um Voice Studio falso. Escolha do motor e a reserva com ele fechado, a voz
padrão que sumiu, os ajustes, a fala do chat sem Markdown nem [S#], os tetos do roteiro, o resumo em áudio pela fila de
jobs (capítulos, cancelamento sem arquivo pela metade), o Range do arquivo e que nenhuma rota de escrita do Voice
Studio é chamada. Dados isolados; nenhum modelo de voz de verdade."""
import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import tests  # noqa: F401
from lumen import AppError, jobs, package, server, store, voice, voicestudio
from lumen.study import learn, listen, settings
from tests import test_study_index as idx
from tests.fake_voicestudio import Fake

ANSWER = ("## Keyframes no Premiere\n\nUm **keyframe** guarda um valor num ponto da linha do tempo [S1].\n\n"
          "- Crie o primeiro no painel *Effect Controls* [S2].\n- Mova a agulha e mude o valor.\n\n```js\nconst x = 1;\n```\n"
          "| Coluna | Valor |\n|---|---|\n| Posição | 10 |\n\nVeja [a documentação](https://exemplo.com).")


def wait_job(timeout=30):
    end = time.monotonic() + timeout
    while jobs.busy() and time.monotonic() < end:
        time.sleep(0.05)
    return jobs.snapshot()


class Base(idx.Base):
    def setUp(self):
        super().setUp()
        self.vs = Fake()
        # a placa e o Ollama de verdade ficam de fora: nenhum teste pede ao Ollama do estudante para soltar a placa
        self.stack += [mock.patch.dict(os.environ, {"LUMEN_VOICESTUDIO_URL": self.vs.url}),
                       mock.patch.object(listen, "AUDIO", self.tmp / "audio"),
                       mock.patch.object(voice, "available", lambda: True),
                       mock.patch.object(listen.transcribe, "gpu_free_gb", lambda: 10.0),
                       mock.patch.object(listen.llm, "release_vram", lambda: False)]
        for p in self.stack[-5:]:
            p.start()
        voicestudio._engine["at"] = -1e9
        voicestudio._pron["at"] = -1e9
        if voicestudio.BACKEND._warm:  # um pré-aquecimento do teste anterior não vaza para este
            voicestudio.BACKEND._warm.join(10)
        voicestudio.BACKEND.failed, voicestudio.BACKEND.state = None, {"phase": "off"}
        # o Whisper de verdade fica de fora; "ligar sozinho" só nos testes do backend (com o processo falso)
        settings.save({"voice": {"verify_long": False, "vs_autostart": False}})

    def tearDown(self):
        self.vs.close()
        super().tearDown()
        self.assertEqual(self.vs.writes(), [], "o Lúmen chamou uma rota de escrita do Voice Studio")


class Settings(Base):
    def test_defaults_validation_and_ranges(self):
        v = settings.load()["voice"]
        self.assertEqual((v["engine"], v["fallback"], v["voice_id"], v["language"]), ("voicestudio", "off", "1faf41ee", "pt"))
        self.assertEqual(settings.save({"voice": {"speed": 3}})["voice"]["speed"], 1.3)
        self.assertEqual(settings.save({"voice": {"speed": 0.1}})["voice"]["speed"], 0.7)
        for bad in ({"engine": "elevenlabs"}, {"voice_id": "../../x"}, {"style": "<script>"}, {"read": "tudo"}, {"chat_voice": "a/b"}):
            with self.assertRaises(AppError, msg=bad):
                settings.save({"voice": bad})
        self.assertEqual(settings.save({"voice": {"style": "low pitch, whisper", "chat_voice": "demo0001"}})["voice"]["style"], "low pitch, whisper")


class Who(Base):
    def test_default_is_the_profile_id_with_the_name_from_the_api(self):
        w = listen.who("chat")
        self.assertEqual((w["engine"], w["voice"], w["name"], w["note"]), ("voicestudio", "1faf41ee", "Jhonny Sirverhand", None))
        settings.save({"voice": {"practice_voice": "demo0001"}})
        self.assertEqual(listen.who("practice")["voice"], "demo0001")

    def test_missing_voice_falls_to_the_first_clone_and_says_which_was_lost(self):
        listen.gallery()  # o nome fica guardado enquanto a voz existe
        self.vs.profiles = [{**self.vs.profiles[1]}, {"id": "abc12345", "name": "Narradora", "kind": "clone", "language": "Auto", "is_demo": 0}]
        w = listen.who("chat")
        self.assertEqual(w["voice"], "abc12345")  # a primeira clonada que não é a de demonstração
        self.assertIn("Jhonny Sirverhand", w["note"])
        self.assertIn("Narradora", w["note"])

    def test_closed_voice_studio_uses_the_fallback_and_says_so(self):
        self.vs.close()
        settings.save({"voice": {"fallback": "chatterbox"}})
        with mock.patch.dict(os.environ, {"LUMEN_VOICESTUDIO_URL": "http://127.0.0.1:9"}), \
                mock.patch.object(voice.ENGINE, "alive", return_value=True), mock.patch.object(voice.ENGINE, "close") as close:
            w = listen.who("chat")
            self.assertEqual(w["engine"], "chatterbox")
            self.assertIn("fechado", w["note"])
            close.assert_not_called()  # na reserva, o Chatterbox aberto fica aberto (não recarrega a cada consulta)
            self.assertEqual(listen.who("chat", closed=True)["engine"], "chatterbox")
            settings.save({"voice": {"fallback": "off"}})
            with self.assertRaises(AppError) as e:
                listen.who("chat")
            self.assertEqual(str(e.exception), voicestudio.CLOSED[0])
            self.assertEqual(voicestudio.status()["running"], False)
        self.vs = Fake()  # o tearDown confere o registro de um servidor que ainda responde

    def test_engine_off_and_one_voice_on_the_gpu(self):
        settings.save({"voice": {"engine": "off"}})
        with self.assertRaises(AppError):
            listen.who()
        settings.save({"voice": {"engine": "voicestudio"}})
        with mock.patch.object(voice.ENGINE, "alive", return_value=True), mock.patch.object(voice.ENGINE, "close") as close:
            listen.who()
        close.assert_called_once()  # com o Voice Studio como motor, o Chatterbox não fica aberto


class Chat(Base):
    def test_live_speech_has_no_markdown_citations_or_code(self):
        events = [e for e in listen.live(ANSWER, "chat", threading.Event()) if e["type"] != "preparing"]
        self.assertEqual(events[0]["type"], "voice")
        said = [e for e in events if e["type"] == "sentence"]
        self.assertGreaterEqual(len(said), 3)
        text = " ".join(e["text"] for e in said)
        for bad in ("[S", "**", "##", "```", "const x", "https://", "|", "*Effect"):
            self.assertNotIn(bad, text)
        self.assertIn("a documentação", text)
        with wave.open(io.BytesIO(base64.b64decode(said[0]["audio"]))) as w:
            self.assertEqual((w.getframerate(), w.getnchannels()), (24000, 1))
        self.assertEqual(events[-1]["type"], "done")
        # a fala ao vivo vai pelo /v1/audio/speech em PCM, uma frase por pedido, com os passos do chat e o idioma (D56)
        speech = [b for b in self.vs.bodies if "input" in b]
        self.assertTrue(speech)
        self.assertTrue(all((b["response_format"], b["num_step"], b["language"]) == ("pcm", listen.STEPS["quality"], "pt")
                            for b in speech))
        self.assertFalse(any(p == "/ws/tts" for _, p in self.vs.calls))

    def test_short_reads_only_the_first_paragraph_and_cancel_stops(self):
        settings.save({"voice": {"read": "short"}})
        said = [e for e in listen.live(ANSWER, "chat", threading.Event()) if e["type"] == "sentence"]
        self.assertEqual([e["text"] for e in said], ["Um keyframe guarda um valor num ponto da linha do tempo."])
        settings.save({"voice": {"read": "answer"}})
        cancel, out = threading.Event(), []
        for e in listen.live(ANSWER, "chat", cancel):
            out.append(e)
            if e["type"] == "sentence":
                cancel.set()
        self.assertEqual([e["type"] for e in out], ["voice", "sentence"])

    def test_test_route_and_style_error_from_the_engine(self):
        r = listen.test("Olá.", "demo0001")
        self.assertEqual(r["who"]["voice"], "demo0001")
        self.assertGreater(r["seconds"], 0)
        settings.save({"voice": {"style": "tag errada"}})
        with self.assertRaises(AppError) as e:
            listen.test("Olá.")
        self.assertIn("tag errada", e.exception.action)


class Script(Base):
    def test_review_script_ceilings_and_pauses(self):
        long = "palavra " * 200
        data = learn.audio_script(mock.Mock(sources={}), {"title": "T" * 300, "intro": long, "outro": long, "chapters": [
            {"title": f"C{i}", "items": [{"question": long, "answer": long, "source": "geral"}] * 9} for i in range(9)]}, "tema")
        self.assertEqual(len(data["chapters"]), 5)
        self.assertTrue(all(len(c["items"]) <= 4 for c in data["chapters"]))
        self.assertTrue(all(len(q["question"]) <= 240 and len(q["answer"]) <= 600 for c in data["chapters"] for q in c["items"]))
        self.assertLessEqual(len(data["title"]), 100)
        it = learn.save("audio", "Revisão", data)
        script = listen.review_script(it["id"])
        parts = [p for c in script["chapters"] for p in c["parts"]]
        self.assertIn(listen.THINK, parts)  # pausa para lembrar antes de cada resposta
        self.assertTrue(any(isinstance(p, str) and p.startswith("Resposta:") for p in parts))
        self.assertEqual(len(script["chapters"]), 6)  # introdução + 5 capítulos


def lesson(key="aula-teste"):
    pkg = {"lumen_id": package.lumen_id(key), "key": key, "lesson": {"title": "Keyframes", "summary": "Um resumo curto da aula. Tem duas frases.",
           "topics": [{"title": "Posição", "explanation": "Cada keyframe guarda a posição.", "why": "Ajuda a animar.", "timestamp": 12.0},
                      {"title": "Suavizar", "explanation": "Ease In e Ease Out deixam o movimento suave.", "why": "", "timestamp": 95.0}]}}
    package.save(pkg)
    return pkg


class Audio(Base):
    def test_lesson_summary_job_writes_m4a_with_chapters(self):
        pkg = lesson()
        listen.start("lesson", "aula-teste")
        j = wait_job()
        self.assertEqual(j["status"], "done", j.get("error"))
        meta = j["result"]["audio"]
        self.assertEqual(meta["id"], "aula-" + pkg["lumen_id"])
        self.assertEqual([c["title"] for c in meta["chapters"]], ["Resumo", "Posição", "Suavizar"])
        ts = [c["t"] for c in meta["chapters"]]
        self.assertEqual(ts, sorted(ts))
        self.assertEqual(ts[0], 0.0)
        self.assertEqual(meta["chapters"][1]["lesson_t"], 12.0)  # o tempo do tópico na aula, para "ver na aula"
        m4a = listen.AUDIO / f"{meta['id']}.m4a"
        self.assertTrue(m4a.exists())
        import av
        with av.open(str(m4a)) as c:
            self.assertAlmostEqual(float(c.duration / 1e6), meta["duration"], delta=0.5)
        self.assertEqual(json.loads((listen.AUDIO / f"{meta['id']}.json").read_text("utf-8"))["voice"], "Jhonny Sirverhand")
        self.assertFalse(list(listen.AUDIO.glob(".*")))  # a pasta das frases foi apagada
        self.assertEqual([a["id"] for a in listen.audios()], [meta["id"]])
        # o texto não foi gerado de novo: o que foi falado é o resumo e os tópicos do pacote
        said = " ".join(b.get("input", "") for b in self.vs.bodies)
        self.assertIn("Ease In e Ease Out", said)

    def test_cancel_leaves_no_half_file(self):
        lesson()
        self.vs.delay = 0.3
        listen.start("lesson", "aula-teste")
        time.sleep(0.5)
        jobs.cancel()
        j = wait_job()
        self.assertEqual(j["status"], "cancelled")
        left = [p.name for p in listen.AUDIO.iterdir() if p.name != "cache"] if listen.AUDIO.exists() else []
        self.assertEqual(left, [])  # nem .m4a pela metade nem a pasta das frases (o cache de frases pode ficar)

    def test_after_lesson_hook_only_when_on(self):
        pkg = lesson()
        # o resultado real da publicação traz a chave; o spec do finish, não (vem da tela, sem "key")
        done = {"key": "aula-teste", "lumen_id": pkg["lumen_id"], "dests": ["obsidian"], "title": "Keyframes"}
        with mock.patch.object(listen, "start") as start, mock.patch.object(listen, "AFTER_S", 0):
            listen.after_lesson("process", {"mode": "new"}, done)
            time.sleep(0.2)
            start.assert_not_called()  # ajuste desligado
            settings.save({"voice": {"summary_after_lesson": True}})
            listen.after_lesson("process", {"mode": "new"}, {"review": True, "key": "aula-teste"})  # só a transcrição
            time.sleep(0.2)
            start.assert_not_called()
            listen.after_lesson("process", {"mode": "new"}, done)
            time.sleep(0.3)
            start.assert_called_once_with("lesson", "aula-teste")
            listen.AUDIO.mkdir(parents=True)
            (listen.AUDIO / f"aula-{pkg['lumen_id']}.m4a").write_bytes(b"x")
            listen.after_lesson("process", {}, done)  # reenviar a aula que já tem o áudio não gera de novo
            time.sleep(0.2)
            self.assertEqual(start.call_count, 1)
        self.assertIn(listen.after_lesson, jobs.ON_DONE)

    def test_unload_only_what_the_lumen_loaded(self):
        before = voicestudio.mark()
        self.assertFalse(before["loaded"])
        voicestudio.speak("Olá.", self.tmp / "a.wav", "1faf41ee")
        self.assertFalse(voicestudio.unload_if_ours(before))  # tarefa curta: fica para o próprio app
        before["t"] -= 999
        self.vs.takes += 1  # o estudante gerou algo no Voice Studio enquanto isso
        self.assertFalse(voicestudio.unload_if_ours(before))
        self.vs.takes -= 1
        self.assertTrue(voicestudio.unload_if_ours(before))
        self.assertEqual(self.vs.unloaded, ["tts"])
        self.vs.calls = [c for c in self.vs.calls if not c[1].startswith("/model/unload/")]  # o único descarregar permitido
        self.assertFalse(voicestudio.unload_if_ours({**before, "loaded": True}))


class Phase6Rest(Base):
    def test_narrated_tour_tags_each_sentence_with_its_part(self):
        events = [e for e in listen.live("", "chat", threading.Event(), ["Codificação. O hipocampo grava.", "Sono profundo. Reativa."])
                  if e["type"] == "sentence"]
        self.assertEqual([e["part"] for e in events], [0, 0, 1, 1])

    def test_feynman_grades_against_the_notes_and_records_the_origin(self):
        from lumen.study import explain, mastery
        prov = mock.Mock(name="ollama")
        prov.json.return_value = {"right": [{"point": "O sono consolida.", "source": "S1"}, {"point": "O sono consolida.", "source": "S1"}],
                                  "missing": [{"point": "O papel do hipocampo.", "source": "S9"}], "wrong": [], "score": 0.55,
                                  "feedback": "Faltou o hipocampo."}
        ctx = mock.Mock(sources={"S1": {"id": "n1", "title": "Memória e sono", "source": "obsidian"}})
        with self.assertRaises(AppError):
            explain.feynman("sono", "curto", prov, ctx)
        r = explain.feynman("memória e sono", "Dormir depois de estudar ajuda a guardar o que aprendi.", prov, ctx)
        self.assertEqual((r["correct"], r["score"], len(r["right"])), (False, 0.55, 1))  # repetido sai (D18)
        self.assertEqual(r["right"][0]["source"]["title"], "Memória e sono")
        self.assertEqual(r["missing"][0]["source"]["source"], "geral")  # fonte que não existe vira "geral"
        schema = prov.json.call_args[0][2]
        self.assertEqual(schema["properties"]["missing"]["maxItems"], 5)
        self.assertIn("feynman", mastery.ORIGINS)
        m = mastery.find("memória e sono")
        self.assertEqual((m["wrong"], json.loads(m["origin"]) if isinstance(m["origin"], str) else m["origin"]), (1, {"feynman": 1}))

    def test_watch_opens_youtube_at_the_lesson_time(self):
        pkg = lesson("aula-yt")
        pkg["source"] = {"kind": "youtube", "yt_id": "dQw4w9WgXcQ"}
        package.save(pkg)
        with mock.patch("webbrowser.open") as opened:
            self.assertEqual(listen.watch("aula-yt", 95.4), {"opened": "youtube", "t": 95})
        opened.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=95s")
        lesson("aula-sem-arquivo")
        with self.assertRaises(AppError):
            listen.watch("aula-sem-arquivo", 10)


class Obsidian(Base):
    def test_audio_goes_into_the_note_only_after_the_preview(self):
        from lumen.study import writes
        (self.vault / ".obsidian" / "app.json").write_text(json.dumps({"attachmentFolderPath": "Anexos"}), "utf-8")
        it = learn.save("audio", "Revisão", {"title": "Sono", "intro": "Oi.", "outro": "Fim.", "sources": [],
                                             "chapters": [{"title": "Sono", "items": [{"question": "O que é?", "answer": "Descanso.", "source": {}}]}]})
        aid = "rev-" + it["id"]
        listen.AUDIO.mkdir(parents=True)
        (listen.AUDIO / f"{aid}.m4a").write_bytes(b"audio")
        (listen.AUDIO / f"{aid}.json").write_text(json.dumps({"id": aid}), "utf-8")
        h = mock.Mock(_json=lambda: {"destination": "obsidian", "title": "Sono", "item_id": it["id"], "with_audio": True})
        from lumen.study import api
        prev = api._save(h)
        self.assertTrue(prev["content"].startswith("![[Sono - áudio.m4a]]"))
        self.assertIn("> [!question]- O que é?", prev["content"])
        self.assertTrue(any("Anexos" in w for w in prev["warnings"]))
        self.assertFalse((self.vault / "Anexos").exists())  # nada copiado antes de confirmar (D11)
        writes.confirm(prev["id"])
        self.assertEqual((self.vault / "Anexos" / "Sono - áudio.m4a").read_bytes(), b"audio")
        self.assertTrue((self.vault / prev["path"]).read_text("utf-8").count("![[Sono - áudio.m4a]]") == 1)


class Range(Base):
    def test_audio_file_is_served_with_range(self):
        listen.AUDIO.mkdir(parents=True)
        aid = "rev-" + "a" * 32
        (listen.AUDIO / f"{aid}.m4a").write_bytes(bytes(range(256)) * 4)
        (listen.AUDIO / f"{aid}.json").write_text(json.dumps({"id": aid}), "utf-8")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_port}/api/study/voice/file?id={aid}&t={server.TOKEN}"
            req = urllib.request.Request(base, headers={"Range": "bytes=10-19"})
            with urllib.request.urlopen(req) as r:
                self.assertEqual((r.status, r.headers["Content-Range"], r.read()), (206, "bytes 10-19/1024", bytes(range(10, 20))))
            with urllib.request.urlopen(base) as r:
                self.assertEqual((r.status, len(r.read()), r.headers["Accept-Ranges"]), (200, 1024, "bytes"))
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base.replace(aid, "../../x"))
            e.exception.close()
        finally:
            srv.shutdown()
            srv.server_close()


ROOT = Path(__file__).resolve().parents[1]


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Backend(Base):
    """D53 a D55: o backend sem janela. O falso roda como processo de verdade (tests/fake_voicestudio.py), com o pipe
    da entrada padrão, a subida lenta, a falha e a saída quando o pipe fecha."""

    def setUp(self):
        super().setUp()
        settings.save({"voice": {"fallback": "chatterbox"}})  # estes testes cobrem a reserva, que não é mais o padrão
        self.port, self.args, self.spawned = free_port(), ["--start", "1.2"], []
        self.lumen_d = self.tmp / "Lumen"
        self.lumen_d.mkdir()
        self.b = voicestudio.Backend()
        real_popen, test = subprocess.Popen, self

        def popen(*a, **k):
            if "fake_voicestudio" in str(a[0] if a else k.get("args")):  # só o backend (não o nvidia-smi nem o tasklist)
                test.spawned.append((a, k))
            return real_popen(*a, **k)
        for p in [mock.patch.dict(os.environ, {"LUMEN_VOICESTUDIO_URL": f"http://127.0.0.1:{self.port}"}),
                  mock.patch.object(voicestudio, "_command", lambda port: (
                      [sys.executable, str(ROOT / "tests" / "fake_voicestudio.py"), "--port", str(port), *test.args], str(ROOT))),
                  mock.patch.object(voicestudio, "launch_problem", lambda: ""),
                  mock.patch.object(voicestudio, "LUMEN_D", self.lumen_d),
                  mock.patch.object(voicestudio, "BACKEND", self.b),
                  mock.patch.object(voicestudio, "app_open", lambda: False),
                  mock.patch.object(voicestudio.subprocess, "Popen", popen)]:
            p.start()
            self.stack.append(p)
        settings.save({"voice": {"vs_autostart": True}})

    def tearDown(self):
        self.b.stop()
        super().tearDown()

    def test_first_speech_starts_the_backend_without_a_window_and_shows_progress(self):
        events = list(listen.live("Olá. Tudo bem?", "chat", threading.Event()))
        kinds = [e["type"] for e in events]
        self.assertIn("preparing", kinds)  # a barra de fala mostra "Preparando a voz…", nunca uma caixa de erro
        self.assertEqual(kinds[-1], "done", events[-1])
        self.assertEqual(next(e for e in events if e["type"] == "voice")["engine"], "voicestudio")
        (argv, kw), = self.spawned
        self.assertTrue(kw["creationflags"] & subprocess.CREATE_NO_WINDOW)
        self.assertEqual(kw["stdin"], subprocess.PIPE)  # o pipe que o Lúmen segura: fechou, o backend sai
        env = kw["env"]
        self.assertEqual((env["OMNIVOICE_DESKTOP_CONTAINED"], env["OMNIVOICE_PORT"]), ("1", str(self.port)))
        self.assertEqual(env["TEMP"], str(self.lumen_d / "cache" / "voicestudio-tmp"))
        self.assertEqual(env.get("HF_HOME"), os.environ.get("HF_HOME"))  # as pastas de modelos ficam como estão
        self.assertFalse(any(k.startswith("POSTHOG_") for k in env))
        self.assertEqual(listen.who("chat")["engine"], "voicestudio")
        self.assertEqual(len(self.spawned), 1)  # já no ar: não sobe outro
        self.assertEqual(voicestudio.status()["owner"], "lumen")

    def test_stop_closes_the_pipe_and_the_process_leaves(self):
        self.b.ensure()
        proc = self.b.proc
        self.b.stop()
        self.assertIsNotNone(proc.poll())  # saiu sozinho quando o pipe fechou (sem taskkill)
        self.assertEqual(voicestudio.health()[0], "closed")
        self.assertIsNone(self.b.lock_fh)

    def test_failure_falls_back_with_the_reason_and_waits_before_retrying(self):
        self.args = ["--crash"]
        w = listen.who("chat")
        self.assertEqual(w["engine"], "chatterbox")
        self.assertIn("não conseguiu ligar", w["note"])
        self.assertEqual(len(self.spawned), 1)
        listen.who("chat")  # logo depois: não tenta subir de novo (60 s de espera)
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("falha falsa", self.b.state["action"])  # o motivo vem do que o backend imprimiu

    def test_already_running_is_only_used_and_a_foreign_port_is_refused(self):
        other = Fake(self.port)  # o app do estudante já está aberto nessa porta
        try:
            self.assertEqual(self.b.ensure(), "app")
            self.assertEqual(self.spawned, [])
            self.b.stop()  # não é dele: não derruba nada
            self.assertEqual(voicestudio.health()[0], "ok")
        finally:
            other.close()
        srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.Handler)  # outro programa, sem o cabeçalho
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual(voicestudio.health()[0], "other")
            with self.assertRaises(AppError) as e:
                self.b.ensure()
            self.assertIn("ocupada por outro programa", str(e.exception))
            self.assertEqual(self.spawned, [])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_lock_keeps_a_second_instance_from_starting_another(self):
        self.assertTrue(self.b._lock())
        other = voicestudio.Backend()
        self.assertFalse(other._lock())  # a outra instância só espera
        self.b._unlock()
        self.assertTrue(other._lock())
        other._unlock()

    def test_idle_shutdown_but_not_with_the_app_open(self):
        from types import SimpleNamespace
        self.b.ensure()
        proc = self.b.proc
        self.b.idle_s, self.b.used = 1, time.monotonic() - 5
        fast = SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)  # só o relógio do voicestudio
        with mock.patch.object(voicestudio, "app_open", lambda: True), mock.patch.object(voicestudio, "time", fast), \
                mock.patch.object(voicestudio.Backend, "ours", side_effect=[True, RuntimeError("fim")]):
            with self.assertRaises(RuntimeError):
                self.b._idle()
        self.assertIsNone(proc.poll())  # com o VoiceStudio.exe aberto, fica
        with mock.patch.object(voicestudio, "time", fast), \
                mock.patch.object(voicestudio.Backend, "ours", side_effect=[True, RuntimeError("fim")]):
            with self.assertRaises(RuntimeError):
                self.b._idle()
        self.assertIsNone(self.b.proc)  # parado e sem o app: desligou
        self.assertIsNotNone(proc.poll())

    def test_update_or_setup_pending_never_runs_the_old_copy(self):
        with mock.patch.object(voicestudio, "launch_problem", lambda: "update"), \
                mock.patch.object(voicestudio, "open_app") as opened:
            with self.assertRaises(AppError):
                self.b.ensure(timeout=0.5)
        opened.assert_called_once_with(minimized=True)  # o app prepara a versão nova; o Lúmen não roda a cópia velha
        self.assertEqual(self.spawned, [])
        self.b.failed = None
        with mock.patch.object(voicestudio, "launch_problem", lambda: "setup"):
            with self.assertRaises(AppError) as e:
                self.b.ensure()
        self.assertIn("Termine a instalação", e.exception.action)

    def test_idle_watch_never_stops_a_slow_start(self):
        from types import SimpleNamespace
        self.args = ["--start", "2.5"]
        self.b.idle_s = 1  # parado há mais de 1 s desligaria; a subida (2,5 s) não conta como parada
        fast = SimpleNamespace(sleep=lambda s: time.sleep(min(s, 0.2)), monotonic=time.monotonic)
        with mock.patch.object(voicestudio, "time", fast):
            self.assertEqual(self.b.ensure(), "lumen")
            self.assertTrue(self.b.ours())  # o vigia rodou várias vezes durante a subida e não derrubou
        self.assertEqual(len(self.spawned), 1)

    def test_foreign_port_falls_back_with_the_reason(self):
        srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.Handler)  # outro programa responde 404 sem o cabeçalho
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            w = listen.who("chat")
            self.assertEqual(w["engine"], "chatterbox")
            self.assertIn("ocupada por outro programa", w["note"])
            self.assertTrue(voicestudio.status()["foreign"])
            self.assertEqual(self.spawned, [])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_state_screen_never_starts_the_backend(self):
        st = listen._state(mock.Mock(command="GET"))  # a tela consulta o estado a cada poucos segundos
        self.assertTrue(st["who"]["starts"])  # desligado, mas liga sozinho: quem fala é a voz padrão, sem "problema"
        self.assertEqual((st["who"]["voice"], st["voicestudio"]["running"]), ("1faf41ee", False))
        self.assertEqual(self.spawned, [])

    def test_app_starting_is_awaited_not_duplicated(self):
        with mock.patch.object(voicestudio, "app_open", lambda: True):  # o app abrindo, a porta ainda fechada
            with self.assertRaises(AppError):
                self.b.ensure(timeout=1)
        self.assertEqual(self.spawned, [])  # não sobe um segundo backend sobre a cópia que o app está preparando

    def test_autostart_off_keeps_it_closed(self):
        settings.save({"voice": {"vs_autostart": False}})
        w = listen.who("chat")
        self.assertEqual(w["engine"], "chatterbox")
        self.assertIn("fechado", w["note"])
        self.assertEqual(self.spawned, [])


class Launch(Base):
    def test_launch_problem_reads_the_real_layout(self):
        app, data = self.tmp / "Programs", self.tmp / "Roaming"
        project = data / "runtime" / "project"
        with mock.patch.multiple(voicestudio, APP=app, USER_DATA=data, PROJECT=project,
                                 PYTHON=project / ".venv" / "Scripts" / "python.exe"), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "L"), "APPDATA": str(self.tmp / "A")}):
            self.assertEqual(voicestudio.launch_problem(), "setup")  # sem o ambiente do app
            voicestudio.PYTHON.parent.mkdir(parents=True)
            voicestudio.PYTHON.write_bytes(b"")
            (project / ".runtime-ready").write_text("ok")
            (app / "resources").mkdir(parents=True)
            (app / "resources" / "pyproject.toml").write_text('[project]\nversion = "0.5.8"\n')
            (project / "pyproject.toml").write_text('[project]\nversion = "0.5.7"\n')
            self.assertEqual(voicestudio.launch_problem(), "update")  # app atualizado e ainda não aberto
            (project / "pyproject.toml").write_text('[project]\nversion = "0.5.8"\n')
            self.assertEqual(voicestudio.launch_problem(), "")
            (data / "runtime-location.json").write_text("{}")
            self.assertEqual(voicestudio.launch_problem(), "custom")  # pasta escolhida no app: só ele monta o ambiente


class Speed(Base):
    """D56 e D59: passos por uso, cache de frases e o pré-aquecimento."""

    def test_first_cut_uses_the_comma_nearest_fifty(self):
        s = "Keyframes guardam valores, como posição, escala e rotação, e o Premiere calcula o caminho entre eles."
        first = listen._first_cut(s)[0]
        # vírgulas em 25, 39 e 57: fica a de 57 (a 7 de 50), não a última antes de 80 nem a primeira
        self.assertEqual(first, "Keyframes guardam valores, como posição, escala e rotação,")
        self.assertEqual(listen._first_cut("Um keyframe guarda um valor num ponto da linha do tempo."),
                         ["Um keyframe guarda um valor num ponto da linha do tempo."])  # sem vírgula e curta: inteira

    def test_cache_follows_the_pronunciations(self):
        list(listen.live("Crie um keyframe.", "chat", threading.Event()))
        self.vs.pron = [{"id": "p1", "term": "keyframe", "replacement": "quíframe", "enabled": True}]
        voicestudio._pron["at"] = -1e9
        list(listen.live("Crie um keyframe.", "chat", threading.Event()))
        said = [b["input"] for b in self.vs.bodies if "input" in b]
        self.assertEqual(said, ["Crie um keyframe.", "Crie um quíframe."])  # a pronúncia nova não toca o áudio antigo
        settings.save({"voice": {"cache_mb": 0}})
        list(listen.live("Crie um keyframe.", "chat", threading.Event()))
        self.assertEqual(len([b for b in self.vs.bodies if "input" in b]), 3)  # cache em 0: nem o que tinha é lido
        listen.clear_cache()
        self.assertFalse((listen.AUDIO / "cache").exists())

    def test_steps_per_use_and_the_global_tier_is_untouched(self):
        lesson()
        settings.save({"voice": {"long_quality": "max", "chat_quality": "fast"}})
        list(listen.live("Uma frase só.", "chat", threading.Event()))
        listen.start("lesson", "aula-teste")
        self.assertEqual(wait_job()["status"], "done")
        steps = [(b.get("response_format"), b.get("num_step")) for b in self.vs.bodies if "input" in b]
        self.assertEqual(steps[0], ("pcm", 8))
        self.assertTrue(all(s == ("wav", 32) for s in steps[1:]))
        self.assertEqual(self.vs.tier, "max")  # o nível global do Voice Studio não muda
        self.assertEqual(json.loads(next(listen.AUDIO.glob("aula-*.json")).read_text("utf-8"))["steps"], 32)

    def test_sentence_cache_hits_and_respects_the_ceiling(self):
        list(listen.live("Primeira frase. Segunda frase.", "chat", threading.Event()))
        n = sum(1 for b in self.vs.bodies if "input" in b)
        again = [e for e in listen.live("Primeira frase. Segunda frase.", "chat", threading.Event()) if e["type"] == "sentence"]
        self.assertEqual(sum(1 for b in self.vs.bodies if "input" in b), n)  # "Ouvir" de novo: nada gerado
        self.assertEqual(len(again), 2)
        settings.save({"voice": {"speed": 1.2}})
        list(listen.live("Primeira frase.", "chat", threading.Event()))
        self.assertEqual(sum(1 for b in self.vs.bodies if "input" in b), n + 1)  # outra velocidade: outra chave
        settings.save({"voice": {"cache_mb": 0}})
        list(listen.live("Frase nova sem cache.", "chat", threading.Event()))
        files = list((listen.AUDIO / "cache").glob("*.wav"))
        self.assertEqual(len(files), 3)  # com o cache em 0, nada novo entra
        big = files[0].stat().st_size
        settings.save({"voice": {"cache_mb": 1}})
        with mock.patch.object(listen, "_cache_dir", return_value=listen.AUDIO / "cache"):
            for f in files[:2]:
                os.utime(f, (1, 1))  # as mais antigas
            listen._keep("x" * 40, b"0" * (1_000_000 - big), settings.load()["voice"])
        left = {f.name for f in (listen.AUDIO / "cache").glob("*.wav")}
        self.assertNotIn(files[0].name, left)  # o teto apaga as usadas há mais tempo
        self.assertIn("x" * 40 + ".wav", left)

    def test_pacing_keeps_at_most_two_sentences_ahead(self):
        from types import SimpleNamespace

        def waited(ahead):
            clock = {"t": 0.0}
            fake_time = SimpleNamespace(monotonic=lambda: clock["t"], sleep=lambda s: clock.__setitem__("t", clock["t"] + s))
            settings.save({"voice": {"cache_mb": 0}})
            with mock.patch.object(listen, "time", fake_time), mock.patch.object(listen, "AHEAD", ahead):
                sent = [e for e in listen.live("Um. Dois. Três. Quatro. Cinco. Seis.", "chat", threading.Event()) if e["type"] == "sentence"]
            self.assertEqual(len(sent), 6)
            return clock["t"]  # a geração "não leva tempo": o relógio só anda esperando a tela tocar
        one, two, three = waited(1), waited(2), waited(3)
        self.assertGreater(one, two)
        self.assertGreater(two, three)
        self.assertGreater(two, 0.5)

    def test_low_vram_frees_ollama_only_when_speaking(self):
        from types import SimpleNamespace
        free = iter([2.0, 2.0, 2.2, 5.0])
        with mock.patch.object(listen.transcribe, "gpu_free_gb", lambda: next(free, 5.0)), \
                mock.patch.object(listen.llm, "release_vram", return_value=True) as rel:
            self.assertEqual(listen.warm("answer")["why"], "vram")  # no meio da resposta: não mexe no Ollama
            rel.assert_not_called()
            with mock.patch.object(listen, "time", SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)):
                events = list(listen._prepare(settings.load()["voice"], lambda: None))
        rel.assert_called_once()  # na hora de falar (a resposta já acabou): pede ao Ollama para soltar a placa
        self.assertIn("Pouca memória na placa", events[0]["label"])

    def test_warm_skips_with_low_ram_and_loads_the_model_otherwise(self):
        with mock.patch.object(listen, "ram_free_gb", return_value=(0.4, 15.8)):
            self.assertEqual(listen.warm("open")["why"], "ram")
            self.assertEqual(listen.warm("answer")["why"], "ram")  # pouca RAM: só o clique ("Ligar a voz agora") liga
        self.vs.load_s = 0.3
        with mock.patch.object(listen, "ram_free_gb", return_value=(8.0, 15.8)):
            listen.warm("open")
        t = voicestudio.BACKEND._warm
        t.join(10)
        self.assertTrue(self.vs.loaded)
        self.assertIn(("POST", "/setup/warmup"), self.vs.calls)  # carregar o modelo não é escrita de ajuste


class Pronunciation(Base):
    def test_the_lumen_applies_the_students_pronunciations(self):
        self.vs.pron = [{"id": "p1", "term": "keyframe", "replacement": "quíframe", "enabled": True}]
        list(listen.live("Crie um keyframe agora.", "chat", threading.Event()))
        said = [b["input"] for b in self.vs.bodies if "input" in b]
        self.assertEqual(said, ["Crie um quíframe agora."])
        self.vs.pron = []
        voicestudio._pron["at"] = -1e9
        self.vs.calls.clear()
        list(listen.live("Outra frase.", "chat", threading.Event()))
        self.assertNotIn(("POST", "/pronunciation/test"), self.vs.calls)  # sem nenhuma entrada, nenhum pedido a mais

    def test_add_delete_and_suggest_only_by_click(self):
        from lumen.study import voice_admin
        h = lambda b, cmd="POST": mock.Mock(command=cmd, _json=lambda: b)  # noqa: E731
        self.assertEqual(voice_admin._pron(h({}, "GET"))["entries"], [])
        self.assertEqual(self.vs.writes(), [])  # ler não escreve
        voice_admin._pron(h({"action": "add", "term": "CTA", "replacement": "cê tê á", "language": "pt"}))
        self.assertEqual(self.vs.writes(), [("POST", "/pronunciation")])
        self.assertEqual(voice_admin._pron(h({"action": "test", "text": "Use um CTA."}))["substituted"], "Use um cê tê á.")
        voice_admin._pron(h({"action": "delete", "id": "p1"}))
        with self.assertRaises(AppError):
            voice_admin._pron(h({"action": "add", "term": "<b>", "replacement": "x"}))
        self.vs.calls.clear()
        with mock.patch.object(voice_admin, "candidates", return_value=["ROI", "keyframe"]), \
                mock.patch("lumen.study.providers.chain", return_value=([], [])):
            self.assertEqual(voice_admin._pron(h({"action": "suggest"}))["suggestions"], [{"term": "ROI", "replacement": "érre ó i"}])
        self.assertEqual(self.vs.writes(), [])  # sugerir não grava: o estudante aceita uma por uma


class Admin(Base):
    """D55 e D57: os modelos no Lúmen; nada muda no Voice Studio sem o clique."""

    def h(self, b, cmd="POST"):
        return mock.Mock(command=cmd, _json=lambda: b)

    def test_reading_the_screens_never_writes(self):
        from lumen.study import voice_admin
        m = voice_admin._models(self.h({}, "GET"))
        self.assertTrue(m["running"])
        self.assertEqual(m["catalog"]["packs"]["balanced"]["missing"],
                         ["deepdml/faster-whisper-large-v3-turbo-ct2", "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"])
        self.assertEqual(m["catalog"]["packs"]["fast"]["missing"], [])
        omni = next(x for x in m["catalog"]["models"] if x["repo_id"] == "k2-fsa/OmniVoice")
        self.assertEqual((omni["license"], omni["personal"]), ("CC-BY-NC", True))  # pesos só para uso pessoal
        self.assertEqual(next(x for x in m["catalog"]["models"] if "tiny" in x["repo_id"])["license"], "")
        tts = {e["id"]: e for e in m["engines"]["tts"]["engines"]}
        self.assertEqual((tts["omnivoice"]["portuguese"], tts["kittentts"]["portuguese"], tts["kittentts"]["cloning"]), (True, False, False))
        with mock.patch.object(voice_admin, "gpu", return_value={"name": "RTX", "total_gb": 12, "used_gb": 10, "free_gb": 2}), \
                mock.patch.object(voice_admin, "ollama_vram_gb", return_value=4.1):  # o Ollama de verdade fica de fora
            mac = voice_admin._machine(self.h({}, "GET"))
        self.assertEqual(mac["vram"]["ollama"], 4.1)
        self.assertTrue(any("Pouca VRAM" in a for a in mac["advice"]))
        voice_admin._move(self.h({}, "GET"))
        listen._state(self.h({}, "GET"))
        self.assertEqual(self.vs.writes(), [])

    def test_pack_needs_confirmation_and_disk_and_each_action_is_one_write(self):
        from lumen.study import voice_admin
        with self.assertRaises(AppError) as e:
            voice_admin._model_action(self.h({"action": "tier", "tier": "balanced"}))
        self.assertIn("2.2 GB", e.exception.action)
        self.assertEqual(self.vs.writes(), [])
        with mock.patch.object(voicestudio, "disk_free_gb", return_value=11.0):
            with self.assertRaises(AppError) as e:
                voice_admin._model_action(self.h({"action": "tier", "tier": "balanced", "confirm": True}))
        self.assertIn("10 GB", str(e.exception))
        self.assertEqual(self.vs.writes(), [])
        with mock.patch.object(voicestudio, "disk_free_gb", return_value=100.0):
            r = voice_admin._model_action(self.h({"action": "tier", "tier": "balanced", "confirm": True}))
        self.assertEqual(len(r["installing"]), 2)
        self.assertEqual(self.vs.tier, "balanced")
        self.assertEqual(self.vs.writes(), [("PUT", "/api/settings/performance-profile"), ("POST", "/models/install"), ("POST", "/models/install")])
        self.vs.calls.clear()
        voice_admin._model_action(self.h({"action": "cancel", "repo": "deepdml/faster-whisper-large-v3-turbo-ct2"}))
        with self.assertRaises(AppError):
            voice_admin._model_action(self.h({"action": "remove", "repo": "Systran/faster-whisper-base"}))
        voice_admin._model_action(self.h({"action": "remove", "repo": "Systran/faster-whisper-base", "confirm": True}))
        voice_admin._model_action(self.h({"action": "engine", "family": "asr", "id": "faster-whisper"}))
        with self.assertRaises(AppError):
            voice_admin._model_action(self.h({"action": "remove", "repo": "../../etc", "confirm": True}))
        self.assertEqual(self.vs.writes(), [("POST", "/models/install/cancel"), ("DELETE", "/models/Systran/faster-whisper-base"),
                                            ("POST", "/engines/select")])
        self.vs.calls.clear()

    def test_copy_models_checks_every_file(self):
        from lumen.study import voice_admin
        src, dst = self.tmp / "hf_cache", self.tmp / "D" / "models"
        (src / "models--a--b" / "blobs").mkdir(parents=True)
        (src / "models--a--b" / "blobs" / "x").write_bytes(b"pesos" * 1000)
        (src / "xet").mkdir()
        (src / "xet" / "y").write_bytes(b"y")
        self.assertTrue(voice_admin.copy_models(src, dst))
        self.assertEqual((dst / "models--a--b" / "blobs" / "x").read_bytes(), b"pesos" * 1000)
        self.assertEqual(voice_admin.MOVE["phase"], "copied")
        self.assertFalse(list(dst.rglob("*.lumen-part")))
        self.assertTrue(src.exists())  # a origem só sai depois, com o Voice Studio usando a pasta nova
        with self.assertRaises(AppError):
            voice_admin._move(self.h({"action": "delete_old", "confirm": True}))  # ainda não usa a pasta nova
        self.assertTrue(src.exists())

    def test_delete_old_only_with_a_checked_copy(self):
        from lumen.study import voice_admin
        src, dst = self.tmp / "hf_cache", self.tmp / "D" / "models"
        (src / "models--a--b").mkdir(parents=True)
        (src / "models--a--b" / "w").write_bytes(b"pesos")
        using_new = mock.patch.object(voice_admin, "_move_state", return_value={"using_new": True, "running": True})
        voice_admin._record_file().unlink(missing_ok=True)
        with using_new, self.assertRaises(AppError):  # sem cópia conferida gravada (ex.: o Lúmen reiniciou): nada sai
            voice_admin._move(self.h({"action": "delete_old", "confirm": True}))
        self.assertTrue(src.exists())
        self.assertFalse(voice_admin.safe_to_delete(".", dst))  # nunca a pasta de trabalho
        self.assertFalse(voice_admin.safe_to_delete("", dst))
        self.assertTrue(voice_admin.copy_models(src, dst))
        (dst / "models--a--b" / "w").write_bytes(b"x")  # a cópia ficou diferente depois
        with using_new, self.assertRaises(AppError):
            voice_admin._move(self.h({"action": "delete_old", "confirm": True}))
        self.assertTrue(src.exists())
        (dst / "models--a--b" / "w").write_bytes(b"pesos")
        (src / "xet" / "logs").mkdir(parents=True)  # o Voice Studio grava um log do downloader a cada subida
        (src / "xet" / "logs" / "xet_1.log").write_text("log")
        self.assertTrue(voice_admin.safe_to_delete(src, dst))
        (src / "models--a--b" / "novo").write_bytes(b"x")  # um modelo que só existe na antiga ainda barra
        self.assertFalse(voice_admin.safe_to_delete(src, dst))
        (src / "models--a--b" / "novo").unlink()
        with using_new:
            voice_admin._move(self.h({"action": "delete_old", "confirm": True}))
        self.assertFalse(src.exists())  # conferida e com o app na pasta nova: a antiga sai
        self.assertTrue((dst / "models--a--b" / "w").exists())
        self.assertIsNone(voice_admin._record())

    def test_design_voice_is_created_only_by_click_with_the_lumen_mark(self):
        from lumen.study import voice_admin
        d = voice_admin._design(self.h({"action": "describe", "text": "cliente cético, homem, 40 anos"}))
        self.assertEqual(d["instruct"], "male, middle-aged")
        self.assertEqual(self.vs.writes(), [])
        with self.assertRaises(AppError):
            voice_admin._design(self.h({"action": "create", "name": "Cliente cético", "instruct": d["instruct"], "attrs": d["attrs"]}))
        self.vs.load_s = 0.1
        out = voice_admin._design(self.h({"action": "create", "name": "Cliente cético", "instruct": d["instruct"],
                                          "attrs": d["attrs"], "confirm": True}))
        self.assertEqual(out["voice"]["name"], "Cliente cético (Lúmen)")
        self.assertEqual(out["voice"]["kind"], "design")
        self.assertEqual(self.vs.writes(), [("POST", "/profiles")])
        self.vs.calls.clear()
        self.assertFalse(any(m == "DELETE" and p.startswith("/profiles") for m, p in self.vs.calls))


class Practice(Base):
    def test_role_play_turns_and_rubric_into_mastery(self):
        from lumen.study import mastery, practice
        prov = mock.Mock(name="ollama")
        prov.json.side_effect = [
            {"line": "Já fui enganado antes. Por que confiar em você?", "end": False},
            {"line": "Hum, e se não funcionar?", "end": False},
            {"criteria": [{"name": "Tratamento de objeções", "score": 0.8, "comment": "Bom."},
                          {"name": "Tratamento de objeções", "score": 0.1, "comment": "Repetido."},
                          {"name": "Inventado", "score": 1, "comment": "x"}],
             "overall": 1.7, "feedback": "Bom começo.", "next": "Feche com um próximo passo."}]
        with mock.patch.object(practice.providers, "chain", return_value=([prov], [])):
            s = practice.start("venda", "persuasão", "demo0001")
            self.assertEqual((s["voice"], s["language"]), ("demo0001", "pt"))
            with self.assertRaises(AppError):
                practice.finish(s["id"])  # sem nenhuma resposta do estudante
            t = practice.turn(s["id"], "Tenho casos de clientes parecidos com você e garantia de 30 dias.")
            self.assertEqual(t["left"], practice.MAX_TURNS - 1)
            r = practice.finish(s["id"])
        self.assertEqual([c["name"] for c in r["criteria"]], ["Tratamento de objeções"])  # repetido e inventado saem
        self.assertEqual((r["overall"], r["correct"]), (0.8, True))  # a média dos critérios, não o 1,7 do modelo
        self.assertIn("practice", mastery.ORIGINS)
        m = mastery.find("Treino falado: Venda para um cliente cético (persuasão)")
        self.assertEqual(m["correct"], 1)
        with self.assertRaises(AppError):
            practice.turn(s["id"], "de novo")  # a conversa terminou

    def test_failed_turn_does_not_spend_an_answer(self):
        from lumen.study import practice
        prov = mock.Mock(name="ollama")
        prov.json.side_effect = [{"line": "Olá. O que você vende?", "end": False}, AppError("A IA falhou."),
                                 {"line": "Entendi.", "end": False}]
        with mock.patch.object(practice.providers, "chain", return_value=([prov], [])):
            s = practice.start("venda")
            with self.assertRaises(AppError):
                practice.turn(s["id"], "Vendo cursos.")
            t = practice.turn(s["id"], "Vendo cursos.")  # tentar de novo: a fala não duplica
        self.assertEqual(t["left"], practice.MAX_TURNS - 1)
        self.assertEqual(sum(1 for x in practice.SESSIONS[s["id"]]["turns"] if x["role"] == "student"), 1)

    def test_practice_speech_is_never_cached(self):
        list(listen.live("Por que eu confiaria em você?", "practice", threading.Event()))
        list(listen.live("Uma resposta temporária.", "chat", threading.Event(), keep=False))
        self.assertFalse((listen.AUDIO / "cache").exists() and any((listen.AUDIO / "cache").iterdir()))

    def test_character_voice_and_english_reach_the_speech(self):
        list(listen.live("Tell me about yourself.", "practice", threading.Event(), voice_id="demo0001", language="en"))
        b = next(b for b in self.vs.bodies if "input" in b)
        self.assertEqual((b["voice"], b["language"]), ("demo0001", "en"))


class Dialog(Base):
    def test_two_voice_review_narrator_asks_and_the_default_answers(self):
        it = learn.save("audio", "Revisão", {"title": "Sono", "intro": "Vamos lá.", "outro": "Fim.", "sources": [],
                                              "chapters": [{"title": "Memória", "items": [{"question": "O que consolida a memória?",
                                                                                           "answer": "O sono profundo.", "source": {}}]}]})
        settings.save({"voice": {"review_dialog": True, "narrator_voice": "demo0001"}})
        script = listen.review_script(it["id"])
        self.assertTrue(script["dialog"])
        listen.start("review", it["id"])
        j = wait_job()
        self.assertEqual(j["status"], "done", j.get("error"))
        by = {b["input"]: b["voice"] for b in self.vs.bodies if "input" in b}
        self.assertEqual(by["O que consolida a memória?"], "demo0001")
        self.assertEqual(by["O sono profundo."], "1faf41ee")  # a resposta, na voz padrão, sem o "Resposta:"
        self.assertIn("Demo Voice e Jhonny Sirverhand", j["result"]["audio"]["voice"])


if __name__ == "__main__":
    unittest.main()
