"use strict";
// Mostruário (/design): a grade com todos os ícones do sprite e os botões de aviso e confirmação.
(async () => {
  const sprite = await (await fetch("/icons.svg")).text();
  const names = [...sprite.matchAll(/<symbol id="([^"]+)"/g)].map((m) => m[1]);
  document.getElementById("ds-icons").replaceChildren(...names.map((n) => {
    const box = document.createElement("span");
    box.className = "ds-icon";
    box.append(ui.icon(n), n);
    return box;
  }));
})();
document.getElementById("ds-toast").addEventListener("click", () => ui.toast("Notion conectado."));
document.getElementById("ds-toast-err").addEventListener("click", () => ui.toast("O Lumen parou de responder. Abra o aplicativo de novo.", "error"));
document.getElementById("ds-confirm").addEventListener("click", () =>
  ui.confirm("A gravação será apagada deste PC.", { title: "Descartar a gravação?", ok: "Descartar", danger: true }));
