"""Capas com o Notion simulado. `Covers`: o formulário do curso novo (Organizar estudo → Novo curso). `PageCovers`:
Capas do Notion (qualquer página que a integração enxerga): a prévia é feita no PC sem tocar no Notion, e aplicar
troca só a capa da página escolhida, com exatamente a imagem aprovada, conferida lendo a página de novo."""
import json
import os
import threading
import time
import types
import unittest
import urllib.error
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen)
from lumen import AppError, catalog, imagegen, llm, notion, server, store, understanding
from tests.fake_notion import Fake

DECOR = json.dumps({"emoji": "🌱", "motifs": ["🌞", "🍃"], "palette": "natureza_sol", "cover": "gradients_8",
                    "color": "green_background", "subtitle": "Resumos de fotossíntese", "image_prompt": "a green leaf"})
PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(6000)  # bytes únicos: dá para achar exatamente esta imagem no upload


def h(body):
    return types.SimpleNamespace(_json=lambda: body)


class Covers(unittest.TestCase):
    def setUp(self):
        store.clear_local_data()
        (store.DATA / "catalog.json").unlink(missing_ok=True)
        server._previews.clear()
        self.fake = Fake()
        self.root = self.fake.add_page("Estudos")
        store.save_config({**store.DEFAULTS, "root_page_id": self.root, "root_page_title": "Estudos"})
        self.render = mock.MagicMock(return_value=PNG)
        self.chat = mock.MagicMock(return_value=DECOR)
        self.patches = [mock.patch.object(store, "get_token", return_value="secret_test"),
                        mock.patch.object(llm, "_chat", self.chat), mock.patch("lumen.cover.render", self.render),
                        mock.patch.object(imagegen, "ready", return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def preview(self, title, **kw):
        return server._preview(h({"title": title, **kw}))

    def course(self, **body):
        return server._catalog_course(h(body))

    def pages_titled(self, title):
        return [p for p in self.fake.pages.values() if p["title"] == title and not p["in_trash"]]

    def test_current_form_publishes_the_approved_preview_without_generating_again(self):  # 1, 2, 11
        n = len(self.fake.calls)
        pv = self.preview("Fotossíntese")
        self.assertEqual(self.fake.calls[n:], [])  # a prévia é local: nenhum pedido ao Notion
        self.assertEqual((pv["kind"], pv["title"], pv["parent"]), ("emojis", "Fotossíntese", "Estudos"))
        self.assertTrue(pv["image"].startswith("data:image/png;base64,"))
        r = self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        self.assertEqual((self.render.call_count, self.chat.call_count), (1, 1))  # nada gerado de novo ao criar
        page = self.fake.pages[r["course"]["notion_page_id"]]
        self.assertEqual(page["cover"]["type"], "file_upload")
        up = self.fake.uploads[page["cover"]["file_upload"]["id"]]
        self.assertEqual(up["status"], "uploaded")
        self.assertIn(PNG, up["body"])  # os mesmos bytes da prévia
        self.assertEqual(page["icon"]["emoji"], "🌱")
        self.assertEqual(r["cover"], {"kind": "emojis", "confirmed": True})  # conferido consultando a página
        self.assertIn(("GET", f"/pages/{page['id']}"), self.fake.calls)
        self.assertIsNone(r["note"])
        self.assertEqual(catalog.load()["courses"][0]["notion_page_id"], page["id"])

    def test_preview_of_another_name_or_expired_is_refused_before_creating(self):  # 3, 4
        pv = self.preview("Fotossíntese")
        for pid, name, msg in ((pv["preview_id"], "Respiração celular", "outro nome"), ("nao-existe", "Fotossíntese", "expirou")):
            with self.assertRaises(AppError) as e:
                self.course(name=name, decorate=True, preview_id=pid)
            self.assertIn(msg, str(e.exception))
        server._previews[pv["preview_id"]]["at"] -= server.PREVIEW_TTL + 1
        with self.assertRaises(AppError) as e:
            self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        self.assertIn("expirou", str(e.exception))
        self.assertEqual(catalog.load()["courses"], [])  # nada criado no Lumen
        self.assertEqual([p["title"] for p in self.fake.pages.values()], ["Estudos"])  # nem no Notion
        self.assertEqual(self.fake.uploads, {})

    def test_one_preview_at_a_time(self):  # 6 (clique duplo / pedidos fora de ordem não disputam a GPU)
        slow = lambda *a, **k: time.sleep(0.6) or PNG  # noqa: E731
        self.render.side_effect = slow
        out = []

        def go():
            try:
                out.append(self.preview("Fotossíntese")["preview_id"])
            except AppError as e:
                out.append(str(e))
        ts = [threading.Thread(target=go) for _ in range(2)]
        for t in ts:
            t.start()
            time.sleep(0.1)
        for t in ts:
            t.join()
        self.assertEqual(sorted(x.startswith("Já estou gerando") for x in out), [False, True])
        self.assertEqual(self.render.call_count, 1)

    def test_double_click_on_create_makes_one_page(self):  # 6
        pv = self.preview("Fotossíntese")
        self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        with self.assertRaises(AppError):  # o segundo pedido é recusado pelo catálogo (nome repetido)
            self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        self.assertEqual(len(self.pages_titled("Fotossíntese")), 1)
        self.assertEqual(len(self.fake.uploads), 1)

    def test_generation_failure_and_fallback_are_explained(self):  # 7, 8
        with mock.patch.object(llm, "_chat", side_effect=AppError("O Ollama não está rodando.", "Abra o Ollama.")):
            with self.assertRaises(AppError) as e:
                self.preview("Fotossíntese")
        self.assertIn("Ollama", str(e.exception))
        self.assertEqual(server._previews, {})  # nada guardado como “aprovável”
        pv = self.preview("Fotossíntese")  # sem gerador instalado: alternativa, dita como alternativa
        self.assertEqual(pv["kind"], "emojis")
        self.assertIn("não está instalado", pv["note"])
        with mock.patch.object(imagegen, "ready", return_value=True), mock.patch.object(imagegen, "generate", return_value=None):
            pv = self.preview("Fotossíntese")  # gerador instalado, mas a geração falhou
        self.assertEqual(pv["kind"], "emojis")
        self.assertIn("alternativa", pv["note"])
        with mock.patch.object(imagegen, "ready", return_value=True), mock.patch.object(imagegen, "generate", return_value=PNG) as g:
            pv = self.preview("Fotossíntese")
        self.assertEqual((pv["kind"], pv["note"]), ("ia", ""))
        self.assertEqual(g.call_args[0][0], "a green leaf")
        self.assertGreaterEqual(pv["seconds"], 0)

    def test_no_drawing_at_all_is_called_a_notion_color_cover(self):  # 8 (o desenho com emojis também falhou)
        self.render.return_value = None
        pv = self.preview("Fotossíntese")
        self.assertEqual((pv["kind"], pv["image"]), ("notion", None))
        self.assertIn("capa de cor do Notion", pv["note"])
        r = self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        page = self.fake.pages[r["course"]["notion_page_id"]]
        self.assertEqual(page["cover"]["type"], "external")  # a capa de cor do Notion, como a prévia avisou
        self.assertEqual(r["cover"], {"kind": "notion", "confirmed": False})
        self.assertIn("capa de cor do Notion", r["note"])
        self.assertEqual(self.fake.uploads, {})

    def test_upload_failure_is_reported_without_a_false_success(self):  # 9
        self.fake.fail_upload = True
        pv = self.preview("Folhas")
        r = self.course(name="Folhas", decorate=True, preview_id=pv["preview_id"])
        self.assertEqual(r["cover"], {"kind": "notion", "confirmed": False})
        self.assertIn("falhou", r["note"])  # chega à interface (antes se perdia em _notion_course)
        page = self.fake.pages[r["course"]["notion_page_id"]]
        self.assertEqual(page["cover"]["external"]["url"], "https://www.notion.so/images/page-cover/gradients_8.png")

    def test_existing_page_is_adopted_untouched(self):  # 10
        pre = self.fake.add_page("Fotossíntese", self.root)
        self.fake.pages[pre].update(cover={"type": "external", "external": {"url": "https://exemplo.com/minha.png"}},
                                    icon={"type": "emoji", "emoji": "🧪"}, blocks=[{"type": "paragraph", "id": "b1"}])
        before = json.dumps(self.fake.pages[pre], sort_keys=True)
        pv = self.preview("Fotossíntese")
        r = self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        self.assertEqual(r["course"]["notion_page_id"], pre)
        self.assertIn("adotada como está", r["note"])
        self.assertEqual(r["cover"], {"adopted": True})
        self.assertEqual(json.dumps(self.fake.pages[pre], sort_keys=True), before)  # título, capa, ícone e conteúdo iguais
        self.assertEqual(self.fake.uploads, {})
        self.assertNotIn(("POST", "/pages"), self.fake.calls)

    def test_course_without_cover_still_works(self):  # 12
        r = self.course(name="Álgebra")
        page = self.fake.pages[r["course"]["notion_page_id"]]
        self.assertIsNone(page["cover"])
        self.assertEqual((r["cover"], self.render.call_count, self.fake.uploads), (None, 0, {}))

    def test_lost_create_response_is_reconciled_not_repeated(self):
        real = notion.request

        def flaky(method, path, token, body=None, once=False):
            out = real(method, path, token, body, once)
            if method == "POST" and path == "/pages":  # o Notion criou, mas a resposta não voltou
                raise notion.Unconfirmed("Não foi possível confirmar o envio ao Notion.", "")
            return out
        pv = self.preview("Fotossíntese")
        with mock.patch.object(notion, "request", flaky):
            r = self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        self.assertEqual(self.fake.calls.count(("POST", "/pages")), 1)
        self.assertEqual([p["id"] for p in self.pages_titled("Fotossíntese")], [r["course"]["notion_page_id"]])
        self.assertTrue(r["cover"]["confirmed"])

    def test_cover_missing_after_creation_is_flagged(self):
        real = notion.request

        def no_cover(method, path, token, body=None, once=False):
            out = real(method, path, token, body, once)
            return {**out, "cover": None} if method == "GET" and path.startswith("/pages/") else out
        pv = self.preview("Fotossíntese")
        with mock.patch.object(notion, "request", no_cover):
            r = self.course(name="Fotossíntese", decorate=True, preview_id=pv["preview_id"])
        self.assertEqual(r["cover"], {"kind": "notion", "confirmed": False})
        self.assertIn("não mostrou a capa", r["note"])


OLD = b"\x89PNG\r\n\x1a\n" + os.urandom(3000)  # a capa que a página já tinha


def q(**query):
    return types.SimpleNamespace(_query=lambda: query)


class PageCovers(unittest.TestCase):
    """Capas do Notion: sem curso, sem página raiz e com o material indo “Só para o Obsidian”."""

    def setUp(self):
        store.clear_local_data()
        (store.DATA / "catalog.json").unlink(missing_ok=True)
        server._previews.clear()
        self.fake = Fake()
        store.save_config({**store.DEFAULTS, "root_page_id": "", "root_page_title": "", "destinations": "obsidian"})
        self.render, self.chat = mock.MagicMock(return_value=PNG), mock.MagicMock(return_value=DECOR)
        self.token = mock.patch.object(store, "get_token", return_value="secret_test")
        self.patches = [self.token, mock.patch.object(llm, "_chat", self.chat), mock.patch("lumen.cover.render", self.render),
                        mock.patch.object(imagegen, "ready", return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.assertEqual(self.fake.violations, [])
        self.fake.close()

    def page(self, ref):
        return server.ROUTES[("GET", "/api/notion/page")](q(ref=ref))

    def search(self, text="", cursor=None):
        return server.ROUTES[("GET", "/api/notion/search")](q(q=text, **({"cursor": cursor} if cursor else {})))

    def preview(self, page, theme=""):
        return server._page_preview(h({"page_id": page["id"], "title": page["title"], "theme": theme}))

    def apply(self, pv, page, **kw):
        return server._cover_apply(h({"preview_id": pv["preview_id"], "page_id": page["id"], "theme": pv["theme"],
                                      "cover": page["cover"], **kw}))

    def only_upload(self):
        self.assertEqual(len(self.fake.uploads), 1)
        return next(iter(self.fake.uploads))

    def test_plain_page_without_course_root_or_notion_destination(self):  # 1, 4, 5, 10, 11, 12
        pid = self.fake.add_page("Orçamento 2026")
        self.fake.pages[pid].update(icon={"type": "emoji", "emoji": "💰"}, blocks=[{"type": "paragraph", "id": "b1"}])
        understanding.start("k1", "Aula de juros", "Arquivo", {"path": "aula.mp4"})  # uma aula em edição
        understanding.save_draft("k1", "O que eu entendi da aula", 1)
        cfg, hist, draft = store.load_config(), store.history(), understanding.load("k1")
        page = self.page(pid)
        self.assertEqual((page["title"], page["where"], page["cover"], page["icon"]),
                         ("Orçamento 2026", "No topo do workspace", None, "💰"))
        n = len(self.fake.calls)
        pv = self.preview(page)
        self.assertEqual(self.fake.calls[n:], [])  # a prévia é só no PC
        self.assertEqual((pv["kind"], pv["theme"]), ("emojis", ""))
        self.assertIn("Título: Orçamento 2026", self.chat.call_args[0][2])  # sem descrição, o tema é o título
        r = self.apply(pv, page)
        self.assertEqual(r["state"], "confirmed")
        self.assertEqual((self.render.call_count, self.chat.call_count), (1, 1))  # aplicar não gera outra imagem
        up = self.only_upload()
        self.assertEqual(self.fake.uploads[up]["file"], PNG)  # os mesmos bytes da prévia
        self.assertEqual(self.fake.patches, [(pid, {"cover": {"type": "file_upload", "file_upload": {"id": up}}})])
        self.assertTrue(r["page"]["cover"].startswith("file:"))
        # só a capa: nada de curso, módulo, subpágina, bloco, registro, catálogo ou mudança na aula em edição
        self.assertEqual(list(self.fake.pages), [pid])
        self.assertFalse([c for c in self.fake.calls if c[0] in ("POST", "PATCH") and c[1] not in
                          ("/file_uploads", f"/file_uploads/{up}/send", f"/pages/{pid}")])
        self.assertEqual((self.fake.pages[pid]["icon"]["emoji"], self.fake.pages[pid]["blocks"]), ("💰", [{"type": "paragraph", "id": "b1"}]))
        self.assertEqual((catalog.load()["courses"], store.load_config(), store.history()), ([], cfg, hist))
        self.assertEqual(understanding.load("k1"), draft)

    def test_subpage_and_ai_theme(self):  # 2
        parent = self.fake.add_page("Finanças")
        sub = self.page(self.fake.add_page("Metas do ano", parent))
        self.assertEqual(sub["where"], "Subpágina de “Finanças”")
        with mock.patch.object(imagegen, "ready", return_value=True), \
                mock.patch.object(imagegen, "generate", return_value=PNG) as g:
            pv = self.preview(sub, "  Uma ilustração   minimalista sobre organização financeira. ")
        self.assertEqual((pv["kind"], pv["note"], pv["theme"]), ("ia", "", "Uma ilustração minimalista sobre organização financeira."))
        self.assertIn("organização financeira", self.chat.call_args[0][2])
        self.assertEqual(g.call_args[0][0], "a green leaf")  # o pedido preparado pela IA local
        self.assertEqual(self.apply(pv, sub)["state"], "confirmed")
        self.assertIsNone(self.fake.pages[parent]["cover"])

    def test_database_row_keeps_title_icon_properties_and_content(self):  # 3, 13
        src, other = self.fake.add_source("Contas da casa"), self.fake.add_page("Casa")
        props = {"Status": {"id": "s%3A", "type": "select", "select": {"id": "1", "name": "Pago", "color": "green"}},
                 "Casa": {"id": "r%3A", "type": "relation", "relation": [{"id": other}], "has_more": False},
                 "Valor": {"id": "n%3A", "type": "number", "number": 120.5}}
        row = self.fake.add_page("Conta de luz", row_of=src, title_key="Tarefa", props=props)
        self.fake.pages[row].update(icon={"type": "emoji", "emoji": "💡"}, blocks=[{"type": "to_do", "id": "t1"}])
        keep = lambda: {k: v for k, v in self.fake.page_json(self.fake.pages[row]).items() if k != "cover"}  # noqa: E731
        before = keep()
        self.assertIn(row, [p["id"] for p in self.search("conta")["pages"]])  # a busca inclui registros
        page = self.page(row)
        self.assertEqual((page["title"], page["where"]), ("Conta de luz", "Registro em “Contas da casa”"))
        r = self.apply(self.preview(page), page)
        self.assertEqual(r["state"], "confirmed")
        self.assertEqual(keep(), before)  # título (em “Tarefa”), ícone, propriedades, relação e lugar iguais
        self.assertEqual(self.fake.pages[row]["blocks"], [{"type": "to_do", "id": "t1"}])
        self.assertEqual([set(body) for _, body in self.fake.patches], [{"cover"}])

    def test_search_pages_through_every_result_page(self):  # 6
        ids = [self.fake.add_page(f"Aula {i:02d}") for i in range(45)]
        self.fake.pages[ids[0]]["in_trash"] = True
        src = self.fake.add_source("Leituras")
        row = self.fake.add_page("Aula registro", row_of=src)
        got, cursor, rounds = [], None, 0
        while True:
            r = self.search("aula", cursor)
            got += [p["id"] for p in r["pages"]]
            rounds, cursor = rounds + 1, r["next_cursor"]
            if not cursor:
                break
        self.assertEqual(rounds, 3)  # 20 + 20 + 5 (46 achadas, uma na lixeira)
        self.assertEqual(got, ids[1:] + [row])
        self.assertNotIn(row, [p["id"] for p in notion.list_pages("secret_test")])  # destinos das aulas: sem registros

    def test_same_titles_are_told_apart_and_applied_by_id(self):  # 7
        a, b = self.fake.add_page("Pessoal"), self.fake.add_page("Trabalho")
        n1, n2 = self.fake.add_page("Notas", a), self.fake.add_page("Notas", b)
        found = {p["id"]: p["where"] for p in self.search("Notas")["pages"]}
        self.assertEqual(found, {n1: "Subpágina de “Pessoal”", n2: "Subpágina de “Trabalho”"})
        n = len(self.fake.calls)  # as mães vieram na mesma leva: o nome sai dela, sem outro pedido
        self.assertEqual({p["id"]: p["where"] for p in self.search()["pages"] if p["title"] == "Notas"}, found)
        self.assertEqual(self.fake.calls[n:], [("POST", "/search")])
        page = self.page(n2)
        self.assertEqual(self.apply(self.preview(page), page)["state"], "confirmed")
        self.assertIsNone(self.fake.pages[n1]["cover"])
        self.assertEqual(self.fake.pages[n2]["cover"]["type"], "file_upload")

    def test_link_to_a_page_the_search_does_not_return(self):  # 8
        pid = self.fake.add_page("Diário", searchable=False)
        self.assertEqual(self.search("Diário")["pages"], [])
        hexid, other = pid.replace("-", ""), "fedcba9876543210fedcba9876543210"
        real, opened = notion.urllib.request.urlopen, []

        def spy(req, *a, **k):
            opened.append(getattr(req, "full_url", req))
            return real(req, *a, **k)
        with mock.patch.object(notion.urllib.request, "urlopen", spy):
            for link in (f"https://www.notion.so/Di%C3%A1rio-{hexid}?pvs=4", pid, hexid.upper(),
                         f"https://www.notion.so/ws/{other}?v={'a' * 32}&p={hexid}&pm=s",
                         f"https://www.notion.so/Di%C3%A1rio-{hexid}#{other}",
                         f"https://evil.example/roubar-{hexid}?token=1"):  # o link colado nunca é aberto
                self.assertEqual(self.page(link)["id"], pid, link)
        self.assertTrue(opened and all(u.startswith(notion.API + "/pages/") for u in opened), opened)

    def test_inaccessible_trashed_database_and_read_only(self):  # 9
        cases = (("0123456789abcdef0123456789abcdef", "não tem acesso", "Conexões"),
                 (self.fake.add_source("Contas"), "não é de uma página", "Copiar link"))
        for ref, msg, action in cases:
            with self.assertRaises(AppError) as e:
                self.page(ref)
            self.assertIn(msg, str(e.exception))
            self.assertIn(action, e.exception.action)
        trashed = self.fake.add_page("Velha")
        self.fake.pages[trashed]["in_trash"] = True
        with self.assertRaises(AppError) as e:
            self.page(trashed)
        self.assertIn("lixeira", str(e.exception))
        page = self.page(self.fake.add_page("Só leitura"))
        pv = self.preview(page)
        self.fake.read_only.add(page["id"])
        with self.assertRaises(AppError) as e:
            self.apply(pv, page)
        self.assertIn("não tem permissão para alterá-la", str(e.exception))
        self.assertIn("Atualizar conteúdo", e.exception.action)
        self.assertIsNone(self.fake.pages[page["id"]]["cover"])
        self.fake.read_only.clear()  # a permissão foi dada: a mesma prévia ainda vale
        self.assertEqual(self.apply(pv, page)["state"], "confirmed")
        self.fake.pages[page["id"]]["in_trash"] = True  # foi para a lixeira depois da prévia: nada é enviado
        n = len(self.fake.patches)
        with self.assertRaises(AppError) as e:
            self.apply(self.preview(page), page)
        self.assertIn("lixeira", str(e.exception))
        self.assertEqual(len(self.fake.patches), n)

    def test_other_page_theme_newer_expired_or_other_connection_is_refused(self):  # 14
        a, b = self.page(self.fake.add_page("A")), self.page(self.fake.add_page("B"))
        pv = self.preview(a)
        for page, kw, msg in ((b, {}, "outra página"), (a, {"theme": "outra coisa"}, "tema mudou")):
            r = self.apply(pv, page, **kw)
            self.assertEqual(r["state"], "regenerate")
            self.assertIn(msg, r["message"])
        pv2 = self.preview(a)
        self.assertIn("mais nova", self.apply(pv, a)["message"])
        with mock.patch.object(store, "get_token", return_value="secret_outro"):
            self.assertIn("conexão", self.apply(pv2, a)["message"])
        server._previews[pv2["preview_id"]]["at"] -= server.PREVIEW_TTL + 1
        self.assertIn("expirou", self.apply(pv2, a)["message"])
        self.assertIn("expirou", self.apply({"preview_id": "nao-existe", "theme": ""}, a)["message"])
        self.assertEqual((self.fake.patches, self.fake.uploads), ([], {}))  # nada escrito no Notion
        with self.assertRaises(AppError):  # a prévia de uma página não cria curso
            server._approved(pv2["preview_id"], "A")

    def test_double_click_and_failed_upload(self):  # 15
        page = self.page(self.fake.add_page("Metas"))
        pv, real, out = self.preview(page), notion.upload_image, []
        slow = lambda *a, **k: time.sleep(0.5) or real(*a, **k)  # noqa: E731

        def go():
            try:
                out.append(self.apply(pv, page)["state"])
            except AppError as e:
                out.append(str(e))
        with mock.patch.object(notion, "upload_image", slow):
            ts = [threading.Thread(target=go) for _ in range(2)]
            for t in ts:
                t.start()
                time.sleep(0.1)
            for t in ts:
                t.join()
        self.assertEqual(sorted(out), ["Já estou aplicando uma capa.", "confirmed"])
        self.assertEqual((len(self.fake.uploads), len(self.fake.patches)), (1, 1))
        page2 = self.page(self.fake.add_page("Planos"))
        pv2 = self.preview(page2)
        self.fake.fail_upload = True
        with self.assertRaises(AppError):
            self.apply(pv2, page2)
        self.assertEqual(len(self.fake.patches), 1)  # sem envio, a página não foi tocada
        self.fake.fail_upload = False
        self.assertEqual(self.apply(pv2, page2)["state"], "confirmed")  # a mesma prévia, sem gerar de novo
        self.assertEqual(self.render.call_count, 2)

    def lose_patch(self, applied):
        """PATCH de página sem resposta: o Notion pode ter feito (`applied`) ou não."""
        real = notion.request

        def flaky(method, path, token, body=None, once=False):
            if method == "PATCH" and path.startswith("/pages/"):
                if applied:
                    real(method, path, token, body, once)
                raise notion.Unconfirmed("Não foi possível confirmar o envio ao Notion.", "")
            return real(method, path, token, body, once)
        return mock.patch.object(notion, "request", flaky)

    def test_lost_response_is_checked_before_trying_again(self):  # 16
        page = self.page(self.fake.add_page("Viagem"))
        pv = self.preview(page)
        with self.lose_patch(applied=True):
            self.assertEqual(self.apply(pv, page)["state"], "confirmed")  # conferida pelos bytes, sem repetir
        self.assertEqual(len(self.fake.patches), 1)
        page2 = self.page(self.fake.add_page("Mudança"))
        pv2 = self.preview(page2)
        with self.lose_patch(applied=False):
            self.assertEqual(self.apply(pv2, page2)["state"], "unconfirmed")
        up = [u for u in self.fake.uploads if u not in {b["cover"]["file_upload"]["id"] for _, b in self.fake.patches}]
        self.assertEqual(len(up), 1)
        n = self.fake.calls.count(("POST", "/file_uploads"))
        self.assertEqual(self.apply(pv2, page2)["state"], "confirmed")  # confere, vê que não foi, reaproveita o envio
        self.assertEqual(self.fake.calls.count(("POST", "/file_uploads")), n)
        self.assertIn(("GET", f"/file_uploads/{up[0]}"), self.fake.calls)
        self.assertEqual(self.fake.pages[page2["id"]]["cover"]["file_upload"]["id"], up[0])

    def test_old_cover_that_stayed_is_never_a_success(self):  # 17
        pid = self.fake.add_page("Receitas")
        self.fake.pages[pid]["cover"] = {"type": "file_upload", "file_upload": {"id": self.fake.add_upload(OLD)}}
        page = self.page(pid)
        self.assertTrue(page["cover"].startswith("file:"))  # a página já tinha uma capa do tipo arquivo
        self.assertEqual(self.page(pid)["cover"], page["cover"])  # a assinatura nova da URL não muda a identidade
        pv = self.preview(page)
        self.fake.ignore_cover = True  # o Notion responde 200, mas a capa anterior continua
        r = self.apply(pv, page)
        self.assertEqual((r["state"], r["page"]["cover"]), ("mismatch", page["cover"]))
        self.fake.ignore_cover = False
        self.assertEqual(self.apply(pv, page)["state"], "confirmed")  # tentar de novo: confere, reenvia, confere
        self.assertEqual(len(self.fake.patches), 2)
        real = notion.urllib.request.urlopen

        def no_files(req, *a, **k):
            if "/files/" in getattr(req, "full_url", req):
                raise urllib.error.URLError("sem rede")
            return real(req, *a, **k)
        page2 = self.page(self.fake.add_page("Viagens"))
        pv2 = self.preview(page2)
        with mock.patch.object(notion.urllib.request, "urlopen", no_files):
            self.assertEqual(self.apply(pv2, page2)["state"], "unconfirmed")  # aplicou, mas não deu para conferir
            self.assertEqual(self.apply(pv2, page2)["state"], "unconfirmed")  # e não reenvia às cegas
        self.assertEqual(len(self.fake.patches), 3)
        self.assertEqual(self.apply(pv2, page2)["state"], "confirmed")  # conferida, sem outro PATCH
        self.assertEqual(len(self.fake.patches), 3)

    def test_cover_changed_since_the_page_was_chosen(self):  # 17
        pid = self.fake.add_page("Treinos")
        page = self.page(pid)
        self.fake.pages[pid]["cover"] = {"type": "external", "external": {"url": "https://www.notion.so/images/page-cover/rijksmuseum_1.jpg"}}
        pv = self.preview(page)
        r = self.apply(pv, page)
        self.assertEqual((r.get("changed"), r["page"]["cover"]), (True, "external:https://www.notion.so/images/page-cover/rijksmuseum_1.jpg"))
        self.assertEqual(self.fake.patches, [])  # avisou antes de substituir
        self.assertEqual(self.apply(pv, r["page"])["state"], "confirmed")  # o usuário viu e confirmou a troca

    def test_no_drawing_at_all_is_an_error_not_a_preview(self):
        self.render.return_value = None
        with self.assertRaises(AppError) as e:
            self.preview(self.page(self.fake.add_page("Livros")))
        self.assertIn("Não foi possível desenhar", str(e.exception))
        self.assertEqual(server._previews, {})


if __name__ == "__main__":
    unittest.main()
