// Teste visual no Obsidian de verdade, pelo CDP, num perfil isolado (não toca no Obsidian do usuário).
// Uso: node tests/obsidian_cdp.mjs <porta> <pasta-das-capturas> <arquivo1> [arquivo2…]
// Abra antes: Obsidian.exe --user-data-dir=<perfil temporário> --remote-debugging-port=<porta>, com um
// obsidian.json nesse perfil apontando para a cópia do cofre (open: true). Para cada arquivo: abre, espera
// desenhar, mede os cards do canvas (sobreposição, texto cortado) e salva uma captura.
import { writeFileSync } from "node:fs";
const [port, outDir, ...files] = process.argv.slice(2);

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const t = list.find((x) => x.type === "page" && x.url.startsWith("app://"));
      if (t) return t;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("Obsidian não respondeu no CDP");
}
const t = await target();
const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400));
  return r.result?.result?.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 60 && !(await ev("!!(window.app && app.workspace && app.workspace.layoutReady)")); i++) await sleep(500);
await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
const report = [];
for (const [n, f] of files.entries()) {
  for (let i = 0; i < 40 && !(await ev(`!!app.vault.getAbstractFileByPath(${JSON.stringify(f)})`)); i++) await sleep(500);
  await ev(`(async () => { const leaf = app.workspace.getLeaf("tab"); window.__leaf = leaf;
    await leaf.openFile(app.vault.getAbstractFileByPath(${JSON.stringify(f)})); app.workspace.setActiveLeaf(leaf, { focus: true }); })()`);
  await sleep(2500);
  let info = null;
  if (f.endsWith(".canvas")) {
    await ev("(() => { const v = window.__leaf.view; v.canvas && v.canvas.zoomToFit(); })()");
    await sleep(1500);
    info = await ev(`(() => {
      const c = window.__leaf.view.canvas, nodes = [...c.nodes.values()];
      const cards = nodes.filter((n) => n.unknownData.type !== "group");
      const box = (n) => ({ x: n.x, y: n.y, w: n.width, h: n.height });
      let overlaps = 0;
      for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) {
        const a = box(cards[i]), b = box(cards[j]);
        if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlaps++;
      }
      // texto cortado: o conteúdo desenhado é mais alto que o card
      const cut = cards.filter((n) => n.unknownData.type === "text" && n.contentEl
        && n.contentEl.querySelector(".markdown-preview-view, .markdown-rendered")
        && n.contentEl.querySelector(".markdown-preview-view, .markdown-rendered").scrollHeight > n.contentEl.clientHeight + 4)
        .map((n) => n.unknownData.text.slice(0, 40));
      return { nodes: nodes.length, edges: c.edges.size, overlaps, cut, groups: nodes.length - cards.length };
    })()`);
  } else {
    info = await ev(`(() => ({ title: document.title, errors: document.querySelectorAll(".bases-error, .callout.callout-error").length }))()`);
  }
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const path = `${outDir}/${n + 1}-${f.split("/").pop().replace(/[^\w.-]+/g, "_")}.png`;
  writeFileSync(path, Buffer.from(shot.result.data, "base64"));
  report.push({ file: f, shot: path, info });
}
process.stdout.write(JSON.stringify(report, null, 1) + "\n");
process.exit(0);
