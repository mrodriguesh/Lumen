import unittest
from lumen.study import agent, registry, search, settings, tools


class TestFreeMode(unittest.TestCase):
    def test_search_empty_sources(self):
        # Quando sources=[], não deve buscar nada e retornar vazio
        r = search.search("conceito de IA", sources=[])
        self.assertEqual(r["results"], [])
        self.assertEqual(r["sources"], [])

    def test_tools_ctx_skip_vault(self):
        ctx_normal = tools.Ctx(skip_vault=False)
        # Por padrão nos ajustes, notion ou obsidian podem estar ligados
        ctx_free = tools.Ctx(skip_vault=True)
        self.assertFalse(ctx_free.allowed("notion"))
        self.assertFalse(ctx_free.allowed("obsidian"))

    def test_tools_specs_skip_vault(self):
        ctx_free = tools.Ctx(skip_vault=True, allowed_sources=[])
        names = [s["name"] for s in tools.specs(ctx_free)]
        self.assertNotIn("search_knowledge", names)
        self.assertNotIn("read_document", names)
        self.assertNotIn("follow_links", names)
        self.assertNotIn("open_document", names)

    def test_system_prompt_skip_vault(self):
        s = settings.load()
        prompt = agent.system_prompt(s, skip_vault=True)
        self.assertIn("[MODO LIVRE ATIVADO]", prompt)
        self.assertIn("Notion", prompt)
        self.assertIn("Obsidian", prompt)

    def test_call_system_prompt_skip_vault(self):
        s = settings.load()
        call_prompt = agent.call_system_prompt(s, skip_vault=True)
        self.assertIn("[MODO LIVRE ATIVADO]", call_prompt)

    def test_registry_commands_has_livre_and_notas(self):
        cmd_names = [c[0] for c in registry.COMMANDS]
        self.assertIn("livre", cmd_names)
        self.assertIn("notas", cmd_names)


if __name__ == "__main__":
    unittest.main()

