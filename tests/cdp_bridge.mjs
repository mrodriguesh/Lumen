// Ponte CDP: lê comandos JSON (uma linha cada) do stdin e responde no stdout. Edge headless já aberto na porta dada.
import { createInterface } from "node:readline";
import { writeFileSync } from "node:fs";
const port = process.argv[2];
const pages = {};

async function open(url) {
  const t = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const pending = new Map(), errors = [];
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
  });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Runtime.enable");
  await send("Page.enable");
  return { send, errors, ws };
}

const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  const c = JSON.parse(line);
  let out;
  try {
    const p = pages[c.name];
    if (c.op === "open") {
      pages[c.name] = await open(c.url);
      await pages[c.name].send("Emulation.setFocusEmulationEnabled", { enabled: true });
      await pages[c.name].send("Emulation.setDeviceMetricsOverride", { width: c.w, height: c.h, deviceScaleFactor: 2, mobile: false });
      out = true;
    } else if (c.op === "eval") {
      const r = await p.send("Runtime.evaluate", { expression: c.expr, awaitPromise: true, returnByValue: true });
      if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "falha ao avaliar");
      out = r.result.result.value;
    } else if (c.op === "size") {
      out = await p.send("Emulation.setDeviceMetricsOverride", { width: c.w, height: c.h, deviceScaleFactor: 2, mobile: false });
    } else if (c.op === "dark") {
      out = await p.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: c.on ? "dark" : "light" }] });
    } else if (c.op === "key") {  // Ctrl+Alt+<letra>
      const k = { key: c.key, code: "Key" + c.key.toUpperCase(), windowsVirtualKeyCode: c.key.toUpperCase().charCodeAt(0), modifiers: c.mods };
      await p.send("Input.dispatchKeyEvent", { type: "rawKeyDown", ...k });
      out = await p.send("Input.dispatchKeyEvent", { type: "keyUp", ...k });
    } else if (c.op === "shot") {
      const s = await p.send("Page.captureScreenshot", { format: "png" });
      writeFileSync(c.path, Buffer.from(s.result.data, "base64"));
      out = c.path;
    } else if (c.op === "errors") {
      out = Object.fromEntries(Object.entries(pages).map(([k, v]) => [k, v.errors]));
    } else if (c.op === "quit") { process.stdout.write(JSON.stringify({ ok: true }) + "\n"); process.exit(0); }
    process.stdout.write(JSON.stringify({ ok: true, value: out ?? null }) + "\n");
  } catch (e) { process.stdout.write(JSON.stringify({ ok: false, error: String(e) }) + "\n"); }
}
