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
  const PRESETS = { 25: { focus: 25, short: 5, long: 15 }, 50: { focus: 50, short: 10, long: 20 } };
  const ICON = {
    play: '<path d="M8 5.5v13l10.5-6.5Z" class="fill"/>',
    pause: '<path d="M8.5 5.5v13M15.5 5.5v13"/>',
    reset: '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v3.8h3.8"/>',
    skip: '<path d="M6 6v12l8.5-6Z" class="fill"/><path d="M18 6v12"/>',
  };
  const svg = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
  let st = null, skew = 0, polling = null, autoPoll = false;
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

  // Estado novo (do servidor ou de outra janela). O aviso de fim sai uma vez só, na janela que viu primeiro.
  function feed(d, share = false) {
    if (!d || typeof d.now !== "number") return;
    st = d; skew = d.now - Date.now() / 1000;
    const e = d.event;
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
    const text = e.ended === "focus" ? `Foco concluído. ${NAMES[e.next]} de ${mins} min${c.auto ? " começou" : " quando quiser"}.`
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

  function draw() {
    if (!st) return;
    const s = left(), c = st.settings, label = NAMES[st.phase];
    for (const v of views) {
      v.root.dataset.phase = st.phase;
      v.root.dataset.running = String(st.running);
      v.time.textContent = clock(s);
      const icon = st.running ? "pause" : "play";
      if (v.icon !== icon) { v.icon = icon; v.play.innerHTML = svg(icon); if (v.sheetPlay) v.sheetPlay.innerHTML = svg(icon); }
      v.play.setAttribute("aria-label", st.running ? "Pausar Pomodoro" : s < st.total ? "Continuar Pomodoro" : "Iniciar Pomodoro");
      v.play.dataset.tip = v.play.getAttribute("aria-label") + " (não afeta a gravação)";
      v.time.setAttribute("aria-label", `Pomodoro: ${label}, ${clock(s)}${st.running ? "" : ", parado"}${v.sheet ? ". Abrir controles" : ""}`);
      v.root.style.setProperty("--pomo-p", st.total ? (1 - s / st.total).toFixed(4) : 0);
      if (!v.sheet || v.sheet.hidden) continue;
      v.q(".pomo-phase").textContent = st.phase === "focus" ? `${label} · ${Math.min(st.done + 1, c.cycles)} de ${c.cycles}` : label;
      v.q(".pomo-big").textContent = clock(s);
      const dots = v.q(".pomo-dots");
      if (dots.childElementCount !== c.cycles) dots.replaceChildren(...Array.from({ length: c.cycles }, () => document.createElement("i")));
      [...dots.children].forEach((b, i) => { b.dataset.on = String(i < st.done); });
      v.sheetPlay.setAttribute("aria-label", v.play.getAttribute("aria-label"));
      if (v.sheet.contains(document.activeElement) && document.activeElement.matches("input")) continue;  // digitando
      const p = v.custom ? "custom" : preset(c);
      v.sheet.querySelectorAll("[data-preset]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preset === p)));
      v.q(".pomo-custom").hidden = p !== "custom";
      for (const k of ["focus", "short", "long", "cycles"]) v.q(`[name=${k}]`).value = c[k];
      v.q("[name=auto]").setAttribute("aria-checked", String(c.auto));
      v.q("[name=sound]").setAttribute("aria-checked", String(c.sound));
    }
  }

  function sheetHTML() {
    const field = (k, label, max) => `<label>${label}<span><input name="${k}" type="number" min="1" max="${max}" inputmode="numeric">${k === "cycles" ? "" : "<small>min</small>"}</span></label>`;
    const sw = (k, label) => `<div class="pomo-row"><span id="pomo-${k}-l${views.length}">${label}</span><button type="button" class="pomo-switch" role="switch" name="${k}" aria-labelledby="pomo-${k}-l${views.length}" aria-checked="false"><span></span></button></div>`;
    return `<p class="pomo-phase"></p>
      <p class="pomo-big" aria-hidden="true"></p>
      <div class="pomo-dots" aria-hidden="true"></div>
      <div class="pomo-controls">
        <button type="button" class="pomo-btn" data-act="reset" aria-label="Reiniciar etapa" data-tip="Reiniciar (de novo: volta ao primeiro foco)">${svg("reset")}</button>
        <button type="button" class="pomo-btn main" data-act="toggle"></button>
        <button type="button" class="pomo-btn" data-act="skip" aria-label="Pular etapa" data-tip="Pular para a próxima etapa">${svg("skip")}</button>
      </div>
      <div class="pomo-presets" role="group" aria-label="Duração">
        <button type="button" data-preset="25" aria-pressed="false">25 min</button><button type="button" data-preset="50" aria-pressed="false">50 min</button><button type="button" data-preset="custom" aria-pressed="false">Personalizado</button>
      </div>
      <div class="pomo-custom" hidden>${field("focus", "Foco", 180)}${field("short", "Pausa curta", 60)}${field("long", "Pausa longa", 90)}${field("cycles", "Ciclos até a pausa longa", 12)}</div>
      ${sw("auto", "Iniciar a próxima etapa sozinho")}${sw("sound", "Som ao terminar")}
      <p class="pomo-msg" role="status">Independente da gravação: pausar aqui não pausa a captura.</p>`;
  }

  // Liga um Pomodoro a um elemento. sheet: os controles completos abrem ao clicar no tempo. dark: tema da barra.
  // beforeOpen: a janela precisa crescer antes (janela flutuante minimizada).
  function mount(el, { sheet = false, beforeOpen } = {}) {
    const root = document.createElement("div");
    root.className = "pomo";
    root.innerHTML = `<button type="button" class="pomo-time"></button><button type="button" class="pomo-play"></button>`;
    const v = { root, time: root.firstChild, play: root.lastChild, sheet: null, custom: false };
    v.q = (s) => v.sheet.querySelector(s);
    v.play.addEventListener("click", (e) => { e.stopPropagation(); act(st?.running ? "pause" : "play"); });
    if (sheet) {
      v.sheet = document.createElement("div");
      v.sheet.className = "pomo-sheet"; v.sheet.hidden = true;
      v.sheet.setAttribute("role", "dialog"); v.sheet.setAttribute("aria-label", "Pomodoro");
      v.sheet.innerHTML = sheetHTML();
      root.append(v.sheet);
      v.msg = v.q(".pomo-msg");
      v.sheetPlay = v.q("[data-act=toggle]");
      v.time.setAttribute("aria-haspopup", "dialog");
      const open = async (on) => {
        if (on && beforeOpen) await beforeOpen();
        v.sheet.hidden = !on; v.custom = false; v.icon = null;
        v.time.setAttribute("aria-expanded", String(on));
        root.classList.toggle("open", on);
        if (on) { draw(); v.sheetPlay.focus(); }
      };
      v.time.addEventListener("click", (e) => { e.stopPropagation(); open(v.sheet.hidden); });
      document.addEventListener("pointerdown", (e) => { if (!v.sheet.hidden && !root.contains(e.target)) open(false); });
      root.addEventListener("keydown", (e) => { if (e.key === "Escape" && !v.sheet.hidden) { e.stopPropagation(); open(false); v.time.focus(); } });
      v.sheet.addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b || !st) return;
        if (b.dataset.act) act(b.dataset.act === "toggle" ? (st.running ? "pause" : "play") : b.dataset.act);
        else if (b.dataset.preset === "custom") { v.custom = true; draw(); v.q("[name=focus]").focus(); }
        else if (b.dataset.preset) { v.custom = false; act("settings", PRESETS[b.dataset.preset]); }
        else if (b.matches(".pomo-switch")) act("settings", { [b.name]: b.getAttribute("aria-checked") !== "true" });
      });
      let typing;
      v.sheet.addEventListener("input", (e) => {
        const n = Number(e.target.value);
        clearTimeout(typing);
        if (!e.target.name || !Number.isFinite(n) || n < 1) return;
        typing = setTimeout(() => act("settings", { [e.target.name]: n }), 500);
      });
    } else v.time.tabIndex = -1;
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

  window.Pomodoro = { mount, feed, watch, state: () => st };
})();
