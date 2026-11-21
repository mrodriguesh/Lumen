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
  if (!r.ok) throw Object.assign(new Error(d.error?.message || "Erro"), { action: d.error?.action || "", details: d.error?.details });
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
      !S.has_token ? "Não conectado" : rootOk === false ? "A página raiz não está mais acessível" : "Escolha a página raiz", () => goIntegrations("notion")),
      usesObsidian() && stat("obsidian", "Obsidian", vaultReady(), S.obsidian?.vaults.find((v) => v.path === S.config.obsidian_vault)?.name || "Cofre escolhido",
        S.obsidian?.error ? "Cofre indisponível" : "Escolha o cofre", () => goIntegrations("obsidian"))].filter(Boolean),
    stat("cpu", "IA local", S.ollama.running && S.ollama.installed, S.config.ollama_model,
      !S.ollama.running ? "Ollama fechado" : `Falta o modelo ${S.config.ollama_model}`, () => goSettings("ai")),
    stat("wave", "Transcrição", w.downloaded, `${w.label} · ${S.gpu ? "GPU" : "processador"}`, `Falta baixar o modelo ${w.label}`, () => goSettings("transcription"))]);
  window.Glass?.system();  // Glass: o selo “Tudo pronto” / “N pendências”, contado destas linhas
  const items = [
    ...(usesNotion() ? [["Notion conectado", S.has_token, "Conectar", () => goIntegrations("notion")],
      [rootOk === false ? "Página raiz dos cursos (a salva não está mais acessível)" : "Página raiz dos cursos", rootReady(), "Escolher", () => goIntegrations("notion")]] : []),
    ...(usesObsidian() ? [["Cofre do Obsidian", vaultReady(), "Escolher", () => goIntegrations("obsidian")]] : []),
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
  for (const t of $$(".src-tabs [role=tab]")) {
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
  window.Glass?.source(kind);  // Glass: o cartão da fonte escolhida fica marcado
  found = null; renderSource();
  if (currentSpec()) inspect();
}
for (const t of $$(".src-tabs [role=tab]")) {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", (e) => {
    const tabs = $$(".src-tabs [role=tab]"), i = tabs.indexOf(t);
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
      c ? icon(c === "ok" ? "check" : "alert") : null, t))),
    // “Guardar gravações” ligado: o WAV fica no PC, então dá para achá-lo
    ...(kind === "recording" && picked.recording?.path && S.config.keep_temp
      ? [el("button", { class: "btn sm", type: "button", "data-tip": "Abre a pasta com o arquivo selecionado",
          onclick: () => api("/api/record/reveal", { path: picked.recording.path }).catch(fail) }, icon("folder"), "Mostrar no Explorer")]
      : []));
  box.hidden = false;
  if (f.duplicate?.classification && !orgTouched) setOrg(f.duplicate.classification, false);  // reprocessar não a tira do lugar
  else renderOrg();
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
    ui.setIcon($("#rec-pause"), paused ? "play" : "pause");
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
  renderStatus(); renderUCap(); renderHero();  // a pílula da barra superior deixa de dizer “Gravando”
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
Pomodoro.mount($("#u-pomo"), { sheet: true, card: true });  // card: as peças do cartão do estilo Glass (escondidas no clássico)
Pomodoro.mount($("#set-pomo"), { panel: true });  // Ajustes → Pomodoro: as mesmas durações do painel
// o painel do Pomodoro diz o que está sendo estudado agora (só na tela; nada é guardado junto com o timer)
Pomodoro.setContext(() => S?.recording?.active ? "gravando uma aula"
  : U && (step === "understand" || step === "analysis") && view === "new" ? U.title || "" : "");
Pomodoro.watch();
$("#lesson-link").addEventListener("change", () => currentSpec() && inspect());
// ---------- Organização do estudo (lumen/catalog.py): tipo → curso → módulo → aula. Uma escolha, os dois destinos ----------
let catalogData = { courses: [], categories: [], last: null, notion: null, notionModules: {} };
let rootOk = null;
let org = { type: "inbox" }, orgTouched = false;  // a organização da próxima aula (o padrão é “organizar depois”)
let orgView = null;                                 // os destinos em palavras (POST /api/organize/preview)
const rootReady = () => !!(S?.has_token && S.config.root_page_id && rootOk !== false);
const GRANT_URL = "https://www.notion.so/profile/integrations";  // o Notion só mostra o que foi liberado à integração
for (const b of document.querySelectorAll("[data-grant]")) b.addEventListener("click", () => window.open(GRANT_URL, "_blank"));
const fold = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();  // sem acento/maiúscula
const LABELS = { course: "Cursos", free: "Conteúdo gratuito", single: "Aulas avulsas", inbox: "A organizar" };
const TYPE_LOOK = { course: ["library", "Curso"], free: ["play", "Conteúdo gratuito"], single: ["file", "Aula avulsa"],
  inbox: ["folder", "A organizar"] };
const courseOf = (id) => catalogData.courses.find((c) => c.id === id) || null;
const byOrder = (a, b) => (a.order || 999) - (b.order || 999) || a.name.localeCompare(b.name, "pt-BR", { numeric: true });
const modName = (m) => (m.order ? String(m.order).padStart(2, "0") + " - " : "") + m.name;
function withNames(c) {  // os nomes vêm do catálogo: renomear um curso vale para todas as aulas
  const out = { ...c }, course = courseOf(c.course_id);
  if (course) { out.course = course.name; out.platform = course.platform; }
  const m = course?.modules.find((x) => x.id === c.module_id);
  if (m) out.module = m.name;
  return out;
}
function crumbsOf(c) {  // os mesmos rótulos de catalog.breadcrumb
  const xs = [LABELS[c.type] || LABELS.inbox, ...(c.type === "course" ? [c.course, c.module] : [c.category])].filter(Boolean);
  if (c.lesson) xs[xs.length - 1] += ` · Aula ${String(c.lesson).padStart(2, "0")}`;
  return xs;
}
const orgClass = (c = org) => Object.fromEntries(["type", "course_id", "module_id", "lesson", "category"]
  .filter((k) => c[k] !== undefined && c[k] !== null && c[k] !== "").map((k) => [k, c[k]]));
const sameOrg = (a, b) => JSON.stringify(orgClass(a)) === JSON.stringify(orgClass(b));
function trailNodes(xs) {  // “A › B › C”: os anteriores mais apagados, o último em destaque
  return xs.flatMap((x, i) => [i ? el("span", { class: "sep", "aria-hidden": "true" }, "›") : null,
    el("span", { class: i < xs.length - 1 ? "up" : "" }, x)]).filter(Boolean);
}

async function loadCatalog(withNotion = true) {
  try { Object.assign(catalogData, await api("/api/catalog")); } catch (e) { fail(e); }
  renderOrg();
  if (withNotion && usesNotion() && S?.has_token && S.config.root_page_id) {
    try {
      const r = await api("/api/catalog?notion=1");
      catalogData.notion = r.notion || [];
      if (r.root_ok !== undefined && rootOk !== r.root_ok) { rootOk = r.root_ok; renderChecks(); renderDestRows(); }
    } catch { /* sem rede: os cursos do Lumen continuam valendo */ }
  }
}

function setOrg(c, touched = true) {
  org = orgClass(c);
  if (!org.type) org.type = "inbox";
  orgTouched = touched;
  renderOrg();
}
function suggestions() {  // nunca aplicadas sozinhas: um botão “Usar”
  const out = [...(found?.suggest || [])];
  const last = catalogData.last;
  if (last && !out.some((s) => s.why === "continuar") && Date.now() - new Date(last.at).getTime() < 12 * 3600e3 && last.type !== "inbox")
    out.unshift({ why: "continuar", classification: { ...last, lesson: last.lesson ? Math.min(999, last.lesson + 1) : undefined } });
  return out.filter((s) => !sameOrg(s.classification, org) && (s.classification.type !== "course" || courseOf(s.classification.course_id)));
}
function renderOrg() {
  const c = withNames(org), [ic, label] = TYPE_LOOK[c.type] || TYPE_LOOK.inbox, rest = crumbsOf(c).slice(1);
  $("#org-ico").replaceChildren(icon(ic));
  $("#org-ico").dataset.type = c.type;
  $("#org-type").textContent = label;
  $("#org-path").replaceChildren(...(rest.length ? trailNodes(rest) : [c.type === "inbox" ? "Organizar depois" : "Sem tema"]));
  $("#org-path").dataset.tip = crumbsOf(c).join(" › ");
  const s = suggestions()[0], box = $("#org-suggest");
  box.hidden = !s;
  if (s) {
    const why = { continuar: "Continuar em", nome: "Parece pertencer a", youtube: "Vídeo do YouTube?" }[s.why] || "Sugestão";
    box.replaceChildren(icon("sparkle", "sm"), el("span", {}, `${why} `, el("strong", {}, crumbsOf(withNames(s.classification)).slice(s.classification.type === "course" ? 1 : 0).join(" › "))),
      el("button", { class: "btn ghost sm", type: "button", onclick: () => setOrg(s.classification) }, "Usar"));
  }
  previewOrg();
  updateGo();
}
let previewSeq = 0, previewTimer = null;
function previewOrg() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const seq = ++previewSeq;
    try {
      const r = await api("/api/organize/preview", { classification: orgClass(), title: found?.title || "" });
      if (seq === previewSeq) { orgView = r; renderDestRows(); }
    } catch { if (seq === previewSeq) { orgView = null; renderDestRows(); } }
  }, 120);
}
$("#org-change").addEventListener("click", () => openOrg(org));

function setObsQuick(open) {  // configuração rápida do cofre, no próprio cartão (os mesmos ajustes de Integrações)
  if ($("#obs-quick").hidden === !open) return;
  $("#obs-quick").hidden = !open;
  $("#dest-obs-change").setAttribute("aria-expanded", String(open));
  renderDestRows();
}
// fecha com Esc ou clicando fora (do painel e da linha do Obsidian)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !e.defaultPrevented && !$("#obs-quick").hidden) { e.preventDefault(); setObsQuick(false); $("#dest-obs-change").focus(); }
});
document.addEventListener("pointerdown", (e) => {
  if (!$("#obs-quick").hidden && !e.target.closest("#obs-quick, #dest-obsidian")) setObsQuick(false);
});

// ---------- diálogo “Organizar estudo” (Nova aula e o “Organizar” de cada aula da Biblioteca) ----------
const orgDlg = $("#org-dlg");
let draft = { type: "inbox" }, orgItem = null;  // orgItem: a aula salva que está sendo reorganizada
function openOrg(start, item = null) {
  orgItem = item;
  draft = { ...orgClass(start) };
  $("#org-dlg-sub").textContent = item ? item.title : "Vale para o Notion e para o Obsidian. Dá para mudar depois, na Biblioteca.";
  $("#org-save").textContent = item ? "Mover para cá" : "Salvar";
  for (const r of $$("input[name=org_type]")) r.checked = r.value === (draft.type || "inbox");
  $("#org-lesson").value = draft.lesson || "";
  $("#org-category").value = draft.category || "";
  $("#org-cats").replaceChildren(...(catalogData.categories || []).map((c) => el("option", { value: c })));
  $("#org-decorate-row").hidden = !(usesNotion() && S?.has_token);
  $("#org-hint").textContent = "";
  closeOrgForms();
  fillCourses(); orgFields();
  orgDlg.showModal();
  (orgDlg.querySelector("input[name=org_type]:checked") || orgDlg.querySelector("input[name=org_type]")).focus();
  if (usesNotion() && S?.has_token && catalogData.notion === null) loadCatalog().then(() => orgDlg.open && fillCourses());
}
function orgFields() {
  const t = draft.type || "inbox";
  $("#org-course-fields").hidden = t !== "course";
  $("#org-cat-fields").hidden = !["free", "single"].includes(t);
  previewDraft();
}
function fillCourses() {
  const sel = $("#org-course"), mine = catalogData.courses.slice().sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
  const fromNotion = (catalogData.notion || []).filter((p) => !mine.some((c) => fold(c.name) === fold(p.title)));
  sel.replaceChildren(el("option", { value: "" }, mine.length || fromNotion.length ? "Escolha o curso…" : "Nenhum curso ainda: crie o primeiro"),
    ...mine.map((c) => el("option", { value: c.id }, c.name + (c.platform ? ` · ${c.platform}` : ""))),
    ...(fromNotion.length ? [el("optgroup", { label: "Páginas de curso no Notion" }, ...fromNotion.map((p) => el("option", { value: "notion:" + p.id }, p.title)))] : []));
  sel.value = draft.course_id && courseOf(draft.course_id) ? draft.course_id : "";
  fillModules();
}
async function fillModules() {
  const sel = $("#org-module"), c = courseOf(draft.course_id);
  $("#org-new-module").disabled = sel.disabled = !c;
  const mods = (c?.modules || []).slice().sort(byOrder);
  const extra = (catalogData.notionModules[c?.id] || []).filter((p) => !mods.some((m) => fold(m.name) === fold(p.title)));
  sel.replaceChildren(el("option", { value: "" }, c ? (mods.length ? "Sem módulo" : "Sem módulo (este curso não tem)") : "Escolha o curso antes"),
    ...mods.map((m) => el("option", { value: m.id }, modName(m))),
    ...(extra.length ? [el("optgroup", { label: "Subpáginas do curso no Notion" }, ...extra.map((p) => el("option", { value: "notion:" + p.id }, p.title)))] : []));
  sel.value = draft.module_id && mods.some((m) => m.id === draft.module_id) ? draft.module_id : "";
  if (c?.notion_page_id && usesNotion() && S?.has_token && !catalogData.notionModules[c.id]) {
    catalogData.notionModules[c.id] = [];
    try {
      const r = await api(`/api/catalog?notion=1&course_id=${encodeURIComponent(c.id)}`);
      catalogData.notionModules[c.id] = (r.notion || []).filter((p) => p.title !== "Minha compreensão");
      if (orgDlg.open && draft.course_id === c.id && catalogData.notionModules[c.id].length) fillModules();
    } catch { /* sem rede: só os módulos do Lumen */ }
  }
}
function closeOrgForms() { $("#org-course-form").hidden = $("#org-module-form").hidden = true; }
$("#org-types").addEventListener("change", (e) => { draft.type = e.target.value; orgFields(); });
$("#org-course").addEventListener("change", async (e) => {
  const v = e.target.value;
  if (v.startsWith("notion:")) {  // adota a página que já existe no Notion (nunca cria outra)
    const title = e.target.selectedOptions[0].textContent;
    try {
      const r = await api("/api/catalog/course", { name: title, notion_page_id: v.slice(7) });
      await loadCatalog(false);
      draft.course_id = r.course.id;
      toast(`Curso “${r.course.name}” adotado do Notion.`);
    } catch (err) { fail(err); draft.course_id = ""; }
    fillCourses();
  } else { draft.course_id = v; draft.module_id = ""; fillModules(); }
  previewDraft();
});
$("#org-module").addEventListener("change", async (e) => {
  const v = e.target.value;
  if (v.startsWith("notion:")) {
    try {
      const r = await api("/api/catalog/module", { course_id: draft.course_id, name: e.target.selectedOptions[0].textContent, notion_page_id: v.slice(7) });
      await loadCatalog(false);
      draft.module_id = r.module.id;
    } catch (err) { fail(err); draft.module_id = ""; }
    fillModules();
  } else draft.module_id = v;
  previewDraft();
});
$("#org-lesson").addEventListener("input", (e) => { draft.lesson = parseInt(e.target.value, 10) || ""; previewDraft(); });
$("#org-category").addEventListener("input", (e) => { draft.category = e.target.value.trim(); previewDraft(); });
// novo curso: nome e plataforma bastam; o parecido é avisado, nunca unido sozinho
function similarTo(name, list) {
  const n = fold(name.trim()).replace(/\s+/g, " ");
  if (n.length < 3) return [null, null];
  const same = list.find((x) => fold(x.name).replace(/\s+/g, " ") === n);
  const near = !same && list.find((x) => { const f = fold(x.name); return f.includes(n) || n.includes(f) || lev(f, n) <= 2; });
  return [same || null, near || null];
}
function lev(a, b) {  // distância de edição (nomes curtos)
  const d = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = d[0]; d[0] = i;
    for (let j = 1; j <= b.length; j++) { const t = d[j]; d[j] = Math.min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1)); prev = t; }
  }
  return d[b.length];
}
function similarHint(input, hint, list, pick) {
  const [same, near] = similarTo(input.value, list), x = same || near;
  hint.hidden = !x;
  if (x) hint.replaceChildren(same ? `Já existe “${x.name}”.` : `Parecido com “${x.name}”.`, " ",
    el("button", { class: "link-btn", type: "button", onclick: () => pick(x) }, `Usar “${x.name}”`));
  return same;
}
$("#org-new-course").addEventListener("click", () => {
  $("#org-course-form").hidden = false; $("#org-module-form").hidden = true;
  $("#org-course-name").value = ""; $("#org-course-platform").value = ""; $("#org-course-similar").hidden = true;
  $("#org-decorate").checked = false; coverReset();
  $("#org-course-name").focus();
});
$("#org-course-cancel").addEventListener("click", () => { $("#org-course-form").hidden = true; $("#org-new-course").focus(); });
const pickCourse = (c) => { draft.course_id = c.id; draft.module_id = ""; $("#org-course-form").hidden = true; fillCourses(); previewDraft(); };
$("#org-course-name").addEventListener("input", () => {
  similarHint($("#org-course-name"), $("#org-course-similar"), catalogData.courses, pickCourse);
  renderCover();  // o nome mudou: a prévia anterior fica marcada como de outro nome (nunca gera sozinho)
});

// ---------- Capa no Notion (novo curso): prévia feita no PC, “Gerar outra”, e a mesma imagem ao criar ----------
// A prévia não toca no Notion; “Criar curso” envia o preview_id e o servidor usa exatamente aquela imagem
// (recusa se ela expirou ou foi feita para outro nome). Uma prévia por vez: o gerador ocupa a GPU.
let cover = null, coverErr = null, coverBusy = false, coverSeq = 0, coverVariant = 0, creating = false;
const COVER_KIND = { ia: "Ilustração com IA local", emojis: "Capa alternativa com emojis", notion: "Capa de cor do Notion" };
const COVER_KIND_LC = { ia: "ilustração com IA local", emojis: "capa alternativa com emojis", notion: "capa de cor do Notion" };
const coverName = () => $("#org-course-name").value.trim();
const coverStale = () => !!cover && fold(cover.name) !== fold(coverName());
function coverReset() {  // formulário novo: nenhuma prévia herdada de outro curso
  cover = null; coverErr = null; coverSeq++; coverVariant = 0;
  $("#org-cover-pic").hidden = true; $("#org-cover-pic").removeAttribute("src"); $("#org-cover-emoji").hidden = true;
  $("#org-cover-sub").textContent = "";
  renderCover();
}
function renderCover() {
  const on = $("#org-decorate").checked, name = coverName(), st = $("#org-cover-state");
  $("#org-cover").hidden = !on;
  $("#org-decorate").setAttribute("aria-expanded", String(on));
  $("#org-cover-title").textContent = name || "Nome do curso";
  $("#org-cover-where").textContent = `Página nova em “${S?.config.root_page_title || "página raiz"}”`;
  const stale = coverStale();
  $("#org-cover-wait").hidden = !!cover?.image && !coverBusy;
  $("#org-cover-wait").textContent = coverBusy ? "Gerando a capa no seu PC…" : cover ? "Sem imagem: a página vai usar uma capa de cor do Notion." : "A prévia aparece aqui.";
  $("#org-cover-fig").dataset.stale = String(stale || coverBusy);
  $("#org-cover-img").dataset.empty = String(!cover?.image);
  const gen = $("#org-cover-gen");
  setLabel(gen, coverBusy ? "Gerando…" : cover ? "Gerar outra" : "Gerar prévia", cover && !coverBusy ? "refresh" : "sparkle");
  gen.disabled = coverBusy || !name || creating;
  gen.classList.toggle("primary", on && !cover && !coverBusy && !!name);  // a próxima ação; depois, Criar curso
  const line = (tone, ic, text) => { st.dataset.tone = tone; swap(st, [ic === "spin" ? el("span", { class: "spinner", "aria-hidden": "true" }) : icon(ic), el("span", {}, text)]); };
  if (!name) line("", "info", "Digite o nome do curso para gerar a capa.");
  else if (coverBusy) line("busy", "spin", "Gerando a capa no seu PC. A IA local escolhe o ícone e as cores, e o gerador desenha a imagem; o Lumen continua livre enquanto isso.");
  else if (coverErr) line("error", "x-circle", `${coverErr.gen ? "Não foi possível gerar a capa: " : ""}${coverErr.message} ${coverErr.action || ""}`.trim() + (cover ? " A prévia anterior continua valendo." : ""));
  else if (stale) line("warn", "alert", `O nome mudou depois da prévia. Gere de novo para usar uma capa feita para “${name}”.`);
  else if (cover) line(cover.kind === "ia" ? "ok" : "warn", cover.kind === "ia" ? "check-circle" : "alert",
    `${COVER_KIND[cover.kind]}${cover.seconds ? `, gerada em ${cover.seconds} s neste PC` : ""}. ${cover.note ? cover.note + " " : ""}É esta imagem que vai para o Notion ao criar o curso.`);
  else line("", "info", S?.covers?.ready ? "Gere a prévia para ver a capa antes de criar a página."
    : "Gere a prévia para ver a capa antes de criar a página. Sem o gerador de IA instalado, a capa é desenhada com emojis.");
  const ok = !on || (cover && !stale && !coverBusy);
  const create = $("#org-course-create");
  create.disabled = creating || !ok;
  create.textContent = creating ? (on ? "Criando com a capa…" : "Criando…") : on && ok ? "Criar curso com a capa" : "Criar curso";
  create.dataset.tip = !ok ? (stale ? "Gere a prévia de novo com o nome atual" : "Gere a prévia da capa primeiro (ou desligue a capa)") : "";
}
async function genCover() {
  const name = coverName();
  if (!name || coverBusy) return;  // clique duplo: uma geração só
  coverBusy = true; coverErr = null;
  const seq = ++coverSeq, variant = cover ? ++coverVariant : (coverVariant = 0);
  renderCover();
  try {
    const r = await api("/api/decor/preview", { title: name, variant });
    if (seq !== coverSeq) return;  // o formulário foi trocado: esta resposta não vale mais
    cover = { id: r.preview_id, name: r.title, kind: r.kind, note: r.note, seconds: r.seconds, image: !!r.image };
    const pic = $("#org-cover-pic");
    if (r.image) pic.src = r.image; else pic.removeAttribute("src");
    pic.hidden = !r.image;  // sem desenho (nem IA nem emojis): nenhuma imagem antiga fica parecendo a aprovada
    pic.alt = `Prévia da capa do curso “${r.title}”: ${COVER_KIND_LC[r.kind]}`;
    $("#org-cover-emoji").textContent = r.decor.emoji; $("#org-cover-emoji").hidden = false;
    $("#org-cover-sub").textContent = r.decor.subtitle || "";
  } catch (e) { if (seq === coverSeq) coverErr = Object.assign(e, { gen: true }); }  // a prévia anterior (se havia) continua valendo
  finally {
    coverBusy = false;  // só existe uma geração por vez, então a que terminou é a que estava rodando
    renderCover();
    if (seq === coverSeq && orgDlg.open && !$("#org-cover").hidden) (cover && !coverErr ? $("#org-course-create") : $("#org-cover-state")).focus();
  }
}
$("#org-decorate").addEventListener("change", renderCover);
$("#org-cover-gen").addEventListener("click", genCover);
async function createOrgCourse() {
  const name = $("#org-course-name").value.trim(), withCover = $("#org-decorate").checked;
  if (!name) return $("#org-course-name").focus();
  if (similarHint($("#org-course-name"), $("#org-course-similar"), catalogData.courses, pickCourse)) return;
  if (creating || (withCover && (!cover || coverStale() || coverBusy))) return renderCover();  // a capa aprovada vem antes
  creating = true; renderCover();
  try {
    const r = await api("/api/catalog/course", { name, platform: $("#org-course-platform").value.trim(), decorate: withCover,
      ...(withCover ? { preview_id: cover.id } : {}) });
    await loadCatalog(false);
    pickCourse(r.course);
    const made = r.cover && !r.cover.adopted ? ` no Notion com a ${COVER_KIND_LC[r.cover.kind]}` : "";
    toast(r.note || `Curso “${r.course.name}” criado${made}.`, r.note ? "warning" : "success");
    coverReset();
    $("#org-module").focus();
  } catch (e) {
    if (/prévia/i.test(e.message)) {  // expirou ou era de outro nome: some da tela e pede para gerar de novo
      cover = null; coverErr = e; $("#org-cover-pic").hidden = $("#org-cover-emoji").hidden = true; $("#org-cover-sub").textContent = "";
    }
    fail(e);
  } finally { creating = false; renderCover(); }
}
$("#org-course-create").addEventListener("click", createOrgCourse);
$("#org-new-module").addEventListener("click", () => {
  $("#org-module-form").hidden = false; $("#org-course-form").hidden = true;
  $("#org-module-name").value = ""; $("#org-module-order").value = "";
  $("#org-module-name").focus();
});
$("#org-module-cancel").addEventListener("click", () => { $("#org-module-form").hidden = true; $("#org-new-module").focus(); });
async function createOrgModule() {
  const name = $("#org-module-name").value.trim(), c = courseOf(draft.course_id);
  if (!name) return $("#org-module-name").focus();
  const same = c.modules.find((m) => fold(m.name) === fold(name));
  if (same) { draft.module_id = same.id; $("#org-module-form").hidden = true; fillModules(); return toast(`O módulo “${same.name}” já existe; ele foi escolhido.`); }
  const btn = $("#org-module-create");
  btn.disabled = true;
  try {
    const r = await api("/api/catalog/module", { course_id: c.id, name, order: $("#org-module-order").value || null });
    await loadCatalog(false);
    draft.module_id = r.module.id;
    $("#org-module-form").hidden = true;
    fillModules(); previewDraft();
    if (r.note) toast(r.note, "warning");
  } catch (e) { fail(e); } finally { btn.disabled = false; }
}
$("#org-module-create").addEventListener("click", createOrgModule);
for (const [input, fn] of [["#org-course-name", createOrgCourse], ["#org-course-platform", createOrgCourse], ["#org-module-name", createOrgModule], ["#org-module-order", createOrgModule]])
  $(input).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fn(); } });
let draftSeq = 0;
async function previewDraft() {
  const seq = ++draftSeq, box = $("#org-preview");
  if (draft.type === "course" && !courseOf(draft.course_id)) {
    return box.replaceChildren(el("dt", {}, "Destino"), el("dd", { class: "muted" }, "Escolha o curso (ou crie um) para ver onde a aula vai ficar."));
  }
  try {
    const r = await api("/api/organize/preview", { classification: orgClass(draft), title: orgItem?.title || found?.title || "",
                                                     key: orgItem?.key || found?.duplicate?.key || "" });
    if (seq !== draftSeq) return;
    const rows = [];
    if (usesNotion()) rows.push(el("dt", {}, icon("page", "sm"), "Notion"), el("dd", {}, r.notion_ready ? r.notion : "Escolha a página de conteúdo gratuito em Integrações → Notion."));
    if (usesObsidian()) rows.push(el("dt", {}, icon("obsidian", "sm"), "Obsidian"), el("dd", { "data-tip": r.obsidian_path || "" }, r.obsidian));
    if (orgItem && usesObsidian()) rows.push(el("dt", {}, ""), el("dd", { class: "muted" }, "A pasta da aula vai junto: nota, mapa, painel e imagens."));
    box.replaceChildren(...rows);
  } catch (e) { if (seq === draftSeq) box.replaceChildren(el("dt", {}, "Destino"), el("dd", {}, e.message)); }
}
async function saveOrg() {
  const c = orgClass(draft);
  if (c.type === "course" && !courseOf(c.course_id)) { $("#org-hint").textContent = "Escolha ou crie o curso."; return $("#org-course").focus(); }
  if (!orgItem) { setOrg(c); orgDlg.close(); return toast(`A aula será organizada em ${crumbsOf(withNames(c)).join(" › ")}.`); }
  const item = orgItem;
  if (sameOrg(c, item.classification || { type: "inbox" })) return orgDlg.close();
  $("#org-save").disabled = true;
  try {
    await api("/api/organize", { key: item.key, classification: c });
    orgDlg.close();
    toast(`Organizando “${item.title}”…`, "info");
    poll();
  } catch (e) { $("#org-hint").textContent = `${e.message} ${e.action || ""}`; } finally { $("#org-save").disabled = false; }
}
$("#org-save").addEventListener("click", saveOrg);
$("#org-cancel").addEventListener("click", () => orgDlg.close());
orgDlg.addEventListener("click", (e) => { if (e.target === orgDlg) orgDlg.close(); });  // clique fora da caixa
let audioWatch = false;
function renderAudioJob(j) {  // resumo e revisão em áudio (study/listen.py): em segundo plano, o andamento fica no status
  if (j.status === "running") { audioWatch = true; return; }
  if (!audioWatch) return;  // só o fim de uma tarefa vista rodando (não a última de uma sessão antiga)
  audioWatch = false;
  if (j.status === "error") return fail(Object.assign(new Error(j.error.message), { action: j.error.action }));
  if (j.status === "cancelled") return toast("Geração do áudio cancelada. Nenhum arquivo ficou pela metade.", "info");
  if (j.status !== "done") return;
  const a = j.result?.audio;
  toast(`Áudio pronto: “${a?.title || "áudio"}” (${a?.voice || "voz"}).`, "success");
  window.dispatchEvent(new CustomEvent("lumen-audio", { detail: a }));
  if (view === "library") loadLibrary();
}
function renderBackground(j) {  // organizar e migrar: rodam como tarefa, e a tela segue livre
  if (j.status === "running") return;
  if (j.status === "error") return fail(Object.assign(new Error(j.error.message), { action: j.error.action }));
  if (j.status !== "done") return;
  const r = j.result || {};
  if (j.kind === "migrate") {
    const m = r.migration || {};
    toast(m.moved ? `${m.moved} ${m.moved === 1 ? "aula foi" : "aulas foram"} para a área de estudos (A organizar).` : "Nada para migrar.");
    loadMigration();
  } else {
    const where = (r.classification ? crumbsOf(withNames(r.classification)) : []).join(" › ");
    const bad = [r.notion, r.obsidian].find((d) => d && d.status !== "ok");
    toast(bad ? `${bad.error} ${bad.action || ""}` : `Aula organizada${where ? " em " + where : ""}.` + (r.notion?.note ? " " + r.notion.note : r.note ? " " + r.note : ""),
      bad ? "warning" : "success");
  }
  loadCatalog(false);
  if (view === "library" || view === "home") loadLibrary();
}

// ---------- revisão ----------
function updateGo() {
  renderWatch();
  const go = $("#go");
  const rows = [];
  if (found) rows.push(["Fonte", `${found.label} — ${found.title}`]);
  rows.push(["Organização", crumbsOf(withNames(org)).join(" › ")]);
  const local = found?.has_captions || found?.resumable ? "Material escrito pela IA local (Ollama)."
    : "Transcrição (Whisper) e material (Ollama) feitos no seu PC.";
  const watching = S?.config.watch_screen && !$("#watch-row").hidden;
  rows.push(["Antes da IA", "Você escreve o que entendeu. Só depois a IA analisa a sua nota e complementa."]);
  rows.push(["No seu PC", local + (watching ? " A tela é lida por IA local." : "") + " O vídeo e o áudio não são enviados."]);
  if (usesNotion()) rows.push(["Enviado ao Notion", "A página da aula e a subpágina “Minha compreensão” (sua nota e a análise)"
    + (watching ? ", com as imagens das telas que você mantiver." : ".")]);
  if (usesObsidian()) rows.push(["No Obsidian", ["Nota de estudo com perguntas", S.config.obsidian_canvas && "mapa conceitual (Canvas)",
    S.config.obsidian_board && S.config.obsidian_attachments && "painel visual com as telas da aula (Canvas)",
    S.config.obsidian_review && "revisões", S.config.obsidian_connections && "conexões com o seu cofre"].filter(Boolean).join(", ") + `, numa pasta da aula em ${orgView?.obsidian || "Estudos"}.`]);
  $("#summary").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));

  let why = "";
  if (usesNotion() && !S?.has_token) why = "Conecte o Notion em Integrações.";
  else if (usesObsidian() && !vaultReady()) why = "Escolha o cofre do Obsidian em Integrações.";
  else if (usesNotion() && org.type !== "free" && !rootReady()) why = "Escolha a página raiz dos cursos em Integrações → Notion.";
  else if (usesNotion() && org.type === "free" && !S.config.notion_free_page_id) why = "Escolha a página de conteúdo gratuito em Integrações → Notion.";
  else if (org.type === "course" && !courseOf(org.course_id)) why = "Escolha o curso da aula (Organização → Alterar).";
  else if (!S.ollama.running) why = "Abra o Ollama para gerar o material.";
  else if (!S.ollama.installed) why = "Baixe o modelo de IA em Ajustes → IA local.";
  else if (kind === "captures" && !S.vision.installed) why = "Baixe o modelo de visão em Ajustes → Captura para ler as capturas.";
  else if (S.recording?.active) why = "Pare a gravação (Parar e usar) para continuar.";
  else if (!found) why = kind === "recording" ? "Grave a aula para continuar." : kind === "captures" ? "Adicione as capturas para continuar." : "Escolha o arquivo da aula.";
  else if (found.needs_transcript) why = "Forneça a transcrição do vídeo.";
  else if (found.needs_transcription && !found.whisper_ready) why = "Baixe o modelo de transcrição em Ajustes → Transcrição.";
  go.disabled = !!why || polling;
  $("#go-hint").textContent = why;
}

$("#go").addEventListener("click", () => {
  if (found.duplicate) {
    const choice = document.querySelector("input[name=dup]:checked").value;
    if (choice === "open") return found.duplicate.url ? window.open(found.duplicate.url, "_blank") : openObsidian(found.duplicate.key, "note");
    lastSpec = { ...currentSpec(), mode: choice };
  } else lastSpec = { ...currentSpec(), mode: "new" };
  Object.assign(lastSpec, chosenDest(), { language: $("#lang").value, speed: $("#speed").value });
  start(lastSpec);
});

// ---------- destino que acompanha a tela ----------
const destCard = $("#dest-card"), destHome = destCard.parentElement, destNext = destCard.nextElementSibling;
function dockDest(slot) {  // move o cartão “Destinos do estudo” (com tudo ligado a ele) para outra tela, ou de volta
  if (!slot) { if (destCard.parentElement !== destHome) destHome.insertBefore(destCard, destNext); return; }
  if (destCard.parentElement !== slot) slot.append(destCard);
}
const chosenDest = () => ({ classification: orgClass() });  // a mesma organização para o Notion e o Obsidian

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
  if (["study_image", "study_pdf", "study_holo"].includes(j.kind)) return;  // o chat mostra o resultado; não é uma aula
  if (j.kind === "audio") return renderAudioJob(j);
  if (j.kind === "download") return renderDownload(j);
  if (j.kind === "analyze") return renderAnalyzing(j);
  if (j.kind === "organize" || j.kind === "migrate") return renderBackground(j);
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
  const back = el("button", { class: "btn ghost", "data-tier": "2", type: "button", onclick: backToCompose }, icon("new"), "Nova aula");
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
      ...[...doneLines(r), visualPreview(r)].filter(Boolean));  // sem visualização, nada (um null aqui viraria o texto “null”)
    if (r.note) res.append(el("span", { class: "dest-line" }, icon("info"), el("span", {}, r.note)));
    window.Glass?.result(res, r);  // Glass: os mesmos fatos em cartões por destino (as linhas acima são as do Clássico)
    act.replaceChildren(...[
      nt?.status === "ok" && el("a", { class: "btn primary", "data-tier": "1", href: nt.url, target: "_blank", rel: "noopener" }, icon("external"), "Abrir no Notion"),
      nt?.status === "ok" && nt.understanding_url && el("a", { class: "btn", "data-tier": "1", href: nt.understanding_url, target: "_blank", rel: "noopener" }, icon("page", "g-only"), "Abrir minha compreensão"),
      ob?.status === "ok" && el("button", { class: "btn" + (nt ? "" : " primary"), "data-tier": "1", type: "button", onclick: () => openObsidian(r.key, "note") }, icon("obsidian"), "Abrir no Obsidian"),
      ob?.status === "ok" && ob.canvas && el("button", { class: "btn", "data-tier": "2", type: "button", onclick: () => openObsidian(r.key, "canvas") }, icon("map"), "Abrir mapa conceitual"),
      ob?.status === "ok" && ob.board && el("button", { class: "btn", "data-tier": "2", type: "button", onclick: () => openObsidian(r.key, "board") }, icon("image"), "Abrir painel visual"),
      nt && nt.status !== "ok" && el("button", { class: "btn primary", "data-tier": "retry", type: "button", onclick: () => redeliver(r.key, "notion") }, icon("refresh"), "Tentar de novo só o Notion"),
      ob && ob.status !== "ok" && el("button", { class: "btn primary", "data-tier": "retry", type: "button", onclick: () => redeliver(r.key, "obsidian", ob.conflict) },
        icon("refresh"), ob.conflict ? "Substituir mesmo assim (com backup)" : "Tentar de novo só o Obsidian"),
      lastSpec && lastUrl !== "/api/deliver" && el("button", { class: "btn ghost", "data-tier": "2", type: "button", onclick: openRedo }, icon("sparkle"), "Refazer material"),
      r.key && window.lumenVoice && el("button", { class: "btn ghost", "data-tier": "2", type: "button", onclick: () => window.lumenVoice.lessonAudio(r.key, r.title || "a aula") }, icon("volume"), "Gerar resumo em áudio"),
      r.key && window.lumenON?.enabled() && el("button", { class: "btn ghost", "data-tier": "2", type: "button", onclick: () => window.lumenON.lesson(r.key, r.title) }, icon("notebook"), "Enviar ao Open Notebook"),
      r.key && window.lumenHB?.enabled() && el("button", { class: "btn ghost", "data-tier": "2", type: "button", onclick: () => window.lumenHB.lesson(r.key, r.title) }, icon("layers"), "Enviar transcrição ao HyperbookLM"),
      back].filter(Boolean));
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
    ? obsidianParts(ob).map((p) => p[1]).join(" · ") : `${ob.error} ${ob.action || ""}`));
  return out;
}
function obsidianParts(ob) {  // [ícone, texto, é aviso]: o que o Obsidian recebeu (a linha do Clássico junta os textos; o Glass lista)
  return [["page", { created: "Nota criada", updated: "Nota atualizada (suas anotações ficaram)", unchanged: "Nota já estava em dia" }[ob.state] || "Nota salva"],
    ob.canvas ? ["map", "mapa conceitual"] : null,
    ob.board ? ["image", `painel visual (${ob.board_images} ${ob.board_images === 1 ? "imagem" : "imagens"})`]
      : ob.board_skipped === "sem-imagens" ? ["image", "painel visual: sem imagens úteis nesta aula"] : null,
    ["link", `${ob.connections} ${ob.connections === 1 ? "conexão" : "conexões"} com o cofre`],
    ["question", `${ob.questions} perguntas de revisão`],
    ob.canvas_error && ["alert", ob.canvas_error, true], ob.board_error && ["alert", ob.board_error, true]].filter(Boolean);
}
function visualPreview(r) {  // a visualização 3D que foi para os destinos (o PNG para quem pediu menos movimento)
  const v = r.visual, f = visualFacts(r);
  if (!v) return null;
  if (v.state === "off") return el("span", { class: "dest-line" }, icon("info"), "Visualização 3D desligada.");
  if (!v.file) return el("span", { class: "dest-line v3d-message", "data-ok": "false" }, icon("info"),
    el("span", {}, el("b", {}, "Visualização 3D"), `não saiu (${f.why}).`), v.state === "failed" && f.retry());
  return el("figure", { class: "v3d-preview" }, f.picture(),
    el("figcaption", {}, el("b", {}, "Visualização 3D"), el("span", {}, `${f.kind} · ${v.describe || ""}`), f.where.length ? el("span", {}, f.where.join(" · ")) : "",
      f.again && f.retry()));
}
function visualFacts(r) {  // os fatos da visualização 3D: a prévia do Clássico e o cartão do Glass dizem a mesma coisa
  const v = r.visual;
  if (!v) return null;
  const src = (kind) => `/api/visual?key=${encodeURIComponent(r.key)}${kind ? "&kind=" + kind : ""}&t=${encodeURIComponent(TOKEN)}`;
  const nt = { confirmed: "no Notion, conferida na página", unconfirmed: "no Notion, sem confirmação da página",
    mismatch: "no Notion, mas a página mostra outra imagem", "upload-failed": "o envio ao Notion falhou" }[v.notion];
  return {
    why: v.reason || (v.state === "skipped" ? "o material não tem elementos para a cena" : "o desenho falhou"),
    kind: v.kind === "gif" ? "Animação (GIF)" : v.state === "static-fallback" ? "Imagem estática (PNG): a animação passou do limite de " + (v.reason || "peso") : "Imagem estática (PNG)",
    where: [nt && nt + (v.notion_kind === "png" && v.kind === "gif" ? " (PNG de reserva)" : ""),
      v.obsidian && "no Obsidian, como anexo da aula", v.obsidian_error,
      v.obsidian_disabled && "Obsidian sem visual: anexos desligados"].filter(Boolean),
    again: v.state === "static-fallback" || !!v.obsidian_error || ["upload-failed", "unconfirmed", "mismatch"].includes(v.notion),
    retry: () => el("button", { class: "btn sm", type: "button", onclick: () =>
      start({ key: r.key, only: r.dests, mode: "replace", retry_visual: true }, "/api/deliver") }, "Tentar visualização novamente"),
    picture: () => el("picture", {}, v.kind === "gif" && el("source", { media: "(prefers-reduced-motion: reduce)", srcset: src("png") }),
      el("img", { src: src(), alt: `Visualização 3D gerada pelo Lumen: ${v.describe || ""}`, loading: "lazy", width: "320", height: "180" })),
  };
}
let lastDeliver = null;
function redeliver(key, only, force = false) {
  lastDeliver = { key, only: [only], force, ...(only === "notion" && lastSpec ? { mode: lastSpec.mode } : {}) };
  start(lastDeliver, "/api/deliver");
}
async function openObsidian(key, what, courseId) {
  try { await api("/api/open", { key, what, course_id: courseId }); toast("Abrindo no Obsidian…"); } catch (e) { fail(e); }
}

function openRedo() {
  $("#redo").hidden = false; dockDest($("#redo-dest")); $("#run-actions").replaceChildren(); $("#redo-note").focus();
}
$("#redo-cancel").addEventListener("click", () => { $("#redo").hidden = true; poll(); });  // volta aos botões do resultado
$("#redo-go").addEventListener("click", () => {
  lastSpec = { ...lastSpec, ...chosenDest(), mode: "redo", redo_note: $("#redo-note").value.trim() };
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
    fk.obsidian && el("button", { class: "btn" + (fk.url ? "" : " primary"), type: "button", onclick: () => openObsidian(U.key, "note") }, icon("obsidian"), "Abrir no Obsidian"),
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
  return el("div", { class: "lib-row", role: "listitem", "data-key": p.key },
    el("span", { class: "lib-ico", "data-tone": tone, "aria-hidden": "true" }, icon(ic)),
    el("span", { class: "lib-text" }, el("span", { class: "lib-title" }, p.title || "Aula"),
      el("span", { class: "lib-meta" }, [prepping ? "Preparando…" : PENDING[p.state], p.label, day(p.updated)].filter(Boolean).join(" · "))),
    el("button", { class: "btn sm" + (p.state === "completed" ? "" : " primary"), type: "button", onclick: () => resume(p.key) },
      p.state === "completed" ? "Ver análise" : "Continuar"));
}
// O que o cartão principal do Início mostra: a gravação, a tarefa (e de que aula) ou a primeira aula em andamento
function heroState() {
  const r = S?.recording || {}, j = lastJob || S?.job || {}, p = S?.pending?.[0];
  if (r.active && !r.error) return { mode: r.paused ? "paused" : "rec", key: null };
  if (j.status === "running" && j.kind !== "download") return { mode: "job", key: j.key || j.spec?.key || null };
  if (p) return { mode: `pending:${p.key}:${p.state}`, key: p.key };
  return { mode: historyItems && !historyItems.length ? "first" : "start", key: null };
}
function renderPending() {
  const hs = S ? heroState() : null;  // no Glass o cartão principal não mostra a aula pendente: ela fica nesta lista
  const items = S?.pending || [], shown = hs && !(window.Glass?.on() && hs.mode.startsWith("pending")) ? hs.key : null;
  const more = items.filter((p) => p.key !== shown);  // sem repetir a aula que já está no cartão principal
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
  if (org.type === "course" && !courseOf(org.course_id)) { $("#review-hint").textContent = "Escolha o curso da aula em Organização."; return; }
  lastSpec = { ...lastSpec, ...chosenDest(), retranscribe: false, edits: changed, include_transcript: $("#include-transcript").checked,
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
  if (lastJob?.status === "done" && lastJob.result?.dests) setOrg({ type: "inbox" }, false);  // aula salva: a próxima recomeça (com a sugestão de continuar)
  loadCatalog();
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
  if (cat === "diagnostics" && !lastDiagData) runDiagnostics(true);
}
// Integrações: uma aba por integração. Trocar de aba só mostra ou oculta o painel: nada é salvo, enviado ou recriado,
// e o que está sendo digitado (e as seções abertas) fica como estava.
const INTEG_TABS = $$("#integ-tabs [role=tab]");
let integTab = (() => { try { return localStorage.getItem("integTab"); } catch { return null; } })() || "notion";
function integSelect(name, focus = false) {
  const tab = INTEG_TABS.find((t) => t.id === "itab-" + name) || INTEG_TABS[0];
  integTab = tab.id.slice(5);
  for (const t of INTEG_TABS) {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
    $("#" + t.getAttribute("aria-controls")).hidden = !on;
  }
  if (focus) tab.focus();
  if (integTab === "voicestudio") window.lumenVoice?.integration($("#integ-voicestudio"));
  if (integTab === "opennotebook") window.lumenON?.load();  // testa a conexão ao abrir a aba (sem travar a tela)
  if (integTab === "hyperbooklm") window.lumenHB?.load();
  try { localStorage.setItem("integTab", integTab); } catch { /* só conveniência */ }
  if (view === "integrations") setWhere(VIEW_NAMES.integrations, tab.querySelector(".integ-tab-name").textContent);
}
INTEG_TABS.forEach((t, i) => {
  t.addEventListener("click", () => integSelect(t.id.slice(5)));
  t.addEventListener("keydown", (e) => {
    const n = INTEG_TABS.length, j = { ArrowRight: i + 1, ArrowLeft: i - 1 + n, Home: 0, End: n - 1 }[e.key];
    if (j === undefined) return;
    e.preventDefault(); integSelect(INTEG_TABS[j % n].id.slice(5), true);
  });
});
integSelect(integTab);
const goIntegrations = (tab) => { if (typeof tab === "string") integSelect(tab); showView("integrations"); };
function openSettings() { goSettings(); }  // a bandeja e a barra chamam “Ajustes”
for (const b of $$("#settings-nav [data-cat]")) b.addEventListener("click", () => goSettings(b.dataset.cat));
// Saindo dos Ajustes/Integrações: o que mudou vale para a aula (o que o fechamento do diálogo fazia)
async function afterSettings() { await refresh().catch(fail); await loadCatalog(); if (found) inspect(); }

function renderSettings() {
  if (!S) return;
  $("#token").placeholder = S.has_token ? "•••••••• (salvo no cofre do Windows)" : "ntn_…";
  $("#token-status").textContent = S.has_token ? "Conectado. O token fica no Gerenciador de Credenciais do Windows." : "Cole o token da integração interna do Notion.";
  setBadge($("#notion-badge"), notionState());
  setBadge($("#obsidian-badge"), obsidianState());
  $("#notion-off").hidden = usesNotion();  // fora dos destinos: diz isso em palavras (os ajustes continuam editáveis)
  $("#obsidian-off").hidden = usesObsidian();
  $("#notion-foot").hidden = !S.has_token;
  if (!$("#root").options.length) {
    $("#root").replaceChildren(el("option", { value: S.config.root_page_id }, S.config.root_page_title || (S.has_token ? "Carregando…" : "Conecte o Notion primeiro")));
  }
  if (!$("#free-root").options.length) {  // o nome salvo enquanto a lista do Notion carrega
    $("#free-root").replaceChildren(el("option", { value: S.config.notion_free_page_id },
      S.config.notion_free_page_title || (S.has_token ? "Escolha a página…" : "Conecte o Notion primeiro")));
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
  const gen = S.covers;
  $("#covers-state").dataset.tone = gen.ready ? "ok" : "";
  $("#covers-ico").replaceChildren(icon(gen.ready ? "check-circle" : "image"));
  $("#covers-title").textContent = gen.ready ? `Gerador instalado · ${gen.label}` : "Gerador não instalado";
  $("#covers-status").textContent = gen.ready ? "As capas são ilustrações feitas na sua GPU. Se a geração falhar, a alternativa desenhada com emojis aparece na prévia antes de aplicar."
    : `Sem ele, a capa é desenhada com emojis e cores, sem baixar nada. O ${gen.label} ocupa ${gen.size}; prefira um SSD.`;
  $("#covers-dl").hidden = gen.ready;
  swap($("#covers-tech"), [["Gerador", `${gen.label} com stable-diffusion.cpp (Vulkan), no seu PC`], ["Licença", gen.license || ""],
    ["Tamanho da capa", "1536 × 640 px (o Notion corta as bordas de cima e de baixo em janelas largas)"], ["Arquivos", `${gen.size} · ${gen.folder || ""}`],
    ["Sem o gerador", "Capa desenhada com emojis e a paleta escolhida pela IA local"],
    ["Conferência", "Depois de aplicar, o Lumen lê a página de novo e compara a imagem da capa com a prévia, byte a byte"]]
    .flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  setLabel($("#covers-dl"), `Baixar ${S.covers.label} (${S.covers.size})`, "download");
  renderCov();
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
  for (const r of $("#v3d-mode").querySelectorAll("input")) r.checked = r.value === (c.visual_3d || "animated");
  const opts = [el("option", { value: "" }, o.vaults.length ? "Escolha o cofre…" : "Nenhum cofre do Obsidian encontrado neste PC")];
  for (const v of o.vaults) opts.push(el("option", { value: v.path, ...(v.ok ? {} : { disabled: "" }) },`${v.name}${v.open ? " · aberto no Obsidian" : ""}${v.ok ? "" : " · pasta não encontrada"}`));
  if (c.obsidian_vault && !o.vaults.some((v) => v.path === c.obsidian_vault)) opts.push(el("option", { value: c.obsidian_vault }, c.obsidian_vault));
  $("#q-vault").replaceChildren(...opts.map((x) => x.cloneNode(true)));
  $("#vault").replaceChildren(...opts);
  $("#vault").value = $("#q-vault").value = c.obsidian_vault;
  const sug = o.vaults.find((v) => v.path === c.obsidian_vault)?.folder || o.folder;
  if (document.activeElement !== $("#vault-folder")) $("#vault-folder").value = c.obsidian_folder;
  $("#vault-folder").placeholder = sug || "Escolha o cofre primeiro";
  if (document.activeElement !== $("#review-intervals")) $("#review-intervals").value = (c.review_intervals || []).join(", ");
  for (const i of $$("[data-cfg]")) i.checked = c[i.dataset.cfg];  // Integrações e a configuração rápida da Nova aula
  for (const r of $("#board-density").querySelectorAll("input")) {
    r.checked = r.value === c.obsidian_board_density;
    r.disabled = !c.obsidian_board || !c.obsidian_attachments;
  }
  for (const i of $$("[data-cfg=obsidian_board]")) i.disabled = !c.obsidian_attachments;
  $("#board-hint").textContent = c.obsidian_attachments
    ? "Um segundo .canvas com as telas e os gráficos da aula, compostos para reconhecer e lembrar. Só imagens reais da aula."
    : "Precisa de “Telas e gráficos no cofre”, logo acima: o painel é feito das imagens da aula.";
  $("#review-intervals").disabled = !c.obsidian_review;
  $("#vault-status").textContent = o.error || (!c.obsidian_vault ? (o.vaults.length > 1
    ? "Há mais de um cofre neste PC: escolha qual o Lumen deve usar." : "Escolha o cofre para ligar o Obsidian.")
    : `Os estudos ficam em “${o.folder}”, uma pasta por aula, organizados por curso, tema ou “A organizar”; nada fora dessa área é alterado.`);
  $("#vault-dashboard").hidden = !c.obsidian_vault || !!o.error;
  renderDestRows();
}

// ---------- Destinos do estudo (Nova aula): o mesmo estado que Integrações mostra ----------
function setBadge(b, [tone, ic, text]) { b.dataset.tone = tone; b.replaceChildren(icon(ic), text); }
function notionState() {
  if (!usesNotion()) return ["", "minus", "Desativado"];
  if (!S.has_token) return ["warn", "alert", "Não conectado"];
  if (!rootReady()) return ["warn", "alert", "Escolha a página raiz"];
  return ["ok", "check", "Conectado"];
}
function obsidianState() {
  if (!usesObsidian()) return ["", "minus", "Desativado"];
  if (S.obsidian?.error) return ["error", "x-circle", "Cofre indisponível"];
  if (!S.config.obsidian_vault) return ["warn", "alert", "Escolha o cofre"];
  return ["ok", "check", "Conectado"];
}
const andList = (xs) => xs.length > 1 ? `${xs.slice(0, -1).join(", ")} e ${xs.at(-1)}` : xs[0];
function renderDestRows() {
  if (!S) return;
  const c = S.config, o = S.obsidian || { vaults: [] };
  const nOn = usesNotion(), nOk = nOn && S.has_token, oOn = usesObsidian(), st = obsidianState(), oOk = st[0] === "ok";
  $("#dest-card").classList.toggle("solo-obsidian", !nOn);
  // Notion: conectado mostra a página (a raiz pendente aparece no caminho “Escolha uma página”); senão, o que falta
  $("#dest-notion").dataset.off = String(!nOn);
  setBadge($("#dest-notion-badge"), nOk ? ["ok", "check", "Conectado"] : notionState());
  for (const x of $("#dest-notion").querySelectorAll(".notion-ok")) x.hidden = !nOk;
  const freeMissing = nOk && org.type === "free" && !c.notion_free_page_id;
  $("#dest-notion-msg").textContent = nOn && !nOk ? "Conecte para criar a página da aula."
    : freeMissing ? "Escolha a página de conteúdo gratuito em Integrações." : "";
  if (nOk) {
    const parts = (orgView?.notion || "").split(" › ").filter(Boolean);
    $("#dest-path").replaceChildren(...(freeMissing ? [] : trailNodes(parts.length > 3 ? ["…", ...parts.slice(-2)] : parts)));
    $("#dest-path").dataset.tip = orgView?.notion || "";
  }
  $("#dest-notion-fix").hidden = nOk && !freeMissing;
  $("#dest-notion-fix").textContent = !nOn ? "Ativar" : freeMissing ? "Escolher" : "Conectar";
  // Obsidian: cofre em destaque, pasta cortada (o caminho inteiro na dica) e só os recursos ligados de verdade
  $("#dest-obsidian").dataset.off = String(!oOn);
  setBadge($("#dest-obs-badge"), st);
  const name = o.vaults.find((v) => v.path === c.obsidian_vault)?.name || c.obsidian_vault.split(/[\\/]/).filter(Boolean).pop();
  const vault = $("#dest-vault");
  vault.dataset.tip = oOk ? `${name} › ${orgView?.obsidian_path || o.folder}` : st[0] === "error" ? o.error : "";
  vault.replaceChildren(...(!oOn ? [] : oOk ? [el("span", { class: "dest-path" }, ...trailNodes((orgView?.obsidian || "Estudos").split(" / ")))]
    : [el("span", { class: "dest-msg" }, st[0] === "error" ? "O cofre escolhido não foi encontrado." : c.obsidian_review ? "Notas, revisões e mapas mentais no seu cofre." : "Notas e mapas mentais no seu cofre.")]));
  const visual = c.obsidian_board && c.obsidian_attachments;  // o painel só existe com as imagens no cofre
  const maps = (c.obsidian_canvas ? 1 : 0) + (visual ? 1 : 0);
  $("#dest-feats").textContent = oOk ? `Nota${maps ? ` + ${maps === 1 ? "" : "2 "}Canvas` : ""} · ${name}` : "";
  $("#dest-feats").dataset.tip = oOk ? ["Nota de estudo", c.obsidian_canvas && "mapa conceitual", visual && "painel visual"].filter(Boolean).join(", ") : "";
  $("#dest-obs-help").hidden = !oOn;
  $("#dest-obs-help").dataset.tip = `No seu cofre, o Lumen cria ${andList(["uma nota de estudo com perguntas", c.obsidian_canvas && "um mapa conceitual (as ideias e as relações)",
    visual && "um painel visual (as telas e os gráficos da aula, para lembrar)",
    c.obsidian_review && "as datas de revisão", c.obsidian_connections && "links para as suas notas ligadas à aula",
    c.obsidian_attachments && "as telas escolhidas"].filter(Boolean))}.`;
  if (!oOn) $("#obs-quick").hidden = true;
  $("#dest-obs-change").textContent = !oOn ? "Ativar" : !$("#obs-quick").hidden ? "Pronto" : oOk ? "Alterar" : st[0] === "error" ? "Corrigir" : "Escolher cofre";
  $("#dest-both").hidden = !(nOn && oOn);
}
const setDestinations = (v) => saveSettings({ destinations: v },
  { both: "O material vai para o Notion e o Obsidian.", notion: "O material vai só para o Notion.", obsidian: "O material vai só para o Obsidian." }[v])
  .then(() => loadCatalog());
$("#dest-notion-fix").addEventListener("click", () => usesNotion() ? goIntegrations("notion") : setDestinations("both"));
for (const b of $$("[data-dest-both]")) b.addEventListener("click", () => setDestinations("both"));
$("#free-root").addEventListener("change", (e) => {
  const o = e.target.selectedOptions[0];
  saveSettings({ notion_free_page: o.value, notion_free_page_title: o.value ? o.dataset.title || o.textContent : "" },
    o.value ? `Conteúdo gratuito: uma página por material em “${o.dataset.title || o.textContent}”.` : "").then(renderOrg);
});
$("#dest-obs-change").addEventListener("click", () => usesObsidian() ? setObsQuick($("#obs-quick").hidden) : setDestinations("both"));
for (const b of $$("[data-go-integ]")) b.addEventListener("click", () => goIntegrations("obsidian"));

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
  if (await saveSettings({ notion_token: v }, "Notion conectado.")) {
    $("#token").value = ""; loadRoots();
    cv.list = []; cv.cursor = null; cv.searched = false; covReset();  // outra conexão: nada da página escolhida antes
  }
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
    const free = $("#free-root");
    free.replaceChildren(...opts.map((x) => x.cloneNode(true)));
    free.options[0].textContent = "Escolha a página…";
    free.value = S.config.notion_free_page_id && pages.some((p) => p.id === S.config.notion_free_page_id) ? S.config.notion_free_page_id : "";
    if (!S.config.notion_free_page_id && S.config.root_page_id) {  // a irmã “Conteúdo gratuito” da raiz, se houver uma só
      const root = pages.find((p) => p.id === S.config.root_page_id);
      const same = pages.filter((p) => fold(p.title) === "conteudo gratuito" && (!root?.parent || p.parent === root.parent));
      if (same.length === 1) {
        free.value = same[0].id;
        saveSettings({ notion_free_page: same[0].id, notion_free_page_title: same[0].path }, `Conteúdo gratuito: usando “${same[0].path}”. Dá para trocar aqui.`);
      }
    }
  } catch (e) { fail(e); }
}
$("#root-load").addEventListener("click", loadRoots);
$("#root").addEventListener("change", (e) => {
  const o = e.target.selectedOptions[0];
  if (o.value) saveSettings({ root_page: o.value, root_page_title: o.dataset.title || o.textContent },
                           `Cursos serão criados dentro de “${o.dataset.title || o.textContent}”.`).then((ok) => ok && loadCatalog());
});
$("#quality").addEventListener("change", (e) => saveSettings({ quality: e.target.value }));
$("#model-save").addEventListener("click", () => saveSettings({ ollama_model: $("#model").value }, "Modelo atualizado."));
$("#keep").addEventListener("change", (e) => saveSettings({ keep_temp: e.target.checked }).then(() => found && renderSource()));
for (const id of ["#watch", "#watch-set"])
  $(id).addEventListener("change", (e) => saveSettings({ watch_screen: e.target.checked },
    e.target.checked ? "O Lumen vai assistir a tela junto." : "Leitura da tela desligada.").then(updateGo));
for (const id of ["#vision-dl", "#vision-dl-set"]) $(id).addEventListener("click", () => download({ what: "vision" }));
$("#lang").addEventListener("change", (e) => { e.target.dataset.touched = "1"; });
$("#whisper-dl").addEventListener("click", () => download({ what: "whisper", quality: S.whisper.active }));
$("#ollama-dl").addEventListener("click", () => download({ what: "ollama" }));
$("#covers-dl").addEventListener("click", () => download({ what: "covers" }));

// ---------- Capas do Notion: escolher a página → gerar a imagem no PC → aplicar só a capa ----------
// A mesma tela em Ajustes, Integrações → Notion, Ctrl+K e no curso da Biblioteca (covOpen) e, na Nova aula, num diálogo
// (covQuick): o bloco #cov-box muda de lugar, o estado é um só. `seq` muda a cada troca de página: uma resposta atrasada
// da página anterior não mexe nesta. O texto digitado nunca é reescrito por aqui.
const cv = { page: null, pv: null, busy: "", genFor: null, err: null, res: null, seq: 0, variant: 0, why: "", target: null,
  list: [], cursor: null, active: 0, qseq: 0, qerr: null, loading: false, searched: false, timer: 0 };
const covTheme = () => $("#cov-theme").value.split(/\s+/).filter(Boolean).join(" ").slice(0, 300);
const covStale = () => !!cv.pv && covTheme() !== cv.pv.theme;
const covLink = (v) => /[0-9a-f]{32}/i.test(v.replace(/-/g, ""));  // link ou ID colado: vai direto à página
const covMeta = (p) => [p.where, p.edited && `editada em ${shortDate(p.edited)}`].filter(Boolean).join(" · ");
const covDlg = $("#cov-dlg");
const covShown = () => covDlg.open || (view === "settings" && settingsCat === "covers");
function covReset() { cv.page = cv.pv = cv.err = cv.res = null; cv.seq++; cv.variant = 0; renderCov(); }
async function covOpen(ref) {  // Ajustes → Capas do Notion
  if (covDlg.open) covDlg.close();
  goSettings("covers");
  await covStart(ref);
}
async function covStart(ref, why = "") {
  cv.why = why;
  if (!S?.has_token || cv.busy) return renderCov();  // gerando ou aplicando: mostra como está, sem trocar a página
  if (ref && ref !== cv.page?.id) await covPickRef(ref);
  else if (!cv.page && !cv.searched) covSearch();
  renderCov();
  (cv.page ? (covDlg.open ? $("#cov-gen") : $("#cov-theme")) : $("#cov-q")).focus();
}
// A página do destino da aula no Notion, só com IDs reais (catálogo e histórico; validada pela API ao abrir). O caminho
// do cartão é uma previsão: nada é deduzido dele nem do título, e nada é criado aqui.
function covTarget() {
  if (!usesNotion()) return {};
  const old = found?.duplicate || (historyItems || []).find((it) => it.key === U?.key) || {};
  if (org.type === "course") {
    const c = courseOf(org.course_id), m = c?.modules.find((x) => x.id === org.module_id);
    if (org.module_id) return m?.notion_page_id ? { id: m.notion_page_id } : { why: "O módulo escolhido ainda não tem página no Notion. Escolha uma página para a capa." };
    return c?.notion_page_id ? { id: c.notion_page_id } : { why: "O curso escolhido ainda não tem página no Notion. Escolha uma página para a capa." };
  }
  if (old.page_id && (org.type === "inbox" || (org.type === "free" && old.notion_own))) return { id: old.page_id };  // onde a aula já está
  if (org.type === "free") return { why: "A página desta aula ainda não existe. Escolha uma página para a capa." };
  return { why: "O destino desta aula ainda não tem uma página identificada. Escolha uma página para a capa." };
}
async function covQuick() {  // Nova aula → Destinos do estudo → Notion → Capa
  const t = covTarget(), key = t.id || t.why || "";
  $("#cov-dlg-body").append($("#cov-box"));
  covDlg.showModal();
  if (cv.busy || key === cv.target) { renderCov(); return covFirst(); }  // reaberto para o mesmo destino: como estava
  cv.target = key;
  if (!t.id && cv.page) covReset();
  await covStart(t.id, t.why || "");
}
function covFirst() { (cv.page ? (!$("#cov-main").hidden ? $("#cov-main") : $("#cov-gen")) : $("#cov-q")).focus(); }
covDlg.addEventListener("close", () => {
  $("#cov-home").append($("#cov-box"));  // de volta a Ajustes; o que estiver em andamento continua e aparece lá
  $("#dest-notion-cover").focus({ preventScroll: true });
});
$("#cov-close").addEventListener("click", () => covDlg.close());
$("#dest-notion-cover").addEventListener("click", covQuick);
async function covSearch(more = false) {
  clearTimeout(cv.timer);
  const text = $("#cov-q").value.trim();
  if (!more && covLink(text)) return covPickRef(text);
  const seq = ++cv.qseq;
  cv.loading = true; cv.qerr = null;
  if (!more) { cv.list = []; cv.cursor = null; cv.active = 0; }
  renderList();
  try {
    const r = await api(`/api/notion/search?q=${encodeURIComponent(text)}` + (more && cv.cursor ? `&cursor=${encodeURIComponent(cv.cursor)}` : ""));
    if (seq !== cv.qseq) return;  // já digitaram outra coisa: esta resposta não vale mais
    cv.list = more ? [...cv.list, ...r.pages] : r.pages; cv.cursor = r.next_cursor;
  } catch (e) { if (seq === cv.qseq) cv.qerr = e; }
  finally { if (seq === cv.qseq) { cv.loading = false; cv.searched = true; renderList(); } }
}
async function covPickRef(ref) {
  clearTimeout(cv.timer);
  const seq = ++cv.qseq;
  cv.loading = true; cv.qerr = null; cv.list = []; cv.cursor = null;
  renderList("Abrindo a página do link…");
  try {
    const page = await api("/api/notion/page?ref=" + encodeURIComponent(ref));
    if (seq === cv.qseq) covSelect(page);
  } catch (e) { if (seq === cv.qseq) cv.qerr = e; }
  finally { if (seq === cv.qseq) { cv.loading = false; renderList(); } }
}
function covSelect(p) {
  clearTimeout(cv.timer); cv.qseq++;  // buscas que ainda iam chegar não valem mais
  cv.loading = false; cv.page = p; cv.pv = cv.err = cv.res = null; cv.seq++; cv.variant = 0;
  renderCov();
  $("#cov-theme").focus();
}
function renderList(busyText) {
  const q = $("#cov-q"), text = q.value.trim(), box = $("#cov-results");
  const opts = cv.list.map((p, i) => el("li", { role: "option", id: "cov-opt-" + i, "aria-selected": String(i === cv.active),
    onmousedown: (e) => { e.preventDefault(); covSelect(p); }, onmousemove: () => { if (cv.active !== i) { cv.active = i; covMark(); } } },
  p.icon ? el("span", { class: "cov-emoji", "aria-hidden": "true" }, p.icon) : icon("page"),
  el("span", { class: "cov-opt" }, el("span", {}, p.title), el("small", {}, covMeta(p) + (p.cover ? " · com capa" : "")))));
  if (opts.length && !text) opts.unshift(el("li", { class: "pal-h", role: "presentation" }, "Editadas recentemente"));
  $("#cov-list").replaceChildren(...opts);
  const e = cv.qerr, msg = $("#cov-list-msg");
  msg.dataset.tone = e ? "error" : "";
  msg.replaceChildren(...(cv.loading ? [el("span", { class: "spinner", "aria-hidden": "true" }), busyText || (cv.list.length ? "Carregando mais…" : "Buscando páginas…")]
    : e ? [icon("x-circle"), `${e.message} ${e.action || ""}`.trim()]
    : cv.searched && !cv.list.length ? [text ? `Nenhuma página com “${text}”.` : "Nenhuma página compartilhada com a integração ainda."] : []));
  $("#cov-retry").hidden = !e;
  $("#cov-more").hidden = !cv.cursor || cv.loading || !!e;
  box.hidden = !cv.list.length && !msg.childNodes.length;
  q.setAttribute("aria-expanded", String(!!cv.list.length));
  covMark();
}
function covMark() {
  $$("#cov-list [role=option]").forEach((li, i) => li.setAttribute("aria-selected", String(i === cv.active)));
  const cur = $("#cov-opt-" + cv.active);
  if (cur && cv.list.length) { $("#cov-q").setAttribute("aria-activedescendant", cur.id); cur.scrollIntoView({ block: "nearest" }); }
  else $("#cov-q").removeAttribute("aria-activedescendant");
}
function covButton(btn, label, ic, primary, disabled) {
  btn.hidden = !label;
  if (!label) return;
  setLabel(btn, label, ic);
  btn.classList.toggle("primary", primary);
  btn.disabled = disabled;
}
function renderCov() {
  if (!S) return;
  if (!S.has_token && (cv.page || cv.pv)) { cv.page = cv.pv = cv.err = cv.res = null; cv.seq++; }  // desconectou
  const p = cv.page;
  $("#cov-off").hidden = S.has_token; $("#cov-flow").hidden = !S.has_token;
  $("#cov-pick").hidden = !!p;
  $("#cov-why").hidden = !cv.why; $("#cov-why-text").textContent = cv.why;
  for (const id of ["#cov-page", "#cov-theme-box", "#cov-actions"]) $(id).hidden = !p;
  if (!p) { $("#cov-area").hidden = true; swap($("#cov-state"), []); return renderList(); }
  $("#cov-page-ico").replaceChildren(p.icon || icon("page"));
  $("#cov-page-title").textContent = p.title;
  setBadge($("#cov-page-badge"), p.cover ? ["", "image", "Tem capa"] : ["", "minus", "Sem capa"]);
  $("#cov-page-where").textContent = covMeta(p);
  $("#cov-page-open").disabled = !p.url;
  $("#cov-page-change").disabled = cv.busy === "apply";
  $("#cov-theme-hint").textContent = `Sem descrição, a capa sai do título “${p.title}”.`;
  const gen = cv.busy === "gen", applying = cv.busy === "apply", stale = covStale(), r = cv.res, e = cv.err;
  $("#cov-area").hidden = !cv.pv && !gen;
  $("#cov-progress").hidden = !gen;  // sem medição real do gerador: progresso indeterminado
  $("#cov-pic").hidden = !cv.pv;
  $("#cov-img").dataset.empty = String(!cv.pv);
  $("#cov-fig").dataset.stale = String(stale || gen || !!cv.pv?.dead);
  $("#cov-wait").hidden = !!cv.pv;
  $("#cov-wait").textContent = gen ? "Gerando a capa no seu PC…" : "";
  const st = $("#cov-state"), line = (tone, ic, text) => { st.dataset.tone = tone; swap(st, text ? [ic === "spin" ? el("span", { class: "spinner", "aria-hidden": "true" }) : icon(ic), el("span", {}, text)] : []); };
  if (gen) line("busy", "spin", cv.genFor === p.id ? "Gerando a capa no seu PC. O Lumen continua livre enquanto isso." : "Terminando a prévia da página anterior…");
  else if (applying) line("busy", "spin", `Enviando a capa para “${p.title}” e conferindo no Notion…`);
  else if (r?.state === "confirmed") line("ok", "check-circle", `Capa aplicada em “${p.title}”.`);
  else if (r?.state === "unconfirmed") line("warn", "alert", "Não foi possível confirmar se a capa ficou na página. A imagem continua aqui: “Tentar de novo” confere o Notion antes de enviar.");
  else if (r?.state === "mismatch") line("error", "x-circle", "O Notion respondeu, mas a página continua com outra capa. Nada foi dado como aplicado.");
  else if (r?.state === "changed") line("warn", "alert", "A capa desta página mudou desde que você a escolheu. Confira acima; “Substituir capa” troca a capa atual.");
  else if (r?.state === "regenerate") line("warn", "alert", `${r.message} ${r.action || ""}`.trim());
  else if (e) line("error", "x-circle", `${e.gen ? "Não foi possível gerar a capa: " : ""}${e.message} ${e.action || ""}`.trim() + (e.gen && cv.pv ? " A prévia anterior continua valendo." : ""));
  else if (stale) line("warn", "alert", "O tema mudou depois da prévia. Gere de novo para usar o tema atual.");
  else if (cv.pv) line(cv.pv.kind === "ia" ? "ok" : "warn", cv.pv.kind === "ia" ? "check-circle" : "alert",
    `${COVER_KIND[cv.pv.kind]}, gerada em ${cv.pv.seconds} s neste PC. ${cv.pv.note ? cv.pv.note + " " : ""}`
    + (p.cover ? `Ela substitui a capa atual de “${p.title}”.` : `É esta imagem que vai para “${p.title}”.`));
  else line("", "info", S.covers?.ready ? "" : "Sem o gerador de IA instalado, a capa é desenhada com emojis (veja Gerador e detalhes técnicos).");
  // uma ação principal por estado
  const usable = cv.pv && !cv.pv.dead && !stale, retry = ["unconfirmed", "mismatch"].includes(r?.state) || (e && !e.gen);
  const main = r?.state === "confirmed" ? ["Abrir no Notion", "external"] : usable ? [applying ? "Aplicando…" : retry ? "Tentar de novo" : p.cover ? "Substituir capa" : "Aplicar capa", null] : [null];
  covButton($("#cov-main"), main[0], main[1], true, !!cv.busy);
  $("#cov-main").dataset.act = r?.state === "confirmed" ? "open" : "apply";
  covButton($("#cov-gen"), gen ? "Gerando…" : cv.pv && !cv.pv.dead ? "Gerar outra" : e?.gen ? "Tentar de novo" : "Gerar capa",
    cv.pv && !cv.pv.dead ? "refresh" : "sparkle", !main[0], !!cv.busy);
}
function covHold() {  // o botão em foco vai ficar desabilitado: o foco espera na linha de estado
  if ([$("#cov-gen"), $("#cov-main")].includes(document.activeElement)) $("#cov-state").focus();
}
function covFocus() {  // ao terminar, o foco vai para a próxima ação (só se a tela ainda estiver aberta)
  if (!covShown() || document.activeElement !== $("#cov-state")) return;
  (!$("#cov-main").hidden ? $("#cov-main") : $("#cov-gen")).focus();
}
async function covGen() {
  const p = cv.page;
  if (!p || cv.busy) return;  // clique duplo: uma geração só
  const seq = cv.seq, theme = covTheme(), variant = cv.pv ? ++cv.variant : (cv.variant = 0);
  covHold();
  cv.busy = "gen"; cv.genFor = p.id; cv.err = cv.res = null;
  renderCov();
  try {
    const r = await api("/api/cover/preview", { page_id: p.id, title: p.title, theme, variant });
    if (seq !== cv.seq) return;  // a página foi trocada: esta prévia não vale aqui
    cv.pv = { id: r.preview_id, kind: r.kind, note: r.note, seconds: r.seconds, theme: r.theme };
    const pic = $("#cov-pic");
    pic.src = r.image; pic.alt = `Prévia da capa para “${p.title}”: ${COVER_KIND_LC[r.kind]}`;
  } catch (e) { if (seq === cv.seq) cv.err = Object.assign(e, { gen: true }); }  // a prévia anterior (se havia) continua valendo
  finally { cv.busy = ""; renderCov(); if (seq === cv.seq) covFocus(); }
}
async function covApply() {
  const p = cv.page, pv = cv.pv;
  if (!p || !pv || pv.dead || cv.busy) return;  // clique duplo: o servidor também recusa um segundo envio
  const seq = cv.seq;
  covHold();
  cv.busy = "apply"; cv.err = null;
  renderCov();
  let r = null;
  try { r = await api("/api/cover/apply", { preview_id: pv.id, page_id: p.id, theme: covTheme(), cover: p.cover ?? null }); }
  catch (e) { if (seq === cv.seq) cv.err = e; }
  finally { cv.busy = ""; }
  if (seq !== cv.seq) {  // desconectou no meio: o resultado é da página anterior
    if (r?.state === "confirmed") toast(`Capa aplicada em “${p.title}”.`);
    return renderCov();
  }
  if (r) {
    cv.res = r.changed ? { state: "changed" } : r;
    if (r.page) cv.page = r.page;
    if (r.state === "regenerate") cv.pv = { ...pv, dead: true };
    if (r.state === "confirmed" && !covShown()) toast(`Capa aplicada em “${p.title}”.`);  // o diálogo foi fechado no meio
  }
  renderCov(); covFocus();
}
$("#cov-q").addEventListener("input", () => {
  cv.active = 0; clearTimeout(cv.timer);
  if (covLink($("#cov-q").value)) covSearch(); else cv.timer = setTimeout(covSearch, 300);
});
$("#cov-q").addEventListener("focus", () => { if (!cv.searched && !cv.loading) covSearch(); });
$("#cov-q").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (cv.list.length) { cv.active = (cv.active + (e.key === "ArrowDown" ? 1 : -1) + cv.list.length) % cv.list.length; covMark(); }
  } else if (e.key === "Enter") {
    e.preventDefault();
    const pick = cv.list[cv.active];
    if (pick && !covLink(e.target.value) && !cv.loading) covSelect(pick); else covSearch();
  } else if (e.key === "Escape" && e.target.value) { e.preventDefault(); e.target.value = ""; covSearch(); }
});
$("#cov-more").addEventListener("click", () => covSearch(true));
$("#cov-retry").addEventListener("click", () => covSearch());
$("#cov-page-change").addEventListener("click", () => { covReset(); $("#cov-q").focus(); });
$("#cov-page-open").addEventListener("click", () => cv.page?.url && window.open(cv.page.url, "_blank"));
$("#cov-theme").addEventListener("input", () => renderCov());
$("#cov-theme").addEventListener("keydown", (e) => { if (e.key === "Enter" && (!cv.pv || covStale() || cv.pv.dead)) { e.preventDefault(); covGen(); } });
$("#cov-gen").addEventListener("click", covGen);
$("#cov-main").addEventListener("click", (e) => e.currentTarget.dataset.act === "open" ? window.open(cv.page?.url, "_blank") : covApply());
$("#cov-connect").addEventListener("click", () => { if (covDlg.open) covDlg.close(); goIntegrations("notion"); });
for (const b of $$("[data-cover-open]")) b.addEventListener("click", () => covOpen());
$("#music-set").addEventListener("change", (e) => saveSettings({ music_filter: e.target.checked },
  e.target.checked ? "Filtro de música ativo." : "Filtro de música desligado."));
$("#music-mode").addEventListener("change", (e) => saveSettings({ music_mode: e.target.value }));
$("#music-dl").addEventListener("click", () => download({ what: "music" }));
$("#dest-mode").addEventListener("change", (e) => setDestinations(e.target.value));
$("#study-level").addEventListener("change", (e) => saveSettings({ study_level: e.target.value }));
$("#board-density").addEventListener("change", (e) => saveSettings({ obsidian_board_density: e.target.value }));
$("#v3d-mode").addEventListener("change", (e) => saveSettings({ visual_3d: e.target.value },
  { animated: "Visualização 3D animada nas próximas páginas.", static: "Visualização 3D estática (PNG) nas próximas páginas.",
    off: "Visualização 3D desligada nas próximas páginas." }[e.target.value]));
for (const id of ["#vault", "#q-vault"])
  $(id).addEventListener("change", (e) => saveSettings({ obsidian_vault: e.target.value }, e.target.value ? "Cofre do Obsidian escolhido." : ""));
for (const id of ["#vault-pick", "#q-vault-pick"]) $(id).addEventListener("click", async () => {
  try {
    const { path } = await api("/api/pick", { kind: "vault" });
    if (path) await saveSettings({ obsidian_vault: path }, "Cofre do Obsidian escolhido.");
  } catch (e) { fail(e); }
});
for (const [id, key] of [["#vault-folder", "obsidian_folder"], ["#review-intervals", "review_intervals"]])
  $(id).addEventListener("change", (e) => saveSettings({ [key]: e.target.value.trim() }, "Ajuste salvo."));
for (const i of $$("[data-cfg]")) i.addEventListener("change", () => saveSettings({ [i.dataset.cfg]: i.checked }));
$("#vault-dashboard").addEventListener("click", () => openObsidian("", "home"));

// Materiais da pasta antiga do Lumen (antes da área de estudos): a migração é pedida, nunca feita sozinha
async function loadMigration() {
  if (!usesObsidian() || !vaultReady()) { $("#migration").hidden = true; return; }
  try {
    const m = await api("/api/migration");
    $("#migration").hidden = !m.lessons.length;
    if (!m.lessons.length) return;
    $("#migration-text").textContent = `${m.lessons.length} ${m.lessons.length === 1 ? "aula ainda está" : "aulas ainda estão"} em “${m.folders.join("”, “")}”, a pasta de antes. Elas vão para “A organizar”, na área de estudos:`;
    $("#migration-list").replaceChildren(...m.lessons.map((l) => el("li", {}, el("strong", {}, l.title),
      el("span", { class: "muted" }, ["nota", l.canvas && "mapa", l.board && "painel", l.attachments && `${l.attachments} ${l.attachments === 1 ? "imagem" : "imagens"}`].filter(Boolean).join(" · ")))));
  } catch { $("#migration").hidden = true; }
}
$("#migration-go").addEventListener("click", async () => {
  if (!await ui.confirm("As aulas da pasta antiga vão para “A organizar”, na área de estudos, cada uma na sua pasta (nota, mapa, painel e imagens). Os nomes dos arquivos ficam iguais e uma cópia da pasta antiga é guardada no PC antes.",
    { title: "Migrar para a área de estudos?", ok: "Migrar" })) return;
  try { await api("/api/migration", {}); toast("Migrando os materiais antigos…", "info"); poll(); } catch (e) { fail(e); }
});
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
  try { S = await api("/api/clear", { forget_token: true }); $("#root").replaceChildren(); $("#free-root").replaceChildren(); renderSettings(); renderChecks(); renderPending(); await loadHistory().catch(() => {}); toast("Notion desconectado."); } catch (e) { fail(e); }
});


// ---------- Diagnóstico do sistema ----------
let lastDiagData = null;
let diagRunning = false;

async function runDiagnostics(silent = false) {
  if (diagRunning) return;
  diagRunning = true;
  const btn = $("#diag-run-btn");
  const label = $("#diag-run-label");
  if (btn) {
    btn.classList.add("scanning");
    btn.disabled = true;
    if (label) label.textContent = "Verificando tudo...";
  }
  try {
    const data = await api("/api/diagnostics");
    lastDiagData = data;
    renderDiagnostics(data);
    refreshRepair();
    if (!silent) toast("Diagnóstico concluído com sucesso.");
  } catch (err) {
    fail(err);
  } finally {
    diagRunning = false;
    if (btn) {
      btn.classList.remove("scanning");
      btn.disabled = false;
      if (label) label.textContent = "Verificar tudo agora";
    }
  }
}

function renderDiagnostics(data) {
  if (!data) return;
  const grid = $("#diag-grid");
  if (!grid) return;

  const summary = data.summary || {};
  const tone = summary.state === "error" ? "error" : summary.state === "warn" ? "warn" : "ok";
  const toneIcon = tone === "ok" ? "check-circle" : tone === "warn" ? "alert" : "x-circle";
  // D186: “100% operacional” só quando todas as obrigatórias rodaram e passaram (summary.operational, do servidor)
  const operational = summary.operational === true;
  const cov = summary.coverage || {}, ready = summary.readiness || {}, states = summary.states || {};

  const titleEl = $("#diag-summary-title");
  if (titleEl) titleEl.textContent = operational ? (summary.state === "ok" ? "Sistema 100% operacional" : "Obrigatórios 100% operacionais")
    : summary.state === "error" ? "Atenção necessária" : "Obrigatórios pendentes";

  const descEl = $("#diag-summary-desc");
  if (descEl) {
    const counts = [["missing", "Faltando", "error"], ["misconfigured", "Configuração incorreta", "error"], ["unreachable", "Inacessível", "warn"],
      ["blocked", "Bloqueado", "warn"], ["unverified", "Não verificado", "warn"], ["disabled", "Opcional desligado", ""]]
      .filter(([k]) => states[k]).map(([k, label, t]) => el("span", { class: "diag-chip", "data-tone": t }, `${label}: ${states[k]}`));
    descEl.replaceChildren(el("span", {}, summary.message || ""),
      cov.checks ? el("span", { class: "diag-coverage" },
        `Cobertura: ${cov.ran} de ${cov.checks} verificações rodaram (${cov.unverified || 0} não verificadas, ${cov.blocked || 0} bloqueadas). ` +
        `Prontidão: ${ready.required_ok} de ${ready.required} obrigatórias ok; opcionais ligadas: ${ready.optional_enabled_ok} de ${ready.optional_enabled}.`) : null,
      counts.length ? el("span", { class: "diag-counts" }, ...counts) : null);
  }

  const scoreBadge = $("#diag-score-badge");
  if ($("#diag-score-wrap")) $("#diag-score-wrap").hidden = false;
  if (scoreBadge) {
    scoreBadge.dataset.tone = tone;
    scoreBadge.setAttribute("aria-label", `Prontidão: ${data.score}% das verificações obrigatórias`);
    scoreBadge.replaceChildren(icon(toneIcon), el("span", { id: "diag-score-val" }, `${data.score}%`));
  }

  const lastScanEl = $("#diag-last-scan");
  if (lastScanEl) {
    const d = new Date(data.timestamp);
    const timeStr = isNaN(d) ? "agora" : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    lastScanEl.textContent = `Última conferência: ${timeStr}`;
  }
  const STATE = { ok: ["OK", "ok"], missing: ["Faltando", "error"], misconfigured: ["Configuração incorreta", "error"], unreachable: ["Inacessível", "warn"],
    disabled: ["Desativado", ""], unverified: ["Não verificado", "warn"], blocked: ["Bloqueado", "warn"] };
  const STAGE = [["installed", "Instalado"], ["configured", "Configurado"], ["authenticated", "Autenticado"], ["reachable", "Alcançável"], ["usable", "Utilizável"]];

  const catCards = (data.categories || []).map((cat) => {
    const cTone = cat.status === "error" ? "error" : cat.status === "warn" ? "warn" : "ok";
    const cBadgeText = cTone === "ok" ? "Pronto" : cTone === "warn" ? "Aviso" : "Requer atenção";

    const itemRows = (cat.items || []).map((it) => {
      const iTone = it.status === "error" ? "error" : it.status === "warn" ? "warn" : it.status === "info" ? "info" : "ok";
      const iIcon = iTone === "ok" ? "check-circle" : iTone === "warn" ? "alert" : iTone === "error" ? "x-circle" : "info";

      let actBtn = null;
      if (it.action) {
        actBtn = el("button", {
          class: "btn sm diag-item-action",
          type: "button",
          onclick: () => {
            if (it.action.view === "integrations") goIntegrations(it.action.tab || "notion");
            else if (it.action.cat) goSettings(it.action.cat);
            else if (it.action.view) showView(it.action.view);
          }
        }, it.action.label || "Resolver");
      }

      const [stLabel, stTone] = STATE[it.state] || [it.state || "", ""];
      const role = "required" in it ? el("span", { class: "diag-chip", "data-tone": it.required ? "req" : "" },
        it.required ? "Obrigatório" : it.enabled === false ? "Opcional · desligado" : "Opcional · ligado") : null;
      const stages = STAGE.filter(([k]) => it.stages && it.stages[k] !== null && it.stages[k] !== undefined);
      // D187: ícone | nome e estado | ação compacta; abaixo, na largura toda, detalhe, próximo passo, etapas e limite
      const repairBtn = it.repair ? el("button", { class: "btn sm primary diag-item-action", type: "button", "data-repair": it.repair,
        "aria-label": `Instalar ou reparar: ${it.name}`, onclick: () => openRepair(it.repair) }, icon("download"), "Instalar / reparar") : null;
      return el("div", { class: "diag-item-row", "data-state": it.state || "", role: "group", "aria-label": `${it.name}: ${stLabel}` },
        el("span", { class: "diag-item-ico", "data-tone": iTone }, icon(iIcon)),
        el("div", { class: "diag-item-head" }, el("span", { class: "diag-item-name" }, it.name),
          el("span", { class: "diag-chips" }, it.state ? el("span", { class: "diag-chip", "data-tone": stTone }, stLabel) : null, role)),
        repairBtn || actBtn ? el("div", { class: "diag-item-acts" }, repairBtn, actBtn) : null,
        el("div", { class: "diag-item-body" },
          el("p", { class: "diag-item-detail" }, it.detail),
          it.next ? el("p", { class: "diag-next" }, el("strong", {}, "Próximo passo: "), it.next) : null,
          stages.length ? el("ul", { class: "diag-stages", "aria-label": "Etapas conferidas" }, ...stages.map(([k, label]) => {
            const v = it.stages[k];
            return el("li", { class: "diag-chip", "data-tone": v ? "ok" : "error" }, icon(v ? "check" : "x"), el("span", {}, `${label}${v ? "" : " (não)"}`));
          })) : null,
          it.limit ? el("p", { class: "diag-limit" }, `Limite: ${it.limit}`) : null)
      );
    });

    return el("div", { class: "diag-group-card" },
      el("div", { class: "diag-group-head" },
        el("div", { class: "diag-group-title" }, icon(cat.icon || "check-circle"), el("span", {}, cat.title)),
        el("span", { class: "badge", "data-tone": cTone }, cBadgeText)
      ),
      el("div", { class: "diag-group-items" }, ...itemRows)
    );
  });

  grid.replaceChildren(...catCards);
}

$("#diag-run-btn")?.addEventListener("click", () => runDiagnostics());
$("#home-diag-btn")?.addEventListener("click", () => { goSettings("diagnostics"); runDiagnostics(); });

// ---------- Instalar / reparar (D187; lumen/repair.py) ----------
// O servidor recalcula o que pode ser feito a cada pedido: daqui só vai o id escolhido, depois da confirmação.
let repairPlan = [], repairTimer = 0;
const REPAIR_STEP = { running: ["sync", "warn", "Em andamento"], done: ["check-circle", "ok", "Concluído"], failed: ["x-circle", "error", "Falhou"], cancelled: ["x", "", "Cancelado"] };
async function refreshRepair() {
  let v;
  try { v = await api("/api/repair"); } catch (err) { return; }  // sem a rota (servidor antigo): o botão só não aparece
  renderRepair(v);
  if (v.job.status === "running" && !repairTimer) waitRepair();  // janela reaberta no meio de um reparo: volta a acompanhar
}
async function openRepair(id) {
  if (!repairPlan.length) await refreshRepair();
  const items = id ? repairPlan.filter((p) => p.id === id) : repairPlan;
  if (!items.length) { toast("Nada a instalar ou reparar agora. Rode o diagnóstico de novo.", "info"); return runDiagnostics(true); }
  for (const p of items) {
    const ok = await window.ui.confirm(`${p.detail}\n\nVai rodar, neste PC e sem administrador:\n${p.commands.map((c) => "• " + c).join("\n")}`,
      { title: p.title, ok: "Instalar / reparar" });
    if (!ok) return;
    try { renderRepair(await api("/api/repair", { action: "start", id: p.id })); } catch (err) { return fail(err); }
    await waitRepair();
  }
}
function waitRepair() {
  return new Promise((resolve) => {
    clearInterval(repairTimer);
    repairTimer = setInterval(async () => {
      let v;
      try { v = await api("/api/repair"); } catch (err) { return; }  // uma falha de leitura não encerra o acompanhamento
      renderRepair(v);
      if (v.job.status !== "running") {
        clearInterval(repairTimer); repairTimer = 0;
        toast(v.job.message, v.job.status === "done" ? "success" : v.job.status === "cancelled" ? "info" : "error", 9000);
        runDiagnostics(true);
        resolve();
      }
    }, 800);
  });
}
function renderRepair(v) {
  const job = (v && v.job) || {}, box = $("#diag-repair"), btn = $("#diag-repair-btn");
  repairPlan = (v && v.plan) || [];
  if (btn) {
    btn.hidden = !repairPlan.length || job.status === "running";
    btn.querySelector("span").textContent = repairPlan.length > 1 ? `Instalar / reparar ${repairPlan.length} itens faltando` : "Instalar / reparar itens faltando";
  }
  if (!box) return;
  box.hidden = !job.id;
  if (!job.id) return;
  const running = job.status === "running";
  box.dataset.status = job.status;
  $("#diag-repair-title").textContent = job.title || "Instalar / reparar";
  $("#diag-repair-steps").replaceChildren(...(job.steps || []).map((s) => {
    const [ic, tone, label] = REPAIR_STEP[s.state] || REPAIR_STEP.running;
    return el("li", { class: "diag-repair-step", "data-state": s.state },
      el("span", { class: "diag-item-ico", "data-tone": tone, "aria-hidden": "true" }, icon(ic)),
      el("span", {}, el("strong", {}, s.label), el("span", { class: "diag-sr" }, ` — ${label}`), s.detail ? el("span", { class: "diag-repair-detail" }, s.detail) : null));
  }));
  const msg = $("#diag-repair-msg");
  msg.textContent = running ? "Em andamento. Você pode cancelar: só o que este reparo iniciou é encerrado." : [job.message, job.action].filter(Boolean).join(" ");
  msg.dataset.tone = running ? "" : job.status === "done" ? "ok" : job.status === "failed" ? "error" : "";
  $("#diag-repair-cancel").hidden = !running;
}
$("#diag-repair-btn")?.addEventListener("click", () => openRepair());
$("#diag-repair-cancel")?.addEventListener("click", async () => {
  try { renderRepair(await api("/api/repair", { action: "cancel" })); } catch (err) { fail(err); }
});

// ---------- janela (botões estilo Mac quando aberto pelo Lumen.exe) ----------
const host = window.chrome && window.chrome.webview;
function desktopPrefs() { if (host && S) host.postMessage("desktop:prefs:" + S.config.widget); }
if (host) host.addEventListener("message", async (e) => {
  const msg = e.data;
  if (msg === "desktop:settings") { if (S) openSettings(); }
  // "Abrir no Cérebro" da Conversa rápida (barra flutuante): o Lumen.exe já validou o identificador; a página confere de novo
  else if (typeof msg === "string" && (msg === "desktop:chat" || msg.startsWith("desktop:chat:"))) {
    showView("study");
    const id = msg.slice("desktop:chat:".length);
    if (id) await window.lumenStudy?.openFromHost(id); else window.lumenStudy?.setTab("chat");
  }
  // “Trazer resposta ao Lúmen” no painel do Perplexity: só abre o diálogo de colar; nada vem da página dele (D185)
  else if (msg === "desktop:perplexity:paste") { showView("study"); window.lumenStudy?.setTab("chat"); window.lumenStudy?.perplexityPaste(); }
  else if (msg === "desktop:preferences-updated") {
    const root = S?.config.root_page_id, connected = S?.has_token;
    await refresh().catch(fail);
    if (root !== S?.config.root_page_id || connected !== S?.has_token) {
      $("#root").replaceChildren(); $("#free-root").replaceChildren(); renderSettings();
      if (view === "integrations" && S.has_token) await loadRoots();
      await loadCatalog();
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
  // Arrastar pela barra: a página pede o movimento ao Lumen.exe (window:drag) em vez de app-region: drag, que tira o mouse da página
  // e deixava o cursor do Lumen sumir ali. Dois cliques maximizam ou restauram, como na barra do Windows.
  document.documentElement.classList.add("page-drag");
  let lastDown = { t: -1e9, x: 0, y: 0 };  // o laço de mover do Windows engole o soltar: o duplo clique é contado aqui, não pelo e.detail
  for (const bar of $$(".topbar, .rail-top"))
    bar.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("button, a, input, select, textarea, [role=button], [role=tab], .pomo, .pomo-slot")) return;
      e.preventDefault();
      const double = e.timeStamp - lastDown.t < 500 && Math.abs(e.screenX - lastDown.x) < 5 && Math.abs(e.screenY - lastDown.y) < 5;
      lastDown = double ? { t: -1e9, x: 0, y: 0 } : { t: e.timeStamp, x: e.screenX, y: e.screenY };
      host.postMessage(double ? "window:maximize" : "window:drag");
    });
}
window.addEventListener("blur", () => document.body.classList.add("inactive"));
window.addEventListener("focus", () => document.body.classList.remove("inactive"));
if (!document.hasFocus()) document.body.classList.add("inactive");  // aberta sem foco (em segundo plano): nunca recebe o blur

// ---------- Áreas: Início, Nova aula, Biblioteca, Integrações, Ajustes ----------
const VIEWS = ["home", "new", "library", "study", "integrations", "settings"];
const VIEW_NAMES = { home: "Início", new: "Nova aula", library: "Biblioteca", study: "Cérebro", integrations: "Integrações", settings: "Ajustes" };
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
  else setWhere(VIEW_NAMES[name], name === "settings" ? $(`#settings-nav [data-cat=${settingsCat}]`).textContent.trim()
    : name === "integrations" ? $(`#itab-${integTab} .integ-tab-name`).textContent : "");
  if (name === "home") { renderHome(); loadHistory().then(renderHome).catch(() => {}); loadReviews(); }
  if (name === "library") loadLibrary();
  if (name === "study") window.lumenStudy?.show();
  if (name === "integrations") {
    if (integTab === "voicestudio") window.lumenVoice?.integration($("#integ-voicestudio"));
    if (was !== name && S?.has_token) loadRoots();
    if (was !== name) { loadMigration(); loadDriveCard(); }
    if (integTab === "opennotebook") window.lumenON?.load();
    if (integTab === "hyperbooklm") window.lumenHB?.load();
  }
  if (S && ["settings", "integrations"].includes(was) && !["settings", "integrations"].includes(name)) afterSettings();
}
for (const b of $$(".rail-item")) b.addEventListener("click", () => {
  b.blur();
  if (b.id === "open-monitor") return;
  if (b.dataset.view === "library") { libFilter = "all"; libCourse = null; }
  if (b.dataset.view === "settings") goSettings(); else if (b.dataset.view) showView(b.dataset.view);
});
for (const b of $$("[data-go]")) b.addEventListener("click", () => {
  b.blur();
  libFilter = b.dataset.filter === "pending" ? "pending" : "all";
  libCourse = null;
  showView(b.dataset.go);
});

// Aulas salvas (Notion e/ou Obsidian): uma leitura só para o Início, a Biblioteca e a busca
let historyItems = null;
async function loadHistory() {
  const r = await api("/api/history");
  historyItems = r.items;
  if (r.courses) catalogData.courses = r.courses;
  if (r.categories) catalogData.categories = r.categories;
  $("#lib-n-saved").textContent = historyItems.length || "";
  return historyItems;
}
const shortDate = (iso) => iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "short", year: "numeric" }) : "";
const emptyState = (ic, title, text, action) =>
  el("div", { class: "empty" }, el("span", { class: "empty-icon", "aria-hidden": "true" }, icon(ic)), el("strong", {}, title), el("p", {}, text), action || null);
const today = () => new Date().toLocaleDateString("sv-SE");  // AAAA-MM-DD no fuso do PC
const clsOf = (it) => it.classification || { type: "inbox" };
const isDue = (it) => !!(S?.config.obsidian_review && it.review?.next && it.review.next <= today());
function savedRow(it, compact = false, inCourse = false) {
  const ob = it.obsidian?.status === "ok", c = clsOf(it);
  const act = (ic, label, tip, attrs) => compact
    ? el(attrs.href ? "a" : "button", { class: "icon-btn sm", "aria-label": `${tip}: ${it.title}`, "data-tip": tip, ...attrs }, icon(ic))
    : el(attrs.href ? "a" : "button", { class: "btn ghost sm", "data-tip": tip, ...attrs }, icon(ic), label);
  const full = it.crumbs || crumbsOf(withNames(c));
  const crumbs = inCourse ? (c.lesson ? [`Aula ${String(c.lesson).padStart(2, "0")}`] : []) : full;  // dentro do curso, a trilha já está no topo
  // os três lugares da aula com o mesmo formato (ícone + nome); o mapa e o painel são do Obsidian e ficam só com o ícone
  const extra = (ic, tip, what) => el("button", { class: "icon-btn sm", type: "button", "aria-label": `${tip}: ${it.title}`, "data-tip": tip, onclick: () => openObsidian(it.key, what) }, icon(ic));
  return el("div", { class: "lib-row", role: "listitem", "data-key": it.key },
    el("span", { class: "lib-ico", "aria-hidden": "true", "data-tone": isDue(it) ? "warn" : "" }, icon((TYPE_LOOK[c.type] || TYPE_LOOK.inbox)[0])),
    el("span", { class: "lib-text" }, el("span", { class: "lib-title" }, it.title),
      el("span", { class: "lib-meta", "data-tip": full.join(" › ") }, [crumbs.join(" › "),
        c.type === "inbox" && it.url && it.course ? `no Notion: ${it.course.split(" › ").pop()}` : "",  // pista para organizar as antigas
        isDue(it) ? `revisão ${it.review.next < today() ? "atrasada" : "hoje"}` : "", shortDate(it.created || it.obsidian?.at)].filter(Boolean).join(" · "))),
    el("span", { class: "lib-actions" },
      it.url ? act("external", "Notion", "Abrir no Notion", { href: it.url, target: "_blank", rel: "noopener" }) : null,
      ob ? act("obsidian", "Obsidian", "Abrir no Obsidian", { type: "button", onclick: () => openObsidian(it.key, "note") }) : null,
      it.lumen_id && window.lumenVoice ? act("volume", "Áudio", "Resumo em áudio (ouvir ou gerar)", { type: "button", onclick: () => window.lumenVoice.lessonAudio(it.key, it.title) }) : null,
      it.lumen_id && window.lumenON?.enabled() ? el("button", { class: "icon-btn sm", type: "button", "aria-label": `Open Notebook: ${it.title}`,
        "data-tip": it.opennotebook?.source ? "Open Notebook: ver o envio ou abrir" : "Enviar a transcrição ao Open Notebook", onclick: () => window.lumenON.lesson(it.key, it.title) }, icon("notebook")) : null,
      it.lumen_id && window.lumenHB?.enabled() ? el("button", { class: "icon-btn sm", type: "button", "aria-label": `HyperbookLM: ${it.title}`,
        "data-tip": it.hyperbooklm?.state === "sent" ? "HyperbookLM: ver o envio ou abrir" : "Enviar a transcrição ao HyperbookLM", onclick: () => window.lumenHB.lesson(it.key, it.title) }, icon("layers")) : null,
      ob && it.obsidian.canvas ? extra("map", "Abrir o mapa conceitual", "canvas") : null,
      ob && it.obsidian.board ? extra("image", "Abrir o painel visual", "board") : null,
      !ob && it.lumen_id && usesObsidian() ? el("button", { class: "btn ghost sm", type: "button", "data-tip": "Cria a nota de estudo desta aula no cofre, sem chamar a IA de novo",
        onclick: () => { showView("new"); redeliver(it.key, "obsidian"); } }, icon("plus"), compact ? "Obsidian" : "Salvar no Obsidian") : null,
      compact ? null : el("button", { class: "icon-btn sm", type: "button", "aria-label": `Organizar: ${it.title}`, "data-tip": "Organizar: curso, módulo ou tema",
        onclick: () => openOrg(c, it) }, icon("move"))));
}
const skeletonRows = (n) => Array.from({ length: n }, () => el("div", { class: "skeleton-row", "aria-hidden": "true" },
  el("span", { class: "skeleton" }), el("span", { class: "lib-text" }, el("span", { class: "skeleton sk-title" }), el("span", { class: "skeleton sk-meta" }))));

// ---------- Biblioteca: vistas da organização, busca e filtros locais ----------
let libFilter = "all", libCourse = null;  // libCourse: o curso aberto (módulos e aulas)
async function loadLibrary() {
  renderLibrary();
  try { await loadHistory(); renderLibrary(); renderHome(); } catch (e) { if (!historyItems) swap($("#library-list"), []); fail(e); }
}
function openCourse(id) { libFilter = "course"; libCourse = id; $("#content").scrollTop = 0; if (view === "library") loadLibrary(); }
const VIEW_TEST = { all: () => true, course: (it) => clsOf(it).type === "course", free: (it) => clsOf(it).type === "free",
  single: (it) => clsOf(it).type === "single", inbox: (it) => clsOf(it).type === "inbox", review: isDue };
function filtered(items) {  // os filtros de “Filtros”: curso, módulo, status, revisão e data
  const fc = $("#lf-course").value, fm = $("#lf-module").value, fs = $("#lf-status").value, fr = $("#lf-review").value, fd = +$("#lf-date").value;
  const since = fd ? new Date(Date.now() - fd * 864e5).toISOString() : "";
  return items.filter((it) => {
    const c = clsOf(it);
    if (fc && c.course_id !== fc) return false;
    if (fm && c.module_id !== fm) return false;
    if (fs && (it.review?.status || "") !== fs) return false;
    if (fr === "due" && !isDue(it)) return false;
    if (fr === "started" && !(+it.review?.stage > 0)) return false;
    if (fr === "none" && it.review?.next) return false;
    if (since && (it.created || it.obsidian?.at || "") < since) return false;
    return true;
  });
}
function renderFilters() {
  const fc = $("#lf-course"), fm = $("#lf-module"), keepC = fc.value, keepM = fm.value;
  fc.replaceChildren(el("option", { value: "" }, "Todos"), ...catalogData.courses.slice().sort((a, b) => a.name.localeCompare(b.name, "pt-BR"))
    .map((c) => el("option", { value: c.id }, c.name)));
  fc.value = catalogData.courses.some((c) => c.id === keepC) ? keepC : "";
  const mods = (courseOf(fc.value)?.modules || []).slice().sort(byOrder);
  fm.replaceChildren(el("option", { value: "" }, fc.value ? "Todos" : "Escolha o curso"), ...mods.map((m) => el("option", { value: m.id }, modName(m))));
  fm.value = mods.some((m) => m.id === keepM) ? keepM : "";
  fm.disabled = !fc.value;
  const n = ["#lf-course", "#lf-module", "#lf-status", "#lf-review", "#lf-date"].filter((x) => $(x).value).length;
  $("#lib-n-filters").textContent = n || "";
}
function courseCards(items) {
  const cards = catalogData.courses.slice().sort((a, b) => a.name.localeCompare(b.name, "pt-BR")).map((c) => {
    const mine = items.filter((it) => clsOf(it).course_id === c.id), due = mine.filter(isDue).length;
    return el("button", { class: "course-card", type: "button", onclick: () => openCourse(c.id) },
      el("span", { class: "course-ico", "aria-hidden": "true" }, icon("library")),
      el("span", { class: "course-name" }, c.name),
      el("span", { class: "course-meta" }, [c.platform, `${mine.length} ${mine.length === 1 ? "aula" : "aulas"}`, c.modules.length ? `${c.modules.length} ${c.modules.length === 1 ? "módulo" : "módulos"}` : ""].filter(Boolean).join(" · ")),
      due ? el("span", { class: "badge", "data-tone": "warn" }, icon("clock"), `${due} para revisar`) : null);
  });
  return cards;
}
function courseView(c, items) {  // a visão do curso: módulos em ordem, aulas em ordem, progresso só com dados reais
  const mine = items.filter((it) => clsOf(it).course_id === c.id);
  const done = mine.filter((it) => it.review?.status === "completed").length, due = mine.filter(isDue).length;
  const head = el("div", { class: "course-head" },
    el("div", { class: "course-title" }, el("h2", { class: "t-h2" }, c.name),
      el("p", { class: "muted t-sm" }, [c.platform, `${mine.length} ${mine.length === 1 ? "aula" : "aulas"}`,
        mine.length && usesObsidian() ? `${done} revisada${done === 1 ? "" : "s"} por você` : "", due ? `${due} para revisar hoje` : ""].filter(Boolean).join(" · "))),
    el("span", { class: "course-actions" },
      usesObsidian() && vaultReady() ? el("button", { class: "btn ghost sm", type: "button", onclick: () => openObsidian("", "course", c.id) }, icon("obsidian"), "Abrir no Obsidian") : null,
      c.notion_page_id && S?.has_token ? el("button", { class: "btn ghost sm", type: "button", onclick: () => covOpen(c.notion_page_id) }, icon("image"), "Criar capa") : null,
      el("button", { class: "btn ghost sm", type: "button", onclick: () => editCourse(c) }, icon("pen"), "Renomear")));
  const out = [head];
  const by = new Map();
  for (const it of mine) { const k = clsOf(it).module_id || ""; if (!by.has(k)) by.set(k, []); by.get(k).push(it); }
  const order = (a, b) => (clsOf(a).lesson || 999) - (clsOf(b).lesson || 999) || a.title.localeCompare(b.title, "pt-BR", { numeric: true });
  for (const m of c.modules.slice().sort(byOrder)) {
    const xs = (by.get(m.id) || []).sort(order);
    out.push(el("p", { class: "group-h" }, `${modName(m)} · ${xs.length}`), ...(xs.length ? xs.map((it) => savedRow(it, false, true)) : [el("p", { class: "muted t-sm mod-empty" }, "Nenhuma aula neste módulo ainda.")]));
    by.delete(m.id);
  }
  const rest = [...by.values()].flat().sort(order);
  if (rest.length) out.push(el("p", { class: "group-h" }, c.modules.length ? `Sem módulo · ${rest.length}` : `Aulas · ${rest.length}`), ...rest.map((it) => savedRow(it, false, true)));
  if (!mine.length) out.push(emptyState("library", "Nenhuma aula neste curso ainda", "Na Nova aula, escolha este curso em Organização. As aulas antigas vão para cá pelo “Organizar” de cada uma."));
  return out;
}
async function editCourse(c) {  // renomear não cria outro curso: o id fica, e a pasta, a nota e a página do Notion acompanham
  const box = $("#library-list").querySelector(".course-head");
  if (!box || box.querySelector(".course-edit")) return;
  const name = el("input", { maxlength: "80", "aria-label": "Nome do curso" }), plat = el("input", { maxlength: "60", "aria-label": "Plataforma", placeholder: "Plataforma (opcional)" });
  name.value = c.name; plat.value = c.platform || "";
  const save = el("button", { class: "btn primary sm", type: "button" }, "Salvar"), cancel = el("button", { class: "btn ghost sm", type: "button", onclick: () => form.remove() }, "Cancelar");
  const form = el("div", { class: "course-edit input-row" }, name, plat, cancel, save);
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const r = await api("/api/catalog/course", { id: c.id, name: name.value.trim(), platform: plat.value.trim() });
      toast(r.note || `Curso renomeado para “${r.course.name}”.`, r.note ? "warning" : "success");
      await loadCatalog(false); await loadLibrary();
    } catch (e) { fail(e); save.disabled = false; }
  });
  box.append(form); name.focus(); name.select();
}
function renderLibrary() {
  window.Glass?.library();  // Glass: números e estrutura da biblioteca (das mesmas listas)
  const box = $("#library-list"), rv = !!S?.config.obsidian_review;  // revisões desligadas: sem vista nem filtro de revisão
  $("#lib-filter [data-f=review]").hidden = $("#lf-review").closest(".field").hidden = !rv;
  if (!rv) { $("#lf-review").value = ""; if (libFilter === "review") libFilter = "all"; }
  for (const b of $$("#lib-filter button")) b.setAttribute("aria-pressed", String(b.dataset.f === libFilter));
  renderFilters();
  const typed = $("#lib-search").value.trim(), q = fold(typed);
  const match = (...t) => !q || t.some((x) => fold(String(x || "")).includes(q));
  const pend = (S?.pending || []).filter((p) => match(p.title, p.label));
  const all = historyItems || [], by = $("#lib-sort").value;
  for (const [f, test] of Object.entries(VIEW_TEST)) if (f !== "all") $("#lib-n-" + f).textContent = all.filter(test).length || "";
  $("#lib-n-pending").textContent = S?.pending?.length || "";
  const course = libFilter === "course" && libCourse ? courseOf(libCourse) : null;
  if (libFilter === "course" && libCourse && !course) libCourse = null;
  // trilha: Biblioteca / Cursos / <curso>
  $("#lib-crumbs").hidden = !course;
  if (course) $("#lib-crumbs").replaceChildren(
    el("button", { class: "crumb", type: "button", onclick: () => { libCourse = null; renderLibrary(); } }, "Cursos"),
    el("span", { class: "sep", "aria-hidden": "true" }, "/"), el("span", { class: "crumb cur", "aria-current": "page" }, course.name));
  const saved = filtered(all.filter(VIEW_TEST[libFilter] || (() => false))).filter((it) =>
    match(it.title, ...(it.crumbs || []), ...(it.concepts || []), clsOf(it).course, clsOf(it).module, clsOf(it).category));
  if (by !== "recent") saved.sort((a, b) => (by === "course" ? (a.crumbs || []).join("/").localeCompare((b.crumbs || []).join("/"), "pt-BR", { numeric: true }) : 0)
    || a.title.localeCompare(b.title, "pt-BR", { numeric: true }));  // a lista vem do servidor da mais nova para a mais velha
  // Cursos: os cards; com um curso aberto, os módulos e as aulas dele
  const grid = $("#course-grid"), cardsOn = libFilter === "course" && !course && !typed;
  grid.hidden = !cardsOn;
  if (cardsOn) swap(grid, catalogData.courses.length ? courseCards(all)
    : [emptyState("library", "Nenhum curso ainda", "Crie o primeiro na Nova aula, em Organização → Alterar → Novo curso. As páginas de curso do seu Notion também podem ser adotadas lá.")]);
  if (course && historyItems) return swap(box, courseView(course, filtered(saved)));
  const out = [];
  if ((libFilter === "all" || libFilter === "pending") && pend.length) out.push(el("p", { class: "group-h" }, "Em andamento"), ...pend.map(pendingRow));
  // as salvas ainda chegando: as em andamento já aparecem, e só o grupo das salvas fica em carregamento
  const title = { all: "Salvas", course: "Aulas de cursos", free: "Conteúdo gratuito", single: "Aulas avulsas", review: "Para revisar hoje", inbox: "Para organizar" }[libFilter];
  if (libFilter !== "pending" && !historyItems) out.push(el("p", { class: "group-h" }, title), ...skeletonRows(3));
  else if (libFilter !== "pending" && saved.length && !cardsOn) out.push(el("p", { class: "group-h" }, title), ...saved.map((it) => savedRow(it)));
  if (libFilter === "inbox" && saved.length) out.splice(1, 0, el("p", { class: "muted t-sm lib-tip" }, "Use “Organizar” (", icon("move", "sm"), ") em cada aula: ela vai inteira para o curso, módulo ou tema."));
  if (out.length || !historyItems || cardsOn) return swap(box, out.length ? out : cardsOn ? [] : skeletonRows(4));
  const start = el("button", { class: "btn primary", type: "button", onclick: () => showView("new") }, icon("new"), "Nova aula");
  swap(box, [typed ? emptyState("search", `Nada com “${typed}”`, "Tente outra palavra do título, do curso, do tema ou de um conceito da aula.")
    : libFilter === "pending" ? emptyState("pen", "Nenhuma aula em andamento", "As aulas que você começar e ainda não salvou ficam aqui, para continuar de onde parou.", start)
    : libFilter === "review" ? emptyState("check-circle", "Nada para revisar hoje", "As revisões vêm das datas marcadas nas notas do Obsidian.")
    : libFilter === "inbox" ? emptyState("check-circle", "Nada para organizar", "Todas as aulas já têm curso, tema ou tipo.")
    : libFilter !== "all" ? emptyState("library", "Nenhuma aula aqui ainda", "Escolha a organização na Nova aula, ou use “Organizar” numa aula salva.")
    : emptyState("library", "Nenhuma aula ainda", "Quando você salvar a primeira aula no Notion ou no Obsidian, ela aparece aqui.", start)]);
}
$("#lib-search").addEventListener("input", renderLibrary);
$("#lib-sort").addEventListener("change", renderLibrary);
for (const id of ["#lf-course", "#lf-module", "#lf-status", "#lf-review", "#lf-date"]) $(id).addEventListener("change", renderLibrary);
$("#lib-more").addEventListener("click", (e) => {  // os filtros ficam recolhidos; o número diz quantos estão valendo
  const open = $("#lib-filters").hidden;
  $("#lib-filters").hidden = !open;
  e.currentTarget.setAttribute("aria-expanded", String(open));
});
$("#lf-clear").addEventListener("click", () => { for (const id of ["#lf-course", "#lf-module", "#lf-status", "#lf-review", "#lf-date"]) $(id).value = ""; renderLibrary(); });
for (const b of $$("#lib-filter button")) b.addEventListener("click", () => { libFilter = b.dataset.f; libCourse = null; renderLibrary(); });

// ---------- Início: o que está acontecendo, o que continuar, o que precisa de atenção ----------
const STAGE_NAMES = { prepare: "Preparando a fonte", transcribe: "Transcrevendo", screen: "Lendo as telas", analyze: "Analisando",
  generate: "Escrevendo o material", connect: "Buscando conexões", obsidian: "Salvando no Obsidian", publish: "Salvando no Notion", download: "Baixando",
  voice: "Gerando o áudio" };
const STAGE_SHORT = { prepare: "Preparando", transcribe: "Transcrevendo", screen: "Lendo as telas", generate: "Escrevendo",
  connect: "Conexões", obsidian: "Salvando", publish: "Salvando", download: "Baixando", voice: "Áudio" };
const pct = (j) => Number.isFinite(j.progress) ? ` · ${Math.round(j.progress * 100)}%` : "";
let heroMode = "";
function renderHome() {  // tudo (ao abrir o Início, ao chegar a lista de aulas); a gravação e a tarefa só mexem no cartão principal
  if (!S || view !== "home") return;
  const h = new Date().getHours();
  $("#home-greet").textContent = h < 5 || h >= 18 ? "Boa noite" : h < 12 ? "Bom dia" : "Boa tarde";
  $("#home-date").textContent = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  renderHero();
  renderPending();
  const recent = (historyItems || []).slice(0, 4);
  $("#home-recent").hidden = !!historyItems && !recent.length;
  swap($("#recent-list"), historyItems ? recent.map((it) => savedRow(it, true)) : skeletonRows(3));
  window.Glass?.journey();
}
function renderHero() {
  if (!S || view !== "home") return;
  const box = $("#home-hero"), r = S.recording || {}, j = lastJob || S.job || {}, p = S.pending?.[0];
  const { mode } = heroState(), busy = mode === "job";
  const n = S.pending?.length || 0, due = reviews.length;
  $("#home-lead").textContent = r.active ? "Uma gravação está em andamento."
    : busy ? "O Lumen está trabalhando numa aula; dá para continuar usando o app."
    : [n ? `${n} ${n === 1 ? "aula espera" : "aulas esperam"} por você` : "", due ? `${due} ${due === 1 ? "revisão" : "revisões"} para hoje` : ""].filter(Boolean).join(" · ") + (n || due ? "." : "")
      || "Grave ou escolha uma aula, escreva o que entendeu e deixe a IA local completar.";
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
  // Glass: sem gravação nem tarefa, o cartão é sempre “Comece uma nova aula”; as aulas em andamento ficam em “Continue de onde parou”
  if (window.Glass?.hero(box)) return;
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
  const heroKids = [
    top("accent", icon("sparkle"), mode === "first" ? "Primeira aula" : "Nova aula"),
    el("p", { class: "hero-title" }, "Grave uma nova aula"),
    el("p", { class: "hero-sub" }, "O Lumen prepara a aula no seu PC. Você escreve o que entendeu e só depois a IA local analisa e completa."),
    mode === "first" ? el("ol", { class: "flow" },
      el("li", {}, el("strong", {}, "Assista ou escolha"), "Grave o som da aula no seu PC."),
      el("li", {}, el("strong", {}, "Escreva o que entendeu"), "Com suas palavras, sem ajuda da IA."),
      el("li", {}, el("strong", {}, "A IA analisa e salva"), S.config.obsidian_review ? "No Notion e no Obsidian, com mapa e revisões." : "No Notion e no Obsidian, com mapa e perguntas.")) : null,
    el("div", { class: "hero-actions" }, btn("primary lg", "record", "Gravar ao assistir", source("recording")))
  ].filter(Boolean);
  box.replaceChildren(...heroKids);
}

// Revisões do Obsidian para hoje (e as atrasadas): marcadas na nota de estudo, lidas do cofre pelo Lumen
let reviews = [];
async function loadReviews() {
  const on = usesObsidian() && S.config.obsidian_review && vaultReady();
  if (on) { try { reviews = (await api("/api/reviews")).items; } catch { reviews = []; } } else reviews = [];
  const box = $("#home-reviews");
  box.hidden = !reviews.length;
  $("#reviews-count").textContent = reviews.length === 1 ? "1 para revisar" : `${reviews.length} para revisar`;
  swap($("#review-list"), reviews.slice(0, 4).map((r) => el("div", { class: "lib-row", role: "listitem", "data-key": r.key || r.lumen_id },
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
  let tone = "ok", ic = "check-circle", text = "Pronto", full = "";
  if (r.error) { tone = "error"; ic = "alert"; text = "Gravação interrompida"; }
  else if (r.active) { tone = r.paused ? "paused" : "rec"; ic = r.paused ? "pause" : "dot"; text = (r.paused ? "Pausado · " : "Gravando · ") + mmss(r.seconds); }
  else if (j.status === "running") {  // na pílula, o nome curto da etapa; o completo vai na dica
    tone = "busy"; ic = "spin";
    text = (j.kind === "analyze" ? "Analisando" : STAGE_SHORT[j.stage] || "Processando") + pct(j);
    full = (j.kind === "analyze" ? "Analisando sua compreensão" : STAGE_NAMES[j.stage] || "Processando") + pct(j) + (j.title ? ` · ${j.title}` : "");
  }
  else if (j.status === "error" && step === "run") { tone = "error"; ic = "alert"; text = "A tarefa falhou"; }
  else if (!$("#setup").hidden) { tone = "warn"; ic = "alert"; text = "Configuração pendente"; }
  if (pill.dataset.ic !== ic) {
    pill.dataset.ic = ic;
    $("#global-status-ico").replaceChildren(ic === "spin" ? el("span", { class: "spinner" }) : ic === "dot" ? el("span", { class: "live-dot" }) : icon(ic));
  }
  // o leitor de tela ouve cada mudança de estado ou de etapa, mas não o relógio nem o percentual a cada leitura
  const said = "Lumen: " + text.replace(/ · [\d:]+$/, "").replace(/ · \d+%$/, "");
  if ($("#status-live").textContent !== said) $("#status-live").textContent = said;
  pill.dataset.tone = tone;
  // O “Pronto” ocioso não diz nada: a pílula só aparece quando há estado de verdade.
  pill.hidden = tone === "ok";
  $("#global-status-text").textContent = text;
  pill.setAttribute("aria-label", `Status do Lumen: ${full || text}`);
  pill.dataset.tip = tone === "ok" ? "Tudo pronto. Clique para ir ao Início." : tone === "warn" ? "Veja o que falta no Início"
    : full ? `${full}. Clique para ver o progresso.` : "Ver na Nova aula";
}
$("#global-status").addEventListener("click", async () => {
  const t = $("#global-status").dataset.tone, j = lastJob || S?.job || {};
  if (t === "busy" && ["audio", "study_image", "study_pdf", "study_holo"].includes(j.kind)) {
    const left = Number.isFinite(j.eta_total) ? ` Faltam cerca de ${fmtDur(j.eta_total)}.` : "";
    const label = j.kind === "audio" ? "Áudio" : j.kind === "study_pdf" ? "PDF" : j.kind === "study_holo" ? "Holograma 3D" : "Imagem";
    if (await ui.confirm(`${j.detail || "Gerando o material"}.${left}`, { title: `${label}: ${j.spec?.title || "em andamento"}`, ok: "Cancelar a geração", cancel: "Continuar gerando", danger: true }))
      api("/api/cancel", {}).catch(fail);
    return;
  }
  showView(t === "ok" || t === "warn" ? "home" : "new");
});

// ---------- Integrações → Google Drive: a conta da cópia de segurança da Proteção (API oficial) ----------
// O Lumen guarda a autorização no cofre do Windows e só vê os arquivos que ele mesmo criar (escopo drive.file). Quem usa
// a conta é a Proteção do cérebro (lumen/protection_drive.py); esta tela só conecta, troca o cliente e desconecta.
let DRV = null, drivePoll = null, driveBusy = false;
async function loadDriveCard() {
  try { DRV = await api("/api/drive"); } catch (e) { DRV = { error: e }; }
  renderDriveCard();
}
function renderDriveCard() {
  const d = DRV, badge = $("#drive-badge");
  if (!d || d.error) {
    setBadge(badge, d ? ["warn", "alert", "Não carregou"] : ["", "clock", "Carregando…"]);
    return renderDrive(null, d?.error);
  }
  setBadge(badge, d.expired && !d.connected ? ["warn", "alert", "Reconecte o Drive"] : d.connected ? ["ok", "check", "Drive conectado"]
    : d.client ? ["", "key", "Falta entrar"] : ["", "minus", "Não configurado"]);
  renderDrive(d);
}
function renderDrive(d, err) {  // o estado do Google Drive em palavras e a próxima ação; nunca bloqueia o resto da página
  const st = $("#drive-status"), acts = $("#drive-actions"), had = acts.contains(document.activeElement);
  clearTimeout(drivePoll);
  const b = (cls, ic, text, fn) => el("button", { class: "btn sm " + cls, type: "button", onclick: fn }, icon(ic), text);
  if (!d) {
    if (!err) { swap(st, [el("span", { class: "skeleton drive-sk", "aria-hidden": "true" })]); return swap(acts, []); }
    swap(st, [el("span", { class: "drive-ico", "data-tone": "warn", "aria-hidden": "true" }, icon("alert")),
      el("span", { class: "drive-text" }, el("strong", {}, err.message), el("small", {}, err.action || "A conexão já feita continua guardada."))]);
    return swap(acts, [b("", "refresh", "Tentar de novo", loadDriveCard)]);
  }
  const login = (text) => b("primary", "key", text, () => driveAct("/api/drive/login"));
  const change = () => b("ghost", "file", "Trocar o arquivo do cliente", () => driveAct("/api/drive/client"));
  let look;  // [tom, ícone, título, explicação, ações]
  if (d.login === "waiting") {
    look = ["busy", "spin", "Aguardando a autorização no navegador", "Entre com a sua conta Google na aba que abriu e autorize o Lumen. O pedido vale por 5 minutos.", []];
    drivePoll = setTimeout(async () => {
      if (view !== "integrations") return;  // fora de Integrações a consulta para (volta ao abrir de novo)
      try { DRV = await api("/api/drive"); } catch { /* tenta de novo */ }
      renderDriveCard();
    }, 2000);
  } else if (d.connected) look = ["ok", "check-circle", "Drive conectado", `${d.email ? `Como ${d.email}. ` : ""}A cópia de segurança da Proteção usa esta conta; o Lumen só vê os arquivos que ele mesmo criou.`,
    [b("ghost danger", "power", "Desconectar", driveLogout)]];
  else if (!d.client) look = ["", "upload", "Não configurado", "Com um projeto seu no Google Cloud, o Lumen guarda a cópia de segurança da Proteção no seu Drive. É opcional: a cópia neste computador não depende disso.",
    [b("", "file", "Escolher o arquivo do cliente…", () => driveAct("/api/drive/client"))]];
  else if (d.login === "error") look = ["warn", "alert", "Não foi possível entrar", d.error || "Tente de novo.", [login("Tentar de novo"), change()]];
  else if (d.expired) look = ["warn", "alert", "Acesso expirado ou revogado", "O Google não aceita mais a autorização (no modo Testing ela vale 7 dias, e pode ter sido removida da conta). Entre de novo para voltar a copiar.",
    [login("Entrar com Google de novo"), change()]];
  else look = ["", "key", "Falta entrar com a sua conta", "O arquivo do cliente já foi escolhido. Entre com Google, no navegador, para o Lumen poder guardar a cópia no seu Drive.",
    [login("Entrar com Google"), change()]];
  const [tone, ic, title, text, list] = look;
  swap(st, [el("span", { class: "drive-ico", "data-tone": tone, "aria-hidden": "true" }, ic === "spin" ? el("span", { class: "spinner" }) : icon(ic)),
    el("span", { class: "drive-text" }, el("strong", {}, title), el("small", {}, text))]);
  swap(acts, list);
  if (had && !acts.contains(document.activeElement)) (acts.querySelector("button") || st).focus();
}
async function driveAct(path, done) {  // uma ação por vez: clique duplo não abre dois logins nem dois seletores de arquivo
  const acts = $("#drive-actions"), had = acts.contains(document.activeElement);
  if (driveBusy) return;
  driveBusy = true;
  if (had) $("#drive-status").focus();  // o botão fica desabilitado: o foco espera no estado
  for (const x of acts.querySelectorAll("button")) x.disabled = true;
  try { DRV = await api(path, {}); if (done) toast(done); } catch (e) { fail(e); }
  finally { driveBusy = false; sigs.delete(acts); }
  renderDriveCard();
  if (had && document.activeElement === $("#drive-status")) acts.querySelector("button")?.focus();
}
async function driveLogout() {
  if (!await ui.confirm("Desconectar o Google Drive deste PC? As cópias já enviadas continuam no seu Drive. Para revogar o acesso no Google, use myaccount.google.com/permissions.",
    { title: "Desconectar Google Drive", ok: "Desconectar", danger: true })) return;
  driveAct("/api/drive/logout", "Google Drive desconectado deste PC.");
}

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
  if (usesObsidian() && vaultReady()) add("Ações", "Abrir Estudos no Obsidian", "external", () => openObsidian("", "home"));
  add("Ações", "Organizar a próxima aula", "folder", () => { showView("new"); openOrg(org); });
  add("Ações", "Criar capa no Notion", "image", () => covOpen(), "qualquer página");
  const pomo = Pomodoro.state();
  if (pomo) add("Pomodoro", pomo.running ? "Pausar o Pomodoro" : Pomodoro.status() === "paused" ? "Continuar o Pomodoro" : "Iniciar o Pomodoro",
    pomo.running ? "pause" : "play", Pomodoro.toggle, "não afeta a gravação");
  add("Pomodoro", "Abrir o Pomodoro", "timer", () => Pomodoro.open());
  for (const [v, ic] of [["home", "home"], ["new", "new"], ["library", "library"], ["study", "brain"], ["integrations", "plug"]]) add("Ir para", VIEW_NAMES[v], ic, () => { libFilter = "all"; showView(v); });
  add("Cérebro", "Conversa por voz", "wave", () => { showView("study"); window.lumenStudy?.setTab("chat"); window.lumenStudy?.openCall?.(); }, "Lumen Study AI");
  add("Cérebro", "Nova conversa de estudo", "sparkle", () => { showView("study"); window.lumenStudy?.setTab("chat"); window.lumenStudy?.newConversation(); }, "Lumen Study AI");
  add("Cérebro", "Revisar flashcards", "copy", () => { showView("study"); window.lumenStudy?.setTab("learn"); window.lumenStudy?.learnGo?.("today"); }, "Lumen Study AI");
  add("Cérebro", "Configurações da IA de estudos", "gear", () => { showView("study"); window.lumenStudy?.openSettings(); }, "Lumen Study AI");
  for (const t of INTEG_TABS) add("Integrações", t.querySelector(".integ-tab-name").textContent, t.querySelector("use").getAttribute("href").split("#")[1],
    () => goIntegrations(t.id.slice(5)), t.querySelector(".integ-state").textContent);
  for (const b of $$("#settings-nav [data-cat]")) add("Ajustes", b.textContent.trim(), b.querySelector("use").getAttribute("href").split("#")[1], () => goSettings(b.dataset.cat));
  for (const p of S?.pending || []) add("Em andamento", p.title || "Aula", (PEND_LOOK[p.state] || ["pen"])[0], () => resume(p.key), PENDING[p.state]);
  for (const it of historyItems || []) add("Biblioteca", it.title, "page", () => (it.url ? window.open(it.url, "_blank") : openObsidian(it.key, "note")),
    (it.crumbs || []).join(" › "));
  for (const c of catalogData.courses) add("Cursos", c.name, "library", () => { showView("library"); openCourse(c.id); }, c.platform || "");
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
$("#open-palette")?.addEventListener("click", openPalette);
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
    showView(view);  // preserva a navegação feita enquanto o estado inicial carregava
    showStep("compose");
    await loadCatalog();
    const key = S.job.result?.key || S.job.spec?.key;
    if (S.job.status === "done" && (S.job.result?.review || S.job.result?.analysis)) {  // janela reaberta no meio
      lastSpec = S.job.kind === "process" ? S.job.spec : null;
      showView("new");
      await openUnderstanding(key, { resume: !lastSpec }).catch(fail);
      if (lastSpec?.classification) setOrg(lastSpec.classification);
    }
    if (S.job.status === "running") {
      if (S.job.kind === "analyze") { showView("new"); await openUnderstanding(key, { resume: true }).catch(fail); }
      else if (S.job.kind === "process") {
        if (S.job.spec) lastSpec = S.job.spec;
        if (lastSpec?.classification) setOrg(lastSpec.classification);
        if (S.job.kind === "process") {  // a preparação já tem a chave da aula; a publicação não
          lastUrl = S.job.key ? "/api/start" : "/api/finish";
          $("#run-h").textContent = S.job.key ? "Preparando a aula" : `Salvando o material ${destName()}`;
          showView("new");
          showStep("run");
        }
      }
      poll();
    }
  } catch (e) { fail(e); }
})();


// === MONITOR DE RECURSOS EM TEMPO REAL (LÚMEN & SISTEMA) ===
let monitorTimer = null;
let monitorData = null;

function renderMonitor(d) {
  monitorData = d;
  const pop = $("#sys-monitor-pop");
  if (!pop) return;

  const cpuName = (d.cpu?.name || "Processador")
    .replace(/@.*$/, "")
    .replace(/\((?:R|TM)\)/gi, "")
    .replace(/CPU/gi, "")
    .trim();
  const cpuCores = d.cpu?.cores_label || "";
  const cpuGhz = d.cpu?.ghz ? `${d.cpu.ghz} GHz` : "";
  const cpuSys = Math.min(100, Math.max(0, d.cpu?.system_pct || 0));
  const cpuApp = Math.min(100, Math.max(0, d.cpu?.app_pct || 0));

  const ramTotal = d.ram?.total_gb || 0;
  const ramUsed = d.ram?.used_gb || 0;
  const ramSysPct = Math.min(100, Math.max(0, d.ram?.system_pct || 0));
  const ramAppMb = d.ram?.app_mb || 0;
  const ramAppPct = Math.min(100, Math.max(0, d.ram?.app_pct || 0));

  const gpu = d.gpu;
  const gpuName = gpu ? gpu.name.replace(/NVIDIA /i, "") : "GPU Não detectada";
  const gpuPct = gpu ? gpu.gpu_pct : 0;
  const gpuTemp = gpu ? `${gpu.temp_c}°C` : "";
  const vramTotalGb = gpu ? (gpu.vram_total_mb / 1024).toFixed(1) : "0";
  const vramUsedGb = gpu ? (gpu.vram_used_mb / 1024).toFixed(1) : "0";
  const vramPct = gpu ? Math.min(100, Math.max(0, gpu.vram_pct || 0)) : 0;
  const models = gpu?.models || [];

  let html = `
    <div class="sys-monitor-hdr">
      <div class="sys-monitor-title-wrap">
        <div class="sys-monitor-title">
          <span class="sys-monitor-live-dot"></span>
          <span>Lúmen & Sistema</span>
        </div>
        <div class="sys-monitor-sub">Monitor de hardware em tempo real</div>
      </div>
      <button class="sys-monitor-close" type="button" id="close-monitor-btn" aria-label="Fechar monitor">
        <svg class="i"><use href="/icons.svg#x"/></svg>
      </button>
    </div>

    <!-- CPU Card -->
    <div class="sys-stat-card">
      <div class="sys-stat-head">
        <div class="sys-stat-label-wrap">
          <svg class="i"><use href="/icons.svg#cpu"/></svg>
          <span>CPU</span>
        </div>
        <span class="sys-stat-sep">·</span>
        <div class="sys-stat-value">${cpuSys.toFixed(0)}%</div>
      </div>
      <div class="sys-stat-subline">
        <span class="sys-stat-subline-detail" title="${d.cpu?.name || ''}">${cpuName} · ${cpuCores}${cpuGhz ? ' · ' + cpuGhz : ''}</span>
      </div>
      <div class="sys-bar-track">
        <div class="sys-bar-fill-sys" id="bar-cpu-sys"></div>
        <div class="sys-bar-fill-app" id="bar-cpu-app"></div>
      </div>
      <div class="sys-stat-badge-row">
        <span class="sys-stat-app-badge" title="Uso exclusivo do processo Lúmen"><span class="dot"></span>Lúmen: ${cpuApp.toFixed(1)}%</span>
      </div>
    </div>

    <!-- RAM Card -->
    <div class="sys-stat-card">
      <div class="sys-stat-head">
        <div class="sys-stat-label-wrap">
          <svg class="i"><use href="/icons.svg#ram"/></svg>
          <span>Memória RAM</span>
        </div>
        <span class="sys-stat-sep">·</span>
        <div class="sys-stat-value">${ramUsed.toFixed(1)} / ${ramTotal.toFixed(1)} GB</div>
      </div>
      <div class="sys-stat-subline">
        <span class="sys-stat-subline-detail">Sistema: ${ramSysPct.toFixed(0)}% em uso</span>
      </div>
      <div class="sys-bar-track">
        <div class="sys-bar-fill-sys" id="bar-ram-sys"></div>
        <div class="sys-bar-fill-app" id="bar-ram-app"></div>
      </div>
      <div class="sys-stat-badge-row">
        <span class="sys-stat-app-badge" title="Memória RAM física utilizada pelo Lúmen"><span class="dot"></span>Lúmen: ${ramAppMb.toFixed(0)} MB</span>
      </div>
    </div>

    <!-- GPU Card -->
    <div class="sys-stat-card">
      <div class="sys-stat-head">
        <div class="sys-stat-label-wrap">
          <svg class="i"><use href="/icons.svg#gpu"/></svg>
          <span>GPU</span>
        </div>
        <span class="sys-stat-sep">·</span>
        <div class="sys-stat-value">${gpu ? gpuPct + '%' : 'N/A'}${gpuTemp ? ' · ' + gpuTemp : ''}</div>
      </div>
      <div class="sys-stat-subline">
        <span class="sys-stat-subline-detail" title="${gpu ? gpu.name : ''}">${gpuName} · VRAM: ${vramUsedGb} / ${vramTotalGb} GB</span>
      </div>
      <div class="sys-bar-track">
        <div class="sys-bar-fill-sys" id="bar-gpu-vram"></div>
      </div>
      ${models.length > 0 ? `
        <div class="sys-stat-badge-row" style="margin-top: 2px;">
          <span class="sys-stat-subline-detail" style="max-width: 100%; color: var(--accent-text);">
            Modelos VRAM: ${models.map(m => m.name).join(', ')}
          </span>
        </div>
      ` : ''}
    </div>

    <!-- Motores Ativos -->
    <div class="sys-engines-section">
      <div class="sys-engines-title">Motores Ativos</div>
      <div class="sys-engines-grid">
        ${(d.engines || []).map(eng => `
          <div class="sys-engine-badge" data-active="${eng.active}">
            <div class="sys-engine-head">
              <span class="sys-engine-dot"></span>
              <span class="sys-engine-name">${eng.name}</span>
            </div>
            <span class="sys-engine-tech">${eng.tech.split('·')[1]?.trim() || eng.tech}</span>
          </div>
        `).join('')}
      </div>
    </div>

    <!-- Action: Liberar VRAM -->
    <button class="sys-vram-btn" type="button" id="btn-release-vram" title="Descarrega modelos inativos da memória de vídeo GPU">
      <svg class="i"><use href="/icons.svg#refresh"/></svg>
      <span>Liberar VRAM da GPU</span>
    </button>
  `;

  pop.innerHTML = html;

  if ($("#bar-cpu-sys")) $("#bar-cpu-sys").style.width = `${cpuSys}%`;
  if ($("#bar-cpu-app")) $("#bar-cpu-app").style.width = `${Math.max(cpuApp, 1)}%`;
  if ($("#bar-ram-sys")) $("#bar-ram-sys").style.width = `${ramSysPct}%`;
  if ($("#bar-ram-app")) $("#bar-ram-app").style.width = `${Math.max(ramAppPct, 1.5)}%`;
  if ($("#bar-gpu-vram")) $("#bar-gpu-vram").style.width = `${vramPct}%`;

  $("#close-monitor-btn")?.addEventListener("click", () => toggleMonitor(false));
  $("#btn-release-vram")?.addEventListener("click", async () => {
    const btn = $("#btn-release-vram");
    if (!btn) return;
    btn.disabled = true;
    btn.innerHTML = `<svg class="i"><use href="/icons.svg#refresh"/></svg><span>Liberando VRAM...</span>`;
    try {
      const updated = await api("/api/monitor/release-vram", {});
      toast("VRAM de modelos IA liberada com sucesso");
      renderMonitor(updated);
    } catch (e) {
      toast("Não foi possível liberar VRAM agora");
      btn.disabled = false;
    }
  });
}

async function pollMonitor() {
  const pop = $("#sys-monitor-pop");
  if (!pop || pop.hidden) return;
  try {
    const d = await api("/api/monitor");
    if (!pop.hidden) renderMonitor(d);
  } catch (err) {
    // Silencioso em caso de transição de rota
  }
}

function toggleMonitor(force) {
  const pop = $("#sys-monitor-pop");
  const btn = $("#open-monitor");
  if (!pop || !btn) return;

  const nextState = force !== undefined ? !!force : pop.hidden;
  if (nextState) {
    pop.hidden = false;
    pop.setAttribute("aria-hidden", "false");
    btn.setAttribute("aria-expanded", "true");
    btn.classList.add("active");
    if (monitorData) renderMonitor(monitorData);
    pollMonitor();
    if (monitorTimer) clearInterval(monitorTimer);
    monitorTimer = setInterval(pollMonitor, 2000);
  } else {
    pop.hidden = true;
    pop.setAttribute("aria-hidden", "true");
    btn.setAttribute("aria-expanded", "false");
    btn.classList.remove("active");
    if (monitorTimer) {
      clearInterval(monitorTimer);
      monitorTimer = null;
    }
  }
}

// Event listeners do monitor
$("#open-monitor")?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleMonitor();
});

document.addEventListener("click", (e) => {
  const pop = $("#sys-monitor-pop");
  if (!pop || pop.hidden) return;
  if (!e.target.closest("#sys-monitor-pop") && !e.target.closest("#open-monitor")) {
    toggleMonitor(false);
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const pop = $("#sys-monitor-pop");
    if (pop && !pop.hidden) toggleMonitor(false);
  }
});
