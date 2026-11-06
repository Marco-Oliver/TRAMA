'use strict';
/* Etapa 1: cadastro e sugestões apenas. Nenhum vínculo é publicado sem aceite. */
(() => {
 const el = id => document.getElementById(id);
 const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const editor=el('lesson-code-dialog'), mapper=el('lesson-map-dialog');
 if(!editor||!mapper)return;
 let preview=null;
 let loadedInvalid=null;
 const show=d=>typeof d.showModal==='function'?d.showModal():d.setAttribute('open','');
 const hide=d=>d.open&&typeof d.close==='function'?d.close():d.removeAttribute('open');
 const feedback=(id,msg)=>{el(id).textContent=msg;};
 const selectedLesson=()=>/^Aula-\d{3,4}$/.test(app?.note?.lesson||'')?app.note.lesson:'Aula-001';
 function updateStudentSelect(node, wanted=null){
   const select=node.querySelector('select[data-code="professor_id"]');
   if(!select)return;
   const original=wanted===null?select.value:wanted;
   select.replaceChildren();
   const empty=document.createElement('option');
   empty.value='';empty.textContent='Selecione um repositório do professor';select.append(empty);
   for(const teacher of el('code-teachers').children){
     const id=teacher.querySelector('[data-code="id"]')?.value.trim()||'';
     const label=teacher.querySelector('[data-code="rotulo"]')?.value.trim()||id;
     if(!id)continue;
     const opt=document.createElement('option');opt.value=id;
     opt.textContent=label+' ('+id+')';select.append(opt);
   }
   // Never silently attach a student to a different teacher.
   select.value=[...select.options].some(opt=>opt.value===original)?original:'';
 }
 function refreshTeacherOptions(){
   for(const student of el('code-students').children)updateStudentSelect(student);
 }
 function row(role,entry={}){
   const list=el(role==='professor'?'code-teachers':'code-students');
   const n=list.children.length+1, node=document.createElement('fieldset');
   node.className='code-repo-row';node.dataset.role=role;
   const def=role==='professor'?'professor':'dupla';
   const field=(name,label,value,wide=false)=>'<label'+(wide?' class="span2"':'')+'>'+label+
     '<input data-code="'+name+'" maxlength="300" value="'+esc(value||'')+'"></label>';
   const option=(value,name,selected)=>'<option value="'+value+'"'+(selected===value?' selected':'')+'>'+name+'</option>';
   const select=(name,selected,empty=false)=>'<label>'+name+'<select data-code="'+(empty?'anterior_tipo':'ref_tipo')+'">'+
      (empty?'<option value="">Não definida</option>':'')+
      option('branch','Branch',selected)+option('tag','Tag',selected)+option('commit','Commit',selected)+'</select></label>';
   node.innerHTML='<legend>'+(role==='professor'?'Professor':'Dupla')+' '+n+'</legend><div class="context-fields">'+
     field('id','Identificador',entry.id||def+'-'+n)+
     field('rotulo','Rótulo',entry.rotulo||'')+
     field('repo','URL do repositório GitHub',entry.repo||'',true)+
     select('Referência',entry.ref_tipo||'branch')+
     field('ref','Branch, tag ou SHA',entry.ref||'main')+
     field('pasta','Pasta (opcional)',entry.pasta||'')+
     (role==='dupla'?'<label>Repositório correspondente do professor<select data-code="professor_id" required></select></label>':
      select('Tipo anterior (opcional)',entry.anterior?.ref_tipo||'',true)+
      field('anterior_ref','Anterior: referência',entry.anterior?.ref||'')+
      field('anterior_pasta','Anterior: pasta',entry.anterior?.pasta||''))+
     '</div><button type="button" class="code-remove-row">Remover repositório</button>'+
     '<button type="button" class="code-freeze-row">Congelar SHA</button>'+
     '<button type="button" class="code-unfreeze-row">Descongelar SHA</button>'+
     (role==='professor'?'<button type="button" class="code-freeze-previous">Congelar anterior</button>'+
       '<button type="button" class="code-unfreeze-previous">Descongelar anterior</button>':'')+
     '<small class="code-freeze-status" role="status"></small>';
   node.querySelector('.code-remove-row').addEventListener('click',()=>{node.remove();refreshTeacherOptions();});
   const freeze=async previous=>{
     if(!loadedLesson){feedback('lesson-code-feedback','Carregue e salve a aula antes de congelar.');return;}
     const ident=node.querySelector('[data-code="id"]')?.value.trim()||'';
     if(!ident){feedback('lesson-code-feedback','Identificador obrigatório para congelar SHA.');return;}
     if(!await askTramaConfirm('Congelar revisão GitHub',
       'Fixar no SQLite o commit '+(previous?'anterior':'atual')+' do cadastro salvo de '+loadedLesson+
       '? Reprocessar não atualizará esse SHA automaticamente.','Congelar SHA'))return;
     const result=await call('freeze_lesson_code',loadedLesson,role,ident,true,previous);
     feedback('lesson-code-feedback',result?.message||'Falha ao congelar SHA.');
     if(result?.ok)node.querySelector('.code-freeze-status').textContent=
       (previous?'Anterior':'Atual')+' fixado: '+result.sha.slice(0,12);
   };
   const unfreeze=async previous=>{
     const ident=node.querySelector('[data-code="id"]')?.value.trim()||'';
     if(!loadedLesson||!ident)return feedback('lesson-code-feedback','Carregue o cadastro antes de descongelar.');
     if(!await askTramaConfirm('Descongelar revisão GitHub',
       'Remover o SHA '+(previous?'anterior':'atual')+' congelado de '+loadedLesson+
       '? A próxima consulta poderá congelar uma versão diferente; nenhuma nota será alterada.',
       'Descongelar SHA'))return;
     const result=await call('unfreeze_lesson_code',loadedLesson,role,ident,
                             previous?'previous':'current',true);
     feedback('lesson-code-feedback',result?.message||'Não foi possível descongelar.');
     if(result?.ok)node.querySelector('.code-freeze-status').textContent=
       (previous?'Anterior':'Atual')+' descongelado.';
   };
   node.querySelector('.code-freeze-row').addEventListener('click',()=>freeze(false));
   node.querySelector('.code-freeze-previous')?.addEventListener('click',()=>freeze(true));
   node.querySelector('.code-unfreeze-row').addEventListener('click',()=>unfreeze(false));
   node.querySelector('.code-unfreeze-previous')?.addEventListener('click',()=>unfreeze(true));
   list.append(node);
   if(role==='dupla')updateStudentSelect(node,entry.professor_id||'');
   else{
     node.querySelectorAll('[data-code="id"],[data-code="rotulo"]').forEach(input=>
       input.addEventListener('input',refreshTeacherOptions));
     refreshTeacherOptions();
   }
 }
 function collect(role){
   return [...el(role==='professor'?'code-teachers':'code-students').children].map(node=>{
     const get=name=>node.querySelector('[data-code="'+name+'"]')?.value.trim()||'';
     const item={id:get('id'),rotulo:get('rotulo'),repo:get('repo'),ref_tipo:get('ref_tipo'),
                 ref:get('ref'),pasta:get('pasta')};
     if(role==='dupla')item.professor_id=get('professor_id');
     else if(get('anterior_tipo'))item.anterior={ref_tipo:get('anterior_tipo'),
                                      ref:get('anterior_ref'),pasta:get('anterior_pasta')};
     return item;
   });
 }
 let loadedLesson='';
 async function loadLesson(){
   const nr=Number(el('lesson-code-number').value);
   if(!Number.isInteger(nr)||nr<1||nr>9999){
     feedback('lesson-code-feedback','Número da aula inválido.');return;
   }
   const lesson='Aula-'+String(nr).padStart(3,'0');
   const result=await call('lesson_code_config',lesson);
   if(!result){feedback('lesson-code-feedback','Não foi possível carregar o cadastro.');return;}
   if(result.fatal){feedback('lesson-code-feedback',(result.erros||[]).join('; '));return;}
   loadedLesson=lesson;
   loadedInvalid=result.invalid?.[lesson]||null;
   el('lesson-code-remove').disabled=!(loadedInvalid||result?.aulas?.[lesson]);
   el('lesson-code-invalid').hidden=!loadedInvalid;
   el('lesson-code-invalid-raw').textContent=loadedInvalid?JSON.stringify(loadedInvalid.raw,null,2):'';
   el('code-teachers').replaceChildren();el('code-students').replaceChildren();
   const current=result?.aulas?.[lesson]||{professor:[],dupla:[]};
   for(const item of current.professor||[])row('professor',item);
   for(const item of current.dupla||[])row('dupla',item);
   const errors=(result.erros||[]).filter(x=>x.startsWith(lesson+'.')||x.startsWith(lesson+':'));
   feedback('lesson-code-feedback',errors.length?
     errors.slice(0,8).join('; ')+' — revise antes de substituir este cadastro.':
     lesson+' carregada; alterações ainda não gravadas.');
   el('lesson-code-token').textContent=result?.github_token_configurado?
     (result.github_token_fonte==='dpapi'?'Token GitHub protegido por DPAPI no Windows.':
       'Token GitHub configurado por variável de ambiente.'):
     'Sem token GitHub: limite baixo e sem acesso a repositórios privados.';
 }
 async function openEditor(){
   el('lesson-code-number').value=Number(selectedLesson().slice(5));
   await loadLesson();
   show(editor);
 }
 async function saveEditor(event){
   event.preventDefault();
   const nr=Number(el('lesson-code-number').value);
   if(!Number.isInteger(nr)||nr<1||nr>9999){feedback('lesson-code-feedback','Número de aula inválido.');return;}
   const lesson='Aula-'+String(nr).padStart(3,'0');
   if(lesson!==loadedLesson){feedback('lesson-code-feedback','Clique em Carregar esta aula antes de salvar outro número.');return;}
   const data={professor:collect('professor'),dupla:collect('dupla')};
   if(!data.professor.length&&!data.dupla.length){
     feedback('lesson-code-feedback','Cadastro vazio bloqueado. Adicione um repositório; remover cadastro exige ação específica.');return;
   }
   let title='Salvar repositórios',message='Gravar '+data.professor.length+
     ' repositório(s) do professor e '+data.dupla.length+' da dupla para '+lesson+'?',accept='Salvar';
   if(loadedInvalid){
     title='ATENÇÃO — substituir registro inválido de '+lesson;
     const original=JSON.stringify(loadedInvalid.raw,null,2);
     message='Registro atual (também exibido integralmente no formulário):\n'+
       (original.length>12000?original.slice(0,12000)+'\n[Exibição resumida aqui: confira o restante no formulário]':original)+
       '\n\nSubstituir este registro inválido pelo cadastro novo? A alteração não será reversível pelo formulário.';
     accept='Substituir cadastro inválido';
   }
   if(!await askTramaConfirm(title,message,accept))return;
   const out=await call('save_lesson_code',lesson,data,true,
                       !!loadedInvalid,loadedInvalid?.digest||'');
   feedback('lesson-code-feedback',out?.message||'Falha ao salvar.');
   if(out?.ok){
     notify('Cadastro GitHub salvo.');
     loadedInvalid=null;
     el('lesson-code-invalid').hidden=true;
     el('lesson-code-invalid-raw').textContent='';
   }
 }
 async function saveGithubToken(){
   const input=el('lesson-code-github-key');
   const token=input.value.trim();
   if(!token){feedback('lesson-code-feedback','Cole um token GitHub antes de salvar.');return;}
   if(!await askTramaConfirm('Proteger token GitHub',
      'Salvar o token criptografado por DPAPI fora do cofre? Nenhuma nota ou banco SQLite será alterado.',
      'Salvar protegido'))return;
   const answer=await call('save_github_token',token,true);
   input.value='';
   feedback('lesson-code-feedback',answer?.message||'Falha ao salvar token.');
   if(answer?.ok)el('lesson-code-token').textContent='Token GitHub protegido por DPAPI no Windows.';
 }
 async function removeGithubToken(){
   if(!await askTramaConfirm('Remover token GitHub protegido',
      'Apagar o token salvo no Windows? Uma variável TRAMA_GITHUB_TOKEN, se existir, não será alterada.',
      'Remover token'))return;
   const answer=await call('remove_github_token',true);
   el('lesson-code-github-key').value='';
   feedback('lesson-code-feedback',answer?.message||'Falha ao remover token.');
   if(answer?.ok)el('lesson-code-token').textContent='Token DPAPI removido; consulte novamente para conferir outras credenciais.';
 }
 async function removeEditor(){
   const nr=Number(el('lesson-code-number').value);
   const lesson='Aula-'+String(nr).padStart(3,'0');
   if(!Number.isInteger(nr)||nr<1||nr>9999||lesson!==loadedLesson){
     feedback('lesson-code-feedback','Carregue a aula antes de remover seu cadastro.');return;
   }
   if(el('lesson-code-remove').disabled)return;
   if(!await askTramaConfirm('Remover cadastro GitHub da aula',
     'Excluir os repositórios associados à '+lesson+'? As demais aulas e as notas do Obsidian serão preservadas.',
     'Remover cadastro'))return;
   const answer=await call('remove_lesson_code',lesson,true,loadedInvalid?.digest||'');
   feedback('lesson-code-feedback',answer?.message||'Não foi possível remover o cadastro.');
   if(answer?.ok){
     el('code-teachers').replaceChildren();el('code-students').replaceChildren();
     loadedInvalid=null;el('lesson-code-invalid').hidden=true;
     el('lesson-code-invalid-raw').textContent='';
     el('lesson-code-remove').disabled=true;
     notify('Cadastro GitHub removido.');
   }
 }
 function displayPreview(data){
   preview=data;const rate=data.taxa||{};
   feedback('lesson-map-quota','API GitHub: '+
      (rate.restantes==null?'saldo não informado':rate.restantes+' de '+rate.limite+' requisições restantes')+
      ' | '+(rate.consultas||0)+' chamadas. '+(data.truncado?'Árvore incompleta: revise os itens.':'')+
      (data.historico_parcial?' Histórico de commits parcial; consulte revisões antigas manualmente.':''));
   const root=el('lesson-map-results');root.replaceChildren();
   if(!data.aulas?.length){root.textContent='Nenhuma aula cadastrada no cofre.';return;}
   const candidates=data.candidatos||[];
   for(const lesson of data.aulas){
     const line=document.createElement('div');line.className='lesson-map-row';line.dataset.aula=lesson.aula;
     const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.dataset.mapCheck='1';
     const label=document.createElement('label');label.append(checkbox,document.createTextNode(' '+lesson.aula));
     const day=document.createElement('input');day.type='date';day.value=lesson.data||'';
     day.setAttribute('aria-label','Data associada a '+lesson.aula);
     const selection=document.createElement('select');
     selection.setAttribute('aria-label','Código de '+lesson.aula);
     const possibles=[...candidates].filter(x=>x.data&&day.value)
       .sort((a,b)=>Math.abs(Date.parse(a.data)-Date.parse(day.value))-
                    Math.abs(Date.parse(b.data)-Date.parse(day.value))).slice(0,40);
     const extras=candidates.filter(c=>c.tipo==='pasta'||c.tipo==='tag').slice(0,90);
     const options=[...new Map([...possibles,...extras,...candidates.slice(0,20)]
                                  .map(c=>[c.id,c])).values()];
     const empty=document.createElement('option');empty.value='';empty.textContent='Selecionar referência';selection.append(empty);
     for(const candidate of options){
       const o=document.createElement('option');o.value=candidate.id;
       o.textContent=candidate.rotulo+' ('+(candidate.data||'sem data')+')';
       selection.append(o);
     }
     if(lesson.candidato_id&&!options.some(c=>c.id===lesson.candidato_id)){
       const c=candidates.find(x=>x.id===lesson.candidato_id);
       if(c){const o=document.createElement('option');o.value=c.id;o.textContent=c.rotulo;selection.append(o);}
     }
     const ensureOption = id => {
       if(!id||[...selection.options].some(option=>option.value===id))return;
       const candidate=candidates.find(c=>c.id===id);
       if(!candidate)return;
       const option=document.createElement('option');option.value=id;
       option.textContent=candidate.rotulo+' ('+(candidate.data||'sem data')+')';
       selection.append(option);
     };
     ensureOption(lesson.candidato_id);
     selection.value=lesson.candidato_id||'';
     const older=document.createElement('label');older.className='lesson-map-previous';
     const olderCheck=document.createElement('input');olderCheck.type='checkbox';olderCheck.dataset.mapPrevious='1';
     older.append(olderCheck,document.createTextNode(' Confirmar anterior'));
     const description=document.createElement('small');
     description.textContent=(lesson.origem_data==='contexto_classroom'?
       'Data do post no Classroom; não comprova data da gravação. ':'')+lesson.motivo;
     const updateOlder=()=>{
       const c=candidates.find(x=>x.id===selection.value);
       older.hidden=!c?.sugestao_anterior;olderCheck.checked=false;
       if(c?.sugestao_anterior)older.lastChild.textContent=' Confirmar anterior sugerida: '+c.sugestao_anterior.pasta;
     };
     selection.addEventListener('change',()=>{checkbox.checked=false;updateOlder();});
     day.addEventListener('change',async()=>{
       const requested=day.value;checkbox.checked=false;olderCheck.checked=false;
       // The Python backend owns date direction and folder/tag/commit priority.
       const recalculated=await call('suggest_lesson_mappings',{[lesson.aula]:requested});
       if(day.value!==requested)return; // Ignore stale replies when users edit quickly.
       if(!recalculated?.ok){
         feedback('lesson-map-feedback',recalculated?.message||'Falha ao atualizar a sugestão.');
         return;
       }
       const suggestion=(recalculated.aulas||[]).find(item=>item.aula===lesson.aula);
       if(!suggestion)return;
       ensureOption(suggestion.candidato_id);
       selection.value=suggestion.candidato_id||'';
       updateOlder();
       description.textContent=(lesson.origem_data==='contexto_classroom'?
         'Data do post no Classroom; não comprova data da gravação. ':'')+suggestion.motivo;
     });
     updateOlder();line.append(label,day,selection,older,description);root.append(line);
   }
   feedback('lesson-map-feedback',data.aulas.length+' aulas. Nenhuma seleção foi gravada.');
 }
 async function previewMappings(){
   feedback('lesson-map-feedback','Consultando commits, tags e árvore do GitHub...');
   preview=null;el('lesson-map-results').replaceChildren();
   const result=await call('preview_lesson_mappings',el('lesson-map-repo').value.trim(),null,el('lesson-map-branch').value.trim());
   if(!result?.ok){feedback('lesson-map-feedback',result?.message||'Não foi possível consultar GitHub.');return;}
   displayPreview(result);
 }
 async function acceptMappings(){
   if(!preview){feedback('lesson-map-feedback','Consulte o repositório antes de aceitar.');return;}
   const selected=[...el('lesson-map-results').children].flatMap(item=>{
     if(!item.querySelector('[data-map-check]')?.checked)return [];
     const value=item.querySelector('select')?.value;
     return value?[{aula:item.dataset.aula,candidato_id:value,
        confirmar_anterior:!!item.querySelector('[data-map-previous]')?.checked}]:[];
   });
   if(!selected.length){feedback('lesson-map-feedback','Marque ao menos uma aula e escolha a referência.');return;}
   if(!await askTramaConfirm('Confirmar mapeamento',
        'Gravar somente '+selected.length+' aula(s) no aulas-github.json?','Confirmar'))return;
   const answer=await call('apply_lesson_mappings',selected,true);
   feedback('lesson-map-feedback',answer?.message||'Falha ao salvar.');
   if(answer?.ok){notify('Mapeamento salvo com confirmação.');preview=null;}
 }
 el('btn-lesson-code').addEventListener('click',openEditor);
 el('lesson-code-load').addEventListener('click',loadLesson);
 el('lesson-code-remove').addEventListener('click',removeEditor);
 el('lesson-code-save-token').addEventListener('click',saveGithubToken);
 el('lesson-code-remove-token').addEventListener('click',removeGithubToken);
 el('lesson-code-add-teacher').addEventListener('click',()=>row('professor'));
 el('lesson-code-add-student').addEventListener('click',()=>row('dupla'));
 el('lesson-code-close').addEventListener('click',()=>hide(editor));
 el('lesson-code-cancel').addEventListener('click',()=>hide(editor));
 el('lesson-code-form').addEventListener('submit',saveEditor);
 el('lesson-code-map-open').addEventListener('click',()=>{
   hide(editor);preview=null;show(mapper);
   feedback('lesson-map-quota','Sem token há poucas requisições por hora. Recomendamos TRAMA_GITHUB_TOKEN.');
 });
 el('lesson-map-close').addEventListener('click',()=>hide(mapper));
 el('lesson-map-dismiss').addEventListener('click',()=>hide(mapper));
 el('lesson-map-search').addEventListener('click',previewMappings);
 el('lesson-map-save').addEventListener('click',acceptMappings);
})();
