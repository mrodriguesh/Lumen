"use strict";
const token = document.querySelector('meta[name="lumen-token"]').content;
const host = window.chrome?.webview;
const $ = (s) => document.querySelector(s);
let state = null, pending = false, collapse, errorUntil = 0;
let busy = "", errorKind = "", lastCommandDone = 0, armedUntil = 0, capsule = null;  // capsule: o que a cápsula de gravação mostra agora (null = ainda não desenhada)
let preferences = null, settingsBusy = false, settingsState = null, settingsPage = "menu", hasToken = false, confirmAction = null;
const clock = (s) => { s = Math.floor(s || 0); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].slice(s >= 3600 ? 0 : 1).map((n) => String(n).padStart(2, "0")).join(":"); };
async function api(path, body) {
  const opt = { headers: { "X-Lumen-Token": token } };
  if (body !== undefined) { opt.method = "POST"; opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  let r;
  try { r = await fetch(path, opt); } catch { throw new Error("Sem conexão com o Lumen. Tente novamente."); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error([d.error?.message || "Não foi possível concluir.", d.error?.action].filter(Boolean).join(" "));
  return d;
}
// Sensor de “Assistir a tela junto”: só mostra “vendo” quando a captura está de fato rodando (recording.screens).
function eyeSensor(d) {
  const r = d.recording, sc = r.screens;
  if (!r.active) return d.watch ? { mode: "armed", text: "Assistir ativado", tip: "A tela será vista junto com o som quando você gravar." } : null;
  if (r.paused && (sc || d.watch)) return { mode: "paused", text: "Tela em pausa", tip: "Captura pausada: nenhuma tela é guardada até você retomar." };
  if (sc?.refused && !sc.seen) return { mode: "warn", text: "Sem capturas", tip: `Ainda não guardei nenhuma tela: ${sc.why}.` };
  if (sc) return { mode: "live", text: "Vendo a tela", n: sc.seen, tip: `Assistindo a tela junto: ${sc.seen} tela${sc.seen === 1 ? "" : "s"} guardada${sc.seen === 1 ? "" : "s"}.` };
  return d.watch ? { mode: "warn", text: "Tela não vista", tip: "Esta gravação não está assistindo a tela." } : null;
}
function render(d) {
  state = d;
  pickNote(d);
  const r = d.recording, j = d.job;
  window.QuickChat?.recording(r);  // a conversa mostra, discreta, a gravação que continua
  const eye = eyeSensor(d);
  document.body.dataset.eye = eye?.mode || "off";
  $("#eye").hidden = !eye;
  if (eye) {
    $("#eye-text").textContent = eye.text;
    $("#eye-n").hidden = !eye.n;
    $("#eye-n").textContent = eye.n || "";
    $("#eye").dataset.tip = eye.tip;
    $("#eye").setAttribute("aria-label", eye.tip);
  }
  const music = r.active ? r.music_filter : d.music;  // a gravação vale pelo ajuste com que começou
  $("#music").hidden = !music;
  const musicTip = r.isolated ? `Filtro de música ativo: o som do ${r.isolated} fica fora da gravação.` : "Filtro de música ativo";
  $("#music").dataset.tip = musicTip;
  $("#music").setAttribute("aria-label", musicTip);
  document.body.dataset.state = r.error ? "error" : r.active ? "live" : "idle";
  document.body.dataset.heard = String(!!r.heard);
  const paused = !!(r.active && r.paused && !r.error);
  document.body.dataset.paused = String(paused);
  renderCapsule(r);
  renderListenChip(d.listening);
  Pomodoro.feed(d.pomodoro);
  $("#action-label").textContent = r.active ? "Parar" : "Gravar";
  $("#time").textContent = clock(r.active ? r.seconds : 0);
  document.body.dataset.job = j.status === "running" ? "running" : "";
  // curto: divide o topo com o Pomodoro; a frase inteira fica na dica e o detalhe da tarefa, no rodapé
  const [short, full] = r.error ? ["Interrompida", "Gravação interrompida"] : paused ? ["Pausada", "Captura pausada"] : r.active ? ["Gravando", "Gravando a aula"]
    : j.status === "running" ? (j.kind === "analyze" ? ["Analisando", "Analisando sua nota"] : j.kind === "download" ? ["Baixando", "Baixando"]
      : ["prepare", "transcribe", "screen"].includes(j.stage) ? ["Preparando", "Preparando a aula"] : ["Salvando", "Salvando o material"])
    : j.review ? ["Sua vez", "Escreva sua compreensão"] : ["Pronto", "Pronto para gravar"];
  $("#status").textContent = short;
  $("#status").parentElement.dataset.tip = full;
  $("#detail").textContent = r.error || (paused ? `Pausada há ${clock(r.paused_for)} · nada é gravado` : r.active && !r.heard ? "Dê play com o volume ligado." : "");
  const left = Number.isFinite(j.eta_total) ? ` · faltam ~${j.eta_total < 90 ? `${Math.max(5, Math.round(j.eta_total / 5) * 5)} s` : `${Math.round(j.eta_total / 60)} min`}` : "";
  $("#job").textContent = j.status === "running" ? `${j.detail || j.stage || "Processando"}${Number.isFinite(j.progress) ? ` · ${Math.round(j.progress * 100)}%` : ""}${left}` : j.review ? "Abra o Lumen e escreva sua compreensão" : "";
  $("#job").hidden = !$("#job").textContent;
  $("#job").dataset.tip = $("#job").textContent;  // o rodapé é estreito: a linha completa vai na dica
  const level = r.active && !r.error ? Math.min(1, Math.sqrt(Math.max(0, Number(r.level) || 0)) * 2) : 0;
  $("#action").style.setProperty("--lvl", level);
  const bars = document.querySelectorAll(".wave i");
  bars.forEach((b, i) => {
    const envelope = Math.sin(Math.PI * (i + 1) / (bars.length + 1));
    b.style.height = `${2 + 30 * level * envelope * (.3 + .7 * Math.abs(Math.sin(i * .8 + (r.seconds || 0) * 3)))}px`;
  });
}
// A cápsula (Gravar/Encerrar + Pausar/Retomar) mostra SEMPRE o estado do servidor, e a animação roda quando esse estado MUDA, não a cada leitura.
// `r` é o `recording` do servidor; vale também durante o aviso de erro de um comando (o texto do painel fica, o estado real não).
function renderCapsule(r) {
  const on = !!(r.active && !r.error), paused = on && !!r.paused, first = capsule === null, body = document.body;
  const pause = $("#pause"), action = $("#action"), want = paused ? "play" : "pause", before = pause.querySelector("svg.i")?.dataset.icon;
  $("#rec-group").dataset.paused = String(paused);
  $("#pause-label").textContent = paused ? "Retomar gravação" : "Pausar gravação";
  ui.setIcon(pause, want);
  if (before && before !== want && !first) { pause.dataset.swap = ""; setTimeout(() => delete pause.dataset.swap, 260); }  // o ícone troca com um esmaecer curto
  pause.dataset.tip = `${paused ? "Retomar" : "Pausar"} gravação (o vídeo continua)`;  // curta: a dica não cobre os controles vizinhos
  pause.dataset.kbd = Shortcuts.capture.label;
  if (!busy) action.setAttribute("aria-label", on ? "Encerrar gravação" : "Iniciar gravação");
  if (first) body.dataset.capsule = "init";  // página recém-carregada (ou barra que abriu já gravando): aparece pronta, sem animar
  if (body.dataset.rec !== (on ? "on" : "off")) {
    if (!on && pause.contains(document.activeElement)) action.focus();  // a pausa vai sair de cena: o foco não se perde
    body.dataset.rec = on ? "on" : "off";
  }
  if (first) requestAnimationFrame(() => requestAnimationFrame(() => delete body.dataset.capsule));
  else if (capsule.on !== on) say(on ? "Gravação iniciada." : "Gravação encerrada.");
  else if (capsule.paused !== paused) say(paused ? "Gravação pausada." : "Gravação retomada.");
  capsule = { on, paused };
}
const say = (text) => { const l = $("#rec-live"); l.textContent = ""; setTimeout(() => { l.textContent = text; }, 30); };  // leitor de tela: só quando o estado muda
// Espera REAL de um comando ao servidor (iniciar, encerrar, pausar, retomar): um anel gira no botão certo, os dois botões recusam cliques
// (aria-disabled, para o foco do teclado não se perder) e o painel diz o que está acontecendo. Sem comando, nada anima.
const BUSY = { start: ["Iniciando…", "Iniciando gravação…"], stop: ["Encerrando…", "Encerrando gravação…"], pause: ["Pausando…"], resume: ["Retomando…"] };
function setBusy(kind) {
  busy = kind;
  document.body.dataset.busy = kind;
  const action = $("#action"), pause = $("#pause");
  for (const b of [action, pause]) b.setAttribute("aria-disabled", String(!!kind));
  const spin = (b, on) => (on ? b.setAttribute("aria-busy", "true") : b.removeAttribute("aria-busy"));
  spin(action, kind === "start" || kind === "stop");
  spin(pause, kind === "pause" || kind === "resume");
  if (kind) { $("#status").textContent = BUSY[kind][0]; if (BUSY[kind][1]) action.setAttribute("aria-label", BUSY[kind][1]); }
}
async function poll() {
  const asked = performance.now();
  try {
    const d = await api("/api/widget");
    delete document.body.dataset.conn;
    if (d.ui === "glass" || d.ui === "classic") document.documentElement.dataset.ui = d.ui;  // idem para o estilo da interface (Ajustes → Aparência)
    // uma leitura pedida ANTES de um comando que já terminou é velha: descartá-la evita a cápsula "voltar atrás" por um instante
    if (!pending && asked >= lastCommandDone) {
      if (errorKind === "start" && d.recording.active) errorUntil = 0;  // outra janela começou a gravar: o aviso de falha não vale mais
      if (Date.now() >= errorUntil) render(d); else { state = d; renderCapsule(d.recording); }
    }
    renderSettingsJob(d.job);
  }
  catch { document.body.dataset.state = "error"; document.body.dataset.conn = "lost"; $("#status").textContent = "Sem conexão com o Lumen."; }
  setTimeout(poll, state?.recording.active ? 250 : 1000);
}
// Depois de uma falha, o estado mostrado volta a ser o do servidor (o comando pode ter valido ou não): uma leitura, sem polling a mais
async function reconcile() { try { const d = await api("/api/widget"); state = d; renderCapsule(d.recording); } catch { /* o poll tenta de novo */ } }
async function toggleRecording() {
  if (pending || !state) return;
  const stopping = !!state.recording.active && !state.recording.error;
  if (stopping && performance.now() < armedUntil) return;  // um duplo clique logo depois de iniciar não encerra a gravação que acabou de começar
  pending = true;
  errorUntil = 0;
  setBusy(stopping ? "stop" : "start");
  try {
    const fresh = await api("/api/widget"), r = fresh.recording;
    if (!!r.active !== stopping) {  // o estado mudou enquanto a pessoa olhava (outra janela): mostra o real e NÃO age (nunca encerra o que ela não viu gravando)
      render(fresh);
      return;
    }
    if (stopping) {
      const file = await api("/api/record/stop", {});
      host?.postMessage("record:ready:" + JSON.stringify({ file, seconds: r.seconds }));
    } else {
      await api("/api/record/start", {});
      host?.postMessage("record:started");
      armedUntil = performance.now() + 700;
    }
    render(await api("/api/widget"));
    lastCommandDone = performance.now();
  } catch (e) {
    $("#status").textContent = "Não foi possível gravar.";
    $("#detail").textContent = e.message;
    document.body.dataset.state = "error";
    errorUntil = Date.now() + 8000;
    errorKind = stopping ? "stop" : "start";
    await reconcile();  // o aviso fica no painel, mas a cápsula mostra o que o servidor realmente está fazendo
    lastCommandDone = performance.now();
  } finally {
    pending = false;
    setBusy("");
    syncActionLabel();
  }
}
const syncActionLabel = () => $("#action").setAttribute("aria-label", capsule?.on ? "Encerrar gravação" : "Iniciar gravação");
$("#action").addEventListener("click", toggleRecording);
// Pausar captura: a mesma gravação continua depois; o vídeo e os outros programas não são tocados.
async function togglePause() {
  if (pending || !state?.recording.active || state.recording.error) return;
  const resume = !!state.recording.paused;
  pending = true;
  errorUntil = 0;
  setBusy(resume ? "resume" : "pause");
  try {
    await api(resume ? "/api/record/resume" : "/api/record/pause", {});
    render(await api("/api/widget"));
    lastCommandDone = performance.now();
  } catch (e) {
    $("#status").textContent = resume ? "Não foi possível retomar." : "Não foi possível pausar.";
    $("#detail").textContent = e.message;
    errorUntil = Date.now() + 6000;
    errorKind = "pause";
    await reconcile();
    lastCommandDone = performance.now();
  } finally {
    pending = false;
    setBusy("");
    syncActionLabel();
  }
}
$("#pause").addEventListener("click", togglePause);
document.addEventListener("keydown", (e) => { if (Shortcuts.capture.test(e)) { e.preventDefault(); togglePause(); } });
Pomodoro.mount($("#pomo-main"));
Pomodoro.mount($("#pomo-note"));
$("#open").addEventListener("click", () => host?.postMessage("window:open"));
function showPreferences(open) {
  if (open && noteOpen) showNote(false);
  if (open && chatOpen) showChat(false);
  if (open && listenOpen) showListen(false);
  $("#preferences").hidden = !open;
  $("#recording-panel").hidden = open || noteOpen || chatOpen || listenOpen;
  $("#settings").setAttribute("aria-expanded", String(open));
  if (!open) $("#prefs-token").value = "";
  if (!open && document.body.dataset.panel === "protection") {
    document.body.dataset.panel = "main"; host?.postMessage("widget:panel:main");
  }
}
function settingsFeedback(message, error = false) {
  $("#prefs-feedback").textContent = message;
  $("#prefs-feedback").dataset.error = String(error);
}
function renderPreferences() {
  document.querySelectorAll("[data-position]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.position === preferences?.widget)));
  $("#position-caption").textContent = $("[data-position][aria-pressed=true]")?.getAttribute("aria-label") || "";
  $("#prefs-autostart").setAttribute("aria-checked", String(!!preferences?.autostart));
  $("#prefs-keep").setAttribute("aria-checked", String(!!preferences?.keep_temp));
  $("#prefs-watch").setAttribute("aria-checked", String(!!preferences?.watch_screen));
  document.querySelector(".prefs-watch").dataset.on = String(!!preferences?.watch_screen);
  $("#watch-sub").textContent = preferences?.watch_screen ? (state?.recording.active ? "Vale na próxima gravação" : "Ativado · lido no seu PC") : "Slides e código na página";
  $("#prefs-token-status").textContent = hasToken ? "Conectado · token no cofre do Windows" : "Conecte sua integração do Notion";
  $("#prefs-model").value = preferences?.ollama_model || "";
  $("#prefs-language").value = preferences?.page_language || "pt";
  if (!$("#prefs-root").options.length) $("#prefs-root").add(new Option(preferences?.root_page_title || "Escolha uma página", preferences?.root_page_id || ""));
  document.querySelectorAll("#prefs-content button, #prefs-content input, #prefs-content select").forEach((b) => { if (!b.closest('[data-protection]')) b.disabled = settingsBusy || !preferences; });
  $("#prefs-root").disabled ||= !hasToken;
  $("#prefs-root-load").disabled ||= !hasToken;
  $("#prefs-quality").disabled = settingsBusy || !preferences || !settingsState;
  $("#prefs-clear").disabled ||= !!state?.recording.active || state?.job.status === "running";
  $("#prefs-forget").disabled ||= !!state?.recording.active || state?.job.status === "running";
  renderAdvanced();
  renderSettingsJob(state?.job);
}
function navigatePreferences(page) {
  settingsPage = page;
  if (page === "protection" || document.body.dataset.panel === "protection") {
    document.body.dataset.panel = page === "protection" ? "protection" : "main";
    host?.postMessage("widget:panel:" + document.body.dataset.panel);
  }
  document.querySelectorAll("[data-page]").forEach((p) => p.hidden = p.dataset.page !== page);
  $("#prefs-title").textContent = ({menu:"Ajustes",protection:"Proteção do cérebro",desktop:"Barra flutuante",notion:"Notion",transcription:"Transcrição",ai:"IA local",covers:"Capas do Notion",privacy:"Privacidade",confirm:"Confirmar"})[page];
  $("#prefs-back").setAttribute("aria-label", page === "menu" ? "Voltar à gravação" : "Voltar aos ajustes");
  $("#prefs-content").scrollTop = 0;
}
function renderAdvanced() {
  if (!settingsState || !preferences) return;
  const s = settingsState, q = preferences.quality, w = s.whisper.models[q];
  if (!$("#prefs-quality input")) {
    $("#prefs-quality-options").replaceChildren(...Object.entries(s.whisper.models).map(([value,m]) => {
      const label = document.createElement("label"), input = document.createElement("input"), text = document.createElement("span");
      input.type = "radio"; input.name = "prefs-quality"; input.value = value;
      text.textContent = m.label; label.append(input,text); return label;
    }));
  }
  document.querySelectorAll("#prefs-quality input").forEach((input) => input.checked = input.value === q);
  $("#prefs-hardware").textContent = s.gpu ? "Transcrição na GPU NVIDIA" : "Transcrição pelo processador";
  $("#prefs-whisper-status").textContent = w ? `${w.name} · ${w.size} · ${w.downloaded ? "Instalado" : "Não instalado"}` : "Selecione a qualidade";
  $("#prefs-whisper-dl").hidden = !w || w.downloaded;
  $("#prefs-model-list").replaceChildren(...s.ollama.models.map((m) => new Option(m,m)));
  const installed = s.ollama.models.some((m) => m === preferences.ollama_model || m === preferences.ollama_model + ":latest");
  $("#prefs-ollama-status").textContent = !s.ollama.running ? "Abra o Ollama para usar a IA local." : installed ? "Modelo instalado no PC" : "Modelo ainda não instalado";
  $("#prefs-ollama-dl").hidden = !s.ollama.running || installed;
  $("#prefs-covers-status").textContent = `${s.covers.label} · ${s.covers.size}\n${s.covers.ready ? "Instalado · capas geradas no PC" : "Sem o gerador, as capas usam emojis."}`;
  $("#prefs-covers-dl").hidden = s.covers.ready;
}
async function loadRoots() {
  const { pages } = await api("/api/notion/pages"), sel = $("#prefs-root");
  sel.replaceChildren(new Option(pages.length ? "Escolha uma página" : "Nenhuma página compartilhada", ""));
  pages.forEach((p) => { const o = new Option(p.path,p.id); o.dataset.title = p.title; sel.add(o); });
  sel.value = preferences.root_page_id;
}
async function openCategory(page) {
  if (settingsBusy || !preferences) return;
  navigatePreferences(page); settingsFeedback("");
  if (!["transcription","ai","covers"].includes(page) && !(page === "notion" && hasToken)) return;
  settingsBusy = true; renderPreferences(); settingsFeedback("Carregando…");
  try {
    if (page === "notion") await loadRoots();
    else { settingsState = await api("/api/state"); preferences.quality = settingsState.whisper.active; renderAdvanced(); }
    settingsFeedback("");
  } catch (e) { settingsFeedback(e.message, true); }
  finally { settingsBusy = false; renderPreferences(); }
}
async function openPreferences() {
  if (!$("#preferences").hidden) { showPreferences(false); return; }
  showPreferences(true);
  if (settingsBusy) return;
  navigatePreferences("menu");
  settingsState = null; $("#prefs-root").replaceChildren(); $("#prefs-token").value = "";
  settingsBusy = true; preferences = null; renderPreferences(); settingsFeedback("Carregando…");
  try {
    const d = await api("/api/widget?view=settings"); preferences = d.config; hasToken = d.has_token;
    if (["left", "right", "top", "bottom", "free"].includes(document.body.dataset.edge)) preferences.widget = document.body.dataset.edge;
    settingsFeedback("");
  } catch (e) { settingsFeedback(e.message, true); }
  finally { settingsBusy = false; renderPreferences(); }
}
async function savePreferences(body) {
  if (settingsBusy || !preferences) return;
  const focused = document.activeElement;
  settingsBusy = true; renderPreferences(); settingsFeedback("Salvando…");
  try {
    const d = await api("/api/settings?view=settings", body), saved = d.config; hasToken = d.has_token;
    preferences = { ...saved, widget: body.widget || preferences.widget };
    if (body.widget) { host?.postMessage("desktop:prefs:" + saved.widget); if (!["free","off"].includes(body.widget)) host?.postMessage("widget:reset"); }
    host?.postMessage("widget:preferences");
    settingsFeedback("Salvo");
    return true;
  } catch (e) { settingsFeedback(e.message, true); return false; }
  finally {
    settingsBusy = false; renderPreferences();
    if (focused?.matches("#prefs-quality input") && document.activeElement === document.body && !$("#preferences").hidden && settingsPage === "transcription") focused.focus();
  }
}
$("#settings").addEventListener("click", openPreferences);
function backPreferences() {
  if (settingsPage !== "menu") { navigatePreferences("menu"); $("[data-category]").focus(); }
  else { showPreferences(false); $("#settings").focus(); }
}
$("#prefs-back").addEventListener("click", backPreferences);
document.querySelectorAll("[data-category]").forEach((b) => b.addEventListener("click", () => openCategory(b.dataset.category)));
document.querySelectorAll("[data-position]").forEach((b) => b.addEventListener("click", () => savePreferences({ widget: b.dataset.position })));
$("#prefs-autostart").addEventListener("click", () => savePreferences({ autostart: !preferences.autostart }));
$("#prefs-reset").addEventListener("click", () => { host?.postMessage("widget:reset"); settingsFeedback("Posição restaurada"); });
$("#prefs-off").addEventListener("click", () => savePreferences({widget:"off"}));
$("#prefs-exit").addEventListener("click", () => host?.postMessage("window:exit"));
$("#prefs-watch").addEventListener("click", () => savePreferences({ watch_screen: !preferences.watch_screen }));
$("#prefs-keep").addEventListener("click", () => savePreferences({keep_temp:!preferences.keep_temp}));
$("#prefs-language").addEventListener("change", (e) => savePreferences({page_language:e.target.value}));
$("#prefs-quality").addEventListener("change", (e) => savePreferences({quality:e.target.value}));
$("#prefs-model-save").addEventListener("click", () => {
  const model = $("#prefs-model").value.trim();
  if (!model) { settingsFeedback("Informe o nome do modelo.",true); $("#prefs-model").focus(); return; }
  savePreferences({ollama_model:model});
});
$("#prefs-token-save").addEventListener("click", async () => {
  const token = $("#prefs-token").value.trim();
  if (!token) { $("#prefs-token").focus(); return; }
  if (await savePreferences({notion_token:token})) { $("#prefs-token").value = ""; await openCategory("notion"); }
});
$("#prefs-root-load").addEventListener("click", () => openCategory("notion"));
$("#prefs-root").addEventListener("change", (e) => {
  const o = e.target.selectedOptions[0];
  savePreferences({root_page:o.value,root_page_title:o.dataset.title || ""}).then(() => { $("#prefs-root").value = preferences.root_page_id; });
});
document.querySelectorAll("#preferences a").forEach((a) => a.addEventListener("click", (e) => {
  if (host) { e.preventDefault(); host.postMessage("window:external:" + a.href); }
}));
let downloading = false, lastSettingsJob = "";
function renderSettingsJob(j) {
  document.querySelectorAll("[data-download]").forEach((b) => b.disabled = settingsBusy || !settingsState || j?.status === "running");
  for (const id of ["#prefs-clear","#prefs-forget"]) $(id).disabled = settingsBusy || !preferences || !!state?.recording.active || j?.status === "running";
  if (!downloading || !j || $("#preferences").hidden) return;
  if (j.status === "running") { settingsFeedback(`${j.detail || "Baixando…"}${Number.isFinite(j.progress) ? ` ${Math.round(j.progress*100)}%` : ""}`); return; }
  if (j.status === lastSettingsJob) return;
  lastSettingsJob = j.status;
  if (j.status === "error") { downloading = false; settingsFeedback([j.error?.message,j.error?.action].filter(Boolean).join(" ") || "Falha no download. Tente novamente.",true); }
  else if (j.status === "cancelled") { downloading = false; settingsFeedback("Download cancelado"); }
  else if (j.status === "done") {
    downloading = false;
    if (!settingsBusy) openCategory(settingsPage).then(() => settingsFeedback("Download concluído"));
  }
}
document.querySelectorAll("[data-download]").forEach((b) => b.addEventListener("click", async () => {
  if (settingsBusy || state?.job.status === "running") return;
  settingsBusy = true; renderPreferences(); settingsFeedback("Iniciando download…");
  try { const j = await api("/api/download",{what:b.dataset.download,quality:preferences.quality}); downloading = true; lastSettingsJob = ""; if (state) state.job = j; }
  catch (e) { settingsFeedback(e.message,true); }
  finally { settingsBusy = false; renderPreferences(); }
}));
function confirmPreferences(action) {
  if (settingsBusy) return;
  confirmAction = action;
  $("#prefs-confirm-text").textContent = action === "forget" ? "Desconectar o Notion? O token será removido do cofre do Windows e o histórico local (com as notas de compreensão guardadas aqui) será apagado." : "Apagar histórico, transcrições, suas notas de compreensão guardadas e arquivos temporários deste PC? As páginas no Notion serão mantidas.";
  navigatePreferences("confirm"); settingsFeedback(""); $("#prefs-cancel").focus();
}
$("#prefs-clear").addEventListener("click", () => confirmPreferences("clear"));
$("#prefs-forget").addEventListener("click", () => confirmPreferences("forget"));
$("#prefs-cancel").addEventListener("click", () => { navigatePreferences("privacy"); confirmAction = null; });
$("#prefs-confirm").addEventListener("click", async () => {
  if (settingsBusy || !confirmAction) return;
  settingsBusy = true; renderPreferences(); settingsFeedback("Aplicando…");
  try {
    const d = await api("/api/clear",{forget_token:confirmAction === "forget"});
    preferences = {...d.config,widget:preferences.widget}; hasToken = d.has_token; settingsState = d;
    if (confirmAction === "forget") { $("#prefs-root").replaceChildren(); try { localStorage.removeItem("lumen.pages"); } catch {} }
    host?.postMessage("widget:preferences"); navigatePreferences("privacy"); settingsFeedback("Concluído"); confirmAction = null;
  } catch (e) { settingsFeedback(e.message,true); }
  finally { settingsBusy = false; renderPreferences(); }
});
$("#exit").addEventListener("click", () => host?.postMessage("window:exit"));
$("#drag").addEventListener("pointerdown", (e) => { if (e.button === 0) { clearTimeout(collapse); host?.postMessage("widget:drag"); } });
$("#drag").addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPreferences(); } });
// ---------- Minha compreensão na barra lateral ----------
// O mesmo documento da janela principal e da janela flutuante (understanding-editor.js): o que se escreve aqui aparece
// lá na hora, e vice-versa. Mostra a aula aberta no Lumen ou, sem ela, a última que espera a compreensão.
let noteKey = null, noteOpen = false;
const noteEditor = new UnderstandingEditor({ text: $("#note-text"), save: $("#note-save"), count: $("#note-count"), mode: "side",
  onChange: (d) => { $("#note-lesson").textContent = d.view?.title || ""; } });
const writing = () => (noteOpen && document.hasFocus() && document.activeElement === $("#note-text")) || (chatOpen && QuickChat.writing());
// A nota é a da aula em foco no Lumen (a mesma da janela principal e da flutuante). Se essa aula já não está na lista
// (salva no Notion), vale a mais recente, e ela passa a ser a aula em foco para as outras janelas também.
let missed = 0;
function pickNote(d, fresh = true) {
  const notes = d.notes || [], active = Notes.active();
  let n = notes.find((x) => x.key === active) || null;
  // A aula em foco pode ainda não estar na lista (acabou de abrir): só troca de aula se faltar em duas leituras
  // seguidas do servidor, e nunca ao receber o aviso de outra janela (a lista pode ser a anterior).
  if (fresh) missed = n ? 0 : missed + 1;
  if (!n && fresh && missed >= 2 && notes[0]) { n = notes[0]; Notes.setActive(n.key); missed = 0; }
  if (fresh) notes.forEach((x) => Notes.merge(x.key, x));  // o que bloqueia “Processar” e textos mais novos, sem polling a mais
  document.body.dataset.note = String(!!n || !!noteKey);
  $("#note-btn").hidden = !n && !noteKey;
  if (!n) { if (fresh && missed >= 2) { if (noteOpen) showNote(false); noteKey = null; } return; }
  if (n.key !== noteKey) { noteKey = n.key; if (noteOpen) bindNote(); }
}
Notes.on("active", () => { if (state) pickNote(state, false); });  // outra janela abriu outra aula: esta acompanha na hora
let unbindStatus = null;
async function bindNote() {
  try {
    await Notes.load(noteKey); noteEditor.bind(noteKey);
    unbindStatus?.();
    unbindStatus = Notes.bindStatus(noteKey, { box: $("#note-status"), text: $("#note-ready"), go: $("#note-go"), compact: true });
  } catch (e) { $("#note-save").textContent = e.message; }
}
$("#note-go").addEventListener("click", async () => {
  try { await Notes.process(noteKey); } catch (e) { $("#note-ready").textContent = e.message; }
});
function showNote(open) {
  if (open && !noteKey) return;
  if (open && chatOpen) showChat(false);
  if (open && listenOpen) showListen(false);
  noteOpen = open;
  if (open) { $("#preferences").hidden = true; $("#settings").setAttribute("aria-expanded", "false"); }
  $("#note-panel").hidden = !open;
  $("#recording-panel").hidden = open || !$("#preferences").hidden || chatOpen || listenOpen;
  $("#note-btn").setAttribute("aria-expanded", String(open));
  document.body.dataset.panel = open ? "note" : "";
  host?.postMessage(open ? "widget:panel:note" : "widget:panel:main");  // a barra cresce para caber a nota
  if (open) bindNote().then(() => { const t = $("#note-text"); t.focus(); t.setSelectionRange(t.value.length, t.value.length); });
  else { noteEditor.unbind(); unbindStatus?.(); unbindStatus = null; }
}
async function detachNote() {  // a mesma nota numa janela flutuante, maior e por cima do vídeo
  if (!noteKey) return;
  await Notes.flush(noteKey);
  Notes.setActive(noteKey);  // a janela principal e a flutuante passam a mostrar esta mesma aula
  Notes.setPref("Mode", "floating"); Notes.setPref("Key", noteKey);
  host?.postMessage("note:float:" + noteKey);
  conceal(); host?.postMessage("widget:collapse");
}
// ---------- Conversa rápida (chat.js) ----------
// O mesmo cérebro do Lumen, sem abrir a janela principal. Abre no tamanho compacto de sempre (a mesma janela de 304×252 da gravação:
// widget:panel:chat) ou, se a pessoa pediu no menu, ampliada (widget:panel:chat-wide). A página não escolhe pixels: só diz ao Lumen.exe
// qual das duas quer, e o painel ocupa o que a janela entregar (widget.css). O texto, as mensagens e a resposta em andamento vivem em
// chat.js: trocar de painel, recolher e reabrir não perdem nada.
let chatOpen = false;
const chatPanelMessage = () => (QuickChat.wide() ? "widget:panel:chat-wide" : "widget:panel:chat");
function showChat(open) {
  if (open === chatOpen) return;
  if (open) { if (noteOpen) showNote(false); if (listenOpen) showListen(false); showPreferences(false); }
  chatOpen = open;
  $("#chat-panel").hidden = !open;
  $("#recording-panel").hidden = open || noteOpen || listenOpen || !$("#preferences").hidden;
  $("#chat-btn").setAttribute("aria-expanded", String(open));
  document.body.dataset.panel = open ? "chat" : "";
  host?.postMessage(open ? chatPanelMessage() : "widget:panel:main");  // a barra só cresce se a conversa foi ampliada (ou volta ao tamanho de antes)
  QuickChat.setOpen(open);
}
$("#chat-btn").addEventListener("click", () => showChat(!chatOpen));
document.addEventListener("quickchat:collapse", () => { conceal(); host?.postMessage("widget:collapse"); });
document.addEventListener("quickchat:size", () => { if (chatOpen) host?.postMessage(chatPanelMessage()); });  // "Ampliar" / "Reduzir" no menu
$("#note-btn").addEventListener("click", () => showNote(!noteOpen));
$("#note-back").addEventListener("click", () => { showNote(false); $("#note-btn").focus(); });
$("#note-detach").addEventListener("click", detachNote);
$("#note-detach").dataset.kbd = Notes.shortcutLabel;
document.addEventListener("keydown", (e) => { if (noteOpen && Notes.isShortcut(e)) { e.preventDefault(); detachNote(); } });
// ---------- Modo escuta (lumen/listening.py) ----------
// Microfone + som do PC transcritos ao vivo numa página do Notion e numa nota do Obsidian. O painel usa o tamanho da nota (360×440:
// widget:panel:note); o servidor guarda tudo num diário e cada destino copia dele, então fechar o painel ou recolher a barra não para nada.
let listenOpen = false, listenTimer = 0, listenData = null, listenBusy = false, listenSession = "", listenLast = -1;
const LISTEN_STATE = { live: ["ok", "Ao vivo"], done: ["ok", "Completo"], setup: ["warn", "Configurar"], error: ["warn", "Tentando de novo"] };
function renderListenChip(L) {
  const on = !!L?.active, finishing = L?.phase === "finishing", chip = $("#listen-chip");
  document.body.dataset.listening = on ? "live" : finishing ? "finishing" : "";
  $("#listen-chip-time").textContent = on || finishing ? clock(L.seconds) : "";
  chip.setAttribute("aria-label", on ? `Modo escuta ligado, ${clock(L.seconds)}` : finishing ? "Modo escuta finalizando" : "Modo escuta");
  chip.dataset.tip = on ? "Escutando a chamada: abrir o modo escuta" : finishing ? "Terminando de gravar o texto" : "Modo escuta: transcrever uma chamada";
}
function renderListen(d) {
  listenData = d;
  const phase = d.phase || "idle", on = !!d.active, panel = $("#listen-panel");
  panel.dataset.phase = phase;
  $("#listen-time").textContent = clock(d.seconds || 0);
  $("#listen-toggle-label").textContent = on ? "Parar escuta" : phase === "finishing" ? "Terminando…" : "Começar a escutar";
  $("#listen-toggle").setAttribute("aria-disabled", String(phase === "finishing" || listenBusy));
  for (const src of document.querySelectorAll(".listen-src")) {
    const k = src.dataset.src, st = d.sources?.[k] || "idle";
    src.dataset.state = on ? st : "idle";
    src.style.setProperty("--lvl", on && st === "on" ? Math.min(1, Math.sqrt(Math.max(0, d.levels?.[k] || 0)) * 2) : 0);
  }
  if ((d.title || "") !== listenSession) { listenSession = d.title || ""; listenLast = -1; $("#listen-lines").replaceChildren(); }
  const list = $("#listen-lines"), stick = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
  for (const l of d.lines || []) {
    if (l.n <= listenLast) continue;
    listenLast = l.n;
    const li = document.createElement("li"), meta = document.createElement("span"), text = document.createElement("p");
    meta.className = "listen-meta"; meta.textContent = `${l.t} · ${l.who}`; li.dataset.who = l.who === "Você" ? "me" : "them";
    text.textContent = l.text; li.append(meta, text); list.append(li);
  }
  while (list.children.length > 40) list.firstElementChild.remove();
  list.dataset.empty = String(!list.children.length);
  list.dataset.hint = on ? "Ouvindo… o texto aparece aqui quando alguém fala." : "O texto da chamada aparece aqui, ao vivo, e vai para o Notion e o Obsidian.";
  if (stick) list.scrollTop = list.scrollHeight;
  for (const name of ["notion", "obsidian"]) {
    const row = document.querySelector(`.listen-dests [data-dest="${name}"]`), s = d[name], el = row.querySelector(".listen-dest-state");
    const [tone, label] = !s ? ["", name === "notion" ? "Uma página por chamada" : "Pasta Chamadas"]
      : s.state === "sending" ? ["busy", `${s.pending} na fila`] : LISTEN_STATE[s.state] || ["", ""];
    row.dataset.tone = tone; el.textContent = label;
    if (s?.message) { row.dataset.tip = s.message; el.setAttribute("aria-description", s.message); } else { delete row.dataset.tip; el.removeAttribute("aria-description"); }
    row.querySelector("[data-open]").hidden = !(name === "notion" ? s?.url : s?.path);
  }
  $("#listen-error").textContent = d.error || "";
}
async function pollListen() {
  clearTimeout(listenTimer);
  try { renderListen(await api("/api/listen")); } catch (e) { $("#listen-error").textContent = e.message; }
  if (listenOpen) listenTimer = setTimeout(pollListen, listenData?.active || listenData?.phase === "finishing" ? 400 : 1500);
}
function showListen(open) {
  if (open === listenOpen) return;
  if (open) { if (noteOpen) showNote(false); if (chatOpen) showChat(false); showPreferences(false); }
  listenOpen = open;
  $("#listen-panel").hidden = !open;
  $("#recording-panel").hidden = open || noteOpen || chatOpen || !$("#preferences").hidden;
  $("#listen-chip").setAttribute("aria-expanded", String(open));
  document.body.dataset.panel = open ? "listen" : "";
  host?.postMessage(open ? "widget:panel:note" : "widget:panel:main");  // o mesmo tamanho da nota: o Lumen.exe não precisa mudar
  clearTimeout(listenTimer);
  if (open) { pollListen(); requestAnimationFrame(() => $("#listen-toggle").focus()); }
}
async function toggleListen() {
  if (listenBusy || listenData?.phase === "finishing") return;
  const stopping = !!listenData?.active, b = $("#listen-toggle");
  listenBusy = true; b.setAttribute("aria-busy", "true"); b.setAttribute("aria-disabled", "true");
  $("#listen-toggle-label").textContent = stopping ? "Parando…" : "Abrindo o som…";
  $("#listen-error").textContent = "";
  try { renderListen(await api(stopping ? "/api/listen/stop" : "/api/listen/start", {})); say(stopping ? "Escuta parada." : "Escuta ligada."); }
  catch (e) { $("#listen-error").textContent = e.message; }
  finally { listenBusy = false; b.removeAttribute("aria-busy"); if (listenData) renderListen(listenData); pollListen(); }
}
async function openListen(target) {
  try {
    const r = await api("/api/listen/open", { target });
    if (r.url) { if (host) host.postMessage("window:external:" + r.url); else window.open(r.url, "_blank", "noopener"); }
  } catch (e) { $("#listen-error").textContent = e.message; }
}
$("#listen-chip").addEventListener("click", () => showListen(!listenOpen));
$("#listen-back").addEventListener("click", () => { showListen(false); $("#listen-chip").focus(); });
$("#listen-toggle").addEventListener("click", toggleListen);
document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openListen(b.dataset.open)));
function syncPresentation() {
  if (!host) return;
  document.body.dataset.expanded = String(innerWidth > 100 || innerHeight > 100);
  if (document.body.dataset.expanded === "false" && !writing()) { document.activeElement?.blur(); showPreferences(false); if (chatOpen) showChat(false); if (listenOpen) showListen(false); }
  else if (document.body.dataset.expanded === "true") QuickChat.expanded();
}
function expand() { clearTimeout(collapse); if (!host) document.body.dataset.expanded = "true"; host?.postMessage("widget:expand"); QuickChat.expanded(); }
// Recolher só esconde a barra: o texto e as mensagens da conversa (e uma resposta em andamento) continuam onde estão.
function conceal() { clearTimeout(collapse); if (!host) document.body.dataset.expanded = "false"; document.activeElement?.blur(); showPreferences(false); if (noteOpen) showNote(false); if (chatOpen) showChat(false); if (listenOpen) showListen(false); }
function retract() {
  clearTimeout(collapse);
  if (writing()) return;  // escrevendo a nota ou a mensagem: a barra não se recolhe embaixo do cursor
  if (chatOpen && QuickChat.engaged()) return;  // conversando: com o foco aqui, o mouse sair não recolhe (recolhe ao clicar em outro programa)
  collapse = setTimeout(() => { conceal(); host?.postMessage("widget:collapse"); }, 450);
}
window.addEventListener("blur", () => { if ((noteOpen || chatOpen) && !document.documentElement.matches(":hover")) retract(); });
$("#peek").addEventListener("click", expand);
document.documentElement.addEventListener("pointerenter", expand);
document.documentElement.addEventListener("pointerleave", retract);
document.addEventListener("focusin", expand);
// Esc: fecha primeiro o que estiver aberto por cima (ajustes, menu da conversa); depois recolhe a barra.
// Nunca encerra o Lumen, nunca interrompe a gravação nem uma resposta; o Esc que fecha uma composição (IME) não conta.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.isComposing) return;
  if (!$("#preferences").hidden) backPreferences();
  else if (chatOpen && QuickChat.escape()) return;
  else { conceal(); host?.postMessage("widget:collapse"); }
});
host?.addEventListener("message", (e) => {
  if (e.data === "side:left" || e.data === "side:right") document.body.dataset.side = e.data.slice(5);
  else if (["edge:left", "edge:right", "edge:top", "edge:bottom", "edge:free"].includes(e.data)) {
    document.body.dataset.edge=e.data.slice(5);
    // na barra deitada a dica abre para o lado de dentro do painel (à direita ela cobriria os controles vizinhos, como a pausa ao lado do Gravar)
    const tipSide = { top: "bottom", bottom: "top" }[document.body.dataset.edge] || "right";
    document.querySelectorAll(".rail [data-tip-pos]").forEach((b) => { b.dataset.tipPos = tipSide; });
    if (preferences && !settingsBusy) { preferences.widget = document.body.dataset.edge; renderPreferences(); }
  }
});
window.addEventListener("resize", syncPresentation);
syncPresentation();
poll();
