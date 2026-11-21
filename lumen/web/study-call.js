"use strict";
/* Conversa por voz em tempo real nos Estudos.
   Abre no lugar do chat dentro dos Estudos (ou minimiza numa pílula flutuante enquanto o estudante navega pelo app),
   lê o fluxo NDJSON de /api/study/call/events e envia comandos para POST /api/study/call.
   Reaproveita o avatar de window.lumenVoice, os cartões visuais de window.lumenStudy e o estado Livre/Notas do chat
   (window.lumenStudy.vault): texto e voz leem e mudam o MESMO estado, e o servidor tira uma fotografia dele a cada turno.
   Tudo o que aparece como estado vem do servidor (state/phase/label); nada aqui inventa progresso. */
(() => {
  const L = window.lumenStudy;
  if (!L) return;
  const { h, ic, md, api, guard, menu, toast, S } = L;
  const TOKEN = document.querySelector('meta[name="lumen-token"]')?.content || "";
  const still = matchMedia("(prefers-reduced-motion: reduce)");

  const C = {
    active: false, minimized: false, muted: false, captions: true, timings: false, mode: "handsfree",
    state: "ended", phase: "", label: "", who: null, conversationId: null, startedAt: 0,
    ctrl: null, tickTimer: 0, pulseTimer: 0, errorTimer: 0, lastSeq: 0, link: "ok", error: "",
    vault: { free: false, sources: null }, vaultPending: false, echo: false, vaultRev: 0,
    userNode: null, lastFinal: null, botNode: null, botText: "", activeSentence: "", prep: null, returnFocus: null,
  };

  const mmss = (sec) => { const s = Math.max(0, Math.floor(sec || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const whoFallback = () => C.who || { name: "Lúmen", voice: "", image: false, kind: "clone" };
  function makeAvatar(size) {
    const V = window.lumenVoice, w = whoFallback();
    if (V?.avatar) return V.avatar(w, size);
    return h("span", { class: "vc-avatar" + (size ? " " + size : ""), "aria-hidden": "true" }, h("span", { text: (w.name || "L").slice(0, 2).toUpperCase() }));
  }
  const ctl = (icon, name, label, cls = "") => h("button", { type: "button", class: "st-call-ctl " + cls, "aria-label": name },
    h("span", { class: "st-call-ctl-ic", "aria-hidden": "true" }, ic(icon)), h("span", { class: "st-call-ctl-label", text: label }));

  // --- Cabeçalho: minimizar · quem fala (trocar a voz) + tempo · legendas ----------------------------------------------
  const minBtn = h("button", { type: "button", class: "icon-btn st-call-min", "aria-label": "Minimizar chamada", "data-tip": "Minimizar: a chamada continua", onclick: () => setMinimized(true) }, ic("dock"));
  const timerEl = h("span", { class: "st-call-timer tabular", text: "0:00" });
  const voiceName = h("span", { class: "st-call-voice-name", text: "Lúmen" });
  const voiceBtn = h("button", { type: "button", class: "st-call-voice", "aria-haspopup": "menu", "aria-label": "Escolher a voz da chamada", "data-tip": "Trocar a voz",
    onclick: (e) => openVoicePicker(e.currentTarget) }, voiceName, ic("chevron-down"));
  const captionsBtn = h("button", { type: "button", class: "icon-btn st-call-cc", "aria-pressed": "true", "aria-label": "Legendas", "data-tip": "Mostrar ou esconder as legendas", onclick: () => toggleCaptions() }, ic("page"));
  const header = h("header", { class: "st-call-top" }, minBtn,
    h("div", { class: "st-call-title" }, h("div", { class: "st-call-sub" }, voiceBtn, timerEl)), captionsBtn);

  // --- Palco: orbe, estado real, dica, microfone aberto, preparo sem porcentagem inventada -------------------------------
  const orbAvatarHost = h("div", { class: "st-call-orb-core" });
  const orbWave = h("span", { class: "st-call-orb-wave", "aria-hidden": "true" });
  const orb = h("div", { class: "st-call-orb", dataset: { state: "preparing" } }, orbWave, orbAvatarHost);
  const stateLive = h("p", { class: "st-call-state", role: "status", "aria-live": "polite", text: "Preparando a voz" });
  const hintEl = h("p", { class: "st-call-hint", text: "" });
  const micBadge = h("span", { class: "st-call-mic-open" }, h("span", { class: "live-dot", "aria-hidden": "true" }), h("span", { text: "Microfone aberto" }));
  const prepFill = h("span", { class: "st-call-prep-fill" });
  const prepBox = h("div", { class: "st-call-prep", hidden: true }, h("div", { class: "st-call-prep-track", "aria-hidden": "true" }, prepFill));

  // --- Livre | Notas: o mesmo estado do chat escrito ---------------------------------------------------------------------
  const segFree = h("button", { type: "button", role: "radio", class: "st-call-seg", "aria-checked": "false", "data-tip": "Livre: não consulta o Notion nem o Obsidian", onclick: () => pickVault(true) }, ic("sparkle"), h("span", { text: "Livre" }));
  const segNotes = h("button", { type: "button", role: "radio", class: "st-call-seg", "aria-checked": "true", "data-tip": "Notas: busca e cita suas notas", onclick: () => pickVault(false) }, ic("notebook"), h("span", { text: "Notas" }));
  const segMore = h("button", { type: "button", class: "st-call-seg-more", "aria-haspopup": "menu", "aria-label": "Escolher as fontes de notas", "data-tip": "Escolher as fontes de notas", onclick: (e) => openSourcesMenu(e.currentTarget) }, ic("chevron-down"));
  const vaultGroup = h("div", { class: "st-call-vault", role: "radiogroup", "aria-label": "Fontes da resposta" }, segFree, segNotes, segMore);
  const vaultNote = h("p", { class: "st-call-vault-note", role: "status", hidden: true });
  vaultGroup.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const toFree = e.key === "ArrowLeft" || e.key === "ArrowUp";
    pickVault(toFree);
    (toFree ? segFree : segNotes).focus();
  });

  const captionsLog = h("div", { class: "st-call-captions", role: "log", "aria-live": "off", "aria-label": "Legenda da conversa" });

  // --- Controles: o essencial grande; o resto discreto -------------------------------------------------------------------
  const muteBtn = ctl("mic", "Silenciar microfone", "Mudo");
  muteBtn.setAttribute("aria-pressed", "false");
  muteBtn.addEventListener("click", () => toggleMute());
  const talkBtn = ctl("stop", "Interromper", "Interromper", "primary");
  talkBtn.addEventListener("click", () => onTalkClick());
  const endBtn = ctl("power", "Encerrar chamada", "Encerrar", "danger");
  endBtn.setAttribute("data-tip", "Encerrar chamada (Esc)");
  endBtn.addEventListener("click", () => endCall());
  // Segurar para falar (modo ptt)
  talkBtn.addEventListener("pointerdown", (e) => {
    if (e.button === 0 && C.mode === "ptt" && C.active) { talkBtn.setPointerCapture?.(e.pointerId); sendCmd({ action: "ptt_down" }); }
  });
  for (const evName of ["pointerup", "pointercancel"]) talkBtn.addEventListener(evName, () => { if (C.mode === "ptt" && C.active) sendCmd({ action: "ptt_up" }); });

  const callView = h("section", { class: "st-call", "aria-label": "Conversa por voz em tempo real", tabindex: "-1", hidden: true },
    header,
    h("div", { class: "st-call-stage" }, orb, stateLive, hintEl, micBadge, prepBox, vaultGroup, vaultNote),
    captionsLog,
    h("footer", { class: "st-call-controls", role: "toolbar", "aria-label": "Controles da chamada" }, muteBtn, talkBtn, endBtn));

  // --- Pílula flutuante (chamada minimizada) ------------------------------------------------------------------------------
  const pillAvatarHost = h("span", { class: "st-call-pill-av" });
  const pillState = h("span", { class: "st-call-pill-state", text: "Ouvindo" });
  const pillMode = h("span", { class: "st-call-pill-mode", text: "Notas" });
  const pillTimer = h("span", { class: "st-call-pill-timer tabular", text: "0:00" });
  const pillMicDot = h("span", { class: "live-dot", role: "img", "aria-label": "Microfone aberto" });
  const pillMuteBtn = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Silenciar microfone", "aria-pressed": "false", "data-tip": "Mudo", onclick: () => toggleMute() }, ic("mic"));
  const pillExpandBtn = h("button", { type: "button", class: "btn sm ghost", "aria-label": "Voltar para a chamada", onclick: () => expandFromPill() }, ic("detach"), h("span", { text: "Abrir" }));
  const pillEndBtn = h("button", { type: "button", class: "btn sm danger primary", "aria-label": "Encerrar chamada", onclick: () => endCall() }, ic("power"), h("span", { text: "Encerrar" }));
  const pill = h("aside", { class: "st-call-pill", "aria-label": "Chamada de voz em andamento", hidden: true },
    pillAvatarHost, pillMicDot,
    h("div", { class: "st-call-pill-info", onclick: () => expandFromPill() }, h("span", { class: "st-call-pill-line" }, pillState, pillMode), pillTimer),
    pillMuteBtn, pillExpandBtn, pillEndBtn);
  document.body.append(pill);

  function mountCallView() {
    const chatPanel = L.chatPanel?.(), main = L.mainEl?.();
    if (chatPanel && !callView.parentElement) chatPanel.insertBefore(callView, main?.nextSibling || null);
  }
  function refreshAvatars() {
    const key = JSON.stringify([C.who?.voice, C.who?.name, C.who?.image]);
    if (orbAvatarHost.dataset.key !== key) {
      orbAvatarHost.dataset.key = key;
      orbAvatarHost.replaceChildren(makeAvatar("xl"));
      pillAvatarHost.replaceChildren(makeAvatar("sm"));
    }
    voiceName.textContent = C.who?.name || "Lúmen";
  }
  function setOrbAmp(val) {
    orb.style.setProperty("--amp", (still.matches ? 0 : Math.max(0, Math.min(1, Number(val) || 0))).toFixed(2));
  }

  // --- Texto de estado: tudo derivado do que o servidor informou ----------------------------------------------------------
  const BUSY = new Set(["end_of_speech", "transcribing", "thinking", "speaking"]);
  function statusText() {
    if (C.link === "reconnecting") return "Reconectando";
    if (C.state === "ended") return "Chamada encerrada";
    if (C.muted && (C.state === "listening" || C.state === "user_speaking")) return "Microfone silenciado";
    switch (C.state) {
      case "preparing": return "Preparando a voz";
      case "listening": return "Ouvindo";
      case "user_speaking": return "Você está falando";
      case "end_of_speech": return "Entendi";
      case "transcribing": return "Transcrevendo";
      case "thinking": return (C.label || "Preparando a resposta").replace(/…$/, "");
      case "speaking": return "Falando";
      case "reconnecting": return "Reconectando o microfone";
      default: return C.label || "";
    }
  }
  function hintText() {
    if (C.error) return C.error;
    if (C.link === "reconnecting") return "Perdi a ligação com o Lúmen por instantes. Tentando de novo; nada será repetido.";
    if (C.state === "preparing") {
      const pct = Number.isFinite(C.prep?.pct) && C.prep.pct > 0 ? ` ${Math.round(C.prep.pct)}%` : "";   // só se o Voice Studio informou
      return (C.prep?.label || "Isso pode levar um tempo na primeira vez do dia.") + pct;
    }
    if (C.muted) return "Ative o microfone para continuar a conversa.";
    if (C.state === "listening") return C.mode === "handsfree" ? "Pode falar quando quiser." : C.mode === "ptt" ? "Segure o botão enquanto fala." : "Toque no botão para falar e toque de novo para enviar.";
    if (C.state === "user_speaking") return C.mode === "handsfree" ? "Faça uma pausa para eu responder." : "";
    if (C.state === "speaking") return C.mode === "handsfree" ? "Fale por cima para me interromper." : "";
    if (C.state === "reconnecting") return "O microfone parou de responder. Tentando reabrir.";
    return "";
  }
  function orbState() {
    if (C.link === "reconnecting" || C.state === "reconnecting") return "reconnecting";
    if (C.error) return "error";
    if (C.state === "end_of_speech") return "understood";
    if (C.state === "preparing") return "preparing";
    if (C.state === "transcribing" || C.state === "thinking") return "thinking";
    if (C.state === "speaking") return "speaking";
    return "listening";
  }

  function renderVault() {
    const free = !!C.vault.free;
    segFree.setAttribute("aria-checked", String(free));
    segNotes.setAttribute("aria-checked", String(!free));
    segFree.tabIndex = free ? 0 : -1;
    segNotes.tabIndex = free ? -1 : 0;
    const one = !free && C.vault.sources?.length === 1 ? C.vault.sources[0] : "";
    segNotes.querySelector("span").textContent = one ? (one === "obsidian" ? "Obsidian" : one === "notion" ? "Notion" : "Notas") : "Notas";
    segMore.hidden = free;
    pillMode.textContent = free ? "Livre" : one ? (one === "obsidian" ? "Obsidian" : "Notion") : "Notas";
    vaultNote.hidden = !C.vaultPending;
    vaultNote.textContent = C.vaultPending ? "Vale a partir da próxima resposta." : "";
  }

  function updateUI() {
    refreshAvatars();
    const micOpen = C.active && !C.muted && C.state !== "ended" && C.state !== "preparing" && C.state !== "reconnecting";
    micBadge.hidden = !micOpen;
    pillMicDot.hidden = !micOpen;

    muteBtn.setAttribute("aria-pressed", String(C.muted));
    muteBtn.classList.toggle("on", C.muted);
    muteBtn.querySelector(".st-call-ctl-label").textContent = C.muted ? "No mudo" : "Mudo";
    muteBtn.querySelector(".st-call-ctl-ic").replaceChildren(ic(C.muted ? "mic-off" : "mic"));
    pillMuteBtn.setAttribute("aria-pressed", String(C.muted));
    pillMuteBtn.replaceChildren(ic(C.muted ? "mic-off" : "mic"));

    captionsBtn.setAttribute("aria-pressed", String(C.captions));
    callView.classList.toggle("no-captions", !C.captions);
    captionsLog.classList.toggle("hide-transcript", !C.captions);

    let talk = "Interromper", talkIcon = "stop", talkOn = BUSY.has(C.state) && C.state !== "end_of_speech";
    if (C.mode === "ptt") { talk = C.state === "user_speaking" ? "Solte para enviar" : "Segure para falar"; talkIcon = "mic"; talkOn = C.state !== "preparing"; }
    else if (C.mode === "tap") { talk = C.state === "user_speaking" ? "Enviar fala" : "Tocar para falar"; talkIcon = "mic"; talkOn = C.state !== "preparing"; }
    talkBtn.querySelector(".st-call-ctl-label").textContent = talk;
    talkBtn.querySelector(".st-call-ctl-ic").replaceChildren(ic(talkIcon));
    talkBtn.setAttribute("aria-label", talk);
    talkBtn.disabled = !talkOn;
    talkBtn.setAttribute("aria-disabled", String(!talkOn));

    stateLive.textContent = statusText();
    hintEl.textContent = hintText();
    hintEl.hidden = !hintEl.textContent;
    pillState.textContent = statusText();
    if (!C.pulseTimer) orb.dataset.state = orbState();
    orb.dataset.muted = String(C.muted);
    orb.dataset.hearing = String(C.state === "user_speaking" && !C.muted);
    prepBox.hidden = C.state !== "preparing";
    if (C.state !== "listening" && C.state !== "user_speaking" && C.state !== "speaking") setOrbAmp(0);
    renderVault();
  }

  function startTimer() {
    clearInterval(C.tickTimer);
    const tick = () => {
      if (!C.active) return;
      const txt = mmss(C.startedAt ? Date.now() / 1000 - C.startedAt : 0);
      timerEl.textContent = txt;
      pillTimer.textContent = txt;
    };
    tick();
    C.tickTimer = setInterval(tick, 1000);
  }

  async function sendCmd(body) { return guard(() => api("/api/study/call", body)); }

  function flashError(msg) {
    C.error = msg;
    clearTimeout(C.errorTimer);
    C.errorTimer = setTimeout(() => { C.error = ""; updateUI(); }, 6000);
    updateUI();
  }

  async function openCall() {
    mountCallView();
    window.lumenVoice?.stop();
    if (C.active) { setMinimized(false); return; }
    captionsLog.replaceChildren();
    Object.assign(C, { userNode: null, botNode: null, botText: "", activeSentence: "", minimized: false, muted: false, state: "preparing",
      phase: "", label: "Preparando a voz", lastSeq: 0, link: "ok", error: "", prep: null, vaultPending: false });
    C.captions = S.state?.settings?.voice?.call_captions !== false;
    C.timings = !!S.state?.settings?.voice?.call_timings;
    C.mode = S.state?.settings?.voice?.call_mode || "handsfree";
    C.vault = L.vault ? L.vault.get() : { free: false, sources: null };
    C.returnFocus = document.activeElement;

    const main = L.mainEl?.();
    if (main) main.hidden = true;
    callView.hidden = false;
    pill.hidden = true;
    updateUI();

    const snap = await sendCmd({
      action: "start",
      conversation_id: S.conv?.id || null,
      project_id: S.conv?.project_id || (S.project && S.project !== "none" ? S.project : null),
      ...(S.temporary ? { temporary: true } : {}),
      skip_vault: !!C.vault.free,
      ...(C.vault.sources && !C.vault.free ? { vault_sources: C.vault.sources } : {}),
      ...(S.profile ? { profile: S.profile } : {}),
    });
    if (!snap) {
      callView.hidden = true;
      if (main) main.hidden = false;
      return;
    }
    applyState(snap);
    startTimer();
    connectStream();
    callView.focus({ preventScroll: true });
  }

  function connectStream() {
    C.ctrl?.abort();
    const ctrl = new AbortController();
    C.ctrl = ctrl;
    (async () => {
      let retries = 0;
      while (C.active && !ctrl.signal.aborted) {
        try {
          // `since`: depois de uma queda, o servidor reenvia só o que a tela não recebeu (e `seq` repetido é ignorado)
          const r = await fetch(`/api/study/call/events?since=${C.lastSeq}`, { headers: { "X-Lumen-Token": TOKEN }, signal: ctrl.signal });
          if (!r.ok || !r.body) throw new Error("sem fluxo");
          retries = 0;
          if (C.link !== "ok") { C.link = "ok"; updateUI(); }
          const reader = r.body.getReader(), dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            let k;
            while ((k = buf.indexOf("\n")) >= 0) {
              const line = buf.slice(0, k);
              buf = buf.slice(k + 1);
              if (line.trim()) { try { handleEvent(JSON.parse(line)); } catch { /* linha cortada: o próximo evento corrige */ } }
            }
          }
          if (!C.active || ctrl.signal.aborted) break;
        } catch (e) {
          if (e.name === "AbortError" || !C.active || ctrl.signal.aborted) break;
        }
        // caiu: mostra "Reconectando" (e não "Ouvindo") até o fluxo voltar
        retries += 1;
        if (C.link !== "reconnecting") { C.link = "reconnecting"; updateUI(); }
        await new Promise((res) => setTimeout(res, Math.min(4000, 400 * retries)));
        try {
          const st = await api("/api/study/call");
          if (!st || st.active === false || st.state === "ended") { if (st) applyState(st); break; }
        } catch { /* servidor ainda fora: tenta de novo */ }
        if (retries > 40) { toast("Sem conexão com o Lúmen. Encerre a chamada e abra outra.", "warning"); break; }
      }
    })();
  }

  function applyState(ev, adoptVaultToo = true) {
    const prev = C.state;
    C.active = ev.active !== false && ev.state !== "ended";
    C.state = ev.state || C.state;
    C.phase = ev.phase || "";
    C.label = ev.label || C.label;
    C.muted = !!ev.muted;
    C.mode = ev.mode || C.mode;
    if (typeof ev.captions === "boolean") C.captions = ev.captions;
    if (typeof ev.timings === "boolean") C.timings = ev.timings;
    if (ev.who) C.who = ev.who;
    if (ev.conversation_id) C.conversationId = ev.conversation_id;
    if (ev.started_at) C.startedAt = ev.started_at;
    if (ev.vault && adoptVaultToo) {   // a resposta de um comando antigo não desfaz um modo escolhido depois dele
      C.vaultPending = !!ev.vault_pending;
      adoptVault(ev.vault);
    }
    if (C.state !== "preparing") C.prep = null;

    // Pulso curto de "Entendi" visível por pelo menos 260 ms mesmo quando a transcrição antecipada já terminou
    if (C.state === "end_of_speech") {
      clearTimeout(C.pulseTimer);
      orb.dataset.state = "understood";
      C.pulseTimer = setTimeout(() => { C.pulseTimer = 0; updateUI(); }, 260);
    }
    updateUI();
    if (!C.active && prev !== "ended") finishCallUI();
  }

  // O servidor mudou o modo (comando de voz, outra janela): o chat escrito acompanha, sem devolver o comando
  function adoptVault(v) {
    C.vaultRev += 1;
    const cur = L.vault?.get() || C.vault;
    const same = !!cur.free === !!v.free && JSON.stringify(cur.sources || null) === JSON.stringify(v.sources || null);
    C.vault = { free: !!v.free, sources: v.sources || null };
    if (!same && L.vault) { C.echo = true; try { L.vault.set(C.vault.free, C.vault.sources); } finally { C.echo = false; } }
  }
  L.vault?.onChange((v) => {
    C.vault = { free: !!v.free, sources: v.sources || null };
    renderVault();
    C.vaultRev += 1;
    sendVault();
  });
  function sendVault() {
    if (!C.active || C.echo) return;
    const rev = C.vaultRev, v = C.vault;
    sendCmd({ action: "vault", skip_vault: !!v.free, vault_sources: v.sources || null }).then((s) => s && applyState(s, rev === C.vaultRev));
  }
  function pickVault(free) {
    if (!!C.vault.free === free) return;
    if (L.vault) L.vault.set(free, free ? null : C.vault.sources);
    else { C.vault = { free, sources: null }; C.vaultRev += 1; renderVault(); sendVault(); }
    toast(free ? "Modo livre: não vou consultar suas notas." : "Voltei a usar suas notas.", "info");
  }
  function openSourcesMenu(anchor) {
    const set = (sources, msg) => { if (L.vault) L.vault.set(false, sources); toast(msg, "info"); };
    menu(anchor, [
      ["Todas as notas (Notion + Obsidian)", "notebook", () => set(null, "Usando suas notas do Notion e do Obsidian.")],
      ["Só Obsidian", "obsidian", () => set(["obsidian"], "Consulta restrita ao Obsidian.")],
      ["Só Notion", "page", () => set(["notion"], "Consulta restrita ao Notion.")],
    ]);
  }

  // --- Legenda ------------------------------------------------------------------------------------------------------------
  function ensureUserNode() {
    if (!C.userNode) { C.userNode = h("div", { class: "st-call-turn user partial" }); captionsLog.append(C.userNode); }
    return C.userNode;
  }
  function ensureBotNode() {
    if (!C.botNode) { C.botNode = h("div", { class: "st-call-turn bot" }); captionsLog.append(C.botNode); }
    return C.botNode;
  }
  function renderBotCaption(interrupted = false) {
    const node = ensureBotNode(), full = C.botText || "", cur = C.activeSentence || "";
    node.replaceChildren();
    if (cur && !interrupted) {
      const idx = full.indexOf(cur);
      if (idx >= 0) {
        const p = h("p", { class: "st-call-bot-line" });
        if (idx > 0) p.append(document.createTextNode(full.slice(0, idx)));
        p.append(h("mark", { class: "st-call-now", text: cur }));
        if (full.slice(idx + cur.length)) p.append(document.createTextNode(full.slice(idx + cur.length)));
        node.append(p);
      } else {
        node.append(h("div", { class: "st-call-bot-md" }, md(full)), h("p", { class: "st-call-now-line" }, h("mark", { class: "st-call-now", text: cur })));
      }
    } else {
      node.append(h("div", { class: "st-call-bot-md" }, md(full)));
    }
    if (interrupted) { node.classList.add("is-interrupted"); node.append(h("span", { class: "badge st-call-cut", text: "interrompida" })); }
    captionsLog.scrollTop = captionsLog.scrollHeight;
  }

  function appendCard(ev) {
    let el = null;
    if (ev.kind === "item" && ev.item) {
      const existing = captionsLog.querySelector(`[data-call-item="${CSS.escape(String(ev.item.id))}"]`);
      el = h("div", { class: "st-call-card", dataset: { callItem: String(ev.item.id) } }, L.callItemBlock(ev.item));
      if (existing) { existing.replaceWith(el); return; }
    } else if (ev.kind === "explain" && ev.explain) {
      el = h("div", { class: "st-call-card" }, L.explainBlock({ id: ev.message?.id, meta: { explain: ev.explain } }));
    } else if (ev.kind === "pending" && ev.action) {
      el = h("div", { class: "st-call-card" }, L.pendingCard(ev.action));
    } else if (ev.kind === "feynman" && ev.feynman) {
      el = h("div", { class: "st-call-card" }, L.feynmanSummaryCard(ev.feynman));
    } else if (ev.kind === "screen") {
      el = h("div", { class: "st-call-card st-call-mini-card" }, ic("screen"), h("span", { text: `Tela lida: ${ev.window || "janela ativa"}` }));
    } else if (ev.kind === "review" && ev.due) {
      el = h("div", { class: "st-call-card st-call-mini-card" }, ic("calendar"), h("span", { text: `Revisão do dia: ${ev.due.total || 0} cartão(ões) vencido(s).` }));
    } else if (ev.kind === "mastery") {
      const items = ev.items || [];
      el = h("div", { class: "st-call-card st-call-mini-card" }, ic("book"),
        h("span", { text: items.length ? "Assuntos para reforçar: " + items.slice(0, 4).map((x) => `${x.label || x.topic} (${x.wrong} erro(s))`).join(" · ") : "Sem erros registrados até agora." }));
    }
    if (el) { captionsLog.append(el); captionsLog.scrollTop = captionsLog.scrollHeight; }
  }

  function handleEvent(ev) {
    if (!ev || typeof ev !== "object") return;
    if (ev.seq) {                       // reenvio depois da queda: o que já foi visto não se repete
      if (ev.seq <= C.lastSeq) return;
      C.lastSeq = ev.seq;
    }
    switch (ev.type) {
      case "state": applyState(ev); break;
      case "preparing": {
        C.prep = ev;
        const pct = Number.isFinite(ev.pct) ? Math.round(ev.pct) : null;   // só o que o Voice Studio informou; sem número, a barra é indeterminada
        prepBox.hidden = false;
        prepFill.style.setProperty("--v", pct != null ? Math.max(4, Math.min(100, pct)) + "%" : "");
        prepFill.classList.toggle("indeterminate", pct == null);
        hintEl.textContent = hintText();
        hintEl.hidden = !hintEl.textContent;
        break;
      }
      case "vault": adoptVault(ev.vault || C.vault); renderVault(); break;
      case "level":
        if (ev.source === "mic" && (C.state === "listening" || C.state === "user_speaking")) setOrbAmp(ev.level);
        if (ev.source === "voice" && C.state === "speaking") setOrbAmp(ev.level);
        break;
      case "partial": {
        const u = ensureUserNode();
        u.className = "st-call-turn user partial";
        u.textContent = ev.text || "";
        captionsLog.scrollTop = captionsLog.scrollHeight;
        break;
      }
      case "final": {
        const u = ensureUserNode();
        u.className = "st-call-turn user final" + (ev.fast ? " command" : "");   // comando rápido (parar, modo livre…): aparece, mas não é mensagem da conversa
        u.textContent = ev.text || "";
        C.userNode = null; C.lastFinal = u;
        C.botNode = null; C.botText = ""; C.activeSentence = "";   // novo bloco de resposta para este turno
        captionsLog.scrollTop = captionsLog.scrollHeight;
        break;
      }
      case "retract":   // o estudante continuou a frase: a pergunta cortada some e a fala inteira entra como uma só
        C.lastFinal?.remove(); C.lastFinal = null;
        C.botNode?.remove(); C.botNode = null; C.botText = ""; C.activeSentence = "";
        break;
      case "conversation":
        if (ev.conversation?.id) {
          C.conversationId = ev.conversation.id;
          if (!S.conv || !S.conv.id) S.conv = { ...ev.conversation, messages: [] };
        }
        break;
      case "token":
        if (ev.replace) C.botText = ev.text || "";
        else C.botText += ev.text || "";
        renderBotCaption(false);
        break;
      case "sentence":
        C.activeSentence = ev.text || "";
        if (!C.botText && ev.spoken_so_far) C.botText = ev.spoken_so_far;
        renderBotCaption(false);
        break;
      case "interrupted":
        C.botText = ev.text || C.botText.slice(0, 120);
        C.activeSentence = "";
        renderBotCaption(true);
        C.botNode = null;
        break;
      case "card": appendCard(ev); break;
      case "timing":
        if (C.timings) {
          const t = (k) => Math.round(ev[k] || 0);
          captionsLog.append(h("p", { class: "st-call-timing tabular faint" },
            `Turno ${ev.turn}: fim ${t("eos_ms")} ms · ASR (${ev.asr_engine}) ${t("asr_ms")} ms · IA ${t("llm_first_ms")} ms${ev.searched ? ` · notas ${t("search_ms")} ms` : ""} · voz (${ev.steps}p) ${t("tts_first_ms")} ms · 1º som ${t("total_ms")} ms${ev.early_hit ? " · antecipada" : ""}`));
          captionsLog.scrollTop = captionsLog.scrollHeight;
        }
        break;
      case "status_note": toast(ev.text, "info"); break;
      case "error":
        toast([ev.message, ev.action].filter(Boolean).join(" "), "error");
        flashError(ev.message || "Houve um erro.");
        break;
      default: break;
    }
  }

  // --- Controles ----------------------------------------------------------------------------------------------------------
  async function toggleMute() {
    if (!C.active) return;
    const snap = await sendCmd({ action: "mute", muted: !C.muted });
    if (snap) applyState(snap);
  }
  async function onTalkClick() {
    if (!C.active) return;
    if (C.mode === "tap") { const snap = await sendCmd({ action: C.state === "user_speaking" ? "ptt_up" : "ptt_down" }); if (snap) applyState(snap); return; }
    if (C.mode === "ptt") return;   // pointerdown/pointerup
    const snap = await sendCmd({ action: "interrupt" });
    if (snap) applyState(snap);
  }
  async function toggleCaptions() {
    C.captions = !C.captions;
    updateUI();
    if (C.active) await sendCmd({ action: "settings", settings: { call_captions: C.captions } });
  }
  async function openVoicePicker(anchor) {
    const r = await api("/api/study/voice/voices").catch(() => ({ voices: [] }));
    const voices = r?.voices || [];
    if (!voices.length) { toast("Nenhuma voz disponível no Voice Studio agora.", "info"); return; }
    menu(anchor, voices.map((v) => [
      `${v.name}${v.id === C.who?.voice ? " ✓" : ""}`, "volume",
      async () => {
        const snap = await sendCmd({ action: "settings", settings: { call_voice: v.id } });
        if (snap) applyState(snap);
        toast(`Voz da chamada: ${v.name}.`, "success");
      },
    ]));
  }

  function setMinimized(min) {
    if (!C.active) return;
    C.minimized = !!min;
    const main = L.mainEl?.();
    if (C.minimized) {
      callView.hidden = true;
      if (main) main.hidden = false;
      pill.hidden = false;
      pillExpandBtn.focus({ preventScroll: true });
    } else {
      pill.hidden = true;
      if (main) main.hidden = true;
      callView.hidden = false;
      callView.focus({ preventScroll: true });
    }
  }
  function expandFromPill() {
    document.querySelector("#nav-study")?.click();
    L.setTab?.("chat");
    const sh = L.settingsHostEl?.();
    if (sh && !sh.hidden) sh.querySelector("button")?.click();
    setMinimized(false);
  }

  async function finishCallUI() {
    clearInterval(C.tickTimer);
    clearTimeout(C.pulseTimer); C.pulseTimer = 0;
    clearTimeout(C.errorTimer);
    const wasMin = C.minimized;
    C.active = false; C.minimized = false; C.link = "ok"; C.error = "";
    C.ctrl?.abort(); C.ctrl = null;
    callView.hidden = true;
    pill.hidden = true;
    const main = L.mainEl?.();
    if (main) main.hidden = false;
    const cid = C.conversationId || S.conv?.id;
    if (cid) { await L.openConversation?.(cid); L.loadConversations?.(); }
    if (!wasMin) (C.returnFocus && document.contains(C.returnFocus) ? C.returnFocus : L.input?.())?.focus?.({ preventScroll: true });
  }
  async function endCall() {
    if (C.active) await api("/api/study/call", { action: "stop" }).catch(() => {});
    await finishCallUI();
  }

  // Se o estudante navegar para outra área do app ou outra aba dos Estudos durante a chamada, vira pílula flutuante
  document.addEventListener("click", (e) => {
    if (!C.active || C.minimized) return;
    const navBtn = e.target.closest?.(".rail-item, .st-tabs [role=tab]");
    if (!navBtn) return;
    const goingOtherView = navBtn.classList.contains("rail-item") && navBtn.dataset.view !== "study";
    const goingOtherTab = navBtn.getAttribute("role") === "tab" && navBtn.dataset.tab !== "chat";
    if (goingOtherView || goingOtherTab) setMinimized(true);
  });

  // Teclado: Esc encerra; Espaço interrompe (ou segura o PTT); M liga/desliga o mudo
  const isTyping = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  document.addEventListener("keydown", (e) => {
    if (!C.active || C.minimized || callView.hidden) return;
    if (document.querySelector("dialog[open], .st-menu")) return;
    if (e.key === "Escape") { e.preventDefault(); endCall(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey || isTyping(document.activeElement)) return;
    if ((e.key === "m" || e.key === "M") && !e.repeat) { e.preventDefault(); toggleMute(); return; }
    if (e.code === "Space" && !e.repeat && document.activeElement?.tagName !== "BUTTON") {
      e.preventDefault();
      if (C.mode === "ptt" || C.mode === "tap") sendCmd({ action: "ptt_down" }).then((s) => s && applyState(s));
      else onTalkClick();
    }
  });
  document.addEventListener("keyup", (e) => {
    if (!C.active || C.minimized || callView.hidden) return;
    if (e.code === "Space" && C.mode === "ptt" && !isTyping(document.activeElement) && document.activeElement?.tagName !== "BUTTON") {
      e.preventDefault();
      sendCmd({ action: "ptt_up" }).then((s) => s && applyState(s));
    }
  });

  L.openCall = openCall;
  L.endCall = endCall;
  L.callActive = () => C.active;
  L.callState = () => ({ ...C });
  L.callTyped = () => { if (C.active && (C.state === "speaking" || C.state === "thinking")) sendCmd({ action: "interrupt" }); };
  L.feedCallEvent = handleEvent;
  L.syncCallSettings = (patch) => { if (C.active) sendCmd({ action: "settings", settings: patch, persist: false }).then((s) => s && applyState(s)); };
})();
