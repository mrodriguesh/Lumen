using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// A janela flutuante compartilha servidor, perfil e gravação com a janela principal.
class WidgetForm : Form
{
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern int GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool SystemParametersInfo(uint action, uint param, out bool value, uint flags);
    WebView2 web;
    readonly string url, positionFile, dataDir;
    readonly Action<string> command;
    readonly Timer animation = new Timer { Interval = 16 };
    readonly Timer beat = new Timer { Interval = 15000 };  // confere se a página da barra ainda responde
    bool recovering;
    int fails;
    string mode, edge = "left";
    Point anchor;
    bool expanded, dragging;
    float scale = 1;
    int collapsedWidth, collapsedHeight, targetWidth, targetHeight, openHeight;
    // Tamanho do painel aberto (96 dpi): os controles de gravação ou, maior, “Minha compreensão”.
    public static readonly Size MainPanel = new Size(304, 252), NotePanel = new Size(360, 440);
    Size panel = MainPanel;

    public WidgetForm(string url, string data, Action<string> command)
    {
        this.url = url; this.command = command; dataDir = data;
        positionFile = Path.Combine(data, "widget-position.txt");
        Text = "Lumen · barra flutuante";
        FormBorderStyle = FormBorderStyle.None;
        AutoScaleMode = AutoScaleMode.None;
        MaximizeBox = false; MinimizeBox = false;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false; TopMost = true;
        BackColor = Color.FromArgb(14, 14, 16);
        web = NewWeb();
        Controls.Add(web);
        animation.Tick += (s, e) => {
            Size = new Size(Approach(Width, targetWidth), Approach(Height, targetHeight));
            Place(); RoundCorners();
            if (Width == targetWidth && Height == targetHeight) animation.Stop();
        };
        Load += async (s, e) => {
            try { await Attach(); }
            catch (Exception) {
                Hide();
                MessageBox.Show("Não foi possível abrir a barra flutuante. A janela principal e a bandeja continuam disponíveis.", "Lumen", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        };
        beat.Tick += async (s, e) => await Heartbeat();
        beat.Start();
        FormClosed += (s, e) => beat.Stop();
        DpiChanged += (s, e) => {
            e.Cancel = true; animation.Stop(); ResizeForDpi(e.DeviceDpiNew);
            SetAnchor(anchor, Screen.FromHandle(Handle).WorkingArea); Place(); RoundCorners(); SendSide();
        };
        Microsoft.Win32.SystemEvents.DisplaySettingsChanged += DisplayChanged;
    }

    WebView2 NewWeb() { return new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor }; }

    async Task Attach()
    {
        var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dataDir, "webview"));
        await web.EnsureCoreWebView2Async(env);
        var core = web.CoreWebView2;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        core.NavigationStarting += (sender, ev) => { if (!ev.Uri.StartsWith(url, StringComparison.Ordinal)) ev.Cancel = true; };
        core.NewWindowRequested += (sender, ev) => ev.Handled = true;
        core.WebMessageReceived += (sender, ev) => {
            if (!ev.Source.StartsWith(url, StringComparison.Ordinal)) return;
            string msg = ev.TryGetWebMessageAsString();
            if (msg == "widget:expand") Expand(true);
            else if (msg == "widget:collapse") Expand(false);
            else if (msg == "widget:drag") Drag();
            else if (msg == "widget:panel:note" || msg == "widget:panel:main") Panel(msg.EndsWith("note") ? NotePanel : MainPanel);
            else command(msg);
        };
        core.NavigationCompleted += (sender, ev) => SendSide();
        core.ProcessFailed += (sender, ev) => Recover(ev.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited);
        web.Source = new Uri(url + "widget");
    }

    // Se o processo do WebView2 morrer ou a página travar, a barra virava uma faixa morta até reiniciar o Lumen. Agora
    // ela recarrega sozinha; se o navegador inteiro caiu, recria o controle.
    async void Recover(bool recreate)
    {
        if (recovering || IsDisposed) return;
        recovering = true;
        try {
            await Task.Delay(800);
            if (recreate) { Controls.Remove(web); web.Dispose(); web = NewWeb(); Controls.Add(web); await Attach(); }
            else web.CoreWebView2.Reload();
        } catch (Exception) { }
        finally { recovering = false; }
    }

    async Task Heartbeat()
    {
        if (recovering || IsDisposed || !Visible || web.CoreWebView2 == null) return;
        try {
            var t = web.ExecuteScriptAsync("document.body ? 'ok' : ''");
            if (await Task.WhenAny(t, Task.Delay(8000)) != t || t.Result != "\"ok\"") { fails++; Recover(fails >= 2); }
            else fails = 0;
        } catch (Exception) { fails++; Recover(fails >= 2); }
    }

    protected override bool ShowWithoutActivation { get { return true; } }

    void ResizeForDpi(int dpi)
    {
        scale = Math.Max(96, dpi) / 96f;
        Rectangle area = Screen.FromPoint(anchor).WorkingArea;
        Size peek = PeekSize(edge, scale, area);
        collapsedWidth = peek.Width; collapsedHeight = peek.Height;
        openHeight = Math.Min(area.Height, (int)Math.Round(panel.Height * scale));
        targetWidth = expanded ? Math.Min(area.Width, (int)Math.Round(panel.Width * scale)) : collapsedWidth;
        targetHeight = expanded ? openHeight : collapsedHeight;
        Size = new Size(targetWidth, targetHeight);
    }

    public void SetMode(string value)
    {
        if (value == "off") { mode = value; animation.Stop(); Hide(); return; }
        if (mode == value && Visible) return;
        bool changed = mode != null && mode != value;
        animation.Stop(); mode = value; expanded = false;
        edge = value == "top" || value == "bottom" || value == "right" ? value : "left";
        ResizeForDpi(GetDpiForWindow(Handle));
        Rectangle area = Screen.PrimaryScreen.WorkingArea;
        anchor = new Point(mode == "right" ? area.Right - collapsedWidth : area.Left,
                           area.Top + (area.Height - collapsedHeight) / 2);
        if (mode == "top" || mode == "bottom") anchor = new Point(area.Left+(area.Width-collapsedWidth)/2, mode == "top" ? area.Top : area.Bottom-collapsedHeight);
        if (!changed || mode == "free") RestorePosition();
        SetAnchor(anchor, Screen.FromPoint(anchor).WorkingArea);
        Place(); RoundCorners(); SendSide(); Show();
        SavePosition();
    }

    public static Point Clamp(Point point, Size size, Rectangle area)
    {
        return new Point(Math.Max(area.Left, Math.Min(point.X, area.Right - size.Width)),
                         Math.Max(area.Top, Math.Min(point.Y, area.Bottom - size.Height)));
    }

    bool RightSide()
    {
        Rectangle a = Screen.FromPoint(anchor).WorkingArea;
        return anchor.X + collapsedWidth / 2 > a.Left + a.Width / 2;
    }

    void Place()
    {
        Bounds = WidgetBounds(anchor, Size, new Size(collapsedWidth, collapsedHeight), Screen.FromPoint(anchor).WorkingArea);
    }

    public static Rectangle WidgetBounds(Point point, Size size, Size peek, Rectangle area)
    {
        size = new Size(Math.Min(size.Width, area.Width), Math.Min(size.Height, area.Height));
        bool right = point.X + peek.Width / 2 > area.Left + area.Width / 2;
        var p = new Point(peek.Width > peek.Height ? point.X-(size.Width-peek.Width)/2 : right ? point.X + peek.Width - size.Width : point.X, point.Y - (size.Height - peek.Height) / 2);
        return new Rectangle(Clamp(p, size, area), size);
    }

    public static Point SnapAnchor(Point point, Size peek, Rectangle area, int distance)
    {
        point = Clamp(point, peek, area);
        if (point.X - area.Left < distance) point.X = area.Left;
        else if (area.Right - point.X - peek.Width < distance) point.X = area.Right - peek.Width;
        if (point.Y - area.Top < distance) point.Y = area.Top;
        else if (area.Bottom - point.Y - peek.Height < distance) point.Y = area.Bottom - peek.Height;
        return point;
    }

    public static string NearestEdge(Rectangle bounds, Rectangle area, int distance)
    {
        int left = bounds.Width >= area.Width ? int.MaxValue : Math.Max(0,bounds.Left-area.Left);
        int right = bounds.Width >= area.Width ? int.MaxValue : Math.Max(0,area.Right-bounds.Right);
        int top = bounds.Height >= area.Height ? int.MaxValue : Math.Max(0,bounds.Top-area.Top);
        int bottom = bounds.Height >= area.Height ? int.MaxValue : Math.Max(0,area.Bottom-bounds.Bottom);
        int closest = Math.Min(left,right);
        string value = left <= right ? "left" : "right";
        if (top < closest) { closest=top; value="top"; }
        if (bottom < closest) { closest=bottom; value="bottom"; }
        return closest < distance ? value : "free";
    }

    public static Size PeekSize(string dock, float scale, Rectangle area)
    {
        bool horizontal = dock == "top" || dock == "bottom";
        return new Size(Math.Min(area.Width,(int)Math.Round((horizontal ? 84 : 12)*scale)),
                        Math.Min(area.Height,(int)Math.Round((horizontal ? 12 : 84)*scale)));
    }

    static int Approach(int current, int target)
    {
        int delta = target - current;
        return current + Math.Sign(delta) * Math.Max(1, (int)Math.Ceiling(Math.Abs(delta) * .25));
    }

    void SetAnchor(Point point, Rectangle area, string dock = null)
    {
        edge = dock ?? NearestEdge(new Rectangle(point,new Size(collapsedWidth,collapsedHeight)),area,(int)Math.Round(48*scale));
        Size peek = PeekSize(edge,scale,area);
        point.Offset((collapsedWidth-peek.Width)/2,(collapsedHeight-peek.Height)/2);
        collapsedWidth=peek.Width; collapsedHeight=peek.Height;
        anchor = SnapAnchor(point, new Size(collapsedWidth, collapsedHeight), area, (int)Math.Round(48 * scale));
        if (!expanded && !dragging) {
            targetWidth=collapsedWidth; targetHeight=collapsedHeight; Size=peek;
        }
    }

    void Expand(bool value)
    {
        if (dragging || mode == "off") return;
        if (WindowState != FormWindowState.Normal) WindowState = FormWindowState.Normal;
        expanded = value;
        Rectangle area = Screen.FromPoint(anchor).WorkingArea;
        targetWidth = Math.Min(area.Width, value ? (int)Math.Round(panel.Width * scale) : collapsedWidth);
        targetHeight = Math.Min(area.Height, value ? openHeight : collapsedHeight);
        bool animate;
        if (SystemParametersInfo(0x1042, 0, out animate, 0) && !animate) { Size = new Size(targetWidth, targetHeight); Place(); RoundCorners(); return; }
        animation.Start();
    }

    void Panel(Size size)
    {
        if (panel == size) return;
        panel = size;
        openHeight = Math.Min(Screen.FromPoint(anchor).WorkingArea.Height, (int)Math.Round(panel.Height * scale));
        if (expanded) Expand(true);  // cresce (ou volta) para dentro da área útil, a partir da alça
    }

    // O app está saindo: a nota escrita aqui que ainda não foi salva vai agora.
    public async Task Flush()
    {
        if (web.CoreWebView2 != null) { try { await web.ExecuteScriptAsync("window.Notes && Notes.flushAll()"); } catch (Exception) { } }
    }

    void SendSide()
    {
        if (web.CoreWebView2 != null) {
            web.CoreWebView2.PostWebMessageAsString(RightSide() ? "side:right" : "side:left");
            web.CoreWebView2.PostWebMessageAsString("edge:"+edge);
        }
    }

    void Drag()
    {
        animation.Stop(); dragging = true;
        ReleaseCapture();
        SendMessage(Handle, 0x00A1, new IntPtr(2), IntPtr.Zero); // WM_NCLBUTTONDOWN, HTCAPTION
        Rectangle area = Screen.FromHandle(Handle).WorkingArea;
        int snap = (int)Math.Round(48 * scale);
        string dock = NearestEdge(Bounds,area,snap);
        Size peek = PeekSize(dock,scale,area);
        bool horizontal = dock == "top" || dock == "bottom", right = Left+Width/2 > area.Left+area.Width/2;
        var point = new Point(horizontal ? Left+(Width-peek.Width)/2 : right ? Right-peek.Width : Left, Top+(Height-peek.Height)/2);
        if (Top-area.Top < snap) point.Y=area.Top;
        else if (area.Bottom-Bottom < snap) point.Y=area.Bottom-peek.Height;
        point.Offset((peek.Width-collapsedWidth)/2,(peek.Height-collapsedHeight)/2);
        SetAnchor(point,area,dock);
        dragging = false; Expand(false); SendSide(); SavePosition();
    }

    void RoundCorners()
    {
        int d = Math.Min(Math.Min(Width, Height), (int)Math.Round(36 * scale));
        using (var path = new GraphicsPath()) {
            path.AddArc(0, 0, d, d, 180, 90);
            path.AddArc(Width - d, 0, d, d, 270, 90);
            path.AddArc(Width - d, Height - d, d, d, 0, 90);
            path.AddArc(0, Height - d, d, d, 90, 90); path.CloseFigure();
            Region old = Region; Region = new Region(path); if (old != null) old.Dispose();
        }
    }

    void RestorePosition()
    {
        try {
            string[] parts = File.ReadAllText(positionFile).Split('|');
            int x, y;
            bool legacy = parts.Length == 3, oriented = parts.Length == 5 && parts[0] == "v3";
            int start = legacy ? 0 : 1;
            int coordinates = oriented ? 3 : start+1;
            if ((legacy || oriented || (parts.Length == 4 && parts[0] == "v2")) && (parts[start] == mode || mode == "free") &&
                int.TryParse(parts[coordinates], out x) && int.TryParse(parts[coordinates + 1], out y)) {
                if (oriented && (parts[2]=="left" || parts[2]=="right" || parts[2]=="top" || parts[2]=="bottom" || parts[2]=="free")) {
                    edge=parts[2]; Size peek=PeekSize(edge,scale,Screen.FromPoint(new Point(x,y)).WorkingArea);
                    collapsedWidth=peek.Width; collapsedHeight=peek.Height;
                }
                anchor = new Point(x, y + (legacy ? (openHeight - collapsedHeight) / 2 : 0));
                if (legacy && mode != "free") anchor = SnapAnchor(anchor, new Size(collapsedWidth, collapsedHeight), Screen.FromPoint(anchor).WorkingArea, (int)Math.Round(96 * scale));
            }
        } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    void SavePosition()
    {
        try { Directory.CreateDirectory(Path.GetDirectoryName(positionFile)); File.WriteAllText(positionFile, "v3|" + mode + "|" + edge + "|" + anchor.X + "|" + anchor.Y); }
        catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    public void ResetPosition()
    {
        string value = mode;
        try { File.Delete(positionFile); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        mode = "off";
        SetMode(value);
    }

    void DisplayChanged(object sender, EventArgs e)
    {
        if (IsDisposed || !IsHandleCreated) return;
        BeginInvoke((Action)(() => { if (mode != "off") { SetAnchor(anchor, Screen.FromPoint(anchor).WorkingArea); Place(); SendSide(); SavePosition(); } }));
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == 0x0112 && ((long)m.WParam & 0xfff0) == 0xf030) return; // SC_MAXIMIZE não se aplica ao widget
        base.WndProc(ref m);
    }


    protected override void Dispose(bool disposing)
    {
        if (disposing) { animation.Dispose(); Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= DisplayChanged; }
        base.Dispose(disposing);
    }
}
