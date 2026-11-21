"""Catálogo, skills editáveis e conjunto de avaliação: sem rede nem credenciais reais."""
import copy
from unittest import mock

import tests  # noqa: F401
from lumen import AppError
from lumen.study import chats, data, db, evaluation, index, memory, registry, search, settings
from tests.test_study_index import Base


class Catalog(Base):
    def test_create_disable_edit_revision_export_and_delete_only_owned_skills(self):
        original = self.note(".claude/skills/original/SKILL.md", "---\nname: original\n---\nLeia minhas notas.")
        created = registry.save_skill("revisar-aula", "Revisar", "<aula>", "Resuma $ARGUMENTS.")
        self.assertIn("revisar-aula", [x["name"] for x in registry.menu()])
        registry.enable(created["id"], False)
        self.assertNotIn("revisar-aula", [x["name"] for x in registry.menu()])
        with self.assertRaises(AppError):
            registry.skill(created["id"])
        changed = registry.save_skill("revisar-aula", "Nova descrição", "<assunto>", "Compare $ARGUMENTS.", created["revision"])
        with self.assertRaises(AppError):
            registry.save_skill("revisar-aula", "", "", "Mudança concorrente", created["revision"])
        registry.enable(created["id"], True)
        self.assertEqual(registry.skill(created["id"])["body"], changed["body"])
        self.assertEqual(data.export()["skills"][0]["revision"], changed["revision"])
        self.assertEqual(data.delete("skills"), 1)
        self.assertTrue(original.exists())
        self.assertEqual(registry._skills("usuario"), [])

    def test_reject_path_escape_reserved_names_collisions_and_frontmatter_injection(self):
        for name in ("../fora", "nul", "COM1", "a/b", "clear", "explicar"):
            with self.subTest(name=name), self.assertRaises(AppError):
                registry.save_skill(name, "", "", "Corpo")
        r = registry.save_skill("valida", "Descrição\n---\nname: outro", "<x>\n---", "Instruções $ARGUMENTS")
        self.assertEqual(r["name"], "valida")
        self.assertIn("Instruções", r["body"])
        with self.assertRaises(AppError):
            registry.enable("cmd:clear", False)

    def test_catalog_roles_include_existing_providers_and_installation_history(self):
        status = {"ollama": {"running": True}, **{p: {"ready": False, "model": ""} for p in settings.KEY_ACCOUNTS}}
        with mock.patch.object(registry.providers, "status", return_value=status), mock.patch.object(registry.llm, "models", return_value=["qwen3.5:4b"]), \
                mock.patch.object(registry.urllib.request, "urlopen", side_effect=OSError), mock.patch.object(settings, "api_key", return_value=""):
            cat = registry.catalog()
        ids = {x["id"] for x in cat["integrations"]}
        self.assertTrue({"openai", "voice", "ollama"} <= ids)
        self.assertNotIn("google", ids)  # o Gemini foi retirado: nenhuma entrada no catálogo
        self.assertTrue({"Imagem", "Vídeo", "Reranker", "Diagramas e 3D"} <= {x["role"] for x in cat["roles"]})
        self.assertGreater(len(cat["installations"]), 5)
        self.assertIn("tokens/s", cat["measurements"])


class Evaluation(Base):
    def case(self, rating=1, correction=""):
        conv = chats.create()
        chats.add_message(conv["id"], "user", "O que o sono faz pela memória?")
        msg = chats.add_message(conv["id"], "assistant", "O sono consolida a memória [S1].", sources=[
            {"sid": "S1", "title": "Sono", "source": "obsidian", "chunks": [{"id": 1, "text": "O sono consolida a memória."}]}])
        memory.feedback(msg["id"], rating, correction)
        return conv, msg

    def provider(self, answer="O sono consolida a memória [S1]."):
        p = mock.Mock()
        p.name, p.model = "ollama", "teste-local"
        p.stream.return_value = [{"type": "text", "text": answer}, {"type": "done", "turn": {"stop": "end"}}]
        p.json.return_value = {"verdict": "atende", "reason": "A resposta preserva o fato da fonte."}
        return p

    def test_feedback_forms_frozen_local_case_and_delete_keeps_messages(self):
        conv, msg = self.case(correction="Explique a consolidação.")
        snapshot = evaluation.export()
        self.assertEqual(len(snapshot["cases"]), 1)
        self.assertEqual(snapshot["cases"][0]["correction"], "Explique a consolidação.")
        result = evaluation.run(snapshot, self.provider())
        self.assertEqual(result["counts"]["atende"], 1)
        self.assertEqual(len(result["results"][0]["prompt_sha256"]), 64)
        self.assertEqual(data.delete("evaluation"), 1)
        self.assertEqual(evaluation.cases(), [])
        self.assertEqual(len(chats.get(conv["id"])["messages"]), 2)
        self.assertEqual(len(snapshot["cases"]), 1)

    def test_invalid_citation_flags_regression_without_judge(self):
        self.case()
        p = self.provider("O sono tem efeitos [S999].")
        result = evaluation.run(evaluation.export(), p)
        self.assertEqual(result["counts"]["regressao"], 1)
        self.assertEqual(result["results"][0]["invalid_citations"], ["S999"])
        p.json.assert_not_called()
        self.assertIsNone(p.stream.call_args.kwargs.get("tools"))
        self.assertFalse(p.stream.call_args.kwargs["allow_external"])

    def test_negative_without_correction_requires_human_and_external_is_rejected(self):
        conv, _ = self.case(-1)
        p = self.provider()
        self.assertEqual(evaluation.run(evaluation.export(), p)["counts"]["revisar"], 1)
        p.json.assert_not_called()
        p.name = "openai"  # qualquer provedor que não seja o local é recusado
        with self.assertRaises(AppError):
            evaluation.run(evaluation.export(), p)
        chats.delete([conv["id"]])
        self.assertEqual(evaluation.cases(), [])

    def test_untrusted_dataset_validation(self):
        self.case()
        dataset = evaluation.export()
        for key, value in (("sources", ["bad"]), ("question", "x" * 60001), ("reference", None), ("mode", []), ("rating", True)):
            candidate = copy.deepcopy(dataset)
            candidate["cases"][0][key] = value
            with self.assertRaises(AppError):
                evaluation.run(candidate, self.provider())

    def test_incomplete_stream_is_regression_and_invalid_judge_never_passes(self):
        self.case()
        p = self.provider()
        p.stream.return_value = [{"type": "text", "text": "Resposta interrompida [S1]."}]
        self.assertEqual(evaluation.run(evaluation.export(), p)["counts"]["regressao"], 1)
        p = self.provider()
        for bad in (None, [], {"verdict": "atende", "reason": ""}):
            p.json.return_value = bad
            self.assertEqual(evaluation.run(evaluation.export(), p)["counts"]["revisar"], 1)


class Router(Base):
    def test_embeddings_never_restore_deleted_or_outdated_memory(self):
        m = memory.create("Estuda matemática.", "profile")
        memory.update(m["id"], content="Estuda psicologia.")
        index.store_vectors("memory", [m["id"]], [[1, 0]], "modelo-teste", ["Estuda matemática."])
        self.assertEqual(db.value("SELECT COUNT(*) FROM vectors"), 0)
        index.store_vectors("memory", [m["id"]], [[1, 0]], "modelo-teste", ["Estuda psicologia."])
        self.assertEqual(db.value("SELECT COUNT(*) FROM vectors"), 1)
        memory.delete(m["id"])
        index.store_vectors("memory", [m["id"]], [[1, 0]], "modelo-teste", ["Estuda psicologia."])
        self.assertEqual(db.value("SELECT COUNT(*) FROM vectors"), 0)

    def test_counts_only_adapt_implicit_choices_and_are_exportable_and_erasable(self):
        conv = chats.create()
        change = {"from": {"mode": "find", "effort": "equilibrado"}, "to": {"mode": "explain", "effort": "rapido"}}
        u = search.heuristic("Sono e memória")
        for _ in range(2):
            search.remember_override(change, conv["id"])
        self.assertEqual(search.adapt(u, "Sono e memória"), u)
        search.remember_override(change, conv["id"])
        adapted = search.adapt(u, "Sono e memória")
        self.assertEqual((adapted["intent"], adapted["effort"]), ("explain", "rapido"))
        self.assertEqual(search.adapt(u, "Encontre materiais em detalhes"), u)
        self.assertEqual(search.adapt(u, "Sono e memória", mode=False, effort=False), u)
        self.assertEqual(len(evaluation.export()["routing"]), 2)
        for _ in range(5):
            search.remember_override({"from": {"effort": "equilibrado"}, "to": {"effort": "maximo"}}, conv["id"])
        self.assertEqual(search.adapt(u, "Sono e memória")["effort"], "equilibrado")
        search.remember_override(change, "")
        self.assertEqual(sum(x["count"] for x in search.routing_counts()), 11)
        data.delete("activity")
        self.assertEqual(search.adapt(u, "Sono e memória"), u)
