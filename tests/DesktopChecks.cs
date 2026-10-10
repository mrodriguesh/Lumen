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
    [STAThread] static void Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s,e) => Assembly.LoadFrom(Path.Combine(Program.Bin,new AssemblyName(e.Name).Name+".dll"));
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        typeof(Program).GetMethod("KillChildrenOnExit",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,null);
        Run(args);
    }
    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    static void Run(string[] args)
    {
        Check(WidgetForm.Clamp(new Point(-3000,9999),new Size(76,252),new Rectangle(-1920,0,1920,1080)) == new Point(-1920,828), "Clamp em tela secundária");
        Check(WidgetForm.Clamp(new Point(9999,-100),new Size(76,252),new Rectangle(0,0,1920,1080)) == new Point(1844,0), "Clamp em tela principal");
        Geometry();
        var desktop = Screen.PrimaryScreen.WorkingArea;
        int idleY = Cursor.Position.Y < desktop.Top+desktop.Height/2 ? desktop.Bottom-84 : desktop.Top;
        Directory.CreateDirectory(Program.Data);
        File.WriteAllText(Path.Combine(Program.Data,"widget-position.txt"),"v2|left|"+desktop.Left+"|"+idleY);
        var main = new MainForm(Path.Combine(Program.Root,".venv","Scripts","pythonw.exe"),true);
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FAIL: timeout de verificação nativa"); Environment.Exit(1); },null,45000,System.Threading.Timeout.Infinite);
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
                Console.WriteLine("OK: quatro orientações nativas, hover, cantos, posição/orientação salva e regressão da cápsula.");
                Environment.ExitCode=0;
            } catch(Exception ex) { Console.WriteLine("FAIL: "+ex.Message); Environment.ExitCode=1; }
            finally { watchdog.Dispose(); typeof(MainForm).GetField("exiting",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(main,true); main.Close(); timer.Dispose(); }
        };
        timer.Start(); Application.Run(main);
    }
}
