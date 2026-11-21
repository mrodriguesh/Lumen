using System;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;

// Verificação NATIVA do cursor próprio (cursor.js) na barra de cima: compile com os três arquivos do launcher usando
// /target:exe /main:CursorDragCheck, na raiz do projeto, e rode com LUMEN_DATA numa pasta isolada.
// MOVE O MOUSE DE VERDADE por alguns segundos (e aperta o botão esquerdo na barra para arrastar a janela) e o devolve ao lugar no fim.
// Desde 20/11/2026 a barra não é app-region: drag (app.js pede window:drag ao Lumen.exe): o cursor do Lumen aparece e segue o mouse
// ali, arrastar move a janela, dois cliques maximizam e restauram, e o “apertado” não fica preso depois de arrastar.
static class CursorDragCheck
{
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
    static void Down() { mouse_event(0x02, 0, 0, 0, UIntPtr.Zero); }
    static void Up() { mouse_event(0x04, 0, 0, 0, UIntPtr.Zero); }
    static int fails;

    static object Field(object o, string name) { return o.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(o); }
    static void Check(bool ok, string what) { Console.WriteLine((ok ? "ok    " : "FALHA ") + what); if (!ok) fails++; }
    static async Task<string> Js(WebView2 w, string js) { return (await w.ExecuteScriptAsync(js)).Trim('"'); }

    [STAThread] static void Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => Assembly.LoadFrom(Path.Combine(Program.Bin, new AssemblyName(e.Name).Name + ".dll"));
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        typeof(Program).GetMethod("KillChildrenOnExit", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, null);
        typeof(Program).GetMethod("SetProcessDpiAwarenessContext", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, new object[] { new IntPtr(-4) });
        if (Environment.GetEnvironmentVariable("LUMEN_DATA") == null) { Console.WriteLine("Uso: LUMEN_DATA=<pasta isolada> Lumen.CursorDragCheck.exe [captura.png]"); Environment.ExitCode = 2; return; }
        Run(args.Length > 0 ? args[0] : null);
    }

    static void Run(string shot)
    {
        Directory.CreateDirectory(Program.Data);
        string style = Environment.GetEnvironmentVariable("LUMEN_UI_STYLE");  // glass ou classic (sem a variável: o padrão do app)
        File.WriteAllText(Path.Combine(Program.Data, "config.json"), "{\"widget\": \"off\"" + (style != null ? ", \"ui_style\": \"" + style + "\"" : "") + "}");
        var main = new MainForm(Path.Combine(Program.Root, ".venv", "Scripts", "pythonw.exe"), false);
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FALHA tempo esgotado"); Environment.Exit(1); }, null, 240000, System.Threading.Timeout.Infinite);
        main.Shown += async (s, e) =>
        {
            Point back = Cursor.Position;
            try { await Checks(main, shot); }
            catch (Exception ex) { Check(false, "exceção: " + ex); }
            SetCursorPos(back.X, back.Y);
            watchdog.Dispose();
            typeof(MainForm).GetField("exiting", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(main, true);
            main.Close();
        };
        Application.Run(main);
        Console.WriteLine(fails == 0 ? "TUDO OK" : fails + " FALHA(S)");
        Environment.ExitCode = fails == 0 ? 0 : 1;
    }

    static async Task Move(Point from, Point to, int steps)
    {
        for (int i = 0; i <= steps; i++) { SetCursorPos(from.X + (to.X - from.X) * i / steps, from.Y + (to.Y - from.Y) * i / steps); await Task.Delay(16); }
    }

    static async Task Checks(MainForm main, string shot)
    {
        var web = (WebView2)Field(main, "web");
        for (int i = 0; i < 480; i++) { try { if (await Js(web, "typeof S !== 'undefined' && !!S && !!document.querySelector('.lumen-cursor')") == "true") break; } catch (Exception) { } await Task.Delay(250); }
        main.TopMost = true; main.Activate(); SetForegroundWindow(main.Handle);
        await Task.Delay(800);
        // um ponto vazio da barra de cima (sem botão por baixo), em pixels da tela
        string r = await Js(web, "(() => { const el = document.querySelector('.topbar'); const b = el.getBoundingClientRect(); for (let x = b.left + 120; x < b.right - 200; x += 20) { const y = b.top + b.height / 2, at = document.elementFromPoint(x, y); if (at && el.contains(at) && !at.closest('button, a, [role=button], [role=tab], .pomo, .pomo-slot')) return [x, y, devicePixelRatio, getComputedStyle(el).appRegion, at.className].join('|'); } return ''; })()");
        Check(r != "", "ponto vazio na barra de cima: " + r);
        if (r == "") return;
        var p = r.Split('|');
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        double k = double.Parse(p[2], inv), bx = double.Parse(p[0], inv), by = double.Parse(p[1], inv);
        Check(p[3] == "no-drag", "a barra não é mais região de arrastar do Windows (appRegion = " + p[3] + ")");
        Point origin = web.PointToScreen(Point.Empty);
        Point bar = new Point(origin.X + (int)(bx * k), origin.Y + (int)(by * k));
        Point middle = new Point(origin.X + web.Width / 2, origin.Y + web.Height / 2);
        await Move(new Point(middle.X - 40, middle.Y), middle, 10);
        await Task.Delay(300);
        Check(await Js(web, "document.querySelector('.lumen-cursor').classList.contains('is-visible')") == "true", "cursor próprio visível no meio da janela");
        await Move(middle, bar, 40);
        await Move(bar, new Point(bar.X + 30, bar.Y), 10);
        await Task.Delay(400);
        string at = await Js(web, "(() => { const d = document.querySelector('.lumen-cursor-dot') || document.querySelector('.lumen-cursor > *'); const m = /translate3d\\(([-\\d.]+)px, ([-\\d.]+)px/.exec(d.style.transform) || []; return [document.querySelector('.lumen-cursor').classList.contains('is-visible'), m[1], m[2]].join('|'); })()");
        var a = at.Split('|');
        Check(a[0] == "true", "sobre a barra de cima o cursor do Lumen aparece (" + at + ")");
        if (a.Length == 3 && a[1] != "")
        {
            double dx = double.Parse(a[1], inv) - (bx + 30 / k), dy = double.Parse(a[2], inv) - by;
            Check(Math.Abs(dx) < 4 && Math.Abs(dy) < 4, "e segue o mouse ali (desvio " + dx.ToString("0.0", inv) + ", " + dy.ToString("0.0", inv) + " px)");
        }
        if (shot != null)
            using (var f = File.Create(shot)) await web.CoreWebView2.CapturePreviewAsync(Microsoft.Web.WebView2.Core.CoreWebView2CapturePreviewImageFormat.Png, f);
        // arrastar pela barra move a janela
        main.TopMost = false;
        Point before = main.Location, grab = new Point(bar.X + 30, bar.Y);
        Down(); await Task.Delay(150);
        await Move(grab, new Point(grab.X + 80, grab.Y + 50), 20);
        Up(); await Task.Delay(400);
        Point after = main.Location;
        Check(Math.Abs(after.X - before.X - 80) <= 6 && Math.Abs(after.Y - before.Y - 50) <= 6, "arrastar a barra move a janela (" + before + " → " + after + ")");
        await Move(new Point(grab.X + 80, grab.Y + 50), new Point(grab.X + 90, grab.Y + 50), 4);
        await Task.Delay(200);
        Check(await Js(web, "document.querySelector('.lumen-cursor').classList.contains('is-down')") == "false", "depois de arrastar o cursor não fica “apertado”");
        // dois cliques maximizam; mais dois restauram
        Point dbl = new Point(grab.X + 80, grab.Y + 50);
        for (int round = 0; round < 2; round++)
        {
            var want = round == 0 ? FormWindowState.Maximized : FormWindowState.Normal;
            if (round == 1)
            {   // maximizada, a barra mudou de lugar: procura o ponto vazio de novo
                await Task.Delay(500);
                string r2 = await Js(web, "(() => { const el = document.querySelector('.topbar'); const b = el.getBoundingClientRect(); for (let x = b.left + 120; x < b.right - 200; x += 20) { const y = b.top + b.height / 2, at = document.elementFromPoint(x, y); if (at && el.contains(at) && !at.closest('button, a, [role=button], [role=tab], .pomo, .pomo-slot')) return [x, y].join('|'); } return ''; })()");
                var q = r2.Split('|'); Point o2 = web.PointToScreen(Point.Empty);
                dbl = new Point(o2.X + (int)(double.Parse(q[0], inv) * k), o2.Y + (int)(double.Parse(q[1], inv) * k));
                SetCursorPos(dbl.X, dbl.Y); await Task.Delay(200);
            }
            Down(); Up(); await Task.Delay(90); Down(); Up();
            await Task.Delay(700);
            Check(main.WindowState == want, (round == 0 ? "dois cliques na barra maximizam" : "mais dois cliques restauram") + " (" + main.WindowState + ")");
        }
        await Move(dbl, middle, 20);
        await Task.Delay(400);
        Check(await Js(web, "document.querySelector('.lumen-cursor').classList.contains('is-visible')") == "true", "de volta ao conteúdo, o cursor próprio continua");
    }
}
