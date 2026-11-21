"""Seus dados no Lúmen: o que está guardado, onde, quem recebeu, exportar e apagar por categoria.

Política de exclusão (mostrada na tela):
- apagar no Lúmen nunca apaga nada no Notion nem no Obsidian (originais); "Documentos indexados" remove só a cópia
  local do texto, o índice de palavras e os vetores;
- apagar memórias remove também o índice de busca e os vetores delas; apagar conversas remove mensagens e o índice;
- o banco usa secure_delete e, depois de cada limpeza, o WAL é truncado: o conteúdo apagado não fica legível no disco;
- os backups da Proteção do cérebro não incluem estes dados (eles copiam o cofre e o Notion, não DATA/study);
- as chaves de provedores ficam no Gerenciador de Credenciais do Windows e só saem quando você as remove."""
import json

from . import activity, chats, db, index, learn, mastery, memory, settings

CATEGORIES = {
    "evaluation": ("Avaliações de respostas", "SELECT COUNT(*) FROM messages WHERE feedback != 0 OR correction != ''",
                   "Marcações de boas ou ruins e correções: conjunto local para comparar modelos e prompts. Não altera os pesos da IA."),
    "skills": ("Suas skills", "SELECT 0", "Instruções que você criou no Lúmen. Skills do cofre e do sistema são preservadas."),
    "memories": ("Memórias", "SELECT COUNT(*) FROM memories", "Memórias salvas e sugeridas, com índice e vetores."),
    "conversations": ("Conversas", "SELECT COUNT(*) FROM conversations", "Conversas, mensagens, anexos, imagens geradas e PDFs."),
    "projects": ("Projetos", "SELECT COUNT(*) FROM projects", "Projetos e as memórias de cada projeto."),
    "index": ("Documentos indexados", "SELECT COUNT(*) FROM documents",
              "Cópia local do texto, índice de palavras, embeddings e cópias das imagens das notas. Os originais no Notion e no Obsidian ficam intactos."),
    "saved": ("Itens salvos", "SELECT COUNT(*) FROM items", "Flashcards, questionários, planos, mapas, práticas, entregas e seus anexos."),
    "mastery": ("O que o Lúmen sabe que você domina", "SELECT COUNT(*) FROM mastery",
                "Acertos e erros por assunto, incluindo práticas. Ajusta o nível das explicações; o modelo de IA não muda."),
    "cache": ("Cache da internet e da voz", "SELECT COUNT(*) FROM web_cache",
              "Páginas públicas lidas recentemente e as frases faladas guardadas pela voz (para tocar de novo na hora)."),
    "activity": ("Histórico de atividades", "SELECT COUNT(*) FROM activity", "O que foi lido, buscado e gravado (sem conteúdo), incluindo trocas manuais que ajustam o Automático. Apagar zera esse ajuste."),
    "pending": ("Gravações pendentes", "SELECT COUNT(*) FROM pending_actions", "Prévias de notas e páginas aguardando ou já decididas."),
}


def inventory():
    from . import registry
    cats = [{"key": k, "label": v[0], "count": db.value(v[1]), "description": v[2]} for k, v in CATEGORIES.items()]
    next(c for c in cats if c["key"] == "skills")["count"] = len(registry._skills("usuario"))
    files = [{"path": str(p), "bytes": p.stat().st_size} for p in db.files()]
    sf = db.HOME / "settings.json"
    if sf.exists():
        files.append({"path": str(sf), "bytes": sf.stat().st_size})
    if db.MEDIA.is_dir():  # anexos e imagens das notas (no D:)
        files.append({"path": str(db.MEDIA), "bytes": sum(p.stat().st_size for p in db.MEDIA.rglob("*") if p.is_file())})
    return {"categories": cats, "files": files, "folder": str(db.HOME),
            "secret": {"where": "Gerenciador de Credenciais do Windows", "name": "credenciais de IA",
                       "present": any(settings.api_key(p) for p in settings.KEY_ACCOUNTS)},
            "providers": activity.providers_used(),
            "temporary": len(chats.TEMP), "mastery": mastery.listing()[:200]}


def export():
    """Tudo o que o usuário criou (sem segredos e sem o índice, que é refeito a partir das fontes)."""
    from . import evaluation, registry
    convs = []
    for c in db.rows("SELECT id FROM conversations ORDER BY created"):
        conv = chats.get(c["id"])
        convs.append(conv)
    return {"format": "lumen-study-export-1", "exported": db.now(),
            "settings": {k: v for k, v in settings.load().items()},
            "projects": chats.projects(include_archived=True), "conversations": convs, "memories": memory.export(),
            "items": [learn.item(r["id"]) for r in learn.items()],
            "flashcards": db.rows("SELECT * FROM flashcards"), "mastery": mastery.listing(), "activity": activity.recent(5000),
            "evaluation": evaluation.export(), "skills": [registry.skill(x["id"], editing=True) for x in registry._skills("usuario")]}


def delete(category):
    if category == "evaluation":
        with db.tx() as c:
            n = c.execute("UPDATE messages SET feedback = 0, correction = '' WHERE feedback != 0 OR correction != ''").rowcount
        db.checkpoint()
    elif category == "skills":
        from . import registry
        own = registry._skills("usuario")
        with settings.LOCK:
            for skill in own:
                (db.HOME / "skills" / skill["dir"] / "SKILL.md").unlink()
            s = settings.load()
            s["catalog"]["disabled"] = [x for x in s["catalog"]["disabled"] if not x.startswith("usuario:")]
            settings.write(s)
        n = len(own)
    elif category == "memories":
        n = memory.clear()
    elif category == "conversations":
        n = chats.delete_all()
    elif category == "projects":
        n = 0
        for p in chats.projects(include_archived=True):
            chats.delete_project(p["id"])
            n += 1
    elif category == "index":
        from . import images
        n = sum(index.purge(s) for s in ("notion", "obsidian", "files"))
        images.drop()
    elif category in ("saved", "mastery", "cache", "activity", "pending"):
        if category == "saved":
            from . import attachments
            attachments.drop(["item-" + r["id"] for r in db.rows("SELECT id FROM items")])
        table = {"saved": "items", "mastery": "mastery", "cache": "web_cache", "activity": "activity", "pending": "pending_actions"}[category]
        with db.tx() as c:
            n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            c.execute(f"DELETE FROM {table}")
            if category == "saved":
                c.execute("DELETE FROM flashcards")
        db.checkpoint()
        if category == "cache":
            from . import listen
            listen.clear_cache()  # as frases faladas guardadas (D59)
    else:
        from .. import AppError
        raise AppError("Categoria desconhecida.")
    if category != "activity":
        activity.log("apagar-dados", target=CATEGORIES[category][0], result=f"{n} registro(s)", permission="confirmado pelo usuário")
    return n


def delete_all():
    total = {k: delete(k) for k in CATEGORIES}
    db.connect().execute("VACUUM")
    return total


def retention():
    """Retenção configurada: conversas antigas (se houver prazo), atividade e cache vencidos, memórias expiradas."""
    s = settings.load()
    out = {"conversations": chats.prune(s["privacy"]["retention_conversations"]),
           "activity": activity.prune(s["privacy"]["retention_activity"]),
           "memories": len(memory._expire())}
    if s["search"]["cache_days"]:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=s["search"]["cache_days"])).isoformat(timespec="seconds")
        with db.tx() as c:
            out["cache"] = c.execute("DELETE FROM web_cache WHERE fetched < ?", (cutoff,)).rowcount
    return out


def export_json():
    return json.dumps(export(), ensure_ascii=False, indent=1, default=str)
