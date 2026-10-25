"use strict";
// “Minha compreensão” em qualquer janela do Lumen: a principal, a barra lateral e a janela flutuante.
// Um documento só por aula (Notes): o texto vive aqui, é salvo no Lumen (lumen/understanding.py) e espelhado entre as
// janelas abertas (BroadcastChannel, com o servidor como reserva). UnderstandingEditor liga um campo de texto a ele.
// Nada de IA aqui: o editor só guarda o que o estudante escreve.
(() => {
  const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
  const me = Math.random().toString(36).slice(2);  // esta janela
  const channel = "BroadcastChannel" in window ? new BroadcastChannel("lumen-notes") : null;
  const docs = new Map();  // chave da aula → documento
  const backupKey = (k) => "lumen.note." + k;
  const store = {  // localStorage pode faltar (modo privado): nada aqui pode quebrar a escrita
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
    drop(k) { try { localStorage.removeItem(k); } catch {} },
  };

  // A mesma regra do servidor (que é quem decide de verdade); aqui só libera o botão sem esperar a rede.
  const MIN_WORDS = 20, MIN_DISTINCT = 12;
  function problem(text) {
    const words = text.normalize("NFC").match(/\p{L}{2,}/gu) || [];
    if (words.length < MIN_WORDS) {
      const n = MIN_WORDS - words.length;
      return `Escreva mais um pouco: faltam ${n} palavra${n > 1 ? "s" : ""}.`;
    }
    if (new Set(words.map((w) => w.toLowerCase())).size < MIN_DISTINCT) return "Explique com suas palavras: a nota repete quase só as mesmas palavras.";
    if (words.filter((w) => /[aeiouyáéíóúâêôãõàü]/i.test(w)).length < words.length * .8) return "A nota não parece um texto. Escreva com suas palavras o que entendeu.";
    return "";
  }
  const wordCount = (t) => (t.match(/[\p{L}\p{N}]+/gu) || []).length;

  async function call(path, body) {
    const opt = { headers: { "X-Lumen-Token": TOKEN } };
    if (body !== undefined) { opt.method = "POST"; opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
    let r;
    try { r = await fetch(path, opt); } catch {
      throw Object.assign(new Error("O Lumen parou de responder."), { action: "Abra o aplicativo de novo.", offline: true });
    }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(d.error?.message || "Erro"), { action: d.error?.action || "" });
    return d;
  }

  function doc(key) {
    if (!docs.has(key)) docs.set(key, { key, text: "", at: 0, view: null, pending: false, timer: null, listeners: new Set(), status: ["", ""] });
    return docs.get(key);
  }
  const emit = (d, kind, from) => { for (const fn of d.listeners) fn(d, kind, from); };
  function status(d, text, s, title = "") { d.status = [text, s, title]; emit(d, "status"); }
  const post = (m) => channel?.postMessage({ ...m, from: me });

  // Abre a nota no servidor. O texto mais novo vence: o desta janela (ainda salvando), o do Lumen ou a cópia deste PC
  // (o app fechou antes de o Lumen confirmar).
  async function load(key) {
    const d = doc(key), v = await call("/api/understanding?key=" + encodeURIComponent(key));
    d.view = v;
    if (!d.pending && (v.at || 0) >= d.at) { d.text = v.text; d.at = v.at || 0; }
    const b = store.get(backupKey(key));
    let recovered = false;
    if (b && b.at > d.at && b.text !== d.text && v.state !== "processing_with_ai") {
      d.text = b.text; d.at = b.at; save(d, 0); recovered = true;
    } else if (b && b.at <= (v.at || 0)) store.drop(backupKey(key));  // só quando o Lumen já tem esse texto
    emit(d, "load");
    return { doc: d, recovered };
  }

  // Uma tecla em qualquer editor: cópia neste PC na hora, as outras janelas na hora, o Lumen 0,6 s depois.
  function edit(key, text, from) {
    const d = doc(key);
    d.text = text; d.at = Date.now();
    store.set(backupKey(key), { text, at: d.at });
    post({ type: "text", key, text, at: d.at });
    status(d, "Salvando…", "dirty");
    emit(d, "text", from);
    save(d, 600);
  }
  function save(d, ms) { d.pending = true; clearTimeout(d.timer); d.timer = setTimeout(() => flush(d.key), ms); }
  async function flush(key) {
    const d = docs.get(key);
    if (!d?.pending) return;
    clearTimeout(d.timer); d.pending = false;
    const { text, at } = d;
    try {
      const v = await call("/api/understanding/draft", { key, text, at });
      d.view = v;
      if (store.get(backupKey(key))?.at <= Math.max(at, v.at || 0)) store.drop(backupKey(key));
      if (v.stale && !d.pending && (v.at || 0) > at) {  // o servidor tem uma versão mais nova (outra janela): esta a adota
        d.text = v.text; d.at = v.at;
        emit(d, "text", "remote");
      }
      if (!d.pending) { status(d, "Salvo", "saved"); post({ type: "saved", key, at }); }
      emit(d, "view");
    } catch (e) {  // o texto continua neste PC (localStorage) e volta ao abrir a aula
      if (!e.offline) return status(d, "Erro ao salvar", "error", [e.message, e.action].filter(Boolean).join(" "));
      status(d, "Guardado neste PC. O Lumen tenta salvar de novo.", "error");
      if (!d.pending) save(d, 4000);
    }
  }
  // Janela fechando, escondida ou o app saindo: o que falta vai na hora (keepalive sobrevive ao fechamento).
  function flushAll() {
    for (const d of docs.values()) {
      if (!d.pending) continue;
      clearTimeout(d.timer); d.pending = false;
      fetch("/api/understanding/draft?t=" + encodeURIComponent(TOKEN), { method: "POST", keepalive: true,
        body: JSON.stringify({ key: d.key, text: d.text, at: d.at }) }).catch(() => {});
      status(d, "Salvo", "saved");
    }
  }
  window.addEventListener("pagehide", flushAll);
  document.addEventListener("visibilitychange", () => { if (document.hidden) flushAll(); });

  // O que as outras janelas fizeram com as notas que esta tem abertas.
  const panels = new Map();  // chave → aberta numa janela flutuante
  channel?.addEventListener("message", ({ data: m }) => {
    if (m.type === "panel") { m.open ? panels.set(m.key, m.from) : panels.get(m.key) === m.from && panels.delete(m.key); return void hooks.panel?.(m); }
    if (m.type === "ask-panel") return void ownPanel && post({ type: "panel", key: ownPanel, open: true });
    if (m.type === "dock") return void hooks.dock?.(m.key);
    if (m.type === "close") return void hooks.close?.(m.key);
    if (m.type === "active") return void hooks.active?.(m.key);
    const d = docs.get(m.key);
    if (!d) return;
    if (m.type === "text" && m.at >= d.at) {
      // A outra janela tem o texto mais novo e salva em 0,6 s (e avisa “saved”); esta só salva se aquela fechar antes
      // de confirmar (5 s). Um autosave só por edição; o Lumen ordena pelo horário e ignora o atrasado.
      d.text = m.text; d.at = m.at;
      save(d, 5000);
      status(d, "Salvando…", "dirty");
      emit(d, "text", "remote");
    } else if (m.type === "saved" && m.at >= d.at) {
      clearTimeout(d.timer); d.pending = false;
      status(d, "Salvo", "saved");
    }
    else if (m.type === "state") load(m.key).then(() => hooks.state?.(m.key)).catch(() => {});  // enviada para a IA, analisada…
  });
  // Reserva sem BroadcastChannel (ou uma mensagem perdida): ao voltar para a janela e a cada 3 s, confere no Lumen.
  const refresh = () => { for (const d of docs.values()) if (d.listeners.size && !d.pending) load(d.key).catch(() => {}); };
  window.addEventListener("focus", refresh);
  setInterval(() => { if (!document.hidden) refresh(); }, 3000);

  // Estado vindo do servidor sem recarregar a nota (a barra e a flutuante já consultam /api/widget): o que bloqueia
  // “Processar” mudou, ou outra janela gravou um texto mais novo (e o aviso entre janelas se perdeu).
  function merge(key, n) {
    const d = docs.get(key);
    if (!d?.view || !n) return;
    if (JSON.stringify(d.view.ready) !== JSON.stringify(n.ready) || d.view.state !== n.state) {
      d.view = { ...d.view, ready: n.ready, state: n.state };
      emit(d, "view");
    }
    if (!d.pending && (n.at || 0) > d.at) load(key).catch(() => {});
  }

  // A regra única de “posso processar? / o que acontece agora?”: o servidor decide o que bloqueia fora da nota
  // (preparação, gravação, outra tarefa, análise); o texto e o salvamento são conferidos aqui, com o texto de agora.
  const HARD = ["processing", "synced", "preparing", "prep_failed", "recording", "busy"];
  function ready(key) {
    const d = docs.get(key), v = d?.view;
    if (!v) return { can: false, tone: "wait", label: "Carregando…", detail: "", phase: "loading", action: "", save: ["", ""] };
    const r = v.ready || {}, save = d.status || ["", ""];
    const out = (can, tone, label, detail = "", action = "Processar minha compreensão") => ({ can, tone, label, detail, action, phase: r.phase, save });
    if (HARD.includes(r.phase)) return out(false, r.tone, r.label, r.detail);
    const why = problem(d.text), text = d.text.trim();
    if (r.phase === "completed" && (!text || text === (v.analyzed_text || "").trim() || why)) return out(false, "ok", r.label);
    if (why) return out(false, "wait", text ? why : "Escreva sua compreensão para continuar");
    if (d.pending || save[1] === "dirty") return out(false, "busy", "Salvando sua compreensão…");
    if (save[1] === "error") return out(false, "error", save[0] === "Erro ao salvar" ? save[0] : "Não foi possível salvar", save[2] || save[0]);
    if (r.phase === "interrupted") return out(true, "error", r.label, r.detail, "Tentar novamente");
    if (r.phase === "completed") return out(true, "ok", "Sua compreensão mudou desde a análise", "", "Analisar de novo");
    return out(true, "ok", "Pronto para analisar");
  }

  // “Processar minha compreensão”, igual em qualquer janela: grava a versão mais recente, confere de novo, e o
  // servidor processa exatamente essa versão (se outra janela gravou algo mais novo no meio, ele recusa).
  async function process(key) {
    const d = doc(key), block = () => { const r = ready(key); if (!r.can) throw Object.assign(new Error(r.label), { action: r.detail }); };
    block();
    await flush(key);
    block();
    try { await call("/api/understanding/submit", { key, text: d.text, at: d.at }); }
    catch (e) { await load(key).catch(() => {}); throw e; }
    clearTimeout(d.timer); d.pending = false; store.drop(backupKey(key));
    await load(key).catch(() => {});
    post({ type: "state", key });
  }

  // Liga um bloco de status (ponto, texto, detalhe e botão) a uma nota: o mesmo em todas as janelas, só muda o tamanho.
  // compact: texto e botão curtos (barra lateral); short: só o botão curto (janela flutuante, que já mostra o “Salvo”).
  function bindStatus(key, ui) {
    const d = doc(key);
    const paint = () => {
      const r = ready(key), busy = ["processing", "synced"].includes(r.phase) || (r.phase === "completed" && !r.can);
      ui.box.dataset.tone = r.tone;
      ui.text.textContent = ui.compact && r.save[0] && r.phase !== "processing" ? `${r.save[0]} · ${r.label}` : r.label;
      if (ui.detail) ui.detail.textContent = r.detail;
      ui.box.dataset.tip = [r.label, r.detail, r.save[2]].filter(Boolean).join(" · ");
      if (ui.go) { ui.go.hidden = busy || ["preparing", "prep_failed", "recording", "busy"].includes(r.phase); ui.go.disabled = !r.can; ui.go.textContent = ui.compact || ui.short ? (r.action === "Processar minha compreensão" ? "Processar" : r.action) : r.action; }
    };
    d.listeners.add(paint);
    paint();
    return () => d.listeners.delete(paint);
  }

  let ownPanel = null;  // esta página é a janela flutuante desta nota
  const hooks = {};
  const Notes = {
    problem, wordCount, load, edit, flush, flushAll, call, merge, ready, process, bindStatus,
    doc: (key) => doc(key),
    cancel(key) { const d = docs.get(key); if (d) { clearTimeout(d.timer); d.pending = false; store.drop(backupKey(key)); } },
    changed(key) { post({ type: "state", key }); },  // avisa as outras janelas (ex.: nota enviada para a IA)
    floating: (key) => panels.has(key),
    on(name, fn) { hooks[name] = fn; },
    announce(key, open) { ownPanel = open ? key : null; post({ type: "panel", key, open }); },
    dock(key) { post({ type: "dock", key }); },
    requestClose(key) { post({ type: "close", key }); },
    // A aula em foco no Lumen: a janela principal, a barra lateral e a flutuante mostram SEMPRE a mesma nota.
    setActive(key) { store.set("understandingActiveKey", key); post({ type: "active", key }); },
    active: () => store.get("understandingActiveKey"),
    // Preferências da interface da nota (lembradas neste PC): modo e, no navegador comum, posição e tamanho.
    pref: (name) => store.get("understandingPanel" + name),
    setPref: (name, v) => store.set("understandingPanel" + name, v),
  };
  post({ type: "ask-panel" });  // quem já está flutuando avisa esta janela

  // Atalhos do Lumen, num lugar só. Para trocar um: localStorage “<nome>Shortcut” = "Ctrl+Shift+D" (ou outro).
  // understanding: destacar/voltar a nota. capture: pausar/retomar a captura (Ctrl+Alt+P não é usado pelo navegador
  // nem pelo Windows; no teclado ABNT2, AltGr+P não digita nada).
  const SHORTCUTS = { understanding: "Ctrl+Shift+D", capture: "Ctrl+Alt+P" };
  const mods = { ctrl: (e) => e.ctrlKey || e.metaKey, shift: (e) => e.shiftKey, alt: (e) => e.altKey };
  const Shortcuts = {};
  for (const [name, fallback] of Object.entries(SHORTCUTS)) {
    const keys = String(store.get(name + "Shortcut") || fallback).split("+").map((x) => x.trim().toLowerCase());
    Shortcuts[name] = {
      label: keys.map((x) => x.length === 1 ? x.toUpperCase() : x[0].toUpperCase() + x.slice(1)).join("+"),
      // e.code: com Ctrl+Alt (= AltGr) o e.key pode vir trocado pelo layout
      test: (e) => keys.every((k) => mods[k] ? mods[k](e) : String(e.key).toLowerCase() === k || String(e.code).toLowerCase() === "key" + k)
        && Object.keys(mods).filter((k) => !keys.includes(k)).every((k) => !mods[k](e)),
    };
  }
  Notes.shortcutLabel = Shortcuts.understanding.label;
  Notes.isShortcut = Shortcuts.understanding.test;
  window.Shortcuts = Shortcuts;

  // Um campo de texto ligado à nota de uma aula. O mesmo componente nos três modos (normal, lateral, flutuante); o
  // modo só muda o visual. Texto, autosave e sincronização são do documento, nunca do campo.
  class UnderstandingEditor {
    constructor({ text, save, count, mode = "normal", grow = false, onChange }) {
      Object.assign(this, { text, saveBox: save, countBox: count, mode, autoGrow: grow, onChange, key: null, locked: false });
      text.dataset.mode = mode;
      this.listener = (d, kind, from) => this.update(d, kind, from);
      text.addEventListener("input", () => { if (this.key) { Notes.edit(this.key, text.value, this); this.grow(); this.counts(); } });
    }
    bind(key) {
      if (this.key === key) return this.update(doc(key), "load");
      if (this.key) docs.get(this.key)?.listeners.delete(this.listener);
      this.key = key;
      const d = doc(key);
      d.listeners.add(this.listener);
      this.update(d, "load");
    }
    unbind() { if (this.key) docs.get(this.key)?.listeners.delete(this.listener); this.key = null; }
    get value() { return this.text.value; }
    lock(on) { this.locked = on; this.applyLock(); }
    applyLock() {
      const st = this.key && docs.get(this.key)?.view?.state;
      this.text.readOnly = this.locked || st === "processing_with_ai" || st === "synced_to_notion";
    }
    update(d, kind, from) {
      if ((kind === "text" || kind === "load") && from !== this && this.text.value !== d.text) {
        const t = this.text, focused = document.activeElement === t, [a, b] = [t.selectionStart, t.selectionEnd];
        t.value = d.text;
        if (focused) t.setSelectionRange(Math.min(a, t.value.length), Math.min(b, t.value.length));  // sem pular o cursor
        this.grow();
      }
      if (this.saveBox) { this.saveBox.textContent = d.status[0]; this.saveBox.dataset.s = d.status[1]; if (d.status[2]) this.saveBox.dataset.tip = d.status[2]; else delete this.saveBox.dataset.tip; }
      this.counts(); this.applyLock();
      this.onChange?.(d, kind);
    }
    counts() {
      if (!this.countBox) return;
      const n = wordCount(this.text.value);
      this.countBox.textContent = n ? `${n} palavra${n === 1 ? "" : "s"}` : "";
    }
    grow() { if (this.autoGrow) { const t = this.text; t.style.height = "auto"; t.style.height = t.scrollHeight + "px"; } }
  }
  window.Notes = Notes;
  window.UnderstandingEditor = UnderstandingEditor;
})();
