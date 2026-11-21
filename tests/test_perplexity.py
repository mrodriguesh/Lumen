"""Perplexity no Lúmen (D185): o comando, o endereço oficial e os limites do painel nativo, conferidos no código.
O fluxo de verdade (janela, site oficial, bloqueios, colar de volta) é a verificação nativa tests/PerplexityCheck.cs."""
import re
import unittest
from pathlib import Path

from lumen.study import registry

ROOT = Path(__file__).resolve().parent.parent
CS = (ROOT / "launcher" / "Lumen.cs").read_text(encoding="utf-8")
JS = (ROOT / "lumen" / "web" / "study.js").read_text(encoding="utf-8")


def site_view():
    start = CS.index("class SiteView : Panel")
    return CS[start:CS.index("\n}\n", start)]


class TestPerplexity(unittest.TestCase):
    def test_command_in_slash_menu(self):
        cmd = {c[0]: c for c in registry.COMMANDS}["perplexity"]
        self.assertEqual(cmd[1], "[pergunta]")
        self.assertIn("só a pergunta vai a ele", cmd[2])

    def test_official_search_url(self):
        # o modelo do https://www.perplexity.ai/opensearch.xml (sem o s=o, que marca buscas da barra do navegador)
        self.assertIn('const PPLX_SEARCH = "https://www.perplexity.ai/search?q=";', JS)
        self.assertIn("PPLX_SEARCH + encodeURIComponent(q)", JS)

    def test_allowed_hosts(self):
        hosts = re.search(r"PerplexityHosts = \{([^}]*)\}", CS).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', hosts), ["www.perplexity.ai", "perplexity.ai", "accounts.google.com", "appleid.apple.com"])
        self.assertIn('u.Scheme == "https" && u.IsDefaultPort', CS)

    def test_panel_never_scripts_or_bridges_the_site(self):
        view = site_view()
        for banned in ("ExecuteScript", "AddScriptToExecuteOnDocumentCreated", "AddHostObjectToScript", "WebMessageReceived",
                       "CookieManager", "IsWebMessageEnabled = true", "UserAgent"):
            self.assertNotIn(banned, view)
        for required in ("IsWebMessageEnabled = false", "AreHostObjectsAllowed = false", "AreDevToolsEnabled = false",
                         "IsPasswordAutosaveEnabled = false", "CoreWebView2PermissionState.Deny", "DownloadStarting", "LaunchingExternalUriScheme"):
            self.assertIn(required, view)

    def test_own_profile(self):
        self.assertIn('"Perplexity", "webview-perplexity", PerplexitySite', CS)

    def test_integrations_tab(self):
        html = (ROOT / "lumen" / "web" / "index.html").read_text(encoding="utf-8")
        for needed in ('id="itab-perplexity"', 'id="integ-perplexity"', 'aria-controls="integ-perplexity"', 'id="px-form"',
                       "Só este texto sai do Lúmen"):
            self.assertIn(needed, html)
        self.assertIn('document.getElementById("px-form")', JS)

    def test_paste_is_labeled_and_never_sent_alone(self):
        self.assertIn('"[Conteúdo do Perplexity colado por mim · não verificado pelo Lúmen]"', JS)
        body = JS[JS.index("async function perplexityPaste()"):JS.index("// --- Contexto: medidor")]
        self.assertNotIn("submit(", body)


if __name__ == "__main__":
    unittest.main()
