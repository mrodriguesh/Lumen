"use strict";
/* Lúmen Study AI — Estudar. Uma atividade por vez, em três níveis: Início → Objetivo (Revisar, Praticar, Planejar, Visualizar) →
   Atividade. Cada formulário é montado UMA vez, na primeira vez que é aberto, e fica guardado: trocar de objetivo, de atividade ou de
   aba (Conversar, Salvos…) não apaga rascunho, resultado nem sessão em andamento. Só a lista de materiais e a revisão pendente são
   buscadas de novo quando a aba é aberta. Usa as peças de window.lumenStudy (study.js) e não cria armazenamento novo. */
(() => {
  const L = window.lumenStudy;
  if (!L) return;
  const { h, put, ic, btn, api, guard, when, n, toast } = L;

  // Rótulos e ícones dos materiais salvos (também usados pelo cartão do chat). Os identificadores são os de sempre.
  const KINDS = [["flashcards", "Flashcards", "copy"], ["quiz", "Questionário", "question"], ["plan", "Plano de estudos", "calendar"],
    ["map", "Mapa de conhecimento", "graph"], ["mindmap", "Mapa mental", "map"], ["gaps", "O que falta estudar", "search"],
    ["audio", "Revisão em áudio", "volume"], ["exercise", "Prática com correção", "pen"], ["action", "Plano de ação", "folder"]];
  const LEVELS = [["", "Automático"], ["basico", "Básico"], ["intermediario", "Intermediário"], ["avancado", "Avançado"]];
  const SOURCES_HELP = "A IA busca no Notion e no Obsidian antes de criar, com a origem de cada item. O que não vier das suas notas aparece marcado como conhecimento geral.";
  const RECENT = 5, RECENT_MAX = 30;

  // O mapa das funções: onde cada uma mora. `kind` é o tipo salvo (identificador interno); sem `kind`, a função não salva material.
  const GROUPS = [
    { id: "review", title: "Revisar", icon: "timer", hint: "Fixe o que já estudou.", acts: ["today", "flashcards", "audio"] },
    { id: "practice", title: "Praticar", icon: "pen", hint: "Teste o que você sabe e receba correção.", acts: ["quiz", "exercise", "feynman", "speaking"] },
    { id: "plan", title: "Planejar", icon: "calendar", hint: "Organize o que estudar e como aplicar.", acts: ["plan", "action", "gaps"] },
    { id: "visual", title: "Visualizar", icon: "map", hint: "Veja o assunto em mapas.", acts: ["mindmap", "map"] },
  ];
  const ACTS = {
    today: { group: "review", title: "Revisão de hoje", icon: "timer", desc: "Cartões vencidos e revisões dos seus planos." },
    flashcards: { group: "review", kind: "flashcards", title: "Flashcards", icon: "copy", go: "Criar flashcards", example: "memória de longo prazo",
      desc: "Cartões de pergunta e resposta, revisados em intervalos que crescem." },
    audio: { group: "review", kind: "audio", title: "Revisão em áudio", icon: "volume", go: "Gerar a revisão", example: "memória de longo prazo",
      desc: "Perguntas e respostas de um assunto para ouvir, com capítulos." },
    quiz: { group: "practice", kind: "quiz", title: "Questionário", icon: "question", go: "Criar questionário", example: "memória de longo prazo",
      desc: "Perguntas de múltipla escolha a respostas abertas, corrigidas na hora." },
    exercise: { group: "practice", kind: "exercise", title: "Prática com correção", icon: "pen", go: "Criar prática", example: "keyframes no Premiere",
      desc: "Uma tarefa com critérios: você entrega um texto ou arquivo e recebe a correção por critério." },
    feynman: { group: "practice", title: "Explique com suas palavras", icon: "brain", desc: "Explique o assunto como se ensinasse alguém e veja o que faltou." },
    speaking: { group: "practice", title: "Treino falado", icon: "wave", desc: "Converse em voz com um personagem (venda, negociação, entrevista) e receba uma avaliação." },
    plan: { group: "plan", kind: "plan", title: "Plano de estudos", icon: "calendar", go: "Criar plano de estudos", example: "biologia celular",
      desc: "Etapas, pré-requisitos e revisões para aprender um assunto." },
    action: { group: "plan", kind: "action", title: "Plano de ação", icon: "folder", go: "Criar plano de ação", example: "curso de persuasão",
      desc: "Entregas e prazos para aplicar o que aprendeu no seu projeto." },
    gaps: { group: "plan", kind: "gaps", title: "O que falta estudar", icon: "search", go: "Ver o que falta", example: "memória de longo prazo",
      desc: "O que você já tem nas notas e o que ainda falta." },
    mindmap: { group: "visual", kind: "mindmap", title: "Mapa mental", icon: "map", go: "Criar mapa mental", example: "fotossíntese",
      desc: "O assunto em tópicos e ramos, do geral ao detalhe." },
    map: { group: "visual", kind: "map", title: "Mapa de conhecimento", icon: "graph", go: "Criar mapa de conhecimento", example: "memória de longo prazo",
      desc: "Os conceitos e como eles se ligam nas suas notas." },
  };
  const ACT_OF_KIND = Object.fromEntries(Object.entries(ACTS).filter(([, a]) => a.kind).map(([id, a]) => [a.kind, id]));
  const kindOf = (kind) => KINDS.find((k) => k[0] === kind) || [kind, "Material", "page"];

  let host = null, shell = null, uidN = 0, seq = 0, loading = null, again = false, pendingOpen = null;
  const state = { due: null, items: null, nav: { screen: "home", act: "", group: "" }, built: {}, backTo: {}, showAll: {}, sig: "" };
  const uid = (p) => `st-lrn-${p}-${++uidN}`;
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0;
  const projectId = () => (L.S.project && L.S.project !== "none" ? L.S.project : null);
  const srcChip = (s) => s ? h("span", { class: "st-src-chip", dataset: { source: s.source || "geral" } }, ic(L.SRC_ICON[s.source] || "sparkle"), s.title || "Conhecimento geral") : null;

  // --- Erros ligados ao campo (rótulo visível, aria-invalid e aria-describedby; nada de aviso solto longe do campo) ---------------
  function clearError(field) {
    if (!field) return;
    field.removeAttribute("aria-invalid");
    if (field.dataset.errId) { document.getElementById(field.dataset.errId)?.remove(); delete field.dataset.errId; }
    const base = field.dataset.describedBase || "";
    if (base) field.setAttribute("aria-describedby", base); else field.removeAttribute("aria-describedby");
  }
  function fieldError(field, message) {
    clearError(field);
    const id = uid("err"), base = field.getAttribute("aria-describedby") || "";
    field.dataset.describedBase = base;
    field.dataset.errId = id;
    const note = h("p", { class: "field-error", id, role: "alert" }, ic("alert"), h("span", { text: message }));
    (field.closest(".st-feynman-row") || field).insertAdjacentElement("afterend", note);   // fora da linha textarea + microfone
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("aria-describedby", [base, id].filter(Boolean).join(" "));
    field.addEventListener("input", () => clearError(field), { once: true });
    field.focus();
  }
  // Campo com rótulo visível ligado ao controle (for/id) e dica opcional como descrição; o controle pode estar numa linha com o microfone.
  function field(label, control, { hint, wrap } = {}) {
    const id = uid("f");
    control.id = id;
    const note = hint ? h("p", { class: "field-hint", id: id + "-hint", text: hint }) : null;
    if (note) control.setAttribute("aria-describedby", id + "-hint");
    return h("div", { class: "field" }, h("label", { for: id, text: label }), wrap || control, note);
  }

  // --- Casca: uma tela por vez --------------------------------------------------------------------------------------------
  function render(target) {
    if (host !== target || !shell) {
      host = target;
      shell = buildShell();
      put(host, shell.root);
      show("home", { focus: false });
      if (pendingOpen) { const it = pendingOpen; pendingOpen = null; open(it); }
    }
    refresh();
  }

  function buildShell() {
    const live = h("p", { class: "sr", role: "status", "aria-live": "polite" });   // anuncia "resultado aberto" sem ler o resultado inteiro
    const root = h("div", { class: "st-lrn" }, live);
    const home = h("div", { class: "st-lrn-screen", dataset: { screen: "home" } });
    const groups = Object.fromEntries(GROUPS.map((g) => [g.id, h("div", { class: "st-lrn-screen", hidden: true, dataset: { screen: "group", group: g.id } })]));
    const acts = h("div", { class: "st-lrn-acts" });
    root.append(home, ...Object.values(groups), acts);
    return { root, home, groups, acts, live };
  }

  function head(title, { back, hint, id }) {
    return h("header", { class: "st-lrn-head" },
      back ? h("button", { type: "button", class: "btn ghost sm st-lrn-back", "aria-label": `Voltar para ${back.label}`, onclick: back.go }, ic("arrow-left"), h("span", { text: back.label })) : null,
      h("h2", { class: "t-h2", id, tabindex: "-1", text: title }), hint ? h("p", { class: "muted st-lrn-hint", text: hint }) : null);
  }

  // Mostra UMA tela (início, objetivo ou atividade) e esconde as outras sem destruí-las.
  // `back`: veio de um "Voltar" — o foco volta ao botão que abriu a tela que acabou de fechar.
  const navKey = (screen, group, act) => screen === "home" ? "home" : screen === "group" ? `group:${group}` : `act:${act}`;
  function show(screen, { group = "", act = "", focus = true, back = false } = {}) {
    const prev = state.nav, prevKey = navKey(prev.screen, prev.group, prev.act);
    const leaving = prev.screen === "act" ? prev.act : "";
    if (leaving && leaving !== act) state.built[leaving]?.onHide?.();
    if (act) {
      ensureAct(act);
      // de onde veio: o "Voltar" da atividade leva de volta ao lugar de onde ela foi aberta (início ou objetivo)
      if (!back && prev.screen !== "act") state.backTo[act] = prev.screen === "group" && prev.group === ACTS[act]?.group ? "group" : prev.screen === "home" ? "home" : "group";
      setBackLabel(act);
    }
    state.nav = { screen, act: act || "", group: group || (act ? (ACTS[act]?.group || "") : "") };
    shell.home.hidden = screen !== "home";
    for (const [id, el] of Object.entries(shell.groups)) el.hidden = !(screen === "group" && id === group);
    for (const [id, a] of Object.entries(state.built)) a.el.hidden = !(screen === "act" && id === act);
    if (screen === "group") paintGroup(group);
    if (screen === "home") paintHome();
    if (screen === "act") state.built[act].onShow?.();
    if (!focus) return;
    const screenEl = screen === "home" ? shell.home : screen === "group" ? shell.groups[group] : state.built[act].el;
    const opener = back ? screenEl.querySelector(`[data-nav="${prevKey}"]`) : null;
    (opener && visible(opener) ? opener : screenEl.querySelector("h2"))?.focus();
  }
  const goHome = (back = true) => show("home", { back });
  const goGroup = (id, back = false) => show("group", { group: id, back });
  const goAct = (id, opts = {}) => show("act", { act: id, ...opts });
  // "Voltar" de uma atividade: ao início se ela foi aberta de lá (ou de um material recente), senão ao objetivo dela
  const backFrom = (id) => (state.backTo[id] === "home" || !ACTS[id]?.group ? goHome(true) : goGroup(ACTS[id].group, true));
  function setBackLabel(id) {
    const label = state.backTo[id] === "home" || !ACTS[id]?.group ? "Estudar" : GROUPS.find((g) => g.id === ACTS[id].group).title;
    const b = state.built[id]?.el.querySelector(".st-lrn-back");
    if (!b) return;
    b.setAttribute("aria-label", `Voltar para ${label}`);
    b.querySelector("span").textContent = label;
  }

  // --- Dados reais: revisão pendente e materiais --------------------------------------------------------------------------
  async function refresh() {
    if (loading) { again = true; return loading; }
    const my = ++seq;
    loading = (async () => {
      const [due, items] = await Promise.all([guard(() => api("/api/study/due?limit=1")), guard(() => api("/api/study/items"))]);
      if (my !== seq) return;
      if (due) state.due = due;
      if (items) state.items = items.items.filter((x) => x.kind !== "answer");
      repaint();
    })().finally(() => { loading = null; if (again) { again = false; refresh(); } });
    return loading;
  }
  function repaint() {
    const sig = JSON.stringify([state.due?.total, state.due?.topics, state.due?.plans, state.items?.map((i) => [i.id, i.updated, i.title])]);
    if (sig === state.sig) return;
    state.sig = sig;
    if (state.nav.screen === "home") paintHome();
    if (state.nav.screen === "group") paintGroup(state.nav.group);
    for (const a of Object.values(state.built)) a.paintPrev?.();
    state.built.today?.paint?.();
  }

  const dirtyOf = (id) => !!state.built[id]?.dirty?.();
  const busyOf = (id) => !!state.built[id]?.busy?.();
  const inProgress = () => ["today", "speaking"].filter(busyOf);

  // Assuntos que o modelo do estudante sugere rever (revisão marcada ou erros seguidos): cada um abre uma explicação no chat.
  function topicsBlock(topics, title = "Assuntos que vale rever") {
    if (!topics?.length) return null;
    return h("div", { class: "st-lrn-topics" }, h("p", { class: "faint", text: title }),
      h("div", { class: "st-chips" }, topics.map((t) => btn(t.label, () => { L.setTab("chat"); const box = L.input(); box.value = `Explique ${t.label}`; box.focus(); },
        { cls: "btn sm ghost", tip: t.level === "dificuldade" ? "Você vem errando este assunto" : "A revisão marcada chegou" }))));
  }

  // --- Início ---------------------------------------------------------------------------------------------------------------
  function paintHome() {
    const due = state.due, items = state.items;
    const mine = inProgress();
    const next = [];
    for (const id of mine) {
      next.push(h("div", { class: "st-lrn-next" }, h("span", { class: "st-lrn-ico" }, ic(ACTS[id].icon)),
        h("div", { class: "st-lrn-next-text" }, h("strong", { text: id === "speaking" ? "Treino falado em andamento" : "Revisão em andamento" }), h("p", { class: "muted", text: "Você parou no meio. Continue de onde estava." })),
        btn("Continuar", () => goAct(id), { icon: "arrow-right", cls: "btn primary" })));
    }
    if (due?.total && !mine.includes("today")) {   // com uma revisão em andamento, o cartão acima já leva a ela
      next.push(h("div", { class: "st-lrn-next" }, h("span", { class: "st-lrn-ico" }, ic("timer")),
        h("div", { class: "st-lrn-next-text" }, h("strong", { text: "Revisão de hoje" }),
          h("p", { class: "muted", text: `${n(due.total)} ${due.total === 1 ? "cartão" : "cartões"} para revisar agora.` }),
          due.plans?.length ? h("p", { class: "faint" }, `${due.plans.length} ${due.plans.length === 1 ? "revisão" : "revisões"} de plano também ${due.plans.length === 1 ? "vence" : "vencem"} hoje.`) : null),
        btn("Começar revisão", () => review(null, { act: "" }), { icon: "play", cls: "btn primary" })));
    } else if (!mine.length) {
      next.push(h("p", { class: "st-lrn-calm muted" }, ic("check-circle"), due?.plans?.length
        ? `Nenhum cartão para revisar agora. ${due.plans.length} ${due.plans.length === 1 ? "revisão de plano vence" : "revisões de plano vencem"} hoje.` : "Nenhuma revisão pendente agora."));
    }
    const rows = items ? (state.showAll.home ? items.slice(0, RECENT_MAX) : items.slice(0, RECENT)) : [];
    put(shell.home,
      head("Estudar", { hint: "Revise, pratique, planeje e visualize a partir das suas notas.", id: "st-lrn-h-home" }),
      h("section", { class: "st-lrn-sec", "aria-labelledby": "st-lrn-s-next" }, h("h3", { class: "eyebrow", id: "st-lrn-s-next", text: "Próxima atividade" }), ...next,
        due?.plans?.length ? btn("Ver as revisões dos planos", () => goAct("today"), { cls: "btn sm ghost" }) : null,
        topicsBlock(due?.topics?.slice(0, 4))),
      h("section", { class: "st-lrn-sec", "aria-labelledby": "st-lrn-s-goal" }, h("h3", { class: "eyebrow", id: "st-lrn-s-goal", text: "Escolha um objetivo" }),
        h("div", { class: "st-lrn-goals" }, GROUPS.map((g) => {
          const flag = g.acts.some(busyOf) ? "Em andamento" : g.acts.some(dirtyOf) ? "Rascunho" : "";
          return h("button", { type: "button", class: "st-lrn-goal", dataset: { nav: `group:${g.id}` }, onclick: () => goGroup(g.id) },
            h("span", { class: "st-lrn-goal-top" }, h("span", { class: "st-lrn-ico" }, ic(g.icon)), h("strong", { text: g.title }), flag ? h("span", { class: "badge", dataset: { tone: "busy" }, text: flag }) : null),
            h("span", { class: "st-lrn-goal-hint", text: g.hint }),
            h("span", { class: "st-lrn-goal-list faint", text: g.acts.map((a) => ACTS[a].title).join(" · ") }));
        }))),
      h("section", { class: "st-lrn-sec", "aria-labelledby": "st-lrn-s-recent" }, h("h3", { class: "eyebrow", id: "st-lrn-s-recent", text: "Materiais recentes" }),
        items === null ? h("p", { class: "faint", text: "Carregando…" }) : rows.length ? recentList(rows, "home", items.length)
          : h("p", { class: "st-lrn-calm muted" }, ic("sparkle"), "Nada criado ainda. Escolha um objetivo para começar.")));
  }

  // Lista compacta de materiais: poucos de início, o resto no mesmo lugar (sem outra tela).
  function recentList(rows, key, total, { kind = true } = {}) {
    const list = h("ul", { class: "st-learn-list" }, rows.map((it) => {
      const [, label, icon] = kindOf(it.kind);
      const lead = it.title.match(/^(.+?)\s*[·:]\s+(.+)$/);
      const title = lead && lead[1].toLowerCase() === label.toLowerCase() ? lead[2] : it.title;   // o tipo aparece uma vez só, na linha de baixo
      return h("li", {}, h("button", { type: "button", class: "st-learn-item", title: it.title, onclick: async () => { const full = await guard(() => api("/api/study/item?id=" + encodeURIComponent(it.id))); if (full) open(full); } },
        h("span", { class: "st-lrn-ico", "aria-hidden": "true" }, ic(icon)),
        h("span", { class: "st-learn-text" }, h("span", { class: "st-learn-title", text: kind ? title : it.title }), kind ? h("span", { class: "st-learn-kind", text: label }) : null),
        h("small", { class: "st-learn-when", text: when(it.updated) })));   // dentro da atividade, o tipo já está no título
    }));
    const more = total > RECENT ? btn(state.showAll[key] ? "Mostrar menos" : `Ver todos (${total > RECENT_MAX ? RECENT_MAX + "+" : total})`, (e) => {
      state.showAll[key] = !state.showAll[key];
      state.nav.screen === "home" ? paintHome() : state.built[state.nav.act]?.paintPrev?.();
      (shell.root.querySelector(`[data-more="${key}"]`) || e.currentTarget)?.focus?.();
    }, { cls: "btn sm ghost", attrs: { "aria-expanded": String(!!state.showAll[key]), "data-more": key } }) : null;
    return h("div", { class: "st-lrn-recent" }, list, more);
  }

  // --- Objetivo: as funções dele, uma linha cada --------------------------------------------------------------------------
  function paintGroup(id) {
    const g = GROUPS.find((x) => x.id === id), el = shell.groups[id];
    if (!g) return;
    put(el, head(g.title, { back: { label: "Estudar", go: () => goHome(true) }, hint: g.hint, id: `st-lrn-h-${id}` }),
      h("ul", { class: "st-lrn-rows" }, g.acts.map((aid) => {
        const a = ACTS[aid];
        const flag = busyOf(aid) ? "Em andamento" : dirtyOf(aid) ? "Rascunho" : "";
        return h("li", {}, h("button", { type: "button", class: "st-lrn-row", dataset: { nav: `act:${aid}` }, onclick: () => goAct(aid) },
          h("span", { class: "st-lrn-ico" }, ic(a.icon)),
          h("span", { class: "st-lrn-row-text" }, h("strong", { text: a.title }), h("span", { class: "muted", text: a.desc })),
          flag ? h("span", { class: "badge", dataset: { tone: "busy" }, text: flag }) : null, ic("chevron-right")));
      })));
  }

  // --- Atividade -------------------------------------------------------------------------------------------------------------
  function ensureAct(id) {
    if (state.built[id]) return state.built[id];
    const spec = ACTS[id] || { group: "", title: "Material salvo", icon: "page", desc: "" };
    const group = GROUPS.find((g) => g.id === spec.group);
    const body = id === "today" ? todayAct() : id === "feynman" ? feynmanAct() : id === "speaking" ? speakingAct() : id === "answer" ? answerAct() : createAct(id, spec);
    const back = { label: group ? group.title : "Estudar", go: () => backFrom(id) };
    const el = h("section", { class: "st-lrn-act", hidden: true, dataset: { act: id }, "aria-labelledby": `st-lrn-h-act-${id}` },
      head(spec.title, { back, hint: spec.desc, id: `st-lrn-h-act-${id}` }), body.el);
    shell.acts.append(el);
    return (state.built[id] = { ...body, el, id });
  }

  // Formulário de criação (flashcards, questionário, planos, mapas, lacunas, revisão em áudio, prática): um campo essencial, o resto recolhido.
  function createAct(id, a) {
    const topic = h("input", { type: "text", maxlength: "300", placeholder: `Ex.: ${a.example}` });
    const level = h("select", {}, LEVELS.map(([v, l]) => h("option", { value: v, text: l })));
    const application = id === "action" ? h("textarea", { rows: 3, maxlength: "2000", placeholder: "Ex.: preparar a aula de psicologia do semestre" }) : null;
    const view = h("div", { class: "st-learn-view" });
    const prev = h("section", { class: "st-lrn-prev", hidden: true });
    let gen = 0, sentKey = "";
    const draft = () => topic.value.trim() + "|" + (application?.value.trim() || "");   // o que está escrito; "já enviado" não é rascunho
    const go = btn(a.go, () => submit(), { icon: "sparkle", cls: "btn primary" });
    const submit = async () => {
      clearError(topic); clearError(application);
      if (!topic.value.trim()) return fieldError(topic, "Escreva o assunto.");
      if (application && !application.value.trim() && !projectId()) return fieldError(application, "Descreva o projeto ou escolha um projeto no Cérebro.");
      const body = { kind: a.kind, topic: topic.value, level: level.value, application: application?.value || "", project_id: projectId() };
      go.disabled = true;
      const my = ++gen;
      put(view, h("p", { class: "st-stage", role: "status" }, h("span", { class: "spinner sm" }), "Buscando nas suas notas e criando…"));
      const it = await guard(() => api("/api/study/learn", body));
      go.disabled = false;
      if (my !== gen) return;   // começou outra criação aqui: este resultado é de uma tentativa antiga
      if (!it) {                // o erro já foi avisado; os campos continuam como estavam para corrigir e tentar de novo
        put(view, h("div", { class: "st-lrn-fail", role: "alert" }, ic("alert"), h("span", { text: "Não foi possível criar agora. O que você escreveu continua aqui." }),
          btn("Tentar de novo", () => submit(), { cls: "btn sm" })));
        return;
      }
      sentKey = draft();
      paint(it);
      if (state.nav.act !== id) toast(`Pronto: ${it.title}`, "success", 8000, ["Abrir", () => open(it)]);
      refresh();
    };
    topic.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
    const paint = (it) => paintItem(id, view, it);
    const el = h("div", { class: "st-lrn-body" },
      h("form", { class: "st-lrn-form", onsubmit: (e) => { e.preventDefault(); submit(); } },
        field("Assunto", topic),
        application ? field("Seu projeto", application, { hint: "Pode usar o projeto selecionado no Cérebro." }) : null,
        h("details", { class: "st-lrn-more" }, h("summary", { text: "Mais opções" }), field("Nível da explicação", level)),
        h("div", { class: "st-lrn-actions" }, go),
        h("details", { class: "st-lrn-help" }, h("summary", { text: "Como funciona" }), h("p", { class: "muted", text: SOURCES_HELP }))),
      view, prev);
    const paintPrev = () => {
      const rows = (state.items || []).filter((x) => x.kind === a.kind);
      prev.hidden = !rows.length;
      if (!rows.length) return;
      const key = id, shown = state.showAll[key] ? rows.slice(0, RECENT_MAX) : rows.slice(0, RECENT);
      put(prev, h("h3", { class: "eyebrow", text: "Criados antes" }), recentList(shown, key, rows.length, { kind: false }));
    };
    paintPrev();
    return { el, dirty: () => draft() !== "|" && draft() !== sentKey, busy: () => go.disabled, paintPrev, view, onShow: paintPrev };
  }

  function answerAct() {
    const view = h("div", { class: "st-learn-view" });
    return { el: view, view };
  }

  // Feynman: explicar com as próprias palavras, por texto ou voz; a IA aponta o que está certo, o que faltou e o que está errado,
  // com as fontes, e o resultado entra no modelo do estudante (origem "feynman").
  function feynmanAct() {
    const topic = h("input", { type: "text", placeholder: "Ex.: keyframes no Premiere", maxlength: "200" });
    const text = h("textarea", { rows: 5, maxlength: "6000", placeholder: "Explique como se ensinasse alguém que nunca viu o assunto." });
    const out = h("div", { class: "st-feynman-out", "aria-live": "polite" });
    topic.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); text.focus(); } });
    let el = null, sentKey = "";
    const draft = () => topic.value.trim() + "|" + text.value.trim();
    const talk = window.lumenVoice?.ptt({ isActive: () => visible(el) && !L.S.practicing,  // só vale com esta atividade na tela
      onText: (t) => { text.value = (text.value.trim() ? text.value.trim() + " " : "") + t; clearError(text); text.focus(); } }) || null;
    const go = btn("Avaliar a explicação", async () => {
      clearError(topic); clearError(text);
      if (!topic.value.trim()) return fieldError(topic, "Escreva o assunto que você vai explicar.");
      if (text.value.trim().split(/\s+/).filter(Boolean).length < 5) return fieldError(text, "Explique com pelo menos uma frase.");
      go.disabled = true;
      put(out, h("p", { class: "st-stage", role: "status" }, h("span", { class: "spinner sm" }), "Comparando com as suas notas…"));
      const r = await guard(() => api("/api/study/feynman", { topic: topic.value, text: text.value, project_id: projectId() }));
      go.disabled = false;
      if (!r) return put(out);
      sentKey = draft();
      const list = (title, items, cls) => items.length ? h("div", { class: "st-feynman-list " + cls }, h("p", { class: "eyebrow", text: title }),
        h("ul", {}, items.map((x) => h("li", {}, h("span", { text: x.point }), " ", srcChip(x.source))))) : null;
      put(out, h("p", { class: r.correct ? "st-ok" : "st-bad" }, ic(r.correct ? "check-circle" : "alert"), r.correct ? `Explicou bem (${Math.round(r.score * 100)}%)` : `Ainda não (${Math.round(r.score * 100)}%)`),
        h("p", { text: r.feedback }), list("O que você explicou certo", r.right, "ok"), list("O que faltou", r.missing, "warn"), list("Errado ou confuso", r.wrong, "bad"),
        window.lumenVoice ? btn("Ouvir o retorno", (e) => window.lumenVoice.speak(r.feedback, { use: "practice", button: e.currentTarget }), { icon: "volume", cls: "btn sm ghost" }) : null,
        h("p", { class: "faint t-sm", text: "Registrado no que o Lúmen sabe que você domina (Seus dados)." }));
    }, { icon: "check", cls: "btn primary" });
    el = h("div", { class: "st-lrn-body st-feynman" },
      h("form", { class: "st-lrn-form", onsubmit: (e) => { e.preventDefault(); go.click(); } },
        field("Assunto", topic),
        field("Sua explicação", text, { hint: "Escreva ou segure o microfone e fale.", wrap: h("div", { class: "st-feynman-row" }, text, talk) }),
        h("div", { class: "st-lrn-actions" }, go)), out);
    return { el, dirty: () => draft() !== "|" && draft() !== sentKey, onHide: () => window.lumenVoice?.stop() };
  }

  // Treino falado (D58): role-play em turnos de voz. O personagem fala com a voz dele; você responde segurando o microfone (ou digitando);
  // no fim, uma avaliação por critérios entra no modelo do estudante (origem "practice"). Cenários e vozes só são buscados na 1ª vez.
  function speakingAct() {
    const V = window.lumenVoice;
    const scen = h("select", {}, h("option", { value: "", text: "Carregando…" }));
    const topic = h("input", { type: "text", maxlength: "120", placeholder: "Ex.: curso de persuasão" });
    const voiceSel = h("select", {}, h("option", { value: "", text: "A voz do Treino falado (Configurações → Voz)" }));
    const log = h("ol", { class: "st-practice-log", "aria-label": "Conversa do treino", "aria-live": "polite" });
    const out = h("div", { class: "st-feynman-out", "aria-live": "polite" });
    const reply = h("textarea", { rows: 3, maxlength: "1500", placeholder: "Segure o microfone e fale, ou escreva aqui." });
    let sess = null, left = 0, loaded = false, el = null;
    const turnBox = h("div", { class: "st-practice-turn" });
    const sessionBox = h("div", { class: "st-lrn-session", hidden: true });
    const sessionTitle = h("p", { class: "st-lrn-session-title" });
    const say = (line) => V?.speak(line, { use: "practice", voice: sess?.voice || null, language: sess?.language || null });
    const add = (who, t) => { log.append(h("li", { class: "st-practice-" + who }, h("strong", { text: who === "character" ? "Personagem" : "Você" }), h("span", { text: t }))); log.lastChild.scrollIntoView({ block: "nearest" }); };
    const leftLine = h("p", { class: "faint" });
    const sendBtn = btn("Responder", () => send(), { icon: "arrow-right", cls: "btn sm primary" });
    const endBtn = btn("Terminar e avaliar", () => finish(), { icon: "check", cls: "btn sm" });
    async function send() {
      const t = reply.value.trim();
      if (!sess) return;
      if (!t) return fieldError(reply, "Fale ou escreva a sua resposta.");
      sendBtn.disabled = true; V?.stop();
      add("student", t); reply.value = "";
      const r = await guard(() => api("/api/study/practice", { action: "turn", id: sess.id, text: t }));
      sendBtn.disabled = false;
      if (!r) { log.lastChild?.remove(); reply.value = t; return; }  // a IA falhou: a fala volta para a caixa
      left = r.left;
      if (r.line) { add("character", r.line); say(r.line); }
      leftLine.textContent = r.end || !left ? "A conversa chegou ao fim. Peça a avaliação." : `${left} resposta(s) até o fim do treino.`;
      sendBtn.disabled = r.end || !left;
    }
    async function finish() {
      if (!sess) return;
      endBtn.disabled = true; V?.stop();
      put(out, h("p", { class: "st-stage", role: "status" }, h("span", { class: "spinner sm" }), "Avaliando a conversa…"));
      const r = await guard(() => api("/api/study/practice", { action: "end", id: sess.id, project_id: projectId() }));
      endBtn.disabled = false;
      if (!r) return put(out);
      sess = null; L.S.practicing = false; sessionBox.hidden = true; setup.hidden = false;
      put(out, h("p", { class: r.correct ? "st-ok" : "st-bad" }, ic(r.correct ? "check-circle" : "alert"), `${r.correct ? "Bom treino" : "Continue treinando"} (${Math.round(r.overall * 100)}%)`),
        h("ul", { class: "st-rubric" }, r.criteria.map((c) => {
          const fill = h("span");
          fill.style.width = `${Math.round(c.score * 100)}%`;
          return h("li", {}, h("span", { class: "t-sm", text: c.name }), h("span", { class: "vc-meter", role: "meter", "aria-label": c.name, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(c.score * 100)) }, fill),
            h("small", { class: "muted", text: c.comment }));
        })),
        h("p", { text: r.feedback }), r.next ? h("p", { class: "muted" }, h("strong", { text: "Próximo treino: " }), r.next) : null,
        V ? btn("Ouvir o retorno", (e) => V.speak(`${r.feedback} ${r.next || ""}`, { use: "practice", button: e.currentTarget }), { icon: "volume", cls: "btn sm ghost" }) : null,
        h("p", { class: "faint t-sm", text: "Registrado no que o Lúmen sabe que você domina (Seus dados)." }));
      refresh();
    }
    const startBtn = btn("Começar o treino", async () => {
      clearError(scen);
      if (!scen.value) return fieldError(scen, "Escolha um cenário.");
      startBtn.disabled = true; log.replaceChildren(); put(out);
      const r = await guard(() => api("/api/study/practice", { action: "start", scenario: scen.value, topic: topic.value, voice: voiceSel.value }));
      startBtn.disabled = false;
      if (!r) return;
      sess = r; left = r.left; sendBtn.disabled = false; L.S.practicing = true;
      sessionTitle.textContent = scen.selectedOptions[0]?.textContent || "Treino em andamento";
      setup.hidden = true; sessionBox.hidden = false;
      leftLine.textContent = `${left} resposta(s) até o fim do treino.`;
      add("character", r.line); say(r.line);
      reply.focus();
    }, { icon: "play", cls: "btn primary" });
    const talk = V?.ptt({ isActive: () => visible(el) && !!sess, onText: (t) => { reply.value = (reply.value.trim() ? reply.value.trim() + " " : "") + t; clearError(reply); if (L.S.state?.settings?.voice?.send_alone) send(); else reply.focus(); } }) || null;
    turnBox.append(field("Sua resposta", reply, { wrap: h("div", { class: "st-feynman-row" }, reply, talk) }), h("div", { class: "st-lrn-actions" }, sendBtn, endBtn), leftLine);
    sessionBox.append(sessionTitle, log, turnBox);
    const setup = h("form", { class: "st-lrn-form", onsubmit: (e) => { e.preventDefault(); startBtn.click(); } },
      field("Cenário", scen),
      field("Tema (opcional)", topic),
      V ? h("details", { class: "st-lrn-more" }, h("summary", { text: "Voz do personagem" }), field("Voz", voiceSel),
        btn("Criar voz para personagem", () => V.designDialog(), { icon: "plus", cls: "btn sm ghost" })) : null,
      h("div", { class: "st-lrn-actions" }, startBtn),
      h("details", { class: "st-lrn-help" }, h("summary", { text: "Como funciona" }),
        h("p", { class: "muted", text: "O personagem fala com a voz dele; você responde segurando o microfone. No fim, uma avaliação por critérios." })));
    el = h("div", { class: "st-lrn-body st-practice" }, setup, sessionBox, out);
    const load = () => {   // só quando a atividade é aberta: cenários e vozes não são buscados só porque a aba Estudar abriu
      if (loaded) return;
      loaded = true;
      api("/api/study/practice").then((r) => scen.replaceChildren(...r.scenarios.map((x) => h("option", { value: x.id, text: x.title + (x.language === "en" ? " · inglês" : "") })))).catch(() => { loaded = false; });
      if (V) V.api("/api/study/voice/voices").then((r) => voiceSel.append(...r.voices.map((v) => h("option", { value: v.id, text: `${v.name} · ${V.kindLabel(v).toLowerCase()}` })))).catch(() => {});
    };
    return { el, onShow: load, onHide: () => V?.stop(), busy: () => !!sess, dirty: () => !!(sess || reply.value.trim() || topic.value.trim()) };
  }

  // Revisão de hoje: resumo, sessão (cartão a cartão, com teclado) e as revisões dos planos.
  function todayAct() {
    const summary = h("div", { class: "st-lrn-today" });
    const session = h("div", { class: "st-lrn-session", hidden: true });
    const paint = () => {
      const due = state.due;
      if (!due) return put(summary, h("p", { class: "faint", text: "Carregando…" }));
      put(summary,
        due.total ? h("div", { class: "st-lrn-next" }, h("span", { class: "st-lrn-ico" }, ic("timer")),
          h("div", { class: "st-lrn-next-text" }, h("strong", { text: `${n(due.total)} ${due.total === 1 ? "cartão" : "cartões"} para revisar agora` }),
            h("p", { class: "muted", text: "Você vê a pergunta, lembra, mostra a resposta e diz como foi." })),
          btn("Começar revisão", () => review(null, { act: "today" }), { icon: "play", cls: "btn primary" }))
          : h("div", { class: "st-lrn-empty" }, h("p", { class: "st-lrn-calm muted" }, ic("check-circle"), "Nenhum cartão para revisar agora."),
            h("p", { class: "faint", text: "Os cartões que você criar entram aqui na data da próxima revisão." }),
            btn("Criar flashcards", () => goAct("flashcards"), { icon: "sparkle", cls: "btn sm" })),
        due.plans?.length ? h("div", { class: "st-lrn-plans" }, h("h3", { class: "eyebrow", text: "Revisões dos seus planos" }),
          h("ul", { class: "st-lrn-rows" }, due.plans.map((r) => h("li", {}, h("button", { type: "button", class: "st-lrn-row", onclick: async () => { const it = await guard(() => api("/api/study/item?id=" + r.id)); if (it) open(it); } },
            h("span", { class: "st-lrn-ico" }, ic("folder")), h("span", { class: "st-lrn-row-text" }, h("strong", { text: r.focus }), h("small", { class: "faint", text: `${r.title} · até ${r.due.split("-").reverse().join("/")}` })), ic("chevron-right")))))) : null,
        topicsBlock(due.topics, "Assuntos para revisar"));
    };
    paint();
    const el = h("div", { class: "st-lrn-body" }, summary, session);
    return { el, paint, summary, session, busy: () => !session.hidden, onShow: paint };
  }

  // Sessão de revisão espaçada (SM-2) dentro de "Revisão de hoje". `from`: de onde veio, para voltar ao lugar certo.
  async function review(deckId, from) {
    const r = await guard(() => api("/api/study/due?limit=50" + (deckId ? "&deck=" + encodeURIComponent(deckId) : "")));
    if (!r?.cards.length) return toast("Nada para revisar agora.", "info");
    const act = state.built.today || ensureAct("today");
    if (act.busy()) { goAct("today"); return toast("Já há uma revisão em andamento. Termine ou feche antes de começar outra.", "info"); }
    goAct("today");
    let i = 0, right = 0;
    const box = h("section", { class: "st-session", "aria-live": "polite" });
    act.summary.hidden = true; act.session.hidden = false;
    put(act.session, box);
    const end = () => {
      document.removeEventListener("keydown", keys);
      act.session.hidden = true; act.summary.hidden = false; put(act.session);
      refresh(); L.refreshState();
      const back = from?.act && from.act !== "today" ? from.act : "";
      if (back) goAct(back); else act.paint();
    };
    const keys = (e) => {
      if (!box.isConnected) return document.removeEventListener("keydown", keys);
      if (!visible(box)) return;   // a sessão escondida (outra tela aberta) não captura o teclado
      // campos de texto e Espaço/Enter num botão focado ficam com o comportamento normal (sem clique duplo)
      if (e.target.closest("input, textarea, select") || ((e.key === " " || e.key === "Enter") && e.target.closest("button"))) return;
      const b = box.querySelector(`[data-key="${e.key}"]`);
      if (b) { e.preventDefault(); b.click(); }
    };
    document.addEventListener("keydown", keys);
    const showCard = () => {
      if (i >= r.cards.length) {
        box.replaceChildren(h("div", { class: "st-session-end" }, ic("check-circle"), h("h3", { class: "t-h2", text: "Revisão concluída" }),
          h("p", { class: "muted", text: `${r.cards.length} cartão(ões) revisados, ${right} lembrados. Os próximos voltam nas datas da revisão espaçada.` }),
          btn("Fechar", end, { cls: "btn" })));
        L.refreshState();
        return;
      }
      const c = r.cards[i], n = r.cards.length;
      const answer = h("div", { class: "st-session-answer", hidden: true }, h("p", { class: "st-card-label", text: "Resposta" }), h("p", { class: "st-flash-answer", text: c.answer }),
        c.explanation ? h("p", { class: "muted", text: c.explanation }) : null, srcChip(c.sources?.[0]));
      const grades = h("div", { class: "st-grades", role: "group", "aria-label": "Como foi?", hidden: true }, [["Errei", 0, "1", "danger"], ["Difícil", 1, "2", "warning"], ["Bom", 2, "3", "accent"], ["Fácil", 3, "4", "success"]].map(([label, g, key, tone]) =>
        h("button", { type: "button", class: "btn st-grade", dataset: { key, tone }, onclick: async () => {
          const res = await guard(() => api("/api/study/review", { card_id: c.id, grade: g }));
          if (!res) return;
          if (g >= 2) right++;
          i++; showCard();
        } }, h("span", { text: label }), h("kbd", { text: key }))));
      const reveal = h("button", { type: "button", class: "btn primary st-reveal", dataset: { key: " " }, onclick: () => { answer.hidden = grades.hidden = false; reveal.hidden = true; grades.querySelector("button")?.focus(); } }, "Mostrar resposta", h("kbd", { text: "Espaço" }));
      const fill = h("span", {});
      fill.style.transform = `scaleX(${i / n})`;   // CSSOM, não atributo style (CSP)
      box.replaceChildren(h("div", { class: "st-session-bar" }, h("p", { class: "eyebrow", text: `Cartão ${i + 1} de ${n}` }),
          h("div", { class: "st-session-progress", role: "progressbar", "aria-label": "Progresso da revisão", "aria-valuemin": "0", "aria-valuemax": String(n), "aria-valuenow": String(i) }, fill),
          btn("Parar por aqui", end, { cls: "btn sm ghost" })),
        // o monte atrás do cartão mostra quantos ainda faltam (até dois)
        h("article", { class: "st-card", dataset: { left: String(Math.min(2, n - i - 1)) } }, h("p", { class: "st-card-label", text: "Pergunta" }), h("h3", { class: "st-question", text: c.question }), answer),
        reveal, grades);
      reveal.focus();
    };
    showCard();
  }

  // --- Resultado de um material ---------------------------------------------------------------------------------------------
  function open(it) {
    if (!host) { pendingOpen = it; return; }
    const aid = ACT_OF_KIND[it.kind] || "answer";
    goAct(aid, { focus: false });
    const act = state.built[aid];
    paintItem(aid, act.view, it);
    act.view.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function announce(msg) {
    if (!shell) return;
    shell.live.textContent = "";
    setTimeout(() => { shell.live.textContent = msg; }, 50);
  }
  function paintItem(aid, view, it, { quiet = false } = {}) {
    const d = it.data, [, label, icon] = kindOf(it.kind);
    const headEl = h("div", { class: "st-item-head" }, h("span", { class: "st-saved-icon" }, ic(icon)),
      h("div", {}, h("h3", { class: "t-h2", text: it.title }), h("p", { class: "faint", text: `${label} · ${when(it.created)} · ${(d.sources || []).length} fonte(s)` })),
      // revisão em áudio: o .m4a vai junto, pela mesma prévia (D11), se já foi gerado
      btn("Salvar no Obsidian…", () => L.prepareSave("obsidian", { item_id: it.id, ...(it.kind === "audio" ? { with_audio: true } : {}) }, it.title), { icon: "obsidian", cls: "btn sm" }),
      btn("", () => view.replaceChildren(), { icon: "x", cls: "icon-btn sm", tip: "Fechar o resultado" }));
    const repaint = (x) => { paintItem(aid, view, x, { quiet: true }); return x; };
    const body = { flashcards: (x) => deck(x, aid), quiz, plan, map: mapView, gaps, audio: listenView, exercise: (x) => exercise(x, view, repaint), action: (x) => actionPlan(x, view, repaint), answer: (x) => h("div", { class: "st-answer" }, L.md(x.data.content)),
      mindmap: (x) => L.diagram ? L.diagram(x.data.diagram, { actions: btn("Salvar no Notion…", () => L.prepareSave("notion", { item_id: x.id }, x.title), { icon: "page", cls: "btn sm ghost" }) }) : null,
    }[it.kind]?.(it) || h("p", { text: "Formato desconhecido." });
    view.replaceChildren(h("section", { class: "card st-item" }, headEl, body,
      d.sources?.length ? h("details", { class: "st-item-sources" }, h("summary", { text: `Fontes usadas (${d.sources.length})` }), d.sources.map((s) => L.resultCard(s))) : null));
    if (!quiet) announce(`Resultado aberto: ${it.title}`);
  }

  function exercise(it, view, repaint) {
    const d = it.data, staged = [], files = h("div", { class: "st-chips", "aria-live": "polite" });
    const response = h("textarea", { rows: 5, maxlength: "12000", placeholder: "Escreva sua solução ou envie um arquivo. Os critérios acima serão usados na correção." });
    const picker = h("input", { type: "file", multiple: true, hidden: true, "aria-label": "Anexos da entrega" });
    const status = h("p", { class: "st-stage", "aria-live": "polite" });
    const send = btn("Corrigir entrega", async () => {
      send.disabled = picker.disabled = true;
      status.textContent = "Comparando a entrega com cada critério…";
      const result = await guard(() => api("/api/study/applied", { action: "submit", id: it.id, text: response.value, attachments: staged.map((a) => a.id) }));
      send.disabled = picker.disabled = false; status.textContent = "";
      if (result) { repaint(result); view.querySelector(".st-attempt:last-child summary")?.focus(); }
    }, { icon: "check", cls: "btn primary sm" });
    const renderFiles = () => {
      files.replaceChildren(...staged.map((a) => h("div", { class: "st-attach-chip" }, h("span", { text: `${a.name} · ${a.status === "ready" ? "Pronto" : a.message || "Lendo…"}` }),
        btn("", async () => { if (await guard(() => api("/api/study/attachment", { action: "remove", id: a.id }))) { staged.splice(staged.indexOf(a), 1); renderFiles(); } }, { icon: "x", cls: "icon-btn sm", tip: "Tirar " + a.name }))));
      send.disabled = staged.some((a) => a.status !== "ready") || picker.disabled;
    };
    const pollFiles = async () => {
      if (!files.isConnected || !staged.some((a) => a.status === "reading")) return;
      const r = await api("/api/study/attachments?ids=" + staged.map((a) => a.id).join(",")).catch(() => null);
      for (const a of r?.attachments || []) Object.assign(staged.find((x) => x.id === a.id) || {}, a);
      renderFiles();
      if (staged.some((a) => a.status === "reading")) setTimeout(pollFiles, 1000);
    };
    picker.addEventListener("change", async () => {
      if (staged.length + picker.files.length > 3) { picker.value = ""; return toast("Use até três anexos por entrega.", "warning"); }
      picker.disabled = send.disabled = true; status.textContent = "Enviando anexos…";
      for (const file of picker.files) { const a = await guard(() => L.uploadAttachment(file)); if (a) staged.push(a); }
      picker.value = ""; picker.disabled = false; status.textContent = ""; renderFiles(); pollFiles();
    });
    return h("div", { class: "st-exercise" }, h("p", { text: d.task }), h("p", {}, h("strong", { text: "O que entregar: " }), d.deliverable),
      h("ol", { class: "st-list" }, d.criteria.map((c) => h("li", {}, h("strong", { text: c.name }), " — ", c.expected, " ", srcChip(c.source)))),
      h("label", { class: "field" }, "Sua entrega", response), picker,
      btn("Anexar entrega", () => picker.click(), { icon: "file", cls: "btn sm ghost" }), files,
      h("p", { class: "faint", text: "A correção considera o texto lido do anexo, sem executar arquivos. Entregas e anexos ficam nesta prática e são apagados com ela." }), send, status,
      h("div", { class: "st-attempts" }, d.attempts.map((a, i) => h("details", { class: "st-attempt", ...(i === d.attempts.length - 1 ? { open: true } : {}) },
        h("summary", { text: `Entrega ${i + 1} · ${Math.round(a.score * 100)}% · ${when(a.at)}` }),
        h("details", {}, h("summary", { text: "Ver minha entrega" }), h("p", { class: "st-submission", text: a.submission })),
        h("ul", { class: "st-list" }, a.criteria.map((c) => h("li", {}, h("strong", { text: `${c.name} · ${Math.round(c.score * 100)}%` }), h("p", { text: c.feedback })))),
        h("p", {}, h("strong", { text: "Próximo passo: " }), a.next)))));
  }

  function actionPlan(it, view, repaint) {
    const d = it.data;
    const change = async (action, index, done) => { const r = await guard(() => api("/api/study/applied", { id: it.id, action, index, done })); if (r) repaint(r); return r; };
    const check = (label, action, index, done) => h("label", { class: "st-action-check" }, h("input", { type: "checkbox", "aria-label": label, ...(done ? { checked: true } : {}), onchange: async (e) => {
      const input = e.currentTarget; input.disabled = true;
      if (await change(action, index, input.checked)) {   // a tela é redesenhada com o resultado: o foco volta para a mesma caixa
        for (const c of view.querySelectorAll(".st-action-check input")) if (c.getAttribute("aria-label") === label) { c.focus(); break; }
      } else { input.checked = !input.checked; input.disabled = false; }
    } }), h("span", { text: label }));
    return h("div", { class: "st-action-plan", dataset: { item: it.id } }, h("p", { text: d.goal }), h("p", { class: "muted", text: "Seu projeto: " + d.application }),
      h("ol", { class: "st-steps" }, d.steps.map((s, i) => h("li", { class: "st-step" }, h("span", { class: "st-step-n", text: String(i + 1) }), h("div", {},
        check(s.title, "step", i, s.done), h("p", { class: "faint", text: `Até ${s.due.split("-").reverse().join("/")} · ${s.minutes} min` }),
        h("p", { text: s.objective }), h("p", {}, h("strong", { text: "Entrega: " }), s.deliverable), srcChip(s.source),
        btn("Focar nesta tarefa", async () => { if (await change("focus", i)) { window.Pomodoro?.setContext(s.title); window.Pomodoro?.open(); toast("Tarefa ligada ao Pomodoro. Inicie o foco quando quiser.", "info"); } }, { icon: "timer", cls: "btn sm ghost" }))))),
      h("h4", { class: "t-h3", text: "Revisões" }), h("ul", { class: "st-list" }, d.reviews.map((r, i) => h("li", {}, check(`${r.due.split("-").reverse().join("/")} · ${r.focus}`, "review", i, r.done)))),
      h("p", { class: "faint", text: `${d.focus_sessions} sessão(ões) de foco registradas. Concluir tarefa ou revisão registra progresso; a prática e os questionários verificam o domínio.` }));
  }

  // O Pomodoro avisa quando uma sessão de foco termina: o plano de ação aberto atualiza o contador, sem trocar de tela.
  window.addEventListener("lumen-pomodoro", async () => {
    const r = await api("/api/study/applied", { action: "event" }).catch(() => null);   // sempre registra o foco, com ou sem o plano aberto
    const act = state.built.action;
    if (r?.id && act?.view.querySelector(".st-action-plan")?.dataset.item === r.id) paintItem("action", act.view, r);
  });

  // Revisão em áudio: o roteiro (pergunta, pausa, resposta) e o player com capítulos quando o áudio fica pronto.
  // A geração vai pela fila de tarefas; o andamento e o Cancelar ficam no status do topo. Um ouvinte só por aba, não um por material.
  const audioWatch = new Map();
  window.addEventListener("lumen-audio", (e) => { const fn = audioWatch.get(e.detail?.id); if (fn) fn(); });
  function listenView(it) {
    const d = it.data, V = window.lumenVoice, aid = "rev-" + it.id, slot = h("div", { class: "st-listen-slot" });
    const offer = (msg) => put(slot, h("p", { class: "muted t-sm", text: msg }), V ? btn(d.audio?.status === "pronto" ? "Gerar de novo" : "Gerar o áudio", async (e) => {
      e.currentTarget.disabled = true;
      if (await V.make({ kind: "review", item_id: it.id })) put(slot, h("p", { class: "st-stage" }, h("span", { class: "spinner sm" }), "Gerando o áudio em segundo plano…"));
      else e.currentTarget.disabled = false;
    }, { icon: "volume", cls: "btn sm primary" }) : null);
    const show = async (waiting = d.audio?.status === "aguardando") => {
      const r = await V?.api(`/api/study/voice/audios?id=${aid}`).catch(() => null);
      if (r?.audio) return put(slot, V.player(r.audio, { onDelete: () => offer("Áudio apagado. O roteiro continua aqui.") }));
      const job = waiting ? await V?.api("/api/job").catch(() => null) : null;
      if (job?.status === "running" && job.kind === "audio" && slot.isConnected) {  // gerando agora: espera e confere de novo
        put(slot, h("p", { class: "st-stage" }, h("span", { class: "spinner sm" }), job.detail || "Gerando o áudio em segundo plano…"));
        if (typeof window.poll === "function") window.poll();  // o andamento e o Cancelar no status do topo
        return setTimeout(() => show(true), 1500);
      }
      offer(waiting && job?.status !== "running" && !r?.audio && job?.kind === "audio" && job.status === "error"
        ? `O áudio não saiu: ${job.error?.message || "erro"}.` : "O áudio desta revisão ainda não foi gerado (ou outra tarefa ocupava a fila).");
    };
    audioWatch.set(aid, () => { if (slot.isConnected) show(); });
    show();
    return h("div", { class: "st-listen" }, slot,
      d.intro ? h("p", { class: "muted", text: d.intro }) : null,
      h("ol", { class: "st-list" }, (d.chapters || []).map((c) => h("li", {}, h("strong", { text: c.title }),
        h("ul", {}, c.items.map((q) => h("li", {}, h("span", { text: q.question }), " ", h("span", { class: "faint", text: "→ " + q.answer }), " ", srcChip(q.source))))))));
  }

  // Flashcards
  function deck(it, aid) {
    const cards = it.data.cards || [];
    return h("div", { class: "st-deck" },
      h("div", { class: "st-source-actions" }, it.data.due ? btn(`Revisar ${it.data.due} agora`, () => review(it.id, { act: aid }), { icon: "play", cls: "btn primary sm" }) : h("span", { class: "faint", text: "Nenhum cartão deste baralho para revisar agora." })),
      h("ol", { class: "st-cards" }, cards.map((c) => h("li", { class: "st-flash" },
        h("details", {}, h("summary", { text: c.question }), h("p", { class: "st-flash-answer", text: c.answer }),
          c.explanation ? h("p", { class: "muted", text: c.explanation }) : null, srcChip(c.source))))));
  }

  // Questionário
  function quiz(it) {
    const qs = it.data.questions || [], answers = it.data.answers || {};
    const KIND = { multipla: "Múltipla escolha", vf: "Verdadeiro ou falso", aberta: "Pergunta aberta", interpretacao: "Interpretação" };
    return h("ol", { class: "st-quiz" }, qs.map((q, idx) => {
      const prev = answers[String(idx)];
      const feedback = h("div", { class: "st-feedback", "aria-live": "polite" });
      const showFeedback = (r) => put(feedback, h("p", { class: r.correct ? "st-ok" : "st-bad" }, ic(r.correct ? "check-circle" : "x-circle"),
        r.correct ? "Correto" : `Ainda não (nota ${Math.round((r.score || 0) * 100)}%)`), h("p", { text: r.feedback }), r.expected && !r.correct ? h("p", { class: "muted", text: "Resposta esperada: " + r.expected }) : null);
      let field;
      if (q.options?.length) {
        const name = `q-${it.id}-${idx}`;
        field = h("div", { class: "st-options", role: "radiogroup", "aria-label": q.question }, q.options.map((o) => h("label", { class: "st-option" }, h("input", { type: "radio", name, value: o }), h("span", { text: o }))));
      } else field = h("textarea", { rows: 3, placeholder: "Sua resposta", "aria-label": "Sua resposta" });
      const send = btn("Responder", async () => {
        const value = q.options?.length ? field.querySelector("input:checked")?.value : field.value;
        if (!value) return toast("Escolha ou escreva uma resposta.", "warning");
        send.disabled = true;
        const r = await guard(() => api("/api/study/quiz", { item_id: it.id, index: idx, response: value }));
        send.disabled = false;
        if (r) showFeedback(r);
      }, { cls: "btn sm primary" });
      if (prev) showFeedback(prev);
      return h("li", { class: "st-q" }, h("p", { class: "eyebrow", text: KIND[q.kind] || "Questão" }), h("p", { class: "st-question", text: q.question }), field,
        h("div", { class: "st-source-actions" }, send, srcChip(q.source)), feedback);
    }));
  }

  // Plano de estudos
  function plan(it) {
    const d = it.data;
    return h("div", { class: "st-plan" },
      d.goal ? h("p", { class: "lead", text: d.goal }) : null,
      d.prerequisites?.length ? h("div", {}, h("h4", { class: "t-h3", text: "Antes de começar" }),
        h("ul", { class: "st-list" }, d.prerequisites.map((p) => h("li", {}, h("strong", { text: p.topic }), " — ", p.why, " ", srcChip(p.source))))) : null,
      h("h4", { class: "t-h3", text: "Etapas" }),
      h("ol", { class: "st-steps" }, (d.steps || []).map((s, i) => h("li", { class: "st-step" }, h("span", { class: "st-step-n", text: String(i + 1) }),
        h("div", {}, h("p", { class: "st-step-title" }, s.title, h("span", { class: "faint", text: ` · ${s.minutes} min` })), h("p", { class: "muted", text: s.objective }),
          s.topics?.length ? h("p", { class: "st-tags" }, s.topics.map((t) => h("span", { class: "badge", text: t }))) : null,
          h("p", { class: "st-chips" }, (s.sources || []).map(srcChip)))))),
      d.reviews?.length ? h("div", {}, h("h4", { class: "t-h3", text: "Revisões" }), h("ul", { class: "st-list" }, d.reviews.map((r) => h("li", {}, h("strong", { text: `Dia ${r.after_days}` }), " — ", r.focus)))) : null);
  }

  // O que falta estudar
  function gaps(it) {
    const d = it.data;
    return h("div", { class: "st-gaps" },
      h("div", {}, h("h4", { class: "t-h3", text: "O que você já tem" }), d.known?.length ? h("ul", { class: "st-list" }, d.known.map((k) => h("li", {}, k.topic, " ", srcChip(k.source)))) : h("p", { class: "faint", text: "Nada encontrado nas notas." })),
      h("div", {}, h("h4", { class: "t-h3", text: "O que falta" }), h("ul", { class: "st-list" }, (d.missing || []).map((m) => h("li", {}, h("strong", { text: m.topic }), " — ", m.why, m.depends_on ? h("span", { class: "faint", text: ` (depende de ${m.depends_on})` }) : null)))),
      d.next?.length ? h("div", {}, h("h4", { class: "t-h3", text: "Próximos passos" }), h("ol", { class: "st-list" }, d.next.map((x) => h("li", { text: x })))) : null);
  }

  // Mapa de conhecimento: layout de forças simples e determinístico, em SVG, com a mesma informação em lista ao lado
  function layout(nodes, edges, w, hgt) {
    const N = nodes.length, pos = nodes.map((_, i) => ({ x: w / 2 + Math.cos(i / N * 2 * Math.PI) * w * .35, y: hgt / 2 + Math.sin(i / N * 2 * Math.PI) * hgt * .35 }));
    const idx = Object.fromEntries(nodes.map((nd, i) => [nd.id, i])), k = Math.sqrt(w * hgt / Math.max(N, 1)) * .8;
    for (let it = 0; it < 300; it++) {
      const disp = pos.map(() => ({ x: 0, y: 0 })), t = (1 - it / 300) * w * .08;
      for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
        const dx = pos[i].x - pos[j].x || .01, dy = pos[i].y - pos[j].y || .01, d = Math.hypot(dx, dy), f = k * k / d;
        disp[i].x += dx / d * f; disp[i].y += dy / d * f; disp[j].x -= dx / d * f; disp[j].y -= dy / d * f;
      }
      for (const e of edges) {
        const a = idx[e.from], b = idx[e.to];
        if (a == null || b == null) continue;
        const dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y, d = Math.hypot(dx, dy) || .01, f = d * d / k;
        disp[a].x -= dx / d * f; disp[a].y -= dy / d * f; disp[b].x += dx / d * f; disp[b].y += dy / d * f;
      }
      for (let i = 0; i < N; i++) {
        const d = Math.hypot(disp[i].x, disp[i].y) || 1;
        pos[i].x = Math.min(w - 60, Math.max(60, pos[i].x + disp[i].x / d * Math.min(d, t)));
        pos[i].y = Math.min(hgt - 30, Math.max(30, pos[i].y + disp[i].y / d * Math.min(d, t)));
      }
    }
    return pos;
  }
  function mapView(it) {
    const { nodes = [], edges = [] } = it.data;
    if (!nodes.length) return h("p", { class: "faint", text: "Não houve conceitos suficientes para montar o mapa." });
    const W = 900, H = 520, NS = "http://www.w3.org/2000/svg", pos = layout(nodes, edges, W, H), at = Object.fromEntries(nodes.map((nd, i) => [nd.id, pos[i]]));
    const s = (tag, attrs, ...kids) => { const e = document.createElementNS(NS, tag); for (const [k2, v] of Object.entries(attrs)) e.setAttribute(k2, v); e.append(...kids); return e; };
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "st-map", role: "img", "aria-label": `Mapa com ${nodes.length} nós e ${edges.length} ligações` });
    for (const e of edges) {
      const a = at[e.from], b = at[e.to];
      if (a && b) svg.append(s("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "st-map-edge" }, s("title", {}, e.label || "ligado")));
    }
    for (const nd of nodes) {
      const p = at[nd.id], concept = nd.kind === "concept";
      const g = s("g", { class: "st-map-node " + (concept ? "concept" : "doc " + (nd.source || "")), transform: `translate(${p.x},${p.y})`, tabindex: "0" },
        concept ? s("circle", { r: 7 }) : s("rect", { x: -6, y: -6, width: 12, height: 12, rx: 3 }),
        s("text", { x: 11, y: 4 }, nd.label), s("title", {}, concept ? `Conceito: ${nd.label}` : `${L.LABEL[nd.source] || "Documento"}: ${nd.label}`));
      if (!concept && nd.doc) g.addEventListener("click", () => guard(() => api("/api/study/open", { id: nd.doc })));
      svg.append(g);
    }
    const name = Object.fromEntries(nodes.map((nd) => [nd.id, nd.label]));
    return h("div", { class: "st-map-wrap" }, svg,
      h("details", { class: "st-map-list" }, h("summary", { text: "Conexões em lista" }),
        h("ul", { class: "st-list" }, edges.map((e) => h("li", {}, h("strong", { text: name[e.from] || e.from }), ` ${e.label || "→"} `, h("strong", { text: name[e.to] || e.to }))))));
  }

  // Cartão do item na conversa
  function itemCard(it) {
    const [, label, icon] = kindOf(it.kind);
    return h("div", { class: "st-item-card" }, h("span", { class: "st-saved-icon" }, ic(icon)),
      h("div", {}, h("p", { class: "st-item-card-title", text: it.title }), h("p", { class: "faint", text: `${label} · salvo em Estudar` })),
      btn("Abrir", () => { L.setTab("learn"); open(it); }, { cls: "btn sm primary" }));
  }

  Object.assign(L, {
    renderLearn: render, openItem: (it) => open(it), itemCard,
    learnHome: () => { if (shell) goHome(true); },                         // clicar de novo em "Estudar" volta ao início
    learnGo: (id) => { if (shell && ACTS[id]) goAct(id); },                // atalhos (Ctrl+K): ir direto a uma atividade
    learnState: () => ({ ...state.nav, dirty: Object.keys(state.built).filter(dirtyOf), busy: Object.keys(state.built).filter(busyOf) }),
  });
})();
