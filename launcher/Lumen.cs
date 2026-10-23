// Lumen.exe: janela nativa (WebView2) que inicia o servidor local do Lumen e o encerra ao fechar.
// Compilado por launcher\build.ps1 com o csc do .NET Framework (C# 5).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

static class Program
{
    public static readonly string Root = Path.GetDirectoryName(Application.ExecutablePath);
    public static readonly string Bin = Path.Combine(Root, "launcher", "bin");
    public static readonly string Data = Path.Combine(Environment.GetEnvironmentVariable("LUMEN_DATA") ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Lumen");
    public static readonly int ShowMessage = RegisterWindowMessage("Lumen.ShowMainWindow");

    [DllImport("user32.dll")] static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern int RegisterWindowMessage(string name);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);
    [DllImport("kernel32.dll")] static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int cls, byte[] info, int size);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();

    // Tudo que o Lumen.exe inicia (Python e seus filhos) fecha junto com ele, mesmo se for encerrado à força.
    static void KillChildrenOnExit()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        var info = new byte[IntPtr.Size == 8 ? 144 : 112];  // JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        BitConverter.GetBytes(0x2000).CopyTo(info, 16);    // LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        SetInformationJobObject(job, 9, info, info.Length);
        AssignProcessToJobObject(job, GetCurrentProcess());
    }

    [STAThread]
    static void Main(string[] args)
    {
        bool created;
        string isolated = Environment.GetEnvironmentVariable("LUMEN_DATA");  // testes: outra pasta de dados, outra instância
        using (var mutex = new Mutex(true, "Lumen.App.SingleInstance" + (isolated == null ? "" : "." + isolated.ToLowerInvariant().GetHashCode()), out created))
        {
            if (!created)  // já aberto: traz a janela para a frente
            {
                IntPtr h = FindWindow(null, "Lumen");
                if (h != IntPtr.Zero) { PostMessage(h, ShowMessage, IntPtr.Zero, IntPtr.Zero); SetForegroundWindow(h); }
                return;
            }
            string py = Path.Combine(Root, ".venv", "Scripts", "pythonw.exe");
            if (!File.Exists(py))  // primeira execução: o .bat instala as dependências e abre o app
            {
                Process.Start(new ProcessStartInfo(Path.Combine(Root, "Iniciar Lumen.bat")) { WorkingDirectory = Root });
                return;
            }
            AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
            {
                string f = Path.Combine(Bin, new AssemblyName(e.Name).Name + ".dll");
                return File.Exists(f) ? Assembly.LoadFrom(f) : null;
            };
            KillChildrenOnExit();
            SetProcessDpiAwarenessContext(new IntPtr(-4));  // nitidez em telas com escala (Per-Monitor V2)
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Run(py, Array.IndexOf(args, "--background") >= 0);
        }
    }

    [MethodImpl(MethodImplOptions.NoInlining)]  // só carrega o WebView2 depois do AssemblyResolve
    static void Run(string py, bool background) { Application.Run(new MainForm(py, background)); }
}

class MainForm : Form
{
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int value, int size);
    [DllImport("user32.dll")] static extern int GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);

    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct NCCALCSIZE_PARAMS { public RECT r0, r1, r2; public IntPtr pos; }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] static extern bool Shell_NotifyIcon(int msg, ref NOTIFYICONDATA data);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct NOTIFYICONDATA {
        public int cbSize; public IntPtr hWnd; public int uID, uFlags, uCallbackMessage; public IntPtr hIcon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string szTip;
        public int dwState, dwStateMask;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string szInfo;
        public int uVersion;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string szInfoTitle;
        public int dwInfoFlags; public Guid guidItem; public IntPtr hBalloonIcon;
    }

    // Barra de título desenhada pela página (botões estilo Mac). Exige WebView2 123+ (regiões arrastáveis).
    readonly bool customFrame;

    readonly Process server;
    readonly WebView2 web;
    readonly string url;
    readonly bool dark;
    readonly NotifyIcon tray;
    WidgetForm widget;
    NoteForm note;
    bool exiting;
    bool ready;
    int lastNotice;  // último aviso do Pomodoro mostrado (as janelas abertas avisam todas; o Windows mostra uma vez)

    public MainForm(string py, bool background)
    {
        // Aplica também aos controles criados implicitamente pelo WebView2; não altera configurações do Windows.
        Environment.SetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            (Environment.GetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") ?? "") + " --disable-gpu");
        dark = IsDark();
        Text = "Lumen";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.Manual;  // posição calculada em OnHandleCreated
        BackColor = dark ? Color.FromArgb(28, 28, 30) : Color.FromArgb(245, 245, 247);  // = --bg do app.css
        web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
        Controls.Add(web);
        tray = new NotifyIcon { Icon = Icon, Text = "Lumen", Visible = true };
        var menu = new ContextMenuStrip();
        menu.Items.Add("Abrir Lumen", null, (s, e) => ShowMain(false));
        menu.Items.Add("Ajustes", null, (s, e) => ShowMain(true));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Sair do Lumen", null, async (s, e) => await ExitApp());
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += (s, e) => ShowMain(false);
        if (background) { WindowState = FormWindowState.Minimized; ShowInTaskbar = false; }

        try
        {
            CoreWebView2Environment.SetLoaderDllFolderPath(Program.Bin);
            string v = CoreWebView2Environment.GetAvailableBrowserVersionString();
            customFrame = int.Parse(v.Split('.')[0]) >= 123;
        }
        catch (Exception) { customFrame = false; }

        int port = FreePort(Path.Combine(Program.Data, "port.txt"));
        url = "http://127.0.0.1:" + port + "/";
        var psi = new ProcessStartInfo(py, "-m lumen") { WorkingDirectory = Program.Root, UseShellExecute = false, CreateNoWindow = true };
        psi.EnvironmentVariables["LUMEN_PORT"] = port.ToString();
        psi.EnvironmentVariables["LUMEN_NO_WINDOW"] = "1";
        server = Process.Start(psi);

        Load += async (s, e) => {
            if (background) Hide();
            try { await Init(); }
            catch (Exception) { ShowMain(false); MessageBox.Show(this, "Não foi possível abrir a interface do Lumen. Confira o WebView2 e tente novamente.", "Lumen", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        };
        FormClosed += (s, e) => { if (note != null) note.Dispose(); if (widget != null) widget.Dispose(); tray.Dispose(); StopServer(); };
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!exiting && e.CloseReason == CloseReason.UserClosing) {
            e.Cancel = true;
            if (ready) Hide();
            else { exiting = true; Close(); }
        }
        base.OnFormClosing(e);
    }

    void ShowMain(bool settings)
    {
        ShowInTaskbar = true;
        Show(); WindowState = FormWindowState.Normal; Activate();
        if (settings && ready) web.CoreWebView2.PostWebMessageAsString("desktop:settings");
    }

    async Task ExitApp()
    {
        if (exiting) return;
        await FlushNotes();
        // Finaliza o WAV antes de encerrar o Python; a gravação fica guardada no disco.
        if (ready) {
            await web.ExecuteScriptAsync("(async()=>{try {const r=await api('/api/widget'); host.postMessage('desktop:exit-state:' + (r.recording.active || r.job.status === 'running'));} catch(e) {host.postMessage('desktop:exit-error');}})()");
            return;
        }
        exiting = true; Close();
    }

    async Task FinishExit(bool busy)
    {
        if (busy && MessageBox.Show(this, "Há uma gravação ou tarefa em andamento. Sair encerra a tarefa e guarda o áudio captado no PC (a gravação aparece ao abrir o Lumen de novo). Deseja sair?", "Sair do Lumen", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
        if (ready) {
            await web.ExecuteScriptAsync("(async()=>{try { const r=await api('/api/record'); if(r.active) await api('/api/record/stop', {exit:true}); host.postMessage('desktop:exit-ready'); } catch(e) { host.postMessage('desktop:exit-error'); }})()");
        } else { exiting = true; Close(); }
    }

    // “Minha compreensão” destacada: a mesma nota numa janela sempre por cima do vídeo (NoteForm).
    void Float(string key)
    {
        if (string.IsNullOrEmpty(key)) return;
        if (note == null || note.IsDisposed) note = new NoteForm(url, Program.Data, dark, (msg) => {
            if (msg == "note:dock") ShowMain(false);
            else if (msg.StartsWith("notify:")) Notify(msg);
        });
        note.Open(key);
    }

    // Fim de uma etapa do Pomodoro ("notify:pomodoro:<id>:<texto>"): notificação do Windows sem som (NIIF_NOSOUND),
    // para não entrar na gravação; o som do Pomodoro é do Lumen e não toca enquanto a captura grava.
    void Notify(string msg)
    {
        string[] p = msg.Split(new[] { ':' }, 4);
        int id;
        if (p.Length < 4 || !int.TryParse(p[2], out id) || id <= lastNotice) return;
        lastNotice = id;
        try {
            var flags = BindingFlags.NonPublic | BindingFlags.Instance;
            var window = (NativeWindow)typeof(NotifyIcon).GetField("window", flags).GetValue(tray);
            var d = new NOTIFYICONDATA { hWnd = window.Handle, uID = (int)typeof(NotifyIcon).GetField("id", flags).GetValue(tray),
                uFlags = 0x10, szInfo = p[3].Length > 255 ? p[3].Substring(0, 255) : p[3], szInfoTitle = "Pomodoro", dwInfoFlags = 0x10 };
            d.cbSize = Marshal.SizeOf(typeof(NOTIFYICONDATA));
            Shell_NotifyIcon(1, ref d);  // NIM_MODIFY + NIF_INFO
        } catch (Exception) { }  // sem o aviso do Windows, fica o destaque discreto do Pomodoro nas janelas do Lumen
    }

    // Antes de sair: as janelas mandam ao Lumen o texto das notas que ainda não foi salvo.
    async Task FlushNotes()
    {
        if (ready) { try { await web.ExecuteScriptAsync("window.Notes && Notes.flushAll()"); } catch (Exception) { } }
        if (note != null && !note.IsDisposed) await note.Flush();
        if (widget != null && !widget.IsDisposed) await widget.Flush();
    }

    void ApplyWidget(string mode)
    {
        if (mode != "left" && mode != "right" && mode != "top" && mode != "bottom" && mode != "free" && mode != "off") return;
        ready = true;
        if (widget == null && mode != "off") {
            widget = new WidgetForm(url, Program.Data, (msg) => {
                if (msg == "window:open") ShowMain(false);
                else if (msg == "window:settings") ShowMain(true);
                else if (msg == "window:exit") { var ignored = ExitApp(); }
                else if (msg.StartsWith("desktop:prefs:")) ApplyWidget(msg.Substring("desktop:prefs:".Length));
                else if (msg == "widget:reset" && widget != null) widget.ResetPosition();
                else if (msg == "widget:preferences") web.CoreWebView2.PostWebMessageAsString("desktop:preferences-updated");
                else if (msg.StartsWith("window:external:")) OpenExternal(msg.Substring("window:external:".Length));
                else if (msg.StartsWith("note:float:")) Float(msg.Substring("note:float:".Length));
                else if (msg.StartsWith("notify:")) Notify(msg);
                else if (msg == "record:started" || msg.StartsWith("record:ready:")) {
                    web.CoreWebView2.PostWebMessageAsString(msg);
                    if (msg.StartsWith("record:ready:")) ShowMain(false);
                }
            });
        }
        if (widget != null) widget.SetMode(mode);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        int on = dark ? 1 : 0;
        DwmSetWindowAttribute(Handle, 20, ref on, 4);   // barra de título escura no tema escuro
        if (customFrame)  // recalcula a moldura sem a barra de título nativa
            SetWindowPos(Handle, IntPtr.Zero, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004);  // FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER
        int border = ColorTranslator.ToWin32(dark ? Color.FromArgb(58, 58, 60) : Color.FromArgb(200, 200, 205));
        DwmSetWindowAttribute(Handle, 34, ref border, 4);  // borda discreta
        int caption = ColorTranslator.ToWin32(BackColor);
        DwmSetWindowAttribute(Handle, 35, ref caption, 4);  // barra de título da mesma cor do app (Windows 11)
        int text = ColorTranslator.ToWin32(dark ? Color.FromArgb(245, 245, 247) : Color.FromArgb(29, 29, 31));
        DwmSetWindowAttribute(Handle, 36, ref text, 4);
        int round = 2;
        DwmSetWindowAttribute(Handle, 33, ref round, 4);  // cantos arredondados
        float k = GetDpiForWindow(Handle) / 96f;
        Rectangle area = Screen.FromHandle(Handle).WorkingArea;
        MinimumSize = new Size(Math.Min((int)(520 * k), area.Width), Math.Min((int)(560 * k), area.Height));
        Size = new Size(Math.Min((int)(1120 * k), area.Width - (int)(24 * k)), Math.Min((int)(860 * k), area.Height - (int)(24 * k)));
        Location = new Point(area.Left + (area.Width - Width) / 2, area.Top + (area.Height - Height) / 2);
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == Program.ShowMessage) { ShowMain(false); return; }
        // WM_NCCALCSIZE: remove só a barra de título; mantém bordas de redimensionar, sombra e encaixe (Snap).
        if (customFrame && m.Msg == 0x0083 && m.WParam != IntPtr.Zero)
        {
            var before = (NCCALCSIZE_PARAMS)Marshal.PtrToStructure(m.LParam, typeof(NCCALCSIZE_PARAMS));
            base.WndProc(ref m);
            var after = (NCCALCSIZE_PARAMS)Marshal.PtrToStructure(m.LParam, typeof(NCCALCSIZE_PARAMS));
            int inset = after.r0.Left - before.r0.Left;  // espessura da borda; maximizada, a janela passa da tela por isso
            after.r0.Top = before.r0.Top + (WindowState == FormWindowState.Maximized ? inset : 0);
            Marshal.StructureToPtr(after, m.LParam, false);
            m.Result = IntPtr.Zero;
            return;
        }
        base.WndProc(ref m);
    }

    async Task Init()
    {
        string data = Path.Combine(Program.Data, "webview");
        var env = await CoreWebView2Environment.CreateAsync(null, data);
        await web.EnsureCoreWebView2Async(env);
        var core = web.CoreWebView2;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        if (customFrame) core.Settings.IsNonClientRegionSupportEnabled = true;  // CSS app-region: drag
        core.ProcessFailed += (s, e) => {  // o renderizador caiu: recarrega em vez de deixar a janela em branco
            if (e.ProcessFailedKind != CoreWebView2ProcessFailedKind.BrowserProcessExited) { try { core.Reload(); } catch (Exception) { } }
        };
        core.WebMessageReceived += async (s, e) =>
        {
            string msg = e.TryGetWebMessageAsString();
            if (e.Source == "about:blank" && msg == "window:close") { Close(); return; }
            if (!e.Source.StartsWith(url, StringComparison.Ordinal)) return;
            if (msg == "window:close") Close();
            else if (msg == "window:minimize") WindowState = FormWindowState.Minimized;
            else if (msg == "window:maximize")
                WindowState = WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized;
            else if (msg.StartsWith("desktop:prefs:")) ApplyWidget(msg.Substring("desktop:prefs:".Length));
            else if (msg == "widget:reset" && widget != null) widget.ResetPosition();
            else if (msg.StartsWith("note:float:")) Float(msg.Substring("note:float:".Length));
            else if (msg.StartsWith("notify:")) Notify(msg);
            else if (msg.StartsWith("desktop:exit-state:")) await FinishExit(msg.EndsWith("true"));
            else if (msg == "desktop:exit-ready") { exiting = true; Close(); }
            else if (msg == "desktop:exit-error") MessageBox.Show(this, "Não foi possível finalizar a gravação. Pare a gravação no Lumen antes de sair.", "Lumen", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        };
        // Links externos (Notion, Ollama) abrem no navegador padrão.
        core.NewWindowRequested += (s, e) => { e.Handled = true; OpenExternal(e.Uri); };
        core.NavigationStarting += (s, e) =>
        {
            if (!e.Uri.StartsWith(url) && !e.Uri.StartsWith("data:") && !e.Uri.StartsWith("about:")) { e.Cancel = true; OpenExternal(e.Uri); }
        };
        core.NavigateToString(Splash("Abrindo…"));
        for (int i = 0; i < 600; i++)  // até 60 s (a primeira carga do Whisper pode demorar)
        {
            if (server.HasExited)
            {
                core.NavigateToString(Splash("O Lumen não conseguiu iniciar. Veja o arquivo lumen.log em %LOCALAPPDATA%\\Lumen."));
                return;
            }
            if (Listening()) { web.Source = new Uri(url + (customFrame ? "?frame=1" : "")); return; }
            await Task.Delay(100);
        }
        core.NavigateToString(Splash("O Lumen demorou demais para iniciar. Feche e abra de novo."));
    }

    string Splash(string msg)
    {
        string bg = dark ? "#1c1c1e" : "#f5f5f7", fg = dark ? "#98989d" : "#6e6e73";
        // Tela de espera arrastável, com o botão de fechar (sem a barra nativa não haveria outro).
        return "<!doctype html><meta charset=utf-8><body style=\"margin:0;height:100vh;display:grid;place-items:center;app-region:drag;background:" + bg +
               ";color:" + fg + ";font:14px 'Segoe UI Variable Text','Segoe UI',sans-serif\">" +
               "<button onclick=\"chrome.webview.postMessage('window:close')\" aria-label=Fechar style=\"app-region:no-drag;position:fixed;top:20px;left:18px;" +
               "width:12px;height:12px;border-radius:50%;border:0;background:#ff5f57;padding:0\"></button>" + System.Net.WebUtility.HtmlEncode(msg);
    }

    bool Listening()
    {
        try { using (var c = new TcpClient()) { c.Connect("127.0.0.1", new Uri(url).Port); return true; } }
        catch (SocketException) { return false; }
    }

    static void OpenExternal(string uri)
    {
        if (uri.StartsWith("https://") || uri.StartsWith("http://")) Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true });
    }

    void StopServer()
    {
        try { if (!server.HasExited && !server.WaitForExit(800)) server.Kill(); } catch (InvalidOperationException) { }
    }

    // A porta da última vez, se estiver livre: o navegador guarda os dados da página (cópia do rascunho da nota,
    // preferências da janela flutuante, páginas recentes) por endereço, e uma porta nova a cada abertura os perdia.
    static int FreePort(string file)
    {
        int last;
        try {
            if (int.TryParse(File.ReadAllText(file).Trim(), out last) && last > 1024 && last < 65536) {
                var t = new TcpListener(System.Net.IPAddress.Loopback, last);
                try { t.Start(); t.Stop(); return last; } catch (SocketException) { }
            }
        } catch (IOException) { } catch (UnauthorizedAccessException) { }
        var l = new TcpListener(System.Net.IPAddress.Loopback, 0);
        l.Start();
        int p = ((System.Net.IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        try { Directory.CreateDirectory(Program.Data); File.WriteAllText(file, p.ToString()); }
        catch (IOException) { } catch (UnauthorizedAccessException) { }
        return p;
    }

    static bool IsDark()
    {
        object v = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", 1);
        return v is int && (int)v == 0;
    }
}
