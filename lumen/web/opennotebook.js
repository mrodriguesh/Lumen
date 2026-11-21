// Open Notebook: a aba de Integrações e o envio da transcrição de uma aula (lumen/opennotebook.py). Carregado depois do
// app.js e usa os utilitários dele ($, el, icon, api, fail, toast, setBadge, host, S). Toda conversa com o Open Notebook
// passa pelo servidor do Lúmen: a senha nunca chega aqui, e a interface não trava enquanto ele não responde.
(() => {
  const CONN = { off: ["", "power", "Desconectado"], connected: ["ok", "check", "Conectado"], unavailable: ["warn", "alert", "Serviço indisponível"],
    password: ["warn", "alert", "Senha necessária"], error: ["error", "alert", "Erro"] };
  // estado do envio de uma aula → [tom, ícone, texto]
  const SENT = {
    none: ["", "info", "Esta transcrição ainda não foi enviada."],
    sending: ["warn", "alert", "Um envio anterior não foi confirmado. Ao tentar de novo, o Lúmen procura a fonte no caderno antes de repetir."],
    queued: ["", "clock", "Na fila do Open Notebook. O processamento depende do worker dele estar ligado."],
    processing: ["", "refresh", "O Open Notebook está processando a fonte…"],
    completed: ["ok", "check", "Fonte pronta no Open Notebook."],
    failed: ["error", "alert", "O envio falhou."],
    missing: ["warn", "alert", "A fonte não está mais no Open Notebook. Você pode enviar de novo."],
    unknown: ["warn", "alert", "O Open Notebook não soube dizer o estado desta fonte."],
  };
  SENT.unconfirmed = SENT.sending;
  // andamento de “Iniciar Open Notebook”, serviço por serviço (lumen/onlocal.py) → [tom, ícone, texto]
  const STEP = { pending: ["", "clock", "aguardando"], checking: ["", "refresh", "verificando…"], starting: ["", "refresh", "iniciando…"],
    reused: ["ok", "check", "já estava aberto"], started: ["ok", "check", "iniciado"], failed: ["error", "alert", "falhou"] };
  const RETRY = { sending: "Tentar de novo", unconfirmed: "Tentar de novo", failed: "Tentar de novo", missing: "Enviar de novo" };
  let V = null, seq = 0;  // V: a última visão da conexão; seq: respostas de um teste antigo são descartadas

  const UIMSG = { down: "Nada responde no endereço da interface do Open Notebook.",
    other: "O endereço da interface responde, mas não como o Open Notebook (outro programa nessa porta, ou ele ainda está iniciando)." };
  function open(url) {  // janela própria do Lúmen (isolada, presa ao endereço do Open Notebook); fora dele, o navegador
    if (host) host.postMessage("opennotebook:open:" + url); else window.open(url, "_blank", "noopener");
  }
  const busy = async (btn, fn) => {
    btn.disabled = true; btn.setAttribute("aria-busy", "true");
    try { return await fn(); } finally { btn.disabled = false; btn.removeAttribute("aria-busy"); }
  };

  // ---------- Integrações → Open Notebook ----------
  function render(v) {
    V = v;
    const on = v.state !== "off", [tone, ic, label] = CONN[v.state];
    setBadge($("#on-badge"), CONN[v.state]);
    setBadge($("#on-status"), [tone, ic, v.state === "connected" ? `${label}${v.version ? ` · versão ${v.version}` : ""}` : on ? `${label}. ${v.message}` : label]);
    for (const [id, val] of [["#on-url", v.opennotebook_url], ["#on-ui", v.opennotebook_ui]]) if (document.activeElement !== $(id)) $(id).value = val;
    $("#on-password").placeholder = v.has_password ? "Senha guardada (digite para trocar)" : "";
    $("#on-connect").textContent = on ? "Testar conexão" : "Conectar";
    $("#on-book-sec").hidden = $("#on-foot").hidden = !on;
    const books = v.notebooks, chosen = v.opennotebook_notebook, sel = $("#on-book");
    sel.replaceChildren(
      ...(books.some((b) => b.id === chosen) ? [] : [el("option", { value: "" }, v.state !== "connected" && chosen ? v.opennotebook_notebook_name : "Escolha um caderno")]),
      ...books.map((b) => el("option", { value: b.id }, `${b.name}${b.archived ? " (arquivado)" : ""} · ${b.sources} ${b.sources === 1 ? "fonte" : "fontes"}`)));
    sel.value = books.some((b) => b.id === chosen) ? chosen : "";
    sel.disabled = $("#on-create").disabled = v.state !== "connected";
    $("#on-create").hidden = books.some((b) => b.name === v.name);  // já existe: está na lista, nunca é criado de novo
    $("#on-open").dataset.tip = UIMSG[v.ui_state] || "";  // a conferência é só um aviso: o botão não fica preso a ela
    local(v.local);
  }
  // O Open Notebook instalado neste PC: o que está parado e a partida, sempre a pedido (abrir a aba não inicia nada).
  function local(l) {
    const run = l?.run, ran = !!run?.steps.length, stopped = !!l?.available && l.missing.length > 0;
    $("#on-start").hidden = !(stopped || run?.active);
    $("#on-start").disabled = !!run?.active;
    const failed = stopped && !!run?.error;  // um erro antigo some quando nada mais está parado
    $("#on-local").hidden = !(stopped || run?.active);
    if (!$("#on-local").hidden) setBadge($("#on-local"), run?.active ? ["", "refresh", `Iniciando o Open Notebook neste PC. ${run.tied ? TIED : "Os serviços continuam abertos depois de fechar o Lúmen."}`]
      : failed ? ["error", "alert", run.error] : ["warn", "alert", `Parado neste PC: ${l.missing.join(", ")}.`]);
    $("#on-steps").hidden = !(ran && (run.active || failed));
    $("#on-steps").replaceChildren(...(ran ? run.steps : []).map((s) => {
      const [tone, ic, text] = STEP[s.state], li = el("li", { class: "integ-state on-status" });
      setBadge(li, [tone, ic, `${s.label}: ${text}${s.state === "starting" && s.detail ? ` (${s.detail})` : ""}`]);
      return li;
    }));
    if (run?.active) watch();
  }
  const TIED = "Este Lumen.exe é anterior a esta função: os serviços iniciados agora fecham junto com o Lúmen.";
  let watching = 0;
  function watch() {  // acompanha a partida até o fim e, então, testa a conexão de novo
    clearTimeout(watching);
    watching = setTimeout(async () => {
      const run = await api("/api/opennotebook/local").catch(() => null);
      if (!run) return watch();
      if (run.active) return local({ ...V.local, run });
      await load().catch(fail);
      if (!run.error) toast(run.tied ? `Open Notebook iniciado. ${TIED}` : V.state === "connected" ? "Open Notebook iniciado e conectado." : `Serviços iniciados. ${CONN[V.state][2]}.`,
        V.state === "connected" && !run.tied ? "success" : "warning");
    }, 1000);
  }
  async function load(path = "/api/opennotebook", body) {
    const n = ++seq, v = await api(path, body);
    if (n === seq) render(v);
    return v;
  }
  const connect = () => busy($("#on-connect"), async () => {
    const v = await load("/api/opennotebook/connect", { url: $("#on-url").value, ui: $("#on-ui").value, password: $("#on-password").value });
    $("#on-password").value = "";
    if (S) S.config.opennotebook_on = true;
    toast(v.state === "connected" ? "Open Notebook conectado." : `${CONN[v.state][2]}. ${v.message}`, v.state === "connected" ? "success" : "warning");
  }).catch(fail);
  $("#on-connect").addEventListener("click", connect);
  for (const id of ["#on-url", "#on-ui", "#on-password"]) $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
  $("#on-start").addEventListener("click", () => api("/api/opennotebook/start", {}).then((run) => local({ ...V.local, run })).catch(fail));
  $("#on-reload").addEventListener("click", () => busy($("#on-reload"), load).catch(fail));
  $("#on-book").addEventListener("change", (e) => e.target.value && load("/api/opennotebook/notebook", { id: e.target.value }).catch((err) => { fail(err); render(V); }));
  $("#on-create").addEventListener("click", () => busy($("#on-create"), async () => {
    const v = await load("/api/opennotebook/notebook", { create: true });
    toast(`Destino: caderno “${v.opennotebook_notebook_name}”.`);
  }).catch(fail));
  // A conferência pode estar velha: confere de novo ao clicar. Só abre se a interface for a do Open Notebook: outro programa
  // na porta (ex.: o HyperbookLM em :3000) responderia 404 em /notebooks/<id>.
  $("#on-open").addEventListener("click", () => busy($("#on-open"), async () => {
    const v = await load().catch(() => V);
    if (v.ui_state === "down") return toast(`${UIMSG.down} Use “Iniciar Open Notebook” e tente de novo.`, "warning");
    if (v.ui_state === "other") return toast(`${UIMSG.other} Confira o endereço da interface ou use “Iniciar Open Notebook”.`, "warning");
    open(v.open_url);
  }));
  $("#on-disconnect").addEventListener("click", () => load("/api/opennotebook/disconnect", {}).then(() => { if (S) S.config.opennotebook_on = false; }).catch(fail));

  // ---------- envio de uma aula ----------
  const dlg = $("#on-dlg");
  let cur = null, timer = 0;  // cur: { key, title } da aula no diálogo
  function show(st, error) {
    const t = st.target, can = t.on && t.notebook_name && st.transcript;
    const sent = !["none", "sending", "unconfirmed"].includes(st.state), retry = st.state in RETRY || st.state === "none";
    $("#on-dlg-what").textContent = !t.on ? "O Open Notebook não está conectado. Abra Integrações → Open Notebook para conectar."
      : !t.notebook_name ? "Nenhum caderno de destino foi escolhido. Abra Integrações → Open Notebook e escolha um."
      : !st.transcript && !sent ? "A transcrição desta aula não está mais guardada neste PC. O Lúmen guarda a da última aula publicada (ou de todas, com “Manter arquivos temporários” ligado)."
      : `Vai só o texto da transcrição, com o título, o curso e o módulo, a data, o idioma e o link da fonte (quando há). Nenhum áudio ou vídeo é enviado. Destino: caderno “${sent ? st.notebook_name : t.notebook_name}”, em ${t.url}.`;
    const [tone, ic, text] = SENT[st.state] || SENT.unknown;
    setBadge($("#on-dlg-state"), error ? ["error", "alert", error] : st.offline ? ["warn", "alert", `${text} ${st.offline}`]
      : [tone, ic, st.state === "failed" && st.error ? `O envio falhou: ${st.error}` : text]);
    $("#on-dlg-open").hidden = !sent || st.state === "missing";
    $("#on-dlg-send").hidden = $("#on-dlg-send-open").hidden = !(can && retry);
    $("#on-dlg-send").textContent = RETRY[st.state] || "Enviar";
    $("#on-dlg-send-open").textContent = st.state in RETRY ? `${RETRY[st.state]} e abrir` : "Enviar e abrir";
    $("#on-dlg-open").onclick = () => open(st.open_url);
    clearTimeout(timer);  // acompanha o processamento de verdade enquanto o diálogo está aberto
    if (dlg.open && ["queued", "processing"].includes(st.state)) timer = setTimeout(() => check(cur.key), 3000);
  }
  const check = (key) => api(`/api/opennotebook/lesson?key=${encodeURIComponent(key)}&check=1`).then((st) => { if (dlg.open && cur?.key === key) show(st); }).catch(() => {});
  function lesson(key, title) {
    cur = { key, title };
    $("#on-dlg-sub").textContent = title || "";
    setBadge($("#on-dlg-state"), ["", "refresh", "Conferindo…"]);
    $("#on-dlg-what").textContent = "";
    for (const id of ["#on-dlg-open", "#on-dlg-send", "#on-dlg-send-open"]) $(id).hidden = true;
    dlg.showModal();
    check(key);
  }
  const send = (btn, andOpen) => busy(btn, async () => {
    const key = cur.key;
    setBadge($("#on-dlg-state"), ["", "refresh", "Enviando a transcrição…"]);
    try {
      const st = await api("/api/opennotebook/send", { key });
      if (cur.key !== key) return;
      show(st);
      if (andOpen) open(st.open_url);
    } catch (e) {  // o estado guardado (falhou ou não confirmado) e o motivo, lado a lado
      const st = await api(`/api/opennotebook/lesson?key=${encodeURIComponent(key)}`).catch(() => null);
      if (st && cur.key === key) show(st, `${e.message} ${e.action || ""}`.trim()); else fail(e);
    }
  });
  $("#on-dlg-send").addEventListener("click", (e) => send(e.currentTarget, false));
  $("#on-dlg-send-open").addEventListener("click", (e) => send(e.currentTarget, true));
  $("#on-dlg-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", () => clearTimeout(timer));

  window.lumenON = { load: () => load().catch(() => {}), lesson, enabled: () => !!S?.config.opennotebook_on };
  setTimeout(window.lumenON.load, 1500);  // o selo da aba aparece mesmo antes de abri-la
})();
