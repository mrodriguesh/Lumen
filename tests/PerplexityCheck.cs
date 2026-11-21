using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Verificação NATIVA do painel do Perplexity (D185), como o OpenNotebookCheck.cs: compile com os três arquivos do launcher
// usando /target:exe /main:PerplexityCheck, na raiz do projeto, e rode com LUMEN_DATA numa pasta isolada:
//     Lumen.PerplexityCheck.exe [pasta para as capturas]
// Rodar duas vezes com a mesma LUMEN_DATA confere que o perfil webview-perplexity continua lá (persistência).
// Usa o fluxo real da página (/perplexity na caixa de mensagem, o diálogo, “Trazer resposta ao Lúmen”) e o site oficial
// de verdade, sem conta: nenhum script roda na página do Perplexity e nada é clicado nela; só se leem o endereço (Source)
// e a captura da tela pelo próprio WebView2. Downloads, permissões e a ponte são conferidos num site local de teste.
static class PerplexityCheck
{
    const string Query = "C++ & 50% ? açaí #1 / \"aspas\" + 2 = ½";
    static int fails;

    static object Field(object o, string name) { return o.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(o); }
    static void Check(bool ok, string what) { Console.WriteLine((ok ? "ok    " : "FALHA ") + what); if (!ok) fails++; }
    static void Note(string what) { Console.WriteLine("info  " + what); }
    static async Task<string> Js(WebView2 w, string js) { return (await w.ExecuteScriptAsync(js)).Trim('"'); }
    static string Q(string s) { return "'" + s.Replace("\\", "\\\\").Replace("'", "\\'").Replace("\n", "\\n") + "'"; }

    static async Task<bool> Until(WebView2 w, string js, int seconds)
    {
        for (int i = 0; i < seconds * 4; i++)
        {
            try { if (await Js(w, js) == "true") return true; } catch (Exception) { }  // WebView2 ainda iniciando
            await Task.Delay(250);
        }
        return false;
    }

    static async Task<bool> Wait(Func<bool> ok, int seconds)
    {
        for (int i = 0; i < seconds * 10; i++) { if (ok()) return true; await Task.Delay(100); }
        return ok();
    }

    static async Task Shot(WebView2 w, string dir, string name)
    {
        if (dir == null) return;
        Directory.CreateDirectory(dir);
        using (var f = File.Create(Path.Combine(dir, name)))
            await w.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, f);
    }

    [STAThread] static void Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) => Assembly.LoadFrom(Path.Combine(Program.Bin, new AssemblyName(e.Name).Name + ".dll"));
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        typeof(Program).GetMethod("KillChildrenOnExit", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, null);
        if (Environment.GetEnvironmentVariable("LUMEN_DATA") == null) { Console.WriteLine("Uso: LUMEN_DATA=<pasta isolada> Lumen.PerplexityCheck.exe [capturas]"); Environment.ExitCode = 2; return; }
        Run(args.Length > 0 ? args[0] : null);
    }

    static void Run(string shots)  // separado do Main: só aqui os tipos do WebView2 são carregados
    {
        Directory.CreateDirectory(Program.Data);
        File.WriteAllText(Path.Combine(Program.Data, "config.json"), "{\"widget\": \"off\"}");  // sem a barra flutuante durante o teste
        string profile = Path.Combine(Program.Data, "webview-perplexity");
        Note(Directory.Exists(profile) ? "perfil do Perplexity já existia (segunda rodada): " + Directory.GetLastWriteTime(profile) : "perfil do Perplexity ainda não existe (primeira rodada)");
        var main = new MainForm(Path.Combine(Program.Root, ".venv", "Scripts", "pythonw.exe"), false);
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FALHA tempo esgotado"); Environment.Exit(1); }, null, 600000, Timeout.Infinite);
        main.Shown += async (s, e) =>
        {
            try { await Checks(main, shots); }
            catch (Exception ex) { Check(false, "exceção: " + ex); }
            watchdog.Dispose();
            typeof(MainForm).GetField("exiting", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(main, true);
            main.Close();
        };
        Application.Run(main);
        Console.WriteLine(fails == 0 ? "TUDO OK" : fails + " FALHA(S)");
        Environment.ExitCode = fails == 0 ? 0 : 1;
    }

    static void Rules()
    {
        string ok = "https://www.perplexity.ai/search?q=" + Uri.EscapeDataString(Query);
        foreach (var c in new[] {
            Tuple.Create(ok, true), Tuple.Create("https://www.perplexity.ai/", true),
            Tuple.Create("http://www.perplexity.ai/search?q=x", false), Tuple.Create("https://www.perplexity.ai:444/search?q=x", false),
            Tuple.Create("https://www.perplexity.ai.example.com/search?q=x", false), Tuple.Create("https://evil.com/?u=https://www.perplexity.ai/", false),
            Tuple.Create("https://user@www.perplexity.ai/search?q=x", false), Tuple.Create("https://www.perplexity.ai/settings", false),
            Tuple.Create("https://www.perplexity.ai/search?x=1", false), Tuple.Create("javascript:alert(1)", false), Tuple.Create("file:///C:/", false) })
            Check(MainForm.PerplexityStart(c.Item1) == c.Item2, "abrir " + c.Item1 + " → " + (c.Item2 ? "aceito" : "recusado"));
        foreach (var c in new[] {
            Tuple.Create("https://www.perplexity.ai/search/new?q=x", true), Tuple.Create("https://perplexity.ai/", true),
            Tuple.Create("https://accounts.google.com/o/oauth2/v2/auth", true), Tuple.Create("https://appleid.apple.com/auth/authorize", true),
            Tuple.Create("http://www.perplexity.ai/", false), Tuple.Create("https://docs.perplexity.ai/", false),
            Tuple.Create("https://www.perplexity.ai.example.com/", false), Tuple.Create("https://example.com/", false),
            Tuple.Create("https://www.perplexity.ai:8443/", false) })
            Check(MainForm.PerplexitySite(new Uri(c.Item1)) == c.Item2, "dentro do painel: " + c.Item1 + " → " + (c.Item2 ? "sim" : "não"));
    }

    static async Task Checks(MainForm main, string shots)
    {
        Rules();
        var web = (WebView2)Field(main, "web");
        Check(await Until(web, "typeof S !== 'undefined' && !!S && !!window.lumenStudy && !!host", 120), "página do Lúmen na janela nativa, com a ponte do aplicativo");
        string home = await Js(web, "location.origin");
        Check(await Js(web, "/LumenShell\\/3\\b/.test(navigator.userAgent)") == "true", "o Lumen.exe se anuncia como LumenShell/3");

        // codificação da pergunta (a mesma função que o comando usa) e volta exata pelo Uri do .NET
        string url = await Js(web, "lumenStudy.perplexityUrl(" + Q(Query) + ")");  // só caracteres de URL: o JSON não escapa nada
        Uri pu = new Uri(url);
        Check(MainForm.PerplexityStart(url), "o endereço montado pela página passa na conferência do Lumen.exe: " + url);
        Check(pu.Query.StartsWith("?q=") && Uri.UnescapeDataString(pu.Query.Substring(3)) == Query && !pu.Query.Contains("&") && !pu.Query.Contains("#"),
            "a pergunta volta exata (com & % ? # / aspas + ½ e acentos), sem virar outro parâmetro");

        // mensagens falsas da página: nada abre
        await Js(web, "host.postMessage('perplexity:open:https://example.com/search?q=x'); host.postMessage('perplexity:open:https://www.perplexity.ai.example.com/search?q=x'); 0");
        await Task.Delay(800);
        Check(Field(main, "perplexity") == null, "endereços fora do site oficial são ignorados pelo Lumen.exe");

        // /perplexity sem pergunta: o diálogo de colar
        await Js(web, "showView('study'); lumenStudy.setTab('chat'); 0");
        await Task.Delay(800);
        await Js(web, "(() => { const i = lumenStudy.input(); i.value = '/perplexity'; i.form.requestSubmit(); return 0; })()");
        Check(await Until(web, "document.querySelector('dialog.st-dialog[open]')?.getAttribute('aria-label') === 'Trazer resposta do Perplexity'", 10), "/perplexity sem pergunta abre “Trazer resposta do Perplexity”");
        await Js(web, "document.querySelector('dialog.st-dialog[open] .dlg-foot .btn:not(.primary)').click(); 0");

        // Integrações → Perplexity: aba própria, estado, colar no Cérebro; pergunta vazia não abre nada
        await Js(web, "showView('integrations'); integSelect('perplexity'); 0");
        await Task.Delay(600);
        Check(await Js(web, "!document.querySelector('#integ-perplexity').hidden && document.querySelector('#itab-perplexity').getAttribute('aria-selected') === 'true'") == "true", "aba Perplexity nas Integrações");
        Check(await Js(web, "document.querySelector('#px-status').textContent.includes('painel dentro do Lúmen') && document.querySelector('#px-badge').textContent === 'Site oficial'") == "true", "estado: abre no painel (" + await Js(web, "document.querySelector('#px-status').textContent") + ")");
        await Shot(web, shots, "0-integracoes.png");
        await Js(web, "document.querySelector('#integ-perplexity').scrollIntoView({ block: 'start' }); 0");
        await Task.Delay(400);
        await Shot(web, shots, "0b-integracoes-painel.png");
        await Js(web, "document.querySelector('#px-flow, .px-flow').scrollIntoView({ block: 'start' }); 0");
        await Task.Delay(400);
        await Shot(web, shots, "0c-integracoes-fluxo.png");
        var size = main.Size;
        main.Size = new System.Drawing.Size(1600, 1000);  // larga: no estilo Glass, a escolha vira uma lista ao lado
        await Task.Delay(1200);
        await Js(web, "scrollTo(0, 0); document.querySelector('.view:not([hidden]) .integ-page')?.scrollIntoView(); 0");
        await Task.Delay(400);
        await Shot(web, shots, "0d-integracoes-larga.png");
        main.Size = size;
        await Task.Delay(800);
        await Js(web, "document.querySelector('#px-q').value = ''; document.querySelector('#px-search').click(); 0");
        await Task.Delay(800);
        Check(Field(main, "perplexity") == null, "pergunta vazia: nada é aberto");
        await Js(web, "document.querySelector('#px-paste').click(); 0");
        Check(await Until(web, "view === 'study' && document.querySelector('dialog.st-dialog[open]')?.getAttribute('aria-label') === 'Trazer resposta do Perplexity'", 10), "“Colar resposta no Cérebro” leva ao Cérebro com o diálogo de colar");
        await Js(web, "document.querySelector('dialog.st-dialog[open] .dlg-foot .btn:not(.primary)').click(); 0");

        // botão visível na barra da caixa de mensagem: o texto escrito vira a sugestão do diálogo, nada sai sem confirmar
        await Js(web, "lumenStudy.input().value = 'fotossíntese'; 0");
        Check(await Js(web, "(() => { const b = document.querySelector('.st-composer-bar .st-pplx'); return !!b && b.offsetParent !== null && b.getAttribute('aria-label') === 'Pesquisar no Perplexity'; })()") == "true", "botão “Pesquisar no Perplexity” visível na caixa de mensagem dos Estudos");
        await Shot(web, shots, "0-botao.png");
        await Js(web, "document.querySelector('.st-composer-bar .st-pplx').click(); 0");
        Check(await Until(web, "document.querySelector('dialog.st-dialog[open]')?.getAttribute('aria-label') === 'Pesquisar no Perplexity' && document.querySelector('dialog.st-dialog[open] textarea').value === 'fotossíntese'", 10), "o botão abre o diálogo com o texto da caixa, para confirmar");
        await Js(web, "document.querySelector('dialog.st-dialog[open] .dlg-foot .btn:not(.primary)').click(); lumenStudy.input().value = ''; 0");
        Check(Field(main, "perplexity") == null, "cancelar não abre nada");

        // /perplexity <pergunta>: o diálogo diz o que sai e deixa editar
        await Js(web, "(() => { const i = lumenStudy.input(); i.value = '/perplexity ' + " + Q(Query) + "; i.form.requestSubmit(); return 0; })()");
        Check(await Until(web, "document.querySelector('dialog.st-dialog[open]')?.getAttribute('aria-label') === 'Pesquisar no Perplexity'", 10), "/perplexity <pergunta> abre “Pesquisar no Perplexity”");
        Check(await Js(web, "document.querySelector('dialog.st-dialog[open] textarea').value === " + Q(Query)) == "true", "o diálogo mostra a pergunta exata, editável");
        Check(await Js(web, "document.querySelector('dialog.st-dialog[open]').textContent.includes('Só esta pergunta sai do Lúmen')") == "true", "o diálogo avisa que só a pergunta vai ao Perplexity");
        await Shot(web, shots, "1-dialogo-pergunta.png");
        await Js(web, "document.querySelector('dialog.st-dialog[open] .dlg-foot .btn.primary').click(); 0");

        SiteView view = null;
        await Wait(() => (view = (SiteView)Field(main, "perplexity")) != null && view.Visible, 10);
        Check(view != null && view.Visible, "“Abrir no Perplexity” mostra o painel dentro da janela do Lúmen");
        if (view == null) return;
        WebView2 pw = null;
        await Wait(() => (pw = (WebView2)Field(view, "web")) != null && pw.CoreWebView2 != null, 40);
        Check(pw != null && pw.CoreWebView2 != null, "WebView2 do painel iniciado");
        if (pw == null || pw.CoreWebView2 == null) return;
        var core = pw.CoreWebView2;
        var log = new StringBuilder();
        core.NavigationStarting += (s, e) => log.AppendLine("navegar " + (e.IsRedirected ? "(redir) " : "") + (e.IsUserInitiated ? "(usuário) " : "") + e.Uri + (e.Cancel ? "  [cancelada]" : ""));
        core.NewWindowRequested += (s, e) => log.AppendLine("janela nova " + e.Uri);
        core.SourceChanged += (s, e) => log.AppendLine("endereço " + core.Source);

        bool loaded = await Wait(() => (bool)Field(view, "loaded") || ((Label)Field(view, "message")).Visible && !((Label)Field(view, "message")).Text.StartsWith("Abrindo"), 60);
        await Task.Delay(6000);  // o site termina de montar (e talvez de redirecionar)
        var status = (Label)Field(view, "status");
        Note("estado na barra: " + status.Text + " · aviso: " + (((Label)Field(view, "message")).Visible ? ((Label)Field(view, "message")).Text : "(nenhum)"));
        Note("endereço atual: " + core.Source);
        Note("título do documento (API do WebView2): " + core.DocumentTitle);
        await Shot(pw, shots, "2-perplexity.png");
        Check(loaded && (bool)Field(view, "loaded"), "o site oficial carregou no painel (sem conta)");
        Uri at = new Uri(core.Source);
        Check(MainForm.PerplexitySite(at), "o painel está num endereço liberado: " + at.Host);
        string q = System.Text.RegularExpressions.Regex.Match(at.Query, "[?&]q=([^&]*)").Groups[1].Value;
        if (q != "") Check(Uri.UnescapeDataString(q.Replace("+", "%20")) == Query, "a pergunta chegou exata ao site: " + at.PathAndQuery);
        else Note("o site já trocou o endereço (sem q=): " + at.PathAndQuery);

        var set = core.Settings;
        Check(!set.IsWebMessageEnabled && !set.AreHostObjectsAllowed && !set.AreDevToolsEnabled && !set.IsPasswordAutosaveEnabled && !set.IsGeneralAutofillEnabled,
            "sem ponte de mensagens, sem objetos do aplicativo, sem DevTools, sem guardar senha nem preencher formulários");
        string a = Path.GetFullPath(web.CoreWebView2.Environment.UserDataFolder), b = Path.GetFullPath(core.Environment.UserDataFolder);
        Check(a != b && b.Equals(Path.Combine(Path.GetFullPath(Program.Data), "webview-perplexity"), StringComparison.OrdinalIgnoreCase), "perfil próprio, na pasta de dados do Lúmen: " + b);
        Check(!b.Equals(Path.Combine(Path.GetFullPath(Program.Data), "webview-hyperbooklm"), StringComparison.OrdinalIgnoreCase), "perfil separado do HyperbookLM e do Open Notebook");

        // O Navigate do aplicativo conta como gesto do usuário no WebView2: um http(s) de fora iria ao navegador padrão. Aqui só
        // um esquema que nunca sai (file:); o redirecionamento por script e o http(s) de fora são conferidos no site local (Fake).
        core.Navigate("file:///C:/Windows/win.ini");
        await Task.Delay(2500);
        Check(log.ToString().Contains("file:///C:/Windows/win.ini  [cancelada]") && MainForm.PerplexitySite(new Uri(core.Source)) && status.Text.Contains("Bloqueado: file:"),
            "file: bloqueado sem sair do Perplexity (" + status.Text + ")");
        await Task.Delay(15000);  // o tempo de o site responder (ou pedir para entrar) sem conta
        Note("endereço depois de 30 s: " + core.Source);
        await Shot(pw, shots, "2b-perplexity-30s.png");
        Check(await Js(web, "location.origin") == home, "a janela principal continua no Lúmen (" + home + ")");

        // volta ao Lúmen pelo botão da barra e colagem confirmada
        var buttons = (Button[])Field(view, "buttons");
        var bring = buttons.FirstOrDefault(x => x.Text.Contains("Trazer resposta"));
        Check(bring != null && bring.AccessibleName == "Trazer resposta ao Lúmen", "barra com “Trazer resposta ao Lúmen” (nome acessível)");
        await Shot(web, shots, "3-antes-de-voltar.png");
        bring.PerformClick();
        Check(!view.Visible, "o painel some e a página do Lúmen volta como estava");
        Check(await Until(web, "document.querySelector('dialog.st-dialog[open]')?.getAttribute('aria-label') === 'Trazer resposta do Perplexity'", 10), "o Lúmen abre “Trazer resposta do Perplexity”");
        string sample = "O açaí (Euterpe oleracea) é uma palmeira amazônica [1][2].\n\nFontes\n[1] https://pt.wikipedia.org/wiki/A%C3%A7a%C3%AD\n[2] https://www.embrapa.br/busca?q=a%C3%A7a%C3%AD&p=1#topo";
        await Js(web, "(() => { lumenStudy.input().value = ''; document.querySelector('dialog.st-dialog[open] textarea').value = " + Q(sample) + "; return 0; })()");
        await Shot(web, shots, "4-colar.png");
        await Js(web, "document.querySelector('dialog.st-dialog[open] .dlg-foot .btn.primary').click(); 0");
        await Task.Delay(500);
        Check(await Js(web, "(() => { const v = lumenStudy.input().value; return v.startsWith('[Conteúdo do Perplexity colado por mim · não verificado pelo Lúmen]\\n\\n') && v.endsWith(" + Q(sample) + "); })()") == "true",
            "a resposta entra na caixa de mensagem, marcada, com as fontes e os links intactos (nada enviado)");
        Check(await Js(web, "!lumenStudy.S.stream") == "true", "nenhuma mensagem foi enviada sozinha");
        await Shot(web, shots, "5-na-mensagem.png");

        // resposta longa: anexo de texto inteiro, para o corte de 8 000 caracteres não levar as fontes
        await Js(web, "(() => { lumenStudy.input().value = ''; lumenStudy.perplexityPaste(); return 0; })()");
        await Until(web, "!!document.querySelector('dialog.st-dialog[open] textarea')", 10);
        await Js(web, "(() => { document.querySelector('dialog.st-dialog[open] textarea').value = 'x'.repeat(9000) + '\\n[1] https://example.org/fim'; document.querySelector('dialog.st-dialog[open] .dlg-foot .btn.primary').click(); return 0; })()");
        Check(await Until(web, "lumenStudy.S.staged.some((a) => a.name.startsWith('perplexity-') && a.name.endsWith('.md') && a.status !== 'uploading')", 30),
            "resposta longa vira o anexo perplexity-….md (" + await Js(web, "JSON.stringify(lumenStudy.S.staged.map((a) => [a.name, a.status, a.message]))") + ")");
        Check(await Js(web, "lumenStudy.input().value === ''") == "true", "e a caixa de mensagem não recebe o texto cortado");

        // abrir de novo: o mesmo painel, a mesma página, sem recarregar
        int navs = log.Length;
        await Js(web, "host.postMessage('perplexity:open:' + lumenStudy.perplexityUrl(" + Q(Query) + ")); 0");
        await Task.Delay(1500);
        Check(view.Visible && (SiteView)Field(main, "perplexity") == view && log.Length == navs, "abrir a mesma pergunta de novo volta ao painel como estava");
        view.Back();

        // pesquisar pela aba das Integrações: o mesmo painel, com a pergunta do campo
        await Js(web, "showView('integrations'); integSelect('perplexity'); document.querySelector('#px-q').value = 'mitose e meiose'; document.querySelector('#px-search').click(); 0");
        Check(await Wait(() => view.Visible && ((string)Field(view, "target")).EndsWith("/search?q=mitose%20e%20meiose"), 10), "“Pesquisar no Perplexity” das Integrações abre o painel com a pergunta do campo");
        await Task.Delay(4000);
        view.Back();
        Check(await Js(web, "view === 'integrations'") == "true", "voltar leva de novo às Integrações, como estavam");

        await Fake(main, shots);
        Note("perfil: " + string.Join(", ", Directory.GetDirectories(b).Select(Path.GetFileName)));
        Note("navegações observadas no painel:\n" + log);
    }

    // Site local de teste no mesmo tipo de painel (com allow): download, permissões, ponte e redirecionamento por script.
    static async Task Fake(MainForm main, string shots)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        int port = ((IPEndPoint)listener.LocalEndpoint).Port;
        new Thread(() => Serve(listener)) { IsBackground = true }.Start();
        var test = new SiteView(main, false, () => { }, "Teste", "webview-sitetest", u => u.Scheme == "http" && u.Host == "127.0.0.1" && u.Port == port, "Sem resposta em {0}", null);
        main.Controls.Add(test);
        test.Open("http://127.0.0.1:" + port + "/");
        WebView2 tw = null;
        await Wait(() => (bool)Field(test, "loaded") && (tw = (WebView2)Field(test, "web")) != null, 40);
        Check(tw != null, "site local de teste aberto no painel");
        if (tw == null) return;
        var status = (Label)Field(test, "status");
        Note("chrome.webview na página: " + await Js(tw, "(() => { try { window.chrome.webview.postMessage('window:close'); return 'postMessage aceito pela página'; } catch (e) { return 'postMessage recusado: ' + e.message; } })()"));
        await Task.Delay(800);
        Check(main.Visible && test.Visible, "a página não comanda o aplicativo (window:close ignorado; a ponte está desligada)");
        await Js(tw, "window.__geo = ''; navigator.geolocation.getCurrentPosition(() => window.__geo = 'liberada', (e) => window.__geo = 'negada:' + e.code); 0");
        Check(await Until(tw, "window.__geo === 'negada:1'", 10), "localização negada sem pedir ao usuário (" + await Js(tw, "window.__geo") + ")");
        await Js(tw, "window.__n = ''; Notification.requestPermission().then((v) => window.__n = v); 0");
        Check(await Until(tw, "window.__n === 'denied'", 10), "notificações negadas (" + await Js(tw, "window.__n") + ")");
        string dl = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "lumen-perplexity-check.bin");
        await Js(tw, "document.querySelector('#dl').click(); 0");
        await Task.Delay(2500);
        Check(status.Text.Contains("Download bloqueado") && !File.Exists(dl), "download cancelado, com aviso na barra (" + status.Text + ")");
        await Shot(tw, shots, "6-site-teste.png");
        // sem gesto do usuário: script ao carregar a página e HTTP 302 (o ExecuteScript do teste contaria como gesto)
        foreach (var p in new[] { "redir", "302" })
        {
            test.Open("http://127.0.0.1:" + port + "/" + p);
            await Task.Delay(3000);
            Check(new Uri(tw.CoreWebView2.Source).Host == "127.0.0.1" && status.Text.Contains("Bloqueado: example.com"), "redirecionamento sozinho para fora (/" + p + "): bloqueado, com aviso (" + status.Text + ")");
        }
        var msg = (Label)Field(test, "message");  // o 302 levou a própria abertura para fora: o painel avisa em vez de ficar em “Abrindo…”
        Check(msg.Visible && msg.Text.Contains("example.com"), "abertura levada para fora: aviso no painel (" + msg.Text.Replace("\n", " ") + ")");
        test.Back();
        main.Controls.Remove(test);
        listener.Stop();
    }

    static void Serve(TcpListener l)
    {
        try { while (true) { var c = l.AcceptTcpClient(); ThreadPool.QueueUserWorkItem(_ => Answer(c)); } }  // conexões antecipadas não travam as outras
        catch (Exception) { }  // listener parado no fim do teste
    }

    static void Answer(TcpClient client)
    {
        try
        {
            {
                using (var c = client)
                using (var st = c.GetStream())
                {
                    var buf = new byte[4096];
                    int n = st.Read(buf, 0, buf.Length);
                    string req = Encoding.ASCII.GetString(buf, 0, n), path = req.Split(' ').Length > 1 ? req.Split(' ')[1] : "/";
                    byte[] body; string head;
                    if (path == "/file.bin") { body = new byte[] { 1, 2, 3 }; head = "Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename=lumen-perplexity-check.bin"; }
                    else if (path == "/") { body = Encoding.UTF8.GetBytes("<!doctype html><meta charset=utf-8><title>Teste</title><a id=dl href=/file.bin download>baixar</a>"); head = "Content-Type: text/html; charset=utf-8"; }
                    else if (path == "/redir") { body = Encoding.UTF8.GetBytes("<!doctype html><script>location.replace('https://example.com/')</script>"); head = "Content-Type: text/html; charset=utf-8"; }
                    else { body = new byte[0]; head = path == "/302" ? "Location: https://example.com/" : "Content-Type: text/plain"; }
                    string code = path == "/302" ? "302 Found" : body.Length > 0 || path == "/file.bin" ? "200 OK" : "404 Not Found";
                    var h = Encoding.ASCII.GetBytes("HTTP/1.1 " + code + "\r\n" + head + "\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n");
                    st.Write(h, 0, h.Length);
                    st.Write(body, 0, body.Length);
                }
            }
        }
        catch (Exception) { }  // conexão fechada pelo navegador
    }
}
