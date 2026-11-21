using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Verificação NATIVA do Open Notebook (janela real do launcher, WebView2), como o DesktopChecks.cs: compile com os três
// arquivos do launcher usando /target:exe /main:OpenNotebookCheck, na raiz do projeto, e rode com LUMEN_DATA numa pasta
// isolada e o Open Notebook instalado aberto:
//     Lumen.OpenNotebookCheck.exe <id de um caderno de teste | criar> [pasta para as capturas]
// Com os serviços parados, clica antes em “Iniciar Open Notebook” e acompanha a partida (use LUMEN_ON_DATA com um banco
// descartável); “criar” usa o botão do caderno “Lúmen — Transcrições” em vez de um id (só com banco descartável).
// Usa os botões reais da página (conectar, escolher o caderno, “Abrir no Open Notebook”) e confere a janela própria:
// perfil separado, presa à origem configurada, sem ponte com o aplicativo; a principal continua no Lúmen.
// Efeito visível: a tentativa de sair da origem abre uma aba do navegador padrão em <API>/health (é o comportamento real).
static class OpenNotebookCheck
{
    const string Ui = "http://127.0.0.1:3000", Outside = "http://127.0.0.1:5055/health";
    static int fails;

    static object Field(object o, string name) { return o.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(o); }
    static void Check(bool ok, string what) { Console.WriteLine((ok ? "ok    " : "FALHA ") + what); if (!ok) fails++; }
    static async Task<string> Js(WebView2 w, string js) { return (await w.ExecuteScriptAsync(js)).Trim('"'); }

    static async Task<bool> Until(WebView2 w, string js, int seconds)
    {
        for (int i = 0; i < seconds * 4; i++)
        {
            try { if (await Js(w, js) == "true") return true; } catch (Exception) { }  // WebView2 ainda iniciando
            await Task.Delay(250);
        }
        return false;
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
        if (args.Length == 0 || Environment.GetEnvironmentVariable("LUMEN_DATA") == null) { Console.WriteLine("Uso: LUMEN_DATA=<pasta isolada> Lumen.OpenNotebookCheck.exe <id do caderno> [capturas]"); Environment.ExitCode = 2; return; }
        Run(args[0], args.Length > 1 ? args[1] : null);
    }

    static void Run(string book, string shots)  // separado do Main: só aqui os tipos do WebView2 são carregados
    {
        Directory.CreateDirectory(Program.Data);
        File.WriteAllText(Path.Combine(Program.Data, "config.json"), "{\"widget\": \"off\"}");  // sem a barra flutuante durante o teste
        var main = new MainForm(Path.Combine(Program.Root, ".venv", "Scripts", "pythonw.exe"), false);
        var watchdog = new System.Threading.Timer(s => { Console.WriteLine("FALHA tempo esgotado"); Environment.Exit(1); }, null, 900000, System.Threading.Timeout.Infinite);
        main.Shown += async (s, e) =>
        {
            try { await Checks(main, book, shots); }
            catch (Exception ex) { Check(false, "exceção: " + ex.Message); }
            watchdog.Dispose();
            typeof(MainForm).GetField("exiting", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(main, true);
            main.Close();
        };
        Application.Run(main);
        Console.WriteLine(fails == 0 ? "TUDO OK" : fails + " FALHA(S)");
        Environment.ExitCode = fails == 0 ? 0 : 1;
    }

    static async Task Checks(MainForm main, string book, string shots)
    {
        var web = (WebView2)Field(main, "web");
        Check(await Until(web, "typeof S !== 'undefined' && !!S && !!window.lumenON && !!host", 120), "página do Lúmen na janela nativa, com a ponte do aplicativo");
        string home = await Js(web, "location.origin");
        await Js(web, "showView('integrations'); integSelect('opennotebook'); document.querySelector('#on-connect').click(); 0");
        if (await Until(web, "document.querySelector('#on-status').textContent.includes('indisponível') && !document.querySelector('#on-start').hidden", 20))
        {
            Check(true, "serviços parados: a janela nativa oferece “Iniciar Open Notebook” (" + await Js(web, "document.querySelector('#on-local').textContent") + ")");
            Check(await Js(web, "document.querySelector('#on-open').disabled") == "true", "“Abrir no Open Notebook” desabilitado sem a interface");
            await Js(web, "document.querySelector('#on-start').click(); 0");
            Check(await Until(web, "document.querySelector('#on-steps').textContent.includes('iniciando')", 60), "andamento por serviço na janela nativa");
            await Shot(web, shots, "nativo-0-iniciando.png");
        }
        Check(await Until(web, "document.querySelector('#on-status').textContent.includes('Conectado')", 600), "conectado ao Open Notebook instalado pelos botões da página");
        Check(await Until(web, "!document.querySelector('#on-open').disabled", 60), "interface conferida: “Abrir no Open Notebook” habilitado");
        if (book == "criar")
        {
            await Js(web, "document.querySelector('#on-create').click(); 0");
            Check(await Until(web, "document.querySelector('#on-book').value !== ''", 30), "caderno “Lúmen — Transcrições” criado pelo botão");
            book = await Js(web, "document.querySelector('#on-book').value");
        }
        await Js(web, "(() => { const s = document.querySelector('#on-book'); s.value = '" + book + "'; s.dispatchEvent(new Event('change', { bubbles: true })); })()");
        await Task.Delay(1500);
        await Js(web, "window.__on = null; api('/api/opennotebook').then((v) => { window.__on = v.opennotebook_notebook; }); 0");
        Check(await Until(web, "window.__on === '" + book + "'", 15), "caderno de teste escolhido como destino");
        await Shot(web, shots, "nativo-1-lumen.png");

        Check(!Application.OpenForms.OfType<NotebookForm>().Any(), "antes do clique: nenhuma janela do Open Notebook");
        await Js(web, "document.querySelector('#on-open').click(); 0");
        NotebookForm nb = null;
        for (int i = 0; i < 40 && nb == null; i++) { nb = Application.OpenForms.OfType<NotebookForm>().FirstOrDefault(); await Task.Delay(250); }
        Check(nb != null && nb.Visible, "“Abrir no Open Notebook” abriu a janela própria");
        if (nb == null) return;
        var nweb = (WebView2)Field(nb, "web");
        Check(await Until(nweb, "location.origin === '" + Ui + "' && document.readyState === 'complete'", 60), "a janela mostra a interface do Open Notebook");
        await Task.Delay(5000);  // o Next.js termina de montar e redirecionar
        string at = await Js(nweb, "location.href");
        Check(at.StartsWith(Ui + "/notebooks/"), "no caderno escolhido: " + at);
        await Shot(nweb, shots, "nativo-2-open-notebook.png");

        Check(!nweb.CoreWebView2.Settings.IsWebMessageEnabled, "sem ponte de mensagens na janela do Open Notebook");
        await Js(nweb, "(() => { try { window.chrome.webview.postMessage('window:close'); } catch (e) { } return 0; })()");
        await Task.Delay(1000);
        Check(main.Visible && !nb.IsDisposed && nb.Visible, "a página do Open Notebook não comanda o aplicativo (window:close ignorado)");
        string a = Path.GetFullPath(web.CoreWebView2.Environment.UserDataFolder), b = Path.GetFullPath(nweb.CoreWebView2.Environment.UserDataFolder);
        Check(a != b && b.StartsWith(Path.GetFullPath(Program.Data), StringComparison.OrdinalIgnoreCase), "perfil WebView2 separado do Lúmen: " + b);

        await Js(nweb, "location.href = '" + Outside + "'; 0");  // outra origem: cancelada aqui, aberta no navegador padrão
        await Task.Delay(2500);
        string still = await Js(nweb, "location.href");
        Check(still.StartsWith(Ui + "/"), "navegação para outra origem cancelada (continua em " + still + ")");
        Check(await Js(web, "location.origin") == home && home.StartsWith("http://127.0.0.1:"), "a janela principal continua no Lúmen (" + home + ")");

        await Js(web, "document.querySelector('#on-open').click(); 0");
        await Task.Delay(1500);
        Check(Application.OpenForms.OfType<NotebookForm>().Count() == 1, "abrir de novo reaproveita a mesma janela");
    }
}
