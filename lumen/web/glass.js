"use strict";
// Lúmen Glass 2026 (Ajustes → Aparência → Estilo da interface): só a apresentação da janela principal muda.
// O estilo chega pronto no <html data-ui> (o servidor marca antes do primeiro quadro); aqui ficam a troca sem recarregar,
// as reorganizações que o CSS sozinho não faz (colunas do Início, faixa do Pomodoro) e o conteúdo das peças exclusivas
// do Glass, sempre a partir dos MESMOS dados e funções do app.js (nenhuma rota, regra ou ação nova).
// Ao voltar ao Clássico, cada elemento movido volta exatamente ao lugar e à ordem de antes.
(() => {
  const root = document.documentElement;
  const on = () => root.dataset.ui === "glass";
  const home = $(".home-grid");
  const HOME_ORDER = [...home.children];                       // a ordem original (a grade do Clássico depende dela)
  const MAIN = ["#home-hero", "#pending", "#g-journey", "#home-recent"], SIDE = ["#home-system", "#g-quick", "#home-reviews"];
  const pomo = $("#u-pomo"), pomoHome = pomo.parentElement, pomoNext = pomo.nextSibling;

  // ---------- reorganização (só a posição dos elementos; nada é recriado, os ouvintes e o foco continuam) ----------
  function arrange() {
    if (on()) {
      if (!home.querySelector(".g-home-col")) {
        const col = (ids, cls) => { const c = el("div", { class: "g-home-col " + cls }); for (const id of ids) c.append($(id)); return c; };
        home.append(col(MAIN, "main"), col(SIDE, "side"));
      }
      if (!$(".g-pomo-lane")) {
        const lane = el("div", { class: "g-pomo-lane" });
        lane.append(pomo);
        $("#content").prepend(lane);
      }
    } else {
      if (home.querySelector(".g-home-col")) {
        home.append(...HOME_ORDER);
        for (const c of home.querySelectorAll(".g-home-col")) c.remove();
      }
      const lane = $(".g-pomo-lane");
      if (lane) { pomoHome.insertBefore(pomo, pomoNext); lane.remove(); }
    }
    settingsArrange();
  }

  // ---------- Início: cartão principal sem gravação nem tarefa ----------
  const goSource = (tab) => {
    showView("new");
    if (step !== "compose") backToCompose();
    $("#tab-" + tab)?.click();
  };
  function hero(box) {  // devolve true quando desenhou (o app.js então não desenha o cartão do Clássico)
    if (!on()) return false;
    const b = (cls, ic, text, fn, attrs = {}) => el("button", { class: "btn " + cls, type: "button", onclick: fn, ...attrs }, icon(ic), text);
    const art = el("div", { class: "g-hero-art", "aria-hidden": "true" }, el("i"), el("i"));
    art.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5Z"/></svg>');
    box.replaceChildren(el("div", { class: "g-hero" }, art, el("div", { class: "g-hero-body" },
      el("h2", { class: "hero-title" }, "Comece uma nova aula"),
      el("p", { class: "hero-sub" }, "Capture o conteúdo, escreva o que você entendeu e só então deixe a IA local aprofundar e completar."),
      el("div", { class: "hero-actions" },
        b("primary lg", "arrow-right", "Iniciar nova aula", () => { showView("new"); if (step !== "compose") backToCompose(); }),
        b("", "record", "Gravar aula", () => { goSource("recording"); $("#rec-start")?.focus(); }, { "data-tip": "Grava o som do PC enquanto você assiste" }),
        b("", "file", "Importar arquivo", () => goSource("file"), { "data-tip": "Um vídeo ou áudio que já está no seu PC" }),
        b("", "link", "Adicionar link", () => { goSource("recording"); const f = $("#lesson-link"); f?.scrollIntoView({ block: "center" }); f?.focus(); },
          { "data-tip": "Link do YouTube ou de um site, como referência da aula" })))));
    return true;
  }

  // ---------- Início: a jornada da aula em andamento (sem aula, nenhuma etapa é marcada) ----------
  const STEPS = ["capture", "understand", "deepen", "organize", "review"];
  const AT = { studying: 0, waiting_for_understanding: 1, understanding_written: 2, processing_with_ai: 2, completed: 3 };
  const NEXT = ["Capturar", "Compreender", "Aprofundar", "Organizar", "Revisar"];
  function journey() {
    if (!on() || !S) return;
    const r = S.recording || {}, j = lastJob || S.job || {}, p = S.pending?.[0];
    let at = -1, who = null, why = "";
    if (r.active && !r.error) { at = 0; why = r.paused ? "Captura pausada" : "Gravando agora"; }
    else if (j.status === "running" && j.kind !== "download") {
      at = j.kind === "analyze" ? 2 : ["prepare", "transcribe", "screen", "download"].includes(j.stage) ? 0 : 3;
      who = j.title || null; why = j.kind === "analyze" ? "A IA local está analisando" : STAGE_NAMES[j.stage] || "Processando";
    } else if (p) { at = AT[p.state] ?? 1; who = p.title || "Aula"; why = PENDING[p.state] || ""; }
    for (const [i, li] of [...$("#g-journey-steps").children].entries())
      li.dataset.on = at < 0 ? "" : i < at ? "done" : i === at ? "now" : "";
    $("#g-journey-steps").setAttribute("aria-label", at < 0 ? "Etapas de uma aula" : `Etapas da aula: agora em ${NEXT[at]}`);
    let foot = $("#g-journey-foot");
    if (!foot) { foot = el("div", { class: "g-journey-foot", id: "g-journey-foot" }); $("#g-journey").append(foot); }
    const go = el("button", { class: "btn sm", type: "button" });
    if (at < 0) {
      go.append(icon("new"), "Nova aula"); go.onclick = () => showView("new");
      swap(foot, [el("span", {}, "Nenhuma aula em andamento agora."), go]);
    } else {
      const canResume = !!p && who === (p.title || "Aula") && j.status !== "running";  // a aula pendente (não a gravação nem a tarefa)
      go.append(icon("arrow-right"), canResume ? (p.state === "completed" ? "Ver a análise" : "Continuar") : "Ver a aula");
      go.onclick = () => (canResume ? resume(p.key) : showView("new"));
      swap(foot, [el("span", {}, who ? el("strong", {}, who) : null, who ? " · " : "", why, ` · etapa: ${NEXT[at]}`), go]);
    }
  }

  // ---------- Início: selo geral do Sistema (lido das linhas que o app.js acabou de desenhar) ----------
  function system() {
    const badge = $("#sys-overall");
    if (!on()) { badge.hidden = true; return; }
    const rows = $$("#side-status .sys"), pend = rows.filter((r) => r.querySelector('.badge[data-tone="warn"]')).length;
    badge.hidden = !rows.length;
    badge.dataset.tone = pend ? "warn" : "ok";
    badge.replaceChildren(icon(pend ? "alert" : "check-circle"), pend ? `${pend} ${pend === 1 ? "pendência" : "pendências"}` : "Tudo pronto");
  }

  // ---------- botões do Início exclusivos do Glass (cada um chama o que já existe) ----------
  $("#g-sys-diag").addEventListener("click", () => $("#home-diag-btn").click());
  for (const b of $$("[data-g-quick]")) b.addEventListener("click", () => {
    const what = b.dataset.gQuick;
    if (what === "plan") { showView("study"); window.lumenStudy?.setTab("learn"); window.lumenStudy?.learnGo?.("plan"); }
    else if (what === "organize") { libFilter = "inbox"; libCourse = null; showView("library"); }
    else openPalette();
  });

  // ---------- Biblioteca: números e estrutura (contados das MESMAS listas que a Biblioteca mostra; nada estimado) ----------
  const lib = $("#view-library"), libNew = lib.querySelector(".page-head [data-go=new]");
  const LIB_MAIN = ["#lib-filter", ".toolbar", "#lib-filters", "#lib-crumbs", "#course-grid", "#library-list"].map((s) => lib.querySelector(s));
  const LIB_ORDER = [...lib.children];
  function libArrange() {
    if (on()) {
      if (lib.querySelector(".g-lib-body")) return;
      const stats = el("div", { class: "g-lib-stats", id: "g-lib-stats", role: "group", "aria-label": "Resumo da biblioteca" });
      const tree = el("nav", { class: "card g-lib-tree", id: "g-lib-tree", "aria-label": "Estrutura da biblioteca" });
      const main = el("div", { class: "g-lib-main" }, ...LIB_MAIN);
      lib.querySelector(".page-head").after(stats);
      stats.after(el("div", { class: "g-lib-body" }, tree, main));
      stats.append(libNew);
    } else if (lib.querySelector(".g-lib-body")) {
      lib.querySelector(".page-head").append(libNew);
      lib.append(...LIB_ORDER);
      lib.querySelector(".g-lib-body")?.remove();
      $("#g-lib-stats")?.remove();
    }
  }
  function library() {
    libArrange();
    if (!on()) return;
    const all = historyItems || [], loading = !historyItems, rv = !!S?.config.obsidian_review;
    const n = (f) => all.filter(VIEW_TEST[f]).length;
    const stat = (ic, label, value, tone, f, tip) => el("button", { class: "g-stat", type: "button", "data-tone": tone, "data-f": f, "data-tip": tip },
      el("span", { class: "g-stat-ico", "aria-hidden": "true" }, icon(ic)),
      el("span", { class: "g-stat-txt" }, el("span", {}, label), el("strong", { class: "tabular" }, loading ? "…" : String(value))));
    const stats = $("#g-lib-stats");
    const cards = [stat("layers", "Aulas salvas", all.length, "", "all", "Todas as aulas salvas no Notion e no Obsidian"),
      stat("play", "Em andamento", S?.pending?.length || 0, "accent", "pending", "Aulas começadas e ainda não salvas"),
      rv ? stat("calendar", "Revisar hoje", n("review"), "ok", "review", "Revisões marcadas para hoje ou atrasadas") : null,
      stat("library", "Cursos", catalogData.courses.length, "", "course", "Cursos com módulos e aulas")].filter(Boolean);
    const keep = document.activeElement?.closest?.("#g-lib-stats, #g-lib-tree") ? document.activeElement.dataset : null;
    stats.replaceChildren(...cards, libNew);
    // a estrutura: o mesmo filtro das vistas, e os cursos do catálogo (abrir um curso = o mesmo da Biblioteca)
    const cur = (f, c) => (c ? libFilter === "course" && libCourse === c : libFilter === f && !libCourse) ? { "aria-current": "true" } : {};
    const row = (ic, label, count, attrs) => el("button", { class: "g-tree-row", type: "button", ...attrs },
      icon(ic), el("span", { class: "g-tree-name" }, label), count ? el("span", { class: "g-tree-n tabular" }, String(count)) : null);
    const courses = catalogData.courses.slice().sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
    const open = $("#g-lib-tree details")?.open ?? true;
    const group = el("details", { class: "g-tree-group" }, el("summary", {}, icon("chevron-right"), el("span", { class: "g-tree-name" }, "Cursos"),
      el("span", { class: "g-tree-n tabular" }, String(n("course") || ""))),
      ...courses.map((c) => row("folder", c.name, all.filter((it) => clsOf(it).course_id === c.id).length, { "data-course": c.id, ...cur("course", c.id) })),
      courses.length ? null : el("p", { class: "g-tree-empty" }, "Nenhum curso ainda."));
    group.open = open;
    $("#g-lib-tree").replaceChildren(el("h2", { class: "g-tree-h" }, icon("folder"), "Estrutura"),
      row("layers", "Todos os estudos", all.length, { "data-f": "all", ...cur("all") }), group,
      row("play", "Conteúdo gratuito", n("free"), { "data-f": "free", ...cur("free") }),
      row("file", "Aulas avulsas", n("single"), { "data-f": "single", ...cur("single") }),
      row("move", "A organizar", n("inbox"), { "data-f": "inbox", ...cur("inbox") }),
      row("pen", "Em andamento", S?.pending?.length || 0, { "data-f": "pending", ...cur("pending") }));
    if (keep) (keep.course ? $(`#g-lib-tree [data-course="${CSS.escape(keep.course)}"]`) : $(`:is(#g-lib-tree, #g-lib-stats) [data-f="${keep.f}"]`))?.focus();
  }
  lib.addEventListener("click", (e) => {
    const b = e.target.closest("#g-lib-tree [data-f], #g-lib-tree [data-course], #g-lib-stats [data-f]");
    if (!b) return;
    if (b.dataset.course) return openCourse(b.dataset.course);
    libFilter = b.dataset.f; libCourse = null; renderLibrary();
  });

  // ---------- Ajustes: cabeçalho de seção e um cartão por grupo. Embrulha os elementos que já existem (nada é recriado) e desfaz no Clássico ----------
  const SET_SUB = {
    general: "A barra flutuante, a abertura com o Windows e a saída do Lumen.",
    appearance: "O estilo da interface de todas as janelas.",
    capture: "Configure como o Lumen acompanha o conteúdo visual e o áudio das suas aulas.",
    pomodoro: "Personalize seus ciclos de foco e descanso. O Pomodoro não interfere na gravação.",
    transcription: "Escolha o modelo local que transforma suas aulas em texto.",
    ai: "Configure como a IA local analisa, aprofunda e organiza seus materiais de estudo.",
    covers: "Crie capas para as suas páginas do Notion com a IA local do Lumen.",
    privacy: "Controle o que fica guardado neste computador e o que pode ser apagado.",
  };
  function settingsArrange() {
    // Diagnóstico: o cabeçalho é dele (não é embrulhado); só ganha o ladrilho de ícone das outras categorias, e o perde no Clássico
    const dh = $("#view-settings .diag-header"), tile = dh?.querySelector(":scope > .g-sec-ico");
    if (dh && on() && !tile) {
      const ico = el("span", { class: "g-sec-ico", "aria-hidden": "true" }), navIcon = $('#settings-nav [data-cat="diagnostics"] svg');
      if (navIcon) ico.append(navIcon.cloneNode(true));
      dh.prepend(ico);
    } else if (tile && !on()) tile.remove();
    for (const panel of $$("#view-settings .set-panel")) {
      const h2 = panel.querySelector(":scope > h2, :scope > .g-sec-head > h2");
      if (!h2) continue;  // Proteção e Diagnóstico têm cabeçalho próprio
      const head = panel.querySelector(":scope > .g-sec-head");
      if (on() && !head) {
        const kids = [...panel.children].filter((k) => k !== h2);
        const ico = el("span", { class: "g-sec-ico", "aria-hidden": "true" });
        const navIcon = $(`#settings-nav [data-cat="${panel.dataset.cat}"] svg`);
        if (navIcon) ico.append(navIcon.cloneNode(true));
        panel.prepend(el("header", { class: "g-sec-head" }, ico, h2, el("p", { class: "g-sec-sub" }, SET_SUB[panel.dataset.cat] || "")));
        let group = null;
        for (const k of kids) {  // um cartão por assunto: começa em cada h3 de rótulo ou [data-g-group]; [data-g-free] fica solto, entre os cartões
          if (k.matches("[data-g-free]")) { panel.append(k); group = null; continue; }
          if (!group || k.matches("h3.eyebrow, [data-g-group]")) { group = el("div", { class: "card g-group" }); panel.append(group); }
          group.append(k);
        }
      } else if (!on() && head) {
        const groups = [...panel.querySelectorAll(":scope > .g-group")];
        // a ordem original: o título e, em seguida, tudo como estava (os cartões se desfazem no lugar; o que estava solto fica onde está)
        panel.append(h2, ...[...panel.children].filter((c) => c !== head).flatMap((c) => c.matches(".g-group") ? [...c.children] : [c]));
        head.remove();
        for (const g of groups) g.remove();
      }
    }
  }
  // ---------- Configurações da IA: o cabeçalho da seção aberta (study-settings.js chama ao desenhar) ----------
  const AI_SUB = {
    models: "Os modelos locais, o comportamento das respostas e os recursos de IA do Lumen.",
    search: "Onde o Lumen busca informações e como usa as suas fontes de conhecimento.",
    memory: "O que o Lumen pode lembrar, como organiza o contexto e quando as conversas são guardadas.",
    personal: "Como o Lumen responde, se comunica e se adapta às suas preferências de estudo.",
    adult: "Um perfil de linguagem independente, com modelo local e preferências próprias.",
    voice: "A voz do Lumen, a qualidade da fala e as conversas em tempo real.",
    pdf: "A aparência dos documentos e a geração de imagens dos seus materiais.",
    privacy: "O que a IA pode acessar, criar e consultar, com os seus dados sob o seu controle.",
    connectors: "Onde o Lumen guarda os materiais produzidos pela IA e o acesso às integrações.",
    performance: "Sincronização, indexação e processamento das suas fontes de conhecimento.",
    catalog: "As capacidades do Lumen: comandos, skills, integrações, modelos e permissões.",
    evaluation: "Suas avaliações e correções, para comparar respostas e versões locais.",
    projects: "Conversas, memórias e documentos em espaços dedicados a cada assunto.",
    activity: "As ações do Lumen, as ferramentas usadas e o resultado de cada operação.",
    data: "O que o Lumen guarda neste computador, e como exportar ou apagar.",
  };
  // Ícones dos cartões e das linhas das Configurações da IA (referências R11–R26): decorativos (aria-hidden, .g-only), escolhidos pelo
  // título do cartão e pelo rótulo da linha. Cartão sem título conhecido usa o ícone da seção; num cartão, as linhas só ganham ícone
  // quando TODAS têm um (nada de metade com, metade sem).
  const CARD_ICO = {
    "Provedor de texto": "cpu", "IA local": "layers", "Imagens e vídeo": "image", "Busca por significado": "search", "Privacidade": "shield",
    "Onde pesquisar": "search", "Como pesquisar": "route", "Memória e personalização": "book", "Personalização": "pen",
    "Perfil adulto": "power", "Estilo e geração": "palette", "Situação": "info", "Motor": "layers", "Qualidade e rapidez": "bolt",
    "Revisão a duas vozes": "chat", "Voz padrão": "mic", "Uma voz por uso": "volume", "Jeito de falar": "wave", "Leitura": "book",
    "Testar a voz": "play", "Conversa por voz": "mic", "Pronúncias": "pen", "PDFs e imagens": "file", "Permissões": "key",
    "Aplicativos permitidos": "screen", "Pesquisa guiada": "search", "Retenção": "clock", "Onde salvar": "folder", "Conexões": "link",
    "Sincronização e índice": "sync", "Catálogo": "book", "Integrações": "plug", "Permissões e modelos por papel": "key",
    "Instalados por este trabalho": "download", "Avaliação local": "check-circle", "Projetos do Lúmen": "library",
    "Histórico de atividades": "clock", "O que está guardado": "folder", "Quem recebeu informações": "upload", "Exportar e limpar": "download",
  };
  const ROW_ICO = {
    "Provedor": "cpu", "Modelo para responder": "chat", "Modelo rápido": "bolt", "Modelo do esforço Máximo": "layers", "Modelo de embeddings": "graph",
    "Temperatura": "wave", "Texto das fontes por resposta": "page", "Mostrar a resposta enquanto é escrita": "eye",
    "Nível de detalhamento": "layers", "Tom de resposta": "chat", "Formato preferido": "page", "Idioma": "book",
    "Usar o perfil adulto": "power", "Quando usar": "route", "Modelo do perfil": "layers", "Temperatura do perfil": "wave",
    "PDF com fundo escuro": "file", "Ilustração na capa da apostila": "image", "Pasta das notas no cofre": "obsidian", "Página do Notion": "notebook",
    "Usar memória": "book", "Salvar novas memórias automaticamente": "sparkle", "Guardar conversas no histórico": "clock", "Memória de longo prazo": "brain",
    "Memória por projeto": "library", "Conversa temporária com privacidade máxima": "shield",
    "Notion": "notebook", "Obsidian": "obsidian", "Arquivos de pastas autorizadas": "folder", "Internet": "link", "Busca híbrida": "search",
    "Ler as imagens das notas": "image", "Preferir fontes científicas": "book", "Número máximo de fontes": "layers", "Cache de páginas da internet (dias)": "clock",
    "Sincronizar a cada (minutos)": "sync", "Dar prioridade às aulas": "bolt", "Trechos por lote de embeddings": "layers", "Imagens das notas lidas por sincronização": "image",
    "A IA pode abrir páginas e notas sozinha": "external", "Criar notas e páginas (nível 2)": "pen", "Guardar histórico de atividades por (dias)": "clock",
    "Apagar conversas sem uso há (dias)": "trash",
    "Motor de voz": "layers", "Ligar o Voice Studio sozinho": "power", "Desligar depois de parada (minutos)": "clock", "Deixar a voz pronta ao abrir o Lúmen": "bolt",
    "Se a voz do Voice Studio não ligar": "shield", "Ler as respostas sozinho": "play", "O que ler": "book", "Velocidade": "timer", "Estilo (tags do motor)": "palette",
    "Semente": "key", "Frases guardadas (MB)": "folder", "Conferir os áudios longos": "check-circle", "Gerar o resumo em áudio no fim de cada aula": "volume",
    "Revisão em formato de conversa": "chat", "Voz do narrador": "mic", "Trocar a voz padrão": "volume", "Testar": "play", "Microfone": "mic",
    "Voz da chamada": "volume", "Velocidade da voz na chamada": "timer", "Modo": "route", "Transcrição da chamada": "wave", "Encerrar sozinho": "power",
    "Interromper falando": "mic", "Legendas ao vivo": "page", "Som de “entendi”": "music", "Resposta antecipada": "bolt", "Esforço na chamada": "layers",
    "Preencher a espera": "chat", "Primeiro trecho da resposta": "bolt", "Estou de fone": "volume", "Tamanho das respostas": "layers",
    "Qualidade da voz na chamada": "sparkle", "Guardar a conversa": "download", "Fim da fala": "timer", "Mostrar os tempos": "clock",
    "Apertar para falar: enviar sozinho": "mic",
  };
  function aiCards(panel, sec) {
    for (const card of panel.querySelectorAll(".st-set-card")) {
      const h3 = card.querySelector(":scope > h3");
      if (h3 && !h3.querySelector(":scope > .g-card-ico")) {
        h3.prepend(el("span", { class: "g-card-ico g-only", "aria-hidden": "true" }, icon(CARD_ICO[h3.textContent.trim()] || sec[2])));
      }
      const rows = [...card.querySelectorAll(".set-row")].filter((r) => !r.querySelector(":scope > .g-row-ico"));
      const picks = rows.map((r) => ROW_ICO[r.querySelector(".set-text > strong")?.textContent.trim()]);
      if (rows.length && picks.every(Boolean)) rows.forEach((r, i) => r.prepend(el("span", { class: "g-row-ico g-only", "aria-hidden": "true" }, icon(picks[i]))));
    }
  }
  // Catálogo (R11): cada skill ganha um ladrilho (pelo nome do comando) e o botão de testar um ícone; decorativos (.g-only)
  const SKILL_ICO = { explicar: "page", resumir: "layers", comparar: "copy", encontrar: "search", flashcards: "notebook", quiz: "question", mapa: "graph",
    "mapa-mental": "map", plano: "calendar", pratica: "pen", acao: "route", lacunas: "alert", imagem: "image", pdf: "file", voz: "volume" };
  function catalogDecor(panel) {
    for (const a of panel.querySelectorAll(".st-catalog-skill")) {
      if (a.querySelector(":scope > .g-tile-ico")) continue;
      a.prepend(el("span", { class: "g-tile-ico g-only", "aria-hidden": "true" }, icon(SKILL_ICO[a.querySelector("strong")?.textContent.replace(/^\//, "")] || "bolt")));
      a.querySelector(".st-source-actions > .btn.ghost")?.prepend(icon("play", "g-only"));
    }
  }
  function aiSection(panel, sec) {
    if (!panel || !sec) return;
    aiCards(panel, sec);
    if (sec[0] === "catalog") catalogDecor(panel);
    if (panel.querySelector(":scope > .g-sec-head")) return;
    const ico = el("span", { class: "g-sec-ico", "aria-hidden": "true" }, icon(sec[2]));
    // decorativo: o nome da seção já está na navegação (aria-current) e nos títulos dos cartões, então não vira um segundo título
    panel.prepend(el("div", { class: "g-sec-head g-only", "aria-hidden": "true" }, ico, el("p", { class: "g-sec-title" }, sec[1]), el("p", { class: "g-sec-sub" }, AI_SUB[sec[0]] || "")));
  }

  // ---------- Configurações da IA › Atividades: a tabela vira uma linha do tempo por dia (R23) ----------
  // Os MESMOS registros da tabela do Clássico (study-settings.js entrega as linhas e o nome de cada ação). O bloco é .g-only: existe nos
  // dois estilos e o Clássico continua com a tabela. Cada registro abre (details) para mostrar resultado, detalhe e permissão por inteiro.
  // A lista entra em lotes: "Carregar mais atividades" só mostra o que a tela já recebeu, sem nenhuma chamada nova.
  const ACT_ICO = {
    "ferramenta": "sparkle", "busca": "search", "abrir": "external", "gravar": "pen", "preparar-gravacao": "eye", "cancelar-gravacao": "x-circle",
    "desfazer-criacao": "reset", "envio-externo": "upload", "sincronizar": "sync", "testar-fonte": "link", "desconectar-fonte": "plug",
    "memoria": "book", "apagar-dados": "trash", "apagar-conversas": "trash", "apagar-projeto": "trash", "credencial": "key",
    "autorizar-pasta": "folder", "remover-pasta": "folder", "indexar-anexo": "file", "troca-automatico": "route", "chamada-turno": "chat",
    "pesquisa-guiada": "search", "abrir-aplicativo": "screen",
  };
  const ACT_STEP = 30;
  function actTone(a) {
    const r = String(a.result || "");
    if (r === "ok") return ["ok", "check", "Concluído"];
    if (/^erro|falh/i.test(r) || a.action === "testar-fonte") return ["error", "alert", r];  // teste de fonte: o que não é "ok" é a mensagem da falha
    if (/cancel/i.test(r)) return ["warn", "x", r];
    if (/aguardando|pedido/i.test(r)) return ["accent", "clock", r];
    return ["", "info", r || "Sem resultado"];
  }
  function activity(card, rows, name) {
    if (!card || !rows?.length) return;
    const now = new Date(), yest = new Date(now); yest.setDate(now.getDate() - 1);
    const dayName = (d) => {
      if (isNaN(d)) return "Sem data";
      const date = d.toLocaleDateString("pt-BR", { day: "2-digit", month: "long", ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }) });
      return d.toDateString() === now.toDateString() ? `Hoje · ${date}` : d.toDateString() === yest.toDateString() ? `Ontem · ${date}` : date;
    };
    const fact = (ic, label, value) => el("span", { class: "g-tl-fact" }, icon(ic), el("span", {}, label + ":"), el("b", {}, value || "—"));
    const more = (pairs) => el("dl", { class: "g-tl-more" }, ...pairs.filter(([, v]) => v).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
    function item(a) {
      const d = new Date(a.at), [tone, ic, label] = actTone(a);
      return el("li", { class: "g-tl-item" }, el("details", { class: "g-tl-card" },
        el("summary", {},
          el("span", { class: "g-tl-ico", "aria-hidden": "true" }, icon(ACT_ICO[a.action] || "clock")),
          el("span", { class: "g-tl-what" }, el("strong", {}, name(a)), el("small", {}, isNaN(d) ? "" : "às " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }))),
          el("span", { class: "g-tl-facts" }, fact("layers", "Ferramenta", [a.tool, a.provider].filter(Boolean).join(" · ")), fact("page", "Alvo", a.target)),
          el("span", { class: "badge", ...(tone ? { "data-tone": tone } : {}) }, icon(ic), el("span", {}, label)),
          icon("chevron-down", "g-tl-chev")),
        more([["Quando", isNaN(d) ? "" : d.toLocaleString("pt-BR", { dateStyle: "long", timeStyle: "medium" })], ["Alvo", a.target], ["Resultado", a.result],
          ["Detalhe", a.detail], ["Permissão", a.permission], ["Provedor", a.provider]])));
    }
    const box = el("div", { class: "g-tl g-only" });
    let shown = 0, day = "", list = null;
    const btn = el("button", { class: "btn g-tl-load", type: "button" }, icon("arrow-down"), "Carregar mais atividades");
    function load() {
      const first = shown;
      for (const a of rows.slice(shown, shown + ACT_STEP)) {
        const d = new Date(a.at), k = isNaN(d) ? "?" : d.toDateString();
        if (k !== day || !list) {
          day = k; list = el("ol", { class: "g-tl-list" });
          box.insertBefore(el("section", { class: "g-tl-day" }, el("h4", { class: "g-tl-date" }, dayName(d)), list), btn.isConnected ? btn : null);
        }
        list.append(item(a));
        shown++;
      }
      if (shown >= rows.length) btn.remove();
      else if (!btn.isConnected) box.append(btn);
      // o botão pode ter sumido: o foco segue para o primeiro registro que acabou de entrar
      if (first) box.querySelectorAll(".g-tl-card > summary")[first]?.focus({ preventScroll: true });
    }
    btn.addEventListener("click", load);
    load();
    card.append(box);
  }

  // ---------- Configurações da IA › Avaliação local: contador, estado vazio e a trilha Avaliar → Registrar → Comparar (R15) ----------
  // Só peças .g-only dentro do cartão de sempre (nada é movido): o fundo de vidro da parte de cima, o número de casos que a frase do
  // Clássico já dizia, o estado vazio e os três passos que a frase do cartão descreve. As explicações e os botões são os mesmos.
  function evaluation(card, n) {
    if (!card || card.querySelector(":scope > .g-ev-back")) return;
    const step = (ic, name, text) => el("li", {}, el("span", { class: "g-tile-ico", "aria-hidden": "true" }, icon(ic)), el("div", {}, el("strong", {}, name), el("small", {}, text)));
    card.prepend(el("div", { class: "g-ev-back g-only", "aria-hidden": "true" }));
    card.append(...[
      el("p", { class: "g-ev-count g-only" }, el("strong", {}, String(n)), el("span", {}, n === 1 ? "caso registrado" : "casos registrados")),
      !n && el("div", { class: "g-ev-empty g-only" }, el("span", { class: "g-ev-empty-ico", "aria-hidden": "true" }, icon("page")),
        el("strong", {}, "Nenhuma avaliação registrada ainda"), el("p", {}, "Avalie respostas nas conversas do Cérebro para começar a formar seu conjunto de avaliação.")),
      el("section", { class: "g-ev-trail g-only" }, el("h4", {}, "Avaliar → Registrar → Comparar"), el("ol", { class: "g-cov-how-steps" },
        step("thumb", "Avaliar", "Marque respostas como boas ou ruins nas conversas e registre correções."),
        step("layers", "Registrar", "Cada avaliação vira um caso, com as fontes da resposta."),
        step("bars", "Comparar", "Exporte o conjunto e compare versões locais de modelos e prompts."))),
      el("p", { class: "g-ev-note g-only" }, "As fontes guardadas com a resposta acompanham a exportação.")].filter(Boolean));
    for (const s of card.querySelectorAll(":scope > details > summary")) { s.prepend(icon("info", "g-only")); s.append(icon("chevron-down", "g-only g-ev-chev")); }
    card.querySelector(":scope > .btn.ghost")?.prepend(icon("folder", "g-only"));
  }

  // ---------- Configurações da IA: um cartão do Clássico em vários cartões de vidro (R21 PDFs e imagens, R26 Personalização) ----------
  // Nada sai do lugar: o cartão vira uma grade sem moldura, cada grupo ganha um fundo de vidro (.g-sp-back) e um cabeçalho (.g-sp-head),
  // e o CSS põe cada linha que já existia no grupo dela. O título do cartão continua lá para o leitor de tela (só não é desenhado).
  function split(card, kind, heads, extra = []) {
    if (!card || card.querySelector(":scope > .g-sp-back")) return;
    card.prepend(...heads.map((_, i) => el("div", { class: "g-sp-back g-only", "data-k": kind + (i + 1), "aria-hidden": "true" })));
    card.append(...heads.map(([ic, title, text], i) => el("div", { class: "g-sp-head g-only", "data-k": kind + (i + 1) },
      el("span", { class: "g-tile-ico", "aria-hidden": "true" }, icon(ic)), el("div", {}, el("strong", {}, title), text && el("small", {}, text)))), ...extra);
  }
  function pdf(card, F) {
    split(card, "pdf", [["file", "Documentos PDF", "A aparência dos PDFs que o Lúmen produz."], ["image", "Imagens dos materiais", "As ilustrações nas apostilas geradas pelo Lúmen."],
      ["bolt", "Comandos rápidos", "Use estes comandos na conversa para gerar materiais."], ["layers", "Tipos, proporções e armazenamento"]], [
      el("ul", { class: "g-sp-cmds g-only" }, ...[["file", "Criar PDF", F.pdf], ["image", "Criar imagem", F.image], ["map", "Texto e relações precisas", F.map]]
        .map(([ic, name, cmd]) => el("li", {}, icon(ic), el("strong", {}, name), el("code", {}, cmd)))),
      el("dl", { class: "g-sp-facts g-only" }, ...[["book", "Tipos de PDF", F.types + "."], ["image", "Proporções de imagens", F.ratios + "."], ["info", "Arquivos gerados", F.files]]
        .flatMap(([ic, k, v]) => [el("dt", {}, icon(ic), k), el("dd", {}, v)]))]);
  }
  function personal(card) {
    split(card, "per", [["chat", "Instruções personalizadas", "Oriente como o Lúmen deve responder."], ["palette", "Estilo das respostas"],
      ["book", "Preferências de estudo", "Conte como você prefere aprender, revisar e organizar seus estudos."]]);
  }

  // ---------- Nova aula: as fontes à vista acionam as abas de sempre (selectTab no app.js faz todo o resto) ----------
  // ---------- Nova aula › Salvar: o resultado em cartões por destino (R05) ----------
  // Os mesmos fatos das linhas do Clássico (doneLines, obsidianParts, visualFacts do app.js), sem nenhum dado novo. O bloco é .g-only:
  // existe nos dois estilos (a troca sem recarregar não precisa redesenhar) e o Clássico não o mostra. Os botões chamam as mesmas funções.
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const facts = (rows) => el("ul", { class: "g-facts" }, ...rows.map(([ic, text, warn]) =>
    el("li", warn ? { "data-warn": "true" } : {}, icon(ic), el("span", {}, text))));
  const secHead = (ic, text) => el("h3", { class: "g-res-h" }, icon(ic), text);
  function destCard(name, ic, d, rows, action) {
    const ok = d.status === "ok";
    return el("article", { class: "g-dest", "data-ok": String(ok) },
      el("header", {}, el("span", { class: "g-dest-logo", "data-dest": name.toLowerCase(), "aria-hidden": "true" }, icon(ic)), el("strong", {}, name),
        el("span", { class: "badge", "data-tone": ok ? "ok" : "warn" }, icon(ok ? "check" : "alert"), ok ? "Salvo" : "Pendente")),
      facts(ok ? rows : [["alert", [d.error, d.action].filter(Boolean).join(" "), true]]), action);
  }
  function result(res, r) {
    const nt = r.notion, ob = r.obsidian, vf = visualFacts(r), v = r.visual, all = [nt, ob].filter(Boolean);
    const box = el("div", { class: "g-result g-only" });
    if (all.length) box.append(el("section", { class: "g-res-sec" }, secHead("layers", "Seus materiais"), el("div", { class: "g-dests" },
      nt && destCard("Notion", "notebook", nt,
        [["page", `Página “${r.title}”`], ["folder", `Organização: ${r.course}`], ["layers", "Subpágina: Minha compreensão"]],
        nt.status === "ok"
          ? el("a", { class: "btn primary", href: nt.url, target: "_blank", rel: "noopener" }, icon("external"), "Abrir no Notion")
          : el("button", { class: "btn primary", type: "button", onclick: () => redeliver(r.key, "notion") }, icon("refresh"), "Tentar de novo só o Notion")),
      ob && destCard("Obsidian", "obsidian", ob, ob.status === "ok" ? obsidianParts(ob).map(([ic, t, w]) => [ic, cap(t), w]) : [],
        ob.status === "ok"
          ? el("button", { class: "btn" + (nt ? "" : " primary"), type: "button", onclick: () => openObsidian(r.key, "note") }, icon("external"), "Abrir no Obsidian")
          : el("button", { class: "btn primary", type: "button", onclick: () => redeliver(r.key, "obsidian", ob.conflict) },
              icon("refresh"), ob.conflict ? "Substituir mesmo assim (com backup)" : "Tentar de novo só o Obsidian")))));
    if (v && v.state !== "off") {
      const rows = v.file ? [[v.kind === "gif" ? "play" : "image", vf.kind], v.describe && ["layers", v.describe], ...vf.where.map((w) => ["screen", cap(w)])].filter(Boolean)
        : [["info", `Não saiu (${vf.why}).`, true]];
      box.append(el("section", { class: "g-res-sec" }, secHead("graph", "Visualização de conceitos"),
        el("div", { class: "g-vis", "data-file": String(!!v.file) }, v.file && el("div", { class: "g-vis-frame" }, vf.picture()),
          el("div", { class: "g-vis-body" }, el("strong", {}, "Visualização 3D"), facts(rows), (v.file ? vf.again : v.state === "failed") && vf.retry()))));
    } else if (v) box.append(el("p", { class: "g-res-note" }, icon("info"), el("span", {}, "Visualização 3D desligada.")));
    if (r.note) box.append(el("p", { class: "g-res-note" }, icon("info"), el("span", {}, r.note)));
    res.append(box);
    // no Glass o cartão é mais alto que a janela: o foco vai para a ação do primeiro destino (no alto) e a tela fica no topo, com o
    // título à vista; o app.js acabou de focar o primeiro botão do rodapé, que ficaria abaixo da dobra
    if (on()) requestAnimationFrame(() => {
      if (!box.isConnected || !on()) return;
      box.querySelector(".g-dest > .btn")?.focus({ preventScroll: true });
      $("#content").scrollTop = 0;
    });
    // o título do cartão: “Material processado com sucesso” quando tudo foi salvo (o do Clássico continua no mesmo elemento)
    if (all.length && all.every((d) => d.status === "ok")) {
      $("#run-h").replaceChildren(el("span", { class: "c-only" }, $("#run-h").textContent), el("span", { class: "g-only" }, "Material processado com sucesso"));
    }
  }

  function source(kind) {
    for (const b of $$("[data-g-src]")) b.setAttribute("aria-pressed", String(b.dataset.gSrc === kind));
  }
  for (const b of $$("[data-g-src]")) b.addEventListener("click", () => $("#tab-" + b.dataset.gSrc)?.click());
  $("#g-cap-set").addEventListener("click", () => goSettings("capture"));
  source($(".src-tabs [aria-selected=true]")?.dataset.kind || "recording");

  // ---------- janela: os controles do Windows (só dentro do Lumen.exe com moldura própria), com as mesmas mensagens de sempre ----------
  const host = window.chrome?.webview;
  if (host && new URLSearchParams(location.search).has("frame"))
    for (const b of $$("[data-g-window]")) b.addEventListener("click", () => host.postMessage("window:" + b.dataset.gWindow));
  // o ícone de maximizar vira "restaurar" quando a janela ocupa a área de trabalho
  const maxBtn = $("#g-win-max");
  function winState() {
    const max = innerWidth >= screen.availWidth - 1 && innerHeight >= screen.availHeight - 1;
    if (maxBtn.dataset.max === String(max)) return;
    maxBtn.dataset.max = String(max);
    maxBtn.setAttribute("aria-label", max ? "Restaurar" : "Maximizar");
    maxBtn.dataset.tip = max ? "Restaurar" : "Maximizar";
    maxBtn.querySelector("svg").innerHTML = max
      ? '<rect x="3.5" y="5.5" width="7" height="7" rx="1.2"/><path d="M5.5 5.5V4.8c0-.7.6-1.3 1.3-1.3h4.4c.7 0 1.3.6 1.3 1.3v4.4c0 .7-.6 1.3-1.3 1.3h-.7"/>'
      : '<rect x="3.5" y="3.5" width="9" height="9" rx="1.5"/>';
  }
  addEventListener("resize", winState, { passive: true });
  winState();

  // ---------- Ajustes → Aparência → Estilo da interface ----------
  const radios = $$('#ui-style input[name="ui_style"]'), state = $("#ui-style-state");
  const mark = () => { for (const r of radios) r.checked = r.value === (on() ? "glass" : "classic"); };
  function apply(style) {
    root.dataset.ui = style === "glass" ? "glass" : "classic";
    arrange();
    mark();
    system();
    if (typeof heroMode !== "undefined") heroMode = "";  // o cartão principal se redesenha no estilo novo
    if (S) { renderPending(); renderHome(); journey(); renderLibrary(); }
    library();
    document.dispatchEvent(new CustomEvent("lumen:ui-style", { detail: { style: root.dataset.ui } }));
  }
  for (const r of radios) r.addEventListener("change", async () => {
    if (!r.checked) return;
    const want = r.value, was = root.dataset.ui;
    for (const x of radios) x.disabled = true;
    state.textContent = "";
    try {
      await api("/api/settings?view=settings", { ui_style: want });
      apply(want);
      state.textContent = want === "glass" ? "Lúmen Glass 2026 aplicado. Para voltar, escolha Clássico." : "Estilo Clássico aplicado.";
    } catch (e) { root.dataset.ui = was; mark(); fail(e); }
    finally { for (const x of radios) x.disabled = false; }
  });

  arrange();
  library();
  mark();
  window.Glass = { on, hero, journey, system, source, library, aiSection, activity, evaluation, pdf, personal, result, apply };
})();
