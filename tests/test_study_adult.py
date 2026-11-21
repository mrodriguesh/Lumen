"""Perfil adulto (D92): configuração própria, precedência da escolha, roteamento automático e integração com o orquestrador.
Ollama falso e dados isolados; o classificador real é medido à parte (bench/adult_route_eval.py)."""
import threading
import time
from unittest import mock

import tests  # noqa: F401
from lumen import AppError
from lumen.study import adult, agent, chats, db, memory, providers, settings
from tests.fake_ollama import FakeOllama
from tests.test_study_core import Core, run_turn
from tests.test_study_index import Base

ADULT = "perfil-adulto-x:1"
CLASSIFIER = "decide, antes de qualquer resposta"  # trecho do prompt do classificador (chave dos roteiros do Ollama falso)


def verdict(perfil="adulto", certeza="alta", motivo="conteudo_adulto"):
    return {"motivo": motivo, "perfil": perfil, "certeza": certeza}


def chat_models(ollama):
    return [b["model"] for p, b in ollama.requests if p == "/api/chat"]


class AdultSettings(Base):
    def test_defaults_are_off_and_independent_from_the_main_model(self):
        s = settings.load()
        self.assertEqual(s["adult"], {"enabled": False, "mode": "auto", "model": "", "instructions": "", "temperature": 0.8})
        with mock.patch.object(settings.llm, "models", return_value=["qwen3:8b"]):
            self.assertEqual(settings.adult_model(s), "")  # recomendado não instalado: nunca cai no principal
        with mock.patch.object(settings.llm, "models", return_value=["qwen3:8b", settings.ADULT_RECOMMENDED]):
            self.assertEqual(settings.adult_model(s), settings.ADULT_RECOMMENDED)  # Automático: o recomendado, se instalado
        with mock.patch.object(settings.llm, "models", return_value=["qwen3:8b", ADULT]):
            settings.save({"adult": {"model": ADULT}})
            self.assertEqual(settings.adult_model(settings.load()), ADULT)  # a escolha do estudante vence
            settings.save({"adult": {"model": ""}})
        before = settings.load()["models"]
        settings.save({"adult": {"enabled": True, "model": ADULT, "temperature": 1.1, "instructions": "Seja direto."}})
        after = settings.load()
        self.assertEqual(after["models"], before)  # o principal não mudou
        self.assertEqual((after["adult"]["enabled"], after["adult"]["model"], after["adult"]["temperature"]), (True, ADULT, 1.1))
        self.assertEqual(settings.public()["resolved"]["adult"], ADULT)

    def test_validation_and_old_files(self):
        for bad in ({"mode": "tudo"}, {"enabled": "sim"}, {"temperature": "alta"}, {"model": "../x y"}):
            with self.assertRaises(AppError, msg=str(bad)):
                settings.save({"adult": bad})
        self.assertEqual(settings.save({"adult": {"temperature": 9}})["adult"]["temperature"], 1.5)  # dentro do intervalo
        self.assertEqual(settings.save({"adult": {"temperature": -1}})["adult"]["temperature"], 0.0)
        settings.save({"adult": {"nova_chave": 1, "instructions": "x" * 5000}})
        s = settings.load()
        self.assertNotIn("nova_chave", s["adult"])
        self.assertEqual(len(s["adult"]["instructions"]), 2000)
        # um arquivo de antes do perfil adulto (sem a seção) carrega com os padrões, sem perder o resto
        raw = settings._file()
        raw.write_text('{"models": {"temperature": 0.5}}', "utf-8")
        old = settings.load()
        self.assertEqual((old["models"]["temperature"], old["adult"]["enabled"]), (0.5, False))

    def test_survives_a_restart(self):
        settings.save({"adult": {"enabled": True, "mode": "adult", "model": ADULT}})
        again = settings.load()  # nova leitura do arquivo, como depois de reabrir
        self.assertEqual((again["adult"]["enabled"], again["adult"]["mode"], again["adult"]["model"]), (True, "adult", ADULT))

    def test_pinned_provider_has_its_own_model_and_temperature(self):
        settings.save({"adult": {"enabled": True, "model": ADULT, "temperature": 1.2}, "models": {"temperature": 0.2}})
        s = settings.load()
        main, dedicated = providers.Ollama(s), providers.Ollama(s, adult=True)
        self.assertEqual((main.temperature, dedicated.temperature), (0.2, 1.2))
        self.assertEqual(dedicated.model, ADULT)
        self.assertNotEqual(main.model, ADULT)

    def test_status_lists_only_chat_models_and_reports_the_adult_model(self):
        fake = FakeOllama(models=("qwen3:8b", "qwen3-embedding:0.6b", ADULT))
        try:
            settings.save({"adult": {"enabled": True, "model": ADULT}})
            st = providers.status(settings.load())
            self.assertNotIn("qwen3-embedding:0.6b", st["ollama"]["models"])
            self.assertTrue(st["ollama"]["embed_installed"])
            self.assertEqual((st["adult"]["model"], st["adult"]["installed"], st["adult"]["enabled"]), (ADULT, True, True))
        finally:
            fake.close()


class Resolve(Base):
    """A precedência e o automático, sem rede: o classificador é um dublê."""

    def cfg(self, **kw):
        settings.save({"adult": {"enabled": True, "model": ADULT, **kw}})
        return settings.load()

    def test_manual_choice_wins_over_everything(self):
        s = self.cfg(mode="adult")
        with mock.patch.object(adult, "classify", side_effect=AssertionError("não deve classificar")):
            self.assertEqual(adult.resolve(s, "oi", manual="main")["use"], "main")  # principal manual vence o modo "adulto"
            d = adult.resolve(self.cfg(mode="main"), "oi", manual="adult")
            self.assertEqual((d["use"], d["by"], d["model"]), ("adult", "manual", ADULT))

    def test_disabled_is_a_master_switch(self):
        s = settings.load()  # desligado por padrão
        with mock.patch.object(adult, "classify", side_effect=AssertionError("não deve classificar")):
            self.assertEqual(adult.resolve(s, "escreve uma cena erótica")["by"], "disabled")
            with self.assertRaises(AppError):  # nem a escolha manual liga o que está desligado
                adult.resolve(s, "oi", manual="adult")

    def test_fixed_modes_do_not_classify(self):
        with mock.patch.object(adult, "classify", side_effect=AssertionError("não deve classificar")):
            self.assertEqual(adult.resolve(self.cfg(mode="main"), "cena erótica")["use"], "main")
            self.assertEqual(adult.resolve(self.cfg(mode="adult"), "explique recursão")["use"], "adult")

    def test_auto_without_any_signal_never_calls_the_classifier(self):
        s = self.cfg()
        with mock.patch.object(adult, "classify", side_effect=AssertionError("não deve classificar")):
            for text in ("Explique recursão em Python.", "continua", "Resuma o capítulo 3 da apostila."):
                self.assertEqual(adult.resolve(s, text, previous="main")["use"], "main")

    def test_auto_follows_a_confident_verdict_and_keeps_conversations_coherent(self):
        s = self.cfg()
        with mock.patch.object(adult, "classify", return_value=verdict()) as c:
            d = adult.resolve(s, "escreve uma cena sensual entre adultos")
            self.assertEqual((d["use"], d["by"]), ("adult", "auto"))
            self.assertEqual(c.call_count, 1)
            d = adult.resolve(s, "mais intenso", previous="adult")  # continuação curta: o classificador roda mesmo sem sinal
            self.assertEqual((d["use"], d["by"]), ("adult", "continuation"))
        with mock.patch.object(adult, "classify", return_value=verdict("principal", motivo="assunto_comum")):
            self.assertEqual(adult.resolve(s, "agora me explica recursão", previous="adult")["use"], "main")  # volta ao principal
        with mock.patch.object(adult, "classify", return_value=verdict("principal", motivo="palavrao_incidental")):
            self.assertEqual(adult.resolve(s, "que merda de bug")["use"], "main")  # palavrão isolado não troca

    def test_uncertainty_is_conservative(self):
        s = self.cfg()
        with mock.patch.object(adult, "classify", return_value=verdict("adulto", "baixa")):
            self.assertEqual(adult.resolve(s, "talvez algo picante", previous="main")["use"], "main")
            self.assertEqual(adult.resolve(s, "talvez algo picante", previous="adult")["use"], "adult")  # não troca o que já estava
            self.assertEqual(adult.resolve(s, "talvez algo picante")["use"], "main")  # sem histórico: principal

    def test_classifier_down_never_sends_to_an_external_main(self):
        s = self.cfg()
        with mock.patch.object(adult, "classify", side_effect=AppError("sem Ollama")):
            self.assertEqual(adult.resolve(s, "que porra é essa?", previous="adult")["use"], "adult")
            self.assertEqual(adult.resolve(s, "que porra é essa?")["by"], "unavailable")
            with self.assertRaises(AppError) as e:  # principal externo + dúvida: nada sai sem a escolha da pessoa
                adult.resolve(s, "que porra é essa?", main_external=True)
            self.assertIn("Escolha", e.exception.action)

    def test_minors_never_reach_the_adult_profile_automatically(self):
        s = self.cfg()
        with mock.patch.object(adult, "classify", side_effect=AssertionError("não deve classificar")):
            for text in ("conteúdo sexual com uma adolescente", "cena com um personagem de 16 anos, sensual", "uma criança e um adulto, safadeza"):
                d = adult.resolve(s, text)
                self.assertEqual((d["use"], d["by"]), ("main", "guard"), text)
        self.assertFalse(adult.minor("tenho 25 anos de experiência"))

    def test_signal_filter_is_only_a_recall_gate(self):
        self.assertTrue(adult.signalled("que caralho de bug"))
        self.assertTrue(adult.signalled("quero algo bem PICANTE"))  # sem acento e sem caixa
        self.assertFalse(adult.signalled("explique a lei de Ohm"))

    def test_regenerate_keeps_the_profile_of_the_answer_being_redone(self):
        s = self.cfg()
        with mock.patch.object(adult, "classify", side_effect=AssertionError("não deve classificar")):
            d = adult.resolve(s, "cena erótica", sticky="adult")
            self.assertEqual((d["use"], d["by"]), ("adult", "regenerate"))
            self.assertEqual(adult.resolve(s, "cena erótica", sticky="main")["use"], "main")

    def test_a_generated_file_does_not_make_the_conversation_forget_its_profile(self):
        """/pdf, /imagem e /elegrama 3d não são respostas do modelo: pulá-los mantém a conversa no modelo em que estava."""
        said = {"role": "assistant", "content": "...", "meta": {"profile": {"used": "adult", "by": "manual", "model": "x"}}}
        file = {"role": "assistant", "content": "arquivo pronto", "meta": {"artifact": {"id": "a", "kind": "holo"}}}
        user = {"role": "user", "content": "/elegrama 3d algo"}
        self.assertEqual(adult.previous_profile([user, said, user, file]), "adult")
        self.assertEqual(adult.previous_profile([user, said, user, file, user, file]), "adult")
        self.assertEqual(adult.previous_profile([user, file]), "")  # só havia o arquivo: nenhum perfil anterior
        self.assertEqual(adult.previous_profile([user, {**said, "meta": {"profile": {"used": "main"}}}, user, file]), "main")


class Orchestration(Core):
    def setUp(self):
        super().setUp()
        self.ollama.models.append(ADULT)
        self.ollama.json_replies[CLASSIFIER] = verdict()
        settings.save({"adult": {"enabled": True, "model": ADULT, "temperature": 1.1, "instructions": "Escreva em tom de conversa."}})

    def chat_bodies(self, final=True):
        return [b for p, b in self.ollama.requests if p == "/api/chat" and not (final and b.get("format"))]

    def test_manual_adult_uses_the_dedicated_model_in_every_step_and_leaves_the_main_one_alone(self):
        main = settings.local_model()
        events = run_turn({"text": "Como o sono ajuda a memória?", "profile": "adult"})
        prof = next(e for e in events if e["type"] == "profile")
        self.assertEqual((prof["used"], prof["by"], prof["model"]), ("adult", "manual", ADULT))
        self.assertEqual(set(chat_models(self.ollama)), {ADULT})  # entender, responder e o resto: só o dedicado
        self.assertNotIn(main, chat_models(self.ollama))
        body = self.chat_bodies()[-1]
        self.assertEqual(body["options"]["temperature"], 1.1)  # a temperatura própria, não a do principal
        self.assertIn("Perfil adulto", body["messages"][0]["content"])
        self.assertIn("Escreva em tom de conversa.", body["messages"][0]["content"])
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertEqual(done["meta"]["profile"], {"used": "adult", "by": "manual", "model": ADULT})
        self.assertEqual(done["meta"]["model"], ADULT)
        self.assertEqual(settings.local_model(), main)  # nada global mudou
        # a mesma conversa, escolhendo o principal: volta ao principal e sem o trecho do perfil
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.ollama.requests.clear()
        run_turn({"conversation_id": cid, "text": "E o hipocampo?", "profile": "main"})
        self.assertEqual(set(chat_models(self.ollama)), {main})
        self.assertNotIn("Perfil adulto", self.chat_bodies()[-1]["messages"][0]["content"])

    def test_no_title_or_automatic_memory_comes_out_of_an_adult_answer(self):
        events = run_turn({"text": "Como o sono ajuda a memória? Prefiro exemplos práticos.", "profile": "adult"})
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertEqual(chats.get(cid)["title"], adult.PRIVATE_TITLE)
        self.assertEqual(memory.listing(), [])
        self.assertFalse([1 for p, b in self.ollama.requests if b.get("format") and "título curto" in b["messages"][0]["content"]])

    def test_every_effort_level_keeps_the_dedicated_model(self):
        for effort in ("rapido", "equilibrado", "profundo", "maximo"):
            self.ollama.requests.clear()
            run_turn({"text": "Como o sono ajuda a memória?", "profile": "adult", "effort": effort})
            self.assertEqual(set(chat_models(self.ollama)), {ADULT}, effort)

    def test_auto_routes_by_intent_and_comes_back_to_the_main_model(self):
        main = settings.local_model()
        self.ollama.json_replies[CLASSIFIER] = verdict()
        events = run_turn({"text": "escreve uma cena sensual entre dois adultos"})
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertEqual(next(e for e in events if e["type"] == "profile")["by"], "auto")
        self.assertEqual(self.chat_bodies()[-1]["model"], ADULT)
        # continuação curta, sem nenhum sinal: o classificador ainda decide, com a resposta anterior no pedido
        self.ollama.requests.clear()
        events = run_turn({"conversation_id": cid, "text": "mais intenso"})
        self.assertEqual(next(e for e in events if e["type"] == "profile")["by"], "continuation")
        asked = [b for p, b in self.ollama.requests if b.get("format") and CLASSIFIER in b["messages"][0]["content"]][0]
        self.assertIn("<anterior>perfil adulto</anterior>", asked["messages"][-1]["content"])
        # mudança clara de assunto
        self.ollama.json_replies[CLASSIFIER] = verdict("principal", motivo="assunto_comum")
        self.ollama.requests.clear()
        run_turn({"conversation_id": cid, "text": "agora me explica recursão"})
        self.assertEqual(self.chat_bodies()[-1]["model"], main)

    def test_an_ordinary_message_costs_no_classifier_call_and_document_text_never_decides(self):
        self.note("Notas/Safadeza.md", "# Safadeza\nPorra, caralho, sexo explícito e palavrão pesado, tudo em nota de estudo sobre sociolinguística.")
        from lumen.study import index
        index.sync("obsidian")
        run_turn({"text": "O que dizem minhas notas sobre sociolinguística?"})
        self.assertFalse([1 for p, b in self.ollama.requests if b.get("format") and CLASSIFIER in b["messages"][0]["content"]])
        self.assertEqual(set(chat_models(self.ollama)), {settings.local_model()})

    def test_regenerate_does_not_swap_the_model_silently(self):
        events = run_turn({"text": "como o sono ajuda a memória?", "profile": "adult"})
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.ollama.json_replies[CLASSIFIER] = verdict("principal", motivo="assunto_comum")
        self.ollama.requests.clear()
        events = run_turn({"conversation_id": cid, "regenerate": True})
        prof = next(e for e in events if e["type"] == "profile")
        self.assertEqual((prof["used"], prof["by"]), ("adult", "regenerate"))
        self.assertEqual(set(chat_models(self.ollama)), {ADULT})

    def test_missing_dedicated_model_is_reported_and_nothing_is_answered_elsewhere(self):
        self.ollama.models.remove(ADULT)
        events = run_turn({"text": "oi", "profile": "adult"})
        err = next(e for e in events if e["type"] == "error")
        self.assertIn("perfil adulto", err["message"])
        self.assertIn("Configurações → Perfil adulto", err["action"])
        self.assertNotIn("done", [e["type"] for e in events])
        self.assertEqual(chat_models(self.ollama), [])  # nenhuma resposta saiu por outro modelo

    def test_cancel_during_classification_leaves_no_answer(self):
        from lumen import Cancelled
        with mock.patch.object(adult, "classify", side_effect=Cancelled()):
            events = run_turn({"text": "escreve uma cena sensual"})
        self.assertEqual(events[-1]["type"], "cancelled")
        self.assertEqual(chat_models(self.ollama), [])

    def test_two_conversations_at_once_do_not_contaminate_each_other(self):
        main, out = settings.local_model(), {}

        def go(name, payload):
            out[name] = run_turn(payload)
        a = threading.Thread(target=go, args=("a", {"text": "Como o sono ajuda a memória?", "profile": "adult"}))
        b = threading.Thread(target=go, args=("b", {"text": "O que é condicionamento operante?", "profile": "main"}))
        a.start(); b.start(); a.join(60); b.join(60)
        for name, want in (("a", ADULT), ("b", main)):
            done = next(e for e in out[name] if e["type"] == "done")["message"]
            self.assertEqual(done["meta"]["model"], want, name)
            self.assertEqual(done["meta"]["profile"]["used"], "adult" if name == "a" else "main", name)

    def test_disabled_profile_leaves_the_flow_untouched(self):
        settings.save({"adult": {"enabled": False}})
        events = run_turn({"text": "Como o sono ajuda a memória?"})
        self.assertNotIn("profile", [e["type"] for e in events])
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertNotIn("profile", done["meta"])
        with self.assertRaises(AppError):
            adult.resolve(settings.load(), "oi", manual="adult")
        events = run_turn({"text": "oi", "profile": "adult"})
        self.assertIn("desligado", next(e for e in events if e["type"] == "error")["message"])

    def test_voice_turn_routes_on_the_final_transcript_like_text(self):
        events = run_turn({"text": "escreve uma cena sensual entre dois adultos", "call": {"length": "short", "effort": "equilibrado"}})
        prof = next(e for e in events if e["type"] == "profile")
        self.assertEqual((prof["used"], prof["by"]), ("adult", "auto"))
        body = self.chat_bodies()[-1]
        self.assertEqual(body["model"], ADULT)
        self.assertIn("Perfil adulto", body["messages"][0]["content"])  # o prompt da chamada também leva o trecho do perfil
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertTrue(done["meta"]["call"])
        self.assertEqual(done["meta"]["profile"]["model"], ADULT)
        cid = next(e for e in events if e["type"] == "conversation")["conversation"]["id"]
        self.assertEqual(chats.get(cid)["title"], adult.PRIVATE_TITLE)

    def test_a_broken_classifier_never_blocks_a_local_answer(self):
        self.ollama.json_replies[CLASSIFIER] = {}  # resposta fora do formato
        events = run_turn({"text": "que porra é essa de recursão?"})
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertEqual((done["meta"]["profile"]["used"], done["meta"]["profile"]["by"]), ("main", "unavailable"))
        self.assertEqual(done["meta"]["model"], settings.local_model())

    def test_catalog_shows_the_dedicated_model_with_its_availability(self):
        from lumen.study import registry
        roles = {r["role"]: r for r in registry.model_roles(settings.load())}
        self.assertEqual((roles["Perfil adulto"]["model"], roles["Perfil adulto"]["installed"], roles["Perfil adulto"]["section"]), (ADULT, True, "adult"))
        settings.save({"adult": {"enabled": False}})
        roles = {r["role"]: r for r in registry.model_roles(settings.load())}
        self.assertEqual((roles["Perfil adulto"]["model"], roles["Perfil adulto"]["installed"]), ("Desligado", None))
