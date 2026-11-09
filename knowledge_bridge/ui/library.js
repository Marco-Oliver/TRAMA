'use strict';
// Biblioteca visual: somente leitura do mesmo vault do Obsidian.
// Todas as strings das notas são escapadas antes de se tornarem HTML.
const libraryState={expanded:new Set(),favorites:new Set(),relatedTab:'content',search:'',searchResults:null,searchResolved:'',searchTotal:0,searchPending:false,searchSeq:0,searchTimer:null,tab:'',lastVault:'',allowEmpty:false,showTechnical:false};
const libE=(value)=>escapeHTML(String(value??''));
const libIcon=(name,classes='')=>`<svg class="ui-svg ${classes}" aria-hidden="true"><use href="#ic-${name}"/></svg>`;
const libNotes=()=>app.snapshot?.notes||[];
function libSearchMatches(notes){
 const q=libraryState.search.trim().toLowerCase();
 if(!q)return notes;
 if(libraryState.searchResolved===libraryState.search&&libraryState.searchResults){
  const match=new Set(libraryState.searchResults.map(item=>item.id));
  return notes.filter(n=>match.has(n.id));
 }
 return notes.filter(n=>(n.id+' '+n.title).toLowerCase().includes(q));
}
function libScheduleContentSearch(){
 const query=libraryState.search.trim();
 if(query.length<2){
  libraryState.searchPending=false;
  libraryState.searchResults=null;
  libraryState.searchResolved='';
  return;
 }
 if(libraryState.searchResolved===libraryState.search)return;
 if(libraryState.searchTimer)clearTimeout(libraryState.searchTimer);
 libraryState.searchPending=true;
 const request=++libraryState.searchSeq;
 libraryState.searchTimer=setTimeout(async()=>{
  libraryState.searchTimer=null;
  const result=await call('search_notes',query,80);
  if(request!==libraryState.searchSeq||query!==libraryState.search.trim()||app.view!=='library')return;
  libraryState.searchPending=false;
  libraryState.searchResolved=libraryState.search;
  libraryState.searchResults=result?.ok?(result.matches||[]):[];
  libraryState.searchTotal=result?.ok?(result.total||0):0;
  if(!result?.ok)notify(result?.message||'Não foi possível pesquisar nas notas.');
  await renderLibraryView();
 },260);
}
const libParts=id=>String(id||'').split('/').filter(Boolean);
const libPretty=folder=>{
  const x=String(folder||'').replace(/^\d{2}[-_]/,'');
  if(x==='00-Visao-geral')return 'Visão geral da aula';
  if(x==='Modulos')return 'Módulos';
  if(x==='Inicio')return 'Início';
  const lesson=/^Aula-(\d{1,4})$/i.exec(x);
  if(lesson)return 'Aula '+lesson[1].padStart(3,'0');
  return x.replaceAll('-',' ');
};
const libIsProposal=id=>/\.PROPOSTA(?:-\d+)?\.md$/i.test(String(id||''));
const libHumanTitle=n=>libIsProposal(n.id)?'Proposta de atualização · '+n.title:
  n.kind==='visao_geral'?'Visão geral da aula':n.title.replace(/^Aula-\d+\s+[—-]\s+/i,'');

function libFindLink(raw,source){
 // Never guess which document the user wanted when multiple lessons share
 // "00-Visao-geral.md" or a generic note name.
 const basic=String(raw||'').split('|')[0].split('#')[0]
  .replaceAll('\\','/').replace(/\.md$/i,'').trim().toLowerCase();
 if(!basic||basic.startsWith('/')||basic.split('/').includes('..'))return null;
 const notes=libNotes();
 const normalized=n=>n.id.toLowerCase().replace(/\.md$/,'');
 const currentDir=libParts(source||'').slice(0,-1).join('/').toLowerCase();
 const exact=notes.filter(n=>normalized(n)===basic);
 if(exact.length===1)return exact[0];
 if(exact.length>1)return null;
 if(basic.includes('/')){
  const suffix=notes.filter(n=>normalized(n).endsWith('/'+basic));
  return suffix.length===1?suffix[0]:null;
 }
 const matches=notes.filter(n=>normalized(n).split('/').at(-1)===basic||
                                  n.title.toLowerCase()===basic);
 if(currentDir){
  const same=matches.filter(n=>normalized(n).startsWith(currentDir+'/'));
  if(same.length===1)return same[0];
  if(same.length>1)return null;
 }
 return matches.length===1?matches[0]:null;
}
function libWiki(content,source){
 let safe=libE(content);
 // Link <https://...> is the original recording/material link. Click delegates
 // to Bridge's allow-listed open_video_link instead of arbitrary navigation.
 safe=safe.replace(/&lt;(https?:\/\/[^\s&<>]{5,400})&gt;/g,(_,url)=>
  `<button type="button" class="lib-external-link" data-lib-external="${libE(url)}">${libE(url)}</button>`);

 // Official Academy material (page or file at the lesson's pinned SHA). The
 // bridge only opens URLs registered for a lesson; anything else stays inert.
 safe=safe.replace(/\[([^\]\n]{1,180})\]\((https:\/\/(?:academiadoprogramador-fullstack\.github\.io\/docs\/|github\.com\/academiadoprogramador-fullstack\/docs\/blob\/[a-f0-9]{40}\/)[^\s<>"')]{0,700})\)/g,(_,label,url)=>
  `<button type="button" class="lib-external-link" data-lib-external="${url}">${label}</button>`);

 // Markdown references to immutable, indexed GitHub code are clickable.
 // The native bridge validates the repository, SHA, path and actual evidence
 // before opening a browser; arbitrary URLs embedded in notes stay inert.
 safe=safe.replace(/\[([^\]\n]{1,180})\]\((https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/blob\/[a-fA-F0-9]{40}\/[^\s<>"')]{1,700}#L\d{1,8})\)/g,(_,label,url)=>
  `<button type="button" class="lib-code-link" data-lib-code="${url}">${label}</button>`);

 safe=safe.replace(/\[\[([^\]\n]+)\]\]/g,(_,inner)=>{
  const raw=inner.replaceAll('&amp;','&').replaceAll('&lt;','<').replaceAll('&gt;','>');
  const n=libFindLink(raw,source);const caption=raw.split('|').at(-1);
  const stamp=/#\^(min-\d+(?:-\d+)*)/.exec(raw);
  const anchor=stamp?' data-lib-anchor="'+stamp[1]+'"':'';
  return n?'<a href="#" data-lib-note="'+libE(n.id)+'"'+anchor+'>'+libE(caption)+'</a>':
    '<span class="lib-dead-link">'+libE(caption)+'</span>';
 });
 safe=safe.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
   .replace(/\*([^*\n]+)\*/g,'<em>$1</em>')
   .replace(/`([^`\n]+)`/g,'<code>$1</code>');
 // Obsidian's source block marker becomes a real scroll target in the
 // read-only TRAMA renderer. Only generated numeric anchors are accepted.
 safe=safe.replace(/\s+\^(min-\d+(?:-\d+)*)$/g,(_,anchor)=>
   '<span id="'+anchor+'" class="trama-source-anchor"></span>');
 return safe;
}
function libRenderMarkdown(markdown,source,title){
 const lines=String(markdown||'').replace(/\r/g,'').split('\n');const sections=[];
 let current={title:'',lines:[]};
 for(const line of lines){const h=/^#{1,3}\s+(.+)/.exec(line);if(h){
   if(current.lines.length||current.title)sections.push(current);
   current={title:h[1].trim(),level:(line.match(/^#+/)||[''])[0].length,lines:[]};
 }else current.lines.push(line);}
 if(current.lines.length||current.title)sections.push(current);
 const renderSection=sec=>{
  const icon=/resumo/i.test(sec.title)?libIcon('book','section-book'):/conceito|conteúdo/i.test(sec.title)?libIcon('file','section-file'):/relacionado|links/i.test(sec.title)?libIcon('link','section-link'):libIcon('file','section-file');
  let header='';if(sec.title&&!(sec.level===1&&sec.title.toLowerCase()===String(title).toLowerCase())){
   const h=sec.level===1?'h2':sec.level===2?'h2':'h3';header=`<${h}>${h==='h2'?`<span class="lib-section-icon">${icon}</span>`:''}${libWiki(sec.title,source)}</${h}>`;
  }
  const out=[];let para=[],list=[],listType='',code=[],isCode=false,blockquote=[];
  const flushParagraph=()=>{if(para.length){out.push(`<p>${libWiki(para.join(' '),source)}</p>`);para=[];}};
  const flushList=()=>{if(list.length){out.push(`<${listType}>${list.map(t=>`<li>${libWiki(t,source)}</li>`).join('')}</${listType}>`);list=[];listType='';}};
  const flushQuote=()=>{
   if(!blockquote.length)return;
   // Quoted transcript timestamps must remain separate study bullets.
   // Escape through libWiki at each leaf; never concatenate untrusted HTML.
   const items=[];let paragraph=[],bullets=[];
   const flushText=()=>{if(paragraph.length){items.push(`<p>${libWiki(paragraph.join(' '),source)}</p>`);paragraph=[];}};
   const flushBullets=()=>{if(bullets.length){items.push(`<ul>${bullets.map(t=>`<li>${libWiki(t,source)}</li>`).join('')}</ul>`);bullets=[];}};
   for(const raw of blockquote){
    const bullet=/^\s*[-*]\s+(.+)/.exec(raw);
    if(bullet){flushText();bullets.push(bullet[1]);}
    else {flushBullets();if(raw.trim())paragraph.push(raw.trim());else flushText();}
   }
   flushText();flushBullets();
   out.push(`<blockquote>${items.join('')}</blockquote>`);
   blockquote=[];
  };
  for(const line of sec.lines){
   if(/^\s*```/.test(line)){flushParagraph();flushList();flushQuote();if(isCode){out.push(`<pre><code>${libE(code.join('\n'))}</code></pre>`);code=[];}isCode=!isCode;continue;}
   if(isCode){code.push(line);continue;}
   if(!line.trim()){flushParagraph();flushList();flushQuote();continue;}
   if(/^\s*---\s*$/.test(line)){flushParagraph();flushList();out.push('<hr>');continue;}
   const item=/^\s*([-*]|\d+\.)\s+(.*)/.exec(line);
   if(item){flushParagraph();flushQuote();const type=/\d/.test(item[1])?'ol':'ul';if(listType&&listType!==type)flushList();listType=type;list.push(item[2]);continue;}
   if(/^\s*>\s?/.test(line)){flushParagraph();flushList();blockquote.push(line.replace(/^\s*>\s?/,''));continue;}
   flushList();flushQuote();para.push(line.trim());
  }
  flushParagraph();flushList();flushQuote();if(isCode)out.push(`<pre><code>${libE(code.join('\n'))}</code></pre>`);
  const b=out.join('');
  const summary=/resumo/i.test(sec.title)&&sec.level>0;
  const related=/notas? relacionadas?/i.test(sec.title);
  return header+(summary?`<div class="lib-summary-box">${b}</div>`:related?`<div class="lib-related-box">${b}</div>`:b);
 };
 return `<div class="lib-md">${sections.map(renderSection).join('')}</div>`;
}
function libTreeMarkup(notes){
 const root={name:'',folders:new Map(),notes:[],path:''};
 for(const n of notes){let node=root;for(const segment of libParts(n.id).slice(0,-1)){
  if(!node.folders.has(segment))node.folders.set(segment,{name:segment,folders:new Map(),notes:[],path:node.path+'/'+segment});
  node=node.folders.get(segment);
 }node.notes.push(n);}
 function levelHTML(node,depth=0){let result='';const rank={'01-Meu-Conhecimento':0,'02-Minhas-Aulas':1,'04-Resumos':2,'03-Meus-Projetos':3,'04-Recursos':4,'00-Inicio':5,'90-Sistema':6};
 const orderedNames=['Área de Estudos','Programação','Linguagens','Orientação a Objetos','Arquitetura','Boas Práticas','Desenvolvimento Web','Cloud & DevOps','Anotações Rápidas','2026 - 2º Semestre','2026 - 1º Semestre','Slides','Artigos','Videos','Vídeos','Templates'];
 const folderRank=x=>{const n=libPretty(x);const i=orderedNames.indexOf(n);return i<0?100:i;};
 const folders=[...node.folders.entries()].sort((a,b)=>depth===0?(rank[a[0]]??10)-(rank[b[0]]??10)||a[0].localeCompare(b[0],'pt-BR',{numeric:true}):(folderRank(a[0])-folderRank(b[0])||a[0].localeCompare(b[0],'pt-BR',{numeric:true})));
  for(const [name,child] of folders){
   const selected=app.selected?.startsWith(child.path.slice(1)+'/');
   const alwaysOpen=(depth===0&&!['00-Inicio','90-Sistema'].includes(name))||(depth===1&&['Área de Estudos','2026 - 2º Semestre'].includes(name))||(libPretty(name)==='Programação'&&depth===2);
   const expanded=!!(libraryState.search||libraryState.expanded.has(child.path)||alwaysOpen||selected);
   result+=`<div class="lib-directory"><button class="lib-folder-row tree-indent-folder depth-${Math.min(depth,12)}" data-lib-folder="${libE(child.path)}" aria-expanded="${expanded?'true':'false'}"><span class="lib-chevron ${expanded?'expanded':''}">▶</span><span class="lib-folder-icon ${depth===0?'top':''}" aria-hidden="true"></span><strong>${libE(libPretty(name))}</strong></button><div class="lib-children ${expanded?'':'hidden'}">${levelHTML(child,depth+1)}</div></div>`;
  }
  for(const n of node.notes.sort((a,b)=>(a.kind==='visao_geral'?-1:b.kind==='visao_geral'?1:0)||a.title.localeCompare(b.title,'pt-BR',{numeric:true}))){
   const match=libraryState.searchResolved===libraryState.search&&libraryState.searchResults?.find(hit=>hit.id===n.id);
   const excerpt=match?.in_content&&match.snippet?'<small class="lib-match-excerpt">'+libE(match.snippet)+'</small>':'';
   result+=`<button class="lib-file-row ${libIsProposal(n.id)?'lib-proposal':''} ${excerpt?'lib-search-hit':''} ${n.kind==='visao_geral'?'is-overview':''} ${n.id===app.selected?'selected':''} tree-indent-file depth-${Math.min(depth,12)}" data-depth="${Math.min(depth,12)}" data-lib-note="${libE(n.id)}"><span class="lib-file-icon" aria-hidden="true"></span><span class="file-label">${libE(libHumanTitle(n))}${excerpt}</span></button>`;
  }
  return result;
 }
 return levelHTML(root)||'<p class="lib-empty-message">Nenhuma nota foi encontrada.</p>';
}
async function libChooseNote(id,anchor=''){
 if(!libNotes().some(n=>n.id===id))return;
 libraryState.allowEmpty=false;app.selected=id;
 app.note=await call('note',id);
 await renderLibraryView();
 if(anchor&&/^min-(?:\d+-)*\d+$/.test(anchor)){
   const target=$('library-workspace').querySelector('#'+anchor);
   if(target)target.scrollIntoView({block:'center',behavior:'auto'});
 }
}
function libMetaPanel(n){const data=app.snapshot,stats=data?.stats||{};const status=data?.connected?'Conectado':'Desconectado';
 const links=[...String(n?.content||'').matchAll(/(?<!!)\[\[([^\]\n]+)\]\]/g)].map(m=>({target:libFindLink(m[1],n.id),label:m[1].split('|').at(-1)}));
 const uniqLinks=[];for(const l of links){if(l.target&&!uniqLinks.some(x=>x.target.id===l.target.id))uniqLinks.push(l);}
 const related=n?.related||[];const noteTags=new Set(n?.tags||[]);const taggedRelated=related.filter(x=>(x.tags||[]).some(tag=>noteTags.has(tag)));const relatedShown=(libraryState.relatedTab==='content'||!noteTags.size)?related:taggedRelated;
 const card=(heading,ico,body)=>`<div class="lib-side-card"><h3><span class="card-heading-ico">${ico}</span>${libE(heading)}</h3><div class="side-body">${body}</div></div>`;
 const stat=(label,val,ico,muted=false)=>`<div class="lib-stat"><span class="stat-label"><span>${ico}</span> ${libE(label)}</span><span class="stat-value ${muted?'muted':''}" title="${libE(val)}">${libE(val)}</span></div>`;
 const action=(title,icon,act)=>`<button class="lib-side-button" data-lib-action="${act}"><span class="action-left">${libIcon(icon,'action-icon')}${libE(title)}</span>${libIcon('arrow','action-end')}</button>`;
 const quickLink=(x)=>`<button class="lib-link" data-lib-note="${libE(x.target.id)}">${libIcon('file','link-icon')}${libE(x.label)}</button>`;
 let html=card('Ligação com Obsidian','<span class="lib-obs-icon small"></span>',[
  stat('Vault:',status,libIcon('check','green-icon')),stat('Notas indexadas:',String(stats.notes||0),libIcon('file')),stat('Última leitura:',(data?.scanned_at||'Ao atualizar a biblioteca'),libIcon('clock'),true),stat('Caminho do vault:',(data?.vault||'Não selecionada').replace(/\\/g,'/'),libIcon('folder'),true),
  '<div class="lib-config-action"><button class="lib-side-button lib-compact-button" data-lib-action="settings">⚙ Configurar conexão</button></div>'
 ].join(''));
 html+=card('Ações da Nota',libIcon('file','heading-icon'),action('Abrir nota no Obsidian','arrow','open')+action('Revelar arquivo no Explorer','folder','reveal')+action('Copiar link interno [[...]]','link','copy')+action(libraryState.favorites.has(n.id)?'Remover dos favoritos':'Adicionar aos favoritos','star','favorite')+(libIsProposal(n.id)?action('Comparar com a nota original','file','compare'):'')+(libTramaTarget(n.id)?action(libTramaTarget(n.id).label,'arrow','trama-open'):'')+action('Como recuperar versões','clock','history'));
 if(!libIsProposal(n.id)){
  const base=n.id.replace(/\.md$/i,'');
  const proposals=libNotes().filter(p=>libIsProposal(p.id)&&p.id.startsWith(base+'.PROPOSTA'));
  if(proposals.length){
   const rows=proposals.slice(0,12).map(p=>'<button class="lib-link" data-lib-note="'+libE(p.id)+'">'+libIcon('file','link-icon')+libE(libHumanTitle(p))+'</button>').join('');
   html+=card('Propostas de atualização',libIcon('file','heading-icon'),
    '<p class="lib-meta-caption">A edição original foi preservada. Confira antes de aceitar qualquer alteração.</p>'+rows);
  }
 }
 html+=card('Links e Referências',libIcon('link','heading-icon'),`<div class="lib-meta-caption">Links desta nota (${uniqLinks.length})</div>${uniqLinks.length?uniqLinks.map(quickLink).join(''):'<p class="lib-empty-message">Nenhum link para outra nota.</p>'}`);
 html+=card('Notas Relacionadas',libIcon('file','heading-icon'),(noteTags.size?`<div class="lib-small-tabs"><button data-lib-relatedtab="content" class="${libraryState.relatedTab==='content'?'active':''}">Por conteúdo (${related.length})</button><button data-lib-relatedtab="tags" class="${libraryState.relatedTab==='tags'?'active':''}">Por tags (${taggedRelated.length})</button></div>`:`<div class="lib-related-label">Por conteúdo (${related.length})</div>`)+`${relatedShown.length?relatedShown.map(x=>quickLink({target:x,label:x.title})).join(''):'<p class="lib-empty-message">Nenhuma relação confirmada.</p>'}`);
 html+=`<div class="lib-graph-entry"><button class="lib-side-button" data-lib-action="graph">${libIcon('network','action-icon')} <span>Visualizar grafo de conexões</span> ${libIcon('arrow','action-end')}</button></div>`;
 return html;
}
function libCenterPanel(n){if(!n||n.error)return '<div class="lib-empty-message">Selecione uma nota para visualizar o conteúdo do seu Obsidian.</div>';
 const parts=libParts(n.id);const crumbs=parts.slice(0,-1).map(libPretty).concat([n.title]);
 const source=(libNotes().find(x=>x.id===n.id)||{});
 const star=libraryState.favorites.has(n.id)?'★':'☆';
 const code=`<div class="lib-tab-strip"><div class="lib-open-tab"><span class="lib-obs-icon small" aria-label="Obsidian"></span><span class="lib-tab-text">${libE(n.title)}</span><button class="lib-tab-close" data-lib-action="close" title="Voltar à Biblioteca">×</button></div><button class="lib-tab-add" data-lib-action="new" title="Abrir o Obsidian">+</button></div>`;
 const proposalButton=libIsProposal(n.id)?
  '<button type="button" class="lib-proposal-compare" data-lib-action="compare">Comparar com a nota original</button>':'';
 const pendingProposals=libIsProposal(n.id)?[]:libNotes().filter(p=>libIsProposal(p.id)&&
   p.id.startsWith(n.id.replace(/\.md$/i,'')+'.PROPOSTA'));
 const proposalHint=pendingProposals.length?
  '<div class="lib-proposal-hint"><strong>Atualização disponível para revisão.</strong> Sua nota original foi preservada. '+
    '<button type="button" data-lib-note="'+libE(pendingProposals[0].id)+'">Ver proposta</button>'+
    (pendingProposals.length>1?' (+'+(pendingProposals.length-1)+' outras)':'')+
   '</div>':'';
 const content=`<div class="lib-note-scroll"><div class="lib-breadcrumb">${crumbs.map((c,i)=>`${i?'<b>›</b>':''}<span>${libE(c)}</span>`).join('')}</div><div class="lib-heading-row"><h1 class="lib-title lib-title-grow">${libE(n.title)}</h1><button class="lib-tab-add lib-favorite-star" data-lib-action="favorite" title="Marcar como favorita">${star}</button>${proposalButton}</div>${proposalHint}<div class="lib-note-meta"><span class="lib-obs-icon small" aria-label="Obsidian"></span> Origem: <span class="origin">Obsidian Vault</span> <span>│</span> <span>▤ Nota do Obsidian</span> <span>│</span><span>◷ Editado em ${libE(n.updated)}</span></div>${libRenderMarkdown(n.content,n.id,n.title)}</div>`;
 return code+content;
}
function libWire(){const root=$('library-workspace');
 // Event delegation prevents duplicate click handlers when the tree is rebuilt.
 root.onclick=async (event)=>{
  const note=event.target.closest('[data-lib-note]');
  if(note){event.preventDefault();await libChooseNote(note.dataset.libNote,note.dataset.libAnchor||'');return;}
  const code=event.target.closest('[data-lib-code]');
  if(code){
    event.preventDefault();
    const result=await call('open_code_link',code.dataset.libCode);
    if(!result?.ok)notify(result?.message||'Esta referência de código não está indexada.');
    return;
  }
  const ext=event.target.closest('[data-lib-external]');
  if(ext){event.preventDefault();const r=await call('open_video_link',ext.dataset.libExternal);if(!r?.ok)notify('Link salvo na nota. Abra-o pelo Obsidian para acessar o material.');return;}
  const folder=event.target.closest('[data-lib-folder]');
  if(folder){
   const path=folder.dataset.libFolder,child=folder.nextElementSibling;
   const expanded=child.classList.toggle('hidden')===false;
   folder.querySelector('.lib-chevron')?.classList.toggle('expanded',expanded);
   folder.setAttribute('aria-expanded',expanded?'true':'false');
   if(expanded)libraryState.expanded.add(path);else libraryState.expanded.delete(path);
   return;
  }
  const related=event.target.closest('[data-lib-relatedtab]');
  if(related){
   libraryState.relatedTab=related.dataset.libRelatedtab;
   const right=root.querySelector('.lib-right-panel');if(right)right.innerHTML=libMetaPanel(app.note);
   return;
  }
  const act=event.target.closest('[data-lib-action]');if(!act)return;
  const a=act.dataset.libAction;
  if(a==='trama-open'&&app.note){await libOpenInTrama(app.note.id);return;}
  if(a==='open'&&app.note)await call('open_note',app.note.id);
  if(a==='reveal'&&app.note)await call('reveal_note',app.note.id);
  if(a==='copy'&&app.note){
    const result=await call('copy_note_link',app.note.id);
    if(result?.ok){notify(result.message||'Link interno copiado.');}
    else{
      const wiki=result?.text||'[['+app.note.id.replace(/\.md$/i,'')+']]';
      try{await navigator.clipboard.writeText(wiki);notify('Link interno copiado.');}
      catch(_){notify('Não foi possível copiar. Link: '+wiki,8500);}
    }
  }
  if(a==='organize'){
    if(!await askTramaConfirm('Organizar biblioteca','Atualizar as notas a partir das fontes cadastradas, sem usar IA e sem sobrescrever alterações pessoais.','Organizar aulas'))return;
    notify('Organizando a biblioteca local…',7500);
    const r=await call('organize_library',true);
    notify(r?.message||'Não foi possível atualizar a organização.',7000);
    if(r?.ok){libraryState.allowEmpty=false;await refresh();}
    return;
  }
  if(a==='technical'){
    libraryState.showTechnical=!libraryState.showTechnical;
    await renderLibraryView();return;
  }
  if(a==='atlas'){
    const map=libNotes().find(n=>n.id==='01-Meu-Conhecimento/Mapa-da-Evolucao.md');
    if(map){app.selected=map.id;app.note=await call('note',map.id);await renderLibraryView();}
    else notify('O mapa aparece após organizar as aulas. Clique em Organizar aulas.');
    return;
  }
  if(a==='refresh')await refresh();
  if(a==='settings')await setView('settings');
  if(a==='graph')await setView('graph');
  if(a==='compare'&&app.note){
   const result=await call('compare_proposal',app.note.id);
   if(!result?.ok){notify(result?.message||'Não foi possível comparar.');return;}
   const dialog=$('trama-diff-dialog'), area=$('trama-diff-content');
   area.replaceChildren();
   for(const line of (result.diff||'Sem diferenças de texto.').split(String.fromCharCode(10))){
    const item=document.createElement('div'); item.textContent=line;
    item.className=line.startsWith('+')?'trama-diff-added':line.startsWith('-')?'trama-diff-removed':'trama-diff-line';
    area.append(item);
   }
   if(result.truncated){const notice=document.createElement('p');
    notice.textContent='Comparação limitada aos primeiros 500 registros.';area.append(notice);}
   const close=()=>{if(dialog.open)dialog.close();};
   $('trama-diff-close').onclick=close;$('trama-diff-dismiss').onclick=close;
   if(typeof dialog.showModal==='function')dialog.showModal();else dialog.setAttribute('open','');
   return;
  }
  if(a==='history'){
   if(await askTramaConfirm('Versões anteriores',
       'Quando você edita uma nota, o TRAMA preserva o original e cria propostas. Para recuperar versões mais antigas, utilize Recuperação de arquivos no Obsidian (se habilitado). Abrir esta nota?',
       'Abrir no Obsidian')&&app.note)await call('open_note',app.note.id);
  }
  if(a==='close'){libraryState.allowEmpty=true;app.selected=null;app.note=null;await renderLibraryView();}
  if(a==='new')await call('open_obsidian');
  if(a==='favorite'&&app.note){const r=await call('toggle_favorite',app.note.id);if(r?.ok){libraryState.favorites=new Set(r.favorites||[]);if(app.snapshot)app.snapshot.favorites=[...libraryState.favorites];await renderLibraryView();}else notify('Não foi possível salvar o favorito.');}
 };
 root.oninput=(event)=>{
  const input=event.target.closest('#lib-folder-search');if(!input)return;
  libraryState.search=input.value;
  libraryState.searchSeq++;
  libraryState.searchResults=null;
  libraryState.searchResolved='';
  const notes=libNotes().filter(n=>libraryState.showTechnical||!['00-Inicio','90-Sistema'].includes(n.section));
  root.querySelector('#lib-tree-content').innerHTML=libTreeMarkup(libSearchMatches(notes));
  const status=root.querySelector('#lib-search-status');
  if(status)status.textContent=libraryState.search.trim().length>=2?'Buscando também dentro das notas…':'';
  libScheduleContentSearch();
 };
 const search=root.querySelector('#lib-folder-search');if(search)search.value=libraryState.search;
}
async function renderLibraryView(){
 if(!app.snapshot)return;
 const root=$('library-workspace');$('overlay-screen').classList.add('hidden');$('list-panel').classList.add('hidden');$('note-panel').classList.add('hidden');$('details-panel').classList.add('hidden');root.classList.remove('hidden');
 const notes=libNotes();
 const visibleNotes=notes.filter(n=>libraryState.showTechnical||!['00-Inicio','90-Sistema'].includes(n.section));
 const treeNotes=libSearchMatches(visibleNotes);
 const isResolved=libraryState.search && libraryState.searchResolved===libraryState.search;
 const searchStatus=!libraryState.search?'':isResolved?
  `${libraryState.searchTotal} nota(s) encontrada(s) no título ou conteúdo`:
  libraryState.search.trim().length>=2?'Buscando dentro das notas…':'Digite pelo menos 2 caracteres para buscar no conteúdo';
 if(libraryState.search){
   // A global search must not show an unrelated previously-selected note.
   if(!treeNotes.some(n=>n.id===app.selected))app.selected=treeNotes[0]?.id||null;
 }else if(!notes.some(n=>n.id===app.selected)){
   app.selected=!libraryState.allowEmpty?notes[0]?.id||null:null;
 }
 app.note=app.selected?await call('note',app.selected):null;
 root.innerHTML=`<section class="lib-tree-panel"><div class="lib-tree-head"><span class="lib-obs-icon" aria-label="Obsidian"></span><div><strong>Biblioteca do Obsidian</strong><small>As mesmas notas do seu cofre, organizadas para estudar.</small></div></div><div class="lib-tree-tools"><button data-lib-action="organize" title="Atualizar organização sem gastar API">↻ Organizar aulas</button><button data-lib-action="atlas" title="Ver conceitos, fontes e retomadas">⌁ Minha evolução</button><button data-lib-action="technical" title="Mostrar ou ocultar pastas internas, sem mover arquivos">${libraryState.showTechnical?"Ocultar técnicas":"Pastas técnicas"}</button></div><div class="lib-search"><span>⌕</span><input id="lib-folder-search" aria-label="Buscar pastas e notas" placeholder="Buscar também dentro das notas..."></div><p class="lib-search-status" id="lib-search-status" role="status">${libE(searchStatus)}</p><div class="lib-tree-scroll" id="lib-tree-content">${libTreeMarkup(treeNotes)}</div></section><section class="lib-note-panel">${libCenterPanel(app.note)}</section><aside class="lib-right-panel">${app.note&&!app.note.error?libMetaPanel(app.note):''}</aside>`;
 libWire();
 if(libraryState.search.trim().length>=2 &&
    libraryState.searchResolved!==libraryState.search&&!libraryState.searchPending){
   libScheduleContentSearch();
 }
}

/* Notas geradas pelo TRAMA (Resumos, Atividades, Repositórios) abrem na tela própria. */
function libTramaTarget(id){
 let m=/^04-Resumos\/Aulas\/(Aula-\d{3,4})\.md$/.exec(id);if(m)return {kind:'lesson',id:m[1],label:'Abrir em Resumos'};
 m=/^04-Resumos\/Modulos\/([a-z0-9-]+)\.md$/.exec(id);if(m)return {kind:'module',id:m[1],label:'Abrir em Resumos'};
 m=/^04-Resumos\/Atividades\/([a-z0-9-]+)\.md$/.exec(id);if(m)return {kind:'activity',id:m[1],label:'Abrir atividade em Resumos'};
 m=/^03-Meus-Projetos\/Repositorios\/([A-Za-z0-9_.-]+)--([A-Za-z0-9_.-]+)\.md$/.exec(id);if(m)return {kind:'repo',id:'https://github.com/'+m[1]+'/'+m[2],label:'Abrir repositório em Projetos'};
 return null;
}
async function libOpenInTrama(id){
 const t=libTramaTarget(id);if(!t)return;
 if(t.kind==='repo'){if(typeof projectsOpenRepo==='function')await projectsOpenRepo(t.id,'');return;}
 if(typeof studyState==='undefined')return;
 if(t.kind==='lesson'){
  const o=await call('study_overview');
  const dev=o?.ok&&(o.development||[]).some(d=>d.lesson===t.id);
  studyState.kind=dev?'dev':'lesson';studyState[dev?'dev':'lesson']=t.id;
 }else{studyState.kind=t.kind;studyState[t.kind]=t.id;}
 app.view='study';if(typeof renderNavigation==='function')renderNavigation();await render();
}
