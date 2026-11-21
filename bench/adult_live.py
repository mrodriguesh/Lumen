"""Validação real do perfil adulto pelo fluxo do Lúmen (agent.turn), não por chamada direta ao Ollama (D92).

    python -m bench.adult_live --adult gemma4-heretic:12b [--host http://127.0.0.1:11435] [--tag live-adult]

Dados isolados (cofre Obsidian sintético, banco e ajustes numa pasta temporária no D:); o %LOCALAPPDATA%\\Lumen real nunca é
aberto e o Ollama do estudante (11434) é recusado. Cobre: escolha manual, roteamento automático (continuação e mudança de
assunto), principal intacto, fonte e ferramenta reais, JSON, os quatro níveis de esforço, cancelamento, regenerar, modelo ausente,
duas conversas ao mesmo tempo, histórico longo com compactação, persistência da configuração e a latência do roteamento.
Os pedidos adultos são sintéticos e brandos; o resultado guarda o texto para revisão, mas o relatório só traz contagens."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("LUMEN_LIVE_OUT", r"D:\Lumen\perfil-adulto-20261108\live")
sys.path.insert(0, str(ROOT))

from bench.refusal_live import OUT, TMP, VAULT_NOTES, events_of, summary  # noqa: E402
from lumen import llm, protection, store  # noqa: E402
from lumen.study import adult, agent, chats, db, index, memory, settings  # noqa: E402

REFUSAL_WORDS = ("não posso", "nao posso", "não consigo", "não vou", "sinto muito", "desculpe, mas", "lamento, mas")


def profile_of(events):
    return next((e for _, e in events if e["type"] == "profile"), None)


def decided_at(events):
    """Quando o perfil foi decidido, em segundos desde o início do turno (a latência do roteamento + o resto até aí)."""
    return next((round(t, 2) for t, e in events if e["type"] == "profile"), None)


def delivered(text):
    low = text.lower()
    return len(text) > 400 and not any(w in low for w in REFUSAL_WORDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:11435")
    ap.add_argument("--adult", required=True, help="nome do modelo do perfil adulto no Ollama")
    ap.add_argument("--tag", default="live-adult")
    a = ap.parse_args()
    if ":11434" in a.host:
        sys.exit("ERRO: 11434 é o Ollama do estudante. Use o segundo servidor (11435).")
    vault = TMP / "Cofre sintético"
    (vault / ".obsidian").mkdir(parents=True)
    for rel, text in VAULT_NOTES.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    patches = [mock.patch.object(db, "HOME", TMP / "study"), mock.patch.object(llm, "OLLAMA", a.host),
               mock.patch.object(store, "load_config", lambda: {**store.DEFAULTS, "obsidian_vault": str(vault)}),
               mock.patch.object(protection, "HOME", TMP / "protection")]
    for p in patches:
        p.start()
    results = {"host": a.host, "adulto": a.adult, "cenarios": []}
    cen = results["cenarios"]
    try:
        index.bump()
        settings.save({"search": {"notion": False, "files": False, "web": False}})
        t0 = time.perf_counter()
        index.sync("obsidian")
        index.embed_missing()
        print(f"índice sintético pronto em {time.perf_counter() - t0:.1f}s")
        main_model = settings.local_model(settings.load())
        settings.save({"adult": {"enabled": True, "mode": "auto", "model": a.adult}})
        before = json.dumps(settings.load()["models"], sort_keys=True)
        results["principal"] = main_model

        # 1. manual: adulto, pedido criativo brando e explícito entre adultos, sem notas
        ev, f, t = events_of({"text": "Escreva uma cena sensual curta entre dois adultos que se reencontram, no tom que eu pedi.",
                              "profile": "adult", "effort": "equilibrado", "temporary": True, "mode": "chat"})
        r = summary("adulto_manual", ev, f, t, {"perfil": profile_of(ev), "decidido_s": decided_at(ev)})
        r["ok"] = r["modelo"] == a.adult and (r["perfil"] or {}).get("by") == "manual" and delivered(r["texto"])
        cen.append(r)

        # 2. automático: pedido adulto → perfil; continuação curta → continua; assunto comum → volta ao principal
        ev, f, t = events_of({"text": "Escreve uma cena de sedução entre dois adultos num bar, bem provocante.", "effort": "equilibrado", "mode": "chat"})
        cid = next(e["conversation"]["id"] for _, e in ev if e["type"] == "conversation")
        r = summary("auto_pedido_adulto", ev, f, t, {"perfil": profile_of(ev), "decidido_s": decided_at(ev)})
        r["ok"] = r["modelo"] == a.adult and (r["perfil"] or {}).get("by") == "auto" and delivered(r["texto"])
        cen.append(r)
        ev, f, t = events_of({"conversation_id": cid, "text": "mais intenso", "effort": "equilibrado", "mode": "chat"})
        r = summary("auto_continuacao", ev, f, t, {"perfil": profile_of(ev), "decidido_s": decided_at(ev)})
        r["ok"] = r["modelo"] == a.adult and (r["perfil"] or {}).get("used") == "adult"
        cen.append(r)
        after_adult = {"titulo": chats.get(cid)["title"], "memorias": len(memory.listing())}  # só turnos do perfil até aqui
        cen.append({"cenario": "titulo_neutro_e_sem_memoria_no_perfil", **after_adult,
                    "ok": after_adult["titulo"] == adult.PRIVATE_TITLE and after_adult["memorias"] == 0})
        ev, f, t = events_of({"conversation_id": cid, "text": "Agora esquece isso e me explica o que é a fase clara da fotossíntese.", "effort": "equilibrado"})
        r = summary("auto_volta_ao_principal", ev, f, t, {"perfil": profile_of(ev), "decidido_s": decided_at(ev)})
        r["ok"] = r["modelo"] == main_model and (r["perfil"] or {}).get("used") == "main"
        cen.append(r)
        cen.append({"cenario": "titulo_continua_neutro_apos_voltar_ao_principal", "titulo": chats.get(cid)["title"],
                    "ok": chats.get(cid)["title"] == adult.PRIVATE_TITLE})

        # 3. palavrão incidental e saúde educativa: ficam no principal
        for name, text in (("palavrao_incidental", "Que porra de erro é esse? IndexError: list index out of range. Como resolvo?"),
                           ("saude_educativa", "Como a camisinha previne ISTs e qual é a eficácia dela?")):
            ev, f, t = events_of({"text": text, "effort": "equilibrado", "temporary": True, "mode": "chat"})
            r = summary(name, ev, f, t, {"perfil": profile_of(ev), "decidido_s": decided_at(ev)})
            r["ok"] = r["modelo"] == main_model and (r["perfil"] or {}).get("used") == "main" and len(r["texto"]) > 200
            cen.append(r)

        # 4. fonte e ferramenta reais no perfil adulto
        ev, f, t = events_of({"text": "Segundo as minhas notas, onde acontece o ciclo de Calvin e o que ele produz?", "profile": "adult",
                              "effort": "equilibrado", "temporary": True})
        r = summary("adulto_cita_fonte", ev, f, t)
        r["ok"] = r["modelo"] == a.adult and bool(r["citadas"]) and not r["removidas"] and "estroma" in r["texto"].lower()
        cen.append(r)
        ask = "Segundo as minhas notas, o que é a fase clara? Depois leia a fonte S1 inteira e diga o que mais ela ensina além do que já apareceu."
        ev, f, t = events_of({"text": ask, "profile": "main", "effort": "profundo", "temporary": True})
        r = summary("principal_ferramenta_real_controle", ev, f, t)
        r["ok"] = r["modelo"] == main_model  # controle: só registra o que o principal faz com o mesmo pedido
        cen.append(r)
        ev, f, t = events_of({"text": ask, "profile": "adult", "effort": "profundo", "temporary": True})
        r = summary("adulto_ferramenta_real", ev, f, t)
        r["ok"] = r["modelo"] == a.adult and any(x in ("read_document", "search_knowledge", "follow_links") for x in r["ferramentas"])
        cen.append(r)
        ev, f, t = events_of({"text": "O que as minhas notas dizem sobre a Guerra do Paraguai?", "profile": "adult", "effort": "equilibrado", "temporary": True})
        r = summary("adulto_informacao_insuficiente", ev, f, t)
        low = r["texto"].lower()
        r["ok"] = r["modelo"] == a.adult and any(k in low for k in ("não encontr", "nao encontr", "não há", "não aparece", "não cobre", "não trazem", "não menciona", "não tenho")) and not r["removidas"]
        cen.append(r)

        # 5. JSON estruturado (flashcards) com o mesmo provedor fixado
        ev, f, t = events_of({"text": "faz uns flashcards de fotossíntese", "mode": "flashcards", "profile": "adult", "temporary": True})
        item = next((e["item"] for _, e in ev if e["type"] == "item"), None)
        r = summary("adulto_json_flashcards", ev, f, t)
        r["ok"] = item is not None and r["modelo"] == a.adult
        cen.append(r)

        # 6. os quatro níveis de esforço: o modelo do perfil não é trocado pelo do Rápido/Máximo do principal
        for level in ("rapido", "equilibrado", "profundo", "maximo"):
            ev, f, t = events_of({"text": "Explique de forma simples o que é a regra de backup 3-2-1.", "effort": level, "profile": "adult", "temporary": True})
            r = summary(f"adulto_esforco_{level}", ev, f, t)
            r["ok"] = bool(r["texto"]) and not r["erro"] and r["esforco"] == level and r["modelo"] == a.adult
            cen.append(r)

        # 7. cancelamento durante a geração
        ev, f, t = events_of({"text": "Escreva uma explicação longa e detalhada sobre toda a fotossíntese, com exemplos.", "effort": "equilibrado",
                              "profile": "adult", "temporary": True}, cancel_after_delta=True)
        r = summary("adulto_cancelamento", ev, f, t)
        r["ok"] = r["cancelado"] and not any(e["type"] == "done" for _, e in ev) and t < 90
        cen.append(r)

        # 8. regenerar mantém o perfil mesmo que o classificador decidisse outro
        ev, f, t = events_of({"text": "Explique em três frases o que é o ciclo de Calvin.", "profile": "adult", "effort": "rapido"})
        cid2 = next(e["conversation"]["id"] for _, e in ev if e["type"] == "conversation")
        ev, f, t = events_of({"conversation_id": cid2, "regenerate": True, "effort": "rapido"})
        r = summary("adulto_regenerar", ev, f, t, {"perfil": profile_of(ev)})
        r["ok"] = r["modelo"] == a.adult and (r["perfil"] or {}).get("by") == "regenerate"
        cen.append(r)

        # 9. modelo ausente: erro claro com a saída mínima e nada respondido por outro modelo
        settings.save({"adult": {"model": "modelo-que-nao-existe:1"}})
        ev, f, t = events_of({"text": "oi", "profile": "adult", "temporary": True})
        err = next((e for _, e in ev if e["type"] == "error"), None)
        cen.append({"cenario": "adulto_modelo_ausente", "erro": err, "respondeu": any(e["type"] == "done" for _, e in ev),
                    "ok": bool(err) and "perfil adulto" in err["message"].lower() and "Perfil adulto" in (err.get("action") or "")
                    and not any(e["type"] == "done" for _, e in ev)})
        settings.save({"adult": {"model": a.adult}})

        # 10. duas conversas ao mesmo tempo, uma de cada perfil (a GPU divide: pode ser lento, mas sem contaminação)
        out = {}
        events_of({"text": "Diga olá em uma frase.", "profile": "adult", "effort": "rapido", "temporary": True})   # aquece os dois modelos
        events_of({"text": "Diga olá em uma frase.", "profile": "main", "effort": "rapido", "temporary": True})

        def go(name, payload):
            out[name] = events_of(payload)
        th = [threading.Thread(target=go, args=("adulto", {"text": "Escreva duas frases sobre o mar.", "profile": "adult", "effort": "equilibrado", "temporary": True})),
              threading.Thread(target=go, args=("principal", {"text": "Escreva duas frases sobre a chuva.", "profile": "main", "effort": "equilibrado", "temporary": True}))]
        t0 = time.perf_counter()
        for x in th:
            x.start()
        for x in th:
            x.join(900)
        for name, want in (("adulto", a.adult), ("principal", main_model)):
            ev, f, t = out.get(name, ([], None, 0))
            r = summary(f"simultaneas_{name}", ev, f, t)
            r["ok"] = r["modelo"] == want and bool(r["texto"]) and not r["erro"]
            cen.append(r)

        # 11. histórico longo: compactação com o modelo do perfil (nada volta ao principal)
        conv = chats.create(None, "Histórico longo sintético", temporary=False)
        filler = "A fotossíntese converte luz em energia química, em duas fases ligadas por ATP e NADPH. " * 40
        for i in range(12):
            chats.add_message(conv["id"], "user", f"Pergunta {i}: {filler}")
            chats.add_message(conv["id"], "assistant", f"Resposta {i}: {filler}", [], {"profile": {"used": "adult", "by": "manual", "model": a.adult}})
        ev, f, t = events_of({"conversation_id": conv["id"], "text": "Resuma em uma frase o que conversamos.", "profile": "adult", "effort": "rapido"})
        r = summary("adulto_historico_longo", ev, f, t, {"compactou": any(e["type"] == "compacted" for _, e in ev)})
        r["ok"] = r["modelo"] == a.adult and bool(r["texto"]) and not r["erro"] and r["compactou"]
        cen.append(r)

        # 12. o principal não mudou e a configuração persiste em outro processo
        after = json.dumps(settings.load()["models"], sort_keys=True)
        cen.append({"cenario": "principal_intacto", "ok": before == after})
        code = ("import os,sys; os.environ['LUMEN_DATA']=sys.argv[1]; sys.path.insert(0, sys.argv[2]);"
                "from pathlib import Path; from lumen import llm; from lumen.study import db, settings;"
                "llm.OLLAMA=sys.argv[4]; db.HOME=Path(sys.argv[3]); import json; s=settings.load()['adult'];"
                "print(json.dumps({'enabled':s['enabled'],'mode':s['mode'],'model':s['model'],'efetivo':settings.adult_model(settings.load())}))")
        outp = subprocess.run([sys.executable, "-I", "-c", code, str(TMP / "data"), str(ROOT), str(TMP / "study"), a.host],
                              capture_output=True, text=True, timeout=60)
        persisted = json.loads(outp.stdout.strip().splitlines()[-1]) if outp.stdout.strip() else {"erro": outp.stderr[-300:]}
        cen.append({"cenario": "persistencia", "lido": persisted, "ok": persisted.get("enabled") is True and persisted.get("model") == a.adult})
        print("[persistencia]", persisted)

        # latência do roteamento: tempo até a decisão, por origem
        lat = {}
        for c in cen:
            d = c.get("decidido_s")
            if d is not None:
                lat[c["cenario"]] = d
        results["decidido_s"] = lat
    finally:
        for p in reversed(patches):
            p.stop()
        db.close()
        index.stop()
    (OUT / f"{a.tag}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    ok = sum(bool(c.get("ok")) for c in results["cenarios"])
    print(f"\nRESULTADO: {ok}/{len(results['cenarios'])} cenários aprovados -> {OUT / (a.tag + '.json')}")
    for c in results["cenarios"]:
        if not c.get("ok"):
            print("  FALHOU:", c["cenario"], {k: v for k, v in c.items() if k in ("modelo", "perfil", "erro", "chars", "etapas")})
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
