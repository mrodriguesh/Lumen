"""Fase 6, parte 3: conversa por voz em tempo real nos Estudos (`lumen/study/call.py`).
Máquina de estados inteira, fim da fala, resposta antecipada cancelada sem rastro, interrupção (botão e voz por cima)
com texto cortado onde parou, comandos rápidos sem LLM, mapa mental/diagrama/flashcards/plano/quiz/Feynman/tela/revisão
pela voz, salvar com prévia sem gravar no cofre, microfone bloqueado durante aula gravando, encerramento por silêncio,
privacidade (zero arquivos de áudio e registro de atividades só com tempos) e validação dos 18 ajustes `call_*`."""
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np

import tests  # noqa: F401
from lumen import AppError, loopback, record, server, store, vision, voice, voicestudio
from lumen.study import activity, agent, call, chats, db, index, learn, listen, mastery, providers, settings, writes
from tests import test_study_index as idx
from tests.fake_ollama import FakeOllama
from tests.fake_voicestudio import Fake as FakeVS


class FakeMic:
    """Microfone contínuo falso em 16 kHz (quadros de 512 amostras = 32 ms) com anel de 320 ms."""

    def __init__(self):
        self.on = False
        self.cb = None
        self.preroll = np.zeros(512 * 3, dtype=np.float32)

    def busy(self):
        return self.on

    def start_continuous(self, on_frame, mic_id="", open_mic=None):
        if record.active():
            raise AppError("Uma aula está sendo gravada.", "Pare a gravação para iniciar uma conversa por voz.")
        self.on = True
        self.cb = on_frame

    def preroll_audio(self):
        return self.preroll.copy()

    def stop(self):
        self.on = False
        self.cb = None
        return np.zeros(0, dtype=np.float32)

    def push(self, speech=True, n_frames=1, amp=0.18, tag=0.0):
        for _ in range(n_frames):
            f = np.full(512, amp if speech else 0.0, dtype=np.float32)
            if tag:
                f[0] = tag
            lv = float(np.sqrt(np.mean(f * f)))
            if self.cb:
                self.cb(f, lv)


class FakeSpeaker:
    """Alto-falante falso que registra os blocos reproduzidos, `flush()` e opcionalmente atrasa por quadro."""

    def __init__(self, delay_per_chunk=0.0):
        self.delay = delay_per_chunk
        self.played = []
        self.flushed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def play(self, chunk):
        a = np.asarray(chunk, dtype=np.float32).copy()
        self.played.append(a)
        if self.delay > 0:
            time.sleep(self.delay)

    def flush(self):
        self.flushed += 1


class FakeVAD:
    def reset(self):
        pass

    def prob(self, frame):
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        return 0.92 if rms >= 0.02 else 0.05


def wait_until(pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.015)
    return bool(pred())


class BaseCall(idx.Base):
    def setUp(self):
        super().setUp()
        chats.TEMP.clear()
        self.vs = FakeVS()
        self.ollama = FakeOllama(("qwen3.5:4b", "qwen3-embedding:0.6b"))
        self.note("Memoria e sono.md", "# Memória e sono\nA consolidação da memória acontece no sono profundo, pelo hipocampo.")
        index.sync("obsidian")
        self.ollama.answer = (
            "A consolidação da memória acontece no sono profundo, transferindo lembranças ao córtex [S1]. "
            "Por isso revisar antes de dormir melhora a retenção."
        )
        self.ollama.json_replies["Monte um mapa mental"] = {
            "center": "Memória", "sources": ["S1"],
            "branches": [
                {"label": "Codificação", "detail": "Entrada.", "children": [{"label": "Atenção", "detail": ""}]},
                {"label": "Consolidação", "detail": "Sono.", "children": [{"label": "Hipocampo", "detail": ""}]},
                {"label": "Evocação", "detail": "Lembrar.", "children": [{"label": "Prática", "detail": ""}]},
            ],
        }
        self.ollama.json_replies["Você prepara o material que acompanha uma explicação"] = {
            "diagram": {
                "family": "processo",
                "title": "Consolidação da memória",
                "relations": [{"from": 0, "to": 1, "kind": "leva a"}],
                "nodes": [
                    {"label": "Estudo", "detail": "Registro inicial.", "parent": -1},
                    {"label": "Sono profundo", "detail": "Fixação cortical.", "parent": -1},
                ],
            },
            "check": {"question": "Onde fixa?", "answer": "No córtex."},
        }
        self.ollama.json_replies["Crie um questionário"] = {
            "questions": [
                {
                    "kind": "multipla",
                    "question": "Qual estágio do sono consolida a memória declarativa?",
                    "options": ["Vigília", "Sono profundo", "Cochilo de 1 min", "Insônia"],
                    "answer": "Sono profundo",
                    "explanation": "Ondas lentas consolidam no córtex.",
                    "source": "S1",
                },
                {
                    "kind": "multipla",
                    "question": "Qual estrutura registra primeiro o episódio?",
                    "options": ["Hipocampo", "Cerebelo", "Medula", "Retina"],
                    "answer": "Hipocampo",
                    "explanation": "O hipocampo codifica primeiro.",
                    "source": "S1",
                },
            ]
        }
        self.ollama.json_replies["Monte um plano de estudos"] = {
            "title": "Plano de memória",
            "goal": "Dominar memória",
            "prerequisites": [{"topic": "Atenção", "why": "Base da codificação", "source": "S1"}],
            "steps": [
                {"title": "Base", "objective": "Ler resumo", "topics": ["Sono"], "sources": ["S1"], "minutes": 25},
                {"title": "Prática", "objective": "Fazer quiz", "topics": ["Hipocampo"], "sources": ["S1"], "minutes": 20},
            ],
            "reviews": [{"after_days": 1, "focus": "Consolidação"}],
        }
        self.ollama.json_replies["técnica de\nFeynman"] = {
            "right": [{"point": "O sono consolida a memória.", "source": "S1"}],
            "missing": [{"point": "Citar o hipocampo.", "source": "S1"}],
            "wrong": [],
            "score": 0.75,
            "feedback": "Boa explicação, só faltou mencionar o hipocampo.",
        }
        self.ollama.json_replies["Você lê uma captura de tela"] = {
            "titulo": "Slide de Neurociência",
            "texto": "Hipocampo -> Neocórtex",
            "descricao": "Diagrama de memória",
            "tipo": "slide",
            "conteudo_da_aula": True,
            "valores": [],
        }

        self.release_calls = 0
        def _count_release():
            self.release_calls += 1
            return False

        self.stack += [
            mock.patch.dict(os.environ, {"LUMEN_VOICESTUDIO_URL": self.vs.url}),
            mock.patch.object(listen, "AUDIO", self.tmp / "audio"),
            mock.patch.object(voice, "available", lambda: True),
            mock.patch.object(listen.transcribe, "gpu_free_gb", lambda: 4.0),
            mock.patch.object(listen.llm, "release_vram", _count_release),
            mock.patch.object(vision, "window_jpeg", lambda: (b"\xff\xd8\xff\xe0fakejpeg", "Aula — slide.pdf")),
        ]
        for p in self.stack[-6:]:
            p.start()

        voicestudio._engine["at"] = -1e9
        voicestudio._pron["at"] = -1e9
        voicestudio.BACKEND.failed, voicestudio.BACKEND.state = None, {"phase": "off"}
        settings.save({"voice": {"verify_long": False, "vs_autostart": False, "call_earcon": True}})

        self.mic = FakeMic()
        self.speakers = []
        self.asr_texts = ["Como o sono ajuda a memória?"]
        self.asr_calls = []

        def fake_asr(audio_16k, choice="auto"):
            self.asr_calls.append((len(audio_16k), choice))
            txt = self.asr_texts.pop(0) if len(self.asr_texts) > 1 else (self.asr_texts[0] if self.asr_texts else "")
            # O Parakeet real fecha toda fala completa com ponto ou interrogação (medido em 08/11/2026: 20 de 20 falas sintéticas).
            # O falso, que se diz "parakeet", faz o mesmo; senão o fim da fala trataria toda frase sem pontuação como cortada.
            if txt and txt.rstrip()[-1] not in ".!?…,;:":
                txt = txt.rstrip() + "."
            return txt, 18.5, "parakeet"

        def make_sp():
            sp = FakeSpeaker(delay_per_chunk=self.sp_delay)
            self.speakers.append(sp)
            return sp

        self.sp_delay = 0.0
        self.cm = call.CallManager(
            mic=self.mic,
            speaker_factory=make_sp,
            vad_factory=FakeVAD,
            asr_fn=fake_asr,
            warm_fn=lambda s, emit: listen.who("call", s),
        )
        self.events = []
        self._sub_q = self.cm.subscribe()
        self._collector_stop = threading.Event()

        def _collect():
            while not self._collector_stop.is_set():
                try:
                    ev = self._sub_q.get(timeout=0.05)
                    self.events.append(ev)
                except Exception:
                    pass

        self._collector = threading.Thread(target=_collect, daemon=True)
        self._collector.start()

    def tearDown(self):
        self.cm.stop()
        self._collector_stop.set()
        self.cm.unsubscribe(self._sub_q)
        chats.TEMP.clear()
        self.ollama.close()
        self.vs.close()
        super().tearDown()
        self.assertEqual(self.vs.writes(), [], "nenhuma rota de escrita do Voice Studio pode ser chamada na conversa")
        self.assertEqual(self.release_calls, 0, "a chamada nunca pode chamar llm.release_vram()")

    def start_ready(self, **kw):
        self.cm.start(**kw)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))

    def speak_utterance(self, text, silence_frames=24, speech_frames=12):
        self.asr_texts = [text]
        self.mic.push(speech=True, n_frames=speech_frames)
        self.assertEqual(self.cm.state, "user_speaking")
        self.mic.push(speech=False, n_frames=silence_frames)


class CallSettingsTests(BaseCall):
    def test_all_18_call_settings_defaults_and_validation(self):
        v = settings.load()["voice"]
        expected = {
            "call_mode": "handsfree",
            "call_silence": "normal",
            "call_barge_in": True,
            "call_headphones": False,
            "call_early": True,
            "call_mic": "",
            "call_voice": "",
            "call_speed": 1.0,
            "call_quality": "balanced",
            "call_length": "short",
            "call_effort": "auto",
            "call_earcon": True,
            "call_filler": False,
            "call_asr": "auto",
            "call_captions": True,
            "call_autostop": 5,
            "call_save": "history",
            "call_timings": False,
        }
        for k, val in expected.items():
            self.assertEqual(v[k], val, k)

        # Velocidade limitada a [0.7, 1.3]
        self.assertEqual(settings.save({"voice": {"call_speed": 9.0}})["voice"]["call_speed"], 1.3)
        self.assertEqual(settings.save({"voice": {"call_speed": 0.2}})["voice"]["call_speed"], 0.7)

        # Uso `call` resolve Jhonny por padrão e respeita `call_voice`
        self.assertEqual(listen.who("call")["voice"], "1faf41ee")
        settings.save({"voice": {"call_voice": "demo0001"}})
        self.assertEqual(listen.who("call")["voice"], "demo0001")
        settings.save({"voice": {"call_voice": ""}})

        # Valores inválidos rejeitados
        invalids = [
            {"call_mode": "telepatia"},
            {"call_silence": "eterno"},
            {"call_barge_in": "sim"},
            {"call_headphones": 1},
            {"call_early": "1"},
            {"call_mic": "bad\x00id"},
            {"call_voice": "../hack"},
            {"call_quality": "ultra"},
            {"call_length": "livro"},
            {"call_effort": "maximo"},
            {"call_asr": "cloud"},
            {"call_autostop": 3},
            {"call_save": "nuvem"},
            {"call_timings": "yes"},
        ]
        for bad in invalids:
            with self.assertRaises(AppError, msg=str(bad)):
                settings.save({"voice": bad})


class StateMachineAndTurnTests(BaseCall):
    def test_full_state_machine_earcon_privacy_and_no_disk_audio(self):
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        self.cm.stop()
        self.assertEqual(self.cm.state, "ended")

        states = [e["state"] for e in self.events if e.get("type") == "state"]
        for expected_state in ("preparing", "listening", "user_speaking", "end_of_speech", "transcribing", "thinking", "speaking", "ended"):
            self.assertIn(expected_state, states, f"faltou estado {expected_state} em {states}")

        # Som de "entendi" tocou em < 300 ms
        timings = [e for e in self.events if e.get("type") == "timing"]
        self.assertEqual(len(timings), 1)
        self.assertIsNotNone(timings[0]["earcon_ms"])
        self.assertLessEqual(timings[0]["earcon_ms"], 300.0)

        # Citação [S1] ficou no texto da conversa, mas sumiu da fala enviada ao Voice Studio; [S9] inventada foi limpa
        conv = chats.get(self.cm.conversation_id)
        bot_msgs = [m for m in conv["messages"] if m["role"] == "assistant"]
        self.assertEqual(len(bot_msgs), 1)
        self.assertIn("[S1]", bot_msgs[0]["content"])
        self.assertNotIn("[S9]", bot_msgs[0]["content"])
        spoken_inputs = " ".join(b.get("input", "") for b in self.vs.bodies if "input" in b)
        self.assertNotIn("[S1]", spoken_inputs)
        self.assertIn("consolidação da memória", spoken_inputs)

        # Privacidade: atividade guarda SÓ tempos, sem o texto da pergunta nem da resposta
        acts = activity.recent(action="chamada-turno")
        self.assertEqual(len(acts), 1)
        dump = json.dumps(acts, ensure_ascii=False)
        self.assertNotIn("sono", dump.lower())
        self.assertNotIn("consolidação", dump.lower())
        detail = json.loads(acts[0]["detail"])
        self.assertIn("total_ms", detail)

        # Nenhum arquivo de gravação do microfone no diretório temporário
        audio_files = [p for p in self.tmp.rglob("*") if p.is_file() and p.suffix.lower() in (".wav", ".pcm", ".raw")]
        self.assertEqual(audio_files, [])

    def test_end_of_speech_respects_silence_presets_and_ptt(self):
        # Paciente (1100 ms = 35 quadros): 22 quadros (704 ms) ainda mantém `user_speaking`
        settings.save({"voice": {"call_silence": "patient", "call_early": False}})
        self.start_ready()
        self.asr_texts = ["Pergunta paciente."]
        self.mic.push(speech=True, n_frames=8)
        self.mic.push(speech=False, n_frames=22)
        self.assertEqual(self.cm.state, "user_speaking")
        self.mic.push(speech=False, n_frames=14)
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))

        # Modo apertar para falar (PTT)
        self.cm.update_settings({"call_mode": "ptt"})
        self.asr_texts = ["Pergunta no botão."]
        self.cm.ptt_down()
        self.assertEqual(self.cm.state, "user_speaking")
        self.mic.push(speech=False, n_frames=40)  # silêncio não encerra sozinho no PTT
        self.assertEqual(self.cm.state, "user_speaking")
        self.cm.ptt_up()
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 2 and self.cm.state == "listening"))

    def test_speculative_early_response_cancelled_leaves_zero_trace(self):
        settings.save({"voice": {"call_silence": "normal", "call_early": True}})
        gate_entered = threading.Event()
        real_turn = agent.turn

        def spied_turn(payload, tid):
            if payload.get("_commit_gate") is not None:
                gate_entered.set()
            yield from real_turn(payload, tid)

        self.cm._custom_turn = spied_turn
        self.start_ready()

        # 1ª metade da fala + pausa de 320 ms (10 quadros >= 250 ms, < 700 ms): dispara resposta antecipada
        self.asr_texts = ["Frase incompleta que será descartada", "Como o sono ajuda a memória?"]
        self.mic.push(speech=True, n_frames=8)
        self.mic.push(speech=False, n_frames=10)
        self.assertTrue(gate_entered.wait(timeout=4.0), "a resposta antecipada não iniciou aos ~250 ms")
        self.assertIsNotNone(self.cm._spec)

        # Estudante volta a falar antes dos 700 ms → cancela especulação sem deixar rastro!
        self.mic.push(speech=True, n_frames=6)
        self.assertIsNone(self.cm._spec)

        # Verifica que nada da frase descartada foi para o chat nem para os eventos
        self.assertEqual(chats.listing(), [])
        emitted_finals = [e["text"] for e in self.events if e.get("type") == "final"]
        self.assertEqual(emitted_finals, [])

        # Agora termina a frase de verdade (24 quadros = 768 ms de silêncio)
        self.mic.push(speech=False, n_frames=24)
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))

        conv = chats.get(self.cm.conversation_id)
        user_msgs = [m["content"] for m in conv["messages"] if m["role"] == "user"]
        self.assertEqual(user_msgs, ["Como o sono ajuda a memória?"])
        self.assertNotIn("Frase incompleta", json.dumps(conv, ensure_ascii=False))
        self.assertTrue(any(e.get("type") == "timing" and e.get("early_hit") for e in self.events))

    def test_interruption_truncates_text_flushes_speaker_and_echo_guard_blocks_pure_echo(self):
        # Resposta longa com várias frases + reprodução compassada para interromper no meio da 1ª frase
        self.ollama.answer = (
            "Primeira frase explicando o hipocampo com bastante calma na chamada. "
            "Segunda frase que jamais chegará a ser tocada porque será interrompida. "
            "Terceira frase que também nunca vai ao ar."
        )
        self.sp_delay = 0.015
        self.start_ready()
        self.speak_utterance("Me explica o hipocampo.")
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking" and len(self.speakers) >= 2))
        time.sleep(0.08)

        # Interrompe com "Falar agora"
        self.cm.interrupt()
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        self.assertTrue(any(sp.flushed > 0 for sp in self.speakers), "faltou dar flush no alto-falante na interrupção")

        conv = chats.get(self.cm.conversation_id)
        bot = [m for m in conv["messages"] if m["role"] == "assistant"][-1]
        self.assertTrue(bot["meta"].get("interrupted"))
        self.assertNotIn("Terceira frase", bot["content"])
        self.assertNotIn("jamais chegará", bot["content"])
        self.assertTrue(any(e.get("type") == "interrupted" for e in self.events))

        # Interrompe falando por cima (barge-in com fone ligado): muda de `speaking` para `user_speaking`
        self.cm.update_settings({"call_headphones": True, "call_barge_in": True})
        self.speak_utterance("Explica de novo o hipocampo.")
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking"))
        self.mic.push(speech=True, n_frames=4, amp=0.25)
        self.assertTrue(wait_until(lambda: self.cm.state == "user_speaking"))
        self.cm.interrupt()  # volta para listening limpo

        # EchoGuard (4.4): eco puro da caixa de som NÃO dispara barge-in; voz real acima da barreira dispara
        eg = call.EchoGuard()
        rng = np.random.default_rng(42)
        spk_24k = (rng.standard_normal(768 * 25) * 0.14).astype(np.float32)
        eg.push_speaker_24k(spk_24k)
        ref_frames = list(eg.ref_frames)
        for i in range(15):
            _, _, _, above = eg.process((ref_frames[i] * 0.22).astype(np.float32), headphones=False)
            self.assertFalse(above, "eco puro da caixa de som não pode ultrapassar a barreira")
        barge_hits = []
        for i in range(15, 22):
            # Sinal não-estacionário (envoltória silábica) bem acima do eco
            env_mod = 0.5 + 0.5 * np.sin(np.linspace(0, np.pi, 512, dtype=np.float32))
            user_voice = (rng.standard_normal(512).astype(np.float32) * 0.45 * env_mod)
            _, _, _, above_loud = eg.process(ref_frames[i] * 0.22 + user_voice, headphones=False)
            barge_hits.append(above_loud)
        self.assertTrue(any(barge_hits), "fala real acima do eco deve passar na barreira")


class FastCommandsAndIntentsTests(BaseCall):
    def test_fast_commands_never_call_llm(self):
        self.start_ready()
        self.cm.last_spoken_answer = "O sono consolida a memória."
        llm_before = len(self.ollama.requests)

        for cmd in ("mais devagar", "mais rápido", "fala mais baixo", "fala com a voz da demo", "repete", "para"):
            self.events.clear()
            self.speak_utterance(cmd)
            self.assertTrue(wait_until(lambda: any(e.get("type") == "final" and e.get("fast") for e in self.events) and self.cm.state == "listening"))

        self.assertEqual(self.cm.who["voice"], "demo0001")
        self.assertLess(self.cm.volume, 1.0)

        # "encerra a chamada" desliga a chamada
        self.speak_utterance("encerra a chamada")
        self.assertTrue(wait_until(lambda: not self.cm.active and self.cm.state == "ended"))
        self.assertEqual(len(self.ollama.requests), llm_before, "comandos rápidos não podem chamar o modelo de texto")

    def test_voice_mindmap_diagram_flashcards_plan_and_screen(self):
        self.start_ready()

        # 1. Mapa mental pela voz → cartão `mindmap` + fala curta de 1 frase
        self.events.clear()
        self.speak_utterance("Cria um mapa mental de memória")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "item"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["item"]["kind"], "mindmap")
        sents = [e["text"] for e in self.events if e.get("type") == "sentence"]
        self.assertEqual(sents, ["Pronto, o mapa mental tem 3 ramos; está na tela."])

        # 2. Explicação com diagrama → cartão `explain` com `diagram`
        self.events.clear()
        self.speak_utterance("Explica com um diagrama como o sono consolida a memória")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 2 and self.cm.state == "listening"))
        ex_cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "explain"]
        self.assertEqual(len(ex_cards), 1)
        self.assertIn("diagram", ex_cards[0]["explain"])

        # 3. Flashcards → cartão `flashcards`
        self.events.clear()
        self.speak_utterance("Cria flashcards de memória")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 3 and self.cm.state == "listening"))
        fc_cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "item"]
        self.assertEqual(fc_cards[0]["item"]["kind"], "flashcards")

        # 4. Plano de estudo → cartão `plan`
        self.events.clear()
        self.speak_utterance("Monta um plano de estudo de memória")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 4 and self.cm.state == "listening"))
        pl_cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "item"]
        self.assertEqual(pl_cards[0]["item"]["kind"], "plan")

        # 5. "Olha minha tela" → cartão `screen` (sem gravar print no disco)
        self.events.clear()
        self.speak_utterance("Olha minha tela e me diz o que está escrito")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 5 and self.cm.state == "listening"))
        sc_cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "screen"]
        self.assertEqual(len(sc_cards), 1)
        self.assertIn("Aula", sc_cards[0]["window"])

    def test_voice_quiz_dont_know_mastery_feynman_review_and_save_preview(self):
        self.start_ready()

        # 1. Inicia quiz por voz
        self.events.clear()
        self.speak_utterance("Me faz um quiz de memória")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        self.assertIsNotNone(self.cm._quiz)

        # Questão 1: responde "letra B" ("Sono profundo" -> correta!)
        self.events.clear()
        self.speak_utterance("letra B")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 2 and self.cm.state == "listening"))
        q1_card = [e for e in self.events if e.get("type") == "card" and e.get("quiz_result")][0]
        self.assertTrue(q1_card["quiz_result"]["correct"])

        # Questão 2: responde "não sei" -> NUNCA inventa acerto (score 0.0, correct False) e registra erro no mastery!
        self.events.clear()
        self.speak_utterance("não sei")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 3 and self.cm.state == "listening"))
        q2_card = [e for e in self.events if e.get("type") == "card" and e.get("quiz_result")][0]
        self.assertFalse(q2_card["quiz_result"]["correct"])
        self.assertEqual(q2_card["quiz_result"]["score"], 0.0)
        self.assertIsNone(self.cm._quiz)

        # 2. "O que eu errei" consulta o `mastery` real
        self.events.clear()
        self.speak_utterance("O que eu mais errei?")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 4 and self.cm.state == "listening"))
        m_cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "mastery"]
        self.assertEqual(len(m_cards), 1)
        self.assertGreaterEqual(len(m_cards[0]["items"]), 1)

        # 3. Feynman em dois turnos ("vou te explicar..." -> explicação)
        self.events.clear()
        self.speak_utterance("Vou te explicar memória e sono")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 5 and self.cm.state == "listening"))
        self.assertEqual(self.cm._feynman_topic, "memória e sono")

        self.events.clear()
        self.speak_utterance("Dormir depois de estudar consolida as lembranças no córtex.")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 6 and self.cm.state == "listening"))
        fey_cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "feynman"]
        self.assertEqual(len(fey_cards), 1)
        self.assertAlmostEqual(fey_cards[0]["feynman"]["score"], 0.75)

        # 4. Revisão do dia (cria um flashcard vencido e responde pela voz)
        saved_fc = learn.save("flashcards", "Memória", {"cards": [{"question": "O que consolida?", "answer": "Sono profundo.", "source": {"sid": "S1"}}]})
        learn.add_cards(saved_fc["id"], saved_fc["data"]["cards"])
        self.events.clear()
        self.speak_utterance("Revisão do dia")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 7 and self.cm.state == "listening"))
        self.assertIsNotNone(self.cm._review)
        self.speak_utterance("não sei")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 8 and self.cm.state == "listening"))
        self.assertIsNone(self.cm._review)

        # 5. Salvar no Obsidian pela voz → abre prévia (`pending`) e NÃO grava arquivo no cofre!
        vault_files_before = sorted(p.relative_to(self.vault) for p in self.vault.rglob("*.md"))
        self.events.clear()
        self.speak_utterance("Salva isso no Obsidian")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 9 and self.cm.state == "listening"))
        pend = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "pending"]
        self.assertEqual(len(pend), 1)
        self.assertEqual([a["id"] for a in writes.pending()], [pend[0]["action"]["id"]])
        vault_files_after = sorted(p.relative_to(self.vault) for p in self.vault.rglob("*.md"))
        self.assertEqual(vault_files_after, vault_files_before, "salvar pela voz nunca pode gravar sem confirmar a prévia")


class GuardsAndRoutesTests(BaseCall):
    def test_blocked_during_lesson_recording_autostop_temporary_and_http_routes(self):
        # 1. Bloqueado enquanto uma aula está sendo gravada
        with mock.patch.object(record, "active", return_value=True):
            with self.assertRaises(AppError) as ctx:
                self.cm.start()
            self.assertIn("sendo gravada", str(ctx.exception))

        # 2. Encerrar sozinho após `call_autostop` minutos em silêncio
        settings.save({"voice": {"call_autostop": 2}})
        self.start_ready()
        self.cm.last_activity = time.monotonic() - 125.0
        self.assertTrue(wait_until(lambda: not self.cm.active and self.cm.state == "ended", timeout=3.0))

        # 3. Conversa temporária (`call_save = "temporary"`): nada gravado no banco SQLite
        settings.save({"voice": {"call_save": "temporary", "call_autostop": 5}})
        self.start_ready()
        self.speak_utterance("Pergunta temporária na chamada.")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        self.assertTrue(self.cm.conversation_id.startswith("tmp-"))
        self.cm.stop()
        self.assertEqual(db.rows("SELECT * FROM conversations"), [])
        self.assertEqual(db.rows("SELECT * FROM messages"), [])

        # 4. Rotas HTTP `/api/study/call`, `/api/study/call/events` e `/api/study/voice/mics` exigem token
        with mock.patch.object(call, "CALL", self.cm), mock.patch.object(loopback, "microphones", return_value=[{"id": "mic1", "name": "USB Mic", "default": True}]):
            httpd = server.serve()
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                base = f"http://127.0.0.1:{httpd.server_port}"
                with self.assertRaises(urllib.error.HTTPError) as herr:
                    urllib.request.urlopen(base + "/api/study/call")
                self.assertEqual(herr.exception.code, 403)

                req = urllib.request.Request(base + "/api/study/voice/mics", headers={"X-Lumen-Token": server.TOKEN})
                with urllib.request.urlopen(req) as r:
                    mics = json.loads(r.read())["microphones"]
                self.assertEqual(mics[0]["name"], "USB Mic")

                req = urllib.request.Request(
                    base + "/api/study/call",
                    data=json.dumps({"action": "start"}).encode(),
                    headers={"X-Lumen-Token": server.TOKEN, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as r:
                    snap = json.loads(r.read())
                self.assertTrue(snap["active"])

                ev_req = urllib.request.Request(base + "/api/study/call/events", headers={"X-Lumen-Token": server.TOKEN})
                with urllib.request.urlopen(ev_req, timeout=3) as r:
                    first_line = json.loads(r.readline())
                    self.assertEqual(first_line["type"], "state")
                    stop_req = urllib.request.Request(
                        base + "/api/study/call",
                        data=json.dumps({"action": "stop"}).encode(),
                        headers={"X-Lumen-Token": server.TOKEN, "Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(stop_req).read()
                    saw_ended = first_line.get("state") == "ended"
                    while not saw_ended:
                        ev_line = json.loads(r.readline())
                        if ev_line.get("type") == "state" and ev_line.get("state") == "ended":
                            saw_ended = True
                    self.assertTrue(saw_ended)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_asr_picker_quiz_answer_mapping_and_deep_effort_voice_notice(self):
        # 1. `pick_call_asr`: com 4 GB livres (< 6,5 GB) e Parakeet baixado, escolhe `parakeet` na CPU
        with mock.patch.object(call.transcribe, "downloaded", return_value=True), \
                mock.patch.object(call.transcribe, "has_gpu", return_value=True), \
                mock.patch.object(call.transcribe, "gpu_free_gb", return_value=4.0):
            self.assertEqual(call.pick_call_asr("auto"), "parakeet")
            self.assertEqual(call.pick_call_asr("whisper"), "whisper")
            self.assertEqual(call.pick_call_asr("parakeet"), "parakeet")
        with mock.patch.object(call.transcribe, "downloaded", return_value=True), \
                mock.patch.object(call.transcribe, "has_gpu", return_value=True), \
                mock.patch.object(call.transcribe, "gpu_free_gb", return_value=8.0):
            self.assertEqual(call.pick_call_asr("auto"), "whisper")

        # 2. `map_quiz_spoken_answer`: ordinais, V/F e "não sei"
        q_mc = {"kind": "multipla", "options": ["Vigília", "Sono profundo", "REM"]}
        self.assertEqual(call.map_quiz_spoken_answer(q_mc, "a segunda opção"), "Sono profundo")
        self.assertEqual(call.map_quiz_spoken_answer(q_mc, "acho que é a letra c"), "REM")
        self.assertEqual(call.map_quiz_spoken_answer({"kind": "vf"}, "acho que é verdadeiro"), "Verdadeiro")
        self.assertTrue(learn.is_dont_know("não tenho ideia"))
        self.assertTrue(learn.is_dont_know("passo"))
        self.assertFalse(learn.is_dont_know("o sono profundo consolida"))

        # 3. Pedido explícito de raciocínio profundo pela voz ("pensa com calma") avisa o tempo estimado
        self.ollama.models.append("qwen3.5:9b")
        self.start_ready()
        self.events.clear()
        self.speak_utterance("Pensa com calma e analisa profundamente como o sono consolida a memória")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        spoken_all = " ".join(b.get("input", "") for b in self.vs.bodies if "input" in b)
        self.assertIn("Vou pensar com calma", spoken_all)


if __name__ == "__main__":
    unittest.main()
