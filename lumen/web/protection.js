/* Shared by main settings and widget. Secrets never enter the DOM.
   Every state shown comes from /api/protection: "places" holds one code per destination, derived by the backend
   from persisted receipts. This file only turns codes into words; it never upgrades a code to success. */
(() => {
  const host=document.querySelector('[data-protection]'); if(!host)return;
  const node=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
  const icon=name=>{const e=document.createElementNS('http://www.w3.org/2000/svg','svg');e.setAttribute('aria-hidden','true');e.classList.add('i');const use=document.createElementNS(e.namespaceURI,'use');use.setAttribute('href',`/icons.svg#${name}`);e.append(use);return e;};
  const glyph=(svg,name)=>{const use=svg.firstChild;if(use.getAttribute('href')!==`/icons.svg#${name}`)use.setAttribute('href',`/icons.svg#${name}`);};
  const put=(e,text)=>{if(e.textContent!==text)e.textContent=text;};
  const request=async(body,path='/api/protection')=>{
    const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Lumen-Token':document.querySelector('meta[name="lumen-token"]').content},...(body?{body:JSON.stringify(body)}:{})});
    const value=await response.json();if(!response.ok)throw Error([value.error?.message,value.error?.action].filter(Boolean).join(' ')||'Não conseguimos atender este pedido. Tente novamente.');return value;
  };
  let data,starting=false,repository='',external=false,timer,lastAnnouncement='',revision=0,refreshSerial=0,feedbackOperation=null;
  const pending=new Set(), feedback=node('p','','protection-feedback'),connection=node('p','','protection-feedback'),announce=node('p','','protection-sr');
  feedback.setAttribute('role','status');connection.setAttribute('role','status');announce.setAttribute('role','status');announce.setAttribute('aria-live','polite');announce.setAttribute('aria-atomic','true');
  const act=async(b,fn,success='')=>{
    if(pending.has(b))return;const issued=++revision;pending.add(b);b.disabled=true;feedback.textContent='';
    try{const r=await fn();feedback.textContent=r?.cancelled?'Escolha cancelada.':r?.verified?`${r.files} arquivos recuperados em uma nova pasta: ${r.path}`:r?.pages?`${r.pages} páginas recuperadas no Notion.${r.limitations?.length?' Algumas partes precisam ser conferidas.':''}`:r?.notice||success;feedbackOperation=r?.notice&&r?.state?.operation?.status==='running'?r.state.operation.id:null;const shown=feedback.textContent;if(r?.notice&&!r?.state)setTimeout(()=>{if(feedback.textContent===shown)feedback.textContent='';},10000);if(r?.config&&issued===revision)render({...data,...r});await refresh();}
    catch(e){feedback.textContent=e.message;}
    finally{pending.delete(b);b.disabled=false;if(data)render(data);}
  };
  const button=(text,fn,success='',cls='')=>{const b=node('button',text,`btn sm protection-button ${cls}`);b.type='button';b.addEventListener('click',()=>act(b,fn,success));return b;};
  const action=name=>()=>request({action:name});
  const disclosure=title=>{const d=node('details','','protection-disclosure');d.append(node('summary',title));return d;};
  // The three lower sections are cards: icon, short title, tag and one line of purpose are visible before opening.
  // `body` holds the content, so callers append to `card.body`; the <details> element itself keeps open/focus behaviour.
  const card=(title,{symbol,tone,badge,hint})=>{
    const d=node('details','','protection-disclosure protection-card-disclosure'),head=node('summary'),mark=node('span','','protection-card-icon'),text=node('span','','protection-card-text'),line=node('span','','protection-card-title'),chevron=icon('chevron-down');
    d.dataset.tone=tone;mark.append(icon(symbol));chevron.classList.add('protection-card-chevron');line.append(node('span',title,'protection-card-name'),node('span',badge,'protection-card-badge'));text.append(line,node('span',hint,'protection-card-hint'));
    head.append(mark,text,chevron);d.body=node('div','','protection-card-body');d.append(head,d.body);return d;
  };
  const open=section=>{section.open=true;section.scrollIntoView({block:'nearest',behavior:'instant'});};
  const moment=value=>{if(!value)return '';const date=new Date(value),now=new Date(),yesterday=new Date(now);yesterday.setDate(now.getDate()-1);const day=date.toDateString()===now.toDateString()?'hoje':date.toDateString()===yesterday.toDateString()?'ontem':date.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});return `${day} às ${date.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}`;};
  const bytes=value=>value>=1048576?`${(value/1048576).toLocaleString('pt-BR',{maximumFractionDigits:1})} MB`:`${Math.ceil(value/1024).toLocaleString('pt-BR')} KB`;
  const sourceName=name=>name==='obsidian'?'Obsidian':name==='notion'?'Notion':'notas';
  // Internal wording (tool names, exit codes) stays in the details; the common view gets a plain sentence.
  const plain=message=>!message||/restic|snapshot|c[óo]digo \d|http|\b[a-f0-9]{16,}\b/i.test(message)?'A última tentativa não terminou.':message;
  const placeNames={local:'Neste computador',drive:'Google Drive',notion_obsidian:'Notion → Obsidian',obsidian_notion:'Obsidian → Notion'};
  const placeHints={notion_obsidian:'Páginas do Notion no seu cofre',obsidian_notion:'Notas do Obsidian no Notion'};
  const ORIGINS={local:['obsidian','notion'],drive:['obsidian','notion'],notion_obsidian:['notion'],obsidian_notion:['obsidian']};
  const STATES={ok:['Cópia confirmada','Notas atualizadas','check-circle'],checking:['Conferindo alterações',null,'sync'],copying:['Copiando agora',null,'sync'],queued:['Aguardando a vez neste backup',null,'clock'],
    first:['Aguardando a primeira cópia',null,'clock'],behind:['Cópia anterior disponível; atualização pendente','Versão anterior disponível; atualização pendente','clock'],
    attention:['Precisa de atenção',null,'alert'],unavailable:['Destino indisponível',null,'x-circle'],disabled:['Desativado por você',null,'info'],unknown:['Ainda não foi possível confirmar',null,'question'],setup:['Falta configurar',null,'info']};
  const SETUP={local:'Falta escolher a pasta',drive:'Falta conectar sua conta do Google',notion_obsidian:'Falta conectar o Notion e o cofre',obsidian_notion:'Falta conectar o Notion'};
  const stateText=(id,code)=>code==='setup'?SETUP[id]:(STATES[code]||STATES.unknown)[ORIGINS[id].length===1&&STATES[code]?.[1]?1:0];
  // An older backend sends no drive_enabled: its Drive copy is on, so only an explicit false means off.
  const driveOn=v=>v.config.drive_enabled!==false;
  const allSettled=v=>Object.keys(placeNames).every(id=>['ok','disabled'].includes(v.places?.[id]?.state));
  const toggleDrive=async()=>{const on=driveOn(data),r=await request({action:'drive-enable',enabled:!on}),notice=on?'Backup no Google Drive desativado. As cópias que já estão lá continuam guardadas.':'Backup no Google Drive ativado. O envio começa em instantes.';setTimeout(()=>{if(feedback.textContent===notice)feedback.textContent='';},10000);return {...r,notice};};
  const stageName=(id,stage)=>stage==='checking'?'Conferindo as cópias…':stage==='saving'?'Salvando uma cópia…':stage==='reading'?'Procurando alterações…':id==='drive'?'Enviando para o Google Drive…':id==='local'?'Guardando neste computador…':'Copiando suas notas…';
  const STEPS=[['obsidian','Ler o Obsidian'],['notion','Ler o Notion'],['local','Guardar neste computador'],['drive','Enviar ao Google Drive'],['notion_obsidian','Atualizar Notion → Obsidian'],['obsidian_notion','Atualizar Obsidian → Notion']];

  host.append(node('h2','Proteção do cérebro','t-h2'),node('p','Cópias das suas notas, para quando você precisar.','protection-intro'));
  const hero=node('section','','protection-hero'),emblem=node('span','','protection-emblem'),emblemIcon=icon('shield'),heroText=node('div'),title=node('h3','Conferindo suas cópias…'),explanation=node('p'),nextStep=node('p','','protection-next');
  hero.setAttribute('aria-label','Situação das cópias');emblem.append(emblemIcon);heroText.append(title,explanation,nextStep);hero.append(emblem,heroText);host.append(hero);
  const help=button('',()=>help.resolve());help.hidden=true;help.classList.add('protection-help');heroText.append(help);
  const actions=node('div','','protection-actions');
  const backup=button('Fazer backup agora',async()=>{if(starting||data?.state.operation?.status==='running')return;starting=true;render(data);try{return await request({action:'now'});}finally{starting=false;}},'','primary');
  backup.disabled=true;
  const recover=button('Recuperar minhas notas',()=>{open(recovery);loadLocal.focus();});actions.append(backup,recover);host.append(actions);
  const backupReason=node('p','','protection-reason');backupReason.id='protection-backup-reason';backupReason.hidden=true;host.append(backupReason);
  const schedule=node('div','','protection-schedule');
  const automatic=button('Backup automático: pausado',async()=>{const on=!data.config.enabled,r=await request({action:on?'start':'pause'});return {...r,notice:on?'As próximas cópias serão feitas automaticamente.':r.state?.operation?.status==='running'?'Backup automático pausado. A cópia que você pediu continua.':'Backup automático pausado. Suas cópias continuam guardadas.'};},'','protection-automatic');automatic.disabled=true;
  const scheduleNote=node('span','','protection-schedule-note');schedule.append(automatic,scheduleNote);
  const lastRun=node('p','','protection-last');lastRun.hidden=true;
  host.append(schedule,lastRun,connection,feedback,announce);
  const resultNote=node('p','','protection-note');resultNote.hidden=true;host.append(resultNote);

  // A requested backup shows its six persisted steps; automatic work shows only what is running now.
  const activity=node('section','','protection-activity'),activityTitle=node('h3','','protection-activity-title'),activityHint=node('p','','protection-note'),steps=node('ol','','protection-steps'),stepRows=new Map();
  activity.setAttribute('aria-label','Andamento do backup');activity.hidden=true;activity.append(activityTitle,activityHint,steps);host.append(activity);
  const progressFor=(box)=>{const detail=node('small'),bar=node('progress');bar.setAttribute('aria-label','Atividade do backup');box.append(detail,bar);return {detail,bar};};
  function showProgress(row,info,label){
    const known=info?.scope==='file'&&info.unit==='bytes'&&info.total>0&&info.done<info.total;row.bar.hidden=!info;row.detail.hidden=!info;if(!info)return;
    if(known){row.bar.max=info.total;row.bar.value=info.done;row.bar.setAttribute('aria-label','Envio do arquivo atual ao Google Drive');put(row.detail,`Arquivo atual: ${bytes(info.done)} de ${bytes(info.total)}. O backup continua após este arquivo.`);}
    else{row.bar.removeAttribute('value');row.bar.removeAttribute('max');row.bar.setAttribute('aria-label',label);put(row.detail,info.unit==='bytes'?'Conferindo o arquivo enviado…':info.done!=null?`${info.done.toLocaleString('pt-BR')} ${info.unit==='pages'?'páginas conferidas':'arquivos conferidos'}`:'');}
  }

  host.append(node('h3','Backups para recuperar suas notas','protection-section-title'),
    node('p','Versões completas e criptografadas, para recuperar suas notas mesmo se o original se perder.','protection-group-note'));
  const places=node('div','','protection-places'),mirrors=node('div','','protection-places'),rows={};let toggleNode;
  for(const [id,symbol] of [['local','folder'],['drive','upload'],['notion_obsidian','obsidian'],['obsidian_notion','page']]){
    const row=node('section','','protection-place'),symbolNode=node('span','','protection-place-icon'),content=node('div','','protection-place-text'),heading=node('h4',placeNames[id]);
    const status=node('p','','protection-status'),statusIcon=icon('question'),statusText=node('span'),lines=node('ul','','protection-origins'),date=node('small','','protection-date'),reason=node('small','','protection-reason');
    reason.id=`protection-reason-${id}`;status.append(statusIcon,statusText);symbolNode.append(icon(symbol));
    if(placeHints[id])heading.append(node('span',placeHints[id],'protection-place-hint'));
    const lineNodes=[node('li'),node('li')];lines.append(...lineNodes);
    content.append(heading,status,lines,date,reason);
    if(id==='drive'){const toggle=button('',toggleDrive,'','protection-drive-toggle');toggle.dataset.part='drive-toggle';content.append(toggle,node('small','O espaço gratuito do Google Drive é limitado, e as cópias ocupam esse espaço. Desligar não desconecta sua conta e não apaga as cópias que já estão lá.','protection-drive-note'));toggleNode=toggle;}
    const contextual=button('',()=>rows[id].resolve());contextual.classList.add('protection-link');row.dataset.place=id;row.append(symbolNode,content,contextual);(id==='local'||id==='drive'?places:mirrors).append(row);
    rows[id]={row,status,statusIcon,statusText,lineNodes,date,reason,button:contextual,resolve:()=>{}};
  }
  host.append(places,node('h3','Notas para consultar no outro aplicativo','protection-section-title'),
    node('p','Cópias para ler e navegar. Elas não substituem o backup: alguns dados e formatos originais só ficam nele.','protection-group-note'),mirrors);

  // Static explanation of the three kinds of copy; it states what each is for and never reports a state.
  const types=node('section','','protection-types'),typesTitle=node('h3','Para que serve cada cópia','protection-types-title'),typeList=node('ul');
  typesTitle.id='protection-types-title';types.setAttribute('aria-labelledby',typesTitle.id);
  for(const [symbol,name,text] of [['folder','Neste computador','Recuperação completa em caso de desastre, com criptografia Restic e histórico de versões. Não depende de internet.'],
    ['upload','Google Drive','Cópia externa criptografada, para o caso de o computador se perder ou falhar. Opcional: desligue para economizar espaço.'],
    ['obsidian','Espelhamento Notion ↔ Obsidian','Leitura e consulta das notas no dia a dia, nos dois aplicativos. Não substitui o backup completo, principalmente dos anexos.']]){
    const li=node('li');li.append(icon(symbol),node('h4',name),node('p',text));typeList.append(li);
  }
  types.append(typesTitle,typeList);host.append(types);

  // "O que precisa de atenção": one notice per cause, ordered by need. Note-level notices come from the "attention"
  // action and reload whenever attention_key changes or the section is opened; stale answers are dropped by serial.
  const issues=disclosure('O que precisa de atenção'),issuesCount=node('span','','protection-count'),issueIntro=node('p','','protection-issues-intro'),issueStatus=node('p','','protection-issues-status'),noticeList=node('div','','protection-notices');
  const kept=disclosure(''),keptList=node('ul','','protection-notice-list');kept.classList.add('protection-kept');kept.hidden=true;kept.append(node('p','Guardadas intactas na pasta Versões preservadas do seu cofre. A nota atual de cada uma já está organizada.','protection-note'),keptList);
  issueStatus.setAttribute('role','status');issues.querySelector('summary').append(issuesCount);issues.classList.add('protection-issues');issues.append(issueIntro,issueStatus,noticeList,kept);host.append(issues);
  let notes=null,noteKey=null,noteSerial=0,notesAt=null,notesFailed=false,lastPlaceItems=[];
  const noticeNodes=new Map(),keptKey={value:''};
  const PLACE_ICONS={local:'folder',drive:'upload',notion_obsidian:'obsidian',obsidian_notion:'page'};
  const TONES={action:['Precisa de ação','alert'],review:['Para conferir','search'],wait:['Aguardando','clock']};
  const PLURAL={icon:['páginas têm um ícone que não pôde ser incluído','O texto dessas páginas foi lido. Só os ícones ficaram de fora.'],
    unsupported:['páginas têm partes que o Notion não disponibiliza','O restante foi lido. Essas partes só podem ser vistas no próprio Notion.'],
    attachment:['páginas têm arquivos que não puderam ser baixados','O restante dessas páginas foi lido. Confira os arquivos no Notion.'],
    deleted:['páginas não estão mais disponíveis no Notion','A última leitura de cada uma foi mantida.'],
    missing:['páginas não apareceram na última leitura','O Lúmen não supõe que foram excluídas. As leituras anteriores foram mantidas.'],
    read:['páginas não puderam ser lidas por completo','As leituras anteriores foram mantidas.'],
    difference:['notas estão diferentes da última cópia','O Lúmen manteve os arquivos como estão, sem sobrescrever nada. Compare quando puder.'],
    structure:['páginas têm uma página acima sem acesso','A parte conhecida está na pasta Estrutura a conferir.'],
    'notion-copy':['notas não foram copiadas por completo para o Notion','As notas originais continuam no seu cofre do Obsidian.'],
    'notion-attachment':['notas têm anexos que não couberam no Notion','As páginas foram criadas no Notion sem esses anexos.']};
  const locate=path=>()=>request({action:'open-place',place:'notion_obsidian',path});
  const noteAction=item=>({'notion-page':['Abrir no Notion',()=>request({action:'open-place',place:'source',path:item.page})],locate:['Localizar nota',locate(item.path)],
    'notion-area':['Ver notas no Notion',()=>request({action:'open-place',place:'obsidian_notion'})],'connect-notion':['Conferir conexão do Notion',connectNotion]})[item.action];
  const fullBackup=()=>{backup.click();return null;};
  function noticeElement(n){
    const [toneText,toneIcon]=TONES[n.tone],el=node('article','','protection-notice'),mark=node('span','','protection-notice-icon'),body=node('div','','protection-notice-body');
    el.dataset.tone=n.tone;mark.append(icon(n.icon||toneIcon));body.append(node('p',toneText,'protection-notice-tone'),node('h4',n.headline));
    if(n.list?.length>1)body.append(node('p',n.summary,'protection-notice-summary'));
    if(n.list?.length>1){const list=node('ul','','protection-notice-list');for(const [i,entry] of n.list.entries()){const li=node('li');li.append(icon('page'),node('span',entry.title));if(entry.act){const b=button(entry.act[0],entry.act[1],'','protection-link');b.dataset.part='item-'+i;b.setAttribute('aria-label',`${entry.act[0]}: ${entry.title}`);li.append(b);}list.append(li);}
      if(n.list.length>4){const more=disclosure(`Ver as ${n.list.length} notas`);more.classList.add('protection-more');more.dataset.part='list';more.append(list);body.append(more);}else body.append(list);}
    else if(n.subject){const subject=node('p','','protection-notice-subject');subject.append(icon(n.subjectIcon||'page'),node('span',n.subject));body.append(subject);}
    if(!(n.list?.length>1))body.append(node('p',n.summary,'protection-notice-summary'));
    const row=node('div','','protection-notice-actions');
    if(n.act){const b=button(n.act[0],n.act[1]);b.dataset.part='action';if(n.backup)b.dataset.backup='true';if(n.subject)b.setAttribute('aria-label',`${n.act[0]}: ${n.subject}`);row.append(b);}
    if(n.details?.length){const more=disclosure('Ver detalhes');more.classList.add('protection-more');more.dataset.part='details';more.querySelector('summary').dataset.part='details-summary';for(const text of n.details)more.append(node('p',text));row.append(more);}
    if(row.childElementCount)body.append(row);
    el.append(mark,body);return el;
  }
  function renderNotices(list){
    const wanted=new Set(list.map(n=>n.key));
    for(const [key,entry] of noticeNodes)if(!wanted.has(key)){entry.el.remove();noticeNodes.delete(key);}
    list.forEach((n,i)=>{
      let entry=noticeNodes.get(n.key);const sig=JSON.stringify(n,(k,v)=>typeof v==='function'?undefined:v);
      if(!entry||entry.sig!==sig){
        const el=noticeElement(n);
        if(entry){// same notice, new content: keep what the person opened and where the focus was
          for(const d of entry.el.querySelectorAll('details[data-part]'))if(d.open){const twin=el.querySelector(`details[data-part="${d.dataset.part}"]`);if(twin)twin.open=true;}
          const focused=entry.el.contains(document.activeElement)&&document.activeElement.dataset.part;entry.el.replaceWith(el);
          if(focused)el.querySelector(`[data-part="${focused}"]`)?.focus({preventScroll:true});}
        entry={el,sig};noticeNodes.set(n.key,entry);
      }
      if(noticeList.children[i]!==entry.el)noticeList.insertBefore(entry.el,noticeList.children[i]||null);
    });
  }
  function noteNotices(){
    const groups=new Map();
    for(const item of notes||[]){if(item.tone==='info')continue;const key=item.cause;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
    return [...groups].map(([cause,items])=>{const one=items[0],many=items.length>1,act=!many&&noteAction(one);
      return {key:'note:'+cause,tone:'review',headline:many?`${items.length} ${PLURAL[cause]?.[0]||'notas precisam de conferência'}`:one.headline,subject:many?'':one.title,
        summary:many?(PLURAL[cause]?.[1]||one.summary):one.summary,details:[...new Set(items.flatMap(item=>item.details||[]))],act:act||null,count:items.length,
        list:many?items.map(item=>({title:item.title,act:noteAction(item)})):null};});
  }
  function renderIssues(v,working){
    const placeItems=placeIssueItems(v,working),noted=noteNotices(),all=[...placeItems.filter(n=>n.tone==='action'),...noted,...placeItems.filter(n=>n.tone==='wait')];
    lastPlaceItems=placeItems;renderNotices(all);
    for(const b of noticeList.querySelectorAll('[data-backup]'))b.disabled=working||!v.config.local||pending.has(b);
    const act=placeItems.filter(n=>n.tone==='action').length,review=noted.reduce((sum,n)=>sum+n.count,0),wait=placeItems.some(n=>n.tone==='wait');
    put(issuesCount,act||review?` · ${[act?`${act} ${act===1?'precisa':'precisam'} de ação`:'',review?`${review} para conferir`:''].filter(Boolean).join(' · ')}`:'');
    put(issueIntro,act?'Comece pelo primeiro aviso: ele precisa de você.':review?'Nada impede as cópias. Os avisos abaixo são para conferir quando puder.':wait?'Nenhuma ação necessária agora. O Lúmen está terminando uma atualização.':notes===null&&!notesFailed?'Conferindo os avisos…':'Nenhuma ação necessária.');
    put(issueStatus,notesFailed?(notesAt?`Não conseguimos atualizar os avisos das notas. Mostrando a consulta de ${moment(notesAt)}; vamos tentar de novo.`:'Não conseguimos consultar os avisos das notas agora. Vamos tentar de novo em instantes.'):notes===null?'Conferindo os avisos das notas…':'');issueStatus.hidden=!issueStatus.textContent;
    const preserved=(notes||[]).filter(item=>item.tone==='info'),key=JSON.stringify(preserved.map(x=>[x.title,x.path]));
    kept.hidden=!preserved.length;
    if(keptKey.value!==key){keptKey.value=key;put(kept.querySelector('summary'),preserved.length===1?'1 versão antiga preservada · nenhuma ação necessária':`${preserved.length} versões antigas preservadas · nenhuma ação necessária`);
      keptList.replaceChildren(...preserved.map(item=>{const li=node('li');const b=button('Localizar',locate(item.path),'','protection-link');b.setAttribute('aria-label',`Localizar ${item.title}`);li.append(icon('page'),node('span',item.title),b);return li;}));}
  }
  async function loadIssues(){
    const serial=++noteSerial;
    try{const r=await request({action:'attention'});if(serial!==noteSerial)return r;notes=r.items.map((x,i)=>x.cause?x:{...x,cause:'legacy-'+i,tone:x.kind==='preserved'?'info':'review',headline:x.description||x.title,subject:x.title,summary:x.saved||'',details:[x.next].filter(Boolean),action:x.page?'notion-page':x.path?'locate':null});notesAt=new Date().toISOString();notesFailed=false;return r;}
    catch(e){if(serial===noteSerial){notesFailed=true;noteKey=null;}return null;}// the next refresh tries again; never a backup failure
    finally{if(serial===noteSerial&&data)renderIssues(data,isWorking(data));}
  }
  function showIssues(){open(issues);}  // opening fires "toggle", which reloads the notices
  issues.addEventListener('toggle',()=>{if(issues.open)loadIssues();});
  const connectNotion=()=>{const target=document.querySelector('#nav-integrations')||document.querySelector('[data-category="notion"]');if(target)target.click();return {notice:'Confira a conexão do Notion e o acesso às páginas escolhidas.'};};
  const connectDrive=()=>request({},'/api/drive/login');

  const security=card('Segurança e chave mestra',{symbol:'key',tone:'warning',badge:'Criptografia',hint:'Sua chave secreta para abrir backups em outro computador.'}),keyText=node('p','','protection-note');security.body.append(node('p','Sua chave permite abrir as cópias em outro computador. Guarde-a separada do backup.','protection-note'),keyText,button('Guardar minha chave de recuperação',action('export-key'),'Chave guardada no lugar escolhido.','primary'),button('Usar uma chave que já tenho',async()=>{const r=await request({action:'import-key'});if(!r.cancelled)external=true;return r;},'Chave conferida e pronta para uso.','secondary'));host.append(security);
  const options=card('Detalhes técnicos e pasta',{symbol:'gear',tone:'neutral',badge:'Ajustes',hint:'Caminho da pasta, espaço em disco e histórico de diagnósticos.'}),technical=node('dl','','protection-details'),detailValues={},storage=node('p','','protection-note'),choose=button('Trocar a pasta das cópias',action('choose'),'Pasta escolhida. A cópia anterior foi preservada.','secondary');
  for(const [key,label] of Object.entries({local:'Pasta das cópias',vault:'Cofre do Obsidian',request:'Último pedido de backup',reads:'Última leitura das notas',localDate:'Última confirmação neste computador',driveDate:'Última confirmação no Drive',problems:'Mensagens das últimas tentativas'})){
    const row=node('div'),value=node('dd','Conferindo…');row.append(node('dt',label),value);technical.append(row);detailValues[key]=value;
  }
  options.body.append(technical,storage,node('p','Todas as versões são mantidas. Nenhuma cópia é apagada automaticamente para liberar espaço.','protection-note'),choose,button('Abrir pasta das cópias',action('open'),'','secondary'),button('Conectar Google Drive',connectDrive,'Conclua a conexão na janela que abriu.','secondary'));host.append(options);
  const recovery=card('Recuperar minhas notas',{symbol:'download',tone:'accent',badge:'Restauração',hint:'Restaure cópias anteriores em uma nova pasta, sem tocar nas notas atuais.'}),versions=node('select');versions.hidden=true;versions.setAttribute('aria-label','Cópia salva para recuperar');recovery.body.append(node('p','Escolha a origem e a data. O Lúmen cria uma pasta nova; suas notas atuais ficam como estão.','protection-note'));
  async function loadVersions(other=false){const r=await request({action:'versions',external:other});if(r.cancelled)return r;repository=r.repository;external=other;versions.replaceChildren(...r.versions.map(v=>new Option(`${sourceName((v.tags||[]).find(x=>x==='obsidian'||x==='notion'))} · ${new Date(v.time).toLocaleString('pt-BR')}`,v.id)));versions.hidden=!r.versions.length;restoreLocal.hidden=!r.versions.length;recoveryLocation.textContent=r.location||'';return {...r,notice:r.versions.length?'Escolha a origem e a data da cópia abaixo.':'Ainda não encontramos uma cópia salva neste lugar.'};}
  const recoveryLocation=node('p','','protection-note'),loadLocal=button('Ver minhas cópias salvas',()=>loadVersions(false),'','primary'),restoreLocal=button('Recuperar a cópia escolhida',()=>{if(!versions.value)throw Error('Primeiro escolha uma cópia salva.');return request({action:'recover',snapshot:versions.value,repository,external});},'','primary');restoreLocal.hidden=true;recovery.body.append(loadLocal,recoveryLocation,versions,restoreLocal);
  const cloud=node('select');cloud.hidden=true;cloud.setAttribute('aria-label','Cópia do Google Drive para recuperar');const restoreCloud=button('Recuperar do Drive',()=>{if(!cloud.value)throw Error('Primeiro escolha uma cópia do Drive.');return request({action:'recover',drive_id:cloud.value,external});},'','primary');restoreCloud.hidden=true;recovery.body.append(button('Procurar minhas cópias no Drive',async()=>{const r=await request({action:'drive-catalogs'});cloud.replaceChildren(...r.catalogs.map((v,i)=>new Option(`${sourceName(v.name.includes('obsidian')?'obsidian':'notion')} · ${v.createdTime?new Date(v.createdTime).toLocaleString('pt-BR'):`cópia ${i+1}`}`,v.id)));cloud.hidden=!r.catalogs.length;restoreCloud.hidden=!r.catalogs.length;return {...r,notice:r.catalogs.length?'Escolha a origem e a data da cópia abaixo.':'Ainda não encontramos cópias no Drive.'};},'','secondary'),cloud,restoreCloud);
  const otherRecovery=disclosure('Outra pasta ou computador');otherRecovery.append(node('p','Para uma cópia de outro computador, use a chave correspondente em Segurança e recuperação.','protection-note'),button('Abrir uma cópia de outro lugar',()=>loadVersions(true),'','secondary'),button('Recuperar no Notion',action('rebuild-notion'),'','secondary'));recovery.body.append(otherRecovery);host.insertBefore(recovery,security);
  host.append(node('p','O Lúmen precisa estar aberto para guardar novas alterações.','protection-footnote'));

  // What a step says while nothing is running for it. Only persisted receipts and live activity are used: a destination
  // is "in sync" only when its place code is ok, never because it merely is not busy.
  function idleStep(id,v,live){
    const place=v.places?.[id],src=v.sources?.[id],reading=['obsidian','notion'].some(o=>live[o]);
    if(id==='obsidian'||id==='notion')return src?.failed?['failed','A última leitura não terminou']:src?.read?['done','Leitura mais recente concluída']:['waiting','Aguardando a primeira leitura'];
    if(!place)return ['waiting','Conferindo…'];
    if(place.state==='ok')return ['done',id==='drive'?'Sincronizado na nuvem':'Em dia'];
    if(place.state==='attention')return ['failed','Precisa de atenção'];
    if(place.state==='unavailable')return ['failed',id==='drive'?'Sem conexão com o Google Drive':'Destino indisponível'];
    if(place.state==='setup')return ['waiting',SETUP[id]];
    if(reading)return ['queued','Aguardando a conclusão da leitura das notas…'];
    return ['queued',id==='drive'?'Na fila para sincronizar…':'Na fila para atualizar…'];
  }
  function renderActivity(v,working){
    const op=v.state.operation||{},requested=op.status==='running'||starting,live=v.activity||{};activity.hidden=!working;if(!working)return;
    // The same six steps are listed for a requested and an automatic backup, so a worker that is waiting is still visible.
    const items=STEPS.map(([id,label])=>[id,label]);
    for(const [id,row] of stepRows)if(!items.some(([key])=>key===id)){row.box.remove();stepRows.delete(id);}
    put(activityTitle,requested?(op.started?`Backup pedido ${moment(op.started)}`:'Backup pedido'):'Guardando alterações');
    const started=Object.keys(op.steps||{}).length||Object.keys(live).length;
    put(activityHint,requested&&!started?'Pedido recebido. O trabalho começa em instantes.':requested?'Cada etapa só aparece como concluída depois de confirmada.':'O backup automático está guardando alterações recentes.');
    const sourcesRead=['obsidian','notion'].every(x=>op.steps?.[x]);
    for(const [id,label] of items){
      if(!stepRows.has(id)){const box=node('li','','protection-step'),mark=icon('dot'),text=node('div'),name=node('span','','protection-step-name'),stateLine=node('span','','protection-step-state');text.append(name,stateLine);box.append(mark,text);const row={box,mark,name,stateLine,...progressFor(text)};steps.append(box);stepRows.set(id,row);}
      const row=stepRows.get(id),step=op.steps?.[id],info=live[id];let code,text,shown=label;
      if(id==='drive'&&!driveOn(v)){code='off';text='Desativado nas configurações (não consome cota)';shown='Google Drive';}
      else if(info){code='working';text=stageName(id,info.stage);}
      else if(requested&&step?.status==='done'){code='done';text='Concluído';}
      else if(requested&&step?.status==='partial'){code='partial';text='Concluído com pendências';}
      else if(requested&&step?.status==='failed'){code='failed';text='Não concluído';}
      else if(requested){code='waiting';text=!['obsidian','notion'].includes(id)&&!sourcesRead?'Aguardando as leituras':'Na fila';}
      else [code,text]=idleStep(id,v,live);
      row.box.dataset.state=code;glyph(row.mark,{done:'check-circle',partial:'alert',failed:'x-circle',working:'sync',waiting:'dot',queued:'clock',off:'pause'}[code]);
      put(row.name,shown);put(row.stateLine,text);
      showProgress(row,code==='working'?info||{}:null,`${shown}: ${text}`);
    }
  }
  function placeLines(id,place,v){
    const sources=v.sources||{},held=place.held||{};
    if(id==='local'||id==='drive')return ORIGINS[id].map(o=>{const h=held[o],newest=sources[o]?.version;
      if(!h)return `${sourceName(o)}: ainda não guardado aqui`;
      return `${sourceName(o)}: versão de ${moment(h.version)}${id==='drive'&&h.objects?` · ${h.objects.toLocaleString('pt-BR')} objetos confirmados`:''}${!h.newest&&newest?` · falta copiar a de ${moment(newest)}`:sources[o]?.unsaved?' · há alterações lidas aguardando cópia':''}`;});
    const o=ORIGINS[id][0],h=held[o],count=place.items;
    const what=id==='notion_obsidian'?(count!=null?`${count.toLocaleString('pt-BR')} páginas${place.organized?' organizadas em páginas e subpáginas':''}`:'Páginas do Notion'):(count!=null?`${count.toLocaleString('pt-BR')} notas do Obsidian`:'Notas do Obsidian');
    return [h?what:'',h?`Reflete o ${sourceName(o)} de ${moment(h.version)}${!h.newest&&sources[o]?.version?` · falta a versão de ${moment(sources[o].version)}`:''}`:''];
  }
  function placeAction(id,place,v){
    const link=place.link,code=place.state;
    if(id==='local'){if(!v.config.local)return ['Escolher pasta',action('choose'),''];return ['Abrir pasta',()=>request({action:'open-place',place:id}),link?'':'O disco da pasta escolhida não está disponível agora.'];}
    if(id==='drive'){const folder=['Abrir pasta no Drive',()=>request({action:'open-place',place:id}),''];
      if(code==='disabled')return link?folder:['Ativar',toggleDrive,''];
      if(!v.drive?.connected)return ['Conectar',connectDrive,''];return link?folder:['Abrir pasta no Drive',folder[1],'Ainda não há uma cópia confirmada no Drive.'];}
    if(!v.notion_connected&&!link)return ['Conectar o Notion',connectNotion,''];
    return ['Ver notas',()=>request({action:'open-place',place:id}),link?'':code==='setup'?'Escolha o cofre do Obsidian nas configurações do Obsidian.':'As notas aparecem aqui depois da primeira cópia.'];
  }
  function overview(v,working){
    const P=v.places||{},src=v.sources||{},s=v.state,op=s.operation||{},codes=Object.values(P).map(x=>x.state);
    const where=o=>['local','drive'].filter(p=>P[p]?.state!=='disabled'&&P[p]?.held?.[o]),label=list=>list.length===2?'neste computador e no Google Drive':list[0]==='local'?'neste computador':'no Google Drive';
    const [wo,wn]=[where('obsidian'),where('notion')];
    const coverage=!wo.length&&!wn.length?'Ainda não há backup recuperável das suas notas.':wo.join()===wn.join()?`Obsidian e Notion têm backup ${label(wo)}.`:
      `${wo.length?`O Obsidian tem backup ${label(wo)}`:'O Obsidian ainda não tem backup'}; ${wn.length?`o Notion tem backup ${label(wn)}`:'o Notion ainda não tem backup'}.`;
    const capturePending=src.notion?.pending||0,sourceFailed=['obsidian','notion'].filter(o=>src[o]?.failed);
    const trouble=codes.some(c=>c==='attention'||c==='unavailable')||sourceFailed.length>0,behind=codes.some(c=>['behind','first','unknown'].includes(c));
    const allOk=allSettled(v);
    const next=[];let help=null,tone='neutral',headline;
    if(working){headline='Guardando suas notas…';tone='working';return {headline,detail:'Você pode continuar usando o Lúmen. As cópias são feitas em segundo plano.',next:'',tone,help};}
    // A window can load this file from disk while the running Lúmen still has the previous backend.
    if(!v.places)return {headline:'Reabra o Lúmen para ver cada cópia',detail:'O Lúmen aberto ainda usa a versão anterior desta tela. Suas cópias não foram afetadas.',next:'Saia pelo menu do Lúmen e abra de novo.',tone:'neutral',help:null};
    if(!v.config.local){headline='Vamos escolher onde guardar suas cópias';next.push('Escolha uma pasta para começar.');help=['Escolher pasta',action('choose')];}
    else if(!v.config.vault||(!v.config.roots?.length&&v.config.discover===false)){headline='Falta conferir as origens das notas';tone='attention';}
    else if(op.status==='failed'){headline='O último backup não terminou';tone='attention';}
    else if(!wo.length&&!wn.length&&!trouble){headline=v.notion_connected&&(v.drive?.connected||!driveOn(v))?'Pronto para fazer a primeira cópia':'Precisamos da sua ajuda';}
    else if(trouble){headline='Uma parte precisa de atenção';tone='attention';}
    else if(allOk&&!capturePending){headline=op.outcome==='unchanged'&&op.status==='completed'?'Nenhuma alteração para guardar':'Suas cópias estão em dia';tone='ready';}
    else if(allOk){headline='Cópias em dia, com partes do Notion a conferir';tone='attention';}
    else if(codes.includes('setup')&&!behind)headline='Falta configurar um destino';
    else headline=wo.length&&wn.length?'Há backups, mas falta atualizar':`Falta guardar o ${wo.length?'Notion':'Obsidian'}`;
    if(v.config.local&&!v.notion_connected){next.push('Conecte o Notion em Integrações para guardar suas páginas.');help=help||['Conectar o Notion',connectNotion];}
    if(!v.config.vault)next.push('Escolha seu cofre nas configurações do Obsidian.');
    if(!v.config.roots?.length&&v.config.discover===false)next.push('Confira a página principal nas configurações do Notion.');
    if(v.config.local&&driveOn(v)&&!v.drive?.connected){next.push('Conecte o Google Drive para ter uma cópia fora deste computador.');help=help||['Conectar Google Drive',connectDrive];}
    if(trouble||op.status==='failed'){next.push('Veja o que aconteceu e o que fazer.');help=help||['Ver o que falta',showIssues];}
    if(v.config.local&&behind&&!trouble)next.push(v.config.enabled?'O backup automático guarda as alterações enquanto o Lúmen estiver aberto.':!wo.length&&!wn.length?'Clique em Fazer backup agora para fazer a primeira cópia.':'Clique em Fazer backup agora para guardar a versão mais recente.');
    if(capturePending){next.push(`Confira ${capturePending===1?'uma parte':`${capturePending} partes`} que o Notion não entrega por completo.`);help=help||['Ver o que falta',showIssues];}
    if(v.config.local&&!next.length)next.push('Nada a fazer agora.');
    return {headline,detail:v.config.local?coverage:'As cópias ficam numa pasta deste computador e, se você quiser, também no Google Drive.',next:next.join(' '),tone,help};
  }
  function placeIssueItems(v,working){
    const P=v.places||{},src=v.sources||{},items=[],paused=!v.config.enabled,op=v.state.operation||{};
    const last=place=>{const dates=Object.values(place?.held||{}).map(h=>h.confirmed).filter(Boolean).sort();return dates.length?moment(dates.at(-1)):'';};
    const retryText='Refazer backup completo',retryDetail='Isso refaz o backup inteiro: lê o Obsidian e o Notion e confere todos os destinos, sem apagar cópias anteriores.';
    if(working)return items;
    for(const o of ['obsidian','notion'])if(src[o]?.failed)items.push({key:'source:'+o,tone:'action',headline:`Não conseguimos ler o ${sourceName(o)}`,subject:sourceName(o),subjectIcon:o==='obsidian'?'obsidian':'page',
      summary:o==='notion'?'Confira a conexão do Notion. As versões já guardadas não foram alteradas.':'Confira se o cofre está acessível. As versões já guardadas não foram alteradas.',
      details:[plain(src[o].message),retryDetail],act:o==='notion'?['Conferir conexão do Notion',connectNotion]:[retryText,fullBackup],backup:o!=='notion'});
    for(const [id,place] of Object.entries(P)){const when=last(place);
      if(place.state==='unavailable')items.push({key:'place:'+id,tone:'action',icon:'x-circle',headline:'Destino indisponível',subject:placeNames[id],subjectIcon:PLACE_ICONS[id],
        summary:id==='local'?'A pasta das cópias não está acessível. Conecte o disco escolhido.':id==='drive'?'A conexão com o Google Drive não está ativa.':'A conexão com o Notion não está ativa.',
        details:[when?`A última cópia confirmada aqui foi ${when}.`:'Ainda não há cópia confirmada aqui.',id==='local'?'O Lúmen não cria uma pasta substituta.':''].filter(Boolean),
        act:id==='drive'?['Conectar Google Drive',connectDrive]:id==='local'?null:['Conferir conexão do Notion',connectNotion]});
      else if(place.state==='attention'&&!place.conflicts&&!(place.own_pending&&!place.message)){
        const localOk=id==='drive'&&P.local?.state==='ok';
        items.push({key:'place:'+id,tone:'action',headline:'A última cópia não terminou',subject:placeNames[id],subjectIcon:PLACE_ICONS[id],
          summary:localOk?'A cópia neste computador foi confirmada. Falta terminar o envio ao Drive.':when?`A cópia anterior, de ${when}, continua registrada aqui.`:'Ainda não há cópia confirmada aqui.',
          details:[plain(place.message),id==='local'?'Confira se o disco está conectado e tem espaço.':id==='drive'?'Confira a internet ou a conta do Google Drive.':'Confira a conexão do Notion.',retryDetail],act:[retryText,fullBackup],backup:true});}}
    const failedSteps=Object.entries(op.steps||{}).filter(([,x])=>x.status==='failed').map(([id])=>STEPS.find(([k])=>k===id)?.[1]).filter(Boolean);
    if(op.status==='failed'&&!items.length)items.push({key:'request',tone:'action',headline:'O último backup não terminou',subject:'',
      summary:failedSteps.length?`Não concluído: ${failedSteps.join(', ')}.`:'O pedido terminou sem confirmar as cópias.',details:[retryDetail],act:[retryText,fullBackup],backup:true});
    const late=Object.entries(P).filter(([,x])=>x.state==='behind').map(([id])=>placeNames[id]);
    if(late.length)items.push({key:'behind',tone:paused?'action':'wait',icon:'clock',headline:'Alterações ainda não copiadas',subject:late.join(', '),subjectIcon:'folder',
      summary:paused?'As versões anteriores continuam registradas. Faça um backup para levar as mais recentes.':'O backup automático leva as alterações enquanto o Lúmen estiver aberto.',
      details:paused?['O backup automático está pausado. Fazer backup agora não muda essa preferência.']:[],act:paused?['Fazer backup agora',fullBackup]:null,backup:true});
    return items;
  }
  const isWorking=v=>starting||v.state.operation?.status==='running'||Object.keys(v.activity||{}).length>0;
  function render(v){
    if(!v)return;data=v;const s=v.state,op=s.operation||{},working=starting||op.status==='running'||Object.keys(v.activity||{}).length>0;
    if(feedbackOperation&&(op.id!==feedbackOperation||op.status!=='running')){feedback.textContent='';feedbackOperation=null;}
    put(backup,working?'Fazendo backup…':'Fazer backup agora');backup.disabled=working||!v.config.local||pending.has(backup);backup.setAttribute('aria-busy',String(working));
    put(backupReason,!v.config.local?'Escolha uma pasta antes do primeiro backup.':'');backupReason.hidden=!backupReason.textContent;
    if(backupReason.textContent)backup.setAttribute('aria-describedby',backupReason.id);else backup.removeAttribute('aria-describedby');
    choose.disabled=working||pending.has(choose);put(automatic,`Backup automático: ${v.config.enabled?'ligado':'pausado'}`);automatic.disabled=pending.has(automatic);automatic.setAttribute('aria-pressed',String(v.config.enabled));
    put(scheduleNote,v.config.enabled?'Copia as alterações enquanto o Lúmen está aberto.':'Só copia quando você pede. As cópias guardadas continuam valendo.');
    const view=overview(v,working);put(title,view.headline);put(explanation,view.detail);put(nextStep,view.next);nextStep.hidden=!view.next;
    hero.dataset.working=String(working);hero.dataset.tone=view.tone;glyph(emblemIcon,{working:'sync',attention:'alert',ready:'check-circle'}[view.tone]||'shield');
    help.hidden=!view.help;if(view.help){put(help,view.help[0]);help.resolve=view.help[1];}
    const finished=!working&&op.finished&&({completed:op.outcome==='unchanged'?'concluído, sem alterações novas':'concluído',partial:'concluído com pendências',failed:'não concluído'})[op.status];
    put(lastRun,finished?`Último backup pedido: ${finished} (${moment(op.finished)}).`:'');lastRun.hidden=!finished;
    renderActivity(v,working);
    const newer=op.status==='completed'&&s.versions?.some(version=>op.targets?.[version.source]&&s.versions.filter(x=>x.source===version.source).at(-1)?.id!==op.targets[version.source]);
    const allOk=allSettled(v);
    resultNote.hidden=!newer||allOk;put(resultNote,newer?'O backup que você pediu terminou. Há novas alterações para guardar.':'');
    const relevant=working?`${op.id||'automatic'}:${Object.entries(op.steps||{}).map(([id,x])=>id+':'+x.status).sort().join(',')}:${Object.entries(v.activity||{}).map(([id,x])=>id+':'+x.stage).sort().join(',')}`:`${op.id||'initial'}:${op.status||view.headline}`;
    if(relevant!==lastAnnouncement){lastAnnouncement=relevant;if(op.id||starting)announce.textContent=working?view.headline+' '+Object.entries(v.activity||{}).map(([id,x])=>stageName(id,x.stage)).filter((x,i,a)=>a.indexOf(x)===i).join(' '):view.headline;}
    for(const [id,row] of Object.entries(rows)){
      const place=v.places?.[id]||{state:'unknown',held:{},link:true},code=place.state,[label,fn,why]=placeAction(id,place,v);
      row.row.dataset.state=code;glyph(row.statusIcon,STATES[code]?.[2]||'question');put(row.statusText,stateText(id,code));
      placeLines(id,place,v).forEach((text,i)=>{if((code==='setup'||code==='disabled')&&!Object.keys(place.held||{}).length)text='';put(row.lineNodes[i],text);row.lineNodes[i].hidden=!text;});
      const mirror=ORIGINS[id].length===1,date=place.confirmed&&code!=='setup'?`${mirror?'Última atualização':'Última confirmação'}: ${moment(place.confirmed)}`:'';
      put(row.date,date);row.date.hidden=!date;
      put(row.button,label);row.resolve=fn;row.button.hidden=label===help.textContent&&!help.hidden;
      const blocked=!!why||working&&id==='local'&&label==='Escolher pasta';row.button.disabled=blocked||pending.has(row.button);put(row.reason,why);row.reason.hidden=!why;
      if(why)row.button.setAttribute('aria-describedby',row.reason.id);else row.button.removeAttribute('aria-describedby');
    }
    const on=driveOn(v);put(toggleNode,on?'Desativar backup no Drive':'Ativar backup no Google Drive');toggleNode.setAttribute('aria-pressed',String(on));toggleNode.disabled=pending.has(toggleNode);
    if(v.attention_key!==noteKey){noteKey=v.attention_key;loadIssues();}
    renderIssues(v,working);
    put(keyText,s.key_exported?'Você já guardou uma chave de recuperação. Mantenha-a em um lugar seguro.':v.has_key?'Sua chave já está protegida neste Windows. Guarde uma cópia para usar em outro computador.':'A chave será preparada quando você fizer a primeira cópia ou guardar sua chave.');
    put(storage,`Histórico: ${bytes(v.bytes)}. Espaço livre neste computador: ${(v.free/1073741824).toFixed(1)} GB.${s.local?.free!=null?` Na pasta das cópias: ${(s.local.free/1073741824).toFixed(1)} GB.`:''}${v.same_device?` As notas e a cópia local estão no mesmo disco. ${driveOn(v)?'A cópia no Drive ajuda se esse disco falhar.':'Ative o backup no Google Drive para ter uma cópia fora deste computador.'}`:''}`);
    const date=value=>value?new Date(value).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'}):'Ainda não confirmada';
    const lastRequest=({running:'Em andamento',completed:op.outcome==='unchanged'?'Conferido, sem novas alterações':'Concluído',partial:'Terminou com pendências',failed:'Não foi possível concluir'})[op.status]||'Nenhum pedido registrado';
    const reads=['obsidian','notion'].map(o=>v.sources?.[o]?.read?`${sourceName(o)} ${moment(v.sources[o].read)}`:'').filter(Boolean).join(' · ')||'Ainda não houve leitura';
    const problems=[...['obsidian','notion'].filter(o=>v.sources?.[o]?.failed).map(o=>`${sourceName(o)}: ${v.sources[o].message}`),...Object.entries(v.places||{}).filter(([,x])=>x.message).map(([id,x])=>`${placeNames[id]}: ${x.message}`)].join(' ')||'Nenhuma';
    const readable={local:v.config.local||'Pasta ainda não escolhida',vault:v.config.vault||'Cofre ainda não escolhido',request:lastRequest+(op.finished?` · ${date(op.finished)}`:''),reads,localDate:date(s.local?.confirmed),driveDate:date(s.drive?.confirmed),problems};
    for(const [key,value] of Object.entries(readable))put(detailValues[key],value);
  }
  async function refresh(){clearTimeout(timer);const serial=++refreshSerial,issued=revision;try{const value=await request();if(serial===refreshSerial&&issued===revision){render(value);connection.textContent='';}}catch{if(serial===refreshSerial&&issued===revision)connection.textContent='Não conseguimos atualizar esta tela. Vamos tentar de novo. O backup pode continuar em segundo plano.';}finally{if(serial===refreshSerial)timer=setTimeout(()=>{if(host.checkVisibility())refresh();else later();},data?.state.operation?.status==='running'?1500:5000);}}
  function later(){clearTimeout(timer);timer=setTimeout(()=>{if(host.checkVisibility())refresh();else later();},5000);}
  new MutationObserver(()=>{if(host.checkVisibility())refresh();}).observe(host.parentElement,{attributes:true,attributeFilter:['hidden']});refresh();
})();
