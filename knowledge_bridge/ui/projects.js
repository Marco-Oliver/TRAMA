'use strict';
/* Projetos: repositórios por dono (Meus / Dupla / Professor), pares lado a lado,
   seletor de versão (entregue, main, branches, tags e pastas V0/V1/V2) e
   navegação de arquivos estilo GitHub, com ícones próprios do TRAMA.
   Sem HTML vindo do GitHub: todo texto passa por escapeHTML. Sem style inline (CSP). */
const projState={overview:null,repo:null,view:null,version:'',folder:'',tree:null,file:null,
  expanded:new Set(),search:'',open:{meu:true,dupla:true,professor:true,outro:true},loading:false};
const PROJ_OWNER={meu:'Meu',dupla:'Dupla',professor:'Professor',outro:'Outro'};

/* ---------- ícones (desenho próprio, inspirado na ideia de cores por tipo) ---------- */
const PROJ_FILE_ICONS=[
  [/\.spec\.ts$|\.test\.ts$/i,'tst','TS'],[/tests?\.cs$/i,'tst','C#'],
  [/\.cs$/i,'cs','C#'],[/\.(cshtml|razor)$/i,'razor','@'],[/\.csproj$/i,'proj','PJ'],[/\.sln$/i,'sln','SL'],
  [/\.tsx?$/i,'ts','TS'],[/\.jsx?$|\.mjs$/i,'js','JS'],[/\.html?$/i,'html','<>'],[/\.s?css$/i,'css','#'],
  [/(^|\/)package(-lock)?\.json$/i,'npm','N'],[/\.json$/i,'json','{}'],[/\.md$/i,'md','M↓'],
  [/\.sql$/i,'sql','DB'],[/\.py$/i,'py','PY'],[/\.(xml|config|props)$/i,'xml','<>'],
  [/\.(ya?ml)$/i,'yml','Y'],[/(^|\/)\.git(ignore|attributes)$/i,'git','G'],[/(^|\/)dockerfile$/i,'docker','D'],
  [/\.(png|jpe?g|gif|svg|webp|ico)$/i,'img','▣'],[/\.(txt|log)$/i,'txt','≡'],[/\.http$/i,'http','H']];
const PROJ_FOLDER_COLORS=[
  [/^controllers?$/i,'ctrl'],[/^views?$|^pages?$/i,'view'],[/^(models?|entities|entidades|dominio|domain)$/i,'model'],
  [/^wwwroot$|^public$|^static$/i,'www'],[/^migrations?$/i,'migr'],[/tests?$|^specs?$/i,'test'],
  [/^src$|^app$/i,'src'],[/^\.github$|^\.vscode$|^\.git$/i,'meta'],[/^services?$|^servicos$|^aplicacao$|^application$/i,'svc'],
  [/^(data|dados|infra|infraestrutura|repositor(y|ies|ios))$/i,'data'],[/^components?$|^shared$|^compartilhado$/i,'comp'],
  [/^(assets|images?|img|imagens|css|js|lib)$/i,'asset'],[/^(config|properties|configuracoes)$/i,'cfg'],
  [/^(v|vers[aã]o)[ ._-]*\d+/i,'ver']];
function projFileIcon(path){
  for(const [re,cls,label] of PROJ_FILE_ICONS)if(re.test(path))return `<span class="pfi pfi-${cls}" aria-hidden="true"><b>${escapeHTML(label)}</b></span>`;
  return '<span class="pfi pfi-other" aria-hidden="true"><b></b></span>';
}
function projFolderIcon(name,open){
  let cls='plain';for(const [re,c] of PROJ_FOLDER_COLORS)if(re.test(name)){cls=c;break;}
  return `<span class="lib-folder-icon pf-fold pfo-${cls}" aria-hidden="true"></span>`;
}
const PROJ_REPO_ICON='<span class="repo-ico" aria-hidden="true"><svg viewBox="0 0 16 16"><circle cx="5" cy="3.6" r="1.6"/><circle cx="5" cy="12.4" r="1.6"/><circle cx="11.2" cy="6" r="1.6"/><path d="M5 5.2v5.6M11.2 7.6c0 2.2-2.4 2.4-5.2 3.4"/></svg></span>';
function projOwnerBadge(klass){return `<span class="owner-badge owner-${escapeHTML(klass)}">${escapeHTML(PROJ_OWNER[klass]||'Outro')}</span>`;}
function projSize(n){return n>=1024?(n/1024).toFixed(n>=10240?0:1)+' KB':n+' B';}

/* ---------- carregamento ---------- */
async function renderProjectsView(){
  const root=$('projects-workspace');
  ['overlay-screen','list-panel','note-panel','details-panel','library-workspace','study-workspace'].forEach(id=>$(id).classList.add('hidden'));
  root.classList.remove('hidden');
  const r=await call('projects_overview');
  if(!r?.ok){root.innerHTML=`<section class="lib-tree-panel"></section><section class="lib-note-panel"><div class="lib-note-scroll"><p class="study-empty">${escapeHTML(r?.message||'Selecione o cofre do Obsidian em Ajustes.')}</p></div></section><aside class="lib-right-panel"></aside>`;return;}
  projState.overview=r;
  if(projState.repo&&!projAllRepos().some(x=>x.url===projState.repo)){projState.repo=null;projState.view=null;}
  projPaint();
}
function projAllRepos(){return (projState.overview?.groups||[]).flatMap(g=>g.repos);}

async function projectsOpenRepo(url,sha){
  app.view='projects';if(typeof renderNavigation==='function')renderNavigation();
  if(app.graphView){app.graphView.destroy();app.graphView=null;}
  projState.repo=null;await renderProjectsView();
  await projSelectRepo(url,sha||'');
}

async function projSelectRepo(url,preferSha){
  projState.repo=url;projState.view=null;projState.tree=null;projState.file=null;projState.folder='';
  projState.expanded=new Set();projState.search='';projState.loading=true;projPaint();
  let view=await call('project_repo',url,true);
  if(!view?.ok){projState.loading=false;notify(view?.message||'Não foi possível abrir o repositório.');projPaint();return;}
  projState.view=view;
  if(view.warning)notify('GitHub: '+view.warning,8000);
  const versions=view.versions||[];
  const chosen=(preferSha&&versions.find(v=>v.sha===preferSha))||versions.find(v=>v.kind==='main')||versions[0];
  projState.version=chosen?chosen.sha:'';
  if(projState.version)await projLoadTree();
  projState.loading=false;projPaint();
}

async function projLoadTree(){
  projState.tree=null;projState.file=null;
  const r=await call('project_tree',projState.repo,projState.version);
  if(!r?.ok){notify(r?.message||'Não foi possível ler a árvore do GitHub.',8000);return;}
  projState.tree=r;
  if(projState.folder&&!(r.version_folders||[]).includes(projState.folder))projState.folder='';
  const base=projState.folder?projState.folder+'/':'';
  const readme=(r.files||[]).find(f=>f.path.toLowerCase()===(base+'readme.md'));
  if(readme)await projOpenFile(readme.path,false);
}

async function projOpenFile(path,paint=true){
  projState.file={path,loading:true};if(paint)projPaintMain();
  const r=await call('project_file',projState.repo,projState.version,path);
  projState.file=r?.ok?{path,content:r.content,size:r.size}:{path,error:r?.message||'Não foi possível abrir o arquivo.'};
  if(paint){projPaintMain();projPaintTree();}
}

/* ---------- árvore ---------- */
function projBuildTree(){
  const files=projState.tree?.files||[];
  const base=projState.folder?projState.folder+'/':'';
  const root={dirs:new Map(),files:[]};
  const q=projState.search.trim().toLowerCase();
  for(const f of files){
    if(base&&!f.path.startsWith(base))continue;
    const rel=f.path.slice(base.length);
    if(q&&!rel.toLowerCase().includes(q))continue;
    const parts=rel.split('/');let node=root,acc=base.replace(/\/$/,'');
    for(const part of parts.slice(0,-1)){
      acc=acc?acc+'/'+part:part;
      if(!node.dirs.has(part))node.dirs.set(part,{path:acc,dirs:new Map(),files:[]});
      node=node.dirs.get(part);
    }
    node.files.push({...f,name:parts.at(-1)});
  }
  return root;
}
function projTreeRows(node,depth,forceOpen){
  let html='';
  const dirs=[...node.dirs.entries()].sort((a,b)=>a[0].localeCompare(b[0],'pt',{sensitivity:'base'}));
  for(const [name,child] of dirs){
    const open=forceOpen||projState.expanded.has(child.path);
    html+=`<button type="button" class="pf-row pf-dir pf-d${Math.min(depth,9)}" data-pf-dir="${escapeHTML(child.path)}" title="${escapeHTML(child.path)}"><span class="pf-chev${open?' open':''}">▶</span>${projFolderIcon(name,open)}<span class="pf-name">${escapeHTML(name)}</span></button>`;
    if(open)html+=projTreeRows(child,depth+1,forceOpen);
  }
  for(const f of node.files.sort((a,b)=>a.name.localeCompare(b.name,'pt',{sensitivity:'base'}))){
    const sel=projState.file?.path===f.path;
    html+=`<button type="button" class="pf-row pf-file pf-d${Math.min(depth,9)}${sel?' selected':''}" data-pf-file="${escapeHTML(f.path)}" title="${escapeHTML(f.path)} · ${projSize(f.size)}"><span class="pf-chev blank"></span>${projFileIcon(f.name)}<span class="pf-name">${escapeHTML(f.name)}</span></button>`;
  }
  return html;
}
function projVersionOptions(){
  const v=projState.view;if(!v)return '';
  const groups={entregue:'Versões entregues',main:'Atual',branch:'Branches',tag:'Tags'};
  let html='';
  for(const kind of ['entregue','main','branch','tag']){
    const items=(v.versions||[]).filter(x=>x.kind===kind);if(!items.length)continue;
    html+=`<optgroup label="${escapeHTML(groups[kind])}">${items.map(x=>`<option value="sha|${escapeHTML(x.sha)}|"${x.sha===projState.version&&!projState.folder?' selected':''}>${escapeHTML(x.label)} · ${escapeHTML(x.sha.slice(0,7))}</option>`).join('')}</optgroup>`;
  }
  const folders=projState.tree?.version_folders||[];
  if(folders.length)html+=`<optgroup label="Pastas de versão (nesta versão)">${folders.map(f=>`<option value="sha|${escapeHTML(projState.version)}|${escapeHTML(f)}"${projState.folder===f?' selected':''}>pasta ${escapeHTML(f)}</option>`).join('')}</optgroup>`;
  return html;
}

/* ---------- pintura ---------- */
function projPaint(){
  const root=$('projects-workspace');
  root.innerHTML=`<section class="lib-tree-panel proj-tree" id="proj-tree"></section>
   <section class="lib-note-panel"><div class="lib-tab-strip"><div class="lib-open-tab">${PROJ_REPO_ICON}<span class="lib-tab-text" id="proj-tab">${escapeHTML(projState.file?.path?.split('/').at(-1)||(projState.view?projState.view.name:'Projetos'))}</span></div></div>
   <div class="lib-note-scroll" id="proj-main"></div></section>
   <aside class="lib-right-panel" id="proj-side"></aside>`;
  projPaintTree();projPaintMain();projPaintSide();
}

function projPaintTree(){
  const el=$('proj-tree');if(!el)return;
  if(!projState.repo){
    const groups=projState.overview?.groups||[];
    const q=projState.search.trim().toLowerCase();
    let html=`<div class="lib-tree-head"><span class="study-head-ico">${PROJ_REPO_ICON}</span><div><strong>Projetos do GitHub</strong><small>Os seus repositórios, os da dupla e os do professor.</small></div></div>
     <div class="study-tree-actions"><button type="button" id="proj-add" class="study-primary">＋ Adicionar repositório</button></div>
     <div class="lib-search"><span>⌕</span><input id="proj-search" maxlength="80" placeholder="Buscar repositório..." value="${escapeHTML(projState.search)}" aria-label="Buscar repositório"></div><div class="lib-tree-scroll">`;
    for(const g of groups){
      const repos=g.repos.filter(r=>!q||(r.owner+'/'+r.name).toLowerCase().includes(q));
      const open=projState.open[g.klass]!==false;
      html+=`<button type="button" class="lib-folder-row depth-0" data-proj-group="${escapeHTML(g.klass)}"><span class="lib-chevron${open?' expanded':''}">▶</span><span class="lib-folder-icon top" aria-hidden="true"></span><strong>${escapeHTML(g.label)}</strong><small class="study-count">${repos.length}</small></button>`;
      if(!open)continue;
      for(const r of repos){
        html+=`<button type="button" class="lib-file-row depth-1 proj-repo-row" data-proj-repo="${escapeHTML(r.url)}" title="${escapeHTML(r.owner+'/'+r.name)}"><span class="lib-folder-icon" aria-hidden="true"></span><span class="file-label">${escapeHTML(r.name)}</span>${r.activities?`<span class="study-tag">${r.activities} entrega(s)</span>`:''}</button>`;
        for(const p of r.pairs)html+=`<button type="button" class="lib-file-row depth-2 proj-pair-row" data-proj-repo="${escapeHTML(p.url)}" title="Par: ${escapeHTML(p.owner+'/'+p.name)}"><span class="lib-file-icon" aria-hidden="true"></span><span class="file-label">par: ${escapeHTML(p.name)}</span>${projOwnerBadge(p.owner_class)}</button>`;
      }
    }
    if(!groups.length)html+=`<p class="study-empty study-indent">Nenhum repositório ainda. Adicione o link do GitHub aqui ou numa atividade em Resumos.</p>`;
    el.innerHTML=html+'</div>';
  }else{
    const v=projState.view;
    let html=`<div class="proj-repo-head"><button type="button" id="proj-back" class="study-link-btn">← Repositórios</button>
      <div class="proj-repo-title">${projOwnerBadge(v?.owner_class||'outro')}<strong title="${escapeHTML(projState.repo)}">${escapeHTML(v?v.owner+'/'+v.name:projState.repo.replace('https://github.com/',''))}</strong></div>
      <label class="proj-version"><span>Versão</span><select id="proj-version" aria-label="Versão do repositório"${projState.loading?' disabled':''}>${projVersionOptions()||'<option>Carregando…</option>'}</select></label></div>
      <div class="lib-search"><span>⌕</span><input id="proj-file-search" maxlength="80" placeholder="Filtrar arquivos..." value="${escapeHTML(projState.search)}" aria-label="Filtrar arquivos"></div>
      <div class="lib-tree-scroll pf-tree">`;
    if(projState.loading)html+='<p class="study-empty study-indent">Lendo o repositório no GitHub…</p>';
    else if(!projState.version)html+='<p class="study-empty study-indent">Nenhuma versão encontrada. Confira o link ou a conexão e clique em “Atualizar versões”.</p>';
    else if(!projState.tree)html+='<p class="study-empty study-indent">Não foi possível carregar os arquivos desta versão.</p>';
    else{
      const tree=projBuildTree();
      html+=projTreeRows(tree,0,!!projState.search.trim())||'<p class="study-empty study-indent">Nenhum arquivo.</p>';
      if(projState.tree.truncated)html+='<p class="study-empty study-indent">Lista cortada em 5.000 arquivos.</p>';
    }
    el.innerHTML=html+'</div>';
  }
  projWireTree(el);
}

function projPaintMain(){
  const el=$('proj-main');if(!el)return;
  const tab=$('proj-tab');
  if(tab)tab.textContent=projState.file?.path?.split('/').at(-1)||(projState.view?projState.view.name:'Projetos');
  if(!projState.repo){
    const total=projState.overview?.total||0;
    const groups=projState.overview?.groups||[];
    el.innerHTML=`<div class="lib-breadcrumb">Projetos</div><h1 class="lib-title">Meus projetos</h1>
     <p class="lib-note-intro">Abra um repositório para navegar pelas pastas e arquivos de qualquer versão: a entregue na atividade, a atual (main), branches, tags e pastas V0/V1/V2 do professor.</p>
     ${projPairsHTML(groups)}
     ${groups.map(g=>studyCard(g.label+' ('+g.repos.length+')','⚒',`<ul class="proj-list">${g.repos.map(r=>`<li><button type="button" class="study-link-btn proj-list-link" data-proj-repo="${escapeHTML(r.url)}">${escapeHTML(r.name)}</button> <small>${escapeHTML(r.owner)}${r.description?' · '+escapeHTML(r.description):''}</small>${r.pairs.length?' <span class="study-tag">par</span>':''}</li>`).join('')}</ul>`)).join('')}
     ${total?'':'<p class="study-empty">Nenhum repositório ainda.</p>'}`;
    projWireMain(el);return;
  }
  const f=projState.file;
  if(!f){
    const v=projState.view;
    const stack=projState.tree?.stack;
    el.innerHTML=`<div class="lib-breadcrumb">Projetos <b>›</b> ${escapeHTML(v?.owner||'')} <b>›</b> ${escapeHTML(v?.name||'')}</div>
      <h1 class="lib-title">${escapeHTML(v?.name||'Repositório')}</h1>${v?.description?`<p class="lib-note-intro">${escapeHTML(v.description)}</p>`:''}
      ${stack?`<div class="study-grid">${studyCard('Stack','⚙',stack.stack.length?`<div class="study-chips">${stack.stack.map(x=>`<span class="study-chip muted">${escapeHTML(x)}</span>`).join('')}</div>`:'<p class="study-empty">Não identificada pelos arquivos.</p>')}
      ${studyCard('Por onde começar','➜',(stack.entries.length?`<ul>${stack.entries.map(e=>`<li><button type="button" class="study-link-btn" data-pf-file="${escapeHTML(e)}">${escapeHTML(e)}</button></li>`).join('')}</ul>`:'')+(stack.run.length?`<div class="study-cmd">${stack.run.map(r=>`<pre><code>${escapeHTML(r)}</code></pre>`).join('')}</div>`:'')||'<p class="study-empty">Escolha um arquivo na árvore.</p>')}</div>`:''}
      <p class="study-empty">Escolha um arquivo na árvore ao lado.</p>`;
    projWireMain(el);return;
  }
  const crumbs=f.path.split('/').map(escapeHTML).join(' <b>›</b> ');
  let body;
  if(f.loading)body='<p class="study-empty">Abrindo arquivo…</p>';
  else if(f.error)body=`<div class="study-alert">${escapeHTML(f.error)}</div>`;
  else{
    const lines=f.content.replace(/\r\n?/g,'\n').split('\n');
    if(lines.length>1&&lines.at(-1)==='')lines.pop();
    const shown=lines.slice(0,6000);
    body=`<div class="pv-head">${projFileIcon(f.path)}<strong>${escapeHTML(f.path.split('/').at(-1))}</strong><small>${lines.length} linha(s) · ${projSize(f.size)}</small></div>
      <div class="pv-code" role="region" aria-label="Código do arquivo">${shown.map((l,i)=>`<div class="pv-line"><span class="pv-num">${i+1}</span><span class="pv-text">${escapeHTML(l)||' '}</span></div>`).join('')}</div>
      ${lines.length>shown.length?'<p class="study-empty">Arquivo cortado em 6.000 linhas; abra no GitHub para ver o resto.</p>':''}`;
  }
  el.innerHTML=`<div class="lib-breadcrumb">${escapeHTML(projState.view?.name||'')} <b>›</b> ${crumbs}</div>${body}`;
  projWireMain(el);
}

function projPairsHTML(groups){
  const all=groups.flatMap(g=>g.repos);const seen=new Set();const rows=[];
  for(const r of all.filter(x=>x.owner_class==='professor')){
    for(const p of r.pairs){const key=r.url+'|'+p.url;if(seen.has(key))continue;seen.add(key);rows.push([r,p]);}
  }
  if(!rows.length)return '';
  const cell=x=>`<button type="button" class="proj-pair-cell" data-proj-repo="${escapeHTML(x.url)}">${projOwnerBadge(x.owner_class)}<span><strong>${escapeHTML(x.name)}</strong><small>${escapeHTML(x.owner)}</small></span></button>`;
  return studyCard('Lado a lado: professor × nosso','⇄',`<div class="proj-pairs">${rows.map(([a,b])=>`<div class="proj-pair">${cell(a)}<span class="proj-pair-sep">⇄</span>${cell(b)}</div>`).join('')}</div>`,'wide');
}

function projPaintSide(){
  const el=$('proj-side');if(!el)return;
  const v=projState.view;
  if(!projState.repo||!v){
    el.innerHTML=`<section class="lib-side-card"><h3><span class="card-heading-ico">${libIcon('book','heading-icon')}</span>Como funciona</h3><div class="side-body"><p class="study-empty">Os repositórios vêm das atividades (Resumos), das aulas com código e dos que você adicionar aqui. O dono (Meu, Dupla, Professor) vem da lista em Ajustes.</p><p class="study-empty">Só leitura: o TRAMA não faz commit nem altera nada no GitHub.</p></div></section>`;
    return;
  }
  const version=(v.versions||[]).find(x=>x.sha===projState.version);
  const ghUrl=projState.file?.path&&projState.version?`${v.url}/blob/${projState.version}/${projState.file.path.split('/').map(encodeURIComponent).join('/')}`:
    (projState.version?`${v.url}/tree/${projState.version}`:v.url);
  let html=`<section class="lib-side-card"><h3><span class="card-heading-ico">${PROJ_REPO_ICON}</span>Repositório</h3><div class="side-body">
    <div class="lib-stat"><span class="stat-label">Dono</span><span class="stat-value"><select id="proj-owner-class" aria-label="Dono do repositório">${['meu','dupla','professor','outro'].map(k=>`<option value="${k}"${v.owner_class===k?' selected':''}>${PROJ_OWNER[k]}</option>`).join('')}</select></span></div>
    <div class="lib-stat"><span class="stat-label">GitHub</span><span class="stat-value muted">${escapeHTML(v.owner)}</span></div>
    <div class="lib-stat"><span class="stat-label">Versão</span><span class="stat-value muted">${escapeHTML(version?version.label:'—')}${projState.folder?' · pasta '+escapeHTML(projState.folder):''}</span></div>
    <button type="button" class="lib-side-button" id="proj-open-github" data-url="${escapeHTML(ghUrl)}"><span class="action-left">${PROJ_REPO_ICON}Abrir no GitHub${projState.file?.path?' (este arquivo)':''}</span>${libIcon('arrow','action-end')}</button>
    <button type="button" class="lib-side-button" id="proj-refresh"><span class="action-left">${libIcon('refresh','action-icon')}Atualizar versões</span>${libIcon('arrow','action-end')}</button>
    <button type="button" class="lib-side-button" id="proj-open-note"><span class="action-left">${libIcon('file','action-icon')}Abrir nota no Obsidian</span>${libIcon('arrow','action-end')}</button>
    <button type="button" class="lib-side-button study-danger" id="proj-remove"><span class="action-left">Tirar da lista</span>${libIcon('arrow','action-end')}</button></div></section>`;
  if((v.pairs||[]).length)html+=`<section class="lib-side-card"><h3><span class="card-heading-ico">${libIcon('link','heading-icon')}</span>Par</h3><div class="side-body">${v.pairs.map(p=>`<button type="button" class="lib-link" data-proj-repo="${escapeHTML(p.url)}">${projOwnerBadge(p.owner_class)}<span>${escapeHTML(p.owner+'/'+p.name)}</span></button>`).join('')}</div></section>`;
  html+=`<section class="lib-side-card"><h3><span class="card-heading-ico">${libIcon('folder','heading-icon')}</span>Atividades</h3><div class="side-body">${(v.activities||[]).length?v.activities.map(a=>`<button type="button" class="lib-link" data-proj-activity="${escapeHTML(a.id)}">${libIcon('file','link-icon')}<span>${escapeHTML(a.title)}${a.sha?` · entregue ${escapeHTML(a.sha.slice(0,7))}`:''}</span></button>`).join(''):'<p class="study-empty">Nenhuma atividade usa este repositório.</p>'}</div></section>`;
  html+=`<section class="lib-side-card"><h3><span class="card-heading-ico">${libIcon('file','heading-icon')}</span>Aulas ligadas</h3><div class="side-body">${(v.lessons||[]).length?v.lessons.map(l=>`<button type="button" class="lib-link" data-proj-lesson="${escapeHTML(l.lesson)}"><span>${escapeHTML(studyLessonLabel(l.lesson))}</span><span>${escapeHTML(l.title||'')}</span></button>`).join(''):'<p class="study-empty">Nenhuma aula ligada ainda.</p>'}</div></section>`;
  el.innerHTML=html;projWireSide(el);
}

/* ---------- eventos ---------- */
function projWireTree(el){
  el.querySelectorAll('[data-proj-group]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.projGroup;projState.open[k]=projState.open[k]===false;projPaintTree();}));
  el.querySelectorAll('[data-proj-repo]').forEach(b=>b.addEventListener('click',()=>projSelectRepo(b.dataset.projRepo,'')));
  el.querySelectorAll('[data-pf-dir]').forEach(b=>b.addEventListener('click',()=>{const p=b.dataset.pfDir;projState.expanded.has(p)?projState.expanded.delete(p):projState.expanded.add(p);projPaintTree();}));
  el.querySelectorAll('[data-pf-file]').forEach(b=>b.addEventListener('click',()=>projOpenFile(b.dataset.pfFile).then(projPaintSide)));
  const add=el.querySelector('#proj-add');if(add)add.addEventListener('click',projOpenAddDialog);
  const back=el.querySelector('#proj-back');if(back)back.addEventListener('click',()=>{projState.repo=null;projState.view=null;projState.file=null;projState.search='';projPaint();});
  for(const id of ['proj-search','proj-file-search']){
    const input=el.querySelector('#'+id);
    if(input)input.addEventListener('input',()=>{projState.search=input.value;const pos=input.selectionStart;projPaintTree();const again=$(id);if(again){again.focus();again.setSelectionRange(pos,pos);}});
  }
  const sel=el.querySelector('#proj-version');
  if(sel)sel.addEventListener('change',async()=>{
    const [,sha,folder]=sel.value.split('|');
    const changed=sha!==projState.version;
    projState.version=sha;projState.folder=folder||'';projState.expanded=new Set();projState.file=null;
    if(changed){projState.loading=true;projPaintTree();await projLoadTree();projState.loading=false;}
    else{const base=projState.folder?projState.folder+'/':'';const readme=(projState.tree?.files||[]).find(f=>f.path.toLowerCase()===base+'readme.md');if(readme)await projOpenFile(readme.path,false);}
    projPaint();
  });
}
function projWireMain(el){
  el.querySelectorAll('[data-proj-repo]').forEach(b=>b.addEventListener('click',()=>projSelectRepo(b.dataset.projRepo,'')));
  el.querySelectorAll('[data-pf-file]').forEach(b=>b.addEventListener('click',()=>projOpenFile(b.dataset.pfFile).then(projPaintSide)));
}
function projWireSide(el){
  el.querySelectorAll('[data-proj-repo]').forEach(b=>b.addEventListener('click',()=>projSelectRepo(b.dataset.projRepo,'')));
  el.querySelectorAll('[data-proj-activity]').forEach(b=>b.addEventListener('click',async()=>{
    studyState.kind='activity';studyState.activity=b.dataset.projActivity;app.view='study';if(typeof renderNavigation==='function')renderNavigation();await render();
  }));
  el.querySelectorAll('[data-proj-lesson]').forEach(b=>b.addEventListener('click',async()=>{
    const lesson=b.dataset.projLesson;const dev=(studyState.overview?.development||[]).some(d=>d.lesson===lesson);
    studyState.kind=dev?'dev':'lesson';studyState[dev?'dev':'lesson']=lesson;app.view='study';if(typeof renderNavigation==='function')renderNavigation();await render();
  }));
  const bind=(id,fn)=>{const b=el.querySelector('#'+id);if(b)b.addEventListener('click',fn);};
  bind('proj-open-github',async()=>{const r=await call('open_study_link',$('proj-open-github').dataset.url);if(!r?.ok)notify(r?.message||'Não foi possível abrir o GitHub.');});
  bind('proj-refresh',async()=>{
    notify('Consultando branches e tags no GitHub…',6000);
    const r=await call('project_repo',projState.repo,'force');
    if(!r?.ok){notify(r?.message||'Não foi possível atualizar.');return;}
    projState.view=r;notify(r.warning?'GitHub: '+r.warning:'Versões atualizadas.',7000);projPaint();
  });
  bind('proj-open-note',async()=>{const r=await call('open_note',projState.view.note);if(!r?.ok)notify('Abra o cofre no Obsidian. A nota do repositório é criada ao atualizar o cofre.');});
  bind('proj-remove',async()=>{
    if(!await askTramaConfirm('Tirar da lista',`Tirar ${projState.view.owner}/${projState.view.name} de Projetos? Nada é apagado no GitHub nem nas atividades.`,'Tirar da lista'))return;
    const r=await call('project_remove',projState.repo,true);
    notify(r?.ok?'Repositório tirado da lista.':(r?.message||'Não foi possível.'));
    if(r?.ok){projState.repo=null;projState.view=null;await renderProjectsView();}
  });
  const owner=el.querySelector('#proj-owner-class');
  if(owner)owner.addEventListener('change',async()=>{
    const v=projState.view;
    const label=v.owner_label&&v.owner_label!==v.owner?v.owner_label:'';
    const r=await call('project_save_owner',v.owner,owner.value,label);
    if(!r?.ok){notify(r?.message||'Não foi possível salvar.');return;}
    notify(`Todos os repositórios de ${v.owner} agora são “${PROJ_OWNER[owner.value]}”.`,7000);
    const o=await call('projects_overview');if(o?.ok)projState.overview=o;
    const again=await call('project_repo',projState.repo,false);if(again?.ok)projState.view=again;projPaint();
  });
}

/* ---------- adicionar repositório ---------- */
function projOpenAddDialog(){
  $('project-add-form').reset();$('project-add-feedback').textContent='';
  studyShowDialog($('project-add-dialog'));$('project-add-url').focus();
}
async function projSubmitAdd(event){
  event.preventDefault();
  const url=$('project-add-url').value.trim();const fb=$('project-add-feedback');
  if(!url){fb.textContent='Cole o link do GitHub.';return;}
  const r=await call('project_add',url);
  if(!r?.ok){fb.textContent=r?.message||'Não foi possível adicionar.';return;}
  studyCloseDialog($('project-add-dialog'));notify('Repositório adicionado.');
  await renderProjectsView();await projSelectRepo(r.url,'');
}

/* ---------- Ajustes: donos ---------- */
async function projectsOwnersMount(root){
  const list=root.querySelector('#owners-list');if(!list)return;
  const status=root.querySelector('#owners-status');
  const paint=owners=>{
    list.innerHTML=owners.length?owners.map(o=>`<div class="owner-row">${projOwnerBadge(o.klass)}<strong>${escapeHTML(o.owner)}</strong><small>${escapeHTML(o.label||'')}</small><button type="button" data-owner-del="${escapeHTML(o.owner)}" title="Remover">×</button></div>`).join(''):'<p class="study-empty">Nenhum dono cadastrado.</p>';
    list.querySelectorAll('[data-owner-del]').forEach(b=>b.addEventListener('click',async()=>{
      if(!await askTramaConfirm('Remover dono',`Remover ${b.dataset.ownerDel}? Os repositórios dele passam a “Outro”.`,'Remover'))return;
      const r=await call('project_delete_owner',b.dataset.ownerDel,true);
      if(r?.ok)paint(r.owners);status.textContent=r?.ok?'Removido.':(r?.message||'Não foi possível remover.');
    }));
  };
  const r=await call('project_owners');
  if(!r?.ok){list.innerHTML=`<p class="study-empty">${escapeHTML(r?.message||'Selecione o cofre primeiro.')}</p>`;return;}
  paint(r.owners);
  root.querySelector('#owner-save').addEventListener('click',async()=>{
    const name=root.querySelector('#owner-name').value.trim();
    const res=await call('project_save_owner',name,root.querySelector('#owner-class').value,root.querySelector('#owner-label').value.trim());
    status.textContent=res?.ok?'Salvo.':(res?.message||'Não foi possível salvar.');
    if(res?.ok){paint(res.owners);root.querySelector('#owner-name').value='';root.querySelector('#owner-label').value='';}
  });
}

function projectsBind(){
  const form=$('project-add-form');if(!form)return;
  form.addEventListener('submit',projSubmitAdd);
  $('project-add-close').addEventListener('click',()=>studyCloseDialog($('project-add-dialog')));
  $('project-add-cancel').addEventListener('click',()=>studyCloseDialog($('project-add-dialog')));
}
projectsBind();
