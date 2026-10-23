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
                foreach (var size in new[] { peek, new Size((int)(80*scale),(int)(132*scale)), new Size((int)(304*scale),(int)(252*scale)) }) {
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
                foreach (var size in new[] { handle,new Size((int)(132*scale),(int)(132*scale)),new Size((int)(304*scale),(int)(252*scale)) }) {
                    Rectangle bounds=WidgetForm.WidgetBounds(point,size,handle,area);
                    Check(area.Contains(bounds) && bounds.Contains(new Rectangle(point,handle)),"Painel mantém o mouse dentro nas quatro orientações");
                    Check(edge=="top" ? bounds.Top==area.Top : edge=="bottom" ? bounds.Bottom==area.Bottom : edge=="left" ? bounds.Left==area.Left : bounds.Right==area.Right,"Expansão para dentro da borda");
                    cases++;
                }
            }
        }
        Console.WriteLine("OK: "+cases+" casos de geometria, quatro bordas/cantos e escalas de 100% a 300%.");
    }
    const string NoteKey = "teste:nota-flutuante";
    [STAThread] static void Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s,e) => Assembly.LoadFrom(Path.Combine(Program.Bin,new AssemblyName(e.Name).Name+".dll"));
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        typeof(Program).GetMethod("KillChildrenOnExit",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,null);
        Run(args);
    }
    // “Minha compreensão” nas três interfaces reais (principal, barra lateral e janela flutuante): o mesmo documento.
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
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FAIL: timeout de verificação nativa"); Environment.Exit(1); },null,120000,System.Threading.Timeout.Infinite);
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
                bool reduced = await web.ExecuteScriptAsync("matchMedia('(prefers-reduced-motion: reduce)').matches") == "true";
                Check(await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('.record-symbol')).animationName === '"+(reduced ? "none" : "record-pulse")+"'")=="true","Pulsação aplicada ao núcleo vermelho no WebView2");
                if (!reduced) {
                    var pulseBefore = await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('.record-symbol')).scale");
                    await Task.Delay(350);
                    var pulseMiddle = await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('.record-symbol')).scale");
                    await Task.Delay(350);
                    var pulseAfter = await web.ExecuteScriptAsync("getComputedStyle(document.querySelector('.record-symbol')).scale");
                    Check(pulseBefore!=pulseMiddle || pulseMiddle!=pulseAfter,"Botão pulsa com o tempo real, sem avançar a animação por script");
                    Console.WriteLine("OK: pulsação do botão avança no WebView2 nativo.");
                }
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
                Check(await web.ExecuteScriptAsync("document.querySelectorAll('[data-category]').length===6")=="true","Todos os grupos de ajustes na barra");
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
                await Understanding(main, w, web, mainWeb);
                Console.WriteLine("OK: quatro orientações nativas, hover, cantos, posição/orientação salva e regressão da cápsula.");
                Environment.ExitCode=0;
            } catch(Exception ex) { Console.WriteLine("FAIL: "+ex.Message); Environment.ExitCode=1; }
            finally { watchdog.Dispose(); typeof(MainForm).GetField("exiting",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(main,true); main.Close(); timer.Dispose(); }
        };
        timer.Start(); Application.Run(main);
    }
}
