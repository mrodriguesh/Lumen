"use strict";
// Peças da interface compartilhadas pelas janelas do Lumen (ver docs/DESIGN.md): ícone do sprite, dica (tooltip),
// confirmação e aviso rápido. Sem dependências; o visual está em ui.css.
(() => {
  const NS = "http://www.w3.org/2000/svg";
  function icon(name, cls = "") {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("class", "i" + (cls ? " " + cls : ""));
    s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS(NS, "use");
    u.setAttribute("href", "/icons.svg#" + name);
    s.append(u);
    return s;
  }
  // Troca o ícone de um botão (pausar ↔ retomar). Nunca mude o href de um <use> já desenhado: com o sprite externo o
  // Chromium não redesenha, e o ícone some ou fica o antigo. Um <svg> novo, só quando o ícone muda.
  function setIcon(el, name) {
    const old = el.querySelector("svg.i");
    if (old?.dataset.icon === name) return;
    const n = icon(name);
    n.dataset.icon = name;
    if (old) old.replaceWith(n); else el.prepend(n);
  }

  // Dica: [data-tip] (vazio = usa o aria-label) e, opcional, [data-kbd] com o atalho. Aparece no hover e no foco pelo
  // teclado, sempre dentro da janela. Substitui o title nativo, que some atrás das janelas "sempre por cima".
  let tip = null, timer = 0, target = null;
  function text(el) { return el.dataset.tip || el.getAttribute("aria-label") || ""; }
  const visible = (n) => { const s = getComputedStyle(n); return n.getBoundingClientRect().width > 1 && s.display !== "none" && s.clipPath === "none"; };
  function show(el) {
    const t = text(el);
    if (!t || !el.isConnected) return;
    // o rótulo já está à vista (rail largo, abas): a dica só repetiria; com atalho de teclado ela ainda informa algo
    if (!el.dataset.kbd && [...el.querySelectorAll("span")].some((s) => s.textContent.trim() === t && visible(s))) return;
    if (!tip) { tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("role", "tooltip"); tip.id = "lumen-tip"; document.body.append(tip); }
    tip.replaceChildren(t);
    if (el.dataset.kbd) { const k = document.createElement("kbd"); k.textContent = el.dataset.kbd; tip.append(k); }
    const r = el.getBoundingClientRect(), pos = el.dataset.tipPos || "bottom";
    tip.style.left = "0px"; tip.style.top = "0px"; tip.classList.add("on");
    const w = tip.offsetWidth, h = tip.offsetHeight, gap = 8, vw = innerWidth, vh = innerHeight;
    let x = pos === "right" ? r.right + gap : pos === "left" ? r.left - w - gap : r.left + r.width / 2 - w / 2;
    let y = pos === "right" || pos === "left" ? r.top + r.height / 2 - h / 2 : pos === "top" ? r.top - h - gap : r.bottom + gap;
    if (pos === "bottom" && y + h > vh - 4) y = r.top - h - gap;
    if (pos === "top" && y < 4) y = r.bottom + gap;
    if (pos === "right" && x + w > vw - 4) x = r.left - w - gap;
    tip.style.left = Math.round(Math.min(Math.max(4, x), vw - w - 4)) + "px";
    tip.style.top = Math.round(Math.min(Math.max(4, y), vh - h - 4)) + "px";
    el.setAttribute("aria-describedby", tip.id);
  }
  function hide() {
    clearTimeout(timer);
    if (target) target.removeAttribute("aria-describedby");
    target = null;
    tip?.classList.remove("on");
  }
  function arm(el, ms) { hide(); target = el; timer = setTimeout(() => show(el), ms); }
  document.addEventListener("pointerover", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el === target) return;
    if (el) arm(el, 450); else hide();
  });
  document.addEventListener("pointerleave", hide);
  document.addEventListener("focusin", (e) => { const el = e.target.closest?.("[data-tip]"); if (el?.matches(":focus-visible")) arm(el, 300); });
  document.addEventListener("focusout", hide);
  document.addEventListener("pointerdown", hide, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  document.addEventListener("scroll", hide, true);

  // Confirmação: só para o que não dá para desfazer. Promise<boolean>.
  let dlg = null;
  function confirm(message, { title = "Tem certeza?", ok = "Confirmar", cancel = "Cancelar", danger = false } = {}) {
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.className = "dlg confirm";
      dlg.setAttribute("aria-labelledby", "confirm-h");
      dlg.setAttribute("aria-describedby", "confirm-text");
      dlg.innerHTML = `<div class="dlg-head"><span class="dlg-icon"></span><h2 id="confirm-h"></h2></div>
        <div class="dlg-body" id="confirm-text"></div>
        <div class="dlg-foot"><button type="button" class="btn" value="cancel"></button><button type="button" class="btn primary" value="ok"></button></div>`;
      document.body.append(dlg);
    }
    const [no, yes] = dlg.querySelectorAll(".dlg-foot button");
    const ic = dlg.querySelector(".dlg-icon");
    ic.replaceChildren(icon(danger ? "alert" : "question"));
    ic.dataset.tone = danger ? "danger" : "";
    dlg.querySelector("h2").textContent = title;
    dlg.querySelector(".dlg-body").textContent = message;
    no.textContent = cancel; yes.textContent = ok;
    yes.classList.toggle("danger", danger);
    return new Promise((resolve) => {
      const done = (v) => { dlg.removeEventListener("close", onClose); no.onclick = yes.onclick = null; if (dlg.open) dlg.close(); resolve(v); };
      const onClose = () => done(false);
      no.onclick = () => done(false);
      yes.onclick = () => done(true);
      dlg.addEventListener("close", onClose);
      dlg.showModal();
      (danger ? no : yes).focus();
    });
  }

  // Aviso rápido: um por vez, no #toast da página (ou criado aqui). success/info 4 s; warning 6 s; error 9 s.
  const ICON = { success: "check-circle", info: "info", warning: "alert", error: "x-circle" };
  let toastTimer = 0;
  function toast(msg, tone = "info", ms) {
    let t = document.getElementById("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); t.setAttribute("aria-live", "polite"); document.body.append(t); }
    const close = document.createElement("button");
    close.type = "button"; close.className = "icon-btn"; close.setAttribute("aria-label", "Fechar aviso");
    close.append(icon("x"));
    close.onclick = () => { t.hidden = true; };
    const span = document.createElement("span");
    span.className = "toast-text"; span.textContent = msg;
    t.replaceChildren(icon(ICON[tone] || ICON.info), span, close);
    t.dataset.tone = tone;
    t.className = "toast" + (tone === "error" ? " err" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, ms || { error: 9000, warning: 6000 }[tone] || 4000);
  }

  window.ui = { icon, setIcon, confirm, toast, hideTip: hide };
})();
