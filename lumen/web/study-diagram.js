"use strict";
/* Lúmen Study AI — diagrama interativo (fase 5; D20). A IA manda só dados (lumen/study/diagram.py, conferidos no
   servidor); o desenho é este: SVG 2D com a paleta do holograma. Os passos acendem em ordem ("Passo a passo"; com
   movimento reduzido, um passo por clique), clicar numa parte ou Enter/Espaço mostra a explicação dela, as setas
   andam entre as partes e "Partes em lista" traz tudo em texto. A largura vem do espaço disponível: em 520 px tudo
   vira uma coluna. */
(() => {
  const L = window.lumenStudy;
  if (!L) return;
  const { h, ic, btn, toast } = L;
  const TOKEN = document.querySelector('meta[name="lumen-token"]').content;
  const NS = "http://www.w3.org/2000/svg";
  const FAMILY = { processo: "Processo", sistema: "Sistema", estrutura: "Estrutura", comparacao: "Comparação", conceitos: "Conceitos",
    linha: "Linha do tempo", ciclo: "Ciclo", mapa: "Mapa mental" };
  const SEQ = ["processo", "linha", "ciclo"];
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
  const LINE = 15, PAD = 9, GAP = 14;

  const s = (tag, attrs = {}, ...kids) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
    e.append(...kids.filter((k) => k != null));
    return e;
  };
  // Quebra o rótulo em até 3 linhas de `max` letras (SVG não quebra texto sozinho)
  function wrap(text, max) {
    const lines = [""];
    for (const w of text.split(" ")) {
      const cur = lines[lines.length - 1];
      if (!cur || (cur + " " + w).length <= max) lines[lines.length - 1] = cur ? cur + " " + w : w;
      else if (lines.length < 3) lines.push(w);
      else { lines[2] = lines[2].replace(/.?$/, "…"); break; }
    }
    return lines.map((l) => l.length > max + 2 ? l.slice(0, max) + "…" : l);
  }
  const boxH = (lines) => PAD * 2 + lines.length * LINE;
  // Relação afirmada pela IA (causa, leva a…): tracejada e com seta; "hub" e "sequencia" são a estrutura do desenho
  const isRel = (x) => !["hub", "sequencia", "contrasta com"].includes(x.kind);

  // Posições {x, y, w, lines, hgt} de cada parte (índice) e do centro (-1), conforme a família e a largura
  function layout(d, W) {
    const n = d.nodes.length, P = {}, wide = (w) => Math.floor((w - 2 * PAD) / 7.2);
    const put = (k, x, y, w, label) => { const lines = wrap(label, wide(w)); P[k] = { x, y, w, lines, hgt: boxH(lines) }; return P[k]; };
    const hasCenter = !SEQ.includes(d.family) && d.family !== "comparacao";
    const RM = d.links.some(isRel) ? 34 : 0;  // nas colunas, as relações passam pela direita, dentro desta margem
    let H = 16;
    if (SEQ.includes(d.family) && d.family === "ciclo" && W >= 560 && n <= 8) {  // anel: o ciclo se vê como ciclo
      const bw = 132, rx = W / 2 - bw / 2 - 12, ry = Math.max(120, n * 26), cx = W / 2, cy = ry + 40;
      d.nodes.forEach((nd, k) => { const a = -Math.PI / 2 + 2 * Math.PI * k / n; const p = put(k, cx + rx * Math.cos(a) - bw / 2, 0, bw, nd.label); p.y = cy + ry * Math.sin(a) - p.hgt / 2; });
      put(-1, cx - 70, cy - 22, 140, d.concept); P[-1].center = true; P[-1].y = cy - P[-1].hgt / 2;
      return { P, H: cy + ry + 48, ring: true };
    }
    if (SEQ.includes(d.family)) {  // uma coluna com o trilho numerado à esquerda
      d.nodes.forEach((nd, k) => { const p = put(k, 52, H, W - 68 - RM, nd.label); H += p.hgt + GAP + 6; });
      return { P, H: H + 4, rail: true, column: true };
    }
    if (d.family === "estrutura") {  // camadas: cada uma um pouco mais larga, como um corte
      const top = put(-1, 16, H, W - 32 - RM, d.concept); top.center = true; H += top.hgt + GAP;
      d.nodes.forEach((nd, k) => { const w = (W - 32 - RM) * (0.62 + 0.38 * (n > 1 ? k / (n - 1) : 1)); const p = put(k, (W - RM - w) / 2, H, w, nd.label); H += p.hgt + 8; });
      return { P, H: H + 8, column: true };
    }
    if (d.family === "comparacao") {  // dois lados, cada um com os seus detalhes embaixo
      const cw = (W - 48) / 2, col = [16, 32 + cw], y = [H, H];
      [0, 1].forEach((side) => { const p = put(side, col[side], H, cw, d.nodes[side].label); y[side] += p.hgt + 26; });
      d.nodes.forEach((nd, k) => { if (k < 2) return; const side = nd.parent; const p = put(k, col[side] + 14, y[side], cw - 14, nd.label); y[side] += p.hgt + 10; });
      return { P, H: Math.max(...y) + 8, versus: true };
    }
    // conceitos, sistema e mapa: o centro no meio e os ramos dos dois lados (filhos para fora); estreito, uma árvore
    const tops = d.nodes.map((nd, k) => k).filter((k) => d.nodes[k].parent < 0), kids = (k) => d.nodes.map((nd, j) => j).filter((j) => d.nodes[j].parent === k);
    const anyKids = tops.some((k) => kids(k).length), need = anyKids ? 660 : 470;
    if (W >= need && hasCenter) {
      const cw = 140, bw = anyKids ? 132 : (W - cw - 64) / 2, kw = anyKids ? (W - cw - 2 * bw - 64) / 2 : 0;
      const right = tops.slice(0, Math.ceil(tops.length / 2)), left = tops.slice(Math.ceil(tops.length / 2)).reverse();
      const col = (list, side) => {
        let y = 16;
        for (const k of list) {
          const bx = side ? W / 2 + cw / 2 + 16 : W / 2 - cw / 2 - 16 - bw, kx = side ? bx + bw + 16 : bx - 16 - kw;
          const b = put(k, bx, 0, bw, d.nodes[k].label), ks = kids(k).map((j) => put(j, kx, 0, kw, d.nodes[j].label));
          const kh = ks.reduce((a, p) => a + p.hgt + 8, -8), gh = Math.max(b.hgt, kh);
          b.y = y + (gh - b.hgt) / 2;
          let ky = y + (gh - Math.max(kh, 0)) / 2;
          for (const p of ks) { p.y = ky; ky += p.hgt + 8; }
          y += gh + GAP;
        }
        return y;
      };
      H = Math.max(col(right, 1), col(left, 0), 90);
      const c = put(-1, W / 2 - cw / 2, 0, cw, d.concept); c.center = true; c.y = H / 2 - c.hgt / 2;
      return { P, H: H + 4, sides: true };
    }
    const c = put(-1, 16, H, Math.min(W - 32 - RM, 300), d.concept); c.center = true; H += c.hgt + GAP;
    for (const k of tops) {
      const b = put(k, 44, H, W - 60 - RM, d.nodes[k].label); H += b.hgt + 8;
      for (const j of kids(k)) { const p = put(j, 72, H, W - 88 - RM, d.nodes[j].label); H += p.hgt + 8; }
      H += GAP - 8;
    }
    return { P, H: H + 4, tree: true, column: true };
  }

  const mid = (p) => ({ x: p.x + p.w / 2, y: p.y + p.hgt / 2 });
  function edge(a, b, how) {  // ponto da borda de cada caixa e uma curva suave entre eles
    const A = mid(a), B = mid(b);
    if (how === "tree") return `M${a.x + 12} ${a.y + a.hgt} V${B.y} H${b.x}`;
    if (how === "side") { const ax = B.x > A.x ? a.x + a.w : a.x, bx = B.x > A.x ? b.x : b.x + b.w, m = (ax + bx) / 2; return `M${ax} ${A.y} C${m} ${A.y},${m} ${B.y},${bx} ${B.y}`; }
    return `M${A.x} ${A.y} L${B.x} ${B.y}`;
  }

  function render(d, opts = {}) {
    const wrapEl = h("figure", { class: "st-dg", dataset: { family: d.family } });
    const detail = h("div", { class: "st-dg-detail", "aria-live": "polite" }, h("p", { class: "faint", text: "Clique numa parte (ou use Tab e Enter) para ver a explicação dela." }));
    const stage = h("div", { class: "st-dg-stage" });
    let nodesEl = [], current = -1, timer = 0, step = -1;
    const order = d.nodes.map((_, k) => k);

    function select(k, focus = false) {
      current = k;
      nodesEl.forEach((g, j) => { g.classList.toggle("sel", j === k); g.setAttribute("aria-pressed", String(j === k)); });
      const nd = d.nodes[k];
      detail.replaceChildren(...[h("h4", { class: "st-dg-title" }, h("span", { class: "st-dg-n", text: String(k + 1) }), nd.label),
        h("p", { text: nd.detail || "A IA não deu uma explicação para esta parte." }),
        opts.ask ? btn("Explicar esta parte", () => opts.ask(`Explique “${nd.label}”, dentro de “${d.concept}”.`), { icon: "sparkle", cls: "btn sm ghost" }) : null].filter(Boolean));
      if (focus) nodesEl[k]?.focus();
    }
    function light(upto) {
      step = upto;
      nodesEl.forEach((g, j) => { g.classList.toggle("lit", order.indexOf(j) <= upto); g.classList.toggle("now", order[upto] === j); });
      if (upto >= 0) select(order[upto]);
      label();
    }
    function label() {  // o que o botão faz agora: começar, pausar, continuar, avançar ou ver de novo
      const end = step >= order.length - 1, next = `(${step + 2} de ${order.length})`;
      tour.replaceChildren(ic(end ? "refresh" : timer ? "pause" : "play"), h("span", { text: step < 0 ? "Passo a passo" : end ? "Ver de novo"
        : timer ? "Pausar" : REDUCED.matches ? `Próximo passo ${next}` : `Continuar ${next}` }));
    }
    function stop() { clearInterval(timer); timer = 0; label(); }
    const tour = btn("Passo a passo", () => {
      if (timer) { stop(); return; }
      if (step >= order.length - 1) { nodesEl.forEach((g) => g.classList.remove("lit", "now")); step = -1; }
      if (REDUCED.matches) { light(step + 1); return; }  // movimento reduzido: um passo por clique, sem animação sozinha
      timer = setInterval(() => { if (!wrapEl.isConnected || step >= order.length - 1) { stop(); return; } light(step + 1); }, 1600);
      light(step + 1);
    }, { icon: "play", cls: "btn sm primary st-dg-tour" });
    // Tour narrado (fase 6): a voz lê cada parte em ordem (rótulo e explicação) e a parte falada acende junto
    const V = window.lumenVoice;
    const narrate = V ? btn("Tour narrado", () => {
      if (narrate.getAttribute("aria-pressed") === "true") return V.stop();
      stop();
      nodesEl.forEach((g) => g.classList.remove("lit", "now")); step = -1;
      narrate.setAttribute("aria-pressed", "true");
      V.speak("", { use: "chat", parts: order.map((k) => `${d.nodes[k].label}. ${d.nodes[k].detail || ""}`),
        onPart: (p) => { if (wrapEl.isConnected) light(p); }, onEnd: () => narrate.setAttribute("aria-pressed", "false") });
    }, { icon: "volume", cls: "btn sm ghost st-dg-narrate", tip: "A voz explica cada parte, em ordem" }) : null;
    narrate?.setAttribute("aria-pressed", "false");

    function draw() {
      const W = Math.max(300, Math.min(760, Math.floor(stage.clientWidth || wrapEl.clientWidth || 640)));
      const { P, H, rail, ring, sides, tree, versus, column } = layout(d, W);
      const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "st-dg-svg", role: "group",
        "aria-label": `${FAMILY[d.family]}: ${d.title}. ${d.nodes.length} partes. Use as setas para andar entre elas.` });
      svg.append(s("defs", {}, s("marker", { id: "st-dg-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, s("path", { d: "M0 0 L10 5 L0 10 z", class: "st-dg-tip" }))));
      const lines = s("g", { class: "st-dg-links" });
      svg.append(lines);
      if (rail) {  // trilho das etapas: número (processo, ciclo) ou ponto (linha do tempo)
        const ks = Object.keys(P).map(Number).filter((k) => k >= 0);
        lines.append(s("line", { x1: 26, y1: mid(P[ks[0]]).y, x2: 26, y2: mid(P[ks[ks.length - 1]]).y, class: "st-dg-rail" }));
        if (d.family === "ciclo") { const a = mid(P[ks[ks.length - 1]]), b = mid(P[0]); lines.append(s("path", { d: `M14 ${a.y} C2 ${a.y},2 ${b.y},14 ${b.y}`, class: "st-dg-link seq", "marker-end": "url(#st-dg-arrow)" }, s("title", {}, "O ciclo recomeça"))); }
      }
      for (const x of d.links) {
        const a = P[x.a], b = P[x.b];
        if (!a || !b || (rail && x.kind === "sequencia")) continue;
        const rel = isRel(x) || (x.kind === "contrasta com" && !versus);
        let path;
        if (ring && x.kind === "sequencia") { const A = mid(a), B = mid(b), cx = (A.x + B.x) / 2 + (B.y - A.y) * .18, cy = (A.y + B.y) / 2 - (B.x - A.x) * .18; path = `M${A.x} ${A.y} Q${cx} ${cy} ${B.x} ${B.y}`; }
        else if (rel && column) { const A = mid(a), B = mid(b), xr = Math.min(W - 4, Math.max(a.x + a.w, b.x + b.w) + 28); path = `M${a.x + a.w} ${A.y} C${xr} ${A.y},${xr} ${B.y},${b.x + b.w} ${B.y}`; }
        else if (rel) { const A = mid(a), B = mid(b); path = `M${A.x} ${A.y} L${B.x} ${B.y}`; }
        else if (versus) { const A = mid(a), B = mid(b); path = x.kind === "contrasta com" ? `M${a.x + a.w} ${A.y} L${b.x} ${B.y}` : `M${a.x + 8} ${a.y + a.hgt} V${B.y} H${b.x}`; }
        else path = edge(a, b, tree ? "tree" : sides ? "side" : "line");
        lines.append(s("path", { d: path, class: "st-dg-link " + (rel ? "rel" : x.kind === "sequencia" ? "seq" : "hub"), "marker-end": rel || x.kind === "sequencia" ? "url(#st-dg-arrow)" : null },
          s("title", {}, rel || x.kind === "contrasta com" ? `${(P[x.a].lines || []).join(" ")} ${x.kind} ${(P[x.b].lines || []).join(" ")}` : "")));
      }
      if (versus) { const A = mid(P[0]), B = mid(P[1]); svg.append(s("text", { x: (A.x + B.x) / 2, y: A.y - 8, class: "st-dg-vs", "text-anchor": "middle" }, "×")); }
      const box = (k, p) => {
        const g = s("g", { class: "st-dg-node" + (p.center ? " center" : "") + (k >= 0 ? " role-" + d.nodes[k].role : ""), transform: `translate(${p.x},${p.y})` },
          s("rect", { width: p.w, height: p.hgt, rx: p.center ? 14 : 10 }),
          s("text", { x: p.center ? p.w / 2 : PAD + (rail ? 2 : 0), y: PAD + 11, "text-anchor": p.center ? "middle" : null }, ...p.lines.map((l, i) => s("tspan", { x: p.center ? p.w / 2 : PAD + (rail ? 2 : 0), dy: i ? LINE : 0 }, l))));
        if (rail && k >= 0) { g.append(s("circle", { cx: 26 - p.x, cy: p.hgt / 2, r: d.family === "linha" ? 6 : 11, class: "st-dg-dot" })); if (d.family !== "linha") g.append(s("text", { x: 26 - p.x, y: p.hgt / 2 + 4, class: "st-dg-num", "text-anchor": "middle" }, String(k + 1))); }
        return g;
      };
      if (P[-1]) svg.append(box(-1, P[-1]));
      nodesEl = d.nodes.map((nd, k) => {
        const g = box(k, P[k]);
        g.setAttribute("tabindex", "0"); g.setAttribute("role", "button"); g.setAttribute("aria-pressed", "false");
        g.setAttribute("aria-label", `Parte ${k + 1} de ${d.nodes.length}: ${nd.label}`);
        g.addEventListener("click", () => { stop(); select(k); });
        g.addEventListener("keydown", (e) => {
          const go = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1, Home: -Infinity, End: Infinity }[e.key];
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); stop(); select(k); }
          else if (go) { e.preventDefault(); const j = Math.max(0, Math.min(d.nodes.length - 1, k + (Number.isFinite(go) ? go : go > 0 ? d.nodes.length : -d.nodes.length))); nodesEl[j].focus(); }
        });
        svg.append(g);
        return g;
      });
      stage.replaceChildren(svg);
      if (step >= 0) light(step);
      if (current >= 0) select(current);
    }

    const tops = d.nodes.map((nd, k) => [nd, k]).filter(([nd]) => nd.parent < 0);
    const item = (nd, k) => h("li", {}, h("strong", { text: nd.label }), nd.detail ? ` — ${nd.detail}` : "");
    const list = h("details", { class: "st-dg-list" }, h("summary", { text: "Partes em lista" }),
      d.family === "mapa"
        ? h("ul", { class: "st-list" }, tops.map(([nd, k]) => h("li", {}, h("strong", { text: nd.label }), nd.detail ? ` — ${nd.detail}` : "",
          h("ul", {}, d.nodes.map((c, j) => c.parent === k ? item(c, j) : null)))))
        : h("ol", { class: "st-list" }, d.nodes.map((nd, k) => item(nd, k))),
      d.links.some((x) => !["hub", "sequencia"].includes(x.kind)) ? h("p", { class: "eyebrow", text: "Ligações" }) : null,
      h("ul", { class: "st-list" }, d.links.filter((x) => !["hub", "sequencia"].includes(x.kind)).map((x) =>
        h("li", {}, h("strong", { text: x.a < 0 ? d.concept : d.nodes[x.a].label }), ` ${x.kind} `, h("strong", { text: d.nodes[x.b].label })))));

    async function png() {
      try {
        const r = await fetch("/api/study/diagram", { method: "POST", headers: { "Content-Type": "application/json", "X-Lumen-Token": TOKEN }, body: JSON.stringify({ spec: d, format: "png" }) });
        if (!r.ok) { let v = {}; try { v = await r.json(); } catch { /* */ } throw new Error(v.error?.message || "Não foi possível gerar a imagem."); }
        const a = h("a", { href: URL.createObjectURL(await r.blob()), download: `${d.title.replace(/[<>:"/\\|?*]/g, " ").slice(0, 80)}.png` });
        document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      } catch (e) { toast(e.message, "error"); }
    }
    wrapEl.append(
      h("figcaption", { class: "st-dg-head" }, h("span", { class: "st-dg-kicker", text: FAMILY[d.family] }), h("span", { class: "st-dg-name", text: d.title }),
        d.more ? h("span", { class: "faint", text: ` · +${d.more} fora do diagrama` }) : null),
      stage, detail,
      h("div", { class: "st-dg-actions" }, tour, narrate, btn("Baixar PNG", png, { icon: "download", cls: "btn sm ghost" }), opts.actions || null),
      list);
    new ResizeObserver(() => { const w = stage.clientWidth; if (w && w !== stage._w) { stage._w = w; draw(); } }).observe(stage);
    return wrapEl;
  }

  L.diagram = render;
})();
