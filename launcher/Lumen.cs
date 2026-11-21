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
        // LimitFlags = KILL_ON_JOB_CLOSE | BREAKAWAY_OK: só sai do grupo quem pede (os serviços do Open Notebook, lumen/onlocal.py)
        BitConverter.GetBytes(0x2800).CopyTo(info, 16);
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

// Cores nativas das janelas: fundo, moldura, barra de título do Windows 11 e o escuro do DWM (= ui.css).
// Limites do Windows: o menu da bandeja e as caixas de mensagem são do sistema e não acompanham essas cores.
static class NativeColors
{
    public static readonly Color Bg = Color.FromArgb(8, 9, 12), Border = Color.FromArgb(38, 41, 48), Text = Color.FromArgb(233, 235, 240), Muted = Color.FromArgb(164, 169, 180);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int value, int size);

    public static string ToHex(Color c) { return "#" + c.R.ToString("x2") + c.G.ToString("x2") + c.B.ToString("x2"); }

    // DWM: escuro (20), borda (34), barra de título (35) e texto dela (36). Em versões do Windows sem suporte o atributo é ignorado.
    public static void Dwm(IntPtr handle)
    {
        int d = 1, border = ColorTranslator.ToWin32(Border), caption = ColorTranslator.ToWin32(Bg), text = ColorTranslator.ToWin32(Text);
        DwmSetWindowAttribute(handle, 20, ref d, 4);
        DwmSetWindowAttribute(handle, 34, ref border, 4);
        DwmSetWindowAttribute(handle, 35, ref caption, 4);
        DwmSetWindowAttribute(handle, 36, ref text, 4);
    }
}

class MainForm : Form
{
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int value, int size);
    [DllImport("user32.dll")] static extern int GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);

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
    readonly NotifyIcon tray;
    WidgetForm widget;
    NoteForm note;
    NotebookForm notebook;
    SiteView hyperbook;  // o HyperbookLM dentro desta janela, por cima da página do Lúmen (que continua como estava)
    SiteView perplexity;  // o site oficial do Perplexity, do mesmo jeito, em outro perfil
    bool exiting;
    bool ready;
    int lastNotice;  // último aviso do Pomodoro mostrado (as janelas abertas avisam todas; o Windows mostra uma vez)

    public MainForm(string py, bool background)
    {
        // Aplica também aos controles criados implicitamente pelo WebView2; não altera configurações do Windows.
        // O padrão continua sendo software: com GPU, a verificação nativa já apresentou fechamentos ao redimensionar
        // (docs/DECISOES.md). LUMEN_WEBVIEW_GPU=1 liga a rasterização por GPU só para testar; sem a variável, volta.
        bool gpu = Environment.GetEnvironmentVariable("LUMEN_WEBVIEW_GPU") == "1";
        Environment.SetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            (Environment.GetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") ?? "")
            + (gpu ? " --ignore-gpu-blocklist --enable-gpu-rasterization" : " --disable-gpu"));
        Text = "Lumen";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.Manual;  // posição calculada em OnHandleCreated
        BackColor = NativeColors.Bg;  // = --bg-base do ui.css (8, 9, 12)
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
        FormClosed += (s, e) => { if (note != null) note.Dispose(); if (notebook != null) notebook.Dispose(); if (widget != null) widget.Dispose(); tray.Dispose(); StopServer(); };
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
        if (settings) ToLumen();
        if (settings && ready) web.CoreWebView2.PostWebMessageAsString("desktop:settings");
    }

    // Um pedido que mostra algo da página do Lúmen (Ajustes, uma conversa, a gravação pronta, a nota) sai do HyperbookLM e do Perplexity.
    void ToLumen() { if (hyperbook != null) hyperbook.Back(); if (perplexity != null) perplexity.Back(); }

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
            await web.ExecuteScriptAsync("(async()=>{try { const r=await api('/api/record'); if(r.active) await api('/api/record/stop', {exit:true}); await api('/api/protection', {action:'stop'}); host.postMessage('desktop:exit-ready'); } catch(e) { host.postMessage('desktop:exit-error'); }})()");
        } else { exiting = true; Close(); }
    }

    // “Minha compreensão” destacada: a mesma nota numa janela sempre por cima do vídeo (NoteForm).
    void Float(string key)
    {
        if (string.IsNullOrEmpty(key)) return;
        if (note == null || note.IsDisposed) note = new NoteForm(url, Program.Data, (msg) => {
            if (msg == "note:dock") { ShowMain(false); ToLumen(); }
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

    // “Abrir no Cérebro” da Conversa rápida (barra flutuante): mostra a janela principal na MESMA conversa. Só passa um identificador
    // de conversa ("chat:open:<id>", letras, números, _ e -, até 64; "tmp-" é a temporária) ou o pedido sem id; qualquer outra coisa é
    // descartada aqui, antes de chegar à página. A pergunta nunca é reenviada: a página só relê a conversa que já está no servidor.
    static readonly System.Text.RegularExpressions.Regex ChatId = new System.Text.RegularExpressions.Regex("^(tmp-)?[A-Za-z0-9_-]{1,64}$");
    void OpenChat(string msg)
    {
        string id = msg.Length > 10 ? msg.Substring(10) : "";  // "chat:open:" tem 10 caracteres
        if (msg != "chat:open" && !ChatId.IsMatch(id)) return;
        ShowMain(false);
        ToLumen();
        if (ready) web.CoreWebView2.PostWebMessageAsString(id.Length > 0 ? "desktop:chat:" + id : "desktop:chat");
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
                else if (msg == "chat:open" || msg.StartsWith("chat:open:")) OpenChat(msg);
                else if (msg.StartsWith("notify:")) Notify(msg);
                else if (msg == "record:started" || msg.StartsWith("record:ready:")) {
                    web.CoreWebView2.PostWebMessageAsString(msg);
                    if (msg.StartsWith("record:ready:")) { ShowMain(false); ToLumen(); }
                }
            });
        }
        if (widget != null) widget.SetMode(mode);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        NativeColors.Dwm(Handle);  // moldura escura, borda, barra de título e texto dela
        if (customFrame)  // recalcula a moldura sem a barra de título nativa
            SetWindowPos(Handle, IntPtr.Zero, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004);  // FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER
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
        if (m.Msg == 0x02E0)  // WM_DPICHANGED: a barra do HyperbookLM e a do Perplexity acompanham a escala
            foreach (var v in new[] { hyperbook, perplexity }) if (v != null) v.Relayout();
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
        core.Settings.IsZoomControlEnabled = false;
        core.Settings.IsPinchZoomEnabled = false;
        // A página sabe o que este Lumen.exe abre nele: 2 = HyperbookLM (hyperbooklm.js); 3 = também o Perplexity (study.js).
        core.Settings.UserAgent += " LumenShell/3";
        web.ZoomFactor = 1.0;
        web.NavigationCompleted += (s, e) => { web.ZoomFactor = 1.0; };
        if (customFrame) core.Settings.IsNonClientRegionSupportEnabled = true;  // CSS app-region: drag
        // Na bandeja ou minimizada, a página pede ao WebView2 menos memória (ele descarta caches); os scripts seguem
        // rodando (Pomodoro, avisos, rascunhos). Ao aparecer, volta ao normal.
        EventHandler trim = (s, e) => core.MemoryUsageTargetLevel = Visible && WindowState != FormWindowState.Minimized
            ? CoreWebView2MemoryUsageTargetLevel.Normal : CoreWebView2MemoryUsageTargetLevel.Low;
        VisibleChanged += trim;
        Resize += trim;
        trim(null, null);
        core.ProcessFailed += (s, e) => {  // o renderizador caiu: recarrega em vez de deixar a janela em branco
            if (e.ProcessFailedKind != CoreWebView2ProcessFailedKind.BrowserProcessExited) { try { core.Reload(); } catch (Exception) { } }
        };
        core.WebMessageReceived += async (s, e) =>
        {
            string msg = e.TryGetWebMessageAsString();
            if (e.Source == "about:blank" && msg == "window:close") { Close(); return; }
            if (!e.Source.StartsWith(url, StringComparison.Ordinal)) return;
            if (msg == "window:close") Close();
            else if (msg == "zoom:reset") web.ZoomFactor = 1.0;
            else if (msg == "window:minimize") WindowState = FormWindowState.Minimized;
            // A barra de título é desenhada pela página: arrastar pede aqui o movimento nativo (encaixe nas bordas incluído). Sem
            // app-region: drag, a página continua recebendo o mouse na barra e o cursor do Lumen não some ali.
            else if (msg == "window:drag" && (MouseButtons & MouseButtons.Left) != 0)
            {
                ReleaseCapture();
                SendMessage(Handle, 0x00A1, new IntPtr(2), IntPtr.Zero);  // WM_NCLBUTTONDOWN, HTCAPTION
            }
            else if (msg == "window:maximize")
                WindowState = WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized;
            else if (msg.StartsWith("desktop:prefs:")) ApplyWidget(msg.Substring("desktop:prefs:".Length));
            else if (msg == "widget:reset" && widget != null) widget.ResetPosition();
            else if (msg.StartsWith("note:float:")) Float(msg.Substring("note:float:".Length));
            else if (msg.StartsWith("notify:")) Notify(msg);
            else if (msg.StartsWith("opennotebook:open:")) OpenNotebook(msg.Substring("opennotebook:open:".Length));
            else if (msg.StartsWith("hyperbooklm:open:")) OpenHyperbook(msg.Substring("hyperbooklm:open:".Length));
            else if (msg.StartsWith("perplexity:open:")) OpenPerplexity(msg.Substring("perplexity:open:".Length));
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
        string bg = NativeColors.ToHex(NativeColors.Bg), fg = NativeColors.ToHex(NativeColors.Muted);  // = --bg-base e --text-secondary do ui.css
        // Tela de espera arrastável, com o botão de fechar (sem a barra nativa não haveria outro).
        return "<!doctype html><meta charset=utf-8><body style=\"margin:0;height:100vh;display:grid;place-items:center;app-region:drag;background:" + bg +
               ";color:" + fg + ";font:14px 'Segoe UI Variable Text','Segoe UI',sans-serif\">" +
               "<button onclick=\"chrome.webview.postMessage('window:close')\" aria-label=Fechar style=\"app-region:no-drag;position:fixed;top:21px;left:8px;" +
               "width:12px;height:12px;border-radius:50%;border:0;background:#f05d63;padding:0\"></button>" + System.Net.WebUtility.HtmlEncode(msg);
    }

    bool Listening()
    {
        try { using (var c = new TcpClient()) { c.Connect("127.0.0.1", new Uri(url).Port); return true; } }
        catch (SocketException) { return false; }
    }

    void OpenNotebook(string uri)
    {
        Uri u;  // só http(s); a janela fica presa à origem deste endereço
        if (!Uri.TryCreate(uri, UriKind.Absolute, out u) || (u.Scheme != "http" && u.Scheme != "https")) return;
        if (notebook == null || notebook.IsDisposed) notebook = new NotebookForm("Open Notebook · Lumen", "webview-opennotebook");
        notebook.Open(u.AbsoluteUri);
    }

    void OpenHyperbook(string uri)
    {
        Uri u;  // só http neste PC (a ponte do HyperbookLM não atende outros); abre dentro desta janela, com perfil próprio
        if (!Uri.TryCreate(uri, UriKind.Absolute, out u) || u.Scheme != "http" || !u.IsLoopback) return;
        if (hyperbook == null)
        {
            hyperbook = new SiteView(this, customFrame, () => web.Focus(), "HyperbookLM", "webview-hyperbooklm", null,
                "O HyperbookLM não está respondendo em {0}.\nAbra-o com npm run dev na pasta dele e clique em Recarregar.", null);
            Controls.Add(hyperbook);
        }
        hyperbook.Open(u.AbsoluteUri);
    }

    // Hosts que o painel do Perplexity abre dentro dele, só por https: o site e as entradas com Google e Apple
    // (redirecionamentos conferidos em 19/11/2026; docs/DECISOES.md D185). Todo o resto vai ao navegador padrão (link
    // clicado) ou é bloqueado (redirecionamento sozinho).
    static readonly string[] PerplexityHosts = { "www.perplexity.ai", "perplexity.ai", "accounts.google.com", "appleid.apple.com" };
    internal static bool PerplexitySite(Uri u) { return u.Scheme == "https" && u.IsDefaultPort && Array.IndexOf(PerplexityHosts, u.Host) >= 0; }

    // "perplexity:open:<endereço>": só a página inicial ou a busca do site oficial (/search?q=, o modelo do opensearch.xml dele).
    internal static bool PerplexityStart(string uri)
    {
        Uri u;
        return Uri.TryCreate(uri, UriKind.Absolute, out u) && u.Scheme == "https" && u.IsDefaultPort && u.Host == "www.perplexity.ai"
            && u.UserInfo == "" && u.Fragment == "" && (u.AbsolutePath == "/" || (u.AbsolutePath == "/search" && u.Query.StartsWith("?q=")));
    }

    void OpenPerplexity(string uri)
    {
        if (!PerplexityStart(uri)) return;
        if (perplexity == null)
        {
            perplexity = new SiteView(this, customFrame, () => web.Focus(), "Perplexity", "webview-perplexity", PerplexitySite,
                "Não foi possível abrir o Perplexity.\nConfira a internet e clique em Recarregar, ou volte ao Lúmen.",
                () => { if (ready) web.CoreWebView2.PostWebMessageAsString("desktop:perplexity:paste"); });
            Controls.Add(perplexity);
        }
        perplexity.Open(uri);
    }

    internal static void OpenExternal(string uri)
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

}

// Open Notebook numa janela própria: perfil WebView2 separado (não vê os dados do Lumen), sem ponte de mensagens com o
// aplicativo e com a navegação presa à origem configurada; qualquer outro endereço abre no navegador padrão.
// (O HyperbookLM e o Perplexity não usam esta janela: abrem dentro da principal, em SiteView.)
class NotebookForm : Form
{
    readonly WebView2 web;
    readonly string profile;
    Task ready;
    string origin;

    public NotebookForm(string title, string profile)
    {
        this.profile = profile;
        Text = title;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        BackColor = NativeColors.Bg;
        var area = Screen.FromPoint(Cursor.Position).WorkingArea;  // proporcional à tela: vale para qualquer DPI
        Size = new Size(area.Width * 4 / 5, area.Height * 9 / 10);
        MinimumSize = new Size(area.Width / 3, area.Height / 3);
        StartPosition = FormStartPosition.CenterScreen;
        web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
        Controls.Add(web);
    }

    public async void Open(string uri)
    {
        origin = new Uri(uri).GetLeftPart(UriPartial.Authority);
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        try
        {
            if (ready == null) ready = Init();
            await ready;
            web.CoreWebView2.Navigate(uri);
        }
        catch (Exception) { Close(); MainForm.OpenExternal(uri); }  // sem WebView2: o navegador padrão
    }

    async Task Init()
    {
        var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Program.Data, profile));
        await web.EnsureCoreWebView2Async(env);
        var core = web.CoreWebView2;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        core.Settings.IsWebMessageEnabled = false;  // a página do Open Notebook não fala com o aplicativo
        core.NavigationStarting += (s, e) => { if (!Inside(e.Uri)) { e.Cancel = true; MainForm.OpenExternal(e.Uri); } };
        core.NewWindowRequested += (s, e) => { e.Handled = true; if (Inside(e.Uri)) core.Navigate(e.Uri); else MainForm.OpenExternal(e.Uri); };
    }

    bool Inside(string uri)
    {
        Uri u;
        return uri == "about:blank" || (Uri.TryCreate(uri, UriKind.Absolute, out u) && u.GetLeftPart(UriPartial.Authority) == origin);
    }
}

// Um site dentro da janela principal (HyperbookLM, Perplexity): um painel nativo por cima da página do Lúmen (que continua
// carregada, no mesmo estado) com uma barra do Lúmen (voltar, recarregar, nome e estado) e um WebView2 com perfil próprio
// (webview-hyperbooklm, webview-perplexity). Esse WebView2 não vê os dados do Lúmen, não tem ponte de mensagens com o
// aplicativo e fica preso ao que foi liberado: a origem local aberta (HyperbookLM) ou a lista de hosts https do site
// (allow, no Perplexity). Link de fora clicado abre no navegador padrão; redirecionamento por script e outros esquemas
// são bloqueados. Num site da internet (allow) também não há download, permissão (microfone, câmera, local, notificação,
// área de transferência para leitura) nem abertura de outro aplicativo por esquema próprio.
// A área nunca fica em branco: enquanto carrega, com o servidor fora do ar ou sem o WebView2, mostra um aviso e o
// “Recarregar” tenta de novo. O botão extra (bring), se houver, volta ao Lúmen e pede à página para colar a resposta.
class SiteView : Panel
{
    [DllImport("user32.dll")] static extern int GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);

    // = ui.css: --surface-2, --surface-3, --success, --warning, --danger-dot
    static readonly Color Hover = Color.FromArgb(24, 27, 33), Rest = Color.FromArgb(32, 36, 43), Ok = Color.FromArgb(60, 207, 145),
        Warn = Color.FromArgb(240, 177, 69), Danger = Color.FromArgb(240, 93, 99);

    readonly Form owner;
    readonly Action back;
    readonly string name, profile, unavailable;  // unavailable: o aviso de “não respondeu”, com {0} = a origem
    readonly Func<Uri, bool> allow;  // null: só a origem aberta (HyperbookLM)
    readonly Panel bar = new Panel(), body = new Panel { Dock = DockStyle.Fill };
    readonly Label title = new Label(), status = new Label { AutoEllipsis = true }, message = new Label();
    readonly Button home = new Button { Text = "←  Voltar ao Lúmen" }, reload = new Button { Text = "↻  Recarregar" };
    readonly Button[] buttons;
    readonly Control[] lights;  // fechar, minimizar e maximizar, como os da página (só sem a barra de título nativa)
    WebView2 web;
    Task ready;
    string origin, target, blocked;
    bool loaded, hot, placing;
    float scale;

    public SiteView(Form owner, bool customFrame, Action back, string name, string profile, Func<Uri, bool> allow, string unavailable, Action bring)
    {
        this.owner = owner;
        this.back = back;
        this.name = name;
        this.profile = profile;
        this.allow = allow;
        this.unavailable = unavailable;
        title.Text = name;
        Dock = DockStyle.Fill;
        Visible = false;
        BackColor = bar.BackColor = body.BackColor = NativeColors.Bg;
        bar.Dock = DockStyle.Top;
        var tips = new ToolTip();
        var paste = bring == null ? null : new Button { Text = "⤓  Trazer resposta ao Lúmen", AccessibleName = "Trazer resposta ao Lúmen" };
        buttons = paste == null ? new[] { home, reload } : new[] { home, reload, paste };
        if (paste != null)
        {
            tips.SetToolTip(paste, "Copie a resposta no " + name + " (botão Copiar) e clique aqui para colar no Lúmen");
            paste.Click += (s, e) => { Back(); bring(); };
        }
        foreach (var b in buttons)
        {
            b.FlatStyle = FlatStyle.Flat;
            b.FlatAppearance.BorderSize = 0;
            b.FlatAppearance.MouseOverBackColor = Hover;
            b.FlatAppearance.MouseDownBackColor = Rest;
            b.BackColor = NativeColors.Bg;
            b.ForeColor = NativeColors.Text;
            b.UseVisualStyleBackColor = false;
            bar.Controls.Add(b);
        }
        home.AccessibleName = "Voltar ao Lúmen";
        reload.AccessibleName = "Recarregar o " + name;
        tips.SetToolTip(home, "Voltar ao Lúmen (a tela continua como estava)");
        tips.SetToolTip(reload, "Recarregar o " + name);
        home.Click += (s, e) => Back();
        reload.Click += async (s, e) => { if (loaded && web != null) web.CoreWebView2.Reload(); else await Go(); };
        title.ForeColor = NativeColors.Text;
        status.ForeColor = NativeColors.Muted;
        foreach (Control c in new Control[] { title, status }) { c.BackColor = NativeColors.Bg; bar.Controls.Add(c); }
        foreach (Control c in new Control[] { bar, title, status }) c.MouseDown += Drag;
        bar.Paint += (s, e) => { using (var p = new Pen(NativeColors.Border)) e.Graphics.DrawLine(p, 0, bar.Height - 1, bar.Width, bar.Height - 1); };
        bar.SizeChanged += (s, e) => Relayout();
        lights = customFrame ? new Control[] { Light(Danger, "Fechar", () => owner.Close()), Light(Warn, "Minimizar", () => owner.WindowState = FormWindowState.Minimized),
            Light(Ok, "Maximizar", Maximize) } : new Control[0];
        message.Dock = DockStyle.Fill;
        message.TextAlign = ContentAlignment.MiddleCenter;
        message.ForeColor = NativeColors.Muted;
        message.BackColor = NativeColors.Bg;
        body.Controls.Add(message);
        Controls.Add(body);  // o último adicionado é encaixado primeiro: a barra em cima, o conteúdo no resto
        Controls.Add(bar);
    }

    Control Light(Color color, string name, Action click)
    {
        var c = new Panel { BackColor = NativeColors.Bg, AccessibleName = name, AccessibleRole = AccessibleRole.PushButton };
        c.Paint += (s, e) =>
        {
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            float d = c.Width / 2f, o = (c.Width - d) / 2f;  // círculo de 12 px num alvo de 24 px, como na página
            using (var b = new SolidBrush(hot ? color : Rest)) e.Graphics.FillEllipse(b, o, o, d, d);
        };
        c.MouseEnter += (s, e) => Heat(true);
        c.MouseLeave += (s, e) => Heat(false);
        c.Click += (s, e) => click();
        bar.Controls.Add(c);
        return c;
    }

    void Heat(bool on) { hot = on; foreach (var c in lights) c.Invalidate(); }  // os três ganham cor juntos, como na página

    void Maximize() { owner.WindowState = owner.WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized; }

    void Drag(object sender, MouseEventArgs e)  // a barra arrasta a janela; dois cliques maximizam
    {
        if (e.Button != MouseButtons.Left) return;
        if (e.Clicks == 2) { Maximize(); return; }
        ReleaseCapture();
        SendMessage(owner.Handle, 0x00A1, new IntPtr(2), IntPtr.Zero);  // WM_NCLBUTTONDOWN, HTCAPTION
    }

    // Medidas em pixels pela escala da janela (o processo é Per-Monitor V2 e o WinForms 4.8 não reescala sozinho).
    internal void Relayout()
    {
        if (placing || !owner.IsHandleCreated) return;
        placing = true;
        float k = GetDpiForWindow(owner.Handle) / 96f;
        if (k != scale)
        {
            scale = k;
            foreach (var b in buttons) b.Font = new Font("Segoe UI", 13f * k, GraphicsUnit.Pixel);
            status.Font = new Font("Segoe UI", 13f * k, GraphicsUnit.Pixel);
            title.Font = new Font("Segoe UI", 13f * k, FontStyle.Bold, GraphicsUnit.Pixel);
            message.Font = new Font("Segoe UI", 14f * k, GraphicsUnit.Pixel);
        }
        int h = (int)(44 * k), gap = (int)(8 * k), x = gap, light = (int)(24 * k), tall = (int)(30 * k);
        bar.Height = h;
        foreach (var c in lights) { c.SetBounds(x, (h - light) / 2, light, light); x += light; }
        if (lights.Length > 0) x += gap;
        foreach (var b in buttons)
        {
            b.SetBounds(x, (h - tall) / 2, TextRenderer.MeasureText(b.Text, b.Font).Width + (int)(18 * k), tall);
            x += b.Width + gap / 2;
        }
        x += gap;
        int th = TextRenderer.MeasureText("Hg", title.Font).Height, tw = TextRenderer.MeasureText(title.Text, title.Font).Width;
        title.SetBounds(x, (h - th) / 2, tw, th);
        x += tw + gap;
        status.SetBounds(x, (h - th) / 2, Math.Max(0, bar.Width - x - gap), th);
        placing = false;
    }

    public async void Open(string uri)
    {
        bool same = loaded && web != null && uri == target;
        origin = new Uri(uri).GetLeftPart(UriPartial.Authority);
        target = uri;
        Visible = true;
        BringToFront();
        Relayout();
        if (same) { web.Focus(); return; }  // já aberto neste endereço (a mesma pergunta): volta como estava, sem recarregar
        await Go();
    }

    public void Back()
    {
        if (!Visible) return;
        Visible = false;  // o HyperbookLM continua carregado para a próxima vez; a página do Lúmen nunca saiu de onde estava
        back();
    }

    async Task Go()
    {
        loaded = false;
        Say("Abrindo o " + name + "…", "Carregando…", NativeColors.Muted);
        try
        {
            if (ready == null) ready = Init();
            if (await Task.WhenAny(ready, Task.Delay(30000)) != ready)  // o WebView2 pode travar em vez de falhar (perfil inacessível)
            {
                Drop();  // abandona a tentativa travada: “Recarregar” começa outra do zero
                Say("O navegador interno (WebView2) demorou demais para iniciar.\nClique em Recarregar para tentar de novo ou volte ao Lúmen.", "Erro", Warn);
                return;
            }
            await ready;
            web.CoreWebView2.Navigate(target);
        }
        catch (Exception)
        {
            Drop();
            Say("Não foi possível iniciar o navegador interno (WebView2).\nClique em Recarregar para tentar de novo ou volte ao Lúmen.", "Erro", Warn);
        }
    }

    void Say(string text, string state, Color color)
    {
        if (web != null) web.Visible = false;
        message.Text = text;
        message.Visible = true;
        status.Text = "·  " + state;
        status.ForeColor = color;
    }

    void Drop()
    {
        if (web != null) { body.Controls.Remove(web); web.Dispose(); web = null; }
        ready = null;
        loaded = false;
    }

    async Task Init()
    {
        var w = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = NativeColors.Bg, Visible = false };
        body.Controls.Add(w);
        web = w;  // se a partida falhar ou travar, Drop() descarta este controle e a próxima tentativa cria outro
        var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Program.Data, profile));
        await w.EnsureCoreWebView2Async(env);
        var core = w.CoreWebView2;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        core.Settings.IsWebMessageEnabled = false;  // a página do site não fala com o aplicativo
        core.Settings.AreHostObjectsAllowed = false;
        if (allow != null)  // site da internet: só navegar, ler e copiar
        {
            core.PermissionRequested += (s, e) => { e.State = CoreWebView2PermissionState.Deny; };
            core.LaunchingExternalUriScheme += (s, e) => { e.Cancel = true; };
            core.DownloadStarting += (s, e) =>
            {
                e.Cancel = true;
                e.Handled = true;
                Status("Download bloqueado aqui: use Copiar no " + name + " e traga a resposta ao Lúmen", Warn);
            };
        }
        core.NavigationStarting += (s, e) =>
        {
            if (Inside(e.Uri)) { if (loaded) Status("Carregando…", NativeColors.Muted); return; }
            e.Cancel = true;
            // Só um link clicado (http/https) sai para o navegador; redirecionamento e o resto são só bloqueados, com aviso.
            if (e.IsUserInitiated && !e.IsRedirected && (e.Uri.StartsWith("https://") || e.Uri.StartsWith("http://"))) MainForm.OpenExternal(e.Uri);
            else Status("Bloqueado: " + (blocked = Host(e.Uri)), Warn);
        };
        core.NewWindowRequested += (s, e) =>
        {
            e.Handled = true;
            if (Inside(e.Uri)) core.Navigate(e.Uri);
            else if (e.IsUserInitiated) MainForm.OpenExternal(e.Uri);
        };
        core.NavigationCompleted += (s, e) =>
        {
            if (w != web) return;
            // Unknown: o servidor respondeu com uma página de erro dele (HTTP 4xx/5xx), que é mostrada como veio.
            if (e.IsSuccess || e.WebErrorStatus == CoreWebView2WebErrorStatus.Unknown)
            {
                loaded = true;
                message.Visible = false;
                w.Visible = true;
                Status(Host(core.Source), Ok);
                if (Visible) w.Focus();
            }
            else if (e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled)
            {
                loaded = false;
                Say(string.Format(unavailable, origin), "Servidor indisponível", Warn);
            }
            else if (loaded && !status.Text.Contains("Bloqueado")) Status(Host(core.Source), Ok);  // link de fora: a página segue a mesma
            else if (!loaded && status.Text.Contains("Bloqueado"))  // a abertura foi levada para fora do liberado: avisa em vez de “Abrindo…”
                Say("O " + name + " tentou ir para " + blocked + ", um endereço que este painel não abre.\nClique em Recarregar ou volte ao Lúmen.", "Bloqueado: " + blocked, Warn);
        };
        core.ProcessFailed += (s, e) =>
        {
            if (w != web) return;
            bool gone = e.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited;
            if (!gone && e.ProcessFailedKind != CoreWebView2ProcessFailedKind.RenderProcessExited) return;  // os outros se recuperam sozinhos
            loaded = false;
            if (gone) Drop();
            Say("O " + name + " parou de responder.\nClique em Recarregar.", "Parado", Warn);
        };
    }

    void Status(string state, Color color) { status.Text = "·  " + state; status.ForeColor = color; }

    static string Host(string uri) { Uri u; return Uri.TryCreate(uri, UriKind.Absolute, out u) && u.Authority != "" ? u.Authority : uri.Split(':')[0] + ":"; }

    bool Inside(string uri)
    {
        Uri u;
        if (uri == "about:blank") return true;
        if (!Uri.TryCreate(uri, UriKind.Absolute, out u)) return false;
        return allow != null ? allow(u) : u.GetLeftPart(UriPartial.Authority) == origin;
    }
}
