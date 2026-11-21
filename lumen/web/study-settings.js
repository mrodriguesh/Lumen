"use strict";
/* Lúmen Study AI — Configurações da IA (LUMEN AI SETTINGS): modelos, pesquisa, memória, personalização, privacidade e
   permissões, conectores, desempenho, projetos, atividades e "Seus dados no Lúmen". Cada controle grava na hora em
   /api/study/settings (validado no servidor). Segredos nunca voltam para a tela: só "há chave" ou "não há". */
(() => {
  const L = window.lumenStudy;
  if (!L) return;
  const { h, ic, btn, api, guard, when, n, dialog, toast, download } = L;
  const SECTIONS = [["models", "Modelos", "cpu"], ["search", "Pesquisa", "search"], ["memory", "Memória", "book"], ["personal", "Personalização", "pen"], ["adult", "Perfil adulto", "shield"],
    ["voice", "Voz", "volume"], ["pdf", "PDFs e imagens", "image"], ["privacy", "Privacidade e permissões", "shield"], ["connectors", "Conectores", "plug"], ["performance", "Desempenho", "sync"],
    ["catalog", "Catálogo", "book"], ["evaluation", "Avaliação local", "check"],
    ["projects", "Projetos", "library"], ["activity", "Atividades", "clock"], ["data", "Seus dados no Lúmen", "folder"]];
  let host, current = "models", close = () => {}, st = null;

  async function save(section, key, value, msg = "Salvo.") {
    const r = await guard(() => api("/api/study/settings", { [section]: { [key]: value } }), msg);
    if (r) st.settings = r.settings;
    return r;
  }
  const row = (label, hint, control) => h("div", { class: "set-row" }, h("span", { class: "set-text" }, h("strong", { text: label }), hint ? h("small", { text: hint }) : null), control);
  function toggle(section, key, label, hint, before) {
    const input = h("input", { type: "checkbox", role: "switch", "aria-label": label, ...(st.settings[section][key] ? { checked: true } : {}) });
    input.addEventListener("change", async () => {
      if (before && !(await before(input.checked))) { input.checked = !input.checked; return; }
      if (!(await save(section, key, input.checked))) input.checked = !input.checked;
      else if (section === "adult") render(host, current);  // a disponibilidade e o chip da conversa dependem do estado
      else if (section === "voice" && key.startsWith("call_")) window.lumenStudy?.syncCallSettings?.({ [key]: input.checked });
    });
    return row(label, hint, h("label", { class: "st-switch" }, input, h("span", { class: "sr", text: label })));
  }
  function select(section, key, label, options, hint) {
    const isNum = typeof st.settings[section][key] === "number";
    const s = h("select", { "aria-label": label }, options.map(([v, l]) => h("option", { value: String(v), text: l })));
    s.value = String(st.settings[section][key]);
    // O modelo para responder muda o que o "Automático" do modelo rápido mostra: redesenha a seção.
    s.addEventListener("change", async () => {
      const val = isNum ? parseInt(s.value, 10) : s.value;
      if (await save(section, key, val)) {
        if (key === "local" || section === "adult") render(host, current);
        if (section === "voice" && key.startsWith("call_")) window.lumenStudy?.syncCallSettings?.({ [key]: val });
      }
    });
    return row(label, hint, s);
  }
  function number(section, key, label, hint, min, max, step = 1) {
    const i = h("input", { type: "number", min, max, step, "aria-label": label, class: "st-num" });
    i.value = st.settings[section][key];
    i.addEventListener("change", () => save(section, key, step < 1 ? parseFloat(i.value) : parseInt(i.value, 10)));
    return row(label, hint, i);
  }
  function text(section, key, label, hint, rows = 0, max = 200) {
    const i = rows ? h("textarea", { rows, maxlength: String(max), "aria-label": label }) : h("input", { type: "text", maxlength: String(max), "aria-label": label });
    i.value = st.settings[section][key];
    i.addEventListener("change", () => save(section, key, i.value));
    return rows ? h("label", { class: "field st-wide" }, label, i, hint ? h("span", { class: "field-hint", text: hint }) : null) : row(label, hint, i);
  }
  const card = (title, lead, ...kids) => h("section", { class: "card st-set-card" }, h("h3", { class: "t-h3", text: title }), lead ? h("p", { class: "muted", text: lead }) : null, kids);

  async function render(target, section, onClose) {
    host = target; current = section || current; close = onClose || close;
    st = await guard(() => api("/api/study/state"));
    if (!st) return;
    const nav = h("nav", { class: "settings-nav st-set-nav", "aria-label": "Seções das configurações" },
      // a seção que já está aberta não é redesenhada de novo: um 2º desenho trocaria os campos enquanto se digita
      SECTIONS.map(([id, label, icon]) => h("button", { type: "button", "aria-current": String(id === current), onclick: () => { if (id !== current) render(host, id); } }, ic(icon), label)));
    const panel = h("div", { class: "st-set-panel" });
    host.replaceChildren(
      h("header", { class: "st-set-head" }, btn("Voltar ao Cérebro", () => close(), { icon: "arrow-left", cls: "btn sm ghost" }),
        h("p", { class: "eyebrow", text: "Lumen AI Settings" }), h("h2", { class: "t-h1", text: "Configurações da IA" })),
      h("div", { class: "settings-layout st-set-layout" }, nav, panel));
    panel.append(...(await ({ models, search, memory, personal, adult, voice, pdf, privacy, connectors, performance, projects, activity, data, catalog, evaluation })[current]()).filter(Boolean));
    panel.querySelector("h3")?.setAttribute("tabindex", "-1");
    window.Glass?.aiSection(panel, SECTIONS.find((x) => x[0] === current));  // Glass: cabeçalho da seção (ladrilho, título e subtítulo), oculto no Clássico
  }

  // --- Perfil adulto (D92) ------------------------------------------------------------------------------------------
  async function adult() {
    const s = st.settings, a = st.providers.adult, o = st.providers.ollama, chosen = s.adult.model || s.resolved.adult;
    const names = [...new Set([...(o.models || []), ...(s.adult.model ? [s.adult.model] : [])])];
    const state = !s.adult.enabled ? "Desligado: só o modelo principal responde."
      : !o.running ? "O Ollama não está rodando. Abra o aplicativo Ollama."
      : !chosen ? "Escolha o modelo do perfil abaixo."
      : a.installed ? `Pronto: ${chosen}` : `O modelo “${chosen}” não está instalado.`;
    const how = { auto: "decide pelo pedido, no seu PC", main: "só quando você escolher na conversa", adult: "sempre" }[s.adult.mode];
    return [card("Perfil adulto", "Um modelo local separado para linguagem informal, palavrões e conteúdo adulto consensual entre maiores de 18 anos. O modelo principal continua o mesmo para todo o resto.",
        toggle("adult", "enabled", "Usar o perfil adulto", "Desligado, nada muda: o Lúmen nunca troca de modelo sozinho."),
        select("adult", "mode", "Quando usar", [["auto", "Automático (pelo pedido)"], ["main", "Só quando eu escolher"], ["adult", "Sempre"]],
          "Automático: o Lúmen lê a intenção do pedido e da conversa, no seu computador, antes de responder. Sua escolha na conversa (chip de modo e esforço, ou /perfil) sempre vale mais."),
        select("adult", "model", "Modelo do perfil", [["", `Recomendado (${s.resolved.adult || "nenhum ainda"})`], ...names.map((m) => [m, m])],
          "Só modelos instalados no Ollama. O perfil nunca usa o modelo principal nem a nuvem."),
        chosen && !a.installed && o.running ? h("div", { class: "st-source-actions" }, btn(`Baixar ${chosen}`, async () => {
          if (await window.ui.confirm(`O Ollama vai baixar ${chosen} para o seu PC.`, { title: "Baixar modelo?", ok: "Baixar" })) await guard(() => api("/api/study/pull", { model: chosen }), "Download iniciado. Acompanhe em Fontes.");
        }, { icon: "download", cls: "btn sm primary" })) : null),
      card("Estilo e geração", "Valem só para o perfil adulto; as instruções gerais e a temperatura do modelo principal não mudam.",
        text("adult", "instructions", "Instruções de estilo do perfil", "Ex.: tom, como tratar você, o que evitar. Soma-se às regras do Lúmen; não as substitui.", 5, 2000),
        number("adult", "temperature", "Temperatura do perfil", "Mais alta deixa o texto mais solto e criativo (0 a 1,5).", 0, 1.5, .1)),
      card("Situação", state,
        h("p", { class: "muted", text: s.adult.enabled ? `Agora: ${how}. Modelo principal (inalterado): ${s.resolved.local}.` : `Modelo principal (inalterado): ${s.resolved.local}.` }),
        h("p", { class: "faint" }, ic("info"), " A decisão automática usa só o texto da sua mensagem e o histórico da conversa; documentos, páginas e resultados de ferramentas nunca a decidem. Nada é enviado à nuvem para decidir. Conversas do perfil não geram título nem memórias automáticas.")),
    ];
  }

  async function catalog() {
    const r = await guard(() => api("/api/study/registry?full=1"));
    if (!r) return [];
    const editSkill = async (item) => {
      const old = item ? await guard(() => api("/api/study/registry?skill=" + encodeURIComponent(item.id))) : {};
      if (!old) return;
      let draft = old;
      while (true) {
        const v = await dialog({ title: item ? "Editar sua skill" : "Criar sua skill", wide: true, ok: "Salvar skill", message: "Instruções em texto. $ARGUMENTS recebe o assunto. As permissões do Lúmen continuam valendo.",
          fields: [{ name: "name", label: "Nome do comando", value: draft.name, hint: "Letras minúsculas, números e hífens." },
            { name: "description", label: "Descrição", value: draft.description }, { name: "args", label: "Argumentos", value: draft.args },
            { name: "body", label: "Instruções", type: "textarea", rows: 10, value: draft.body }] });
        if (!v) return;
        draft = v;
        if (item && v.name !== item.name) { toast("Mantenha o nome ao editar. Para outro comando, crie uma nova skill.", "warning"); continue; }
        if (await guard(() => api("/api/study/registry", { action: "save", ...v, revision: old.revision || "" }), "Skill salva.")) { L.S.menu = null; render(host, "catalog"); return; }
      }
    };
    const testSkill = async (item) => {
      const v = await dialog({ title: "Testar /" + item.name, ok: "Testar", fields: [{ name: "args", label: "Assunto para testar", placeholder: item.args }] });
      if (!v) return;
      L.S.menu = null; close(); L.setTab("chat"); L.input().value = "/" + item.name + (v.args ? " " + v.args : ""); L.input().form.requestSubmit();
    };
    const skills = r.menu.filter((x) => x.kind === "skill");
    const bytes = (n) => n == null ? "Não informado" : `${(n / 2 ** 30).toFixed(2)} GB`;
    return [card("Catálogo", "Comandos, skills e integrações vêm do mesmo registro que alimenta o menu /. Informações técnicas ficam recolhidas.",
      h("details", {}, h("summary", { text: `Comandos (${r.menu.filter((x) => x.kind === "command").length})` }),
        h("ul", { class: "st-list" }, r.menu.filter((x) => x.kind === "command").map((x) => h("li", {}, h("code", { text: `/${x.name} ${x.args}` }), h("p", { text: x.description })))),
        h("p", { class: "muted", text: "Ctrl+Shift+K: compactar a conversa. Ctrl+K: paleta do aplicativo. Ctrl+V: colar imagem." })),
      h("details", { open: true }, h("summary", { text: `Skills (${skills.length})` }), btn("Criar skill", () => editSkill(), { icon: "plus", cls: "btn sm" }),
        skills.map((x) => {
          const input = h("input", { type: "checkbox", role: "switch", "aria-label": "Ativar /" + x.name, ...(x.enabled ? { checked: true } : {}), onchange: async (e) => {
            const el = e.currentTarget; el.disabled = true;
            const ok = await guard(() => api("/api/study/registry", { action: "enable", id: x.id, enabled: el.checked }));
            if (ok) { L.S.menu = null; render(host, "catalog"); } else { el.checked = !el.checked; el.disabled = false; }
          } });
          return h("article", { class: "st-catalog-skill" }, h("div", {}, h("strong", { text: "/" + x.name }), h("small", { class: "muted", text: ` · ${x.origin} · ${x.args}` }), h("p", { text: x.description })),
            h("div", { class: "st-source-actions" }, h("label", { class: "st-switch" }, input),
              btn("Testar /" + x.name, () => testSkill(x), { cls: "btn sm ghost", attrs: { disabled: !x.enabled } }),
              x.origin === "usuario" ? btn("Editar /" + x.name, () => editSkill(x), { cls: "btn sm ghost", icon: "pen" }) : null));
        }))),
      card("Integrações", "Desligar uma fonte tira suas notas da pesquisa. Provedores e voz têm controles próprios; o catálogo não encerra aplicativos.",
        ...r.integrations.filter((x) => x.id !== "anthropic" && x.id !== "openai").map((x) => h("div", { class: "st-catalog-integration" }, h("strong", { text: `${x.name} · ${x.on ? "Disponível" : "Inativa ou indisponível"}` }),
          h("p", { class: "muted", text: x.access }), x.version ? h("small", { text: x.version }) : null,
          ["notion", "obsidian", "files", "web"].includes(x.id) ? toggle("search", x.id, "Usar " + x.name, "Vale para consultas futuras.") :
            btn("Configurar " + x.name, () => render(host, x.id === "voice" ? "voice" : "models"), { cls: "btn sm ghost" })))),
      card("Permissões e modelos por papel", "Os valores de tamanho e VRAM vêm do Ollama disponível agora. VRAM vazia significa que o modelo não está carregado ou o serviço não informou.",
        btn("Ajustar permissões", () => render(host, "privacy"), { cls: "btn sm" }),
        h("details", {}, h("summary", { text: "Ferramentas e níveis de acesso" }), h("ul", { class: "st-list" }, r.permissions.map((x) => h("li", { text: `${x.name} · nível ${x.level} · ${x.description}` })))),
        ...r.roles.map((x) => h("details", { class: "st-model-role" }, h("summary", { text: `${x.role} · ${x.model}` }),
          h("p", { text: `Instalação: ${x.installed == null ? "Consulte a seção do motor" : x.installed ? "Disponível" : "Indisponível"}` }),
          x.location ? h("p", { class: "st-submission", text: x.location }) : null,
          h("p", { class: "faint", text: `Tamanho: ${bytes(x.size)} · VRAM em uso: ${bytes(x.vram)}` }),
          btn("Configurar " + x.role, () => render(host, x.section), { cls: "btn sm ghost" }))),
        h("details", {}, h("summary", { text: "Medições anteriores neste PC (01/11/2026)" }), L.md(r.measurements || "Relatório de medições indisponível."))),
      card("Instalados por este trabalho", "Registro histórico das instalações e remoções. Versões e locais registrados na documentação; nenhum download é iniciado ao abrir o catálogo.",
        h("details", {}, h("summary", { text: `${r.installations.length} registros` }), h("ul", { class: "st-list" }, r.installations.map((x) => h("li", {},
          h("strong", { text: `${x.date} · ${x.name}` }), h("p", { text: `${x.version} · ${x.size} · ${x.license}` }), h("p", { class: "st-submission", text: x.location }), h("p", { class: "muted", text: x.reason }))))))];
  }

  async function evaluation() {
    const r = await guard(() => api("/api/study/evaluation"));
    if (!r) return [];
    const sec = card("Avaliação local", "Respostas marcadas com 👍/👎 e suas correções formam casos para comparar versões de modelos e prompts. Os pesos da IA não mudam.",
      h("p", { text: `${r.cases.length} caso(s). As fontes guardadas com a resposta acompanham a exportação.` }),
      h("details", {}, h("summary", { text: "O que o Automático aprendeu com suas escolhas" }),
        h("p", { class: "muted", text: "Conta as últimas 200 trocas manuais. Uma maioria de pelo menos três trocas ajusta pedidos sem indicação explícita. Nunca escolhe Máximo nem cria atividades por hábito. Usar memória desligado e conversas temporárias não usam esse ajuste. Apagar o Histórico de atividades zera as contagens." }),
        h("ul", { class: "st-list" }, (r.routing || []).map((x) => h("li", { text: `${x.field === "mode" ? "Função" : "Esforço"}: ${(x.field === "mode" ? L.INTENT_LABEL : L.EFFORT_LABEL)[x.from] || x.from} → ${(x.field === "mode" ? L.INTENT_LABEL : L.EFFORT_LABEL)[x.to] || x.to} · ${x.count} troca(s)` })))),
      btn("Exportar conjunto de avaliação", () => download("lumen-avaliacao.json", JSON.stringify(r, null, 2), "application/json"), { icon: "download", cls: "btn sm primary" }),
      h("details", {}, h("summary", { text: "Como comparar uma versão local" }), h("p", { text: "Na pasta do projeto, execute o script com o conjunto exportado e escolha um nome novo para cada resultado:" }),
        h("pre", { class: "st-submission", text: '.venv\\Scripts\\python.exe bench/study_eval.py "D:\\Lumen\\lumen-avaliacao.json" --out "D:\\Lumen\\avaliacao-rodada1.json" --model qwen3.5:4b' }),
        h("p", { class: "muted", text: "O script isola os dados e usa somente o Ollama, sem ferramentas ou escrita externa. A triagem automática pode errar: compare as respostas e justificativas. Casos com avaliação negativa sem correção exigem revisão humana." })),
      h("ul", { class: "st-list" }, r.cases.map((c) => h("li", {}, h("details", {}, h("summary", { text: `${c.rating > 0 ? "Boa" : c.rating < 0 ? "Ruim" : "Corrigida"} · ${c.question.slice(0, 120)}` }),
        h("p", { class: "st-submission", text: c.reference }), c.correction ? h("p", {}, h("strong", { text: "Sua correção: " }), c.correction) : null)))),
      btn("Gerenciar estes dados", () => render(host, "data"), { cls: "btn sm ghost" }));
    window.Glass?.evaluation(sec, r.cases.length);  // Glass: contador, estado vazio e a trilha Avaliar → Registrar → Comparar (ocultos no Clássico)
    return [sec];
  }

  // --- Modelos ------------------------------------------------------------------------------------------------------
  async function pdf() {
    // Os comandos e as listas ficam aqui uma vez só: o texto do Clássico e os cartões do Glass saem dos mesmos valores.
    const F = { pdf: "/pdf [tipo] [assunto]", image: "/imagem [proporção] [descrição]", map: "/mapa-mental",
      types: "apostila, revisao, cornell, exercicios, flashcards, plano, simulado, mapa e explicacao", ratios: "quadrada, paisagem, retrato e capa",
      files: "Os arquivos ficam na mídia dos Estudos, no D:, e são apagados com a conversa." };
    const sec = card("PDFs e imagens", `Use ${F.pdf} ou ${F.image} na conversa.`,
      toggle("pdf", "dark", "PDF com fundo escuro", "Desligado: fundo claro para impressão. Papel A4."),
      toggle("pdf", "cover_image", "Ilustração na capa da apostila", "No máximo uma imagem por apostila. Os outros tipos usam apenas o conteúdo e os diagramas."),
      h("p", { class: "muted", text: `Tipos: ${F.types}.` }),
      h("p", { class: "muted", text: `Proporções: ${F.ratios}. Para texto e relações precisas, use ${F.map}. ${F.files}` }));
    window.Glass?.pdf(sec, F);  // Glass: os mesmos controles e textos em quatro cartões (ocultos no Clássico)
    return [sec];
  }
  async function models() {
    const o = st.providers.ollama, s = st.settings;
    const local = [["", `Automático (${s.resolved.local})`], ...o.models.map((m) => [m, m])];
    // Sem modelo para responder, a tela diz o que fazer pelo fluxo que já existe (Ajustes → IA local); nada é baixado sozinho.
    const missing = !o.running ? "O Ollama não está rodando. Abra o aplicativo Ollama."
      : !o.models.length ? "Nenhum modelo de chat está instalado no Ollama."
      : !o.installed ? `O modelo “${o.model}” não está instalado.` : "";
    return [
      card("Provedor de texto", "O Lúmen usa só a IA local (Ollama): ela roda no seu PC, sem cota de API, e o texto da conversa não sai dele. Não há IA em nuvem no Lúmen.",
        row("Provedor", "Fixo. Nenhuma IA em nuvem faz parte do Lúmen.", h("strong", { text: "IA local (Ollama)" }))),
      card("IA local", o.running ? `Ollama rodando · ${o.models.length} modelo(s) instalado(s).` : "O Ollama não está rodando. Abra o aplicativo Ollama.",
        missing ? h("p", { class: "faint", role: "status" }, ic("info"), ` ${missing} A IA local só fica pronta com um modelo instalado: escolha ou baixe um em Ajustes → IA local (Ollama). O Lúmen não baixa modelos sozinho.`) : null,
        select("models", "local", "Modelo para responder", local, "Automático: o que se saiu melhor na medição feita neste PC. Se ele não estiver instalado, vale o modelo dos Ajustes."),
        select("models", "fast", "Modelo rápido", [["", `Automático (${s.resolved.fast})`], ...o.models.map((m) => [m, m])], "Entende a pergunta e propõe memórias. Automático: o mesmo modelo de responder, para não trocar de modelo a cada pergunta."),
        select("models", "max", "Modelo do esforço Máximo", [["", `Automático (${s.resolved.max})`], ...o.models.map((m) => [m, m])], "O maior modelo que cabe na placa. Carregar outro modelo leva até 2 minutos na primeira vez."),
        number("models", "temperature", "Temperatura", "Mais baixa = mais fiel às fontes.", 0, 1, .1),
        number("models", "context_chars", "Texto das fontes por resposta", "Caracteres de trechos que entram no contexto (4.000 a 120.000).", 4000, 120000, 1000),
        toggle("models", "stream", "Mostrar a resposta enquanto é escrita", "Desligado, a resposta aparece inteira no fim.")),
      card("Imagens e vídeo", "Imagens e capas são geradas no seu PC (gerador local, sem cota de API). O Lúmen não gera vídeo.",
        h("p", { class: "faint" }, ic("info"), " Vídeos criados antes continuam no histórico.")),
      card("Busca por significado", o.embed_installed ? `Modelo ${o.embed} instalado.` : `Modelo ${o.embed} não instalado.`,
        text("models", "embed", "Modelo de embeddings", "Trocar o modelo recalcula os vetores em segundo plano."),
        !o.embed_installed ? h("div", { class: "st-source-actions" }, btn(`Baixar ${o.embed}`, async () => {
          if (await window.ui.confirm(`O Ollama vai baixar ${o.embed} para o seu PC.`, { title: "Baixar modelo?", ok: "Baixar" })) await guard(() => api("/api/study/pull", { model: o.embed }), "Download iniciado. Acompanhe em Fontes.");
        }, { icon: "download", cls: "btn sm primary" })) : null),
      card("Privacidade", "As notas, o texto da conversa e o áudio não saem do PC: a IA, as vozes e a busca por significado são locais.",
        h("p", { class: "faint" }, ic("info"), " Os registros do Lúmen guardam apenas ação, modelo e contagens, nunca o conteúdo.")),
    ];
  }

  // --- Pesquisa -----------------------------------------------------------------------------------------------------
  async function search() {
    return [card("Onde pesquisar", "Fontes que entram nas buscas e respostas (um projeto pode restringir mais).",
      toggle("search", "notion", "Notion"), toggle("search", "obsidian", "Obsidian"), toggle("search", "files", "Arquivos de pastas autorizadas"),
      toggle("search", "web", "Internet", "Ler páginas públicas e pesquisar pelo navegador (pesquisa guiada no Edge, com a IA local). A consulta vai ao buscador.")),
    card("Como pesquisar", null,
      toggle("search", "hybrid", "Busca híbrida", "Palavras e significado juntos. Desligada, só palavras."),
      number("search", "max_sources", "Número máximo de fontes", "Documentos por resposta (3 a 20).", 3, 20),
      toggle("search", "scientific", "Preferir fontes científicas", "Quando a IA usar a internet, prioriza artigos revisados, universidades e órgãos oficiais."),
      number("search", "cache_days", "Cache de páginas da internet (dias)", "0 = sempre ler de novo.", 0, 90),
      toggle("search", "images", "Ler as imagens das notas", "Prints e fotos no Obsidian e no Notion viram texto pesquisável, lido pela IA local em segundo plano. As cópias ficam no D:."))];
  }

  // --- Memória ------------------------------------------------------------------------------------------------------
  const CATS = { profile: "Perfil", long_term: "Longo prazo", episodic: "Episódica", project: "Projeto", procedural: "Procedimental" };
  async function memory() {
    const filters = { q: "", category: "", status: "", project: "" };
    const list = h("div", { class: "st-mem-list" });
    async function load() {
      const r = await guard(() => api("/api/study/memories?" + new URLSearchParams(Object.entries(filters).filter(([, v]) => v))));
      if (!r) return;
      list.replaceChildren(r.memories.length ? "" : h("div", { class: "empty" }, ic("book", "empty-icon"), h("p", { text: filters.q || filters.category ? "Nenhuma memória com esses filtros." : "Nenhuma memória ainda. Elas aparecem conforme você conversa (se a memória automática estiver ligada) ou quando você cria uma." })));
      for (const m of r.memories) {
        const origin = m.origin?.type === "conversation" ? "De uma conversa" : m.origin?.type === "import" ? `Importada de ${m.origin.path || "arquivo"}` : m.origin?.type === "feedback" ? "De uma correção sua" : m.origin?.type === "analysis" ? "Da análise das suas avaliações" : "Criada por você";
        list.append(h("article", { class: "st-mem" + (m.status === "pending" ? " pending" : ""), dataset: { id: m.id } },
          h("div", { class: "st-mem-top" }, h("span", { class: "badge", text: m.category_label }), m.project_name ? h("span", { class: "badge", text: m.project_name }) : null,
            m.status === "pending" ? h("span", { class: "badge st-badge-warn", text: "Sugestão: aprovar?" }) : null),
          h("p", { class: "st-mem-text", text: m.content }),
          h("p", { class: "faint st-mem-meta", text: `${origin} · criada ${when(m.created)} · atualizada ${when(m.updated)} · usada ${m.uses}× · confiança ${Math.round((m.confidence || 0) * 100)}%` }),
          h("div", { class: "st-mem-actions" },
            m.status === "pending" ? btn("Aprovar", async () => { await guard(() => api("/api/study/memories", { action: "approve", id: m.id }), "Memória aprovada."); load(); }, { icon: "check", cls: "btn sm primary" }) : null,
            btn("Editar", async () => {
              const v = await dialog({ title: "Editar memória", fields: [{ name: "content", label: "Conteúdo", type: "textarea", rows: 3, value: m.content },
                { name: "category", label: "Categoria", type: "select", value: m.category, options: Object.entries(CATS) }], ok: "Salvar" });
              if (v) { await guard(() => api("/api/study/memories", { action: "update", id: m.id, content: v.content, category: v.category }), "Memória atualizada."); load(); }
            }, { icon: "pen", cls: "btn sm" }),
            btn(m.status === "pending" ? "Recusar" : "Excluir", async () => {
              if (m.status === "pending" || await window.ui.confirm("A memória, o índice de busca e os vetores dela serão apagados.", { title: "Excluir memória?", ok: "Excluir", danger: true })) {
                await guard(() => api("/api/study/memories", { action: m.status === "pending" ? "reject" : "delete", id: m.id }), "Memória excluída."); load();
              }
            }, { icon: "trash", cls: "btn sm ghost" }))));
      }
    }
    const q = h("input", { type: "search", placeholder: "Pesquisar memórias", "aria-label": "Pesquisar memórias" });
    let t = 0;
    q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { filters.q = q.value; load(); }, 250); });
    const cat = h("select", { "aria-label": "Categoria" }, h("option", { value: "", text: "Todas as categorias" }), Object.entries(CATS).map(([v, l]) => h("option", { value: v, text: l })));
    cat.addEventListener("change", () => { filters.category = cat.value; load(); });
    const status = h("select", { "aria-label": "Situação" }, [["", "Todas"], ["active", "Ativas"], ["pending", "Sugestões"]].map(([v, l]) => h("option", { value: v, text: l })));
    status.addEventListener("change", () => { filters.status = status.value; load(); });
    const proj = h("select", { "aria-label": "Projeto" }, h("option", { value: "", text: "Todos os escopos" }), h("option", { value: "global", text: "Só globais" }), (st.projects || []).map((p) => h("option", { value: p.id, text: p.name })));
    proj.addEventListener("change", () => { filters.project = proj.value; load(); });
    const file = h("input", { type: "file", accept: ".json,application/json", class: "sr", tabindex: "-1" });
    file.addEventListener("change", async () => {
      const f = file.files[0]; file.value = "";
      if (!f) return;
      try {
        const items = JSON.parse(await f.text());
        if (!Array.isArray(items)) throw new Error();
        const r = await guard(() => api("/api/study/memories", { action: "import", items: items.slice(0, 500) }));
        if (r) { toast(`${r.imported} memória(s) importada(s).`, "success"); load(); }
      } catch { toast("Arquivo inválido: use um JSON exportado pelo Lúmen.", "error"); }
    });
    setTimeout(load, 0);
    return [
      card("Memória e personalização", "O Lúmen usa essas informações para compreender melhor seus objetivos, preferências e projetos. Não é treinamento: o modelo não muda; a memória entra como contexto, e você vê, edita e apaga tudo aqui.",
        toggle("memory", "enabled", "Usar memória", "Desligado, nenhuma memória entra nas respostas."),
        toggle("memory", "auto", "Salvar novas memórias automaticamente", "As de confiança alta são salvas; as de confiança média viram sugestões para você aprovar."),
        toggle("memory", "projects", "Memória por projeto", "Cada projeto tem as próprias memórias, que não entram em outros projetos."),
        toggle("memory", "long_term", "Memória de longo prazo", "Objetivos e contexto duradouro."),
        toggle("memory", "history", "Guardar conversas no histórico", "Desligado, toda conversa nova é temporária."),
        toggle("memory", "temporary_private", "Conversa temporária com privacidade máxima", "A conversa temporária também não lê suas memórias.")),
      h("section", { class: "card st-set-card" },
        h("div", { class: "st-mem-head" }, h("div", {}, h("h3", { class: "t-h3", text: "Memórias salvas" }), h("p", { class: "muted", text: "Conteúdo, categoria, origem, data e relevância de cada memória." })),
          btn("Nova memória", async () => {
            const v = await dialog({ title: "Nova memória", fields: [{ name: "content", label: "O que o Lúmen deve lembrar", type: "textarea", rows: 3, placeholder: "Ex.: Prefere explicações com exemplos práticos." },
              { name: "category", label: "Categoria", type: "select", value: "profile", options: Object.entries(CATS).filter(([k]) => k !== "project") },
            ], ok: "Salvar" });
            if (v) { await guard(() => api("/api/study/memories", { action: "create", content: v.content, category: v.category }), "Memória salva."); load(); }
          }, { icon: "plus", cls: "btn sm primary" })),
        h("div", { class: "input-row st-mem-filters" }, h("label", { class: "search-field" }, ic("search"), q), cat, status, proj),
        list,
        h("div", { class: "st-source-actions st-mem-tools" },
          btn("Importar do Claude Code (cofre)", async () => {
            const r = await guard(() => api("/api/study/memories", { action: "import_preview" }));
            if (!r) return;
            if (!r.items.length) return toast("Nada para importar em C04 Claude Obsidian/04 Memory.", "info");
            const boxes = r.items.map((it) => { const c = h("input", { type: "checkbox", checked: true }); return [c, it]; });
            const body = h("div", { class: "st-import" }, h("p", { class: "muted", text: "Itens encontrados na memória do Claude Code no seu cofre. Escolha o que o Lúmen deve lembrar; o cofre não é alterado." }),
              h("ul", { class: "st-import-list" }, boxes.map(([c, it]) => h("li", {}, h("label", {}, c, h("span", { class: "badge", text: CATS[it.category] }), " ", it.content)))));
            if (!(await dialog({ title: "Importar memórias do cofre", body, ok: "Importar selecionadas", wide: true }))) return;
            const chosen = boxes.filter(([c]) => c.checked).map(([, it]) => it);
            const done = await guard(() => api("/api/study/memories", { action: "import", items: chosen }));
            if (done) { toast(`${done.imported} memória(s) importada(s).`, "success"); load(); }
          }, { icon: "obsidian", cls: "btn sm" }),
          btn("Analisar minhas preferências", async () => { const r = await guard(() => api("/api/study/memories", { action: "analyze" })); if (r) { toast(`${r.suggested.length} sugestão(ões) criada(s) a partir das suas avaliações.`, "success"); load(); } }, { icon: "sparkle", cls: "btn sm" }),
          btn("Exportar", async () => { const r = await guard(() => api("/api/study/memories", { action: "export" })); if (r) download(r.filename, r.content, "application/json"); }, { icon: "download", cls: "btn sm" }),
          btn("Importar JSON", () => file.click(), { icon: "upload", cls: "btn sm" }), file,
          btn("Limpar uma categoria", async () => {
            const v = await dialog({ title: "Limpar categoria", message: "As memórias da categoria, com o índice e os vetores delas, serão apagadas.", danger: true, ok: "Limpar",
              fields: [{ name: "category", label: "Categoria", type: "select", value: "episodic", options: Object.entries(CATS) }] });
            if (v) { await guard(() => api("/api/study/memories", { action: "clear", category: v.category }), "Categoria limpa."); load(); }
          }, { icon: "trash", cls: "btn sm ghost" }),
          btn("Limpar todas as memórias", async () => {
            const v = await dialog({ title: "Limpar todas as memórias?", danger: true, require: "APAGAR", ok: "Apagar todas",
              message: "Serão apagadas todas as memórias (perfil, longo prazo, episódicas, de projetos e procedimentais), com o índice de busca e os vetores delas. Conversas, projetos e suas notas não são tocados. Não dá para desfazer." });
            if (v) { await guard(() => api("/api/study/memories", { action: "clear_all", confirm: "APAGAR" }), "Todas as memórias foram apagadas."); load(); }
          }, { icon: "trash", cls: "btn sm danger" }))),
    ];
  }

  // --- Personalização -----------------------------------------------------------------------------------------------
  async function personal() {
    const sec = card("Personalização", "Como o Lúmen responde. As regras de fontes (citar só o que encontrou) continuam valendo sempre.",
      text("personal", "instructions", "Instruções personalizadas", "Ex.: Explique como se eu fosse aluno do 1º ano de psicologia; use analogias.", 5, 4000),
      select("personal", "detail", "Nível de detalhamento", [["breve", "Breve"], ["equilibrado", "Equilibrado"], ["detalhado", "Detalhado"]]),
      select("personal", "tone", "Tom de resposta", [["didatico", "Didático"], ["direto", "Direto"], ["conversacional", "Conversacional"], ["formal", "Formal"]]),
      select("personal", "format", "Formato preferido", [["estruturado", "Estruturado com títulos"], ["topicos", "Em tópicos"], ["texto", "Texto corrido"]]),
      select("personal", "language", "Idioma", [["pt-BR", "Português do Brasil"], ["en", "Inglês"], ["es", "Espanhol"]]),
      text("personal", "study", "Preferências de estudo", "Ex.: estudo à noite, gosto de revisões curtas.", 3, 2000));
    window.Glass?.personal(sec);  // Glass: instruções, estilo e preferências em três cartões (os mesmos campos)
    return [sec];
  }

  // --- Voz (fase 6) ---------------------------------------------------------------------------------------------------
  // O motor, a voz padrão e uma por uso, o jeito de falar e a leitura. As vozes vêm do Voice Studio pelo backend.
  async function voice() {
    const V = window.lumenVoice, vs = await guard(() => api("/api/study/voice/state"));
    if (!V || !vs) return [card("Voz", "A voz não carregou. Recarregue a janela.")];
    const s = vs.settings, list = vs.voicestudio.running ? (await api("/api/study/voice/voices").catch(() => ({ voices: [] }))).voices : [];
    const micsRes = await api("/api/study/voice/mics").catch(() => ({ microphones: [] }));
    const mics = micsRes.microphones || micsRes.mics || [];
    const redraw = () => render(host, "voice");
    const pick = (key, label, hint) => {
      const def = list.find((v) => v.id === s.voice_id);
      const sel = h("select", { "aria-label": label }, h("option", { value: "", text: `A padrão (${def?.name || "voz padrão"})` }),
        list.map((v) => h("option", { value: v.id, text: `${v.name} · ${V.kindLabel(v).toLowerCase()}` })));
      sel.value = list.some((v) => v.id === s[key]) ? s[key] : "";
      sel.addEventListener("change", () => save("voice", key, sel.value, "Voz salva."));
      return row(label, hint, sel);
    };
    const def = list.find((v) => v.id === s.voice_id);
    const status = vs.voicestudio.running ? `Voice Studio pronto${vs.voicestudio.owner === "lumen" ? " (em segundo plano, sem janela)" : " (o app está aberto)"}${vs.voicestudio.version ? " · v" + vs.voicestudio.version : ""}${vs.voicestudio.gpu ? " · " + vs.voicestudio.gpu : ""}.`
      : !vs.voicestudio.installed ? "O Voice Studio não está instalado neste PC."
        : s.vs_autostart ? "Voice Studio desligado: liga sozinho, sem janela, quando a voz for usada." : "O Voice Studio está fechado.";
    const sampleBox = h("textarea", { rows: 2, maxlength: "400", "aria-label": "Texto para testar a voz" });
    sampleBox.value = "Olá! Eu sou a voz dos seus estudos no Lúmen. Vamos revisar juntos o que você aprendeu hoje.";
    const whoLine = h("p", { class: "t-caption muted", "aria-live": "polite" });
    const testAv = V.avatar({ name: vs.who?.name || "?", voice: vs.who?.voice, image: vs.who?.image });
    async function test(text) {
      whoLine.textContent = "Gerando…";
      try {
        const r = await V.api("/api/study/voice/test", { text: text || sampleBox.value });
        whoLine.textContent = `${r.who.name} · ${V.kindLabel(r.who).toLowerCase()} · ${String(r.seconds).replace(".", ",")} s${r.who.note ? " · " + r.who.note : ""}`;
        await V.playClip(r.audio, testAv);
      } catch (e) { whoLine.textContent = ""; toast([e.message, e.action].filter(Boolean).join(" "), "error"); }
    }
    // velocidade: o valor aparece enquanto arrasta; ao soltar, grava e toca a prévia
    const speedOut = h("output", { class: "st-num t-caption", text: s.speed.toFixed(2).replace(".", ",") + "×" });
    const speed = h("input", { type: "range", min: "0.7", max: "1.3", step: "0.05", "aria-label": "Velocidade da fala", class: "st-range" });
    speed.value = String(s.speed);
    speed.addEventListener("input", () => { speedOut.textContent = parseFloat(speed.value).toFixed(2).replace(".", ",") + "×"; });
    speed.addEventListener("change", async () => { if (await save("voice", "speed", parseFloat(speed.value), "Velocidade salva.")) { s.speed = parseFloat(speed.value); test("Esta é a nova velocidade da minha voz."); } });
    const engineSel = h("select", { "aria-label": "Motor de voz" }, [["voicestudio", "Voice Studio (as vozes do seu PC)"], ["chatterbox", "Chatterbox pt-br (local)"], ["off", "Desligada"]].map(([v, l]) => h("option", { value: v, text: l })));
    engineSel.value = s.engine;
    engineSel.addEventListener("change", async () => { if (await save("voice", "engine", engineSel.value, "Motor salvo.")) redraw(); });
    const toModels = () => { close(); document.querySelector("#nav-integrations")?.click(); setTimeout(() => document.querySelector("#itab-voicestudio")?.click(), 50); };
    const q = (key, label, hint) => select("voice", key, label, [["fast", `Rápido (${vs.steps.fast} passos)`], ["balanced", `Equilibrado (${vs.steps.balanced} passos)`],
      ["quality", `Qualidade (${vs.steps.quality} passos)`], ["max", `Máximo (${vs.steps.max} passos)`]], hint);
    const narrator = (() => {
      const sel = h("select", { "aria-label": "Voz do narrador" }, h("option", { value: "", text: "Escolha uma voz" }),
        list.filter((v) => v.id !== s.voice_id).map((v) => h("option", { value: v.id, text: `${v.name} · ${V.kindLabel(v).toLowerCase()}` })));
      sel.value = list.some((v) => v.id === s.narrator_voice) ? s.narrator_voice : "";
      sel.addEventListener("change", () => save("voice", "narrator_voice", sel.value, "Narrador salvo."));
      return row("Voz do narrador", "Lê o título, as perguntas e o fim; a voz padrão responde.", sel);
    })();
    return [
      card("Motor", status,
        row("Motor de voz", "O Voice Studio usa as vozes clonadas e criadas por você. O Chatterbox roda no Lúmen, com a voz padrão dele.", engineSel),
        s.engine === "voicestudio" ? toggle("voice", "vs_autostart", "Ligar o Voice Studio sozinho", "Com o app fechado, o Lúmen liga a voz sem abrir janela e desliga depois de parada. O app, se você abrir, usa a mesma voz.") : null,
        s.engine === "voicestudio" ? number("voice", "vs_idle_minutes", "Desligar depois de parada (minutos)", "Só a voz que o Lúmen ligou, e nunca com o app aberto (5 a 240).", 5, 240) : null,
        s.engine === "voicestudio" ? toggle("voice", "vs_warm_on_open", "Deixar a voz pronta ao abrir o Lúmen", "Carrega o modelo na abertura (cerca de 2,7 GB na placa). Desligado, a voz liga no primeiro uso.") : null,
        select("voice", "fallback", "Se a voz do Voice Studio não ligar", [["chatterbox", "Usar o Chatterbox pt-br (avisando)"], ["off", "Não falar"]], vs.chatterbox ? "A tela sempre diz qual voz está falando." : "O Chatterbox não está instalado: sem o Voice Studio, a voz fica desligada."),
        s.engine === "voicestudio" ? h("div", { class: "st-source-actions" }, btn("Modelos de voz", toModels, { icon: "cpu", cls: "btn sm" }),
          btn("Abrir o app", () => V.openVS(), { icon: "external", cls: "btn sm ghost" })) : null,
        vs.problem ? h("p", { class: "callout" }, ic("alert"), h("span", { text: [vs.problem.message, vs.problem.action].filter(Boolean).join(" ") })) : null),
      s.engine === "voicestudio" ? card("Qualidade e rapidez", "Os passos do modelo em cada pedido do Lúmen. O nível do próprio Voice Studio não muda.",
        q("chat_quality", "Fala do chat", "Medido neste PC: 8 passos 1,9 s até o 1º som, 12 passos 2,2 s, 16 passos 2,7 s."),
        q("long_quality", "Áudios longos (resumo e revisão)", "Mais passos custam tempo, não memória da placa."),
        number("voice", "cache_mb", "Frases guardadas (MB)", "“Ouvir” de novo e as frases repetidas saem na hora. 0 = não guardar. Conversas temporárias e o Treino falado nunca são guardados.", 0, 5000),
        h("div", { class: "st-source-actions" }, btn("Limpar frases guardadas", async () => {
          const r = await guard(() => V.api("/api/study/voice/cache", { action: "clear" }), "Frases guardadas apagadas.");
          if (r) redraw();
        }, { icon: "trash", cls: "btn sm ghost" }))) : null,
      s.engine === "voicestudio" && list.length > 1 ? card("Revisão a duas vozes", "Na revisão em áudio, o narrador pergunta e a voz padrão responde.",
        toggle("voice", "review_dialog", "Revisão em formato de conversa", "Sem um narrador escolhido, a revisão sai numa voz só."), narrator) : null,
      s.engine === "voicestudio" ? await pronunciationCard(vs) : null,
      s.engine === "voicestudio" ? card("Voz padrão", def ? "Fala no chat, nos resumos e nas revisões, a não ser que um uso tenha outra voz." : "A voz padrão não está no Voice Studio agora.",
        list.length ? h("ul", { class: "vc-voices" }, (def ? [def] : list.slice(0, 1)).map((v) => V.voiceRow(v, { isDefault: !!def, onEdit: V.openVS }))) : h("p", { class: "muted t-sm", text: "Abra o Voice Studio para ver as vozes." }),
        list.length > 1 ? row("Trocar a voz padrão", "Também dá para escolher em Integrações → Voice Studio.", (() => {
          const sel = h("select", { "aria-label": "Voz padrão" }, list.map((v) => h("option", { value: v.id, text: `${v.name} · ${V.kindLabel(v).toLowerCase()}` })));
          sel.value = def ? def.id : list[0].id;
          sel.addEventListener("change", async () => { if (await save("voice", "voice_id", sel.value, "Voz padrão salva.")) redraw(); });
          return sel;
        })()) : null) : null,
      s.engine === "voicestudio" && list.length ? card("Uma voz por uso", "Vazio = a voz padrão. No Treino falado, cada personagem pode ter outra voz.",
        pick("chat_voice", "Conversa (Ouvir e voz no chat)"), pick("call_voice", "Conversa por voz (chamada em tempo real)"),
        pick("summary_voice", "Resumo em áudio das aulas"),
        pick("review_voice", "Revisão em áudio"), pick("practice_voice", "Treino falado")) : null,
      callSettingsCard(s, vs, list, mics, pick, V),
      card("Jeito de falar", s.engine === "chatterbox" ? "O Chatterbox fala na velocidade dele; velocidade, estilo e idioma valem para o Voice Studio." : null,
        row("Velocidade", "Ao soltar, a voz fala uma frase na velocidade nova.", h("span", { class: "input-row" }, speed, speedOut)),
        select("voice", "language", "Idioma", [["pt", "Português (pt)"], ["", "Automático (o Voice Studio detecta)"]], "Medido neste PC: com “pt”, 0% de erro de palavras; no automático, 1,9%."),
        vs.voicestudio.engine?.instruct === "tags" ? text("voice", "style", "Estilo (tags do motor)", "Separadas por vírgula, como “low pitch” ou “whisper”. O motor ativo aceita tags de estilo; uma tag que ele não conhece volta como erro no Testar. Vazio = o jeito da própria voz.") : null,
        number("voice", "seed", "Semente", "Fixa, a voz soa igual todo dia. 0 = uma variação nova a cada fala.", 0, 2147483647)),
      card("Leitura", null,
        toggle("voice", "autoplay", "Ler as respostas sozinho", "Cada resposta do chat é lida assim que fica pronta."),
        select("voice", "read", "O que ler", [["answer", "A resposta inteira"], ["short", "Só o primeiro parágrafo"]], "Markdown, código e as citações [S#] nunca são lidos."),
        toggle("voice", "send_alone", "Apertar para falar: enviar sozinho", "Desligado, o texto transcrito fica na caixa para você conferir."),
        toggle("voice", "verify_long", "Conferir os áudios longos", "No resumo e na revisão em áudio, o Whisper ouve cada frase e ela é gerada de novo se sair errada. Mais lento, mais fiel."),
        toggle("voice", "summary_after_lesson", "Gerar o resumo em áudio no fim de cada aula", "Usa a placa de vídeo por alguns minutos depois de cada aula.")),
      card("Testar a voz", null, h("div", { class: "vc-test" }, testAv, h("div", { class: "vc-test-main" }, sampleBox, whoLine)),
        h("div", { class: "st-source-actions" }, btn("Testar a voz", () => test(), { icon: "volume", cls: "btn sm primary" }))),
    ];
  }

  // Conversa por voz em tempo real (fase 6, parte 3 — seção 4.2)
  function callSettingsCard(s, vs, list, mics) {
    const micOpts = [["", "Padrão do sistema"], ...mics.map((m) => [m.id, m.default ? `${m.name} (padrão)` : m.name])];
    const micSel = h("select", { "aria-label": "Microfone da chamada" }, micOpts.map(([v, l]) => h("option", { value: v, text: l })));
    micSel.value = micOpts.some(([v]) => v === s.call_mic) ? s.call_mic : "";
    micSel.addEventListener("change", () => save("voice", "call_mic", micSel.value, "Microfone salvo."));

    const defVoice = list.find((v) => v.id === s.voice_id);
    const callVoiceSel = h("select", { "aria-label": "Voz da chamada" },
      h("option", { value: "", text: `A padrão (${defVoice?.name || "voz padrão"})` }),
      list.map((v) => h("option", { value: v.id, text: v.name })));
    callVoiceSel.value = list.some((v) => v.id === s.call_voice) ? s.call_voice : "";
    callVoiceSel.addEventListener("change", async () => {
      if (await save("voice", "call_voice", callVoiceSel.value, "Voz da chamada salva.")) {
        window.lumenStudy?.syncCallSettings?.({ call_voice: callVoiceSel.value });
      }
    });

    const cSpeedOut = h("output", { class: "st-num t-caption", text: Number(s.call_speed || 1).toFixed(2).replace(".", ",") + "×" });
    const cSpeed = h("input", { type: "range", min: "0.7", max: "1.3", step: "0.05", "aria-label": "Velocidade da voz na chamada", class: "st-range" });
    cSpeed.value = String(s.call_speed || 1);
    cSpeed.addEventListener("input", () => { cSpeedOut.textContent = parseFloat(cSpeed.value).toFixed(2).replace(".", ",") + "×"; });
    cSpeed.addEventListener("change", async () => {
      const val = parseFloat(cSpeed.value);
      if (await save("voice", "call_speed", val, "Velocidade da chamada salva.")) {
        window.lumenStudy?.syncCallSettings?.({ call_speed: val });
      }
    });

    return card("Conversa por voz", "Como funciona a chamada de voz em tempo real nos Estudos. O áudio do microfone fica só na memória e nunca é gravado em arquivo.",
      select("voice", "call_mode", "Modo", [["handsfree", "Mãos livres (detecta o fim da fala)"], ["ptt", "Apertar para falar (segurar botão ou espaço)"], ["tap", "Tocar para falar (um toque inicia, outro envia)"]], "Mãos livres usa o detector de voz na CPU; os outros dois usam o botão ou a barra de espaço."),
      select("voice", "call_silence", "Fim da fala", [["fast", "Rápido (450 ms de silêncio)"], ["normal", "Normal (700 ms de silêncio)"], ["patient", "Paciente (1100 ms de silêncio)"]], "Quanto silêncio encerra a sua vez em mãos livres."),
      toggle("voice", "call_barge_in", "Interromper falando", "Fale por cima para o Lúmen parar na hora e ouvir você."),
      toggle("voice", "call_headphones", "Estou de fone", "Com fone, a interrupção pela voz fica sensível; com caixa de som, usa cancelamento de eco e barreira conservadora."),
      toggle("voice", "call_early", "Resposta antecipada", "Aos 250 ms de silêncio já começa a transcrever e pensar; se você voltar a falar antes do fim, descarta tudo sem rastro."),
      row("Microfone", "Padrão: o microfone padrão do Windows.", micSel),
      s.engine === "voicestudio" ? row("Voz da chamada", "Quem responde na chamada em tempo real.", callVoiceSel) : null,
      row("Velocidade da voz na chamada", "De 0,7× a 1,3×.", h("span", { class: "input-row" }, cSpeed, cSpeedOut)),
      s.engine === "voicestudio" ? select("voice", "call_quality", "Qualidade da voz na chamada", [["fast", `Rápido (${vs.steps.fast} passos)`], ["balanced", `Equilibrado (${vs.steps.balanced} passos)`], ["quality", `Qualidade (${vs.steps.quality} passos)`]], "Medido neste PC: 12 passos equilibra naturalidade e atraso menor que 2,0 s.") : null,
      s.engine === "voicestudio" ? select("voice", "call_first_quality", "Primeiro trecho da resposta", [["same", "Igual ao resto"], ["fast", `Mais rápido (${vs.steps.fast} passos só no 1º trecho)`]], "Opcional: a voz começa cerca de 0,3 s antes. Confira de ouvido se a qualidade do início continua boa para você.") : null,
      select("voice", "call_length", "Tamanho das respostas", [["short", "Curta (1 a 3 frases)"], ["chat", "Conversa (2 a 5 frases)"], ["detailed", "Detalhada"]], "Adapta as instruções do modelo durante a chamada."),
      select("voice", "call_effort", "Esforço na chamada", [["auto", "Automático (teto Equilibrado)"], ["rapido", "Rápido"], ["equilibrado", "Equilibrado"]], "Profundo e Máximo só entram quando pedidos pela voz (“pensa com calma”), avisando quanto vai levar."),
      toggle("voice", "call_earcon", "Som de “entendi”", "Um sinal curto e suave quando a sua vez termina, para saber na hora que foi ouvido."),
      toggle("voice", "call_filler", "Preencher a espera", "Se a primeira fala demorar mais que 1,9 s, diz uma frase curta guardada (“Deixa eu ver.”), no máximo uma por turno."),
      select("voice", "call_asr", "Transcrição da chamada", [["auto", "Automático (pela memória livre da placa)"], ["parakeet", "Parakeet int8 (CPU)"], ["whisper", "Whisper turbo (placa de vídeo)"]], "Automático usa o Parakeet na CPU quando a placa está dividida com o modelo de texto e o Voice Studio."),
      toggle("voice", "call_captions", "Legendas ao vivo", "Mostra o que você e o Lúmen estão dizendo em tempo real."),
      select("voice", "call_autostop", "Encerrar sozinho", [[0, "Nunca"], [2, "Após 2 min de silêncio"], [5, "Após 5 min de silêncio"], [10, "Após 10 min de silêncio"]], "Fecha o microfone automaticamente se ninguém falar."),
      select("voice", "call_save", "Guardar a conversa", [["history", "No histórico de conversas"], ["temporary", "Como conversa temporária"]], "O áudio nunca é guardado, apenas o texto da conversa."),
      toggle("voice", "call_timings", "Mostrar os tempos", "Exibe, em cada turno, o tempo medido de cada etapa."));
  }

  // Pronúncias (D58): o dicionário do Voice Studio, que o Lúmen também aplica na fala dele. Cada mudança é um clique.
  async function pronunciationCard() {
    const V = window.lumenVoice, ALSO = "Isto muda também no Voice Studio.";
    const box = h("div", { class: "vc-pron" }), out = h("p", { class: "t-caption muted", "aria-live": "polite" });
    const term = h("input", { type: "text", maxlength: "60", placeholder: "keyframe", "aria-label": "Termo" });
    const rep = h("input", { type: "text", maxlength: "120", placeholder: "quíframe", "aria-label": "Como deve soar" });
    const tryBox = h("input", { type: "text", maxlength: "400", "aria-label": "Frase para testar" });
    tryBox.value = "Crie um keyframe no Premiere e defina o CTA.";
    const sugg = h("ul", { class: "vc-pron-sugg", "aria-label": "Sugestões de pronúncia", "aria-live": "polite" });
    async function load() {
      const r = await V.api("/api/study/voice/pron").catch(() => null);
      if (!r?.running) return box.replaceChildren(h("p", { class: "muted t-sm", text: "As pronúncias aparecem com a voz ligada (Integrações → Voice Studio)." }));
      box.replaceChildren(r.entries.length ? h("ul", { class: "vc-model-list", "aria-label": "Pronúncias" }, r.entries.map((e) => h("li", { class: "vc-model-row" },
        h("span", { class: "t-sm" }, h("strong", { text: e.term }), ` → ${e.replacement}`, e.enabled ? "" : h("span", { class: "muted", text: " (desligada)" })),
        h("button", { type: "button", class: "icon-btn sm", "aria-label": `Remover ${e.term}`, "data-tip": "Remover", onclick: async () => {
          if (!(await window.ui.confirm(`A pronúncia de “${e.term}” sai do dicionário. ${ALSO}`, { title: "Remover a pronúncia?", ok: "Remover", danger: true }))) return;
          if (await guard(() => V.api("/api/study/voice/pron", { action: "delete", id: e.id }), "Pronúncia removida.")) load();
        } }, ic("trash"))))) : h("p", { class: "muted t-sm", text: "Nenhuma pronúncia ainda." }));
    }
    const add = async (t, r) => { const ok = await guard(() => V.api("/api/study/voice/pron", { action: "add", term: t, replacement: r, language: "*" }), `“${t}” agora soa “${r}”.`); if (ok) load(); return ok; };
    const file = h("input", { type: "file", accept: ".json,application/json", hidden: true, "aria-label": "Arquivo de pronúncias" });
    file.addEventListener("change", async () => {
      const f = file.files[0];
      file.value = "";
      if (!f) return;
      let entries;
      try { const j = JSON.parse(await f.text()); entries = Array.isArray(j) ? j : j.entries; } catch { return toast("O arquivo não é um JSON de pronúncias.", "error"); }
      if (!Array.isArray(entries) || !entries.length) return toast("O arquivo não tem pronúncias.", "warning");
      if (!(await window.ui.confirm(`Adiciona ${entries.length} pronúncia(s) ao dicionário (as atuais ficam). ${ALSO}`, { title: "Importar pronúncias?", ok: "Importar" }))) return;
      if (await guard(() => V.api("/api/study/voice/pron", { action: "import", entries }), "Pronúncias importadas.")) load();
    });
    load();
    return card("Pronúncias", "Como a voz diz termos em inglês e siglas (Premiere, keyframe, CTA). É o dicionário do Voice Studio, aplicado também na fala do Lúmen.",
      box,
      h("div", { class: "input-row vc-pron-add" }, term, rep, btn("Adicionar", async () => {
        if (!term.value.trim() || !rep.value.trim()) return toast("Escreva o termo e como ele deve soar.", "warning");
        if (await add(term.value.trim(), rep.value.trim())) { term.value = ""; rep.value = ""; }
      }, { icon: "plus", cls: "btn sm primary" })),
      h("p", { class: "field-hint", text: ALSO }),
      row("Testar", "Mostra o texto como a voz recebe e fala a frase.", h("span", { class: "input-row" }, tryBox, btn("Ouvir", async () => {
        const r = await guard(() => V.api("/api/study/voice/pron", { action: "test", text: tryBox.value, listen: true }));
        if (r) { out.textContent = `A voz recebe: “${r.substituted}”`; if (r.audio) V.playClip(r.audio); }
      }, { icon: "play", cls: "btn sm" }))),
      out,
      h("div", { class: "st-source-actions" },
        btn("Sugerir das minhas notas", async (ev) => {
          const b = ev.currentTarget;
          b.disabled = true;
          sugg.replaceChildren(h("li", { class: "muted t-sm", text: "Procurando termos em inglês e siglas nas suas notas…" }));
          const r = await guard(() => V.api("/api/study/voice/pron", { action: "suggest" }));
          b.disabled = false;
          if (!r) return sugg.replaceChildren();
          sugg.replaceChildren(...(r.suggestions.length ? r.suggestions.map((x) => {
            const li = h("li", { class: "vc-model-row" }, h("span", { class: "t-sm" }, h("strong", { text: x.term }), ` → ${x.replacement}`),
              h("span", { class: "input-row" }, btn("Aceitar", async () => { if (await add(x.term, x.replacement)) li.remove(); }, { icon: "check", cls: "btn sm" }),
                btn("Ignorar", () => li.remove(), { cls: "btn sm ghost" })));
            return li;
          }) : [h("li", { class: "muted t-sm", text: "Nenhum termo novo encontrado nas notas." })]));
        }, { icon: "sparkle", cls: "btn sm" }),
        btn("Exportar", async () => { const r = await guard(() => V.api("/api/study/voice/pron", { action: "export" })); if (r) download("pronuncias-voice-studio.json", JSON.stringify(r, null, 1), "application/json"); }, { icon: "download", cls: "btn sm ghost" }),
        btn("Importar", () => file.click(), { icon: "upload", cls: "btn sm ghost" }), file),
      sugg);
  }

  // --- Privacidade --------------------------------------------------------------------------------------------------
  async function privacy() {
    return [
      card("Privacidade", "Por padrão tudo roda no seu PC (modo local).",
        toggle("privacy", "open_windows", "A IA pode abrir páginas e notas sozinha", "Desligado, ela deixa um botão para você abrir.")),
      card("Permissões", "Escolha onde a IA pode criar. Notas e páginas originais são preservadas. Cada criação confirmada oferece Abrir e Desfazer.",
        h("ol", { class: "st-levels" },
          h("li", {}, h("strong", { text: "Nível 1 · Leitura (automática)" }), h("span", { class: "muted", text: " Pesquisar, abrir, ler, comparar e navegar por links nas fontes autorizadas, sem pedir a cada documento." })),
          h("li", {}, h("strong", { text: "Nível 2 · Criação" }), h("span", { class: "muted", text: " Use /nota ou /pagina. A área da IA pode receber novas criações conforme a opção abaixo; fora dela, sempre há prévia." })),
          h("li", {}, h("strong", { text: "Nível 3 · Modificação (indisponível para a IA)" }), h("span", { class: "muted", text: " Editar, sobrescrever ou mover originais." })),
          h("li", {}, h("strong", { text: "Nível 4 · Risco (indisponível para a IA)" }), h("span", { class: "muted", text: " Apagar, revogar integrações, credenciais, comandos. Limpezas de dados do Lúmen pedem confirmação digitada." }))),
        select("privacy", "organize", "Criar notas e páginas (nível 2)", [["ai", "Criar diretamente nas áreas da IA"], ["ask", "Sempre com prévia e confirmação"], ["off", "Nunca"]],
          "Área da IA: C04 Claude Obsidian/01 Outputs e a página Lúmen Study AI no Notion. Desfazer preserva uma criação que você tenha editado.")),
      card("Aplicativos permitidos", "Use /abrir e o nome abaixo. Desligar um aplicativo também bloqueia o botão de abrir.",
        ...[["obsidian", "Obsidian"], ["notion", "Notion"], ["edge", "Microsoft Edge"], ["vault", "Pasta do cofre"], ["calculator", "Calculadora"]].map(([id, label]) => toggle("agent", id, label))),
      card("Pesquisa guiada", "Use /web e sua consulta. Ligue Internet em Pesquisa e permita abrir janelas. O Edge usa um perfil separado no D: e mostra versões de leitura, com Pausar e Parar.",
        h("p", { class: "faint", text: "Sem scripts dos sites, formulários, login ou downloads. Só a consulta é enviada ao buscador; páginas consultadas podem ser citadas na resposta." })),
      card("Retenção", null,
        number("privacy", "retention_conversations", "Apagar conversas sem uso há (dias)", "0 = guardar até você apagar. Conversas fixadas ficam.", 0, 3650),
        number("privacy", "retention_activity", "Guardar histórico de atividades por (dias)", null, 7, 3650),
        h("p", { class: "faint", text: `Conversas temporárias ficam só na memória do Lúmen e somem ao fechar o app ou após ${st.temporary_hours} h sem uso.` })),
    ];
  }

  // --- Conectores e desempenho ---------------------------------------------------------------------------------------
  async function connectors() {
    return [card("Onde salvar", "Destinos das gravações confirmadas.",
      text("connectors", "obsidian_output", "Pasta das notas no cofre", "Padrão: C04 Claude Obsidian/01 Outputs (área de entregas da IA no seu CLAUDE.md)."),
      text("connectors", "notion_parent", "Página do Notion", "Link ou ID. Vazio = a página principal de Integrações. O Lúmen cria “Lúmen Study AI” dentro dela.")),
    card("Conexões", "Tokens e cofre ficam em Integrações; pastas e internet em Fontes.",
      h("div", { class: "st-source-actions" }, btn("Abrir Integrações", () => document.querySelector("#nav-integrations")?.click(), { icon: "plug", cls: "btn sm" }),
        btn("Abrir Fontes", () => { close(); L.setTab("sources"); }, { icon: "folder", cls: "btn sm" })))];
  }
  async function performance() {
    const c = st.counts;
    return [card("Sincronização e índice", null,
      number("performance", "sync_minutes", "Sincronizar a cada (minutos)", "Só fontes que você já sincronizou uma vez.", 2, 1440),
      toggle("performance", "yield_to_lessons", "Dar prioridade às aulas", "Pausa a sincronização enquanto uma aula é processada."),
      number("performance", "embed_batch", "Trechos por lote de embeddings", null, 1, 64),
      number("performance", "images_per_sync", "Imagens das notas lidas por sincronização", "Cerca de 2 s cada na placa de vídeo. 0 = pausar a leitura.", 0, 500),
      h("dl", { class: "st-source-facts" }, ["notion", "obsidian", "files"].map((k) => h("div", {}, h("dt", { text: L.LABEL[k] }), h("dd", { text: `${n(c[k]?.documents)} docs · ${n(c[k]?.vectors)}/${n(c[k]?.chunks)} vetores` })))),
      h("div", { class: "st-source-actions" }, btn("Sincronizar fontes agora", async () => {
        for (const k of ["obsidian", "notion", "files"]) if (st.sources[k]?.connected && st.sources[k]?.index?.synced) await guard(() => api("/api/study/sources", { action: "sync", source: k }));
        toast("Sincronização pedida.", "success");
      }, { icon: "sync", cls: "btn sm" })))];
  }

  // --- Projetos -------------------------------------------------------------------------------------------------------
  async function projects() {
    const r = await guard(() => api("/api/study/projects"));
    const SRC = [["notion", "Notion"], ["obsidian", "Obsidian"], ["files", "Arquivos"], ["web", "Internet"]];
    async function edit(p = {}) {
      const boxes = SRC.map(([k, l]) => { const c = h("input", { type: "checkbox", ...((p.sources?.[k] ?? true) ? { checked: true } : {}) }); return [k, c, h("label", { class: "st-check" }, c, l)]; });
      const v = await dialog({ title: p.id ? "Editar projeto" : "Novo projeto", wide: true, ok: "Salvar",
        fields: [{ name: "name", label: "Nome", value: p.name || "" }, { name: "description", label: "Descrição", type: "textarea", rows: 2, value: p.description || "" },
          { name: "goals", label: "Objetivos", type: "textarea", rows: 2, value: p.goals || "" },
          { name: "instructions", label: "Instruções para a IA neste projeto", type: "textarea", rows: 3, value: p.instructions || "" }],
        body: h("fieldset", { class: "st-fieldset" }, h("legend", { text: "Fontes que este projeto pode consultar" }), boxes.map(([, , l]) => l)) });
      if (!v) return;
      const project = { ...v, id: p.id, sources: Object.fromEntries(boxes.map(([k, c]) => [k, c.checked])) };
      if (await guard(() => api("/api/study/projects", { action: "save", project }), "Projeto salvo.")) { L.loadConversations(); render(host, "projects"); }
    }
    return [h("section", { class: "card st-set-card" },
      h("div", { class: "st-mem-head" }, h("div", {}, h("h3", { class: "t-h3", text: "Projetos do Lúmen" }), h("p", { class: "muted", text: "Organize conversas, memórias e documentos por assunto. A memória de um projeto não entra em outro." })),
        btn("Novo projeto", () => edit(), { icon: "plus", cls: "btn sm primary" })),
      r?.projects.length ? h("div", { class: "st-projects" }, r.projects.map((p) => h("article", { class: "st-project" },
        h("div", {}, h("h4", { class: "t-h3", text: p.name }), p.description ? h("p", { class: "muted", text: p.description }) : null,
          h("p", { class: "faint", text: `${p.conversations} conversa(s) · ${p.memories} memória(s) · ${p.documents} documento(s) fixado(s) · fontes: ${SRC.filter(([k]) => p.sources[k]).map(([, l]) => l).join(", ") || "nenhuma"}` })),
        h("div", { class: "st-mem-actions" }, btn("Editar", () => edit(p), { icon: "pen", cls: "btn sm" }),
          btn("Excluir", async () => {
            if (await window.ui.confirm(`O projeto “${p.name}” e as ${p.memories} memória(s) dele serão apagados. As conversas ficam, sem projeto.`, { title: "Excluir projeto?", ok: "Excluir", danger: true })) {
              await guard(() => api("/api/study/projects", { action: "delete", id: p.id }), "Projeto excluído."); L.loadConversations(); render(host, "projects");
            }
          }, { icon: "trash", cls: "btn sm ghost" }))))) :
        h("div", { class: "empty" }, ic("library", "empty-icon"), h("p", { text: "Nenhum projeto ainda. Crie um para separar estudos (Psicologia, Programação…)." })))];
  }

  // --- Atividades -----------------------------------------------------------------------------------------------------
  async function activity() {
    const r = await guard(() => api("/api/study/activity?limit=300"));
    const NAMES = { "ferramenta": "Ferramenta da IA", "busca": "Busca", "abrir": "Abrir original", "gravar": "Gravação", "preparar-gravacao": "Prévia de gravação",
      "cancelar-gravacao": "Gravação cancelada", "envio-externo": "Envio ao provedor externo", "sincronizar": "Sincronização", "testar-fonte": "Teste de fonte",
      "desconectar-fonte": "Fonte desconectada", "memoria": "Memória", "apagar-dados": "Dados apagados", "apagar-conversas": "Conversas apagadas", "credencial": "Credencial",
      "autorizar-pasta": "Pasta autorizada", "remover-pasta": "Pasta removida", "apagar-projeto": "Projeto apagado",
      "troca-automatico": "Troca do Automático", "chamada-turno": "Turno da conversa por voz",
      "pesquisa-guiada": "Pesquisa guiada", "abrir-aplicativo": "Aplicativo aberto", "indexar-anexo": "Anexo indexado", "desfazer-criacao": "Criação desfeita" };
    const sec = h("section", { class: "card st-set-card" }, h("h3", { class: "t-h3", text: "Histórico de atividades" }),
      h("p", { class: "muted", text: "O que a IA e você fizeram: ação, ferramenta, documento, quando, resultado e permissão usada. O conteúdo das notas nunca entra aqui." }),
      r?.activity.length ? h("div", { class: "st-table" }, h("table", { class: "st-activity" },
        h("thead", {}, h("tr", {}, ["Quando", "Ação", "Ferramenta", "Documento ou alvo", "Resultado", "Permissão"].map((t) => h("th", { text: t })))),
        h("tbody", {}, r.activity.map((a) => h("tr", {}, h("td", { text: when(a.at) }), h("td", { text: NAMES[a.action] || a.action }), h("td", { text: [a.tool, a.provider].filter(Boolean).join(" · ") }),
          h("td", { text: a.target }), h("td", { text: [a.result, a.detail].filter(Boolean).join(" · ") }), h("td", { text: a.permission })))))) :
        h("p", { class: "faint", text: "Nada registrado ainda." }));
    window.Glass?.activity(sec, r?.activity, (a) => NAMES[a.action] || a.action);  // Glass: os mesmos registros em linha do tempo (oculta no Clássico)
    return [sec];
  }

  // --- Seus dados ----------------------------------------------------------------------------------------------------
  const RISK = { memories: "high", conversations: "high", projects: "high", saved: "high", skills: "high", evaluation: "medium", mastery: "medium", index: "medium", pending: "low", cache: "low", activity: "low" };
  const MASTERY = { domina: "domina", aprendendo: "está aprendendo", dificuldade: "com dificuldade" };
  async function data() {
    const inv = await guard(() => api("/api/study/data"));
    if (!inv) return [];
    const del = async (c) => {
      const risk = RISK[c.key];
      let ok;
      if (risk === "high") ok = await dialog({ title: `Apagar ${c.label.toLowerCase()}?`, message: `${c.description} Serão apagados ${n(c.count)} registro(s), de vez. Nada no Notion ou no Obsidian é tocado.`, danger: true, require: "APAGAR", ok: "Apagar" });
      else ok = await window.ui.confirm(`${c.description} ${n(c.count)} registro(s).${c.key === "index" ? " Os originais ficam intactos; o índice pode ser refeito sincronizando as fontes." : ""}`, { title: `Apagar ${c.label.toLowerCase()}?`, ok: "Apagar", danger: risk === "medium" });
      if (ok) { await guard(() => api("/api/study/data", { action: "delete", category: c.key }), "Dados apagados."); render(host, "data"); }
    };
    return [
      h("section", { class: "card st-set-card" }, h("h3", { class: "t-h3", text: "O que está guardado" }),
        h("p", { class: "muted", text: "Tudo fica no seu PC, nesta pasta: " }, h("code", { text: inv.folder })),
        h("div", { class: "st-data-list" }, inv.categories.map((c) => h("div", { class: "st-data-row" },
          h("div", {}, h("strong", { text: c.label }), h("p", { class: "faint", text: c.description })),
          h("span", { class: "st-data-n", text: n(c.count) }),
          btn("Apagar", () => del(c), { icon: "trash", cls: "btn sm ghost", attrs: { disabled: c.count ? null : true } })))),
        inv.mastery?.length ? h("details", { class: "st-mastery" }, h("summary", { text: `O que o Lúmen sabe que você domina, por assunto (${n(inv.mastery.length)})` }),
          h("ul", { class: "st-list" }, inv.mastery.map((m) => h("li", {}, h("strong", { text: m.label }),
            ` — ${MASTERY[m.level] || "sem prática ainda"} (${m.correct} acerto(s), ${m.wrong} erro(s))`,
            m.next_review ? h("span", { class: "faint", text: m.due ? " · revisar agora" : ` · próxima revisão: ${when(m.next_review)}` }) : null)))) : null,
        h("p", { class: "faint", text: `Arquivos: ${inv.files.map((f) => `${f.path.split(/[\\/]/).pop()} (${(f.bytes / 1048576).toFixed(1)} MB)`).join(", ")}. Conversas temporárias abertas agora: ${inv.temporary}.` }),
        h("p", { class: "faint", text: `Chaves de API de IA em nuvem: ${inv.secret.present ? "há uma guardada, mas o Lúmen não a usa" : "nenhuma"} no ${inv.secret.where}.` })),
      card("Quem recebeu informações", "Provedores externos que receberam trechos das suas notas ou conversas (registro histórico: hoje o Lúmen não envia nada para fora).",
        inv.providers.length ? h("ul", { class: "st-list" }, inv.providers.map((p) => h("li", { text: `${({ anthropic: "Anthropic (Claude)", openai: "OpenAI (ChatGPT)", google: "Google (Gemini)" })[p.provider] || p.provider}: ${n(p.calls)} envio(s), de ${when(p.first)} a ${when(p.last)}` })))
          : h("p", { class: "faint", text: "Nenhum: tudo foi processado pela IA local." })),
      card("Exportar e limpar", "A exportação inclui conversas, memórias, projetos, itens salvos e ajustes (sem a chave).",
        h("div", { class: "st-source-actions" },
          btn("Exportar meus dados", async () => { const r = await guard(() => api("/api/study/data", { action: "export" })); if (r) download(r.filename, r.content, "application/json"); }, { icon: "download", cls: "btn sm primary" }),
          btn("Limpar tudo", async () => {
            const v = await dialog({ title: "Limpar todos os dados do Lumen Study AI?", danger: true, require: "APAGAR TUDO", ok: "Limpar tudo",
              message: "Memórias, conversas, projetos, itens salvos, índice, cache, atividades e prévias serão apagados de vez. Ajustes e a chave ficam. Seus documentos no Notion e no Obsidian não são tocados." });
            if (v) { await guard(() => api("/api/study/data", { action: "delete_all", confirm: "APAGAR TUDO" }), "Tudo foi apagado."); L.newConversation(); L.loadConversations(); render(host, "data"); }
          }, { icon: "trash", cls: "btn sm danger" })),
        h("details", { class: "st-policy" }, h("summary", { text: "Política de exclusão" }), h("ul", { class: "st-list" },
          ["Apagar no Lúmen nunca apaga nada no Notion ou no Obsidian.",
            "“Documentos indexados” remove a cópia local do texto, o índice de palavras e os vetores; os originais continuam onde estão.",
            "Apagar memórias e conversas remove também o índice de busca e os vetores ligados a elas.",
            "O banco apaga com sobrescrita (secure_delete) e o registro de transações é truncado depois de cada limpeza: o conteúdo apagado não fica legível no disco.",
            "Os backups da Proteção do cérebro copiam o cofre e o Notion, não estes dados.",
            "Conversas temporárias nunca são gravadas em disco."].map((t) => h("li", { text: t }))))),
    ];
  }

  Object.assign(L, { renderSettings: render });
})();
