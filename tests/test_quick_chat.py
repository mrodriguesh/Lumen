"""Conversa rápida (barra flutuante) no backend: uma resposta de chat por conversa de cada vez, em qualquer janela; a conversa diz
se está respondendo (`generating`); a conferência `brief` não carrega mensagens; Livre/Notas chega ao agente. Ollama falso."""
import json
import threading
import time
import unittest
from unittest import mock

import tests  # noqa: F401
from lumen.study import agent, api, chats
from tests.test_study_core import Core, run_turn


def start(payload, turn_id):
    """Uma resposta em segundo plano: devolve (thread, eventos) e espera a conversa ficar reservada."""
    events = []
    t = threading.Thread(target=lambda: events.extend(agent.turn(payload, turn_id)), daemon=True)
    t.start()
    return t, events


def wait_for(cond, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class QuickChat(Core):
    def setUp(self):
        super().setUp()
        self.cid = next(e for e in run_turn({"text": "Primeira pergunta sobre sono"}) if e["type"] == "conversation")["conversation"]["id"]
        # só depois da conversa criada: as respostas seguintes transmitem de verdade e esperam no `gate`
        self.ollama.delay, self.ollama.gate, self.ollama.hold_after = 0.01, None, 2

    def release(self):
        if self.ollama.gate is not None:
            self.ollama.gate.set()

    def tearDown(self):
        self.release()
        super().tearDown()

    def hold(self, cid=None, turn_id="held-turn-0001", **extra):
        self.ollama.gate = threading.Event()  # esta resposta espera aqui, no meio, até release()
        t, events = start({"text": "Pergunta que fica esperando", "conversation_id": cid or self.cid, **extra}, turn_id)
        self.assertTrue(wait_for(lambda: agent.generating(cid or self.cid)), "a conversa devia ficar reservada")
        return t, events

    def test_second_chat_turn_on_same_conversation_is_refused_and_does_not_touch_it(self):
        t, events = self.hold()
        before = [m["content"] for m in chats.get(self.cid)["messages"]]
        refused = list(agent.turn({"text": "segunda ao mesmo tempo", "conversation_id": self.cid}, "second-turn-0001"))
        self.assertEqual([e["type"] for e in refused], ["error"])
        self.assertEqual(refused[0]["code"], "conversation_busy")
        # a recusada não salvou pergunta nenhuma: o histórico é o de antes mais só a pergunta da que está respondendo
        after = [m["content"] for m in chats.get(self.cid)["messages"]]
        self.assertNotIn("segunda ao mesmo tempo", after)
        self.assertEqual(after[:len(before)], before)
        self.release()
        t.join(30)
        self.assertFalse(agent.generating(self.cid), "terminou: a conversa foi liberada")
        ok = list(agent.turn({"text": "agora pode", "conversation_id": self.cid}, "third-turn-0001"))
        self.assertEqual(ok[-1]["type"], "done")

    def test_other_conversation_is_not_blocked(self):
        t, _ = self.hold()
        t2, other = start({"text": "conversa nova, outra", "temporary": True}, "other-turn-0001")
        self.assertTrue(wait_for(lambda: any(e["type"] == "user" for e in other)), "a outra conversa seguiu enquanto a primeira esperava")
        self.assertNotIn("error", [e["type"] for e in other])
        self.release()
        t.join(30), t2.join(30)
        self.assertEqual(other[-1]["type"], "done")

    def test_cancel_releases_the_conversation(self):
        t, events = self.hold()
        agent.cancel("held-turn-0001")
        self.release()
        t.join(30)
        self.assertFalse(t.is_alive())
        self.assertEqual(events[-1]["type"], "cancelled")
        self.assertFalse(agent.generating(self.cid))
        self.assertEqual(agent.ACTIVE_CONV, {}, "nada fica reservado depois de cancelar")

    def test_error_before_the_answer_releases_the_conversation(self):
        self.ollama.models[:] = []  # nenhuma IA: o servidor confirma a pergunta e só então falha
        events = list(agent.turn({"text": "sem modelo", "conversation_id": self.cid}, "noai-turn-0001"))
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("Nenhuma IA", events[-1]["message"])
        self.assertFalse(agent.generating(self.cid))
        self.assertEqual(agent.ACTIVE_CONV, {})

    def test_closing_the_stream_midway_releases_the_conversation(self):
        gen = agent.turn({"text": "vou fechar no meio", "conversation_id": self.cid}, "closed-turn-0001")
        next(gen)
        self.assertTrue(agent.generating(self.cid))
        gen.close()  # a conexão caiu (a janela fechou): o `finally` solta a reserva
        self.assertFalse(agent.generating(self.cid))

    def test_new_conversation_is_reserved_once_it_exists(self):
        t, events = start({"text": "conversa nova que demora", "temporary": True}, "new-turn-0001")
        self.assertTrue(wait_for(lambda: any(e["type"] == "conversation" for e in events)))
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertTrue(agent.generating(cid))
        self.release()
        t.join(30)
        self.assertFalse(agent.generating(cid))

    def test_voice_call_turns_are_not_serialized_by_the_chat_guard(self):
        # as respostas antecipadas da chamada correm em paralelo na MESMA conversa: o guarda de chat não pode barrá-las
        t, _ = self.hold()
        def fake_turn(*a, **k):
            yield {"type": "done", "message": {}}
        with mock.patch.object(agent, "_turn", fake_turn):
            events = list(agent.turn({"text": "fala", "conversation_id": self.cid, "call": {"effort": "auto"}}, "call-turn-0001"))
        self.assertEqual(events[-1]["type"], "done")
        self.assertTrue(agent.generating(self.cid), "a chamada não soltou a reserva do chat")
        self.release()
        t.join(30)

    def test_conversation_route_reports_generating_and_brief_skips_the_messages(self):
        t, _ = self.hold()
        handler = mock.Mock()
        handler._query.return_value = {"id": self.cid, "brief": "1"}
        brief = api._conversation(handler)
        self.assertEqual(set(brief), {"id", "updated", "temporary", "generating"})
        self.assertTrue(brief["generating"])
        handler._query.return_value = {"id": self.cid}
        full = api._conversation(handler)
        self.assertTrue(full["generating"] and full["messages"])
        self.release()
        t.join(30)
        handler._query.return_value = {"id": self.cid, "brief": "1"}
        self.assertFalse(api._conversation(handler)["generating"])
        self.assertEqual(json.dumps(api._conversation(handler))[:2], '{"')

    def test_temporary_conversation_stays_temporary_and_reports_state(self):
        events = run_turn({"text": "só aqui", "temporary": True})
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertTrue(cid.startswith("tmp-"))
        handler = mock.Mock()
        handler._query.return_value = {"id": cid, "brief": "1"}
        self.assertTrue(api._conversation(handler)["temporary"])
        again = run_turn({"text": "mais uma", "conversation_id": cid})
        self.assertEqual(next(e for e in again if e["type"] == "conversation")["conversation"]["temporary"], True)
        self.assertNotIn(cid, [c["id"] for c in chats.listing() if not c.get("temporary")])

    def test_free_mode_does_not_search_the_vault_and_notes_mode_does(self):
        with mock.patch("lumen.study.agent.search.search", wraps=agent.search.search) as searched:
            free = run_turn({"text": "Como o sono ajuda a memória?", "skip_vault": True})
            self.assertEqual(searched.call_count, 0, "Livre não consulta Notion nem Obsidian")
            done = next(e for e in free if e["type"] == "done")["message"]
            self.assertTrue(done["meta"].get("free_mode"))
            self.assertEqual(done["sources"], [])
            notes = run_turn({"text": "Como o sono ajuda a memória?", "skip_vault": False})
            self.assertGreaterEqual(searched.call_count, 1)
            done = next(e for e in notes if e["type"] == "done")["message"]
            self.assertFalse(done["meta"].get("free_mode"))
            self.assertTrue(done["sources"])

    def test_retry_with_regenerate_does_not_duplicate_the_question(self):
        self.ollama.models[:] = []
        failed = list(agent.turn({"text": "pergunta que falha", "conversation_id": self.cid}, "fail-turn-0001"))
        self.assertEqual(failed[-1]["type"], "error")
        users_before = [m["content"] for m in chats.get(self.cid)["messages"] if m["role"] == "user"]
        self.assertEqual(users_before.count("pergunta que falha"), 1, "a pergunta confirmada fica no histórico")
        self.ollama.models[:] = ["qwen3:8b", "qwen3-embedding:0.6b"]
        again = list(agent.turn({"text": "", "regenerate": True, "conversation_id": self.cid}, "retry-turn-0001"))
        self.assertEqual(again[-1]["type"], "done")
        conv = chats.get(self.cid)
        self.assertEqual([m["content"] for m in conv["messages"] if m["role"] == "user"].count("pergunta que falha"), 1)
        self.assertEqual(conv["messages"][-1]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
