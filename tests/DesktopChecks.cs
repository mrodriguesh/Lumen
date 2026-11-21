using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Compilado com os arquivos do launcher; dados isolados por LUMEN_DATA.
static class DesktopChecks
{
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    static void Check(bool ok, string message) { if (!ok) throw new Exception(message); }
    static object Field(object o, string name) { return o.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(o); }
    static async Task<bool> Until(WebView2 web, string js, int ms = 5000)
    {
        for (int i = 0; i < ms / 100; i++) { if (await web.ExecuteScriptAsync(js) == "true") return true; await Task.Delay(100); }
        return false;
    }
    static async Task<bool> Until(Func<bool> ok, int ms = 5000)
    {
        for (int i = 0; i < ms / 100 && !ok(); i++) await Task.Delay(100);
        return ok();
    }
    // Uma promessa da página (ExecuteScriptAsync não espera): resolve num global e confere até ele ficar true.
    static async Task<bool> Ask(WebView2 web, string promise, int ms = 5000)
    {
        await web.ExecuteScriptAsync("window.__ok=null;(" + promise + ").then(v=>window.__ok=!!v,()=>window.__ok=false)");
        return await Until(web, "window.__ok===true", ms);
    }
    // Imagem do WebView2 real (renderização por software, como no app) quando LUMEN_SHOTS aponta para uma pasta.
    static async Task Shot(WebView2 web, string name)
    {
        string dir = Environment.GetEnvironmentVariable("LUMEN_SHOTS");
        if (dir == null || web.CoreWebView2 == null) return;
        Directory.CreateDirectory(dir);
        await Task.Delay(250);
        using (var f = File.Create(Path.Combine(dir, name + ".png")))
            await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, f);
    }
    static string Js(string text) { return "'" + text.Replace("\\", "\\\\").Replace("'", "\\'") + "'"; }
    static string Typing(string field, string text)
    {
        return "(()=>{const t=document.querySelector('" + field + "');t.focus();t.value=" + Js(text) + ";t.dispatchEvent(new Event('input'));})()";
    }
    // Janela flutuante de “Minha compreensão”: sempre inteira na tela, entre o tamanho mínimo e o máximo.
    static void NoteGeometry()
    {
        int cases = 0;
        foreach (var area in new[] { new Rectangle(0,0,1920,1040), new Rectangle(-1920,0,1920,1080), new Rectangle(0,-1080,1920,1080), new Rectangle(0,0,1366,728), new Rectangle(0,0,800,560) })
        foreach (float k in new[] { 1f, 1.25f, 1.5f, 2f }) {
            Size min = NoteForm.MinSize(area, k), max = NoteForm.MaxSize(area);
            var first = NoteForm.Default(area, k);
            Check(area.Contains(first), "Posição inicial dentro da tela");
            Check(first.Right > area.Left + area.Width / 2, "Posição inicial longe do centro (lado direito, onde o player costuma não estar)");
            foreach (var wanted in new[] { new Rectangle(area.Right - 10, area.Bottom - 10, 400, 500), new Rectangle(area.Left - 5000, area.Top - 5000, 99999, 99999),
                                           new Rectangle(area.Left + 20, area.Top + 20, 1, 1), new Rectangle(area.Left + 100, area.Top + 100, 420, 380) }) {
                var r = NoteForm.Fit(wanted, area, min, max);
                Check(area.Contains(r), "Janela flutuante inteira dentro da área útil: " + r + " em " + area);
                Check(r.Width >= Math.Min(min.Width, area.Width) && r.Height >= Math.Min(min.Height, area.Height), "Tamanho mínimo confortável");
                Check(r.Width <= Math.Max(min.Width, max.Width) && r.Height <= Math.Max(min.Height, max.Height), "Tamanho máximo: não ocupa a tela toda por acidente");
                cases++;
            }
            string saved = "v1|" + (area.Left + 30) + "|" + (area.Top + 40) + "|" + (int)(420 * k) + "|" + (int)(380 * k);
            var back = NoteForm.Restore(saved, new[] { area }, area, k);
            Check(back.Location == new Point(area.Left + 30, area.Top + 40), "Lembra a posição salva");
            Check(NoteForm.Restore("v1|99999|99999|400|500", new[] { area }, area, k) == first, "Tela que não existe mais: volta ao padrão");
            Check(NoteForm.Restore("lixo", new[] { area }, area, k) == first, "Arquivo inválido: volta ao padrão");
            cases += 3;
        }
        Console.WriteLine("OK: " + cases + " casos de geometria da janela flutuante (telas, origens negativas, escalas, notebook e tela pequena).");
    }
    static void Geometry()
    {
        int cases = 0;
        foreach (var area in new[] { new Rectangle(0,0,1920,1040), new Rectangle(-1920,0,1920,1080), new Rectangle(0,-1080,1920,1080), new Rectangle(0,0,800,1280) })
        foreach (float scale in new[] { 1f, 1.25f, 1.5f, 2f, 3f }) {
            var peek = new Size((int)Math.Round(12*scale),(int)Math.Round(84*scale));
            foreach (bool right in new[] { false, true }) foreach (bool bottom in new[] { false, true }) {
                var point = new Point(right ? area.Right-peek.Width : area.Left, bottom ? area.Bottom-peek.Height : area.Top);
                var near = new Point(point.X+(right ? -10 : 10),point.Y+(bottom ? -10 : 10));
                Check(WidgetForm.SnapAnchor(near,peek,area,(int)(48*scale)) == point,"Encaixe no canto");
                foreach (var size in new[] { peek, new Size((int)(80*scale),(int)(132*scale)), new Size((int)(304*scale),(int)(252*scale)), new Size((int)(WidgetForm.ProtectionPanel.Width*scale),(int)(WidgetForm.ProtectionPanel.Height*scale)),
                                             new Size((int)(WidgetForm.ChatWide.Width*scale),(int)(WidgetForm.ChatWide.Height*scale)) }) {
                    var bounds = WidgetForm.WidgetBounds(point,size,peek,area);
                    Check(area.Contains(bounds),"Painel dentro da área útil, inclusive DPI e telas com origem negativa");
                    Check(bounds.Contains(new Rectangle(point,peek)),"Animação mantém a alça sob o mouse");
                    Check((right ? bounds.Right == area.Right : bounds.Left == area.Left) && (bottom ? bounds.Bottom == area.Bottom : bounds.Top == area.Top),"Painel cresce para dentro do canto");
                    cases++;
                }
            }
            foreach (string edge in new[] { "left","right","top","bottom" }) {
                bool horizontal=edge=="top" || edge=="bottom";
                Size handle=WidgetForm.PeekSize(edge,scale,area);
                var point=new Point(horizontal ? area.Left+(area.Width-handle.Width)/2 : edge=="left" ? area.Left : area.Right-handle.Width,
                                    horizontal ? edge=="top" ? area.Top : area.Bottom-handle.Height : area.Top+(area.Height-handle.Height)/2);
                Check(WidgetForm.NearestEdge(new Rectangle(point,handle),area,(int)(48*scale))==edge,"Seleciona orientação da borda");
                foreach (var size in new[] { handle,new Size((int)(132*scale),(int)(132*scale)),new Size((int)(304*scale),(int)(252*scale)),new Size((int)(WidgetForm.ProtectionPanel.Width*scale),(int)(WidgetForm.ProtectionPanel.Height*scale)),
                                             new Size((int)(WidgetForm.ChatWide.Width*scale),(int)(WidgetForm.ChatWide.Height*scale)) }) {
                    Rectangle bounds=WidgetForm.WidgetBounds(point,size,handle,area);
                    Check(area.Contains(bounds) && bounds.Contains(new Rectangle(point,handle)),"Painel mantém o mouse dentro nas quatro orientações");
                    Check(edge=="top" ? bounds.Top==area.Top : edge=="bottom" ? bounds.Bottom==area.Bottom : edge=="left" ? bounds.Left==area.Left : bounds.Right==area.Right,"Expansão para dentro da borda");
                    cases++;
                }
            }
        }
        Console.WriteLine("OK: "+cases+" casos de geometria, quatro bordas/cantos e escalas de 100% a 300%.");
    }
    // ---------- Conversa rápida na barra REAL (WebView2, renderização por software, janela nativa) ----------
    // O backend real e a lógica da conversa já são provados em tests/chat_ui.py (servidor real, Ollama falso). Aqui o que só a janela nativa
    // prova: tamanho e posição ao abrir/recolher, quatro bordas, interrupção da animação, mensagens ao Lumen.exe, e o streaming no WebView2 de
    // verdade. A resposta vem de um fetch simulado NA PÁGINA (o servidor isolado não tem IA), com pedaços a cada 30 ms.
    const string ChatStub = @"(() => {
  if (window.__stub) return; window.__stub = { turns: 0, aborted: 0, words: 120, gap: 30 };
  const real = window.fetch.bind(window), enc = new TextEncoder(), line = (o) => enc.encode(JSON.stringify(o) + '\n');
  const conv = () => ({ id: 'stub0001', title: 'Teste', updated: '1', temporary: false, generating: false, project_id: null, messages: window.__stub.messages || [], pending: [], created: [] });
  window.fetch = (u, o) => {
    const url = String(u);
    if (url === '/api/study/turn') {
      window.__stub.turns++;
      const body = JSON.parse(o.body); let timer = 0, acc = '';
      const stream = new ReadableStream({ start(c) {
        const evs = [{ type: 'conversation', conversation: { id: 'stub0001', title: 'Teste', project_id: null, temporary: false } }, { type: 'user', message: { id: 11, content: body.text, meta: {} } }, { type: 'status', stage: 'searching' }];
        let i = 0, k = 0;
        const pump = () => {
          if (k < evs.length) c.enqueue(line(evs[k++]));
          else if (i < window.__stub.words) { const t = 'palavra' + (i++) + ' '; acc += t; c.enqueue(line({ type: 'delta', text: t })); }
          else { window.__stub.messages = [{ id: 11, role: 'user', content: body.text, sources: [], meta: {} }, { id: 12, role: 'assistant', content: acc, sources: [], meta: {} }]; c.enqueue(line({ type: 'done', message: { id: 12, content: acc, sources: [], meta: {} } })); c.close(); return; }
          timer = setTimeout(pump, window.__stub.gap);
        };
        pump();
        if (o.signal) o.signal.addEventListener('abort', () => { clearTimeout(timer); window.__stub.aborted++; try { c.error(new DOMException('abort', 'AbortError')); } catch (e) {} });
      } });
      return Promise.resolve(new Response(stream, { status: 200 }));
    }
    if (url.startsWith('/api/study/conversation')) return Promise.resolve(new Response(JSON.stringify(conv()), { status: 200 }));
    if (url === '/api/study/cancel') return Promise.resolve(new Response('{}', { status: 200 }));
    return real(u, o);
  };
  window.__probe = { on: false, last: 0, frames: 0, sum: 0, max: 0, long: 0, longMs: [] };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { window.__probe.long++; window.__probe.longMs.push(Math.round(e.duration)); } }).observe({ entryTypes: ['longtask'] }); } catch (e) {}
  const loop = (t) => { const p = window.__probe; if (p.on) { if (p.last) { const d = t - p.last; p.frames++; p.sum += d; if (d > p.max) p.max = d; } p.last = t; } else p.last = 0; requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
})()";
    // Cada tamanho que a janela assume durante uma animação (1 amostra a cada ~8 ms), para provar que ela vai de um estado ao outro sem salto.
    static async Task<System.Collections.Generic.List<Size>> Trace(Form f, int ms)
    {
        var list = new System.Collections.Generic.List<Size>();
        var clock = System.Diagnostics.Stopwatch.StartNew();
        while (clock.ElapsedMilliseconds < ms) { list.Add(f.Size); await Task.Delay(8); }
        return list;
    }
    static double WebViewCpu()
    {
        double total = 0; string dir = Path.Combine(Program.Data, "webview");
        try {
            using (var s = new System.Management.ManagementObjectSearcher("SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='msedgewebview2.exe'"))
                foreach (System.Management.ManagementObject o in s.Get()) {
                    string cmd = o["CommandLine"] as string ?? "";
                    if (cmd.IndexOf(dir, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    try { total += System.Diagnostics.Process.GetProcessById(Convert.ToInt32(o["ProcessId"])).TotalProcessorTime.TotalSeconds; } catch (Exception) { }
                }
        } catch (Exception) { }
        return total;
    }
    // Essenciais da conversa: existem, estão visíveis, DENTRO da janela (viewport) e recebem clique (elementFromPoint no centro); o painel não tem
    // overflow e a moldura (.notch) tem o tamanho da janela. Devolve "ok" ou a lista do que falhou.
    const string ChatEssentials = "(()=>{const o=[],vw=innerWidth,vh=innerHeight,n=document.querySelector('.notch').getBoundingClientRect();" +
        "if(Math.abs(n.width-vw)>1.5||Math.abs(n.height-vh)>1.5||Math.abs(n.left)>1.5||Math.abs(n.top)>1.5)o.push('notch '+Math.round(n.left)+','+Math.round(n.top)+' '+Math.round(n.width)+'x'+Math.round(n.height)+' em '+vw+'x'+vh);" +
        "for(const s of ['#chat-title','#chat-more','#chat-collapse','#chat-mode','#chat-input','#chat-send','#chat-thread','#chat-form']){const e=document.querySelector(s);if(!e){o.push(s+' ausente');continue;}" +
        "const b=e.getBoundingClientRect(),c=getComputedStyle(e);if(c.visibility==='hidden'||c.display==='none'||b.width<4||b.height<4){o.push(s+' oculto');continue;}" +
        "if(b.left<-.5||b.top<-.5||b.right>vw+.5||b.bottom>vh+.5){o.push(s+' fora '+[b.left,b.top,b.right,b.bottom].map(Math.round));continue;}" +
        "const t=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);if(!(t&&(e===t||e.contains(t))))o.push(s+' coberto');}" +
        "const p=document.querySelector('#chat-panel');if(p.scrollWidth>p.clientWidth+1||p.scrollHeight>p.clientHeight+1)o.push('overflow do painel');" +
        "const ta=document.querySelector('#chat-input');if(!ta.value&&ta.scrollHeight>ta.clientHeight+1)o.push('campo vazio com rolagem (a dica quebrou de linha)');" +
        "return o.length?o.join(' | '):'ok';})()";
    // Medidas da página (CSS px) para confrontar com a janela (pixels físicos): viewport, documento, moldura, blocos da conversa e o que a tela informa.
    const string ChatProbe = "(()=>{const r=(s)=>{const e=document.querySelector(s);if(!e)return null;const b=e.getBoundingClientRect();return [b.left,b.top,b.right,b.bottom].map(v=>Math.round(v*10)/10);};" +
        "return {inner:[innerWidth,innerHeight],doc:[document.documentElement.clientWidth,document.documentElement.clientHeight],dpr:devicePixelRatio,screen:[screen.availWidth,screen.availHeight],size:document.body.dataset.chatSize," +
        "notch:r('.notch'),head:r('.chat-head'),mode:r('.chat-modebar'),thread:r('#chat-thread'),composer:r('#chat-form'),input:r('#chat-input'),send:r('#chat-send')};})()";
    const string ToggleSize = "(()=>{document.querySelector('#chat-more').click();document.querySelector('#chat-size').click();return true;})()";
    // Troca o tamanho e, enquanto a janela anima, confere os essenciais várias vezes: nenhum controle essencial pode ficar cortado em nenhum quadro medido.
    static async Task<int> SampleWhile(WebView2 web, Func<bool> done, int ms, string label)
    {
        int samples = 0;
        var clock = System.Diagnostics.Stopwatch.StartNew();
        while (clock.ElapsedMilliseconds < ms) {
            string state = await web.ExecuteScriptAsync(ChatEssentials);
            Check(state == "\"ok\"", label + ": controle essencial cortado durante a animação: " + state);
            samples++;
            if (done()) break;
        }
        return samples;
    }
    static async Task Chat(MainForm main, WidgetForm w, WebView2 web, WebView2 mainWeb)
    {
        main.Opacity = 0;  // ShowMain (Abrir no Cérebro) não pode piscar uma janela na tela durante a verificação
        float k = w.DeviceDpi / 96f;
        int cases = 0;
        await web.ExecuteScriptAsync(ChatStub);
        // Contrato com a página: a conversa compacta é a janela principal de 304×252 (a barra NÃO cresce); ampliada, 360×540; mensagens desconhecidas não são de tamanho.
        Check(WidgetForm.ChatPanel == WidgetForm.MainPanel && WidgetForm.MainPanel == new Size(304, 252) && WidgetForm.ChatWide == new Size(360, 540), "Tamanhos: conversa compacta = painel principal 304×252; ampliada 360×540");
        Check(WidgetForm.PanelFor("widget:panel:chat") == WidgetForm.MainPanel && WidgetForm.PanelFor("widget:panel:chat-wide") == WidgetForm.ChatWide && WidgetForm.PanelFor("widget:panel:main") == WidgetForm.MainPanel, "Mensagens de tamanho da conversa");
        Check(WidgetForm.PanelFor("widget:panel:chat-gigante") == null && WidgetForm.PanelFor("chat:open") == null && WidgetForm.PanelFor("widget:panel:") == null, "Mensagem de tamanho desconhecida é ignorada");
        // Foco: a barra abre por hover SEM ativar a janela (ShowWithoutActivation) e sem NOACTIVATE: o clique de quem vai conversar ativa e foca o campo.
        var nonActivating = typeof(Form).GetProperty("ShowWithoutActivation", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(w, null);
        Check((bool)nonActivating, "Abrir por hover não ativa a janela (ShowWithoutActivation)");
        Check((GetWindowLong(w.Handle, -20) & 0x08000000) == 0, "Sem WS_EX_NOACTIVATE: o clique para conversar ativa a janela e o teclado vai para o campo");
        foreach (string dock in new[] { "left", "right", "top", "bottom" }) {
            w.SetMode(dock); await Task.Delay(250);
            await web.ExecuteScriptAsync("expand()"); await Task.Delay(700);
            var area = Screen.FromControl(w).WorkingArea;
            bool horizontal = dock == "top" || dock == "bottom";
            Func<bool> collapsed = () => horizontal ? (w.Width <= 90 && w.Height <= 16) : (w.Width <= 16 && w.Height <= 110);  // a alça de cima/baixo é 84×12
            Size mainSize = w.Size;
            Size wide = new Size(Math.Min(area.Width, (int)Math.Round(WidgetForm.ChatWide.Width * k)), Math.Min(area.Height, (int)Math.Round(WidgetForm.ChatWide.Height * k)));
            Check(mainSize == new Size((int)Math.Round(304 * k), (int)Math.Round(252 * k)), dock + ": painel de gravação aberto com o tamanho de contrato: " + mainSize);
            await web.ExecuteScriptAsync("document.querySelector('#chat-btn').click()");
            await Task.Delay(1000);
            Check(w.Size == mainSize, dock + ": a conversa compacta abre na MESMA janela, sem crescer: " + w.Size + " (esperado " + mainSize + ")");
            Check(area.Contains(w.Bounds), dock + ": conversa inteira dentro da área útil: " + w.Bounds + " em " + area);
            Check(await web.ExecuteScriptAsync("document.querySelector('#chat-panel').hidden") == "false", dock + ": painel da conversa visível");
            string measure = await web.ExecuteScriptAsync(ChatProbe);
            Console.WriteLine("MEDIDA conversa compacta/" + dock + " (DPI " + w.DeviceDpi + "): Bounds=" + w.Bounds + " ClientSize=" + w.ClientSize + " WebView2=" + web.Size + " página=" + measure);
            Check(web.ClientSize == w.ClientSize, dock + ": o WebView2 ocupa a área cliente inteira: " + web.ClientSize + " vs " + w.ClientSize);
            Check(await web.ExecuteScriptAsync("Math.abs(innerWidth*" + k.ToString(System.Globalization.CultureInfo.InvariantCulture) + "-" + web.Width + ")<=" + (k + 1).ToString(System.Globalization.CultureInfo.InvariantCulture) + "&&Math.abs(innerHeight*" + k.ToString(System.Globalization.CultureInfo.InvariantCulture) + "-" + web.Height + ")<=" + (k + 1).ToString(System.Globalization.CultureInfo.InvariantCulture)) == "true", dock + ": pixels CSS × escala = pixels físicos do WebView2 (sem aplicar a escala duas vezes)");
            Check(await web.ExecuteScriptAsync(ChatEssentials) == "\"ok\"", dock + ": cabeçalho, menu, modo, mensagens, campo e enviar dentro da janela e clicáveis: " + await web.ExecuteScriptAsync(ChatEssentials));
            Check(await web.ExecuteScriptAsync("document.activeElement.id==='chat-input'") == "true", dock + ": o campo de mensagem fica pronto para digitar");
            if (dock == "left" || dock == "right" || dock == "top") await Shot(web, "chat-compacta-" + dock);
            // Ampliar pelo menu: a janela cresce em passos até 360×540 (limitada à área útil) sem cortar nada em nenhum quadro medido; Reduzir volta ao compacto
            await web.ExecuteScriptAsync(ToggleSize);
            int grew = await SampleWhile(web, () => w.Size == wide, 3000, dock + " ampliando");
            Check(await Until(() => w.Size == wide, 4000), dock + ": ampliada: " + w.Size + " (esperado " + wide + ")");
            Check(area.Contains(w.Bounds), dock + ": ampliada dentro da área útil: " + w.Bounds + " em " + area);
            await Task.Delay(250);
            Check(await web.ExecuteScriptAsync(ChatEssentials) == "\"ok\"", dock + ": ampliada, tudo dentro da janela: " + await web.ExecuteScriptAsync(ChatEssentials));
            Console.WriteLine("MEDIDA conversa ampliada/" + dock + ": Bounds=" + w.Bounds + " WebView2=" + web.Size + " página=" + await web.ExecuteScriptAsync(ChatProbe) + " (" + grew + " amostras durante a animação)");
            if (dock == "left" || dock == "top") await Shot(web, "chat-ampliada-" + dock);
            await web.ExecuteScriptAsync(ToggleSize);
            await SampleWhile(web, () => w.Size == mainSize, 3000, dock + " reduzindo");
            Check(await Until(() => w.Size == mainSize, 4000), dock + ": reduzida de volta ao compacto: " + w.Size);
            await Task.Delay(250);
            Check(await web.ExecuteScriptAsync(ChatEssentials) == "\"ok\"", dock + ": reduzida, tudo dentro da janela");
            // recolher: volta à alça sem sobras; reabrir mostra o painel de gravação (a conversa fica à espera no ícone)
            await web.ExecuteScriptAsync("conceal(); host.postMessage('widget:collapse')");
            Check(await Until(collapsed), dock + ": recolhe de verdade: " + w.Size);
            Check(area.Contains(w.Bounds), dock + ": alça dentro da área útil");
            await web.ExecuteScriptAsync("expand()"); await Task.Delay(700);
            Check(await Until(() => w.Size == mainSize, 4000), dock + ": depois de recolher, a barra volta ao tamanho do painel de gravação (" + w.Size + ", esperado " + mainSize + ")");
            await web.ExecuteScriptAsync("host.postMessage('widget:collapse')");
            Check(await Until(collapsed), dock + ": recolhe de novo");
            cases += 17;
        }
        w.SetMode("left"); await Task.Delay(250);
        await web.ExecuteScriptAsync("expand()"); await Task.Delay(700);
        var wa = Screen.FromControl(w).WorkingArea;
        Size wideSize = new Size(Math.Min(wa.Width, (int)Math.Round(WidgetForm.ChatWide.Width * k)), Math.Min(wa.Height, (int)Math.Round(WidgetForm.ChatWide.Height * k)));
        Size compact = w.Size;
        await web.ExecuteScriptAsync("document.querySelector('#chat-btn').click()"); await Task.Delay(600);
        // Animação: crescimento contínuo, sem salto nem ricochete; interrompida no meio, continua do tamanho atual
        await web.ExecuteScriptAsync(ToggleSize);
        var grow = await Trace(w, 700);
        for (int i = 1; i < grow.Count; i++) Check(grow[i].Width >= grow[i - 1].Width && grow[i].Height >= grow[i - 1].Height, "Crescimento sem recuo nem ricochete: " + grow[i - 1] + " → " + grow[i]);
        Check(grow[grow.Count - 1] == wideSize && grow.Exists(s => s != wideSize && s != compact), "Cresce passo a passo (" + grow.Count + " amostras) até " + wideSize);
        // Reduz e, 60 ms depois (no meio do caminho), amplia de novo: a janela inverte o movimento a partir do tamanho em que está
        var seq = new System.Collections.Generic.List<Size>();
        var watch = System.Diagnostics.Stopwatch.StartNew();
        bool reopened = false;
        await web.ExecuteScriptAsync(ToggleSize);
        while (watch.ElapsedMilliseconds < 1000) {
            seq.Add(w.Size);
            if (!reopened && watch.ElapsedMilliseconds >= 60) { reopened = true; await web.ExecuteScriptAsync(ToggleSize); }
            await Task.Delay(8);
        }
        int smallest = int.MaxValue, jump = 0;
        for (int i = 1; i < seq.Count; i++) {
            smallest = Math.Min(smallest, seq[i].Width);
            jump = Math.Max(jump, Math.Max(Math.Abs(seq[i].Width - seq[i - 1].Width) * 100 / Math.Max(1, wideSize.Width - compact.Width), Math.Abs(seq[i].Height - seq[i - 1].Height) * 100 / Math.Max(1, wideSize.Height - compact.Height)));
        }
        Check(smallest < wideSize.Width - (wideSize.Width - compact.Width) / 10, "A janela chegou a encolher antes de ampliar de novo (menor largura " + smallest + ")");
        Check(jump <= 50, "Animação interrompida e invertida sem salto: maior passo " + jump + "% do percurso");
        Check(seq[seq.Count - 1] == wideSize, "Termina no tamanho certo depois de interromper: " + seq[seq.Count - 1]);
        Check(await web.ExecuteScriptAsync(ChatEssentials) == "\"ok\"", "Depois da animação interrompida, nada cortado");
        // A ampliação é uma escolha da sessão: recolher e reabrir a conversa a mantém; reduzir devolve o compacto
        Check(await web.ExecuteScriptAsync("conceal(); host.postMessage('widget:collapse'); true") == "true", "recolher no meio de tudo");
        Check(await Until(() => w.Width <= 16 && w.Height <= 110), "Recolher logo depois de abrir termina na alça: " + w.Size);
        Check(wa.Contains(w.Bounds), "Alça dentro da área útil");
        await web.ExecuteScriptAsync("expand()"); await Task.Delay(700);
        await web.ExecuteScriptAsync("document.querySelector('#chat-btn').click()");
        Check(await Until(() => w.Size == wideSize, 4000), "Reabrir a conversa ampliada na mesma sessão a abre ampliada: " + w.Size);
        await web.ExecuteScriptAsync(ToggleSize);
        Check(await Until(() => w.Size == compact, 4000) && await web.ExecuteScriptAsync("QuickChat.wide()") == "false", "Reduzir devolve o tamanho compacto: " + w.Size);
        cases += 12;
        // Streaming no WebView2 real: texto aparecendo, botão vira Interromper, recolher no meio não cancela, ponto de novidade, rascunho
        await web.ExecuteScriptAsync("conceal(); host.postMessage('widget:collapse')"); await Until(() => w.Width <= 16 && w.Height <= 110);
        await web.ExecuteScriptAsync("expand()"); await Task.Delay(500);
        await web.ExecuteScriptAsync("document.querySelector('#chat-btn').click()");
        Check(await Until(() => w.Size == compact), "Conversa aberta para o streaming");
        await web.ExecuteScriptAsync(Typing("#chat-input", "Como o sono ajuda a memória?"));
        double cpu0 = System.Diagnostics.Process.GetCurrentProcess().TotalProcessorTime.TotalSeconds, wv0 = WebViewCpu();
        await web.ExecuteScriptAsync("window.__probe.on = true; window.__stub.words = 150; window.__stub.gap = 30; QuickChat.send()");
        Check(await Until(web, "QuickChat.state().streaming && document.querySelector('#chat-send').dataset.mode==='stop'"), "Resposta em streaming e botão Interromper");
        Check(await Until(web, "(document.querySelector('.chat-msg.bot.live .chat-answer')||{textContent:''}).textContent.length>40", 8000), "Texto aparecendo conforme chega");
        Check(await web.ExecuteScriptAsync(ChatEssentials) == "\"ok\"", "Respondendo no painel compacto: Interromper e campo dentro da janela e clicáveis");
        await Shot(web, "chat-respondendo");
        await Task.Delay(1500);
        string conversationBefore = await web.ExecuteScriptAsync("JSON.stringify(QuickChat.state().conv)");
        await web.ExecuteScriptAsync("conceal(); host.postMessage('widget:collapse')");
        Check(await Until(() => w.Width <= 16 && w.Height <= 110), "Recolher durante a resposta");
        Check(await web.ExecuteScriptAsync("QuickChat.state().streaming===true && window.__stub.aborted===0") == "true", "Recolher não cancelou a resposta (" + await web.ExecuteScriptAsync("JSON.stringify(window.__stub)") + ")");
        Check(await Until(web, "!QuickChat.state().streaming", 15000), "A resposta termina com a barra recolhida");
        await web.ExecuteScriptAsync("window.__probe.on = false");
        Check(await web.ExecuteScriptAsync("document.querySelector('#chat-btn').dataset.attn==='done' && QuickChat.state().unread===true") == "true", "Ponto de novidade no ícone da conversa");
        string probe = await web.ExecuteScriptAsync("JSON.stringify(window.__probe)");
        double cpu = System.Diagnostics.Process.GetCurrentProcess().TotalProcessorTime.TotalSeconds - cpu0, wvcpu = WebViewCpu() - wv0;
        Console.WriteLine("MEDIDA streaming (150 pedaços, 30 ms, recolhido na metade): processo do Lumen " + cpu.ToString("0.00") + " s de CPU, WebView2 " + wvcpu.ToString("0.00") + " s; quadros e tarefas longas: " + probe);
        await web.ExecuteScriptAsync(Typing("#chat-input", "rascunho que atravessa tudo"));
        await web.ExecuteScriptAsync("expand()"); await Task.Delay(500);
        Check(await Until(() => w.Size == compact, 4000), "Reaberta, a barra volta ao painel de gravação (" + w.Size + ", esperado " + compact + ")");
        await web.ExecuteScriptAsync("document.querySelector('#chat-btn').click()");
        Check(await Until(() => w.Size == compact), "Reabre a conversa");
        Check(await web.ExecuteScriptAsync("document.querySelector('#chat-input').value==='rascunho que atravessa tudo' && document.querySelectorAll('.chat-msg.bot').length===1 && document.querySelectorAll('.chat-msg.user').length===1 && document.querySelector('#chat-btn').dataset.attn===undefined") == "true", "Mensagens, resposta e rascunho intactos; novidade lida");
        Check(await web.ExecuteScriptAsync("JSON.stringify(QuickChat.state().conv)") == conversationBefore, "A mesma conversa (mesmo identificador)");
        Check(await web.ExecuteScriptAsync(ChatEssentials) == "\"ok\"", "Conversa com mensagens no painel compacto: tudo dentro da janela e clicável");
        // Trocar de painel: ajustes, compreensão e gravação continuam a funcionar com a conversa guardada
        await web.ExecuteScriptAsync("document.querySelector('#settings').click()");
        Check(await Until(() => w.Size == compact), "Ajustes: a janela fica no tamanho de antes: " + w.Size);
        Check(await web.ExecuteScriptAsync("document.querySelector('#chat-panel').hidden && !document.querySelector('#preferences').hidden && document.querySelector('#chat-input').value==='rascunho que atravessa tudo'") == "true", "Trocar para ajustes esconde a conversa sem perder o rascunho");
        await web.ExecuteScriptAsync("backPreferences(); document.querySelector('#chat-btn').click()");
        Check(await Until(() => w.Size == compact), "De volta à conversa pelo ícone");
        // Esc: fecha o menu aberto; depois recolhe; nunca sai do Lumen nem mexe na gravação
        await web.ExecuteScriptAsync("document.querySelector('#chat-more').click()");
        Check(await web.ExecuteScriptAsync("!!document.querySelector('.chat-menu')") == "true", "Menu da conversa abre");
        Check(await web.ExecuteScriptAsync("(()=>{const m=document.querySelector('.chat-menu').getBoundingClientRect(),p=document.querySelector('#chat-panel').getBoundingClientRect();return m.left>=p.left-.5&&m.right<=p.right+.5&&m.top>=p.top-.5&&m.bottom<=p.bottom+.5;})()") == "true", "O menu cabe dentro do painel compacto");
        await web.ExecuteScriptAsync("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))");
        Check(await web.ExecuteScriptAsync("!document.querySelector('.chat-menu') && !document.querySelector('#chat-panel').hidden") == "true" && w.Size == compact, "Primeiro Esc só fecha o menu");
        await web.ExecuteScriptAsync("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))");
        Check(await Until(() => w.Width <= 16 && w.Height <= 110), "Segundo Esc recolhe a barra");
        Check(w.Visible && !((bool)Field(main, "exiting")), "Esc não encerra o Lumen");
        // Abrir no Cérebro: o Lumen.exe valida o identificador e entrega a MESMA conversa à janela principal (nada é reenviado)
        await mainWeb.ExecuteScriptAsync("window.__chatMsgs=[]; chrome.webview.addEventListener('message', e => window.__chatMsgs.push(e.data));");
        await web.ExecuteScriptAsync("host.postMessage('chat:open:../../etc/passwd'); host.postMessage('chat:open:abc def'); host.postMessage('chat:open:'); host.postMessage('chat:open:" + new string('a', 70) + "');");
        await Task.Delay(500);
        Check(await mainWeb.ExecuteScriptAsync("window.__chatMsgs.length") == "0", "Identificadores inválidos não chegam à janela principal");
        await web.ExecuteScriptAsync("host.postMessage('chat:open:stub0001')");
        Check(await Until(mainWeb, "window.__chatMsgs.includes('desktop:chat:stub0001')"), "Abrir no Cérebro entrega o mesmo identificador à janela principal");
        await web.ExecuteScriptAsync("host.postMessage('chat:open')");
        Check(await Until(mainWeb, "window.__chatMsgs.includes('desktop:chat')"), "Abrir no Cérebro sem conversa abre só a aba de conversa");
        main.Hide();
        cases += 20;
        Console.WriteLine("OK: Conversa rápida no WebView2 real (" + cases + " verificações): abre na janela compacta sem crescer, ampliar/reduzir sem salto e sem cortar nada em nenhum quadro medido, nas quatro bordas e dentro da área útil, interrupção da animação, streaming com recolher no meio, rascunho, troca de painel, Esc e mensagens ao Lumen.exe.");
    }
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int index);
    const string NoteKey = "teste:nota-flutuante";
    [STAThread] static void Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s,e) => Assembly.LoadFrom(Path.Combine(Program.Bin,new AssemblyName(e.Name).Name+".dll"));
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        typeof(Program).GetMethod("KillChildrenOnExit",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,null);
        Run(args);
    }
    // “Minha compreensão” nas três interfaces reais (principal, barra lateral e janela flutuante): o mesmo documento.
    // Cápsula de gravação no WebView2 REAL: nenhuma gravação é iniciada (a página recebe o estado por render(), com a leitura do servidor
    // suspensa em `pending`); mede a janela, os controles, os cliques e a transição (quadros exatos) nas quatro orientações. csc do Framework é C# 5.
    const string CapsuleProbe = @"(() => {
        const ids = ['#open', '#action', '#pause', '#chat-btn', '#settings'];
        const rs = ids.map(s => { const e = document.querySelector(s); return [s, e.getBoundingClientRect()]; });
        const rail = document.querySelector('.rail').getBoundingClientRect(), pill = document.querySelector('.rec-pill').getBoundingClientRect();
        for (const [s, r] of rs) if (r.width < 1 || r.left < -0.5 || r.top < -0.5 || r.right > innerWidth + 0.5 || r.bottom > innerHeight + 0.5) return 'fora da janela: ' + s + ' ' + [r.left, r.top, r.right, r.bottom].map(Math.round);
        for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
          const a = rs[i][1], b = rs[j][1];
          if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0.5 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5) return 'sobrepostos: ' + rs[i][0] + ' e ' + rs[j][0];
        }
        for (const [s, r] of rs) { const e = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2); if (!e || !e.closest('button') || '#' + e.closest('button').id !== s) return 'o clique em ' + s + ' vai para ' + (e && (e.closest('button') ? e.closest('button').id : e.className)); }
        if (pill.left < rail.left - 0.5 || pill.top < rail.top - 0.5 || pill.right > rail.right + 0.5 || pill.bottom > rail.bottom + 0.5) return 'pílula fora da barra';
        return 'ok';
      })()";
    const string CapsuleFrameProbe = @"(() => {
        const p = document.querySelector('#pause').getBoundingClientRect();
        for (const s of ['#open', '#chat-btn', '#settings']) { const o = document.querySelector(s).getBoundingClientRect();
          if (Math.min(p.right, o.right) - Math.max(p.left, o.left) > 1 && Math.min(p.bottom, o.bottom) - Math.max(p.top, o.top) > 1) return 'a pausa invade ' + s; }
        for (const s of ['#open', '#action', '#pause', '#chat-btn', '#settings']) { const r = document.querySelector(s).getBoundingClientRect();
          if (r.left < -0.5 || r.top < -0.5 || r.right > innerWidth + 0.5 || r.bottom > innerHeight + 0.5) return 'fora da janela: ' + s; }
        return 'ok';
      })()";
    const string CapsuleSettled = "document.getAnimations().filter(a => a instanceof CSSTransition).length === 0";
    static string Rect(string sel) { return "JSON.stringify((r => [r.left, r.top, r.right, r.bottom].map(Math.round))(document.querySelector('" + sel + "').getBoundingClientRect()))"; }
    static async Task Capsule(MainForm main, WidgetForm w, WebView2 web)
    {
        int cases = 0;
        foreach (string dock in new[] { "left", "right", "top", "bottom" }) {
            w.SetMode(dock); await Task.Delay(250);
            await web.ExecuteScriptAsync("expand()"); await Task.Delay(700);
            Size size = w.Size;
            // render() sem notas só esconde "Minha compreensão" depois de duas leituras seguidas: três desenhos deixam a barra no estado que as medidas vão usar
            await web.ExecuteScriptAsync("pending = true; for (let i = 0; i < 3; i++) render({recording:{active:false},job:{status:'idle',review:false}}); 0");
            await Task.Delay(300);
            Check(await Until(web, CapsuleSettled), dock + ": a barra assenta parada");
            string chatBefore = await web.ExecuteScriptAsync(Rect("#chat-btn")), actionBefore = await web.ExecuteScriptAsync(Rect("#action"));
            Check(await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('#pause')).visibility==='hidden' && document.body.dataset.rec==='off'") == "true", dock + ": parado, a pausa não existe");
            if (dock == "left" || dock == "top") await Shot(web, "capsula-parado-" + dock);
            // quadros exatos da entrada: as transições são pausadas e posicionadas em t ms
            await web.ExecuteScriptAsync("render({recording:{active:true,seconds:65,heard:true,level:.3},job:{status:'idle',review:false}}); document.getAnimations().filter(a => a instanceof CSSTransition).forEach(a => a.pause()); 0");
            foreach (int t in new[] { 0, 80, 160, 240, 320 }) {
                await web.ExecuteScriptAsync("document.getAnimations().filter(a => a instanceof CSSTransition).forEach(a => { a.currentTime = " + t + "; }); 0");
                Check(await web.ExecuteScriptAsync(CapsuleFrameProbe) == "\"ok\"", dock + ": quadro " + t + " ms: " + await web.ExecuteScriptAsync(CapsuleFrameProbe));
                cases++;
            }
            await web.ExecuteScriptAsync("document.getAnimations().filter(a => a instanceof CSSTransition).forEach(a => a.finish()); 0");
            Check(await Until(web, CapsuleSettled), dock + ": a entrada termina");
            Check(await web.ExecuteScriptAsync("document.body.dataset.rec==='on' && getComputedStyle(document.querySelector('#pause')).visibility==='visible' && +getComputedStyle(document.querySelector('#pause')).opacity===1") == "true", dock + ": gravando, a pausa aparece");
            Check(w.Size == size, dock + ": a janela NÃO cresce para a cápsula: " + w.Size + " (esperado " + size + ")");
            Check(await web.ExecuteScriptAsync(Rect("#action")) == actionBefore, dock + ": o Gravar/Encerrar não saiu do lugar");
            Check(await web.ExecuteScriptAsync(CapsuleProbe) == "\"ok\"", dock + ": gravando: " + await web.ExecuteScriptAsync(CapsuleProbe));
            if (dock == "left" || dock == "top") await Shot(web, "capsula-gravando-" + dock);
            await web.ExecuteScriptAsync("render({recording:{active:true,paused:true,seconds:65,heard:true},job:{status:'idle',review:false}}); 0");
            Check(await Until(web, CapsuleSettled), dock + ": pausada assenta");
            Check(await web.ExecuteScriptAsync("document.querySelector('#pause svg use').getAttribute('href').endsWith('#play') && document.querySelector('#pause-label').textContent==='Retomar gravação' && document.body.dataset.paused==='true'") == "true", dock + ": pausada, o botão vira Retomar (ícone e texto)");
            Check(await web.ExecuteScriptAsync(CapsuleProbe) == "\"ok\"", dock + ": pausada: " + await web.ExecuteScriptAsync(CapsuleProbe));
            if (dock == "left" || dock == "top") await Shot(web, "capsula-pausado-" + dock);
            await web.ExecuteScriptAsync("render({recording:{active:false},job:{status:'idle',review:false}}); 0");
            Check(await Until(web, CapsuleSettled), dock + ": a saída termina");
            string chatAfter = await web.ExecuteScriptAsync(Rect("#chat-btn")), actionAfter = await web.ExecuteScriptAsync(Rect("#action"));
            Check(chatAfter == chatBefore && actionAfter == actionBefore, dock + ": depois de parar, tudo volta ao lugar de antes: chat " + chatBefore + " -> " + chatAfter + ", gravar " + actionBefore + " -> " + actionAfter + ", rec=" + await web.ExecuteScriptAsync("document.body.dataset.rec"));
            Check(await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('#pause')).visibility==='hidden'") == "true", dock + ": depois de parar, a pausa some");
            Check(w.Size == size, dock + ": a janela segue do mesmo tamanho");
            await web.ExecuteScriptAsync("pending = false; 0");
            cases += 8;
        }
        Console.WriteLine("OK: Cápsula de gravação no WebView2 real (" + cases + " verificações): quatro orientações, janela sem crescer, Gravar fixo, quadros da transição sem sobreposição, pausa/retomar, volta ao lugar.");
    }
    static async Task Understanding(MainForm main, WidgetForm w, WebView2 web, WebView2 mainWeb)
    {
        main.Opacity = 0;  // nada aparece na tela durante a verificação
        float k = w.DeviceDpi / 96f;
        await mainWeb.ExecuteScriptAsync("openUnderstanding('" + NoteKey + "')");
        Check(await Until(mainWeb, "step==='understand' && document.querySelector('#u-text').value==='Entendi que'"), "Editor principal abre a nota salva");
        string one = "Entendi que a planta usa a luz do sol.";
        await mainWeb.ExecuteScriptAsync(Typing("#u-text", one));
        w.SetMode("left"); await web.ExecuteScriptAsync("expand()"); await Task.Delay(700);
        Check(await Until(web, "!document.querySelector('#note-btn').hidden"), "Barra lateral oferece “Minha compreensão” da aula aberta");
        await web.ExecuteScriptAsync("showNote(true)");
        Check(await Until(() => w.Width >= (int)(340 * k) && w.Height >= (int)(420 * k)), "Barra cresce para a nota: " + w.Size);
        Check(Screen.FromControl(w).WorkingArea.Contains(w.Bounds), "Barra com a nota dentro da tela");
        Check(await Until(web, "document.querySelector('#note-text').value===" + Js(one)), "Teste 1: o que se escreve na principal aparece na lateral");
        await Shot(web, "widget-note");
        string two = one + " A fase clara quebra a água.";
        await web.ExecuteScriptAsync(Typing("#note-text", two));
        Check(await Until(mainWeb, "document.querySelector('#u-text').value===" + Js(two)), "Teste 8: o que se escreve na lateral aparece na principal");
        await web.ExecuteScriptAsync("detachNote()");
        Check(await Until(() => { var f = Field(main, "note") as NoteForm; return f != null && f.Visible; }), "Teste 2: destacar abre a janela flutuante");
        var nf = (NoteForm)Field(main, "note");
        nf.Opacity = 0;
        var nweb = (WebView2)Field(nf, "web");
        Check(await Until(() => nweb.CoreWebView2 != null), "WebView2 da janela flutuante");
        Check(await Until(nweb, "document.querySelector('#nw-text').value===" + Js(two)), "Teste 2: o mesmo texto na janela flutuante");
        Check(nf.TopMost, "Janela flutuante fica por cima (do vídeo e do Lumen)");
        Check(await Until(() => w.Width <= 16), "A barra lateral se recolhe para não cobrir o vídeo");
        string three = two + " O oxigênio vem da água.";
        await nweb.ExecuteScriptAsync(Typing("#nw-text", three));
        Check(await Until(mainWeb, "document.querySelector('#u-text').value===" + Js(three)), "Teste 3: o que se escreve na flutuante aparece na principal");
        await web.ExecuteScriptAsync("expand(); showNote(true)");
        Check(await Until(web, "document.querySelector('#note-text').value===" + Js(three)), "Teste 3: … e na lateral");
        await web.ExecuteScriptAsync("conceal(); host.postMessage('widget:collapse')");
        Check(await Until(mainWeb, "!document.querySelector('#u-float').hidden"), "Principal avisa que a nota também está flutuando");
        Check(await Until(nweb, "document.querySelector('#nw-save').textContent==='Salvo'"), "Autosave na janela flutuante");
        await Shot(nweb, "note-window");
        // Teste 6: mover e redimensionar (o fim de um arrasto chega como ResizeEnd)
        var area = Screen.FromControl(nf).WorkingArea;
        MethodInfo end = typeof(Form).GetMethod("OnResizeEnd", BindingFlags.Instance | BindingFlags.NonPublic);
        nf.Bounds = new Rectangle(area.Right - 40, area.Bottom - 40, area.Width * 2, area.Height * 2);  // arrastada para fora e esticada
        end.Invoke(nf, new object[] { EventArgs.Empty });
        Check(area.Contains(nf.Bounds), "Teste 6: não sai da tela: " + nf.Bounds);
        Check(nf.Width <= area.Width * .6 + 2 && nf.Height <= area.Height * .92 + 2, "Teste 6: não ocupa a tela inteira");
        nf.Bounds = new Rectangle(area.Left + 40, area.Top + 60, 20, 20);
        end.Invoke(nf, new object[] { EventArgs.Empty });
        Check(nf.Width >= Math.Min(area.Width, (int)(300 * k)) - 1 && nf.Height >= Math.Min(area.Height, (int)(240 * k)) - 1, "Teste 6: tamanho mínimo confortável: " + nf.Size);
        var chosen = new Rectangle(area.Left + 100, area.Top + 80, (int)(420 * k), (int)(380 * k));
        nf.Bounds = chosen; end.Invoke(nf, new object[] { EventArgs.Empty });
        Check(nf.Bounds == chosen, "Teste 6: aceita posição e tamanho escolhidos");
        Check(File.ReadAllText(Path.Combine(Program.Data, "understanding-panel.txt")) == "v1|" + chosen.X + "|" + chosen.Y + "|" + chosen.Width + "|" + chosen.Height, "Lembra posição e tamanho");
        await nweb.ExecuteScriptAsync("compact(true)");
        Check(await Until(() => nf.Height < 90 * k), "Minimizar deixa só a barra: " + nf.Size);
        Check(await nweb.ExecuteScriptAsync("document.querySelector('#nw-text').value===" + Js(three)) == "true", "Minimizar não toca no texto");
        await nweb.ExecuteScriptAsync("compact(false)");
        Check(await Until(() => nf.Height == chosen.Height), "Volta ao tamanho de antes");
        // Teste 4: fechar a janela flutuante não perde nada
        await nweb.ExecuteScriptAsync("leave(false)");
        Check(await Until(() => !nf.Visible), "Teste 4: fechar a janela flutuante");
        Check(await Until(mainWeb, "document.querySelector('#u-float').hidden"), "Principal volta ao normal ao fechar");
        Check(await Ask(mainWeb, "Notes.call('/api/understanding?key=" + NoteKey + "').then(v=>v.text===" + Js(three) + ")"), "Teste 4: nada perdido no Lumen");
        // Teste 5: abrir de novo, no mesmo lugar e com a nota intacta
        await mainWeb.ExecuteScriptAsync("detach('" + NoteKey + "')");
        Check(await Until(() => nf.Visible), "Teste 5: abrir de novo pela principal");
        Check(nf.Bounds == chosen, "Teste 5: no mesmo lugar e tamanho: " + nf.Bounds);
        Check(await Until(nweb, "document.querySelector('#nw-text').value===" + Js(three)), "Teste 5: nota intacta");
        // Voltar para o Lumen: a janela flutuante fecha e o editor volta para a principal, com o mesmo texto
        string four = three + " E a glicose sai da fase escura.";
        await nweb.ExecuteScriptAsync(Typing("#nw-text", four));
        await nweb.ExecuteScriptAsync("leave(true)");
        Check(await Until(() => !nf.Visible && main.Visible), "Voltar para o Lumen mostra a janela principal");
        Check(await Until(mainWeb, "step==='understand' && U.key==='" + NoteKey + "' && document.querySelector('#u-text').value===" + Js(four)), "O editor volta para a principal com o texto intacto");
        Check(await Ask(mainWeb, "Notes.call('/api/understanding?key=" + NoteKey + "').then(v=>v.text===" + Js(four) + ")"), "Texto salvo ao voltar");
        await Shot(mainWeb, "main-understand");
        await mainWeb.ExecuteScriptAsync("showView('home')"); await Shot(mainWeb, "main-home");
        await mainWeb.ExecuteScriptAsync("goSettings('general')"); await Shot(mainWeb, "main-settings");
        // Capas do Notion no WebView2 real: sem token (dados isolados), o aviso; com a API do Notion simulada na página,
        // escolher a página e ver a prévia (nada vai ao Notion daqui)
        await mainWeb.ExecuteScriptAsync("covOpen()");
        Check(await Until(mainWeb, "view==='settings' && settingsCat==='covers' && !document.querySelector('#cov-off').hidden"), "Capas do Notion abre e, sem o Notion, diz o que falta");
        await Shot(mainWeb, "main-covers-off");
        await mainWeb.ExecuteScriptAsync("(()=>{const c=document.createElement('canvas');c.width=768;c.height=320;const g=c.getContext('2d');" +
            "const k=g.createLinearGradient(0,0,768,320);k.addColorStop(0,'#4f46e5');k.addColorStop(1,'#06b6d4');g.fillStyle=k;g.fillRect(0,0,768,320);" +
            "const page={id:'pg-1',title:'Orçamento doméstico 2026',url:'https://www.notion.so/x',icon:'💰',where:'No topo do workspace',edited:'2026-10-26T12:00:00.000Z',cover:null};" +
            "const real=api;S.has_token=true;api=(u,b)=>u.startsWith('/api/notion/page')?Promise.resolve(page):u==='/api/cover/preview'?" +
            "Promise.resolve({preview_id:'p1',kind:'ia',seconds:34,theme:'',note:'',image:c.toDataURL()}):real(u,b);renderCov();})()");
        Check(await Ask(mainWeb, "covPickRef('pg-1').then(()=>covGen()).then(()=>!!cv.pv && document.querySelector('#cov-main').textContent==='Aplicar capa' && document.querySelector('#cov-pic').naturalWidth===768)"),
            "Escolher a página e gerar a prévia no WebView2");
        await Shot(mainWeb, "main-covers-ready");
        // Nova aula → Destinos do estudo → Notion → Capa: o mesmo fluxo num diálogo, sem sair da aula
        await mainWeb.ExecuteScriptAsync("showView('new'); showStep('compose'); renderDestRows(); document.querySelector('#dest-notion-cover').click()");
        Check(await Until(mainWeb, "covDlg.open && view==='new' && document.querySelector('#cov-dlg-body').contains(document.querySelector('#cov-box'))"), "Capa abre o diálogo na Nova aula");
        Check(await Ask(mainWeb, "covPickRef('pg-1').then(()=>covGen()).then(()=>document.querySelector('#cov-main').textContent==='Aplicar capa')"), "Diálogo: página, prévia e “Aplicar capa” no WebView2");
        await Shot(mainWeb, "main-cover-dialog");
        await mainWeb.ExecuteScriptAsync("covDlg.close()");
        Check(await Until(mainWeb, "!covDlg.open && view==='new' && document.activeElement.id==='dest-notion-cover' && document.querySelector('#cov-home').contains(document.querySelector('#cov-box'))"),
            "Fechar volta ao botão Capa na Nova aula: " + await mainWeb.ExecuteScriptAsync("JSON.stringify({open:covDlg.open,view,focus:document.activeElement.id||document.activeElement.tagName,home:document.querySelector('#cov-home').contains(document.querySelector('#cov-box')),step,shown:!!document.querySelector('#dest-notion-cover').offsetParent})"));
        await Shot(mainWeb, "main-new-cover-button");
        Console.WriteLine("OK: Capas do Notion no WebView2 (Ajustes e diálogo da Nova aula: aviso sem token, página escolhida, prévia, “Aplicar capa” e volta à aula).");
        main.Hide();
        // Teste 7: recarregar a página (e o rascunho continua)
        mainWeb.CoreWebView2.Reload();
        await Task.Delay(1500);
        await mainWeb.ExecuteScriptAsync("openUnderstanding('" + NoteKey + "')");
        Check(await Until(mainWeb, "typeof U!=='undefined' && U && document.querySelector('#u-text').value===" + Js(four), 8000), "Teste 7: rascunho continua depois de recarregar");
        // Teste 10: a IA continua bloqueada até a compreensão ser enviada pelo fluxo de sempre
        Check(await Ask(mainWeb, "Notes.call('/api/review?key=" + NoteKey + "').then(()=>false,()=>true)"), "Teste 10: transcrição e telas continuam escondidas");
        Check(await Ask(mainWeb, "Notes.call('/api/understanding/submit',{key:'" + NoteKey + "',text:'curta'}).then(()=>false,()=>true)"), "Teste 10: a IA recusa nota curta");
        Console.WriteLine("OK: “Minha compreensão” igual nas três interfaces, janela flutuante (mover, redimensionar, minimizar, lembrar, fechar, voltar) e autosave.");
    }
    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    static void Run(string[] args)
    {
        Check(WidgetForm.Clamp(new Point(-3000,9999),new Size(76,252),new Rectangle(-1920,0,1920,1080)) == new Point(-1920,828), "Clamp em tela secundária");
        Check(WidgetForm.Clamp(new Point(9999,-100),new Size(76,252),new Rectangle(0,0,1920,1080)) == new Point(1844,0), "Clamp em tela principal");
        Geometry();
        NoteGeometry();
        if (Array.IndexOf(args, "--geometry-only") >= 0) return;
        var desktop = Screen.PrimaryScreen.WorkingArea;
        int idleY = Cursor.Position.Y < desktop.Top+desktop.Height/2 ? desktop.Bottom-84 : desktop.Top;
        Directory.CreateDirectory(Program.Data);
        File.WriteAllText(Path.Combine(Program.Data,"widget-position.txt"),"v2|left|"+desktop.Left+"|"+idleY);
        // Uma aula preparada esperando a compreensão (como lumen/understanding.py grava), para as três interfaces.
        string hash;
        using (var sha = System.Security.Cryptography.SHA256.Create())
            hash = BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(NoteKey))).Replace("-","").ToLowerInvariant().Substring(0,16);
        Directory.CreateDirectory(Path.Combine(Program.Data,"understanding"));
        File.WriteAllText(Path.Combine(Program.Data,"understanding",hash+".json"),"{\"key\":\""+NoteKey+"\",\"created\":\"2026-10-20T10:00:00\",\"title\":\"Fotossíntese\",\"label\":\"Arquivo local\",\"spec\":{},\"current_understanding\":\"Entendi que\",\"current_at\":1,\"original_understanding\":null,\"ai_analysis\":null,\"final_knowledge\":null,\"prepared\":true}",new System.Text.UTF8Encoding(false));
        var main = new MainForm(Path.Combine(Program.Root,".venv","Scripts","pythonw.exe"),true);
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FAIL: timeout de verificação nativa"); Environment.Exit(1); },null,240000,System.Threading.Timeout.Infinite);
        var timer = new Timer { Interval = 500 };
        int ticks = 0;
        timer.Tick += async (s,e) => {
            ticks++;
            var w = Field(main,"widget") as WidgetForm;
            if (w == null && ticks < 50) return;
            timer.Stop();
            try {
                Check(w != null,"Barra criada na abertura --background");
                w.Opacity = 0; w.Enabled = false;
                Check(w.Visible && IsWindowVisible(w.Handle),"Barra visível no Windows");
                Check(!main.Visible,"Janela principal oculta no startup background");
                Check(w.Width <= 16 && w.Height <= 110,"Inicializa escondido em uma pequena alça");
                var web = (WebView2)Field(w,"web");
                for(int i=0;i<60 && web.CoreWebView2 == null;i++) await Task.Delay(100);
                Check(web.CoreWebView2 != null,"WebView2 inicializado");
                web.CoreWebView2.ProcessFailed += (sender,ev) => Console.WriteLine("Web failed: "+ev.ProcessFailedKind);
                await Task.Delay(1500);
                Check((await web.ExecuteScriptAsync("document.title")).Contains("barra flutuante"),"Página da barra carregada");
                await web.ExecuteScriptAsync("expand()"); await Task.Delay(600);
                Check(w.Width > 250,"Expansão animada nativa");
                Check(w.Height > 240,"Altura expandida nativa");
                // parado, o botão de gravar fica em repouso; só gravando o halo pulsa (nada pisca enquanto se estuda)
                Check(await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('.record-symbol')).animationName==='none' && getComputedStyle(document.querySelector('#action'),'::after').animationName==='none'")=="true","Botão de gravar em repouso no WebView2");
                Check(await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('.notch')).borderRadius==='18px' && document.querySelector('.notch').offsetWidth===304")=="true","Moldura da barra no tamanho da janela nativa (304 px, cantos de 18)");
                await Shot(web, "widget-left");
                web.CoreWebView2.PostWebMessageAsString("widget:hidden");
                await Task.Delay(150);
                Check(await web.ExecuteScriptAsync("document.body.dataset.expanded === 'true'") == "true", "Mensagem atrasada não deixa uma cápsula gigante sem controles");
                for(int i=0;i<30;i++) {
                    await web.ExecuteScriptAsync("expand(); retract(); expand();");
                    if(i%3==0) await web.ExecuteScriptAsync("host.postMessage('widget:collapse'); host.postMessage('widget:expand');");
                }
                await Task.Delay(700);
                Check(await web.ExecuteScriptAsync("document.body.dataset.expanded === 'true'") == "true", "Entradas/saídas rápidas não dessincronizam a interface");
                await web.ExecuteScriptAsync("document.querySelector('#action').focus(); document.documentElement.dispatchEvent(new PointerEvent('pointerleave'));");
                await Task.Delay(1100);
                Check(w.Width <= 16 && w.Height <= 110,"Recolhe mesmo após focar um botão");
                SendMessage(w.Handle,0x0112,new IntPtr(0xf030),IntPtr.Zero);
                await Task.Delay(150);
                Check(w.WindowState == FormWindowState.Normal && w.Width <= 16,"Impede maximização acidental do widget");
                w.SetMode("right");
                Check(w.Left > Screen.PrimaryScreen.WorkingArea.Width/2,"Ancoragem à direita");
                w.SetMode("off"); Check(!w.Visible,"Desativação da barra");
                w.SetMode("left"); w.ResetPosition();
                Check(w.Left == Screen.PrimaryScreen.WorkingArea.Left,"Restaurar na borda esquerda");
                Check(File.Exists(Path.Combine(Program.Data,"widget-position.txt")),"Persistência da posição");
                w.SetMode("off");
                File.WriteAllText(Path.Combine(Program.Data,"widget-position.txt"),"left|230|160");
                w.SetMode("free");
                Check(w.Location == new Point(230,244),"Restaura posição livre salva com alça centralizada");
                foreach (bool right in new[] { false,true }) foreach(bool bottom in new[] { false,true }) {
                    var area=Screen.PrimaryScreen.WorkingArea;
                    int x=right ? area.Right-(int)Field(w,"collapsedWidth") : area.Left, y=bottom ? area.Bottom-(int)Field(w,"collapsedHeight") : area.Top;
                    w.SetMode("off"); File.WriteAllText(Path.Combine(Program.Data,"widget-position.txt"),"v2|free|"+x+"|"+y); w.SetMode("free");
                    Check(w.Location == new Point(x,y),"Alça no canto real: "+w.Location+" esperado "+new Point(x,y));
                    await web.ExecuteScriptAsync("expand()"); await Task.Delay(650);
                    Check(area.Contains(w.Bounds),"Painel aberto dentro da tela real");
                    Check(await web.ExecuteScriptAsync("document.body.dataset.expanded === 'true'") == "true","Controles visíveis no canto");
                    await web.ExecuteScriptAsync("host.postMessage('widget:collapse')"); await Task.Delay(650);
                    Check(w.Location == new Point(x,y),"Alça retorna ao mesmo canto");
                }
                foreach(string dock in new[] { "top","bottom" }) {
                    w.SetMode(dock); await Task.Delay(150);
                    var area=Screen.PrimaryScreen.WorkingArea;
                    Check(w.Width==84 && w.Height==12,"Alça horizontal em cima/embaixo");
                    Check(dock=="top" ? w.Top==area.Top : w.Bottom==area.Bottom,"Encaixe superior/inferior");
                    Check(await web.ExecuteScriptAsync("document.body.dataset.edge === '"+dock+"' && document.body.dataset.expanded === 'false'")=="true","Interface sincronizada na orientação horizontal");
                    await web.ExecuteScriptAsync("expand()"); await Task.Delay(650);
                    Check(area.Contains(w.Bounds),"Painel horizontal dentro da área útil");
                    Check(await web.ExecuteScriptAsync("(()=>{const r=document.querySelector('#action').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight;})()")=="true","Controles horizontais acessíveis");
                    await web.ExecuteScriptAsync("host.postMessage('widget:collapse')"); await Task.Delay(650);
                    Point saved=w.Location; w.SetMode("off"); w.SetMode("free"); await Task.Delay(150);
                    Check(w.Location==saved && w.Width==84 && w.Height==12,"Restaura posição e orientação horizontais");
                }
                w.SetMode("left"); w.ResetPosition();
                await web.ExecuteScriptAsync("expand()"); await Task.Delay(650);
                await web.ExecuteScriptAsync("document.querySelector('#settings').click()");
                for(int i=0;i<30 && await web.ExecuteScriptAsync("settingsBusy || preferences === null")=="true";i++) await Task.Delay(100);
                Check(!main.Visible,"Engrenagem abre ajustes locais sem mostrar a janela principal");
                Check(await web.ExecuteScriptAsync("!document.querySelector('#preferences').hidden && document.querySelector('#recording-panel').hidden")=="true","Painel de ajustes integrado à barra");
                await Shot(web, "widget-prefs");
                Check(await web.ExecuteScriptAsync("document.querySelectorAll('[data-category]').length===8")=="true","Todos os grupos de ajustes na barra (com a Proteção do cérebro e a Aparência são oito)");
                await web.ExecuteScriptAsync("openCategory('privacy')");
                await web.ExecuteScriptAsync("savePreferences({keep_temp:true,page_language:'original'})");
                for(int i=0;i<30 && await web.ExecuteScriptAsync("settingsBusy")=="true";i++) await Task.Delay(100);
                Check(await web.ExecuteScriptAsync("preferences.keep_temp && preferences.page_language==='original'")=="true","Ajustes completos salvos pela API real");
                await web.ExecuteScriptAsync("openCategory('transcription')");
                for(int i=0;i<80 && await web.ExecuteScriptAsync("settingsBusy")=="true";i++) await Task.Delay(100);
                Check(await web.ExecuteScriptAsync("settingsState !== null && document.querySelectorAll('#prefs-quality input[type=radio]').length===3")=="true","Seletor de qualidade personalizado e hardware reais no painel adaptativo");
                foreach(string dock in new[] {"left","right","top","bottom"}) {
                    w.SetMode(dock); await web.ExecuteScriptAsync("expand()"); await Task.Delay(650);
                    await web.ExecuteScriptAsync("showPreferences(true); navigatePreferences('privacy'); document.querySelector('#prefs-forget').scrollIntoView({block:'nearest'})");
                    Check(await web.ExecuteScriptAsync("(()=>{const p=document.querySelector('#preferences').getBoundingClientRect(),r=document.querySelector('#prefs-forget').getBoundingClientRect();return p.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight;})()")=="true","Ajustes com rolagem acessíveis na borda "+dock);
                }
                await web.ExecuteScriptAsync("navigatePreferences('desktop')");
                await web.ExecuteScriptAsync("savePreferences({widget:'top'})");
                for(int i=0;i<30 && await web.ExecuteScriptAsync("settingsBusy")=="true";i++) await Task.Delay(100);
                await Task.Delay(500);
                Check(w.Width==84 && w.Height==12 && w.Top==Screen.PrimaryScreen.WorkingArea.Top,"Ajuste local posiciona a barra na borda superior");
                Check(await web.ExecuteScriptAsync("preferences.widget==='top' && document.querySelector('#prefs-feedback').dataset.error==='false'")=="true","Preferência de posição gravada pela API real");
                var mainWeb=(WebView2)Field(main,"web");
                for(int i=0;i<40 && await mainWeb.ExecuteScriptAsync("S.config.widget==='top'")!="true";i++) await Task.Delay(100);
                Check(await mainWeb.ExecuteScriptAsync("S.config.widget==='top'")=="true","Configurações principais recebem a mudança da barra");
                Console.WriteLine("OK: ajustes integrados, posição salva pela API e sincronização com a janela principal.");
                await Chat(main, w, web, mainWeb);
                await Capsule(main, w, web);
                await Understanding(main, w, web, mainWeb);
                Console.WriteLine("OK: quatro orientações nativas, hover, cantos, posição/orientação salva e regressão da cápsula.");
                Environment.ExitCode=0;
            } catch(Exception ex) { Console.WriteLine("FAIL: "+ex.Message); Environment.ExitCode=1; }
            finally { watchdog.Dispose(); typeof(MainForm).GetField("exiting",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(main,true); main.Close(); timer.Dispose(); }
        };
        timer.Start(); Application.Run(main);
    }
}
