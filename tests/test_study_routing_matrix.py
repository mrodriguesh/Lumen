"""Modo × esforço × modelo/papel do catálogo, com o Ollama falso: rota escolhida, modelo de cada chamada, raciocínio, tetos,
tempo-limite, revisão e as chamadas que não precisam acontecer (entender sem nada a decidir; trocar de modelo no meio)."""
import threading
import time
from unittest import mock

import tests  # noqa: F401
from lumen.study import agent, search, settings
from tests.test_study_core import Core, run_turn

# Os modelos de chat instalados neste PC (15/11/2026) e os papéis que as Configurações deixam escolher.
MAIN, BIG, OTHER, ADULT = "qwen3.5:4b", "qwen3.5:9b", "qwen3:8b", "qwen3.5-heretic:9b"
CATALOG = (MAIN, BIG, OTHER, ADULT, "qwen3-embedding:0.6b")
# (nome, ajustes, papéis esperados: responder, rápido, máximo; adulto = um modelo em tudo)
CONFIGS = [
    ("automatico-4b", {"models": {"local": MAIN}}, (MAIN, MAIN, BIG)),
    ("principal-9b", {"models": {"local": BIG}}, (BIG, BIG, BIG)),
    ("principal-8b", {"models": {"local": OTHER}}, (OTHER, OTHER, BIG)),
    ("papeis-distintos", {"models": {"local": OTHER, "fast": MAIN, "max": BIG}}, (OTHER, MAIN, BIG)),
    ("adulto", {"models": {"local": MAIN}, "adult": {"enabled": True, "mode": "adult"}}, (ADULT, ADULT, ADULT)),
]
MODES = ("", "explain", "summary", "compare", "find")  # os da tela que chamam a IA ("Só buscar" não chama)
EFFORTS = ("", "rapido", "equilibrado", "profundo", "maximo")
ROUTED = "equilibrado"  # o que o roteador falso (FakeOllama.default_json) devolve


class Matrix(Core):
    def setUp(self):
        super().setUp()
        self.ollama.models[:] = list(CATALOG)
        self.limits, self.searches = [], []
        real_turn, real_search = agent._turn, search.search

        def spy_turn(payload, turn_id, check, limit=None):
            self.limits.append(limit)
            return real_turn(payload, turn_id, check, limit)

        def spy_search(*a, **k):
            self.searches.append(k.get("limit"))
            return real_search(*a, **k)
        for p in (mock.patch.object(agent, "_turn", spy_turn), mock.patch.object(search, "search", spy_search)):
            p.start()
            self.addCleanup(p.stop)

    def calls(self, since):
        out = self.ollama.requests[since:]
        chat = [b for p, b in out if p == "/api/chat" and not b.get("format")]
        js = [b for p, b in out if p == "/api/chat" and b.get("format")]
        router = [b for b in js if "analisa pedidos de estudo" in b["messages"][0]["content"]]
        return chat, js, router

    def test_every_mode_effort_and_model_role(self):
        for name, cfg, (answer, fast, big) in CONFIGS:
            settings.save({"models": {"local": "", "fast": "", "max": ""}, "adult": {"enabled": False, "mode": "auto"}})
            settings.save(cfg)
            adult = name == "adulto"
            for free in (True, False):
                for mode in MODES:
                    for effort in EFFORTS:
                        with self.subTest(config=name, free=free, mode=mode or "auto", effort=effort or "auto"):
                            self.check_turn(adult, answer, fast, big, free, mode, effort)

    def check_turn(self, adult, answer, fast, big, free, mode, effort):
        n, nlim, nsearch = len(self.ollama.requests), len(self.limits), len(self.searches)
        events = run_turn({"text": "Como o sono ajuda a memória?", "mode": mode, "effort": effort, "skip_vault": free})
        self.assertEqual(events[-1]["type"], "done", events[-1])
        meta = events[-1]["message"]["meta"]
        u = next(e for e in events if e["type"] == "understanding")["understanding"]
        want_effort, want_mode = effort or ROUTED, mode or "explain"
        lv = agent.EFFORT[want_effort]
        # rota escolhida e o que foi automático
        self.assertEqual((u["mode"], u["effort"], meta["mode"], meta["effort"]), (want_mode, want_effort, want_mode, want_effort))
        self.assertEqual(meta["auto"], {"mode": not mode, "effort": not effort})
        chat, js, router = self.calls(n)
        model = answer if adult else fast if want_effort == "rapido" else big if want_effort == "maximo" else answer
        aux = model if adult or want_effort in ("rapido", "maximo") else fast
        # entender só quando há algo a decidir ou a buscar
        self.assertEqual(len(router), 0 if (mode and effort and free) else 1)
        # resposta: modelo, raciocínio, teto e ferramentas; o Máximo revisa (mais uma chamada, sem ferramentas)
        self.assertEqual(len(chat), 2 if want_effort == "maximo" else 1)
        self.assertEqual({(b["model"], b["think"], b["options"]["num_predict"]) for b in chat},
                         {(model, lv["think"], 8192 if lv["think"] else 4096)})
        self.assertIn("tools", chat[0])
        if want_effort == "maximo":
            self.assertNotIn("tools", chat[1])
            self.assertEqual(chat[1]["messages"][-1]["content"], agent.REVIEW)
        self.assertEqual((meta["model"], meta["reviewed"]), (model, want_effort == "maximo"))
        # entender, extras da explicação, título e memória: um só modelo, o do papel (sem trocar de modelo no HD no meio)
        self.assertLessEqual({b["model"] for b in js}, {aux})  # vazio no perfil adulto sem nada a decidir: nem título nem memória
        explained = want_mode == "explain" and want_effort != "rapido"
        self.assertEqual("explain" in meta, explained)
        # tempo-limite e fontes do nível
        self.assertEqual(self.limits[nlim]["seconds"], lv["seconds"])
        self.assertEqual(self.searches[nsearch:], [] if free else [agent._sources(want_effort, settings.load())])

    def test_explicit_max_request_routes_on_the_max_model_only(self):
        settings.save({"models": {"local": MAIN}})
        n = len(self.ollama.requests)
        events = run_turn({"text": "Explique com o máximo de cuidado como o sono consolida a memória"})
        meta = events[-1]["message"]["meta"]
        self.assertEqual((meta["effort"], meta["auto"]["effort"], meta["reviewed"]), ("maximo", True, True))
        chat, js, router = self.calls(n)
        self.assertEqual({b["model"] for b in chat + js}, {BIG}, "nenhuma chamada carrega o modelo rápido no meio do Máximo")
        self.assertEqual(len(router), 1)

    def test_manual_override_beats_router_and_is_persisted(self):
        settings.save({"models": {"local": MAIN}})
        self.ollama.json_replies["analisa pedidos de estudo"] = {
            "intent": "find", "topic": "sono", "query": "sono", "keywords": ["sono"], "expansions": [], "level": "",
            "needs_web": False, "effort": "rapido", "reason": "achou"}
        auto = run_turn({"text": "sono e memória"})
        cid = next(e for e in auto if e["type"] == "conversation")["conversation"]["id"]
        self.assertEqual((auto[-1]["message"]["meta"]["mode"], auto[-1]["message"]["meta"]["effort"]), ("find", "rapido"))
        manual = run_turn({"text": "e o hipocampo?", "conversation_id": cid, "mode": "summary", "effort": "profundo",
                           "override": {"from": {"mode": "find", "effort": "rapido"}, "to": {"mode": "summary", "effort": "profundo"}}})
        meta = manual[-1]["message"]["meta"]
        self.assertEqual((meta["mode"], meta["effort"], meta["auto"]), ("summary", "profundo", {"mode": False, "effort": False}))
        from lumen.study import activity, chats
        self.assertEqual([x["target"] for x in activity.recent(action="troca-automatico")], ["mode: find → summary, effort: rapido → profundo"])
        saved = chats.get(cid)["messages"][-1]["meta"]  # o que a tela relê ao abrir a conversa
        self.assertEqual((saved["mode"], saved["effort"], saved["model"]), ("summary", "profundo", MAIN))
        regen = run_turn({"conversation_id": cid, "regenerate": True, "mode": "", "effort": ""})  # refazer repete modo e esforço
        self.assertEqual((regen[-1]["message"]["meta"]["mode"], regen[-1]["message"]["meta"]["effort"]), ("summary", "profundo"))

    def test_cancel_during_streaming_and_review(self):
        settings.save({"models": {"local": MAIN}})
        self.ollama.delay, self.ollama.gate = 0.01, threading.Event()
        events = []
        t = threading.Thread(target=lambda: events.extend(agent.turn({"text": "Sono", "mode": "explain", "effort": "maximo",
                                                                      "skip_vault": True}, "cancel-max-0001")))
        t.start()
        deadline = time.monotonic() + 20
        while not any(e.get("type") == "delta" for e in events) and time.monotonic() < deadline:
            time.sleep(0.02)
        agent.cancel("cancel-max-0001")
        self.ollama.gate.set()
        t.join(30)
        self.assertFalse(t.is_alive())
        self.assertEqual(events[-1]["type"], "cancelled")
        self.assertNotIn("done", [e["type"] for e in events])
        self.assertEqual(agent.ACTIVE, {})

    def test_time_limit_follows_the_level(self):
        settings.save({"models": {"local": MAIN}})
        self.ollama.delay = 0.05
        with mock.patch.dict(agent.EFFORT, {"rapido": {**agent.EFFORT["rapido"], "seconds": 0.2}}):
            events = run_turn({"text": "Sono", "mode": "explain", "effort": "rapido", "skip_vault": True})
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("tempo limite", events[-1]["message"])
        self.assertEqual(agent.ACTIVE, {})

    def test_missing_role_model_fails_clearly_or_falls_back(self):
        settings.save({"models": {"local": MAIN, "max": "nao-instalado:1b"}})
        events = run_turn({"text": "Sono", "mode": "explain", "effort": "maximo", "skip_vault": True})
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("nao-instalado:1b", events[-1]["message"])
        self.ollama.no_think.add(BIG)
        self.ollama.no_tools.add(BIG)
        settings.save({"models": {"max": ""}})
        events = run_turn({"text": "Sono", "mode": "explain", "effort": "maximo", "skip_vault": True})
        self.assertEqual(events[-1]["type"], "done")  # sem raciocínio nem ferramentas, o maior ainda responde e revisa
        self.assertTrue(events[-1]["message"]["meta"]["reviewed"])
