"use strict";
// Pomodoro em qualquer janela do Lumen: um timer só, guardado no servidor (lumen/pomodoro.py) com o horário em que a
// etapa termina. Aqui só se desenha o que falta (fim − agora), então janela fechada, minimizada ou travada não atrasa
// nada. As janelas abertas se atualizam na hora (BroadcastChannel) e conferem no Lumen a cada 2 s.
// Independente da gravação: nada aqui pausa ou retoma a captura.
(() => {
  const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
  const host = window.chrome?.webview;
  const channel = "BroadcastChannel" in window ? new BroadcastChannel("lumen-pomodoro") : null;
  const NAMES = { focus: "Foco", short: "Pausa curta", long: "Pausa longa" };
  // Estado à vista (status()): sempre em palavras, nunca só na cor do anel
  const LABEL = { ready: "Pronto", focus: "Foco", paused: "Pausado", short: "Pausa", long: "Pausa longa",
                  focusdone: "Foco concluído", breakdone: "Hora de focar" };
  const PRESETS = { 25: { focus: 25, short: 5, long: 15 }, 50: { focus: 50, short: 10, long: 20 } };
  const ICON = {
    play: '<path d="M8 5.5v13l10.5-6.5Z" class="fill"/>',
    pause: '<path d="M8.5 5.5v13M15.5 5.5v13"/>',
    reset: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v3.8h3.8"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" class="fill"/>',
    more: '<path d="m7 10 5 5 5-5"/>',
  };
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
  const ring = (size, r) => `<svg class="pomo-ring" viewBox="0 0 ${size} ${size}" aria-hidden="true"><circle class="trk" cx="${size / 2}" cy="${size / 2}" r="${r}"/>`
    + `<circle class="arc" cx="${size / 2}" cy="${size / 2}" r="${r}" pathLength="100"/></svg>`;
  let st = null, skew = 0, polling = null, autoPoll = false, context = "", studyEvent = 0;
  const views = [];

  async function call(body) {
    const opt = { headers: { "X-Lumen-Token": TOKEN } };
    if (body) { opt.method = "POST"; opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
    const r = await fetch("/api/pomodoro", opt);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error?.message || "Não foi possível atualizar o Pomodoro.");
    return d;
  }
  const left = () => !st ? 0 : st.running ? Math.max(0, st.ends_at - (Date.now() / 1000 + skew)) : st.left;
  const clock = (s) => { s = Math.ceil(s - 1e-3); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : String(m).padStart(2, "0")) + ":" + String(s % 60).padStart(2, "0"); };
  const preset = (c) => Object.keys(PRESETS).find((k) => ["focus", "short", "long"].every((p) => PRESETS[k][p] === c[p])) || "custom";
  // Parado no começo de uma pausa só acontece quando um foco acaba (sem início automático): “Foco concluído”
  function status(s) {
    if (st.running) return st.phase;
    if (s < st.total - .5) return "paused";
    if (st.phase !== "focus") return "focusdone";
    return st.done ? "breakdone" : "ready";
  }
  const put = (el, text) => { if (el.textContent !== text) el.textContent = text; };

  // Estado novo (do servidor ou de outra janela). O aviso de fim sai uma vez só, na janela que viu primeiro.
  function feed(d, share = false) {
    if (!d || typeof d.now !== "number") return;
    st = d; skew = d.now - Date.now() / 1000;
    const e = d.event;
    if (e?.id > studyEvent) { studyEvent = e.id; window.dispatchEvent(new CustomEvent("lumen-pomodoro", { detail: e })); }
    if (e && d.now - e.at < 90) {
      let seen = 0;
      try { seen = Number(localStorage.getItem("lumen.pomodoroEvent")) || 0; } catch {}
      if (e.id > seen) { try { localStorage.setItem("lumen.pomodoroEvent", String(e.id)); } catch {} notify(e); }
    }
    if (share) channel?.postMessage(d);
    draw();
  }
  channel?.addEventListener("message", ({ data }) => feed(data));

  function notify(e) {
    const c = st.settings, mins = c[e.next];
    const text = e.ended === "focus" ? `Sessão de foco concluída (${c.focus} min). ${NAMES[e.next]} de ${mins} min${c.auto ? " começou" : " quando quiser"}.`
      : `${NAMES[e.ended]} terminou. Hora de focar (${mins} min)${c.auto ? "" : " quando quiser"}.`;
    views.forEach((v) => { v.root.classList.remove("pomo-ended"); void v.root.offsetWidth; v.root.classList.add("pomo-ended"); });
    setTimeout(() => views.forEach((v) => v.root.classList.remove("pomo-ended")), 8000);
    if (host) host.postMessage("notify:pomodoro:" + e.id + ":" + text);  // aviso do Windows, discreto (Lumen.exe)
    else if (typeof window.toast === "function") window.toast(text);
  }

  async function act(action, settings) {
    try { feed(await call({ action, settings }), true); }
    catch (err) { views.forEach((v) => { if (v.msg) v.msg.textContent = err.message; }); }
  }
  const toggle = () => act(st?.running ? "pause" : "play");

  function draw() {
    if (!st) return;
    const s = left(), k = status(s), c = st.settings, label = LABEL[k];
    const idle = k === "focusdone" || k === "breakdone";  // a etapa seguinte ainda não começou: o tempo é o dela
    const time = clock(idle ? st.total : s), p = st.total && !idle ? (1 - s / st.total).toFixed(4) : idle && k === "focusdone" ? "1" : "0";
    const start = k === "focusdone" ? `Iniciar ${NAMES[st.phase].toLowerCase()}` : k === "ready" || k === "breakdone" ? "Iniciar foco" : "";
    const playLabel = st.running ? "Pausar" : start || "Continuar";
    for (const v of views) {
      const r = v.root;
      r.dataset.state = k; r.dataset.phase = st.phase; r.dataset.running = String(st.running);
      r.style.setProperty("--pomo-p", p);
      if (v.time) {
        put(v.clock, time); put(v.short, st.phase === "focus" ? "Foco" : "Pausa");
        put(v.label, k === "ready" ? "Iniciar" : label);  // “Pronto” já é a pílula do Lumen ao lado
        const icon = st.running ? "pause" : "play";
        if (v.icon !== icon) { v.icon = icon; v.play.innerHTML = svg(icon); }
        v.play.setAttribute("aria-label", `${playLabel} Pomodoro`);
        v.play.dataset.tip = `${playLabel} Pomodoro (não afeta a gravação)`;
        const said = `Pomodoro · ${label}${idle ? "" : ` · ${time}${st.running ? " restantes" : ""}`}`;
        v.time.setAttribute("aria-label", said + (v.sheet ? ". Abrir o Pomodoro" : ""));
        v.time.dataset.tip = said;
        if (v.total) {  // cartão (estilo Glass): “13:54 / 25:00” e o Parar, que é o “reiniciar a etapa” do painel
          put(v.total, "/ " + clock(st.total));
          v.stop.hidden = k === "ready" || idle;  // no começo da etapa, reiniciar recomeçaria a sequência: aí o Parar some
        }
      }
      if (v.sheet && !v.sheet.hidden) {
        put(v.q(".pomo-big"), time); put(v.q(".pomo-state"), label);
        put(v.q(".pomo-cycle"), st.phase === "focus" ? `Sessão ${Math.min(st.done + 1, c.cycles)} de ${c.cycles}` : `${st.done} de ${c.cycles} sessões feitas`);
        const now = typeof context === "function" ? context() : context;
        put(v.q(".pomo-ctx"), now ? `Agora: ${now}` : st.phase === "focus" ? "Sessão de foco" : "Intervalo: descanse os olhos");
        const dots = v.q(".pomo-dots");
        if (dots.childElementCount !== c.cycles) dots.replaceChildren(...Array.from({ length: c.cycles }, () => document.createElement("i")));
        [...dots.children].forEach((b, i) => { b.dataset.on = String(i < st.done); });
        const main = v.q("[data-act=toggle]");
        if (main.dataset.icon !== v.icon) { main.dataset.icon = v.icon; main.querySelector("svg")?.remove(); main.insertAdjacentHTML("afterbegin", svg(v.icon)); }
        put(main.querySelector("span"), playLabel + (start && !st.running ? ` · ${c[st.phase]} min` : ""));
        const skip = v.q("[data-act=skip]");
        skip.hidden = k === "ready" || k === "breakdone";
        put(skip, k === "focusdone" ? "Continuar focando" : st.phase === "focus" ? "Encerrar foco" : "Encerrar pausa");
        v.q("[data-act=reset]").hidden = k === "ready";
        v.q(".pomo-sec").hidden = k === "ready";
      }
      if (v.set && (!v.sheet || !v.sheet.hidden)) drawSettings(v, c);
    }
  }
  function drawSettings(v, c) {
    const box = v.set;
    if (box.contains(document.activeElement) && document.activeElement.matches("input")) return;  // digitando
    const p = v.custom ? "custom" : preset(c);
    box.querySelectorAll("[data-preset]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preset === p)));
    box.querySelector(".pomo-custom").hidden = !v.fields && p !== "custom";
    for (const k of ["focus", "short", "long", "cycles"]) box.querySelector(`[name=${k}]`).value = c[k];
    box.querySelector("[name=auto]").setAttribute("aria-checked", String(c.auto));
    box.querySelector("[name=sound]").setAttribute("aria-checked", String(c.sound));
  }

  function settingsHTML(n) {
    const field = (k, label, max) => `<label>${label}<span><input name="${k}" type="number" min="1" max="${max}" inputmode="numeric">${k === "cycles" ? "<small>focos</small>" : "<small>min</small>"}</span></label>`;
    const sw = (k, label) => `<div class="pomo-row"><span id="pomo-${k}-l${n}">${label}</span><button type="button" class="pomo-switch" role="switch" name="${k}" aria-labelledby="pomo-${k}-l${n}" aria-checked="false"><span></span></button></div>`;
    return `<div class="pomo-presets" role="group" aria-label="Duração">
        <button type="button" data-preset="25" aria-pressed="false">25 / 5</button><button type="button" data-preset="50" aria-pressed="false">50 / 10</button><button type="button" data-preset="custom" aria-pressed="false">Personalizado</button>
      </div>
      <div class="pomo-custom" hidden>${field("focus", "Sessão de foco", 180)}${field("short", "Pausa curta", 60)}${field("long", "Pausa longa", 90)}${field("cycles", "Pausa longa a cada", 12)}</div>
      ${sw("auto", "Iniciar a próxima etapa sozinho")}${sw("sound", "Som ao terminar (nunca durante a gravação)")}`;
  }
  function sheetHTML(n) {
    return `<header class="pomo-head"><strong>Pomodoro</strong><span class="pomo-cycle"></span></header>
      <div class="pomo-dial">${ring(120, 54)}<div class="pomo-dial-text"><p class="pomo-big"></p><p class="pomo-state"></p></div></div>
      <div class="pomo-dots" aria-hidden="true"></div>
      <p class="pomo-ctx"></p>
      <button type="button" class="pomo-main" data-act="toggle"><span></span></button>
      <div class="pomo-sec">
        <button type="button" class="pomo-link" data-act="skip"></button>
        <button type="button" class="pomo-btn" data-act="reset" aria-label="Reiniciar etapa" data-tip="Reiniciar a etapa (de novo: volta ao primeiro foco)">${svg("reset")}</button>
      </div>
      <details class="pomo-more"><summary>Durações e som</summary><div class="pomo-set">${settingsHTML(n)}</div></details>
      <p class="pomo-msg" role="status">Independente da gravação: pausar aqui não pausa a captura.</p>`;
  }

  function bindSettings(v) {
    v.set.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || !st) return;
      if (b.dataset.preset === "custom") { v.custom = true; draw(); v.set.querySelector("[name=focus]").focus(); }
      else if (b.dataset.preset) { v.custom = false; act("settings", PRESETS[b.dataset.preset]); }
      else if (b.matches(".pomo-switch")) act("settings", { [b.name]: b.getAttribute("aria-checked") !== "true" });
    });
    let typing;
    v.set.addEventListener("input", (e) => {
      const n = Number(e.target.value);
      clearTimeout(typing);
      if (!e.target.name || !Number.isFinite(n) || n < 1) return;
      typing = setTimeout(() => act("settings", { [e.target.name]: n }), 500);
    });
  }

  // Liga um Pomodoro a um elemento. sheet: o painel completo abre ao clicar no chip. beforeOpen: a janela precisa
  // crescer antes (janela flutuante minimizada). panel: só as durações e o som, sempre à vista (Ajustes).
  // card: também o tempo total, o Parar e a seta do painel (o estilo Glass os mostra; o clássico os esconde no CSS).
  function mount(el, { sheet = false, beforeOpen, panel = false, card = false } = {}) {
    const n = views.length;
    const root = document.createElement("div");
    const v = { root, custom: false };
    if (panel) {
      root.className = "pomo-panel";
      root.innerHTML = settingsHTML(n);
      v.set = root; v.fields = true;
      bindSettings(v);
    } else {
      root.className = "pomo";
      root.innerHTML = `<button type="button" class="pomo-time">${ring(20, 7.5)}`
        + (card ? '<svg class="pomo-ico" aria-hidden="true"><use href="/icons.svg#timer"/></svg>' : "") + `<span class="pomo-name">Pomodoro</span>`
        + `<span class="pomo-label"></span><span class="pomo-short"></span><span class="pomo-clock"></span>${card ? '<span class="pomo-total"></span>' : ""}</button>`
        + '<button type="button" class="pomo-play"></button>'
        + (card ? `<button type="button" class="pomo-stop" hidden aria-label="Parar e voltar ao início da etapa" data-tip="Parar (volta ao início da etapa; não afeta a gravação)">${svg("stop")}</button>`
          + `<button type="button" class="pomo-expand" aria-label="Abrir o Pomodoro" aria-haspopup="dialog" data-tip="Durações, sessões e som">${svg("more")}</button>` : "");
      Object.assign(v, { time: root.firstChild, play: root.querySelector(".pomo-play"), sheet: null });
      for (const k of ["clock", "label", "short"]) v[k] = root.querySelector(".pomo-" + k);
      v.play.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
      if (card) {
        Object.assign(v, { total: root.querySelector(".pomo-total"), stop: root.querySelector(".pomo-stop"), expand: root.querySelector(".pomo-expand") });
        v.stop.addEventListener("click", (e) => { e.stopPropagation(); act("reset"); });
      }
    }
    v.q = (s) => v.sheet.querySelector(s);
    if (sheet) {
      v.sheet = document.createElement("div");
      v.sheet.className = "pomo-sheet"; v.sheet.hidden = true;
      v.sheet.setAttribute("role", "dialog"); v.sheet.setAttribute("aria-label", "Pomodoro");
      v.sheet.innerHTML = sheetHTML(n);
      root.append(v.sheet);
      v.msg = v.q(".pomo-msg"); v.set = v.q(".pomo-set");
      bindSettings(v);
      v.time.setAttribute("aria-haspopup", "dialog");
      v.open = async (on) => {
        if (on && beforeOpen) await beforeOpen();
        v.sheet.hidden = !on; v.custom = false;
        v.time.setAttribute("aria-expanded", String(on));
        v.expand?.setAttribute("aria-expanded", String(on));
        root.classList.toggle("open", on);
        if (on) { draw(); v.q("[data-act=toggle]").focus(); }
      };
      v.time.addEventListener("click", (e) => { e.stopPropagation(); v.open(v.sheet.hidden); });
      v.expand?.addEventListener("click", (e) => { e.stopPropagation(); v.open(v.sheet.hidden); });
      document.addEventListener("pointerdown", (e) => { if (!v.sheet.hidden && !root.contains(e.target)) v.open(false); });
      root.addEventListener("keydown", (e) => { if (e.key === "Escape" && !v.sheet.hidden) { e.stopPropagation(); v.open(false); v.time.focus(); } });
      v.sheet.addEventListener("click", (e) => {
        const b = e.target.closest("[data-act]");
        if (b && st) b.dataset.act === "toggle" ? toggle() : act(b.dataset.act);
      });
    } else if (v.time) v.time.tabIndex = -1;
    el.append(root);
    views.push(v);
    draw();
    return v;
  }

  // Sem barra para alimentar o estado: esta janela pergunta ao Lumen (só visível; ao voltar, na hora).
  async function poll() { try { feed(await call()); } catch {} }
  function watch() {
    autoPoll = true;
    clearInterval(polling);
    polling = setInterval(() => { if (!document.hidden) poll(); }, 2000);
    poll();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && autoPoll) poll(); draw(); });
  window.addEventListener("focus", () => { if (autoPoll) poll(); });
  // Um relógio só por janela, para todos os Pomodoros dela; no fim da etapa, confere logo no Lumen.
  setInterval(() => {
    if (document.hidden || !st) return;
    draw();
    if (st.running && left() <= 0 && autoPoll) poll();
  }, 250);

  // O que o estudante está fazendo agora (texto ou função lida ao desenhar o painel; nada é guardado com o Pomodoro)
  function setContext(c) { context = c || ""; }
  const open = () => views.find((v) => v.sheet)?.open(true);
  window.Pomodoro = { mount, feed, watch, setContext, open, toggle, act, state: () => st, status: () => st && status(left()) };
})();
