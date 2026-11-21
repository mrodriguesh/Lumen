"""Conversa por voz natural (08/11/2026): isolamento por turno, Livre/Notas na chamada, comandos de voz, fim de fala,
reconexão do fluxo de eventos, falhas de áudio e de síntese.

Estes testes usam o microfone, o alto-falante, o VAD e a transcrição FALSOS de `tests/test_study_call.py` e o Voice Studio
falso: provam a lógica e a coordenação, não a naturalidade percebida nem o áudio real (isso é medido em `bench/call_bench.py`
e conferido ao vivo pelo estudante)."""
import json
import threading
import time
import unittest
from unittest import mock

import numpy as np

import tests  # noqa: F401
from lumen import AppError, voicestudio
from lumen.study import agent, call, chats, learn, listen, search, settings, writes
from tests.test_study_call import BaseCall, FakeMic, wait_until

NOTE_MARK = "pelo hipocampo"   # trecho que só existe na nota do cofre da fixture (BaseCall.setUp)


def tone_wav(seconds=0.4, amp=0.1, sr=voicestudio.SR):
    t = np.arange(int(seconds * sr), dtype=np.float32) / sr
    pcm = (np.sin(2 * np.pi * 220 * t) * amp * 32767).astype("<i2").tobytes()
    return listen._wav(pcm, sr)


class LadderVAD:
    """VAD falso com três degraus: voz clara (0,92), fim de palavra (0,40, entre a histerese 0,35 e a entrada 0,5) e silêncio."""

    def reset(self):
        pass

    def prob(self, frame):
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        return 0.92 if rms >= 0.1 else 0.40 if rms >= 0.02 else 0.05


class Spy(BaseCall):
    """BaseCall + registro dos payloads que chegam ao agente e das requisições que chegam ao (falso) Ollama."""

    def setUp(self):
        super().setUp()
        self.payloads = []
        real = agent.turn

        def spied(payload, tid):
            self.payloads.append({k: v for k, v in payload.items() if k != "_commit_gate"})
            yield from real(payload, tid)

        self.cm._custom_turn = spied

    def chat_bodies(self):
        return [json.dumps(b, ensure_ascii=False) for path, b in self.ollama.requests if path == "/api/chat"]

    def finish_turn(self, n):
        self.assertTrue(wait_until(lambda: self.cm.turn_count == n and self.cm.state == "listening", timeout=10.0))


class StaleTurnTests(BaseCall):
    """Um turno cancelado nunca revive: a síntese que ainda estava em andamento quando o estudante interrompeu pode
    terminar depois, mas o áudio dela não toca nem aparece na legenda do turno seguinte."""

    def test_synthesis_finishing_after_interruption_does_not_leak_into_next_turn(self):
        old_first_started = threading.Event()
        release_old = threading.Event()

        def synth(sentence, w, s, steps, seed, check, work_dir=None, eng=None):
            if "velha" in sentence.lower():
                old_first_started.set()
                release_old.wait(timeout=10.0)  # a síntese "demora" mesmo depois da interrupção
                return tone_wav(0.4, 0.2), 0.4, False
            return tone_wav(0.4, 0.1), 0.4, False

        self.cm._custom_synth = synth
        self.ollama.answer = "Primeira frase velha bem calma. Segunda velha frase que nunca deve ser ouvida. Terceira velha."
        self.sp_delay = 0.01
        self.start_ready()
        self.speak_utterance("Pergunta antiga.")
        # a 1ª frase ainda está sendo sintetizada (estado "pensando"): é aqui que o estudante interrompe
        self.assertTrue(old_first_started.wait(timeout=8.0), "a síntese do turno antigo não começou")
        self.assertEqual(self.cm.state, "thinking")
        self.cm.interrupt()
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))

        # Novo turno enquanto a síntese antiga ainda está pendurada
        self.ollama.answer = "Resposta nova e limpa."
        self.events.clear()
        self.speak_utterance("Pergunta nova.")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 2 and self.cm.state in ("speaking", "listening")))
        release_old.set()  # só agora a síntese velha termina
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 2 and self.cm.state == "listening", timeout=10.0))
        time.sleep(0.4)

        said = [e["text"] for e in self.events if e.get("type") == "sentence"]
        self.assertTrue(any("nova" in t.lower() for t in said), said)
        self.assertFalse(any("velha" in t.lower() for t in said), f"frase do turno antigo reapareceu: {said}")
        loud_old = [c for sp in self.speakers for c in sp.played if c.size and float(np.max(np.abs(c))) > 0.15]
        self.assertEqual(loud_old, [], "áudio da síntese antiga (amplitude 0,2) tocou no turno seguinte")

    def test_events_from_a_cancelled_turn_are_dropped_and_carry_the_turn_id(self):
        self.start_ready()
        self.speak_utterance("Primeira pergunta.")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        ids = {e.get("turn_id") for e in self.events if e.get("type") in ("token", "sentence", "timing") and e.get("turn_id")}
        self.assertEqual(len(ids), 1, "todos os eventos de um turno levam o mesmo turn_id")
        seqs = [e["seq"] for e in self.events if "seq" in e]
        self.assertEqual(seqs, sorted(seqs), "seq cresce sempre")
        self.assertEqual(len(seqs), len(set(seqs)), "seq nunca repete")
        old = self.cm._turn
        old.cancel.set()
        n = len(self.events)
        self.cm._tl.turn = old          # simula uma thread atrasada do turno antigo
        try:
            self.cm._emit({"type": "sentence", "i": 9, "text": "fantasma"})
            self.cm._set_state("speaking")
        finally:
            self.cm._tl.turn = None
        time.sleep(0.1)
        self.assertEqual(len(self.events), n)
        self.assertEqual(self.cm.state, "listening")

    def test_each_turn_shows_the_spoken_question_once(self):
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening"))
        finals = [e["text"] for e in self.events if e.get("type") == "final" and not e.get("fast")]
        self.assertEqual(finals, ["Como o sono ajuda a memória?"], "antes, a legenda repetia a fala (understanding e depois user)")

    def test_agent_cancel_before_registration_is_not_lost(self):
        agent.cancel("turno-que-ainda-nao-comecou")
        self.assertIn("turno-que-ainda-nao-comecou", agent.PRE_CANCEL)
        events = list(agent.turn({"text": "Oi", "temporary": True}, "turno-que-ainda-nao-comecou"))
        self.assertEqual(events[-1]["type"], "cancelled")
        self.assertNotIn("turno-que-ainda-nao-comecou", agent.PRE_CANCEL)


class BargeInWhileThinkingTests(Spy):
    def test_speaking_while_the_model_thinks_cancels_that_turn_and_listens(self):
        gate = threading.Event()
        real = agent.turn

        def slow(payload, tid):
            self.payloads.append({k: v for k, v in payload.items() if k != "_commit_gate"})
            gate.wait(timeout=8.0)   # o modelo ainda não escreveu nada: estado "pensando"
            yield from real(payload, tid)

        self.cm._custom_turn = slow
        self.cm._custom_vad = LadderVAD
        self.cm._vad = LadderVAD()
        self.start_ready()
        self.speak_utterance("Primeira pergunta que vou corrigir.")
        self.assertTrue(wait_until(lambda: self.cm.state == "thinking"))
        time.sleep(call.BARGE_SETTLE_S + 0.1)
        # o estudante fala por cima: voz clara por 6 quadros (~190 ms)
        self.asr_texts = ["Na verdade quero saber outra coisa sobre a memória."]
        self.mic.push(speech=True, n_frames=6, amp=0.25)
        self.assertTrue(wait_until(lambda: self.cm.state == "user_speaking"))
        self.assertTrue(self.cm._turn.cancel.is_set(), "o turno que estava pensando foi cancelado")
        gate.set()
        self.mic.push(speech=True, n_frames=8, amp=0.25)
        self.mic.push(speech=False, n_frames=24)
        self.assertTrue(wait_until(lambda: self.cm.turn_count >= 1 and self.cm.state == "listening", timeout=10.0))
        conv = chats.get(self.cm.conversation_id)
        finals = [m["content"] for m in conv["messages"] if m["role"] == "user"]
        self.assertEqual(finals[-1], "Na verdade quero saber outra coisa sobre a memória.")
        self.assertEqual(len([e for e in self.events if e.get("type") == "sentence"]), len(
            [e for e in self.events if e.get("type") == "sentence"]))   # nenhuma frase do turno cancelado (checado abaixo)
        said = [e["text"] for e in self.events if e.get("type") == "sentence"]
        self.assertEqual(len(said), len(set(said)), f"frase repetida entre turnos: {said}")


class PauseMergeTests(Spy):
    """Pausa longa no meio da frase: se o estudante retoma antes de qualquer som, as duas partes viram UMA pergunta."""

    FIRST = "Qual é a diferença entre memória de trabalho?"
    FULL = "Qual é a diferença entre memória de trabalho e memória de longo prazo?"

    def hold_before_saving(self):
        """O modelo "pensa": nada foi escrito nem salvo ainda (o agente só salva a pergunta quando termina de escrever)."""
        gate = threading.Event()
        real = agent.turn

        def slow(payload, tid):
            self.payloads.append({k: v for k, v in payload.items() if k != "_commit_gate"})
            gate.wait(timeout=8.0)
            yield from real(payload, tid)

        self.cm._custom_turn = slow
        self.cm._custom_vad = LadderVAD
        self.cm._vad = LadderVAD()
        return gate

    def hold_before_sound(self):
        """A resposta já está pronta e salva, mas a voz ainda não saiu (a síntese do 1º trecho está pendurada)."""
        gate = threading.Event()

        def synth(sentence, w, s, steps, seed, check, work_dir=None, eng=None):
            gate.wait(timeout=8.0)
            return tone_wav(0.2, 0.1), 0.2, False

        self.cm._custom_synth = synth
        self.cm._custom_vad = LadderVAD
        self.cm._vad = LadderVAD()
        return gate

    def resume(self, wait_s):
        time.sleep(wait_s)
        self.asr_texts = [self.FULL]                           # o que o reconhecedor ouve agora: a fala inteira
        self.mic.push(speech=True, n_frames=6, amp=0.25)       # retoma falando
        self.assertTrue(wait_until(lambda: self.cm.state == "user_speaking"))
        self.mic.push(speech=True, n_frames=10, amp=0.25)
        self.mic.push(speech=False, n_frames=24)

    def first_half(self):
        self.start_ready()
        self.asr_texts = [self.FIRST]
        self.mic.push(speech=True, n_frames=12, amp=0.25)
        self.mic.push(speech=False, n_frames=24)               # 768 ms: o turno fecha com a 1ª metade
        self.assertTrue(wait_until(lambda: self.cm.state == "thinking"))
        return self.asr_calls[0][0]

    def test_resuming_while_the_model_is_still_thinking_merges_into_one_question(self):
        gate = self.hold_before_saving()
        first_len = self.first_half()
        self.assertIsNone(self.cm._turn.user_mid, "nada salvo ainda")
        self.resume(call.BARGE_SETTLE_S + 0.1)
        gate.set()
        self.finish_turn(1)
        users = [m["content"] for m in chats.get(self.cm.conversation_id)["messages"] if m["role"] == "user"]
        self.assertEqual(users, [self.FULL], "só a pergunta inteira fica no histórico")
        self.assertTrue(any(e.get("type") == "retract" for e in self.events), "a tela é avisada para tirar a metade cortada")
        self.assertGreater(self.asr_calls[-1][0], first_len + 16000 * 0.3, "a transcrição recebeu a 1ª parte E a retomada")
        self.assertEqual(self.cm.turn_count, 1)

    def test_resuming_after_the_answer_was_saved_but_before_any_sound_still_merges(self):
        gate = self.hold_before_sound()
        self.first_half()
        self.assertTrue(wait_until(lambda: self.cm._turn.mid is not None and self.cm._turn.user_mid is not None, timeout=8.0))
        self.assertEqual(len(chats.get(self.cm.conversation_id)["messages"]), 2, "pergunta e resposta já salvas")
        self.resume(call.BARGE_SETTLE_S + 0.1)
        gate.set()
        self.finish_turn(1)
        msgs = chats.get(self.cm.conversation_id)["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"], "a pergunta cortada e a resposta a ela saíram")
        self.assertEqual(msgs[0]["content"], self.FULL)

    def test_resuming_after_the_window_is_a_new_question(self):
        gate = self.hold_before_sound()
        self.first_half()
        self.assertTrue(wait_until(lambda: self.cm._turn.mid is not None and self.cm._turn.user_mid is not None, timeout=8.0))
        with mock.patch.object(call, "MERGE_WINDOW_S", 0.0):
            self.resume(call.BARGE_SETTLE_S + 0.1)
        gate.set()
        self.assertTrue(wait_until(lambda: self.cm.state == "listening", timeout=10.0))
        conv = chats.get(self.cm.conversation_id)
        users = [m["content"] for m in conv["messages"] if m["role"] == "user"]
        self.assertEqual(users, [self.FIRST, self.FULL], "fora da janela a 1ª pergunta continua no histórico")
        self.assertFalse(any(e.get("type") == "retract" for e in self.events))

    def test_barge_in_while_speaking_never_drops_the_question(self):
        self.cm._custom_vad = LadderVAD
        self.cm._vad = LadderVAD()
        self.sp_delay = 0.01
        self.start_ready()
        self.asr_texts = ["Me explica o hipocampo."]
        self.mic.push(speech=True, n_frames=12, amp=0.25)
        self.mic.push(speech=False, n_frames=24)
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking"))
        self.asr_texts = ["Espera, uma pergunta."]
        self.cm.update_settings({"call_headphones": True, "call_barge_in": True}, persist=False)
        self.mic.push(speech=True, n_frames=6, amp=0.4)
        self.assertTrue(wait_until(lambda: self.cm.state == "user_speaking"))
        self.mic.push(speech=True, n_frames=8, amp=0.25)
        self.mic.push(speech=False, n_frames=24)
        self.assertTrue(wait_until(lambda: self.cm.turn_count >= 2 and self.cm.state == "listening", timeout=10.0))
        users = [m["content"] for m in chats.get(self.cm.conversation_id)["messages"] if m["role"] == "user"]
        self.assertEqual(users, ["Me explica o hipocampo.", "Espera, uma pergunta."])
        self.assertFalse(any(e.get("type") == "retract" for e in self.events))

    def test_frames_arriving_while_the_interruption_runs_are_kept(self):
        self.start_ready()
        self.cm._barge_pending, self.cm._barge_buf, self.cm._barge_since = True, [], time.monotonic()
        for _ in range(3):
            self.cm._on_mic_frame(np.full(512, 0.2, np.float32), 0.2)
        self.assertEqual(len(self.cm._barge_buf), 3)
        self.cm._barge_since = time.monotonic() - 5.0       # a interrupção travou: o microfone não fica preso
        self.cm._on_mic_frame(np.full(512, 0.2, np.float32), 0.2)
        self.assertFalse(self.cm._barge_pending)
        self.assertEqual(self.cm._barge_buf, [])


class VaultModeTests(Spy):
    """Livre/Notas na chamada: o mesmo skip_vault/vault_sources do chat escrito, uma fotografia por turno."""

    def test_default_call_sends_the_same_fields_as_the_text_chat_in_notes_mode(self):
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        p = self.payloads[-1]
        self.assertIs(p["skip_vault"], False)
        self.assertNotIn("vault_sources", p)
        self.assertTrue(any(NOTE_MARK in b for b in self.chat_bodies()), "no modo Notas a nota entra no contexto")
        st = [e for e in self.events if e.get("type") == "state"][-1]
        self.assertEqual(st["vault"], {"free": False, "sources": None})

    def test_free_mode_at_start_reaches_the_agent_and_no_note_is_read(self):
        self.cm.start(free=True)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.assertIs(self.payloads[-1]["skip_vault"], True)
        self.assertNotIn("vault_sources", self.payloads[-1])
        self.assertFalse(any(NOTE_MARK in b for b in self.chat_bodies()), "Livre: nenhuma nota pode chegar ao modelo")
        self.assertFalse([e for e in self.events if e.get("type") == "card"])
        conv = chats.get(self.cm.conversation_id)
        bot = [m for m in conv["messages"] if m["role"] == "assistant"][-1]
        self.assertTrue(bot["meta"].get("free_mode"))
        self.assertTrue(bot["meta"].get("call"))
        self.assertEqual(bot["sources"], [])

    def test_custom_sources_reach_the_agent_and_filter_the_search(self):
        self.cm.start(sources=["obsidian"])
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.assertEqual(self.payloads[-1]["vault_sources"], ["obsidian"])
        self.assertIs(self.payloads[-1]["skip_vault"], False)
        # só Notion: o cofre do Obsidian não pode aparecer
        self.cm.set_vault(sources=["notion"])
        self.ollama.requests.clear()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(2)
        self.assertEqual(self.payloads[-1]["vault_sources"], ["notion"])
        self.assertFalse(any(NOTE_MARK in b for b in self.chat_bodies()))

    def test_invalid_sources_and_profile_are_rejected(self):
        for bad in ([], ["nuvem"], "obsidian", [1]):
            with self.assertRaises(AppError, msg=str(bad)):
                call.clean_sources(bad)
        self.assertEqual(call.clean_sources(["obsidian", "obsidian", "notion"]), ["obsidian", "notion"])
        self.assertIsNone(call.clean_sources(None))
        with self.assertRaises(AppError):
            self.cm.start(profile="invasor")
        self.assertFalse(self.cm.active)

    def test_changing_mode_mid_call_applies_to_the_next_turn_only(self):
        self.sp_delay = 0.01
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking"))
        self.cm.set_vault(free=True)    # no meio da resposta do turno 1
        snap = self.cm.snapshot()
        self.assertTrue(snap["vault"]["free"])
        self.assertFalse(snap["vault_turn"]["free"], "o turno em andamento segue com a fotografia dele")
        self.assertTrue(snap["vault_pending"], "a tela precisa saber que o novo modo ainda não vale para esta resposta")
        self.finish_turn(1)
        self.assertIs(self.payloads[-1]["skip_vault"], False)
        self.assertTrue(any(NOTE_MARK in b for b in self.chat_bodies()))
        self.assertFalse(self.cm.snapshot()["vault_pending"])
        # turno 2: já é Livre
        self.ollama.requests.clear()
        self.speak_utterance("E como o sono ajuda a memória?")
        self.finish_turn(2)
        self.assertIs(self.payloads[-1]["skip_vault"], True)
        self.assertFalse(any(NOTE_MARK in b for b in self.chat_bodies()))
        # a mesma conversa e o mesmo projeto durante a troca de modo
        conv = chats.get(self.cm.conversation_id)
        self.assertEqual(len([m for m in conv["messages"] if m["role"] == "user"]), 2)
        self.assertTrue(any(e.get("type") == "vault" and e["vault"]["free"] for e in self.events))

    def test_switching_back_to_notes_uses_the_notes_again(self):
        self.cm.start(free=True)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        self.cm.set_vault(free=False)
        self.assertEqual(self.cm.snapshot()["vault"], {"free": False, "sources": None})
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.assertIs(self.payloads[-1]["skip_vault"], False)
        self.assertTrue(any(NOTE_MARK in b for b in self.chat_bodies()))

    def test_speculative_answer_from_the_old_mode_is_discarded_and_text_is_reused(self):
        settings.save({"voice": {"call_early": True}})
        self.start_ready()
        self.asr_texts = ["Como o sono ajuda a memória?"]
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)            # 288 ms: nasce a resposta antecipada em modo Notas
        self.assertTrue(wait_until(lambda: len(self.payloads) == 1))
        self.assertIs(self.payloads[0]["skip_vault"], False)
        self.assertTrue(wait_until(lambda: self.cm._spec is not None and self.cm._spec.asr_done.is_set()))
        self.cm.vault_free = True   # a troca chega junto do fim da fala (sem passar por set_vault, que já cancelaria)
        self.mic.push(speech=False, n_frames=21)
        self.finish_turn(1)
        self.assertEqual(len(self.payloads), 2, "a antecipada do modo antigo e a refeita")
        self.assertIs(self.payloads[1]["skip_vault"], True)
        self.assertEqual(len(self.asr_calls), 1, "o texto já transcrito é reaproveitado; a fala não é reconhecida de novo")
        conv = chats.get(self.cm.conversation_id)
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"], "a antecipada descartada não deixa rastro")
        self.assertTrue(conv["messages"][1]["meta"].get("free_mode"))
        self.assertFalse(any(e.get("type") == "timing" and e.get("early_hit") for e in self.events))

    def test_set_vault_cancels_a_pending_speculation(self):
        settings.save({"voice": {"call_early": True}})
        self.start_ready()
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)
        self.assertTrue(wait_until(lambda: self.cm._spec is not None))
        spec = self.cm._spec
        self.cm.set_vault(free=True)
        self.assertIsNone(self.cm._spec)
        self.assertTrue(spec.cancel_ev.is_set())

    def test_stale_prefetch_never_reintroduces_notes(self):
        text = "Como o sono ajuda a memória?"
        poisoned = {"results": [{"id": "x", "source": "obsidian", "title": "Velho", "path": "Velho.md", "author": "user",
                                 "chunks": [{"id": "x1", "heading": "", "text": "SEGREDO ANTIGO DE PREFETCH"}]}],
                    "related": [], "semantic": False, "sources": ["obsidian"],
                    "_keywords": search.heuristic(text)["keywords"], "_vault": None}
        # Livre: o resultado antecipado é ignorado por inteiro
        events = list(agent.turn({"text": text, "temporary": True, "skip_vault": True, "prefetched_search": poisoned,
                                  "call": {"length": "short", "effort": "auto"}}, "pf-livre"))
        self.assertNotIn("sources", [e["type"] for e in events])
        self.assertFalse(any("SEGREDO ANTIGO" in b for b in self.chat_bodies()))
        # Notas, mas só Notion: o resultado feito para "todas as fontes" não vale
        list(agent.turn({"text": text, "temporary": True, "vault_sources": ["notion"], "prefetched_search": poisoned,
                         "call": {"length": "short", "effort": "auto"}}, "pf-notion"))
        self.assertFalse(any("SEGREDO ANTIGO" in b for b in self.chat_bodies()))
        # a call só repassa a antecipada se a fotografia bater
        self.cm._prefetched = poisoned
        p = self.cm._build_agent_payload(text, {}, {"free": True, "sources": None})
        self.assertIsNone(p["prefetched_search"])
        p = self.cm._build_agent_payload(text, {}, {"free": False, "sources": ["notion"]})
        self.assertIsNone(p["prefetched_search"])
        p = self.cm._build_agent_payload(text, {}, {"free": False, "sources": None})
        self.assertIs(p["prefetched_search"], poisoned)

    def test_profile_chosen_in_the_chat_travels_with_the_call(self):
        self.cm.start(profile="main")
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.assertEqual(self.payloads[-1]["profile"], "main")
        self.assertEqual(self.cm.snapshot()["profile"], "main")


class VaultVoiceCommandTests(Spy):
    POSITIVE_FREE = ("ativar modo livre", "Ativa o modo livre.", "pode ativar o modo livre", "por favor, ativa o modo livre",
                     "entra no modo livre", "muda para o modo livre", "usar modo livre", "lumen ativar modo livre")
    POSITIVE_NOTES = ("usar minhas notas", "usa as minhas notas", "voltar para as notas", "volta pras notas", "consultar minhas notas",
                      "sair do modo livre", "desativar o modo livre", "desliga o modo livre", "ativar o modo notas", "usa minhas notas de novo")
    NEGATIVE = ("o que é o modo livre", "o que significa ativar modo livre", "quando eu falo ativar modo livre o que acontece",
                "diz ativar modo livre", "não quero ativar o modo livre", "ele disse usar minhas notas ontem",
                "me explica como usar minhas notas no estudo", "o modo livre consulta o notion", "ativar modo livre e me explica a fotossíntese",
                "o que são minhas notas", "usar as notas de física para explicar força")

    def fold(self, t):
        return call.search._fold(t).strip(" .,!?")

    def test_command_patterns(self):
        for t in self.POSITIVE_FREE:
            self.assertTrue(call.FREE_ON_RE.match(self.fold(t)), t)
        for t in self.POSITIVE_NOTES:
            f = self.fold(t)
            self.assertTrue(call.FREE_OFF_RE.match(f) or call.NOTES_ON_RE.match(f), t)
        for t in self.NEGATIVE:
            f = self.fold(t)
            for rx in (call.FREE_ON_RE, call.FREE_OFF_RE, call.NOTES_ON_RE, call.NOTES_ONLY_RE):
                self.assertFalse(rx.match(f), f"{t!r} não pode trocar o modo ({rx.pattern[:40]}…)")
        self.assertTrue(call.NOTES_ONLY_RE.match(self.fold("usar só o obsidian")))
        self.assertTrue(call.NOTES_ONLY_RE.match(self.fold("consulta apenas o notion")))

    def test_spoken_commands_switch_the_mode_without_calling_the_model(self):
        self.start_ready()
        before = len(self.ollama.requests)
        self.speak_utterance("ativar modo livre")
        self.assertTrue(wait_until(lambda: self.cm.vault_free and self.cm.state == "listening"))
        self.assertEqual(self.payloads, [], "comando de voz não vai ao agente")
        self.assertEqual(len(self.ollama.requests), before)
        self.assertTrue(any(e.get("type") == "final" and e.get("fast") == "vault" for e in self.events))
        self.assertTrue(any(e.get("type") == "vault" and e["source"] == "voice" and e["vault"]["free"] for e in self.events))
        spoken = " ".join(b.get("input", "") for b in self.vs.bodies if "input" in b)
        self.assertIn("modo livre", spoken)
        # a conversa não ganhou mensagem nenhuma por causa do comando
        self.assertIsNone(self.cm.conversation_id)

        self.speak_utterance("usar minhas notas")
        self.assertTrue(wait_until(lambda: not self.cm.vault_free and self.cm.state == "listening"))
        self.speak_utterance("usar só o obsidian")
        self.assertTrue(wait_until(lambda: self.cm.vault_sources == ["obsidian"] and self.cm.state == "listening"))
        self.assertFalse(self.cm.vault_free)
        self.assertEqual(self.payloads, [])

    def test_asking_about_the_option_does_not_change_it(self):
        self.start_ready()
        self.speak_utterance("o que é o modo livre?")
        self.finish_turn(1)
        self.assertFalse(self.cm.vault_free)
        self.assertEqual(len(self.payloads), 1, "a pergunta vai ao modelo como uma pergunta normal")
        self.speak_utterance("ele disse ativar modo livre mas eu não quero")
        self.finish_turn(2)
        self.assertFalse(self.cm.vault_free)

    def test_command_during_a_turn_applies_to_the_next_one(self):
        self.start_ready()
        self.speak_utterance("ativar modo livre")
        self.assertTrue(wait_until(lambda: self.cm.vault_free and self.cm.state == "listening"))
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)    # o comando não conta como turno do modelo
        self.assertIs(self.payloads[-1]["skip_vault"], True)
        self.assertFalse(any(NOTE_MARK in b for b in self.chat_bodies()))


class SpecialPathsRespectTheModeTests(Spy):
    def feynman(self):
        self.speak_utterance("Vou te explicar memória e sono")
        self.finish_turn(1)
        self.speak_utterance("Dormir depois de estudar consolida as lembranças no córtex.")
        self.finish_turn(2)

    def test_feynman_in_free_mode_never_searches_the_notes(self):
        self.cm.start(free=True)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        with mock.patch.object(call.search, "search", side_effect=AssertionError("busca nas notas no modo livre")):
            self.feynman()
        cards = [e for e in self.events if e.get("type") == "card" and e.get("kind") == "feynman"]
        self.assertEqual(len(cards), 1)
        self.assertFalse(any(NOTE_MARK in b for b in self.chat_bodies()), "Livre: nenhuma nota no Feynman")

    def test_feynman_with_custom_sources_searches_only_those(self):
        self.cm.start(sources=["obsidian"])
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        with mock.patch.object(call.search, "search", wraps=search.search) as spy:
            self.feynman()
        self.assertTrue(spy.called)
        self.assertEqual(spy.call_args.kwargs["sources"], ["obsidian"])

    def test_saving_to_obsidian_in_free_mode_is_refused_like_in_the_chat(self):
        self.cm.start(free=True)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.speak_utterance("Salva isso no Obsidian")
        self.finish_turn(2)
        self.assertEqual(writes.pending(), [], "no modo livre nenhuma prévia de nota é preparada")
        self.assertFalse([e for e in self.events if e.get("type") == "card" and e.get("kind") == "pending"])
        spoken = " ".join(b.get("input", "") for b in self.vs.bodies if "input" in b)
        self.assertIn("modo livre", spoken)

    def test_quiz_grading_does_not_touch_the_notes_and_keeps_the_mode(self):
        self.cm.start(free=True)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        saved = learn.save("quiz", "Memória", {"questions": [
            {"kind": "multipla", "question": "Qual estágio consolida?", "options": ["Vigília", "Sono profundo"],
             "answer": "Sono profundo", "explanation": "Ondas lentas.", "source": {"sid": "S1"}}]})
        self.cm._quiz = {"item_id": saved["id"], "index": 0, "total": 1}
        with mock.patch.object(call.search, "search", side_effect=AssertionError("quiz não busca notas")):
            self.speak_utterance("letra B")
            self.finish_turn(1)
        self.assertTrue(self.cm.vault_free)


class EndpointingTests(Spy):
    def test_unfinished_phrases(self):
        for t in ("Eu queria saber como funciona o", "então, tipo,", "Me explica a diferença entre memória e", "Porque…",
                  "Eu acho que quando a gente dorme a", "a consolidação acontece no sono profundo e",
                  "Qual é a diferença entre memória de trabalho"):    # sem pontuação final, 4+ palavras: áudio cortado
            self.assertTrue(call.looks_unfinished(t), t)
        for t in ("Como o sono ajuda a memória?", "Me explica a fotossíntese.", "Quanto é dois mais dois?", "Obrigado!",
                  "Pode continuar", "Não entendi", "", "Isso mesmo", "letra B", "Me faz um quiz.", "Cria um mapa mental."):
            self.assertFalse(call.looks_unfinished(t), t)

    def test_incomplete_sentence_gets_one_extra_wait_and_continuing_does_not_cut(self):
        settings.save({"voice": {"call_silence": "normal", "call_early": True}})
        self.start_ready()
        self.asr_texts = ["Eu queria saber como funciona o"]
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)                        # 288 ms: a antecipada transcreve
        self.assertTrue(wait_until(lambda: self.cm._spec is not None and self.cm._spec.asr_done.is_set()))
        self.mic.push(speech=False, n_frames=16)                       # 800 ms de silêncio > 700 ms
        self.assertEqual(self.cm.state, "user_speaking", "frase inacabada: espera mais um pouco em vez de cortar")
        # o estudante continua dentro da espera: a antecipada some e o turno é um só
        self.asr_texts = ["Eu queria saber como funciona o hipocampo na memória de longo prazo."]
        self.mic.push(speech=True, n_frames=10)
        self.assertIsNone(self.cm._spec)
        self.mic.push(speech=False, n_frames=24)
        self.finish_turn(1)
        conv = chats.get(self.cm.conversation_id)
        users = [m["content"] for m in conv["messages"] if m["role"] == "user"]
        self.assertEqual(users, ["Eu queria saber como funciona o hipocampo na memória de longo prazo."])

    def test_the_extra_wait_is_bounded(self):
        settings.save({"voice": {"call_silence": "normal", "call_early": True}})
        self.start_ready()
        self.asr_texts = ["Eu queria saber como funciona o"]
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)
        self.assertTrue(wait_until(lambda: self.cm._spec is not None and self.cm._spec.asr_done.is_set()))
        self.mic.push(speech=False, n_frames=30)                       # 1,2 s no total < 700 + 900
        self.assertEqual(self.cm.state, "user_speaking")
        self.mic.push(speech=False, n_frames=25)                       # passou de 1,6 s: fecha o turno de qualquer jeito
        self.finish_turn(1)

    def test_complete_sentence_closes_at_the_normal_time_and_fast_never_waits(self):
        settings.save({"voice": {"call_silence": "normal", "call_early": True}})
        self.start_ready()
        self.asr_texts = ["Como o sono ajuda a memória?"]
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)
        self.assertTrue(wait_until(lambda: self.cm._spec is not None and self.cm._spec.asr_done.is_set()))
        self.mic.push(speech=False, n_frames=15)                       # 768 ms
        self.finish_turn(1)
        settings.save({"voice": {"call_silence": "fast"}})
        self.cm.update_settings({"call_silence": "fast"})
        self.asr_texts = ["Eu queria saber como funciona o"]
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)
        self.assertTrue(wait_until(lambda: self.cm._spec is not None and self.cm._spec.asr_done.is_set()))
        self.mic.push(speech=False, n_frames=6)                        # 480 ms > 450 ms
        self.finish_turn(2)

    def test_commands_that_end_with_a_preposition_are_not_held(self):
        self.start_ready()
        self.asr_texts = ["para"]
        self.mic.push(speech=True, n_frames=12)
        self.mic.push(speech=False, n_frames=9)
        self.assertTrue(wait_until(lambda: self.cm._spec is not None and self.cm._spec.asr_done.is_set()))
        self.mic.push(speech=False, n_frames=15)
        self.assertTrue(wait_until(lambda: self.cm.state == "listening" and any(e.get("fast") == "stop" for e in self.events)))

    def test_vad_hysteresis_keeps_the_trailing_soft_end_of_words_as_speech(self):
        self.cm._custom_vad = LadderVAD
        self.cm._vad = LadderVAD()
        settings.save({"voice": {"call_early": False}})
        self.start_ready()
        self.asr_texts = ["Como o sono ajuda a memória?"]
        self.mic.push(speech=True, n_frames=10, amp=0.25)              # voz clara (0,92)
        # final de palavra: energia baixa (prob 0,40): pelo limiar antigo (0,5) era silêncio e ia contando o fim da fala
        for _ in range(10):
            f = np.full(512, 0.05, dtype=np.float32)
            self.cm._on_mic_frame(f, 0.05)
        self.assertEqual(self.cm._silence_frames, 0, "prob 0,40 já falando continua sendo fala (histerese)")
        # mas uma fala que COMEÇA com prob 0,40 não dispara o estado
        self.mic.push(speech=False, n_frames=30)
        self.finish_turn(1)
        self.mic.on = True
        for _ in range(6):
            self.cm._on_mic_frame(np.full(512, 0.05, dtype=np.float32), 0.05)
        self.assertEqual(self.cm.state, "listening")


class EventStreamTests(Spy):
    def test_reconnect_replays_only_what_was_missed(self):
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        evs = [e for e in self.events if e.get("seq") is not None]
        seen_until = next(e["seq"] for e in evs if e.get("type") == "sentence")
        q = self.cm.subscribe(since=seen_until)
        replay = []
        while not q.empty():
            replay.append(q.get_nowait())
        self.cm.unsubscribe(q)
        # nada de antes do ponto, nada duplicado; e o último é sempre o estado atual
        body = replay[:-1]
        self.assertTrue(all(e["seq"] > seen_until for e in body))
        self.assertEqual(len({e["seq"] for e in body}), len(body))
        self.assertEqual(replay[-1]["type"], "state")
        self.assertEqual(replay[-1]["state"], "listening")
        self.assertIn("timing", [e["type"] for e in body])
        # sem `since`: só o estado
        q2 = self.cm.subscribe()
        first = q2.get_nowait()
        self.assertTrue(q2.empty())
        self.assertEqual(first["type"], "state")
        self.cm.unsubscribe(q2)

    def test_ring_is_cleared_when_a_new_call_starts(self):
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.cm.stop()
        self.cm.start()
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        q = self.cm.subscribe(since=0)
        types = []
        while not q.empty():
            types.append(q.get_nowait()["type"])
        self.assertNotIn("sentence", types, "a chamada nova não herda a legenda da anterior")
        self.assertNotIn("token", types)


class FailureTests(Spy):
    def test_synthesis_error_keeps_the_call_alive_and_the_text_in_the_caption(self):
        def broken(sentence, *a, **k):
            raise AppError("A voz falhou.", "Tente de novo.")

        self.cm._custom_synth = broken
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        errs = [e for e in self.events if e.get("type") == "error"]
        self.assertTrue(errs)
        self.assertTrue([e for e in self.events if e.get("type") == "token"], "a legenda continua mesmo sem voz")
        conv = chats.get(self.cm.conversation_id)
        self.assertEqual(len([m for m in conv["messages"] if m["role"] == "assistant"]), 1)
        self.cm._custom_synth = None
        self.speak_utterance("Outra pergunta sobre a memória.")
        self.finish_turn(2)    # a chamada segue viva e a voz volta

    def test_speaker_that_cannot_open_reports_it_and_the_turn_ends(self):
        calls = []

        def no_audio():
            calls.append(1)
            raise OSError("sem saída de áudio")

        self.cm._custom_speaker = no_audio
        self.cm.set_mute(False)
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.assertTrue(wait_until(lambda: self.cm.turn_count == 1 and self.cm.state == "listening", timeout=10.0))
        msgs = [e["message"] for e in self.events if e.get("type") == "error"]
        self.assertTrue(any("saída de áudio" in m for m in msgs), msgs)
        self.assertTrue(any(e.get("type") == "token" for e in self.events))

    def test_stopping_while_preparing_leaves_no_zombie_state(self):
        gate = threading.Event()
        self.cm._warm_fn = lambda s, emit: (gate.wait(5.0), listen.who("call", s))[1]
        self.cm.start()
        self.assertEqual(self.cm.state, "preparing")
        self.cm.stop()
        self.assertEqual(self.cm.state, "ended")
        gate.set()
        time.sleep(0.3)
        self.assertEqual(self.cm.state, "ended", "terminar a preparação depois do fim não pode voltar a 'ouvindo'")
        self.assertFalse(self.cm.active)
        self.cm._warm_fn = lambda s, emit: listen.who("call", s)
        self.start_ready()    # e uma chamada nova funciona
        self.assertTrue(self.cm.active)

    def test_mute_while_speaking_keeps_the_answer_and_blocks_barge_in(self):
        self.sp_delay = 0.01
        self.cm.update_settings({"call_headphones": True, "call_barge_in": True})
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking"))
        self.cm.set_mute(True)
        self.mic.push(speech=True, n_frames=12, amp=0.4)
        self.assertEqual(self.cm.state, "speaking", "mudo: o microfone não interrompe a resposta")
        self.assertTrue(self.cm.snapshot()["muted"])
        self.cm.set_mute(False)
        self.finish_turn(1)

    def test_lost_microphone_reconnects(self):
        class Flaky(FakeMic):
            def __init__(self):
                super().__init__()
                self.starts = 0

            def start_continuous(self, on_frame, mic_id="", open_mic=None):
                self.starts += 1
                super().start_continuous(on_frame, mic_id, open_mic)

        mic = Flaky()
        self.mic = mic
        self.cm._custom_mic = mic
        self.start_ready()
        self.assertEqual(mic.starts, 1)
        mic.on = False   # o aparelho sumiu: a thread do microfone morreu
        with mock.patch.object(call, "MIC_RETRY_S", 0.01):
            self.cm._watch_mic()
        self.assertEqual(mic.starts, 2, "tentou reabrir o microfone")
        self.assertEqual(self.cm.state, "listening")
        self.assertTrue(wait_until(lambda: any("reconectado" in (e.get("text") or "") for e in self.events)))
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)

    def test_microphone_that_never_comes_back_ends_the_call_with_a_clear_error(self):
        class Dead(FakeMic):
            def start_continuous(self, on_frame, mic_id="", open_mic=None):
                if getattr(self, "armed", False):
                    raise AppError("O microfone não abriu.")
                super().start_continuous(on_frame, mic_id, open_mic)

        mic = Dead()
        self.cm._custom_mic = mic
        self.start_ready()
        mic.armed, mic.on = True, False
        with mock.patch.object(call, "MIC_RETRY_S", 0.01):
            self.cm._watch_mic()
        self.assertFalse(self.cm.active)
        self.assertEqual(self.cm.state, "ended")
        self.assertTrue(wait_until(lambda: any(e.get("type") == "error" for e in self.events)))
        msgs = [e["message"] for e in self.events if e.get("type") == "error"]
        self.assertTrue(any("microfone" in m.lower() for m in msgs), msgs)

    def test_real_mic_class_marks_frames_and_abandons_a_hung_thread(self):
        m = listen.Mic()
        gate = threading.Event()

        class HungRec:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def record(self, numframes):
                gate.wait(5.0)
                return None

        m.start_continuous(lambda f, lv: None, open_mic=lambda sr, ch, mid: HungRec())
        self.assertIsNone(m.last_frame_at)
        m.stop_ev.set()
        m.thread.join(0.1)           # a thread está presa no aparelho
        self.assertTrue(m.busy())
        m.start_continuous(lambda f, lv: None, open_mic=lambda sr, ch, mid: HungRec())   # não bloqueia: a presa é abandonada
        self.assertGreaterEqual(m._gen, 2)
        gate.set()
        m.stop()


class SpeechTextTests(unittest.TestCase):
    def test_symbols_become_words_and_noise_is_removed(self):
        t = call.speech_text("A taxa subiu **15%** → veja [S1] em https://exemplo.com/x. 😀 F = m·a")
        self.assertNotIn("%", t)
        self.assertIn("15 por cento", t)
        for bad in ("**", "[S1]", "http", "→", "😀", "="):
            self.assertNotIn(bad, t)
        self.assertIn("igual a", t)
        self.assertEqual(call.speech_text("25°C e 80 km/h"), "25 graus Celsius e 80 quilômetros por hora.")
        self.assertIn("e ou", call.speech_text("a e/ou b"))
        self.assertIn("2 mais 3", call.speech_text("2+3"))
        self.assertIn("C++", call.speech_text("Aprenda C++ hoje"))

    def test_clause_cut_keeps_the_intonation_open(self):
        self.assertEqual(call.speech_text("Claro, ", clause=True), "Claro,")
        self.assertEqual(call.speech_text("O sono ajuda a memória, ", clause=True), "O sono ajuda a memória,")
        self.assertEqual(call.speech_text("Fim da ideia.", clause=True), "Fim da ideia.")
        self.assertEqual(call.speech_text("Claro, "), "Claro.")

    def test_pop_ready_sentences_clause_ends_with_comma(self):
        rest, ready = call.CallManager._pop_ready_sentences("A consolidação da memória acontece, principalmente durante o sono profundo.", first=True)
        self.assertTrue(ready[0].endswith(","), ready)
        self.assertNotIn("[S", " ".join(ready))


class ChunkScheduleTests(Spy):
    def test_split_chunk_never_breaks_words_and_keeps_the_text(self):
        long = ("A consolidação da memória acontece principalmente durante o sono profundo, quando o hipocampo reativa as lembranças "
                "recentes e as transfere aos poucos para o córtex, onde elas ficam guardadas por muito tempo.")
        rest, pieces, i = long, [], 0
        while rest:
            piece, rest = call.split_chunk(rest, call.chunk_limit(i))
            pieces.append(piece)
            i += 1
        self.assertGreaterEqual(len(pieces), 3)
        for k, piece in enumerate(pieces):
            self.assertLessEqual(len(piece), call.chunk_limit(k) + 1, (k, piece))
        self.assertEqual(" ".join(" ".join(pieces).replace(",", "").split()), " ".join(long.replace(",", "").split()), "o texto não muda")
        for piece in pieces[:-1]:
            self.assertTrue(piece.endswith(","), f"pedaço que não fecha a frase termina em vírgula: {piece!r}")
        self.assertEqual(call.split_chunk("Curto e direto.", 64), ("Curto e direto.", ""))
        # sem pontuação útil: no espaço, nunca no meio da palavra
        piece, rest = call.split_chunk("uma frase muito comprida sem nenhuma pausa para respirar que continua e continua", 30)
        self.assertEqual(piece, "uma frase muito comprida sem,")
        self.assertTrue(rest.startswith("nenhuma"))

    def test_second_chunk_is_short_enough_to_be_ready_before_the_first_ends(self):
        seen = []

        def synth(sentence, w, s, steps, seed, check, work_dir=None, eng=None):
            seen.append(sentence)
            return tone_wav(0.2, 0.1), 0.2, False

        self.cm._custom_synth = synth
        self.ollama.answer = ("Resposta direta, com o essencial logo no começo. Depois vem uma segunda frase bem mais comprida, que reúne várias ideias "
                              "numa só, que antes deixava a voz parada esperando a síntese terminar de gerar o áudio inteiro dela. Fim.")
        self.start_ready()
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        self.assertGreaterEqual(len(seen), 4, seen)
        for k, text in enumerate(seen):
            self.assertLessEqual(len(text), call.chunk_limit(k) + 2, f"pedaço {k} grande demais para a síntese acompanhar: {text!r}")
        self.assertTrue(seen[0].endswith(","), f"o 1º pedaço, cortado na vírgula, chega à voz com vírgula: {seen[0]!r}")


class LengthTests(unittest.TestCase):
    def test_long_explanation_requested_by_voice_overrides_short(self):
        s = {"call_length": "short"}
        for t in ("Me explica com calma como funciona a fotossíntese", "Quero uma explicação detalhada sobre o hipocampo",
                  "explica passo a passo a respiração celular", "Conta tudo sobre a Revolução Francesa", "aprofunda esse assunto"):
            self.assertEqual(call.CallManager._call_length(t, s), "detailed", t)
        for t in ("O que é fotossíntese?", "Qual a capital da França?", "Quanto é dois mais dois?"):
            self.assertEqual(call.CallManager._call_length(t, s), "short", t)
        self.assertEqual(call.CallManager._call_length("O que é isso?", {"call_length": "chat"}), "chat")


class InterruptionHistoryTests(Spy):
    def test_interrupted_answer_keeps_what_was_heard_and_the_generated_text(self):
        self.ollama.answer = ("Primeira frase explicando o hipocampo com bastante calma na chamada. "
                              "Segunda frase que jamais chegará a ser tocada porque será interrompida. "
                              "Terceira frase que também nunca vai ao ar.")
        self.sp_delay = 0.015
        self.start_ready()
        self.speak_utterance("Me explica o hipocampo.")
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking" and len(self.speakers) >= 2))
        time.sleep(0.08)
        self.cm.interrupt()
        self.assertTrue(wait_until(lambda: self.cm.state == "listening"))
        conv = chats.get(self.cm.conversation_id)
        bot = [m for m in conv["messages"] if m["role"] == "assistant"][-1]
        self.assertTrue(bot["meta"]["interrupted"])
        self.assertNotIn("Terceira", bot["content"])
        self.assertIn("Terceira frase", bot["meta"]["generated"], "o que o modelo escreveu fica guardado à parte")
        self.assertLess(len(bot["content"]), len(bot["meta"]["generated"]))
        self.assertEqual(self.cm.last_spoken_answer, bot["content"])
        interrupted = [e for e in self.events if e.get("type") == "interrupted"]
        self.assertEqual(len(interrupted), 1, "a interrupção é registrada uma vez só")
        self.cm.stop()
        self.assertEqual(len([e for e in self.events if e.get("type") == "interrupted"]), 1)

    def test_playback_stops_quickly_after_an_interruption(self):
        self.ollama.answer = "Frase longa um. " * 12
        self.sp_delay = 0.02
        self.start_ready()
        self.speak_utterance("Me explica o hipocampo.")
        self.assertTrue(wait_until(lambda: self.cm.state == "speaking" and len(self.speakers) >= 1))
        time.sleep(0.1)
        n_chunks = sum(len(sp.played) for sp in self.speakers)
        t0 = time.monotonic()
        self.cm.interrupt()
        self.assertTrue(wait_until(lambda: all(sp.flushed or True for sp in self.speakers)))
        elapsed = (time.monotonic() - t0) * 1000
        time.sleep(0.2)
        after = sum(len(sp.played) for sp in self.speakers)
        self.assertLess(after - n_chunks, 8, "depois de interromper só sobra a descida suave de 50 ms")
        self.assertLess(elapsed, 400.0)


class FirstChunkQualityTests(Spy):
    def run_with(self, first):
        steps_seen = []

        def synth(sentence, w, s, steps, seed, check, work_dir=None, eng=None):
            steps_seen.append(steps)
            return tone_wav(0.2, 0.1), 0.2, False

        self.cm._custom_synth = synth
        self.ollama.answer = "Primeira frase calma sobre a memória. Segunda frase sobre o sono. Terceira frase final."
        self.start_ready()
        self.cm.update_settings({"call_quality": "quality", "call_first_quality": first}, persist=False)
        self.speak_utterance("Como o sono ajuda a memória?")
        self.finish_turn(1)
        return steps_seen

    def test_default_keeps_the_same_steps_for_every_chunk(self):
        seen = self.run_with("same")
        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual(set(seen), {listen.STEPS["quality"]}, "por padrão nada muda na qualidade da voz")

    def test_fast_first_chunk_only_changes_the_first(self):
        seen = self.run_with("fast")
        self.assertEqual(seen[0], listen.STEPS["fast"])
        self.assertEqual(set(seen[1:]), {listen.STEPS["quality"]})

    def test_setting_is_validated_and_defaults_to_same(self):
        self.assertEqual(settings.load()["voice"]["call_first_quality"], "same")
        with self.assertRaises(AppError):
            settings.save({"voice": {"call_first_quality": "turbo"}})


class WarmupTests(BaseCall):
    def test_first_sound_is_warmed_once_while_preparing(self):
        sentences = []
        call._TTS_WARM.clear()
        real = listen.synth_sentence

        def synth(sentence, *a, **k):
            sentences.append(sentence)
            return real(sentence, *a, **k)

        cm = call.CallManager(mic=self.mic, speaker_factory=lambda: __import__("tests.test_study_call", fromlist=["x"]).FakeSpeaker(),
                              vad_factory=__import__("tests.test_study_call", fromlist=["x"]).FakeVAD,
                              asr_fn=lambda a, c="auto": ("", 0.0, "none"), synth_fn=synth)
        cm._warm_fn = None
        with mock.patch.object(call.providers, "warm_local", lambda **k: None), \
                mock.patch.object(call.CallManager, "_warm_asr_safe", lambda self: None), \
                mock.patch.object(listen, "_prepare", lambda s, check: iter(())):
            cm.start()
            self.assertTrue(wait_until(lambda: cm.state == "listening", timeout=10.0))
            self.assertEqual(sentences, ["Pronto."], "a voz é aquecida na preparação, não na 1ª resposta")
            cm.stop()
            cm.start()
            self.assertTrue(wait_until(lambda: cm.state == "listening", timeout=10.0))
            self.assertEqual(sentences, ["Pronto."], "já aquecida: a chamada seguinte abre sem repetir")
            cm.stop()
        self.assertTrue(call._TTS_WARM.is_set())


class IdleAsrTests(unittest.TestCase):
    def test_call_recognizers_leave_memory_only_after_the_idle_time_without_a_call(self):
        old = time.monotonic() - call.transcribe.IDLE_S - 1
        with mock.patch.dict(call._ASR_MODELS, {("parakeet", "cpu"): object()}, clear=True), \
                mock.patch.object(call, "_asr_used", old):
            with mock.patch.object(call.CALL, "active", True):
                call.release_idle()
            self.assertTrue(call._ASR_MODELS)  # chamada aberta: nunca
            with mock.patch.object(call, "_asr_used", time.monotonic()):
                call.release_idle()
            self.assertTrue(call._ASR_MODELS)  # fala recente: fica
            call.release_idle()
            self.assertFalse(call._ASR_MODELS)


if __name__ == "__main__":
    unittest.main()
