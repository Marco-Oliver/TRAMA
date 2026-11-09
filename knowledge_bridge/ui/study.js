'use strict';
/* Resumos de estudo (04-Resumos): resumo por aula e por módulo.
   Mesmo visual da Biblioteca. Nenhum HTML vindo da IA é interpretado:
   tudo passa por escapeHTML. Sem atributos style inline (CSP). */
const studyState={kind:'lesson',lesson:null,module:null,overview:null,view:null,search:'',
  open:{lessons:true,modules:true},busy:false};
const STUDY_STATUS={atualizado:['✓','Resumo em dia','ok'],desatualizado:['!','Fontes mudaram — atualize','warn'],
  pendente:['•','Resumo ainda não gerado','pending'],sem_analise:['○','Gravações ainda sem análise','off']};
const studyLessonLabel=id=>String(id||'').replace(/^Aula-0*(\d+)$/,(_,n)=>'Aula '+String(n).padStart(3,'0'));

function studyModuleName(id){
  if(id==='a-classificar')return 'A classificar';
  return studyState.overview?.modules?.find(m=>m.id===id)?.name||id;
}
function studyVideos(codes){
  return (codes||[]).length?`<span class="study-videos">${codes.map(c=>`<span class="study-video">${escapeHTML(c)}</span>`).join('')}</span>`:'';
}
function studyCard(title,icon,body,extra=''){
  return `<section class="study-card ${extra}"><h3><span class="study-card-ico">${icon}</span>${escapeHTML(title)}</h3><div class="study-card-body">${body}</div></section>`;
}
function studyEmpty(text){return `<p class="study-empty">${escapeHTML(text)}</p>`;}

async function studyLoadOverview(){
  const result=await call('study_overview');
  if(!result?.ok){studyState.overview=null;return result;}
  studyState.overview=result;
  const lessons=result.lessons||[];
  if(studyState.kind==='lesson'&&!lessons.some(l=>l.lesson===studyState.lesson)){
    studyState.lesson=(lessons.find(l=>l.status==='atualizado')||lessons[0])?.lesson||null;
  }
  if(studyState.kind==='module'&&studyState.module!=='a-classificar'&&
     !(result.modules||[]).some(m=>m.id===studyState.module)){
    studyState.kind='lesson';
  }
  return result;
}

async function renderStudyView(){
  const root=$('study-workspace');
  ['overlay-screen','list-panel','note-panel','details-panel','library-workspace'].forEach(id=>$(id).classList.add('hidden'));
  root.classList.remove('hidden');
  const loaded=await studyLoadOverview();
  if(!loaded?.ok){
    root.innerHTML=`<section class="lib-tree-panel"></section><section class="lib-note-panel"><div class="lib-note-scroll">${studyEmpty(loaded?.message||'Selecione o cofre do Obsidian em Ajustes para ver os resumos.')}</div></section><aside class="lib-right-panel"></aside>`;
    return;
  }
  if(studyState.kind==='lesson'&&studyState.lesson)studyState.view=await call('study_lesson',studyState.lesson);
  else if(studyState.kind==='module'&&studyState.module)studyState.view=await call('study_module',studyState.module);
  else studyState.view=null;
  root.innerHTML=`<section class="lib-tree-panel study-tree">${studyTreeHTML()}</section>
    <section class="lib-note-panel"><div class="lib-tab-strip"><div class="lib-open-tab"><span>▤</span><span class="lib-tab-text">${escapeHTML(studyState.kind==='module'?'Resumo do Módulo':'Resumo da Aula')}</span></div></div>
    <div class="lib-note-scroll" id="study-content">${studyContentHTML()}</div></section>
    <aside class="lib-right-panel" id="study-side">${studySideHTML()}</aside>`;
  studyWire(root);
}

function studyTreeHTML(){
  const o=studyState.overview||{lessons:[],modules:[],unassigned:[]};
  const q=studyState.search.trim().toLowerCase();
  const matches=l=>!q||(l.lesson+' '+l.title+' '+l.phrase).toLowerCase().includes(q);
  const lessonRow=(l,depth)=>{
    const st=STUDY_STATUS[l.status]||STUDY_STATUS.pendente;
    const selected=studyState.kind==='lesson'&&studyState.lesson===l.lesson;
    return `<button type="button" class="lib-file-row depth-${depth}${selected?' selected':''}" data-study-lesson="${escapeHTML(l.lesson)}" title="${escapeHTML(st[1])}"><span class="study-dot ${st[2]}">${st[0]}</span><span class="file-label">${escapeHTML(studyLessonLabel(l.lesson))}${l.title?' — '+escapeHTML(l.title):''}</span></button>`;
  };
  const folder=(key,label,count,open,depth,top=false)=>`<button type="button" class="lib-folder-row depth-${depth}" data-study-toggle="${escapeHTML(key)}"><span class="lib-chevron${open?' expanded':''}">▶</span><span class="lib-folder-icon${top?' top':''}">${top?'▰':'▱'}</span><strong>${escapeHTML(label)}</strong><small class="study-count">${count}</small></button>`;
  const lessons=(o.lessons||[]).filter(matches);
  let html=`<div class="lib-tree-head"><span class="study-head-ico">▤</span><div><strong>Resumos</strong><small>Área de estudo com resumos das aulas e dos módulos.</small></div></div>
   <div class="study-tree-actions"><button type="button" id="study-generate" class="study-primary"${o.pending?'':' disabled'}>${o.pending?`Gerar resumos (${o.pending})`:'Resumos em dia'}</button></div>
   <div class="lib-search"><span>⌕</span><input id="study-search" maxlength="80" placeholder="Buscar nos resumos..." value="${escapeHTML(studyState.search)}" aria-label="Buscar nos resumos"></div>
   <div class="lib-tree-scroll">`;
  html+=folder('lessons','Aulas',lessons.length,studyState.open.lessons,0,true);
  if(studyState.open.lessons){
    html+=lessons.length?lessons.map(l=>lessonRow(l,1)).join(''):`<p class="study-empty study-indent">${q?'Nenhuma aula encontrada.':'Importe e processe aulas para gerar resumos.'}</p>`;
  }
  const modules=[...(o.modules||[])];
  if((o.unassigned||[]).length)modules.push({id:'a-classificar',name:'A classificar',lessons:o.unassigned});
  html+=folder('modules','Módulos',modules.length,studyState.open.modules,0,true);
  if(studyState.open.modules){
    for(const m of modules){
      const key='module:'+m.id,open=!!studyState.open[key];
      html+=folder(key,m.name,(m.lessons||[]).length,open,1);
      if(open){
        const selected=studyState.kind==='module'&&studyState.module===m.id;
        html+=`<button type="button" class="lib-file-row depth-2${selected?' selected':''}" data-study-module="${escapeHTML(m.id)}"><span class="lib-file-icon">◆</span><span class="file-label">Resumo do módulo</span></button>`;
        const byId=new Map((o.lessons||[]).map(l=>[l.lesson,l]));
        html+=(m.lessons||[]).map(id=>byId.get(id)).filter(Boolean).filter(matches).map(l=>lessonRow(l,2)).join('');
      }
    }
    html+=`<button type="button" class="lib-file-row depth-1 study-new-module" id="study-new-module"><span class="lib-file-icon">＋</span><span class="file-label">Novo módulo</span></button>`;
  }
  return html+'</div>';
}

function studyContentHTML(){
  const v=studyState.view;
  if(!v||!v.ok){
    return `<div class="lib-breadcrumb">Resumos</div><h1 class="lib-title">Resumos de estudo</h1>${studyEmpty(v?.message||'Escolha uma aula ou um módulo na lista ao lado.')}`;
  }
  return studyState.kind==='module'?studyModuleHTML(v):studyLessonHTML(v);
}

function studyLessonHTML(v){
  const st=STUDY_STATUS[v.status]||STUDY_STATUS.pendente;
  const mods=(v.modules||[]).map(id=>`<button type="button" class="study-chip" data-study-module="${escapeHTML(id)}">${escapeHTML(studyModuleName(id))}</button>`).join('')||'<span class="study-chip muted">A classificar</span>';
  const origin={manual:'escolhido por você',ia:'sugerido pela IA',automatico:'por palavras-chave'}[v.module_origin]||'';
  let html=`<div class="lib-breadcrumb">Resumos <b>›</b> Aulas <b>›</b> ${escapeHTML(studyLessonLabel(v.lesson))}</div>
   <h1 class="lib-title">${escapeHTML(studyLessonLabel(v.lesson))}${v.title?' — '+escapeHTML(v.title):''}</h1>
   <div class="lib-note-meta"><span class="study-status ${st[2]}">${st[0]} ${escapeHTML(st[1])}</span>${v.date?`<span>▦ Agenda ${escapeHTML(v.date)}</span>`:''}${v.generated?`<span>◷ Gerado em ${escapeHTML(v.generated)}</span>`:''}</div>
   <div class="study-modules-line"><span>Módulos:</span>${mods}<button type="button" class="study-link-btn" id="study-edit-lesson-modules">Alterar</button>${origin?`<small>${escapeHTML(origin)}</small>`:''}</div>`;
  const s=v.summary;
  if(!s){
    const can=v.status==='pendente'||v.status==='desatualizado';
    return html+studyCard('Resumo ainda não gerado','▤',
      `<p>${v.status==='sem_analise'?'As gravações desta aula ainda não foram analisadas. Processe a aula em <strong>Aulas</strong> primeiro.':'Gere o resumo de estudo desta aula a partir das análises já salvas (1 chamada à IA).'}</p>`+
      (can?'<button type="button" class="study-primary" id="study-generate-one">Gerar resumo desta aula</button>':''));
  }
  if(v.status==='desatualizado'){
    html+=`<div class="study-alert">As fontes desta aula mudaram depois deste resumo. <button type="button" class="study-link-btn" id="study-generate-one">Atualizar resumo</button></div>`;
  }
  html+=`<div class="study-phrase"><strong>Em poucas palavras:</strong> ${escapeHTML(s.em_uma_frase)}</div>`;
  if((s.mapa_mental||[]).length){
    html+=studyCard('Mapa mental','◎',`<div class="study-mind">${s.mapa_mental.map(t=>`<div class="study-mind-theme"><h4>${escapeHTML(t.tema)}</h4><ul>${t.pontos.map(p=>`<li>${escapeHTML(p.texto)}${studyVideos(p.videos)}</li>`).join('')}</ul></div>`).join('')}</div>`,'wide');
  }
  if((s.o_que_saber||[]).length){
    html+=studyCard('O que você precisa saber','✓',`<ol class="study-know">${s.o_que_saber.map(k=>`<li><strong>${escapeHTML(k.ponto)}</strong>${k.explicacao?' — '+escapeHTML(k.explicacao):''}${studyVideos(k.videos)}</li>`).join('')}</ol>`,'wide');
  }
  html+='<div class="study-grid">';
  html+=studyCard('Comandos e código','⌨',(s.comandos||[]).length?s.comandos.map(c=>`<div class="study-cmd"><pre><code>${escapeHTML(c.codigo)}</code></pre><p>${escapeHTML(c.para_que||'')} <small>(fonte: ${escapeHTML(c.origem)}${(c.videos||[]).length?' · '+escapeHTML(c.videos.join(', ')):''})</small></p></div>`).join(''):studyEmpty('Nenhum comando literal nas fontes desta aula.'));
  const links=s.ligacoes||{};
  html+=studyCard('Ligação com outras aulas','⇄',(links.anterior||links.prepara)?
    (links.anterior?`<p><strong>Vem de:</strong> ${escapeHTML(links.anterior)}</p>`:'')+(links.prepara?`<p><strong>Prepara para:</strong> ${escapeHTML(links.prepara)}</p>`:''):studyEmpty('Sem ligação identificada nas fontes.'));
  html+=studyCard('Lacunas','⚠',(s.lacunas||[]).length?`<ul>${s.lacunas.map(g=>`<li><strong>${escapeHTML(g.item)}</strong>${g.situacao?' — '+escapeHTML(g.situacao):''}</li>`).join('')}</ul>`:studyEmpty('Nenhuma lacuna entre a agenda e as gravações.'),'warn');
  html+=studyCard('Para fazer','☐',(s.para_fazer||[]).length?`<ul class="study-todo">${s.para_fazer.map(t=>`<li>${escapeHTML(t)}</li>`).join('')}</ul>`:studyEmpty('Nenhuma atividade registrada.'));
  html+=studyCard('Dúvidas em aberto','?',(v.doubts||[]).length?`<ul>${v.doubts.map(d=>`<li>${escapeHTML(d.pergunta)} <small>${escapeHTML(d.video||'')} · ${escapeHTML(d.estado)}</small></li>`).join('')}</ul>`:studyEmpty('Nenhuma dúvida em aberto.'));
  html+=studyCard('Revisão rápida','✎',(s.revisao||[]).length?s.revisao.map((q,i)=>`<details class="study-quiz"><summary>${i+1}. ${escapeHTML(q.pergunta)}</summary><p>${escapeHTML(q.resposta)}</p></details>`).join(''):studyEmpty('Sem perguntas de revisão.'));
  html+='</div>';
  if(s.comandos_descartados)html+=`<p class="study-footnote">${s.comandos_descartados} comando(s) sugerido(s) pela IA foram descartados por não aparecerem literalmente nas fontes.</p>`;
  return html;
}

function studyModuleHTML(v){
  const m=v.module||{},s=v.summary,living=v.living||{aulas:[],conceitos:[],duvidas:[]},st=v.status||{};
  const editable=m.id!=='a-classificar';
  let html=`<div class="lib-breadcrumb">Resumos <b>›</b> Módulos <b>›</b> ${escapeHTML(m.name||'')}</div>
   <h1 class="lib-title">${escapeHTML(m.name||'Módulo')}</h1>
   ${m.description?`<p class="lib-note-intro">${escapeHTML(m.description)}</p>`:''}
   <div class="lib-note-meta"><span>${living.aulas.length} aula(s)</span><span>${st.summarized||0} com resumo</span>${v.generated?`<span>◷ Resumo do módulo em ${escapeHTML(v.generated)}</span>`:''}</div>`;
  if(editable){
    html+=`<div class="study-module-tools"><button type="button" class="study-primary" id="study-update-module"${st.summarized?'':' disabled'}>${s?'Atualizar resumo do módulo':'Gerar resumo do módulo'}${st.new_since_summary&&s?` (${st.new_since_summary} aula(s) nova(s))`:''}</button>
      <button type="button" id="study-edit-module">Editar</button><button type="button" id="study-move-up" title="Mover para cima">↑</button><button type="button" id="study-move-down" title="Mover para baixo">↓</button><button type="button" id="study-delete-module" class="study-danger">Excluir</button></div>`;
  }
  if(s){
    html+=`<div class="study-phrase"><strong>Visão geral:</strong> ${escapeHTML(s.visao_geral)}</div>`;
    if((s.trilha||[]).length)html+=studyCard('Trilha do aprendizado','➜',`<ol class="study-know">${s.trilha.map(t=>`<li><strong>${escapeHTML(t.etapa)}</strong> — ${escapeHTML(t.resumo)} ${t.aulas.map(a=>`<button type="button" class="study-chip" data-study-lesson="${escapeHTML(a)}">${escapeHTML(studyLessonLabel(a))}</button>`).join('')}</li>`).join('')}</ol>`,'wide');
    html+='<div class="study-grid">';
    if((s.conceitos_chave||[]).length)html+=studyCard('Conceitos-chave','◆',`<ul>${s.conceitos_chave.map(c=>`<li><strong>${escapeHTML(c.conceito)}</strong> — ${escapeHTML(c.explicacao)}</li>`).join('')}</ul>`);
    if(s.como_se_conecta)html+=studyCard('Como tudo se conecta','⇄',`<p>${escapeHTML(s.como_se_conecta)}</p>`);
    if((s.pontos_de_atencao||[]).length)html+=studyCard('Pontos de atenção','⚠',`<ul>${s.pontos_de_atencao.map(t=>`<li>${escapeHTML(t)}</li>`).join('')}</ul>`,'warn');
    if((s.checklist_revisao||[]).length)html+=studyCard('Checklist de revisão','☐',`<ul class="study-todo">${s.checklist_revisao.map(t=>`<li>${escapeHTML(t)}</li>`).join('')}</ul>`);
    html+='</div>';
  }else if(editable){
    html+=`<div class="study-alert">O resumo do módulo pela IA é gerado automaticamente depois de 3 aulas com resumo, e atualizado a cada 5 aulas novas. A página viva abaixo é atualizada a cada aula, sem IA.</div>`;
  }
  html+=studyCard('Página viva — aulas do módulo','▤',living.aulas.length?living.aulas.map(a=>`<div class="study-living-row"><button type="button" class="study-link-btn" data-study-lesson="${escapeHTML(a.aula)}">${escapeHTML(studyLessonLabel(a.aula))}${a.titulo?' — '+escapeHTML(a.titulo):''}</button>${a.em_uma_frase?`<p>${escapeHTML(a.em_uma_frase)}</p>`:'<p class="study-empty">Resumo da aula ainda não gerado.</p>'}${a.pontos.length?`<ul>${a.pontos.map(p=>`<li>${escapeHTML(p)}</li>`).join('')}</ul>`:''}</div>`).join(''):studyEmpty('Nenhuma aula neste módulo ainda.'),'wide');
  if(living.conceitos.length)html+=studyCard('Conceitos vistos no módulo','◆',`<div class="study-chips">${living.conceitos.map(c=>`<span class="study-chip muted" title="${escapeHTML(c.aulas.join(', '))}">${escapeHTML(c.nome)}</span>`).join('')}</div>`,'wide');
  if(living.duvidas.length)html+=studyCard('Dúvidas em aberto no módulo','?',`<ul>${living.duvidas.map(d=>`<li><button type="button" class="study-link-btn" data-study-lesson="${escapeHTML(d.aula)}">${escapeHTML(studyLessonLabel(d.aula))}</button> ${escapeHTML(d.pergunta)}</li>`).join('')}</ul>`,'wide');
  return html;
}

function studySideHTML(){
  const v=studyState.view;
  if(!v?.ok)return '';
  const note=v.note;
  const fav=libraryState.favorites?.has?.(note);
  let html=`<section class="lib-side-card"><h3><span class="card-heading-ico">⚙</span>Ações do resumo</h3><div class="side-body">
    <button type="button" class="lib-side-button" id="study-open-obsidian"><span class="action-left">↗ Abrir nota no Obsidian</span></button>
    <button type="button" class="lib-side-button" id="study-copy-link"><span class="action-left">▤ Copiar link interno</span></button>
    <button type="button" class="lib-side-button" id="study-favorite"><span class="action-left">${fav?'★ Remover dos favoritos':'☆ Adicionar aos favoritos'}</span></button>`;
  if(studyState.kind==='lesson')html+=`<button type="button" class="lib-side-button" id="study-open-evidence"><span class="action-left">◈ Abrir aula completa (evidências)</span></button>`;
  html+='</div></section>';
  if(studyState.kind==='lesson'){
    const vids=(v.videos||[]).map(x=>`<div class="lib-stat"><span class="stat-label">▶ ${escapeHTML(x.code||'')}</span><span class="stat-value muted">${escapeHTML(x.label)}</span></div>`).join('');
    html+=`<section class="lib-side-card"><h3><span class="card-heading-ico">▶</span>Gravações</h3><div class="side-body">${vids||studyEmpty('Sem gravações.')}</div></section>`;
    if((v.materials||[]).length)html+=`<section class="lib-side-card"><h3><span class="card-heading-ico">▤</span>Material oficial</h3><div class="side-body">${v.materials.map((m,i)=>`<button type="button" class="lib-link" data-study-material="${i}"><span>↗</span><span>${escapeHTML(m.title||m.url)}</span></button>`).join('')}</div></section>`;
  }
  return html;
}

function studyWire(root){
  root.querySelectorAll('[data-study-toggle]').forEach(el=>el.addEventListener('click',()=>{
    const key=el.dataset.studyToggle;studyState.open[key]=!studyState.open[key];
    root.querySelector('.study-tree').innerHTML=studyTreeHTML();studyWire(root);
  }));
  root.querySelectorAll('[data-study-lesson]').forEach(el=>el.addEventListener('click',async()=>{
    studyState.kind='lesson';studyState.lesson=el.dataset.studyLesson;await renderStudyView();
  }));
  root.querySelectorAll('[data-study-module]').forEach(el=>el.addEventListener('click',async()=>{
    studyState.kind='module';studyState.module=el.dataset.studyModule;
    studyState.open.modules=true;studyState.open['module:'+studyState.module]=true;await renderStudyView();
  }));
  const search=root.querySelector('#study-search');
  if(search)search.addEventListener('input',()=>{
    studyState.search=search.value;
    const pos=search.selectionStart;
    root.querySelector('.study-tree').innerHTML=studyTreeHTML();studyWire(root);
    const again=root.querySelector('#study-search');again.focus();again.setSelectionRange(pos,pos);
  });
  const bind=(id,fn)=>{const el=root.querySelector('#'+id);if(el)el.addEventListener('click',fn);};
  bind('study-generate',()=>studyGenerate(null));
  bind('study-generate-one',()=>studyGenerate(studyState.lesson));
  bind('study-new-module',()=>studyOpenModuleDialog(null));
  bind('study-edit-module',()=>studyOpenModuleDialog(studyState.view?.module));
  bind('study-delete-module',studyDeleteModule);
  bind('study-move-up',()=>studyMoveModule(-1));
  bind('study-move-down',()=>studyMoveModule(1));
  bind('study-update-module',studyUpdateModule);
  bind('study-edit-lesson-modules',studyOpenLessonModules);
  bind('study-open-obsidian',async()=>{const r=await call('open_note',studyState.view.note);if(!r?.ok)notify('Abra o cofre no Obsidian e tente novamente. A nota é criada após gerar o resumo.');});
  bind('study-copy-link',async()=>{
    const id=studyState.view.note;const r=await call('copy_note_link',id);
    if(r?.ok){notify('Link copiado.');return;}
    const text='[['+id.replace(/\.md$/,'')+']]';
    try{await navigator.clipboard.writeText(text);notify('Link copiado.');}catch(_){notify('Copie o link: '+text,8500);}
  });
  bind('study-favorite',async()=>{
    const r=await call('toggle_favorite',studyState.view.note);
    if(!r?.ok){notify(r?.message||'A nota ainda não existe no cofre. Gere o resumo primeiro.');return;}
    libraryState.favorites=new Set(r.favorites||[]);if(app.snapshot)app.snapshot.favorites=r.favorites||[];
    $('study-side').innerHTML=studySideHTML();studyWire(root);
    notify(libraryState.favorites.has(studyState.view.note)?'Adicionado aos favoritos.':'Removido dos favoritos.');
  });
  bind('study-open-evidence',async()=>{
    app.view='lessons';app.selected=studyState.view.evidence_note;app.tab='Nota completa';renderNavigation();await render();
  });
  root.querySelectorAll('[data-study-material]').forEach(el=>el.addEventListener('click',async()=>{
    const m=studyState.view?.materials?.[Number(el.dataset.studyMaterial)];
    if(!m)return;const r=await call('open_video_link',m.url);if(!r?.ok)notify(r?.message||'Não foi possível abrir o material.');
  }));
}

async function studyGenerate(lesson){
  if(studyState.busy)return;
  const pending=studyState.overview?.pending||0;
  if(!lesson&&!pending){notify('Todos os resumos de estudo já estão em dia.');return;}
  const text=lesson?`O resumo de estudo de ${studyLessonLabel(lesson)} será gerado a partir das análises já salvas (1 chamada à IA).`:
    `Serão gerados ${pending} resumo(s) de aula (1 chamada cada, com pausa entre elas para respeitar o limite por minuto). Resumos de módulo vencidos também são atualizados.`;
  if(!app.aiConsent&&!await askTramaConfirm('Gerar resumos de estudo',text,'Gerar resumos'))return;
  studyState.busy=true;notify('Gerando resumos de estudo… mantenha o TRAMA aberto.',60000);
  document.querySelectorAll('#study-generate,#study-generate-one').forEach(b=>{b.disabled=true;b.textContent='Gerando…';});
  try{
    const r=await call('study_generate',true,lesson);
    notify(r?.message||'Não foi possível gerar os resumos.',9000);
  }finally{studyState.busy=false;await renderStudyView();}
}

async function studyUpdateModule(){
  const v=studyState.view;if(!v?.module||studyState.busy)return;
  if(!app.aiConsent&&!await askTramaConfirm('Atualizar resumo do módulo',`O resumo de ${v.module.name} será refeito a partir dos resumos das aulas (1 a 2 chamadas à IA).`,'Atualizar'))return;
  studyState.busy=true;const btn=$('study-update-module');if(btn){btn.disabled=true;btn.textContent='Atualizando…';}
  try{const r=await call('study_update_module',v.module.id,true);notify(r?.message||'Não foi possível atualizar.',8000);}
  finally{studyState.busy=false;await renderStudyView();}
}

async function studyDeleteModule(){
  const m=studyState.view?.module;if(!m)return;
  if(!await askTramaConfirm('Excluir módulo',`Excluir “${m.name}”? As aulas e os resumos das aulas continuam salvos; aulas só deste módulo vão para “A classificar”.`,'Excluir'))return;
  const r=await call('study_delete_module',m.id,true);
  notify(r?.ok?'Módulo excluído.':(r?.message||'Não foi possível excluir.'));
  if(r?.ok){studyState.kind='lesson';}
  await renderStudyView();
}

async function studyMoveModule(direction){
  const m=studyState.view?.module;if(!m)return;
  const r=await call('study_move_module',m.id,direction);
  if(!r?.ok)notify(r?.message||'Não foi possível mover.');
  await renderStudyView();
}

function studyShowDialog(dlg){if(typeof dlg.showModal==='function')dlg.showModal();else dlg.setAttribute('open','');}
function studyCloseDialog(dlg){if(dlg.open&&typeof dlg.close==='function')dlg.close();else dlg.removeAttribute('open');}

function studyOpenModuleDialog(module){
  const dlg=$('study-module-dialog'),form=$('study-module-form');
  form.reset();form.dataset.moduleId=module?.id||'';
  $('study-module-title').textContent=module?'Editar módulo':'Novo módulo';
  form.elements.namedItem('name').value=module?.name||'';
  form.elements.namedItem('description').value=module?.description||'';
  form.elements.namedItem('keywords').value=(module?.keywords||[]).join(', ');
  $('study-module-feedback').textContent='';
  studyShowDialog(dlg);form.elements.namedItem('name').focus();
}

async function studySaveModule(event){
  event.preventDefault();
  const form=$('study-module-form'),feedback=$('study-module-feedback');
  const record={name:form.elements.namedItem('name').value,description:form.elements.namedItem('description').value,
    keywords:form.elements.namedItem('keywords').value};
  if(form.dataset.moduleId)record.id=form.dataset.moduleId;
  const r=await call('study_save_module',record);
  if(!r?.ok){feedback.textContent=r?.message||'Não foi possível salvar.';return;}
  studyCloseDialog($('study-module-dialog'));
  studyState.kind='module';studyState.module=r.module.id;studyState.open.modules=true;studyState.open['module:'+r.module.id]=true;
  notify('Módulo salvo.');await renderStudyView();
}

function studyOpenLessonModules(){
  const v=studyState.view;if(!v?.lesson)return;
  const box=$('study-lesson-modules-list');box.replaceChildren();
  for(const m of studyState.overview?.modules||[]){
    const label=document.createElement('label');label.className='study-check';
    const input=document.createElement('input');input.type='checkbox';input.value=m.id;input.checked=(v.modules||[]).includes(m.id);
    label.append(input,document.createTextNode(' '+m.name));box.append(label);
  }
  $('study-lesson-modules-title').textContent='Módulos de '+studyLessonLabel(v.lesson);
  $('study-lesson-modules-feedback').textContent=v.module_origin==='manual'?'Escolha manual ativa: a IA não muda estes módulos.':'Hoje os módulos são automáticos. Ao salvar, a sua escolha passa a valer sempre.';
  studyShowDialog($('study-lesson-modules-dialog'));
}

async function studySaveLessonModules(reset){
  const v=studyState.view;if(!v?.lesson)return;
  const ids=reset?null:[...$('study-lesson-modules-list').querySelectorAll('input:checked')].map(i=>i.value);
  const r=await call('study_set_lesson_modules',v.lesson,ids);
  if(!r?.ok){$('study-lesson-modules-feedback').textContent=r?.message||'Não foi possível salvar.';return;}
  studyCloseDialog($('study-lesson-modules-dialog'));
  notify(reset?'Módulos voltaram ao automático.':'Módulos da aula salvos.');await renderStudyView();
}

function studyBind(){
  const form=$('study-module-form');if(!form)return;
  form.addEventListener('submit',studySaveModule);
  $('study-module-close').addEventListener('click',()=>studyCloseDialog($('study-module-dialog')));
  $('study-module-cancel').addEventListener('click',()=>studyCloseDialog($('study-module-dialog')));
  $('study-lesson-modules-close').addEventListener('click',()=>studyCloseDialog($('study-lesson-modules-dialog')));
  $('study-lesson-modules-save').addEventListener('click',()=>studySaveLessonModules(false));
  $('study-lesson-modules-reset').addEventListener('click',()=>studySaveLessonModules(true));
}
studyBind();
