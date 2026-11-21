using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;

// Verificação NATIVA do anel de foco nos itens do menu (WebView2 real): compile com os três arquivos do launcher usando
// /target:exe /main:FocusRingCheck, na raiz do projeto, e rode com LUMEN_DATA numa pasta isolada. CLICA COM O MOUSE DE VERDADE
// num item do menu (o cursor volta ao lugar no fim). Um clique de mouse não pode deixar o anel aceso depois que a janela
// recebe o foco de volta (outra janela, web.Focus() ao voltar de um painel) nem depois de Alt; o Tab tem de acendê-lo.
static class FocusRingCheck
{
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern void mouse_event(int flags, int dx, int dy, int data, IntPtr extra);
    [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, int flags, IntPtr extra);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    static int fails;

    static object Field(object o, string name) { return o.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(o); }
    static void Check(bool ok, string what) { Console.WriteLine((ok ? "ok    " : "FALHA ") + what); if (!ok) fails++; }
    static async Task<string> Js(WebView2 w, string js) { return (await w.ExecuteScriptAsync(js)).Trim('"'); }
    const string Ring = "(() => { const e = document.activeElement; const s = getComputedStyle(e); return (e.className || e.tagName) + '|' + (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0); })()";

    [STAThread] static void Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => Assembly.LoadFrom(Path.Combine(Program.Bin, new AssemblyName(e.Name).Name + ".dll"));
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        typeof(Program).GetMethod("KillChildrenOnExit", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, null);
        typeof(Program).GetMethod("SetProcessDpiAwarenessContext", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, new object[] { new IntPtr(-4) });
        if (Environment.GetEnvironmentVariable("LUMEN_DATA") == null) { Console.WriteLine("Uso: LUMEN_DATA=<pasta isolada> Lumen.FocusRingCheck.exe [captura.png]"); Environment.ExitCode = 2; return; }
        Directory.CreateDirectory(Program.Data);
        File.WriteAllText(Path.Combine(Program.Data, "config.json"), "{\"widget\": \"off\", \"ui_style\": \"glass\"}");
        bool bg = Array.IndexOf(args, "--background") >= 0;  // como o “Abrir com o Windows”: começa escondido, aparece pela bandeja
        var main = new MainForm(Path.Combine(Program.Root, ".venv", "Scripts", "pythonw.exe"), bg);
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FALHA tempo esgotado"); Environment.Exit(1); }, null, 240000, System.Threading.Timeout.Infinite);
        string shot = args.Length > 0 && !args[0].StartsWith("--") ? args[0] : null;
        if (bg)
        {
            var later = new Timer { Interval = 12000 };  // o servidor e a página sobem escondidos; depois, “Abrir Lumen” na bandeja
            later.Tick += (s, e) => { later.Stop(); typeof(MainForm).GetMethod("ShowMain", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(main, new object[] { false }); };
            later.Start();
        }
        bool once = false;
        main.Shown += async (s, e) =>
        {
            if (once) return;
            once = true;
            if (bg) await Task.Delay(500);
            Point back = Cursor.Position;
            try { await Checks(main, shot); } catch (Exception ex) { Check(false, "exceção: " + ex); }
            SetCursorPos(back.X, back.Y);
            watchdog.Dispose();
            typeof(MainForm).GetField("exiting", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(main, true);
            main.Close();
        };
        Application.Run(main);
        Console.WriteLine(fails == 0 ? "TUDO OK" : fails + " FALHA(S)");
        Environment.ExitCode = fails == 0 ? 0 : 1;
    }

    static async Task Checks(MainForm main, string shot)
    {
        var web = (WebView2)Field(main, "web");
        for (int i = 0; i < 480; i++) { try { if (await Js(web, "typeof S !== 'undefined' && !!S && !!document.querySelector('.rail-item[data-view=\"library\"]')") == "true") break; } catch (Exception) { } await Task.Delay(250); }
        await Task.Delay(1500);
        string start = await Js(web, Ring);
        Check(!start.EndsWith("true"), "abrir o Lúmen: nenhum item com anel sem o teclado (" + start + ")");
        main.TopMost = true; main.Activate(); SetForegroundWindow(main.Handle);
        await Task.Delay(800);
        start = await Js(web, Ring);
        Check(!start.EndsWith("true"), "janela ativada: nenhum item com anel sem o teclado (" + start + ")");
        string[] r = (await Js(web, "(() => { const b = document.querySelector('.rail-item[data-view=\"library\"]').getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2, devicePixelRatio].join('|'); })()")).Split('|');
        double k = double.Parse(r[2], System.Globalization.CultureInfo.InvariantCulture);
        Point o = web.PointToScreen(Point.Empty);
        SetCursorPos(o.X + (int)(double.Parse(r[0], System.Globalization.CultureInfo.InvariantCulture) * k), o.Y + (int)(double.Parse(r[1], System.Globalization.CultureInfo.InvariantCulture) * k));
        await Task.Delay(200);
        mouse_event(0x0002, 0, 0, 0, IntPtr.Zero); mouse_event(0x0004, 0, 0, 0, IntPtr.Zero);  // clique esquerdo de verdade
        await Task.Delay(800);
        string a = await Js(web, Ring);
        Check(!a.EndsWith("true"), "clique do mouse: sem anel (" + a + ")");
        web.Focus();  // o que o Lumen.exe faz ao voltar de um painel (HyperbookLM, Perplexity)
        await Task.Delay(600);
        a = await Js(web, Ring);
        Check(!a.EndsWith("true"), "web.Focus() (voltar de um painel): sem anel (" + a + ")");
        var other = new Form { Text = "outra", Width = 300, Height = 200, StartPosition = FormStartPosition.Manual, Location = new Point(0, 0), TopMost = true };
        other.Show(); other.Activate(); SetForegroundWindow(other.Handle);
        await Task.Delay(700);
        main.Activate(); SetForegroundWindow(main.Handle);
        await Task.Delay(700);
        other.Close();
        a = await Js(web, Ring);
        Check(!a.EndsWith("true"), "a janela volta ao foco (outra janela antes): sem anel (" + a + ")");
        // fechar para a bandeja e reabrir (ShowMain: Show, Normal, Activate)
        main.Hide();
        await Task.Delay(800);
        typeof(MainForm).GetMethod("ShowMain", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(main, new object[] { false });
        await Task.Delay(1200);
        a = await Js(web, Ring);
        Check(!a.EndsWith("true"), "reabrir pela bandeja (Hide → ShowMain): sem anel (" + a + ")");
        // “Voltar ao Lúmen” de um painel (HyperbookLM/Perplexity): o painel some e o foco volta à página do Lúmen
        string page = (string)Field(main, "url");
        typeof(MainForm).GetMethod("OpenHyperbook", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(main, new object[] { page });
        await Task.Delay(4000);
        var view = (SiteView)Field(main, "hyperbook");
        ((Button)Field(view, "home")).Focus();  // o clique do mouse deixa o foco no botão nativo
        ((Button)Field(view, "home")).PerformClick();
        await Task.Delay(1000);
        a = await Js(web, Ring);
        Check(!a.EndsWith("true"), "Voltar ao Lúmen de um painel: nenhum item do menu fica com anel (" + a + ")");
        if (shot != null) using (var f = File.Create(shot)) await web.CoreWebView2.CapturePreviewAsync(Microsoft.Web.WebView2.Core.CoreWebView2CapturePreviewImageFormat.Png, f);
        keybd_event(0x09, 0, 0, IntPtr.Zero); keybd_event(0x09, 0, 2, IntPtr.Zero);  // Tab: navegação pelo teclado
        await Task.Delay(500);
        a = await Js(web, Ring);
        Check(a.EndsWith("true"), "Tab: o anel aparece para quem usa o teclado (" + a + ")");
    }
}
