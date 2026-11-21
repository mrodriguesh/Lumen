// HyperbookLM: a aba de Integrações e o envio manual da transcrição de uma aula (lumen/hyperbooklm.py). Carregado depois
// do app.js e usa os utilitários dele ($, el, icon, api, fail, toast, setBadge, host, S). Toda conversa com o HyperbookLM
// passa pelo servidor do Lúmen: o código de pareamento só aparece aqui uma vez, ao ser gerado, para ir ao .env.local dele.
(() => {
  // estado da conexão → [tom, ícone, texto]. “Conectado” é o servidor; as chaves de IA dele aparecem à parte (#hb-ai)
  const CONN = { off: ["", "power", "Desconectado"], connected: ["ok", "check", "Conectado"], unavailable: ["warn", "alert", "Servidor indisponível"],
    pairing: ["warn", "key", "Falta parear"], unauthorized: ["warn", "alert", "Código recusado"], notfound: ["warn", "alert", "Ponte não encontrada"],
    error: ["error", "alert", "Erro"] };
  const SENT = {
    none: ["", "info", "Esta transcrição ainda não foi enviada."],
    sending: ["warn", "alert", "Um envio anterior não foi confirmado. Tentar de novo é seguro: o mesmo texto nunca vira duas fontes."],
    sent: ["ok", "check", "Guardada no HyperbookLM. Ela aparece em Sources ao abrir a janela dele ou voltar a ela."],
    failed: ["error", "alert", "O envio falhou."],
    missing: ["warn", "alert", "A fonte não está mais no HyperbookLM. Você pode enviar de novo."],
  };
  SENT.unconfirmed = SENT.sending;
  const RETRY = { sending: "Tentar de novo", unconfirmed: "Tentar de novo", failed: "Tentar de novo", missing: "Enviar de novo" };
  const REACHABLE = ["connected", "pairing", "unauthorized"];  // quem respondeu é o HyperbookLM: dá para abrir
  let V = null, seq = 0, line = "";  // V: a última visão da conexão; seq: descarta respostas antigas; line: a linha recém-gerada

  // Dentro da janela do Lúmen: o Lumen.exe mostra o HyperbookLM num painel próprio (perfil isolado, preso a este endereço,
  // com “Voltar ao Lúmen”). Num Lumen.exe anterior a esta função, ou fora dele, abre no navegador padrão.
  function open(url) {
    if (host && /LumenShell\/([2-9]|\d\d)\b/.test(navigator.userAgent)) host.postMessage("hyperbooklm:open:" + url);  // 2 ou depois
    else window.open(url, "_blank", "noopener");
  }
  const busy = async (btn, fn) => {
    btn.disabled = true; btn.setAttribute("aria-busy", "true");
    try { return await fn(); } finally { btn.disabled = false; btn.removeAttribute("aria-busy"); }
  };
  // As chaves de IA são do HyperbookLM: aqui só se sabe se existem (nenhuma é lida nem testada).
  function ai(f) {  // f.text: chat, resumo e mapa mental; f.slides: slides (os nomes das chaves estão no README do HyperbookLM)
    const miss = [!f.text && "do chat, do resumo e do mapa mental (OPENAI_API_KEY)", !f.slides && "dos slides"].filter(Boolean);
    return miss.length ? ["warn", "alert", `IA do HyperbookLM: falta a chave ${miss.join(" e a ")} no .env.local dele (veja o README dele). A transcrição chega, mas essa análise não funciona.`]
      : ["ok", "check", "IA do HyperbookLM: chaves do chat, do resumo, do mapa mental e dos slides presentes. O Lúmen não as lê nem testa; a análise usa a conta delas."];
  }

  // ---------- Integrações → HyperbookLM ----------
  function render(v) {
    V = v;
    const on = v.state !== "off", ok = v.state === "connected", [tone, ic, label] = CONN[v.state] || CONN.error;
    if (ok) line = "";
    setBadge($("#hb-badge"), [tone, ic, label]);
    setBadge($("#hb-status"), [tone, ic, ok ? `Servidor conectado · ${v.sources} ${v.sources === 1 ? "transcrição guardada" : "transcrições guardadas"}`
      : on ? `${label}. ${v.message}` : label]);
    $("#hb-ai").hidden = !ok;
    if (ok) setBadge($("#hb-ai"), ai(v.features));
    if (document.activeElement !== $("#hb-url")) $("#hb-url").value = v.hyperbooklm_url;
    $("#hb-connect").textContent = on ? "Testar conexão" : "Conectar";
    $("#hb-open").disabled = !REACHABLE.includes(v.state);
    $("#hb-open").dataset.tip = $("#hb-open").disabled ? "O HyperbookLM não está respondendo neste endereço." : "";
    $("#hb-foot").hidden = !on;
    $("#hb-pair-sec").hidden = !on || ok;
    $("#hb-pair").lastChild.textContent = v.has_token ? "Gerar novo código" : "Gerar código de pareamento";
    $("#hb-line-box").hidden = !line;
    $("#hb-line").value = line;
  }
  async function load(path = "/api/hyperbooklm", body) {
    const n = ++seq, v = await api(path, body);
    if (n === seq) render(v);
    return v;
  }
  const connect = () => busy($("#hb-connect"), async () => {
    setBadge($("#hb-status"), ["", "refresh", "Testando a conexão…"]);
    const v = await load("/api/hyperbooklm/connect", { url: $("#hb-url").value }).catch((e) => { if (V) render(V); throw e; });
    if (S) S.config.hyperbooklm_on = true;
    $("#hb-url").value = v.hyperbooklm_url;
    toast(v.state === "connected" ? `HyperbookLM conectado${v.detected ? ` em ${v.hyperbooklm_url}` : ""}.`
      : `${v.detected ? `HyperbookLM encontrado em ${v.hyperbooklm_url}. ` : ""}${CONN[v.state][2]}. ${v.message}`, v.state === "connected" ? "success" : "warning");
  }).catch(fail);
  $("#hb-connect").addEventListener("click", connect);
  $("#hb-url").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
  $("#hb-open").addEventListener("click", () => open(V.hyperbooklm_url));
  const copy = () => navigator.clipboard.writeText(line).then(() => true, () => false);
  $("#hb-pair").addEventListener("click", () => busy($("#hb-pair"), async () => {
    const v = await api("/api/hyperbooklm/pair", {});
    line = v.line;
    render(v);
    const copied = await copy();
    toast(copied ? "Linha copiada. Cole no .env.local do HyperbookLM, reinicie-o e teste a conexão." : "Código gerado. Copie a linha e cole no .env.local do HyperbookLM.", copied ? "success" : "warning");
  }).catch(fail));
  $("#hb-copy").addEventListener("click", async () => {
    if (await copy()) toast("Linha copiada."); else { $("#hb-line").select(); toast("Não deu para copiar sozinho: use Ctrl+C.", "warning"); }
  });
  $("#hb-line").addEventListener("focus", (e) => e.target.select());
  $("#hb-disconnect").addEventListener("click", () => { line = ""; load("/api/hyperbooklm/disconnect", {}).then(() => { if (S) S.config.hyperbooklm_on = false; }).catch(fail); });

  // ---------- envio de uma aula ----------
  const dlg = $("#hb-dlg");
  let cur = null;  // { key, title } da aula no diálogo
  function show(st, error, duplicate) {
    const t = st.target, sent = st.state === "sent";
    $("#hb-dlg-what").textContent = !t.on ? "O HyperbookLM não está conectado. Abra Integrações → HyperbookLM para conectar."
      : !st.transcript && !sent ? "A transcrição desta aula não está mais guardada neste PC. O Lúmen guarda a da última aula publicada (ou de todas, com “Manter arquivos temporários” ligado)."
      : `Vai só o título da aula e o texto da transcrição, para o HyperbookLM em ${t.url}. Nenhum áudio, tela, anotação ou caminho de arquivo é enviado.`;
    const [tone, ic, text] = SENT[st.state] || SENT.none;
    setBadge($("#hb-dlg-state"), error ? ["error", "alert", error] : st.offline ? ["warn", "alert", `${text} ${st.offline}`]
      : duplicate ? ["ok", "check", "Esta transcrição já estava no HyperbookLM: nada foi reenviado."]
      : [tone, ic, st.state === "failed" && st.error ? `O envio falhou: ${st.error}` : text]);
    $("#hb-dlg-open").hidden = !sent;
    $("#hb-dlg-send").hidden = !(t.on && st.transcript && !sent);
    $("#hb-dlg-send").textContent = RETRY[st.state] || "Enviar";
    $("#hb-dlg-open").onclick = () => open(st.open_url);
  }
  const lessonState = (key, check) => api(`/api/hyperbooklm/lesson?key=${encodeURIComponent(key)}${check ? "&check=1" : ""}`);
  function lesson(key, title) {
    cur = { key, title };
    $("#hb-dlg-sub").textContent = title || "";
    setBadge($("#hb-dlg-state"), ["", "refresh", "Conferindo…"]);
    $("#hb-dlg-what").textContent = "";
    for (const id of ["#hb-dlg-open", "#hb-dlg-send"]) $(id).hidden = true;
    dlg.showModal();
    lessonState(key, true).then((st) => { if (dlg.open && cur?.key === key) show(st); }).catch(fail);
  }
  $("#hb-dlg-send").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const key = cur.key;
    setBadge($("#hb-dlg-state"), ["", "refresh", "Enviando a transcrição…"]);
    try {
      const st = await api("/api/hyperbooklm/send", { key });
      if (cur.key === key) show(st, "", st.duplicate);
    } catch (err) {  // o estado guardado (falhou ou não confirmado) e o motivo, lado a lado; o botão vira “Tentar de novo”
      const st = await lessonState(key).catch(() => null);
      if (st && cur.key === key) show(st, `${err.message} ${err.action || ""}`.trim()); else fail(err);
    }
  }));
  $("#hb-dlg-close").addEventListener("click", () => dlg.close());

  window.lumenHB = { load: () => load().catch(() => {}), lesson, enabled: () => !!S?.config.hyperbooklm_on };
  setTimeout(window.lumenHB.load, 1800);  // o selo da aba aparece mesmo antes de abri-la
})();
