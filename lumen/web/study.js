"use strict";
/* Lúmen Study AI — a aba Estudos. Tudo vem de /api/study/* e é montado elemento a elemento (nunca innerHTML): texto de
   nota, de página ou da IA vira texto, nunca código. Os estados mostrados (entendendo, buscando, lendo, escrevendo) são
   eventos reais do servidor; nada é animado sem trabalho de verdade por trás. Os módulos study-learn.js (Estudar) e
   study-settings.js (configurações) usam o que este arquivo expõe em window.lumenStudy. */
(() => {
  const root = document.querySelector("[data-study]");
  if (!root) return;
  const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
  const LABEL = { notion: "Notion", obsidian: "Obsidian", files: "Arquivo local", web: "Internet", geral: "Conhecimento geral", anexo: "Anexo", tela: "Tela" };
  const SRC_ICON = { notion: "page", obsidian: "obsidian", files: "file", web: "external", geral: "sparkle", anexo: "file", tela: "screen" };
  const KIND_ICON = { text: "file", pdf: "page", office: "page", image: "image", audio: "music", video: "play" };
  const img = (q, alt = "") => h("img", { src: `/api/study/image?${q}&t=${encodeURIComponent(TOKEN)}`, alt, loading: "lazy", decoding: "async" });
  const AUTHOR = { user: "escrita por você", ai: "gerada por IA", lumen: "gerada pelo Lúmen" };
  const STAGES = {
    understanding: () => "Entendendo a pergunta…", searching: () => "Buscando no Notion e no Obsidian…",
    reading: (d) => `Lendo “${d}”…`, web: () => "Lendo a internet…", tool: () => "Consultando suas fontes…",
    writing: () => "Escrevendo a resposta…", continuing: () => "Continuando com o que encontrou…", fallback: (d) => `Usando ${d}…`,
    compacting: () => "Resumindo as mensagens antigas para caber no contexto…",
    thinking: () => "Pensando antes de responder…", reviewing: () => "Revisando o rascunho…",
    screen: () => "Vendo a janela que você usava antes do Lúmen (nada é guardado)…",
    visual: () => "Montando o diagrama e a checagem…",
    artifact: (d) => d || "Preparando o arquivo…",
  };
  // Função inteligente: o que o Automático decidiu e os níveis de esforço (agent.EFFORT)
  const INTENT_LABEL = { find: "Encontrar", explain: "Explicar", summary: "Resumir", compare: "Comparar", chat: "Conversar",
    flashcards: "Flashcards", quiz: "Questionário", plan: "Plano", map: "Mapa", gaps: "Lacunas", mindmap: "Mapa mental", exercise: "Prática", action: "Plano de ação" };
  // Abaixo de uma explicação: continuar no mesmo assunto, de outro jeito (o "tour narrado" é da fase 6 e o PDF, da 7)
  const EXPLAIN_MORE = [["Mais simples", "Explique de novo, mais simples: sem jargão, com uma analogia do dia a dia."],
    ["Mais fundo", "Aprofunde: o mecanismo em detalhe, a versão precisa e as nuances."],
    ["Outro exemplo", "Dê outro exemplo, diferente dos anteriores, e um contraexemplo."],
    ["De outro jeito", "Explique de outro jeito, com outra analogia e outra ordem."]];
  const EFFORTS = [["", "Automático", "O Lúmen escolhe pelo pedido."], ["rapido", "Rápido", "Menos fontes e no máximo uma busca extra."],
    ["equilibrado", "Equilibrado", "O padrão: até 8 fontes."], ["profundo", "Profundo", "Mais fontes; a IA pensa antes de responder (mais lento)."],
    ["maximo", "Máximo", "O maior modelo e uma revisão do rascunho (o mais lento)."]];
  const EFFORT_LABEL = Object.fromEntries(EFFORTS.map(([id, label]) => [id, label]));
  // Partes do contexto (/context), na ordem em que aparecem; os números vêm do servidor (aproximados, 3 caracteres por token)
  const PARTS = [["system", "Instruções do sistema"], ["memories", "Memórias"], ["summary", "Resumo e mensagens fixadas"],
    ["history", "Histórico da conversa"], ["sources", "Fontes"], ["question", "Pergunta"], ["tools", "Ferramentas"]];
  const SLASH_ICON = { command: "chevron-right", sistema: "sparkle", cofre: "obsidian", usuario: "pen" };
  const ORIGIN = { sistema: "do Lúmen", cofre: "do seu cofre", usuario: "sua" };
  const SUGGESTIONS = [
    ["search", "Encontrar materiais", "find", "Encontre tudo o que tenho sobre "],
    ["sparkle", "Explicar um conceito", "explain", "Explique "],
    ["graph", "Comparar meus estudos", "compare", "Compare o que minhas notas dizem sobre "],
    ["page", "Criar um resumo", "summary", "Faça um resumo do que tenho sobre "],
    ["copy", "Gerar flashcards", "flashcards", "Gere flashcards sobre "],
    ["calendar", "Preparar uma revisão", "quiz", "Prepare um questionário de revisão sobre "],
  ];

  // --- Utilidades -------------------------------------------------------------------------------------------------
  const ic = (name, cls = "") => window.ui.icon(name, cls);
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
  // replaceChildren não achata listas nem ignora null: put() faz as duas coisas
  const put = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
  const btn = (label, onclick, { icon, cls = "btn sm", tip, attrs = {} } = {}) =>
    h("button", { type: "button", class: cls, onclick, "data-tip": tip, "aria-label": tip && !label ? tip : null, ...attrs }, icon ? ic(icon) : null, label ? h("span", { text: label }) : null);
  async function api(path, body, method) {
    const r = await fetch(path, { method: method || (body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-Lumen-Token": TOKEN },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    let v = {};
    try { v = await r.json(); } catch { /* resposta vazia */ }
    if (!r.ok) throw new Error([v.error?.message, v.error?.action].filter(Boolean).join(" ") || "Não foi possível atender o pedido.");
    return v;
  }
  const qs = (o) => "?" + new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== "")).toString();
  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso), now = new Date(), y = new Date(now); y.setDate(now.getDate() - 1);
    const day = d.toDateString() === now.toDateString() ? "hoje" : d.toDateString() === y.toDateString() ? "ontem" : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
    return `${day} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
  }
  const n = (v) => Number(v || 0).toLocaleString("pt-BR");
  const toast = (m, t, ms, action) => window.ui.toast(m, t, ms, action);
  const fold = (v) => String(v).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  // 12345 → "12 mil"; 5449 → "5,4 mil"; janela (down): 32768 → "32 mil", não "33"
  const mil = (v, down) => down ? `${Math.floor(v / 1000)} mil`
    : v >= 1000 ? `${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: v < 10000 ? 1 : 0 })} mil` : String(Math.round(v || 0));
  function download(name, content, type = "text/markdown") {
    const url = URL.createObjectURL(new Blob([content], { type: type + ";charset=utf-8" }));
    const a = h("a", { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  async function guard(fn, okMsg) {
    try { const r = await fn(); if (okMsg) toast(okMsg, "success"); return r; } catch (e) { toast(e.message, "error"); return null; }
  }

  // Diálogo com campos (renomear, confirmar digitando, prévia). Promise com os valores, ou null se cancelado.
  function dialog({ title, message, fields = [], ok = "Confirmar", danger = false, require = "", body = null, wide = false }) {
    return new Promise((resolve) => {
      const inputs = {};
      const form = h("form", { class: "dlg-body st-dlg-body", method: "dialog" });
      if (message) form.append(h("p", { class: "muted", text: message }));
      if (body) form.append(body);
      for (const f of fields) {
        const input = f.type === "textarea" ? h("textarea", { rows: f.rows || 6, placeholder: f.placeholder || "" })
          : f.type === "select" ? h("select", {}, f.options.map(([v, l]) => h("option", { value: v, text: l })))
          : h("input", { type: f.type || "text", placeholder: f.placeholder || "", autocomplete: "off", spellcheck: "false" });
        input.value = f.value ?? "";
        inputs[f.name] = input;
        form.append(h("label", { class: "field" }, f.label, input, f.hint ? h("span", { class: "field-hint", text: f.hint }) : null));
      }
      let typed = null;
      if (require) { typed = h("input", { type: "text", autocomplete: "off", "aria-label": `Digite ${require} para confirmar` }); form.append(h("label", { class: "field" }, `Para confirmar, digite ${require}`, typed)); }
      const yes = h("button", { type: "submit", class: "btn primary" + (danger ? " danger" : ""), text: ok });
      const no = h("button", { type: "button", class: "btn", text: "Cancelar" });
      const dlg = h("dialog", { class: "dlg st-dialog" + (wide ? " wide" : ""), "aria-label": title },
        h("div", { class: "dlg-head" }, h("span", { class: "dlg-icon", dataset: { tone: danger ? "danger" : "" } }, ic(danger ? "alert" : "info")), h("h2", { text: title })),
        form, h("div", { class: "dlg-foot" }, no, yes));
      const finish = (v) => { if (dlg.open) dlg.close(); dlg.remove(); resolve(v); };
      const check = () => { yes.disabled = !!require && typed.value.trim() !== require; };
      typed?.addEventListener("input", check); check();
      no.onclick = () => finish(null);
      dlg.addEventListener("cancel", (e) => { e.preventDefault(); finish(null); });
      form.addEventListener("submit", (e) => { e.preventDefault(); if (yes.disabled) return; const out = {}; for (const [k, i] of Object.entries(inputs)) out[k] = i.value; finish(out); });
      yes.addEventListener("click", (e) => { e.preventDefault(); form.requestSubmit(); });
      document.body.append(dlg); dlg.showModal();
      (Object.values(inputs)[0] || typed || (danger ? no : yes)).focus();
    });
  }

  // Menu de ações (popover simples, fecha com Esc ou clique fora). items: lista [rótulo, ícone, ação, perigo] ou um nó
  // pronto (informações da resposta).
  let openMenu = null;
  function menu(anchor, items) {
    closeMenu();
    const isUnified = items instanceof Node && (items.classList?.contains("unified-panel") || items.querySelector?.(".unified-panel"));
    const m = items instanceof Node ? h("div", { class: isUnified ? "st-menu unified-dialog" : "st-menu st-pop", role: "dialog" }, items)
      : h("div", { class: "st-menu", role: "menu" }, items.filter(Boolean).map(([label, icon, fn, danger]) =>
        h("button", { type: "button", role: "menuitem", class: danger ? "danger" : "", onclick: () => { closeMenu(); fn(); } }, ic(icon), h("span", { text: label }))));
    document.body.append(m);
    const r = anchor.getBoundingClientRect();
    m.style.top = (r.bottom + 4 + m.offsetHeight > innerHeight - 8 ? Math.max(8, r.top - 4 - m.offsetHeight) : r.bottom + 4) + "px";
    const anchorCenter = r.left + r.width / 2;
    m.style.left = isUnified
      ? Math.max(8, Math.min(anchorCenter - m.offsetWidth / 2, innerWidth - m.offsetWidth - 8)) + "px"
      : Math.max(8, Math.min(r.right - m.offsetWidth, innerWidth - m.offsetWidth - 8)) + "px";
    openMenu = m; m.querySelector("button")?.focus();
  }
  function closeMenu() { openMenu?.remove(); openMenu = null; }
  document.addEventListener("pointerdown", (e) => {
    if (openMenu && !openMenu.contains(e.target)) closeMenu();
    if (!statusPop.hidden && !statusPop.parentElement.contains(e.target)) toggleStatus(false);
  });
  // Ctrl+Shift+K compacta a conversa aberta (Ctrl+K, sem Shift, é a paleta do app)
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || !e.shiftKey || e.altKey || e.key.toLowerCase() !== "k") return;
    if (root.closest(".view")?.hidden || S.tab !== "chat" || !settingsHost.hidden || document.querySelector("dialog[open]")) return;
    e.preventDefault();
    compactNow("");
  });
  // Esc fecha o que estiver por cima: menu, estado, painel de fontes e, em janela estreita, o histórico
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || document.querySelector("dialog[open]") || root.closest(".view")?.hidden) return;
    if (openMenu) closeMenu();
    else if (!statusPop.hidden) { toggleStatus(false); statusBtn.focus(); }
    else if (S.aside) showAside(false);
    else if (S.side && narrow.matches) showSide(false);
  });

  // --- Markdown seguro ---------------------------------------------------------------------------------------------
  // O renderizador é compartilhado com a Conversa rápida da barra flutuante (md.js): um só tratamento seguro de texto da IA.
  const { md } = window.LumenMd;

  // --- Estado ---------------------------------------------------------------------------------------------------
  const PROFILE_LABEL = { main: "Principal", adult: "Perfil adulto" };  // antes do primeiro renderChip()
  const S = { state: null, tab: "chat", conv: null, convs: [], projects: [], project: "", archived: false, query: "", from: "", to: "",
    temporary: false, mode: "auto", level: "", stream: null, sources: [], related: [], memories: [], filter: "all", selecting: false,
    selected: new Set(), results: null, sourceFilter: "", side: false, aside: false, ctx: null, menu: null,
    effort: "", decided: null, override: null, profile: "", profileUsed: null };

  // --- Estrutura ------------------------------------------------------------------------------------------------
  // Uma linha só: título, abas discretas e um único indicador de estado. O detalhe da IA, do Notion e do Obsidian fica
  // num painel que só abre quando pedido.
  const pill = (cls) => h("button", { type: "button", class: "st-pill " + cls });
  const pills = { ai: pill("ai"), notion: pill("notion"), obsidian: pill("obsidian") };
  const statusBtn = h("button", { type: "button", class: "st-status-btn", "aria-haspopup": "dialog", "aria-expanded": "false", "aria-controls": "st-status-pop", "aria-label": "Estado da IA e das fontes" }, h("span", { class: "dot" }), h("span", { text: "Estado" }));
  const statusPop = h("div", { class: "st-status-pop", id: "st-status-pop", role: "dialog", "aria-label": "Estado da IA e das fontes", hidden: true },
    h("p", { class: "eyebrow", text: "Conexões" }), pills.ai, pills.notion, pills.obsidian);
  function toggleStatus(open = statusPop.hidden) {
    statusPop.hidden = !open;
    statusBtn.setAttribute("aria-expanded", String(open));
    if (open) pills.ai.focus();
  }
  statusBtn.addEventListener("click", () => toggleStatus());
  const TABS = [["chat", "Conversar"], ["learn", "Estudar"], ["saved", "Salvos"], ["sources", "Fontes"]];
  const tabs = h("div", { class: "st-tabs", role: "tablist", "aria-label": "Áreas do Cérebro" },
    TABS.map(([id, label]) => h("button", { type: "button", role: "tab", id: "st-tab-" + id, "aria-controls": "st-panel-" + id, dataset: { tab: id },
      // clicar de novo na aba já aberta volta ao início dela (as atividades continuam guardadas, com os rascunhos)
      onclick: () => { if (id === "learn" && S.tab === "learn" && !panels.learn.hidden) window.lumenStudy.learnHome?.(); else setTab(id); } }, label, id === "learn" ? h("span", { class: "st-due" }) : null)));
  const head = h("header", { class: "st-head" },
    h("div", { class: "st-title" }, h("h1", { id: "study-h", text: "Cérebro" }), h("p", { class: "st-sub", text: "Central de inteligência e base de conhecimento." })),
    tabs,
    h("div", { class: "st-head-tools" }, h("div", { class: "st-status" }, statusBtn, statusPop),
      btn("", () => openSettings(), { icon: "gear", cls: "icon-btn sm", tip: "Configurações da IA" })));
  const panels = Object.fromEntries(TABS.map(([id]) => [id, h("section", { class: "st-panel", id: "st-panel-" + id, role: "tabpanel", "aria-labelledby": "st-tab-" + id, hidden: true })]));
  const settingsHost = h("section", { class: "st-settings", hidden: true, "aria-label": "Configurações da IA" });
  root.append(head, ...Object.values(panels), settingsHost);

  function setTab(id) {
    S.tab = id;
    toggleStatus(false);
    for (const b of tabs.children) b.setAttribute("aria-selected", String(b.dataset.tab === id));
    for (const [k, p] of Object.entries(panels)) p.hidden = k !== id || !settingsHost.hidden;
    if (id === "learn") window.lumenStudy.renderLearn?.(panels.learn);
    if (id === "saved") renderSaved();
    if (id === "sources") renderSourcesTab();
  }
  function openSettings(section) {
    settingsHost.hidden = false;
    for (const p of Object.values(panels)) p.hidden = true;
    tabs.hidden = true;
    window.lumenStudy.renderSettings?.(settingsHost, section, () => { settingsHost.hidden = true; tabs.hidden = false; setTab(S.tab); refreshState(); });
  }

  // --- Aba conversar: histórico (recolhível) · conversa · fontes (só quando pedidas) ----------------------------------
  // Nada ocupa espaço sem uso: o histórico abre e fecha pela barra da conversa (em janela estreita, por cima), e o painel
  // de fontes só existe quando há fontes e o estudante pede (citação, referência abaixo da resposta ou o botão Fontes).
  const side = h("aside", { class: "st-side", id: "st-side", "aria-label": "Conversas" });
  const main = h("div", { class: "st-main" });
  const aside = h("aside", { class: "st-sources-panel", id: "st-sources", "aria-label": "Fontes desta resposta", hidden: true });
  const scrim = h("div", { class: "st-scrim", hidden: true, onclick: () => { showAside(false); if (narrow.matches) showSide(false); } });
  panels.chat.append(side, main, aside, scrim);
  const narrow = matchMedia("(max-width: 900px)"), mid = matchMedia("(max-width: 1180px)");
  let sideWanted = (() => { try { return localStorage.getItem("lumen.studySide") !== "closed"; } catch { return true; } })();
  const hasAside = () => !!(S.sources.length || S.related?.length || S.memories?.length);
  function showSide(open) {
    S.side = open;
    if (!narrow.matches) { sideWanted = open; try { localStorage.setItem("lumen.studySide", open ? "open" : "closed"); } catch { /* só conveniência */ } }
    layout(); renderHero();
  }
  function showAside(open) { S.aside = open && hasAside(); layout(); }
  function layout() {
    if (!hasAside()) S.aside = false;
    side.hidden = !S.side; aside.hidden = !S.aside;
    sideBtn.setAttribute("aria-expanded", String(S.side));
    srcBtn.hidden = !hasAside();
    srcBtn.setAttribute("aria-expanded", String(S.aside));
    srcBtn.replaceChildren(ic("book"), h("span", { text: "Fontes" }), S.sources.length ? h("span", { class: "st-count", text: String(S.sources.length) }) : null);
    scrim.hidden = !((S.side && narrow.matches) || (S.aside && mid.matches));
    panels.chat.classList.toggle("side-open", S.side);
  }
  narrow.addEventListener("change", () => { S.side = narrow.matches ? false : sideWanted; layout(); renderHero(); });
  mid.addEventListener("change", () => { if (mid.matches) S.aside = false; layout(); });  // a coluna de fontes não vira, sozinha, um painel por cima

  const convSearch = h("input", { type: "search", placeholder: "Pesquisar conversas", "aria-label": "Pesquisar conversas" });
  const projectSel = h("select", { class: "st-project-sel", "aria-label": "Projeto" });
  const tempToggle = h("button", { type: "button", class: "st-temp", "aria-pressed": "false", "aria-label": "Conversa temporária", "data-tip": "Conversa temporária: não entra no histórico nem cria memórias" }, ic("timer"), h("span", { text: "Temporária" }));
  const convList = h("nav", { class: "st-conv-list", "aria-label": "Histórico de conversas" });
  const sideFoot = h("div", { class: "st-side-foot" });
  side.append(
    btn("Nova conversa", () => newConversation(), { icon: "pen", cls: "btn ghost sm st-new" }),
    h("label", { class: "search-field st-conv-search" }, ic("search"), convSearch),
    h("label", { class: "st-proj-filter" }, ic("library"), projectSel), convList, sideFoot);
  // Barra da conversa: abrir o histórico, título, conversa temporária e fontes
  const sideBtn = btn("", () => showSide(!S.side), { icon: "sidebar", cls: "icon-btn sm", tip: "Histórico de conversas", attrs: { "aria-controls": "st-side" } });
  const convTitle = h("p", { class: "st-chat-title" });
  const srcBtn = h("button", { type: "button", class: "st-src-toggle", "aria-controls": "st-sources", hidden: true, "data-tip": "Fontes usadas na resposta", onclick: () => showAside(!S.aside) });
  const chatbar = h("div", { class: "st-chatbar" }, sideBtn,
    btn("", () => newConversation(), { icon: "plus", cls: "icon-btn sm st-new-mini", tip: "Nova conversa" }), convTitle, tempToggle, srcBtn);
  let searchTimer = 0;
  convSearch.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { S.query = convSearch.value.trim(); loadConversations(); }, 250); });
  projectSel.addEventListener("change", () => { S.project = projectSel.value; loadConversations(); });
  tempToggle.addEventListener("click", () => { S.temporary = !S.temporary; tempToggle.setAttribute("aria-pressed", String(S.temporary)); if (!S.conv || S.conv.messages?.length) newConversation(); else renderHero(); });

  async function loadConversations() {
    const r = await guard(() => api("/api/study/conversations" + qs({ q: S.query, project: S.project, archived: S.archived ? "1" : "", from: S.from, to: S.to })));
    if (!r) return;
    S.convs = r.conversations; S.projects = r.projects;
    renderProjectSelect(); renderConvList(); renderHero();
  }
  function renderProjectSelect() {
    const v = S.project;
    put(projectSel, h("option", { value: "", text: "Todos os projetos" }), h("option", { value: "none", text: "Sem projeto" }),
      S.projects.map((p) => h("option", { value: p.id, text: p.name })));
    projectSel.value = v;
  }
  function group(c) {
    if (c.temporary) return "Temporárias";
    if (c.pinned) return "Fixadas";
    const d = new Date(c.updated), now = new Date(), days = (now - d) / 864e5;
    return d.toDateString() === now.toDateString() ? "Hoje" : days < 7 ? "Últimos 7 dias" : days < 31 ? "Este mês" : "Mais antigas";
  }
  function renderConvList() {
    convList.replaceChildren();
    if (!S.convs.length) {
      convList.append(h("p", { class: "st-empty-small", text: S.query ? "Nenhuma conversa encontrada." : S.archived ? "Nenhuma conversa arquivada." : "Suas conversas aparecem aqui." }));
    }
    let current = "";
    for (const c of S.convs) {
      const g = group(c);
      if (g !== current) { convList.append(h("p", { class: "st-group", text: g })); current = g; }
      const active = S.conv?.id === c.id;
      const check = S.selecting && !c.temporary ? h("input", { type: "checkbox", "aria-label": "Selecionar " + (c.title || "conversa"), onchange: (e) => { e.target.checked ? S.selected.add(c.id) : S.selected.delete(c.id); renderSideFoot(); } }) : null;
      if (check && S.selected.has(c.id)) check.checked = true;
      const more = btn("", (e) => convMenu(e.currentTarget, c), { icon: "more", cls: "icon-btn sm st-conv-more", tip: "Ações da conversa" });
      convList.append(h("div", { class: "st-conv" + (active ? " active" : ""), dataset: { id: c.id }, oncontextmenu: (e) => { e.preventDefault(); convMenu(more, c); } }, check,
        h("button", { type: "button", class: "st-conv-open", "aria-current": active ? "true" : null, onclick: () => openConversation(c.id) },
          h("span", { class: "st-conv-title" }, c.pinned ? ic("pen", "st-pin") : null, c.temporary ? ic("timer", "st-pin") : null, c.title || c.first || "Nova conversa"),
          h("span", { class: "st-conv-meta", text: short(c.updated) })), more));
      if (active) convTitle.textContent = c.title || c.first || "";
    }
    renderSideFoot();
  }
  function short(iso) {  // a data da conversa em poucas letras: o grupo (Hoje, Últimos 7 dias…) já diz o resto
    if (!iso) return "";
    const d = new Date(iso), now = new Date();
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString("pt-BR", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  }
  function renderSideFoot() {
    sideFoot.replaceChildren(
      S.selecting ? h("div", { class: "st-select-bar" }, h("span", { text: `${S.selected.size} selecionada(s)` }),
        btn("Apagar", () => deleteSelected(), { icon: "trash", cls: "btn sm danger", attrs: { disabled: S.selected.size ? null : true } }),
        btn("Cancelar", () => { S.selecting = false; S.selected.clear(); renderConvList(); }))
        : h("div", { class: "st-side-actions" },
          btn(S.archived ? "Ver ativas" : "Arquivadas", () => { S.archived = !S.archived; loadConversations(); }, { icon: "library", cls: "link-btn" }),
          btn("", (e) => menu(e.currentTarget, [
            ["Selecionar várias", "check", () => { S.selecting = true; renderConvList(); }],
            ["Filtrar por data", "calendar", () => dateFilter()],
            ["Projetos", "library", () => openSettings("projects")],
            ["Apagar todas as conversas", "trash", () => deleteAll(), true],
          ]), { icon: "more", cls: "icon-btn sm", tip: "Mais opções do histórico" })));
  }
  async function dateFilter() {
    const v = await dialog({ title: "Filtrar por data", fields: [{ name: "from", label: "De", type: "date", value: S.from }, { name: "to", label: "Até", type: "date", value: S.to }], ok: "Filtrar" });
    if (v) { S.from = v.from; S.to = v.to; loadConversations(); }
  }
  function convMenu(anchor, c) {
    menu(anchor, [
      !c.temporary && ["Renomear", "pen", async () => { const v = await dialog({ title: "Renomear conversa", fields: [{ name: "title", label: "Título", value: c.title }], ok: "Salvar" }); if (v) { await guard(() => api("/api/study/conversations", { action: "rename", id: c.id, title: v.title })); loadConversations(); } }],
      !c.temporary && [c.pinned ? "Desafixar" : "Fixar", "pen", async () => { await guard(() => api("/api/study/conversations", { action: c.pinned ? "unpin" : "pin", id: c.id })); loadConversations(); }],
      !c.temporary && ["Mover para projeto", "library", async () => {
        const v = await dialog({ title: "Mover para projeto", fields: [{ name: "project", label: "Projeto", type: "select", value: c.project_id || "", options: [["", "Sem projeto"], ...S.projects.map((p) => [p.id, p.name])] }], ok: "Mover" });
        if (v) { await guard(() => api("/api/study/conversations", { action: "move", id: c.id, project_id: v.project })); loadConversations(); }
      }],
      !c.temporary && [c.archived ? "Desarquivar" : "Arquivar", "library", async () => { await guard(() => api("/api/study/conversations", { action: c.archived ? "unarchive" : "archive", id: c.id })); if (S.conv?.id === c.id) newConversation(); loadConversations(); }],
      !c.temporary && ["Exportar Markdown", "download", () => exportConversation(c.id, "md")],
      !c.temporary && ["Exportar JSON", "download", () => exportConversation(c.id, "json")],
      ["Apagar", "trash", async () => {
        if (!(await window.ui.confirm("A conversa, as mensagens e os arquivos anexados nela serão apagados. Suas notas no Notion e no Obsidian não são tocadas.", { title: "Apagar conversa?", ok: "Apagar", danger: true }))) return;
        await guard(() => api("/api/study/conversations", { action: "delete", id: c.id }), "Conversa apagada.");
        if (S.conv?.id === c.id) newConversation();
        loadConversations();
      }, true],
    ]);
  }
  async function exportConversation(id, format) {
    const r = await guard(() => api("/api/study/export" + qs({ id, format })));
    if (r) download(r.filename, r.content, format === "json" ? "application/json" : "text/markdown");
  }
  async function deleteSelected() {
    const ids = [...S.selected];
    if (!(await window.ui.confirm(`${ids.length} conversa(s) serão apagadas. Suas notas originais não são tocadas.`, { title: "Apagar conversas?", ok: "Apagar", danger: true }))) return;
    await guard(() => api("/api/study/conversations", { action: "delete_many", ids }), "Conversas apagadas.");
    S.selecting = false; S.selected.clear();
    if (S.conv && ids.includes(S.conv.id)) newConversation();
    loadConversations();
  }
  async function deleteAll() {
    const v = await dialog({ title: "Apagar todas as conversas?", message: "Todas as conversas e mensagens do histórico serão apagadas de vez, inclusive o índice de busca delas. Memórias, projetos e suas notas no Notion e no Obsidian ficam.", danger: true, require: "APAGAR", ok: "Apagar todas" });
    if (!v) return;
    await guard(() => api("/api/study/conversations", { action: "delete_all", confirm: "APAGAR" }), "Histórico apagado.");
    newConversation(); loadConversations();
  }

  // Centro: estado vazio, conversa e campo de mensagem (fixo embaixo; no estado vazio, centralizado com as sugestões)
  const thread = h("div", { class: "st-thread", "aria-live": "polite" });
  const statusLine = h("p", { class: "st-stage", role: "status", hidden: true });
  const input = h("textarea", { rows: 1, placeholder: "Pergunte qualquer coisa…", "aria-label": "Pergunta para o Lumen", maxlength: "8000" });
  const sendBtn = h("button", { type: "submit", class: "st-send", "aria-label": "Enviar", "data-tip": "Enviar (Enter) · Shift+Enter quebra a linha · / abre os comandos" }, ic("arrow-up"));
  const modeBtn = h("button", { type: "button", class: "st-mode", "aria-haspopup": "menu", "data-tip": "Modo da resposta" });
  const levelSel = h("select", { class: "st-level", "aria-label": "Nível da explicação", hidden: true },
    [["", "Nível: automático"], ["basico", "Básico"], ["intermediario", "Intermediário"], ["avancado", "Avançado"]].map(([v, l]) => h("option", { value: v, text: l })));
  // Alternador de busca no Notion e Obsidian (Modo Livre / IA Pura)
  S.skipVault = localStorage.getItem("lumen.study.skipVault") === "true";
  S.vaultSources = (() => { try { const r = localStorage.getItem("lumen.study.vaultSources"); return r ? JSON.parse(r) : null; } catch { return null; } })();
  const vaultDot = h("span", { class: "st-vault-dot", "aria-hidden": "true" });
  const vaultLabel = h("span", { class: "st-vault-label" });
  const vaultBtn = h("button", { type: "button", class: "st-vault-toggle", "aria-haspopup": "menu" }, vaultDot, vaultLabel, ic("chevron-down"));
  function renderVaultBtn() {
    const isFree = !!S.skipVault;
    vaultBtn.classList.toggle("free", isFree);
    let labelText = "Notas";
    let tip = "Fontes de notas ativas (Notion + Obsidian) · Clique para alternar para Modo Livre";
    if (isFree) {
      labelText = "Modo Livre";
      tip = "Modo Livre ativado: IA responde com raciocínio puro, sem consultar Notion ou Obsidian · Clique para reativar notas";
    } else if (S.vaultSources && S.vaultSources.length === 1) {
      labelText = S.vaultSources[0] === "obsidian" ? "Só Obsidian" : "Só Notion";
      tip = `Apenas notas do ${S.vaultSources[0] === "obsidian" ? "Obsidian" : "Notion"} ativas · Clique para alternar`;
    }
    vaultLabel.textContent = labelText;
    vaultBtn.dataset.tip = tip;
    vaultBtn.setAttribute("aria-label", `${labelText}: ${tip}`);
  }
  const vaultListeners = new Set();
  function setVaultState(free, sources = null) {
    S.skipVault = !!free;
    S.vaultSources = sources && sources.length ? sources : null;
    try {
      localStorage.setItem("lumen.study.skipVault", String(!!free));
      if (S.vaultSources) localStorage.setItem("lumen.study.vaultSources", JSON.stringify(S.vaultSources));
      else localStorage.removeItem("lumen.study.vaultSources");
    } catch { /* sem armazenamento: o estado vale só nesta janela */ }
    renderVaultBtn();
    for (const fn of vaultListeners) { try { fn({ free: S.skipVault, sources: S.vaultSources }); } catch { /* um ouvinte não derruba os outros */ } }
  }
  // Livre/Notas: um só estado para o chat escrito e a chamada de voz (a chamada lê, muda e escuta por aqui)
  const vaultApi = {
    get: () => ({ free: !!S.skipVault, sources: S.vaultSources }),
    set: (free, sources = null) => setVaultState(free, sources),
    onChange: (fn) => { vaultListeners.add(fn); return () => vaultListeners.delete(fn); },
  };
  function vaultMenu() {
    const opt = (label, hint, on, fn) => h("button", {
      type: "button", role: "menuitemradio", "aria-checked": String(on), class: "st-chip-opt",
      onclick: () => { closeMenu(); fn(); input.focus(); }
    }, h("span", { class: "st-chip-label", text: label }), hint ? h("span", { class: "st-chip-hint", text: hint }) : null);

    menu(vaultBtn, h("div", { class: "st-chip-menu", role: "menu", "aria-label": "Fontes de conhecimento da IA" },
      h("p", { class: "eyebrow", text: "Fontes de Conhecimento" }),
      opt("Notas Conectadas (Notion + Obsidian)", "Busca e cita trechos das suas notas nas respostas", !S.skipVault && !S.vaultSources, () => {
        setVaultState(false, null);
        toast("Notion e Obsidian conectados.", "success");
      }),
      opt("✨ Modo Livre (IA Pura)", "Desativa busca no Notion/Obsidian; responde com raciocínio direto", S.skipVault, () => {
        setVaultState(true, null);
        toast("Modo Livre ativado: respostas livres de notas.", "success");
      }),
      h("p", { class: "eyebrow", text: "Filtro Individual" }),
      opt("Só Obsidian", "Consulta apenas o cofre local do Obsidian", !S.skipVault && S.vaultSources?.length === 1 && S.vaultSources[0] === "obsidian", () => {
        setVaultState(false, ["obsidian"]);
        toast("Consulta restrita ao Obsidian.", "info");
      }),
      opt("Só Notion", "Consulta apenas as páginas do Notion", !S.skipVault && S.vaultSources?.length === 1 && S.vaultSources[0] === "notion", () => {
        setVaultState(false, ["notion"]);
        toast("Consulta restrita ao Notion.", "info");
      })
    ));
  }
  vaultBtn.addEventListener("click", (e) => {
    const rect = vaultBtn.getBoundingClientRect();
    if (e.clientX > rect.right - 22) return vaultMenu();
    const next = !S.skipVault;
    setVaultState(next, S.vaultSources);
    toast(next ? "Modo Livre ativado: sem consulta ao Notion e Obsidian." : "Notas ativadas: consultando Notion e Obsidian.", "info");
  });
  vaultBtn.addEventListener("contextmenu", (e) => { e.preventDefault(); vaultMenu(); });
  renderVaultBtn();
  // Livre/Notas também muda na Conversa rápida da barra flutuante (outra janela, mesmas chaves): este botão acompanha na hora
  window.addEventListener("storage", (e) => {
    if (e.key !== "lumen.study.skipVault" && e.key !== "lumen.study.vaultSources") return;
    S.skipVault = localStorage.getItem("lumen.study.skipVault") === "true";
    S.vaultSources = (() => { try { const r = localStorage.getItem("lumen.study.vaultSources"); return r ? JSON.parse(r) : null; } catch { return null; } })();
    renderVaultBtn();
    for (const fn of vaultListeners) { try { fn({ free: S.skipVault, sources: S.vaultSources }); } catch { /* um ouvinte não derruba os outros */ } }
  });
  // Medidor do contexto: uso medido na última resposta ("12 mil / 16 mil"); clicar abre o /context
  const ctxBtn = h("button", { type: "button", class: "st-ctx", hidden: true, "aria-haspopup": "dialog", onclick: () => contextPanel() });
  // Menu "/": comandos e skills do registro único, acima do campo
  const slash = h("div", { class: "st-slash", id: "st-slash", role: "listbox", "aria-label": "Comandos e skills", hidden: true });
  input.setAttribute("aria-controls", "st-slash");
  // Anexos (Study AI 2.0, fase 4): clipe, arrastar ou colar um print. O tipo real é conferido no servidor pelos bytes.
  const fileInput = h("input", { type: "file", multiple: true, hidden: true, tabindex: "-1", "aria-hidden": "true" });
  const attachBtn = h("button", { type: "button", class: "st-attach", "aria-label": "Anexar arquivo",
    "data-tip": "Anexar texto, PDF, Office, imagem, áudio ou vídeo · também dá para arrastar ou colar um print (Ctrl+V)", onclick: () => fileInput.click() }, ic("plus"));
  // Perplexity (D185): o texto da caixa vira só a sugestão do diálogo, que mostra e confirma o que vai ao site
  const pplxBtn = h("button", { type: "button", class: "st-attach st-pplx", "aria-label": "Pesquisar no Perplexity",
    "data-tip": "Pesquisar no Perplexity · abre o site oficial aqui dentro; só a pergunta que você confirmar vai até ele (/perplexity)",
    onclick: () => perplexityOpen(input.value.trim()) }, ic("external"));
  const attachRow = h("div", { class: "st-attach-row", role: "list", "aria-label": "Anexos desta pergunta", hidden: true });
  // Apertar para falar (fase 6): o texto transcrito entra na caixa para conferir; com "enviar sozinho", já vai
  const talkBtn = window.lumenVoice?.ptt({
    isActive: () => !root.hidden && !panels.chat.hidden && !main.hidden && settingsHost.hidden,
    onText: (t) => { input.value = (input.value.trim() ? input.value.trim() + " " : "") + t; autosize(); input.focus();
      S.voiceTurn = true;  // conversa por voz: a resposta desta pergunta é lida em voz alta
      if (S.state?.settings?.voice?.send_alone) submit(); } }) || null;
  const callBtn = h("button", { type: "button", class: "st-call-open", "aria-label": "Conversa por voz", "data-tip": "Conversa por voz · fale e ouça a resposta, sem apertar nada", onclick: () => window.lumenStudy.openCall?.() },
    h("span", { class: "st-call-open-bars", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")));
  // Aquecimento seletivo: só quando o estudante dá sinal de que vai falar (passa o mouse ou foca o botão); a voz sobe enquanto ele decide
  for (const evName of ["pointerenter", "focus"]) callBtn.addEventListener(evName, () => window.lumenVoice?.warm("answer"));
  const composer = h("form", { class: "st-composer", onsubmit: (e) => { e.preventDefault(); submit(); } },
    attachRow, input, h("div", { class: "st-composer-bar" }, attachBtn, pplxBtn, modeBtn, levelSel, vaultBtn, ctxBtn, talkBtn, callBtn, sendBtn), fileInput);
  const dock = h("div", { class: "st-dock" }, slash, composer);
  S.staged = [];
  let attachPoll = 0;
  async function uploadAttachment(file, name = file.name) {
    const r = await fetch("/api/study/attachments" + qs({ name }), { method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Lumen-Token": TOKEN }, body: file });
    const v = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error([v.error?.message, v.error?.action].filter(Boolean).join(" ") || "Não foi possível anexar.");
    return v;
  }
  async function attach(files) {
    for (const f of [...files].slice(0, 10)) {
      const name = f.name || `print-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-")}.png`;
      const tmp = { id: "up" + Math.random().toString(36).slice(2), name, kind: "", status: "uploading", message: "Enviando…" };
      S.staged.push(tmp); renderStaged();
      try {
        Object.assign(tmp, await uploadAttachment(f, name));
      } catch (e) {
        S.staged = S.staged.filter((x) => x !== tmp);
        toast(e.message, "error");
      }
      renderStaged();
    }
    pollStaged();
  }
  // Enquanto algum anexo está sendo lido (visão, transcrição), a ficha mostra o andamento real
  function pollStaged() {
    clearTimeout(attachPoll);
    const reading = S.staged.filter((x) => x.status === "reading");
    if (!reading.length) return;
    attachPoll = setTimeout(async () => {
      const r = await api("/api/study/attachments" + qs({ ids: reading.map((x) => x.id).join(",") })).catch(() => null);
      for (const a of r?.attachments || []) Object.assign(S.staged.find((x) => x.id === a.id) || {}, a);
      renderStaged(); pollStaged();
    }, 1500);
  }
  function renderStaged() {
    attachRow.hidden = !S.staged.length;
    put(attachRow, S.staged.map((a) => h("div", { class: "st-attach-chip " + a.status, role: "listitem", "data-tip": a.message || null },
      a.thumb && a.status === "ready" ? img(qs({ a: a.id }).slice(1)) : ic(KIND_ICON[a.kind] || "file"),
      h("span", { class: "st-attach-name", text: a.name }),
      h("span", { class: "st-attach-state", text: a.status === "ready" ? (a.label || "") : a.status === "error" ? "Não deu para ler" : a.message || "Lendo…" }),
      a.status === "uploading" ? null : btn("", () => unstage(a), { icon: "x", cls: "icon-btn sm", tip: `Tirar ${a.name}` }))));
  }
  async function unstage(a) {
    S.staged = S.staged.filter((x) => x !== a); renderStaged();
    await api("/api/study/attachment", { action: "remove", id: a.id }).catch(() => {});
  }
  fileInput.addEventListener("change", () => { attach(fileInput.files); fileInput.value = ""; });
  input.addEventListener("paste", (e) => {  // print com Ctrl+V: só imagens e arquivos; texto colado segue normal
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); attach(files); }
  });
  main.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); composer.classList.add("drop"); } });
  main.addEventListener("dragleave", (e) => { if (!main.contains(e.relatedTarget)) composer.classList.remove("drop"); });
  main.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { e.preventDefault(); composer.classList.remove("drop"); attach(e.dataTransfer.files); } });
  const hero = h("div", { class: "st-hero" }), heroMore = h("div", { class: "st-hero-more" });
  main.append(chatbar, hero, thread, statusLine, dock, heroMore);
  const MODES = [["auto", "Automático", "sparkle"], ["search", "Só buscar", "search"], ["explain", "Explicar", "book"], ["summary", "Resumir", "page"], ["compare", "Comparar", "graph"], ["find", "Encontrar materiais", "folder"]];
  function setMode(m) {
    S.mode = m;
    levelSel.hidden = m !== "explain";
    input.placeholder = m === "search" ? "Pesquise nas suas notas e páginas…" : "Pergunte qualquer coisa…";
    renderChip();
  }
  const EFFORT_KEYS = ["", "rapido", "equilibrado", "profundo", "maximo"];
  const EFFORT_INFO = {
    "": { label: "Automático", icon: "sparkle", tag: "Adaptativo", desc: "O Lúmen analisa a complexidade do pedido e ajusta o raciocínio dinamicamente.", time: "Tempo flexível", sources: "Até 8 fontes", think: "Raciocínio adaptativo", review: "Revisão sob demanda" },
    "rapido": { label: "Rápido", icon: "timer", tag: "Velocidade", desc: "Respostas instantâneas e diretas. Menos fontes e no máximo uma busca complementar.", time: "Até 120s", sources: "Até 4 fontes", think: "Raciocínio direto", review: "Sem auto-revisão" },
    "equilibrado": { label: "Equilibrado", icon: "check-circle", tag: "Padrão", desc: "Equilíbrio entre agilidade e profundidade: até 8 fontes com síntese contextual.", time: "Até 180s", sources: "Até 8 fontes", think: "Raciocínio balanceado", review: "Sem auto-revisão" },
    "profundo": { label: "Profundo", icon: "brain", tag: "Extended Thinking", desc: "Raciocínio estendido ativo: a IA planeja passo a passo antes de responder e analisa até 12 fontes.", time: "Até 420s", sources: "Até 12 fontes", think: "Extended Thinking", review: "Sem auto-revisão" },
    "maximo": { label: "Máximo", icon: "cpu", tag: "Potência Máxima", desc: "Capacidade analítica máxima: maior modelo, raciocínio estendido completo e auto-revisão do rascunho.", time: "Até 900s", sources: "Até 16 fontes", think: "Thinking completo", review: "Auto-revisão crítica" }
  };

  function createMetricPill(iconName, text) {
    return h("span", { class: "st-effort-metric" }, ic(iconName), h("span", { text }));
  }

  function renderMetrics(container, cur) {
    container.replaceChildren(
      createMetricPill("clock", cur.time),
      createMetricPill("book", cur.sources),
      createMetricPill("brain", cur.think),
      createMetricPill("sync", cur.review)
    );
  }

  function createMiniSlider(idx) {
    const track = h("span", {
      class: "st-effort-track-mini",
      "data-tip": "Nível de esforço"
    });
    const pct = (idx / 4) * 100;
    const fill = h("span", { class: "st-effort-fill-mini" });
    fill.style.width = `calc(6px + ${pct * 0.01} * (100% - 12px))`;
    track.append(fill);
    for (let i = 0; i < 5; i++) {
      const dot = h("span", { class: "st-effort-dot-mini" + (i <= idx ? " on" : "") });
      dot.style.left = `calc(6px + ${i * 0.25} * (100% - 12px))`;
      track.append(dot);
    }
    const thumb = h("span", { class: "st-effort-thumb-mini" });
    thumb.style.left = `calc(6px + ${pct * 0.01} * (100% - 12px))`;
    track.append(thumb);
    return track;
  }

  function createFullEffortWidget(currentEffort, onSelect) {
    let effIdx = EFFORT_KEYS.indexOf(currentEffort);
    if (effIdx < 0) effIdx = 0;

    const wrap = h("div", { class: "st-effort-widget", role: "region", "aria-label": "Controle de Esforço e Raciocínio" });
    const header = h("div", { class: "st-effort-header" });
    const title = h("p", { class: "eyebrow", text: "Esforço de Raciocínio" });
    const info = EFFORT_INFO[EFFORT_KEYS[effIdx]] || EFFORT_INFO[""];
    const badge = h("span", { class: "st-effort-tag " + (effIdx >= 3 ? "purple" : ""), text: info.tag });
    header.append(title, badge);

    const sliderContainer = h("div", { class: "st-effort-slider-box" });
    const track = h("div", {
      class: "st-effort-track-full",
      role: "slider",
      "aria-valuemin": "0",
      "aria-valuemax": "4",
      "aria-valuenow": String(effIdx),
      "aria-valuetext": info.label,
      tabindex: "0"
    });

    const pct = (effIdx / 4) * 100;
    const fill = h("div", { class: "st-effort-fill-full" });
    fill.style.width = `calc(9px + ${pct * 0.01} * (100% - 18px))`;

    const dots = [];
    for (let i = 0; i < 5; i++) {
      const dot = h("span", { class: "st-effort-dot-full" + (i <= effIdx ? " on" : "") });
      dot.style.left = `calc(9px + ${i * 0.25} * (100% - 18px))`;
      dots.push(dot);
    }

    const thumb = h("div", { class: "st-effort-thumb-full" });
    thumb.style.left = `calc(9px + ${pct * 0.01} * (100% - 18px))`;
    track.append(fill, ...dots, thumb);

    const labelsRow = h("div", { class: "st-effort-labels-row" },
      EFFORT_KEYS.map((k, i) => {
        const isAuto = k === "";
        const btn = h("button", {
          type: "button",
          role: "menuitemradio",
          "aria-label": isAuto ? "Automático (Esforço)" : EFFORT_INFO[k].label,
          "aria-checked": String(i === effIdx),
          class: "st-effort-label-btn" + (i === effIdx ? " active" : ""),
          onclick: (e) => {
            e.preventDefault();
            update(i);
            onSelect(k);
            closeMenu();
            input.focus();
          }
        }, h("span", { text: EFFORT_INFO[k].label }));

        btn.onpointerenter = () => {
          const cur = EFFORT_INFO[k];
          cardIcon.querySelector("use")?.setAttribute("href", `/icons.svg#${cur.icon}`);
          cardTitle.textContent = `${cur.label} · ${cur.tag}`;
          cardDesc.textContent = cur.desc;
          renderMetrics(metricsGrid, cur);
        };
        btn.onpointerleave = () => {
          const cur = EFFORT_INFO[EFFORT_KEYS[effIdx]];
          cardIcon.querySelector("use")?.setAttribute("href", `/icons.svg#${cur.icon}`);
          cardTitle.textContent = `${cur.label} · ${cur.tag}`;
          cardDesc.textContent = cur.desc;
          renderMetrics(metricsGrid, cur);
        };
        return btn;
      })
    );

    sliderContainer.append(track, labelsRow);

    const card = h("div", { class: "st-effort-card" });
    const cardIcon = ic(info.icon);
    const cardTitle = h("span", { class: "st-effort-card-title", text: `${info.label} · ${info.tag}` });
    const cardHead = h("div", { class: "st-effort-card-title-row" }, cardIcon, cardTitle);
    const cardDesc = h("p", { class: "st-effort-card-desc", text: info.desc });
    const metricsGrid = h("div", { class: "st-effort-metrics" });
    renderMetrics(metricsGrid, info);
    card.append(cardHead, cardDesc, metricsGrid);

    function update(newIdx) {
      effIdx = Math.max(0, Math.min(4, newIdx));
      const k = EFFORT_KEYS[effIdx];
      const cur = EFFORT_INFO[k];
      badge.textContent = cur.tag;
      badge.className = "st-effort-tag " + (effIdx >= 3 ? "purple" : "");
      const newPct = (effIdx / 4) * 100;
      fill.style.width = `calc(9px + ${newPct * 0.01} * (100% - 18px))`;
      thumb.style.left = `calc(9px + ${newPct * 0.01} * (100% - 18px))`;
      dots.forEach((d, i) => d.classList.toggle("on", i <= effIdx));
      track.setAttribute("aria-valuenow", String(effIdx));
      track.setAttribute("aria-valuetext", cur.label);
      labelsRow.querySelectorAll(".st-effort-label-btn").forEach((b, i) => {
        b.classList.toggle("active", i === effIdx);
        b.setAttribute("aria-checked", String(i === effIdx));
      });
      cardIcon.querySelector("use")?.setAttribute("href", `/icons.svg#${cur.icon}`);
      cardTitle.textContent = `${cur.label} · ${cur.tag}`;
      cardDesc.textContent = cur.desc;
      renderMetrics(metricsGrid, cur);
    }

    function handleTrackEvent(e) {
      const rect = track.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const newIdx = Math.round(ratio * 4);
      update(newIdx);
      onSelect(EFFORT_KEYS[newIdx]);
    }
    track.addEventListener("pointerdown", (e) => {
      track.setPointerCapture?.(e.pointerId);
      handleTrackEvent(e);
      const onMove = (mv) => handleTrackEvent(mv);
      const onUp = (up) => {
        track.removeEventListener("pointermove", onMove);
        track.removeEventListener("pointerup", onUp);
      };
      track.addEventListener("pointermove", onMove);
      track.addEventListener("pointerup", onUp);
    });
    track.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); update(effIdx + 1); onSelect(EFFORT_KEYS[effIdx]); }
      if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); update(effIdx - 1); onSelect(EFFORT_KEYS[effIdx]); }
    });

    wrap.append(header, sliderContainer, card);
    return { wrap, update };
  }

  // Perfil adulto (D92): o modelo da resposta. "" segue o ajuste (automático ou fixo); a escolha vale para esta conversa.
  const PROFILES = [["", "Automático", "sparkle", "Segue o ajuste do perfil adulto: o Lúmen decide pelo pedido, no seu PC."],
    ["main", "Principal", "cpu", "Responde com o modelo principal, mesmo que o pedido pareça do perfil adulto."],
    ["adult", "Perfil adulto", "shield", "Responde com o modelo local dedicado, com as instruções e a temperatura próprias."]];
  function createProfileWidget(onSelect) {
    const tiles = PROFILES.map(([id, label, icon, desc]) => h("button", { type: "button", role: "menuitemradio", "aria-checked": String(S.profile === id),
      class: "st-mode-tile" + (S.profile === id ? " active" : ""), title: desc,
      onclick: (e) => { e.preventDefault(); onSelect(id); closeMenu(); input.focus(); } }, ic(icon), h("span", { text: label })));
    return h("div", { class: "st-mode-section", role: "region", "aria-label": "Modelo da resposta" },
      h("div", { class: "st-mode-header" }, h("p", { class: "eyebrow", text: "Modelo da resposta" })),
      h("div", { class: "st-mode-grid", role: "group", "aria-label": "Opções de modelo" }, tiles));
  }
  function chooseProfile(id) { S.profile = id; S.profileUsed = id || S.profileUsed; renderChip(); }

  // O chip mostra o modo e o esforço, e o que o Automático decidiu na última resposta (com o motivo na dica)
  function renderChip() {
    const [, label, icon] = MODES.find((x) => x[0] === S.mode) || MODES[0];
    // Do que veio da última resposta, só o que o Automático decidiu (um esforço escolhido à mão não aparece como automático)
    const d = S.mode === "search" ? null : S.decided, autoMode = S.mode === "auto" && d?.auto?.mode, autoEffort = !S.effort && d?.auto?.effort;
    const modeText = autoMode ? `Automático · ${INTENT_LABEL[d.mode] || d.mode}` : label;
    const effort = S.mode === "search" ? "" : S.effort || (autoEffort ? d.effort : "");
    const profile = S.profile ? PROFILE_LABEL[S.profile] : S.profileUsed === "adult" ? PROFILE_LABEL.adult : "";
    const text = [modeText, effort ? EFFORT_LABEL[effort] : "", profile].filter(Boolean).join(" · ");

    let effIdx = EFFORT_KEYS.indexOf(S.effort);
    if (effIdx < 0) effIdx = 0;

    const miniSlider = createMiniSlider(effIdx);

    modeBtn.replaceChildren(ic(icon), h("span", { text }), miniSlider, ic("chevron-down"));
    modeBtn.dataset.tip = autoMode || autoEffort ? `Escolha automática${d.reason ? ": " + d.reason : ""}` : "Modo e esforço da resposta";
    modeBtn.setAttribute("aria-label", `Modo e esforço: ${text}`);
  }
  function chooseChip(kind, id) {
    if (kind === "mode") setMode(id); else { S.effort = id; renderChip(); }
  }
  // Troca do que o Automático decidiu na última resposta, calculada no envio: só o que mudou (voltar atrás não conta)
  function override() {
    const d = S.decided, from = {}, to = {};
    if (d?.auto?.mode && !["auto", "search", d.mode].includes(S.mode)) { from.mode = d.mode; to.mode = S.mode; }
    if (d?.auto?.effort && S.effort && S.effort !== d.effort) { from.effort = d.effort; to.effort = S.effort; }
    return Object.keys(from).length ? { from, to } : null;
  }
  const MODE_INFO = {
    auto: { label: "Automático", tag: "Inteligente", icon: "sparkle", desc: "O Lúmen detecta o melhor formato sozinho pelo tom e pelo pedido da pergunta." },
    search: { label: "Só buscar", tag: "Sem IA", icon: "search", desc: "Busca híbrida nas notas (Notion e Obsidian) com relevância calculada, sem chamar a IA." },
    explain: { label: "Explicar", tag: "Didático", icon: "book", desc: "Explicação didática em camadas, com diagramas conceituais e checagem rápida." },
    summary: { label: "Resumir", tag: "Síntese", icon: "page", desc: "Resumo estruturado com ideias centrais, pontos-chave e conclusões das notas." },
    compare: { label: "Comparar", tag: "Relações", icon: "graph", desc: "Mapeia semelhanças, contrastes, divergências e contradições entre os temas." },
    find: { label: "Encontrar materiais", tag: "Fontes", icon: "folder", desc: "Localiza e mapeia quais notas e páginas você possui sobre o assunto." }
  };

  function createModeWidget(currentMode, onSelect) {
    let modeKey = currentMode || "auto";
    const curInfo = MODE_INFO[modeKey] || MODE_INFO.auto;

    const wrap = h("div", { class: "st-mode-section", role: "region", "aria-label": "Modo da Resposta" });
    const header = h("div", { class: "st-mode-header" });
    const title = h("p", { class: "eyebrow", text: "Modo de Resposta" });
    const badge = h("span", { class: "st-effort-tag", text: curInfo.tag });
    header.append(title, badge);

    const grid = h("div", { class: "st-mode-grid", role: "group", "aria-label": "Opções de Modo" });
    const tiles = [];

    const card = h("div", { class: "st-mode-card" });
    const cardIcon = ic(curInfo.icon);
    const cardTitle = h("span", { class: "st-mode-card-title", text: `${curInfo.label} · ${curInfo.tag}` });
    const cardHead = h("div", { class: "st-mode-card-title-row" }, cardIcon, cardTitle);
    const cardDesc = h("p", { class: "st-mode-card-desc", text: curInfo.desc });
    card.append(cardHead, cardDesc);

    function update(newKey) {
      modeKey = newKey;
      const info = MODE_INFO[modeKey] || MODE_INFO.auto;
      badge.textContent = info.tag;
      cardIcon.querySelector("use")?.setAttribute("href", `/icons.svg#${info.icon}`);
      cardTitle.textContent = `${info.label} · ${info.tag}`;
      cardDesc.textContent = info.desc;
      tiles.forEach(({ btn, id }) => {
        const isSel = id === modeKey;
        btn.setAttribute("aria-checked", String(isSel));
        btn.classList.toggle("active", isSel);
      });
    }

    MODES.forEach(([id, label, icon]) => {
      const isSel = id === modeKey;
      const tile = h("button", {
        type: "button",
        role: "menuitemradio",
        "aria-checked": String(isSel),
        class: "st-mode-tile" + (isSel ? " active" : ""),
        onclick: (e) => {
          e.preventDefault();
          update(id);
          onSelect(id);
          closeMenu();
          input.focus();
        }
      }, ic(icon), h("span", { text: label }));

      tile.onpointerenter = () => {
        const hInfo = MODE_INFO[id] || MODE_INFO.auto;
        cardIcon.querySelector("use")?.setAttribute("href", `/icons.svg#${hInfo.icon}`);
        cardTitle.textContent = `${hInfo.label} · ${hInfo.tag}`;
        cardDesc.textContent = hInfo.desc;
      };
      tile.onpointerleave = () => {
        const aInfo = MODE_INFO[modeKey] || MODE_INFO.auto;
        cardIcon.querySelector("use")?.setAttribute("href", `/icons.svg#${aInfo.icon}`);
        cardTitle.textContent = `${aInfo.label} · ${aInfo.tag}`;
        cardDesc.textContent = aInfo.desc;
      };

      tiles.push({ btn: tile, id });
      grid.append(tile);
    });

    wrap.append(header, grid, card);
    return { wrap, update };
  }

  function chipMenu() {
    const modeWidget = createModeWidget(S.mode, (newMode) => {
      chooseChip("mode", newMode);
    });

    const effortWidget = createFullEffortWidget(S.effort, (newKey) => {
      chooseChip("effort", newKey);
    });

    const divider = h("div", { class: "st-panel-divider" });
    const adultOn = S.state?.settings?.adult?.enabled;

    menu(modeBtn, h("div", { class: "st-chip-menu unified-panel", role: "menu", "aria-label": "Painel Unificado de Modo e Esforço" },
      modeWidget.wrap,
      divider,
      effortWidget.wrap,
      adultOn ? h("div", { class: "st-panel-divider" }) : null,
      adultOn ? createProfileWidget(chooseProfile) : null,
      S.decided?.reason ? h("div", { class: "faint st-decided-hint" }, ic("sparkle"), h("span", { text: `Última escolha automática: ${S.decided.reason}.` })) : null));
  }
  modeBtn.addEventListener("click", chipMenu);
  levelSel.addEventListener("change", () => { S.level = levelSel.value; });
  input.addEventListener("input", () => { autosize(); updateSlash(); });
  input.addEventListener("blur", () => setTimeout(closeSlash, 150));
  input.addEventListener("keydown", (e) => {
    if (!slash.hidden && slashItems.length) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        slashActive = (slashActive + (e.key === "ArrowDown" ? 1 : -1) + slashItems.length) % slashItems.length;
        return updateSlash();
      }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); return pickSlash(slashActive); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); return closeSlash(); }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });

  // --- Menu "/" (registro único: GET /api/study/registry) ---------------------------------------------------------
  let slashItems = [], slashActive = 0;
  async function registryMenu() {
    if (!S.menu) S.menu = (await guard(() => api("/api/study/registry")))?.menu || null;
    return S.menu || [];
  }
  const slashQuery = () => (/^\/(\S*)$/.exec(input.value) || [])[1]?.toLowerCase() ?? null;
  async function updateSlash() {
    const q = slashQuery();
    if (q === null) return closeSlash();
    if (q === "" && slash.hidden) S.menu = null;  // cada "/" novo relê a lista (uma skill nova aparece sem recarregar)
    const all = await registryMenu();
    if (slashQuery() !== q) return;  // o texto mudou enquanto a lista chegava
    slashItems = all.filter((x) => x.name.startsWith(q) || (q.length > 1 && x.name.includes(q)));
    if (!slashItems.length) return closeSlash();
    slashActive = Math.min(slashActive, slashItems.length - 1);
    put(slash, slashItems.map((x, i) => h("div", { role: "option", id: "st-slash-" + i, class: "st-slash-item", "aria-selected": String(i === slashActive),
      onpointerdown: (e) => { e.preventDefault(); pickSlash(i); } },
      ic(SLASH_ICON[x.kind === "command" ? "command" : x.origin] || "sparkle"),
      h("span", { class: "st-slash-name" }, "/" + x.name, x.args ? h("span", { class: "st-slash-args", text: " " + x.args }) : null),
      h("span", { class: "st-slash-desc", text: x.description + (x.kind === "skill" && x.origin !== "sistema" ? ` · skill ${ORIGIN[x.origin]}` : "") }))));
    slash.hidden = false;
    input.setAttribute("aria-activedescendant", "st-slash-" + slashActive);
    slash.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }
  function closeSlash() { slash.hidden = true; slashItems = []; slashActive = 0; input.removeAttribute("aria-activedescendant"); }
  function pickSlash(i) {
    const x = slashItems[i];
    if (!x) return;
    closeSlash();
    // um comando cujo argumento começa por uma palavra fixa (“3d <assunto>”) já a escreve: /elegrama 3d␣
    const lead = x.kind === "command" ? /^([a-z0-9]+)\s/.exec(x.args || "")?.[1] : "";
    input.value = `/${x.name}` + (x.args ? " " : "") + (lead ? lead + " " : "");
    autosize(); input.focus();
    if (!x.args) submit();
  }
  // "/nome argumentos": executa um comando aqui (devolve null) ou diz como enviar (texto, modo ou skill)
  async function command(text) {
    const [, raw, rest = ""] = /^\/(\S+)\s*([\s\S]*)$/.exec(text) || [];
    const name = (raw || "").toLowerCase(), arg = rest.trim();
    const item = (await registryMenu()).find((x) => x.name === name);
    const done = () => { input.value = ""; autosize(); return null; };
    if (!item) { toast(`Comando desconhecido: /${name}. Digite / para ver a lista.`, "warning"); return null; }
    if (item.kind === "skill") {
      if (!arg && item.args.startsWith("<")) { toast(`Escreva ${item.args} depois de /${item.name}.`, "info"); return null; }
      return item.origin === "sistema" ? { text: arg, mode: item.mode } : { text, skill: item.id };
    }
    switch (name) {
      case "ajuda": input.value = "/"; autosize(); updateSlash(); return null;
      case "clear": done(); clearConversation(); return null;
      case "compact": done(); compactNow(arg); return null;
      case "context": done(); contextPanel(); return null;
      case "buscar": if (!arg) { toast("Escreva o que buscar depois de /buscar.", "info"); return null; } done(); runSearch(arg); return null;
      case "temp": done(); tempToggle.click(); return null;
      case "anexar": done(); fileInput.click(); return null;
      case "tela": return { text: arg || "O que aparece na janela que estou usando? Me ajude a entender.", screen: true };
      case "web":
        if (!arg) { toast("Escreva a consulta depois de /web.", "info"); return null; }
        return { text: arg, web: true, mode: "chat" };
      case "perplexity": done(); if (arg) perplexityOpen(arg); else perplexityPaste(); return null;
      case "nota": case "pagina":
        if (!arg) { toast("Descreva o que criar depois do comando.", "info"); return null; }
        return { text: arg, create_destination: name === "nota" ? "obsidian" : "notion", mode: "chat" };
      case "abrir": {
        const app = ({ calculadora: "calculator", cofre: "vault", "pasta do cofre": "vault", "microsoft edge": "edge" })[arg.toLowerCase()] || arg.toLowerCase();
        const r = await guard(() => api("/api/study/open-app", { app }));
        if (r?.opened) toast(`${r.title} aberto.`, "success");
        return done();
      }
      case "imagem":
        return { text };  // sempre o gerador local: a imagem em nuvem é cobrada e está bloqueada (servidor e política)
      case "video":
        toast("O Lúmen não gera vídeo.", "info");
        return null;
      case "pdf":
        return { text };  // a capa ilustrada também é gerada no seu PC
      case "elegrama": case "holograma": {
        // /elegrama 3d <assunto>: sem o “3d” ou sem assunto não sai pedido nenhum, só o exemplo (o servidor confere de novo)
        const topic = /^3d(?:\s+([\s\S]*))?$/i.exec(arg)?.[1]?.trim();
        if (!topic) { toast(`Use /${name} 3d <assunto>. Exemplo: /${name} 3d do sistema solar`, "info"); return null; }
        return { text };
      }
      case "modo": {
        const a = fold(arg), alias = { conversar: "auto", automatico: "auto", buscar: "search" }[a];
        const m = MODES.find(([id, label]) => id === alias || (a && fold(label).startsWith(a)));
        if (!arg || !m) { toast("Modos: automático, buscar, explicar, resumir, comparar ou encontrar. Ex.: /modo explicar", "info"); return null; }
        done(); chooseChip("mode", m[0]); toast(`Modo: ${m[1]}.`, "success"); return null;
      }
      case "esforco": {
        const e = EFFORTS.find(([id, label]) => arg && fold(label).startsWith(fold(arg)));
        if (!e) { toast("Esforços: automático, rápido, equilibrado, profundo ou máximo. Ex.: /esforco profundo", "info"); return null; }
        done(); chooseChip("effort", e[0]); toast(`Esforço: ${e[1]}.`, "success"); return null;
      }
      case "perfil": {
        const a = fold(arg), id = { automatico: "", auto: "", principal: "main", adulto: "adult", "perfil adulto": "adult" }[a];
        if (!arg || id === undefined) { toast("Perfis: automático, principal ou adulto. Ex.: /perfil adulto", "info"); return null; }
        if (id === "adult" && !S.state?.settings?.adult?.enabled) { toast("Ligue o perfil adulto em Configurações → Perfil adulto.", "warning"); openSettings("adult"); return null; }
        done(); chooseProfile(id); toast(`Modelo da resposta: ${id ? PROFILE_LABEL[id] : "Automático"}.`, "success"); return null;
      }
      case "memoria": done(); openSettings("memory"); return null;
      case "livre": case "puro":
        done(); setVaultState(true, null);
        toast("Modo Livre ativado: respostas com raciocínio puro, sem buscar no Notion ou Obsidian.", "info");
        return null;
      case "notas": case "cofre":
        done(); setVaultState(false, null);
        toast("Notas ativadas: Notion e Obsidian conectados às respostas.", "success");
        return null;
      case "exportar":
        if (!S.conv?.id || S.conv.temporary) { toast("Só conversas salvas no histórico podem ser exportadas.", "info"); return null; }
        done(); exportConversation(S.conv.id, "md"); return null;
    }
    return null;
  }

  // --- Perplexity: o site oficial num painel do Lumen.exe (perfil próprio, sem ponte com o app, D185) -----------------
  // Só a pergunta confirmada aqui sai do Lúmen; a volta é sempre colar à mão o que foi copiado lá, marcado como tal.
  const PPLX_SEARCH = "https://www.perplexity.ai/search?q=";  // o modelo do opensearch.xml do site (conferido em 19/11/2026)
  const PPLX_LABEL = "[Conteúdo do Perplexity colado por mim · não verificado pelo Lúmen]";
  const PPLX_MAX = 8000;  // o servidor corta a mensagem em 8 000 caracteres (agent.py): mais que isso vira anexo, sem perder as fontes
  const perplexityUrl = (q) => PPLX_SEARCH + encodeURIComponent(q);
  async function perplexityOpen(arg) {
    const v = await dialog({ title: "Pesquisar no Perplexity", ok: "Abrir no Perplexity",
      message: "Só esta pergunta sai do Lúmen e vai ao Perplexity, no site oficial e com a sua conta de lá. Conversa, notas, anexos e fontes não são enviados.",
      fields: [{ name: "q", label: "Pergunta enviada ao Perplexity", type: "textarea", rows: 3, value: arg }] });
    const q = v?.q.trim();
    if (q) perplexityGo(q);
  }
  // Lumen.exe 3+: painel dentro da janela (perfil webview-perplexity); antes dele ou fora dele, o navegador padrão.
  // Sem pergunta, a página inicial do site.
  const perplexityInPanel = () => !!host && /LumenShell\/([3-9]|\d\d)\b/.test(navigator.userAgent);
  function perplexityGo(q) {
    const url = q ? perplexityUrl(q) : "https://www.perplexity.ai/";
    if (perplexityInPanel()) host.postMessage("perplexity:open:" + url);
    else window.open(url, "_blank", "noopener");
    toast("Quando tiver a resposta, use Copiar no Perplexity e “Trazer resposta ao Lúmen” (ou /perplexity sem pergunta).", "info", 9000);
  }
  // Integrações → Perplexity: o campo diz o que sai; os botões usam o mesmo caminho do Cérebro
  const pxForm = document.getElementById("px-form");
  if (pxForm) {
    const pxQ = document.getElementById("px-q");
    setBadge(document.getElementById("px-status"), perplexityInPanel()
      ? ["ok", "check", "Abre num painel dentro do Lúmen, com perfil próprio. O login fica nele entre as aberturas."]
      : ["warn", "alert", "Fora do Lumen.exe atual: o Perplexity abre no navegador padrão."]);
    setBadge(document.getElementById("px-badge"), perplexityInPanel() ? ["", "check", "Site oficial"] : ["warn", "external", "No navegador"]);
    pxForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = pxQ.value.trim();
      if (!q) { toast("Escreva a pergunta que vai ao Perplexity.", "info"); pxQ.focus(); return; }
      perplexityGo(q);
    });
    pxQ.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); pxForm.requestSubmit(); } });
    document.getElementById("px-home").addEventListener("click", () => perplexityGo(""));
    document.getElementById("px-paste").addEventListener("click", () => { showView("study"); setTab("chat"); perplexityPaste(); });
  }
  async function perplexityPaste() {
    const v = await dialog({ title: "Trazer resposta do Perplexity", ok: "Pôr na mensagem", wide: true,
      message: "No Perplexity, clique em Copiar na resposta (as fontes e os links vêm juntos) e cole aqui. O texto entra na caixa de mensagem marcado como conteúdo do Perplexity colado por você, não verificado pelo Lúmen. Nada é enviado até você mandar.",
      fields: [{ name: "text", label: "Resposta copiada do Perplexity", type: "textarea", rows: 12, placeholder: "Cole aqui (Ctrl+V)" }] });
    const t = v?.text.trim();
    if (!t) return;
    const block = PPLX_LABEL + "\n\n" + t, before = input.value.trim();
    if ((before ? before.length + 2 : 0) + block.length > PPLX_MAX) {  // longa demais para a mensagem: anexo de texto, inteiro
      const name = `perplexity-${new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-")}.md`;
      await attach([new File([block], name, { type: "text/markdown" })]);
      toast(`A resposta é longa: entrou inteira como o anexo ${name}, marcada como conteúdo do Perplexity.`, "info", 9000);
    } else { input.value = before ? before + "\n\n" + block : block; autosize(); }
    input.focus();
  }

  // --- Contexto: medidor, /context, /compact e /clear ------------------------------------------------------------
  function renderMeter() {
    const c = S.ctx;
    ctxBtn.hidden = !c;
    if (!c) return;
    const pct = Math.round(100 * c.used / c.limit);
    const fill = h("span");
    fill.style.width = Math.min(100, pct) + "%";  // CSSOM: a CSP não deixa atributo style
    ctxBtn.replaceChildren(h("span", { class: "st-ctx-bar", "aria-hidden": "true" }, fill),
      h("span", { text: `${c.estimated ? "≈ " : ""}${mil(c.used)} / ${mil(c.limit, true)}` }));
    ctxBtn.classList.toggle("warn", pct >= 80);
    ctxBtn.setAttribute("aria-label", `Contexto: ${mil(c.used)} de ${mil(c.limit, true)} tokens (${pct}%)${c.estimated ? ", estimado" : ""}. Abrir detalhes`);
    ctxBtn.dataset.tip = "Contexto da IA nesta conversa (/context)";
  }
  async function contextPanel() {
    if (S.conv?.id && !S.ctx) S.ctx = await guard(() => api("/api/study/context" + qs({ id: S.conv.id })));
    const c = S.ctx, sum = S.conv?.summary;
    const rows = c ? PARTS.filter(([k]) => c.parts?.[k]).map(([k, label]) => h("div", {}, h("dt", { text: label }), h("dd", { text: "≈ " + mil(c.parts[k]) }))) : [];
    const upto = S.conv?.summary_upto || 0;  // as duas últimas trocas nunca entram no resumo
    const canCompact = !!S.conv?.id && (S.conv.messages || []).filter((m) => Number(String(m.id).replace(/^t/, "")) > upto).length > 4;
    menu(ctxBtn.hidden ? modeBtn : ctxBtn, h("div", { class: "st-info st-ctx-panel" },
      h("p", { class: "eyebrow", text: "Contexto desta conversa" }),
      c ? h("p", { class: "st-ctx-total", text: `${c.estimated ? "≈ " : ""}${mil(c.used)} de ${mil(c.limit, true)} tokens (${Math.round(100 * c.used / c.limit)}%)` }) : h("p", { class: "faint", text: "Nada medido ainda: envie uma pergunta." }),
      c ? h("p", { class: "faint", text: c.estimated ? "Estimado depois da compactação; a próxima resposta mede de novo." : "Medido pela IA na última resposta. As partes são aproximadas." }) : null,
      rows.length ? h("dl", {}, rows) : null,
      sum ? h("p", { class: "faint", text: `O resumo cobre ${sum.covered} mensagem(ns) antiga(s)${sum.focus ? `, com foco em “${sum.focus}”` : ""}.` }) : null,
      h("p", { class: "faint", text: "Compactar resume as mensagens antigas para a IA. Nenhuma é apagada; as duas últimas trocas e as fixadas vão sempre inteiras." }),
      canCompact ? btn("Compactar agora", () => { closeMenu(); compactNow(""); }, { icon: "minus", cls: "btn sm" }) : null));
  }
  async function compactNow(focus) {
    if (!S.conv?.id) { toast("Ainda não há conversa para compactar.", "info"); return; }
    if (S.stream) { toast("Espere a resposta terminar.", "info"); return; }
    statusLine.hidden = false; statusLine.replaceChildren(h("span", { class: "st-pulse", "aria-hidden": "true" }), h("span", { class: "st-stage-text", text: STAGES.compacting() }));
    const r = await guard(() => api("/api/study/conversations", { action: "compact", id: S.conv.id, focus }));
    statusLine.hidden = true;
    if (!r) return;
    S.conv.summary = r.summary; S.conv.summary_upto = r.upto; S.ctx = r.context;
    renderMeter(); markSummary();
    toast(`Conversa compactada: ${r.covered} mensagem(ns) antiga(s) viraram um resumo para a IA. Nada foi apagado.`, "success");
  }
  // Linha na conversa depois da última mensagem resumida: o que está acima vai para a IA como resumo
  function markSummary() {
    thread.querySelector(".st-summary-mark")?.remove();
    const upto = S.conv?.summary_upto;
    const last = upto && [...thread.querySelectorAll(".st-msg")].filter((el) => Number(String(el.dataset.id).replace(/^t/, "")) <= upto).pop();
    if (last) last.after(h("div", { class: "st-summary-mark", role: "note" }, h("span", { text: "Acima: resumido para a IA · as mensagens continuam salvas" })));
  }
  function clearConversation() {
    const prev = S.conv?.id ? { id: S.conv.id, temporary: S.conv.temporary, project_id: S.conv.project_id || null } : null;
    newConversation();
    if (prev?.project_id) S.conv.project_id = prev.project_id;  // a conversa nova fica no mesmo projeto
    if (prev) toast(prev.temporary ? "Conversa nova. A temporária anterior não entra no histórico." : "Conversa nova. A anterior continua no histórico.",
      "info", 0, ["Desfazer", () => openConversation(prev.id)]);
  }
  function autosize() {
    input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 240) + "px";
    composer.classList.toggle("has-text", !!input.value.trim());
  }

  function renderHero() {
    const on = (!S.conv || !S.conv.messages?.length) && !S.results;
    hero.hidden = heroMore.hidden = !on;
    main.classList.toggle("is-empty", on);
    if (!on) return;
    // "Retomar" repete o histórico: só aparece quando ele está fechado
    const recent = S.side ? [] : S.convs.filter((c) => c.first && !c.temporary).slice(0, 3);
    put(hero, h("h2", { class: "st-hero-title", text: "O que vamos aprender hoje?" }),
      S.temporary ? h("p", { class: "st-temp-note" }, ic("timer"), "Conversa temporária: não entra no histórico, não cria memórias e some quando você fechar o Lúmen (ou em 24 h).") : null);
    put(heroMore, h("div", { class: "st-suggestions", role: "list" }, SUGGESTIONS.map(([icon, label, mode, prefix]) =>
      h("button", { type: "button", class: "st-chip", role: "listitem", onclick: () => { setMode(["flashcards", "quiz"].includes(mode) ? "auto" : mode); input.value = prefix; input.focus(); autosize(); S.forced = ["flashcards", "quiz"].includes(mode) ? mode : null; } }, ic(icon), h("span", { text: label })))),
      recent.length ? h("div", { class: "st-recent" }, h("p", { class: "eyebrow", text: "Retomar" }),
        recent.map((c) => h("button", { type: "button", class: "st-recent-item", onclick: () => openConversation(c.id) }, ic("clock"), h("span", { text: c.title || c.first })))) : null);
  }

  function newConversation() {
    stopStream();
    S.conv = { id: null, messages: [], temporary: S.temporary }; S.sources = []; S.related = []; S.memories = []; S.results = null; S.ctx = null;
    S.profile = ""; S.profileUsed = null;
    S.decided = null;
    watchElsewhere(null);
    thread.replaceChildren(); convTitle.textContent = ""; renderAside(); renderHero(); renderMeter(); renderChip(); input.focus();
    for (const el of convList.querySelectorAll(".st-conv.active")) el.classList.remove("active");
    if (narrow.matches && S.side) showSide(false);
  }
  async function openConversation(id) {
    stopStream();
    const conv = await guard(() => api("/api/study/conversation" + qs({ id })));
    if (!conv) return;
    S.conv = conv; S.results = null;
    const lastA = [...conv.messages].reverse().find((m) => m.role === "assistant");
    S.sources = lastA?.sources || []; S.related = []; S.memories = [];
    convTitle.textContent = conv.title || "";
    thread.replaceChildren(...conv.messages.map((m) => messageView(m)));
    for (const p of conv.pending || []) thread.append(pendingCard(p));
    for (const a of conv.created || []) thread.append(createdCard(a));
    S.ctx = lastA?.meta?.context || null;
    S.decided = lastA?.meta?.mode ? { mode: lastA.meta.mode, effort: lastA.meta.effort || "equilibrado", reason: lastA.meta.reason || "", auto: lastA.meta.auto || {} } : null;
    S.profile = lastA?.meta?.profile?.by === "manual" ? lastA.meta.profile.used : "";  // a escolha manual acompanha a conversa
    S.profileUsed = lastA?.meta?.profile?.used || null;
    if (narrow.matches && S.side) showSide(false);
    renderAside(); renderHero(); renderConvList(); renderMeter(); markSummary(); renderChip();
    thread.lastElementChild?.scrollIntoView({ block: "end" });
    watchElsewhere(conv);
  }
  // Uma resposta sendo escrita em OUTRA janela (a Conversa rápida da barra flutuante): esta janela espera, diz isso e relê no fim.
  // O servidor aceita uma geração por conversa de cada vez; por isso o envio fica desligado enquanto a outra termina.
  let elsewhereTimer = 0;
  function watchElsewhere(conv) {
    clearTimeout(elsewhereTimer);
    const on = !!conv?.generating && !S.stream;
    sendBtn.disabled = on;
    if (!on) { if (statusLine.dataset.elsewhere) { statusLine.hidden = true; delete statusLine.dataset.elsewhere; } return; }
    statusLine.hidden = false; statusLine.dataset.elsewhere = "1";
    statusLine.replaceChildren(h("span", { class: "st-pulse", "aria-hidden": "true" }), h("span", { class: "st-stage-text", text: "Esta conversa está respondendo na barra flutuante…" }));
    const id = conv.id;
    const tick = async () => {
      if (S.conv?.id !== id || S.stream) return watchElsewhere(null);
      try {
        const b = await api("/api/study/conversation" + qs({ id, brief: 1 }));
        if (!b.generating) { await openConversation(id); return; }
      } catch { /* apagada ou servidor ocupado: a próxima volta confere de novo */ }
      elsewhereTimer = setTimeout(tick, 1500);
    };
    elsewhereTimer = setTimeout(tick, 1200);
  }
  // A barra flutuante pede "Abrir no Cérebro": a MESMA conversa (mesmo id; nada é copiado nem reenviado). Uma resposta em
  // andamento aqui, de outra conversa, não é cancelada por isso: o pedido espera o estudante decidir.
  async function openFromHost(id) {
    if (!/^(tmp-)?[\w-]{1,64}$/.test(String(id || ""))) return false;
    setTab("chat");
    if (S.stream && S.conv?.id !== id) { toast("Há uma resposta sendo escrita aqui. Espere terminar ou interrompa antes de abrir a outra conversa.", "warning"); return false; }
    if (S.stream) return true;
    await openConversation(id);
    return true;
  }

  function citeButton(sid, sources) {
    const s = sources.find((x) => x.sid === sid);
    return h("button", { type: "button", class: "st-cite" + (s ? "" : " missing"), dataset: { sid }, "aria-label": s ? `Fonte ${sid}: ${s.title}` : `Fonte ${sid}`,
      "data-tip": s ? `${s.title} · ${LABEL[s.source] || s.source}` : "", onclick: () => focusSource(sid, sources) }, sid.slice(1));
  }
  // Fichas dos anexos e o aviso do /tela acima da pergunta. Anexo de conversa salva: "Adicionar ao índice" no clique.
  function sentFiles(m) {
    const files = m.meta?.attachments || [];
    if (!files.length && !m.meta?.screen) return null;
    return h("div", { class: "st-sent-files" },
      m.meta?.screen ? h("span", { class: "st-attach-chip ready screen", "data-tip": "A IA viu a janela que você usava; a imagem não foi guardada" }, ic("screen"), h("span", { class: "st-attach-name", text: "Tela vista nesta pergunta" })) : null,
      files.map((f) => h("button", { type: "button", class: "st-attach-chip ready", "aria-label": `Anexo ${f.name}: opções`, "data-tip": "Anexo desta conversa (apagado junto com ela)",
        onclick: (e) => S.conv?.temporary ? toast("Conversa temporária: o anexo some com ela e não entra no índice.", "info") : menu(e.currentTarget, [
          ["Adicionar ao índice", "plus", () => guard(() => api("/api/study/attachment", { action: "index", id: f.id }), `“${f.name}” entrou no índice: as próximas conversas também vão encontrá-lo.`)],
        ]) }, ic(KIND_ICON[f.kind] || "file"), h("span", { class: "st-attach-name", text: f.name }))));
  }
  function messageView(m) {
    if (m.role === "user") return h("div", { class: "st-msg user" + (m.pinned ? " pinned" : ""), dataset: { id: m.id } }, sentFiles(m), h("div", { class: "st-bubble", text: m.content }));
    const sources = m.sources || [];
    return h("article", { class: "st-msg bot" + (m.pinned ? " pinned" : ""), dataset: { id: m.id } },
      h("div", { class: "st-answer" }, md(m.content, { cite: (sid) => citeButton(sid, sources) }),
        m.meta?.interrupted ? h("span", { class: "badge st-call-cut", text: "interrompida", "data-tip": "Na chamada de voz: aqui fica só o trecho que foi falado" }) : null,
        m.meta?.generated ? h("details", { class: "st-generated" }, h("summary", { text: "Ver o que a IA já tinha escrito (não foi falado)" }), h("div", { class: "st-answer", text: m.meta.generated })) : null,
        m.meta?.free_mode ? h("span", { class: "st-free-badge", text: "✨ Modo Livre" }) : null),
      m.meta?.item_card ? callItemBlock(m.meta.item_card) : null,
      m.meta?.feynman ? feynmanSummaryCard(m.meta.feynman) : null,
      explainBlock(m),
      artifactBlock(m),
      m.meta?.mode === "explain" ? h("div", { class: "st-explain-more", role: "group", "aria-label": "Continuar a explicação" },
        EXPLAIN_MORE.map(([label, text]) => btn(label, () => ask(text), { cls: "btn sm ghost" })),
        btn("Gerar PDF", () => printExplanation(m), { icon: "page", cls: "btn sm ghost" })) : null,
      answerFooter(m));
  }
  async function printExplanation(m) {
    if (S.stream) return toast("Espere a resposta atual terminar.", "info");
    const draft = input.value;
    input.value = "/pdf explicacao " + (m.meta?.explain?.topic || S.conv?.title || "Explicação");
    S.pdfMessage = m.id;
    try { await submit(); } finally { S.pdfMessage = null; input.value = draft; autosize(); }
  }
  function artifactBlock(m) {
    const a = m.meta?.artifact;
    if (!a) return null;
    if (a.kind === "holo") return holoBlock(a);
    const url = `/api/study/artifact/file?id=${encodeURIComponent(a.id)}&t=${encodeURIComponent(TOKEN)}`;
    const video = a.kind === "video", image = a.kind === "image";
    return h("section", { class: "st-artifact", "aria-label": video ? "Vídeo gerado" : image ? "Imagem gerada" : "PDF gerado" },
      image ? h("img", { src: url, alt: a.name, loading: "lazy" })
        : video ? h("video", { src: url, controls: true, preload: "metadata", "aria-label": a.name })
          : h("p", { text: a.name }),
      h("p", { class: "muted t-sm", text: video ? "Vídeo gerado por IA; pode conter erros. O arquivo fica neste computador."
        : image ? "Gerada por IA, pode conter erros. Ilustração; não é fonte." : `${m.meta.pages || ""} página(s) · A4 · texto selecionável` }),
      h("div", { class: "st-explain-more" }, h("a", { class: "btn sm", href: url, download: a.name,
        text: "Baixar " + (video ? "vídeo" : image ? "imagem" : "PDF") }),
        !video && !S.conv?.temporary ? btn("Salvar no Obsidian…", () => prepareSave("obsidian", { artifact_id: a.id }, a.name), { cls: "btn sm ghost" }) : null,
        !video && !S.conv?.temporary ? btn("Salvar no Notion…", () => prepareSave("notion", { artifact_id: a.id }, a.name), { cls: "btn sm ghost" }) : null));
  }
  // Holograma 3D (/elegrama 3d): a animação (GIF) com o PNG de reserva. Quem pediu menos movimento (prefers-reduced-motion) vê o
  // PNG parado e inicia a animação pelo botão; o mesmo botão para a animação de quem não pediu. Sem animação (a geração caiu
  // para o PNG), não há botão de reproduzir e a legenda diz que é imagem estática.
  function holoBlock(a) {
    const base = `/api/study/artifact/file?id=${encodeURIComponent(a.id)}&t=${encodeURIComponent(TOKEN)}`;
    const poster = a.poster ? base + "&variant=poster" : base;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let playing = !!a.animated && !still?.matches;
    const img = h("img", { src: playing ? base : poster, alt: a.alt || a.name, width: String(a.width || 960), height: String(a.height || 540), decoding: "async" });
    const frame = h("div", { class: "st-holo-frame" }, img);
    const play = a.animated ? btn("", () => { playing = !playing; sync(); }, { attrs: { "aria-pressed": String(playing) } }) : null;
    const zoom = btn("Ampliar", () => {
      const on = frame.classList.toggle("zoom");
      zoom.querySelector("span").textContent = on ? "Ajustar à largura" : "Ampliar";
      zoom.setAttribute("aria-pressed", String(on));
      frame.tabIndex = on ? 0 : -1;
    }, { attrs: { "aria-pressed": "false", "data-tip": "Mostra a imagem em tamanho original, com rolagem dentro do cartão" } });
    function sync() {
      img.src = playing ? base : poster;
      if (play) { play.replaceChildren(h("span", { text: playing ? "Pausar animação" : "Reproduzir animação" })); play.setAttribute("aria-pressed", String(playing)); }
    }
    sync();
    const seconds = a.duration_ms ? ` · ${(a.duration_ms / 1000).toFixed(a.duration_ms % 1000 ? 1 : 0)} s` : "";
    const kind = a.animated ? `Animação (GIF) · ${a.width}×${a.height}${seconds} · ${a.frames} quadros`
      : `Imagem estática (PNG) · ${a.width}×${a.height}`;
    const stem = String(a.name || "holograma").replace(/\.(gif|png)$/i, "");
    return h("section", { class: "st-artifact st-holo", "aria-label": "Visualização 3D gerada" },
      h("figure", {}, frame,
        h("figcaption", { class: "muted t-sm" }, `${kind} · representação esquemática gerada pelo Lumen.`,
          a.state === "static-fallback" ? h("span", { class: "st-holo-note", text: " A animação não coube no limite; esta é a alternativa estática." }) : null)),
      h("div", { class: "st-explain-more" }, play, zoom,
        a.animated ? h("a", { class: "btn sm", href: base, download: a.name, text: "Baixar animação (GIF)" }) : null,
        h("a", { class: "btn sm" + (a.animated ? " ghost" : ""), href: poster, download: stem + ".png", text: "Baixar PNG" }),
        !S.conv?.temporary ? btn("Salvar no Obsidian…", () => prepareSave("obsidian", { artifact_id: a.id }, a.name), { cls: "btn sm ghost" }) : null,
        !S.conv?.temporary ? btn("Salvar no Notion…", () => prepareSave("notion", { artifact_id: a.id }, a.name), { cls: "btn sm ghost" }) : null));
  }
  // Pergunta nova no modo Explicar (botões da explicação, "Explicar esta parte" do diagrama, checagem errada)
  async function ask(text) {
    if (S.stream) return toast("Espere a resposta atual terminar.", "info");
    const draft = input.value;  // o rascunho volta depois (e o modo Explicar não fica preso se o envio não sair)
    input.value = text; S.forced = "explain";
    try { await submit(); } finally {
      S.forced = null;
      if (!input.value || input.value === text) { input.value = draft; autosize(); }
    }
  }
  // O que acompanha a explicação (explain.extras): diagrama, checagem, resumo, flashcards e a próxima revisão
  function explainBlock(m) {
    const ex = m.meta?.explain;
    if (!ex) return null;
    return h("div", { class: "st-explain" },
      ex.diagram && window.lumenStudy?.diagram ? window.lumenStudy.diagram(ex.diagram, { ask }) : null,
      ex.check ? checkCard(m, ex.check) : null,
      ex.summary?.length ? h("div", { class: "st-explain-summary" }, h("p", { class: "eyebrow", text: "Em 3 linhas" }), h("ol", { class: "st-list" }, ex.summary.map((t) => h("li", { text: t })))) : null,
      ex.deck ? h("p", { class: "st-explain-note" }, ic("copy"), h("span", { text: `${ex.deck.count} flashcard(s) no baralho de revisão espaçada.` }),
        btn("Revisar", async () => { const it = await guard(() => api("/api/study/item?id=" + encodeURIComponent(ex.deck.id))); if (it) { setTab("learn"); window.lumenStudy.openItem(it); } }, { cls: "btn sm ghost" })) : null,
      ex.next_review ? h("p", { class: "st-explain-note" }, ic("calendar"), h("span", { text: `Próxima revisão de “${ex.topic}” marcada para ${when(ex.next_review)}.` })) : null,
      ex.failed ? h("p", { class: "faint", text: `O diagrama e a checagem não saíram desta vez (${ex.failed}).` }) : null);
  }
  function checkCard(m, q) {
    const ta = h("textarea", { rows: 2, placeholder: "Responda com as suas palavras", "aria-label": "Sua resposta à checagem" });
    const fb = h("div", { class: "st-feedback", "aria-live": "polite" });
    const send = btn("Responder", async () => {
      const response = ta.value.trim();
      if (!response) return toast("Escreva a sua resposta.", "warning");
      send.disabled = true;
      const r = await guard(() => api("/api/study/check", { conversation_id: S.conv?.id, message_id: m.id, response }));
      send.disabled = false;
      if (!r) return;
      put(fb, h("p", { class: r.correct ? "st-ok" : "st-bad" }, ic(r.correct ? "check-circle" : "x-circle"), r.correct ? "Entendeu" : `Ainda não (nota ${Math.round((r.score || 0) * 100)}%)`),
        h("p", { text: r.feedback }), r.correct ? null : h("p", { class: "muted", text: "Resposta esperada: " + r.expected }));
      // errou: a IA explica de outro jeito, a partir do que ele respondeu
      if (!r.correct) ask(`Errei a checagem “${q.question}”. Respondi: “${response.slice(0, 400)}”. Explique de outro jeito, com outra analogia e outro exemplo, focando no que eu confundi.`);
    }, { cls: "btn sm primary" });
    return h("section", { class: "st-check", "aria-label": "Checagem rápida" }, h("p", { class: "eyebrow", text: "Checagem rápida" }),
      h("p", { class: "st-question", text: q.question }), ta, h("div", { class: "st-source-actions" }, send), fb);
  }
  async function pinMessage(m) {
    const r = await guard(() => api("/api/study/conversations", { action: "pin_message", id: S.conv.id, message_id: m.id, pinned: !m.pinned }),
      m.pinned ? "Mensagem desafixada: ela pode entrar no próximo resumo." : "Mensagem fixada: vai sempre inteira para a IA, mesmo depois de compactar.");
    if (r) { m.pinned = r.pinned; thread.querySelector(`.st-msg[data-id="${CSS.escape(String(m.id))}"]`)?.classList.toggle("pinned", r.pinned); }
  }
  // Abaixo da resposta: as fontes citadas (nome e origem; abrem o painel com o trecho e o link) e poucas ações à vista.
  // Aprofundar, avaliar e os detalhes técnicos (IA, modelo, citações) ficam em "Mais opções".
  function answerFooter(m) {
    const sources = m.sources || [], cited = sources.filter((s) => s.cited), shown = cited.slice(0, 3), persisted = typeof m.id === "number";
    const refs = sources.length ? h("div", { class: "st-refs", "aria-label": "Fontes desta resposta" },
      shown.map((s) => h("button", { type: "button", class: "st-ref", dataset: { source: s.source }, "data-tip": `${LABEL[s.source] || s.source} · abrir o trecho usado`, onclick: () => focusSource(s.sid, sources) },
        h("span", { class: "st-ref-n", text: s.sid.slice(1) }), ic(SRC_ICON[s.source] || "page"), h("span", { class: "st-ref-title", text: s.title }))),
      sources.length > shown.length ? h("button", { type: "button", class: "st-ref more", onclick: () => focusSource(null, sources),
        "data-tip": shown.length ? null : "A resposta não cita suas notas: o que ela afirma veio do conhecimento geral da IA" },
        shown.length ? `+${sources.length - shown.length}` : `${sources.length} ${sources.length === 1 ? "fonte consultada" : "fontes consultadas"}, nenhuma citada`) : null) : null;
    const copyBtn = btn("", () => copy(copyBtn, m.content), { icon: "copy", cls: "icon-btn sm", tip: "Copiar" });
    // Ouvir: a voz do uso "chat" (Configurações → Voz); de novo no mesmo botão, para
    // numa conversa temporária, a fala não fica no cache de frases (D59): a conversa promete ficar só na memória
    const hear = window.lumenVoice ? btn("", (e) => window.lumenVoice.speak(m.content, { use: "chat", button: e.currentTarget, temporary: !!(S.temporary || S.conv?.temporary),
      target: e.currentTarget.closest(".st-msg")?.querySelector(".st-answer") }), { icon: "volume", cls: "icon-btn sm st-hear", tip: "Ouvir" }) : null;
    hear?.setAttribute("aria-pressed", "false");
    return h("footer", { class: "st-answer-foot" }, refs,
      h("span", { class: "st-pin-badge" }, ic("pen"), "Fixada no contexto"),
      h("div", { class: "st-answer-actions" }, hear, copyBtn,
        !m.meta?.artifact && (persisted || /^t\d+$/.test(String(m.id))) ? btn("", () => regenerate(), { icon: "refresh", cls: "icon-btn sm", tip: "Gerar de novo" }) : null,
        persisted ? btn("", (e) => saveMenu(e.currentTarget, m), { icon: "download", cls: "icon-btn sm", tip: "Salvar" }) : null,
        btn("", (e) => moreMenu(e.currentTarget, m), { icon: "more", cls: "icon-btn sm", tip: "Mais opções" })));
  }
  function copy(b, text) {
    navigator.clipboard.writeText(text).then(() => {
      const label = (t) => { b.setAttribute("aria-label", t); b.dataset.tip = t; };
      window.ui.setIcon(b, "check"); b.classList.add("done"); label("Copiado");
      setTimeout(() => { window.ui.setIcon(b, "copy"); b.classList.remove("done"); label("Copiar"); }, 1600);
    }, () => toast("Não foi possível copiar.", "error"));
  }
  function moreMenu(anchor, m) {
    const persisted = typeof m.id === "number";
    const fb = (v) => async () => {
      let correction = "";
      if (v < 0) { const r = await dialog({ title: "O que não ficou bom?", message: "Opcional. A correção vira uma sugestão de memória para você aprovar; o modelo não é treinado.", fields: [{ name: "c", label: "Como deveria ser", type: "textarea", rows: 3 }], ok: "Enviar" }); if (r === null) return; correction = r.c; }
      const r = await guard(() => api("/api/study/feedback", { message_id: m.id, value: v, correction }), v > 0 ? "Obrigado! Avaliação registrada." : "Avaliação registrada.");
      if (r?.suggested) toast("A correção virou uma sugestão de memória (Configurações → Memória).", "info");
    };
    menu(anchor, [
      ["Aprofundar", "arrow-down", () => { input.value = "Aprofunde este assunto: vá além do que já foi dito, com exemplos e conexões."; submit(); }],
      persisted && ["Boa resposta", "check", fb(1)],
      persisted && ["Resposta ruim (corrigir)…", "x", fb(-1)],
      (persisted || /^t\d+$/.test(String(m.id))) && [m.pinned ? "Desafixar do contexto" : "Fixar no contexto", "pen", () => pinMessage(m)],
      ["Informações da resposta", "info", () => answerInfo(anchor, m)],
    ]);
  }
  function answerInfo(anchor, m) {
    const meta = m.meta || {}, sources = m.sources || [], cited = sources.filter((s) => s.cited).length;
    const rows = [
      ["Gerada por", ({ ollama: "IA local (Ollama)", anthropic: "Claude (Anthropic)", openai: "ChatGPT (OpenAI)", google: "Gemini (Google)" })[meta.provider] || "—"],
      ["Modelo", meta.model || "—"],
      meta.profile ? ["Perfil", `${PROFILE_LABEL[meta.profile.used] || "Principal"} (${({ manual: "escolha sua", setting: "pelo ajuste", auto: "automático", continuation: "continuação da conversa", regenerate: "mantido ao refazer", conservative: "mantido por cautela", unavailable: "classificador indisponível", guard: "principal por segurança", disabled: "perfil desligado" })[meta.profile.by] || meta.profile.by})`] : null,
      meta.free_mode ? ["Modo Livre", "Sim (sem consultar Notion ou Obsidian)"] : null,
      meta.effort ? ["Esforço", EFFORT_LABEL[meta.effort] + (meta.reviewed ? " (rascunho revisado)" : "")] : null,
      ["Fontes", sources.length ? `${cited} citada(s) de ${sources.length} consultada(s)` : "Nenhuma fonte usada"],
      meta.removed_citations ? ["Referências removidas", `${meta.removed_citations} sem fonte correspondente`] : null,
      meta.memories?.length ? ["Memórias usadas", String(meta.memories.length)] : null,
      meta.tools?.length ? ["Consultas extras", `${meta.tools.length} (busca, leitura ou link)`] : null,
      meta.material_cut ? ["Material", "parte ficou de fora pelo limite de contexto"] : null,
    ].filter(Boolean);
    menu(anchor, h("div", { class: "st-info" }, h("p", { class: "eyebrow", text: "Informações da resposta" }),
      h("dl", {}, rows.map(([k, v]) => h("div", {}, h("dt", { text: k }), h("dd", { text: v }))))));
  }
  function saveMenu(anchor, m) {
    const title = (S.conv?.title || "Estudo").slice(0, 80);
    const ref = m.meta?.artifact ? { artifact_id: m.meta.artifact.id } : { message_id: m.id };
    menu(anchor, [
      ["Salvar em Salvos", "library", async () => { const v = await dialog({ title: "Salvar resposta", fields: [{ name: "t", label: "Título", value: title }], ok: "Salvar" }); if (v) await guard(() => api("/api/study/items", { action: "save_answer", message_id: m.id, title: v.t }), "Resposta salva em Salvos."); }],
      ["Criar nota no Obsidian…", "obsidian", () => prepareSave("obsidian", ref, title)],
      ["Salvar no Notion…", "page", () => prepareSave("notion", ref, title)],
      ["Exportar Markdown", "download", () => download(`${title}.md`, m.content)],
    ]);
  }
  async function prepareSave(destination, ref, title) {
    const v = await dialog({ title: destination === "obsidian" ? "Criar nota no Obsidian" : "Salvar no Notion", fields: [{ name: "t", label: "Título", value: title }], ok: "Ver prévia" });
    if (!v) return;
    const action = await guard(() => api("/api/study/save", { destination, title: v.t, ...ref }));
    if (action) previewDialog(action);
  }
  async function previewDialog(action) {
    const card = pendingCard(action, true);
    const r = await dialog({ title: action.kind === "obsidian-note" ? "Prévia da nota no Obsidian" : "Prévia da página no Notion", body: card, ok: "Confirmar e salvar", wide: true });
    const ta = card.querySelector("textarea");
    if (r === null) { await guard(() => api("/api/study/pending", { id: action.id, decision: "cancel" })); return; }
    const done = await guard(() => api("/api/study/pending", { id: action.id, decision: "confirm", content: ta.value }));
    if (done) { toast(done.message || "Salvo.", "success"); thread.append(createdCard(done)); }
  }
  function pendingCard(a, inDialog = false) {
    const ta = h("textarea", { class: "st-preview-text", rows: 14, "aria-label": "Conteúdo que será gravado" });
    ta.value = a.content;
    const card = h("section", { class: "st-pending", "aria-label": "Gravação aguardando confirmação" },
      h("p", { class: "eyebrow", text: "Aguardando sua confirmação · nada foi gravado" }),
      h("p", { class: "st-pending-where" }, ic(a.kind === "obsidian-note" ? "obsidian" : "page"),
        a.kind === "obsidian-note" ? `Cofre “${a.vault}” › ${a.path}` : `Notion › ${a.container} › ${a.title}`),
      (a.warnings || []).map((w) => h("p", { class: "st-warn" }, ic("alert"), w)),
      a.duplicates?.length ? h("details", { class: "st-dups" }, h("summary", { text: `Notas com título parecido (${a.duplicates.length})` }),
        h("ul", {}, a.duplicates.map((d) => h("li", { text: `${d.title} · ${LABEL[d.source] || d.source}` })))) : null,
      ta);
    if (!inDialog) card.append(h("div", { class: "st-pending-actions" },
      btn("Confirmar e salvar", async () => { const r = await guard(() => api("/api/study/pending", { id: a.id, decision: "confirm", content: ta.value })); if (r) { toast(r.message || "Salvo.", "success"); card.replaceWith(createdCard(r)); } }, { icon: "check", cls: "btn primary sm" }),
      btn("Cancelar", async () => { await guard(() => api("/api/study/pending", { id: a.id, decision: "cancel" })); card.replaceWith(h("p", { class: "st-saved faint", text: "Gravação cancelada. Nada foi salvo." })); })));
    return card;
  }

  function createdCard(a) {
    const card = h("section", { class: "st-created", "data-action-id": a.id, "aria-label": "Criação do Lúmen" });
    if (a.status === "undone") { card.append(h("p", { text: `Criação desfeita: ${a.title || "nota"}.` })); return card; }
    card.append(h("p", {}, ic("check-circle"), h("span", { text: a.message || "Criação confirmada." })),
      h("div", { class: "st-pending-actions" },
        a.uri || a.url ? h("a", { class: "btn sm ghost", href: a.uri || a.url, target: "_blank", rel: "noopener noreferrer", text: "Abrir criação" }) : null,
        a.undo ? btn("Desfazer criação", async (e) => {
          const button = e.currentTarget; button.disabled = true;
          const r = await guard(() => api("/api/study/pending", { id: a.id, decision: "undo" }));
          if (r) { card.replaceWith(createdCard({ ...a, status: "undone" })); toast(r.message, "success"); }
          else button.disabled = false;
        }, { cls: "btn sm ghost", icon: "arrow-left" }) : null));
    return card;
  }

  let browserTimer = 0, browserCard = null, browserRun = "", browserReading = false;
  async function pollBrowser() {
    if (browserReading || !S.conv?.id) return;
    browserReading = true;
    try {
      const r = await api("/api/study/browser" + qs({ conversation: S.conv.id }));
      if (!r.id || (!r.active && browserRun !== r.id)) return;
      if (browserRun !== r.id || !browserCard?.isConnected) {
        browserRun = r.id;
        browserCard = h("section", { class: "st-browser", "aria-label": "Pesquisa guiada no Edge" });
        thread.append(browserCard);
      }
      const action = async (name) => { await guard(() => api("/api/study/browser", { id: r.id, action: name })); pollBrowser(); };
      put(browserCard, h("p", { class: "eyebrow", text: "Pesquisa guiada · Edge em modo de leitura" }),
        h("p", { role: "status", text: r.paused ? "Pesquisa pausada" : r.stage }),
        r.image ? h("img", { src: r.image, alt: "Página que o Lúmen está lendo", class: "st-browser-shot" }) : null,
        r.url ? h("p", { class: "faint st-browser-url", text: r.url }) : null,
        r.error ? h("p", { class: "st-warn", text: r.error }) : null,
        r.active ? h("div", { class: "st-pending-actions" },
          btn(r.paused ? "Retomar pesquisa" : "Pausar pesquisa", () => action(r.paused ? "resume" : "pause"), { cls: "btn sm" }),
          btn("Parar pesquisa", () => action("stop"), { cls: "btn sm ghost", icon: "stop" })) : null);
    } catch { /* o erro da pesquisa aparece no streaming; uma leitura de estado pode ser repetida */ }
    finally { browserReading = false; }
  }

  // Envio e streaming
  async function submit(regen = false) {
    if (S.stream) return;
    window.lumenVoice?.stop();  // outra mensagem: a fala da anterior para
    window.lumenStudy.callTyped?.();  // escrever durante a chamada: a fala da IA para (a resposta escrita segue no chat)
    if (!regen && S.staged.some((a) => a.status === "reading" || a.status === "uploading")) { toast("Espere o Lúmen terminar de ler os anexos.", "info"); return; }
    const files = regen ? [] : S.staged.filter((a) => a.status === "ready");
    if (!regen && !input.value.trim() && files.length) input.value = files.length > 1 ? "O que estes anexos trazem de importante para eu estudar?" : "O que este anexo traz de importante para eu estudar?";
    const text = input.value.trim();
    if (!regen && !text) { input.focus(); return; }
    let cmd = null;  // "/comando": os da tela rodam aqui; as skills seguem como pergunta com modo ou skill
    if (!regen && text.startsWith("/")) { closeSlash(); cmd = await command(text); if (!cmd) return; }
    if (S.mode === "search" && !regen && !cmd) return runSearch(text);
    if (S.results) { S.results = null; thread.replaceChildren(); }  // a conversa não começa debaixo de uma busca antiga
    const sent = cmd ? cmd.text : text;
    const body = { text: regen ? "" : sent, mode: cmd?.mode || S.forced || (S.mode === "auto" ? "" : S.mode), level: S.level, regenerate: regen,
      effort: S.effort, override: override(), ...(S.profile ? { profile: S.profile } : {}),
      skip_vault: !!S.skipVault, ...(S.vaultSources ? { vault_sources: S.vaultSources } : {}),
      ...(S.pdfMessage ? { pdf_message: S.pdfMessage } : {}),
      conversation_id: S.conv?.id || null, temporary: S.temporary,
      project_id: S.conv?.project_id || (S.project && S.project !== "none" ? S.project : null),
      ...(cmd?.skill ? { skill: cmd.skill } : {}), ...(cmd?.screen ? { screen: true } : {}),
      ...(cmd?.web ? { web: true } : {}), ...(cmd?.create_destination ? { create_destination: cmd.create_destination } : {}),
      ...(files.length ? { attachments: files.map((a) => a.id) } : {}) };
    S.forced = null;
    if (!regen) { input.value = ""; autosize(); }
    if (body.attachments) { S.staged = S.staged.filter((a) => !files.includes(a)); renderStaged(); }
    if (!S.conv) S.conv = { id: null, messages: [] };
    if (!regen) {
      const um = { role: "user", content: sent, id: "pending", meta: { ...(body.attachments ? { attachments: files.map(({ id, name, kind }) => ({ id, name, kind })) } : {}), ...(body.screen ? { screen: true } : {}) } };
      S.conv.messages.push(um); thread.append(messageView(um));
    }
    else thread.querySelector(".st-msg.bot:last-of-type")?.remove();
    renderHero();
    const turnId = (crypto.randomUUID?.() || String(Date.now()) + Math.random()).replace(/[^\w]/g, "").slice(0, 40);
    const ctrl = new AbortController();
    S.stream = { ctrl, turnId, text: "", node: null, sources: [], voice: !regen && !!S.voiceTurn };
    S.voiceTurn = false;
    // a resposta vai ser lida: a voz liga e o modelo carrega enquanto o texto ainda está sendo escrito (D54)
    if (S.stream.voice || S.state?.settings?.voice?.autoplay) window.lumenVoice?.warm("answer");
    setBusy(true);
    browserRun = "";
    browserTimer = setInterval(pollBrowser, 1200);
    let answer = null;
    try {
      const r = await fetch("/api/study/turn", { method: "POST", signal: ctrl.signal, headers: { "Content-Type": "application/json", "X-Lumen-Token": TOKEN }, body: JSON.stringify({ ...body, turn_id: turnId }) });
      if (!r.ok) { let v = {}; try { v = await r.json(); } catch { /* */ } throw new Error(v.error?.message || "Não foi possível falar com o Lumen."); }
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let k;
        while ((k = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, k); buf = buf.slice(k + 1); if (line.trim()) { const ev = JSON.parse(line); answer = handle(ev) || answer; } }
      }
    } catch (e) {
      if (e.name !== "AbortError") showError(e.message);
    } finally {
      clearInterval(browserTimer); browserTimer = 0;
      await pollBrowser();
      setBusy(false); S.stream = null; statusLine.hidden = true;
      if (S.conv?.id && !S.conv.temporary) loadConversations();
    }
    return answer;
  }
  function regenerate() { submit(true); }
  function stopStream() {
    if (!S.stream) return;
    S.stream.ctrl.abort();
    api("/api/study/cancel", { turn_id: S.stream.turnId }).catch(() => {});
  }
  function setBusy(on) {
    sendBtn.replaceChildren(ic(on ? "stop" : "arrow-up"));
    sendBtn.setAttribute("aria-label", on ? "Parar a resposta" : "Enviar");
    sendBtn.type = on ? "button" : "submit";
    sendBtn.onclick = on ? (e) => { e.preventDefault(); stopStream(); } : null;
    composer.classList.toggle("busy", on);
  }
  let paint = 0;
  function liveAnswer() {
    const st = S.stream;
    if (!st.node) {
      st.body = h("div", { class: "st-answer streaming" });
      st.node = h("article", { class: "st-msg bot" }, st.body);
      thread.append(st.node);
    }
    if (paint) return;
    paint = requestAnimationFrame(() => {
      paint = 0;
      if (!S.stream) return;
      st.body.replaceChildren(md(st.text, { cite: (sid) => citeButton(sid, st.sources) }));
      st.node.scrollIntoView({ block: "end" });
    });
  }
  function handle(ev) {
    const st = S.stream;
    switch (ev.type) {
      case "conversation":
        if (!S.conv.id) { S.conv.id = ev.conversation.id; S.conv.title = ev.conversation.title; S.conv.temporary = ev.conversation.temporary; S.conv.project_id = ev.conversation.project_id; }
        break;
      case "user": {
        const um = S.conv.messages.find((m) => m.id === "pending");
        if (um) um.id = ev.message.id;
        const node = thread.querySelector('.st-msg.user[data-id="pending"]');
        if (node) node.dataset.id = ev.message.id;
        break;
      }
      case "usage": S.ctx = { used: ev.used, limit: ev.limit, parts: ev.parts, estimated: ev.estimated }; renderMeter(); break;
      case "compacted":
        S.conv.summary_upto = ev.upto; S.conv.summary = { ...(S.conv.summary || {}), covered: ev.covered }; markSummary();
        toast("O contexto estava perto do limite: as mensagens antigas viraram um resumo para a IA. Nada foi apagado.", "info");
        break;
      case "compact_failed": toast(`Não deu para resumir as mensagens antigas (${ev.message}). A resposta segue com o histórico inteiro.`, "warning"); break;
      case "status": statusLine.hidden = false; statusLine.replaceChildren(h("span", { class: "st-pulse", "aria-hidden": "true" }), h("span", { class: "st-stage-text", text: (STAGES[ev.stage] || (() => "Trabalhando…"))(ev.detail || "") })); break;
      case "understanding": {
        const u = ev.understanding;
        if (u.source === "ai" && u.topic) statusLine.dataset.topic = u.topic;
        S.decided = { mode: u.mode, effort: u.effort, reason: u.reason || "", auto: u.auto || {} };
        renderChip();
        break;
      }
      case "profile": S.profileUsed = ev.used; renderChip(); break;
      case "sources": S.sources = ev.items; st.sources = ev.items; if (ev.related) S.related = ev.related; renderAside(ev.semantic); break;
      case "memories": S.memories = ev.items; renderAside(); break;
      case "screen": toast(`A IA viu a janela “${ev.window}”. A imagem não foi guardada.`, "info"); break;
      // "Mostrar a resposta enquanto é escrita" desligado: junta o texto e mostra tudo no fim (evento done)
      case "delta": st.text += ev.text; if (S.state?.settings?.models?.stream !== false) liveAnswer(); break;
      case "replace": st.text = ev.text; if (S.state?.settings?.models?.stream !== false) liveAnswer(); break;
      case "pending": thread.append(pendingCard(ev.action)); break;
      case "created": thread.append(createdCard(ev.action)); break;
      case "item": {
        const it = ev.item, L2 = window.lumenStudy;
        if (it.kind === "mindmap" && L2.diagram) thread.append(L2.diagram(it.data.diagram, { ask, actions: [
          btn("Salvar no Obsidian…", () => prepareSave("obsidian", { item_id: it.id }, it.title), { icon: "obsidian", cls: "btn sm ghost" }),
          btn("Salvar no Notion…", () => prepareSave("notion", { item_id: it.id }, it.title), { icon: "page", cls: "btn sm ghost" })] }));
        thread.append(L2.itemCard?.(it) || h("p", { text: it.title }));
        break;
      }
      case "done": {
        const msg = { role: "assistant", ...ev.message };
        S.conv.messages.push(msg); S.sources = msg.sources; renderAside();
        const view = messageView(msg);
        if (st.node) st.node.replaceWith(view); else thread.append(view);
        // ler sozinho: a leitura automática ligada, ou a pergunta foi falada (apertar para falar)
        if ((st.voice || S.state?.settings?.voice?.autoplay) && S.state?.settings?.voice?.engine !== "off") view.querySelector(".st-hear")?.click();
        if (msg.meta?.opened?.length) thread.append(h("div", { class: "st-open-row" }, msg.meta.opened.map((o) => btn(`Abrir “${o.title}”`, () => o.app ? guard(() => api("/api/study/open-app", { app: o.app })) : openDoc(o.id), { icon: "external", cls: "btn sm" }))));
        return msg;
      }
      case "error": showError([ev.message, ev.action].filter(Boolean).join(" ")); break;
      case "cancelled": thread.append(h("p", { class: "st-note faint", text: "Resposta interrompida." })); break;
    }
    return null;
  }
  function showError(text) {
    thread.append(h("div", { class: "st-error", role: "alert" }, ic("alert"), h("span", { text })));
    S.stream?.node?.remove();
  }

  // Busca sem IA (modo "Só buscar"): resultados editoriais
  async function runSearch(text, source = S.sourceFilter) {
    S.sourceFilter = source;
    statusLine.hidden = false; statusLine.replaceChildren(h("span", { class: "st-pulse", "aria-hidden": "true" }), h("span", { class: "st-stage-text", text: "Buscando no Notion e no Obsidian…" }));
    const r = await guard(() => api("/api/study/search" + qs({ q: text, source, project: S.project !== "none" ? S.project : "" })));
    statusLine.hidden = true;
    if (!r) return;
    S.results = { ...r, q: text };
    thread.replaceChildren(resultsView(S.results));
    renderHero();
  }
  function resultsView(r) {
    const filters = [["", "Todas"], ["notion", "Notion"], ["obsidian", "Obsidian"], ["files", "Arquivos"]];
    return h("section", { class: "st-results", "aria-label": "Resultados da busca" },
      h("div", { class: "st-results-head" },
        h("h2", { class: "t-h2", text: r.results.length ? `${r.results.length} resultado(s) para “${r.q}”` : `Nada encontrado para “${r.q}”` }),
        h("div", { class: "segmented sm", role: "group", "aria-label": "Filtrar por fonte" }, filters.map(([v, l]) =>
          h("button", { type: "button", "aria-pressed": String(S.sourceFilter === v), onclick: () => runSearch(r.q, v) }, l)))),
      h("p", { class: "faint st-results-how", text: r.semantic ? "Busca por palavras e por significado, combinadas." : "Busca por palavras (a busca por significado liga quando o modelo de embeddings estiver baixado)." }),
      r.results.length ? r.results.map((x) => resultCard(x, true)) :
        h("div", { class: "empty" }, h("p", { text: "Tente outras palavras, um sinônimo ou o nome do conceito em inglês. Confira também se as fontes estão sincronizadas em Fontes." })),
      r.related?.length ? h("div", { class: "st-related" }, h("p", { class: "eyebrow", text: "Conexões nas suas notas" }),
        r.related.map((x) => h("button", { type: "button", class: "st-related-item", onclick: () => openDoc(x.id) }, ic(SRC_ICON[x.source] || "page"), h("span", { text: x.title }), h("small", { class: "faint", text: x.reason })))) : null);
  }
  function resultCard(x, big = false) {
    const pct = x.relevance != null ? Math.round(x.relevance * 100) : null;
    const doc = x.id && !["anexo", "tela"].includes(x.source) && !String(x.id).startsWith("files:anexo:") ? x.id : "";  // anexo e tela não têm original para abrir
    const chunks = h("details", { class: "st-chunks" }, h("summary", { text: big ? "Ver trechos encontrados" : "Ver trecho usado" }),
      (x.chunks || []).map((c) => h("blockquote", { class: "st-chunk" }, c.heading ? h("p", { class: "st-chunk-head", text: c.heading }) : null, h("p", { text: (c.text || "").slice(0, 1200) }))));
    return h("article", { class: "st-result" + (big ? " big" : ""), dataset: { source: x.source, sid: x.sid || "" } },
      h("div", { class: "st-result-head" },
        x.sid ? h("span", { class: "st-sid", text: x.sid.slice(1) }) : null,
        h("span", { class: "st-src", dataset: { source: x.source } }, ic(SRC_ICON[x.source] || "page"), LABEL[x.source] || x.source),
        h("h3", { class: "st-result-title", text: x.title }),
        pct != null ? h("span", { class: "st-rel", "data-tip": "Relevância relativa nesta busca (calculada pela combinação de palavras e significado)", "aria-label": `Relevância ${pct}%` }, bar(pct), `${pct}%`) : null),
      h("p", { class: "st-result-meta faint", text: [x.path || x.url, x.updated ? "atualizado " + when(x.updated) : "", AUTHOR[x.author]].filter(Boolean).join(" · ") }),
      x.snippet ? h("p", { class: "st-snippet", text: x.snippet }) : null,
      x.images?.length ? h("div", { class: "st-thumbs" }, x.images.map((q) => img(q, "Imagem usada como fonte"))) : null,
      x.reasons?.length ? h("p", { class: "st-reasons" }, ic("info"), x.reasons.join(" · ")) : null,
      x.tags?.length ? h("p", { class: "st-tags" }, x.tags.map((t) => h("span", { class: "badge", text: "#" + t }))) : null,
      x.also_in?.length ? h("p", { class: "faint st-also", text: "Mesmo conteúdo também em: " + x.also_in.map((a) => `${a.title} (${LABEL[a.source]})`).join(", ") }) : null,
      x.same_subject?.length ? h("p", { class: "faint st-also", text: "Trata do mesmo assunto que: " + x.same_subject.map((a) => a.title).join(", ") }) : null,
      x.chunks?.length ? chunks : null,
      h("div", { class: "st-result-actions" },
        doc ? btn("Abrir original", () => openDoc(doc), { icon: "external", cls: "btn sm" }) : null,
        x.url && !x.id ? h("a", { class: "btn sm", href: x.url, target: "_blank", rel: "noopener noreferrer" }, ic("external"), "Abrir página") : null,
        big && doc ? btn("Perguntar sobre isto", () => { setMode("auto"); input.value = `Explique o que a nota “${x.title}” diz e como ela se conecta com meus outros estudos.`; S.results = null; thread.replaceChildren(); submit(); }, { icon: "sparkle", cls: "btn sm ghost" }) : null,
        S.project && S.project !== "none" && doc ? btn("Fixar no projeto", () => guard(() => api("/api/study/projects", { action: "pin", id: S.project, doc_id: doc }), "Fixado no projeto."), { icon: "pen", cls: "btn sm ghost" }) : null));
  }
  function bar(pct) {  // CSSOM, não atributo style: a CSP do app ('self') não permite estilo em linha
    const s = h("span", { class: "st-bar" });
    s.style.setProperty("--v", pct + "%");
    return s;
  }
  async function openDoc(id) { const r = await guard(() => api("/api/study/open", { id })); if (r?.notice) toast(r.notice, "success"); }

  // Painel de fontes: só existe quando há o que mostrar e fica fechado até o estudante pedir
  function renderAside() {
    const list = S.sources.filter((s) => S.filter === "all" || s.source === S.filter);
    const counts = {};
    for (const s of S.sources) counts[s.source] = (counts[s.source] || 0) + 1;
    const origins = Object.keys(counts);
    put(aside,
      h("div", { class: "st-aside-head" }, h("h2", { text: "Fontes" }), S.sources.length ? h("span", { class: "st-count", text: String(S.sources.length) }) : null,
        btn("", () => showAside(false), { icon: "x", cls: "icon-btn sm", tip: "Fechar fontes" })),
      origins.length > 1 ? h("div", { class: "segmented sm st-filter", role: "group", "aria-label": "Filtrar fontes" },
        [["all", "Todas"], ...origins.map((o) => [o, LABEL[o] || o])].map(([v, l]) =>
          h("button", { type: "button", "aria-pressed": String(S.filter === v), onclick: () => { S.filter = v; renderAside(); } }, l, v !== "all" ? h("span", { class: "count", text: counts[v] })  : null))) : null,
      list.map((s) => resultCard(s)),
      S.related?.length ? h("div", { class: "st-related" }, h("p", { class: "eyebrow", text: "Conexões" }),
        S.related.map((x) => h("button", { type: "button", class: "st-related-item", onclick: () => openDoc(x.id) }, ic(SRC_ICON[x.source] || "page"), h("span", { text: x.title }), h("small", { class: "faint", text: x.reason })))) : null,
      S.memories?.length ? h("div", { class: "st-memories" }, h("p", { class: "eyebrow", text: "Memórias usadas" }),
        S.memories.map((m) => h("p", { class: "st-memory" }, h("span", { class: "badge", text: m.category }), m.content)),
        btn("Gerenciar memórias", () => openSettings("memory"), { cls: "link-btn" })) : null);
    layout();
  }
  // Abre o painel nas fontes da resposta clicada (não só da última) e destaca a fonte citada
  function focusSource(sid, sources = S.sources) {
    if (sources !== S.sources) { S.sources = sources; S.related = []; S.memories = []; }
    S.filter = "all"; renderAside(); showAside(true);
    if (!sid) return aside.querySelector("button")?.focus();
    const card = aside.querySelector(`[data-sid="${sid}"]`);
    if (!card) return toast("Esta fonte não está mais disponível.", "warning");
    card.scrollIntoView({ block: "nearest" }); card.classList.add("flash");
    card.querySelector("details")?.setAttribute("open", "");
    setTimeout(() => card.classList.remove("flash"), 1600);
  }

  // --- Salvos -------------------------------------------------------------------------------------------------------
  const KIND = { answer: ["Resposta", "page"], flashcards: ["Flashcards", "copy"], quiz: ["Questionário", "question"], plan: ["Plano de estudos", "calendar"],
    map: ["Mapa de conhecimento", "graph"], mindmap: ["Mapa mental", "map"], gaps: ["O que falta estudar", "search"] };
  async function renderSaved() {
    const r = await guard(() => api("/api/study/items"));
    if (!r) return;
    panels.saved.replaceChildren(h("div", { class: "st-section-head" }, h("h2", { class: "t-h2", text: "Salvos" }),
      h("p", { class: "muted", text: "Respostas, resumos, flashcards, questionários, planos e mapas que você guardou." })));
    if (!r.items.length) { panels.saved.append(h("div", { class: "empty" }, ic("library", "empty-icon"), h("p", { text: "Nada salvo ainda. Use “Salvar” numa resposta, ou crie flashcards e planos em Estudar." }))); return; }
    panels.saved.append(h("div", { class: "st-saved-list" }, r.items.map((it) => {
      const [label, icon] = KIND[it.kind] || [it.kind, "page"];
      return h("article", { class: "st-saved-item" }, h("span", { class: "st-saved-icon" }, ic(icon)),
        h("div", { class: "st-saved-text" }, h("h3", { class: "t-h3", text: it.title }), h("p", { class: "faint", text: `${label} · ${when(it.updated)}` })),
        h("div", { class: "st-saved-actions" },
          btn("Abrir", async () => { const full = await guard(() => api("/api/study/item" + qs({ id: it.id }))); if (full) { setTab("learn"); window.lumenStudy.openItem?.(full); } }, { cls: "btn sm" }),
          btn("", (e) => menu(e.currentTarget, [
            ["Criar nota no Obsidian…", "obsidian", () => prepareSave("obsidian", { item_id: it.id }, it.title)],
            ["Salvar no Notion…", "page", () => prepareSave("notion", { item_id: it.id }, it.title)],
            ["Exportar Markdown", "download", async () => { const md2 = await guard(() => api("/api/study/item" + qs({ id: it.id, format: "md" }))); if (md2) download(md2.filename, md2.content); }],
            ["Apagar", "trash", async () => { if (await window.ui.confirm("O item salvo será apagado. Nada no Notion ou no Obsidian é tocado.", { title: "Apagar item?", ok: "Apagar", danger: true })) { await guard(() => api("/api/study/items", { action: "delete", id: it.id }), "Item apagado."); renderSaved(); } }, true],
          ]), { icon: "more", cls: "icon-btn sm", tip: "Mais ações" })));
    })));
  }

  // --- Fontes de conhecimento -----------------------------------------------------------------------------------
  const SOURCE_INFO = {
    notion: ["Notion", "page", "Conecte suas páginas, anotações e materiais de estudo.",
      ["Conecte o Notion em Integrações (token da integração interna, guardado no Gerenciador de Credenciais).",
        "No Notion, compartilhe as páginas de estudo com a integração: menu ••• da página → Conexões → escolha a integração do Lúmen.",
        "Volte aqui e clique em Sincronizar. O Lúmen lê só o que foi compartilhado; a busca da API do Notion vê títulos, então o conteúdo é indexado aqui no seu PC."]],
    obsidian: ["Obsidian", "obsidian", "Conecte seu cofre e explore sua base de conhecimento pessoal.",
      ["Escolha o cofre em Integrações → Obsidian (o mesmo que o Lúmen usa para as aulas).",
        "O Lúmen lê os arquivos Markdown direto do disco, só leitura: funciona com o Obsidian fechado, sem plugin, e nunca lê a pasta .obsidian.",
        "A cópia do Notion que a Proteção do cérebro cria no cofre fica de fora, para nada aparecer duas vezes."]],
  };
  function sourceState(s) {
    if (!s.connected) return ["Não conectado", "off"];
    if (S.state?.index?.running && S.state.index.source === s.key) return ["Sincronizando", "sync"];
    if (s.index.state === "syncing") return ["Sincronizando", "sync"];
    if (s.index.state === "error") return ["Erro de conexão", "err"];
    if (!s.enabled) return ["Conectado (fora da busca)", "idle"];
    if (!s.index.synced) return ["Conectado · falta sincronizar", "idle"];
    return [s.index.state === "partial" ? "Conectado · com avisos" : "Conectado", "ok"];
  }
  function renderSourcesTab() {
    const st = S.state;
    if (!st) return;
    const card = (key) => {
      const s = { ...st.sources[key], key }, [label, icon, desc, steps] = SOURCE_INFO[key], [stateText, tone] = sourceState(s), c = st.counts[key] || {};
      const prog = st.index.running && st.index.source === key && st.index.total ? h("progress", { max: st.index.total, value: st.index.done, "aria-label": "Progresso da sincronização" }) : null;
      return h("article", { class: "card st-source-card", dataset: { source: key, tone } },
        h("div", { class: "st-source-head" }, h("span", { class: "st-source-logo" }, ic(icon)), h("div", {}, h("h3", { class: "t-h3", text: label }), h("p", { class: "muted", text: desc })),
          h("span", { class: "st-state", dataset: { tone } }, h("span", { class: "dot" }), stateText)),
        h("dl", { class: "st-source-facts" },
          h("div", {}, h("dt", { text: "Documentos indexados" }), h("dd", { text: n(c.documents) })),
          h("div", {}, h("dt", { text: "Trechos com significado" }), h("dd", { text: c.chunks ? `${n(c.vectors)} de ${n(c.chunks)}` : "—" })),
          h("div", {}, h("dt", { text: "Última sincronização" }), h("dd", { text: s.index.synced ? when(s.index.synced) : "Nunca" }))),
        prog ? h("div", { class: "st-progress" }, prog, h("small", { class: "faint", text: `${n(st.index.done)} de ${n(st.index.total)} documentos lidos` })) : null,
        s.message && !s.connected ? h("p", { class: "field-error" }, ic("alert"), h("span", { text: s.message })) : null,
        s.index.message ? h("p", { class: s.index.state === "error" ? "field-error" : "faint" }, s.index.state === "error" ? ic("alert") : null, h("span", { text: s.index.message })) : null,
        !s.connected || !s.index.synced ? h("details", { class: "st-howto", open: !s.connected ? true : null }, h("summary", { text: "Como conectar" }), h("ol", {}, steps.map((t) => h("li", { text: t })))) : null,
        h("div", { class: "st-source-actions" },
          s.connected ? btn(s.index.synced ? "Sincronizar" : "Sincronizar agora", () => sourceAction(key, "sync"), { icon: "sync", cls: "btn primary sm" })
            : btn("Abrir Integrações", () => document.querySelector(`#nav-integrations`)?.click(), { icon: "plug", cls: "btn primary sm" }),
          s.connected ? btn("Testar conexão", () => sourceAction(key, "test"), { icon: "check", cls: "btn sm" }) : null,
          s.connected && s.enabled ? btn("Desconectar", () => disconnect(key, label), { icon: "x", cls: "btn sm ghost" }) : null));
    };
    const emb = st.providers.ollama, p = st.pull;
    const files = st.sources.files;
    panels.sources.replaceChildren(
      h("div", { class: "st-section-head" }, h("h2", { class: "t-h2", text: "Fontes de conhecimento" }),
        h("p", { class: "muted", text: "O Lúmen indexa suas fontes aqui no seu PC e pesquisa nelas por palavras e por significado. Nada é apagado nos originais." })),
      h("div", { class: "st-source-grid" }, card("notion"), card("obsidian")),
      h("article", { class: "card st-embed" },
        h("div", { class: "st-source-head" }, h("span", { class: "st-source-logo" }, ic("sparkle")),
          h("div", {}, h("h3", { class: "t-h3", text: "Busca por significado" }),
            h("p", { class: "muted", text: emb.embed_installed ? `Ativa com ${emb.embed}. Encontra notas pelo sentido, mesmo sem as mesmas palavras.` : `Precisa do modelo de embeddings ${emb.embed} no Ollama (roda no seu PC).` })),
          h("span", { class: "st-state", dataset: { tone: emb.embed_installed ? "ok" : "off" } }, h("span", { class: "dot" }), emb.embed_installed ? "Ativa" : "Desligada")),
        p.running ? h("div", { class: "st-progress" }, h("progress", { max: 1, value: p.progress, "aria-label": "Download do modelo" }), h("small", { class: "faint", text: `Baixando ${p.model}: ${Math.round(p.progress * 100)}%` })) : null,
        p.error ? h("p", { class: "field-error" }, ic("alert"), h("span", { text: p.error })) : null,
        !emb.embed_installed && !p.running ? h("div", { class: "st-source-actions" }, btn(`Baixar ${emb.embed}`, () => pullModel(emb.embed), { icon: "download", cls: "btn primary sm" }),
          !emb.running ? h("span", { class: "field-error" }, ic("alert"), h("span", { text: "O Ollama não está rodando." })) : null) : null,
        st.index.embedding?.total && st.index.phase === "embedding" ? h("small", { class: "faint", text: `Calculando significado: ${n(st.index.embedding.done)} de ${n(st.index.embedding.total)} trechos` }) : null),
      h("article", { class: "card st-folders" },
        h("div", { class: "st-source-head" }, h("span", { class: "st-source-logo" }, ic("folder")),
          h("div", {}, h("h3", { class: "t-h3", text: "Pastas autorizadas" }), h("p", { class: "muted", text: "Arquivos Markdown, texto, HTML, CSV e PDF de pastas que você autorizar. Só leitura." }))),
        (files.folders || []).length ? h("ul", { class: "st-folder-list" }, files.folders.map((f) => h("li", {}, ic("folder"), h("span", { text: f }),
          btn("", async () => { if (await window.ui.confirm("O Lúmen deixa de ler esta pasta e tira os arquivos dela do índice. Os arquivos continuam onde estão.", { title: "Remover pasta?", ok: "Remover" })) { S.state = await guard(() => api("/api/study/folders", { action: "remove", path: f })) || S.state; renderSourcesTab(); } }, { icon: "x", cls: "icon-btn sm", tip: "Remover pasta" })))) :
          h("p", { class: "faint", text: "Nenhuma pasta autorizada." }),
        h("div", { class: "st-source-actions" }, btn("Autorizar pasta…", async () => { const r = await guard(() => api("/api/study/folders", { action: "add" })); if (r && !r.cancelled) { S.state = r; renderSourcesTab(); sourceAction("files", "sync"); } }, { icon: "plus", cls: "btn sm" }),
          (files.folders || []).length ? btn("Sincronizar", () => sourceAction("files", "sync"), { icon: "sync", cls: "btn sm" }) : null)),
      h("article", { class: "card st-web" },
        h("div", { class: "st-source-head" }, h("span", { class: "st-source-logo" }, ic("external")),
          h("div", {}, h("h3", { class: "t-h3", text: "Internet" }), h("p", { class: "muted", text: "Ler páginas públicas funciona com a IA local. /web faz a pesquisa guiada no navegador (Edge); só a consulta vai ao buscador." })),
          h("label", { class: "st-switch" }, h("input", { type: "checkbox", role: "switch", ...(st.web_enabled ? { checked: true } : {}), onchange: async (e) => { await guard(() => api("/api/study/settings", { search: { web: e.target.checked } }), e.target.checked ? "Leitura da internet ligada." : "Leitura da internet desligada."); refreshState(); } }), h("span", { text: "Permitir" })))));
  }
  async function sourceAction(key, action) {
    if (action === "test") { const r = await guard(() => api("/api/study/sources", { action, source: key })); if (r) toast(r.result.message, r.result.connected ? "success" : "warning"); return; }
    const r = await guard(() => api("/api/study/sources", { action, source: key }), "Sincronização iniciada. Pode continuar usando o Lúmen.");
    if (r) { S.state = r; renderSourcesTab(); pollFast(); }
  }
  async function disconnect(key, label) {
    const v = await dialog({ title: `Desconectar ${label}?`, message: `${label} deixa de entrar nas buscas e respostas. A conexão em Integrações continua; nada é apagado no ${label}.`,
      fields: [{ name: "purge", label: "Índice local", type: "select", value: "keep", options: [["keep", "Manter o índice (reconectar é instantâneo)"], ["purge", "Apagar o índice, os trechos e os vetores desta fonte"]] }], ok: "Desconectar" });
    if (!v) return;
    S.state = await guard(() => api("/api/study/sources", { action: "disconnect", source: key, purge: v.purge === "purge" }), "Fonte desconectada.") || S.state;
    renderSourcesTab(); renderPills();
  }
  async function pullModel(model) {
    if (!(await window.ui.confirm(`O Ollama vai baixar ${model} (cerca de 640 MB) para o seu PC. A busca por significado liga quando terminar.`, { title: "Baixar modelo de embeddings?", ok: "Baixar" }))) return;
    await guard(() => api("/api/study/pull", { model }), "Download iniciado.");
    pollFast();
  }

  // --- Estado e cabeçalho --------------------------------------------------------------------------------------
  function renderPills() {
    const st = S.state;
    if (!st) return;
    const o = st.providers.ollama;
    const aiOk = o.running && o.installed;
    const aiText = !o.running ? "IA local parada" : !o.installed ? "Falta o modelo local" : "IA local pronta";
    const row = (el, tone, icon, title, detail, go) => {
      el.replaceChildren(h("span", { class: "dot", dataset: { tone } }), ic(icon), h("span", { class: "st-pill-text" }, h("span", { text: title }), detail ? h("small", { text: detail }) : null), ic("chevron-right", "st-pill-go"));
      el.onclick = () => { toggleStatus(false); go(); };
    };
    row(pills.ai, aiOk ? "ok" : "err", "cpu", aiText,
      `IA local (Ollama) · ${o.model || "modelo não escolhido"}`, () => openSettings("models"));
    const tones = [aiOk ? "ok" : "err"];
    for (const key of ["notion", "obsidian"]) {
      const s = { ...st.sources[key], key }, [text, tone] = sourceState(s), c = st.counts[key]?.documents || 0;
      row(pills[key], tone, key === "notion" ? "page" : "obsidian", `${LABEL[key]} · ${text}`, c ? `${n(c)} ${c === 1 ? "documento" : "documentos"} no índice` : "", () => setTab("sources"));
      tones.push(tone);
    }
    // Um único ponto no cabeçalho: o pior estado entre a IA e as fontes conectadas ("não conectado" não é problema)
    const worst = ["err", "sync", "idle"].find((t) => tones.includes(t)) || "ok";
    statusBtn.replaceChildren(h("span", { class: "dot", dataset: { tone: worst } }), h("span", { text: aiOk ? "IA local (Ollama)" : aiText }), ic("chevron-down"));
    statusBtn.setAttribute("aria-label", `Estado: ${aiText}. Abrir detalhes da IA e das fontes`);
    const due = tabs.querySelector(".st-due");
    if (due) due.textContent = st.due ? String(st.due) : "";
    // o nome da aba continua "Estudar" (o selo é só visual); a contagem vai como descrição, que o leitor de tela lê depois do nome
    due?.setAttribute("aria-hidden", "true");
    const learnTab = tabs.querySelector('[data-tab="learn"]');
    if (st.due) learnTab?.setAttribute("aria-description", `${st.due} ${st.due === 1 ? "cartão" : "cartões"} para revisar`); else learnTab?.removeAttribute("aria-description");
  }
  let stateTimer = 0, fastUntil = 0;
  async function refreshState() {
    clearTimeout(stateTimer);
    try {
      S.state = await api("/api/study/state");
      renderPills();
      if (S.tab === "sources" && settingsHost.hidden && !panels.sources.contains(document.activeElement)) renderSourcesTab();
    } catch { /* o cabeçalho mostra o último estado conhecido */ }
    finally {
      const busy = S.state?.index?.running || S.state?.pull?.running;
      if (root.closest(".view") && !root.closest(".view").hidden) stateTimer = setTimeout(refreshState, busy || Date.now() < fastUntil ? 1500 : 6000);
    }
  }
  function pollFast() { fastUntil = Date.now() + 20000; refreshState(); }

  let started = false;
  function show() {
    if (!started) { started = true; S.side = !narrow.matches && sideWanted; setMode("auto"); newConversation(); setTab("chat"); loadConversations(); }
    // com a leitura automática ligada, a voz fica pronta ao abrir os Estudos (D54; com pouca RAM, o servidor não aquece)
    Promise.resolve(refreshState()).then(() => { if (S.state?.settings?.voice?.autoplay) window.lumenVoice?.warm("open"); }).catch(() => {});
  }
  function callItemBlock(it) {
    const L2 = window.lumenStudy;
    return h("div", { class: "st-call-item-wrap" },
      it.kind === "mindmap" && it.data?.diagram && L2?.diagram ? L2.diagram(it.data.diagram, { ask, actions: [
        btn("Salvar no Obsidian…", () => prepareSave("obsidian", { item_id: it.id }, it.title), { icon: "obsidian", cls: "btn sm ghost" }),
        btn("Salvar no Notion…", () => prepareSave("notion", { item_id: it.id }, it.title), { icon: "page", cls: "btn sm ghost" })] }) : null,
      L2?.itemCard ? L2.itemCard(it) : h("p", { text: it.title }));
  }
  function feynmanSummaryCard(f) {
    return h("section", { class: "card st-call-feynman-card", "aria-label": `Avaliação Feynman de ${f.topic}` },
      h("div", { class: "st-mem-top" }, h("span", { class: "eyebrow", text: "Técnica de Feynman" }),
        h("span", { class: "badge", text: `${Math.round((f.score || 0) * 100)}%` })),
      h("p", { class: "t-h3", text: f.topic }),
      h("p", { text: f.feedback }),
      f.missing?.length ? h("p", { class: "muted t-sm", text: "Faltou mencionar: " + f.missing.map((x) => x.point).join(" · ") }) : null);
  }
  window.lumenStudy = { show, api, h, put, ic, btn, md, dialog, menu, guard, when, n, download, toast, S, LABEL, INTENT_LABEL, EFFORT_LABEL, SRC_ICON, openSettings, setTab, uploadAttachment,
    perplexityPaste, perplexityUrl, resultCard, prepareSave, refreshState, loadConversations, newConversation, openConversation, openFromHost, pendingCard, explainBlock, messageView, callItemBlock, feynmanSummaryCard, ask, mainEl: () => main, chatPanel: () => panels.chat, settingsHostEl: () => settingsHost, input: () => input, vault: vaultApi };
})();
