"use strict";
// Janela flutuante: no Lumen.exe, uma janela nativa sempre por cima (launcher/NoteForm.cs); no navegador comum, um popup.
// Só a nota do estudante: nenhuma análise, sugestão ou texto de IA aparece aqui.
const host = window.chrome?.webview;
const $ = (s) => document.querySelector(s);
let key = new URLSearchParams(location.search).get("key");
const HINTS = {
  completed: "Você está editando a versão atual. A compreensão original continua guardada.",
  synced_to_notion: "Esta nota já foi salva no Notion.",
};
const editor = new UnderstandingEditor({ text: $("#nw-text"), save: $("#nw-save"), count: $("#nw-count"), mode: "floating",
  onChange: (d) => {
    const v = d.view || {};
    $("#nw-lesson").textContent = v.title || "";
    document.title = "Minha compreensão" + (v.title ? " · " + v.title : "");
    $("#nw-hint").textContent = HINTS[v.state] || "";
  } });
let unbindStatus = null;
function bindStatus() {
  unbindStatus?.();
  unbindStatus = Notes.bindStatus(key, { box: $("#nw-status"), text: $("#nw-ready"), detail: $("#nw-hint"), go: $("#nw-go"), compact: false });
}
$("#nw-go").addEventListener("click", async () => {
  try { await Notes.process(key); } catch (e) { $("#nw-hint").textContent = [e.message, e.action].filter(Boolean).join(" "); }
});

// Esta janela mostra a aula em foco no Lumen: se a janela principal (ou a barra) abrir outra, ela acompanha, com o
// texto da outra aula e sem misturar as duas.
async function follow(next) {
  if (!next || next === key || leaving) return;
  await Notes.flush(key);
  editor.unbind();
  Notes.announce(key, false);
  key = next;
  history.replaceState(null, "", "/note?key=" + encodeURIComponent(key));
  host?.postMessage("note:key:" + key);
  Notes.setPref("Key", key);
  try { await Notes.load(key); editor.bind(key); Notes.announce(key, true); bindStatus(); }
  catch (e) { $("#nw-hint").textContent = e.message + (e.action ? " " + e.action : ""); }
}
Notes.on("active", follow);
window.addEventListener("storage", (e) => { if (e.key === "understandingActiveKey" && e.newValue) follow(JSON.parse(e.newValue)); });

let leaving = false;
async function leave(dock) {  // fechar ou voltar nunca descarta nada: o texto já está no documento e é salvo antes
  if (leaving) return;
  leaving = true;
  await Notes.flush(key);
  Notes.announce(key, false);
  if (dock) Notes.dock(key);
  if (host) host.postMessage(dock ? "note:dock" : "note:close");
  else window.close();
}
function compact(on) {  // “minimizar”: fica só a barra, por cima do vídeo, sem esconder a nota de vez
  document.body.classList.toggle("compact", on);
  $("#nw-min").setAttribute("aria-label", on ? "Mostrar a nota" : "Minimizar");
  $("#nw-min").title = on ? "Mostrar a nota" : "Minimizar";
  host?.postMessage(on ? "note:minimize" : "note:restore");
  if (!on) $("#nw-text").focus();
}
$("#nw-min").addEventListener("click", () => compact(!document.body.classList.contains("compact")));
$("#nw-dock").addEventListener("click", () => leave(true));
$("#nw-close").addEventListener("click", () => leave(false));
$("#nw-dock").title += ` (${Notes.shortcutLabel})`;
const tools = "button, input, .pomo-sheet";  // clicar neles não arrasta nem minimiza a janela
$("#nw-bar").addEventListener("pointerdown", (e) => {  // arrastar pela barra (o Windows move a janela)
  if (e.button === 0 && !e.target.closest(tools)) host?.postMessage("note:drag");
});
$("#nw-bar").addEventListener("dblclick", (e) => { if (!e.target.closest(tools)) compact(!document.body.classList.contains("compact")); });

// Pomodoro: o mesmo da barra e da janela principal. Minimizada, a janela mostra só o tempo; os controles abrem a nota.
Pomodoro.mount($("#nw-pomo"), { sheet: true, beforeOpen: () => { if (document.body.classList.contains("compact")) compact(false); } });
Pomodoro.watch();

// Captura: sempre à vista enquanto se escreve (gravando em vermelho, pausada em âmbar). Pausar não mexe no vídeo.
let rec = null, recBusy = false;
const mmss = (s) => { s = Math.floor(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : String(m).padStart(2, "0")) + ":" + String(s % 60).padStart(2, "0"); };
function renderRec(r) {
  rec = r;
  const b = $("#nw-rec"), paused = !!r.paused;
  b.hidden = !r.active;
  if (!r.active) return;
  b.dataset.paused = String(paused);
  $("#nw-rec-text").textContent = paused ? "Pausada" : mmss(r.seconds);
  b.setAttribute("aria-label", paused ? `Captura pausada há ${mmss(r.paused_for)}. Retomar captura` : `Gravando, ${mmss(r.seconds)}. Pausar captura`);
  b.title = (paused ? "Captura pausada: nada é gravado. Clique para retomar" : "Gravando. Clique para pausar a captura (o vídeo continua)") + ` (${Shortcuts.capture.label})`;
}
async function pollRec() {
  if (document.hidden || recBusy) return;
  try {
    const d = await Notes.call("/api/widget");
    renderRec(d.recording);
    (d.notes || []).forEach((n) => Notes.merge(n.key, n));  // preparação pronta, gravação, outra tarefa, análise
  } catch {}
}
async function togglePause() {
  if (recBusy || !rec?.active) return;
  recBusy = true;
  try { renderRec(await Notes.call(rec.paused ? "/api/record/resume" : "/api/record/pause", {})); }
  catch (e) { $("#nw-hint").textContent = e.message; }
  finally { recBusy = false; }
}
$("#nw-rec").addEventListener("click", togglePause);
document.addEventListener("keydown", (e) => { if (Shortcuts.capture.test(e)) { e.preventDefault(); togglePause(); } });
setInterval(pollRec, 1000);
document.addEventListener("visibilitychange", pollRec);
pollRec();
document.addEventListener("keydown", (e) => { if (Notes.isShortcut(e)) { e.preventDefault(); leave(true); } });
Notes.on("close", (k) => { if (k === key) leave(false); });  // “Trazer de volta” na janela principal
window.addEventListener("pagehide", () => { if (!leaving) Notes.announce(key, false); });
if (!host) {  // popup do navegador: lembra posição e tamanho (no Lumen.exe, quem lembra é a janela nativa)
  $("#nw-min").hidden = true;
  const remember = () => { Notes.setPref("Size", { w: outerWidth, h: outerHeight }); Notes.setPref("Position", { x: screenX, y: screenY }); };
  window.addEventListener("resize", remember);
  window.addEventListener("pagehide", remember);
}

(async () => {
  if (!key) { $("#nw-hint").textContent = "Abra uma aula no Lumen e use “Destacar” no editor."; return; }
  try {
    const { recovered } = await Notes.load(key);
    editor.bind(key);
    bindStatus();
    Notes.announce(key, true);
    if (recovered) $("#nw-save").textContent = "Texto recuperado deste PC";
    const t = $("#nw-text");
    t.focus(); t.setSelectionRange(t.value.length, t.value.length);
  } catch (e) { $("#nw-hint").textContent = e.message + (e.action ? " " + e.action : ""); }
})();
