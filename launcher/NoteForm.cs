using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// “Minha compreensão” numa janela própria, sempre por cima: dá para escrever enquanto o vídeo da aula toca em outro
// programa. A página (/note) usa o mesmo documento da janela principal e da barra lateral (understanding-editor.js).
// Moldura do sistema sem a barra de título (como a janela principal): bordas de redimensionar, sombra e cantos
// arredondados do Windows; a barra desenhada pela página arrasta a janela.
class NoteForm : Form
{
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern int GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int value, int size);
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct NCCALCSIZE_PARAMS { public RECT r0, r1, r2; public IntPtr pos; }

    // Em pixels de 96 dpi: confortável para escrever, sem ocupar a tela por acidente.
    public static readonly Size Preferred = new Size(400, 500), Least = new Size(300, 240);
    const double MaxWidth = .6, MaxHeight = .92;  // parte da área útil da tela
    const int Bar = 46;                            // altura da barra (minimizada, só ela fica)

    readonly WebView2 web;
    readonly string url, file, dataDir;
    readonly bool dark;
    readonly Action<string> command;
    string key;
    bool compact;
    int fullHeight;

    public NoteForm(string url, string data, bool dark, Action<string> command)
    {
        this.url = url; this.dark = dark; this.command = command; dataDir = data;
        file = Path.Combine(data, "understanding-panel.txt");
        Text = "Minha compreensão · Lumen";
        FormBorderStyle = FormBorderStyle.SizableToolWindow;  // sem botão na barra de tarefas; fica junto do Lumen
        ShowInTaskbar = false; TopMost = true; MaximizeBox = false; MinimizeBox = false;
        StartPosition = FormStartPosition.Manual; AutoScaleMode = AutoScaleMode.None;
        BackColor = dark ? Color.FromArgb(28, 28, 30) : Color.FromArgb(245, 245, 247);
        web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
        Controls.Add(web);
        Load += async (s, e) => { try { await Attach(); } catch (Exception) { Hide(); } };
        ResizeEnd += (s, e) => { Settle(); SaveBounds(); };  // fim de mover ou redimensionar
        DpiChanged += (s, e) => BeginInvoke((Action)(() => { Limits(); Settle(); }));
    }

    async Task Attach()
    {
        var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dataDir, "webview"));
        await web.EnsureCoreWebView2Async(env);
        var core = web.CoreWebView2;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        core.NavigationStarting += (s, e) => { if (!e.Uri.StartsWith(url, StringComparison.Ordinal) && e.Uri != "about:blank") e.Cancel = true; };
        core.NewWindowRequested += (s, e) => e.Handled = true;
        core.ProcessFailed += (s, e) => { try { if (Visible && key != null) Navigate(); } catch (Exception) { } };
        core.WebMessageReceived += (s, e) => {
            if (!e.Source.StartsWith(url, StringComparison.Ordinal)) return;
            string msg = e.TryGetWebMessageAsString();
            if (msg == "note:close") Dismiss();
            else if (msg == "note:dock") { Dismiss(); command(msg); }
            else if (msg.StartsWith("notify:")) command(msg);
            else if (msg.StartsWith("note:key:")) key = msg.Substring("note:key:".Length);  // a janela passou a mostrar outra aula
            else if (msg == "note:minimize") Compact(true);
            else if (msg == "note:restore") Compact(false);
            else if (msg == "note:drag") { ReleaseCapture(); SendMessage(Handle, 0x00A1, new IntPtr(2), IntPtr.Zero); }  // HTCAPTION
        };
        Navigate();
    }

    void Navigate() { if (web.CoreWebView2 != null && key != null) web.CoreWebView2.Navigate(url + "note?key=" + Uri.EscapeDataString(key)); }

    // Abre (ou traz para a frente) a janela com a nota desta aula.
    public void Open(string value)
    {
        bool same = value == key && Visible;
        key = value;
        if (!Visible) { Show(); if (compact) Compact(false); }
        if (!same) Navigate();
        Activate();
    }

    // Fechar nunca descarta a nota: a página já salvou; aqui a janela só se esconde (abre de novo na hora).
    void Dismiss()
    {
        SaveBounds();
        if (web.CoreWebView2 != null) web.CoreWebView2.Navigate("about:blank");
        key = null;
        Hide();
    }

    // O app está saindo: o que a página ainda não salvou vai agora.
    public async Task Flush()
    {
        if (Visible && web.CoreWebView2 != null) { try { await web.ExecuteScriptAsync("window.Notes && Notes.flushAll()"); } catch (Exception) { } }
    }

    float Scale() { return Math.Max(96, GetDpiForWindow(Handle)) / 96f; }

    Rectangle Area() { return Screen.FromRectangle(Bounds).WorkingArea; }

    void Limits()
    {
        float k = Scale();
        Rectangle area = Area();
        MinimumSize = compact ? new Size(Math.Min(area.Width, (int)(Least.Width * k)), 0) : MinSize(area, k);
        MaximumSize = MaxSize(area);
    }

    public static Size MinSize(Rectangle area, float k)
    {
        return new Size(Math.Min(area.Width, (int)Math.Round(Least.Width * k)), Math.Min(area.Height, (int)Math.Round(Least.Height * k)));
    }

    public static Size MaxSize(Rectangle area)
    {
        return new Size(Math.Max(1, (int)(area.Width * MaxWidth)), Math.Max(1, (int)(area.Height * MaxHeight)));
    }

    // Tamanho entre o mínimo e o máximo, e a janela inteira dentro da área útil: nunca fora da tela nem sem como fechar.
    public static Rectangle Fit(Rectangle wanted, Rectangle area, Size min, Size max)
    {
        max = new Size(Math.Max(min.Width, Math.Min(max.Width, area.Width)), Math.Max(min.Height, Math.Min(max.Height, area.Height)));
        var size = new Size(Math.Min(area.Width, Math.Max(min.Width, Math.Min(wanted.Width, max.Width))),
                            Math.Min(area.Height, Math.Max(min.Height, Math.Min(wanted.Height, max.Height))));
        return new Rectangle(WidgetForm.Clamp(wanted.Location, size, area), size);
    }

    // Primeira vez: canto inferior direito, longe do centro da tela, onde costuma ficar o player.
    public static Rectangle Default(Rectangle area, float k)
    {
        var size = new Size((int)Math.Round(Preferred.Width * k), (int)Math.Round(Preferred.Height * k));
        int margin = (int)Math.Round(24 * k);
        return Fit(new Rectangle(area.Right - size.Width - margin, area.Bottom - size.Height - margin, size.Width, size.Height),
                   area, MinSize(area, k), MaxSize(area));
    }

    // Posição e tamanho salvos, se ainda estiverem numa tela que existe; senão, o padrão na tela principal.
    public static Rectangle Restore(string saved, Rectangle[] areas, Rectangle primary, float k)
    {
        string[] p = (saved ?? "").Split('|');
        int x, y, w, h;
        if (p.Length == 5 && p[0] == "v1" && int.TryParse(p[1], out x) && int.TryParse(p[2], out y) &&
            int.TryParse(p[3], out w) && int.TryParse(p[4], out h)) {
            var r = new Rectangle(x, y, w, h);
            foreach (var area in areas)
                if (area.IntersectsWith(r)) return Fit(r, area, MinSize(area, k), MaxSize(area));
        }
        return Default(primary, k);
    }

    void Settle()
    {
        if (compact) { Location = WidgetForm.Clamp(Location, Size, Area()); return; }
        Limits();
        Bounds = Fit(Bounds, Area(), MinimumSize, MaximumSize);
    }

    void Compact(bool on)
    {
        if (on == compact) return;
        if (on) { fullHeight = Height; compact = true; Limits(); Height = (int)Math.Round(Bar * Scale()) + (Height - ClientSize.Height); }
        else { compact = false; Limits(); Height = fullHeight > 0 ? fullHeight : (int)Math.Round(Preferred.Height * Scale()); Settle(); }
        SaveBounds();
    }

    void SaveBounds()
    {
        if (!IsHandleCreated) return;
        int h = compact ? fullHeight : Height;
        try { Directory.CreateDirectory(dataDir); File.WriteAllText(file, "v1|" + Left + "|" + Top + "|" + Width + "|" + h); }
        catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    protected override bool ShowWithoutActivation { get { return false; } }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        int on = dark ? 1 : 0;
        DwmSetWindowAttribute(Handle, 20, ref on, 4);  // moldura escura no tema escuro
        int border = ColorTranslator.ToWin32(dark ? Color.FromArgb(58, 58, 60) : Color.FromArgb(205, 205, 210));
        DwmSetWindowAttribute(Handle, 34, ref border, 4);  // borda discreta
        int round = 2;
        DwmSetWindowAttribute(Handle, 33, ref round, 4);  // cantos arredondados (Windows 11)
        SetWindowPos(Handle, IntPtr.Zero, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004);  // recalcula sem a barra de título
        string saved = null;
        try { saved = File.ReadAllText(file); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        var areas = Array.ConvertAll(Screen.AllScreens, s => s.WorkingArea);
        Bounds = Restore(saved, areas, Screen.PrimaryScreen.WorkingArea, Scale());
        Limits();
    }

    protected override void WndProc(ref Message m)
    {
        // WM_NCCALCSIZE: tira só a barra de título; mantém as bordas de redimensionar (laterais e de baixo) e a sombra.
        if (m.Msg == 0x0083 && m.WParam != IntPtr.Zero)
        {
            var before = (NCCALCSIZE_PARAMS)Marshal.PtrToStructure(m.LParam, typeof(NCCALCSIZE_PARAMS));
            base.WndProc(ref m);
            var after = (NCCALCSIZE_PARAMS)Marshal.PtrToStructure(m.LParam, typeof(NCCALCSIZE_PARAMS));
            after.r0.Top = before.r0.Top;
            Marshal.StructureToPtr(after, m.LParam, false);
            m.Result = IntPtr.Zero;
            return;
        }
        if (m.Msg == 0x0112 && ((long)m.WParam & 0xfff0) == 0xf030) return;  // sem maximizar (ocuparia a tela toda)
        base.WndProc(ref m);
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Dismiss(); return; }  // Alt+F4: só esconde
        SaveBounds();
        base.OnFormClosing(e);
    }
}
