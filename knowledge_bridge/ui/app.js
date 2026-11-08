'use strict';
const $ = id => document.getElementById(id);
const TRAMA_PREVIEW_CHECK_ON_OPEN = false; // Build script enables only for isolated Preview.
const escapeHTML = value => String(value??'').replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const app={view:'lessons',tab:'Nota completa',snapshot:null,note:null,selected:null,filter:'',listFilter:'all',aiConsent:false,graphView:null};
let bridge=null;
const categories={lessons:'02-Minhas-Aulas',knowledge:'01-Meu-Conhecimento',projects:'03-Meus-Projetos'};
const titles={lessons:'Minhas Aulas',knowledge:'Meu Conhecimento',projects:'Meus Projetos',library:'Biblioteca do Obsidian'};
const friendlyKinds={visao_geral:'Visão geral',aula:'Gravação',conceito:'Conceito',pessoa:'Pessoa',projeto:'Projeto',modulo:'Módulo'};
const friendlyStates={fontes_organizadas:'Fontes organizadas',aguardando_ia:'Aguardando resumo',resumida_com_ia:'Resumo gerado',sem_transcricao:'Sem transcrição'};
const prettyLesson=v=>String(v||'').replace(/^Aula-(\d+)$/i,(_,n)=>'Aula '+n);

const stripMarkup = s => String(s||'').replace(/\[\[([^\]]+)\]\]/g,(_,v)=>v.split('|').at(-1)).replace(/\*\*/g,'').replace(/`/g,'').replace(/^[-*] /gm,'• ');
function empty(msg){return `<p class="empty-text">${escapeHTML(msg)}</p>`;}
function notify(message,wait=5500){
 $('status-message').textContent=message;
 const toast=$('toast');toast.textContent=message;toast.classList.remove('hidden');
 toast.dataset.kind=/\\b(falha|erro|inválid|não foi possível|indisponível|corrompid)/i.test(message)?'error':
   /\\b(concluído|adicionado|criado|salvo|sucesso|copiado|restaurado)/i.test(message)?'success':'info';
 clearTimeout(notify.timer);notify.timer=setTimeout(()=>toast.classList.add('hidden'),wait);
}
let confirmationActive=false;
function askTramaConfirm(title,description,acceptLabel='Continuar'){
 const dialog=$('trama-confirm-dialog');
 if(!dialog||confirmationActive)return Promise.resolve(false);
 confirmationActive=true;
 $('trama-confirm-title').textContent=title;
 $('trama-confirm-description').textContent=description;
 $('trama-confirm-accept').textContent=acceptLabel;
 return new Promise(resolve=>{
  let finished=false;
  const yes=$('trama-confirm-accept'),no=$('trama-confirm-cancel'),close=$('trama-confirm-close');
  function finish(accepted){
   if(finished)return;finished=true;
   yes.removeEventListener('click',onYes);no.removeEventListener('click',onNo);
   close.removeEventListener('click',onNo);dialog.removeEventListener('cancel',onCancel);
   if(dialog.open){if(typeof dialog.close==='function')dialog.close();else dialog.removeAttribute('open');}
   confirmationActive=false;resolve(accepted);
  }
  const onYes=()=>finish(true),onNo=()=>finish(false);
  const onCancel=event=>{event.preventDefault();finish(false);};
  yes.addEventListener('click',onYes);no.addEventListener('click',onNo);
  close.addEventListener('click',onNo);dialog.addEventListener('cancel',onCancel);
  if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','');
 });
}
async function call(name,...args){if(!bridge||typeof bridge[name]!=='function'){notify('Conecte o aplicativo TRAMA.');return null;}try{return await bridge[name](...args);}catch(e){notify('Falha ao executar: '+String(e).slice(0,160));return null;}}
async function refresh(){const data=await call('snapshot');if(!data)return;app.snapshot=data;libraryState.favorites=new Set(data.favorites||[]);document.body.classList.toggle('connected',!!data.connected);$('connect-state').textContent=data.connected?'Obsidian conectado':'Configure o cofre do Obsidian';const s=data.stats||{};$('status-counts').textContent=`▤ ${s.notes||0} notas   │   ▶ ${s.videos||0} vídeos   │   ▤ ${s.transcriptions||0} transcrições   │   ▰ ${s.materials||0} materiais   │   ▱ ${s.repositories||0} projetos`;
 document.querySelector('.status-version').textContent='TRAMA v2.2.3  │  '+(data.connected?'Obsidian conectado':'Sem cofre selecionado');
 if(!data.connected){app.note=null;app.selected=null;}
 renderNavigation();await render();}
function getNotes(){const notes=app.snapshot?.notes||[];let matches=notes;
 if(categories[app.view])matches=notes.filter(n=>n.section===categories[app.view]);
 if(app.view==='lessons'){
   const overviews=new Set(matches.filter(n=>n.kind==='visao_geral').map(n=>n.lesson));
   matches=matches.filter(n=>!n.lesson||n.kind==='visao_geral'||!overviews.has(n.lesson));
 }

 if(app.filter){const q=app.filter.toLowerCase();matches=matches.filter(n=>(n.title+' '+n.id+' '+n.lesson).toLowerCase().includes(q));}
 if(app.listFilter==='favorites'){matches=matches.filter(n=>libraryState.favorites.has(n.id));}
 if(app.listFilter==='recent'){matches=[...matches].sort((a,b)=>{
  // Bridge returns the actual date in pt-BR (DD/MM/YYYY). Date.parse
  // cannot parse days > 12 consistently, so sort these explicitly.
  const timestamp=n=>{
    const value=String(n.updated||'');
    const br=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
    return br?Date.UTC(+br[3],+br[2]-1,+br[1]):(Date.parse(value)||0);
  };
  return timestamp(b)-timestamp(a)||a.id.localeCompare(b.id);
 }).slice(0,20);}
 return matches;
}
function renderNavigation(){document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.view===app.view));}
async function setView(view){app.view=view;app.filter='';app.listFilter='all';app.tab=view==='lessons'?'Nota completa':'Resumo';$('search-all').value='';$('list-search').value='';renderNavigation();await render();}
async function render(){if(app.view!=='graph'&&app.graphView){app.graphView.destroy();app.graphView=null;}if(!app.snapshot)return;if(app.view==='library'){await renderLibraryView();return;}if(['graph','home','settings','teacher'].includes(app.view)){renderOverlay();return;}
 $('library-workspace').classList.add('hidden');$('overlay-screen').classList.add('hidden');$('list-panel').classList.remove('hidden');$('note-panel').classList.remove('hidden');$('details-panel').classList.remove('hidden');
 $('list-title').textContent=titles[app.view]||'Minha Biblioteca';
 document.querySelectorAll('[data-list-filter]').forEach(btn=>btn.classList.toggle('active',btn.dataset.listFilter===app.listFilter));
 $('btn-context').style.display=app.view==='lessons'?'':'none';
  $('btn-lesson-code').style.display=app.view==='lessons'?'':'none';
 $('list-search').placeholder=app.view==='lessons'?'Buscar aulas...':'Buscar notas...';
 const notes=getNotes();if(!notes.some(n=>n.id===app.selected))app.selected=notes[0]?.id||null;
 renderList(notes);if(app.selected){app.note=await call('note',app.selected);}else app.note=null;
 renderNote();renderRight();}
function renderList(notes){const container=$('items');container.replaceChildren();
 if(!notes.length){container.innerHTML=empty('Nenhuma nota encontrada. Importe seus materiais para começar.');return;}
 if(app.view==='library'&&!app.filter){renderTree(notes,container);return;}
 const heading=document.createElement('div');heading.className='group-heading';heading.textContent=app.view==='lessons'?'AULAS DISPONÍVEIS':'NOTAS DO COFRE';container.append(heading);
 for(const n of notes){const btn=document.createElement('button');btn.type='button';btn.className='lesson-row'+(n.id===app.selected?' selected':'');
 btn.innerHTML=`<span class="lesson-dot"></span><span class="lesson-row-body"><strong class="lesson-name">${escapeHTML(prettyLesson(n.lesson)||n.title).slice(0,120)}</strong><span class="lesson-descr">${escapeHTML(n.lesson?n.title.replace(n.lesson+' — ',''):n.id.split('/').at(-1).replace('.md','')).slice(0,160)}</span><span class="lesson-date">${escapeHTML(n.updated||'')}</span></span>`;
 btn.addEventListener('click',async()=>{app.selected=n.id;app.tab=n.kind==='visao_geral'?'Nota completa':'Resumo';await render();});container.append(btn);}
}
function renderTree(notes,target){const root={folders:new Map(),notes:[]};for(const n of notes){let cur=root;const segments=n.id.split('/');segments.pop();for(const folder of segments){if(!cur.folders.has(folder))cur.folders.set(folder,{folders:new Map(),notes:[]});cur=cur.folders.get(folder);}cur.notes.push(n);}
 const renderNode=(node,parent,level)=>{for(const [name,child] of node.folders){const wrap=document.createElement('details');wrap.open=level<1||[...child.notes].some(n=>n.id===app.selected);wrap.className='folder-group';wrap.style.marginLeft=(level*9)+'px';const title=document.createElement('summary');title.textContent='📁  '+name.replace(/^\d\d-/,'').replaceAll('-',' ');wrap.append(title);renderNode(child,wrap,level+1);parent.append(wrap);}
 for(const n of node.notes){const btn=document.createElement('button');btn.type='button';btn.className='tree-note'+(app.selected===n.id?' selected':'');btn.textContent='▤  '+n.title;btn.addEventListener('click',async()=>{app.selected=n.id;await render();});parent.append(btn);}};
 renderNode(root,target,0);
}
function renderNote(){const n=app.note;if(!n||n.error){$('note-heading').innerHTML='<div class="breadcrumb">Seu Obsidian</div><h1 class="note-title">Comece sua biblioteca</h1><p class="empty-text">Escolha uma pasta do Obsidian ou importe uma transcrição para visualizar os conteúdos.</p>';$('note-tabs').replaceChildren();$('note-content').innerHTML=empty('Suas notas aparecerão aqui, sem duplicar arquivos.');return;}
 const head=$('note-heading');const title=(n.lesson?n.title.replace(/^Aula-\d+\s+—\s+/,''):n.title);
 head.innerHTML=`<div class="breadcrumb">◈ &nbsp; ${escapeHTML(app.view==='lessons'?'Aulas':app.view==='knowledge'?'Meu Conhecimento':app.view==='projects'?'Meus Projetos':'Obsidian')} &nbsp; › &nbsp; ${escapeHTML(n.lesson||n.id.split('/').at(-1))}</div><h1 class="note-title">${escapeHTML(title)}</h1><div class="note-meta">▦ &nbsp; Arquivo atualizado em ${escapeHTML(n.updated)} &nbsp; · &nbsp; Origem: Obsidian Vault</div><div class="note-chips"><span class="chip">✓ &nbsp; ${escapeHTML(friendlyStates[n.state]||n.state?.replaceAll('_',' ')||'Nota no Obsidian')}</span><span class="chip blue">▤ &nbsp; ${escapeHTML(friendlyKinds[n.kind]||n.kind)}</span>${n.lesson?`<span class="chip blue">${escapeHTML(n.lesson)}</span>`:''}</div>`;
 const tabs=app.view==='lessons'?['Resumo','Nota completa','Markdown',`Vídeos (${(n.media?.video?.length||0)+(n.media?.video_links?.length||0)})`,'Transcrição','Conferência','Relacionados']:['Resumo','Nota completa','Markdown','Relacionados'];
 $('note-tabs').replaceChildren();for(const raw of tabs){const name=raw.startsWith('Vídeos')?'Vídeos':raw;const button=document.createElement('button');button.className='tab'+(app.tab===name?' active':'');button.textContent=raw;button.addEventListener('click',()=>{app.tab=name;document.querySelectorAll('#note-tabs .tab').forEach(x=>x.classList.toggle('active',x===button));renderNoteBody();});$('note-tabs').append(button);}renderNoteBody();}
function card(heading,body,kind=''){return `<article class="info-card ${kind}"><h3><span class="card-icon">${kind==='summary'?'▤':'✧'}</span>${escapeHTML(heading)}</h3>${body}</article>`;}
function paragraphs(s){if(!s)return empty('Ainda não há informações suficientes.');const lines=stripMarkup(s).split('\n').map(x=>x.trim()).filter(Boolean);return lines.map(x=>`<p>${escapeHTML(x)}</p>`).join('');}
function renderNoteBody(){const n=app.note;if(!n)return;const box=$('note-content');box.replaceChildren();
 if(app.tab==='Nota completa'){
   box.innerHTML=`<div class="note-source-banner">Visualização da mesma nota Markdown do Obsidian. Para ver edições recentes, clique em Atualizar.</div>${libRenderMarkdown(n.content,n.id,n.title)}`;
   box.querySelectorAll('[data-lib-note]').forEach(el=>el.addEventListener('click',async(e)=>{
      e.preventDefault();libraryState.search='';app.selected=el.dataset.libNote;app.view='library';app.note=await call('note',app.selected);await render();
   }));
   box.querySelectorAll('[data-lib-code]').forEach(link=>link.addEventListener('click',async()=>{
     const result=await call('open_code_link',link.dataset.libCode);
     if(!result?.ok)notify(result?.message||'Não foi possível abrir esta referência.');
   }));
   box.querySelectorAll('[data-lib-external]').forEach(link=>link.addEventListener('click',async()=>{
     const result=await call('open_video_link',link.dataset.libExternal);
     if(!result?.ok)notify(result?.message||'Abra este material diretamente no Obsidian.');
   }));
   return;
 }
 if(app.tab==='Markdown'){const pre=document.createElement('pre');pre.className='note-markdown';pre.textContent=n.content;box.append(pre);return;}

 if(app.tab==='Vídeos'){const files=n.media?.video||[],urls=n.media?.video_links||[];const rows=[...urls.map((x,i)=>fileRow('↗',x.label,'Link externo · sem cópia do vídeo','Abrir vídeo','video_links',i)),...files.map((x,i)=>fileRow('▶',x.label,'Vídeo local de versão anterior','Abrir','video',i))];box.innerHTML=card('Gravações da aula',rows.length?rows.join(''):empty('Cadastre o título e o link do vídeo em Aulas → Contexto +. Não é necessário baixar o vídeo.'));wireFiles();return;}
 if(app.tab==='Transcrição'){
   const files=n.media?.transcript||[];
   box.innerHTML=card('Transcrições originais',files.length?
     files.map((x,i)=>fileRow('▤',x.label,'Transcrição salva no cofre','Abrir','transcript',i)).join(''):
     empty('Nenhuma transcrição cadastrada.'))+
     (files.length?card('Pesquisar transcrição (local, sem IA)',
       '<p>Encontre palavras e horários da transcrição original sem consumir a API.</p>'+
       '<div class="transcript-find"><input id="transcript-query" maxlength="160" placeholder="Ex.: terminal, SDK, dotnet" aria-label="Termo da transcrição"/>'+
       '<button id="transcript-search" type="button">Pesquisar</button></div>'+
       '<div id="transcript-search-results" role="status" aria-live="polite"></div>'):'');
   wireFiles();
   const button=box.querySelector('#transcript-search');
   if(button){
     const input=box.querySelector('#transcript-query');
     const results=box.querySelector('#transcript-search-results');
     const search=async()=>{
       const term=input.value.trim();
       if(!term){results.textContent='Digite um termo para pesquisar.';return;}
       results.textContent='Pesquisando apenas nos arquivos locais…';button.disabled=true;
       try{
         const found=[];
         for(const file of files.slice(0,4)){
           const response=await call('search_transcript',file.stored,term);
           if(response?.ok && response.excerpt)found.push({file,response});
         }
         results.replaceChildren();
         if(!found.length){results.textContent='Nenhum trecho encontrado. Tente outra grafia ou expressão.';return;}
         for(const {file,response} of found){
           const label=document.createElement('strong');label.textContent=file.label;results.append(label);
           const excerpt=document.createElement('pre');excerpt.className='transcript-find-excerpt';
           excerpt.textContent=response.excerpt;results.append(excerpt);
           const open=document.createElement('button');open.type='button';open.textContent='Abrir original';
           open.addEventListener('click',()=>call('open_attachment',file.stored));results.append(open);
         }
       }finally{button.disabled=false;}
     };
     button.addEventListener('click',search);
     input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();search();}});
   }
   return;
 }
 if(app.tab==='Conferência'){
   box.innerHTML=card('Conferência local das fontes', '<p>Verificando transcrições, horários e referências no Obsidian…</p>');
   call('audit_note',n.id).then(result=>{
      if(!app.note||app.note.id!==n.id||app.tab!=='Conferência')return;
      if(!result?.ok){box.innerHTML=card('Conferência das fontes',empty(result?.message||'Não foi possível conferir esta nota.'));return;}
      const c=result.contagens||{},rows=[
        `Transcrições preservadas: ${c.arquivos_integros||0}/${c.transcricoes||0}`,
        `Gravações com resumo de IA: ${c.com_resumo||0}/${c.transcricoes||0}`,
        `Contextos do Classroom: ${c.contextos||0}`,
        `Horários informados pela IA e encontrados no TXT: ${c.horarios_validos||0}`,
        `Menções com horário recuperado localmente: ${c.horarios_recuperados_txt||0}`,
        `Trechos para conferir: ${c.referencias_duvidosas||0}`,
        `Links de gravações: ${c.videos_links||0}`];
      box.innerHTML=card('Conferência local das fontes',
        '<p><strong>Este teste não usa Gemini e não comprova a interpretação da IA.</strong></p>'+
        '<ul>'+rows.map(v=>`<li>${escapeHTML(v)}</li>`).join('')+'</ul>')+
        card('Pendências e limites','<ul>'+(result.pendencias||[]).map(v=>`<li>${escapeHTML(v)}</li>`).join('')+'</ul>');
   });return;
 }
 if(app.tab==='Relacionados'){box.innerHTML=card('Conhecimentos relacionados',n.related.length?n.related.map((x,i)=>`<button class="simplelink" data-related="${i}">↗ &nbsp; ${escapeHTML(x.title)}</button>`).join(''):empty('Ainda não existem conexões confirmadas entre esta nota e outras.'));wireRelations();return;}
 // Technical and people profiles are not lesson summaries: show the actual
 // linked evidence instead of empty "Principais conceitos" placeholders.
 if(app.tab==='Resumo'&&(n.kind==='conceito'||n.kind==='pessoa')){
   const heading=n.kind==='conceito'?'Explicações e fontes das aulas':'Menções nas aulas';
   box.innerHTML=card(heading,n.summary?libRenderMarkdown(n.summary,n.id,n.title):
     empty('Ainda não há referências verificáveis nesta nota.'),'summary');
   box.querySelectorAll('[data-lib-note]').forEach(el=>el.addEventListener('click',async event=>{
     event.preventDefault();libraryState.search='';
     const anchor=el.dataset.libAnchor||'';
     app.selected=el.dataset.libNote;app.view='library';
     app.note=await call('note',app.selected);await render();
     if(/^min-(?:\d+-)*\d+$/.test(anchor)){
       const target=$('library-workspace').querySelector('#'+anchor);
       if(target)target.scrollIntoView({block:'center',behavior:'auto'});
     }
   }));
   return;
 }
 let html=card('Resumo da aula',paragraphs(n.summary),'summary');
 const lessonPending=n.state==='aguardando_ia' ||
   (n.kind==='visao_geral' && n.content.includes('**Pendente:**'));
 if(n.lesson && (n.kind==='aula' || (n.kind==='visao_geral' && (n.media?.transcript||[]).length))){
   const pending=lessonPending;
   html+=card(pending?'Resumo pendente':'Revisar análise da aula',
     '<p>'+(pending?
       'A transcrição está salva, mas o resumo por IA ainda não foi gerado.':
       'Você pode refazer a análise desta aula se encontrou erros na transcrição ou nos conceitos.')+
     '</p><button id="refresh-this-lesson" type="button">'+
     (pending?'Gerar resumo desta aula':'Reanalisar somente esta aula')+'</button>');
 }
 html+=card('Principais conceitos',n.concepts?paragraphs(n.concepts):empty('Os conceitos aparecem aqui quando houver análise. Consulte também a Nota completa.'));
 if(n.examples)html+=card('Exemplos mencionados',paragraphs(n.examples));
 const vids=n.media?.video||[],urls=n.media?.video_links||[],trans=n.media?.transcript||[];
 const links=[...trans.map((x,i)=>fileRow('▤',x.label,'Transcrição original','Abrir','transcript',i)),...urls.map((x,i)=>fileRow('↗',x.label,'Gravação vinculada por URL','Abrir','video_links',i)),...vids.map((x,i)=>fileRow('▶',x.label,'Vídeo local de versão anterior','Abrir','video',i))];
 html+=card('Materiais e links',links.length?`<div class="card-rows">${links.join('')}</div>`:empty('Os materiais associados aparecerão aqui.'));
 box.innerHTML=html;wireFiles();
 const update=box.querySelector('#refresh-this-lesson');
 if(update)update.addEventListener('click',async()=>{
   const action=lessonPending?'Gerar resumos pendentes':'Refazer análise completa';
   if(!app.aiConsent && !await askTramaConfirm(action,
     lessonPending?`Apenas as gravações e trechos pendentes de ${n.lesson} serão enviados à API. Os resumos existentes serão reaproveitados.`:
     `Esta ação refaz os resumos de ${n.lesson} e volta a consumir a cota da API. As fontes e notas editadas permanecem protegidas.`,action))return;
   update.disabled=true;update.textContent='Processando esta aula…';
   try{
     const result=await call('process_lesson',n.lesson,true,!lessonPending);
     if(!result?.ok){
       let status=box.querySelector('#lesson-ai-feedback');
       if(!status){status=document.createElement('p');status.id='lesson-ai-feedback';
         status.className='trama-ai-feedback';status.setAttribute('role','status');
         update.insertAdjacentElement('afterend',status);}
       status.textContent=result?.message||'Análise pendente. Confira o diagnóstico em Ajustes.';
       notify('Análise pausada. Consulte a explicação nesta tela.',8000);
       return;
     }
     notify(lessonPending?'Resumos pendentes concluídos.':'Aula reanalisada. As notas foram atualizadas.',7000);
     await refresh();
   }finally{update.disabled=false;}
 });}
function fileRow(icon,title,detail,cta,kind,i){return `<div class="resource-row"><span class="resource-icon">${icon}</span><span class="resource-text"><strong>${escapeHTML(title)}</strong><small>${escapeHTML(detail)}</small></span><button class="row-open" data-file-kind="${kind}" data-file-idx="${i}">${cta} ↗</button></div>`;}
function wireFiles(){document.querySelectorAll('[data-file-kind]').forEach(el=>el.addEventListener('click',async()=>{const kind=el.dataset.fileKind,media=app.note?.media?.[kind]?.[Number(el.dataset.fileIdx)];if(media)await call(kind==='video_links'?'open_video_link':'open_attachment',kind==='video_links'?media.url:media.stored);}));}
function wireRelations(){document.querySelectorAll('[data-related]').forEach(el=>el.addEventListener('click',async()=>{libraryState.search='';app.selected=app.note.related[Number(el.dataset.related)].id;app.view='library';await render();}));}
function detail(title,icon,body){return `<section class="detail-card"><h3><span class="mini-icon">${icon}</span>${escapeHTML(title)}</h3><div class="detail-body">${body}</div></section>`;}
function detailRow(icon,caption,action,idx){return `<button class="detail-row" data-action="${action}" data-idx="${idx}"><span class="detail-icon">${icon}</span><span class="detail-title">${escapeHTML(caption)}</span><span class="detail-muted">↗</span></button>`;}
function renderRight(){const area=$('details-panel'),n=app.note;if(!n){area.innerHTML=detail('Obsidian','◆',empty('Aguardando conexão com sua biblioteca.'));return;}
 const videos=n.media?.video||[],urls=n.media?.video_links||[],trs=n.media?.transcript||[];
 let html='';if(app.view==='lessons'){
  html+=detail('Conteúdo da Aula','▤',[
  ...urls.map((v,i)=>detailRow('↗',v.label,'video_links',i)),
  ...videos.map((v,i)=>detailRow('▶',v.label,'video',i)),
  ...trs.map((v,i)=>detailRow('▤','Transcrição: '+v.label,'transcript',i))].join('')||empty('Nenhuma gravação ou transcrição associada.'));
 }else{html+=detail('Ligação com Obsidian','◆',`<div class="soft-count">● Vault conectado</div><div class="soft-count">${app.snapshot.stats?.notes||0} notas indexadas</div><div class="soft-count">Pasta local selecionada</div>`);}
 const related=n.related||[];
 const knowledge=related.filter(r=>r.section==='01-Meu-Conhecimento');
 const isPerson=r=>r.kind==='pessoa'||r.id?.startsWith('01-Meu-Conhecimento/Pessoas/');
 const isTechnical=r=>r.kind==='conceito'||r.id?.startsWith('01-Meu-Conhecimento/Conceitos/');
 const sameLesson=n.lesson?
   related.filter(r=>r.section==='02-Minhas-Aulas' &&
     r.id.startsWith('02-Minhas-Aulas/'+n.lesson+'/')):[];
 const groups={
  'knowledge-technical':knowledge.filter(isTechnical),
  'knowledge-people':knowledge.filter(isPerson),
  'knowledge-other':knowledge.filter(r=>!isPerson(r)&&!isTechnical(r)),
  '03-Meus-Projetos':related.filter(r=>r.section==='03-Meus-Projetos'),
  'lesson-recordings':sameLesson,
  '02-Minhas-Aulas':related.filter(r=>r.section==='02-Minhas-Aulas'&&!sameLesson.includes(r)),
 };
 for(const [title,icon,action] of [
  ['Conhecimentos técnicos','♧','knowledge-technical'],
  ['Pessoas citadas','♙','knowledge-people'],
  ['Outros materiais de estudo','▤','knowledge-other'],
  ['Projetos Relacionados','▱','03-Meus-Projetos'],
  ['Gravações e notas desta aula','▤','lesson-recordings'],
  ['Outras aulas relacionadas','▤','02-Minhas-Aulas']]){
  const list=groups[action];
  if((action==='knowledge-people'||action==='knowledge-other'||action==='lesson-recordings'||action==='02-Minhas-Aulas')&&!list.length)continue;
  html+=detail(title,icon,list.length?list.map((v,i)=>detailRow('↗',v.title,action,i)).join(''):empty('Sem vínculos confirmados ainda.'));
 }
 html+=detail('Ações da Nota','⚙','<button class="detail-action" id="open-note">↗ &nbsp; Abrir nota no Obsidian</button><button class="detail-action" id="copy-note">▤ &nbsp; Copiar link interno</button>');
 area.innerHTML=html;
 area.querySelector('#open-note').addEventListener('click',()=>call('open_note',n.id));
 area.querySelector('#copy-note').addEventListener('click',async()=>{
   const response=await call('copy_note_link',n.id);
   if(response?.ok){notify('Link copiado.');return;}
   const text=response?.text||'[['+n.id.replace(/\.md$/,'')+']]';
   try{await navigator.clipboard.writeText(text);notify('Link copiado.');}
   catch(_){notify('Copie o link: '+text,8500);}
 });
 area.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',async()=>{
  const action=button.dataset.action,i=Number(button.dataset.idx);
  if(['video','transcript','video_links'].includes(action)){
   const m=n.media[action][i];if(m)await call(action==='video_links'?'open_video_link':'open_attachment',action==='video_links'?m.url:m.stored);return;}
  const related=groups[action]?.[i];if(related){libraryState.search='';app.selected=related.id;app.view='library';await render();}
 }));}
async function renderOverlay(){$('library-workspace').classList.add('hidden');const el=$('overlay-screen');el.classList.remove('hidden');el.classList.toggle('teacher-overlay',app.view==='teacher');$('list-panel').classList.add('hidden');$('note-panel').classList.add('hidden');$('details-panel').classList.add('hidden');
 if(app.view==='teacher'){renderTeacher(el);return;}
 if(app.view==='settings'){
  el.innerHTML=`<div class="wide-header"><h2>Ajustes</h2><p>O cofre do Obsidian é a fonte principal. O TRAMA não cria outra biblioteca.</p></div>
  <div class="settings-grid"><div class="setting-block"><h3>Atualizações do TRAMA</h3>
    <p><strong>Versão instalada: 2.2.3.</strong> Para atualizar: clique em Verificar, depois em Baixar e confirme a instalação. Você não precisa reinstalar Python nem baixar arquivos ZIP.</p>
    <button id="check-updates">Verificar atualizações</button>
    <p id="update-message" class="setting-status">Clique em “Verificar atualizações” para consultar o GitHub.</p>
    <button id="install-update" class="hidden">Baixar e instalar nova versão</button>
    <button id="open-update" class="hidden">Ver detalhes no GitHub</button>
    </div><div class="setting-block"><h3>Biblioteca do Obsidian</h3>
    <p>Selecione a pasta original do seu Obsidian. Ela continua acessível mesmo sem o TRAMA.</p>
    <code>${escapeHTML(app.snapshot?.vault||'Nenhum cofre selecionado')}</code>
    <button id="choose-vault">Selecionar pasta do Obsidian</button>
    <p>Crie uma cópia do cofre antes de migrar ou atualizar. O ZIP não é criptografado e não é enviado a um servidor.</p>
    <button id="backup-vault">Criar backup local (.zip)</button>
    <button id="restore-vault">Restaurar backup em nova pasta</button>
    <p id="backup-message" class="setting-status" aria-live="polite">Nenhum backup iniciado.</p>
    <h3>Espaço utilizado pelo cofre</h3>
    <p>Consulte o tamanho das notas, transcrições, materiais e repositórios. O TRAMA apenas lê os tamanhos dos arquivos.</p>
    <button type="button" id="check-storage">Calcular espaço utilizado</button>
    <p id="storage-report" class="setting-status" aria-live="polite">Nenhum cálculo realizado.</p></div>
  <div class="setting-block"><h3>IA gratuita · chaves protegidas</h3>
    <p>Escolha uma conta Free <strong>sem faturamento</strong>. Chaves são protegidas pelo Windows (DPAPI). Modelos pagos não são selecionados.</p>
    <label for="ai-provider">Provedor</label><select id="ai-provider"><option value="gemini">Google Gemini API Free</option><option value="groq">GroqCloud Free</option><option value="openrouter">OpenRouter free</option></select>
    <label for="ai-key">Chave de API (não será exibida depois)</label>
    <input type="password" id="ai-key" placeholder="Cole sua chave aqui" autocomplete="off" spellcheck="false"/>
    <label class="free-confirm"><input id="ai-free" type="checkbox"/> Confirmei que a chave é de uma conta/projeto Free sem faturamento.</label>
    <div class="ai-key-actions"><button id="save-ai">Salvar chave</button><button id="remove-ai">Remover chave</button></div>
    <p id="ai-status" class="setting-status">Consultando configuração…</p>
    <label class="free-confirm trama-persistent-consent"><input type="checkbox" id="ai-processing-consent"/>
      Autorizar processamento com IA nas operações que eu iniciar. Posso revogar em qualquer momento.</label>
    <p id="ai-consent-status" class="setting-status" role="status">Nenhuma fonte será enviada automaticamente.</p>
    <div class="ai-diagnostic">
      <h3>Testar inteligência artificial</h3>
      <p>Teste a conexão, a compreensão da aula e a ligação com trechos de código. Usa <strong>até 2 requisições</strong> do provedor selecionado e não altera as notas do Obsidian.</p>
      <label for="ai-test-mode">Materiais para o teste</label>
      <select id="ai-test-mode"><option value="demo">Demonstração fictícia (sem importar arquivos)</option><option value="real">Uma aula + repositório já importados</option></select>
      <label class="free-confirm"><input type="checkbox" id="ai-test-consent"/> Autorizo enviar o trecho de teste à API externa selecionada.</label>
      <div class="ai-test-actions"><button type="button" id="test-ai">Testar inteligência artificial</button><button type="button" id="open-ai-report" disabled>Abrir relatório</button></div>
      <p id="ai-test-status" class="setting-status" aria-live="polite">Aguardando teste.</p>
    </div>
    <p>O TRAMA interrompe as chamadas ao alcançar a cota ou o limite local; não consegue verificar nem impedir cobranças em uma conta externa com faturamento ativo.</p>
  </div></div>`;
  const refreshUpdateStatus=async()=>{
    const output=el.querySelector('#update-message');
    output.textContent='Verificando o canal de atualizações…';
    const r=await call('check_updates');
    output.textContent=r?.message||'Não foi possível consultar.';
    const link=el.querySelector('#open-update'),install=el.querySelector('#install-update');
    link.classList.add('hidden');install.classList.add('hidden');
    if(r?.available&&r?.release_page){link.classList.remove('hidden');install.classList.remove('hidden');
      link.onclick=()=>call('open_update_page',r.release_page);
      install.onclick=async()=>{
        if(!await askTramaConfirm('Baixar atualização','O instalador do canal selecionado será baixado e sua integridade será verificada antes de abrir.','Baixar e verificar'))return;
        install.disabled=true;output.textContent='Baixando e verificando instalador...';
        try{
          const downloaded=await call('prepare_update',true);
          output.textContent=downloaded?.message||'Falha no download.';
          if(downloaded?.ok&&downloaded?.path&&await askTramaConfirm('Instalador verificado','A instalação será aberta agora. Salve seu trabalho e feche o TRAMA quando o Windows solicitar.','Abrir instalador')){
             const launched=await call('launch_update',downloaded.path,true);
             output.textContent=launched?.message||'Não foi possível iniciar.';
          }
        }finally{install.disabled=false;}
      };
    }
  };
  el.querySelector('#check-updates').addEventListener('click',refreshUpdateStatus);
  if(TRAMA_PREVIEW_CHECK_ON_OPEN) void refreshUpdateStatus();
  el.querySelector('#choose-vault').addEventListener('click',chooseVault);
  el.querySelector('#backup-vault').addEventListener('click', async()=>{
    if(!await askTramaConfirm('Criar backup do Obsidian','O ZIP será salvo no computador e incluirá notas e fontes sem criptografia. Guarde-o em local seguro.','Criar backup'))return;
    const button=el.querySelector('#backup-vault'),status=el.querySelector('#backup-message');
    button.disabled=true;status.textContent='Preparando backup verificado…';
    try{const r=await call('backup_vault',true);
      status.textContent=r?.message||'Backup não concluído.';}
    finally{button.disabled=false;}
  });
  el.querySelector('#restore-vault').addEventListener('click', async()=>{
    if(!await askTramaConfirm('Restaurar em pasta separada','Escolha um ZIP e uma pasta de destino. O TRAMA criará outro cofre e não substituirá o original.','Selecionar backup'))return;
    const button=el.querySelector('#restore-vault'),status=el.querySelector('#backup-message');
    button.disabled=true;status.textContent='Selecione o ZIP e a pasta onde criar o cofre restaurado…';
    try{const r=await call('restore_vault',true);
      status.textContent=r?.message||'Backup não restaurado.';}
    finally{button.disabled=false;}
  });
  el.querySelector('#check-storage').addEventListener('click',async()=>{
    const button=el.querySelector('#check-storage'),report=el.querySelector('#storage-report');
    button.disabled=true;report.textContent='Calculando espaço local…';
    const formatBytes=value=>{
      if(!Number.isFinite(value))return '—';
      if(value>=1024*1024*1024)return (value/(1024*1024*1024)).toFixed(2)+' GB';
      if(value>=1024*1024)return (value/(1024*1024)).toFixed(1)+' MB';
      return Math.max(0,Math.round(value/1024))+' KB';
    };
    try{
      const result=await call('vault_disk_usage');
      if(!result?.ok){report.textContent=result?.message||'Não foi possível consultar o cofre.';return;}
      const c=result.categories||{};
      report.textContent='Total: '+formatBytes(result.total_bytes)+
        ' · Notas: '+formatBytes(c.notes)+
        ' · Anexos: '+formatBytes(c.attachments)+
        ' · GitHub: '+formatBytes(c.repositories)+
        ' · Índices: '+formatBytes(c.catalog)+
        ' · Outros: '+formatBytes(c.other)+
        (result.partial?' · Estimativa parcial: limite de arquivos atingido.':'');
    }finally{button.disabled=false;}
  });
  const renderStatus=async()=>{
    const r=await call('ai_status');const p=el.querySelector('#ai-status');if(!p)return;
    if(!r){p.textContent='Configuração indisponível.';return;}
    const names=Object.entries(r.configured||{}).filter(([k,v])=>v).map(([k])=>k).join(', ');
    p.textContent='Chaves configuradas: '+(names||'nenhuma')+'.';
    app.aiConsent=r.processing_consent===true;
    const consent=el.querySelector('#ai-processing-consent');if(consent)consent.checked=app.aiConsent;
    el.querySelector('#ai-consent-status').textContent=app.aiConsent
      ?'Autorizado para ações iniciadas por você. Nenhum processamento automático em segundo plano.'
      :'Desativado: cada operação com IA exigirá autorização individual.';
    el.querySelector('#ai-test-consent').closest('label').classList.toggle('hidden',app.aiConsent);
   };
  el.querySelector('#ai-processing-consent').addEventListener('change',async event=>{
    const checkbox=event.target;checkbox.disabled=true;
    try{
      const result=await call('set_ai_processing_consent',checkbox.checked);
      if(!result?.ok){
        checkbox.checked=!checkbox.checked;
        el.querySelector('#ai-consent-status').textContent=result?.message||'Falha ao salvar autorização.';
        return;
      }
      app.aiConsent=result.processing_consent===true;
      el.querySelector('#ai-consent-status').textContent=result.message;
      el.querySelector('#ai-test-consent').closest('label').classList.toggle('hidden',app.aiConsent);
    }finally{checkbox.disabled=false;}
  });
  el.querySelector('#save-ai').addEventListener('click',async()=>{const provider=el.querySelector('#ai-provider').value;
    const input=el.querySelector('#ai-key'),key=input.value;input.value='';
    const checked=el.querySelector('#ai-free').checked;
    const r=await call('save_ai_key',provider,key,checked);notify(r?.message||'Não foi possível salvar.');await renderStatus();});
  el.querySelector('#remove-ai').addEventListener('click',async()=>{const provider=el.querySelector('#ai-provider').value;
    const r=await call('remove_ai_key',provider);notify(r?.ok?'Chave removida.':r?.message||'Erro.');await renderStatus();});
  el.querySelector('#test-ai').addEventListener('click',async()=>{
    const button=el.querySelector('#test-ai'), status=el.querySelector('#ai-test-status');
    if(!app.aiConsent && !el.querySelector('#ai-test-consent').checked){status.textContent='Marque a autorização para enviar o teste à API externa.';return;}
    button.disabled=true;status.textContent='Testando conexão, aula e evidências de código… (até 2 chamadas)';
    try{
      const result=await call('test_ai',el.querySelector('#ai-provider').value,el.querySelector('#ai-test-mode').value,true);
      if(!result?.ok){status.textContent=result?.message||'Não foi possível executar o teste.';return;}
      status.textContent=`Concluído · ${result.provider} · ${result.requests} chamada(s) · ${result.concepts} conceito(s) · ${result.relations} relação(ões) · ${result.discarded} referência(s) descartada(s).`; 
      el.querySelector('#open-ai-report').disabled=false;
    }finally{button.disabled=false;}
  });
  el.querySelector('#open-ai-report').addEventListener('click',async()=>{const r=await call('open_ai_test_report');if(!r?.ok)notify(r?.message||'Relatório indisponível.');});
  await renderStatus();return;
 }
 if(app.view==='home'){
  el.innerHTML=`<div class="wide-header"><h2>Seu conhecimento, organizado.</h2><p>Um lugar para conectar aulas, pessoas, materiais, conhecimentos e projetos sem substituir o Obsidian.</p></div><div class="settings-grid"><div class="setting-block"><h3>1. Conectar Obsidian</h3><p>Escolha seu cofre em Ajustes. As notas continuam locais e acessíveis mesmo sem o TRAMA.</p><button id="home-settings">Conectar meu cofre</button></div><div class="setting-block"><h3>2. Organizar minhas aulas</h3><p>Adicione transcrições, prints, links e códigos para criar notas e materiais de revisão.</p><button id="home-lessons">Ver minhas aulas</button></div><div class="setting-block"><h3>3. Estudar com IA Professor</h3><p>Peça explicações, desafios ou ajuda com código usando suas notas, sem modificar o cofre.</p><button id="home-teacher">Abrir IA Professor</button></div><div class="setting-block"><h3>Biblioteca e backup</h3><p>Revise as notas e, antes de atualizar, crie uma cópia em Ajustes.</p><button id="home-library">Abrir biblioteca</button></div></div>`;
  el.querySelector('#home-settings').addEventListener('click',()=>setView('settings'));
  el.querySelector('#home-teacher').addEventListener('click',()=>setView('teacher'));
  el.querySelector('#home-lessons').addEventListener('click',()=>setView('lessons'));
  el.querySelector('#home-library').addEventListener('click',()=>setView('library'));return;
 }
 const graph=await call('graph');const nodes=graph?.nodes||[],edges=graph?.edges||[];
 if(app.graphView){app.graphView.destroy();app.graphView=null;}
 el.innerHTML=`<div class="wide-header"><h2>Grafo de conexões</h2><p>${nodes.length} notas e ${edges.length} links reais entre arquivos do Obsidian. Passe o mouse para ver as ligações; clique para abrir.</p></div><div id="graph-host"></div>`;
 if(!nodes.length){$('graph-host').innerHTML='<p class="empty-text">Seu grafo será construído quando suas notas tiverem links internos [[...]].</p>';return;}
 app.graphView=TramaGraph.mount($('graph-host'),{nodes,edges},{
   onOpen:async id=>{app.selected=id;app.view='library';renderNavigation();await render();}
 });
}
function openClassroomContext(){
 const dlg=$('classroom-dialog');$('context-feedback').textContent='';
 if(typeof dlg.showModal==='function')dlg.showModal();else dlg.setAttribute('open','');
}
function closeClassroomContext(){const dlg=$('classroom-dialog');if(dlg.open && typeof dlg.close==='function')dlg.close();else dlg.removeAttribute('open');}
async function saveClassroomContext(event){
 event.preventDefault();
 const form=$('context-form'),button=$('context-save'),feedback=$('context-feedback');
 const record=Object.fromEntries(new FormData(form).entries());
 if(!record.aula){feedback.textContent='Informe o número da aula.';return;}
 button.disabled=true;feedback.textContent='Salvando no cofre…';
 try{
  const result=await call('save_classroom_context',record);
  if(!result?.ok){feedback.textContent=result?.message||'Não foi possível salvar.';return;}
  closeClassroomContext();form.reset();app.view='lessons';await refresh();
  notify(`Contexto ${result.aula} salvo no cofre. As fontes originais foram preservadas.`);
 }finally{button.disabled=false;}
}
async function chooseVault(){const r=await call('select_vault');if(r?.ok){
 teacherState.messages=[];teacherState.draft='';teacherState.code='';
 await call('teacher_reset');
 notify('Cofre conectado.');await refresh();
 }else if(r?.message)notify(r.message);}
async function updateAutoQueue(result){
 if(!result?.ok){$('auto-feedback').textContent=result?.message||'Falha ao preparar os arquivos.';return;}
 const items=result.items||[],list=$('auto-queue');list.replaceChildren();
 $('auto-queue-count').textContent=`(${items.length}/${result.max||100})`;
 if(!items.length){const li=document.createElement('li');li.textContent='Nenhum arquivo preparado. Cole prints com Ctrl+V ou adicione documentos.';list.append(li);}
 for(const item of items){const li=document.createElement('li');li.className='auto-queue-item';
  const label=document.createElement('span');label.textContent=`${item.kind==='print colado'?'▧':'▤'} ${item.name} · ${Math.max(1,Math.round(item.size/1024))} KB`;
  const remove=document.createElement('button');remove.type='button';remove.textContent='Remover';remove.setAttribute('aria-label',`Remover ${item.name}`);
  remove.addEventListener('click',async()=>updateAutoQueue(await call('remove_staged',item.id)));
  li.append(label,remove);list.append(li);
 }
 if(result.errors?.length)$('auto-feedback').textContent=result.errors.join(' | ');
 else if(result.added)$('auto-feedback').textContent=`${result.added} arquivo(s) adicionado(s). Nada foi enviado. Continue adicionando ou clique em Processar tudo.`;
}
async function openAutoImport(){
 const dlg=$('auto-dialog');if(typeof dlg.showModal==='function')dlg.showModal();else dlg.setAttribute('open','');
 const status=await call('ai_status');
 app.aiConsent=status?.processing_consent===true;
 $('auto-consent-row').classList.toggle('hidden',app.aiConsent);
 $('auto-consent-info').classList.toggle('hidden',!app.aiConsent);
 await updateAutoQueue(await call('staged_items'));
}
function closeAutoImport(){const dlg=$('auto-dialog');if(dlg.open && typeof dlg.close==='function')dlg.close();else dlg.removeAttribute('open');}
async function addAutoFiles(){const btn=$('auto-add-files');btn.disabled=true;
 try{await updateAutoQueue(await call('stage_files'));}finally{btn.disabled=false;}}
async function pasteAutoImage(event){
 if(!$('auto-dialog').open)return;
 const imageItem=Array.from(event.clipboardData?.items||[]).find(i=>i.type==='image/png'||i.type==='image/jpeg');
 if(!imageItem)return; // Ctrl+V de texto permanece disponível no campo de links.
 event.preventDefault();const file=imageItem.getAsFile();if(!file)return;
 if(file.size>6*1024*1024){$('auto-feedback').textContent='Print maior que 6 MB. Recorte uma área menor.';return;}
 $('auto-feedback').textContent='Adicionando print à fila (sem enviar à IA)…';
 const reader=new FileReader();reader.onerror=()=>$('auto-feedback').textContent='Não foi possível ler o print.';
 reader.onload=async()=>updateAutoQueue(await call('stage_clipboard_image',reader.result));
 reader.readAsDataURL(file);
}
async function runAutoImport(){
 const feedback=$('auto-feedback');
 if(!app.aiConsent && !$('auto-consent').checked){feedback.textContent='Marque a autorização antes de processar o lote.';return;}
 const links=[$('auto-links').value,$('auto-repos').value]
   .map(value=>value.trim()).filter(Boolean).join('\n');
 const button=$('auto-start'),add=$('auto-add-files'),clear=$('auto-clear');
 button.disabled=true;add.disabled=true;clear.disabled=true;
 feedback.textContent='Processando toda a fila de uma vez. Mantenha a janela aberta…';
 try{
   const result=await call('process_staged',links,true);
   if(!result?.ok){feedback.textContent=result?.message||'O processamento falhou; a fila foi preservada.';return;}
   const pend=result.pending||[],errors=result.errors||[];
   feedback.textContent=`Concluído: ${result.files||0} arquivo(s) novo(s), ${result.visual_analyzed||0} imagem(ns) analisada(s), ${(result.lessons||[]).length} aula(s), ${result.repositories||0} repositório(s), ${result.calls||0} chamada(s) à IA. `+
    (pend.length?`Pendências (${pend.length}): ${pend.slice(0,4).join(' | ')}`:'Sem pendências de associação.')+
    (errors.length?` Erros: ${errors.slice(0,2).join(' | ')}`:'');
   if(!result.queue_retained){$('auto-links').value='';$('auto-repos').value='';await updateAutoQueue(await call('staged_items'));}
   await refresh();notify('Lote processado. Veja o resultado no Obsidian.',7000);
 }finally{button.disabled=false;add.disabled=false;clear.disabled=false;}
}
async function importFiles(){openAutoImport();}
async function generate(){
 if(!app.aiConsent && !await askTramaConfirm('Gerar resumos','Apenas os materiais necessários serão enviados à API configurada. As análises já concluídas serão reaproveitadas.','Gerar resumos'))return;
 notify('Processando notas com a IA gratuita configurada…',10000);
 const r=await call('process',true);
 notify(r?.ok?(r.logs?.at(-1)||'Processamento concluído.'):(r?.message||'Sem provedor gratuito disponível.'),6500);
 await refresh();
}
function addRepo(){
 const dialog=$('repo-dialog');
 $('repo-feedback').textContent='Cole o link e confirme a importação.';
 if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','');
 $('repo-url').focus();
}
function closeRepoDialog(){
 const dialog=$('repo-dialog');
 if(dialog.open){if(typeof dialog.close==='function')dialog.close();else dialog.removeAttribute('open');}
}
async function submitRepo(event){
 event.preventDefault();
 const url=$('repo-url').value.trim();
 const status=$('repo-feedback'),button=$('repo-submit');
 if(!url){status.textContent='Informe o link ou caminho da pasta.';return;}
 button.disabled=true;
 status.textContent='Lendo o repositório e indexando o código. Isso pode levar alguns instantes…';
 try{
  const result=await call('add_repo',url);
  if(!result?.ok){status.textContent=result?.message||'Não foi possível importar o projeto.';return;}
  closeRepoDialog();$('repo-url').value='';
  notify('Repositório adicionado à biblioteca. Os vínculos com aulas serão atualizados.',7000);
  await refresh();
 }finally{button.disabled=false;}
}
function bind(){document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>setView(el.dataset.view)));
 $('btn-refresh').addEventListener('click',refresh);$('btn-import').addEventListener('click',importFiles);$('btn-list-add').addEventListener('click',()=>app.view==='projects'?addRepo():importFiles());
 $('btn-generate').addEventListener('click',generate);$('btn-obsidian').addEventListener('click',()=>call('open_obsidian'));
 $('btn-settings').addEventListener('click',()=>setView('settings'));
 $('btn-context').addEventListener('click',openClassroomContext);
 $('repo-form').addEventListener('submit',submitRepo);
 $('repo-recalculate').addEventListener('click',async()=>{
   const repo=$('repo-url').value.trim();
   if(!repo){$('repo-feedback').textContent='Informe o repositório para recalcular.';return;}
   if(!await askTramaConfirm('Recalcular versões automáticas',
      'Reavaliar versões de todas as aulas deste repositório? Ajustes manuais serão preservados.','Recalcular'))return;
   $('repo-feedback').textContent='Recalculando versões por conteúdo, fala e ordem...';
   const result=await call('recalculate_github_versions',repo,true);
   $('repo-feedback').textContent=result?.ok?
      'Recálculo finalizado: '+(result.mapped||0)+' aula(s). '+(result.pending||[]).join(' '):
      (result?.message||'Não foi possível recalcular.');
   if(result?.ok){await refresh();}
 });
 $('repo-close').addEventListener('click',closeRepoDialog);
 $('repo-cancel').addEventListener('click',closeRepoDialog);
 $('auto-close').addEventListener('click',closeAutoImport);
 $('auto-start').addEventListener('click',runAutoImport);
 $('auto-add-files').addEventListener('click',addAutoFiles);
 $('auto-clear').addEventListener('click',async()=>{await updateAutoQueue(await call('clear_staged'));$('auto-feedback').textContent='Fila limpa. Nenhuma nota foi modificada.';});
 $('auto-paste-zone').addEventListener('click',()=>$('auto-paste-zone').focus());
 $('auto-dialog').addEventListener('paste',pasteAutoImage);
 $('context-cancel').addEventListener('click',closeClassroomContext);
 $('context-dismiss').addEventListener('click',closeClassroomContext);
 $('context-form').addEventListener('submit',saveClassroomContext);
 $('context-attach').addEventListener('click',async()=>{
   const aula=$('context-form').elements.namedItem('aula').value;
   if(!aula){$('context-feedback').textContent='Informe o número da aula primeiro.';return;}
   const result=await call('import_classroom_materials',aula);
   $('context-feedback').textContent=result?.ok?`${result.count} material(is) associado(s). ${result.errors?.length||0} erro(s).`:(result?.message||'Não foi possível anexar.');
 });
 async function toggleFullscreen(){const result=await call('window_action','fullscreen');if(result?.ok)window.__tramaFullscreen=!window.__tramaFullscreen;}
 $('btn-fullscreen').addEventListener('click',toggleFullscreen);
 document.addEventListener('keydown',event=>{
   if(event.key==='F11'){event.preventDefault();toggleFullscreen();}
   else if(event.key==='Escape' && !['classroom-dialog','auto-dialog','repo-dialog','trama-confirm-dialog'].some(id=>$(id)?.open) && window.__tramaFullscreen){event.preventDefault();toggleFullscreen();}
 });
 async function runGlobalSearch(){
   app.filter=$('search-all').value.trim();libraryState.search=app.filter;
   app.view='library';renderNavigation();await render();
 }
 $('search-all').addEventListener('keydown',async e=>{if(e.key==='Enter'){e.preventDefault();await runGlobalSearch();}});
 $('btn-search-all').addEventListener('click',runGlobalSearch);
 document.querySelectorAll('[data-list-filter]').forEach(btn=>btn.addEventListener('click',async()=>{
   app.listFilter=btn.dataset.listFilter;await render();
 }));
 $('list-search').addEventListener('input',async e=>{app.filter=e.target.value.trim();await render();});}
async function start(){bridge=window.pywebview?.api||window.__TRAMA_API__||null;bind();if(!bridge){notify('Abra pelo aplicativo TRAMA no Windows.');return;}await refresh();}
if(window.pywebview?.api||window.__TRAMA_API__){start();}else{window.addEventListener('pywebviewready',start,{once:true});}
