"""Área de estudos: curso → módulo → aula, conteúdo gratuito, aulas avulsas, A organizar; mover, renomear, reprocessar,
migrar a pasta antiga do Lumen (com rollback) e segurança dos caminhos, num cofre temporário."""
import hashlib
import json
import os
import re
import subprocess
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import AppError, area, canvas, catalog, obsidian, package, store, vault
from tests.test_board import SCREENS, jpeg
from tests.test_obsidian import LINKS, MINE, SRC, TR, Base, lesson


class Area(Base):
    def setUp(self):
        super().setUp()
        (store.DATA / "catalog.json").unlink(missing_ok=True)
        (store.DATA / "history.json").unlink(missing_ok=True)
        (store.DATA / area.JOURNAL).unlink(missing_ok=True)
        self.home = self.root / "Estudos"

    def make(self, cls=None, les=None, screens=SCREENS):
        p = package.build(SRC, TR, les or lesson(), dict(MINE), screens=screens, links=json.loads(json.dumps(LINKS)),
                          classification=catalog.classification(cls), model="m",
                          intervals=self.cfg["review_intervals"], today=date(2026, 10, 23))
        return package.validate(p, [n["name"] for n in vault.index(self.root)])

    def assets(self, p):
        return {"screens": {s["id"]: jpeg(s["id"] + 1) for s in p["screens"]}, "charts": []}

    def put(self, cls=None, prev=None, move=False, les=None):
        p = self.make(cls, les)
        return obsidian.deliver(p, self.cfg, self.assets(p), prev=prev, move=move)

    def course(self, name="Edição de Vídeos", **kw):
        return catalog.create_course(name, **kw)

    def files_ok(self, out):
        """Tudo o que a aula referencia existe: nota, Canvas, imagens dos Canvas, anexos do manifesto."""
        for k in ("note", "canvas", "board"):
            if out.get(k):
                self.assertTrue((self.root / out[k]).is_file(), out[k])
        for k in ("canvas", "board"):
            if out.get(k):
                for n in json.loads(self.read(out[k]))["nodes"]:
                    if n["type"] == "file":
                        self.assertTrue((self.root / n["file"]).is_file(), n["file"])
        for rel in out.get("files") or {}:
            self.assertTrue((self.root / rel).is_file(), rel)

    def tree(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()
                      and ".obsidian" not in p.parts)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}


class Paths(Area):
    def test_course_module_lesson(self):
        c = self.course(platform="Hotmart")
        m = catalog.create_module(c["id"], "Motion Graphics", 3)
        out = self.put({"type": "course", "course_id": c["id"], "module_id": m["id"], "lesson": 7})
        d = "Estudos/01 - Cursos/Edição de Vídeos/03 - Motion Graphics/07 - RAG busca + geração"
        self.assertEqual(out["note"], f"{d}/RAG busca + geração.md")
        self.assertEqual(out["canvas"], f"{d}/Mapa - RAG busca + geração.canvas")
        self.assertEqual(out["board"], f"{d}/Painel - RAG busca + geração.canvas")
        self.assertTrue(all(r.startswith(f"{d}/Anexos/") for r in out["files"]))
        self.files_ok(out)
        fm = vault.fields(vault.split(self.read(out["note"]))[0])
        self.assertEqual((fm["study-type"], fm["course"], fm["course-id"], fm["module"], fm["module-id"], fm["lesson"],
                          fm["platform"]), ("course", "Edição de Vídeos", c["id"], "Motion Graphics", m["id"], "7", "Hotmart"))
        self.assertRegex(fm["cover"], r"^\[\[.+\.jpg\]\]$")  # a imagem principal do painel, para os cards da Base
        self.assertIn("- **Organização:** Cursos › Edição de Vídeos › Motion Graphics · Aula 07", self.read(out["note"]))
        # a nota do curso (MOC) e a Home
        moc = self.read("Estudos/01 - Cursos/Edição de Vídeos/00 - Edição de Vídeos.md")
        self.assertIn("### 03 - Motion Graphics\n- [[RAG busca + geração]] · Aula 07", moc)
        self.assertIn("- **Plataforma:** Hotmart", moc)
        self.assertIn("O Lumen não guarda credenciais", moc)
        self.assertIn(f"'note[\"course-id\"] == \"{c['id']}\"'", moc)
        self.assertIn("## Sobre", moc)  # a parte do usuário
        home = self.read("Estudos/00 - Estudos.md")
        self.assertIn("[[00 - Edição de Vídeos|Edição de Vídeos]] · 1 aula · Hotmart", home)
        self.assertIn("![[Estudos.base#Para revisar]]", home)
        self.assertNotIn("Materiais para organizar", home)  # só aparece quando há o que organizar
        known = {f.name.casefold() for f in self.root.rglob("*")} | {f.stem.casefold() for f in self.root.rglob("*")}
        for f in ("Estudos/00 - Estudos.md", "Estudos/01 - Cursos/Edição de Vídeos/00 - Edição de Vídeos.md", out["note"]):
            text = self.read(f)
            for link in re.findall(r"(?<!\\)\[\[([^\]|#]+)", re.sub(r"```.*?```", "", text, flags=re.S)):
                self.assertIn(link.strip().casefold(), known, (f, link))

    def test_course_without_module_free_single_and_inbox(self):
        c = self.course("Python")
        cases = [({"type": "course", "course_id": c["id"]}, "Estudos/01 - Cursos/Python/RAG busca + geração"),
                 ({"type": "free", "category": "IA"}, "Estudos/02 - Conteúdo gratuito/IA/RAG busca + geração"),
                 ({"type": "free"}, "Estudos/02 - Conteúdo gratuito/RAG busca + geração"),
                 ({"type": "single", "category": "Programação"}, "Estudos/03 - Aulas avulsas/Programação/RAG busca + geração"),
                 (None, "Estudos/90 - A organizar/RAG busca + geração")]
        for cls, d in cases:
            with self.subTest(cls=cls):
                for x in self.home.glob("[09]*"):
                    if x.is_dir():
                        import shutil
                        shutil.rmtree(x)
                out = self.put(cls)
                self.assertEqual(out["note"].rsplit("/", 1)[0], d)
                self.files_ok(out)
        # sem anexos: nenhuma pasta Anexos vazia
        self.cfg["obsidian_attachments"] = False
        p = package.validate(package.build({**SRC, "key": "file:outra"}, TR, lesson(title="Outra aula"), dict(MINE)))
        out = obsidian.deliver(p, self.cfg)
        self.assertTrue(out["note"].endswith("/Outra aula/Outra aula.md"))
        self.assertFalse((self.root / out["note"]).parent.joinpath("Anexos").exists())

    def test_windows_names_and_long_paths(self):
        c = self.course('Curso: "A/B" <x>? * | \\ fim.')
        m = catalog.create_module(c["id"], "CON", 1)
        t = "Introdução à Programação Orientada a Objetos: herança, polimorfismo, encapsulamento e muito mais " * 2
        out = self.put({"type": "course", "course_id": c["id"], "module_id": m["id"], "lesson": 12}, les=lesson(title=t))
        for rel in [out["note"], out["canvas"], out["board"], *out["files"]]:
            f = self.root / rel
            self.assertTrue(f.is_file(), rel)
            self.assertLess(len(str(f)), 260, rel)
            self.assertFalse(re.search(r'[:*?"<>|]', rel), rel)
        self.assertIn("/01 - CON (aula)/", out["note"])
        self.files_ok(out)

    def test_nothing_is_written_outside_the_area(self):
        with self.assertRaises(AppError):
            area._inside(self.home.parent / "fora" / "x", self.home)
        self.assertEqual(area.lesson_dir(self.home, {"type": "free", "category": ".."}, "..").name, "Aula")
        bad = catalog.classification({"type": "free", "category": "../../Windows"})
        self.assertTrue(str(area.lesson_dir(self.home, bad, "x")).startswith(str(self.home)))
        if os.name == "nt":  # uma pasta da área que é um atalho para fora do cofre: recusada
            outside = Path(self.tmp) / "fora"
            outside.mkdir()
            (self.home / "02 - Conteúdo gratuito").mkdir(parents=True)
            subprocess.run(["cmd", "/c", "mklink", "/J", str(self.home / "02 - Conteúdo gratuito" / "IA"), str(outside)],
                           capture_output=True, check=True)
            with self.assertRaises(AppError):
                self.put({"type": "free", "category": "IA"})
            self.assertEqual(list(outside.iterdir()), [])


class Catalog(Area):
    def test_ids_duplicates_and_credentials(self):
        c = self.course()
        self.assertRegex(c["id"], r"^c-[0-9a-f]{8}$")
        for same in ("edicao de videos", "EDIÇÃO DE VÍDEOS"):
            with self.subTest(same), self.assertRaises(AppError):
                catalog.create_course(same)
        self.assertEqual(catalog.similar([c["name"]], "Edição de Vídeo"), ([], ["Edição de Vídeos"]))
        with self.assertRaises(AppError):
            catalog.create_course("Outro", platform="senha sk-abcdefghijklmnopqrstuvwxyz123")
        d = catalog.create_course("Outro", url="https://eu:minhasenha@plataforma.com/curso?x=1")
        self.assertEqual(d["url"], "https://plataforma.com/curso?x=1")  # sem usuário e senha embutidos
        old, new = catalog.update_course(c["id"], name="Edição Profissional de Vídeos")
        self.assertEqual((old["id"], new["id"]), (c["id"], c["id"]))
        self.assertEqual(catalog.classification({"type": "course", "course_id": c["id"]})["course"],
                         "Edição Profissional de Vídeos")
        with self.assertRaises(AppError):
            catalog.classification({"type": "course"})  # curso é obrigatório quando o tipo é curso

    def test_suggestions_never_apply_themselves(self):
        c = self.course()
        m = catalog.create_module(c["id"], "Motion Graphics")
        self.assertEqual(catalog.suggest("Aula qualquer"), [])
        catalog.remember({"type": "course", "course_id": c["id"], "module_id": m["id"], "lesson": 7})
        s = catalog.suggest("Aula qualquer")
        self.assertEqual((s[0]["why"], s[0]["classification"]["lesson"], s[0]["classification"]["module"]),
                         ("continuar", 8, "Motion Graphics"))
        cat = catalog.load()
        cat["last"]["at"] = "2026-01-01T00:00:00"  # há muito tempo: não sugere continuar
        catalog.save(cat)
        self.assertEqual(catalog.suggest("Aula 3 do curso Edição de Vídeos")[0]["why"], "nome")
        self.assertEqual(catalog.suggest("Vídeo", "https://youtu.be/abc")[0]["classification"], {"type": "free"})


class Move(Area):
    def test_inbox_to_course_module_then_between_modules(self):
        first = self.put()
        self.assertTrue(first["note"].startswith("Estudos/90 - A organizar/"))
        c = self.course()
        m1, m2 = catalog.create_module(c["id"], "Fundamentos", 1), catalog.create_module(c["id"], "Ferramentas", 2)
        cls = {"type": "course", "course_id": c["id"], "module_id": m1["id"]}
        out = self.put(cls, prev=json.loads(json.dumps(first)), move=True)
        d = "Estudos/01 - Cursos/Edição de Vídeos/01 - Fundamentos/RAG busca + geração"
        self.assertEqual(out["note"], f"{d}/RAG busca + geração.md")
        self.assertEqual(out["state"], "updated")  # a trilha e as propriedades mudaram
        self.assertFalse((self.root / "Estudos/90 - A organizar/RAG busca + geração").exists())
        self.files_ok(out)
        self.assertTrue(all(r.startswith(d) for r in [*out["files"], *out["images"].values()]))
        fm = vault.fields(vault.split(self.read(out["note"]))[0])
        self.assertEqual((fm["study-type"], fm["module"]), ("course", "Fundamentos"))
        # outra organização no Lumen (a gravada no manifesto é diferente): vai sozinha, sem duplicar
        out2 = self.put({**cls, "module_id": m2["id"]}, prev=json.loads(json.dumps(out)))
        self.assertIn("/02 - Ferramentas/", out2["note"])
        self.files_ok(out2)
        self.assertEqual(len(list(self.root.rglob("RAG busca + geração.md"))), 1)
        self.assertEqual(len(list(self.root.rglob("*.canvas"))), 2)
        # reprocessar depois de mover: atualiza onde está, sem recriar nada no lugar antigo
        out3 = self.put({**cls, "module_id": m2["id"]}, prev=json.loads(json.dumps(out2)))
        self.assertEqual((out3["note"], out3["state"]), (out2["note"], "unchanged"))
        self.assertFalse((self.root / d).exists())

    def test_folder_moved_in_obsidian_is_not_moved_back(self):
        out = self.put()
        src = (self.root / out["note"]).parent
        dst = self.home / "Minha pasta" / src.name
        dst.parent.mkdir()
        os.rename(src, dst)
        again = self.put(prev=json.loads(json.dumps(out)))  # a mesma organização: o Lumen atualiza onde ela está
        self.assertTrue(again["note"].startswith("Estudos/Minha pasta/"))

    def test_rename_course_keeps_identity_and_links(self):
        c = self.course()
        cls = {"type": "course", "course_id": c["id"]}
        out = self.put(cls)
        store.remember("aula", {"lumen_id": out.get("lumen_id") or package.lumen_id(SRC["key"]), "obsidian": out,
                                "classification": catalog.classification(cls)})
        old, new = catalog.update_course(c["id"], name="Edição Profissional de Vídeos")
        area.rename_course(self.cfg, old, new)
        self.assertFalse((self.home / "01 - Cursos/Edição de Vídeos").exists())
        base = self.home / "01 - Cursos/Edição Profissional de Vídeos"
        self.assertTrue((base / "00 - Edição Profissional de Vídeos.md").exists())
        self.assertFalse((base / "00 - Edição de Vídeos.md").exists())
        ob = store.history()["aula"]["obsidian"]
        self.assertTrue(ob["note"].startswith("Estudos/01 - Cursos/Edição Profissional de Vídeos/"))
        self.files_ok(ob)
        fm = vault.fields(vault.split(self.read(ob["note"]))[0])
        self.assertEqual((fm["course"], fm["course-id"]), ("Edição Profissional de Vídeos", c["id"]))
        self.assertIn("[[00 - Edição Profissional de Vídeos|Edição Profissional de Vídeos]]",
                      self.read("Estudos/00 - Estudos.md"))
        # reprocessar com o nome novo: a mesma nota, no lugar novo
        again = self.put(cls, prev=json.loads(json.dumps(ob)))
        self.assertEqual(again["note"], ob["note"])
        self.assertEqual(len(list(self.root.rglob("RAG busca + geração.md"))), 1)
        # só maiúsculas: no Windows é a mesma pasta, e mesmo assim muda
        old2, new2 = catalog.update_course(c["id"], name="edição profissional de vídeos")
        area.rename_course(self.cfg, old2, new2)
        self.assertIn("edição profissional de vídeos", [p.name for p in (self.home / "01 - Cursos").iterdir()])


class Home(Area):
    def test_base_views_user_edits_and_inbox_section(self):
        out = self.put()
        base = self.read("Estudos/Estudos.base")
        for view in ("Biblioteca", "Para revisar", "Continuar estudando", "Recentes", "Cursos", "Conteúdo gratuito",
                     "Aulas avulsas", "A organizar", "Gerados pelo Lumen", "Todos"):
            self.assertIn(f"    name: {view}\n", base)
        self.assertIn('file.inFolder("Estudos")', base)
        self.assertIn("image: note.cover", base)
        home = self.read("Estudos/00 - Estudos.md")
        self.assertIn("## Materiais para organizar", home)
        self.assertIn("1 material espera", home)
        # o usuário ajustou uma visão no Obsidian: o Lumen não regrava a Base
        (self.root / "Estudos/Estudos.base").write_text(base + "\n# meu ajuste\n", "utf-8")
        area.refresh(self.cfg)
        self.assertIn("# meu ajuste", self.read("Estudos/Estudos.base"))
        # o que o usuário escreveu na Home fica
        p = self.root / "Estudos/00 - Estudos.md"
        p.write_text(p.read_text("utf-8") + "\nMinhas metas do mês.\n", "utf-8")
        self.put(prev=out)
        self.assertIn("Minhas metas do mês.", p.read_text("utf-8"))

    @unittest.skipUnless(os.name == "nt" and Path(r"D:\downloads\cerebro\Cerebro Oficial\.claude\scripts\vault-check.mjs").exists(),
                         "checker do cofre do usuário")
    def test_vault_checker_accepts_the_whole_area(self):
        c = self.course(platform="Hotmart")
        m = catalog.create_module(c["id"], "Motion Graphics", 3)
        self.put({"type": "course", "course_id": c["id"], "module_id": m["id"], "lesson": 1})
        r = subprocess.run(["node", r"D:\downloads\cerebro\Cerebro Oficial\.claude\scripts\vault-check.mjs", str(self.root)],
                           capture_output=True, text=True, encoding="utf-8")
        head, _, rest = r.stdout.partition("## Links amb")
        self.assertEqual([ln for ln in head.splitlines() if "Estudos/" in ln], [], r.stdout)
        self.assertNotIn("Estudos/", rest.split("##")[0], r.stdout)


class Migration(Area):
    """Pasta antiga como a real: C04 Claude Obsidian/16 Lumen com notas datadas, Mapa e Painel lado a lado, um Anexos só
    e o Lumen Dashboard. Montada a partir de uma entrega de verdade, achatada como o Lumen gravava antes."""
    OLD = "C04 Claude Obsidian/16 Lumen"

    def legacy(self):
        out = self.put()
        lesson_dir = (self.root / out["note"]).parent
        old = self.root / self.OLD
        (old / "Anexos").mkdir(parents=True)
        moves = {}
        note_new = old / "2026-10-23 - RAG busca + geração.md"
        moves[out["note"]] = note_new
        for k in ("canvas", "board"):
            moves[out[k]] = old / Path(out[k]).name
        for rel in out["files"]:
            moves[rel] = old / "Anexos" / Path(rel).name
        for a, b in moves.items():
            os.rename(self.root / a, b)
        remap = {a: b.relative_to(self.root).as_posix() for a, b in moves.items()}
        for k in ("canvas", "board"):
            f = moves[out[k]]
            data = json.loads(f.read_text("utf-8"))
            for n in data["nodes"]:
                if n["type"] == "file":
                    n["file"] = remap.get(n["file"], n["file"])
            f.write_text(canvas.dumps(data), "utf-8")
        import shutil
        shutil.rmtree(self.home)
        text = note_new.read_text("utf-8")
        note_new.write_text(re.sub(r"(?m)^study-type: .*\n", "", text).replace("lumen-version", "aliases:\n  - \"RAG busca + geração\"\nlumen-version", 1), "utf-8")
        (old / "Lumen Dashboard.md").write_text(obsidian.compose(["type: system", "author: lumen-ai"],
                                                                 "\n" + obsidian.BEGIN, "# Lumen Dashboard",
                                                                 "\n\n" + obsidian.USER), "utf-8")
        ob = {**out, **{k: remap[out[k]] for k in ("note", "canvas", "board")},
              "files": {remap[r]: s for r, s in out["files"].items()},
              "images": {i: remap[r] for i, r in out["images"].items()}}
        ob.pop("placed")
        store.remember("yt:aula", {"lumen_id": package.lumen_id(SRC["key"]), "title": "RAG", "obsidian": ob})
        (store.DATA / "catalog.json").unlink(missing_ok=True)
        return ob

    def test_plan_then_migrate_preserves_everything_and_is_idempotent(self):
        ob = self.legacy()
        before = self.snapshot()
        plan = area.plan_view(self.cfg)
        self.assertEqual(plan["folders"], [self.OLD])
        (l,) = plan["lessons"]
        self.assertEqual((l["title"], l["canvas"], l["board"], l["attachments"]), ("RAG busca + geração", True, True,
                                                                                     len(ob["files"])))
        self.assertEqual(l["target"], "Estudos/90 - A organizar/RAG busca + geração")
        self.assertEqual(self.snapshot(), before)  # o plano não toca em nada
        out = area.migrate(self.cfg)
        self.assertEqual(out["moved"], 1)
        d = self.root / "Estudos/90 - A organizar/RAG busca + geração"
        self.assertTrue((d / "2026-10-23 - RAG busca + geração.md").is_file())  # o nome fica: nenhum link quebra
        self.assertEqual(len(list((d / "Anexos").iterdir())), len(ob["files"]))
        self.assertFalse((self.root / self.OLD).exists())  # vazia: removida (o zip guarda tudo)
        with zipfile.ZipFile(out["backup"]) as z:
            self.assertEqual(sorted(z.namelist()), sorted(k for k in before if k.startswith(self.OLD)))
        after = self.snapshot()
        for rel, h in before.items():  # cada arquivo continua existindo, com o mesmo conteúdo (Canvas e nota à parte)
            if rel.startswith(self.OLD) and not rel.endswith((".canvas", ".md")):
                new = "Estudos/90 - A organizar/RAG busca + geração/Anexos/" + rel.rsplit("/", 1)[1]
                self.assertEqual(after.get(new), h, rel)
        e = store.history()["yt:aula"]
        self.files_ok(e["obsidian"])
        self.assertEqual(e["classification"], {"type": "inbox"})
        fm = vault.fields(vault.split((d / "2026-10-23 - RAG busca + geração.md").read_text("utf-8"))[0])
        self.assertEqual(fm["study-type"], "inbox")
        self.assertIn("## Materiais para organizar", self.read("Estudos/00 - Estudos.md"))
        # de novo: nada a migrar, nada duplicado
        snap = self.snapshot()
        self.assertEqual(area.migrate(self.cfg)["moved"], 0)
        self.assertEqual(self.snapshot(), snap)
        # e a aula migrada segue o fluxo normal: organizar leva a pasta para o curso
        c = self.course()
        moved = self.put({"type": "course", "course_id": c["id"]}, prev=json.loads(json.dumps(e["obsidian"])), move=True)
        self.files_ok(moved)
        self.assertTrue(moved["note"].startswith("Estudos/01 - Cursos/Edição de Vídeos/RAG busca + geração/"))

    def test_failure_in_the_middle_rolls_everything_back(self):
        self.legacy()
        before = self.snapshot()
        with mock.patch.object(area, "_rewrite_canvases", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                area.migrate(self.cfg)
        after = {k: v for k, v in self.snapshot().items() if not k.startswith("Estudos/")}
        self.assertEqual(after, before)
        self.assertFalse((store.DATA / area.JOURNAL).exists())

    def test_interrupted_migration_is_undone_next_time(self):
        self.legacy()
        before = self.snapshot()
        src = self.root / self.OLD / "2026-10-23 - RAG busca + geração.md"
        dst = self.root / "Estudos/90 - A organizar/x/2026-10-23 - RAG busca + geração.md"
        dst.parent.mkdir(parents=True)
        os.rename(src, dst)  # o Lumen fechou logo depois deste passo
        store._write(area.JOURNAL, {"status": "running", "done": [[src.relative_to(self.root).as_posix(),
                                                                   dst.relative_to(self.root).as_posix()]]})
        self.assertEqual(area.recover(self.cfg), 1)
        self.assertEqual({k: v for k, v in self.snapshot().items() if not k.startswith("Estudos/")}, before)

    def test_user_wrote_in_the_old_dashboard_so_it_stays(self):
        self.legacy()
        dash = self.root / self.OLD / "Lumen Dashboard.md"
        dash.write_text(dash.read_text("utf-8") + "\nMinhas anotações importantes.\n", "utf-8")
        out = area.migrate(self.cfg)
        self.assertIn("Minhas anotações importantes.", dash.read_text("utf-8"))
        self.assertIn("[[00 - Estudos]]", dash.read_text("utf-8"))
        self.assertEqual(out["left"], [self.OLD])
        self.assertTrue((self.root / self.OLD / "README - Migrado para Estudos.md").exists())


if __name__ == "__main__":
    unittest.main()
