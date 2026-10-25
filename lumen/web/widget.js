"use strict";
const token = document.querySelector('meta[name="lumen-token"]').content;
const host = window.chrome?.webview;
const $ = (s) => document.querySelector(s);
let state = null, pending = false, collapse, errorUntil = 0;
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
  $("#pause").hidden = !r.active || !!r.error;
  $("#pause-label").textContent = paused ? "Retomar captura" : "Pausar captura";
  ui.setIcon($("#pause"), paused ? "play" : "pause");
  $("#pause").dataset.tip = `${paused ? "Retomar" : "Pausar"} a captura do som e da tela. O vídeo não é pausado.`;
  $("#pause").dataset.kbd = Shortcuts.capture.label;
  Pomodoro.feed(d.pomodoro);
  const label = r.active ? "Parar e usar gravação" : "Iniciar gravação";
  $("#action").setAttribute("aria-label", label);
  $("#action-label").textContent = r.active ? "Parar" : "Gravar";
  $("#time").textContent = clock(r.active ? r.seconds : 0);
  document.body.dataset.job = j.status === "running" ? "running" : "";
  $("#status").textContent = r.error ? "Gravação interrompida" : paused ? "Captura pausada" : r.active ? "Gravando" : j.status === "running" ? (j.kind === "analyze" ? "Analisando sua nota" : j.kind === "download" ? "Baixando"
    : ["prepare", "transcribe", "screen"].includes(j.stage) ? "Preparando a aula" : "Salvando o material") : j.review ? "Escreva sua compreensão" : "Pronto para gravar";
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
async function poll() {
  try {
    const d = await api("/api/widget");
    if (!pending && Date.now() >= errorUntil) render(d);
    renderSettingsJob(d.job);
  }
  catch { document.body.dataset.state = "error"; $("#status").textContent = "Sem conexão com o Lumen."; }
  setTimeout(poll, state?.recording.active ? 250 : 1000);
}
async function toggleRecording() {
  if (pending || !state) return;
  showPreferences(false);
  pending = true;
  errorUntil = 0;
  $("#action").disabled = true;
  try {
    const r = (await api("/api/widget")).recording;
    if (r.active) {
      const file = await api("/api/record/stop", {});
      host?.postMessage("record:ready:" + JSON.stringify({ file, seconds: r.seconds }));
    } else {
      await api("/api/record/start", {});
      host?.postMessage("record:started");
    }
    render(await api("/api/widget"));
  } catch (e) {
    $("#status").textContent = "Não foi possível gravar.";
    $("#detail").textContent = e.message;
    document.body.dataset.state = "error";
    errorUntil = Date.now() + 8000;
    pending = false;
    $("#action").disabled = false;
    return;
  }
  pending = false;
  $("#action").disabled = false;
}
$("#action").addEventListener("click", toggleRecording);
// Pausar captura: a mesma gravação continua depois; o vídeo e os outros programas não são tocados.
async function togglePause() {
  if (pending || !state?.recording.active) return;
  pending = true;
  errorUntil = 0;
  $("#pause").disabled = true;
  try {
    await api(state.recording.paused ? "/api/record/resume" : "/api/record/pause", {});
    render(await api("/api/widget"));
  } catch (e) {
    $("#status").textContent = "Não foi possível pausar.";
    $("#detail").textContent = e.message;
    errorUntil = Date.now() + 6000;
  } finally {
    pending = false;
    $("#pause").disabled = false;
  }
}
$("#pause").addEventListener("click", togglePause);
document.addEventListener("keydown", (e) => { if (Shortcuts.capture.test(e)) { e.preventDefault(); togglePause(); } });
Pomodoro.mount($("#pomo-main"));
Pomodoro.mount($("#pomo-note"));
$("#open").addEventListener("click", () => host?.postMessage("window:open"));
function showPreferences(open) {
  if (open && noteOpen) showNote(false);
  $("#preferences").hidden = !open;
  $("#recording-panel").hidden = open || noteOpen;
  $("#settings").setAttribute("aria-expanded", String(open));
  if (!open) $("#prefs-token").value = "";
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
  document.querySelectorAll("#prefs-content button, #prefs-content input, #prefs-content select").forEach((b) => b.disabled = settingsBusy || !preferences);
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
  document.querySelectorAll("[data-page]").forEach((p) => p.hidden = p.dataset.page !== page);
  $("#prefs-title").textContent = ({menu:"Ajustes",desktop:"Barra flutuante",notion:"Notion",transcription:"Transcrição",ai:"IA local",covers:"Capas com IA",privacy:"Privacidade",confirm:"Confirmar"})[page];
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
const writing = () => noteOpen && document.hasFocus() && document.activeElement === $("#note-text");
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
  noteOpen = open;
  if (open) { $("#preferences").hidden = true; $("#settings").setAttribute("aria-expanded", "false"); }
  $("#note-panel").hidden = !open;
  $("#recording-panel").hidden = open || !$("#preferences").hidden;
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
$("#note-btn").addEventListener("click", () => showNote(!noteOpen));
$("#note-back").addEventListener("click", () => { showNote(false); $("#note-btn").focus(); });
$("#note-detach").addEventListener("click", detachNote);
$("#note-detach").dataset.kbd = Notes.shortcutLabel;
document.addEventListener("keydown", (e) => { if (noteOpen && Notes.isShortcut(e)) { e.preventDefault(); detachNote(); } });
function syncPresentation() {
  if (!host) return;
  document.body.dataset.expanded = String(innerWidth > 100 || innerHeight > 100);
  if (document.body.dataset.expanded === "false" && !writing()) { document.activeElement?.blur(); showPreferences(false); }
}
function expand() { clearTimeout(collapse); if (!host) document.body.dataset.expanded = "true"; host?.postMessage("widget:expand"); }
function conceal() { clearTimeout(collapse); if (!host) document.body.dataset.expanded = "false"; document.activeElement?.blur(); showPreferences(false); if (noteOpen) showNote(false); }
function retract() {
  clearTimeout(collapse);
  if (writing()) return;  // escrevendo a nota: a barra não se recolhe embaixo do cursor
  collapse = setTimeout(() => { conceal(); host?.postMessage("widget:collapse"); }, 450);
}
window.addEventListener("blur", () => { if (noteOpen && !document.documentElement.matches(":hover")) retract(); });
$("#peek").addEventListener("click", expand);
document.documentElement.addEventListener("pointerenter", expand);
document.documentElement.addEventListener("pointerleave", retract);
document.addEventListener("focusin", expand);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (!$("#preferences").hidden) backPreferences(); else { conceal(); host?.postMessage("widget:collapse"); } } });
host?.addEventListener("message", (e) => {
  if (e.data === "side:left" || e.data === "side:right") document.body.dataset.side = e.data.slice(5);
  else if (["edge:left", "edge:right", "edge:top", "edge:bottom", "edge:free"].includes(e.data)) {
    document.body.dataset.edge=e.data.slice(5);
    if (preferences && !settingsBusy) { preferences.widget = document.body.dataset.edge; renderPreferences(); }
  }
});
window.addEventListener("resize", syncPresentation);
syncPresentation();
poll();
