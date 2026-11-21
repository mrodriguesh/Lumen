"""Conversa rápida: modelo rápido como padrão, ajustes próprios e conversa temporária (09/11/2026). Ollama falso, dados isolados.

O que fica provado no SERVIDOR (a tela só pede): o padrão é o modelo rápido do Lúmen resolvido na hora; a escolha própria é validada contra
os modelos locais instalados; nada muda no chat principal nem em models.fast; um ajuste não altera a resposta em andamento; tentar de novo
mantém a configuração; a temporária não deixa conteúdo em banco, memória, registro de atividades nem em nenhum arquivo dos dados."""
import json
import os
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import tests  # noqa: F401
from lumen import AppError
from lumen.study import activity, adult, agent, api, chats, db, memory, providers, settings, tools
from tests.test_quick_chat import start, wait_for
from tests.test_study_core import Core, run_turn

FAST, MAIN, OTHER, ADULT = "qwen3.5:4b", "qwen3:8b", "gemma3:4b", "perfil-adulto-x:1"


def chat_models(ollama):
    """Os modelos das chamadas de chat (resposta e etapas em JSON) que o Ollama falso recebeu."""
    return [b["model"] for p, b in ollama.requests if p == "/api/chat"]


def answer_models(ollama):
    return [b["model"] for p, b in ollama.requests if p == "/api/chat" and not b.get("format")]


def done(events):
    return next(e for e in events if e["type"] == "done")["message"]


def conv_of(events):
    return next(e for e in events if e["type"] == "conversation")["conversation"]


class Quick(Core):
    def setUp(self):
        super().setUp()
        self.ollama.models += [FAST, OTHER]
        settings.save({"models": {"local": MAIN, "fast": FAST}})
        self.ollama.requests.clear()

    def route(self, method="GET", body=None):
        h = mock.Mock()
        h.command = method
        h._json.return_value = body or {}
        return api._quick(h)

    def quick(self, text="Como o sono ajuda a memória?", **extra):
        return run_turn({"text": text, "surface": "quick", **extra})


class DefaultFast(Quick):
    def test_without_a_saved_preference_the_bar_answers_with_the_fast_model_in_every_step(self):
        self.assertEqual(settings.load()["quick"], {"model": "", "new_chat": "normal"})
        events = self.quick(temporary=False)
        meta = done(events)["meta"]
        self.assertEqual((meta["model"], meta["effort"], meta["quick"]), (FAST, "rapido", {"source": "fast", "requested": FAST, "fallback": False}))
        # resposta, entender a pergunta, título e memória: UM modelo só (nenhum outro é carregado do HD)
        self.assertEqual(set(chat_models(self.ollama)), {FAST})
        self.assertIn(("/api/chat", True), {(p, bool(b.get("format"))) for p, b in self.ollama.requests})

    def test_the_main_chat_keeps_its_own_configuration_and_models_fast_is_untouched(self):
        main = run_turn({"text": "Como o sono ajuda a memória?"})
        self.assertEqual(done(main)["meta"]["model"], MAIN)
        self.assertNotIn("quick", done(main)["meta"])
        self.assertEqual(set(answer_models(self.ollama)), {MAIN})
        self.ollama.requests.clear()
        before = settings.load()["models"]
        self.quick()
        after = settings.load()
        self.assertEqual(after["models"], before, "a barra não mexe em models.*")
        self.assertEqual(after["quick"], {"model": "", "new_chat": "normal"})

    def test_the_default_follows_the_fast_model_resolved_now_never_a_fixed_name(self):
        settings.save({"models": {"fast": ""}})  # sem escolha: o Automático (RECOMMENDED vazio → o principal)
        self.assertEqual(self.route()["resolved"]["model"], MAIN)
        settings.save({"models": {"fast": OTHER}})
        self.assertEqual(self.route()["resolved"]["model"], OTHER)
        events = self.quick()
        self.assertEqual(done(events)["meta"]["model"], OTHER)

    def test_effort_is_really_rapido_not_only_a_label(self):
        events = self.quick()
        und = next(e for e in events if e["type"] == "understanding")["understanding"]
        self.assertEqual((und["effort"], und["auto"]["effort"]), ("rapido", False))
        sent = [b for p, b in self.ollama.requests if p == "/api/chat" and not b.get("format")][0]
        self.assertIs(sent["think"], False)
        self.assertEqual(done(events)["meta"]["effort"], "rapido")

    def test_an_explicit_effort_from_the_request_still_wins(self):
        events = self.quick(effort="equilibrado")
        self.assertEqual(done(events)["meta"]["effort"], "equilibrado")
        self.assertEqual(done(events)["meta"]["model"], FAST, "o modelo continua o da barra")

    def test_no_external_call_is_introduced(self):
        hosts = []
        real = urllib.request.urlopen

        def spy(req, *a, **k):
            hosts.append(urllib.request.urlparse(req.full_url if hasattr(req, "full_url") else req).hostname)
            return real(req, *a, **k)
        with mock.patch("urllib.request.urlopen", spy):
            self.quick()
            self.quick(temporary=True)
        self.assertTrue(hosts)
        self.assertEqual(set(hosts), {"127.0.0.1"}, "só o Ollama local")


class OwnSettings(Quick):
    def test_manual_local_choice_is_validated_persisted_and_used(self):
        self.assertEqual(self.route("POST", {"model": OTHER})["settings"], {"model": OTHER, "new_chat": "normal"})
        self.assertEqual(settings.load()["quick"]["model"], OTHER)  # persiste: volta a ler do arquivo
        events = self.quick()
        meta = done(events)["meta"]
        self.assertEqual((meta["model"], meta["quick"]["source"]), (OTHER, "chosen"))
        self.assertEqual(set(chat_models(self.ollama)), {OTHER}, "inclusive entender a pergunta e o título")
        self.assertEqual(settings.load()["models"]["fast"], FAST, "models.fast global intacto")

    def test_invalid_choices_are_refused_by_the_backend(self):
        for bad in ("modelo-que-nao-existe:1b", "../../etc/passwd", "http://example.com/x", "C:\\x\\y.gguf", "qwen3-embedding:0.6b", "anthropic", "a b", 7):
            with self.subTest(bad=bad):
                with self.assertRaises(AppError):
                    self.route("POST", {"model": bad})
        self.assertEqual(settings.load()["quick"]["model"], "")
        with self.assertRaises(AppError):
            self.route("POST", {"new_chat": "publica"})
        self.assertEqual(settings.load()["quick"]["new_chat"], "normal")

    def test_the_adult_dedicated_model_is_not_offered_and_cannot_be_chosen(self):
        self.ollama.models.append(adult.settings.ADULT_RECOMMENDED)
        self.assertNotIn(adult.settings.ADULT_RECOMMENDED, self.route()["choices"])
        with self.assertRaises(AppError):
            self.route("POST", {"model": adult.settings.ADULT_RECOMMENDED})

    def test_choices_are_the_installed_chat_models_only(self):
        view = self.route()
        self.assertEqual(set(view["choices"]), {MAIN, FAST, OTHER})
        self.assertNotIn("qwen3-embedding:0.6b", view["choices"])
        self.assertEqual((view["fast"], view["resolved"]["model"], view["resolved"]["source"]), (FAST, FAST, "fast"))

    def test_the_request_cannot_pick_a_model_the_settings_do_not_hold(self):
        events = self.quick(model="gemma-secreto:7b", provider="anthropic", url="http://evil.test", quick_model="x")
        self.assertEqual(done(events)["meta"]["model"], FAST)
        self.assertEqual(set(chat_models(self.ollama)), {FAST})

    def test_changing_a_setting_does_not_touch_the_turn_in_progress_and_applies_to_the_next(self):
        self.ollama.delay, self.ollama.hold_after = 0.01, 2
        self.ollama.gate = threading.Event()
        t, events = start({"text": "Pergunta que fica esperando", "surface": "quick"}, "quick-held-0001")
        self.assertTrue(wait_for(lambda: any(e["type"] == "delta" for e in events)))
        cid = conv_of(events)["id"]
        self.route("POST", {"model": OTHER, "new_chat": "temporary"})  # no meio da resposta
        self.ollama.gate.set()
        t.join(30)
        first = done(events)["meta"]
        self.assertEqual((first["model"], first["quick"]["source"]), (FAST, "fast"), "a resposta em andamento seguiu como estava")
        self.assertEqual(events[-1]["type"], "done")
        self.assertFalse(chats.is_temp(cid), "e a conversa que já existia não virou temporária")
        self.ollama.delay, self.ollama.gate = 0.0, None
        nxt = self.quick(conversation_id=cid, text="E depois?")
        self.assertEqual(done(nxt)["meta"]["model"], OTHER, "da próxima resposta em diante vale o novo")

    def test_retry_keeps_the_configuration_and_never_duplicates_the_question(self):
        self.route("POST", {"model": OTHER})
        self.ollama.models.remove(OTHER)
        self.ollama.models.remove(FAST)
        self.ollama.models.remove(MAIN)  # nenhum modelo local de chat: erro claro, pergunta confirmada
        failed = self.quick("pergunta que falha")
        self.assertEqual(failed[-1]["type"], "error")
        self.assertIn(OTHER, failed[-1]["message"])
        self.assertIn("não está instalado", failed[-1]["message"])
        cid = conv_of(failed)["id"]
        self.ollama.models += [OTHER, FAST, MAIN]
        again = list(agent.turn({"text": "", "regenerate": True, "conversation_id": cid, "surface": "quick"}, "retry-quick-0001"))
        self.assertEqual(done(again)["meta"]["model"], OTHER, "tentar de novo usa o ajuste vigente")
        users = [m["content"] for m in chats.get(cid)["messages"] if m["role"] == "user"]
        self.assertEqual(users, ["pergunta que falha"])

    def test_missing_model_recovers_locally_and_says_which_model_answered(self):
        self.route("POST", {"model": OTHER})
        self.ollama.models.remove(OTHER)
        events = self.quick()
        fallback = next(e for e in events if e.get("stage") == "fallback")
        self.assertIn(FAST, fallback["detail"])
        self.assertIn(OTHER, fallback["detail"])
        meta = done(events)["meta"]
        self.assertEqual((meta["model"], meta["quick"]["fallback"], meta["quick"]["requested"]), (FAST, True, OTHER))
        self.assertEqual(set(chat_models(self.ollama)), {FAST})
        view = self.route()
        self.assertEqual((view["resolved"]["model"], view["resolved"]["fallback"]), (FAST, True))
        self.assertEqual(settings.load()["quick"]["model"], OTHER, "o ajuste não é reescrito em silêncio")

    def test_missing_fast_model_falls_back_to_the_main_local_model(self):
        settings.save({"models": {"fast": "rapido-sumiu:1b"}})
        events = self.quick()
        self.assertEqual(done(events)["meta"]["model"], MAIN)
        self.assertTrue(done(events)["meta"]["quick"]["fallback"])

    def test_ollama_models_gone_is_a_clear_error_and_nothing_is_downloaded(self):
        self.ollama.models[:] = []
        events = self.quick()
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("/api/pull", [p for p, _ in self.ollama.requests])
        self.assertIn("user", [e["type"] for e in events], "a pergunta foi confirmada antes de falhar (Tentar de novo)")

    def test_reset_restores_only_these_settings(self):
        events = self.quick()
        cid = conv_of(events)["id"]
        mems = len(memory.listing())
        settings.save({"models": {"temperature": 0.7}})
        self.route("POST", {"model": OTHER, "new_chat": "temporary"})
        view = self.route("POST", {"reset": True})
        self.assertEqual(view["settings"], {"model": "", "new_chat": "normal"})
        self.assertEqual(settings.load()["models"]["temperature"], 0.7)
        self.assertEqual((settings.load()["models"]["fast"], settings.load()["models"]["local"]), (FAST, MAIN))
        self.assertEqual(chats.get(cid)["messages"][0]["role"], "user")
        self.assertEqual(len(memory.listing()), mems)
        self.assertEqual(self.ollama.models.count(OTHER), 1, "nenhum modelo foi apagado nem baixado")

    def test_old_settings_files_migrate_by_defaults_and_bad_values_fall_back(self):
        f = db.HOME / "settings.json"
        f.write_text(json.dumps({"models": {"temperature": 0.5}}), "utf-8")  # arquivo de antes do ajuste
        self.assertEqual(settings.load()["quick"], {"model": "", "new_chat": "normal"})
        self.assertEqual(settings.load()["models"]["temperature"], 0.5)
        f.write_text(json.dumps({"quick": {"model": "http://x/y z", "new_chat": "segredo"}}), "utf-8")  # editado à mão
        self.assertEqual(settings.load()["quick"], {"model": "", "new_chat": "normal"})

    def test_adult_profile_keeps_precedence_and_its_content_never_goes_to_the_quick_model(self):
        self.ollama.models.append(ADULT)
        settings.save({"adult": {"enabled": True, "mode": "adult", "model": ADULT}})
        self.route("POST", {"model": OTHER})
        events = self.quick("escreva uma cena", profile="adult")
        self.assertEqual(done(events)["meta"]["model"], ADULT)
        self.assertNotIn("quick", done(events)["meta"])
        self.assertEqual(set(answer_models(self.ollama)), {ADULT})
        self.assertNotIn(OTHER, chat_models(self.ollama), "nada do perfil adulto passou pelo modelo da barra")


class Temporary(Quick):
    CANARY = "CANARIO-TEMPORARIO-7f3a91"

    def data_files(self):
        base = Path(os.environ["LUMEN_DATA"]).resolve()
        roots = [base, db.HOME.resolve()]
        seen = set()
        for root in roots:
            for p in root.rglob("*"):
                if p.is_file() and p not in seen and "sem-voicestudio" not in p.parts:
                    seen.add(p)
                    yield p

    def leaks(self, marker):
        db.checkpoint()
        found = []
        for p in self.data_files():
            try:
                if marker.encode() in p.read_bytes():
                    found.append(p.name)
            except OSError:
                pass
        return found

    def test_temporary_leaves_nothing_in_the_database_memories_activity_or_files(self):
        self.ollama.answer = f"Resposta com {self.CANARY}-ia"
        before_mem = len(memory.listing())
        events = self.quick(f"Pergunta {self.CANARY}-pergunta sobre memória", temporary=True)
        cid = conv_of(events)["id"]
        self.assertTrue(cid.startswith("tmp-"))
        self.assertTrue(conv_of(events)["temporary"])
        for table in ("conversations", "messages", "messages_fts"):
            self.assertEqual(db.value(f"SELECT COUNT(*) FROM {table}"), 0, table)
        self.assertEqual(len(memory.listing()), before_mem, "não cria memórias")
        self.assertFalse([a for a in activity.recent() if self.CANARY in json.dumps(a, ensure_ascii=False)], "o registro de atividades não guarda o conteúdo")
        self.assertEqual(self.leaks(self.CANARY), [], "nenhum arquivo dos dados contém o texto temporário")
        self.assertEqual(len(chats.get(cid)["messages"]), 2, "mas a conversa existe na memória do processo")

    def test_the_leak_scanner_is_not_blind_a_normal_conversation_is_found(self):
        self.quick(f"Pergunta {self.CANARY}-normal sobre memória", temporary=False)
        self.assertTrue(self.leaks(self.CANARY + "-normal"), "o controle: o texto normal APARECE nos dados (o banco), então o exame enxerga")

    def test_temporary_does_not_read_personal_memories_and_normal_still_does(self):
        run_turn({"text": "Prefiro exemplos práticos sempre. Como o sono ajuda a memória?"})  # cria a memória ativa
        self.assertTrue(memory.listing())
        temp = self.quick("E o hipocampo?", temporary=True)
        self.assertNotIn("memories", [e["type"] for e in temp])
        system = [b for p, b in self.ollama.requests if p == "/api/chat" and not b.get("format")][-1]["messages"][0]["content"]
        self.assertNotIn("Prefere explicações com exemplos práticos.", system)
        normal = self.quick("E o hipocampo?", temporary=False)
        self.assertIn("memories", [e["type"] for e in normal])

    def test_tool_errors_in_a_temporary_conversation_do_not_log_what_was_typed(self):
        ctx = tools.Ctx("tmp-abc123")
        text, failed = tools.run(ctx, "read_document", {"id": f"{self.CANARY}-ferramenta"})
        self.assertTrue(failed)
        rows = activity.recent(10, "ferramenta")
        self.assertTrue(rows)
        self.assertFalse([r for r in rows if self.CANARY in json.dumps(r, ensure_ascii=False)])
        normal = tools.Ctx("abc123")
        tools.run(normal, "read_document", {"id": "S404"})
        self.assertTrue([r for r in activity.recent(10, "ferramenta") if "S404" in r["target"]], "fora da temporária o registro continua igual")

    def test_new_chat_setting_makes_the_bars_new_conversations_temporary_only_there(self):
        self.route("POST", {"new_chat": "temporary"})
        bar = conv_of(self.quick())
        self.assertTrue(bar["temporary"] and bar["id"].startswith("tmp-"))
        normal = conv_of(self.quick(temporary=False))
        self.assertFalse(normal["temporary"], "uma escolha explícita (Nova conversa normal) vale mais que o ajuste")
        brain = conv_of(run_turn({"text": "No Cérebro"}))
        self.assertFalse(brain["temporary"], "o Cérebro (sem surface) não segue o ajuste da barra")
        self.route("POST", {"new_chat": "normal"})
        self.assertFalse(conv_of(self.quick())["temporary"])

    def test_history_off_still_makes_every_new_conversation_temporary(self):
        settings.save({"memory": {"history": False}})
        self.assertTrue(conv_of(self.quick(temporary=False))["temporary"])

    def test_retry_and_follow_ups_keep_the_conversation_temporary_with_the_same_id(self):
        events = self.quick("Primeira temporária", temporary=True)
        cid = conv_of(events)["id"]
        self.route("POST", {"model": OTHER, "new_chat": "normal"})  # mudar ajuste não torna a conversa normal
        more = self.quick("Segunda", conversation_id=cid)
        self.assertEqual(conv_of(more), {**conv_of(events), "title": conv_of(more)["title"]})
        self.assertTrue(conv_of(more)["temporary"])
        again = list(agent.turn({"text": "", "regenerate": True, "conversation_id": cid, "surface": "quick"}, "retry-temp-0001"))
        self.assertEqual(done(again)["meta"]["model"], OTHER)
        msgs = chats.get(cid)["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user", "assistant"], "sem pergunta duplicada")
        self.assertEqual(db.value("SELECT COUNT(*) FROM conversations"), 0)

    def test_the_brain_opens_the_same_temporary_conversation_with_its_temporary_nature(self):
        events = self.quick("Continuar no Cérebro", temporary=True)
        cid = conv_of(events)["id"]
        h = mock.Mock()
        h._query.return_value = {"id": cid}
        full = api._conversation(h)
        self.assertEqual((full["id"], full["temporary"]), (cid, True))
        self.assertEqual([m["role"] for m in full["messages"]], ["user", "assistant"])
        listed = [c for c in chats.listing() if c["id"] == cid]
        self.assertTrue(listed and listed[0]["temporary"])

    def test_temporary_conversation_can_still_consult_notes_when_asked(self):
        events = self.quick("Como o sono ajuda a memória?", temporary=True, skip_vault=False)
        self.assertTrue(done(events)["sources"], "Livre/Notas é outra dimensão: Notas funciona na temporária")
        free = self.quick("Como o sono ajuda a memória?", temporary=True, skip_vault=True)
        self.assertEqual(done(free)["sources"], [])
        self.assertTrue(done(free)["meta"].get("free_mode"))

    def test_normal_and_temporary_conversations_do_not_mix(self):
        n = conv_of(self.quick("Texto da normal", temporary=False))["id"]
        t = conv_of(self.quick("Texto da temporária", temporary=True))["id"]
        self.assertNotEqual(n, t)
        self.assertEqual([m["content"] for m in chats.get(n)["messages"] if m["role"] == "user"], ["Texto da normal"])
        self.assertEqual([m["content"] for m in chats.get(t)["messages"] if m["role"] == "user"], ["Texto da temporária"])
        self.assertEqual(db.value("SELECT COUNT(*) FROM conversations"), 1)
        self.assertEqual(db.value("SELECT COUNT(*) FROM messages WHERE content LIKE '%temporária%'"), 0)

    def test_temporary_expires_by_the_existing_policy(self):
        cid = conv_of(self.quick(temporary=True))["id"]
        with chats._temp_lock:
            chats.TEMP[cid]["touched"] -= (chats.TEMP_HOURS + 1) * 3600
        chats._expire()
        with self.assertRaises(AppError):
            chats.get(cid)


if __name__ == "__main__":
    unittest.main()
