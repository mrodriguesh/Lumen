"""Obsidian: StudyPackage, nota (renderer + writer), Canvas, conexões, revisões e segurança, num cofre temporário."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, canvas, llm, obsidian, package, store, vault
from tests.test_llm import ANALYSIS, NOTE

RAW = {
    "title": "RAG: busca + geração", "summary": "RAG busca trechos e gera respostas com eles.\n\nReduz invenções.",
    "simple_explanation": "Como consultar um livro antes de responder.\n\nA IA lê e depois fala.",
    "topics": [{"title": "Embeddings", "explanation": "Vetores que guardam o sentido.", "why": "Permitem buscar por "
                "sentido.", "timestamp": "[00:40]"},
               {"title": "Banco vetorial", "explanation": "Guarda e busca vetores.", "why": "", "timestamp": ""}],
    "glossary": [{"term": "Embedding", "definition": "Vetor que representa o sentido de um texto."}],
    "examples": [{"text": "Busca em manuais", "origin": "aula"}, {"text": "Um bibliotecário", "origin": "didatico"}],
    "steps": ["Dividir os documentos", "Gerar embeddings", "Buscar os trechos", "Gerar a resposta"],
    "review_questions": [{"kind": "recordacao", "question": "O que é RAG?", "answer": "Busca + geração."},
                         {"kind": "diagnostico", "question": "E sem a busca?", "answer": "A IA inventa mais."},
                         {"kind": "relacao", "question": "Embeddings e banco vetorial?", "answer": "Um guarda o outro."}],
    "key_moments": [{"timestamp": "01:05", "label": "Exemplo dos manuais"}], "caveats": ["Reranking ficou confuso."],
    "map_kind": "sistema",
    "mind_map": {"center": "RAG", "branches": [
        {"label": "Recuperação", "emoji": "🔎", "children": ["Embeddings", "Banco vetorial"]},
        {"label": "Geração", "emoji": "🧠", "children": ["LLM", "Contexto da pergunta"]}]},
    "relations": [{"from": "Recuperação", "type": "leva a", "to": "Geração"},
                  {"from": "Embeddings", "type": "parte de", "to": "Algo que não está no mapa"}],
    "mistakes": ["Achar que RAG treina o modelo."], "applications": ["Chat com documentos da empresa."],
    "open_questions": ["Como escolher o tamanho dos trechos?"],
    "permanent_ideas": ["Buscar antes de gerar reduz invenção."],
}
SRC = {"key": "yt:dQw4w9WgXcQ", "kind": "youtube", "label": "YouTube", "title": "Aula de RAG",
       "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "yt_id": "dQw4w9WgXcQ"}
TR = {"duration": 600, "language": "pt", "origin": "Transcrição importada.",
      "segments": [{"start": 0, "end": 5, "text": "oi"}]}
MINE = {"original_understanding": NOTE, "current_understanding": NOTE, "ai_analysis": ANALYSIS,
        "submitted": "2026-10-23T10:00:00", "model": "m", "analyzed_text": NOTE, "earlier": []}
LINKS = {"links": [{"note": "Busca semântica", "relation": "fundamenta", "reason": "RAG depende de busca por sentido."},
                   {"note": "Projeto Lumen", "relation": "usado no projeto", "reason": "O Lumen busca no cofre."},
                   {"note": "Nota Inventada", "relation": "relacionado", "reason": "não existe"}],
         "anchors": ["Inteligência Artificial"], "anchor_suggestion": ""}


def lesson(**kw):
    return llm.validate({**RAW, **kw}, duration=600)


def make_vault(root):
    files = {
        "A02 Anchor Topics/Inteligência Artificial.md": "---\ntype: anchor\nauthor: user\n---\n> [!info]- x\n# IA\n",
        "A02 Anchor Topics/Notas permanentes/Busca semântica.md":
            "---\ntype: permanent\nauthor: user\n---\nBusca por sentido com embeddings e vetores.\n",
        "B01 Projects/Projeto Lumen.md": "---\ntype: project\nauthor: user\n---\nApp de estudos que usa embeddings.\n",
        "B05 Systems/Templates/Template - Nota Permanente.md": "---\ntype: permanent\n---\nembeddings embeddings\n",
        "B05 Systems/Sistema - Estudos.md": "---\ntype: system\n---\nembeddings e RAG\n",
        "B03 Resources/Receita de bolo.md": "---\ntype: resource\n---\nFarinha, ovos e açúcar.\n",
    }
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    (Path(root) / ".obsidian").mkdir()
    for i in list(range(16)) + [99]:
        (Path(root) / "C04 Claude Obsidian" / f"{i:02d} Pasta").mkdir(parents=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lumen-vault-")
        self.root = Path(self.tmp) / "Cérebro com espaço"
        self.root.mkdir()
        make_vault(self.root)
        self.cfg = {**store.DEFAULTS, "destinations": "obsidian", "obsidian_vault": str(self.root)}
        self.patch = mock.patch.object(store, "get_token", return_value="secret_ABCDEFGHIJKLMNOPQRSTUV")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pkg(self, les=None, links=LINKS, mine=MINE, today=date(2026, 10, 23)):
        p = package.build(SRC, TR, les or lesson(), dict(mine), links=json.loads(json.dumps(links)), course="IA",
                          model="qwen3:8b", intervals=self.cfg["review_intervals"], today=today)
        return package.validate(p, [n["name"] for n in vault.index(self.root)])

    def deliver(self, p=None, **kw):
        return obsidian.deliver(p or self.pkg(), self.cfg, **kw)

    def read(self, rel):
        return (self.root / rel).read_text("utf-8")


class Package(Base):
    def test_human_and_ai_stay_apart_and_hash_is_stable(self):
        a, b = self.pkg(), self.pkg()
        self.assertEqual(a["content_hash"], b["content_hash"])
        self.assertEqual(a["understanding"]["original_understanding"], NOTE)
        self.assertNotIn("original_understanding", a["lesson"])
        other = self.pkg(mine={**MINE, "current_understanding": NOTE + " Mais uma frase minha."})
        self.assertNotEqual(a["content_hash"], other["content_hash"])
        self.assertEqual(a["lumen_id"], package.lumen_id(SRC["key"]))

    def test_validator_cleans_relations_links_and_secrets(self):
        p = self.pkg(les=lesson(summary="Use o token secret_ABCDEFGHIJKLMNOPQRSTUV e sk-abcdefghijklmnopqrstuvwxyz12"))
        self.assertEqual([r["to"] for r in p["lesson"]["relations"]], ["Geração"])
        self.assertEqual([c["note"] for c in p["connections"]], ["Busca semântica", "Projeto Lumen"])
        self.assertNotIn("secret_ABC", json.dumps(p))
        self.assertNotIn("sk-abc", json.dumps(p))
        self.assertIn(package.REDACTED, p["lesson"]["summary"])

    def test_validator_refuses_incomplete(self):
        p = package.build(SRC, TR, lesson(), {**MINE, "original_understanding": " "})
        with self.assertRaises(AppError):
            package.validate(p)
        bad = lesson()
        bad["review_questions"].append({"kind": "", "question": "Sem resposta?", "answer": ""})
        with self.assertRaises(AppError):
            package.validate(package.build(SRC, TR, bad, MINE))

    def test_flashcards_and_timeline_never_invent_times(self):
        p = self.pkg()
        self.assertIn({"front": "Embedding", "back": "Vetor que representa o sentido de um texto."}, p["flashcards"])
        self.assertIn({"front": "O que é RAG?", "back": "Busca + geração."}, p["flashcards"])
        self.assertEqual(p["timeline"], [{"t": 65, "label": "Exemplo dos manuais"}])
        self.assertEqual(p["review_dates"][:2], ["2026-10-24", "2026-10-26"])


class Note(Base):
    def test_note_canvas_and_dashboard_are_created_and_valid(self):
        out = self.deliver()
        self.assertEqual(out["state"], "created")
        self.assertEqual(out["note"], "C04 Claude Obsidian/16 Lumen/2026-10-23 - RAG busca + geração.md")
        self.assertEqual(out["canvas"], "C04 Claude Obsidian/16 Lumen/Mapa - RAG busca + geração.canvas")
        text = self.read(out["note"])
        fm = vault.fields(vault.split(text)[0])
        self.assertEqual((fm["type"], fm["author"], fm["status"]), ("ai-study", "lumen-ai", "review-required"))
        self.assertEqual(fm["topics"], ["[[Inteligência Artificial]]"])
        self.assertEqual(fm["related"], ["[[Busca semântica]]", "[[Projeto Lumen]]"])
        self.assertEqual(fm["aliases"], ["RAG busca + geração"])
        self.assertEqual((fm["next-review"], fm["review-stage"]), ("2026-10-24", "0"))
        self.assertEqual(fm["lumen-id"], package.lumen_id(SRC["key"]))
        self.assertTrue(re.match(r"---\n.*?\n---\n\n> \[!info\]- Como usar esta nota", text, re.S))
        self.assertIn("> [!warning] Conteúdo gerado por IA", text)
        self.assertIn("![[Mapa - RAG busca + geração.canvas]]", text)
        self.assertIn("> [!quote] Minha nota original\n> " + NOTE[:40], text)  # a nota do estudante, intacta
        self.assertIn("> [!question]- O que é RAG?\n> *Recordação* · Busca + geração.", text)
        self.assertIn("## Teste de compreensão", text)
        self.assertIn("[00:40](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=40s)", text)
        self.assertIn("- [ ] Revisão 1 · 2026-10-24", text)
        self.assertIn("- [ ] Buscar antes de gerar reduz invenção.", text)
        self.assertIn("[[Template - Nota Permanente]]", text)
        self.assertNotIn("Nota Inventada", text)
        self.assertNotIn("🔎", text)  # sem emojis decorativos (preferência do cofre)
        known = {f.name.casefold() for f in self.root.rglob("*")} | {f.stem.casefold() for f in self.root.rglob("*")}
        self.assertEqual(obsidian.check(text, known), [])
        cv = json.loads(self.read(out["canvas"]))
        self.assertEqual(canvas.check(cv), [])
        self.assertEqual([n["file"] for n in cv["nodes"] if n["type"] == "file"][0], out["note"])
        self.assertIn("leva a", [e.get("label") for e in cv["edges"]])
        self.assertTrue((self.root / "C04 Claude Obsidian/16 Lumen/Lumen Dashboard.md").exists())
        self.assertFalse([p for p in self.root.rglob("*") if p.name.endswith(".lumen-tmp")])

    def test_ai_text_cannot_create_links_tags_comments_or_html(self):
        les = lesson(summary="Veja [[Falsa]] e #tag e %% fim %% e <script>x</script> e `=this.file`",
                     glossary=[{"term": "A|B", "definition": "pipe | na tabela"}])
        text = self.read(self.deliver(self.pkg(les))["note"])
        self.assertNotRegex(text, r"(?<!\\)\[\[Falsa")
        self.assertIn("[\\[Falsa]]", text)
        self.assertIn("\\#tag", text)
        self.assertNotIn("<script>", text)
        self.assertIn("% % fim % %", text)
        self.assertIn("| **A\\|B** | pipe \\| na tabela |", text)
        self.assertIn("`\u200b=this.file`", text)

    def test_reprocessing_is_idempotent(self):
        first = self.deliver()
        before = self.read(first["note"])
        again = self.deliver(prev=first)
        self.assertEqual(again["state"], "unchanged")
        self.assertEqual(self.read(first["note"]), before)
        self.assertEqual(len(list((self.root / "C04 Claude Obsidian/16 Lumen").glob("*.md"))), 2)  # nota + painel
        self.assertEqual(len(list(self.root.rglob("*.canvas"))), 1)

    def test_update_keeps_user_notes_keys_status_and_checked_boxes(self):
        first = self.deliver()
        path = self.root / first["note"]
        text = path.read_text("utf-8")
        text = text.replace("status: review-required", "status: completed").replace("type: ai-study", "type: ai-study\nminha-chave: valor")
        text = text.replace("- [ ] Revisão 1 · 2026-10-24", "- [x] Revisão 1 · 2026-10-24")
        text = text.replace("- [ ] Buscar antes", "- [x] Buscar antes")
        text += "\nMinha anotação pessoal que o Lumen não pode apagar.\n"
        path.write_text(text, "utf-8")
        out = self.deliver(self.pkg(lesson(summary="Resumo novo da aula reprocessada.")), prev=first)
        self.assertEqual(out["state"], "updated")
        new = path.read_text("utf-8")
        self.assertIn("Minha anotação pessoal que o Lumen não pode apagar.", new)
        self.assertIn("minha-chave: valor", new)
        self.assertIn("status: completed", new)
        self.assertIn("- [x] Revisão 1 · 2026-10-24", new)
        self.assertIn("- [x] Buscar antes de gerar reduz invenção.", new)
        self.assertIn("Resumo novo da aula reprocessada.", new)
        self.assertEqual(new.count("%% lumen:begin"), 1)
        self.assertTrue(list((store.DATA / "obsidian-backups").rglob("*.md")))

    def test_edit_inside_the_block_is_a_conflict_until_forced(self):
        first = self.deliver()
        path = self.root / first["note"]
        edited = path.read_text("utf-8").replace("Reduz invenções.", "Reduz invenções (anotei aqui).")
        path.write_text(edited, "utf-8")
        with self.assertRaises(AppError) as e:
            self.deliver(self.pkg(lesson(summary="Outro resumo.")), prev=first)
        self.assertIn("editada dentro do bloco", str(e.exception))
        self.assertEqual(path.read_text("utf-8"), edited)  # nada gravado
        out = self.deliver(self.pkg(lesson(summary="Outro resumo.")), prev=first, force=True)
        self.assertEqual(out["state"], "updated")
        self.assertIn("Outro resumo.", path.read_text("utf-8"))
        backups = list((store.DATA / "obsidian-backups").rglob("*.md"))
        self.assertTrue(any("anotei aqui" in b.read_text("utf-8") for b in backups))

    def test_renamed_note_is_found_by_lumen_id(self):
        first = self.deliver()
        new = self.root / "C04 Claude Obsidian/16 Lumen/Sub/Meu nome.md"
        new.parent.mkdir()
        os.replace(self.root / first["note"], new)
        out = self.deliver(self.pkg(lesson(summary="Mudou.")), prev=first)
        self.assertEqual(out["note"], "C04 Claude Obsidian/16 Lumen/Sub/Meu nome.md")
        self.assertIn("Mudou.", new.read_text("utf-8"))
        self.assertEqual(len(list(self.root.rglob("2026-10-23 - *.md"))), 0)

    def test_note_moved_out_of_the_lumen_folder_is_not_touched(self):
        first = self.deliver()
        dest = self.root / "B03 Resources/Minha nota.md"
        os.replace(self.root / first["note"], dest)
        before = dest.read_text("utf-8")
        with self.assertRaises(AppError):
            self.deliver(prev=first)
        self.assertEqual(dest.read_text("utf-8"), before)

    def test_name_collision_uses_the_course_never_a_counter(self):
        (self.root / "Outra pasta").mkdir()
        (self.root / "Outra pasta/2026-10-23 - RAG busca + geração.md").write_text("minha", "utf-8")
        out = self.deliver()
        self.assertEqual(Path(out["note"]).name, "2026-10-23 - RAG busca + geração (IA).md")
        self.assertEqual(self.read("Outra pasta/2026-10-23 - RAG busca + geração.md"), "minha")

    def test_canvas_failure_keeps_the_note_without_a_broken_embed(self):
        with mock.patch.object(canvas, "check", return_value=["sobreposição: a × b"]):
            out = self.deliver()
        self.assertIn("mapa mental", out["canvas_error"])
        self.assertNotIn(".canvas]]", self.read(out["note"]))

    def test_frontmatter_only_update(self):
        out = self.deliver()
        obsidian.set_fields(self.root / out["note"], {"notion": "https://notion.so/abc"})
        fm = vault.fields(vault.split(self.read(out["note"]))[0])
        self.assertEqual(fm["notion"], "https://notion.so/abc")
        self.assertEqual(self.deliver(prev=out)["state"], "unchanged")  # mudar o frontmatter não é editar o bloco
        self.assertIn('notion: "https://notion.so/abc"', self.read(out["note"]))  # nem apaga o link


class Paths(Base):
    def test_folders_outside_the_vault_or_hidden_are_refused(self):
        for bad in ("../fora", "C:/Windows", "/etc", ".obsidian", "C04 Claude Obsidian/../../fora", "a/.trash/b"):
            with self.subTest(bad), self.assertRaises(AppError):
                obsidian.folders({**self.cfg, "obsidian_folder": bad})
        with self.assertRaises(AppError):
            obsidian.folders({**self.cfg, "obsidian_vault": self.tmp})  # sem .obsidian: não é cofre
        root, notes, maps = obsidian.folders(self.cfg)
        self.assertEqual(notes, root / "C04 Claude Obsidian" / "16 Lumen")
        self.assertEqual(maps, notes)

    @unittest.skipUnless(os.name == "nt", "junction é do Windows")
    def test_junction_pointing_outside_is_refused(self):
        outside = Path(self.tmp) / "fora"
        outside.mkdir()
        link = self.root / "C04 Claude Obsidian" / "Atalho"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=True)
        with self.assertRaises(AppError):
            obsidian.folders({**self.cfg, "obsidian_folder": "C04 Claude Obsidian/Atalho"})

    def test_file_names(self):
        self.assertEqual(obsidian.clean('Aula 01: RAG/Vetores <x>? "y" #1 [a]|b^'), "Aula 01 RAG Vetores x y 1 a b")
        self.assertEqual(obsidian.clean("Programação é fácil."), "Programação é fácil")
        self.assertEqual(obsidian.clean("CON"), "CON (aula)")
        self.assertEqual(obsidian.clean("   "), "Aula")
        self.assertEqual(len(obsidian.clean("x" * 300)), 100)

    def test_long_title_keeps_the_path_short(self):
        out = self.deliver(self.pkg(lesson(title="Um título muito comprido " * 12)))
        self.assertLess(len(str(self.root / out["note"])), 260)


class Canvas(unittest.TestCase):
    def pkg(self, n, long=False):
        text = "Uma explicação bem mais longa que ocupa várias linhas no cartão do mapa " * (3 if long else 0)
        mm = {"center": "Tema", "branches": [{"label": f"Ramo {i} {text[:40]}", "emoji": "",
                                              "children": [f"Filho {i}.{j} {text}" for j in range(i % 4 + 1)]}
                                             for i in range(n)]}
        les = lesson(mind_map=mm, relations=[{"from": "Ramo 0 " + text[:40], "type": "causa", "to": "Tema"}])
        p = package.build(SRC, TR, les, MINE, links=LINKS, course="IA")
        return package.validate(p, ["Busca semântica", "Projeto Lumen", "Inteligência Artificial"])

    def test_layout_has_no_overlaps_and_valid_edges(self):
        files = {"Busca semântica": "A/Busca semântica.md", "Projeto Lumen": "B/Projeto Lumen.md",
                 "Inteligência Artificial": "A/Inteligência Artificial.md"}
        for n in range(2, 9):
            for long in (False, True):
                with self.subTest(n=n, long=long):
                    c = canvas.build(self.pkg(n, long), "Lumen/Aula.md", files)
                    self.assertEqual(canvas.check(c), [])
                    kinds = {x["type"] for x in c["nodes"]}
                    self.assertEqual(kinds, {"file", "text", "group", "link"})
                    self.assertEqual(c["nodes"][0]["type"], "group")  # grupos primeiro: ficam atrás dos cards

    def test_ids_are_stable_and_merge_keeps_what_the_user_did(self):
        p = self.pkg(3)
        a, b = canvas.build(p, "L/A.md"), canvas.build(p, "L/A.md")
        self.assertEqual(a, b)
        moved = json.loads(json.dumps(a))
        leaf = next(n for n in moved["nodes"] if n["type"] == "text" and "Filho" in n.get("text", ""))
        leaf.update(x=5000, y=5000, width=400)
        moved["nodes"].append({"id": "meu-card", "type": "text", "text": "meu", "x": 0, "y": 9000, "width": 200, "height": 80})
        moved["edges"].append({"id": "minha-seta", "fromNode": "meu-card", "toNode": leaf["id"]})
        merged = canvas.merge(moved, canvas.build(self.pkg(4), "L/A.md"))
        got = {n["id"]: n for n in merged["nodes"]}
        self.assertEqual((got[leaf["id"]]["x"], got[leaf["id"]]["width"]), (5000, 400))
        self.assertIn("meu-card", got)
        self.assertIn("minha-seta", [e["id"] for e in merged["edges"]])
        self.assertEqual(canvas.check(merged, layout=False), [])

    def test_check_finds_problems(self):
        bad = {"nodes": [{"id": "a", "type": "text", "text": "x", "x": 0, "y": 0, "width": 100, "height": 100},
                         {"id": "b", "type": "text", "text": "y", "x": 50, "y": 50, "width": 100, "height": 100},
                         {"id": "c", "type": "nada", "x": 0, "y": 0, "width": 10, "height": 10}],
               "edges": [{"id": "e", "fromNode": "a", "toNode": "z"}]}
        probs = " ".join(canvas.check(bad))
        for word in ("sobreposição", "card inválido", "inexistente", "pequeno"):
            self.assertIn(word, probs)


class Reviews(Base):
    def test_checked_reviews_move_the_next_date(self):
        out = self.deliver()
        path = self.root / out["note"]
        path.write_text(path.read_text("utf-8").replace("- [ ] Revisão 1", "- [x] Revisão 1"), "utf-8")
        self.assertEqual(obsidian.sync_reviews(self.cfg), 1)
        fm = vault.fields(vault.split(path.read_text("utf-8"))[0])
        self.assertEqual((fm["review-stage"], fm["next-review"]), ("1", "2026-10-26"))
        text = path.read_text("utf-8")
        path.write_text(re.sub(r"- \[ \] Revisão", "- [x] Revisão", text), "utf-8")
        obsidian.sync_reviews(self.cfg)
        fm = vault.fields(vault.split(path.read_text("utf-8"))[0])
        self.assertEqual(fm["review-stage"], "6")
        self.assertNotIn("next-review", fm)
        self.assertEqual(obsidian.sync_reviews(self.cfg), 0)
        self.assertEqual(self.deliver(prev=out)["state"], "unchanged")  # marcar revisões não é conflito nem recomeço
        self.assertNotIn("next-review", vault.fields(vault.split(path.read_text("utf-8"))[0]))

    def test_intervals_come_from_the_config(self):
        self.cfg["review_intervals"] = [2, 5]
        text = self.read(self.deliver()["note"])
        self.assertIn("- [ ] Revisão 2 · 2026-10-28", text)
        self.assertNotIn("Revisão 3", text)


class Vault(Base):
    def test_registered_vaults_and_default_folder(self):
        appdata = Path(self.tmp) / "appdata"
        (appdata / "obsidian").mkdir(parents=True)
        (appdata / "obsidian" / "obsidian.json").write_text(json.dumps({"vaults": {
            "a": {"path": str(self.root), "open": True}, "b": {"path": str(Path(self.tmp) / "sumiu")}}}), "utf-8")
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
            got = vault.vaults()
        self.assertEqual([(v["name"], v["open"], v["ok"]) for v in got], [("Cérebro com espaço", True, True),
                                                                           ("sumiu", False, False)])
        self.assertEqual(vault.default_folder(self.root), "C04 Claude Obsidian/16 Lumen")

    def test_search_ranks_meaning_words_and_skips_templates_and_system(self):
        notes = vault.index(self.root)
        got = [n["name"] for n in vault.search(notes, [("embeddings vetores busca", 2)])]
        self.assertEqual(got[0], "Busca semântica")
        self.assertNotIn("Template - Nota Permanente", got)
        self.assertNotIn("Sistema - Estudos", got)
        self.assertNotIn("Receita de bolo", got)
        self.assertEqual([n["name"] for n in vault.anchors(notes)], ["Inteligência Artificial"])

    @unittest.skipUnless(shutil.which("node") and Path(r"D:\downloads\cerebro\Cerebro Oficial\.claude\scripts\vault-check.mjs").exists(),
                         "checker do cofre do usuário")
    def test_vault_checker_of_the_users_vault_accepts_the_output(self):
        self.deliver()
        r = subprocess.run(["node", r"D:\downloads\cerebro\Cerebro Oficial\.claude\scripts\vault-check.mjs",
                            str(self.root)], capture_output=True, text=True, encoding="utf-8")
        errors = r.stdout.split("## Links amb")[0]  # links quebrados, frontmatter e callout; órfãs são só aviso
        self.assertEqual([ln for ln in errors.splitlines() if "Lumen" in ln], [], r.stdout)


class Connect(unittest.TestCase):
    def test_only_candidates_can_come_back(self):
        answer = {"links": [{"note": "Busca semântica", "relation": "fundamenta", "reason": "Base da busca."},
                            {"note": "Inventada", "relation": "aplica", "reason": "x"},
                            {"note": "Busca semântica", "relation": "aplica", "reason": "repetida"}],
                  "anchors": ["Inteligência Artificial", "Outra"], "anchor_suggestion": "ignorado"}
        seen = {}

        def fake(model, system, user, check, tokens, schema=None, **kw):
            seen["schema"] = schema
            return json.dumps(answer)
        with mock.patch.object(llm, "_chat", side_effect=fake):
            out = llm.connect(lesson(), [{"name": "Busca semântica", "kind": "Nota permanente", "excerpt": "e"}],
                              [{"name": "Inteligência Artificial", "kind": "Anchor Topic", "excerpt": ""}], "m", "pt",
                              lambda: None, lambda *a: None)
        self.assertEqual(seen["schema"]["properties"]["links"]["items"]["properties"]["note"]["enum"], ["Busca semântica"])
        self.assertEqual(out, {"links": [{"note": "Busca semântica", "reason": "Base da busca.", "relation": "fundamenta"}],
                               "anchors": ["Inteligência Artificial"], "anchor_suggestion": ""})

    def test_deep_mode_refines_and_keeps_first_version_on_failure(self):
        segs = [{"start": 0, "end": 75, "text": "aula"}]
        better = {**RAW, "summary": "Resumo revisado."}
        with mock.patch.object(llm, "_chat", side_effect=[json.dumps(RAW), json.dumps(better)]) as chat:
            out = llm.generate(segs, 75, "m", "pt", lambda: None, lambda *a: None, understanding=NOTE, deep=True)
        self.assertEqual((out["summary"], out["refined"], chat.call_count), ("Resumo revisado.", True, 2))
        with mock.patch.object(llm, "_chat", side_effect=[json.dumps(RAW), "{quebrado"]):
            out = llm.generate(segs, 75, "m", "pt", lambda: None, lambda *a: None, understanding=NOTE, deep=True)
        self.assertNotIn("refined", out)


if __name__ == "__main__":
    unittest.main()
