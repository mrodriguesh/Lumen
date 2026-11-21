"use strict";
/* Markdown seguro do Lumen, compartilhado pelo Cérebro (study.js) e pela Conversa rápida da barra flutuante (chat.js).
   O texto da IA, de notas e de páginas vira elementos (textContent), nunca HTML: nada do que o modelo escrever é
   interpretado como código. Links só com http(s). `opts.cite(sid)` transforma [S1] num botão de fonte. */
(() => {
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(e.dataset, v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) e.append(kid instanceof Node ? kid : String(kid));
    return e;
  }

  const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*|(?<!\w)_[^_\s][^_\n]*_(?!\w))|(\[[^\]\n]+\]\((https?:\/\/[^)\s]+)\))|(\[S\d{1,3}\])|(\[\[[^\]\n]+\]\])/g;
  function inline(text, opts = {}) {
    const out = []; let last = 0;
    for (const m of text.matchAll(INLINE)) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const t = m[0];
      if (m[1]) out.push(h("code", { text: t.slice(1, -1) }));
      else if (m[2]) out.push(h("strong", {}, inline(t.slice(2, -2), opts)));
      else if (m[3]) out.push(h("em", {}, inline(t.slice(1, -1), opts)));
      else if (m[4]) out.push(h("a", { href: m[5], target: "_blank", rel: "noopener noreferrer" }, t.slice(1, t.indexOf("]("))));
      else if (m[6]) { const sid = t.slice(1, -1); out.push(opts.cite ? opts.cite(sid) : t); }
      else if (m[7]) out.push(h("span", { class: "st-wikilink", text: t.slice(2, -2).split("|").pop() }));
      last = m.index + t.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }
  function md(text, opts = {}) {
    const frag = document.createDocumentFragment(), lines = String(text || "").replace(/\r/g, "").split("\n");
    let i = 0;
    const isTableSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l || "");
    const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*```/.test(line)) {
        const lang = line.trim().slice(3).trim(), code = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        i++;
        frag.append(h("pre", { class: "st-code", dataset: { lang } }, h("code", { text: code.join("\n") })));
        continue;
      }
      const head = line.match(/^(#{1,6})\s+(.*)$/);
      if (head) { frag.append(h(["h3", "h3", "h4", "h5", "h5", "h5"][head[1].length - 1], {}, inline(head[2], opts))); i++; continue; }
      if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) { frag.append(h("hr")); i++; continue; }
      if (/^\s*\|/.test(line) && isTableSep(lines[i + 1])) {
        const head2 = cells(line), body = []; i += 2;
        while (i < lines.length && /^\s*\|/.test(lines[i])) body.push(cells(lines[i++]));
        frag.append(h("div", { class: "st-table" }, h("table", {}, h("thead", {}, h("tr", {}, head2.map((c) => h("th", {}, inline(c, opts))))),
          h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => h("td", {}, inline(c, opts)))))))));
        continue;
      }
      if (/^\s*>/.test(line)) {
        const q = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
        frag.append(h("blockquote", {}, md(q.join("\n"), opts)));
        continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        const stack = [];
        while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
          const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?(.*)$/), depth = Math.floor(m[1].replace(/\t/g, "  ").length / 2);
          const ordered = /\d/.test(m[2]);
          while (stack.length > depth + 1) stack.pop();
          if (stack.length < depth + 1) {
            const list = h(ordered ? "ol" : "ul");
            (stack.length ? stack[stack.length - 1].lastElementChild || stack[stack.length - 1] : frag).append(list);
            stack.push(list);
          }
          const li = h("li", m[3] ? { class: "st-task" } : {}, m[3] ? h("input", { type: "checkbox", disabled: true, ...(/x/i.test(m[3]) ? { checked: true } : {}) }) : null, inline(m[4], opts));
          stack[stack.length - 1].append(li); i++;
        }
        continue;
      }
      if (!line.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*```|\s*>|\s*([-*+]|\d+[.)])\s+|\s*\|)/.test(lines[i])) para.push(lines[i++].trim());
      if (!para.length) para.push(lines[i++].trim());
      frag.append(h("p", {}, inline(para.join(" "), opts)));
    }
    return frag;
  }

  window.LumenMd = { md, inline };
})();
