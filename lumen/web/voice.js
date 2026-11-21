"use strict";
/* Voz do Lúmen (fase 6): tocar a fala que vem do servidor, a barra de fala, apertar para falar, o player com capítulos
   e a aba Integrações → Voice Studio. O navegador nunca fala com o Voice Studio (a CSP é connect-src 'self'): tudo vem
   de /api/study/voice/*. Os Estudos usam o que fica em window.lumenVoice. Tudo é montado elemento a elemento. */
(() => {
  const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const ic = (name) => window.ui.icon(name);
  const toast = (m, t) => window.ui.toast(m, t);
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    e.append(...kids.flat(Infinity).filter((x) => x != null && x !== false));
    return e;
  }
  async function api(path, body) {
    const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json", "X-Lumen-Token": TOKEN },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    let v = {};
    try { v = await r.json(); } catch { /* vazio */ }
    if (!r.ok) throw Object.assign(new Error(v.error?.message || "Não foi possível falar com o Lúmen."), { action: v.error?.action || "" });
    return v;
  }
  const say = (e) => toast([e.message, e.action].filter(Boolean).join(" "), "error");
  const url = (path, q) => `${path}?${new URLSearchParams({ ...q, t: TOKEN })}`;
  const initials = (name) => (String(name || "?").match(/\p{L}+/gu) || ["?"]).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  const kindLabel = (v) => v.engine === "chatterbox" || v.kind === "local" ? "Voz local" : v.kind === "design" ? "Criada" : "Clonada";
  const lang = (l) => ({ auto: "idioma automático", english: "en", portuguese: "pt", "portuguese (brazil)": "pt" })[String(l || "auto").toLowerCase()] || l;
  const mmss = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

  // Avatar redondo: a imagem do perfil ou as iniciais sobre o gradiente do acento. O anel (.vc-ring) segue a amplitude
  // real do áudio (--amp, pelo AnalyserNode); com movimento reduzido, fica parado.
  function avatar(v, size = "") {
    const pic = v.image && v.voice ? h("img", { src: url("/api/study/voice/image", { id: v.voice }), alt: "" }) : null;
    return h("span", { class: "vc-avatar" + (size ? " " + size : ""), "aria-hidden": "true" }, h("span", { class: "vc-ring" }), pic || h("span", { text: initials(v.name) }));
  }

  // --- tocar (WebAudio) ---------------------------------------------------------------------------------------------
  let ctx = null, analyser = null, ringEl = null, waveEl = null, raf = 0;
  function audio() {
    if (!ctx) { ctx = new AudioContext(); analyser = ctx.createAnalyser(); analyser.fftSize = 512; analyser.connect(ctx.destination); }
    if (ctx.state === "suspended" && !cur?.paused) ctx.resume();
    return ctx;
  }
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0)).buffer;
  function meter() {
    cancelAnimationFrame(raf);
    const buf = new Uint8Array(analyser.fftSize), bars = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const x of buf) sum += ((x - 128) / 128) ** 2;
      const amp = Math.min(1, Math.sqrt(sum / buf.length) * 4);
      if (ringEl) ringEl.style.setProperty("--amp", still.matches ? "0" : amp.toFixed(3));
      if (waveEl && !still.matches) {
        analyser.getByteFrequencyData(bars);
        const c = waveEl.getContext("2d"), n = 16, w = waveEl.width / n;
        c.clearRect(0, 0, waveEl.width, waveEl.height);
        c.fillStyle = getComputedStyle(waveEl).color;
        for (let i = 0; i < n; i++) {
          const v = bars[2 + i * 3] / 255, bh = Math.max(2, v * waveEl.height);
          c.fillRect(i * w + 1, (waveEl.height - bh) / 2, w - 2, bh);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
  }
  function quiet() {
    cancelAnimationFrame(raf); raf = 0;
    ringEl?.style.setProperty("--amp", "0"); ringEl?.closest(".vc-avatar")?.classList.remove("speaking");
    if (waveEl) waveEl.getContext("2d").clearRect(0, 0, waveEl.width, waveEl.height);
  }

  // Um som curto (amostra, teste): toca uma vez, com o anel no avatar de quem fala. Outro som para este.
  let clip = null;
  async function playClip(data, av) {
    stop();
    const a = audio(), buffer = await a.decodeAudioData(data instanceof ArrayBuffer ? data : b64(data));
    const src = a.createBufferSource();
    src.buffer = buffer; src.connect(analyser);
    ringEl = av?.querySelector(".vc-ring") || null; waveEl = null;
    av?.classList.add("speaking");
    clip = src;
    meter();
    return new Promise((done) => { src.onended = () => { if (clip === src) { clip = null; quiet(); } done(); }; src.start(); });
  }

  // --- a fala do chat: frases que chegam (NDJSON) e tocam em ordem, com a barra de fala -------------------------------
  let cur = null;  // a fala atual: { ctrl, queue, i, n, who, src, paused, done, target, bar }
  function stop() {
    if (clip) { try { clip.onended = null; clip.stop(); } catch { /* já parou */ } clip = null; quiet(); }
    if (!cur) return;
    const s = cur; cur = null;
    s.ctrl.abort();
    if (s.src) { s.src.onended = null; try { s.src.stop(); } catch { /* */ } }
    if (ctx?.state === "suspended") ctx.resume();
    clearMark(); quiet();
    s.bar?.remove();
    s.button?.setAttribute("aria-pressed", "false");
    s.onEnd?.();
  }
  function fold(t) { return t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  // A frase que está tocando fica destacada na resposta (CSS Custom Highlight: o texto não é mexido).
  function index(root) {
    const map = [];
    let flat = "";
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n; (n = walk.nextNode());) {
      if (n.parentElement.closest(".st-cite, pre, code")) continue;  // [S#] e código não são lidos
      for (let i = 0; i < n.data.length; i++) {
        const c = fold(n.data[i]);
        if (/[a-z0-9]/.test(c)) { flat += c; map.push([n, i]); }
      }
    }
    return { flat, map, at: 0 };
  }
  function mark(s, text) {
    if (!s.idx || !window.CSS?.highlights || !window.Highlight) return;
    const key = fold(text).replace(/[^a-z0-9]/g, "");
    if (!key) return;
    let k = s.idx.flat.indexOf(key, s.idx.at), len = key.length;
    if (k < 0) { k = s.idx.flat.indexOf(key.slice(0, 24), s.idx.at); len = Math.min(key.length, s.idx.flat.length - k); }
    if (k < 0) return clearMark();
    const [a, ai] = s.idx.map[k], [b, bi] = s.idx.map[Math.min(k + len, s.idx.map.length) - 1];
    const r = document.createRange();
    r.setStart(a, ai); r.setEnd(b, bi + 1);
    CSS.highlights.set("lumen-voice", new Highlight(r));
    s.idx.at = k + len;
  }
  function clearMark() { window.CSS?.highlights?.delete("lumen-voice"); }

  function barFor(s) {
    const live = h("span", { class: "vc-bar-state", role: "status", "aria-live": "polite" });
    const pauseBtn = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Pausar", "data-tip": "Pausar", onclick: () => togglePause() }, ic("pause"));
    const wave = h("canvas", { class: "vc-wave", width: "96", height: "22", "aria-hidden": "true" });
    const bar = h("div", { class: "vc-bar", role: "group", "aria-label": "Fala do Lúmen" },
      avatar(s.who), h("span", { class: "vc-bar-who" }, h("strong", { text: s.who.name.split(" ")[0] }), live), wave,
      h("span", { class: "vc-bar-count" }),
      pauseBtn,
      h("button", { type: "button", class: "icon-btn sm", "aria-label": "Pular frase", "data-tip": "Pular frase", onclick: () => skip() }, ic("skip")),
      h("button", { type: "button", class: "icon-btn sm", "aria-label": "Parar a fala", "data-tip": "Parar (Esc)", onclick: () => stop() }, ic("stop")));
    // sobre a caixa de mensagem quando o chat está na tela; senão (Estudar, Feynman), flutuando embaixo
    const dock = document.querySelector("[data-study] .st-dock");
    if (dock && dock.offsetParent !== null) dock.insertBefore(bar, dock.querySelector(".st-composer"));
    else document.body.append(Object.assign(bar, { className: "vc-bar floating" }));
    s.ui = { live, pauseBtn, wave, count: bar.querySelector(".vc-bar-count") };
    return bar;
  }
  function renderBar(s, state) {
    if (!s.bar) return;
    const pct = Number.isFinite(s.prep?.pct) && s.prep.pct > 0 ? ` ${Math.round(s.prep.pct)}%` : "";
    const word = { preparing: `Preparando a voz…${pct}`, loading: "preparando…", speaking: "falando", paused: "pausado" }[state];
    s.ui.live.textContent = `${word}${s.who.note ? " · " + s.who.note : ""}`;
    s.ui.count.textContent = s.n ? `frase ${Math.min(s.i + 1, s.n)} de ${s.n}` : "";
    window.ui.setIcon(s.ui.pauseBtn, s.paused ? "play" : "pause");
    s.ui.pauseBtn.setAttribute("aria-label", s.paused ? "Continuar" : "Pausar"); s.ui.pauseBtn.dataset.tip = s.ui.pauseBtn.getAttribute("aria-label");
    s.bar.classList.toggle("paused", s.paused);
  }
  function next(s) {
    if (cur !== s) return;
    const item = s.queue.shift();
    if (!item) { if (s.done) stop(); else renderBar(s, "loading"); s.src = null; return; }
    s.i = item.i;
    s.onPart?.(item.part);  // tour narrado: acende a parte do diagrama que está sendo falada
    const src = audio().createBufferSource();
    src.buffer = item.buffer; src.connect(analyser);
    src.onended = () => next(s);
    s.src = src; src.start();
    ringEl = s.bar?.querySelector(".vc-ring"); waveEl = s.ui?.wave || null;
    s.bar?.querySelector(".vc-avatar")?.classList.add("speaking");
    meter(); mark(s, item.text); renderBar(s, "speaking");
  }
  function togglePause() {
    if (!cur) return;
    cur.paused = !cur.paused;
    if (cur.paused) { ctx.suspend(); quiet(); } else { ctx.resume(); meter(); }
    renderBar(cur, cur.paused ? "paused" : "speaking");
  }
  function skip() { if (cur?.src) cur.src.stop(); }

  async function speak(text, { use = "chat", target = null, button = null, parts = null, onPart = null, onEnd = null, voice = null, language = null, temporary = false } = {}) {
    if (button && cur?.button === button) return stop();  // o mesmo "Ouvir" de novo: para
    stop();
    const s = cur = { ctrl: new AbortController(), queue: [], i: 0, n: 0, who: null, src: null, paused: false, done: false,
      target, button, idx: target ? index(target) : null, bar: null, onPart, onEnd, prep: null };
    button?.setAttribute("aria-pressed", "true");
    audio();
    try {
      const r = await fetch("/api/study/voice/say", { method: "POST", signal: s.ctrl.signal, headers: { "Content-Type": "application/json", "X-Lumen-Token": TOKEN },
        body: JSON.stringify({ text, use, ...(parts ? { parts } : {}), ...(voice ? { voice } : {}), ...(language != null ? { language } : {}), ...(temporary ? { temporary: true } : {}) }) });
      if (!r.ok) { let v = {}; try { v = await r.json(); } catch { /* */ } throw Object.assign(new Error(v.error?.message || "Não foi possível falar."), { action: v.error?.action }); }
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let k;
        while ((k = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, k); buf = buf.slice(k + 1);
          if (!line.trim() || cur !== s) continue;
          const ev = JSON.parse(line);
          // a voz ligando (o backend sem janela subindo, o modelo carregando): a barra mostra o progresso, sem erro
          if (ev.type === "preparing") { s.prep = ev; if (!s.bar) { s.who = { name: "Voz do Lúmen", voice: null }; s.bar = barFor(s); } renderBar(s, "preparing"); }
          else if (ev.type === "voice") { s.who = ev; s.bar?.remove(); s.bar = barFor(s); renderBar(s, "loading"); if (ev.note) toast(ev.note, "warning"); }
          else if (ev.type === "sentence") {
            s.n = ev.n;
            s.queue.push({ i: ev.i, part: ev.part, text: ev.text, buffer: await ctx.decodeAudioData(b64(ev.audio)) });
            if (!s.src && !s.paused) next(s); else renderBar(s, s.paused ? "paused" : "speaking");
          } else if (ev.type === "error") throw Object.assign(new Error(ev.message), { action: ev.action });
        }
      }
      s.done = true;
      if (cur === s && !s.src && !s.queue.length) stop();
    } catch (e) {
      if (e.name === "AbortError") return;
      if (cur === s) stop();
      if (e.message === "O Voice Studio está fechado." && await window.ui.confirm("Sem ele, a voz fica desligada (a voz de reserva está desligada nas Configurações → Voz).",
        { title: "O Voice Studio está fechado", ok: "Abrir o Voice Studio", cancel: "Agora não" })) openVS();
      else if (e.message !== "O Voice Studio está fechado.") say(e);
    }
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && cur && !document.querySelector("dialog[open]")) stop(); });
  // Pré-aquecer (D54): o backend e o modelo ficam prontos enquanto o texto ainda está sendo escrito. Uma vez por minuto.
  let warmedAt = 0;
  function warm(reason = "open") {
    if (Date.now() - warmedAt < 60000) return;
    warmedAt = Date.now();
    api("/api/study/voice/warm", { reason }).catch(() => {});
  }

  // --- apertar para falar -----------------------------------------------------------------------------------------
  // Segure o botão (ou a barra de espaço fora da caixa de texto) enquanto fala; ao soltar, o Python transcreve e o
  // texto entra na caixa. O microfone abre só enquanto está segurando.
  function ptt({ onText, isActive = () => true }) {
    const live = h("span", { class: "sr", role: "status", "aria-live": "polite" });
    const b = h("button", { type: "button", class: "st-ptt", "aria-label": "Apertar para falar", "aria-pressed": "false",
      "data-tip": "Segure para falar (ou segure a barra de espaço fora da caixa de texto)" }, ic("record"), live);
    let state = "idle", poll = 0;
    const set = (st, msg) => { state = st; b.dataset.state = st; b.setAttribute("aria-pressed", String(st === "listening")); live.textContent = msg || ""; };
    async function start() {
      if (state !== "idle") return;
      stop();  // a fala do Lúmen para quando o estudante começa a falar
      set("opening", "Abrindo o microfone…");
      try { await api("/api/study/voice/listen", { action: "start" }); } catch (e) { set("idle"); return say(e); }
      if (state !== "opening") return api("/api/study/voice/listen", { action: "cancel" }).catch(() => {});
      set("listening", "Ouvindo. Solte para enviar ao Lúmen.");
      const tick = async () => {
        if (state !== "listening") return;
        const r = await api("/api/study/voice/listen").catch(() => null);
        if (r) b.style.setProperty("--amp", still.matches ? "0" : Math.min(1, r.level * 3).toFixed(2));
        poll = setTimeout(tick, 150);
      };
      tick();
    }
    async function finish(cancel = false) {
      clearTimeout(poll); b.style.setProperty("--amp", "0");
      if (state === "opening") { set("idle"); return; }
      if (state !== "listening") return;
      set("working", cancel ? "" : "Transcrevendo…");
      try {
        const r = await api("/api/study/voice/listen", { action: cancel ? "cancel" : "stop" });
        set("idle", r.text ? "Transcrito." : "");
        if (r.text) onText(r.text);
      } catch (e) { set("idle"); say(e); }
    }
    b.addEventListener("pointerdown", (e) => { if (e.button === 0) { b.setPointerCapture(e.pointerId); start(); } });
    for (const ev of ["pointerup", "pointercancel"]) b.addEventListener(ev, () => finish());
    b.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); start(); } });
    b.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); finish(); } });
    b.addEventListener("click", (e) => e.preventDefault());
    const typing = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(el.tagName));
    // barra de espaço segurada fora da caixa de texto; vale só para o botão que está na tela (a aba aberta)
    document.addEventListener("keydown", (e) => {
      if (!b.isConnected) return;
      if (e.key === "Escape" && state === "listening") return finish(true);
      if (e.code !== "Space" || e.repeat || typing(document.activeElement) || !isActive() || document.querySelector("dialog[open]")) return;
      e.preventDefault(); start();
    });
    document.addEventListener("keyup", (e) => { if (b.isConnected && e.code === "Space" && state !== "idle" && !typing(document.activeElement)) { e.preventDefault(); finish(); } });
    return b;
  }

  // --- player com capítulos ---------------------------------------------------------------------------------------
  function player(meta, { onDelete } = {}) {
    const a = new Audio();
    a.preload = "metadata";
    a.src = url("/api/study/voice/file", { id: meta.id });
    const key = "vc-pos:" + meta.id;
    const playBtn = h("button", { type: "button", class: "btn sm primary vc-play", onclick: () => (a.paused ? a.play() : a.pause()).catch?.(() => {}) }, ic("play"), "Ouvir");
    const seek = h("input", { type: "range", min: "0", max: String(meta.duration || 0), step: "1", value: "0", "aria-label": "Posição", class: "vc-seek" });
    const time = h("span", { class: "vc-time t-caption", "aria-hidden": "true", text: `0:00 / ${mmss(meta.duration)}` });
    const speed = h("select", { "aria-label": "Velocidade", class: "vc-speed" }, ["0.75", "1", "1.25", "1.5", "1.75", "2"].map((v) => h("option", { value: v, text: v.replace(".", ",") + "×" })));
    speed.value = "1";
    speed.addEventListener("change", () => { a.playbackRate = parseFloat(speed.value); });
    // “Ver na aula (mm:ss)”: o tópico do resumo tem o tempo real da aula (lesson_t); abre o vídeo naquele ponto
    const watch = (c) => api("/api/study/voice/audio", { action: "watch", id: meta.id, t: c.lesson_t }).then((r) => {
      a.pause();
      toast(r.opened === "youtube" ? `Abrindo a aula em ${mmss(c.lesson_t)}.` : `A aula abriu no player do Windows: pule para ${mmss(c.lesson_t)}.`, "info");
    }).catch(say);
    const chapters = h("ol", { class: "vc-chapters", "aria-label": "Capítulos" }, (meta.chapters || []).map((c, i) =>
      h("li", { class: "vc-chapter-row" }, h("button", { type: "button", class: "vc-chapter", onclick: () => { a.currentTime = c.t; a.play().catch(() => {}); } },
        h("span", { class: "vc-chapter-t t-caption", text: mmss(c.t) }), h("span", { text: c.title || `Parte ${i + 1}` })),
        meta.kind === "lesson" && Number.isFinite(c.lesson_t) ? h("button", { type: "button", class: "btn sm ghost vc-watch", onclick: () => watch(c),
          "aria-label": `Ver na aula: ${c.title} em ${mmss(c.lesson_t)}` }, ic("play"), `Ver na aula (${mmss(c.lesson_t)})`) : null)));
    let saved = 0;
    a.addEventListener("loadedmetadata", () => { const p = parseFloat(localStorage.getItem(key) || "0"); if (p > 0 && p < a.duration - 5) a.currentTime = p; });
    a.addEventListener("timeupdate", () => {
      seek.value = String(Math.floor(a.currentTime));
      time.textContent = `${mmss(a.currentTime)} / ${mmss(a.duration || meta.duration)}`;
      const at = (meta.chapters || []).reduce((k, c, i) => (a.currentTime >= c.t ? i : k), 0);
      [...chapters.querySelectorAll(".vc-chapter")].forEach((b, i) => b.toggleAttribute("aria-current", i === at));
      if (Math.abs(a.currentTime - saved) > 3) { saved = a.currentTime; try { localStorage.setItem(key, String(saved)); } catch { /* */ } }
    });
    a.addEventListener("play", () => { window.ui.setIcon(playBtn, "pause"); playBtn.lastChild.textContent = "Pausar"; });
    a.addEventListener("pause", () => { window.ui.setIcon(playBtn, "play"); playBtn.lastChild.textContent = "Ouvir"; });
    a.addEventListener("ended", () => { try { localStorage.removeItem(key); } catch { /* */ } });
    seek.addEventListener("input", () => { a.currentTime = parseFloat(seek.value); });
    const who = { name: meta.voice, voice: null, kind: meta.engine === "chatterbox" ? "local" : "clone", engine: meta.engine };
    const sec = h("section", { class: "vc-player", "aria-label": `Áudio: ${meta.title}` },
      h("header", { class: "vc-player-head" }, avatar(who, "sm"),
        h("div", {}, h("strong", { text: meta.title }), h("p", { class: "t-caption muted", text: `${meta.voice} · ${kindLabel(who).toLowerCase()} · ${mmss(meta.duration)}` }))),
      meta.note ? h("p", { class: "t-caption vc-note" }, ic("info"), h("span", { text: meta.note })) : null,
      h("div", { class: "vc-controls" }, playBtn, seek, time, speed),
      meta.chapters?.length > 1 ? chapters : null,
      h("div", { class: "vc-player-foot" },
        h("a", { class: "btn sm ghost", href: url("/api/study/voice/file", { id: meta.id }), download: `${meta.title}.m4a` }, ic("download"), "Baixar"),
        h("button", { type: "button", class: "btn sm ghost", onclick: () => api("/api/study/voice/audio", { action: "reveal", id: meta.id }).catch(say) }, ic("folder"), "Mostrar na pasta"),
        onDelete ? h("button", { type: "button", class: "btn sm ghost", onclick: async () => {
          if (!(await window.ui.confirm("O arquivo de áudio sai do PC. O roteiro continua salvo, e dá para gerar de novo.", { title: "Apagar o áudio?", ok: "Apagar", danger: true }))) return;
          a.pause(); await api("/api/study/voice/audio", { action: "delete", id: meta.id }).then(onDelete).catch(say);
        } }, ic("trash"), "Apagar") : null));
    sec.vcAudio = a;
    new MutationObserver((_, obs) => { if (!sec.isConnected) { a.pause(); obs.disconnect(); } }).observe(document.body, { childList: true, subtree: true });
    return sec;
  }
  // Gerar um áudio longo (fila de tarefas): o andamento aparece no status global; ao terminar, avisa (evento lumen-audio).
  async function make(body) {
    try { await api("/api/study/voice/make", body); } catch (e) { say(e); return false; }
    toast("O áudio está sendo gerado em segundo plano. O andamento aparece no topo.", "info");
    if (typeof window.poll === "function") window.poll(); else if (typeof poll === "function") poll();  // eslint-disable-line no-undef
    return true;
  }

  // O resumo em áudio de uma aula (Biblioteca e resultado): pronto → o player num diálogo; senão, gera pela fila.
  async function lessonAudio(key, title) {
    let r;
    try { r = await api("/api/study/voice/audios?" + new URLSearchParams({ key })); } catch (e) { return say(e); }
    if (!r.audio) {
      if (await window.ui.confirm(`O Lúmen lê o resumo e os tópicos que a aula já tem, sem chamar a IA de novo. A placa de vídeo fica ocupada por alguns minutos.`,
        { title: `Gerar o resumo em áudio de “${title}”?`, ok: "Gerar o áudio" })) make({ kind: "lesson", key });
      return;
    }
    const dlg = h("dialog", { class: "dlg vc-dlg", "aria-label": `Resumo em áudio: ${title}` },
      h("div", { class: "dlg-head" }, h("h2", { class: "t-h2", text: "Resumo em áudio" }),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Fechar", "data-tip": "Fechar", onclick: () => dlg.close() }, ic("x"))),
      h("div", { class: "dlg-body" }, player(r.audio, { onDelete: () => dlg.close() })),
      h("div", { class: "dlg-foot" }, h("button", { type: "button", class: "btn ghost", onclick: () => { dlg.close(); make({ kind: "lesson", key }); } }, ic("refresh"), "Gerar de novo")));
    dlg.addEventListener("close", () => { dlg.querySelector(".vc-player")?.vcAudio?.pause(); dlg.remove(); });
    document.body.append(dlg);
    dlg.showModal();
  }

  // --- uma linha de voz (galeria e Configurações) -------------------------------------------------------------------
  function voiceRow(v, { isDefault, onDefault, onEdit } = {}) {
    const who = { ...v, voice: v.id };
    const av = avatar(who);
    const test = h("button", { type: "button", class: "btn sm", onclick: async () => {
      test.disabled = true; test.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), "Gerando…");
      try {
        const r = await api("/api/study/voice/test", { voice: v.id });
        if (r.who.note) toast(r.who.note, "warning");  // nunca troca de voz em silêncio (a reserva, uma voz que sumiu)
        await playClip(r.audio, av);
      } catch (e) { say(e); }
      finally { test.disabled = false; test.replaceChildren(ic("sparkle"), "Testar"); }
    } }, ic("sparkle"), "Testar");
    const ref = h("button", { type: "button", class: "icon-btn sm", "aria-label": `Ouvir a referência de ${v.name}`, "data-tip": "Ouvir a referência", onclick: async () => {
      if (clip && av.classList.contains("speaking")) return stop();
      try { const r = await fetch(url("/api/study/voice/sample", { id: v.id })); if (!r.ok) throw new Error("A referência não carregou."); await playClip(await r.arrayBuffer(), av); } catch (e) { say(e); }
    } }, ic("play"));
    return h("li", { class: "vc-voice" + (isDefault ? " is-default" : "") }, av,
      h("div", { class: "vc-voice-main" }, h("strong", { class: "vc-voice-name", text: v.name }),
        h("span", { class: "vc-voice-meta t-caption" }, h("span", { class: "badge", "data-tone": "" }, kindLabel(v)), ` ${lang(v.language)}`,
          v.demo ? " · demonstração" : "", isDefault ? h("span", { class: "badge", "data-tone": "ok" }, ic("check"), "Padrão") : null)),
      h("div", { class: "vc-voice-actions" }, ref, test,
        !isDefault && onDefault ? h("button", { type: "button", class: "btn sm ghost", onclick: () => onDefault(v) }, ic("check"), "Usar como padrão") : null,
        onEdit ? h("button", { type: "button", class: "icon-btn sm", "aria-label": `Editar ${v.name} no Voice Studio`, "data-tip": "Editar no Voice Studio", onclick: onEdit }, ic("external")) : null));
  }

  // --- Integrações → Voice Studio -----------------------------------------------------------------------------------
  let panel = null, timer = 0, ids = "", machineTimer = 0, modelsTimer = 0, tierPick = null;
  async function openVS() {
    try { await api("/api/voicestudio/open", {}); toast("Abrindo o Voice Studio…", "info"); refreshStatus(true); } catch (e) { say(e); }
  }
  // O estado (D53): pronto em segundo plano (o Lúmen subiu, sem janela), pronto com o app aberto, preparando, ou
  // desligado e ligando sozinho quando precisar. `short` é o selo da aba.
  function statusTone(st, short = false) {
    const vs = st.voicestudio || st, b = vs.backend || {}, auto = st.settings?.vs_autostart !== false;
    const pct = Number.isFinite(b.pct) && b.pct > 0 ? ` ${Math.round(b.pct)}%` : "";
    if (!vs.installed) return ["warn", "alert", "Não instalado"];
    if (vs.foreign) return ["warn", "alert", short ? "Porta ocupada" : "A porta do Voice Studio está ocupada por outro programa"];
    if (b.phase === "starting" || b.phase === "loading" || vs.model?.loading) return ["busy", "clock", short ? "Preparando" : `Preparando a voz…${pct}`];
    if (vs.running) return ["ok", "check", short ? "Pronto" : vs.owner === "lumen" ? "Pronto (rodando em segundo plano)" : vs.app_open ? "Pronto (o app está aberto)" : "Pronto"];
    if (b.phase === "failed") return ["warn", "alert", short ? "Não ligou" : "A voz não ligou"];
    return auto ? ["", "power", short ? "Desligado" : "Desligado, liga sozinho quando precisar"] : ["warn", "alert", "Fechado"];
  }
  const TIERS = [["fast", "Rápido"], ["balanced", "Equilibrado"], ["quality", "Qualidade"], ["max", "Máximo"], ["auto", "Automático"]];
  const ROLE_ICON = { tts: "volume", asr: "wave", translation: "book", dictation: "pen" };
  const gb = (x) => (x == null ? "—" : `${Number(x).toFixed(Number(x) < 10 ? 1 : 0).replace(".", ",")} GB`);
  const ALSO = "Isto muda também no Voice Studio.";
  const meterEl = (label, used, total, detail) => {
    const pct = total ? Math.max(0, Math.min(100, (used / total) * 100)) : 0, fill = h("span");
    fill.style.width = `${pct.toFixed(1)}%`;
    return h("div", { class: "vc-meter-row" }, h("span", { class: "vc-meter-label t-sm", text: label }),
      h("span", { class: "vc-meter", role: "meter", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": String(total || 0), "aria-valuenow": String(used || 0),
        "data-tone": pct > 90 ? "danger" : pct > 75 ? "warn" : "" }, fill),
      h("span", { class: "vc-meter-num t-caption", text: detail }));
  };

  // Modelos de voz (D55): os pacotes da tela do Voice Studio, os modelos, os motores, a transcrição do Lúmen e a pasta.
  async function renderModels() {
    clearTimeout(modelsTimer);
    const box = panel?.querySelector(".vc-models");
    if (!box || panel.hidden || panel.offsetParent === null) return;
    let r;
    try { r = await api("/api/study/voice/models"); } catch (e) { box.replaceChildren(h("p", { class: "muted t-sm", text: e.message })); return; }
    renderQuality(r);
    if (!r.running) {
      box.replaceChildren(h("p", { class: "callout" }, ic("info"), h("span", { text: "Os modelos aparecem com a voz ligada." }),
        h("button", { type: "button", class: "btn sm", onclick: async (ev) => { ev.currentTarget.disabled = true; await api("/api/study/voice/models", { action: "start" }).catch(say); refreshStatus(true); setTimeout(renderModels, 3000); } }, ic("power"), "Ligar a voz agora")),
        lumenAsr(r.lumen_asr));
      return;
    }
    const c = r.catalog, rows = Object.fromEntries(c.models.map((m) => [m.repo_id, m]));
    const tier = tierPick || c.tier || "balanced", shown = tier === "auto" ? (c.resolved || "balanced") : tier, pack = c.packs[shown] || { models: [], missing: [] };
    const jobs = (c.jobs || []).filter((j) => j.state !== "failed");
    const seg = h("div", { class: "vc-seg", role: "radiogroup", "aria-label": "Pacote de modelos" }, TIERS.map(([id, label]) =>
      h("button", { type: "button", role: "radio", "aria-checked": String(id === tier), tabindex: id === tier ? "0" : "-1",  // uma parada de Tab; as setas trocam
        class: id === c.tier ? "is-active" : "", onclick: () => { tierPick = id; renderModels(); } }, label)));
    seg.addEventListener("keydown", (e) => {
      const k = TIERS.findIndex(([id]) => id === tier), d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (d) { e.preventDefault(); tierPick = TIERS[(k + d + TIERS.length) % TIERS.length][0]; renderModels().then(() => panel.querySelector('.vc-seg [aria-checked="true"]')?.focus()); }
    });
    const card = (m) => h("li", { class: "vc-model" + (m.installed ? " is-installed" : "") },
      h("span", { class: "vc-model-icon", "aria-hidden": "true" }, ic(ROLE_ICON[String(m.role || "").toLowerCase()] || "cpu")),
      h("span", { class: "vc-model-main" }, h("strong", { class: "vc-model-name", text: m.label }),
        h("span", { class: "t-caption muted" }, `${String(m.role || "").toUpperCase()} · ${gb(m.size_gb)}`, m.license ? ` · ${m.license}` : "",
          m.personal ? h("span", { class: "badge", "data-tone": "warn" }, "uso pessoal") : null)),
      jobs.some((j) => j.repo_id === m.repo_id) ? h("span", { class: "spinner", "aria-label": "Baixando" })
        : m.installed ? h("span", { class: "vc-model-ok", "aria-label": "Instalado" }, ic("check")) : h("span", { class: "t-caption muted", text: "Baixar" }));
    const missingGb = pack.download_gb || 0, label = TIERS.find(([id]) => id === tier)[1];
    const useBtn = h("button", { type: "button", class: "btn sm primary", disabled: jobs.length > 0, onclick: async () => {
      const msg = pack.missing.length ? `Baixa ${gb(missingGb)} para a pasta dos modelos (${r.catalog.models_dir?.effective || "a pasta do Voice Studio"}), com ${gb(c.disk_free_gb)} livres hoje. ${ALSO}` : `O Voice Studio passa a usar o nível ${label}. ${ALSO}`;
      if (!(await window.ui.confirm(msg, { title: `Usar o pacote ${label}?`, ok: pack.missing.length ? `Baixar ${gb(missingGb)}` : "Usar" }))) return;
      try { await api("/api/study/voice/models", { action: "tier", tier, confirm: true }); toast(`Pacote ${label} escolhido.`, "success"); tierPick = null; renderModels(); } catch (e) { say(e); }
    } }, ic(pack.missing.length ? "download" : "check"), pack.missing.length ? `Instalar pacote ${label} · ${gb(missingGb)}` : tier === c.tier ? `O pacote ${label} está ativo` : `Usar pacote ${label}`);
    if (tier === c.tier && !pack.missing.length) useBtn.disabled = true;
    const jobRows = jobs.map((j) => {
      const pct = j.total_bytes ? Math.round((100 * (j.bytes_done || 0)) / j.total_bytes) : null, fill = h("span");
      if (pct != null) fill.style.width = `${pct}%`;
      return h("li", { class: "vc-job" }, h("span", { class: "t-sm", text: rows[j.repo_id]?.label || j.repo_id }),
        h("span", { class: "progress" + (pct == null ? " indeterminate" : "") }, fill),
        h("span", { class: "t-caption muted", text: j.state === "cancelling" ? "cancelando…" : pct != null ? `${pct}%${j.eta_seconds ? " · " + mmss(j.eta_seconds) : ""}` : "começando…" }),
        j.state === "downloading" ? h("button", { type: "button", class: "btn sm ghost", onclick: () => api("/api/study/voice/models", { action: "cancel", repo: j.repo_id }).then(renderModels).catch(say) }, "Cancelar") : null);
    });
    const all = c.models.filter((m) => m.installed || m.curated);
    const allRows = all.map((m) => h("li", { class: "vc-model-row" }, h("span", { class: "t-sm" }, h("strong", { text: m.label }),
      h("span", { class: "t-caption muted", text: ` · ${gb(m.size_gb)}${m.license ? " · " + m.license : ""}${m.personal ? " · uso pessoal (CC-BY-NC)" : ""}` })),
      m.installed ? h("button", { type: "button", class: "btn sm ghost", onclick: async () => {
        const core = m.repo_id === "k2-fsa/OmniVoice";
        if (!(await window.ui.confirm(`${core ? "É o modelo da voz do Lúmen: a voz para de funcionar até baixar de novo. " : ""}Libera ${gb(m.size_gb)}. ${ALSO}`, { title: `Remover ${m.label}?`, ok: "Remover", danger: true }))) return;
        try { await api("/api/study/voice/models", { action: "remove", repo: m.repo_id, confirm: true }); toast("Modelo removido.", "success"); renderModels(); } catch (e) { say(e); }
      } }, ic("trash"), "Remover") : h("button", { type: "button", class: "btn sm", onclick: async () => {
        if (!(await window.ui.confirm(`Baixa ${gb(m.size_gb)} para a pasta dos modelos. ${ALSO}`, { title: `Baixar ${m.label}?`, ok: "Baixar" }))) return;
        try { await api("/api/study/voice/models", { action: "install", repo: m.repo_id, confirm: true }); renderModels(); } catch (e) { say(e); }
      } }, ic("download"), "Baixar")));
    box.replaceChildren(...[  // replaceChildren não pula null (o h() pula): filtra aqui
      seg,
      h("ul", { class: "vc-model-grid", "aria-label": `Modelos do pacote ${label}` }, pack.models.map((id) => card(rows[id]))),
      jobRows.length ? h("ul", { class: "vc-jobs", "aria-live": "polite", "aria-label": "Downloads" }, jobRows) : null,
      h("div", { class: "vc-pack-foot" }, h("span", { class: "t-caption muted", text: `${pack.models.length} modelos · ${gb(pack.total_gb)} · ${pack.missing.length ? gb(missingGb) + " para baixar" : "tudo instalado"} · ${gb(c.disk_free_gb)} livres no disco dos modelos` }), useBtn),
      h("p", { class: "field-hint" }, ic("info"), h("span", { text: ` O pacote vale para o que você gera no próprio Voice Studio. A fala do Lúmen usa a qualidade escolhida abaixo, pedido a pedido. ${ALSO}` })),
      h("details", { class: "vc-more" }, h("summary", { text: "Todos os modelos" }), h("ul", { class: "vc-model-list" }, allRows)),
      engines(r.engines), lumenAsr(r.lumen_asr), folder(r)].filter(Boolean));
    if (jobs.length) modelsTimer = setTimeout(renderModels, 2000);
  }
  function engines(e) {
    const fam = (key, title, need) => {
      const f = e[key], sel = h("select", { "aria-label": title }, f.engines.map((x) => {
        const warn = key === "tts" ? [x.cloning ? "" : "não clona", x.portuguese === false ? "só outros idiomas" : ""].filter(Boolean).join(", ") : "";
        return h("option", { value: x.id, disabled: !x.available, text: `${x.name}${warn ? " (" + warn + ")" : ""}${x.available ? "" : " · indisponível"}` });
      }));
      sel.value = f.active;
      sel.addEventListener("change", async () => {
        const x = f.engines.find((y) => y.id === sel.value);
        if (need && (!x.cloning || x.portuguese === false) && !(await window.ui.confirm(`${x.name} ${!x.cloning ? "não clona vozes" : "não fala português"}: a voz do Jhonny não funciona com ele. ${ALSO}`, { title: "Trocar o motor de voz?", ok: "Trocar mesmo assim" }))) { sel.value = f.active; return; }
        try { await api("/api/study/voice/models", { action: "engine", family: key, id: sel.value }); toast("Motor trocado.", "success"); renderModels(); } catch (err) { sel.value = f.active; say(err); }
      });
      const off = f.engines.filter((x) => !x.available);
      return h("div", { class: "vc-engine" }, h("label", { class: "field" }, title, sel, h("span", { class: "field-hint", text: ALSO })),
        off.length ? h("details", { class: "vc-more" }, h("summary", { text: `Indisponíveis (${off.length})` }), h("ul", { class: "vc-model-list" }, off.map((x) =>
          h("li", { class: "vc-model-row is-off" }, h("span", { class: "t-sm" }, h("strong", { text: x.name }), h("span", { class: "t-caption muted", text: x.reason ? " · " + x.reason : "" })),
            x.one_click ? h("button", { type: "button", class: "btn sm", onclick: async () => {
              if (!(await window.ui.confirm(`O Voice Studio baixa e instala ${x.name} (alguns GB, no disco dos modelos). ${ALSO}`, { title: `Instalar ${x.name}?`, ok: "Instalar" }))) return;
              try { await api("/api/study/voice/models", { action: "engine_install", id: x.id, confirm: true }); toast("Instalação iniciada no Voice Studio.", "info"); } catch (err) { say(err); }
            } }, ic("download"), "Instalar") : null)))) : null);
    };
    return h("div", { class: "vc-engines" }, h("h4", { class: "eyebrow", text: "Motores" }),
      fam("tts", "Motor de voz", true), fam("asr", "Motor de transcrição do Voice Studio", false));
  }
  function lumenAsr(rows) {
    return h("div", { class: "vc-asr" }, h("h4", { class: "eyebrow", text: "Transcrição do Lúmen" }),
      h("p", { class: "field-hint", text: "É o Whisper do próprio Lúmen (não o do Voice Studio). O modelo segue a qualidade de Ajustes → Transcrição." }),
      h("ul", { class: "vc-model-list" }, (rows || []).map((x) => h("li", { class: "vc-model-row" },
        h("span", { class: "t-sm" }, h("strong", { text: `Whisper ${x.name}` }), h("span", { class: "t-caption muted", text: ` · ${x.uses.join(" e ")} · ${x.size || ""}${x.vram_gb ? " · até " + gb(x.vram_gb) + " de VRAM" : ""}${x.loaded ? " · carregado" : ""}` }))))));
  }
  function folder(r) {
    const d = r.catalog.models_dir || {}, onD = /^d:/i.test(d.effective || "");
    return h("div", { class: "vc-folder" }, h("h4", { class: "eyebrow", text: "Pasta dos modelos" }),
      h("p", { class: "t-sm" }, h("code", { text: d.effective || "—" }), r.storage?.models_bytes ? ` · ${gb(r.storage.models_bytes / 1e9)}` : ""),
      h("div", { class: "st-source-actions" },
        !onD ? h("button", { type: "button", class: "btn sm", onclick: moveDialog }, ic("move"), "Mover para o D:") : null,
        onD && r.move_old ? h("button", { type: "button", class: "btn sm", onclick: moveDialog }, ic("trash"), "Apagar a cópia antiga no C:") : null,
        r.storage?.temp_bytes ? h("button", { type: "button", class: "btn sm ghost", onclick: async () => {
          if (!(await window.ui.confirm(`Apaga os arquivos temporários do Voice Studio (${gb(r.storage.temp_bytes / 1e9)}). Vozes, histórico e modelos ficam. ${ALSO}`, { title: "Limpar temporários do Voice Studio?", ok: "Limpar" }))) return;
          try { await api("/api/study/voice/models", { action: "temp_clear", confirm: true }); toast("Temporários limpos.", "success"); renderModels(); } catch (e) { say(e); }
        } }, ic("trash"), `Limpar temporários (${gb(r.storage.temp_bytes / 1e9)})`) : null));
  }

  // Mover os modelos para o D: (D55). O Voice Studio só aceita a pasta nova escolhida na janela dele: o Lúmen copia e
  // confere; o estudante escolhe a pasta lá; depois, o Lúmen apaga a cópia antiga, com confirmação.
  async function moveDialog() {
    let st;
    try { st = await api("/api/study/voice/move"); } catch (e) { return say(e); }
    const body = h("div", { class: "dlg-body vc-move" }), live = h("p", { class: "t-sm", role: "status", "aria-live": "polite" });
    const dlg = h("dialog", { class: "dlg vc-form-dlg", "aria-label": "Mover os modelos do Voice Studio para o D:" },
      h("div", { class: "dlg-head" }, h("h2", { class: "t-h2", text: "Mover os modelos para o D:" }),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Fechar", "data-tip": "Fechar", onclick: () => dlg.close() }, ic("x"))), body);
    let t = 0;
    const draw = () => {
      const copying = st.phase === "copying", copied = st.phase === "copied" || st.using_new, size = st.size_gb || 0;
      live.textContent = copying ? `Copiando e conferindo… ${Math.round((100 * (st.done || 0)) / (st.total || 1))}%` : st.phase === "failed" ? `A cópia parou: ${st.error}` : copied ? "Cópia conferida, arquivo a arquivo." : "";
      body.replaceChildren(
        h("p", {}, `De `, h("code", { text: st.source || "—" }), ` (${gb(size)}) para `, h("code", { text: st.to }), "."),
        h("ul", { class: "vc-move-disk t-sm" }, h("li", { text: `C: ${gb(st.free_c_gb)} livres hoje → cerca de ${gb((st.free_c_gb || 0) + size)} depois.` }),
          h("li", { text: `D: ${gb(st.free_d_gb)} livres hoje → cerca de ${gb((st.free_d_gb || 0) - size)} depois.` })),
        h("ol", { class: "vc-move-steps" },
          h("li", {}, h("strong", { text: "Copiar e conferir. " }), "O Lúmen copia cada arquivo e confere pelo conteúdo. Nada é apagado nesta etapa.",
            h("div", {}, h("button", { type: "button", class: "btn sm primary", disabled: copying || copied || !st.running, onclick: async () => {
              if (!(await window.ui.confirm(`Copia ${gb(size)} para o D:. Leva alguns minutos; a voz continua funcionando.`, { title: "Copiar os modelos?", ok: "Copiar" }))) return;
              try { st = await api("/api/study/voice/move", { action: "copy", confirm: true }); poll(); } catch (e) { say(e); }
            } }, ic("copy"), "Copiar e conferir"))),
          h("li", {}, h("strong", { text: "Escolher a pasta no Voice Studio. " }), "Em Configurações → Armazenamento → Pasta dos modelos, escolha ", h("code", { text: st.to }),
            " e reinicie o app. O Voice Studio só aceita essa troca pela janela dele.",
            h("div", {}, h("button", { type: "button", class: "btn sm", disabled: !copied, onclick: () => api("/api/study/voice/move", { action: "open_app" }).catch(say) }, ic("external"), "Abrir o Voice Studio"))),
          h("li", {}, h("strong", { text: "Apagar a cópia antiga. " }), st.using_new ? "O Voice Studio já usa a pasta nova." : "Fica disponível quando o Voice Studio passar a usar a pasta nova.",
            h("div", {}, h("button", { type: "button", class: "btn sm danger", disabled: !st.using_new || !st.old || st.phase === "done", onclick: async () => {
              if (!(await window.ui.confirm(`Apaga a pasta antiga “${st.old || "?"}” (${gb(size)}). Antes, o Lúmen confere de novo que cada arquivo está na pasta nova, no D:, que fica.`, { title: "Apagar a cópia antiga?", ok: "Apagar", danger: true }))) return;
              try { st = await api("/api/study/voice/move", { action: "delete_old", confirm: true }); toast("Cópia antiga apagada.", "success"); draw(); } catch (e) { say(e); }
            } }, ic("trash"), "Apagar a cópia antiga")))),
        live);
    };
    // enquanto o diálogo está aberto: o progresso da cópia e, depois, quando o Voice Studio passa a usar a pasta nova
    const poll = async () => { clearTimeout(t); try { st = await api("/api/study/voice/move"); } catch { return; } if (!dlg.open) return; draw(); t = setTimeout(poll, st.phase === "copying" ? 1500 : 3000); };
    dlg.addEventListener("close", () => { clearTimeout(t); dlg.remove(); renderModels(); });
    document.body.append(dlg);
    draw();
    dlg.showModal();
    t = setTimeout(poll, st.phase === "copying" ? 1500 : 3000);
  }

  // Qualidade da fala do Lúmen (D56): passos por pedido, sem mexer no nível global do Voice Studio.
  function renderQuality(r) {
    const box = panel?.querySelector(".vc-quality");
    if (!box) return;
    const sel = (key, label, hint) => {
      const s = h("select", { "aria-label": label }, TIERS.slice(0, 4).map(([id, l]) => h("option", { value: id, text: `${l} (${r.steps[id]} passos)` })));
      s.value = r.quality[key === "chat_quality" ? "chat" : "long"];
      s.addEventListener("change", async () => { try { await api("/api/study/settings", { voice: { [key]: s.value } }); toast("Qualidade salva.", "success"); } catch (e) { say(e); } });
      return h("label", { class: "field" }, label, s, h("span", { class: "field-hint", text: hint }));
    };
    box.replaceChildren(sel("chat_quality", "Fala do chat", "Medido neste PC (frase de chat, modelo quente): 8 passos 1,9 s até o 1º som, 12 passos 2,2 s, 16 passos 2,7 s. Erro de palavras de 0 a 1%."),
      sel("long_quality", "Áudios longos (resumo e revisão)", "Gerados em segundo plano: mais passos custam tempo, não memória (0,27 s por segundo de fala com 8 passos, 0,39 com 16, 0,68 com 32)."));
  }

  // Esta máquina (D59): só com a aba aberta, a cada 5 s.
  async function renderMachine() {
    clearTimeout(machineTimer);
    const box = panel?.querySelector(".vc-machine");
    if (!box || panel.hidden || panel.offsetParent === null) return;  // fora da tela: para (volta ao abrir a aba)
    let m;
    try { m = await api("/api/study/voice/machine"); } catch { machineTimer = setTimeout(renderMachine, 5000); return; }
    const g = m.gpu, v = m.vram, ram = m.ram, last = m.last || {};
    const parts = [v.ollama != null && `Ollama ${gb(v.ollama).replace(" GB", "")}`, v.voicestudio != null && `Voz ${gb(v.voicestudio).replace(" GB", "")}`, v.lumen && `Lúmen ${gb(v.lumen).replace(" GB", "")}`].filter(Boolean);
    box.replaceChildren(...[
      g ? meterEl("Placa", g.used_gb, g.total_gb, `${gb(g.used_gb).replace(" GB", "")}/${gb(g.total_gb)}${parts.length ? " (" + parts.join(" · ") + ")" : ""}`) : h("p", { class: "muted t-sm", text: "A placa não respondeu ao nvidia-smi." }),
      ram ? meterEl("RAM", ram[1] - ram[0], ram[1], `${gb(ram[1] - ram[0]).replace(" GB", "")}/${gb(ram[1])}`) : null,
      h("p", { class: "vc-disks t-sm" }, Object.entries(m.disks || {}).map(([d, free]) => h("span", { text: `${d} ${gb(free)} livres` }))),
      h("p", { class: "t-caption muted", text: last.first_s != null ? `Último: 1º som ${String(last.first_s).replace(".", ",")} s${last.rtf ? " · " + String(last.rtf).replace(".", ",") + " s por s de fala" : ""}${last.steps ? " · " + last.steps + " passos" : ""}` : "Último: a voz ainda não falou nesta sessão." }),
      m.advice?.length ? h("ul", { class: "vc-advice" }, m.advice.map((a) => h("li", { class: "callout" }, ic("info"), h("span", { text: a })))) : null].filter(Boolean));
    machineTimer = setTimeout(renderMachine, 5000);
  }

  // Criar voz para personagem (D58): a descrição vira as tags do OmniVoice; a voz só é criada no clique, com "(Lúmen)".
  async function designDialog() {
    const name = h("input", { type: "text", maxlength: "50", placeholder: "Cliente cético", "aria-label": "Nome da voz" });
    const desc = h("textarea", { rows: 2, maxlength: "300", placeholder: "cliente cético, homem, 40 anos, voz grave", "aria-label": "Descrição da voz" });
    const langSel = h("select", { "aria-label": "Idioma da prévia" }, h("option", { value: "pt", text: "Português" }), h("option", { value: "en", text: "Inglês" }));
    const tags = h("p", { class: "t-sm", "aria-live": "polite" }), av = avatar({ name: "?" });
    let parsed = null;
    desc.addEventListener("input", () => { parsed = null; tags.textContent = ""; });  // descrição nova: tags novas
    const understand = async () => {
      if (!desc.value.trim()) return toast("Descreva a voz.", "warning");
      try { parsed = await api("/api/study/voice/design", { action: "describe", text: desc.value }); }
      catch (e) { return say(e); }
      tags.replaceChildren(h("strong", { text: "Tags: " }), parsed.instruct || "nenhuma reconhecida", parsed.unmatched?.length ? h("span", { class: "muted", text: ` · não entendi: ${parsed.unmatched.join(", ")}` }) : "");
      return parsed;
    };
    const dlg = h("dialog", { class: "dlg vc-form-dlg", "aria-label": "Criar voz para personagem" },
      h("div", { class: "dlg-head" }, h("h2", { class: "t-h2", text: "Criar voz para personagem" }),
        h("button", { type: "button", class: "icon-btn", "aria-label": "Fechar", "data-tip": "Fechar", onclick: () => dlg.close() }, ic("x"))),
      h("div", { class: "dlg-body vc-design" },
        h("p", { class: "muted t-sm", text: "Para o Treino falado: um cliente, um negociador, uma recrutadora. A voz é criada pelo Voice Studio a partir da descrição, sem clonar ninguém." }),
        h("label", { class: "field" }, "Nome", name), h("label", { class: "field" }, "Descrição", desc), h("label", { class: "field" }, "Idioma da prévia", langSel),
        h("div", { class: "vc-test" }, av, tags)),
      h("div", { class: "dlg-foot" },
        h("button", { type: "button", class: "btn ghost", onclick: understand }, ic("sparkle"), "Entender a descrição"),
        h("button", { type: "button", class: "btn", onclick: async (ev) => {
          const b = ev.currentTarget;
          if (!parsed && !(await understand())) return;
          b.disabled = true;
          try { const r = await api("/api/study/voice/design", { action: "preview", instruct: parsed.instruct || "", language: langSel.value }); await playClip(r.audio, av); }
          catch (e) { say(e); } finally { b.disabled = false; }
        } }, ic("play"), "Ouvir uma prévia"),
        h("button", { type: "button", class: "btn primary", onclick: async () => {
          if (!parsed && !(await understand())) return;
          const nm = (name.value.trim() || "Personagem") + " (Lúmen)";
          if (!(await window.ui.confirm(`Cria a voz “${nm}” no Voice Studio, com as tags “${parsed.instruct || "neutras"}”. ${ALSO}`, { title: "Criar a voz?", ok: "Criar" }))) return;
          try { await api("/api/study/voice/design", { action: "create", name: name.value, instruct: parsed.instruct || "", attrs: parsed.attrs || {}, language: langSel.value, confirm: true }); toast(`${nm} criada no Voice Studio.`, "success"); dlg.close(); ids = ""; renderGallery(); }
          catch (e) { say(e); }
        } }, ic("plus"), "Criar no Voice Studio")));
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    name.focus();
  }
  // só troca quando muda: reescrever o mesmo texto numa região aria-live faz o leitor de tela repetir a cada consulta
  function badge(el, [tone, icon, text]) { if (!el || el.dataset.text === text) return; el.dataset.text = text; el.dataset.tone = tone; el.replaceChildren(ic(icon), text); }
  const setText = (el, text) => { if (el && el.textContent !== text) el.textContent = text; };
  async function setDefault(v) {
    try { await api("/api/study/settings", { voice: { voice_id: v.id } }); toast(`${v.name} é a voz padrão.`, "success"); ids = ""; renderGallery(); }
    catch (e) { say(e); }
  }
  async function renderGallery() {
    const list = panel?.querySelector(".vc-voices");
    if (!list) return;
    panel.querySelector(".vc-lost")?.remove();
    try {
      const [r, st] = await Promise.all([api("/api/study/voice/voices"), api("/api/study/voice/state")]);
      const def = st.settings.voice_id;
      ids = r.voices.map((v) => v.id).join(",") + "|" + def;
      list.replaceChildren(...(r.voices.length ? r.voices.map((v) => voiceRow(v, { isDefault: v.id === def, onDefault: setDefault, onEdit: openVS }))
        : [h("li", { class: "empty" }, h("span", { class: "empty-icon" }, ic("volume")), h("strong", { text: "Nenhuma voz no Voice Studio" }),
          h("p", { text: "Clone ou crie uma voz no Voice Studio. Ela aparece aqui sozinha." }), h("button", { type: "button", class: "btn sm", onclick: openVS }, ic("external"), "Abrir o Voice Studio"))]));
      if (!r.voices.some((v) => v.id === def) && r.voices.length) list.before(h("p", { class: "callout vc-lost" }, ic("alert"), h("span", { text: st.who?.note || "A voz padrão não está mais no Voice Studio." })));
    } catch (e) {
      const closed = e.message === "O Voice Studio está fechado.";
      list.replaceChildren(h("li", { class: "vc-voices-off muted t-sm" }, ic("info"), h("span", { text: closed ? "As vozes aparecem com a voz ligada." : e.message }),
        closed ? h("button", { type: "button", class: "btn sm", onclick: async (ev) => { ev.currentTarget.disabled = true; await api("/api/study/voice/warm", { reason: "hear" }).catch(say); refreshStatus(true); } }, ic("power"), "Ligar a voz agora") : null));
    }
  }
  async function refreshStatus(soon) {
    clearTimeout(timer);
    if (!panel || panel.hidden) return;
    let st;
    try { st = await api("/api/study/voice/state"); } catch { return; }
    const vs = st.voicestudio, s = st.settings, card = panel.querySelector(".vc-status"), b = vs.backend || {};
    badge(document.querySelector("#vs-badge"), statusTone(st, true));
    badge(card.querySelector(".badge"), statusTone(st));
    setText(card.querySelector(".vc-status-meta"), vs.running ? [vs.version && "v" + vs.version, vs.gpu, vs.engine?.name?.split(" (")[0]].filter(Boolean).join(" · ") : "");
    setText(card.querySelector(".vc-lead"), !vs.installed ? "O Voice Studio não está instalado neste PC."
      : vs.foreign ? "Outro programa responde na porta do Voice Studio: a voz não liga até ele fechar."
        : s.vs_autostart ? `A voz liga sozinha quando o Lúmen precisa, sem abrir janela, e desliga depois de ${s.vs_idle_minutes} min parada (não com o app aberto).`
          : `“Ligar sozinho” está desligado (Configurações → Voz): sem o app aberto, ${s.fallback === "chatterbox" && st.chatterbox ? "quem fala é a voz de reserva, o Chatterbox pt-br" : "a voz fica desligada"}.`);
    const warmBox = card.querySelector(".vc-warm input");
    warmBox.checked = !!s.vs_warm_on_open;
    const prog = card.querySelector(".progress"), busy = b.phase === "starting" || b.phase === "loading" || vs.model?.loading;
    prog.hidden = !busy;
    if (busy) {
      const p = Number.isFinite(b.pct) ? b.pct / 100 : vs.model?.progress == null ? NaN : Number(vs.model.progress);
      prog.classList.toggle("indeterminate", !Number.isFinite(p)); prog.firstChild.style.width = Number.isFinite(p) ? `${Math.round(p * (p > 1 ? 1 : 100))}%` : "";
    }
    const fail = card.querySelector(".vc-off");
    fail.hidden = b.phase !== "failed" || vs.running;
    setText(fail.querySelector("span"), [b.error, b.action].filter(Boolean).join(" "));
    const now = vs.running ? "on" : "off";
    if (now !== card.dataset.was) { card.dataset.was = now; renderGallery(); renderModels(); }
    // só enquanto a aba está aberta: preparando ou desligado, confere de novo
    timer = setTimeout(() => refreshStatus(), soon || busy || !vs.running ? 2000 : 15000);
  }
  function integration(el) {
    panel = el;
    if (!el.dataset.ready) {
      el.dataset.ready = "1";
      const warm = h("input", { type: "checkbox", role: "switch", "aria-label": "Deixar a voz pronta ao abrir o Lúmen" });
      warm.addEventListener("change", () => api("/api/study/settings", { voice: { vs_warm_on_open: warm.checked } }).then(() => toast(warm.checked ? "A voz fica pronta quando o Lúmen abre." : "A voz liga só quando for usada.", "success")).catch((e) => { warm.checked = !warm.checked; say(e); }));
      const sec = (title, cls, ...kids) => h("div", { class: "integ-sec " + cls, role: "group", "aria-label": title }, h("h3", { class: "eyebrow", text: title }), kids);
      el.replaceChildren(
        h("header", { class: "integ-head" }, h("span", { class: "integ-icon", "aria-hidden": "true" }, ic("volume")),
          h("div", {}, h("h2", { class: "t-h2", text: "Voice Studio" }), h("p", { class: "muted t-sm", text: "Vozes clonadas e criadas no seu PC. Nada sai daqui." })),
          h("button", { type: "button", class: "btn sm ghost", onclick: openVS }, ic("external"), "Abrir o app")),
        h("div", { class: "vc-status", role: "group", "aria-label": "Estado do Voice Studio", "aria-live": "polite" },
          h("div", { class: "vc-status-top" }, h("span", { class: "badge", "data-tone": "" }), h("span", { class: "vc-status-meta t-caption muted" })),
          h("p", { class: "vc-lead t-sm muted" }),
          h("div", { class: "progress", hidden: true }, h("span")),
          h("label", { class: "vc-warm set-row" }, h("span", { class: "set-text" }, h("strong", { text: "Deixar a voz pronta ao abrir o Lúmen" }),
            h("small", { text: "Sobe o Voice Studio sem janela e carrega o modelo na abertura (cerca de 2,7 GB na placa). Desligado, a voz liga no primeiro uso." })),
            h("span", { class: "st-switch" }, warm, h("span", { class: "sr", text: "Deixar a voz pronta ao abrir o Lúmen" }))),
          h("p", { class: "callout vc-off", hidden: true }, ic("alert"), h("span"), h("button", { type: "button", class: "btn sm", onclick: openVS }, "Abrir o app"))),
        sec("Vozes", "vc-voices-sec", h("ul", { class: "vc-voices", "aria-label": "Vozes do Voice Studio" }, [0, 1].map(() => h("li", { class: "skeleton vc-skel" }))),
          h("div", { class: "st-source-actions" }, h("button", { type: "button", class: "btn sm", onclick: designDialog }, ic("plus"), "Criar voz para personagem"))),
        sec("Modelos de voz", "vc-models-sec", h("div", { class: "vc-models" }, h("div", { class: "skeleton vc-skel" }))),
        sec("Qualidade da fala do Lúmen", "vc-quality-sec", h("div", { class: "vc-quality" })),
        sec("Esta máquina", "vc-machine-sec", h("div", { class: "vc-machine", "aria-live": "off" }, h("div", { class: "skeleton vc-skel" }))),
        h("p", { class: "field-hint vc-foot" }, ic("shield"), h("span", { text: " O Lúmen lê as vozes e pede fala por aqui; pacote, motor, modelos, pronúncias e vozes novas só mudam quando você clica, e cada controle avisa que muda também no Voice Studio. Apagar ou travar uma voz e o histórico ficam no app. Cada voz clonada é de uso pessoal, neste PC." }),
          h("button", { type: "button", class: "link-btn", onclick: () => { if (typeof window.showView === "function") window.showView("study"); window.lumenStudy?.openSettings?.("voice"); } }, "Ajustes da voz")));
      el.querySelector(".vc-status").dataset.was = "";
    }
    refreshStatus();
    renderModels();
    renderMachine();
  }
  // o selo da aba aparece mesmo antes de abri-la
  setTimeout(() => api("/api/study/voice/state").then((st) => { const b = document.querySelector("#vs-badge"); if (b) badge(b, statusTone(st, true)); }).catch(() => {}), 1500);

  window.lumenVoice = { speak, stop, playClip, ptt, player, make, lessonAudio, voiceRow, avatar, integration, api, openVS, initials, kindLabel, warm, designDialog };

  // Se a aba de Voice Studio já estiver ativa na inicialização, renderiza o painel
  const vsPanel = document.querySelector("#integ-voicestudio");
  if (vsPanel && !vsPanel.hidden) {
    integration(vsPanel);
  }
})();
