"""Retirada completa do Gemini (09/11/2026): o Lúmen usa só a IA local. Os testes provam que (1) ajustes antigos migram para o
local, uma vez e sem perder preferências; (2) nenhum payload, rota, conversa antiga ou ajuste forjado reativa uma chamada externa
(nenhuma requisição sai do 127.0.0.1); (3) a chave do Gemini é a única credencial apagada do cofre (simulado, em memória);
(4) o Google Drive da Proteção, as conversas e os materiais antigos seguem intactos; (5) a interface e o código não oferecem
nem implementam o Gemini; (6) a IA local continua respondendo, e a falta dela é explicada. Nenhuma chamada real."""
import copy
import json
import re
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import keyring

import tests  # noqa: F401  (isola LUMEN_DATA e instala o cofre em memória)
from lumen import AppError, gdrive, llm, server, store
from lumen.study import (activity, api, artifacts, chats, db, policy, providers, registry, settings, tools)
from tests.test_study_core import Core, run_turn
from tests.test_study_index import Base

ROOT = Path(__file__).resolve().parent.parent
FAKE_SECRET = "AQ.chave-falsa-so-para-teste-0123456789"  # formato novo do Google; nunca uma chave real

# Um settings.json como o Lúmen oficial anterior o deixava: Gemini como principal, imagem do Gemini, envio externo ligado e a
# seção de aceites; com preferências pessoais que a migração precisa preservar.
OLD = {
    "gemini": {"accept_quotas": True, "accept_data_use": True, "key_epoch": 3, "confirmed_epoch": 3, "confirmed_at": "2026-11-09T10:00:00",
               "locked_epoch": -1, "locked_reason": "", "migrated": "2026-11-09"},
    "models": {"provider": "google", "fallback": "google", "local": "qwen3:8b", "fast": "", "max": "", "anthropic": "", "openai": "",
               "google": "gemini-3.8-flash", "image_provider": "google", "image_openai": "", "image_google": "gemini-2.5-flash-image",
               "video_provider": "google", "video_model": "gemini-omni-1.1-flash", "embed": "qwen3-embedding:0.6b",
               "temperature": 0.5, "context_chars": 20000, "stream": False},
    "privacy": {"external": True, "open_windows": True, "organize": "ask", "retention_conversations": 30, "retention_activity": 90},
    "search": {"web": True, "scientific": True, "max_sources": 12},
    "pdf": {"dark": True},
    "voice": {"engine": "voicestudio", "voice_id": "1faf41ee", "call_asr": "parakeet"},
    "adult": {"enabled": True},
}


def write_raw(data):
    """Grava o arquivo como uma versão antiga (ou editada à mão) o deixaria: sem passar por settings.save nem pela política."""
    settings._file().parent.mkdir(parents=True, exist_ok=True)
    settings._file().write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


def raw():
    return json.loads(settings._file().read_text("utf-8"))


class NoRemote:
    """Nada sai do 127.0.0.1: qualquer urlopen ou consulta de DNS para outro endereço é registrada e falha o teste."""

    def __enter__(self):
        self.urls, self.hosts = [], []
        real_open, real_dns = urllib.request.urlopen, socket.getaddrinfo

        def spy_open(req, *args, **kwargs):
            url = req if isinstance(req, str) else req.full_url
            if not url.startswith(("http://127.0.0.1", "http://localhost")):
                self.urls.append(url)
                raise AssertionError("requisição externa: " + url.split("?")[0])
            return real_open(req, *args, **kwargs)

        def spy_dns(host, *args, **kwargs):
            if host not in ("127.0.0.1", "localhost", None, ""):
                self.hosts.append(str(host))
                raise OSError("rede bloqueada no teste: " + str(host))
            return real_dns(host, *args, **kwargs)
        self.patches = [mock.patch.object(urllib.request, "urlopen", side_effect=spy_open),
                        mock.patch.object(socket, "getaddrinfo", side_effect=spy_dns)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

    def assert_clean(self, test):
        test.assertEqual(self.urls, [])
        test.assertEqual(self.hosts, [])
        test.assertNotIn("anthropic", sys.modules)  # nenhum SDK de nuvem: o do Claude nem está mais instalado (D188)


class Migration(Base):
    def test_old_gemini_settings_become_local_and_personal_choices_survive(self):
        write_raw(OLD)
        original = settings._file().read_text("utf-8")
        found = settings.migrate()
        self.assertTrue(found)
        disk = raw()
        m = disk["models"]
        self.assertEqual((m["provider"], m["fallback"], m["image_provider"], m["video_provider"]), ("ollama", "none", "local", "none"))
        for gone in ("google", "image_google"):
            self.assertNotIn(gone, m)
        self.assertNotIn("gemini", disk)
        self.assertNotIn("external", disk["privacy"])
        # o modelo local que já estava escolhido e as demais preferências ficam como estavam
        self.assertEqual((m["local"], m["temperature"], m["context_chars"], m["stream"]), ("qwen3:8b", 0.5, 20000, False))
        self.assertEqual((disk["search"]["web"], disk["search"]["max_sources"], disk["pdf"]["dark"], disk["adult"]["enabled"]), (True, 12, True, True))
        self.assertEqual((disk["voice"]["voice_id"], disk["voice"]["call_asr"]), ("1faf41ee", "parakeet"))
        self.assertEqual((disk["privacy"]["open_windows"], disk["privacy"]["retention_conversations"]), (True, 30))
        self.assertEqual(settings._backup_name().read_text("utf-8"), original)  # restauração: o arquivo como estava
        self.assertTrue(any(r["action"] == "migracao-gemini" for r in activity.recent(20)))

    def test_no_local_model_name_is_invented(self):
        write_raw({"models": {"provider": "google", "google": "gemini-3.8-flash", "local": ""}})
        settings.migrate()
        self.assertEqual(raw()["models"]["local"], "")  # vazio = Automático, resolvido pelo que existir no Ollama
        self.assertEqual(settings.load()["models"]["provider"], "ollama")

    def test_rerunning_changes_nothing_makes_no_second_backup_and_keeps_new_preferences(self):
        write_raw(OLD)
        settings.migrate()
        settings.save({"models": {"temperature": 0.9}, "search": {"max_sources": 5}})
        before = settings._file().read_text("utf-8")
        self.assertEqual(settings.migrate(), [])
        self.assertEqual(settings.migrate(), [])
        self.assertEqual(settings._file().read_text("utf-8"), before)
        self.assertEqual((settings.load()["models"]["temperature"], settings.load()["search"]["max_sources"]), (0.9, 5))
        self.assertEqual(len(list(settings._file().parent.glob("settings.json*.bak"))), 1)
        self.assertIn('"google"', settings._backup_name().read_text("utf-8"))  # a cópia continua sendo a original

    def test_a_clean_file_or_no_file_is_left_alone(self):
        self.assertEqual(settings.migrate(), [])
        self.assertFalse(settings._file().exists())
        settings.save({"search": {"web": True}})
        before = settings._file().read_text("utf-8")
        self.assertEqual(settings.migrate(), [])
        self.assertEqual(settings._file().read_text("utf-8"), before)
        self.assertEqual(list(settings._file().parent.glob("*.bak")), [])
        settings._file().write_text("{isto nao e json", "utf-8")
        self.assertEqual(settings.migrate(), [])
        self.assertEqual(settings._file().read_text("utf-8"), "{isto nao e json")

    def test_reading_neutralizes_a_stale_file_even_before_migrating(self):
        write_raw(OLD)
        loaded = settings.load()
        self.assertEqual((loaded["models"]["provider"], loaded["models"]["fallback"]), ("ollama", "none"))
        self.assertNotIn("gemini", loaded)
        self.assertEqual([p.name for p in providers.chain()[0] if p.name != "ollama"], [])
        self.assertIn('"google"', settings._file().read_text("utf-8"))  # ler não reescreve o arquivo

    def test_obsolete_fields_are_no_longer_part_of_the_settings(self):
        self.assertNotIn("gemini", settings.DEFAULTS)
        for key in ("google", "image_google"):
            self.assertNotIn(key, settings.DEFAULTS["models"])
        self.assertNotIn("external", settings.DEFAULTS["privacy"])
        saved = settings.save({"models": {"temperature": 0.2}})
        self.assertNotIn("gemini", saved)
        self.assertNotIn("gemini", raw())
        self.assertEqual(settings.migrate(), [])

    def test_the_open_server_runs_the_migration_once_and_never_fails_to_open(self):
        write_raw(OLD)
        with mock.patch.object(api, "_migrated", False):
            httpd = server.serve(0)
            httpd.server_close()
            self.assertEqual(settings.load()["models"]["provider"], "ollama")
            self.assertNotIn("gemini", raw())
        with mock.patch.object(api, "_migrated", False), mock.patch.object(settings, "migrate", side_effect=RuntimeError("falha")):
            httpd = server.serve(0)  # um erro na migração não impede o app de abrir
            httpd.server_close()


class Credential(Base):
    """O cofre é o de memória de tests/__init__.py: nenhum teste toca no Gerenciador de Credenciais do Windows."""

    def setUp(self):
        super().setUp()
        self.vault = tests.VAULT
        self.saved = dict(self.vault.items)
        self.vault.items.clear()
        self.vault.items.update({
            (store.APP, "google-api-key"): FAKE_SECRET,                       # a chave do Gemini no Lúmen: a única a sair
            (store.APP, "google-drive"): json.dumps({"client_id": "1.apps.googleusercontent.com", "refresh_token": "rt-drive"}),
            (store.APP, "notion"): "ntn_token_falso",
            (store.APP, "anthropic-api-key"): "sk-ant-falsa",
            (store.APP, "google-api-key-copia"): "nome parecido",
            ("OutroAplicativo", "google-api-key"): "de outro app",
            (store.APP, "protection-recovery"): "segredo da proteção",
        })
        self.before = dict(self.vault.items)

    def tearDown(self):
        self.vault.items.clear()
        self.vault.items.update(self.saved)
        super().tearDown()

    def test_only_the_exact_gemini_entry_leaves_the_vault(self):
        write_raw(OLD)
        settings.migrate()
        self.assertNotIn((store.APP, "google-api-key"), self.vault.items)
        for key, value in self.before.items():
            if key != (store.APP, "google-api-key"):
                self.assertEqual(self.vault.items.get(key), value, key)
        self.assertEqual(len(self.vault.items), len(self.before) - 1)

    def test_removal_never_reads_prints_or_logs_the_secret(self):
        with mock.patch.object(keyring, "get_password", side_effect=AssertionError("o segredo não pode ser lido")):
            write_raw(OLD)
            settings.migrate()
            settings.migrate()
        everything = json.dumps(activity.recent(50), ensure_ascii=False)
        logf = store.DATA / "lumen.log"
        everything += logf.read_text("utf-8") if logf.exists() else ""
        self.assertNotIn(FAKE_SECRET, everything)
        self.assertNotIn(FAKE_SECRET, settings._backup_name().read_text("utf-8"))  # a cópia do arquivo nunca teve a chave
        self.assertNotIn(FAKE_SECRET, settings._file().read_text("utf-8"))

    def test_removal_is_idempotent_and_tolerates_a_missing_or_unavailable_vault(self):
        self.assertTrue(settings.forget_legacy_gemini_key())
        self.assertFalse(settings.forget_legacy_gemini_key())  # já não existe: sem erro
        self.vault.items[(store.APP, "google-api-key")] = FAKE_SECRET
        with mock.patch.object(keyring, "delete_password", side_effect=keyring.errors.KeyringError("cofre indisponível")):
            self.assertFalse(settings.forget_legacy_gemini_key())  # não derruba o app; a próxima abertura tenta de novo
        self.assertTrue(settings.forget_legacy_gemini_key())

    def test_the_gemini_key_can_no_longer_be_stored_read_or_listed(self):
        self.assertNotIn("google", settings.KEY_ACCOUNTS)
        for call in (lambda: settings.api_key("google"), lambda: settings.set_api_key(FAKE_SECRET, "google"),
                     lambda: settings.set_api_key("", "google")):
            with self.assertRaises(AppError):
                call()
        self.assertEqual(self.vault.items, self.before)  # nada foi gravado nem apagado

    def test_drive_and_notion_credentials_still_work_after_the_migration(self):
        write_raw(OLD)
        settings.migrate()
        self.assertEqual(gdrive._creds()["refresh_token"], "rt-drive")
        self.assertTrue(gdrive.status()["connected"])
        self.assertEqual(store.get_token(), "ntn_token_falso")
        self.assertEqual(settings.api_key("anthropic"), "sk-ant-falsa")  # a política segue bloqueando o uso, sem apagar a chave dele


class Rejection(Base):
    def test_removed_provider_ids_are_refused_in_every_form(self):
        for bad in ("google", "gemini", "Google", "GEMINI", "gemini-3.8-flash", "google ", "outro"):
            for key in ("provider", "fallback"):
                with self.assertRaises(AppError, msg=(key, bad)):
                    settings.save({"models": {key: bad}})
        for key in ("image_provider",):
            for bad in ("google", "openai", "gemini"):
                with self.assertRaises(AppError):
                    settings.save({"models": {key: bad}})
        with self.assertRaises(AppError):
            settings.save({"models": {"video_provider": "google"}})
        self.assertEqual(settings.load()["models"]["provider"], "ollama")

    def test_old_fields_sent_in_a_payload_are_ignored_not_stored(self):
        saved = settings.save({"models": {"google": "gemini-3.8-flash", "image_google": "gemini-2.5-flash-image", "temperature": 0.4},
                               "gemini": {"accept_quotas": True, "accept_data_use": True, "confirmed_epoch": 0},
                               "privacy": {"external": True}})
        for blob in (saved, raw()):
            text = json.dumps(blob)
            self.assertNotIn("gemini", text)
            self.assertNotIn("accept_quotas", text)
            self.assertNotIn('"external"', text)
        self.assertEqual(saved["models"]["temperature"], 0.4)

    def test_the_policy_allows_only_the_local_ai(self):
        policy.authorize({}, "ollama")
        expected = {"google": "removed_provider", "gemini": "removed_provider", "anthropic": "paid_provider", "openai": "paid_provider",
                    "mistral": "unknown_provider", "": "unknown_provider"}
        for provider, code in expected.items():
            with self.assertRaises(policy.Blocked, msg=provider) as cm:
                policy.authorize({}, provider, "qualquer-modelo")
            self.assertEqual(cm.exception.code, code, provider)
        for feature in ("image", "video", "tts", "asr", "embeddings", "web_search", "storage"):
            with self.assertRaises(policy.Blocked) as cm:
                policy.authorize({}, "google", "", feature)
            self.assertEqual(cm.exception.code, "paid_feature", feature)
        self.assertEqual(policy.PROVIDERS, ("ollama",))

    def test_the_provider_factory_and_chain_never_build_a_removed_provider(self):
        forged = settings.load()
        forged["models"] = {**forged["models"], "provider": "google", "fallback": "gemini"}  # ajustes forjados, fora da leitura normalizada
        with NoRemote() as net:
            for name in ("google", "gemini", "desconhecido"):
                with self.assertRaises(policy.Blocked):
                    providers.get(name, forged)
            chain, reasons = providers.chain(forged)
        net.assert_clean(self)
        self.assertFalse([p for p in chain if p.name != "ollama"])
        self.assertTrue(any("retirada" in r for r in reasons), reasons)

    def test_every_removed_class_function_constant_and_route_is_gone(self):
        gone = [(providers, ("Google", "CloudProvider", "GOOGLE_API", "RateLimited", "models_for", "generate_image", "generate_video",
                             "_request_json", "_request_stream", "_model_rows", "_google_schema", "_google_declaration", "_tool_messages")),
                (policy, ("GEMINI_FREE_CHAT", "GEMINI_EXCLUDED", "GEMINI_DEFAULTS", "gemini_state", "gemini_blockers", "gemini_view",
                          "plan_confirmed", "RATE_LIMITS_URL", "PROJECTS_URL", "SOURCES", "EXTERNAL")),
                (settings, ("gemini_consent", "lock_gemini", "_gemini_update")),
                (api, ("_key", "_gemini")),
                (artifacts, ("providers", "settings"))]
        for module, names in gone:
            for name in names:
                self.assertFalse(hasattr(module, name), f"{module.__name__}.{name}")
        for path in ("/api/study/key", "/api/study/gemini"):
            self.assertNotIn(("POST", path), api.ROUTES)
            self.assertNotIn(("POST", path), server.ROUTES)

    def test_creating_cloud_media_has_no_code_path(self):
        with NoRemote() as net, mock.patch.object(artifacts.imagegen, "ready", return_value=False):
            with self.assertRaises(AppError):
                artifacts.image_blob("Uma capa", 512, 512)  # só o gerador local; ele não está instalado aqui
            with self.assertRaises(AppError) as cm:
                artifacts.video({"topic": "Nuvens"}, "cid")
        net.assert_clean(self)
        self.assertIn("não gera vídeo", str(cm.exception))
        self.assertEqual(artifacts.request("/video Nuvens")["kind"], "video")  # reconhecido, para a pessoa receber o aviso


class Routes(Base):
    """Pelo servidor de verdade: as rotas retiradas respondem 404 e nenhuma função antiga é executada."""

    REMOVED = [("POST", "/api/study/key"), ("POST", "/api/study/gemini"),
               ("GET", "/api/notebook"), ("POST", "/api/notebook/link"), ("POST", "/api/notebook/unlink"), ("GET", "/api/notebook/lesson"),
               ("POST", "/api/notebook/choose"), ("POST", "/api/notebook/export"), ("POST", "/api/notebook/open"),
               ("POST", "/api/notebook/reveal"), ("POST", "/api/notebook/confirm"), ("POST", "/api/notebook/import"),
               ("POST", "/api/notebook/import-audio"), ("GET", "/api/notebook/imported"), ("POST", "/api/notebook/play"),
               ("POST", "/api/notebook/forget"), ("GET", "/api/notebook/drive"), ("POST", "/api/notebook/drive/client"),
               ("POST", "/api/notebook/drive/login"), ("POST", "/api/notebook/drive/logout"), ("POST", "/api/notebook/drive/send"),
               ("POST", "/api/notebook/drive/check")]

    def setUp(self):
        super().setUp()
        self.httpd = server.serve(0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_port

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers={"X-Lumen-Token": server.TOKEN},
                                     data=json.dumps(body or {}).encode() if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_removed_routes_are_not_found_and_run_nothing(self):
        with NoRemote() as net, mock.patch.object(settings, "set_api_key") as store_key, \
                mock.patch.object(gdrive, "login") as login, mock.patch.object(gdrive, "set_client") as client:
            for method, path in self.REMOVED:
                self.assertNotIn((method, path), server.ROUTES, path)
                code, body = self.call(method, path, {"provider": "google", "key": FAKE_SECRET, "key_": "x"})
                self.assertEqual(code, 404, (method, path))
                self.assertEqual(body["error"]["message"], "Não encontrado.")
            store_key.assert_not_called()
            login.assert_not_called()
            client.assert_not_called()
        net.assert_clean(self)

    def test_the_models_route_lists_only_local_models(self):
        with mock.patch.object(llm, "models", return_value=["qwen3.5:4b", "qwen3-embedding:0.6b"]):
            code, body = self.call("GET", "/api/study/models?google=1")
        self.assertEqual(code, 200)
        self.assertEqual(body, {"local": ["qwen3.5:4b"]})

    def test_the_drive_routes_that_protection_needs_moved_and_answer(self):
        for method, path in (("GET", "/api/drive"), ("POST", "/api/drive/client"), ("POST", "/api/drive/login"), ("POST", "/api/drive/logout")):
            self.assertIn((method, path), server.ROUTES)
        with mock.patch.object(gdrive, "_creds", return_value={"client_id": "1.apps.googleusercontent.com", "refresh_token": "rt-secreto"}):
            code, body = self.call("GET", "/api/drive")
        self.assertEqual(code, 200)
        self.assertEqual((body["client"], body["connected"]), (True, True))
        self.assertNotIn("rt-secreto", json.dumps(body))
        self.assertNotIn("folder", body)

    def test_state_and_catalog_do_not_mention_the_removed_provider(self):
        with mock.patch.object(llm, "models", return_value=["qwen3.5:4b"]), mock.patch.object(registry.urllib.request, "urlopen", side_effect=OSError):
            state = api.state()
            integrations = registry.integrations()
            roles = registry.model_roles(settings.load())
        self.assertEqual(set(state["providers"]), {"ollama", "adult", "anthropic", "openai"})
        self.assertNotIn("google", {x["id"] for x in integrations})
        self.assertFalse(re.search(r"(?i)gemini|google", json.dumps([state["providers"], state["settings"], integrations, roles])))
        self.assertEqual(roles[0]["role"], "Chat principal (local)")


class LegacyData(Base):
    """Conversas, materiais e dados do conector retirado continuam lá: nada é lido por uma integração, nada é apagado."""

    def test_old_conversations_and_artifacts_made_by_the_removed_provider_stay_readable(self):
        conv = chats.create(title="Conversa de antes", provider="google", model="gemini-3.8-flash")
        chats.add_message(conv["id"], "user", "Como o sono ajuda a memória?")
        chats.add_message(conv["id"], "assistant", "Consolida a memória [S1].", meta={"provider": "google", "model": "gemini-3.8-flash"})
        got = chats.get(conv["id"])
        self.assertEqual([m["role"] for m in got["messages"]], ["user", "assistant"])
        self.assertEqual(got["messages"][1]["meta"]["provider"], "google")  # a origem fica registrada, só não há mais como chamar
        self.assertIn("Consolida a memória", chats.export(conv["id"], "md"))
        self.assertEqual(chats.listing()[0]["id"], conv["id"])

    def test_the_legacy_notebook_files_are_left_exactly_as_they_were(self):
        store.DATA.mkdir(parents=True, exist_ok=True)
        links = store.DATA / "notebook.json"
        links.write_text(json.dumps({"notebooks": {"nb1": {"title": "Biologia", "url": "https://notebook.google.com/notebook/abcdefgh12"}}}), "utf-8")
        folder = store.DATA / "notebook" / "imports" / "aula1"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "resumo.md").write_text("# Resumo trazido do caderno\n", "utf-8")
        (store.DATA / "notebook" / "state.json").write_text('{"aula1": {"notebook": "nb1"}}', "utf-8")
        snapshot = {p: p.read_bytes() for p in (store.DATA / "notebook").rglob("*") if p.is_file()} | {links: links.read_bytes()}
        write_raw(OLD)
        settings.migrate()
        server.serve(0).server_close()
        api.state()
        self.assertEqual({p: p.read_bytes() for p in snapshot}, snapshot)
        self.assertFalse(hasattr(server, "notebook"))  # e nenhum módulo as lê mais

    def test_the_library_no_longer_carries_notebook_fields_and_saved_lessons_stay(self):
        lesson = {"url": "https://notion.so/aula", "title": "Aula 1", "created": "2026-11-01T10:00:00"}
        with mock.patch.object(store, "history", return_value={"k1": lesson}):
            out = server._history()
        self.assertNotIn("course_notebooks", out)
        self.assertEqual([it["title"] for it in out["items"]], ["Aula 1"])
        self.assertEqual(out["items"][0]["url"], "https://notion.so/aula")
        self.assertNotIn("notebook", out["items"][0])


class LocalAI(Core):
    """A IA local segue respondendo; e, sem ela, a tela diz o que fazer em vez de fingir que funciona."""

    def test_a_turn_with_old_gemini_settings_is_answered_by_the_local_model_and_nothing_leaves_the_pc(self):
        write_raw(OLD)
        with NoRemote() as net:
            events = run_turn({"text": "Como o sono ajuda a memória?"})
        net.assert_clean(self)
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertEqual(done["meta"]["provider"], "ollama")
        self.assertEqual(activity.recent(action="envio-externo"), [])

    def test_a_web_request_goes_to_the_guided_edge_search_with_the_local_model(self):
        write_raw(OLD)
        with NoRemote() as net, mock.patch.object(tools, "run", return_value=("Resultado da pesquisa guiada.", False)) as research:
            run_turn({"text": "Pesquise na internet sobre sono e memória", "web": True})
        net.assert_clean(self)
        self.assertEqual(research.call_args.args[1], "research_web")

    def test_a_forged_removed_provider_in_the_request_cannot_choose_the_model(self):
        with NoRemote() as net:
            events = run_turn({"text": "Como o sono ajuda a memória?", "provider": "google", "model": "gemini-3.8-flash"})
        net.assert_clean(self)
        done = next(e for e in events if e["type"] == "done")["message"]
        self.assertEqual((done["meta"]["provider"], done["meta"]["model"] in ("", None) or "gemini" not in done["meta"]["model"]), ("ollama", True))

    def test_without_ollama_the_failure_is_explained_and_no_other_service_is_tried(self):
        write_raw(OLD)
        with NoRemote() as net, mock.patch.object(llm, "models", return_value=None):
            chain, reasons = providers.chain()
            status = providers.status()
            ready = providers.Ollama().ready()
            events = run_turn({"text": "Como o sono ajuda a memória?"})
        net.assert_clean(self)
        self.assertEqual(chain, [])
        self.assertTrue(any("Ollama não está rodando" in r for r in reasons), reasons)
        self.assertFalse(status["ollama"]["running"])
        self.assertFalse(ready[0])
        errors = [e for e in events if e["type"] == "error"]
        self.assertTrue(errors, [e["type"] for e in events])
        self.assertIn("Ollama", json.dumps(errors, ensure_ascii=False))
        self.assertNotIn("done", [e["type"] for e in events])

    def test_with_ollama_but_no_chat_model_the_status_says_so(self):
        with mock.patch.object(llm, "models", return_value=["qwen3-embedding:0.6b"]):
            status = providers.status()
            ok, why = providers.Ollama().ready()
        self.assertTrue(status["ollama"]["running"])
        self.assertFalse(status["ollama"]["installed"])
        self.assertEqual(status["ollama"]["models"], [])  # só modelos de chat entram na lista
        self.assertFalse(ok)
        self.assertIn("não está instalado", why)


class Sources(unittest.TestCase):
    """O código e a interface ativos não implementam nem oferecem o Gemini (o que sobra é história, migração e recusa)."""

    PY = [p for p in (ROOT / "lumen").rglob("*.py") if "__pycache__" not in p.parts]
    WEB = [p for p in (ROOT / "lumen" / "web").iterdir() if p.suffix in (".js", ".html", ".css")]
    PROTOCOL = re.compile(r"generativelanguage|generateContent|streamGenerateContent|functionDeclarations|thoughtSignature|"
                          r"x-goog-api-key|googleSearch|aistudio\.google|ai\.google\.dev|gemini-api", re.I)

    def test_no_python_module_has_the_provider_protocol_or_endpoints(self):
        hits = [f"{p.relative_to(ROOT)}:{n}" for p in self.PY for n, line in enumerate(p.read_text("utf-8").splitlines(), 1)
                if self.PROTOCOL.search(line)]
        self.assertEqual(hits, [])

    def test_the_user_interface_never_offers_or_calls_the_removed_features(self):
        hits = [f"{p.name}:{n}" for p in self.WEB for n, line in enumerate(p.read_text("utf-8").splitlines(), 1)
                if re.search(r"(?i)gemini|notebooklm|/api/notebook|/api/study/key|/api/study/gemini|accept_quotas|generativelanguage", line)]
        # restam só os rótulos de procedência de conversas e envios antigos (histórico verdadeiro), nunca um controle
        allowed = {"study.js", "study-settings.js", "index.html"}  # index: o texto de “Limpar dados” cita os arquivos antigos
        self.assertTrue(all(h.split(":")[0] in allowed for h in hits), hits)
        self.assertLessEqual(len(hits), 3, hits)
        for p in self.WEB:
            text = p.read_text("utf-8")
            for removed in ("openNotebook", "loadNbCard", "nb-dlg", "integ-notebook", "itab-notebook", "api/notebook"):
                self.assertNotIn(removed, text, f"{p.name}: {removed}")

    def test_the_only_python_mentions_are_migration_rejection_history_and_notes(self):
        allowed = {"policy.py", "settings.py", "providers.py", "api.py", "server.py", "store.py", "gdrive.py", "registry.py", "activity.py"}
        files = {p.name for p in self.PY if re.search(r"(?i)gemini", p.read_text("utf-8"))}
        self.assertLessEqual(files, allowed, files)
        self.assertFalse((ROOT / "lumen" / "notebook.py").exists())

    def test_no_active_documentation_teaches_how_to_configure_the_removed_provider(self):
        readme = (ROOT / "README.md").read_text("utf-8")
        self.assertNotRegex(readme, r"(?i)chave\s+(?:de\s+API\s+)?do\s+Gemini|Estudar no Gemini Notebook|aistudio\.google\.com/apikey")


if __name__ == "__main__":
    unittest.main()
