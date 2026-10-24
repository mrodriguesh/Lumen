"""QA da interface com API simulada; usa o Chrome instalado e não toca nos dados reais."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit, parse_qs

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "tests" / "desktop-artifacts"
ART.mkdir(exist_ok=True)
env = {**os.environ, "LUMEN_DATA": tempfile.mkdtemp(prefix="lumen-widget-ui-")}
proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c",
                         "from lumen import server; h=server.serve(); print(h.server_port,flush=True); h.serve_forever()"],
                        cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
try:
    url = "http://127.0.0.1:" + proc.stdout.readline().strip()
    cfg = dict(root_page_id="", root_page_title="", quality="equilibrado", ollama_model="qwen3:8b",
               page_language="pt", keep_temp=False, widget="left", autostart=True, destinations="notion", watch_screen=False,
               music_filter=False, music_mode="balanceado", study_level="balanceado", obsidian_vault="", obsidian_folder="",
               obsidian_canvas_folder="", obsidian_canvas=True, obsidian_connections=True, obsidian_review=True,
               obsidian_attachments=True, obsidian_open=False, review_intervals=[1, 3, 7])
    recording = {"active": False, "seconds": 0, "level": 0, "heard": False}
    job = {"status": "idle", "review": False}
    counters = {"start": 0, "stop": 0}
    reject = [False]
    settings_error = [None]
    settings_requests = []
    has_token = [False]
    downloads = []
    clears = []
    history = [{"title":"Aula anterior","course":"Curso","created":"2026-10-10T10:00:00","url":"https://www.notion.so/test"}]
    errors = []
    def route(r):
        path = urlsplit(r.request.url).path
        compact = parse_qs(urlsplit(r.request.url).query).get("view") == ["settings"]
        body = r.request.post_data_json if r.request.method == "POST" else {}
        code = 200
        if settings_error[0] == ("load" if r.request.method == "GET" else "save") and (compact or path in ("/api/state","/api/notion/pages","/api/download","/api/clear")):
            r.fulfill(status=400,content_type="application/json",body=json.dumps({"error":{"message":"Não foi possível salvar os ajustes.","action":"Tente novamente."}})); return
        if path == "/api/widget" and compact:
            data = {"config": cfg,"has_token":has_token[0]}
        elif path == "/api/state":
            data = {"config": cfg, "has_token": has_token[0], "gpu": False,
                    "whisper": {"active": cfg["quality"], "models": {k:{"label":label,"name":"small","size":"500 MB","downloaded":k=="equilibrado"} for k,label in (("rapido","Rápido"),("equilibrado","Equilibrado"),("maximo","Maior precisão"))}},
                    "ollama": {"running": True, "installed": cfg["ollama_model"]=="qwen3:8b", "models": ["qwen3:8b"]},
                    "sources": {k: {"id": "ok", "label": "Compatível"} for k in ("recording", "file", "youtube", "telegram")},
                    "formats": {".wav": "WAV"}, "covers": {"ready": False, "label": "Gerador", "size": "1 GB"},
                    "job": job, "recording": recording, "pending": [], "images": [".png"],
                    "vision": {"model": "qwen3.5:4b", "size": "3,3 GB", "installed": True}, "music": {"ready": False, "size": "72 MB"},
                    "obsidian": {"vaults": [], "folder": "", "error": None}}
        elif path == "/api/widget": data = {"recording": recording, "job": job}
        elif path == "/api/record": data = recording
        elif path == "/api/record/start":
            counters["start"] += 1
            if reject[0]: code, data = 400, {"error": {"message": "Saída de áudio indisponível.", "action": "Conecte um fone."}}
            else:
                recording.update(active=True, seconds=12, level=.3, heard=True)
                data = recording
        elif path == "/api/record/stop":
            counters["stop"] += 1; recording.update(active=False)
            data = {"path": "C:/teste/Aula.wav", "name": "Aula.wav", "warning": None}
        elif path == "/api/inspect": data = {"title": "Aula", "label": "Gravação", "duration": 12, "needs_transcription": True, "whisper_ready": True}
        elif path == "/api/settings":
            settings_requests.append(body)
            if body.get("notion_token"): has_token[0]=True
            if "root_page" in body: cfg.update(root_page_id=body["root_page"],root_page_title=body["root_page_title"])
            cfg.update({k:v for k,v in body.items() if k in cfg})
            if compact:
                r.fulfill(status=200,content_type="application/json",body=json.dumps({"config":cfg,"has_token":has_token[0]})); return
            # A mesma resposta de /api/state, mantendo o cenário de teste.
            r.fulfill(status=200, content_type="application/json", body=json.dumps(state_response)); return
        elif path == "/api/notion/pages": data={"pages":[{"id":"root-1","title":"Cursos","path":"Cursos","top":True},{"id":"root-2","title":"<img src=x>","path":"Cursos / <img src=x>","top":False}]}
        elif path == "/api/courses": data={"courses":[],"root_ok":True,"root":cfg["root_page_id"]}
        elif path == "/api/history": data={"items":history}
        elif path == "/api/download":
            downloads.append(body); job.update(status="running",detail="Baixando modelo",progress=.25); data=job
        elif path == "/api/clear":
            clears.append(body)
            if recording["active"]: code,data=400,{"error":{"message":"Há uma gravação em andamento."}}
            else:
                if body.get("forget_token"): has_token[0]=False; cfg.update(root_page_id="",root_page_title="")
                data={**state_response,"has_token":has_token[0],"config":cfg}
        else: data = {}
        if path == "/api/state":
            globals()["state_response"] = data
        r.fulfill(status=code, content_type="application/json", body=json.dumps(data))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 304, "height": 252}, device_scale_factor=2)
        context.add_init_script("window.messages=[]; window.hostListeners=[]; window.chrome.webview={postMessage:m=>messages.push(m),addEventListener:(type,fn)=>hostListeners.push(fn)};")
        context.route("**/api/**", route)
        widget = context.new_page(); widget.on("pageerror", lambda e: errors.append(str(e)))
        widget.goto(url + "/widget")
        widget.wait_for_function("() => state !== null")
        widget.mouse.move(100, 100)
        widget.wait_for_function("() => document.body.dataset.expanded === 'true'")
        widget.evaluate("hostListeners.forEach(fn=>fn({data:'widget:hidden'}))")
        assert widget.evaluate("document.body.dataset.expanded === 'true'")
        widget.evaluate("document.body.dataset.expanded='false'")
        assert widget.locator("#peek").bounding_box()["width"] == 12
        assert widget.locator("#peek").bounding_box()["height"] == 84
        widget.evaluate("syncPresentation()")
        widget.evaluate("pending=true")
        # Parado, o botão de gravar fica em repouso (nada pisca na tela enquanto se estuda); gravando, o halo pulsa
        assert widget.locator(".record-symbol").evaluate("n=>n.getAnimations().length") == 0
        assert widget.locator("#action").evaluate("n=>['::before','::after'].every(p=>getComputedStyle(n,p).animationName==='none')")
        widget.evaluate("pending=false")
        widget.screenshot(path=str(ART / "widget-expanded.png"), animations="disabled")
        widget.locator("#exit").click()
        assert widget.evaluate("messages.filter(m=>m==='window:exit').length") == 1
        assert widget.locator("#exit").get_attribute("aria-label") == "Sair do Lumen"
        assert widget.locator("#exit").get_attribute("title") is None
        assert widget.locator("#exit svg use").get_attribute("href").endswith("#power"), "Sair é o ícone de desligar, não uma bolinha vermelha"
        widget.locator("#action").click()
        widget.wait_for_function("() => document.body.dataset.state === 'live'")
        assert widget.locator("#time").inner_text() == "00:12"
        widget.screenshot(path=str(ART / "widget-recording.png"), animations="disabled")
        widget.locator("#action").click()
        widget.wait_for_function("() => messages.some(m => m.startsWith('record:ready:'))")
        payload = widget.evaluate("JSON.parse(messages.find(m=>m.startsWith('record:ready:')).slice(13))")
        assert payload["file"]["name"] == "Aula.wav"
        assert counters == {"start": 1, "stop": 1}
        reject[0] = True
        widget.locator("#action").click()
        widget.wait_for_function("() => document.body.dataset.state === 'error'")
        widget.wait_for_timeout(1200)
        assert "Conecte um fone" in widget.locator("#detail").inner_text()
        assert widget.locator("#action").is_enabled()
        reject[0] = False
        widget.evaluate("hostListeners.forEach(fn=>fn({data:'side:right'}))")
        widget.evaluate("document.querySelector('#action').focus(); document.documentElement.dispatchEvent(new PointerEvent('pointerleave'))")
        widget.wait_for_function("() => messages.includes('widget:collapse')")
        widget.set_viewport_size({"width": 12, "height": 84})
        widget.wait_for_function("() => document.body.dataset.expanded === 'false'")
        widget.mouse.move(400, 400)
        widget.screenshot(path=str(ART / "widget-right-peek.png"))
        assert widget.locator("#action").is_hidden()
        assert widget.locator("#peek").is_visible()
        bounds = widget.locator("#peek").bounding_box()
        assert bounds["x"] == 0 and bounds["width"] == 12
        widget.mouse.move(6, 42)
        widget.set_viewport_size({"width": 304, "height": 252})
        widget.wait_for_function("() => document.body.dataset.expanded === 'true'")
        for edge in ("top", "bottom"):
            widget.evaluate("errorUntil=0;render(state)")
            widget.evaluate("edge=>hostListeners.forEach(fn=>fn({data:'edge:'+edge}))", edge)
            widget.set_viewport_size({"width": 84, "height": 12})
            widget.mouse.move(400,400)
            widget.wait_for_function("() => document.body.dataset.expanded === 'false'")
            b=widget.locator("#peek").bounding_box()
            assert b["width"]==84 and b["height"]==12 and b["x"]==0 and b["y"]==0
            widget.screenshot(path=str(ART / f"widget-{edge}-peek.png"))
            widget.mouse.move(42,6)
            widget.set_viewport_size({"width":304,"height":252})
            widget.wait_for_function("() => document.body.dataset.expanded === 'true'")
            for selector in ("#settings", "#open", "#action", "#exit", "#drag"):
                b=widget.locator(selector).bounding_box()
                assert b and b["x"]>=0 and b["y"]>=0 and b["x"]+b["width"]<=304 and b["y"]+b["height"]<=252, (edge,selector,b)
            widget.screenshot(path=str(ART / f"widget-{edge}-expanded.png"), animations="disabled")
        for edge in ("left", "right", "top", "bottom"):
            widget.evaluate("edge=>{pending=true; hostListeners.forEach(fn=>fn({data:'edge:'+edge})); hostListeners.forEach(fn=>fn({data:'side:'+(edge==='right'?'right':'left')}));}", edge)
            scenarios = [
                {"active": False, "seconds": 0, "heard": False},
                {"active": True, "seconds": 0, "heard": False},
                {"active": True, "seconds": 3722, "heard": True, "level": .3},
                {"active": False, "seconds": 0, "heard": False, "error": "A saída de áudio foi desconectada. Confira o fone ou alto-falante e tente novamente."},
            ]
            for index, rec in enumerate(scenarios):
                widget.evaluate("rec=>render({recording:rec,job:{status:'idle',review:false}})", rec)
                assert widget.locator("[title]").count()==0, "Barra flutuante sem tooltips em todos os estados"
                pulse = widget.locator("#action").evaluate("n=>['::before','::after'].map(p=>getComputedStyle(n,p).animationName)")
                assert pulse == (["none","live-halo"] if rec["active"] else ["none","none"])
                assert widget.locator(".record-symbol").evaluate("n=>getComputedStyle(n).animationName") == "none"
                for selector in ("#action", "#settings", "#open", "#exit", "#drag"):
                    b=widget.locator(selector).bounding_box()
                    assert b and b["x"]>=0 and b["y"]>=0 and b["x"]+b["width"]<=304 and b["y"]+b["height"]<=252, (edge,index,selector,b)
                action = widget.locator("#action").bounding_box()
                rail = widget.locator(".rail").bounding_box()
                # Gravar fica no centro da barra de ícones, nas quatro orientações.
                assert action["width"] == action["height"]
                for axis, size in (("x", "width"), ("y", "height")):
                    assert abs(action[axis] + action[size]/2 - (rail[axis] + rail[size]/2)) < 1
                axis, size = ("x", "width") if edge in ("top", "bottom") else ("y", "height")
                brand = widget.locator("#open").bounding_box()
                settings = widget.locator("#settings").bounding_box()
                centers = [b[axis]+b[size]/2 for b in (brand,action,settings)]
                assert abs((centers[1]-centers[0])-(centers[2]-centers[1])) < 1, "Espaçamento simétrico entre os três controles"
                assert 44 <= centers[1]-centers[0] <= 60, "Grupo compacto sem sobreposição"
                assert widget.locator("#action").get_attribute("aria-label") == ("Parar e usar gravação" if rec["active"] else "Iniciar gravação")
                for selector in ("#open", "#settings", "#drag"):
                    other = widget.locator(selector).bounding_box()
                    assert action["x"]+action["width"] <= other["x"] or other["x"]+other["width"] <= action["x"] or action["y"]+action["height"] <= other["y"] or other["y"]+other["height"] <= action["y"], (edge, selector, "controles sobrepostos")
                if index in (1,3): assert widget.locator("#detail").is_visible()
                if index != 3:
                    time = widget.locator("#time").bounding_box()
                    wave = widget.locator(".wave").bounding_box()
                    panel = widget.locator("#recording-panel").bounding_box()
                    assert wave["y"] >= time["y"]+time["height"], (edge, "onda abaixo do contador")
                    assert abs(wave["x"]+wave["width"]/2 - (time["x"]+time["width"]/2)) < 1
                    assert wave["x"] >= panel["x"] and wave["x"]+wave["width"] <= panel["x"]+panel["width"]
                    assert wave["y"]+wave["height"] <= panel["y"]+panel["height"]
                    assert widget.locator("#job").is_hidden()
                    assert wave["y"]+wave["height"] <= widget.locator("footer").bounding_box()["y"]
                    assert widget.locator("#exit").inner_text()==""
                    heights = widget.locator(".wave i").evaluate_all("nodes=>nodes.map(n=>parseFloat(n.style.height))")
                    assert len(heights)==29 and all(2 <= h <= 32 for h in heights)
                    assert max(heights)>2 if index==2 else all(h==2 for h in heights)
                if index==2:
                    assert widget.locator("#time").inner_text()=="01:02:02"
                    assert widget.locator("#time").evaluate("n=>n.scrollWidth<=n.clientWidth+1")
                if index==0: widget.screenshot(path=str(ART / f"minimal-{edge}.png"),animations="disabled")
                if index==2: widget.screenshot(path=str(ART / f"audio-{edge}.png"),animations="disabled")
            widget.evaluate("pending=false")
        widget.evaluate("pending=true")
        for job_state in ({"status":"running","detail":"Transcrevendo","progress":.5}, {"status":"idle","review":True}, {"status":"idle","review":False}):
            widget.evaluate("job=>render({recording:{active:false},job})", job_state)
            assert widget.locator("[title]").count()==0
            if job_state["status"]=="running":
                assert widget.locator("#job").is_visible() and "50%" in widget.locator("#job").inner_text()
            elif job_state["review"]:
                assert widget.locator("#job").is_visible() and "compreensão" in widget.locator("#job").inner_text()
            else:
                assert widget.locator("#job").is_hidden()
        heights = []
        for level, seconds in ((0,1), (.001,1), (1,1), (1,1.25)):
            widget.evaluate("([level,seconds])=>render({recording:{active:true,heard:true,level,seconds},job:{status:'idle'}})", [level,seconds])
            heights.append(widget.locator(".wave i").evaluate_all("nodes=>nodes.map(n=>parseFloat(n.style.height))"))
        assert max(heights[0])==2 and max(heights[1])<max(heights[2])<=32
        assert heights[2] != heights[3], "A onda se move com as atualizações do áudio"
        widget.emulate_media(reduced_motion="reduce")
        assert widget.locator(".wave i").first.evaluate("n=>getComputedStyle(n).transitionDuration") == "0s"
        assert widget.locator("#action").evaluate("n=>['::before','::after'].every(p=>getComputedStyle(n,p).animationName==='none')")
        assert widget.locator(".record-symbol").evaluate("n=>getComputedStyle(n).animationName") == "none"
        widget.emulate_media(reduced_motion="no-preference")
        widget.evaluate("pending=false")
        recording.update(active=True,seconds=12,heard=True,level=.3)
        recorder_calls = counters.copy()
        widget.evaluate("render({recording:{active:true,seconds:12,heard:true,level:.3},job:{status:'idle'}})")
        for edge in ("left","right","top","bottom"):
            widget.evaluate("edge=>{hostListeners.forEach(fn=>fn({data:'edge:'+edge}));hostListeners.forEach(fn=>fn({data:'side:'+(edge==='right'?'right':'left')}));}", edge)
            widget.locator("#settings").click()
            widget.wait_for_function("() => !settingsBusy && preferences !== null")
            assert widget.locator("#preferences").is_visible() and widget.locator("#recording-panel").is_hidden()
            assert widget.locator("#settings").get_attribute("aria-expanded")=="true"
            assert widget.evaluate("messages.includes('window:settings')")==False
            for selector in ("[data-category=desktop]","[data-category=privacy]"):
                b=widget.locator(selector).bounding_box()
                assert b and b["y"]+b["height"]<=252, (edge,selector,b)
            widget.screenshot(path=str(ART/f"preferences-menu-{edge}.png"),animations="disabled")
            widget.locator("[data-category=desktop]").click()
            assert widget.locator(f'[data-position="{edge}"]').get_attribute("aria-pressed")=="true"
            for selector in ("#prefs-back","[data-position=left]","[data-position=free]","#prefs-autostart","#prefs-reset"):
                widget.locator(selector).scroll_into_view_if_needed()
                b=widget.locator(selector).bounding_box()
                assert b and b["x"]>=0 and b["y"]>=0 and b["x"]+b["width"]<=304 and b["y"]+b["height"]<=252, (edge,selector,b)
            assert widget.locator("[title]").count()==0
            widget.screenshot(path=str(ART/f"preferences-{edge}.png"),animations="disabled")
            widget.locator("#prefs-back").click()
            assert widget.locator("nav[data-page=menu]").is_visible()
            widget.locator("#prefs-back").click()
            assert widget.locator("#recording-panel").is_visible()
        widget.locator("#settings").click()
        widget.wait_for_function("() => !settingsBusy && preferences !== null")
        widget.locator("[data-category=desktop]").click()
        for position in ("right","top","bottom","free","left"):
            widget.locator(f'[data-position="{position}"]').click()
            widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').textContent==='Salvo'")
            assert cfg["widget"]==position
            assert widget.evaluate("position=>messages.includes('desktop:prefs:'+position)", position)
        widget.locator("#prefs-autostart").click()
        widget.wait_for_function("() => !settingsBusy && preferences.autostart===false")
        assert cfg["autostart"]==False and widget.locator("#prefs-autostart").get_attribute("aria-checked")=="false"
        settings_error[0]="save"
        widget.locator("#prefs-autostart").click()
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        assert cfg["autostart"]==False and widget.locator("#prefs-autostart").is_enabled()
        assert widget.locator("#prefs-feedback").is_visible()
        settings_error[0]=None
        saved_count=len(settings_requests)
        widget.evaluate("()=>{savePreferences({autostart:true});savePreferences({autostart:true});}")
        widget.wait_for_function("() => !settingsBusy && preferences.autostart===true")
        assert len(settings_requests)==saved_count+1
        widget.keyboard.press("Escape")
        assert widget.locator("nav[data-page=menu]").is_visible()
        widget.locator("[data-category=privacy]").click()
        assert widget.locator("#prefs-clear").is_disabled() and widget.locator("#prefs-forget").is_disabled()
        widget.locator("#prefs-keep").click()
        widget.wait_for_function("() => !settingsBusy && preferences.keep_temp===true")
        widget.locator("#prefs-language").select_option("original")
        widget.wait_for_function("() => !settingsBusy && preferences.page_language==='original'")
        widget.keyboard.press("Escape")
        widget.keyboard.press("Escape")
        assert widget.locator("#preferences").is_hidden()
        settings_error[0]="load"
        widget.locator("#settings").click()
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        assert widget.locator("#prefs-autostart").is_disabled()
        settings_error[0]=None
        widget.keyboard.press("Escape")
        assert counters==recorder_calls and recording["active"], "Ajustes preservam a gravação em andamento"
        recording.update(active=False)
        widget.evaluate("render({recording:{active:false},job:{status:'idle'}})")
        widget.locator("#settings").click()
        widget.wait_for_function("() => !settingsBusy && preferences !== null")
        for edge in ("left","right","top","bottom"):
            widget.evaluate("edge=>{hostListeners.forEach(fn=>fn({data:'edge:'+edge}));hostListeners.forEach(fn=>fn({data:'side:'+(edge==='right'?'right':'left')}));}",edge)
            for category in ("notion","transcription","ai","covers","privacy"):
                widget.locator(f'[data-category="{category}"]').click()
                widget.wait_for_function("() => !settingsBusy")
                controls=widget.locator(f'[data-page="{category}"] :is(input:not([name="prefs-quality"]),select,button,a), [data-page="{category}"] .quality-picker label')
                for control in controls.all():
                    if not control.is_visible(): continue
                    control.scroll_into_view_if_needed()
                    b=control.bounding_box()
                    assert b and b["x"]>=0 and b["x"]+b["width"]<=304 and b["y"]>=0 and b["y"]+b["height"]<=252,(edge,category,b)
                assert widget.evaluate("document.querySelector('#preferences').getBoundingClientRect().bottom<=252")
                widget.screenshot(path=str(ART/f"preferences-{category}-{edge}.png"),animations="disabled")
                widget.keyboard.press("Escape")
        widget.locator("[data-category=transcription]").click()
        widget.wait_for_function("() => !settingsBusy")
        widget.keyboard.press("Escape")
        settings_error[0]="load"
        widget.locator("[data-category=transcription]").click()
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        settings_error[0]=None
        widget.keyboard.press("Escape")
        widget.locator("[data-category=transcription]").click()
        widget.wait_for_function("() => !settingsBusy")
        assert widget.locator("#prefs-quality select").count()==0
        assert widget.locator('#prefs-quality input[value="equilibrado"]').is_checked()
        settings_error[0]="save"
        widget.locator('#prefs-quality label').filter(has_text="Maior precisão").click()
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        assert widget.locator('#prefs-quality input[value="equilibrado"]').is_checked()
        settings_error[0]=None
        widget.locator('#prefs-quality label').filter(has_text="Rápido").click()
        widget.wait_for_function("() => !settingsBusy && preferences.quality==='rapido'")
        assert widget.locator('#prefs-quality input[value="rapido"]').is_checked()
        widget.locator('#prefs-quality input[value="rapido"]').focus()
        widget.keyboard.press("ArrowRight")
        widget.wait_for_function("() => !settingsBusy && preferences.quality==='equilibrado'")
        assert widget.locator('#prefs-quality input[value="equilibrado"]').is_checked()
        assert widget.locator('#prefs-quality input[value="equilibrado"]').evaluate("n=>n===document.activeElement")
        widget.keyboard.press("ArrowRight")
        widget.wait_for_function("() => !settingsBusy && preferences.quality==='maximo'")
        assert widget.locator("#prefs-whisper-dl").is_visible()
        widget.locator("#prefs-whisper-dl").click()
        widget.wait_for_function("() => !settingsBusy && downloading")
        assert downloads[-1]=={"what":"whisper","quality":"maximo"}
        assert widget.locator("#prefs-whisper-dl").is_disabled()
        widget.evaluate("renderSettingsJob({status:'running',detail:'Baixando modelo',progress:.5})")
        assert "50%" in widget.locator("#prefs-feedback").inner_text()
        job.update(status="error",error={"message":"Download interrompido.","action":"Tente novamente."})
        widget.evaluate("renderSettingsJob({status:'error',error:{message:'Download interrompido.',action:'Tente novamente.'}})")
        assert "interrompido" in widget.locator("#prefs-feedback").inner_text()
        assert widget.locator("#prefs-whisper-dl").is_enabled()
        job.update(status="idle")
        widget.keyboard.press("Escape")
        widget.locator("[data-category=ai]").click()
        widget.wait_for_function("() => !settingsBusy")
        widget.locator("#prefs-model").fill("")
        widget.locator("#prefs-model-save").click()
        assert widget.locator("#prefs-feedback").get_attribute("data-error")=="true"
        widget.locator("#prefs-model").fill("qwen3:4b")
        widget.locator("#prefs-model-save").click()
        widget.wait_for_function("() => !settingsBusy && preferences.ollama_model==='qwen3:4b'")
        widget.locator("#prefs-ollama-dl").click()
        widget.wait_for_function("() => !settingsBusy && downloading")
        assert downloads[-1]["what"]=="ollama"
        job.update(status="done")
        widget.evaluate("renderSettingsJob({status:'done'})")
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').textContent==='Download concluído'")
        job.update(status="idle")
        widget.locator(".prefs-link").click()
        assert widget.evaluate("messages.includes('window:external:https://ollama.com/download')")
        widget.keyboard.press("Escape")
        widget.locator("[data-category=covers]").click()
        widget.wait_for_function("() => !settingsBusy")
        settings_error[0]="save"
        widget.locator("#prefs-covers-dl").click()
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        assert widget.locator("#prefs-covers-dl").is_enabled()
        settings_error[0]=None
        widget.locator("#prefs-covers-dl").click()
        widget.wait_for_function("() => !settingsBusy && downloading")
        assert downloads[-1]["what"]=="covers"
        job.update(status="done")
        widget.evaluate("renderSettingsJob({status:'done'})")
        widget.wait_for_function("() => !settingsBusy && !downloading")
        job.update(status="idle")
        widget.keyboard.press("Escape")
        widget.locator("[data-category=notion]").click()
        widget.locator("#prefs-token").fill("fake-test-token")
        widget.locator("#prefs-token-save").click()
        widget.wait_for_function("() => !settingsBusy && hasToken && document.querySelector('#prefs-root').options.length===3")
        assert widget.locator("#prefs-token").input_value()==""
        assert widget.locator("#prefs-root img").count()==0
        widget.locator("#prefs-root").select_option("root-1")
        widget.wait_for_function("() => !settingsBusy && preferences.root_page_id==='root-1'")
        settings_error[0]="save"
        widget.locator("#prefs-root").select_option("root-2")
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        assert widget.locator("#prefs-root").input_value()=="root-1"
        settings_error[0]=None
        widget.keyboard.press("Escape")
        widget.locator("[data-category=privacy]").click()
        widget.locator("#prefs-clear").click()
        widget.locator("#prefs-cancel").click()
        assert not clears
        widget.locator("#prefs-clear").click()
        settings_error[0]="save"
        widget.locator("#prefs-confirm").click()
        widget.wait_for_function("() => !settingsBusy && document.querySelector('#prefs-feedback').dataset.error==='true'")
        assert widget.locator("#prefs-confirm").is_enabled()
        settings_error[0]=None
        widget.locator("#prefs-confirm").click()
        widget.wait_for_function("() => !settingsBusy && settingsPage==='privacy'")
        assert clears==[{"forget_token":False}]
        widget.locator("#prefs-forget").click()
        widget.locator("#prefs-confirm").click()
        widget.wait_for_function("() => !settingsBusy && !hasToken")
        assert clears[-1]=={"forget_token":True} and cfg["root_page_id"]==""
        widget.keyboard.press("Escape")
        widget.locator("[data-category=desktop]").click()
        widget.locator("#prefs-off").click()
        widget.wait_for_function("() => !settingsBusy && preferences.widget==='off'")
        assert widget.evaluate("messages.includes('desktop:prefs:off')")
        cfg.update(widget="left",quality="equilibrado")
        main = context.new_page(); main.on("pageerror", lambda e: errors.append(str(e)))
        main.set_viewport_size({"width": 1120, "height": 860})
        main.goto(url + "/?frame=1")
        try: main.wait_for_function("() => S !== null && messages.includes('desktop:prefs:left')", timeout=8000)
        except Exception: raise AssertionError((errors, main.evaluate("document.querySelector('#toast').textContent")))
        main.locator("#nav-library").click()
        main.locator("#library-list .lib-title").first.wait_for()
        history.clear()
        main.evaluate("hostListeners.forEach(fn=>fn({data:'desktop:preferences-updated'}))")
        main.wait_for_function("() => document.querySelector('#library-list').textContent.includes('Nenhuma aula ainda')")
        main.locator("#nav-new").click()
        cfg["autostart"]=False
        main.evaluate("hostListeners.forEach(fn=>fn({data:'desktop:preferences-updated'}))")
        main.wait_for_function("() => S.config.autostart===false")
        assert not main.locator("#autostart").is_checked()
        has_token[0]=True
        cfg.update(root_page_id="root-1",root_page_title="Cursos")
        main.evaluate("hostListeners.forEach(fn=>fn({data:'desktop:preferences-updated'}))")
        main.wait_for_function("() => S.has_token && document.querySelector('#root').value==='root-1'")
        has_token[0]=False
        cfg.update(root_page_id="",root_page_title="")
        main.evaluate("hostListeners.forEach(fn=>fn({data:'desktop:preferences-updated'}))")
        main.wait_for_function("() => !S.has_token && document.querySelector('#root').value===''")
        cfg["autostart"]=True
        main.evaluate("hostListeners.forEach(fn=>fn({data:'desktop:preferences-updated'}))")
        main.wait_for_function("() => S.config.autostart===true")
        assert main.locator(".light svg").count()==0
        for command in ("close", "minimize", "maximize"):
            control = main.locator(f'[data-window="{command}"]')
            control.hover()
            assert control.inner_text()==""
            control.click()
            assert main.evaluate("command=>messages.includes('window:'+command)", command)
        main.screenshot(path=str(ART / "main-window-controls.png"),animations="disabled")
        main.locator("#open-settings").click()
        assert main.locator("#view-settings").is_visible() and main.locator("#widget-position").is_visible()
        assert main.locator("#autostart").is_checked()
        main.locator("#widget-position").select_option("right")
        main.wait_for_function("() => messages.includes('desktop:prefs:right')")
        for edge in ("top", "bottom"):
            main.locator("#widget-position").select_option(edge)
            main.wait_for_function("edge => messages.includes('desktop:prefs:'+edge)", arg=edge)
        main.locator("#widget-reset").click()
        assert main.evaluate("messages.includes('widget:reset')")
        main.locator("#autostart").uncheck()
        main.wait_for_function("() => S.config.autostart === false")
        main.screenshot(path=str(ART / "settings.png"))
        main.locator("#nav-new").click()
        main.evaluate("data=>hostListeners.forEach(fn=>fn({data:'record:ready:'+JSON.stringify(data)}))", payload)
        main.wait_for_function("() => picked.recording?.name === 'Aula.wav'")
        main.wait_for_function("() => found?.title === 'Aula'")
        assert main.locator("#rec-start-label").inner_text() == "Gravar de novo"
        assert "Gravação pronta" in main.locator("#rec-hint").inner_text()
        assert not errors, errors
        browser.close()
    print("OK: alças horizontais/verticais, painéis superior/inferior, hover, gravação/parada, ajustes e entrega da gravação; API simulada.")
finally:
    proc.terminate(); proc.wait(timeout=10)
    import shutil
    shutil.rmtree(env["LUMEN_DATA"], ignore_errors=True)
