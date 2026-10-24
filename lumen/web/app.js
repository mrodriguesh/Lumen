"use strict";
const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

let S = null;            // estado do servidor
let view = "home";       // área aberta (showView)
let kind = "recording";  // aba ativa
const picked = { recording: null, file: null, telegram: null, ytcopy: null, captures: [] };
let found = null;        // resultado de /api/inspect
let lastSpec = null;
let polling = false;

async function api(path, body) {
  const opt = { headers: { "X-Lumen-Token": TOKEN } };
  if (body !== undefined) {
    opt.method = "POST";
    if (body instanceof Blob) opt.body = body;
    else { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  }
  let r;
  try { r = await fetch(path, opt); } catch {
    throw Object.assign(new Error("O Lumen parou de responder."), { action: "Abra o aplicativo de novo.", offline: true });
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error?.message || "Erro"), { action: d.error?.action || "" });
  return d;
}

// tone: true = erro (como antes), ou "success" | "info" | "warning" | "error" (ui.js)
function toast(msg, tone = "success") { ui.toast(msg, tone === true ? "error" : tone || "success"); }
const fail = (e) => toast(e.message + (e.action ? " " + e.action : ""), true);
const icon = (name, cls) => ui.icon(name, cls);
// Troca o conteúdo só se ele mudou: quem está com o foco ou o mouse numa linha não a perde a cada atualização
const sigs = new WeakMap();
function swap(box, nodes) {
  const sig = nodes.map((n) => n.outerHTML ?? n.textContent).join("");
  if (sigs.get(box) === sig) return;
  sigs.set(box, sig);
  box.replaceChildren(...nodes);
}
const setLabel = (btn, text, ic) => btn.replaceChildren(...(ic ? [icon(ic)] : []), text);  // botão com ícone

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  n.append(...kids.filter((k) => k !== null && k !== undefined && k !== false));
  return n;
}
const fmtDur = (s) => {
  if (!s) return "";
  const m = Math.round(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : `${Math.max(m, 1)} min`;
};

// Tempo que falta para a tarefa toda (medido neste PC; ver lumen/eta.py): segundos quando é pouco, e o horário.
function etaText(s, what) {
  s = Math.max(1, Math.round(s));
  let left;
  if (s < 90) left = `${Math.max(5, Math.round(s / 5) * 5)} s`;
  else if (s < 3600) {
    const q = Math.round(s / 15) * 15, m = Math.floor(q / 60), r = q % 60;  // de 15 em 15 s
    left = `${m} min${r ? ` ${r} s` : ""}`;
  } else left = fmtDur(s);
  const at = new Date(Date.now() + s * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return `Faltam cerca de ${left} · ${what} por volta de ${at}`;
}

// ---------- estado geral ----------
async function refresh() {
  S = await api("/api/state");
  $("#formats").textContent = "Formatos testados: " + Object.values(S.formats).join(", ");
  renderChecks();
  renderSettings();
  renderPending();
  renderHome();
  renderStatus();
  return S;
}

let checkTimer = null;
const DESTS = { notion: ["notion"], obsidian: ["obsidian"], both: ["obsidian", "notion"] };
const dests = () => DESTS[S?.config.destinations] || ["notion"];
const usesNotion = () => dests().includes("notion"), usesObsidian = () => dests().includes("obsidian");
const vaultReady = () => !!(S?.config.obsidian_vault && !S.obsidian?.error);
const destName = () => usesNotion() && usesObsidian() ? "no Notion e no Obsidian" : usesObsidian() ? "no Obsidian" : "no Notion";
function renderChecks() {
  const w = S.whisper.models[S.whisper.active];
  // Sistema (Início): ícone, o que é, o estado em palavras e um selo; nunca só a cor
  const stat = (ic, name, ok, on, off, go) => el("div", { class: "sys" }, icon(ic),
    el("span", {}, name, el("small", {}, ok ? on : off)),
    el("span", { class: "badge", "data-tone": ok ? "ok" : "warn" }, icon(ok ? "check" : "alert"), ok ? "Pronto" : "Pendente"),
    ok ? null : el("button", { class: "icon-btn sm", type: "button", "aria-label": `Resolver: ${name}`, "data-tip": "", onclick: go }, icon("chevron-right")));
  swap($("#side-status"), [
    ...[usesNotion() && stat("page", "Notion", rootReady(), `Salvando em “${S.config.root_page_title || "página raiz"}”`,
      !S.has_token ? "Não conectado" : rootOk === false ? "A página raiz não está mais acessível" : "Escolha a página raiz", goIntegrations),
      usesObsidian() && stat("notebook", "Obsidian", vaultReady(), S.obsidian?.vaults.find((v) => v.path === S.config.obsidian_vault)?.name || "Cofre escolhido",
        S.obsidian?.error ? "Cofre indisponível" : "Escolha o cofre", goIntegrations)].filter(Boolean),
    stat("cpu", "IA local", S.ollama.running && S.ollama.installed, S.config.ollama_model,
      !S.ollama.running ? "Ollama fechado" : `Falta o modelo ${S.config.ollama_model}`, () => goSettings("ai")),
    stat("wave", "Transcrição", w.downloaded, `${w.label} · ${S.gpu ? "GPU" : "processador"}`, `Falta baixar o modelo ${w.label}`, () => goSettings("transcription"))]);
  const items = [
    ...(usesNotion() ? [["Notion conectado", S.has_token, "Conectar", goIntegrations],
      [rootOk === false ? "Página raiz dos cursos (a salva não está mais acessível)" : "Página raiz dos cursos", rootReady(), "Escolher", goIntegrations]] : []),
    ...(usesObsidian() ? [["Cofre do Obsidian", vaultReady(), "Escolher", goIntegrations]] : []),
    ["Ollama em execução", S.ollama.running, "Como instalar", () => window.open("https://ollama.com/download", "_blank")],
    [`Modelo de IA (${S.config.ollama_model})`, S.ollama.installed, "Baixar", () => goSettings("ai")],
    [`Modelo de transcrição (${w.label}, ${w.size})`, w.downloaded, "Baixar", () => goSettings("transcription")],
  ];
  swap($("#checks"), items.map(([label, ok, act, fn]) =>
    el("li", {}, el("span", { class: "check-label" }, el("span", { class: ok ? "ok" : "no", role: "img", "aria-label": ok ? "Pronto:" : "Pendente:" }, icon(ok ? "check-circle" : "alert")), label),
      ok ? null : el("button", { class: "btn sm", type: "button", onclick: fn }, act))));
  // O modelo de transcrição só é exigido quando a fonte precisa ser transcrita (avisado na fonte).
  $("#setup").hidden = items.slice(0, -1).every(([, ok]) => ok);
  updateGo();
  // O Lumen abre com o Windows, às vezes antes do Ollama: enquanto a IA não estiver pronta, pergunta de novo
  // a cada 5 s (com os Ajustes ou as Integrações abertos, espera sair para não mexer no que está sendo editado).
  clearTimeout(checkTimer);
  if (!(S.ollama.running && S.ollama.installed))
    checkTimer = setTimeout(() => editingSettings() ? renderChecks() : refresh().catch(() => renderChecks()), 5000);
}

// ---------- abas ----------
function selectTab(btn) {
  for (const t of $$("[role=tab]")) {
    const on = t === btn;
    t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1;
    $("#" + t.getAttribute("aria-controls")).hidden = !on;
  }
  kind = btn.dataset.kind;
  $("#lesson-reference").hidden = kind === "youtube";
  $("#speed-setting").hidden = kind === "captures";  // capturas não têm fala
  const hint = $("#lesson-link-hint");
  hint.dataset.v ??= hint.textContent; $("#lesson-link-h").dataset.v ??= $("#lesson-link-h").textContent;
  $("#lesson-link-h").textContent = kind === "captures" ? "Link de origem" : $("#lesson-link-h").dataset.v;
  hint.textContent = kind === "captures" ? "Opcional: o site ou a página de onde vieram as capturas; fica como referência na página." : hint.dataset.v;
  $("#speed-hint").textContent = kind === "recording"
    ? "A gravação sai na velocidade em que a aula tocou: se o player estava em 2× ou 4×, escolha essa velocidade."
    : "Vale a velocidade real do arquivo. Assistir em 2× ou 4× no player não acelera o arquivo: use Normal.";
  renderWatch();
  $("#hero-title").textContent = btn.querySelector(".tab-label").textContent;
  $("#hero-sub").textContent = btn.dataset.sub;
  found = null; renderSource();
  if (currentSpec()) inspect();
}
for (const t of $$("[role=tab]")) {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", (e) => {
    const tabs = $$("[role=tab]"), i = tabs.indexOf(t);
    const next = e.key === "ArrowDown" || e.key === "ArrowRight", prev = e.key === "ArrowUp" || e.key === "ArrowLeft";
    const j = next ? (i + 1) % tabs.length : prev ? (i + tabs.length - 1) % tabs.length : -1;
    if (j >= 0) e.preventDefault();
    if (j >= 0) { tabs[j].focus(); selectTab(tabs[j]); }
  });
}

// ---------- escolha de fonte ----------
for (const b of $$("[data-pick]")) {
  b.addEventListener("click", async () => {
    const what = b.dataset.pick;
    b.disabled = true;
    try {
      const r = await api("/api/pick", { kind: ["captions", "telegram", "images"].includes(what) ? what : "media" });
      if (what === "images") return addCaps((r.paths || []).map((p, i) => ({ path: p, name: r.names[i] })));
      if (!r.path && !r.text) return;
      if (what === "captions") { $("#yt-text").value = r.text; toast(`“${r.name}” importado.`); }
      else picked[what === "media" ? "file" : what] = r;
      await inspect();
    } catch (e) { fail(e); } finally { b.disabled = false; }
  });
}

const drop = $("#drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", async (e) => {
  e.preventDefault(); drop.classList.remove("over");
  const f = e.dataTransfer.files[0];
  if (!f) return;
  const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
  if (!S.formats[ext]) return toast(`O formato “${ext}” não é suportado. Use: ${Object.keys(S.formats).join(", ")}.`, true);
  $("#source").hidden = false;
  $("#source").textContent = `Copiando “${f.name}” para o Lumen… (o arquivo não sai do seu PC)`;
  try {
    picked.file = await api("/api/upload?name=" + encodeURIComponent(f.name), f);
    await inspect();
  } catch (err) { fail(err); renderSource(); }
});
// ---------- capturas de tela (aba “Capturas de tela” e “Adicionar capturas” na revisão) ----------
const isImage = (f) => /\.(png|jpe?g|webp|bmp)$/i.test(f.name || "") || /^image\//.test(f.type || "");
async function uploadImages(files) {
  const out = [];
  for (const f of files) {  // uma imagem colada não tem nome: vira “captura.png”
    const name = /\.[a-z]+$/i.test(f.name || "") ? f.name : `captura.${(f.type.split("/")[1] || "png").replace("jpeg", "jpg")}`;
    out.push(await api("/api/upload?name=" + encodeURIComponent(name), f));
  }
  return out;
}
function renderCaps() {
  $("#caps-grid").replaceChildren(...picked.captures.map((c, i) => el("figure", { class: "cap", role: "listitem" },
    el("img", { src: `/api/capture?path=${encodeURIComponent(c.path)}&t=${encodeURIComponent(TOKEN)}`, alt: c.name, loading: "lazy" }),
    el("button", { class: "cap-x", type: "button", "aria-label": `Remover ${c.name}`, "data-tip": "", onclick: () => {
      picked.captures.splice(i, 1); renderCaps(); capsChanged();
    } }, icon("x")),
    el("figcaption", {}, `${i + 1} · ${c.name}`))));
}
async function capsChanged() { found = null; renderSource(); if (currentSpec()) await inspect(); else updateGo(); }
async function addCaps(items) {
  if (!items.length) return;
  const room = 30 - picked.captures.length;
  if (items.length > room) toast(`O limite é de 30 capturas por aula; ${room > 0 ? `só as ${room} primeiras entraram` : "nenhuma entrou"}.`, true);
  picked.captures.push(...items.slice(0, Math.max(room, 0)));
  renderCaps();
  await capsChanged();
}
async function addToReview(items) {  // junta capturas à aula que está na revisão
  if (!review || !items.length) return;
  const btn = $("#shots-add"), n = items.length;
  btn.disabled = true;
  $("#shots-info").textContent = `Lendo ${n} captura${n === 1 ? "" : "s"} com a IA de visão no seu PC… (≈ ${Math.max(5, n * 4)} s)`;
  try {
    review.screens = await api("/api/captures/add", { key: review.key, paths: items.map((p) => p.path) });
    renderShots(review, true);
    toast(`${n} captura${n === 1 ? " adicionada" : "s adicionadas"} à aula.`);
  } catch (e) { fail(e); renderShots(review, true); }
  finally { btn.disabled = false; }
}
$("#shots-add").addEventListener("click", async () => {
  $("#shots-add").disabled = true;
  try {
    const r = await api("/api/pick", { kind: "images" });
    $("#shots-add").disabled = false;
    await addToReview((r.paths || []).map((p, i) => ({ path: p, name: r.names[i] })));
  } catch (e) { fail(e); } finally { $("#shots-add").disabled = false; }
});
for (const [zone, add] of [[$("#drop-caps"), addCaps], [$("#shots"), addToReview]]) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", async (e) => {
    e.preventDefault(); zone.classList.remove("over");
    const files = [...e.dataTransfer.files].filter(isImage);
    if (!files.length) return toast("Solte imagens de tela (png, jpg, webp ou bmp).", true);
    try { await add(await uploadImages(files)); } catch (err) { fail(err); }
  });
}
document.addEventListener("paste", async (e) => {  // Ctrl+V de uma captura (Win+Shift+S) na aba Capturas ou na revisão
  const files = [...(e.clipboardData?.files || [])].filter(isImage);
  const reviewing = !$("#review").hidden, composing = !$("#compose").hidden && kind === "captures" && !$("#view-new").hidden;
  if (!files.length || !(reviewing || composing)) return;
  e.preventDefault();
  try { const ups = await uploadImages(files); await (reviewing ? addToReview(ups) : addCaps(ups)); } catch (err) { fail(err); }
});

// Evita que soltar um arquivo fora da área abra o vídeo na janela.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

$("#yt-check").addEventListener("click", () => inspect());
$("#yt-url").addEventListener("keydown", (e) => { if (e.key === "Enter") inspect(); });
$("#yt-text").addEventListener("change", () => $("#yt-url").value.trim() && inspect());

function currentSpec() {
  if (kind === "captures")
    return picked.captures.length ? { kind, paths: picked.captures.map((c) => c.path), title: $("#caps-title").value.trim(),
                                      link: $("#lesson-link").value.trim() } : null;
  if (kind === "youtube") {
    const url = $("#yt-url").value.trim();
    if (!url) return null;
    return { kind, url, captions: $("#yt-text").value, path: picked.ytcopy?.path || "" };
  }
  const p = picked[kind];
  return p ? { kind, path: p.path, link: $("#lesson-link").value.trim() } : null;
}

async function inspect() {
  const spec = currentSpec();
  if (!spec) return;
  const box = $("#source");
  box.hidden = false; box.textContent = "Verificando…";
  try { found = await api("/api/inspect", spec); } catch (e) { found = null; box.textContent = ""; box.hidden = true; return fail(e); }
  renderSource();
}

function renderSource() {
  const box = $("#source");
  if (!found) { box.hidden = true; box.replaceChildren(); updateGo(); return; }
  const f = found, tags = [];
  if (f.info) tags.push([f.info.format, ""]);
  if (f.duration) tags.push([fmtDur(f.duration), ""]);
  if (f.captures) tags.push([`${f.captures} captura${f.captures === 1 ? "" : "s"} · lida${f.captures === 1 ? "" : "s"} no seu PC pela IA de visão`, "ok"]);
  if (f.has_captions) tags.push([`Transcrição pronta (${f.segments} trechos)`, "ok"]);
  else if (f.resumable) tags.push(["Transcrição já feita — será reaproveitada", "ok"]);
  else if (f.needs_transcription) tags.push([`Será transcrito no seu PC${f.estimate ? ` · cerca de ${fmtDur(f.estimate)} (estimativa)` : ""}`, ""]);
  if (f.needs_transcription && !f.whisper_ready) tags.push([`Baixe o modelo de transcrição “${f.whisper_model}” em Ajustes`, "warn"]);
  if (f.needs_transcript) tags.push(["Falta a transcrição: cole o texto, importe uma legenda ou escolha uma cópia local", "warn"]);
  box.replaceChildren(
    el("span", { class: "eyebrow" }, f.label + (f.author ? " · " + f.author : "")),
    el("strong", {}, f.title),
    el("div", { class: "tags" }, ...tags.map(([t, c]) => el("span", { class: "badge", "data-tone": c === "ok" ? "ok" : c || "" },
      c ? icon(c === "ok" ? "check" : "alert") : null, t))));
  box.hidden = false;
  $("#dup").hidden = !f.duplicate;
  if (f.duplicate) {
    const d = f.duplicate, when = d.created || d.obsidian?.at || "";
    $("#dup-legend").textContent = d.url ? "Esta aula parece já existir no Notion" : "Esta aula já está no Obsidian";
    $("#dup-info").textContent = `“${d.title}”` + (d.url ? ` em ${d.course}` : "") + (when ? `, criada em ${when.slice(0, 16).replace("T", " às ")}` : "")
      + (d.obsidian?.status === "ok" ? ". No Obsidian, a mesma nota é sempre atualizada (suas anotações ficam)." : ".");
  }
  updateGo();
}

// ---------- gravação do áudio do PC ----------
const mmss = (s) => { s = Math.floor(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60);
  return (h ? h + ":" + String(m).padStart(2, "0") : String(m).padStart(2, "0")) + ":" + String(s % 60).padStart(2, "0"); };
let recTimer = null;
const BARS = 56;
const wave = $("#rec-wave"), recorder = $("#recorder");
wave.replaceChildren(...Array.from({ length: BARS }, (_, i) => { const b = document.createElement("i"); b.style.setProperty("--i", i); return b; }));
let levels = new Array(BARS).fill(0);
const barHeight = (l) => Math.max(.06, Math.min(1, Math.sqrt(l) * 1.7));  // fala fica entre 30% e 90%
function drawWave() { wave.childNodes.forEach((b, i) => { b.style.transform = `scaleY(${barHeight(levels[i])})`; }); }
function setRecState(state, label) {
  recorder.dataset.state = state;
  if (state === "idle") wave.childNodes.forEach((b) => { b.style.transform = ""; });
  $("#rec-start-label").textContent = label;
  $("#rec-start").setAttribute("aria-label", label);
}
function renderRec(r) {
  S.recording = r;
  if (r.active) {
    if (recorder.dataset.state !== "live") { levels.fill(0); setRecState("live", "Parar e usar"); }
    levels.push(r.level || 0); levels.shift();  // a onda corre da direita para a esquerda
    drawWave();
    recorder.style.setProperty("--lvl", Math.min(1, Math.sqrt(r.level || 0) * 1.4).toFixed(2));
    $("#rec-time").textContent = mmss(r.seconds);
    const sc = r.screens;
    const eye = !sc ? "" : !sc.seen ? (sc.refused ? ` · Sem capturas ainda: ${sc.why}.` : " · Assistindo a tela junto.")
      : ` · ${sc.seen} tela${sc.seen === 1 ? " nova" : "s novas"}`
      + (sc.read ? `, ${sc.kept} com conteúdo da aula.` : " (lidas ao processar).");
    const mus = !r.music_filter ? "" : r.isolated ? ` · Filtro de música ativo: o som do ${r.isolated} fica fora da gravação.` : " · Filtro de música ativo.";
    $("#rec-hint").textContent = (r.level > 0.005 ? "Gravando o som da aula…"
      : r.heard ? "Silêncio no momento." : "Nenhum som ainda: dê play na aula (volume ligado).") + eye + mus;
    const paused = !!r.paused, label = paused ? "Retomar captura" : "Pausar captura";
    recorder.dataset.paused = String(paused);
    $("#rec-pause use").setAttribute("href", "/icons.svg#" + (paused ? "play" : "pause"));
    $("#rec-pause-label").textContent = paused ? "Retomar" : "Pausar";
    $("#rec-pause").setAttribute("aria-label", label);
    $("#rec-pause").dataset.tip = label;
    $("#rec-pause").dataset.kbd = Shortcuts.capture.label;
    if (paused) $("#rec-hint").textContent = `Captura pausada há ${mmss(r.paused_for)}: nada do som nem da tela é gravado. O vídeo continua; retome quando quiser.`;
    $("#watch").disabled = true;
  } else if (recorder.dataset.state === "live") {
    setRecState("idle", "Iniciar gravação");
    $("#rec-time").textContent = "00:00";
  }
  if (!r.active) recorder.dataset.paused = "false";
  // O app fechou no meio de uma gravação (ou saiu guardando): ela é oferecida, nunca usada nem apagada sozinha.
  const lost = !r.active && r.recovered && recorder.dataset.state === "idle" ? r.recovered : null;
  $("#rec-recover").hidden = !lost;
  if (lost) $("#rec-recover-text").textContent = `Encontrei uma gravação que não terminou (${mmss(lost.seconds)}).`;
  if (!r.active) $("#watch").disabled = false;
  if (r.error) $("#rec-hint").textContent = r.error;
  updateGo();
  renderUCap(); renderStatus(); renderHero();
}
function watchRec() {
  clearInterval(recTimer);
  recTimer = setInterval(async () => {
    try { const r = await api("/api/record"); renderRec(r); if (!r.active) clearInterval(recTimer); }
    catch (e) { clearInterval(recTimer); fail(e); }
  }, 220);
}
async function startRec() {
  try {
    $("#rec-hint").textContent = "";
    renderRec(await api("/api/record/start", {}));
    picked.recording = null; found = null; renderSource();
    watchRec();
  } catch (e) { fail(e); }
}
async function stopRec() {
  clearInterval(recTimer);
  const secs = S.recording?.seconds || 0;
  try {
    const r = await api("/api/record/stop", {});
    await useRecording(r, secs);
  } catch (e) { renderRec(await api("/api/record")); setRecState("idle", "Iniciar gravação"); fail(e); }
}
async function useRecording(r, secs) {
  showView("new");
  if (step === "understand" || step === "analysis") { if (U) await Notes.flush(U.key); backToCompose(); }  // nova gravação parada na barra
  picked.recording = null; found = null;
  $("#tab-recording").click();
  picked.recording = r;
  S.recording = { active: false };
  setRecState("done", "Gravar de novo");
  drawWave();
  $("#rec-time").textContent = mmss(secs);
  $("#rec-hint").textContent = `Gravação pronta: “${r.name.replace(/\.wav$/, "")}”` + (r.warning ? ". " + r.warning : "");
  updateGo();
  await inspect();
}
$("#rec-start").addEventListener("click", () => (recorder.dataset.state === "live" ? stopRec() : startRec()));
$("#rec-discard").addEventListener("click", async () => {
  if (!await ui.confirm("O áudio e as telas desta gravação serão apagados. Não dá para desfazer.",
    { title: "Descartar esta gravação?", ok: "Descartar", danger: true })) return;
  clearInterval(recTimer);
  try {
    renderRec(await api("/api/record/discard", {}));
    setRecState("idle", "Iniciar gravação"); $("#rec-time").textContent = "00:00";
    $("#rec-hint").textContent = "Gravação descartada.";
  } catch (e) { fail(e); }
});
// Pausar captura: a mesma gravação continua depois; nada do intervalo entra na aula (nem como silêncio).
async function toggleRecPause() {
  if (!S.recording?.active || toggleRecPause.busy) return;
  toggleRecPause.busy = true;
  try { renderRec(await api(S.recording.paused ? "/api/record/resume" : "/api/record/pause", {})); }
  catch (e) { fail(e); }
  finally { toggleRecPause.busy = false; }
}
$("#rec-pause").addEventListener("click", toggleRecPause);
document.addEventListener("keydown", (e) => { if (Shortcuts.capture.test(e) && S.recording?.active) { e.preventDefault(); toggleRecPause(); } });
$("#rec-recover-use").addEventListener("click", async () => {
  const secs = S.recording?.recovered?.seconds || 0;
  try { const r = await api("/api/record/recover", { use: true }); $("#rec-recover").hidden = true; await useRecording(r, secs); }
  catch (e) { fail(e); renderRec(await api("/api/record")); }
});
$("#rec-recover-drop").addEventListener("click", async () => {
  if (!await ui.confirm("A gravação que ficou pela metade será apagada deste PC.",
    { title: "Descartar a gravação?", ok: "Descartar", danger: true })) return;
  try { renderRec(await api("/api/record/recover", { use: false })); toast("Gravação descartada."); } catch (e) { fail(e); }
});
Pomodoro.mount($("#u-pomo"), { sheet: true });
Pomodoro.watch();
$("#lesson-link").addEventListener("change", () => currentSpec() && inspect());
$("#course-text").addEventListener("input", () => updateGo());

// ---------- cursos ----------
let pages = [], pagesState = "idle", rootOk = null;  // idle | loading | ok | error
const rootReady = () => !!(S?.has_token && S.config.root_page_id && rootOk !== false);
function gotPages(r) {
  pages = r.courses; pagesState = "ok"; pagesAt = Date.now();
  if (rootOk !== r.root_ok && S) { rootOk = r.root_ok; renderChecks(); }
  try { localStorage.setItem("lumen.pages", JSON.stringify({ courses: r.courses, root_ok: r.root_ok, root: r.root })); } catch {}
}
async function loadCourses() {
  pages = [];
  if (S?.has_token) {
    // o Notion leva alguns segundos para listar tudo: mostra já a última lista e troca quando a nova chegar
    let cached = null;
    try { cached = JSON.parse(localStorage.getItem("lumen.pages")); } catch {}
    if (cached?.root === S.config.root_page_id && Array.isArray(cached.courses)) {
      pages = cached.courses; pagesState = "ok"; rootOk = cached.root_ok; renderChecks(); renderCourses();
    } else { pagesState = "loading"; renderResults(); }
    try { gotPages(await api("/api/courses")); }
    catch (e) { if (pagesState !== "ok") pagesState = "error"; fail(e); }  // com a lista guardada, segue usando ela
  } else pagesState = "idle";
  renderCourses();
  renderResults();
}
// Notion só mostra à integração as páginas liberadas: o botão abre a tela oficial de acesso
const GRANT_URL = "https://www.notion.so/profile/integrations";
for (const b of document.querySelectorAll("[data-grant]")) b.addEventListener("click", () => window.open(GRANT_URL, "_blank"));
function renderCourses(want) {  // seletor escondido = destino escolhido; a tela usa o cartão e o navegador
  const sel = $("#course"), prev = want || sel.value;
  const top = pages.filter((p) => p.top), rest = pages.filter((p) => !p.top);
  const opts = rootReady() ? [el("option", { value: "__none__" }, "Sem curso (organizar depois)")]
    : [el("option", { value: "__none__", disabled: "" }, "Sem curso — escolha a página raiz em Ajustes")];
  opts.push(...pages.map((p) => el("option", { value: p.id, "data-title": p.title }, p.path)));
  // sem nenhuma página do topo do workspace: explica como liberar (o Notion não as envia sem permissão)
  const seen = rest.filter((p) => !p.path.includes(" › ")).map((p) => `“${p.title}”`);
  $("#roots-hint").hidden = pagesState !== "ok" || top.length > 0 || !seen.length;
  $("#roots-seen").textContent = seen.slice(0, 3).join(", ") + (seen.length > 3 ? ` e mais ${seen.length - 3}` : "");
  if (rootReady()) opts.push(el("option", { value: "__new__" }, "Novo curso em “" + (S?.config.root_page_title || "página raiz") + "”…"));
  sel.replaceChildren(...opts);
  if ([...sel.options].some((o) => o.value === prev && !o.disabled)) sel.value = prev;
  else if (!rootReady() && pages.length) sel.value = (top[0] || rest[0]).id;
  else if (prev && prev !== "__none__" && prev !== "__new__") toast("A página escolhida não existe mais no Notion; escolha outra.", true);
  courseChanged();
}

// ---------- busca de páginas (combobox) ----------
const fold = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();  // sem acento/maiúscula
const search = $("#course-filter"), results = $("#course-results");
let hits = [], active = -1;
function highlight(text, q) {
  const i = q ? fold(text).indexOf(q) : -1;
  if (i < 0) return [text];
  return [text.slice(0, i), el("mark", {}, text.slice(i, i + q.length)), text.slice(i + q.length)];
}
function renderResults() {
  if (document.activeElement !== search) return;
  const q = fold(search.value.trim());
  const info = (t) => [el("li", { class: "r-info", role: "presentation" }, t)];
  let items;
  if (pagesState === "loading") items = info("Carregando páginas do Notion…");
  else if (pagesState === "idle") items = info("Conecte o Notion em Integrações para ver suas páginas.");
  else if (pagesState === "error") items = info("Não foi possível carregar as páginas. Clique no campo de novo para tentar outra vez.");
  else {
    const scored = [];
    for (const p of pages) {
      const t = fold(p.title), path = fold(p.path);
      const s = !q ? (p.top ? 2 : 3) : t.startsWith(q) ? 0 : t.includes(q) ? 1 : path.includes(q) ? 2 : -1;
      if (s >= 0) scored.push([s, p]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].path.localeCompare(b[1].path, "pt-BR", { numeric: true }));
    hits = scored.slice(0, 60).map(([, p]) => p);
    const typed = search.value.trim();
    if (typed && !pages.some((p) => fold(p.title) === q)) hits.push({ create: typed });
    active = hits.length ? Math.min(active, hits.length - 1) : -1;  // campo vazio: nada pré-selecionado
    items = hits.length ? [
      el("li", { class: "r-count", role: "presentation" },
        q ? `${scored.length} página${scored.length === 1 ? "" : "s"} encontrada${scored.length === 1 ? "" : "s"}` : `${pages.length} páginas — digite para filtrar`),
      ...hits.map((p, i) => {
        if (p.create) {
          const sel = selectedPage();
          const li = el("li", { role: "option", id: "r-" + i, class: "r-create", "aria-selected": String(i === active) },
            el("span", { class: "r-title" }, `Criar página “${p.create}”`),
            el("span", { class: "r-path" }, `dentro de ${sel ? sel.path : (S?.config.root_page_title || "página raiz")}`));
          li.addEventListener("mousedown", (e) => { e.preventDefault(); createFromSearch(p.create); });
          return li;
        }
        const parent = p.path.slice(0, Math.max(0, p.path.length - p.title.length)).replace(/ › $/, "");
        const li = el("li", { role: "option", id: "r-" + i, "aria-selected": String(i === active) },
          el("span", { class: "r-title" }, ...highlight(p.title, q)),
          parent ? el("span", { class: "r-path" }, parent) : p.top ? el("span", { class: "r-path r-top" }, "Página raiz do Notion") : null);
        li.addEventListener("mousedown", (e) => { e.preventDefault(); choosePage(p); });
        li.addEventListener("mousemove", () => { if (active !== i) { active = i; markActive(); } });
        return li;
      })] : info(`Nenhuma página com “${search.value.trim()}”.`);
    if (hits.length && hits.every((h) => h.create)) items.splice(0, 1, el("li", { class: "r-count", role: "presentation" }, "Nenhuma página com esse nome"));
  }
  results.replaceChildren(...items);
  results.hidden = false;
  search.setAttribute("aria-expanded", "true");
  markActive();
}
function markActive() {
  results.querySelectorAll("[role=option]").forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
  const cur = results.querySelector(`#r-${active}`);
  if (cur) { search.setAttribute("aria-activedescendant", cur.id); cur.scrollIntoView({ block: "nearest" }); }
  else search.removeAttribute("aria-activedescendant");
}
function closeResults() {
  results.hidden = true; search.setAttribute("aria-expanded", "false"); search.removeAttribute("aria-activedescendant");
}
function createFromSearch(name) {
  search.value = "";
  closeResults();
  openNewPage(name);
}
function choosePage(p) {
  if (p.create) return createFromSearch(p.create);
  renderCourses(p.id);
  search.value = "";
  closeResults();
  search.blur();  // ao voltar para a janela, a lista não reabre sozinha
  courseChanged();
  toast(`A aula será salva em “${p.path}”.`);
}
search.addEventListener("input", () => { active = 0; renderResults(); });
search.addEventListener("focus", () => {
  active = -1;
  if (pagesState === "error") loadCourses();  // nova tentativa ao voltar ao campo
  // sobe a busca para o alto da área de conteúdo, para a lista de resultados caber inteira
  const box = $("#content"), top = search.getBoundingClientRect().top - box.getBoundingClientRect().top;
  if (top > 120) box.scrollTop += top - 90;  // imediato: a rolagem suave era interrompida pelo clique
  renderResults();
});
search.addEventListener("blur", () => setTimeout(closeResults, 120));
search.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (results.hidden) return renderResults();
    if (!hits.length) return;
    active = e.key === "ArrowDown" ? (active + 1) % hits.length : (active - 1 + hits.length) % hits.length;
    markActive();
  } else if (e.key === "Enter") {
    if (!results.hidden && hits[active]) { e.preventDefault(); choosePage(hits[active]); }
  } else if (e.key === "Escape") {
    if (!results.hidden) { e.preventDefault(); e.stopPropagation(); closeResults(); }
  }
});
function courseChanged() {
  const sp = selectedPage();
  if ($("#course").value === "__new__") openNewPage("", true);
  // quadro “Nova página” aberto: acompanha a página escolhida (antes ficava preso no destino antigo)
  else if (!$("#new-course").hidden && sp && newParent?.id !== sp.id) openNewPage($("#new-course-name").value);
  renderDest();
  renderBrowse();
  updateGo();
}
$("#course").addEventListener("change", courseChanged);

// ---------- navegador de páginas ----------
let level = null;  // página cujas subpáginas estão na lista (null = páginas principais do Notion)
let recent = [];
try { recent = JSON.parse(localStorage.getItem("lumen.recent")) || []; } catch {}
function remember(id) {
  if (!id || id === "__new__") return;
  recent = [id, ...recent.filter((x) => x !== id)].slice(0, 5);
  try { localStorage.setItem("lumen.recent", JSON.stringify(recent)); } catch {}
}
const pageIcon = (p) => p?.icon || icon("page", "sm");  // o emoji é da página (Notion); sem ele, o ícone do Lumen
const byTitle = (a, b) => (b.top - a.top) || a.title.localeCompare(b.title, "pt-BR", { numeric: true });
function tree() {
  const by = new Map(pages.map((p) => [p.id, p])), kids = new Map();
  for (const p of pages) {
    const k = p.parent && by.has(p.parent) ? p.parent : null;
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k).push(p);
  }
  return { by, kids };
}
function trail(p, by) {  // da página principal até p
  const out = [];
  for (let i = 0; p && i < 60; i++) { out.unshift(p); p = by.get(p.parent); }
  return out;
}
function renderDest() {
  const p = selectedPage(), v = $("#course").value;
  $("#dest-icon").replaceChildren(p ? pageIcon(p) : icon(v === "__none__" ? "folder" : "page", "sm"));
  if (!p) return $("#dest-path").replaceChildren(v === "__none__" ? "Sem curso (organizar depois)" : "Escolha uma página");
  const t = trail(p, tree().by), shown = t.length > 3 ? t.slice(-3) : t;
  $("#dest-path").dataset.tip = t.map((x) => x.title).join(" › ");
  $("#dest-path").replaceChildren(...(t.length > 3 ? [el("span", { class: "up" }, "…"), el("span", { class: "sep" }, "›")] : []),
    ...shown.flatMap((x, i) => [i ? el("span", { class: "sep", "aria-hidden": "true" }, "›") : null,
      el("span", { class: i === shown.length - 1 ? "" : "up" }, x.title)]).filter(Boolean));
}
function pick(id) {
  $("#course").value = id;
  courseChanged();
}
function renderBrowse() {
  if ($("#picker").hidden) return;
  const { by, kids } = tree(), cur = $("#course").value;
  if (level && !by.has(level)) level = null;
  const lv = level ? by.get(level) : null;
  // usadas recentemente (+ “organizar depois”)
  const chip = (label, id, ic) => el("button", { type: "button", class: "chip" + (cur === id ? " on" : ""), "data-tip": label,
    onclick: () => { const p = by.get(id); level = p ? (kids.has(p.id) ? p.id : p.parent || null) : level; pick(id); } }, ic, label);
  $("#recents").replaceChildren(...recent.filter((id) => by.has(id)).map((id) => chip(by.get(id).title, id, pageIcon(by.get(id)))),
    ...(rootReady() ? [chip("Organizar depois", "__none__", icon("folder", "sm"))] : []));
  // caminho clicável
  const crumbs = [el("button", { type: "button", class: "crumb" + (lv ? "" : " cur"), onclick: () => { level = null; renderBrowse(); } }, "Notion")];
  if (lv) for (const x of trail(lv, by)) crumbs.push(el("span", { class: "sep", "aria-hidden": "true" }, "›"),
    el("button", { type: "button", class: "crumb" + (x.id === lv.id ? " cur" : ""), onclick: () => { level = x.id; pick(x.id); } }, x.title));
  $("#crumbs").replaceChildren(...crumbs);
  // páginas deste nível: clicar escolhe; se tiver subpáginas, entra nela
  const list = (kids.get(level) || []).slice().sort(byTitle);
  $("#browse").replaceChildren(...(list.length ? list.map((p) => {
    const n = (kids.get(p.id) || []).length;
    return el("li", {}, el("button", { type: "button", class: "brow" + (p.id === cur ? " on" : ""), "aria-current": String(p.id === cur),
      onclick: () => { if (n) level = p.id; pick(p.id); } },
      el("span", { class: "b-icon", "aria-hidden": "true" }, pageIcon(p)), el("span", { class: "b-title" }, p.title),
      n ? el("span", { class: "b-count", "aria-label": `${n} subpáginas` }, String(n), icon("chevron-right")) : null));
  }) : [el("li", { class: "b-empty" }, pagesState === "loading" ? "Carregando páginas do Notion…"
    : `Nenhuma subpágina em “${lv?.title || "Notion"}”. Use “Nova subpágina” (+) para criar uma.`)]));
}
function setPicker(open) {
  if ($("#picker").hidden === !open) return;
  $("#picker").hidden = !open;
  $("#dest-change").textContent = open ? "Pronto" : "Alterar";
  $("#dest-change").setAttribute("aria-expanded", String(open));
  if (open) {  // abre mostrando onde a página escolhida está
    const p = selectedPage(), { kids } = tree();
    level = p ? (kids.has(p.id) ? p.id : p.parent || null) : null;
    renderBrowse();
  }
}
$("#dest-change").addEventListener("click", () => setPicker($("#picker").hidden));
// fecha com Esc ou clicando fora (do navegador e do cartão do destino)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !e.defaultPrevented && !$("#picker").hidden) { e.preventDefault(); setPicker(false); $("#dest-change").focus(); }
});
document.addEventListener("pointerdown", (e) => {
  if (!$("#picker").hidden && !e.target.closest("#picker, .dest")) setPicker(false);
});

// Ao voltar para a janela, atualiza a lista de páginas em segundo plano (no máximo a cada 30 s),
// para aparecer o que foi criado, renomeado ou conectado no Notion enquanto o Lumen estava aberto.
let pagesAt = 0, refreshing = false;
async function refreshPagesSilently() {
  if (refreshing || pagesState === "loading" || !S?.has_token) return;
  if (Date.now() - pagesAt < 30_000) return;
  refreshing = true;
  try {
    gotPages(await api("/api/courses"));
    renderCourses();                                   // mantém a página escolhida, se ela ainda existir
    if (!results.hidden) renderResults();
  } catch { /* silencioso: a lista anterior continua valendo */ } finally { refreshing = false; }
}
window.addEventListener("focus", refreshPagesSilently);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshPagesSilently(); });

// ---------- criar subpágina no Notion ----------
let newParent = null;  // {id, path}
function selectedPage() {
  return pages.find((p) => p.id === $("#course").value) || null;
}
function openNewPage(name = "", atRoot = false) {
  const root = pages.find((p) => p.id === S?.config.root_page_id);
  const sel = atRoot ? null : selectedPage();
  newParent = sel ? { id: sel.id, path: sel.path }
    : { id: S?.config.root_page_id, path: root ? root.path : (S?.config.root_page_title || "página raiz") };
  if (!newParent.id) return toast("Conecte o Notion em Integrações primeiro.", true);
  $("#new-course-where").replaceChildren("Nova página dentro de ", el("strong", {}, newParent.path),
    sel ? "" : el("span", { class: "muted" }, " (escolha outra página antes para criar dentro dela)"));
  $("#new-course").hidden = false;
  $("#new-course-name").value = name;
  $("#new-course-name").focus();
  preview = null;
  if (typeof showCoverIdle === "function") showCoverIdle();
}
function closeNewPage() {
  $("#new-course").hidden = true;
  $("#cover-preview").hidden = true;
  if ($("#course").value === "__new__") { $("#course").value = "__none__"; updateGo(); }
}
async function createCourse() {
  const name = $("#new-course-name").value.trim();
  if (!name) return $("#new-course-name").focus();
  const same = pages.find((p) => p.title.toLowerCase() === name.toLowerCase() && p.path === `${newParent.path} › ${p.title}`);
  if (same) {  // evita página repetida no mesmo lugar
    $("#course").value = same.id; closeNewPage(); courseChanged();
    return toast(`“${same.title}” já existe aí; ela foi escolhida como destino.`);
  }
  const btn = $("#new-course-btn"), deco = $("#decorate").checked;
  btn.disabled = true;
  if (deco) btn.textContent = !(preview && preview.name === name) && S?.covers?.ready ? "Criando capa (≈ 30 s)…" : "Criando…";
  try {
    const usePreview = deco && preview && preview.name === name ? preview.id : null;
    const c = await api("/api/courses", { title: name, parent_id: newParent.id, decorate: deco, parent_path: newParent.path,
                                          preview_id: usePreview });
    pages.push({ id: c.id, title: c.title, path: `${newParent.path} › ${c.title}`, top: false, parent: newParent.id,
                 icon: c.decor?.emoji || null });
    pages.sort((a, b) => a.path.localeCompare(b.path, "pt-BR", { numeric: true }));
    remember(c.id);
    renderCourses(c.id);
    $("#new-course-name").value = ""; $("#course-filter").value = "";
    closeNewPage(); courseChanged();
    toast(c.note ? c.note : `${c.decor ? c.decor.emoji + " " : ""}Página “${c.title}” criada dentro de “${newParent.path}”`
      + (c.decor ? " com ícone, capa e destaque." : ".") + " A aula será salva nela.", !!c.note);
  } catch (e) { fail(e); } finally { btn.disabled = false; btn.textContent = "Criar"; }
}
$("#new-sub").addEventListener("click", () => openNewPage());

// ---------- prévia da capa (IA local + desenho no PC) ----------
let preview = null, previewTimer = null, previewSeq = 0, variant = 0;
function showCoverIdle() {  // nome mudou: a prévia antiga não vale mais; espera o clique em “Gerar capa”
  const name = $("#new-course-name").value.trim();
  const box = $("#cover-preview");
  previewSeq++; preview = null;
  if (!$("#decorate").checked || name.length < 2 || $("#new-course").hidden) { box.hidden = true; return; }
  box.hidden = false;
  $("#cover-img").style.backgroundImage = "";
  $("#cover-wait").hidden = false;
  $("#cover-wait").textContent = S?.covers?.ready
    ? "Clique em “Gerar capa” para criar uma ilustração com IA (≈ 30 s). Ou só clique em Criar."
    : "Clique em “Gerar capa” para ver a prévia.";
  $("#cover-emoji").textContent = ""; $("#cover-sub").textContent = "";
  setLabel($("#cover-again"), "Gerar capa", "sparkle"); $("#cover-again").disabled = false;
}
async function loadPreview(again = false) {
  const name = $("#new-course-name").value.trim();
  const box = $("#cover-preview");
  if (!$("#decorate").checked || name.length < 2 || $("#new-course").hidden) { box.hidden = true; preview = null; return; }
  variant = again ? variant + 1 : 0;
  const seq = ++previewSeq;
  box.hidden = false;
  $("#cover-img").style.backgroundImage = "";
  $("#cover-wait").hidden = false;
  $("#cover-wait").textContent = S?.covers?.ready ? "Criando a ilustração com IA no seu PC (≈ 30 s)…" : "Criando a capa…";
  $("#cover-emoji").textContent = ""; $("#cover-sub").textContent = "";
  $("#cover-again").disabled = true;
  try {
    const r = await api("/api/decor/preview", { title: name, parent_path: newParent?.path || "", variant });
    if (seq !== previewSeq) return;  // o usuário já digitou outra coisa
    preview = { id: r.preview_id, name };
    if (r.image) { $("#cover-img").style.backgroundImage = `url("${r.image}")`; $("#cover-wait").hidden = true; }
    else $("#cover-wait").textContent = "Não foi possível desenhar a capa; será usada uma capa do Notion.";
    $("#cover-emoji").textContent = r.decor.emoji;
    $("#cover-sub").textContent = r.decor.subtitle;
    setLabel($("#cover-again"), "Gerar outra", "refresh");
  } catch (e) {
    if (seq !== previewSeq) return;
    preview = null;
    $("#cover-wait").textContent = e.message + " A página será criada sem enfeites.";
  } finally { if (seq === previewSeq) $("#cover-again").disabled = false; }
}
$("#new-course-name").addEventListener("input", () => { clearTimeout(previewTimer); previewTimer = setTimeout(showCoverIdle, 300); });
$("#cover-again").addEventListener("click", () => loadPreview(!!preview));
try { $("#decorate").checked = localStorage.getItem("lumen.decorate") !== "0"; } catch { $("#decorate").checked = true; }
$("#decorate").addEventListener("change", (e) => {
  try { localStorage.setItem("lumen.decorate", e.target.checked ? "1" : "0"); } catch {}
  showCoverIdle();
});
$("#new-course-btn").addEventListener("click", createCourse);
$("#new-course-cancel").addEventListener("click", closeNewPage);
$("#new-course-name").addEventListener("keydown", (e) => {
  if (e.key === "Enter") createCourse();
  if (e.key === "Escape") closeNewPage();
});

// ---------- revisão ----------
function updateGo() {
  renderWatch();
  const sel = $("#course"), go = $("#go");
  const course = sel.selectedOptions[0];
  const rows = [];
  if (found) rows.push(["Fonte", `${found.label} — ${found.title}`]);
  const solo = !usesNotion();
  $("#dest-card").classList.toggle("solo-obsidian", solo);
  rows.push(["Curso", solo ? $("#course-text").value.trim() || "—" : course && course.value !== "__new__" ? course.textContent : "—"]);
  const local = found?.has_captions || found?.resumable ? "Material escrito pela IA local (Ollama)."
    : "Transcrição (Whisper) e material (Ollama) feitos no seu PC.";
  const watching = S?.config.watch_screen && !$("#watch-row").hidden;
  rows.push(["Antes da IA", "Você escreve o que entendeu. Só depois a IA analisa a sua nota e complementa."]);
  rows.push(["No seu PC", local + (watching ? " A tela é lida por IA local." : "") + " O vídeo e o áudio não são enviados."]);
  if (usesNotion()) rows.push(["Enviado ao Notion", "A página da aula e a subpágina “Minha compreensão” (sua nota e a análise)"
    + (watching ? ", com as imagens das telas que você mantiver." : ".")]);
  if (usesObsidian()) rows.push(["No Obsidian", "Nota de estudo, mapa mental (Canvas), perguntas, revisões e conexões com o seu cofre, na pasta do Lumen."]);
  $("#summary").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));

  let why = "";
  if (usesNotion() && !S?.has_token) why = "Conecte o Notion em Integrações.";
  else if (usesObsidian() && !vaultReady()) why = "Escolha o cofre do Obsidian em Integrações.";
  else if (usesNotion() && course?.value === "__none__" && !rootReady()) why = "Escolha uma página do Notion (ou a página raiz em Integrações).";
  else if (!S.ollama.running) why = "Abra o Ollama para gerar o material.";
  else if (!S.ollama.installed) why = "Baixe o modelo de IA em Ajustes → IA local.";
  else if (kind === "captures" && !S.vision.installed) why = "Baixe o modelo de visão em Ajustes → Captura para ler as capturas.";
  else if (!found) why = kind === "recording" ? "Grave a aula para continuar." : kind === "captures" ? "Adicione as capturas para continuar." : "Escolha o arquivo da aula.";
  else if (found.needs_transcript) why = "Forneça a transcrição do vídeo.";
  else if (found.needs_transcription && !found.whisper_ready) why = "Baixe o modelo de transcrição em Ajustes → Transcrição.";
  else if (usesNotion() && (!course || course.value === "__new__")) why = "Escolha ou crie um curso.";
  else if (S.recording?.active) why = "Pare a gravação antes de gerar.";
  go.disabled = !!why || polling;
  $("#go-hint").textContent = why;
}

$("#go").addEventListener("click", () => {
  const sel = $("#course");
  if (found.duplicate) {
    const choice = document.querySelector("input[name=dup]:checked").value;
    if (choice === "open") return found.duplicate.url ? window.open(found.duplicate.url, "_blank") : openObsidian(found.duplicate.key, "note");
    lastSpec = { ...currentSpec(), mode: choice };
  } else lastSpec = { ...currentSpec(), mode: "new" };
  Object.assign(lastSpec, chosenDest() || {});
  Object.assign(lastSpec, {
                            language: $("#lang").value, speed: $("#speed").value });
  start(lastSpec);
});

// ---------- destino que acompanha a tela ----------
const destCard = $("#dest-card"), destHome = destCard.parentElement, destNext = destCard.nextElementSibling;
function dockDest(slot) {  // move o cartão “Onde salvar” (com tudo ligado a ele) para outra tela, ou de volta
  if (!slot) { if (destCard.parentElement !== destHome) destHome.insertBefore(destCard, destNext); return; }
  if (destCard.parentElement !== slot) slot.append(destCard);
}
function chosenDest() {
  if (!usesNotion()) return { course_title: $("#course-text").value.trim().slice(0, 120) };
  const sel = $("#course");
  if (!sel.value || sel.value === "__new__") return null;
  remember(sel.value);
  return { course_id: sel.value, course_title: sel.value === "__none__" ? "" : sel.selectedOptions[0].dataset.title };
}

// ---------- execução ----------
let lastUrl = "/api/start";
async function start(spec, url = "/api/start") {
  lastUrl = url;
  try { await api(url, spec); } catch (e) { return fail(e); }
  showStep("run"); $("#redo").hidden = true; prepKey = null;
  $("#run-h").textContent = url === "/api/start" ? "Preparando a aula" : `Salvando o material ${destName()}`;
  $("#result").replaceChildren(); $("#result").className = "result";
  $("#run-h").focus();
  poll();
}

const ORDER = ["prepare", "transcribe", "screen", "generate", "connect", "obsidian", "publish"];
let lastJob = null;
function renderJob(j) {
  lastJob = j;
  if (j.kind === "download") return renderDownload(j);
  if (j.kind === "analyze") return renderAnalyzing(j);
  if (j.kind === "process" && lastUrl === "/api/start" && j.key && followPrep(j)) return;
  const cur = ORDER.indexOf(j.stage);
  for (const li of $$("#stages li")) {
    const i = ORDER.indexOf(li.dataset.stage);
    li.className = (j.status === "done" || i < cur ? "done" : i === cur && j.status === "running" ? "active"
      : i === cur && j.status === "error" ? "failed" : "")
      + ((j.skipped || []).includes(li.dataset.stage) ? " skip" : "");
    li.querySelector(".ps-mark").setAttribute("aria-label", li.classList.contains("done") ? "Concluída" : li.classList.contains("active") ? "Em andamento"
      : li.classList.contains("failed") ? "Falhou" : "Pendente");
    if (li.dataset.stage === "screen") li.hidden = !j.screen;
    const to = j.dests || dests();
    if (li.dataset.stage === "publish") li.hidden = !to.includes("notion");
    if (li.dataset.stage === "obsidian") li.hidden = !to.includes("obsidian");
    if (li.dataset.stage === "connect") li.hidden = !to.includes("obsidian") || !S?.config.obsidian_connections || S?.config.study_level === "rapido";
  }
  const bar = $("#bar");
  const det = j.status === "running" && (j.progress === null || j.progress === undefined);
  $("#stage-now").hidden = j.status !== "running";
  bar.classList.toggle("indeterminate", det);
  const pct = j.status === "done" ? 100 : Math.round((j.progress || 0) * 100);
  bar.querySelector("span").style.width = det ? "" : pct + "%";
  if (det) bar.removeAttribute("aria-valuenow"); else bar.setAttribute("aria-valuenow", pct);
  $("#detail").textContent = j.status === "running" ? j.detail || "" : "";
  $("#eta").textContent = j.status !== "running" ? ""
    : Number.isFinite(j.eta_total) ? etaText(j.eta_total, lastUrl === "/api/start" ? "Transcrição pronta" : "Página pronta")
    : j.eta ? `Faltam cerca de ${fmtDur(j.eta)} nesta etapa.` : "";

  // enquanto transcreve, o destino ainda pode mudar (ele só é usado ao gerar a página)
  const transcribing = j.status === "running" && lastUrl === "/api/start" && ["prepare", "transcribe"].includes(j.stage);
  if (transcribing) dockDest($("#run-dest"));
  $("#run-dest").hidden = !transcribing;
  const res = $("#result"), act = $("#run-actions");
  const back = el("button", { class: "btn ghost", type: "button", onclick: backToCompose }, icon("new"), "Nova aula");
  const head = (ic, text) => el("strong", {}, icon(ic), text);
  // o cabeçalho diz o estado da tarefa (o resultado detalha por destino)
  const fin = j.status === "done" && !j.result?.review, bad = fin && [j.result.notion, j.result.obsidian].some((d) => d && d.status !== "ok");
  const tone = j.status === "error" ? "error" : j.status === "cancelled" || bad ? "warn" : fin ? "ok" : "";
  $(".run-ico").dataset.tone = tone;
  $(".run-ico").replaceChildren(icon({ ok: "check-circle", warn: "alert", error: "x-circle" }[tone] || "sparkle", "lg"));
  if (j.status !== "running") $("#run-h").textContent = { ok: "Material salvo", warn: j.status === "cancelled" ? "Tarefa cancelada" : "Material salvo, com uma pendência",
    error: "Não foi possível concluir" }[tone] || $("#run-h").textContent;
  if (j.status === "running") {
    act.replaceChildren(el("button", { class: "btn ghost", type: "button", onclick: cancelJob }, icon("x"), "Cancelar tarefa"));
  } else if (j.status === "done" && j.result.review) {  // aula preparada: agora é a vez do estudante
    if (step === "run") return openUnderstanding(j.result.key).catch(fail);
    return refresh().catch(() => {});  // saiu para “Escrever depois”: a aula aparece em Continuar aprendendo
  } else if (j.status === "done") {
    const r = j.result, nt = r.notion, ob = r.obsidian, fails = [nt, ob].filter((d) => d && d.status !== "ok");
    res.className = "result " + (fails.length ? "partial" : "ok");
    res.replaceChildren(head(fails.length ? "alert" : "check-circle", fails.length ? "Material processado, com um destino pendente" : "Material processado"),
      ...doneLines(r));
    if (r.note) res.append(el("span", { class: "dest-line" }, icon("info"), el("span", {}, r.note)));
    act.replaceChildren(...[
      nt?.status === "ok" && el("a", { class: "btn primary", href: nt.url, target: "_blank", rel: "noopener" }, icon("external"), "Abrir no Notion"),
      nt?.status === "ok" && nt.understanding_url && el("a", { class: "btn", href: nt.understanding_url, target: "_blank", rel: "noopener" }, "Abrir minha compreensão"),
      ob?.status === "ok" && el("button", { class: "btn" + (nt ? "" : " primary"), type: "button", onclick: () => openObsidian(r.key, "note") }, icon("notebook"), "Abrir no Obsidian"),
      ob?.status === "ok" && ob.canvas && el("button", { class: "btn", type: "button", onclick: () => openObsidian(r.key, "canvas") }, icon("map"), "Abrir mapa mental"),
      nt && nt.status !== "ok" && el("button", { class: "btn primary", type: "button", onclick: () => redeliver(r.key, "notion") }, icon("refresh"), "Tentar de novo só o Notion"),
      ob && ob.status !== "ok" && el("button", { class: "btn primary", type: "button", onclick: () => redeliver(r.key, "obsidian", ob.conflict) },
        icon("refresh"), ob.conflict ? "Substituir mesmo assim (com backup)" : "Tentar de novo só o Obsidian"),
      lastSpec && lastUrl !== "/api/deliver" && el("button", { class: "btn ghost", type: "button", onclick: openRedo }, icon("sparkle"), "Refazer material"), back].filter(Boolean));
    act.querySelector("a, button")?.focus();
  } else if (j.status === "error") {
    res.className = "result err";
    res.replaceChildren(head("x-circle", j.error.message), el("span", {}, j.error.action));
    act.replaceChildren(lastSpec ? el("button", { class: "btn primary", type: "button", onclick: () => start(lastUrl === "/api/deliver" ? lastDeliver : lastSpec, lastUrl) }, icon("refresh"), "Tentar novamente") : null,
      el("button", { class: "btn ghost", type: "button", onclick: backToCompose }, icon("arrow-left"), "Voltar"));
  } else if (j.status === "cancelled") {
    res.className = "result cancel";
    res.replaceChildren(head("alert", "Cancelado"), el("span", {}, "As etapas já concluídas foram guardadas e serão reaproveitadas."));
    act.replaceChildren(lastSpec ? el("button", { class: "btn primary", type: "button", onclick: () => start(lastSpec, lastUrl) }, icon("play"), "Retomar") : null,
      el("button", { class: "btn ghost", type: "button", onclick: backToCompose }, icon("arrow-left"), "Voltar"));
  }
}

function doneLines(r) {  // uma linha por destino: o que foi feito ou o que falhou e o que fazer
  const out = [], nt = r.notion, ob = r.obsidian;
  const line = (who, ok, text) => el("span", { class: "dest-line", "data-ok": String(ok) }, icon(ok ? "check-circle" : "x-circle"),
    el("span", {}, el("b", {}, who), el("span", { class: "sr" }, ok ? " (salvo): " : " (falhou): "), text));
  if (nt) out.push(line("Notion", nt.status === "ok", nt.status === "ok"
    ? `Página “${r.title}” em ${r.course}, com a subpágina “Minha compreensão”.` : `${nt.error} ${nt.action || ""}`));
  if (ob) out.push(line("Obsidian", ob.status === "ok", ob.status === "ok"
    ? [{ created: "Nota criada", updated: "Nota atualizada (suas anotações ficaram)", unchanged: "Nota já estava em dia" }[ob.state] || "Nota salva",
       ob.canvas ? "mapa mental (Canvas)" : null, `${ob.connections} ${ob.connections === 1 ? "conexão" : "conexões"} com o cofre`,
       `${ob.questions} perguntas de revisão`, ob.canvas_error].filter(Boolean).join(" · ")
    : `${ob.error} ${ob.action || ""}`));
  return out;
}
let lastDeliver = null;
function redeliver(key, only, force = false) {
  lastDeliver = { key, only: [only], force, ...(only === "notion" && lastSpec ? { course_id: lastSpec.course_id, mode: lastSpec.mode } : {}) };
  start(lastDeliver, "/api/deliver");
}
async function openObsidian(key, what) {
  try { await api("/api/open", { key, what }); toast("Abrindo no Obsidian…"); } catch (e) { fail(e); }
}

function openRedo() {
  $("#redo").hidden = false; dockDest($("#redo-dest")); $("#run-actions").replaceChildren(); $("#redo-note").focus();
}
$("#redo-cancel").addEventListener("click", () => { $("#redo").hidden = true; poll(); });  // volta aos botões do resultado
$("#redo-go").addEventListener("click", () => {
  const dest = chosenDest();
  if (!dest) return $("#redo-note").focus();
  lastSpec = { ...lastSpec, ...dest, mode: "redo", redo_note: $("#redo-note").value.trim() };
  start(lastSpec, "/api/finish");
});

async function cancelJob() {
  $("#detail").textContent = "Cancelando… (termina o trecho atual)";
  try { await api("/api/cancel", {}); } catch (e) { fail(e); }
}

// ---------- telas do fluxo: fonte → minha compreensão → análise + salvar no Notion ----------
const STEPS = ["compose", "understand", "analysis", "run", "review"];
let step = "compose";
function showStep(...names) {  // a primeira é a principal; a análise e “Salvar no Notion” aparecem juntas
  if (step !== names[0] && view === "new") $("#content").scrollTop = 0;
  step = names[0];
  for (const s of STEPS) $("#" + s).hidden = !names.includes(s);
  $("#review-more").hidden = $("#review").hidden;  // a revisão da transcrição fica na coluna principal, junto da análise
  $("#view-new").dataset.step = step;
  renderStepper();
}
// Fonte → Compreensão → Análise → Salvar: onde a aula está no fluxo (a tarefa diz se é preparo ou publicação)
function renderStepper() {
  const saving = step === "run" && lastUrl !== "/api/start";
  const at = { compose: 0, understand: 1, run: saving ? 3 : 1, analysis: U?.state === "synced_to_notion" ? 4 : 2 }[step] ?? 0;
  $$("#stepper li").forEach((li, i) => {
    li.dataset.on = i < at ? "done" : i === at ? "now" : "";
    if (i === at) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
  const names = { compose: "", understand: "Minha compreensão", analysis: U?.state === "synced_to_notion" ? "Material salvo" : "Análise",
    run: saving ? "Salvando" : "Preparando", review: "" };
  if (view === "new") setWhere("Nova aula", names[step]);
}
// ---------- Minha compreensão (a IA só trabalha depois desta nota) ----------
// Texto, autosave e sincronização entre janelas são do componente compartilhado (understanding-editor.js): este
// editor, o da barra lateral e o da janela flutuante são o mesmo documento. A regra de verdade está no servidor.
const noteProblem = Notes.problem;
const day = (iso) => iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "long" }) : "";
const WRITING = ["studying", "waiting_for_understanding", "understanding_written"];

let U = null;  // a compreensão aberta (GET /api/understanding): estado e análise; nunca a transcrição
let prepKey = null;
const uEditor = new UnderstandingEditor({ text: $("#u-text"), save: $("#u-save"), count: $("#u-count"), grow: true,
  onChange: (d) => {
    if (U?.key !== d.key) return;
    const was = U.state;
    if (d.view && U.state !== "processing_with_ai") U.state = d.view.state;  // escrita ↔ pronta, vindo do autosave
    if (d.view?.state === "processing_with_ai") U.state = d.view.state;       // enviada por outra janela
    if (step === "understand") {
      if (was !== U.state) { $("#understand").dataset.state = U.state; renderUStatus(); }
      noteState();
    }
  } });
// Enviada ou analisada em outra janela (barra lateral, flutuante): esta acompanha a tarefa até o fim.
Notes.on("state", (key) => { if (U?.key === key && !polling) poll(); });
const mineEditor = new UnderstandingEditor({ text: $("#mine-text"), save: $("#mine-save"), grow: true,
  onChange: (d) => { if (U?.key === d.key && step === "analysis") mineChanged(); } });

async function openUnderstanding(key, { resume = false } = {}) {
  const { doc, recovered } = await Notes.load(key);
  if (resume || !lastSpec) lastSpec = doc.view.spec;
  U = { ...doc.view };
  Notes.setActive(key);  // a barra lateral acompanha a aula aberta aqui
  if (recovered) toast("Recuperamos o texto que você tinha escrito.");
  renderUnderstanding();
  // na última vez a nota estava destacada: volta a abrir a janela flutuante (preferência lembrada neste PC)
  if (Notes.pref("Mode") === "floating" && Notes.pref("Key") === key && WRITING.includes(U.state) && !Notes.floating(key))
    detach(key);
}

function renderUnderstanding() {
  if (["completed", "synced_to_notion"].includes(U.state)) return renderAnalysis();
  const first = step !== "understand";
  showStep("understand");
  $("#understand").dataset.state = U.state;
  $("#u-lesson").textContent = [U.label, U.title].filter(Boolean).join(" · ");
  const t = $("#u-text");
  uEditor.bind(U.key);
  uEditor.lock(U.state === "processing_with_ai");
  if (first && t.value && !$("#u-save").textContent) { $("#u-save").textContent = "Rascunho salvo"; $("#u-save").dataset.s = "saved"; }
  noteState();
  renderUStatus();
  renderFloat();
  renderUCap();
  if (first && !t.readOnly) { t.focus({ preventScroll: true }); t.setSelectionRange(t.value.length, t.value.length); }
}
function noteState() {  // a regra de “posso processar?” é uma só (Notes.ready), a mesma da barra e da janela flutuante
  const r = Notes.ready(U.key), busy = U.state === "processing_with_ai" || r.phase === "processing";
  $("#u-go").hidden = busy;
  $("#u-go").disabled = !r.can;
  $("#u-go").textContent = r.action || "Processar minha compreensão";
  $("#u-later").textContent = busy ? "Voltar à Nova aula" : "Escrever depois";
  const hint = $("#u-hint");
  hint.dataset.tone = busy ? "" : r.tone;
  const end = (t) => (/[.…?!]$/.test(t) ? t : t + ".");
  hint.textContent = busy ? "" : [r.label, r.detail || (r.phase === "ready" || r.phase === "completed" ? "A IA só lê a sua nota quando você pedir" : "")]
    .filter(Boolean).map(end).join(" ");
}
function renderUStatus(j = lastJob) {  // o que acontece por trás do papel: a preparação da aula ou a IA lendo a nota
  const box = $("#u-status");
  const mine = j && (j.key || j.spec?.key) === U?.key, running = mine && j.status === "running";
  const spin = () => el("span", { class: "spinner", "aria-hidden": "true" });
  if (U.state === "processing_with_ai" || (running && j.kind === "analyze")) {
    box.hidden = false; box.dataset.tone = "busy";
    const parts = running && /partes/.test(j.detail || "") ? j.detail : "";  // aula longa: “Lendo a aula por partes (1 de 3)…”
    return box.replaceChildren(...[spin(), el("strong", {}, "Analisando sua compreensão…"), parts && el("span", {}, parts),
      running && Number.isFinite(j.eta_total) && el("span", {}, etaText(j.eta_total, "Análise pronta"))].filter(Boolean));
  }
  box.hidden = U.state !== "studying";
  if (box.hidden) return;
  const again = el("button", { class: "btn sm", type: "button", onclick: () => prepare(U.spec) }, icon("refresh"), "Preparar de novo");
  if (running) {
    box.dataset.tone = "busy";
    const bar = el("span", { class: "u-mini", "aria-hidden": "true" }, el("span"));
    bar.firstChild.style.width = Math.round((j.progress || 0) * 100) + "%";
    box.replaceChildren(...[spin(), el("span", {}, el("strong", {}, "Preparando a aula"), j.detail ? " · " + j.detail : ""),
      Number.isFinite(j.progress) && bar].filter(Boolean));
  } else {
    box.dataset.tone = "error";
    if (mine && j.status === "error") box.replaceChildren(icon("alert"), el("strong", {}, j.error.message), el("span", {}, j.error.action), again);
    else box.replaceChildren(icon("alert"), el("span", {}, "A preparação desta aula não terminou."), again);
  }
}
// A captura enquanto se escreve: gravando (vermelho, com o tempo) ou pausada (âmbar), com o botão para pausar/retomar
function renderUCap() {
  const box = $("#u-cap"), r = S?.recording;
  box.hidden = !r?.active || step !== "understand";
  if (box.hidden) return;
  const paused = !!r.paused;
  box.dataset.tone = paused ? "paused" : "rec";
  const btn = el("button", { class: "btn sm", type: "button", "data-tip": paused ? "Retomar captura" : "Pausar captura (o vídeo continua)",
    "data-kbd": Shortcuts.capture.label, onclick: toggleRecPause }, icon(paused ? "play" : "pause"), paused ? "Retomar" : "Pausar");
  if (box.dataset.mode === box.dataset.tone) {  // a cada 220 ms só o tempo muda
    box.querySelector(".tabular").textContent = mmss(r.seconds);
    return;
  }
  box.dataset.mode = box.dataset.tone;
  box.replaceChildren(paused ? icon("pause") : el("span", { class: "live-dot", "aria-hidden": "true" }),
    el("span", {}, paused ? "Captura pausada · " : "Gravando · "), el("span", { class: "tabular" }, mmss(r.seconds)), btn);
}
async function prepare(spec) {  // prepara de novo sem sair do editor
  lastUrl = "/api/start"; lastSpec = spec;
  try { await api("/api/start", spec); } catch (e) { return fail(e); }
  poll();
}
// Preparação em andamento: assim que a aula tem nome, o editor abre e ela segue em segundo plano.
function followPrep(j) {
  if (step === "understand" && U?.key === j.key) {
    if (j.status === "done") openUnderstanding(j.key).catch(fail);
    else renderUStatus(j);
    return true;
  }
  if (step === "run" && j.status === "running" && prepKey !== j.key) {
    prepKey = j.key;
    api("/api/understanding?key=" + encodeURIComponent(j.key)).then((r) => {
      // aula já analisada (ex.: “Transcrever de novo”): segue no cartão de progresso até ficar pronta
      if (step === "run" && !["completed", "synced_to_notion"].includes(r.state)) return openUnderstanding(j.key);
    }).catch(() => {});
  }
  return false;
}

$("#u-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !$("#u-go").disabled) { e.preventDefault(); $("#u-go").click(); }
});
$("#u-go").addEventListener("click", () => submitNote());
$("#u-later").addEventListener("click", async () => { await Notes.flush(U.key); backToCompose(); });
async function submitNote() {
  // Notes.process grava a versão mais recente, confere os pré-requisitos e envia exatamente essa versão; o servidor
  // confere tudo de novo e trava a nota para edição até a análise terminar.
  try { await Notes.process(U.key); } catch (e) { return fail(e); }
  U.state = "processing_with_ai";
  lastJob = null;
  renderUnderstanding();
  poll();
}
function renderAnalyzing(j) {
  const key = j.spec?.key;
  if (j.status === "running") {
    if (U?.key === key && step === "understand") {
      U.state = "processing_with_ai"; $("#understand").dataset.state = U.state; uEditor.lock(true);
      noteState(); renderUStatus(j);
    }
    return;
  }
  if (U?.key !== key || !["understand", "analysis"].includes(step)) return refresh().catch(() => {});
  if (j.status === "done") return openUnderstanding(key).then(() => toast("Análise concluída.")).catch(fail);
  openUnderstanding(key).catch(() => {});  // erro ou cancelado: a nota continua guardada e o botão volta
  if (j.status === "error") fail(Object.assign(new Error(j.error.message), { action: j.error.action }));
}

// ---------- análise: a nota (intacta) e, à parte, o que a IA observou ----------
const SECTIONS = [["acertos", "O que eu compreendi corretamente", "check-circle"], ["parciais", "O que entendi em parte", "alert"],
  ["lacunas", "O que faltou", "minus"], ["confusoes", "Possíveis confusões", "x-circle"], ["complementos", "Complementos importantes", "plus"],
  ["conexoes", "Conexões", "graph"], ["perguntas", "Perguntas para aprofundar", "question"]];
async function renderAnalysis() {
  const a = U.analysis, synced = U.state === "synced_to_notion";
  $("#a-lesson").textContent = [U.label, U.title].filter(Boolean).join(" · ");
  const fk = U.final_knowledge;
  $("#a-title").textContent = synced ? "Material salvo" : "Análise concluída";
  $("#a-sub").textContent = synced ? [fk?.url && "A página da aula e a subpágina “Minha compreensão” estão no seu Notion.",
    fk?.obsidian && "A nota de estudo e o mapa mental estão no seu Obsidian."].filter(Boolean).join(" ")
    : "A IA comparou sua nota com a aula. Sua compreensão original continua exatamente como você escreveu.";
  mineEditor.bind(U.key);
  mineEditor.lock(true);
  setLabel($("#mine-edit"), "Editar", "pen"); $("#mine-edit").hidden = synced; $("#mine-foot").hidden = true;
  $("#mine-when").textContent = U.submitted ? "em " + day(U.submitted) : "";
  mineChanged();
  const of = (U.analyzed_text || "").trim() === (U.original || "").trim() ? "" : " · da sua versão atual";
  $("#ai").replaceChildren(el("p", { class: "ai-label" }, icon("sparkle"), "Análise da IA local" + (U.model ? " · " + U.model : "") + of),
    ...SECTIONS.filter(([k]) => a[k]?.length).map(([k, title, ic], i) => {
      const sec = el("section", { class: "ai-sec " + k }, el("h3", {}, icon(ic), title),
        k === "confusoes" ? el("div", {}, ...a[k].map((c) => el("div", { class: "conf" }, el("q", {}, c.trecho),
          el("p", {}, el("b", {}, "Na aula: "), c.correcao))))
          : el(k === "perguntas" ? "ol" : "ul", {}, ...a[k].map((x) => el("li", {}, x))));
      sec.style.animationDelay = `${i * 70}ms`;
      return sec;
    }));
  $("#a-actions").replaceChildren(...(synced ? [
    fk.url && el("a", { class: "btn primary", href: fk.url, target: "_blank", rel: "noopener" }, icon("external"), "Abrir no Notion"),
    fk.understanding_url && el("a", { class: "btn", href: fk.understanding_url, target: "_blank", rel: "noopener" }, "Abrir minha compreensão"),
    fk.obsidian && el("button", { class: "btn" + (fk.url ? "" : " primary"), type: "button", onclick: () => openObsidian(U.key, "note") }, icon("notebook"), "Abrir no Obsidian"),
    el("button", { class: "btn ghost", type: "button", onclick: backToCompose }, icon("new"), "Nova aula")].filter(Boolean) : []));
  $("#a-actions").hidden = !synced;
  if (synced) showStep("analysis");
  else {
    let r;
    try { r = await api("/api/review?key=" + encodeURIComponent(U.key)); } catch (e) { showStep("analysis"); return fail(e); }
    showReview(r);
  }
  requestAnimationFrame(() => mineEditor.grow());
  $("#a-title").focus({ preventScroll: true });
}
function mineChanged() {  // editada depois da análise: a original aparece à parte e dá para analisar de novo
  const text = $("#mine-text").value, changed = (U.original || "").trim() !== text.trim();
  $("#mine-label").textContent = changed ? "Sua versão atual" : "Você escreveu";
  $("#mine-original").hidden = !changed;
  $("#mine-original-text").textContent = U.original || "";
  $("#mine-again").hidden = text.trim() === (U.analyzed_text || "").trim() || !!noteProblem(text);
}
$("#mine-edit").addEventListener("click", async () => {
  const editing = mineEditor.locked;
  mineEditor.lock(!editing);
  setLabel($("#mine-edit"), editing ? "Concluir" : "Editar", editing ? "check" : "pen");
  $("#mine-foot").hidden = false;
  if (editing) { $("#mine-save").textContent = "A versão original fica guardada à parte."; $("#mine-text").focus(); }
  else await Notes.flush(U.key);
});
$("#mine-again").addEventListener("click", async () => { await Notes.flush(U.key); submitNote(); });

// ---------- destacar a nota: janela flutuante, sempre por cima do vídeo da aula ----------
// No Lumen.exe é uma janela nativa (launcher/NoteForm.cs); no navegador comum, um popup. É o mesmo documento: o que
// se escreve lá aparece aqui na hora, e vice-versa.
async function detach(key) {
  await Notes.flush(key);
  Notes.setPref("Mode", "floating"); Notes.setPref("Key", key);
  if (host) return host.postMessage("note:float:" + key);
  const size = Notes.pref("Size") || { w: 420, h: 520 }, pos = Notes.pref("Position");
  const w = Math.min(Math.max(size.w, 320), screen.availWidth), h = Math.min(Math.max(size.h, 260), screen.availHeight);
  const x = Math.min(Math.max(pos ? pos.x : screen.availWidth - w - 24, 0), screen.availWidth - w);
  const y = Math.min(Math.max(pos ? pos.y : screen.availHeight - h - 24, 0), screen.availHeight - h);
  if (!window.open("/note?key=" + encodeURIComponent(key), "lumen-note", `popup,width=${w},height=${h},left=${x},top=${y}`))
    toast("O navegador bloqueou a janela flutuante. Permita pop-ups para o Lumen.", true);
}
function attach(key) {  // “Trazer de volta”: a janela flutuante salva e fecha; aqui o texto já é o mesmo
  Notes.setPref("Mode", "docked");
  Notes.requestClose(key);
}
function renderFloat() {
  const on = !!U && Notes.floating(U.key);
  $("#u-float").hidden = !on || step !== "understand";
  $("#u-detach").setAttribute("aria-pressed", String(on));
  const label = on ? "Trazer de volta para cá" : "Destacar numa janela flutuante, por cima do vídeo";
  $("#u-detach").setAttribute("aria-label", label);
  $("#u-detach-label").textContent = on ? "Trazer de volta" : "Destacar";
  $("#u-detach").dataset.tip = label;
  $("#u-detach").dataset.kbd = Notes.shortcutLabel;
}
Notes.on("panel", renderFloat);
Notes.on("dock", (key) => {  // “Voltar para o Lumen” na janela flutuante: o editor volta para esta tela
  Notes.setPref("Mode", "docked");
  showView("new");
  if (step === "understand" && U?.key === key) renderFloat();
  else openUnderstanding(key, { resume: U?.key !== key }).catch(fail);
});
$("#u-detach").addEventListener("click", () => (Notes.floating(U.key) ? attach : detach)(U.key));
$("#u-float-back").addEventListener("click", () => attach(U.key));
document.addEventListener("keydown", (e) => {
  if (Notes.isShortcut(e) && step === "understand" && view === "new" && U) { e.preventDefault(); $("#u-detach").click(); }
});

// ---------- Continuar aprendendo: aulas que esperam a compreensão (ou só salvar no Notion) ----------
const PENDING = { studying: "Preparação não terminou", waiting_for_understanding: "Aguardando compreensão",
  understanding_written: "Compreensão escrita · falta processar", processing_with_ai: "Analisando sua compreensão…",
  completed: "Análise pronta · falta salvar o material" };
// Ícone e tom de cada estado: preparando (neutro), escrevendo (âmbar), pronta para analisar (azul), analisada (verde)
const PEND_LOOK = { studying: ["clock", ""], waiting_for_understanding: ["pen", "warn"], understanding_written: ["pen", "accent"],
  processing_with_ai: ["sparkle", "accent"], completed: ["check-circle", "ok"] };
const resume = (key) => { showView("new"); openUnderstanding(key, { resume: true }).catch(fail); };
function pendingRow(p) {
  const prepping = p.state === "studying" && S.job?.status === "running" && S.job.key === p.key;
  const [ic, tone] = PEND_LOOK[p.state] || ["pen", ""];
  return el("div", { class: "lib-row", role: "listitem" },
    el("span", { class: "lib-ico", "data-tone": tone, "aria-hidden": "true" }, icon(ic)),
    el("span", { class: "lib-text" }, el("span", { class: "lib-title" }, p.title || "Aula"),
      el("span", { class: "lib-meta" }, [prepping ? "Preparando…" : PENDING[p.state], p.label, day(p.updated)].filter(Boolean).join(" · "))),
    el("button", { class: "btn sm" + (p.state === "completed" ? "" : " primary"), type: "button", onclick: () => resume(p.key) },
      p.state === "completed" ? "Ver análise" : "Continuar"));
}
// O cartão principal do Início mostra a gravação, a tarefa ou, sem elas, a primeira aula em andamento
const heroBusy = () => !!(S?.recording?.active && !S.recording.error) || ((lastJob || S?.job)?.status === "running" && (lastJob || S.job).kind !== "download");
function renderPending() {
  const items = S?.pending || [], more = heroBusy() ? items : items.slice(1);  // sem repetir a que já está no cartão
  $("#pending").hidden = !more.length;
  $("#pending-all").hidden = more.length <= 3;
  swap($("#pending-list"), more.slice(0, 3).map(pendingRow));
  $("#lib-n-pending").textContent = items.length || "";
  if (view === "library") renderLibrary();
}

// ---------- revisão da transcrição ----------
let review = null, edits = {}, shotsOff = new Set();
function renderShots(r, keepOff = false) {
  const sc = r.screens, items = sc?.items || [];
  shotsOff = keepOff ? new Set([...shotsOff].filter((id) => items.some((s) => s.id === id))) : new Set();
  $("#shots").hidden = false;  // sempre: é por aqui que se adicionam capturas de tela
  $("#shots-info").textContent = (items.length
    ? `${items.length} com conteúdo${sc.seen > items.length ? `, de ${sc.seen} telas vistas` : ""}. Desmarque o que não deve ir para a página.`
    : sc?.seen ? "Nenhuma tela com conteúdo da aula (slide, quadro, código) foi encontrada."
    : "Nenhuma captura de tela nesta aula. Adicione imagens (sites, textos, slides, código) para entrarem na página.")
    + (sc?.warning ? " " + sc.warning : "");
  $("#shot-grid").replaceChildren(...items.map((s) => {
    const cb = el("input", { type: "checkbox", "aria-label": `Usar ${s.manual ? "a captura" : "a tela de " + mmss(s.t)}: ${s.titulo}` });
    cb.checked = !shotsOff.has(s.id);
    const card = el("label", { class: "shot", role: "listitem" },
      el("img", { src: `/api/screen?key=${encodeURIComponent(r.key)}&id=${s.id}&t=${encodeURIComponent(TOKEN)}`,
                  alt: s.titulo || "Tela da aula", loading: "lazy" }),
      el("span", { class: "shot-cap" }, cb, el("span", { class: "shot-time" }, s.manual ? icon("image", "sm") : mmss(s.t)), el("span", { class: "shot-title" }, s.titulo)));
    card.classList.toggle("off", !cb.checked);
    cb.addEventListener("change", () => { cb.checked ? shotsOff.delete(s.id) : shotsOff.add(s.id); card.classList.toggle("off", !cb.checked); });
    return card;
  }));
}
function musicNote(m) {  // “Filtrar música externa”: uma linha discreta na revisão, nunca um aviso que interrompe
  if (!m) return "";
  if (m.error) return ` Filtro de música não aplicado (${m.error}): foi transcrito o áudio original.`;
  if (!m.filtered) return " Filtro de música ativo: nenhuma música externa detectada.";
  const min = (s) => s >= 90 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`;
  return " Música externa detectada e filtrada" + (m.removed_s ? ` (${min(m.removed_s)} só de música ficaram fora)` : "")
    + "." + (m.doubt_s ? ` Trechos com voz e música juntas estão marcados como “música ao fundo”.` : "");
}
function reviewLabels() {
  const both = usesNotion() && usesObsidian();
  $("#review-h").textContent = "Salvar " + (both ? "no Notion e no Obsidian" : usesObsidian() ? "no Obsidian" : "no Notion");
  $("#review-desc").textContent = both ? "A página da aula no Notion e a nota de estudo com mapa mental no Obsidian, escritas a partir da sua compreensão."
    : usesObsidian() ? "A nota de estudo, o mapa mental, as perguntas e as revisões no seu cofre, escritos a partir da sua compreensão."
    : "A página da aula e a subpágina “Minha compreensão”, escritas a partir da sua compreensão.";
  $("#review-go").textContent = both ? "Salvar no Notion e no Obsidian" : usesObsidian() ? "Salvar no Obsidian" : "Criar página no Notion";
}

function showReview(r) {
  reviewLabels();  // “Salvar no Notion”, abaixo da análise (só existe depois da compreensão)
  review = r; edits = {};
  renderShots(r);
  $("#review-link-row").hidden = lastSpec?.kind === "youtube";
  $("#review-link").value = lastSpec?.link || "";
  showStep("analysis", "review"); dockDest($("#review-dest"));
  $("#review-more").open = false;
  const flagged = r.segments.filter((s) => s.flags && s.flags.length).length;
  const sp = r.speed;
  const how = !sp ? "transcrição importada"
    : sp.requested === "auto" ? `velocidade sugerida: ${sp.used == 4 ? "4×" : sp.used == 2 ? "2×" : "normal"}${sp.words_per_s ? ` (${sp.words_per_s.toFixed(1)} palavras/s)` : ""}`
      + (sp.unsure ? ". A detecção não é segura: confirme a velocidade abaixo" : ", confira abaixo")
    : "velocidade escolhida por você";
  $("#review-info").textContent = `${r.segments.length} trechos · ${flagged} marcados para revisão · ${how}.`
    + (sp && sp.warning ? " " + sp.warning : "")
    + (r.engine ? ` Transcrito com ${r.engine}.` : "") + musicNote(r.music);
  $("#speed-row").hidden = !r.can_retranscribe;
  const caps = lastSpec?.kind === "captures";  // revisão de capturas: o que vale são as telas, não os trechos
  $("#review-title").firstChild.textContent = caps ? "Revisar as capturas " : "Revisar a transcrição e as telas ";
  if (caps) $("#review-info").textContent = `${r.screens?.items?.length || 0} capturas lidas pelo Lumen no seu PC. Confira abaixo e desmarque o que não deve ir para a página.`;
  $("#segments").hidden = caps; $("#only-flagged").closest("label, .switch-row, div")?.toggleAttribute("hidden", caps);
  for (const i of $$("input[name=rspeed]")) i.checked = sp && String(sp.used) === i.value;
  $("#retranscribe").disabled = true;
  const box = $("#segments");
  box.classList.toggle("only-flagged", $("#only-flagged").checked);
  box.replaceChildren(...r.segments.map((s, i) => {
    const text = el("div", { class: "seg-text", contenteditable: "plaintext-only", role: "textbox", spellcheck: "true",
      "aria-label": `Trecho ${s.start != null ? mmss(s.start) : i + 1}` }, s.text);
    text.addEventListener("input", () => {
      edits[i] = text.textContent;
      row.classList.toggle("edited", text.textContent.trim() !== s.text);
    });
    const alt = s.alt ? el("div", { class: "alt" }, el("span", { class: "muted" }, "Outro modelo ouviu: "), el("q", {}, s.alt),
      el("button", { class: "btn ghost sm", type: "button", onclick: () => { text.textContent = s.alt; text.dispatchEvent(new Event("input")); } }, "Usar esta")) : null;
    const body = el("div", {}, text, s.flags && s.flags.length ? el("div", { class: "chips" }, ...s.flags.map((f) => el("span", { class: "chip" }, f))) : null, alt);
    const row = el("div", { class: "seg-row" + (s.flags && s.flags.length ? " flagged" : ""), role: "listitem" },
      el("span", { class: "seg-time" }, s.start != null ? mmss(s.start) : "—"), body);
    return row;
  }));
}
$("#only-flagged").addEventListener("change", (e) => $("#segments").classList.toggle("only-flagged", e.target.checked));
$("#review-speed").addEventListener("change", (e) => { $("#retranscribe").disabled = !review || String(review.speed?.used) === e.target.value; });
$("#retranscribe").addEventListener("click", () => {
  const v = document.querySelector("input[name=rspeed]:checked").value;
  lastSpec = { ...lastSpec, speed: v, retranscribe: true,
    ...(lastSpec.kind !== "youtube" ? { link: $("#review-link").value.trim() } : {}) };
  start(lastSpec, "/api/start");
  lastSpec = { ...lastSpec, retranscribe: false };
});
$("#review-go").addEventListener("click", () => {
  if (!U || U.key !== review.key || !["completed", "synced_to_notion"].includes(U.state)) {  // o servidor confere de novo
    $("#review-hint").textContent = "Escreva e processe sua compreensão antes de salvar o material."; return;
  }
  const changed = Object.fromEntries(Object.entries(edits).filter(([i, t]) => t.trim() !== review.segments[i].text));
  const dest = chosenDest();
  if (!dest) { $("#review-hint").textContent = "Escolha onde salvar (ou termine de criar a página nova)."; return; }
  lastSpec = { ...lastSpec, ...dest, retranscribe: false, edits: changed, include_transcript: $("#include-transcript").checked,
               screens_off: [...shotsOff] };
  if (lastSpec.kind !== "youtube") {
    lastSpec.link = $("#review-link").value.trim();
    $("#lesson-link").value = lastSpec.link;
  }
  if (lastSpec.kind === "captures" && !S.config.keep_temp) picked.captures = [];  // as imagens somem ao gerar a página
  // a gravação é apagada ao gerar a página (sem “manter arquivos temporários”): deixa de ser a fonte escolhida, e
  // “Nova aula” volta para gravar em vez de conferir um arquivo que não existe mais (“Arquivo não encontrado”)
  if (lastSpec.kind === "recording" && !S.config.keep_temp) picked.recording = null;
  start(lastSpec, "/api/finish");
});
$("#review-cancel").addEventListener("click", async () => { if (U) await Notes.flush(U.key); backToCompose(); });

function backToCompose() {
  showView("new");
  showStep("compose"); $("#redo").hidden = true;
  dockDest(null);
  refresh().catch(() => {});
  found = null; renderSource(); renderCaps();
  if (currentSpec()) inspect();
  else if (kind === "recording" && recorder.dataset.state === "done") {  // a gravação já virou aula
    setRecState("idle", "Iniciar gravação"); $("#rec-time").textContent = "00:00"; $("#rec-hint").textContent = "";
  }
  loadCourses();
}

async function poll() {
  if (polling) return;
  polling = true; updateGo();
  try {
    for (;;) {
      const j = await api("/api/job");
      renderJob(j);  // guarda lastJob
      renderStatus(); renderHero();
      if (j.status !== "running") {
        if (j.kind === "download") await refresh();
        break;
      }
      await new Promise((r) => setTimeout(r, 800));
    }
  } catch (e) { fail(e); } finally { polling = false; updateGo(); }
}

// ---------- Ajustes e Integrações (páginas; antes um diálogo) ----------
let settingsCat = "general";
const editingSettings = () => view === "settings" || view === "integrations";
function goSettings(cat = settingsCat) {
  settingsCat = cat;
  for (const b of $$("#settings-nav [data-cat]")) b.setAttribute("aria-current", String(b.dataset.cat === cat));
  for (const p of $$(".set-panel")) p.hidden = p.dataset.cat !== cat;
  showView("settings");
}
const goIntegrations = () => showView("integrations");
function openSettings() { goSettings(); }  // a bandeja e a barra chamam “Ajustes”
for (const b of $$("#settings-nav [data-cat]")) b.addEventListener("click", () => goSettings(b.dataset.cat));
// Saindo dos Ajustes/Integrações: o que mudou vale para a aula (o que o fechamento do diálogo fazia)
async function afterSettings() { await refresh().catch(fail); await loadCourses(); if (found) inspect(); }

function renderSettings() {
  if (!S) return;
  $("#token").placeholder = S.has_token ? "•••••••• (salvo no cofre do Windows)" : "ntn_…";
  $("#token-status").textContent = S.has_token ? "Conectado. O token fica no Gerenciador de Credenciais do Windows." : "Cole o token da integração interna do Notion.";
  const nb = $("#notion-badge"), ob = $("#obsidian-badge"), o = S.obsidian || {};
  const badge = (b, tone, ic, text) => { b.dataset.tone = tone; b.replaceChildren(icon(ic), text); };
  if (!usesNotion()) badge(nb, "", "minus", "Fora dos destinos");
  else if (!S.has_token) badge(nb, "warn", "alert", "Não conectado");
  else if (!rootReady()) badge(nb, "warn", "alert", "Escolha a página raiz");
  else badge(nb, "ok", "check", "Conectado");
  if (!usesObsidian()) badge(ob, "", "minus", "Fora dos destinos");
  else if (o.error) badge(ob, "error", "x-circle", "Cofre indisponível");
  else if (!S.config.obsidian_vault) badge(ob, "warn", "alert", "Escolha o cofre");
  else badge(ob, "ok", "check", "Conectado");
  $("#integ-notion").dataset.off = String(!usesNotion());
  $("#integ-obsidian").dataset.off = String(!usesObsidian());
  $("#forget").hidden = !S.has_token;
  if (!$("#root").options.length) {
    $("#root").replaceChildren(el("option", { value: S.config.root_page_id }, S.config.root_page_title || (S.has_token ? "Carregando…" : "Conecte o Notion primeiro")));
  }
  $("#hw").textContent = S.gpu ? "GPU NVIDIA com CUDA detectada: transcrição acelerada." : "Sem GPU compatível: a transcrição usa o processador (mais lenta).";
  const q = S.whisper.active;  // já normalizado pelo servidor (valores antigos viram "equilibrado")
  const opts = Object.entries(S.whisper.models).map(([k, m]) => [k, m.label, `${m.name} · ${m.size}`]);
  $("#quality").replaceChildren(...opts.map(([v, l, s]) => el("label", {},
    Object.assign(el("input", { type: "radio", name: "quality", value: v }), { checked: v === q }), l, el("small", {}, s))));
  const w = S.whisper.models[S.whisper.active];
  $("#whisper-status").textContent = w.downloaded ? `Modelo ${w.label} (${w.name}) instalado.` : `O modelo ${w.label} (${w.name}, ${w.size}) ainda não foi baixado. Ele fica salvo no PC e só é baixado uma vez.`;
  $("#whisper-dl").hidden = w.downloaded;
  setLabel($("#whisper-dl"), `Baixar modelo ${w.label} (${w.size})`, "download");
  $("#model").value = S.config.ollama_model;
  $("#model-list").replaceChildren(...S.ollama.models.map((m) => el("option", { value: m })));
  $("#ollama-status").textContent = !S.ollama.running ? "Ollama não encontrado. Instale em ollama.com (gratuito) e abra o aplicativo."
    : S.ollama.installed ? `Pronto. Modelos instalados: ${S.ollama.models.join(", ")}.`
    : `“${S.config.ollama_model}” não está instalado.`;
  $("#ollama-dl").hidden = !S.ollama.running || S.ollama.installed;
  setLabel($("#ollama-dl"), `Baixar ${S.config.ollama_model}` + (S.config.ollama_model === "qwen3:8b" ? " (≈ 5,2 GB)" : ""), "download");
  $("#keep").checked = S.config.keep_temp;
  $("#widget-position").value = S.config.widget;
  $("#autostart").checked = S.config.autostart;
  for (const id of ["#widget-position", "#widget-reset", "#autostart", "#desktop-exit"]) $(id).disabled = !host;
  $("#widget-reset").disabled = !host || S.config.widget === "off";
  $("#desktop-hint").textContent = host ? "Ao fechar a janela, o Lumen continua na barra flutuante e na bandeja do Windows." : "Disponível na janela do Lumen.exe.";
  $("#covers-status").textContent = S.covers.ready
    ? `${S.covers.label} instalado: as capas são ilustrações criadas no seu PC (≈ 30 s cada).`
    : `Sem o gerador, as capas são desenhadas com emojis. ${S.covers.label} (Apache 2.0) ocupa ${S.covers.size}; prefira um SSD.`;
  $("#covers-dl").hidden = S.covers.ready;
  setLabel($("#covers-dl"), `Baixar ${S.covers.label} (${S.covers.size})`, "download");
  $("#lang").value = $("#lang").dataset.touched ? $("#lang").value : S.config.page_language;
  renderWatch();
  const mu = S.music;
  $("#music-set").checked = S.config.music_filter;
  $("#music-mode").hidden = !S.config.music_filter;
  for (const r of $("#music-mode").querySelectorAll("input")) r.checked = r.value === S.config.music_mode;
  $("#music-status").textContent = !S.config.music_filter ? "Desligado: a transcrição usa o áudio como ele é."
    : !mu.ready ? `Falta baixar o filtro (${mu.size}). Sem ele, a transcrição segue sem filtrar.`
    : "Ativo. Na gravação, o som de apps de música (Spotify, Deezer…) fica de fora. Música que ainda chegar é detectada e separada da fala no seu PC antes da transcrição. O vídeo e o arquivo originais não são alterados.";
  $("#music-dl").hidden = !S.config.music_filter || mu.ready;
  setLabel($("#music-dl"), `Baixar filtro de música (${mu.size})`, "download");
  renderDestSettings();
}

function renderDestSettings() {  // Destinos do material: o cofre só é escolhido pelo usuário (nunca em silêncio)
  const c = S.config, o = S.obsidian || { vaults: [] };
  for (const r of $("#dest-mode").querySelectorAll("input")) r.checked = r.value === c.destinations;
  for (const r of $("#study-level").querySelectorAll("input")) r.checked = r.value === c.study_level;
  const opts = [el("option", { value: "" }, o.vaults.length ? "Escolha o cofre…" : "Nenhum cofre do Obsidian encontrado neste PC")];
  for (const v of o.vaults) opts.push(el("option", { value: v.path, ...(v.ok ? {} : { disabled: "" }) },`${v.name}${v.open ? " · aberto no Obsidian" : ""}${v.ok ? "" : " · pasta não encontrada"}`));
  if (c.obsidian_vault && !o.vaults.some((v) => v.path === c.obsidian_vault)) opts.push(el("option", { value: c.obsidian_vault }, c.obsidian_vault));
  $("#vault").replaceChildren(...opts);
  $("#vault").value = c.obsidian_vault;
  const sug = o.vaults.find((v) => v.path === c.obsidian_vault)?.folder || o.folder;
  if (document.activeElement !== $("#vault-folder")) $("#vault-folder").value = c.obsidian_folder;
  $("#vault-folder").placeholder = sug || "Escolha o cofre primeiro";
  if (document.activeElement !== $("#canvas-folder")) $("#canvas-folder").value = c.obsidian_canvas_folder;
  if (document.activeElement !== $("#review-intervals")) $("#review-intervals").value = (c.review_intervals || []).join(", ");
  $("#obs-canvas").checked = c.obsidian_canvas; $("#obs-connections").checked = c.obsidian_connections;
  $("#obs-review").checked = c.obsidian_review; $("#obs-attachments").checked = c.obsidian_attachments;
  $("#obs-open").checked = c.obsidian_open;
  $("#review-intervals").disabled = !c.obsidian_review;
  $("#vault-status").textContent = o.error || (!c.obsidian_vault ? (o.vaults.length > 1
    ? "Há mais de um cofre neste PC: escolha qual o Lumen deve usar." : "Escolha o cofre para ligar o Obsidian.")
    : `As notas ficam em “${o.folder}”, como material da IA para revisar (type: ai-study); nada fora dessa pasta é alterado.`);
  $("#vault-dashboard").hidden = !c.obsidian_vault || !!o.error;
}

function renderWatch() {  // “Assistir a tela junto”: chave no cartão da fonte e nos Ajustes
  if (!S) return;
  const on = S.config.watch_screen, v = S.vision, missing = S.ollama.running && !v.installed;
  $("#watch").checked = $("#watch-set").checked = on;
  $("#watch-row").hidden = kind === "captures" || (kind === "youtube" && !picked.ytcopy);
  $("#watch-status").textContent = !on ? ""
    : !S.ollama.running ? "Abra o Ollama para a IA ler a tela."
    : missing ? `Falta o modelo de visão (${v.model}, ${v.size}). Ele é baixado uma vez e fica no PC.`
    : kind === "recording" ? "A tela é capturada enquanto você grava e lida nos intervalos. Só ficam as telas com conteúdo da aula."
    : "O vídeo do arquivo é lido depois da transcrição.";
  $("#vision-dl").hidden = !on || !missing;
  $("#vision-status").textContent = !S.ollama.running ? "Precisa do Ollama aberto."
    : v.installed ? `Modelo de visão ${v.model} instalado (Apache 2.0).` : `O modelo de visão ${v.model} (${v.size}, Apache 2.0) ainda não foi baixado.`;
  $("#vision-dl-set").hidden = !missing;
  for (const b of [$("#vision-dl"), $("#vision-dl-set")]) setLabel(b, `Baixar modelo de visão (${v.size})`, "download");
}

async function saveSettings(body, msg) {
  try { S = await api("/api/settings", body); desktopPrefs(); renderSettings(); renderChecks(); if (msg) toast(msg); return true; }
  catch (e) { renderSettings(); fail(e); return false; }
}
$("#widget-position").addEventListener("change", (e) => saveSettings({ widget: e.target.value }));
$("#autostart").addEventListener("change", (e) => saveSettings({ autostart: e.target.checked }, "Inicialização atualizada."));
$("#widget-reset").addEventListener("click", () => host?.postMessage("widget:reset"));
$("#desktop-exit").addEventListener("click", async () => {
  try {
    const d = await api("/api/widget");
    host?.postMessage("desktop:exit-state:" + !!(d.recording.active || d.job.status === "running"));
  } catch (e) { fail(e); }
});
$("#token-save").addEventListener("click", async () => {
  const v = $("#token").value.trim();
  if (!v) return $("#token").focus();
  $("#token-status").textContent = "Validando com o Notion…";
  if (await saveSettings({ notion_token: v }, "Notion conectado.")) { $("#token").value = ""; loadRoots(); }
  else $("#token-status").textContent = "Não foi possível validar o token.";
});
async function loadRoots() {
  const sel = $("#root");
  try {
    const { pages } = await api("/api/notion/pages");
    const opt = (p) => el("option", { value: p.id, "data-title": p.title }, p.path);
    const top = pages.filter((p) => p.top);
    const opts = [el("option", { value: "" }, pages.length ? "Escolha uma página…" : "Nenhuma página compartilhada com a integração")];
    if (top.length) opts.push(el("optgroup", { label: "Páginas raiz do Notion" }, ...top.map(opt)),
                              el("optgroup", { label: "Subpáginas" }, ...pages.filter((p) => !p.top).map(opt)));
    else opts.push(...pages.map(opt));
    sel.replaceChildren(...opts);
    sel.value = S.config.root_page_id && pages.some((p) => p.id === S.config.root_page_id) ? S.config.root_page_id : "";
  } catch (e) { fail(e); }
}
$("#root-load").addEventListener("click", loadRoots);
$("#root").addEventListener("change", (e) => {
  const o = e.target.selectedOptions[0];
  if (o.value) saveSettings({ root_page: o.value, root_page_title: o.dataset.title || o.textContent },
                           `Cursos serão criados dentro de “${o.dataset.title || o.textContent}”.`).then((ok) => ok && loadCourses());
});
$("#quality").addEventListener("change", (e) => saveSettings({ quality: e.target.value }));
$("#model-save").addEventListener("click", () => saveSettings({ ollama_model: $("#model").value }, "Modelo atualizado."));
$("#keep").addEventListener("change", (e) => saveSettings({ keep_temp: e.target.checked }));
for (const id of ["#watch", "#watch-set"])
  $(id).addEventListener("change", (e) => saveSettings({ watch_screen: e.target.checked },
    e.target.checked ? "O Lumen vai assistir a tela junto." : "Leitura da tela desligada.").then(updateGo));
for (const id of ["#vision-dl", "#vision-dl-set"]) $(id).addEventListener("click", () => download({ what: "vision" }));
$("#lang").addEventListener("change", (e) => { e.target.dataset.touched = "1"; });
$("#whisper-dl").addEventListener("click", () => download({ what: "whisper", quality: S.whisper.active }));
$("#ollama-dl").addEventListener("click", () => download({ what: "ollama" }));
$("#covers-dl").addEventListener("click", () => download({ what: "covers" }));
$("#music-set").addEventListener("change", (e) => saveSettings({ music_filter: e.target.checked },
  e.target.checked ? "Filtro de música ativo." : "Filtro de música desligado."));
$("#music-mode").addEventListener("change", (e) => saveSettings({ music_mode: e.target.value }));
$("#music-dl").addEventListener("click", () => download({ what: "music" }));
$("#dest-mode").addEventListener("change", (e) => saveSettings({ destinations: e.target.value },
  { both: "O material vai para o Notion e o Obsidian.", notion: "O material vai só para o Notion.", obsidian: "O material vai só para o Obsidian." }[e.target.value])
  .then(() => { renderChecks(); loadCourses(); }));
$("#study-level").addEventListener("change", (e) => saveSettings({ study_level: e.target.value }));
$("#vault").addEventListener("change", (e) => saveSettings({ obsidian_vault: e.target.value }, e.target.value ? "Cofre do Obsidian escolhido." : ""));
$("#vault-pick").addEventListener("click", async () => {
  try {
    const { path } = await api("/api/pick", { kind: "vault" });
    if (path) await saveSettings({ obsidian_vault: path }, "Cofre do Obsidian escolhido.");
  } catch (e) { fail(e); }
});
for (const [id, key] of [["#vault-folder", "obsidian_folder"], ["#canvas-folder", "obsidian_canvas_folder"], ["#review-intervals", "review_intervals"]])
  $(id).addEventListener("change", (e) => saveSettings({ [key]: e.target.value.trim() }, "Ajuste salvo."));
for (const [id, key] of [["#obs-canvas", "obsidian_canvas"], ["#obs-connections", "obsidian_connections"], ["#obs-review", "obsidian_review"],
                         ["#obs-attachments", "obsidian_attachments"], ["#obs-open", "obsidian_open"]])
  $(id).addEventListener("change", (e) => saveSettings({ [key]: e.target.checked }));
$("#vault-dashboard").addEventListener("click", () => openObsidian("", "dashboard"));
async function download(body) {
  try { await api("/api/download", body); poll(); } catch (e) { fail(e); }
}
function renderDownload(j) {
  const target = (j.detail || "").includes("capas") ? $("#covers-status")
    : (j.detail || "").includes("filtro de música") ? $("#music-status")
    : S && (j.detail || "").includes(S.vision.model) ? $("#vision-status")
    : $("#ollama-dl").hidden ? $("#whisper-status") : $("#ollama-status");
  if (target.id === "vision-status" && j.status === "running") $("#watch-status").textContent = j.detail + (j.progress ? ` ${Math.round(j.progress * 100)}%` : "");
  if (j.status === "running") target.textContent = j.detail + (j.progress ? ` ${Math.round(j.progress * 100)}%` : "");
  else if (j.status === "done") toast("Download concluído.");
  else if (j.status === "error") fail(Object.assign(new Error(j.error.message), { action: j.error.action }));
  for (const b of [$("#whisper-dl"), $("#ollama-dl"), $("#covers-dl"), $("#vision-dl"), $("#vision-dl-set"), $("#music-dl")]) b.disabled = j.status === "running";
}
$("#clear").addEventListener("click", async () => {
  if (!await ui.confirm("Apaga o histórico de aulas, as transcrições guardadas, as suas notas de compreensão deste PC (inclusive as que ainda não foram salvas) e os arquivos temporários. As páginas no Notion e as notas no Obsidian ficam.",
    { title: "Limpar os dados locais?", ok: "Apagar dados locais", danger: true })) return;
  try { S = await api("/api/clear", {}); await loadHistory().catch(() => {}); renderPending(); renderHome(); toast("Dados locais apagados."); } catch (e) { fail(e); }
});
$("#forget").addEventListener("click", async () => {
  if (!await ui.confirm("O token sai do cofre do Windows e o histórico local (com as notas de compreensão guardadas neste PC) é apagado. As páginas no Notion ficam.",
    { title: "Desconectar o Notion?", ok: "Desconectar", danger: true })) return;
  try { localStorage.removeItem("lumen.pages"); } catch {}
  try { S = await api("/api/clear", { forget_token: true }); $("#root").replaceChildren(); renderSettings(); renderChecks(); renderPending(); await loadHistory().catch(() => {}); toast("Notion desconectado."); } catch (e) { fail(e); }
});

// ---------- janela (botões estilo Mac quando aberto pelo Lumen.exe) ----------
const host = window.chrome && window.chrome.webview;
function desktopPrefs() { if (host && S) host.postMessage("desktop:prefs:" + S.config.widget); }
if (host) host.addEventListener("message", async (e) => {
  const msg = e.data;
  if (msg === "desktop:settings") { if (S) openSettings(); }
  else if (msg === "desktop:preferences-updated") {
    const root = S?.config.root_page_id, connected = S?.has_token;
    await refresh().catch(fail);
    if (root !== S?.config.root_page_id || connected !== S?.has_token) {
      $("#root").replaceChildren(); renderSettings();
      if (view === "integrations" && S.has_token) await loadRoots();
      await loadCourses();
    }
    if (view === "library") await loadLibrary();
  }
  else if (msg === "record:started") {
    picked.recording = null; found = null;
    try { renderRec(await api("/api/record")); renderSource(); watchRec(); } catch (err) { fail(err); }
  } else if (typeof msg === "string" && msg.startsWith("record:ready:")) {
    clearInterval(recTimer);
    const data = JSON.parse(msg.slice("record:ready:".length));
    await useRecording(data.file, data.seconds).catch(fail);
  }
});
if (host && new URLSearchParams(location.search).has("frame")) {
  $("#lights").hidden = false;
  for (const b of $$("[data-window]")) b.addEventListener("click", () => host.postMessage("window:" + b.dataset.window));
  for (const bar of $$(".topbar, .rail-top"))
    bar.addEventListener("dblclick", (e) => { if (!e.target.closest("button, .pomo")) host.postMessage("window:maximize"); });
}
window.addEventListener("blur", () => document.body.classList.add("inactive"));
window.addEventListener("focus", () => document.body.classList.remove("inactive"));

// ---------- Áreas: Início, Nova aula, Biblioteca, Integrações, Ajustes ----------
const VIEWS = ["home", "new", "library", "integrations", "settings"];
const VIEW_NAMES = { home: "Início", new: "Nova aula", library: "Biblioteca", integrations: "Integrações", settings: "Ajustes" };
function setWhere(name, sub = "") {
  $("#where-view").textContent = name;
  $("#where-sub").textContent = sub; $("#where-sub").hidden = !sub;
}
function showView(name) {
  const was = view;
  view = name;
  for (const v of VIEWS) $("#view-" + v).hidden = v !== name;
  for (const b of $$(".rail-item")) { if (b.dataset.view === name) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); }
  if (was !== name) $("#content").scrollTop = 0;
  if (name === "new") renderStepper();
  else setWhere(VIEW_NAMES[name], name === "settings" ? $(`#settings-nav [data-cat=${settingsCat}]`).textContent.trim() : "");
  if (name === "home") { renderHome(); loadHistory().then(renderHome).catch(() => {}); loadReviews(); }
  if (name === "library") loadLibrary();
  if (name === "integrations" && was !== name && S?.has_token) loadRoots();
  if (S && ["settings", "integrations"].includes(was) && !["settings", "integrations"].includes(name)) afterSettings();
}
for (const b of $$(".rail-item")) b.addEventListener("click", () => {
  if (b.dataset.view === "library") libFilter = "all";
  if (b.dataset.view === "settings") goSettings(); else showView(b.dataset.view);
});
for (const b of $$("[data-go]")) b.addEventListener("click", () => { libFilter = b.dataset.filter || "all"; showView(b.dataset.go); });

// Aulas salvas (Notion e/ou Obsidian): uma leitura só para o Início, a Biblioteca e a busca
let historyItems = null;
async function loadHistory() {
  historyItems = (await api("/api/history")).items;
  $("#lib-n-saved").textContent = historyItems.length || "";
  return historyItems;
}
const shortDate = (iso) => iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "short", year: "numeric" }) : "";
const emptyState = (ic, title, text, action) =>
  el("div", { class: "empty" }, el("span", { class: "empty-icon", "aria-hidden": "true" }, icon(ic)), el("strong", {}, title), el("p", {}, text), action || null);
function savedRow(it, compact = false) {
  const ob = it.obsidian?.status === "ok", course = it.course || it.spec?.course_title;
  const act = (ic, label, tip, attrs) => compact
    ? el(attrs.href ? "a" : "button", { class: "icon-btn sm", "aria-label": `${tip}: ${it.title}`, "data-tip": tip, ...attrs }, icon(ic))
    : el(attrs.href ? "a" : "button", { class: "btn ghost sm", "data-tip": tip, ...attrs }, icon(ic), label);
  return el("div", { class: "lib-row", role: "listitem" },
    el("span", { class: "lib-ico", "aria-hidden": "true" }, icon("page")),
    el("span", { class: "lib-text" }, el("span", { class: "lib-title" }, it.title),
      el("span", { class: "lib-meta" }, [course, shortDate(it.created || it.obsidian?.at)].filter(Boolean).join(" · "))),
    el("span", { class: "lib-actions" },
      it.url ? act("external", "Notion", "Abrir no Notion", { href: it.url, target: "_blank", rel: "noopener" }) : null,
      ob ? act("notebook", "Obsidian", "Abrir no Obsidian", { type: "button", onclick: () => openObsidian(it.key, "note") }) : null,
      ob && it.obsidian.canvas ? act("map", "Mapa", "Abrir o mapa mental", { type: "button", onclick: () => openObsidian(it.key, "canvas") }) : null,
      !ob && it.lumen_id && usesObsidian() ? el("button", { class: "btn ghost sm", type: "button", "data-tip": "Cria a nota de estudo desta aula no cofre, sem chamar a IA de novo",
        onclick: () => { showView("new"); redeliver(it.key, "obsidian"); } }, icon("plus"), compact ? "Obsidian" : "Salvar no Obsidian") : null));
}
const skeletonRows = (n) => Array.from({ length: n }, () => el("div", { class: "skeleton-row", "aria-hidden": "true" },
  el("span", { class: "skeleton" }), el("span", { class: "lib-text" }, el("span", { class: "skeleton sk-title" }), el("span", { class: "skeleton sk-meta" }))));

// ---------- Biblioteca: busca e filtro locais ----------
let libFilter = "all";
async function loadLibrary() {
  renderLibrary();
  try { await loadHistory(); renderLibrary(); } catch (e) { if (!historyItems) $("#library-list").replaceChildren(); fail(e); }
}
function renderLibrary() {
  const box = $("#library-list");
  for (const b of $$("#lib-filter button")) b.setAttribute("aria-pressed", String(b.dataset.f === libFilter));
  if (!historyItems) return swap(box, skeletonRows(4));
  const typed = $("#lib-search").value.trim(), q = fold(typed), match = (...t) => !q || t.some((x) => fold(x || "").includes(q));
  const pend = (S?.pending || []).filter((p) => match(p.title, p.label));
  const saved = historyItems.filter((it) => match(it.title, it.course, it.spec?.course_title));
  const out = [];
  if (libFilter !== "saved" && pend.length) out.push(el("p", { class: "group-h" }, "Em andamento"), ...pend.map(pendingRow));
  if (libFilter !== "pending" && saved.length) out.push(el("p", { class: "group-h" }, "Salvas"), ...saved.map((it) => savedRow(it)));
  if (out.length) return swap(box, out);
  const start = el("button", { class: "btn primary", type: "button", onclick: () => showView("new") }, icon("new"), "Nova aula");
  swap(box, [typed ? emptyState("search", `Nada com “${typed}”`, "Tente outra palavra do título ou do curso.")
    : libFilter === "pending" ? emptyState("pen", "Nenhuma aula em andamento", "As aulas que você começar e ainda não salvou ficam aqui, para continuar de onde parou.", start)
    : emptyState("library", "Nenhuma aula ainda", "Quando você salvar a primeira aula no Notion ou no Obsidian, ela aparece aqui.", start)]);
}
$("#lib-search").addEventListener("input", renderLibrary);
for (const b of $$("#lib-filter button")) b.addEventListener("click", () => { libFilter = b.dataset.f; renderLibrary(); });

// ---------- Início: o que está acontecendo, o que continuar, o que precisa de atenção ----------
const STAGE_NAMES = { prepare: "Preparando a fonte", transcribe: "Transcrevendo", screen: "Lendo as telas", analyze: "Analisando",
  generate: "Escrevendo o material", connect: "Buscando conexões", obsidian: "Salvando no Obsidian", publish: "Salvando no Notion", download: "Baixando" };
const pct = (j) => Number.isFinite(j.progress) ? ` · ${Math.round(j.progress * 100)}%` : "";
let heroMode = "";
function renderHome() {  // tudo (ao abrir o Início, ao chegar a lista de aulas); a gravação e a tarefa só mexem no cartão principal
  if (!S || view !== "home") return;
  const h = new Date().getHours();
  $("#home-greet").textContent = h < 5 || h >= 18 ? "Boa noite" : h < 12 ? "Bom dia" : "Boa tarde";
  $("#home-date").textContent = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  renderHero();
  const recent = (historyItems || []).slice(0, 4);
  $("#home-recent").hidden = !!historyItems && !recent.length;
  swap($("#recent-list"), historyItems ? recent.map((it) => savedRow(it, true)) : skeletonRows(3));
}
function renderHero() {
  if (!S || view !== "home") return;
  const box = $("#home-hero"), r = S.recording || {}, j = lastJob || S.job || {}, p = S.pending?.[0];
  const busy = j.status === "running" && j.kind !== "download";
  const n = S.pending?.length || 0, due = reviews.length;
  $("#home-lead").textContent = r.active ? "Uma gravação está em andamento."
    : busy ? "O Lumen está trabalhando numa aula; dá para continuar usando o app."
    : [n ? `${n} ${n === 1 ? "aula espera" : "aulas esperam"} por você` : "", due ? `${due} ${due === 1 ? "revisão" : "revisões"} para hoje` : ""].filter(Boolean).join(" · ") + (n || due ? "." : "")
      || "Grave ou escolha uma aula, escreva o que entendeu e deixe a IA local completar.";
  const mode = r.active && !r.error ? (r.paused ? "paused" : "rec") : busy ? "job" : p ? `pending:${p.key}:${p.state}` : historyItems && !historyItems.length ? "first" : "start";
  // a cada leitura só o que mudou (o tempo, a etapa, o progresso): os botões continuam os mesmos, sem perder foco
  if (mode === heroMode && (mode === "rec" || mode === "paused")) { box.querySelector(".hero-time").textContent = mmss(r.seconds); return; }
  if (mode === heroMode && mode === "job") {
    box.querySelector(".hero-title").textContent = j.title || U?.title || "Aula em processamento";
    box.querySelector(".badge").lastChild.textContent = j.kind === "analyze" ? "Analisando sua compreensão" : STAGE_NAMES[j.stage] || "Processando";
    box.querySelector(".hero-sub").textContent = [j.detail, Number.isFinite(j.eta_total) && etaText(j.eta_total, "Pronta")].filter(Boolean).join(" · ");
    const bar = box.querySelector(".progress"), det = !Number.isFinite(j.progress);
    bar.classList.toggle("indeterminate", det);
    bar.firstChild.style.width = det ? "" : Math.round(j.progress * 100) + "%";
    return;
  }
  heroMode = mode;
  box.dataset.mode = mode.split(":")[0];
  renderPending();
  const top = (tone, ic, text) => el("div", { class: "hero-top" }, el("span", { class: "badge", "data-tone": tone }, ic, text));
  const btn = (cls, ic, text, fn, attrs = {}) => el("button", { class: "btn " + cls, type: "button", onclick: fn, ...attrs }, icon(ic), text);
  if (mode === "rec" || mode === "paused") {
    const paused = mode === "paused";
    return box.replaceChildren(top(paused ? "warn" : "rec", paused ? icon("pause") : el("span", { class: "live-dot", "aria-hidden": "true" }), paused ? "Captura pausada" : "Gravando agora"),
      el("p", { class: "hero-time", role: "timer", "aria-label": "Tempo gravado" }, mmss(r.seconds)),
      el("p", { class: "hero-sub" }, paused ? "Nada do som nem da tela é gravado. O vídeo continua; retome quando quiser."
        : "O Lumen grava o som do PC. Dá para escrever sua compreensão na barra flutuante enquanto assiste."),
      el("div", { class: "hero-actions" },
        btn("primary", "stop", "Parar e usar", () => { showView("new"); stopRec(); }),
        btn("", paused ? "play" : "pause", paused ? "Retomar" : "Pausar", toggleRecPause, { "data-tip": paused ? "Retomar captura" : "Pausar captura", "data-kbd": Shortcuts.capture.label }),
        btn("ghost", "chevron-right", "Ver a captura", () => showView("new"))));
  }
  if (mode === "job") {
    const det = !Number.isFinite(j.progress), bar = el("div", { class: "progress" + (det ? " indeterminate" : ""), role: "progressbar", "aria-label": "Progresso" }, el("span"));
    if (!det) bar.firstChild.style.width = Math.round(j.progress * 100) + "%";
    return box.replaceChildren(top("busy", el("span", { class: "spinner", "aria-hidden": "true" }), j.kind === "analyze" ? "Analisando sua compreensão" : STAGE_NAMES[j.stage] || "Processando"),
      el("p", { class: "hero-title" }, j.title || U?.title || "Aula em processamento"),
      el("p", { class: "hero-sub" }, [j.detail, Number.isFinite(j.eta_total) && etaText(j.eta_total, "Pronta")].filter(Boolean).join(" · ")),
      el("div", { class: "hero-progress" }, bar),
      el("div", { class: "hero-actions" }, btn("primary", "chevron-right", "Ver o progresso", () => showView("new"))));
  }
  if (p) {
    const [ic, tone] = PEND_LOOK[p.state] || ["pen", ""];
    // onde a aula está no fluxo: o mesmo stepper da Nova aula, em miniatura
    const at = { studying: 0, waiting_for_understanding: 1, understanding_written: 2, processing_with_ai: 2, completed: 3 }[p.state] ?? 1;
    const steps = el("ol", { class: "stepper mini", "aria-label": "Etapas desta aula" }, ...["Fonte", "Compreensão", "Análise", "Salvar"].map((t, i) =>
      el("li", { "data-on": i < at ? "done" : i === at ? "now" : "" }, el("span", { class: "step-n" }, String(i + 1)), el("span", {}, t))));
    return box.replaceChildren(top(tone || "", icon(ic), "Continue de onde parou"),
      el("p", { class: "hero-title" }, p.title || "Aula"),
      el("p", { class: "hero-sub" }, [PENDING[p.state], p.label, day(p.updated)].filter(Boolean).join(" · ")), steps,
      el("div", { class: "hero-actions" }, btn("primary lg", "arrow-right", p.state === "completed" ? "Ver a análise" : "Continuar", () => resume(p.key)),
        btn("ghost", "new", "Nova aula", () => { showView("new"); if (step !== "compose") backToCompose(); })));
  }
  const source = (tab) => () => { showView("new"); if (step !== "compose") backToCompose(); $("#tab-" + tab).click(); };
  box.replaceChildren(top("accent", icon("sparkle"), mode === "first" ? "Primeira aula" : "Nova aula"),
    el("p", { class: "hero-title" }, "Grave ou escolha uma aula"),
    el("p", { class: "hero-sub" }, "O Lumen prepara a aula no seu PC. Você escreve o que entendeu e só depois a IA local analisa e completa."),
    mode === "first" ? el("ol", { class: "flow" },
      el("li", {}, el("strong", {}, "Assista ou escolha"), "Grave o som da aula, use um arquivo ou capturas de tela."),
      el("li", {}, el("strong", {}, "Escreva o que entendeu"), "Com suas palavras, sem ajuda da IA."),
      el("li", {}, el("strong", {}, "A IA analisa e salva"), "No Notion e no Obsidian, com mapa e revisões.")) : null,
    el("div", { class: "hero-actions" }, btn("primary lg", "record", "Gravar ao assistir", source("recording")),
      btn("", "file", "Arquivo local", source("file")), btn("", "image", "Capturas de tela", source("captures"))));
}

// Revisões do Obsidian para hoje (e as atrasadas): marcadas na nota de estudo, lidas do cofre pelo Lumen
let reviews = [];
async function loadReviews() {
  const on = usesObsidian() && S.config.obsidian_review && vaultReady();
  if (on) { try { reviews = (await api("/api/reviews")).items; } catch { reviews = []; } } else reviews = [];
  const box = $("#home-reviews");
  box.hidden = !reviews.length;
  $("#reviews-count").textContent = reviews.length === 1 ? "1 para revisar" : `${reviews.length} para revisar`;
  swap($("#review-list"), reviews.slice(0, 4).map((r) => el("div", { class: "lib-row", role: "listitem" },
    el("span", { class: "lib-ico", "data-tone": r.overdue ? "warn" : "accent", "aria-hidden": "true" }, icon("calendar")),
    el("span", { class: "lib-text" }, el("span", { class: "lib-title" }, r.title),
      el("span", { class: "lib-meta" }, `${r.overdue ? "Atrasada · era para " + new Date(r.next_review + "T12:00").toLocaleDateString("pt-BR", { day: "numeric", month: "short" }) : "Para hoje"} · revisão ${r.stage + 1}`)),
    r.key ? el("button", { class: "icon-btn sm", type: "button", "aria-label": `Revisar “${r.title}” no Obsidian`, "data-tip": "Abrir no Obsidian", onclick: () => openObsidian(r.key, "note") }, icon("external")) : null)));
  renderHero();  // o subtítulo do Início conta as revisões
}

// ---------- Status global (barra superior): pronto, gravando, pausado, processando, erro ----------
function renderStatus() {
  if (!S) return;
  const pill = $("#global-status"), r = S.recording || {}, j = lastJob || S.job || {};
  let tone = "ok", ic = "check-circle", text = "Pronto";
  if (r.error) { tone = "error"; ic = "alert"; text = "Gravação interrompida"; }
  else if (r.active) { tone = r.paused ? "paused" : "rec"; ic = r.paused ? "pause" : "dot"; text = (r.paused ? "Pausado · " : "Gravando · ") + mmss(r.seconds); }
  else if (j.status === "running") { tone = "busy"; ic = "spin"; text = (j.kind === "analyze" ? "Analisando sua compreensão" : STAGE_NAMES[j.stage] || "Processando") + pct(j); }
  else if (j.status === "error" && step === "run") { tone = "error"; ic = "alert"; text = "A tarefa falhou"; }
  else if (!$("#setup").hidden) { tone = "warn"; ic = "alert"; text = "Configuração pendente"; }
  if (pill.dataset.ic !== ic) {
    pill.dataset.ic = ic;
    $("#global-status-ico").replaceChildren(ic === "spin" ? el("span", { class: "spinner" }) : ic === "dot" ? el("span", { class: "live-dot" }) : icon(ic));
  }
  // o leitor de tela ouve só a mudança de estado (gravando, pausado, processando…), não o relógio a cada segundo
  if (pill.dataset.tone !== tone) $("#status-live").textContent = "Lumen: " + text.replace(/ · [\d:]+$/, "").replace(/ · \d+%$/, "");
  pill.dataset.tone = tone;
  $("#global-status-text").textContent = text;
  pill.setAttribute("aria-label", `Status do Lumen: ${text}`);
  pill.dataset.tip = tone === "ok" ? "Tudo pronto. Clique para ir ao Início." : tone === "warn" ? "Veja o que falta no Início" : "Ver na Nova aula";
}
$("#global-status").addEventListener("click", () => {
  const t = $("#global-status").dataset.tone;
  showView(t === "ok" || t === "warn" ? "home" : "new");
});

// ---------- Busca global (Ctrl+K): telas, ajustes, ações e aulas ----------
const pal = $("#palette"), palIn = $("#pal-input"), palList = $("#pal-list");
let palItems = [], palActive = 0;
function palCommands() {
  const out = [], add = (group, label, ic, fn, sub = "") => out.push({ group, label, ic, fn, sub });
  const toCompose = () => { showView("new"); if (step !== "compose") backToCompose(); };
  if (S?.recording?.active) {
    add("Ações", "Parar a gravação e usar", "stop", () => { showView("new"); stopRec(); });
    add("Ações", S.recording.paused ? "Retomar captura" : "Pausar captura", S.recording.paused ? "play" : "pause", toggleRecPause, Shortcuts.capture.label);
  } else add("Ações", "Iniciar gravação", "record", () => { toCompose(); $("#tab-recording").click(); startRec(); });
  add("Ações", "Escolher arquivo de aula", "file", () => { toCompose(); $("#tab-file").click(); $("[data-pick=media]").click(); });
  add("Ações", "Adicionar capturas de tela", "image", () => { toCompose(); $("#tab-captures").click(); });
  if (step === "understand" && U) add("Ações", Notes.floating(U.key) ? "Trazer a nota de volta" : "Destacar a nota numa janela flutuante", "detach", () => { showView("new"); $("#u-detach").click(); }, Notes.shortcutLabel);
  if (usesObsidian() && vaultReady()) add("Ações", "Abrir o painel de estudos no Obsidian", "external", () => openObsidian("", "dashboard"));
  for (const [v, ic] of [["home", "home"], ["new", "new"], ["library", "library"], ["integrations", "plug"]]) add("Ir para", VIEW_NAMES[v], ic, () => { libFilter = "all"; showView(v); });
  for (const b of $$("#settings-nav [data-cat]")) add("Ajustes", b.textContent.trim(), b.querySelector("use").getAttribute("href").split("#")[1], () => goSettings(b.dataset.cat));
  for (const p of S?.pending || []) add("Em andamento", p.title || "Aula", (PEND_LOOK[p.state] || ["pen"])[0], () => resume(p.key), PENDING[p.state]);
  for (const it of historyItems || []) add("Biblioteca", it.title, "page", () => (it.url ? window.open(it.url, "_blank") : openObsidian(it.key, "note")),
    it.course || it.spec?.course_title || "");
  return out;
}
function renderPalette() {
  const q = fold(palIn.value.trim());
  palItems = palCommands().filter((c) => !q || fold(`${c.label} ${c.sub} ${c.group}`).includes(q)).slice(0, 40);
  palActive = Math.min(palActive, Math.max(0, palItems.length - 1));
  const kids = [];
  let g = "";
  palItems.forEach((c, i) => {
    if (c.group !== g) { g = c.group; kids.push(el("li", { class: "pal-h", role: "presentation" }, g)); }
    const li = el("li", { role: "option", id: "pal-" + i, "aria-selected": String(i === palActive) }, icon(c.ic), el("span", {}, c.label), c.sub ? el("small", {}, c.sub) : null);
    li.addEventListener("mousedown", (e) => { e.preventDefault(); runPalette(i); });
    li.addEventListener("mousemove", () => { if (palActive !== i) { palActive = i; markPalette(); } });
    kids.push(li);
  });
  palList.replaceChildren(...(kids.length ? kids : [el("li", { class: "pal-empty", role: "presentation" }, `Nada encontrado para “${palIn.value.trim()}”.`)]));
  markPalette();
}
function markPalette() {
  palList.querySelectorAll("[role=option]").forEach((li, i) => li.setAttribute("aria-selected", String(i === palActive)));
  const cur = $("#pal-" + palActive);
  if (cur) { palIn.setAttribute("aria-activedescendant", cur.id); cur.scrollIntoView({ block: "nearest" }); } else palIn.removeAttribute("aria-activedescendant");
}
function runPalette(i) { const c = palItems[i]; if (!c) return; pal.close(); c.fn(); }
function openPalette() {
  if (pal.open) return pal.close();
  palIn.value = ""; palActive = 0; renderPalette();
  pal.showModal(); palIn.focus();
  if (!historyItems) loadHistory().then(() => pal.open && renderPalette()).catch(() => {});
}
palIn.addEventListener("input", () => { palActive = 0; renderPalette(); });
palIn.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (palItems.length) { palActive = (palActive + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) % palItems.length; markPalette(); }
  } else if (e.key === "Enter") { e.preventDefault(); runPalette(palActive); }
});
pal.addEventListener("click", (e) => { if (e.target === pal) pal.close(); });  // clique fora da caixa
$("#open-palette").addEventListener("click", openPalette);
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
});

// Avisa o servidor quando a janela fecha, para ele encerrar.
if (!host) window.addEventListener("pagehide", () => navigator.sendBeacon("/api/bye?t=" + encodeURIComponent(TOKEN)));

(async () => {
  try {
    await refresh();
    desktopPrefs();
    renderRec(S.recording);  // antes dos cursos (que falham sem o Notion): gravação, pausa e gravação a recuperar
    if (S.recording.active) watchRec();
    showView("home");
    showStep("compose");
    await loadCourses();
    const key = S.job.result?.key || S.job.spec?.key;
    if (S.job.status === "done" && (S.job.result?.review || S.job.result?.analysis)) {  // janela reaberta no meio
      lastSpec = S.job.kind === "process" ? S.job.spec : null;
      showView("new");
      await openUnderstanding(key, { resume: !lastSpec }).catch(fail);
      if (lastSpec?.course_id) renderCourses(lastSpec.course_id);
    }
    if (S.job.status === "running") {
      if (S.job.kind === "analyze") { showView("new"); await openUnderstanding(key, { resume: true }).catch(fail); }
      else {
        if (S.job.spec) lastSpec = S.job.spec;
        if (lastSpec?.course_id) renderCourses(lastSpec.course_id);
        if (S.job.kind === "process") {  // a preparação já tem a chave da aula; a publicação não
          lastUrl = S.job.key ? "/api/start" : "/api/finish";
          $("#run-h").textContent = S.job.key ? "Preparando a aula" : `Salvando o material ${destName()}`;
          showView("new");
          showStep("run");
        }
      }
      poll();
    }
    if (S.recording.recovered && !S.recording.active) showView("new");  // gravação que não terminou: oferecida na Nova aula
  } catch (e) { fail(e); }
})();
