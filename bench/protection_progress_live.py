"""Real progress against the existing isolated native profile and cloud test IDs.

One checkpointed note edit, one durable request; never enables automatic backup.
Run with the system Python containing Playwright. No credentials are printed.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\Aplicativos\Lumen-protecao-validacao-20261028")
os.environ["LUMEN_DATA"] = str(ROOT / "native")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parents[1] / ".venv/Lib/site-packages"))
from lumen import protection as p, protection_drive as pd
from playwright.sync_api import sync_playwright, expect

volume = os.environ.get("LUMEN_PROGRESS_CASE") == "volume"
ART = ROOT / ("interface-protecao-volume" if volume else "interface-protecao")
ART.mkdir(exist_ok=True)
JOURNAL = ART / "evidencias.json"
report = p.read(JOURNAL)
config = p.configuration()
assert config["vault"] == str(ROOT / "cofre-teste")
assert not config["enabled"]
assert p.HOME == ROOT / "native/Lumen/protection"
fingerprint = p.digest(p.HOME / "config.json")
if report.get("completed"):
    print("This request is already verified; reuse the existing evidence.")
    raise SystemExit(0)
note = Path(config["vault"]) / ("TESTE progresso de volume.png" if volume else "Continuidade automatica - TESTE.md")
if not report.get("change"):
    if volume:
        from PIL import Image
        Image.frombytes("RGB", (1200,1200), os.urandom(1200*1200*3)).save(note,compress_level=0)
    else:
        note.write_text("# Teste isolado\nAcompanhamento de backup em " + p.now() + "\n", "utf-8")
    report["change"] = {"at": p.now(), "sha256": p.digest(note), "path": str(note)}
    p.write(JOURNAL, report)
url = "http://127.0.0.1:" + (p.HOME.parent / "port.txt").read_text().strip()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
    page = browser.new_page(viewport={"width":1120,"height":860}, reduced_motion="reduce")
    page.route('**/api/bye*', lambda route: route.fulfill(status=204))
    errors = []; page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url);page.wait_for_load_state("networkidle")
        page.wait_for_function('S !== null')
        page.locator('#open-settings').click();page.locator('#settings-nav [data-cat="protection"]').click()
        panel = page.locator('[data-protection]')
        token = page.locator('meta[name="lumen-token"]').get_attribute('content')
        headers = {'X-Lumen-Token': token}
        def state(): return page.request.get(url+'/api/protection', headers=headers).json()
        current = state()
        operation = current['state'].get('operation', {})
        if not report.get('operation_id'):
            assert operation.get('status') != 'running', 'An earlier request must be reconciled before creating another'
            panel.get_by_role('button', name='Fazer backup agora', exact=True).click()
            expect(panel.get_by_role('heading', name='Guardando suas notas…')).to_be_visible()
            expect(panel.get_by_role('heading', name='Backup concluído')).to_have_count(0)
            current = state();operation = current['state']['operation']
            assert operation['status']=='running'
            report['operation_id']=operation['id'];report['accepted_at']=p.now()
            report['accepted_was_not_completion']=True
            second=page.request.post(url+'/api/protection',headers=headers,data={'action':'now'}).json()
            assert second['state']['operation']['id']==operation['id']
            report['duplicate_request_reused_id']=True
            p.write(JOURNAL,report)
        samples=report.setdefault('progress',[]);signature=None
        deadline=time.monotonic()+420
        screenshot=False
        while time.monotonic()<deadline:
            current=state();operation=current['state']['operation']
            assert operation['id']==report['operation_id']
            assert not current['config']['enabled']
            summary={'at':p.now(),'activity':current.get('activity',{}),'steps':{k:v['status'] for k,v in operation['steps'].items()},'status':operation['status']}
            key=json.dumps([summary['activity'],summary['steps'],summary['status']],sort_keys=True)
            if key!=signature:
                samples.append(summary);signature=key
                p.write(JOURNAL, report)
            if not screenshot and current.get('activity'):
                page.locator('#content').evaluate('(e)=>e.scrollTop=0')
                page.screenshot(path=str(ART/'real-working.png'));screenshot=True
                page.locator('#nav-home').click();page.locator('#open-settings').click()
                page.locator('#settings-nav [data-cat="protection"]').click()
                report['reopened_while_running']=True
            if operation['status']!='running':break
            page.wait_for_timeout(200 if volume else 400)
        assert operation['status']=='completed', {k:v for k,v in operation.items() if k!='targets'}
        assert all(current['current'].values()), current['current']
        expect(panel.get_by_role('heading',name='Backup concluído')).to_be_visible(timeout=10000)
        expect(panel.get_by_role('button',name='Backup automático: pausado')).to_be_visible()
        page.locator('#content').evaluate('(e)=>e.scrollTop=0');page.screenshot(path=str(ART/'real-complete.png'))
        versions={v['id']:v for v in current['state']['versions']}
        version=versions[operation['targets']['obsidian']]
        copied=Path(version['local']['path'])/'Atual/obsidian/files'/note.name
        assert p.digest(copied)==report['change']['sha256']
        downloaded=ART/'drive-catalog.json';pd.download(version['drive']['id'],downloaded)
        assert p.digest(downloaded)==version['drive']['catalog_sha256']
        assert p.read(downloaded)['original_snapshot']==version['id']
        assert p.digest(p.HOME/'config.json')==fingerprint
        assert not errors, errors
        report.update(completed=True,completed_at=p.now(),operation=operation,
            current=current['current'],local_file_sha256_verified=True,drive_catalog_download_verified=True,
            automatic_pause_preserved=True,configuration_sha256=fingerprint,
            observed_unknown_progress=any(any('total' not in a for a in s['activity'].values()) for s in samples),
            observed_file_bytes=any(any(a.get('scope')=='file' and a.get('total') for a in s['activity'].values()) for s in samples))
        p.write(JOURNAL,report)
        print(json.dumps({k:report[k] for k in ['operation_id','completed','completed_at','automatic_pause_preserved','local_file_sha256_verified','drive_catalog_download_verified','observed_unknown_progress','observed_file_bytes']}))
    except Exception:
        page.screenshot(path=str(ART/'failure.png'))
        print(json.dumps({'screen':str(ART/'failure.png'),'view':page.evaluate('typeof view === "undefined" ? null : view'),'ui_errors':errors}),flush=True)
        raise
    finally:
        browser.close()
