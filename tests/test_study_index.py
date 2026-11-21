"""Lúmen Study AI: índice, conectores (Obsidian isolado, Notion falso) e busca híbrida. Tudo em dados isolados."""
import json
import shutil
import tempfile
import zlib
from pathlib import Path
from unittest import TestCase, mock

import numpy as np

import tests  # noqa: F401 — LUMEN_DATA isolado antes de importar o app
from lumen import AppError, notion, protection, store, vault
from lumen.study import db, index, providers, search, settings
from lumen.study.sources import notion as notion_source
from tests.fake_notion import Fake

# Embeddings falsos e determinísticos: palavras do mesmo "conceito" caem na mesma dimensão, então "hipocampo" fica
# perto de "memória" sem dividir nenhuma palavra (é o que a busca semântica precisa provar).
CONCEPTS = {"memori": 0, "hipoca": 0, "consol": 0, "lembra": 0, "behavi": 1, "condic": 1, "cognit": 2, "mental": 2}


def fake_embed(texts, model, query=False):
    out = []
    for t in texts:
        v = np.zeros(32, dtype=np.float32)
        for tok in vault.tokens(t):
            v[CONCEPTS.get(tok, 3 + zlib.crc32(tok.encode()) % 29)] += 1
        out.append(v.tolist())
    return out


class Base(TestCase):
    def stop_index(self):
        index.stop()
        if index._thread:
            index._thread.join(20)
            self.assertFalse(index._thread.is_alive(), "O índice anterior precisa parar antes de trocar a pasta da fixture")

    def setUp(self):
        self.stop_index()
        self.tmp = Path(tempfile.mkdtemp(prefix="lumen-study-"))
        self.vault = self.tmp / "Cérebro com espaço"
        (self.vault / ".obsidian").mkdir(parents=True)
        self.stack = [mock.patch.object(db, "HOME", self.tmp / "study"),
                      mock.patch.object(store, "load_config", lambda: {**store.DEFAULTS, "obsidian_vault": str(self.vault)}),
                      mock.patch.object(protection, "HOME", self.tmp / "protection"),
                      mock.patch.object(notion, "rate_wait", lambda delay=0: None)]
        for p in self.stack:
            p.start()
        index.bump()

    def tearDown(self):
        self.stop_index()
        db.close()
        for p in reversed(self.stack):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def note(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
        return p


class Chunks(TestCase):
    def test_headings_paths_code_and_size(self):
        text = "# Memória\nIntro.\n\n## Longo prazo\n" + ("Frase longa sobre consolidação. " * 80) + \
               "\n\n```python\n# não é título\nx = 1\n```\n\n## Curto prazo\nTexto."
        parts = index.chunks(text)
        headings = [h for h, _ in parts]
        self.assertIn("Memória › Longo prazo", headings)
        self.assertIn("Memória › Curto prazo", headings)
        self.assertNotIn("Memória › Longo prazo › não é título", headings)
        self.assertTrue(all(len(t) <= index.SIZE + index.OVERLAP + 2 for _, t in parts))
        self.assertTrue(any("x = 1" in t for _, t in parts))
        self.assertEqual(index.chunks(""), [])


class ObsidianIndex(Base):
    def build(self):
        self.note("B02 Estudos/Memória de longo prazo.md",
                  "---\ntags: [psicologia, memoria]\ntype: permanent\n---\n# Memória de longo prazo\n"
                  "A consolidação depende do sono. Ver [[Atenção]].\n#neurociencia")
        self.note("Atenção.md", "# Atenção\nFoco seletivo e memória de trabalho.")
        self.note("Behaviorismo.md", "Condicionamento operante e reforço.")
        self.note("Templates/Template - Nota.md", "modelo de memória")
        self.note(".obsidian/plugins/x.md", "memória escondida")
        self.note(".claude/skills/s.md", "memória da IA")
        self.note("Lumen - Backup do Notion/Página.md", "memória duplicada do Notion")
        (self.vault / "Lumen - Backup do Notion" / ".lumen-protection.json").write_text(
            json.dumps({"kind": "notion-mirror", "owner": "x"}), "utf-8")
        self.note("Gerada.md", "---\nlumen-protection-origin: notion\n---\nmemória gerada")

    def test_sync_respects_exclusions_and_is_incremental(self):
        self.build()
        stats = index.sync("obsidian")
        titles = {r["title"] for r in db.rows("SELECT title FROM documents")}
        self.assertEqual(titles, {"Memória de longo prazo", "Atenção", "Behaviorismo"})
        self.assertEqual(stats["documents"], 3)
        doc = db.one("SELECT * FROM documents WHERE title = 'Memória de longo prazo'")
        self.assertEqual(doc["author"], "user")
        self.assertIn("neurociencia", json.loads(doc["tags"]))
        self.assertIn("Atenção", json.loads(doc["links"]))
        # nada mudou: nada é relido
        self.assertEqual(index.sync("obsidian")["updated"], 0)
        # uma nota alterada e uma apagada
        self.note("Atenção.md", "# Atenção\nFoco seletivo, alerta e memória de trabalho. Texto novo.")
        (self.vault / "Behaviorismo.md").unlink()
        stats = index.sync("obsidian")
        self.assertEqual((stats["updated"], stats["removed"], stats["documents"]), (1, 1, 2))
        self.assertIn("alerta", " ".join(r["text"] for r in db.rows("SELECT text FROM chunks")))
        self.assertEqual(db.value("SELECT COUNT(*) FROM chunks_fts"), db.value("SELECT COUNT(*) FROM chunks"))

    def test_lexical_semantic_and_hybrid(self):
        self.build()
        index.sync("obsidian")
        with mock.patch.object(providers, "embed_ready", return_value=False):
            r = search.search("memória de longo prazo")
        self.assertEqual(r["results"][0]["title"], "Memória de longo prazo")
        self.assertFalse(r["semantic"])
        self.assertTrue(any("título" in x.casefold() for x in r["results"][0]["reasons"]))
        self.assertTrue(0 < r["results"][-1]["relevance"] <= r["results"][0]["relevance"] == 1)
        with mock.patch.object(providers, "embed_ready", return_value=True), mock.patch.object(providers, "embed", fake_embed):
            self.assertGreater(index.embed_missing(), 0)
            self.assertEqual(index.embed_missing(), 0)  # nada falta
            r = search.search("hipocampo")  # nenhuma nota tem essa palavra
        self.assertTrue(r["semantic"])
        self.assertEqual(r["results"][0]["title"], "Memória de longo prazo")
        self.assertTrue(any("Significado" in x for x in r["results"][0]["reasons"]))
        # links: a nota citada aparece como conexão quando não está entre os resultados
        with mock.patch.object(providers, "embed_ready", return_value=False):
            r = search.search("consolidação sono", limit=1)
        self.assertEqual([x["title"] for x in r["related"]], ["Atenção"])

    def test_same_content_is_one_result_and_purge_keeps_originals(self):
        self.build()
        self.note("Cópia/Memória de longo prazo.md", (self.vault / "B02 Estudos/Memória de longo prazo.md").read_text("utf-8"))
        index.sync("obsidian")
        with mock.patch.object(providers, "embed_ready", return_value=False):
            r = search.search("consolidação")
        first = r["results"][0]
        self.assertEqual(len(first["also_in"]), 1)
        self.assertEqual(sum(1 for x in r["results"] if x["title"] == "Memória de longo prazo"), 1)
        self.assertEqual(index.purge("obsidian"), 4)
        self.assertEqual(db.value("SELECT COUNT(*) FROM chunks_fts"), 0)
        self.assertTrue((self.vault / "Atenção.md").is_file())

    def test_failed_listing_never_deletes(self):
        self.build()
        index.sync("obsidian")
        with mock.patch.object(vault, "check", side_effect=AppError("A pasta do cofre do Obsidian não existe mais.")):
            with self.assertRaises(AppError):
                index.sync("obsidian")
        self.assertEqual(db.value("SELECT COUNT(*) FROM documents"), 3)
        self.assertEqual(index.source_view("obsidian")["state"], "error")


class NotionIndex(Base):
    def setUp(self):
        super().setUp()
        self.fake = Fake()
        self.stack.append(mock.patch.object(store, "get_token", return_value="secret_test"))
        self.stack[-1].start()

    def tearDown(self):
        self.fake.close()
        super().tearDown()

    def rich(self, text):
        return [{"type": "text", "text": {"content": text, "link": None}, "plain_text": text, "href": None, "annotations": {}}]

    def block(self, kind, text, children=None, **extra):
        bid = str(__import__("uuid").uuid4())
        b = {"id": bid, "object": "block", "type": kind, "has_children": bool(children),
             kind: {"rich_text": self.rich(text), **extra, **({"children": children} if children else {})}}
        if children:
            self.fake.blocks[bid] = b
        return b

    def test_hierarchy_pagination_and_exclusions(self):
        f = self.fake
        main = f.add_page("Psicologia cognitiva")
        f.pages[main]["blocks"] = [
            self.block("heading_2", "Memória"),
            self.block("bulleted_list_item", "Tipos", [self.block("bulleted_list_item", "Episódica"),
                                                       self.block("to_do", "Revisar Baddeley", checked=True)]),
            self.block("code", "print('oi')", language="python"),
        ] + [self.block("paragraph", f"Parágrafo {i}") for i in range(130)]  # mais de 100 filhos: paginado
        mirror = f.add_page("Backup do Obsidian")
        child = f.add_page("Nota espelhada", parent=mirror)
        trashed = f.add_page("Na lixeira")
        f.pages[trashed]["in_trash"] = True
        for i in range(103):  # mais de 100 páginas: a enumeração pagina
            f.add_page(f"Página vazia {i}")
        (self.tmp / "protection").mkdir(parents=True)
        (self.tmp / "protection" / "notion-mirror.json").write_text(json.dumps({"k": {"id": mirror}}), "utf-8")
        stats = index.sync("notion")
        ids = {r["source_id"] for r in db.rows("SELECT source_id FROM documents WHERE source = 'notion'")}
        self.assertIn(notion.page_id(main), ids)
        self.assertNotIn(notion.page_id(mirror), ids)
        self.assertNotIn(notion.page_id(child), ids)
        self.assertNotIn(notion.page_id(trashed), ids)
        self.assertEqual(stats["documents"], 104)
        text = "\n".join(r["text"] for r in db.rows("""SELECT c.text FROM chunks c JOIN documents d ON d.id = c.doc_id
                                                       WHERE d.title = 'Psicologia cognitiva' ORDER BY c.ord"""))
        self.assertIn("- Tipos\n  - Episódica\n  - [x] Revisar Baddeley", text)
        self.assertIn("```python", text)
        self.assertIn("Parágrafo 129", text)  # veio da segunda página de filhos
        self.assertEqual(f.violations, [])
        # incremental: sem edição, nenhum bloco é relido
        calls = len(f.calls)
        self.assertEqual(index.sync("notion")["updated"], 0)
        self.assertFalse(any(path.endswith("/children") for _, path in f.calls[calls:]))
        f.pages[main]["edited"] = "2026-10-30T12:00:00.000Z"
        self.assertEqual(index.sync("notion")["updated"], 1)

    def test_markdown_converter_keeps_structure(self):
        table = {"id": "t", "type": "table", "has_children": True, "table": {},
                 "children": [{"type": "table_row", "table_row": {"cells": [self.rich("A"), self.rich("B")]}},
                              {"type": "table_row", "table_row": {"cells": [self.rich("1"), self.rich("2")]}}]}
        md = notion_source.markdown([self.block("quote", "Citação"), table,
                                     {"type": "child_page", "id": "p1", "child_page": {"title": "Sub"}}])
        self.assertIn("> Citação", md)
        self.assertIn("| A | B |\n| --- | --- |\n| 1 | 2 |", md)
        self.assertIn("[Subpágina: Sub]", md)


class Settings(Base):
    def test_validation_and_secret(self):
        s = settings.save({"search": {"max_sources": 99, "notion": False}, "models": {"temperature": 3}, "nope": {"x": 1}})
        self.assertEqual((s["search"]["max_sources"], s["search"]["notion"], s["models"]["temperature"]), (20, False, 1.0))
        with self.assertRaises(AppError):
            settings.save({"models": {"provider": "inexistente"}})
        with self.assertRaises(AppError):
            settings.save({"privacy": {"organize": "talvez"}})
        with mock.patch.object(settings, "api_key", return_value="sk-ant-segredo"):
            public = settings.public()
        self.assertTrue(public["has_anthropic_key"])
        self.assertNotIn("sk-ant-segredo", json.dumps(public))
