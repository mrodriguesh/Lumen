"""Falhas de retomada que exigem preservar arquivos e blocos, sem repetir uma escrita incerta."""
import copy
import json
import unittest
from unittest import mock

import tests
from lumen import AppError, Cancelled, notion, visual3d as v
from tests.fake_notion import Fake
from tests.test_visual3d import RICH, pkg


class Cache(unittest.TestCase):
    def test_fallback_is_cached_until_an_explicit_new_render(self):
        p = pkg(RICH, "lm-000000000000ffaa")
        with mock.patch.object(v, "ATTEMPTS", ()):
            a, _ = v.prepare(p, "animated", refresh=True)
        self.assertEqual((a["kind"], a["state"]), ("png", "static-fallback"))
        with mock.patch.object(v, "render", side_effect=AssertionError("redesenhou")):
            b, _ = v.prepare(p, "animated")
        self.assertTrue(b["cached"])
        c, _ = v.prepare(p, "animated", refresh=True)
        self.assertEqual(c["kind"], "gif")

    def test_cancel_while_waiting_for_renderer(self):
        check = mock.Mock(side_effect=[None, Cancelled])
        with v._LOCK, self.assertRaises(Cancelled):
            v.prepare(pkg(RICH), "static", check)

    def test_many_long_labels_do_not_overlap_in_any_frame(self):
        with mock.patch.multiple(v, **tests.REAL_VISUAL):
            labels = ["Conceito extenso com palavras suficientes para ocupar duas linhas " + str(i) for i in range(7)]
            p = pkg({**RICH, "mind_map": {"center": "Tema com rótulos longos", "branches": [
                {"label": s, "children": []} for s in labels]}})
            sc = v._scene(v.spec(p)); layout = v._layout(sc, 960, 540, 1)
            for k in range(48):
                cam, boxes = v._Cam(sc["cam"], k / 48, 960, 540), []
                for i, item in layout.items():
                    point = cam.project(sc["labels"][i]["at"])[0][0]
                    x, y = item["fixed"] if "fixed" in item else point + item["off"]
                    box = (x, y, x + item["pw"], y + item["ph"])
                    self.assertTrue(0 <= x < box[2] <= 960 and 0 <= y < box[3] <= 500)
                    self.assertFalse(any(v._overlap(box, b) for b in boxes), (k, i))
                    boxes.append(box)


class Journal(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.addCleanup(self.fake.close)
        self.root = self.fake.add_page("Teste de retomada")
        self.journal = {}
        self.saved = None
        self.blocks = [notion._b("paragraph", notion._rt("Material de teste"))]

    def save(self, value):
        self.saved = json.loads(json.dumps(value))  # como um reinício: só o JSON persistido sobrevive

    def publish(self, **kw):
        return notion.publish("secret_test", self.root, "Teste", self.blocks, lambda: None,
                              journal=self.journal, save=self.save, **kw)

    def lost(self):
        self.fake.lose_reply = 1
        with self.assertRaises(notion.Unconfirmed):
            self.publish()
        self.assertEqual(self.saved["ops"][0]["state"], "pending")
        self.journal = self.saved

    def test_changed_integration_or_content_is_refused_without_writing(self):
        self.lost()
        before = len(self.fake.calls)
        self.journal["bot"] = "another-bot"
        with self.assertRaises(AppError):
            self.publish()
        self.assertFalse(any(m in ("POST", "PATCH", "DELETE") for m, _ in self.fake.calls[before:]))
        self.journal["bot"] = "lumen-test-bot"
        self.blocks = [notion._b("paragraph", notion._rt("Outro conteúdo"))]
        with self.assertRaises(AppError):
            self.publish()

    def test_user_copy_is_kept_and_not_adopted(self):
        self.lost()
        original = self.fake.pages[self.root]["blocks"]
        copies = copy.deepcopy(original)
        for i, block in enumerate(copies):
            block.update(id=f"copy-{i}", created_by={"id": "user"})
        original.extend(copies)
        _, _, ids = self.publish()
        self.assertEqual(ids, [b["id"] for b in original[:2]])
        self.assertEqual(len(original), 4)
        self.assertFalse(any(m == "DELETE" for m, _ in self.fake.calls))

    def test_ambiguous_or_user_edited_sequence_is_preserved(self):
        self.lost()
        blocks = self.fake.pages[self.root]["blocks"]
        blocks[0]["last_edited_by"] = {"id": "user"}
        with self.assertRaises(notion.Unconfirmed):
            self.publish()
        blocks[0].pop("last_edited_by")
        copies = copy.deepcopy(blocks)
        for i, block in enumerate(copies):
            block["id"] = f"ambiguous-{i}"
        blocks.extend(copies)
        with self.assertRaises(notion.Unconfirmed):
            self.publish()
        self.assertEqual(len(blocks), 4)
        self.assertFalse(any(m == "DELETE" for m, _ in self.fake.calls))

    def test_lost_subpage_and_long_transcript_resume_without_duplicates(self):
        transcript = [f"Linha {i}" for i in range(230)]
        sub = [notion._b("paragraph", notion._rt("Compreensão de teste"))]
        route = self.fake.route
        def lose_page(method, path, body):
            result = route(method, path, body)
            return (502, {"code": "bad_gateway"}) if method == "POST" and path == "/pages" else result
        with mock.patch.object(self.fake, "route", side_effect=lose_page), self.assertRaises(notion.Unconfirmed):
            self.publish(transcript=transcript, subpage=sub)
        self.journal = self.saved
        before = len(self.fake.calls)
        _, _, ids = self.publish(transcript=transcript, subpage=sub)
        self.assertFalse(any(m in ("POST", "PATCH", "DELETE") for m, _ in self.fake.calls[before:]))
        self.assertEqual(len(self.fake.pages), 2)
        self.assertEqual(len(ids), 4)
        head = self.fake.pages[self.root]["blocks"][-1]
        self.assertEqual(len(head["heading_3"]["children"]), 230)
