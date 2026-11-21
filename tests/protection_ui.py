"""Isolated HTTP UI plus deterministic request/progress scenarios; never uses personal data.
  py -3.14 tests/protection_ui.py   (Playwright + Chrome; the backend runs from .venv with a temporary LUMEN_DATA)
"""
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ART = Path(os.environ.get("LUMEN_PROTECTION_ARTIFACTS", ROOT / "tests/desktop-artifacts/protection-without-selection-20261031"))
ART.mkdir(parents=True, exist_ok=True)
PLACES = ("local", "drive", "notion_obsidian", "obsidian_notion")
T0, T1, T2, T3 = "2026-10-29T20:03:19+00:00", "2026-10-30T16:12:19+00:00", "2026-10-31T01:43:14+00:00", "2026-10-31T13:20:00+00:00"


def held(version, newest=True, partial=False):
    return {"version": version, "confirmed": version, "partial": partial, "newest": newest}


def place(code, keep=None, confirmed=T1, link=True, **extra):
    return {"state": code, "held": keep or {}, "confirmed": confirmed, "link": link, "message": "", "items": None,
            "organized": False, "conflicts": 0, "own_pending": 0, **extra}


def everything_ok(pending=0):
    both = {"obsidian": held(T0), "notion": held(T1, partial=bool(pending))}
    return ({"local": place("ok", both), "drive": place("ok", both),
             "notion_obsidian": place("ok", {"notion": held(T1, partial=bool(pending))}, items=479, organized=True),
             "obsidian_notion": place("ok", {"obsidian": held(T0)}, items=136)},
            {"obsidian": {"read": T2, "version": T0, "pending": 0, "failed": False, "message": "", "unsaved": False},
             "notion": {"read": T2, "version": T1, "pending": pending, "failed": False, "message": "", "unsaved": False}})


def personal_like():
    """Shape of the personal profile on 31/10: the newest Notion reading was not copied yet (automatic paused)."""
    older = {"obsidian": held(T0), "notion": held(T1, newest=False, partial=True)}
    places, sources = everything_ok(pending=2)
    places.update(local=place("behind", older, confirmed=T1), drive=place("behind", older, confirmed=T2),
                  notion_obsidian=place("behind", {"notion": held(T1, newest=False, partial=True)}, confirmed=T2, items=479, organized=True))
    sources["notion"]["version"] = T2
    return places, sources


with tempfile.TemporaryDirectory(prefix="protection-ui-") as temp:
    env = {**os.environ, "LUMEN_DATA": temp}
    proc = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-u", "-c",
        "from lumen import server; h=server.serve(); print(h.server_port,flush=True); h.serve_forever()"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
    report = {"screenshots": str(ART), "checks": []}
    def ok(name): report["checks"].append(name)
    try:
        url = "http://127.0.0.1:" + proc.stdout.readline().strip()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu"])
            page = browser.new_page(viewport={"width": 1120, "height": 860}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            def panel(): return page.locator('[data-protection]')
            def no_selection_panel():
                expect(panel().locator('summary', has_text='O que guardar')).to_have_count(0)
                expect(panel().get_by_label('Link de uma página do Notion')).to_have_count(0)
                for name in ('Adicionar página', 'Retirar', 'Conferir acesso às páginas'):
                    expect(panel().get_by_role('button', name=name, exact=True)).to_have_count(0)
                titles = panel().locator(':scope > details > summary').all_text_contents(); first = lambda t: next(i for i, x in enumerate(titles) if x.startswith(t)); assert first('Recuperar minhas notas') < first('Segurança e chave mestra') < first('Detalhes técnicos e pasta'), titles
            def row(pid): return panel().locator(f'.protection-place[data-place="{pid}"]')
            def open_main():
                page.locator('#open-settings').click()
                page.locator('#settings-nav [data-cat="protection"]').click()
            def fits():
                assert panel().evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+1')
            def shot(name): page.screenshot(path=str(ART / f"{name}.png"))
            def top(): page.locator('#content').evaluate('(e)=>e.scrollTop=0')
            def full(name):  # whole panel in one image: a tall viewport instead of stitching scrolled captures
                page.set_viewport_size({'width': 1120, 'height': 2300}); top(); fits(); shot(name)
                page.set_viewport_size({'width': 1120, 'height': 860})

            # 1. Real isolated backend: nothing configured yet.
            page.goto(url)
            page.wait_for_load_state('networkidle')
            open_main()
            expect(panel().get_by_role('heading', name='Vamos escolher onde guardar suas cópias')).to_be_visible()
            for title in ('Segurança e chave mestra', 'Detalhes técnicos e pasta', 'Recuperar minhas notas'):
                assert not panel().locator('details').filter(has=page.locator('summary', has_text=title)).first.get_attribute('open')
            expect(panel().get_by_role('button', name='Escolher pasta', exact=True).first).to_be_visible()
            expect(panel().get_by_role('button', name='Fazer backup agora', exact=True)).to_be_disabled()
            expect(panel().get_by_text('Escolha uma pasta antes do primeiro backup.')).to_be_visible()
            expect(row('local').locator('.protection-status')).to_have_text('Falta escolher a pasta')
            shot('incomplete'); ok('configuração incompleta (backend isolado real)')
            no_selection_panel()
            ok('painel de seleção removido do DOM; recuperação antes de segurança')
            token = page.locator('meta[name="lumen-token"]').get_attribute('content')
            baseline = page.request.get(url + '/api/protection', headers={'X-Lumen-Token': token}).json()
            assert set(baseline['places']) == set(PLACES) and set(baseline['sources']) == {'obsidian', 'notion'}
            assert 'connected' in baseline['drive'] and baseline['config']['drive_enabled'] is False, baseline.get('drive')
            ok('API real devolve places/sources')

            # 2. Controlled states through a routed API.
            state = copy.deepcopy(baseline)
            iid = '12345678-1234-1234-1234-123456789abc'
            state['config'].update(enabled=False, local=r'D:\TESTE\cópias', vault=r'D:\TESTE\cofre', roots=[iid], drive_enabled=True)
            state.update(notion_connected=True, has_key=True, local_available=True, drive={'connected': True}, activity={})
            state['places'] = {k: place('first', confirmed=None, link=k == 'local') for k in PLACES}
            state['sources'] = {o: {'read': None, 'version': None, 'pending': 0, 'failed': False, 'message': '', 'unsaved': False} for o in ('obsidian', 'notion')}
            state['state'] = {'versions': [], 'page_titles': {iid: {'title': 'Meus estudos e anotações de teste', 'accessible': True}}}
            counts = {'now': 0}; posted = []; opened = []; fail_get = [False]; hold_get = [False]; delayed = []; initial_loading = [True]
            def note(cause, title, headline, summary, tone='review', action='notion-page', **extra):
                return {'cause': cause, 'tone': tone, 'title': title, 'headline': headline, 'summary': summary, 'action': action,
                        'details': [f'Explicação completa sobre {title}.'], **extra}
            ICON = note('icon', 'Template - Ficha de Lead | Barbearia', 'Um ícone desta página não pôde ser incluído', 'O texto da página foi lido. Só o ícone ficou de fora.', page='page-icon')
            def unsupported(title, page): return note('unsupported', title, 'Uma parte desta página não é disponibilizada pelo Notion', 'O restante da página foi lido. Essa parte só pode ser vista no próprio Notion.', page=page)
            def kept_note(n): return note('preserved', f'Nota antiga {n}', 'Versão antiga preservada para comparação', 'Nenhuma ação necessária.', tone='info', action='locate', path=f'Versões preservadas/{n}.md')
            att = {'items': [ICON, unsupported('Personalidade', 'page-unsupported'), kept_note(1), kept_note(2)], 'fail': False, 'hold': False, 'held': []}
            def route(request_route):
                req = request_route.request
                if req.method == 'GET':
                    if initial_loading[0]: delayed.append(request_route); return
                    if hold_get[0]:
                        hold_get[0] = False; delayed.append(request_route); return
                    if fail_get[0]: return request_route.fulfill(status=503, json={'error': {'message': 'screen refresh fault'}})
                    return request_route.fulfill(json=state)
                body = req.post_data_json; action = body['action']
                posted.append(action)
                if action == 'now':
                    counts['now'] += 1
                    state['state']['operation'] = {'id': 'request-' + str(counts['now']), 'status': 'running', 'started': T3, 'steps': {}, 'targets': {}}
                    for k in PLACES: state['places'][k]['state'] = 'queued'
                elif action in ('start', 'pause'): state['config']['enabled'] = action == 'start'
                elif action == 'drive-enable':
                    state['config']['drive_enabled'] = body['enabled']
                    state['places']['drive']['state'] = 'ok' if body['enabled'] else 'disabled'
                elif action in ('choose', 'export-key', 'import-key'): return request_route.fulfill(json={'cancelled': True})
                elif action == 'attention':
                    if att['fail']: return request_route.fulfill(status=503, json={'error': {'message': 'attention fault'}})
                    if att['hold']: att['hold'] = False; att['held'].append(request_route); return
                    return request_route.fulfill(json={'items': att['items']})
                elif action == 'open-place': opened.append(body); return request_route.fulfill(json={'notice': 'Destino aberto.'})
                elif action == 'versions': return request_route.fulfill(json={'versions': [{'id': 'old-notion', 'time': T0, 'tags': ['notion']}, {'id': 'new-obsidian', 'time': T1, 'tags': ['obsidian']}], 'repository': 'test'})
                else: raise AssertionError(action)
                return request_route.fulfill(json=state)
            page.route('**/api/protection', route)
            page.reload(wait_until='domcontentloaded')
            for _ in range(300):
                if page.evaluate('typeof S!=="undefined" && S!==null'): break
                page.wait_for_timeout(50)
            open_main()
            expect(panel().get_by_role('button', name='Fazer backup agora', exact=True)).to_be_disabled()
            expect(panel().get_by_role('button', name='Backup automático: pausado')).to_be_disabled()
            expect(panel().get_by_role('heading', name='Conferindo suas cópias…')).to_be_visible()
            ok('carregando: comandos desativados até a primeira leitura')
            initial_loading[0] = False
            for waiting in delayed: waiting.fulfill(json=state)
            delayed.clear()
            expect(panel().get_by_role('heading', name='Pronto para fazer a primeira cópia')).to_be_visible()
            for pid in PLACES: expect(row(pid).locator('.protection-status')).to_have_text('Aguardando a primeira cópia')
            expect(row('drive').get_by_role('button', name='Abrir pasta no Drive')).to_be_disabled()
            expect(row('drive').get_by_text('Ainda não há uma cópia confirmada no Drive.')).to_be_visible()
            expect(row('notion_obsidian').get_by_text('As notas aparecem aqui depois da primeira cópia.')).to_be_visible()
            shot('ready'); full('ready-full'); ok('primeira cópia: estados separados e ações indisponíveis explicadas')

            # 3. One request, even with rapid clicks; accepted is not started is not finished.
            panel().get_by_role('button', name='Fazer backup agora', exact=True).evaluate('(b)=>{b.click();b.click();b.click();}')
            expect(panel().get_by_role('heading', name='Guardando suas notas…')).to_be_visible()
            expect(panel().get_by_role('button', name='Fazendo backup…')).to_be_disabled()
            expect(panel().get_by_role('button', name='Recuperar minhas notas', exact=True)).to_be_enabled()
            expect(panel().get_by_text('Pedido recebido. O trabalho começa em instantes.')).to_be_visible()
            assert counts['now'] == 1
            expect(panel().locator('.protection-step')).to_have_count(6)
            expect(panel().locator('.protection-step[data-state=done]')).to_have_count(0)
            expect(panel().get_by_text('Cópia confirmada', exact=True)).to_have_count(0)
            expect(row('local').locator('.protection-status')).to_have_text('Aguardando a vez neste backup')
            ok('cliques rápidos: um pedido; pedido aceito sem conclusão')
            state['state']['operation']['steps'] = {'obsidian': {'status': 'done'}}
            state['activity'] = {'notion': {'stage': 'reading', 'done': 12, 'unit': 'pages'}}
            expect(panel().get_by_text('12 páginas conferidas', exact=True)).to_be_visible(timeout=8000)
            expect(panel().locator('.protection-step[data-state=done]')).to_have_count(1)
            expect(panel().locator('.protection-step', has_text='Guardar neste computador')).to_contain_text('Aguardando as leituras')
            assert panel().locator('.protection-step[data-state=working] progress').get_attribute('value') is None
            ok('trabalho iniciado: etapas reais, progresso indeterminado sem total')
            panel().get_by_role('button', name='Recuperar minhas notas', exact=True).click()
            panel().get_by_role('button', name='Ver minhas cópias salvas', exact=True).click()
            field = panel().get_by_label('Cópia salva para recuperar'); field.select_option('new-obsidian'); field.focus()
            scroll = page.locator('#content').evaluate('(e)=>e.scrollTop')
            state['state']['operation']['steps'].update(notion={'status': 'partial'})
            state['activity'] = {'drive': {'stage': 'uploading', 'done': 8 * 1048576, 'total': 20 * 1048576, 'unit': 'bytes', 'scope': 'file'}}
            state['places']['drive']['state'] = 'copying'
            progress = panel().get_by_role('progressbar', name='Envio do arquivo atual ao Google Drive')
            expect(progress).to_have_attribute('value', str(8 * 1048576), timeout=8000)
            expect(progress).to_have_attribute('max', str(20 * 1048576))
            expect(panel().get_by_text('Arquivo atual: 8 MB de 20 MB.', exact=False)).to_be_visible()
            expect(row('drive').locator('.protection-status')).to_have_text('Copiando agora')
            expect(panel().locator('.protection-step', has_text='Ler o Notion')).to_contain_text('Concluído com pendências')
            assert field.input_value() == 'new-obsidian'
            assert field.evaluate('(e)=>document.activeElement===e')
            assert abs(page.locator('#content').evaluate('(e)=>e.scrollTop') - scroll) < 2
            assert panel().locator('details', has=page.locator('summary', has_text='Recuperar minhas notas')).get_attribute('open') is not None
            shot('working'); top(); shot('working-overview')
            ok('polling: versão escolhida, foco, rolagem e recuperação aberta preservados; bytes só do arquivo atual')
            panel().locator('summary', has_text='Recuperar minhas notas').click()
            page.locator('#nav-home').click(); open_main()
            expect(panel().get_by_role('heading', name='Guardando suas notas…')).to_be_visible()
            assert counts['now'] == 1
            ok('fechar e reabrir a área retoma o andamento')
            fail_get[0] = True
            expect(panel().get_by_text('Não conseguimos atualizar esta tela.', exact=False)).to_be_visible(timeout=8000)
            expect(panel().get_by_role('heading', name='O último backup não terminou')).to_have_count(0)
            fail_get[0] = False
            ok('falha temporária da tela não vira falha do backup')
            panel().get_by_role('button', name='Backup automático: pausado').click()
            expect(panel().get_by_role('button', name='Backup automático: ligado')).to_be_visible()
            panel().get_by_role('button', name='Backup automático: ligado').click()
            expect(panel().get_by_text('A cópia que você pediu continua.', exact=False)).to_be_visible()
            assert not state['config']['enabled']
            ok('pausa e retomada não cancelam o pedido manual')

            # 4. Partial: Drive failed, the local copy stays confirmed.
            state['activity'] = {}
            places, sources = everything_ok()
            places['drive'] = place('attention', places['drive']['held'], confirmed=T0, message='Sessão de envio interrompida. O Lúmen retomará pelo mesmo identificador.')
            state.update(places=places, sources=sources)
            state['state'].update(operation={'id': 'request-1', 'status': 'partial', 'started': T3, 'finished': T3, 'steps': {'drive': {'status': 'failed'}}},
                                  local={'status': 'confirmed', 'confirmed': T1}, drive={'status': 'pending', 'confirmed': T0})
            expect(panel().get_by_role('heading', name='Uma parte precisa de atenção')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('A cópia que você pediu continua.', exact=False)).to_have_count(0)
            expect(row('local').locator('.protection-status')).to_have_text('Cópia confirmada')
            expect(row('drive').locator('.protection-status')).to_have_text('Precisa de atenção')
            expect(row('drive').get_by_text('Notion: versão de', exact=False)).to_be_visible()
            expect(panel().get_by_text('Último backup pedido: concluído com pendências', exact=False)).to_be_visible()
            panel().get_by_role('button', name='Ver o que falta').click()
            sec = panel().locator('details.protection-issues')
            def notices(): return sec.locator('.protection-notice')
            drive_notice = notices().filter(has_text='A última cópia não terminou')
            expect(drive_notice).to_contain_text('Precisa de ação')
            expect(drive_notice).to_contain_text('Google Drive')
            expect(drive_notice).to_contain_text('A cópia neste computador foi confirmada. Falta terminar o envio ao Drive.')
            expect(drive_notice.get_by_role('button', name='Refazer backup completo: Google Drive')).to_be_visible()
            expect(notices().first).to_contain_text('A última cópia não terminou')  # what blocks a copy comes first
            expect(sec.locator('.protection-count')).to_have_text(' · 1 precisa de ação · 2 para conferir')
            for label in ('O que aconteceu', 'O que já está guardado', 'O que fazer'): expect(sec).not_to_contain_text(label + ':')
            expect(notices().filter(has_text='Personalidade').get_by_role('button', name='Refazer backup completo')).to_have_count(0)
            expect(sec.get_by_role('button', name='Tentar novamente')).to_have_count(0)
            expect(sec.locator('.protection-kept summary')).to_have_text('2 versões antigas preservadas · nenhuma ação necessária')
            expect(notices().filter(has_text='Nota antiga 1')).to_have_count(0)
            sec.locator('.protection-kept summary').click()
            sec.get_by_role('button', name='Localizar Nota antiga 1').click()
            expect(panel().get_by_text('Destino aberto.', exact=True)).to_be_visible()
            assert opened.pop() == {'action': 'open-place', 'place': 'notion_obsidian', 'path': 'Versões preservadas/1.md'}
            sec.locator('.protection-kept summary').click()
            fits(); shot('partial-drive-failed'); full('partial-drive-failed-full')
            ok('falha de um destino não apaga a confirmação dos outros; ação certa só onde ajuda; versões preservadas fora da contagem')
            panel().locator('summary', has_text='O que precisa de atenção').click()
            panel().locator('summary', has_text='Detalhes técnicos e pasta').click()
            expect(panel().locator('.protection-details')).to_contain_text('Terminou com pendências')
            expect(panel().locator('.protection-details')).to_contain_text(state['config']['local'])
            expect(panel().locator('pre, code')).to_have_count(0)
            assert 'request-1' not in panel().inner_text()
            fits(); shot('details-readable')
            panel().locator('summary', has_text='Detalhes técnicos e pasta').click()
            ok('detalhes legíveis, sem IDs')

            # 4b. "O que precisa de atenção": need-based notices, grouping and live updates.
            def at_section(name):
                sec.evaluate("(s)=>s.scrollIntoView({block:'start'})"); fits(); shot(name)
            state['places'], state['sources'] = everything_ok()
            state['state']['operation'] = {'id': 'request-2', 'status': 'completed', 'started': T3, 'finished': T3, 'steps': {}}
            att['items'] = []; state['attention_key'] = 'k-empty'
            sec.locator('summary').first.click()
            expect(sec.locator('.protection-issues-intro')).to_have_text('Nenhuma ação necessária.', timeout=8000)
            expect(notices()).to_have_count(0)
            expect(sec.locator('.protection-count')).to_have_text('')
            expect(sec.locator('.protection-kept')).to_be_hidden()
            at_section('attention-none'); ok('sem pendências: “Nenhuma ação necessária”, sem contagem')
            att['items'] = [ICON, unsupported('Personalidade', 'p1'), unsupported('Diário de estudos: anotações sobre ação & reação, coração e atenção', 'p2'),
                            unsupported('Página com um título realmente comprido para ver a quebra de linha sem rolagem horizontal ' * 2, 'p3'), kept_note(1), kept_note(2)]
            state['attention_key'] = 'k-1'
            expect(sec.locator('.protection-count')).to_have_text(' · 4 para conferir', timeout=8000)
            expect(notices()).to_have_count(2)
            group = notices().filter(has_text='3 páginas têm partes que o Notion não disponibiliza')
            expect(group.locator('li')).to_have_count(3)
            expect(group).to_contain_text('O restante foi lido. Essas partes só podem ser vistas no próprio Notion.')
            expect(sec.locator('.protection-issues-intro')).to_have_text('Nada impede as cópias. Os avisos abaixo são para conferir quando puder.')
            expect(sec.get_by_role('button', name='Refazer backup completo')).to_have_count(0)
            expect(sec.locator('.protection-kept summary')).to_have_text('2 versões antigas preservadas · nenhuma ação necessária')
            group.get_by_role('button', name='Abrir no Notion: Diário de estudos: anotações sobre ação & reação, coração e atenção').click()
            expect(panel().get_by_text('Destino aberto.', exact=True)).to_be_visible()
            assert opened.pop() == {'action': 'open-place', 'place': 'source', 'path': 'p2'}
            at_section('attention-review'); full('attention-review-full')
            ok('pendência surge; mesma causa agrupada; contagem só de pendências reais; ação abre a página certa')
            icon_notice = notices().filter(has_text='Um ícone desta página não pôde ser incluído')
            icon_notice.locator('summary', has_text='Ver detalhes').click()
            expect(icon_notice).to_contain_text('Explicação completa sobre Template - Ficha de Lead | Barbearia.')
            icon_button = icon_notice.get_by_role('button', name='Abrir no Notion: Template - Ficha de Lead | Barbearia')
            icon_button.focus(); scroll = page.locator('#content').evaluate('(e)=>e.scrollTop')
            att['items'] = att['items'] + [note('difference', 'Plano de estudos', 'Esta nota está diferente da última cópia', 'O Lúmen manteve o arquivo como está, sem sobrescrever nada. Compare quando puder.', action='locate', path='Particular/Plano de estudos.md')]
            state['attention_key'] = 'k-2'
            expect(sec.locator('.protection-count')).to_have_text(' · 5 para conferir', timeout=8000)
            assert icon_notice.locator('details.protection-more').get_attribute('open') is not None
            assert icon_button.evaluate('(b)=>document.activeElement===b')
            assert abs(page.locator('#content').evaluate('(e)=>e.scrollTop') - scroll) < 2
            notices().filter(has_text='Plano de estudos').get_by_role('button', name='Localizar nota: Plano de estudos').click()
            expect(panel().get_by_text('Destino aberto.', exact=True)).to_be_visible()
            assert opened.pop() == {'action': 'open-place', 'place': 'notion_obsidian', 'path': 'Particular/Plano de estudos.md'}
            at_section('attention-details-open')
            ok('atualização mantém detalhes abertos, foco e rolagem; conflito real só localiza, sem sobrescrever')
            stale = list(att['items']); att['hold'] = True; att['items'] = [ICON, kept_note(1)]; state['attention_key'] = 'k-3'
            for _ in range(100):
                if att['held']: break
                page.wait_for_timeout(50)
            assert att['held']
            sec.locator('summary').first.click(); sec.locator('summary').first.click()  # reopening asks again
            expect(sec.locator('.protection-count')).to_have_text(' · 1 para conferir', timeout=8000)
            att['held'].pop().fulfill(json={'items': stale}); page.wait_for_timeout(400)
            expect(sec.locator('.protection-count')).to_have_text(' · 1 para conferir')
            expect(notices()).to_have_count(1)
            ok('resposta antiga não substitui a nova; reabrir mostra o momento atual')
            att['items'] = [kept_note(1)]; state['attention_key'] = 'k-4'
            expect(sec.locator('.protection-issues-intro')).to_have_text('Nenhuma ação necessária.', timeout=8000)
            expect(notices()).to_have_count(0)
            expect(sec.locator('.protection-kept summary')).to_have_text('1 versão antiga preservada · nenhuma ação necessária')
            ok('pendência resolvida sai da lista; versão preservada continua discreta')
            att['items'] = [ICON, kept_note(1)]; state['attention_key'] = 'k-5'
            expect(notices()).to_have_count(1, timeout=8000)
            att['fail'] = True; state['attention_key'] = 'k-6'
            expect(sec.locator('.protection-issues-status')).to_contain_text('Não conseguimos atualizar os avisos das notas. Mostrando a consulta de', timeout=8000)
            expect(notices()).to_have_count(1)
            expect(panel().get_by_role('heading', name='O último backup não terminou')).to_have_count(0)
            at_section('attention-query-failed')
            att['fail'] = False
            expect(sec.locator('.protection-issues-status')).to_be_hidden(timeout=12000)
            ok('falha da consulta mantém o último conteúdo, explica e se recupera; não vira falha do backup')
            # A destination that needs action: one full backup, even with rapid clicks.
            places, sources = everything_ok()
            places['drive'] = place('attention', places['drive']['held'], confirmed=T0, message='Sessão de envio interrompida.')
            state.update(places=places, sources=sources)
            expect(sec.locator('.protection-issues-intro')).to_have_text('Comece pelo primeiro aviso: ele precisa de você.', timeout=8000)
            before = counts['now']
            sec.get_by_role('button', name='Refazer backup completo: Google Drive').evaluate('(b)=>{b.click();b.click();b.click();}')
            expect(panel().get_by_role('button', name='Fazendo backup…')).to_be_disabled()
            assert counts['now'] == before + 1, counts
            expect(notices().filter(has_text='A última cópia não terminou')).to_have_count(0, timeout=8000)  # while working: nothing to act on yet
            expect(sec.get_by_role('button', name='Abrir no Notion: Template - Ficha de Lead | Barbearia')).to_be_enabled()
            ok('tentar de novo dispara um único backup completo; abrir notas continua disponível durante o backup')
            state['state']['operation'].update(status='completed', finished=T3); state['activity'] = {}
            places, sources = everything_ok()
            places['local'] = place('behind', places['local']['held']); places['drive'] = place('behind', places['drive']['held'])
            state.update(places=places, sources=sources)
            behind = notices().filter(has_text='Alterações ainda não copiadas')
            expect(behind).to_contain_text('Precisa de ação', timeout=8000)
            expect(behind.get_by_role('button', name='Fazer backup agora: Neste computador, Google Drive')).to_be_visible()
            state['config']['enabled'] = True
            expect(behind).to_contain_text('Aguardando', timeout=8000)
            expect(behind.get_by_role('button')).to_have_count(0)
            state['config']['enabled'] = False
            ok('alterações pendentes: ação com automático pausado, apenas aguardar com automático ligado')
            att['items'] = [note('attachment', f'Anexo {n}: relatório trimestral com um título bastante comprido, acentuação e mais palavras', 'Um arquivo desta página não pôde ser baixado',
                                 'O restante da página foi lido. Confira o arquivo no Notion.', page=f'a{n}') for n in range(1, 7)] + [ICON]
            state['places'], state['sources'] = everything_ok(); state['attention_key'] = 'k-7'
            many = notices().filter(has_text='6 páginas têm arquivos que não puderam ser baixados')
            expect(many).to_be_visible(timeout=8000)
            expect(many.locator('summary', has_text='Ver as 6 notas')).to_be_visible()
            expect(sec.locator('.protection-count')).to_have_text(' · 7 para conferir')
            many.locator('summary', has_text='Ver as 6 notas').click()
            at_section('attention-many'); full('attention-many-full')
            page.set_viewport_size({'width': 760, 'height': 600}); at_section('attention-many-small')
            page.set_viewport_size({'width': 1120, 'height': 860})
            ok('muitas notas e títulos longos: agrupadas, recolhidas, sem rolagem horizontal')
            sec.locator('summary').first.focus(); page.keyboard.press('Tab')
            assert page.evaluate("document.activeElement.closest('.protection-notice')!==null")
            assert page.evaluate('getComputedStyle(document.activeElement).outlineStyle') != 'none'
            details_summary = many.locator('summary', has_text='Ver detalhes')
            details_summary.focus(); page.keyboard.press('Enter')
            assert details_summary.evaluate('(e)=>e.parentElement.open')
            page.keyboard.press('Space'); assert not details_summary.evaluate('(e)=>e.parentElement.open')
            page.keyboard.press('Shift+Tab'); assert page.evaluate("document.activeElement.closest('.protection-notice')!==null")
            ok('teclado na seção: Tab, Shift+Tab, Enter, Espaço e foco visível')
            main_notice_titles = notices().locator('h4').all_inner_texts()
            sec.locator('summary').first.click()

            # 5. Complete, unchanged and capture limitations.
            state['places'], state['sources'] = everything_ok()
            state['state']['operation'].update(status='completed', steps={})
            state['state']['drive'] = {'status': 'confirmed', 'confirmed': T1}
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            for pid, text in (('local', 'Cópia confirmada'), ('drive', 'Cópia confirmada'), ('notion_obsidian', 'Notas atualizadas'), ('obsidian_notion', 'Notas atualizadas')):
                expect(row(pid).locator('.protection-status')).to_have_text(text)
                expect(row(pid).locator('.protection-date')).to_be_visible()
            state['config']['vault'] = ''
            expect(panel().get_by_role('heading', name='Falta conferir as origens das notas')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('Escolha seu cofre nas configurações do Obsidian.')).to_be_visible()
            state['config'].update(vault=r'D:\TESTE\cofre', roots=[], discover=False)
            expect(panel().get_by_text('Confira a página principal nas configurações do Notion.')).to_be_visible(timeout=8000)
            no_selection_panel(); shot('sources-missing')
            state['config'].update(roots=[iid], discover=True)
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            ok('origens ausentes: aviso principal verdadeiro, sem recriar seleção')
            expect(row('notion_obsidian')).to_contain_text('479 páginas organizadas em páginas e subpáginas')
            expect(panel().get_by_role('button', name='Fazer backup agora')).to_be_enabled()
            top(); shot('complete'); full('complete-full'); ok('conclusão completa: quatro sinais separados com data')
            state['state']['operation']['outcome'] = 'unchanged'
            expect(panel().get_by_role('heading', name='Nenhuma alteração para guardar')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('concluído, sem alterações novas', exact=False)).to_be_visible()
            shot('unchanged'); ok('conclusão sem alterações')
            state['places'], state['sources'] = everything_ok(pending=2)
            expect(panel().get_by_role('heading', name='Cópias em dia, com partes do Notion a conferir')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('Confira 2 partes que o Notion não entrega', exact=False)).to_be_visible()
            ok('limitações da captura não viram “tudo protegido”')

            # 6. Shape of the personal profile: previous copies, newest Notion reading pending.
            state['places'], state['sources'] = personal_like()
            state['state']['operation'] = {'id': 'request-0', 'status': 'partial', 'started': T1, 'finished': T1, 'steps': {}}
            expect(panel().get_by_role('heading', name='Há backups, mas falta atualizar')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('Obsidian e Notion têm backup neste computador e no Google Drive.')).to_be_visible()
            expect(panel().get_by_text('Clique em Fazer backup agora para guardar a versão mais recente.', exact=False)).to_be_visible()
            for pid in ('local', 'drive'):
                expect(row(pid).locator('.protection-status')).to_have_text('Cópia anterior disponível; atualização pendente')
                expect(row(pid)).to_contain_text('falta copiar a de')
            expect(row('notion_obsidian').locator('.protection-status')).to_have_text('Versão anterior disponível; atualização pendente')
            expect(row('obsidian_notion').locator('.protection-status')).to_have_text('Notas atualizadas')
            top(); fits(); shot('previous-copy-update-pending'); full('previous-copy-update-pending-full')
            ok('cópia anterior disponível; atualização pendente (formato do perfil pessoal)')
            places, sources = everything_ok()
            for pid in ('local', 'drive'): places[pid] = place('behind', {'obsidian': held(T0)})
            state['places'], state['sources'] = places, sources
            expect(panel().get_by_role('heading', name='Falta guardar o Notion')).to_be_visible(timeout=8000)
            expect(row('local')).to_contain_text('Notion: ainda não guardado aqui')
            expect(panel().get_by_text('O Obsidian tem backup neste computador e no Google Drive; o Notion ainda não tem backup.')).to_be_visible()
            ok('só uma origem guardada: diz qual falta')
            places, sources = everything_ok()
            places['local'] = place('unavailable', places['local']['held'], link=False)
            state['places'], state['local_available'] = places, False
            expect(row('local').locator('.protection-status')).to_have_text('Destino indisponível', timeout=8000)
            expect(row('local').get_by_role('button', name='Abrir pasta')).to_be_disabled()
            expect(row('local').get_by_text('O disco da pasta escolhida não está disponível agora.')).to_be_visible()
            shot('local-unavailable'); ok('destino indisponível explica o motivo')
            state['places'], state['local_available'] = everything_ok()[0], True
            state['state']['operation'] = {'id': 'request-9', 'status': 'failed', 'started': T3, 'finished': T3, 'steps': {'obsidian': {'status': 'failed'}, 'notion': {'status': 'failed'}}}
            expect(panel().get_by_role('heading', name='O último backup não terminou')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('Último backup pedido: não concluído', exact=False)).to_be_visible()
            shot('failed'); full('failed-full'); ok('falha do pedido')
            state['state']['operation']['status'] = 'completed'

            # 7. Each action opens its own recorded destination (the backend validates and opens it).
            state['places'], state['sources'] = everything_ok()
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            for pid, name in (('local', 'Abrir pasta'), ('drive', 'Abrir pasta no Drive'), ('notion_obsidian', 'Ver notas'), ('obsidian_notion', 'Ver notas')):
                row(pid).get_by_role('button', name=name).click()
                expect(panel().get_by_text('Destino aberto.', exact=True)).to_be_visible()
            assert [x['place'] for x in opened] == list(PLACES), opened
            ok('ações por destino enviam o destino correto')

            # 7b. The Drive is optional: off is a choice, not a problem; the toggle posts an explicit value and the
            # POST answer still carries the Drive status (no "Conectar" flicker).
            expect(panel().locator('.protection-types li')).to_have_count(3)
            expect(panel().locator('.protection-types')).to_contain_text('Não depende de internet')
            expect(panel().locator('.protection-types')).to_contain_text('Opcional')
            expect(panel().locator('.protection-types')).to_contain_text('Não substitui o backup completo')
            expect(row('drive').locator('.protection-drive-note')).to_contain_text('limitado')
            expect(row('drive').get_by_text('objetos confirmados', exact=False)).to_have_count(0)  # only shown when the backend sends a count
            state['places']['drive']['held']['obsidian']['objects'] = 128
            expect(row('drive').get_by_text('128 objetos confirmados', exact=False)).to_be_visible(timeout=8000)
            expect(row('local').get_by_text('objetos confirmados', exact=False)).to_have_count(0)
            toggle = row('drive').get_by_role('button', name='Desativar backup no Drive')
            expect(toggle).to_have_attribute('aria-pressed', 'true')
            before = len(posted)
            toggle.click()
            expect(row('drive').locator('.protection-status')).to_have_text('Desativado por você', timeout=8000)
            assert posted[before:before + 1] == ['drive-enable'] and state['config']['drive_enabled'] is False, posted[before:]
            expect(row('drive').get_by_role('button', name='Ativar backup no Google Drive')).to_have_attribute('aria-pressed', 'false')
            expect(row('drive').get_by_role('button', name='Abrir pasta no Drive')).to_be_enabled()
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible()
            expect(panel().locator('.protection-hero')).to_contain_text('Obsidian e Notion têm backup neste computador.')
            expect(panel().locator('details.protection-issues .protection-notice', has_text='Google Drive')).to_have_count(0)
            shot('drive-disabled'); full('drive-disabled-full')
            previous_operation = copy.deepcopy(state['state'].get('operation'))
            state['state']['operation'] = {'id': 'request-drive-off', 'status': 'running', 'started': T3, 'steps': {'obsidian': {'status': 'done'}}}
            expect(panel().locator('.protection-step')).to_have_count(6, timeout=8000)
            expect(panel().locator('.protection-step', has_text='Google Drive')).to_contain_text('Desativado nas configurações (não consome cota)')
            expect(panel().locator('.protection-steps')).not_to_contain_text('Enviar ao Google Drive')
            state['state']['operation'] = previous_operation
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            row('drive').get_by_role('button', name='Ativar backup no Google Drive').click()
            expect(row('drive').locator('.protection-status')).to_have_text('Cópia confirmada', timeout=8000)
            assert posted[-1] == 'drive-enable' and state['config']['drive_enabled'] is True
            ok('Drive opcional: desligado não é problema, o botão envia a escolha e o card explica os três tipos')

            # 7c. The three lower sections are cards: icon, tag and purpose are readable before opening; one primary action each.
            cards = panel().locator('details.protection-card-disclosure')
            expect(cards).to_have_count(3)
            def card(name): return cards.filter(has=page.locator('summary', has_text=name))
            for name, badge, hint in (('Recuperar minhas notas', 'Restauração', 'sem tocar nas notas atuais'), ('Segurança e chave mestra', 'Criptografia', 'abrir backups em outro computador'),
                                      ('Detalhes técnicos e pasta', 'Ajustes', 'histórico de diagnósticos')):
                expect(card(name).locator('summary .protection-card-badge')).to_have_text(badge)
                expect(card(name).locator('summary .protection-card-hint')).to_contain_text(hint)
                expect(card(name).locator('summary .protection-card-icon svg')).to_be_visible()
                expect(card(name).locator('.protection-card-body')).to_be_hidden()
            def is_primary(box, name): return box.get_by_role('button', name=name, exact=True).evaluate('(e)=>e.classList.contains("primary")')
            card('Segurança e chave mestra').locator(':scope > summary').click()
            page.wait_for_timeout(350)
            assert card('Segurança e chave mestra').locator('.protection-card-chevron').evaluate('(e)=>getComputedStyle(e).transform') != 'none'
            assert is_primary(card('Segurança e chave mestra'), 'Guardar minha chave de recuperação') and not is_primary(card('Segurança e chave mestra'), 'Usar uma chave que já tenho')
            card('Recuperar minhas notas').locator(':scope > summary').click()
            card('Detalhes técnicos e pasta').locator(':scope > summary').click()
            assert is_primary(card('Recuperar minhas notas'), 'Ver minhas cópias salvas') and not is_primary(card('Recuperar minhas notas'), 'Procurar minhas cópias no Drive')
            assert not any(is_primary(card('Detalhes técnicos e pasta'), n) for n in ('Trocar a pasta das cópias', 'Abrir pasta das cópias', 'Conectar Google Drive'))
            fits(); full('cards-open')
            for name in ('Recuperar minhas notas', 'Segurança e chave mestra', 'Detalhes técnicos e pasta'): card(name).locator(':scope > summary').click()
            page.wait_for_timeout(350)
            assert card('Segurança e chave mestra').locator('.protection-card-chevron').evaluate('(e)=>getComputedStyle(e).transform') in ('none', 'matrix(1, 0, 0, 1, 0, 0)')
            fits(); full('cards-closed')
            ok('seções inferiores em cards: ícone, selo e microcópia visíveis, seta gira, uma ação principal por seção')

            # 8. Automatic parallel work and a late response after a new request.
            state['activity'] = {'local': {'stage': 'checking'}, 'drive': {'stage': 'uploading', 'done': 20 * 1048576, 'total': 20 * 1048576, 'unit': 'bytes', 'scope': 'file'}}
            state['places']['local']['state'], state['places']['drive']['state'] = 'checking', 'copying'
            expect(panel().get_by_role('heading', name='Guardando suas notas…')).to_be_visible(timeout=8000)
            expect(panel().locator('.protection-step')).to_have_count(6)
            expect(panel().get_by_text('Conferindo o arquivo enviado…', exact=True)).to_be_visible()
            expect(row('local').locator('.protection-status')).to_have_text('Conferindo alterações')
            assert all(x.get_attribute('value') is None for x in panel().locator('progress').all())
            shot('parallel'); ok('trabalhos paralelos; 100% do arquivo não aparece antes da conferência')

            # 8b. Automatic backup: the Drive row never disappears; each wording follows persisted state and live activity.
            def drive_step(): return panel().locator('.protection-step', has_text='Google Drive')
            state['activity'] = {'notion': {'stage': 'reading', 'done': 12, 'unit': 'pages'}}
            state['places']['local']['state'], state['places']['drive']['state'] = 'behind', 'behind'
            expect(drive_step()).to_contain_text('Aguardando a conclusão da leitura das notas…', timeout=8000)
            expect(drive_step()).to_have_attribute('data-state', 'queued')
            expect(panel().locator('.protection-step', has_text='Ler o Notion')).to_contain_text('Procurando alterações…')
            shot('auto-drive-waiting-read')
            state['activity'] = {'local': {'stage': 'checking'}}
            expect(drive_step()).to_contain_text('Na fila para sincronizar…', timeout=8000)
            state['activity'] = {'drive': {'stage': 'uploading', 'done': 8 * 1048576, 'total': 20 * 1048576, 'unit': 'bytes', 'scope': 'file'}}
            state['places']['drive']['state'] = 'copying'
            expect(drive_step()).to_contain_text('Enviando para o Google Drive…', timeout=8000)
            assert drive_step().locator('progress').get_attribute('value') is not None
            expect(drive_step()).to_contain_text('8 MB de 20 MB')
            shot('auto-drive-uploading')
            state['activity'] = {'local': {'stage': 'checking'}}
            state['places'], state['sources'] = everything_ok()
            expect(drive_step()).to_contain_text('Sincronizado na nuvem', timeout=8000)
            expect(drive_step()).to_have_attribute('data-state', 'done')
            state['config']['drive_enabled'] = False; state['places']['drive']['state'] = 'disabled'
            expect(drive_step()).to_contain_text('Desativado nas configurações (não consome cota)', timeout=8000)
            expect(drive_step()).to_have_attribute('data-state', 'off')
            shot('auto-drive-disabled')
            state['config']['drive_enabled'] = True; state['activity'] = {}
            ok('backup automático lista o Drive em todas as fases: esperando a leitura, na fila, enviando, sincronizado e desativado')
            state['activity'] = {}; state['places'], state['sources'] = everything_ok()
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            old = copy.deepcopy(state); hold_get[0] = True
            page.locator('#nav-home').click(); open_main()
            for _ in range(100):
                if delayed: break
                page.wait_for_timeout(50)
            assert delayed
            panel().get_by_role('button', name='Fazer backup agora', exact=True).click()
            expect(panel().get_by_role('heading', name='Guardando suas notas…')).to_be_visible()
            delayed.pop().fulfill(json=old)
            page.wait_for_timeout(200)
            expect(panel().get_by_role('heading', name='Guardando suas notas…')).to_be_visible()
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_have_count(0)
            ok('resposta antiga não substitui a nova')
            state['state']['operation']['status'] = 'completed'; state['places'] = everything_ok()[0]
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            panel().locator('summary', has_text='Segurança e chave mestra').click()
            panel().get_by_role('button', name='Guardar minha chave de recuperação').click()
            expect(panel().get_by_text('Escolha cancelada.', exact=True)).to_be_visible()
            expect(panel().get_by_text('Chave guardada no lugar escolhido.', exact=True)).to_have_count(0)
            assert state['config']['local'] == r'D:\TESTE\cópias' and not state['config']['enabled']
            panel().locator('summary', has_text='Segurança e chave mestra').click()
            ok('seletor cancelado é explícito e preserva a configuração')
            kept = state.pop('places'), state.pop('sources')
            expect(panel().get_by_role('heading', name='Reabra o Lúmen para ver cada cópia')).to_be_visible(timeout=8000)
            expect(panel().get_by_text('Cópia confirmada', exact=True)).to_have_count(0)
            expect(row('drive').locator('.protection-status')).to_have_text('Ainda não foi possível confirmar')
            shot('old-backend'); state['places'], state['sources'] = kept
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible(timeout=8000)
            ok('backend anterior ainda carregado: nada aparece como confirmado')

            # 9. Keyboard, focus, sizes, long text, zoom.
            backup = panel().get_by_role('button', name='Fazer backup agora')
            backup.focus(); page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.textContent') == 'Recuperar minhas notas'
            assert page.evaluate('getComputedStyle(document.activeElement).outlineStyle') != 'none'
            page.keyboard.press('Shift+Tab')
            assert page.evaluate('document.activeElement.textContent') == 'Fazer backup agora'
            page.keyboard.press('Tab'); page.keyboard.press('Enter')
            expect(panel().locator('details', has=page.locator('summary', has_text='Recuperar minhas notas'))).to_have_attribute('open', '')
            assert page.evaluate('document.activeElement.textContent') == 'Ver minhas cópias salvas'
            summary = panel().locator('summary', has_text='Segurança e chave mestra')
            summary.focus(); page.keyboard.press('Space')
            assert summary.evaluate('(e)=>e.parentElement.open')
            page.keyboard.press('Enter'); assert not summary.evaluate('(e)=>e.parentElement.open')
            panel().locator('summary', has_text='Recuperar minhas notas').click()
            ok('teclado: Tab, Shift+Tab, Enter, Espaço e foco visível')
            assert panel().evaluate("(e)=>getComputedStyle(e.querySelector('.protection-step progress, progress')||document.body).animationName") in ('none', '')
            page.set_viewport_size({'width': 760, 'height': 600}); fits(); top(); shot('small')
            state['config']['local'] = r'D:\Uma pasta com um nome realmente longo para backups\Subpasta com mais um nome comprido\Lumen - Protecao do cerebro'
            panel().locator('summary', has_text='Detalhes técnicos e pasta').click()
            expect(panel().locator('.protection-details')).to_contain_text(state['config']['local'], timeout=8000)
            fits(); shot('long-path')
            panel().locator('summary', has_text='Detalhes técnicos e pasta').click()
            ok('janela menor, títulos e caminhos longos sem rolagem horizontal')
            for scale in (1.25, 1.5):
                page.set_viewport_size({'width': 1120, 'height': 860})
                page.evaluate('(scale)=>document.documentElement.style.zoom=scale', scale)
                fits(); top(); shot(f'zoom-{scale}')
            page.evaluate("document.documentElement.style.zoom=''")
            ok('zoom de navegador 125% e 150%')
            main_texts = panel().locator('.protection-hero h3, .protection-place .protection-status').all_inner_texts()

            # 10. Widget: same states, same component.
            page.goto(url + '/widget'); page.evaluate("document.body.dataset.expanded='true'")
            page.locator('#settings').click(force=True); page.locator('[data-category="protection"]').click()
            no_selection_panel()
            expect(panel().get_by_role('heading', name='Suas cópias estão em dia')).to_be_visible()
            assert panel().locator('.protection-hero h3, .protection-place .protection-status').all_inner_texts() == main_texts
            assert page.locator('.notch').bounding_box()['height'] == 540
            fits(); shot('widget')
            expect(panel().locator('.protection-types li')).to_have_count(3)
            panel().locator('.protection-types').scroll_into_view_if_needed(); fits(); shot('widget-types')
            wsec = panel().locator('details.protection-issues')
            wsec.locator('summary').first.click()
            expect(wsec.locator('.protection-count')).to_have_text(' · 7 para conferir', timeout=8000)
            assert wsec.locator('.protection-notice h4').all_inner_texts() == main_notice_titles
            wsec.locator('.protection-notice').first.locator('summary', has_text='Ver as 6 notas').click()
            wsec.evaluate("(s)=>s.scrollIntoView({block:'start'})"); fits(); shot('widget-attention')
            wsec.locator('.protection-notice').nth(1).evaluate("(s)=>s.scrollIntoView({block:'start'})"); shot('widget-attention-2')
            wsec.locator('summary').first.click()
            ok('widget e janela principal mostram os mesmos estados e os mesmos avisos')
            state['places'], state['sources'] = personal_like()
            expect(panel().get_by_role('heading', name='Há backups, mas falta atualizar')).to_be_visible(timeout=8000)
            fits(); shot('widget-previous-copy')
            panel().locator('.protection-places').first.scroll_into_view_if_needed(); shot('widget-places')
            state['state']['operation'] = {'id': 'request-widget', 'status': 'running', 'started': T3, 'steps': {'obsidian': {'status': 'done'}}}
            state['activity'] = {'notion': {'stage': 'reading'}}
            expect(panel().get_by_role('heading', name='Guardando suas notas…')).to_be_visible(timeout=8000)
            page.evaluate('renderPreferences()')
            expect(panel().get_by_role('button', name='Fazendo backup…')).to_be_disabled()
            panel().locator('.protection-activity').scroll_into_view_if_needed(); shot('widget-working')
            page.set_viewport_size({'width': 320, 'height': 400})
            for edge in ('left', 'right', 'top', 'bottom'):
                page.evaluate('(edge)=>{document.body.dataset.edge=edge;document.body.dataset.side=edge==="right"?"right":"left";}', edge)
                box = page.locator('.notch').bounding_box()
                assert box['width'] <= 320 and box['height'] <= 400 and box['x'] >= 0 and box['y'] >= 0, box
                fits()
            shot('widget-clamped'); ok('widget limitado nas quatro bordas')
            assert not {'roots', 'page-titles'}.intersection(posted), posted
            assert state['config']['roots'] == [iid] and state['config']['vault'] == r'D:\TESTE\cofre'
            ok('sem consultas de títulos nem alteração de raízes; seleção persistida preservada na janela e widget')
            assert not errors, errors
            browser.close()
        report.update(passed=True, requests=counts['now'], opened=[x['place'] for x in opened])
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        proc.terminate(); proc.wait(timeout=10)
