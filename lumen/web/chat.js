"use strict";
/* Conversa rápida da barra flutuante (widget.html). Fala com o MESMO cérebro do Cérebro: POST /api/study/turn (NDJSON),
   POST /api/study/cancel e GET /api/study/conversation. Não há servidor, banco nem agente próprios: a conversa mora em
   /api/study/*, e "Abrir no Cérebro" abre o mesmo identificador na janela principal (nada é copiado nem reenviado).

   Regras que este arquivo cumpre:
   - Texto da IA vira elementos (md.js), nunca HTML. Links externos saem pelo Lumen.exe ("window:external:").
   - O texto digitado só some depois que o servidor confirma a pergunta (evento "user"); falha antes disso o mantém.
   - Uma resposta por vez; interromper é uma ação explícita (botão); recolher a barra não cancela nada.
   - Livre/Notas usa as mesmas chaves do Cérebro (lumen.study.skipVault / vaultSources) e vale na resposta seguinte.
   - Rascunho NORMAL em sessionStorage (some com a janela; nunca em config global). Só o identificador da conversa NORMAL fica em
     localStorage, para a conversa anterior continuar disponível.
   - Conversa TEMPORÁRIA: nada dela vai para o armazenamento do navegador (nem mensagens, nem rascunho, nem identificador): só a
     memória desta página e a do servidor. O rascunho temporário e o normal são dois espaços separados; trocar de conversa troca de espaço.
   - Ajustes próprios (modelo, novas conversas): ficam no servidor (settings quick.*, GET/POST /api/study/quick) e o SERVIDOR os aplica a
     cada resposta (surface: "quick"). Mudar um ajuste nunca reenvia, interrompe ou apaga nada; vale da próxima resposta.
   - Nada de polling quando parado: só confere o servidor ao abrir o painel e enquanto espera uma resposta de outra janela. */
(() => {
  const panel = document.querySelector("#chat-panel");
  if (!panel) return;
  const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
  const host = window.chrome?.webview;
  const $ = (s) => panel.querySelector(s);
  const { md } = window.LumenMd;
  const ic = (name, cls) => window.ui.icon(name, cls);

  const thread = $("#chat-thread"), input = $("#chat-input"), form = $("#chat-form"), sendBtn = $("#chat-send"), emptyEl = $("#chat-empty");
  const modeBox = $("#chat-mode"), scopeEl = $("#chat-scope"), moreBtn = $("#chat-more"), live = $("#chat-live");
  const bottomBtn = $("#chat-bottom"), tempChip = $("#chat-temp"), recChip = $("#chat-rec"), railBtn = document.querySelector("#chat-btn");

  const LABEL = { notion: "Notion", obsidian: "Obsidian", files: "Arquivo local", web: "Internet", geral: "Conhecimento geral", anexo: "Anexo", tela: "Tela" };
  const SRC_ICON = { notion: "page", obsidian: "obsidian", files: "file", web: "external", geral: "sparkle", anexo: "file", tela: "screen" };
  const EFFORT = { rapido: "Rápido", equilibrado: "Equilibrado", profundo: "Profundo", maximo: "Máximo" };
  // Etapas reais do servidor (eventos "status"); nada aqui é animado sem trabalho por trás.
  const STAGES = {
    understanding: () => "Entendendo a pergunta…", searching: () => "Buscando no Notion e no Obsidian…", reading: (d) => `Lendo “${d}”…`,
    web: () => "Lendo a internet…", tool: () => "Consultando suas fontes…", writing: () => "Escrevendo a resposta…",
    continuing: () => "Continuando com o que encontrou…", fallback: (d) => `Usando ${d}…`, compacting: () => "Resumindo as mensagens antigas…",
    thinking: () => "Pensando antes de responder…", reviewing: () => "Revisando o rascunho…", screen: () => "Vendo a janela que você usava…",
    visual: () => "Montando o diagrama…", artifact: (d) => d || "Preparando o arquivo…",
  };
  const MAX_SHOWN = 60;       // mensagens desenhadas de uma conversa longa; o resto fica no Cérebro
  const NEAR = 56;            // px do fim: só dentro disto a resposta em escrita "puxa" a rolagem
  const PAINT_MS = 90;        // a resposta em escrita é redesenhada no máximo ~11 vezes por segundo

  // ---------- utilidades ----------
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(e.dataset, v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) e.append(kid instanceof Node ? kid : String(kid));
    return e;
  }
  const mem = {};  // se o armazenamento do navegador faltar (janela privada), o estado vale só nesta página
  const store = {
    get(area, key) { try { return window[area].getItem(key); } catch { return mem[area + key] ?? null; } },
    set(area, key, v) { try { window[area].setItem(key, v); } catch { mem[area + key] = v; } },
    drop(area, key) { try { window[area].removeItem(key); } catch { delete mem[area + key]; } },
  };
  async function api(path, body) {
    const opt = { headers: { "X-Lumen-Token": TOKEN } };
    if (body !== undefined) { opt.method = "POST"; opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
    let r;
    try { r = await fetch(path, opt); } catch { throw new Error("Sem conexão com o Lumen. Tente novamente."); }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error([d.error?.message, d.error?.action].filter(Boolean).join(" ") || "Não foi possível concluir.");
    return d;
  }
  const gone = (msg) => /não encontrada/i.test(msg || "");
  const say = (text) => { live.textContent = ""; setTimeout(() => { live.textContent = text; }, 30); };  // leitor de tela: só o essencial
  const visible = () => document.body.dataset.expanded === "true" && !panel.hidden;

  // ---------- estado ----------
  const K_WIDE = "lumen.quick.wide";  // ampliada: só nesta sessão do Lumen (sessionStorage); o padrão é sempre a janela compacta
  // newTemporary: null = segue o ajuste "Novas conversas"; true/false = a pessoa escolheu no menu (vale só até a conversa existir)
  const Q = { conv: null, messages: [], updated: "", booted: false, stream: null, cancelling: false, elsewhere: false, stick: true, savedTop: 0,
    newTemporary: null, syncing: false, project: "", elsewhereTimer: 0, wide: store.get("sessionStorage", K_WIDE) === "1",
    pref: { model: "", new_chat: "normal" }, quick: null, view: null, draftCtx: "normal", draftTemp: "", saving: Promise.resolve() };
  document.body.dataset.chatSize = Q.wide ? "wide" : "compact";
  // Esta conversa (ou a próxima, se ainda não existe) é temporária? A conversa que existe manda; senão a escolha do menu; senão o ajuste.
  const curTemp = () => (Q.conv ? !!Q.conv.temporary : Q.newTemporary ?? Q.pref.new_chat === "temporary");
  let vault = { free: false, sources: null };

  // ---------- Livre / Notas (o mesmo estado do Cérebro) ----------
  const K_FREE = "lumen.study.skipVault", K_SRC = "lumen.study.vaultSources";
  function readVault() {
    let sources = null;
    try { const raw = JSON.parse(store.get("localStorage", K_SRC) || "null"); if (Array.isArray(raw)) sources = raw.filter((x) => x === "notion" || x === "obsidian"); } catch { /* valor inválido: sem filtro */ }
    vault = { free: store.get("localStorage", K_FREE) === "true", sources: sources?.length ? sources : null };
  }
  function setFree(free) {
    vault.free = free;
    store.set("localStorage", K_FREE, String(free));  // a seleção "só Obsidian/Notion" fica como está (o Cérebro faz o mesmo)
    renderMode();
  }
  function renderMode() {
    for (const b of modeBox.querySelectorAll("[role=radio]")) {
      const on = (b.dataset.mode === "free") === vault.free;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    }
    const only = !vault.free && vault.sources?.length === 1 ? (vault.sources[0] === "obsidian" ? "Só o Obsidian" : "Só o Notion") : "";
    scopeEl.hidden = !only; scopeEl.textContent = only;
    renderHint();
    if (only) scopeEl.dataset.tip = only; else delete scopeEl.dataset.tip;  // dica do Lumen (ui.js), nunca o title nativo
  }
  // Livre/Notas (fontes) e Normal/Temporária (histórico e memória) são coisas diferentes: o texto de apoio diz as duas, sem misturá-las
  function renderHint() {
    const only = !vault.free && vault.sources?.length === 1 ? (vault.sources[0] === "obsidian" ? "Só o Obsidian" : "Só o Notion") : "";
    const base = vault.free ? "Resposta direta, sem consultar suas notas." : only ? `${only} será consultado.` : "Consulto suas notas e mostro as fontes.";
    $("#chat-empty-hint").textContent = curTemp() ? `${base} Temporária: fica fora do histórico e não cria memórias.` : base;
  }
  modeBox.addEventListener("click", (e) => { const b = e.target.closest("[role=radio]"); if (b) setFree(b.dataset.mode === "free"); });
  modeBox.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault(); setFree(!vault.free); modeBox.querySelector("[aria-checked=true]").focus();
  });
  window.addEventListener("storage", (e) => { if (e.key === K_FREE || e.key === K_SRC) { readVault(); renderMode(); } });  // o Cérebro mudou o modo

  // ---------- rascunho e ponteiro da conversa ----------
  const K_DRAFT = "lumen.quick.draft", K_CONV = "lumen.quick.conv";
  // Dois espaços de rascunho, nunca misturados: o NORMAL vai para o sessionStorage; o TEMPORÁRIO existe só na memória desta página.
  let draftTimer = 0;
  const readDraft = (ctx) => (ctx === "temp" ? Q.draftTemp : store.get("sessionStorage", K_DRAFT) || "");
  function writeDraft(ctx, text) {
    if (ctx === "temp") { Q.draftTemp = text; return; }
    if (text) store.set("sessionStorage", K_DRAFT, text); else store.drop("sessionStorage", K_DRAFT);
  }
  const saveDraft = () => { clearTimeout(draftTimer); draftTimer = setTimeout(() => writeDraft(Q.draftCtx, input.value), 250); };
  const clearDraft = () => { clearTimeout(draftTimer); writeDraft(Q.draftCtx, ""); };
  // O campo mostra o rascunho do contexto atual (normal ou temporário): ao trocar de conversa, guarda o que há no espaço de saída e traz o do outro.
  function switchDraft() {
    const want = curTemp() ? "temp" : "normal";
    if (want === Q.draftCtx) return;
    clearTimeout(draftTimer);
    writeDraft(Q.draftCtx, input.value);
    Q.draftCtx = want;
    input.value = readDraft(want);
    autosize(); updateSend();
  }
  // O servidor decidiu o tipo da conversa (ex.: histórico desligado a tornou temporária): o texto digitado passa a pertencer a esse espaço e,
  // se for o temporário, não pode ficar guardado como rascunho normal.
  function adoptDraftContext() {
    const want = curTemp() ? "temp" : "normal";
    if (want === Q.draftCtx) return;
    if (want === "temp") store.drop("sessionStorage", K_DRAFT);
    Q.draftCtx = want;
  }
  // Só a conversa NORMAL tem ponteiro no localStorage. Um ponteiro temporário de uma versão anterior é apagado, não restaurado.
  const pointer = () => {
    try {
      const v = JSON.parse(store.get("localStorage", K_CONV) || "null");
      if (v?.temporary) { store.drop("localStorage", K_CONV); return null; }
      return v && /^[\w-]{1,64}$/.test(v.id) && !v.id.startsWith("tmp-") ? v : null;
    } catch { return null; }
  };
  const setPointer = (c) => { if (c?.id && !c.temporary) store.set("localStorage", K_CONV, JSON.stringify({ id: c.id })); else if (!c) store.drop("localStorage", K_CONV); };
  // O campo começa com uma linha e cresce em linhas inteiras até um terço da altura do painel (no máximo 132 px); depois rola por dentro.
  // Assim ele nunca come a área de leitura, nem na janela compacta nem na ampliada.
  function inputMax() {
    const room = panel.clientHeight, line = parseFloat(getComputedStyle(input).lineHeight) || 20, pad = 12;
    if (!room) return parseFloat(panel.style.getPropertyValue("--chat-input-max")) || 132;
    return Math.round(pad + line * Math.max(2, Math.floor((Math.min(132, room * 0.34) - pad) / line)));
  }
  function autosize() {
    const max = inputMax();
    panel.style.setProperty("--chat-input-max", max + "px");
    input.style.height = "auto";  // vazio: uma linha (a dica do campo, se quebrasse, não pode inflar a altura)
    input.style.height = Math.min(input.value ? input.scrollHeight : input.clientHeight, max) + "px";
  }
  // A dica longa só entra se CABE numa linha no campo (medida com a fonte real do campo): quebrada, ela inflava a altura e mostrava barra de rolagem
  // num campo vazio (visto no WebView2 da barra deitada). Largura do campo, não da tela nem do painel.
  const HINT = "Pergunte ou consulte suas notas…";
  let ruler = null;
  function hintFits() {
    const room = input.clientWidth;
    if (!room) return true;  // painel oculto: reavalia ao abrir
    ruler ||= document.createElement("canvas").getContext("2d");
    const cs = getComputedStyle(input);
    ruler.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    return ruler.measureText(HINT).width + 8 <= room;
  }
  const placeholder = () => (Q.elsewhere ? "Respondendo em outra janela…" : hintFits() ? HINT : "Pergunte…");
  input.value = readDraft("normal");

  // ---------- rolagem ----------
  const nearBottom = () => thread.scrollHeight - thread.scrollTop - thread.clientHeight <= NEAR;
  function scrollEnd() { thread.scrollTop = thread.scrollHeight; Q.stick = true; bottomBtn.hidden = true; }
  thread.addEventListener("scroll", () => {
    Q.stick = nearBottom();
    bottomBtn.hidden = Q.stick || !(Q.stream || thread.scrollHeight > thread.clientHeight * 1.6);
  }, { passive: true });
  bottomBtn.addEventListener("click", () => { scrollEnd(); input.focus(); });

  // ---------- mensagens ----------
  function citeButton(sid, m) {
    const s = (m.sources || []).find((x) => x.sid === sid);
    if (!s || m.live) return h("span", { class: "chat-cite" + (s ? "" : " missing"), "aria-hidden": m.live ? "true" : null, text: sid.slice(1) });
    return h("button", { type: "button", class: "chat-cite", "aria-label": `Fonte ${sid}: ${s.title}`, "data-tip": `${s.title} · ${LABEL[s.source] || s.source}`,
      onclick: (e) => { const art = e.currentTarget.closest(".chat-msg"); openSources(art, true); art.querySelector(`.chat-src[data-sid="${sid}"]`)?.scrollIntoView({ block: "nearest" }); } }, sid.slice(1));
  }
  function decorateCode(root) {
    for (const pre of root.querySelectorAll("pre.st-code")) {
      const code = pre.textContent, lang = pre.dataset.lang || "código";
      const copy = h("button", { type: "button", class: "chat-code-copy", "aria-label": `Copiar ${lang}`, "data-tip": "Copiar o código" }, ic("copy"));
      copy.addEventListener("click", () => copyText(code, copy));
      const wrap = h("div", { class: "chat-code", dataset: { lang } }, copy);
      pre.before(wrap); wrap.prepend(pre);  // (replaceWith falha: o novo elemento conteria o que ele está trocando)
    }
  }
  async function copyText(text, button) {
    let ok = true;
    try { await navigator.clipboard.writeText(text); }
    catch {
      try { const t = h("textarea", { class: "sr", "aria-hidden": "true" }); t.value = text; document.body.append(t); t.select(); ok = document.execCommand("copy"); t.remove(); }
      catch { ok = false; }
    }
    const label = button.querySelector("span"), old = button.dataset.label || label?.textContent;
    if (label) { button.dataset.label = old; label.textContent = ok ? "Copiado" : "Não copiou"; setTimeout(() => { label.textContent = old; }, 1600); }
    else { button.dataset.done = ok ? "ok" : "fail"; setTimeout(() => { delete button.dataset.done; }, 1600); }
    say(ok ? "Copiado." : "Não foi possível copiar.");
  }
  function userView(m, state) {
    return h("div", { class: "chat-msg user", dataset: { id: m.id ?? "", state: state || "" } }, h("div", { class: "chat-bubble", text: m.content }));
  }
  // Só o que a barra não consegue mostrar de verdade (diagrama, checagem, flashcards, arquivo gerado) manda para o Cérebro
  const hasRich = (m) => { const x = m.meta || {}, e = x.explain || {}; return !!(x.item || x.artifact || x.item_card || x.feynman || e.diagram || e.check || e.summary?.length || e.deck); };
  function detailsLine(m) {
    const meta = m.meta || {}, bits = [];
    const q = meta.quick;
    if (meta.model) bits.push(q?.fallback ? `Modelo ${meta.model} (${q.source === "chosen" ? "o escolhido" : "o Rápido"}, ${q.requested}, não estava instalado)` : `Modelo ${meta.model}`);
    if (meta.effort && EFFORT[meta.effort]) bits.push(`Esforço ${EFFORT[meta.effort]}`);
    bits.push(meta.free_mode ? "Livre: sem consultar suas notas" : "Notas");
    if (meta.profile?.used === "adult") bits.push("Perfil adulto");
    return bits.join(" · ");
  }
  function sourceRow(s, m) {
    const status = h("span", { class: "chat-src-status", role: "status", "aria-live": "polite" });
    const canOpen = (s.id && !["anexo", "tela"].includes(s.source) && !String(s.id).startsWith("files:anexo:")) || /^https?:\/\//.test(s.url || "");
    const open = canOpen ? h("button", { type: "button", class: "chat-src-open", "aria-label": `Abrir “${s.title}”`, onclick: () => openSource(s, open, status) }, ic("external"), h("span", { text: "Abrir" })) : null;
    return h("li", { class: "chat-src", dataset: { sid: s.sid, cited: String(!!s.cited) } },
      h("span", { class: "chat-src-ico", "aria-hidden": "true" }, ic(SRC_ICON[s.source] || "page")),
      h("span", { class: "chat-src-main" }, h("span", { class: "chat-src-title", text: s.title || "Sem título" }),
        h("span", { class: "chat-src-meta", text: [s.sid ? s.sid.slice(1) + " ·" : "", LABEL[s.source] || s.source, s.cited ? "citada" : "consultada"].filter(Boolean).join(" ") }), status),
      open);
  }
  async function openSource(s, button, status) {
    status.textContent = "";
    if (!s.id && /^https?:\/\//.test(s.url || "")) { host?.postMessage("window:external:" + s.url); return; }  // pelo Lumen.exe; sem retorno para confirmar
    button.disabled = true;
    try { const r = await api("/api/study/open", { id: s.id }); status.textContent = r.notice || "Aberto."; status.dataset.tone = "ok"; }
    catch (e) { status.textContent = e.message; status.dataset.tone = "error"; }
    finally { button.disabled = false; }
  }
  function openSources(art, open) {
    const box = art.querySelector(".chat-sources"), toggle = art.querySelector(".chat-more");
    if (!box || !toggle) return;
    box.hidden = !open; toggle.setAttribute("aria-expanded", String(open));
    if (open) requestAnimationFrame(() => box.scrollIntoView({ block: "nearest" }));  // a lista abre abaixo da resposta: leva-a à vista
  }
  function actionsView(m) {
    const sources = (m.sources || []).filter((s) => s.title);
    const meta = m.meta || {};
    const copy = h("button", { type: "button", class: "chat-act", "aria-label": "Copiar a resposta" }, ic("copy"), h("span", { text: "Copiar" }));
    copy.addEventListener("click", () => copyText(m.content, copy));
    const toggle = sources.length || meta.model
      ? h("button", { type: "button", class: "chat-act chat-more", "aria-expanded": "false", "aria-label": sources.length ? `Fontes: ${sources.length}` : "Detalhes da resposta" },
        h("span", { text: sources.length ? `Fontes · ${sources.length}` : "Detalhes" }), ic("chevron-down")) : null;
    const box = toggle ? h("div", { class: "chat-sources", hidden: true },
      h("p", { class: "chat-details", text: detailsLine(m) }),
      sources.length ? h("ul", { class: "chat-src-list" }, sources.map((s) => sourceRow(s, m))) : null) : null;
    toggle?.addEventListener("click", () => openSources(toggle.closest(".chat-msg"), box.hidden));
    const rich = hasRich(m) ? h("button", { type: "button", class: "chat-act chat-rich", onclick: () => openBrain() }, ic("external"), h("span", { text: "Resultado completo no Cérebro" })) : null;
    const open = (meta.opened || []).slice(0, 4).map((o) => h("button", { type: "button", class: "chat-act", "aria-label": `Abrir “${o.title}”`,
      onclick: async (e) => {
        const b = e.currentTarget;
        if (o.app) { b.disabled = true; try { const r = await api("/api/study/open-app", { app: o.app }); say(r?.opened ? `${r.title} aberto.` : "Pedido enviado."); } catch (er) { say(er.message); } finally { b.disabled = false; } }
        else if (o.id) { const st = h("span"); await openSource({ id: o.id, title: o.title, source: "obsidian" }, b, st); say(st.textContent); }
      } }, ic("external"), h("span", { text: `Abrir “${o.title}”` })));
    return h("div", { class: "chat-actions" }, copy, toggle, rich, ...open, meta.free_mode ? h("span", { class: "chat-tag", text: "Livre" }) : null, box);
  }
  function botView(m) {
    const answer = h("div", { class: "chat-answer" }, md(m.content, { cite: (sid) => citeButton(sid, m) }));
    decorateCode(answer);
    return h("article", { class: "chat-msg bot", dataset: { id: m.id ?? "" } }, answer, actionsView(m));
  }
  function noticeRow(text, { tone = "info", action } = {}) {
    const row = h("div", { class: "chat-note", dataset: { tone }, role: tone === "error" ? "alert" : "status" }, h("span", { text }));
    if (action) row.append(h("button", { type: "button", class: "chat-note-btn", onclick: action[1] }, action[0]));
    return row;
  }
  const clearNotes = () => { for (const n of thread.querySelectorAll(".chat-note, .chat-partial-tag")) n.remove(); };
  function setEmpty() {
    const none = !Q.messages.length && !Q.stream && !Q.elsewhere && !thread.querySelector(".chat-msg");
    emptyEl.hidden = !none;
  }
  function renderThread() {
    for (const n of [...thread.children]) if (n !== emptyEl) n.remove();
    const msgs = Q.messages, shown = msgs.slice(-MAX_SHOWN);
    if (msgs.length > shown.length) thread.append(noticeRow(`Mostrando as últimas ${shown.length} mensagens.`, { action: ["Ver tudo no Cérebro", () => openBrain()] }));
    for (const m of shown) thread.append(m.role === "user" ? userView(m) : botView(m));
    const last = msgs[msgs.length - 1];
    if (last?.role === "user" && !Q.elsewhere) thread.append(noticeRow("Esta pergunta ficou sem resposta.", { tone: "warn", action: ["Tentar de novo", () => run({ regenerate: true })] }));
    setEmpty(); renderHead(); updateSend();
    scrollEnd();
  }

  // ---------- cabeçalho, envio, estados ----------
  const busy = () => !!(Q.stream || Q.cancelling);
  function renderHead() {
    const temp = curTemp();
    tempChip.hidden = !temp;
    renderHint();
    const projectChip = panel.querySelector(".chat-project");
    if (projectChip) projectChip.remove();
    if (Q.conv?.project_id) {
      const chip = h("span", { class: "chat-chip chat-project", "data-tip": "Esta conversa usa as instruções, as fontes e a memória do projeto", text: Q.project || "Projeto" });
      tempChip.before(chip);
    }
    if (menu) fillMenu();  // o que está bloqueado muda com a resposta (nova conversa só com a conversa livre)
  }
  async function loadProject(id) {
    if (!id) return;
    try { const r = await api("/api/study/projects"); Q.project = (r.projects || []).find((p) => p.id === id)?.name || ""; renderHead(); } catch { /* o nome é só um enfeite */ }
  }
  function updateSend() {
    const st = Q.stream && !Q.stream.stopping;
    const mode = Q.cancelling || Q.stream?.stopping ? "wait" : st ? "stop" : "send";
    sendBtn.dataset.mode = mode;
    sendBtn.type = mode === "stop" ? "button" : "submit";
    const label = mode === "stop" ? "Interromper a resposta" : mode === "wait" ? "Interrompendo…" : "Enviar";
    sendBtn.setAttribute("aria-label", label);
    sendBtn.dataset.tip = mode === "send" ? "Enviar (Enter) · Shift+Enter quebra a linha" : label;
    window.ui.setIcon(sendBtn, mode === "stop" ? "stop" : "arrow-up");
    sendBtn.disabled = mode === "wait" || Q.elsewhere || (mode === "send" && !input.value.trim());
    sendBtn.setAttribute("aria-disabled", String(sendBtn.disabled));
    form.dataset.busy = String(busy() || Q.elsewhere);
    if (Q.elsewhere || input.clientWidth) input.placeholder = placeholder();  // com o campo oculto (ajustes abertos) não dá para medir a dica: fica como estava
    thread.setAttribute("aria-busy", String(!!Q.stream));
  }
  // Ponto discreto no ícone da barra quando a conversa tem novidade e o painel não está à vista (sempre com o texto no aria-label)
  function attention() {
    const state = visible() ? "" : Q.stream ? "busy" : Q.unread ? "done" : "";
    if (state) railBtn.dataset.attn = state; else delete railBtn.dataset.attn;
    railBtn.setAttribute("aria-label", state === "busy" ? "Conversa rápida: respondendo" : state === "done" ? "Conversa rápida: resposta nova" : "Conversa rápida");
    railBtn.dataset.tip = railBtn.getAttribute("aria-label");
  }

  // ---------- envio e streaming ----------
  const newId = () => (crypto.randomUUID?.() || String(Date.now()) + Math.random()).replace(/[^\w]/g, "").slice(0, 40).padEnd(8, "0");
  async function send() {
    if (busy() || Q.elsewhere) return;
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    // Comandos "/" têm confirmações próprias (envio externo, custo) que só existem no Cérebro: aqui não saem como texto.
    if (/^\//.test(text)) { clearNotes(); thread.append(noticeRow("Comandos que começam com / funcionam no Cérebro.", { action: ["Abrir no Cérebro", () => openBrain()] })); scrollEnd(); return; }
    return run({ text });
  }
  async function run({ text = "", regenerate = false }) {
    if (busy()) return;
    clearNotes();
    const turnId = newId(), ctrl = new AbortController();
    const st = Q.stream = { ctrl, turnId, text: "", sources: [], node: null, body: null, stage: null, confirmed: regenerate, optimistic: null, sentText: text, dirty: false, rich: false,
      final: null, failed: null, cancelled: false, stopping: false, regenerate };
    for (const p of thread.querySelectorAll(".chat-msg.bot.partial")) p.remove();  // a parte incompleta de uma tentativa anterior não fica no meio da conversa
    if (!regenerate) { st.optimistic = userView({ content: text }, "sending"); thread.append(st.optimistic); }
    st.stage = h("p", { class: "chat-stage", role: "status" }, h("i", { class: "chat-pulse", "aria-hidden": "true" }), h("span", { text: "Enviando…" }));
    thread.append(st.stage);
    setEmpty(); renderHead(); updateSend(); attention(); scrollEnd();
    // surface "quick": o servidor aplica os ajustes desta conversa (modelo, novas conversas) lidos NESTE envio. `temporary` só vai quando a pessoa
    // escolheu no menu; sem ele, o servidor segue o ajuste "Novas conversas". Conversa que já existe nunca muda de tipo.
    const body = { text: regenerate ? "" : text, regenerate, conversation_id: Q.conv?.id || null, surface: "quick",
      ...(Q.conv?.id || Q.newTemporary === null ? {} : { temporary: Q.newTemporary }),
      skip_vault: vault.free, ...(vault.sources ? { vault_sources: vault.sources } : {}), turn_id: turnId };
    try {
      const r = await fetch("/api/study/turn", { method: "POST", signal: ctrl.signal, headers: { "Content-Type": "application/json", "X-Lumen-Token": TOKEN }, body: JSON.stringify(body) });
      if (!r.ok) { const v = await r.json().catch(() => ({})); throw new Error(v.error?.message || "Não foi possível falar com o Lumen."); }
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let k;
        while ((k = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, k); buf = buf.slice(k + 1); if (line.trim()) handle(JSON.parse(line)); }
      }
      if (!st.final && !st.failed && !st.cancelled) st.failed = { message: "A conexão foi encerrada antes do fim da resposta." };
    } catch (e) {
      if (e.name === "AbortError") st.cancelled = true;
      else st.failed = { message: e instanceof SyntaxError ? "O Lumen enviou uma resposta ilegível. Tente de novo."
        : e instanceof TypeError ? "Sem conexão com o Lumen. Tente novamente." : e.message };
    }
    finish(st);
  }
  function handle(ev) {
    const st = Q.stream;
    if (!st) return;
    switch (ev.type) {
      case "conversation":
        if (!Q.conv?.id) { Q.conv = { id: ev.conversation.id, title: ev.conversation.title, temporary: !!ev.conversation.temporary, project_id: ev.conversation.project_id }; Q.newTemporary = null; adoptDraftContext(); setPointer(Q.conv); renderHead(); }
        break;
      case "user":
        st.confirmed = true;
        st.optimistic?.setAttribute("data-state", "");
        if (st.optimistic) st.optimistic.dataset.id = ev.message.id;
        Q.messages.push({ id: ev.message.id, role: "user", content: ev.message.content ?? st.sentText, meta: ev.message.meta || {} });
        if (!st.regenerate && input.value.trim() === st.sentText) { input.value = ""; autosize(); clearDraft(); updateSend(); }  // o texto só sai depois da confirmação
        break;
      case "status": setStage(ev); break;
      case "sources": st.sources = ev.items || []; break;
      case "delta": st.text += ev.text; schedulePaint(); break;
      case "replace": st.text = ev.text; schedulePaint(); break;
      case "pending": case "created": case "item": st.rich = true; break;
      case "done": st.final = { role: "assistant", ...ev.message }; break;
      case "error": st.failed = { message: [ev.message, ev.action].filter(Boolean).join(" "), code: ev.code }; break;
      case "cancelled": st.cancelled = true; break;
      default: break;  // usage, memories, understanding, profile, compacted: não têm lugar nesta tela
    }
  }
  function setStage(ev) {
    const st = Q.stream;
    if (!st?.stage) return;
    st.stage.querySelector("span").textContent = (STAGES[ev.stage] || (() => "Trabalhando…"))(ev.detail || "");
  }
  let paintTimer = 0, lastPaint = 0;
  function schedulePaint() {
    if (paintTimer) return;
    paintTimer = setTimeout(() => { paintTimer = 0; paint(); }, Math.max(0, PAINT_MS - (performance.now() - lastPaint)));
  }
  function paint() {
    const st = Q.stream;
    if (!st) return;
    if (!visible()) { st.dirty = true; return; }  // recolhida: nada é desenhado; quando a barra voltar, desenha uma vez
    st.dirty = false; lastPaint = performance.now();
    if (!st.node) {
      st.body = h("div", { class: "chat-answer streaming" });
      st.node = h("article", { class: "chat-msg bot live" }, st.body);
      st.stage.before(st.node);
      setEmpty();
    }
    const m = { sources: st.sources, live: true };
    st.body.replaceChildren(md(st.text, { cite: (sid) => citeButton(sid, m) }));
    if (Q.stick) thread.scrollTop = thread.scrollHeight;
  }
  function finish(st) {
    clearTimeout(paintTimer); paintTimer = 0;
    st.stage?.remove();
    const done = st.final;
    if (done) {
      const msg = { ...done, sources: done.sources || [], meta: done.meta || {} };
      Q.messages.push(msg);
      const view = botView(msg);
      if (st.node) st.node.replaceWith(view); else thread.append(view);
      if (!visible()) Q.unread = true;
      say("Resposta pronta.");
      if (Q.stick) scrollEnd();
    } else if (st.failed || st.cancelled) {
      // Mensagem parcial NUNCA vira resposta concluída: fica marcada, fora do histórico, com a saída para tentar de novo.
      if (st.text) {
        const partial = h("article", { class: "chat-msg bot partial" }, h("div", { class: "chat-answer" }, md(st.text, { cite: (sid) => citeButton(sid, { sources: [], live: true }) })),
          h("p", { class: "chat-partial-tag", text: st.cancelled ? "Resposta interrompida. Esta parte não foi concluída." : "Resposta incompleta. Esta parte não foi concluída." }));
        decorateCode(partial);
        if (st.node) st.node.replaceWith(partial); else thread.append(partial);
      } else st.node?.remove();
      if (st.failed && gone(st.failed.message)) onGone(st);
      else if (st.failed) {
        if (!st.confirmed) st.optimistic?.remove();  // não saiu: o texto continua no campo
        thread.append(noticeRow(st.failed.message + (st.confirmed ? "" : " Seu texto continua no campo."), { tone: "error", action: st.confirmed ? ["Tentar de novo", () => run({ regenerate: true })] : null }));
        say("Não foi possível concluir a resposta.");
      } else {
        if (!st.confirmed) st.optimistic?.remove();
        else thread.append(noticeRow("Você interrompeu a resposta.", { action: ["Tentar de novo", () => run({ regenerate: true })] }));
        say("Resposta interrompida.");
      }
    }
    Q.stream = null;
    if (st.cancelled && Q.conv?.id) settle();           // espera o servidor liberar a conversa antes de aceitar outra pergunta
    else { Q.cancelling = false; if (Q.conv?.id && st.final) stamp(); }
    renderHead(); setEmpty(); updateSend(); attention();
    if (Q.stick) scrollEnd();
  }
  function onGone(st) {
    if (!st.confirmed) st.optimistic?.remove();
    const text = st.sentText;
    resetGone();
    if (text && !input.value.trim()) { input.value = text; autosize(); }
    thread.append(noticeRow("Esta conversa foi apagada em outra janela. Seu texto continua no campo: envie para começar uma nova.", { tone: "warn" }));
    updateSend();
  }
  function stop() {
    const st = Q.stream;
    if (!st || st.stopping) return;
    st.stopping = true; Q.cancelling = true; updateSend();
    st.ctrl.abort();
    api("/api/study/cancel", { turn_id: st.turnId }).catch(() => {});
  }
  // Depois de interromper, o servidor ainda fecha a resposta: espera ele liberar a conversa antes de aceitar outra pergunta.
  async function settle() {
    Q.cancelling = true; updateSend();
    for (let i = 0; i < 30; i++) {
      try { const b = await api("/api/study/conversation?brief=1&id=" + encodeURIComponent(Q.conv.id)); Q.updated = b.updated; if (!b.generating) break; }
      catch { break; }
      await new Promise((r) => setTimeout(r, 300));
    }
    Q.cancelling = false; renderHead(); updateSend();
  }
  async function stamp() { try { const b = await api("/api/study/conversation?brief=1&id=" + encodeURIComponent(Q.conv.id)); Q.updated = b.updated; } catch { /* a próxima abertura relê */ } }

  // ---------- conversa: abrir, trocar, sincronizar ----------
  // Começa do zero na barra. temporary: null segue o ajuste; true/false é a escolha do menu. keepPointer: entrar numa conversa TEMPORÁRIA não
  // esquece a conversa normal anterior (ela continua no histórico e é a que a barra reabre depois de um reinício).
  // A conversa sumiu (apagada em outra janela ou temporária que expirou): recomeça no MESMO tipo, para o texto devolvido ao campo não trocar de espaço
  function resetGone() { const temp = !!Q.conv?.temporary; reset({ temporary: temp || null, keepPointer: temp }); }
  function reset({ temporary = null, keepPointer = false } = {}) {
    Q.conv = null; Q.messages = []; Q.updated = ""; Q.elsewhere = false; Q.project = ""; Q.newTemporary = temporary;
    clearTimeout(Q.elsewhereTimer);
    if (!keepPointer) setPointer(null);
    switchDraft();  // o campo traz o rascunho do tipo de conversa que começa (o outro fica guardado, separado)
    renderThread();
  }
  async function loadConversation(id) {
    const conv = await api("/api/study/conversation?id=" + encodeURIComponent(id));
    Q.conv = { id: conv.id, title: conv.title, temporary: !!conv.temporary, project_id: conv.project_id };
    Q.messages = (conv.messages || []).map((m) => ({ id: m.id, role: m.role, content: m.content, sources: m.sources || [], meta: m.meta || {} }));
    Q.updated = conv.updated; Q.newTemporary = null;
    setPointer(Q.conv);  // (a temporária não tem ponteiro: ver setPointer)
    switchDraft();
    Q.elsewhere = !!conv.generating && !Q.stream;
    renderThread();
    if (conv.pending?.length) thread.append(noticeRow(`${conv.pending.length === 1 ? "Há uma ação" : `Há ${conv.pending.length} ações`} esperando sua confirmação.`, { tone: "warn", action: ["Revisar no Cérebro", () => openBrain()] }));
    if (Q.elsewhere) enterElsewhere();
    loadProject(conv.project_id);
  }
  function enterElsewhere() {
    Q.elsewhere = true;
    if (!thread.querySelector(".chat-stage.elsewhere")) thread.append(h("p", { class: "chat-stage elsewhere", role: "status" }, h("i", { class: "chat-pulse", "aria-hidden": "true" }), h("span", { text: "Respondendo em outra janela…" })));
    setEmpty(); renderHead(); updateSend();
    clearTimeout(Q.elsewhereTimer);
    const tick = async () => {
      if (!Q.elsewhere || !Q.conv?.id) return;
      if (!visible()) { Q.elsewhereTimer = setTimeout(tick, 3000); return; }  // recolhida: confere devagar
      try {
        const b = await api("/api/study/conversation?brief=1&id=" + encodeURIComponent(Q.conv.id));
        if (!b.generating) { Q.elsewhere = false; await loadConversation(Q.conv.id); if (!visible()) Q.unread = true; attention(); return; }
      } catch (e) { if (gone(e.message)) { resetGone(); return; } }
      Q.elsewhereTimer = setTimeout(tick, 1500);
    };
    Q.elsewhereTimer = setTimeout(tick, 1200);
  }
  async function sync() {
    if (!Q.conv?.id || busy() || Q.elsewhere || Q.syncing) return;
    Q.syncing = true;
    try {
      const b = await api("/api/study/conversation?brief=1&id=" + encodeURIComponent(Q.conv.id));
      if (b.generating) enterElsewhere();
      else if (b.updated !== Q.updated) await loadConversation(Q.conv.id);
    } catch (e) {
      if (gone(e.message)) { const had = Q.conv; resetGone(); if (had) thread.append(noticeRow("Esta conversa foi apagada em outra janela.", { tone: "warn" })); }
    } finally { Q.syncing = false; }
  }
  async function boot() {
    Q.booted = true;
    const prefs = loadPrefs();  // em paralelo: sem ela, o servidor aplica os ajustes dele (o chip só chega um instante depois)
    const ptr = pointer();
    if (!ptr) { await prefs; return; }
    try { await loadConversation(ptr.id); }
    catch (e) {
      if (gone(e.message)) setPointer(null);
      else { Q.booted = false; thread.append(noticeRow(e.message, { tone: "error" })); }  // servidor fora do ar: tenta de novo na próxima abertura
    }
    await prefs;
  }
  // Entrar ou sair do modo temporário SEMPRE cria uma conversa nova: a atual (normal ou temporária) fica como está; nada vira privado ou público depois.
  function newConversation(temporary) {
    if (busy()) return;
    reset({ temporary: !!temporary, keepPointer: !!temporary });
    thread.querySelector(".chat-note")?.remove();
    input.focus();
    say(temporary ? "Nova conversa temporária." : "Nova conversa normal.");
  }
  function openBrain() { host?.postMessage(Q.conv?.id ? "chat:open:" + Q.conv.id : "chat:open"); }

  // ---------- menu "mais opções" ----------
  // Nova conversa, temporária, continuar no Cérebro e o tamanho (compacta ou ampliada) ficam aqui, fora da primeira linha: poucos controles à vista.
  let menu = null;
  function closeMenu(focus) {
    if (!menu) return false;
    menu.remove(); menu = null; moreBtn.setAttribute("aria-expanded", "false");
    if (focus) moreBtn.focus();
    return true;
  }
  // Compacta ou ampliada: a única configuração de tamanho (o menu e "Ajustes desta conversa" chamam esta). Só desta sessão do Lumen.
  function setWide(wide) {
    if (Q.wide === wide) return;
    Q.wide = wide;
    store.set("sessionStorage", K_WIDE, Q.wide ? "1" : "0");
    document.body.dataset.chatSize = Q.wide ? "wide" : "compact";
    document.dispatchEvent(new CustomEvent("quickchat:size"));  // widget.js pede o tamanho ao Lumen.exe; o painel só acompanha a janela
    say(Q.wide ? "Conversa ampliada." : "Conversa compacta.");
    if (Q.view === "settings") renderSettings();
  }
  const toggleWide = () => setWide(!Q.wide);
  function menuItems() {
    const locked = busy() || Q.elsewhere, wait = "Espere a resposta terminar ou interrompa", temp = curTemp();
    return [
      // Na conversa temporária, a saída é "Nova conversa normal": cria outra conversa e deixa a temporária como está
      { id: "chat-menu-new", label: Q.conv?.temporary || temp ? "Nova conversa normal" : "Nova conversa",
        hint: locked ? wait : Q.conv?.temporary ? "A temporária continua no Cérebro até o Lumen fechar" : "A atual continua no histórico", off: locked, run: () => newConversation(false) },
      { id: "chat-menu-temp", label: "Nova conversa temporária", hint: locked ? wait : "Não entra no histórico nem cria memórias", off: locked, run: () => newConversation(true) },
      "-",
      { id: "chat-brain", label: "Continuar no Cérebro", hint: Q.conv?.id ? "Abre esta mesma conversa, sem reenviar nada" : "Abre o Cérebro", run: openBrain },
      { id: "chat-size", label: Q.wide ? "Reduzir a conversa" : "Ampliar a conversa", hint: Q.wide ? "Volta ao tamanho compacto da barra" : "Mais espaço para ler (360 × 540)", run: toggleWide },
      { id: "chat-menu-settings", label: "Ajustes desta conversa", hint: "Modelo, novas conversas e tamanho", run: openSettings },
    ];
  }
  function fillMenu() {
    const had = menu.contains(document.activeElement) ? document.activeElement.id : "";
    menu.replaceChildren(...menuItems().map((it) => it === "-" ? h("hr", { "aria-hidden": "true" })
      : h("button", { type: "button", role: "menuitem", id: it.id, disabled: it.off || null, "aria-label": `${it.label}. ${it.hint}`, onclick: () => { closeMenu(true); it.run(); } },
        h("span", { text: it.label }), h("small", { text: it.hint }))));
    if (had) menu.querySelector("#" + had)?.focus();
  }
  function openMenu() {
    if (closeMenu()) return;
    menu = h("div", { class: "chat-menu", role: "menu", "aria-label": "Mais opções da conversa" });
    panel.append(menu);
    fillMenu();
    moreBtn.setAttribute("aria-expanded", "true");
    (menu.querySelector("button:not(:disabled)") || menu.querySelector("button")).focus();
  }
  moreBtn.addEventListener("click", openMenu);

  // ---------- ajustes desta conversa (painel interno, no lugar da conversa) ----------
  // Só o que a barra precisa: Modelo, Novas conversas, Tamanho e Restaurar. Tudo vive no servidor (settings quick.*): a tela só mostra e pede.
  // Mudar um ajuste não toca na resposta em andamento, no campo de mensagem nem no Cérebro; vale da PRÓXIMA resposta.
  const setPanel = document.querySelector("#chat-set"), setModel = $("#set-model"), setNew = $("#set-new"), setSize = $("#set-size");
  const setNote = $("#set-model-note"), setStatus = $("#chat-set-status"), setBack = $("#chat-set-back");
  const applyPrefs = (v) => { Q.quick = v; Q.pref = { model: v.settings?.model || "", new_chat: v.settings?.new_chat === "temporary" ? "temporary" : "normal" }; Q.prefError = ""; };
  async function fetchPrefs() {
    try { applyPrefs(await api("/api/study/quick")); }
    catch (e) { Q.prefError = e.message || "erro"; }  // sem leitura agora: o servidor segue aplicando os ajustes dele a cada resposta
  }
  // Leituras e gravações dos ajustes entram na MESMA fila: uma leitura começada antes de uma gravação não pode terminar depois dela e devolver o valor velho à tela
  const queue = (fn) => { const run = Q.saving.then(fn); Q.saving = run.catch(() => {}); return run; };
  async function loadPrefs() {
    await queue(fetchPrefs);
    if (!Q.conv && Q.newTemporary === null) { switchDraft(); renderHead(); }  // sem conversa e sem escolha no menu: o chip segue o ajuste
    if (Q.view === "settings") renderSettings();
  }
  function savePrefs(body, okText) {
    return queue(async () => {
      try {
        applyPrefs(await api("/api/study/quick", body));
        if (!Q.conv && Q.newTemporary === null) { switchDraft(); renderHead(); }
        setStatusLine(okText + (Q.stream || Q.elsewhere ? " A resposta em andamento continua como está; o ajuste vale na próxima." : " Vale a partir da próxima resposta."), "ok");
      } catch (e) {
        await fetchPrefs();  // a tela volta ao que o servidor realmente guardou
        setStatusLine(e.message, "error");
      }
      renderSettings();
    });
  }
  function setStatusLine(text, tone) { setStatus.textContent = text; setStatus.dataset.tone = tone || ""; }
  function radioRow(value, title, sub, checked, tag) {
    return h("button", { type: "button", role: "radio", class: "chat-opt", "aria-checked": String(checked), tabindex: checked ? "0" : "-1", dataset: { value } },
      h("span", { class: "chat-opt-main" }, h("span", { class: "chat-opt-title", text: title }), tag ? h("span", { class: "chat-opt-tag", text: tag }) : null),
      sub ? h("small", { text: sub }) : null);
  }
  // Só refaz a lista de modelos quando o CONTEÚDO mudou (modelo instalado ou removido, nome resolvido); senão só move a seleção. Assim reler os
  // ajustes ao abrir não pisca nem tira o foco de quem já está navegando pela lista.
  let modelSig = "";
  function renderSettings() {
    const v = Q.quick, chosen = Q.pref.model, choices = v?.choices || [], fast = v?.fast || "";
    const had = setPanel.contains(document.activeElement) ? document.activeElement.dataset.value : null;
    const LOAD_ERR = "Não consegui ler os ajustes agora. Se continuar, reabra o Lumen: ele pode estar numa versão anterior.";
    if (!v && Q.prefError) setStatusLine(LOAD_ERR, "error");
    else if (v && setStatus.textContent === LOAD_ERR) setStatusLine("", "");  // a leitura voltou: o aviso de falha não fica na tela
    const sig = JSON.stringify([fast, v ? 1 : Q.prefError ? 2 : 0, choices, chosen && !choices.includes(chosen) ? [chosen, v?.running] : null]);
    if (sig !== modelSig) {
      modelSig = sig;
      const rows = [radioRow("", "Rápido do Lumen", fast || (v ? "" : Q.prefError ? "" : "Lendo…"), !chosen, "padrão")];
      for (const n of choices) rows.push(radioRow(n, n, "", chosen === n));
      if (chosen && !choices.includes(chosen)) rows.push(radioRow(chosen, chosen, v?.running === false ? "Ollama fora do ar" : "não instalado", true));
      setModel.replaceChildren(...rows);
    }
    for (const b of setModel.querySelectorAll("[role=radio]")) { const on = b.dataset.value === chosen; b.setAttribute("aria-checked", String(on)); b.tabIndex = on ? 0 : -1; }
    const r = v?.resolved;
    setNote.textContent = !r ? "" : r.unavailable ? `Nenhum modelo local disponível para “${r.requested}”.`
      : r.fallback ? `Respondo com ${r.model}: “${r.requested}” não está instalado.` : `Responde com ${r.model}.`;
    for (const b of setNew.querySelectorAll("[role=radio]")) { const on = b.dataset.value === Q.pref.new_chat; b.setAttribute("aria-checked", String(on)); b.tabIndex = on ? 0 : -1; }
    for (const b of setSize.querySelectorAll("[role=radio]")) { const on = (b.dataset.value === "wide") === Q.wide; b.setAttribute("aria-checked", String(on)); b.tabIndex = on ? 0 : -1; }
    if (had != null) setPanel.querySelector(`[data-value="${CSS.escape(had)}"]`)?.focus();
  }
  function openSettings() {
    if (Q.view === "settings") return;
    closeMenu();
    Q.savedTop = thread.scrollTop;
    Q.view = "settings"; panel.dataset.view = "settings"; setPanel.hidden = false;
    setStatusLine("", "");
    renderSettings();
    loadPrefs();  // o que está salvo e o que está instalado agora
    setBack.focus();
  }
  function closeSettings(focus) {
    if (Q.view !== "settings") return false;
    Q.view = null; delete panel.dataset.view; setPanel.hidden = true;
    if (focus) moreBtn.focus();
    renderHead(); input.placeholder = placeholder(); autosize();  // o campo voltou a existir: a dica é medida agora
    requestAnimationFrame(() => { if (Q.stick) scrollEnd(); else thread.scrollTop = Q.savedTop; });
    return true;
  }
  setBack.addEventListener("click", () => closeSettings(true));
  function arrowsInGroup(box, pick) {  // grupo de rádios: setas movem E escolhem (padrão ARIA), Home/End vão às pontas
    box.addEventListener("keydown", (e) => {
      const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
      if (!keys.includes(e.key)) return;
      const items = [...box.querySelectorAll("[role=radio]")], i = items.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      const to = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (i + (/Right|Down/.test(e.key) ? 1 : items.length - 1)) % items.length;
      items[to].focus(); pick(items[to]);
    });
    box.addEventListener("click", (e) => { const b = e.target.closest("[role=radio]"); if (b) pick(b); });
  }
  arrowsInGroup(setModel, (b) => { if (b.dataset.value !== Q.pref.model) { savePrefs({ model: b.dataset.value }, "Modelo salvo."); } });
  arrowsInGroup(setNew, (b) => { if (b.dataset.value !== Q.pref.new_chat) savePrefs({ new_chat: b.dataset.value }, "Salvo."); });
  arrowsInGroup(setSize, (b) => { setWide(b.dataset.value === "wide"); setStatusLine("", ""); });
  // Restaurar: só os ajustes desta conversa (modelo, novas conversas, tamanho). Conversas, notas, modelos e o resto dos ajustes ficam como estão.
  $("#set-reset").addEventListener("click", async () => {
    await savePrefs({ reset: true }, "Ajustes restaurados.");
    setWide(false);
    if (!setStatus.dataset.tone || setStatus.dataset.tone === "ok") setStatusLine("Ajustes restaurados. Conversas, notas e modelos não mudaram.", "ok");
  });
  panel.addEventListener("keydown", (e) => {
    if (!menu || !menu.contains(document.activeElement)) return;
    const items = [...menu.querySelectorAll("button:not(:disabled)")], i = items.indexOf(document.activeElement);
    if (!items.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus(); }
    else if (e.key === "Home" || e.key === "End") { e.preventDefault(); items[e.key === "Home" ? 0 : items.length - 1].focus(); }
    else if (e.key === "Tab") closeMenu(false);  // sair do menu pelo Tab não deixa um popover órfão aberto
  });
  document.addEventListener("pointerdown", (e) => { if (menu && !menu.contains(e.target) && !moreBtn.contains(e.target)) closeMenu(); });

  // ---------- ligações ----------
  form.addEventListener("submit", (e) => { e.preventDefault(); if (sendBtn.dataset.mode === "send") send(); });
  sendBtn.addEventListener("click", (e) => { if (sendBtn.dataset.mode === "stop") { e.preventDefault(); stop(); } });
  input.addEventListener("input", () => { autosize(); saveDraft(); updateSend(); });
  input.addEventListener("keydown", (e) => {
    // Enter envia; Shift+Enter quebra a linha; o Enter que confirma uma composição (IME) nunca envia
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); if (sendBtn.dataset.mode === "send") send(); }
  });
  $("#chat-collapse").addEventListener("click", () => document.dispatchEvent(new CustomEvent("quickchat:collapse")));
  thread.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a) return;
    e.preventDefault();  // o WebView2 da barra não abre janelas: o link sai pelo Lumen.exe, que só aceita http(s)
    if (/^https?:\/\//i.test(a.href)) host?.postMessage("window:external:" + a.href);
  });

  // ---------- o que a barra (widget.js) usa ----------
  readVault(); renderMode(); renderHead(); updateSend(); autosize();
  // O painel muda de tamanho com a janela (ampliar, reduzir, outra tela): o limite do campo e o texto de apoio acompanham a área real
  if (window.ResizeObserver) new ResizeObserver(() => { if (!panel.hidden) { input.placeholder = placeholder(); autosize(); } }).observe(panel);
  window.QuickChat = {
    setOpen(open) {
      if (!open) { if (Q.view !== "settings") Q.savedTop = thread.scrollTop; closeMenu(); closeSettings(false); attention(); return; }
      Q.unread = false; attention();
      if (!input.disabled) input.focus();
      input.placeholder = placeholder(); autosize();
      if (!Q.booted) boot().then(() => { autosize(); }); else sync();
      if (Q.stream?.dirty) paint();
      requestAnimationFrame(() => { if (Q.stick) scrollEnd(); else thread.scrollTop = Q.savedTop; });
    },
    expanded() { if (Q.stream?.dirty) paint(); attention(); },  // a barra voltou a aparecer
    isOpen: () => !panel.hidden,
    wide: () => Q.wide,
    writing: () => !panel.hidden && document.hasFocus() && document.activeElement === input,
    engaged: () => !panel.hidden && document.hasFocus(),
    busy: () => busy() || Q.elsewhere,
    // Esc: primeiro fecha o menu aberto, depois a tela de ajustes; devolve false quando não havia nada a fechar (aí o Esc recolhe a barra)
    escape() { return closeMenu(true) || closeSettings(true); },
    // A gravação continua ao trocar para a conversa: um indicador discreto no cabeçalho (o relógio muda; o aria-label só quando o estado muda)
    recording(r) {
      const active = !!r?.active && !r.error, paused = active && !!r.paused, text = !active ? "" : paused ? "Pausada" : clock(r.seconds);
      if (recChip.dataset.text === text) return;
      const label = paused ? "Gravação pausada" : "Gravação em andamento";
      recChip.dataset.text = text; recChip.hidden = !text; recChip.dataset.paused = String(paused);
      $("#chat-rec-text").textContent = text;
      if (recChip.getAttribute("aria-label") !== label) { recChip.setAttribute("aria-label", label); recChip.dataset.tip = label; }
    },
    send, stop, newConversation, setWide, openSettings, closeSettings,
    state: () => ({ conv: Q.conv, temporary: curTemp(), pref: { ...Q.pref }, view: Q.view, draftCtx: Q.draftCtx, messages: Q.messages.length, streaming: !!Q.stream, cancelling: Q.cancelling, elsewhere: Q.elsewhere, vault, unread: !!Q.unread }),
  };
  const clock = (s) => { s = Math.floor(s || 0); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].slice(s >= 3600 ? 0 : 1).map((n) => String(n).padStart(2, "0")).join(":"); };
})();
