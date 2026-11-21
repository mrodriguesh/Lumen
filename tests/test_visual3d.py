"""Visualização 3D: especificação limitada, cena com perspectiva e oclusão, GIF/PNG conferidos, orçamento, cache, falhas
e a entrega nos dois destinos (Notion simulado e cofre temporário), página por página."""
import io
import json
import math
import threading
import types
import unittest
from unittest import mock

import numpy as np

import tests  # noqa: F401  (isola LUMEN_DATA antes do lumen, mesmo sem -t .)
from lumen import catalog, charts, jobs, llm, mindmap, notion, server, store, visual3d as v
from tests import REAL_VISUAL
from tests import test_flow as tf
from tests.test_flow import GOOD, SPEC, full, wait

MAP = {"center": "Fotossíntese", "branches": [
    {"label": "Fase clara", "emoji": "☀️", "children": ["Depende de luz", "Ocorre nos tilacoides"]},
    {"label": "Ciclo de Calvin", "emoji": "🔁", "children": ["Fixa o carbono"]},
    {"label": "Clorofila", "emoji": "🌿", "children": ["Pigmento verde"]}]}
RICH = {**GOOD, "map_kind": "sistema", "mind_map": MAP,
        "relations": [{"from": "Fase clara", "type": "leva a", "to": "Ciclo de Calvin"}]}


def pkg(lesson, lid="lm-00000000000000aa"):
    return {"lumen_id": lid, "lesson": lesson, "map": mindmap.data(lesson)}


def lesson(**kw):
    base = {"title": "Aula", "map_kind": "conceitual", "steps": [], "relations": [], "mind_map": MAP,
            "topics": [{"title": "Fase clara"}]}
    return {**base, **kw}


class Spec(unittest.TestCase):
    """O que a cena mostra vem do material (rótulos, passos, relações), nunca de fora; a família segue a forma."""

    def test_family_follows_the_content_and_cites_the_material(self):
        steps = ["Misture farinha e água", "Descanse uma hora", "Adicione o sal", "Asse com vapor"]
        cases = {
            "processo": lesson(map_kind="tutorial", steps=steps),
            "sistema": lesson(map_kind="sistema", relations=[{"from": "Fase clara", "type": "leva a", "to": "Ciclo de Calvin"}]),
            "estrutura": lesson(map_kind="livro"),
            "comparacao": lesson(relations=[{"from": "Fase clara", "type": "contrasta com", "to": "Ciclo de Calvin"}]),
            "conceitos": lesson(),
        }
        for fam, les in cases.items():
            s = v.validate(v.spec(pkg(les)))
            self.assertEqual(s["family"], fam)
            self.assertEqual(s["concept"], "Fotossíntese")
            material = {b["label"] for b in MAP["branches"]} | {k for b in MAP["branches"] for k in b["children"]} | set(steps)
            self.assertTrue({n["label"] for n in s["nodes"]} <= material, fam)  # nenhum rótulo inventado
            for ref in s["evidence"]:  # cada origem aponta para algo que existe no material
                self.assertTrue(v._REF.match(ref), ref)
        p = v.spec(pkg(cases["processo"]))
        self.assertEqual([n["label"] for n in p["nodes"]], steps)  # na ordem da aula
        self.assertEqual([(x["a"], x["b"]) for x in p["links"]], [(0, 1), (1, 2), (2, 3)])
        self.assertEqual(p["evidence"][1:], [f"steps[{i}]" for i in range(4)])

    def test_relations_are_only_the_ones_the_lesson_states(self):
        les = lesson(map_kind="sistema", relations=[{"from": "Fase clara", "type": "leva a", "to": "Ciclo de Calvin"},
                                                    {"from": "Clorofila", "type": "causa", "to": "Algo fora do mapa"},
                                                    {"from": "Clorofila", "type": "inventada", "to": "Fase clara"}])
        s = v.spec(pkg(les))
        rel = [(x["a"], x["b"], x["kind"]) for x in s["links"] if x["kind"] != "hub"]
        self.assertEqual(rel, [(0, 1, "leva a")])
        self.assertEqual(s["evidence"].count("relations[0]"), 1)
        self.assertNotIn("relations[1]", s["evidence"])
        hubs = {(x["a"], x["b"]) for x in s["links"] if x["kind"] == "hub"}
        self.assertEqual(hubs, {(-1, 0), (-1, 1), (-1, 2)})  # do próprio mapa: cada ramo é do tema central
        self.assertIn("1 relação", v.describe(s))

    def test_few_concepts_and_old_packages(self):
        one = {"title": "Introdução", "topics": [{"title": "Boas-vindas"}]}  # pacote antigo: sem mapa, passos ou relações
        s = v.validate(v.spec({"lumen_id": "lm-00000000000000bb", "lesson": one}))
        self.assertEqual((s["family"], [n["label"] for n in s["nodes"]]), ("conceitos", ["Boas-vindas"]))
        self.assertIsNone(v.spec({"lumen_id": "lm-00000000000000bb", "lesson": {"title": "Vazia", "topics": []}}))
        too_many = lesson(mind_map={"center": "X", "branches": [{"label": f"Ramo {i}", "children": []} for i in range(8)]})
        s = v.validate(v.spec(pkg(too_many)))
        self.assertEqual((len(s["nodes"]), s["more"]), (7, 1))
        self.assertIn("+1 fora da imagem", v.describe(s))

    def test_labels_are_cleaned_and_cut_at_a_word(self):
        self.assertEqual(v._text("🔎 Busca\x00 semântica\n\n<b>"), "Busca semântica <b>")
        self.assertEqual(v._text("Tensão → corrente"), "Tensão → corrente")  # sinais de matemática ficam
        long = v._text("Uma frase bem comprida que não cabe inteira no rótulo da cena tridimensional", 30)
        self.assertTrue(long.endswith("…") and len(long) <= 30 and " " in long)

    def test_malicious_or_broken_specs_are_refused(self):
        good = v.spec(pkg(lesson(map_kind="sistema")))
        v.validate(json.loads(json.dumps(good)))
        bad = [
            {**good, "script": "import os"},                                     # campo a mais
            {**good, "family": "shader"},                                        # família desconhecida
            {**good, "v": True},                                                  # bool não é versão
            {**good, "title": "a" * 200},                                         # rótulo longo
            {**good, "concept": "Ataque\x1b[31m"},                                # controle
            {**good, "nodes": [{**good["nodes"][0], "label": "C:\\Windows\\system32\x00"}]},
            {**good, "nodes": [{**good["nodes"][0], "sub": 1.5}]},                # número não inteiro
            {**good, "nodes": [{**good["nodes"][0], "sub": float("nan")}]},       # NaN
            {**good, "nodes": [{**good["nodes"][0], "path": "../../x"}]},
            {**good, "nodes": good["nodes"] * 3},                                 # complexidade acima do limite
            {**good, "links": [{"a": 0, "b": 99, "kind": "leva a"}]},             # índice fora
            {**good, "links": [{"a": 0, "b": 0, "kind": "leva a"}]},              # ligação consigo
            {**good, "links": [{"a": 0, "b": 1, "kind": "exec"}]},                # relação desconhecida
            {**good, "links": good["links"] * 5},
            {**good, "evidence": ["../../etc/passwd"]},
            {**good, "more": -1},
            {**good, "family": "processo"},                                       # elementos que não são etapas
            "não é um objeto", None,
        ]
        for b in bad:
            with self.assertRaises((ValueError, TypeError, KeyError), msg=str(b)[:80]):
                v.validate(b)


class Geometry(unittest.TestCase):
    """Cena tridimensional de verdade: perspectiva, paralaxe na órbita, faces escondidas e oclusão."""

    def test_perspective_and_parallax(self):
        cam = {"target": (0, 1, 0), "dist": 10.0, "az": 0.4, "el": 0.3, "amp": 0.3}
        c = v._Cam(cam, 0.0, 960, 540)
        near, far = np.array([0, 1, 0]) + c.R[2] * -3, np.array([0, 1, 0]) + c.R[2] * 3  # no eixo da câmera
        side = c.R[0] * 1.0  # o mesmo deslocamento lateral, perto e longe
        (pn, pn2), _ = c.project([near, near + side])
        (pf, pf2), _ = c.project([far, far + side])
        self.assertGreater(np.linalg.norm(pn2 - pn), 1.5 * np.linalg.norm(pf2 - pf))  # mais longe, menor
        c2 = v._Cam(cam, 0.25, 960, 540)  # a câmera girou: o de perto anda mais que o de longe (não é um 2D deslocado)
        move_near = np.linalg.norm(c2.project([near])[0][0] - pn)
        move_far = np.linalg.norm(c2.project([far])[0][0] - pf)
        self.assertGreater(abs(move_near - move_far), 20)

    def test_hidden_faces_of_convex_shapes(self):
        cam = v._Cam({"target": (0, 1.5, 0), "dist": 10.6, "az": 0.52, "el": 0.3, "amp": 0.2}, 0.1, 960, 540)
        for shape, faces in (("cube", 6), ("ico", 20), ("oct", 8)):
            V, F, _ = v.SHAPES[shape]
            self.assertEqual(len(F), faces)
            P = V * 0.5 + np.array([0, 1.5, 0])
            front = 0
            for f in F:
                Q = P[list(f)]
                n = np.cross(Q[1] - Q[0], Q[2] - Q[0])
                n *= 1 if np.dot(n, Q.mean(0) - P.mean(0)) > 0 else -1
                front += np.dot(n, cam.eye - Q.mean(0)) > 0
            self.assertTrue(0 < front < faces, shape)  # parte das faces fica escondida atrás

    def test_the_nearer_object_covers_the_farther_one(self):
        s = v.validate(v.spec(pkg(lesson())))
        cam = {"target": (0, 1.5, 0), "dist": 10.0, "az": 0.0, "el": 0.0, "amp": 0.0}

        def color_at_center(near_rgb, far_rgb):
            sc = {"family": "conceitos", "paths": [], "labels": [], "cam": cam, "pos": {}, "n": 1, "spec": s,
                  "objs": [{"shape": "cube", "pos": (0, 1.5, 2.5), "r": 0.6, "color": near_rgb},
                           {"shape": "cube", "pos": (0, 1.5, -2.5), "r": 0.9, "color": far_rgb}]}
            f = v._frame(sc, 0.0, 320, 180, {})
            c = v._Cam(cam, 0.0, 320, 180).project([(0, 1.5, 2.5)])[0][0]
            win = f[int(c[1]) - 3:int(c[1]) + 4, int(c[0]) - 3:int(c[0]) + 4].reshape(-1, 3).astype(int)
            return win.mean(0)
        red_front = color_at_center((255, 40, 40), (40, 255, 40))
        green_front = color_at_center((40, 255, 40), (255, 40, 40))
        self.assertGreater(red_front[0] - red_front[1], 0)
        self.assertGreater(green_front[1] - green_front[0], 0)

    def test_every_family_builds_its_own_scene(self):
        steps = ["Etapa um", "Etapa dois", "Etapa três"]
        for les, fam, objs in ((lesson(map_kind="tutorial", steps=steps), "processo", 3),
                               (lesson(map_kind="livro"), "estrutura", 3), (lesson(), "conceitos", 4),
                               (lesson(map_kind="sistema"), "sistema", 4),
                               (lesson(relations=[{"from": "Fase clara", "type": "contrasta com", "to": "Clorofila"}]),
                                "comparacao", 5)):
            sc = v._scene(v.validate(v.spec(pkg(les))))
            self.assertEqual((sc["family"], len(sc["objs"])), (fam, objs))
            labels = {ln for lab in sc["labels"] for ln in lab["lines"]}
            self.assertTrue({n["label"] for n in v.spec(pkg(les))["nodes"]} <= labels, fam)
        sc = v._scene(v.validate(v.spec(pkg(lesson(map_kind="tutorial", steps=steps)))))
        xs = [o["pos"][0] for o in sc["objs"]]
        self.assertEqual(xs, sorted(xs))  # as etapas avançam em ordem


class Files(unittest.TestCase):
    """GIF com quadros diferentes, PNG válido, peso e tamanho, e a conferência que recusa arquivo ruim."""

    def setUp(self):
        self.s = v.validate(v.spec(pkg(RICH)))

    def test_small_animation_and_static_image_pass_the_check(self):
        out = v.render(self.s, "animated")
        self.assertEqual(out["state"], "ok")
        gi = out["gif_info"]
        self.assertEqual((gi["width"], gi["height"], gi["frames"], gi["mime"]), (320, 180, 6, "image/gif"))
        self.assertEqual(out["gif"][:6], b"GIF89a")
        self.assertEqual(v.inspect(out["png"], "png", 320, 180)["mime"], "image/png")
        self.assertEqual(v.render(self.s, "static")["gif"], None)

    def test_real_size_within_limits(self):
        with mock.patch.multiple(v, **REAL_VISUAL):
            out = v.render(self.s, "animated")
        gi = out["gif_info"]
        self.assertEqual(out["state"], "ok", out["reason"])
        self.assertEqual((gi["width"], gi["height"]), (960, 540))  # 16:9
        self.assertLessEqual(gi["frames"], 48)
        self.assertTrue(3000 <= gi["duration_ms"] <= 4000, gi["duration_ms"])
        self.assertGreaterEqual(gi["duration_ms"] / gi["frames"], 1000 / 12.5)  # até 12 quadros por segundo
        self.assertLessEqual(gi["bytes"], 4_500_000)
        self.assertLessEqual(len(out["png"]), v.MAX_PNG)
        self.assertLess(out["render_s"], v.BUDGET_S)

    def test_broken_files_are_refused(self):
        out = v.render(self.s, "animated")
        frame = np.asarray(__import__("PIL.Image", fromlist=["Image"]).open(io.BytesIO(out["png"])).convert("RGB"))
        cases = [(out["gif"][:len(out["gif"]) // 2], "gif"), (out["png"], "gif"), (out["gif"], "png"),
                 (charts._gif([frame] * 6, 12, -1, 64), "gif"),  # parado: sem movimento
                 (v._png(np.zeros((180, 320, 3), np.uint8)), "png"),  # vazio
                 (out["png"], "webp")]
        for data, kind in cases:
            with self.assertRaises(ValueError):
                v.inspect(data, kind, 320, 180)
        with self.assertRaises(ValueError):
            v.inspect(out["png"], "png", 960, 540)  # dimensões
        with mock.patch.object(v, "MAX_PNG", 1000), self.assertRaises(ValueError):
            v.inspect(out["png"], "png", 320, 180)  # peso

    def test_time_budget_size_and_limit_fall_back_to_png(self):
        self.assertEqual(v.render(self.s, "animated", budget=0)[("state")], "static-fallback")
        out = v.render(self.s, "animated", limit=0)
        self.assertEqual((out["state"], out["reason"], out["gif"]), ("static-fallback", "tempo", None))
        with mock.patch.object(v, "MAX_GIF", 100):
            out = v.render(self.s, "animated")
        self.assertEqual((out["state"], out["reason"]), ("static-fallback", "peso"))
        self.assertTrue(out["png"].startswith(b"\x89PNG"))


COMPARE = {"v": 1, "family": "comparacao", "concept": "DNA e RNA", "title": "DNA × RNA", "evidence": ["title"], "more": 0,
           "nodes": [{"label": "DNA", "role": "a", "sub": 0}, {"label": "RNA", "role": "b", "sub": 0},
                     {"label": "Dupla hélice", "role": "a", "sub": 0}, {"label": "Açúcar desoxirribose", "role": "a", "sub": 0},
                     {"label": "Fita simples", "role": "b", "sub": 0}, {"label": "Uracila no lugar da timina", "role": "b", "sub": 0}],
           "links": [{"a": 0, "b": 1, "kind": "contrasta com"}, {"a": 0, "b": 2, "kind": "hub"}, {"a": 0, "b": 3, "kind": "hub"},
                     {"a": 1, "b": 4, "kind": "hub"}, {"a": 1, "b": 5, "kind": "hub"}]}


class Labels(unittest.TestCase):
    """Rótulos que o desenho não pode embaralhar nem trocar por quadrados (achados ao conferir o holograma do chat)."""

    def test_comparison_labels_keep_to_their_side_in_the_two_column_layout(self):
        s = v.validate(COMPARE)
        sc = v._scene(s)
        sc["spec"], sc["origin"], sc["foot"] = s, "da aula", None
        with mock.patch.object(v, "_overlap", return_value=1.0):  # tudo colide: força o arranjo em duas colunas
            lay = v._layout(sc, 960, 540, 1.0)
        shown = [i for i in lay if "fixed" in lay[i]]
        self.assertEqual(len(shown), 6)
        for i in shown:
            role = sc["labels"][i]["role"]
            self.assertEqual(lay[i]["fixed"][0] < 480, role == "a", (sc["labels"][i]["lines"], role))  # A à esquerda, B à direita
        ys = {r: sorted(lay[i]["fixed"][1] for i in shown if sc["labels"][i]["role"] == r) for r in "ab"}
        for r in "ab":
            self.assertEqual(len(set(ys[r])), len(ys[r]))  # uma linha para cada rótulo: nenhum sobre outro

    def test_other_families_still_alternate_the_columns(self):
        s = v.validate(v.spec(pkg(RICH)))
        sc = v._scene(s)
        sc["spec"], sc["origin"], sc["foot"] = s, "da aula", None
        with mock.patch.object(v, "_overlap", return_value=1.0):
            lay = v._layout(sc, 960, 540, 1.0)
        xs = [lay[i]["fixed"][0] for i in lay if "fixed" in lay[i]]
        self.assertGreaterEqual(len(xs), 2)
        self.assertEqual(set(xs), {18.0, 710.0})  # sem lados: as duas colunas se alternam como antes

    def test_glyphs_the_font_lacks_become_a_compatible_character_or_leave_never_a_square(self):
        f = v._font("Constante ℏ ≈ 1,0546 × 10⁻³⁴ J·s", 18, 520)
        text = v._drawable("Constante ℏ ≈ 1,0546 × 10⁻³⁴ J·s", f)
        miss = bytes(f.getmask("\U0010fffd"))
        self.assertTrue(all(c.isspace() or bytes(f.getmask(c)) != miss for c in text), text)
        self.assertTrue(text.startswith("Constante") and text.endswith("J·s"), text)
        plain = "Ação & reação — ñ ç ã é ü Ångström (Å) H₂O"
        self.assertEqual(v._drawable(plain, v._font(plain, 18, 520)), plain)  # o que a fonte tem passa intacto
        lines, _ = v._wrap("ñ ç ã é ü", 18, 520, 250)
        self.assertEqual(lines, ["ñ ç ã é ü"])


class Prepare(unittest.TestCase):
    """Feito uma vez e guardado: tentar de novo, reabrir o app e os dois destinos reaproveitam o mesmo arquivo."""

    def setUp(self):
        import shutil
        shutil.rmtree(store.DATA / "visuals", ignore_errors=True)
        self.p = pkg(RICH, "lm-00000000000000cc")

    def test_cache_survives_a_restart_and_is_checked_again(self):
        a, rec = v.prepare(self.p, "animated")
        self.assertEqual((a["kind"], a["cached"], rec["state"]), ("gif", False, "ok"))
        files = sorted(f.name for f in (store.DATA / "visuals" / "lm-00000000000000cc").iterdir())
        self.assertEqual(len(files), 3)  # GIF, PNG de reserva e o registro (sem base64 em lugar nenhum)
        meta = json.loads((store.DATA / "visuals" / "lm-00000000000000cc" / f"{a['spec_hash']}.json").read_text("utf-8"))
        self.assertTrue({"spec_hash", "renderer", "mode", "file", "width", "height", "bytes", "state"} <= set(meta))
        v._FONTS.clear()  # “reiniciar”: nada na memória
        v._BG.clear()
        with mock.patch.object(v, "render", side_effect=AssertionError("desenhou de novo")):
            b, _ = v.prepare(self.p, "animated")
        self.assertEqual((b["cached"], b["data"]), (True, a["data"]))
        # o arquivo guardado estragou: não passa na conferência e é desenhado de novo
        (store.DATA / "visuals" / "lm-00000000000000cc" / a["file"]).write_bytes(b"GIF89a quebrado")
        c, _ = v.prepare(self.p, "animated")
        self.assertEqual((c["cached"], c["data"]), (False, a["data"]))

    def test_one_file_per_lesson_and_static_mode_is_png(self):
        a, _ = v.prepare(self.p, "animated")
        b, _ = v.prepare(self.p, "static")
        self.assertEqual((b["kind"], b["mime"]), ("png", "image/png"))
        names = {f.name for f in (store.DATA / "visuals" / "lm-00000000000000cc").iterdir()}
        self.assertFalse(any(n.startswith(a["spec_hash"]) for n in names))  # o anterior desta aula saiu
        self.assertIn("imagem estática", v.caption(b))
        self.assertIn("animação", v.caption(a))
        self.assertNotIn("mouse", v.caption(a) + v.caption(b))  # um GIF não se gira com o mouse

    def test_failures_never_raise(self):
        with mock.patch.object(v, "_frame", side_effect=RuntimeError("quebrou")):
            a, rec = v.prepare(self.p, "animated")
        self.assertEqual((a, rec["state"]), (None, "failed"))
        self.assertEqual(v.prepare(self.p, "off"), (None, {"state": "off", "mode": "off"}))
        a, rec = v.prepare({"lumen_id": "lm-00000000000000cc", "lesson": {"title": "x", "topics": []}}, "animated")
        self.assertEqual((a, rec["state"]), (None, "skipped"))
        with self.assertRaises(ValueError):
            v.prepare({**self.p, "lumen_id": "../../fora"}, "animated")

    def test_one_render_at_a_time(self):
        v._LOCK.acquire()
        try:
            with mock.patch.object(v, "LIMIT_S", 0.05):
                a, rec = v.prepare(self.p, "animated")
        finally:
            v._LOCK.release()
        self.assertEqual((a, rec["state"]), (None, "failed"))
        self.assertIn("outra visualização", rec["reason"])

    def test_cancel_stops_the_drawing(self):
        from lumen import Cancelled
        with self.assertRaises(Cancelled):
            v.prepare(self.p, "animated", check=mock.Mock(side_effect=Cancelled))

    def test_storage_failure_is_optional(self):
        with mock.patch.object(v, "_atomic", side_effect=PermissionError("read only")):
            asset, rec = v.prepare(self.p, "static")
        self.assertIsNone(asset)
        self.assertEqual(rec["state"], "failed")

    def test_cache_metadata_cannot_choose_a_path_or_change_the_mode(self):
        a, _ = v.prepare(self.p, "static")
        folder = v._folder(self.p["lumen_id"])
        meta = folder / (a["spec_hash"] + ".json")
        original = json.loads(meta.read_text("utf-8"))
        outside = store.DATA / "outside.png"
        outside.write_bytes(a["data"])
        for changes in ({"file": str(outside)}, {"mode": "animated"}, {"renderer": "old"}):
            meta.write_text(json.dumps({**original, **changes}), "utf-8")
            b, _ = v.prepare(self.p, "static")
            self.assertFalse(b["cached"], changes)
        self.assertEqual(outside.read_bytes(), a["data"])

    def test_cancel_also_applies_to_static_cache_and_lock_wait(self):
        from lumen import Cancelled
        cancel = mock.Mock(side_effect=Cancelled)
        v.prepare(self.p, "static")
        with self.assertRaises(Cancelled):
            v.prepare(self.p, "static", cancel)
        with self.assertRaises(Cancelled):
            v.render(v.spec(self.p), "static", cancel)


def visuals(blocks):
    return [b for b in blocks if b["type"] == "image" and "Visualização 3D" in json.dumps(b, ensure_ascii=False)]


def after_central_idea(blocks):
    """O bloco logo depois da Ideia central de cada aula da página."""
    return [blocks[i + 1] for i, b in enumerate(blocks) if b["type"] == "callout"
            and "Ideia central" in json.dumps(b, ensure_ascii=False)]


class Pages(unittest.TestCase):
    """A matriz: cada tipo de página que o Lumen gera, nos dois destinos. Um visual por material, no mesmo lugar."""
    def setUp(self):
        tf.Destinations.setUp(self)
        self.chat = mock.patch.object(llm, "_chat", return_value=json.dumps(RICH))
        self.chat.start()

    def tearDown(self):
        # Os patches se desfazem na ordem inversa: este (empilhado sobre o do Flow) primeiro. Parado depois do tearDown do Flow
        # (como addCleanup fazia), ele devolvia ao llm._chat o mock do Flow, que vazava para os testes seguintes.
        self.chat.stop()
        tf.Flow.tearDown(self)

    note = tf.Destinations.note

    def lesson_ok(self, page_blocks, n=1):
        vs = visuals(page_blocks)
        self.assertEqual(len(vs), n)
        self.assertEqual([b["id"] for b in after_central_idea(page_blocks)], [b["id"] for b in vs])
        return vs

    def note_ok(self, path):
        text = path.read_text("utf-8")
        self.assertEqual(text.count("![[visualização 3d · "), 1)
        name = text.split("![[visualização 3d · ", 1)[1].split("]]", 1)[0]
        self.assertIn("> [!abstract] Ideia central", text.split("![[visualização 3d · ")[0].rsplit("## Visão geral", 1)[1])
        self.assertTrue((path.parent / "Anexos" / f"visualização 3d · {name}").is_file())
        self.assertIn("*Visualização 3D gerada pelo Lumen (animação, esquemática)", text)
        return text

    def no_visual_elsewhere(self, note_path):
        for f in self.vault.rglob("*"):
            if f.suffix in (".md", ".canvas", ".base") and f != note_path:
                self.assertNotIn("visualização 3d", f.read_text("utf-8").casefold(), f.name)

    def test_lesson_in_a_course_module_page(self):
        bio = catalog.create_course("Biologia")
        mod = catalog.create_module(bio["id"], "Plantas", 1)
        j = full({**SPEC, "classification": {"type": "course", "course_id": bio["id"], "module_id": mod["id"]}})
        self.assertEqual(j["status"], "done", j.get("error"))
        e = store.history()["yt:dQw4w9WgXcQ"]
        module, course = self.fake.pages[e["page_id"]], self.fake.pages[self.fake.pages[e["page_id"]]["parent"]]
        self.assertEqual((module["title"], course["title"]), ("Plantas", "Biologia"))
        vs = self.lesson_ok(module["blocks"])
        self.assertEqual(visuals(course["blocks"]), [])  # a página do curso (criada pelo app) não ganha visual
        up = self.fake.uploads[vs[0]["image"]["file_upload"]["id"]]
        self.assertEqual((up["status"], up["content_type"]), ("uploaded", "image/gif"))
        self.assertEqual(e["notion_visual"]["state"], "confirmed")  # lido de volta e comparado
        self.assertEqual(e["notion_visual"]["block"], vs[0]["id"])
        self.assertIn(notion.visual_marker(e["lumen_id"]), json.dumps(vs[0], ensure_ascii=False))
        sub = [p for p in self.fake.pages.values() if p["title"] == notion.UNDERSTANDING][0]
        self.assertEqual(visuals(sub["blocks"]), [])  # “Minha compreensão” é do estudante: sem visual
        note = self.vault / e["obsidian"]["note"]
        self.note_ok(note)
        self.no_visual_elsewhere(note)  # 00 - Estudos, a nota do curso, a Base e os Canvas: nada
        self.assertEqual((j["result"]["visual"]["state"], j["result"]["visual"]["notion"]), ("ok", "confirmed"))
        self.assertTrue(j["result"]["visual"]["obsidian"]["file"].endswith(".gif"))
        rec = e["visual"]
        self.assertTrue({"spec_hash", "renderer", "mode", "file", "width", "height", "bytes", "state", "family"} <= set(rec))
        self.assertNotIn("data", rec)

    def test_free_content_page_is_the_lessons_own_page(self):
        free = self.fake.add_page("Conteúdo gratuito")
        store.save_config({**store.load_config(), "notion_free_page_id": free, "notion_free_page_title": "Conteúdo gratuito"})
        j = full({**SPEC, "classification": {"type": "free", "category": "Biologia"}})
        self.assertEqual(j["status"], "done", j.get("error"))
        e = store.history()["yt:dQw4w9WgXcQ"]
        self.assertTrue(e["notion_own"])  # página física criada só para este material
        self.lesson_ok(self.fake.pages[e["page_id"]]["blocks"])
        self.assertEqual(visuals(self.fake.pages[free]["blocks"]), [])
        self.note_ok(self.vault / e["obsidian"]["note"])

    def test_two_lessons_in_one_shared_page_get_one_visual_each(self):
        """Aula avulsa e “A organizar” vão para a página compartilhada “Sem curso”: cada aula com o seu visual, e
        atualizar uma não mexe na outra."""
        self.assertEqual(full({**SPEC, "classification": {"type": "single", "category": "Biologia"}})["status"], "done")
        other = {**RICH, "title": "Respiração celular", "mind_map": {**MAP, "center": "Respiração"}}
        with mock.patch.object(llm, "_chat", return_value=json.dumps(other)):
            self.assertEqual(full({**SPEC, "url": "https://youtu.be/aaaaaaaaaaa"})["status"], "done")  # A organizar
        h = store.history()
        a, b = h["yt:dQw4w9WgXcQ"], h["yt:aaaaaaaaaaa"]
        self.assertEqual(a["page_id"], b["page_id"])
        page = self.fake.pages[a["page_id"]]
        vs = self.lesson_ok(page["blocks"], 2)
        self.assertNotEqual(*[notion.visual_marker(x["lumen_id"]) for x in (a, b)])
        keep_b = b["notion_visual"]["block"]
        self.assertEqual(full({**SPEC, "classification": {"type": "single", "category": "Biologia"}, "mode": "replace"})["status"], "done")
        vs2 = self.lesson_ok(page["blocks"], 2)
        self.assertIn(keep_b, [x["id"] for x in vs2])  # o da outra aula ficou
        self.assertNotIn(a["notion_visual"]["block"], [x["id"] for x in vs2])  # o antigo desta saiu
        self.assertEqual(len({x["id"] for x in vs} | {x["id"] for x in vs2}), 3)

    def test_reprocessing_is_idempotent_and_reuses_the_drawing(self):
        self.assertEqual(full(dict(SPEC))["status"], "done")
        files = sorted(p.relative_to(self.vault).as_posix() for p in self.vault.rglob("*") if p.is_file())
        note = self.note()
        before = note.read_text("utf-8")
        with mock.patch.object(v, "render", side_effect=AssertionError("desenhou de novo")):
            jobs.start("process", jobs.deliver, {"key": "yt:dQw4w9WgXcQ", "only": ["obsidian", "notion"], "mode": "replace"})
            j = wait()
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(j["result"]["obsidian"]["state"], "unchanged")
        self.assertEqual(sorted(p.relative_to(self.vault).as_posix() for p in self.vault.rglob("*") if p.is_file()), files)
        self.assertEqual(note.read_text("utf-8"), before)
        page = self.fake.pages[store.history()["yt:dQw4w9WgXcQ"]["page_id"]]
        self.lesson_ok(page["blocks"])
        # “Tentar de novo só o Notion”: o mesmo arquivo, enviado de novo, sem desenhar
        with mock.patch.object(v, "render", side_effect=AssertionError("desenhou de novo")):
            jobs.start("process", jobs.deliver, {"key": "yt:dQw4w9WgXcQ", "only": ["notion"], "mode": "replace"})
            self.assertEqual(wait()["status"], "done")
        self.lesson_ok(page["blocks"])

    def test_update_keeps_user_content_and_a_visual_the_user_embedded(self):
        self.assertEqual(full(dict(SPEC))["status"], "done")
        note = self.note()
        gif = next((note.parent / "Anexos").glob("visualização 3d · *.gif"))
        note.write_text(note.read_text("utf-8") + "\nMinha anotação sobre a fotossíntese.\n", "utf-8")
        store.save_config({**store.load_config(), "visual_3d": "static"})
        self.assertEqual(full({**SPEC, "mode": "replace"})["status"], "done")
        text = note.read_text("utf-8")
        self.assertIn("Minha anotação sobre a fotossíntese.", text)
        self.assertIn("(imagem estática, esquemática)", text)
        self.assertFalse(gif.exists())  # o GIF que só o Lumen usava saiu
        png = next((note.parent / "Anexos").glob("visualização 3d · *.png"))
        (self.vault / "Outra nota.md").write_text(f"Uso esta imagem: ![[{png.name}]]\n", "utf-8")  # o usuário embutiu
        store.save_config({**store.load_config(), "visual_3d": "off"})
        self.assertEqual(full({**SPEC, "mode": "replace"})["status"], "done")
        self.assertNotIn("visualização 3d", note.read_text("utf-8").casefold())
        self.assertTrue(png.exists())  # ainda citado em outra nota: não é apagado
        self.assertEqual(visuals(self.fake.pages[store.history()["yt:dQw4w9WgXcQ"]["page_id"]]["blocks"]), [])

    def test_modes_static_and_off(self):
        store.save_config({**store.load_config(), "visual_3d": "static"})
        self.assertEqual(full(dict(SPEC))["status"], "done")
        vs = self.lesson_ok(self.fake.pages[store.history()["yt:dQw4w9WgXcQ"]["page_id"]]["blocks"])
        self.assertEqual(self.fake.uploads[vs[0]["image"]["file_upload"]["id"]]["content_type"], "image/png")
        self.assertIn("imagem estática", json.dumps(vs[0], ensure_ascii=False))
        self.assertTrue(list(self.vault.rglob("visualização 3d · *.png")))
        store.save_config({**store.load_config(), "visual_3d": "off"})
        with mock.patch.object(v, "prepare", side_effect=AssertionError("desenhou com a opção desligada")):
            j = full({**SPEC, "url": "https://youtu.be/bbbbbbbbbbb"})
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(store.history()["yt:bbbbbbbbbbb"]["visual"], {"state": "off", "mode": "off"})

    def test_renderer_failure_keeps_the_text_in_both(self):
        with mock.patch.object(v, "_frame", side_effect=RuntimeError("quebrou")):
            j = full(dict(SPEC))
        self.assertEqual((j["result"]["notion"]["status"], j["result"]["obsidian"]["status"]), ("ok", "ok"))
        self.assertEqual(j["result"]["visual"]["state"], "failed")
        page = self.fake.pages[store.history()["yt:dQw4w9WgXcQ"]["page_id"]]
        self.assertEqual(visuals(page["blocks"]), [])
        self.assertIn("Plantas produzem glicose.", json.dumps(page["blocks"], ensure_ascii=False))
        self.assertNotIn("visualização 3d", self.note().read_text("utf-8").casefold())

    def test_upload_failure_uses_the_png_then_none(self):
        sleep = mock.patch.object(jobs, "time", types.SimpleNamespace(sleep=lambda s: None, monotonic=__import__("time").monotonic))  # as novas tentativas do envio, sem esperar
        sleep.start()
        self.addCleanup(sleep.stop)
        self.fake.fail_types = {"image/gif"}
        self.assertEqual(full(dict(SPEC))["status"], "done")
        e = store.history()["yt:dQw4w9WgXcQ"]
        vs = self.lesson_ok(self.fake.pages[e["page_id"]]["blocks"])
        self.assertEqual(self.fake.uploads[vs[0]["image"]["file_upload"]["id"]]["content_type"], "image/png")
        self.assertEqual((e["notion_visual"]["kind"], e["notion_visual"]["state"]), ("png", "confirmed"))
        self.assertTrue(list(self.vault.rglob("visualização 3d · *.gif")))  # o Obsidian recebeu a animação
        self.fake.fail_types = {"image/gif", "image/png"}
        j = full({**SPEC, "mode": "replace"})
        self.assertEqual(j["result"]["notion"]["status"], "ok")
        self.assertEqual(visuals(self.fake.pages[e["page_id"]]["blocks"]), [])
        self.assertEqual(store.history()["yt:dQw4w9WgXcQ"]["notion_visual"]["state"], "upload-failed")

    def test_uncertain_publication_is_reconciled_before_trying_again(self):
        self.fake.lose_reply = 1  # o Notion grava a aula, mas a resposta se perde
        j = full(dict(SPEC))
        self.assertEqual(j["result"]["notion"]["status"], "error")
        page = [p for p in self.fake.pages.values() if p["title"] == notion.NO_COURSE][0]
        self.assertEqual(len(visuals(page["blocks"])), 1)  # ficou na página, sem registro
        self.assertEqual(store.history()["yt:dQw4w9WgXcQ"]["notion_visual"]["state"], "pending")
        jobs.start("process", jobs.deliver, {"key": "yt:dQw4w9WgXcQ", "only": ["notion"]})
        self.assertEqual(wait()["status"], "done")
        self.lesson_ok(page["blocks"])
        self.assertEqual(len(visuals(page["blocks"])), 1)  # o visual não duplicou
        self.assertEqual(store.history()["yt:dQw4w9WgXcQ"]["notion_visual"]["state"], "confirmed")

    def test_user_replacement_with_the_same_size_is_not_overwritten_or_deleted(self):
        self.assertEqual(full(dict(SPEC))["status"], "done")
        gif = next(self.vault.rglob("visualização 3d · *.gif"))
        user_data = b"u" * gif.stat().st_size
        gif.write_bytes(user_data)
        self.assertEqual(full({**SPEC, "mode": "replace"})["status"], "done")
        self.assertEqual(gif.read_bytes(), user_data)
        store.save_config({**store.load_config(), "visual_3d": "off"})
        self.assertEqual(full({**SPEC, "mode": "replace"})["status"], "done")
        self.assertEqual(gif.read_bytes(), user_data)

    def test_unconfirmed_check_is_reported_not_repeated(self):
        real = notion.request

        def flaky(method, path, *a, **kw):
            if method == "GET" and path.startswith("/blocks/") and "/children" not in path:
                raise notion.Unconfirmed("sem resposta", "")
            return real(method, path, *a, **kw)
        with mock.patch.object(notion, "request", side_effect=flaky):
            j = full(dict(SPEC))
        self.assertEqual(j["result"]["notion"]["visual"], "unconfirmed")
        page = self.fake.pages[store.history()["yt:dQw4w9WgXcQ"]["page_id"]]
        self.assertEqual(len(visuals(page["blocks"])), 1)

    def test_old_package_without_the_visual_is_updated_explicitly(self):
        """Uma aula salva antes da visualização: o pacote guardado não tem nada dela, e só ganha o visual quando o
        usuário a salva de novo (nenhuma página antiga muda sozinha)."""
        store.save_config({**store.load_config(), "visual_3d": "off"})
        self.assertEqual(full(dict(SPEC))["status"], "done")
        page = self.fake.pages[store.history()["yt:dQw4w9WgXcQ"]["page_id"]]
        self.assertEqual(visuals(page["blocks"]), [])
        store.save_config({**store.load_config(), "visual_3d": "animated"})
        self.assertEqual(visuals(page["blocks"]), [])  # ligar não mexe em nada sozinho
        jobs.start("process", jobs.deliver, {"key": "yt:dQw4w9WgXcQ", "only": ["notion", "obsidian"], "mode": "replace"})
        self.assertEqual(wait()["status"], "done")
        self.lesson_ok(page["blocks"])
        self.note_ok(self.note())

    def test_moving_the_lesson_keeps_one_visual_and_the_embed(self):
        self.assertEqual(full(dict(SPEC))["status"], "done")
        bio = catalog.create_course("Biologia")
        with mock.patch.object(v, "render", side_effect=AssertionError("desenhou de novo")):
            jobs.start("organize", jobs.organize, {"key": "yt:dQw4w9WgXcQ", "classification": {"type": "course",
                                                                                               "course_id": bio["id"]}})
            self.assertEqual(wait()["status"], "done")
        e = store.history()["yt:dQw4w9WgXcQ"]
        self.lesson_ok(self.fake.pages[e["page_id"]]["blocks"])
        old = [p for p in self.fake.pages.values() if p["title"] == notion.NO_COURSE][0]
        self.assertEqual(visuals(old["blocks"]), [])
        self.note_ok(self.vault / e["obsidian"]["note"])  # a pasta inteira foi junto: o anexo e o embed valem

    def test_synthetic_visual_never_becomes_a_lesson_screen_or_the_cover(self):
        from lumen import board
        self.assertEqual(full(dict(SPEC))["status"], "done")
        text = self.note().read_text("utf-8")
        self.assertNotIn("cover:", text.split("---")[1])  # sem telas: nenhuma capa, nem o visual
        with mock.patch.object(board, "plan", wraps=board.plan) as plan:
            jobs.start("process", jobs.deliver, {"key": "yt:dQw4w9WgXcQ", "only": ["obsidian"]})
            self.assertEqual(wait()["status"], "done")
        for call in plan.call_args_list:
            self.assertFalse([p for p in call.args[1] if "visualização" in p["file"]])

    def test_settings_and_the_preview_route(self):
        cfg = server._apply_settings({"visual_3d": "static"})
        self.assertEqual(cfg["visual_3d"], "static")
        self.assertEqual(server._apply_settings({"visual_3d": "rm -rf /"})["visual_3d"], "static")
        store.save_config({**store.load_config(), "visual_3d": "animated"})
        self.assertEqual(full(dict(SPEC))["status"], "done")
        h = lambda **q: types.SimpleNamespace(_query=lambda: q)  # noqa: E731
        data, ctype = server._visual_file(h(key="yt:dQw4w9WgXcQ"))
        self.assertEqual((data[:6], ctype), (b"GIF89a", "image/gif"))
        data, ctype = server._visual_file(h(key="yt:dQw4w9WgXcQ", kind="png"))
        self.assertEqual((data[:4], ctype), (b"\x89PNG", "image/png"))
        for bad in ("yt:nao-existe", "../../x"):
            with self.assertRaises(Exception):
                server._visual_file(h(key=bad))

    def test_nothing_is_drawn_before_the_understanding(self):
        jobs.start("process", jobs.process, dict(SPEC))
        j = wait()
        self.assertTrue(j["result"]["review"])
        self.assertFalse((store.DATA / "visuals").exists() and any((store.DATA / "visuals").iterdir()))


if __name__ == "__main__":
    unittest.main()
