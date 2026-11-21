"use strict";
// Cursor próprio da janela principal (cursor.js): o ponto acompanha o mouse na hora e o anel chega depois.
// O atraso é medido em tempo, não em quadros, para o efeito ser o mesmo em 60 Hz e em 120 Hz. Só liga com
// ponteiro fino e sem "reduzir movimento"; sobre campos de texto o cursor nativo volta para não atrapalhar.
(() => {
  const fine = window.matchMedia?.("(pointer: fine)");
  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  if (!fine?.matches || still?.matches) return;

  const root = document.createElement("div");
  root.className = "lumen-cursor";
  root.setAttribute("aria-hidden", "true");
  root.innerHTML = '<span class="lumen-cursor-dot"></span><span class="lumen-cursor-ring"></span>';
  document.body.append(root);
  const dot = root.firstElementChild;
  const ring = root.lastElementChild;

  const LINK = "a, button, label, summary, [role=button], [role=tab], [role=option], [role=menuitem], [data-cursor=link]";
  const TEXT = 'input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=button]):not([type=submit]):not([type=reset]), textarea, [contenteditable=""], [contenteditable=true]';
  const modal = (el) => el?.closest?.("dialog[open], [role=dialog]");
  // Barra de arrastar (app-region: drag): o Windows trata o mouse ali como barra de título, então a página recebe um
  // último movimento ao entrar e mais nenhum; o ponto e o anel ficariam parados ao lado da seta nativa. Ali eles somem.
  const dragging = (el) => {
    for (let n = el; n?.nodeType === 1; n = n.parentElement) {
      const r = getComputedStyle(n).appRegion;
      if (r === "drag" || r === "no-drag") return r === "drag";
    }
    return false;
  };

  let targetX = 0, targetY = 0, ringX = 0, ringY = 0;
  let raf = 0, last = 0, visible = false;

  const place = (el, x, y) => { el.style.transform = `translate3d(${x}px, ${y}px, 0)`; };
  const hide = () => {
    visible = false;
    unlit();
    root.classList.remove("is-visible", "is-link", "is-down", "is-text");
    document.documentElement.classList.remove("lumen-cursor-on");
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    last = 0;
  };
  const state = (el) => {
    const text = el?.closest?.(TEXT);
    const link = text ? null : el?.closest?.(LINK);
    root.classList.toggle("is-text", Boolean(text));
    root.classList.toggle("is-link", Boolean(link) && !link.disabled);
  };

  // Brilho dos cartões (ui.css): delegação única; só --sx/--sy mudam. Diálogos e menus ficam de fora.
  let lit = null;
  const unlit = () => { lit?.style.removeProperty("--sx"); lit?.style.removeProperty("--sy"); lit = null; };
  const spot = (el) => {
    let card = el?.closest?.(".card:not(.set-panel)");
    if (card?.closest("dialog, [role=dialog], [role=menu]")) card = null;
    if (card !== lit) unlit();
    if (!card) return;
    lit = card;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--sx", `${targetX - r.left}px`);
    card.style.setProperty("--sy", `${targetY - r.top}px`);
  };

  // O anel persegue o alvo com uma constante de tempo de ~95 ms: a diferença para o ponto é o peso do movimento.
  function frame(now) {
    const dt = Math.min(64, now - (last || now));
    last = now;
    const k = 1 - Math.exp(-dt / 95);
    ringX += (targetX - ringX) * k;
    ringY += (targetY - ringY) * k;
    place(ring, ringX, ringY);
    if (Math.abs(targetX - ringX) + Math.abs(targetY - ringY) > .12) raf = requestAnimationFrame(frame);
    else { raf = 0; last = 0; }
  }
  const follow = () => { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } };

  document.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch") return;
    if (modal(e.target) || dragging(e.target)) { hide(); return; }
    targetX = e.clientX; targetY = e.clientY;
    if (!e.buttons) root.classList.remove("is-down");  // arrastar a janela pela barra: o Windows engole o soltar (pointerup)
    if (!visible) {
      visible = true;
      ringX = targetX; ringY = targetY;
      place(ring, ringX, ringY);
      document.documentElement.classList.add("lumen-cursor-on");
      root.classList.add("is-visible");
    }
    place(dot, targetX, targetY);
    state(e.target);
    spot(e.target);
    follow();
  }, { passive: true });
  // Mudou o conteúdo sob o ponteiro sem mover o mouse (troca de tela, diálogo): o anel se atualiza.
  document.addEventListener("pointerover", (e) => {
    if (modal(e.target) || dragging(e.target)) hide();
    else if (visible) state(e.target);
  }, { passive: true });
  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch") return;
    if (modal(e.target)) hide();
    else root.classList.add("is-down");
  }, true);
  document.addEventListener("pointerup", () => root.classList.remove("is-down"), true);
  document.addEventListener("pointercancel", () => root.classList.remove("is-down"), true);
  document.addEventListener("pointerleave", hide);
  document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); });
  window.addEventListener("blur", hide);
})();
