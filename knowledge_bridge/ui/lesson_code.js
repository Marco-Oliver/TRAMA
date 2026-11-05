'use strict';
/* Etapa 1: cadastro e sugestões apenas. Nenhum vínculo é publicado sem aceite. */
(() => {
 const el = id => document.getElementById(id);
 const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const editor=el('lesson-code-dialog'), mapper=el('lesson-map-dialog');
 if(!editor||!mapper)return;
 let preview=null;
 const show=d=>typeof d.showModal==='function'?d.showModal():d.setAttribute('open','');
 const hide=d=>d.open&&typeof d.close==='function'?d.close():d.removeAttribute('open');
 const feedback=(id,msg)=>{el(id).textContent=msg;};
 const selectedLesson=()=>/^Aula-\d{3,4}$/.test(app?.note?.lesson||'')?app.note.lesson:'Aula-001';
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
     (role==='dupla'?field('professor_id','ID correspondente do professor',entry.professor_id||''):
      select('Tipo anterior (opcional)',entry.anterior?.ref_tipo||'',true)+
      field('anterior_ref','Anterior: referência',entry.anterior?.ref||'')+
      field('anterior_pasta','Anterior: pasta',entry.anterior?.pasta||''))+
     '</div><button type="button" class="code-remove-row">Remover repositório</button>';
   node.querySelector('.code-remove-row').addEventListener('click',()=>node.remove());
   list.append(node);
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
 async function openEditor(){
   feedback('lesson-code-feedback','');
   const lesson=selectedLesson(), result=await call('lesson_code_config');
   el('lesson-code-number').value=Number(lesson.slice(5));
   el('code-teachers').replaceChildren();el('code-students').replaceChildren();
   const current=result?.aulas?.[lesson]||{professor:[],dupla:[]};
   for(const item of current.professor||[])row('professor',item);
   for(const item of current.dupla||[])row('dupla',item);
   if(result?.erros?.length)feedback('lesson-code-feedback',result.erros.slice(0,5).join('; ')+(result.erros.length>5?' (+mais erros)':''));
   el('lesson-code-token').textContent=result?.github_token_configurado?
     'Token GitHub encontrado no ambiente.':
     'Sem token: limite baixo de requisições e sem acesso a repositórios privados. Recomendamos configurar TRAMA_GITHUB_TOKEN.';
   show(editor);
 }
 async function saveEditor(event){
   event.preventDefault();
   const nr=Number(el('lesson-code-number').value);
   if(!Number.isInteger(nr)||nr<1||nr>9999){feedback('lesson-code-feedback','Número de aula inválido.');return;}
   const lesson='Aula-'+String(nr).padStart(3,'0');
   const data={professor:collect('professor'),dupla:collect('dupla')};
   if(!await askTramaConfirm('Salvar repositórios',
       'Gravar '+data.professor.length+' repositório(s) do professor e '+data.dupla.length+
       ' da dupla para '+lesson+'?','Salvar'))return;
   const out=await call('save_lesson_code',lesson,data,true);
   feedback('lesson-code-feedback',out?.message||'Falha ao salvar.');
   if(out?.ok)notify('Cadastro GitHub salvo.');
 }
 function nearest(day, candidates){
   const value=Date.parse(day+'T12:00:00Z');
   if(!day||!Number.isFinite(value))return '';
   const ordered=candidates.filter(x=>x.data).map(c=>[Math.abs(Date.parse(c.data+'T12:00:00Z')-value),c])
     .filter(x=>Number.isFinite(x[0])).sort((a,b)=>a[0]-b[0]);
   return ordered.length&&ordered[0][0]<=30*86400000?ordered[0][1].id:'';
 }
 function displayPreview(data){
   preview=data;const rate=data.taxa||{};
   feedback('lesson-map-quota','API GitHub: '+
      (rate.restantes==null?'saldo não informado':rate.restantes+' de '+rate.limite+' requisições restantes')+
      ' | '+(rate.consultas||0)+' chamadas. '+(data.truncado?'Árvore incompleta: revise os itens.':''));
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
     day.addEventListener('change',()=>{
       selection.value=nearest(day.value,candidates);checkbox.checked=false;updateOlder();
     });
     updateOlder();line.append(label,day,selection,older,description);root.append(line);
   }
   feedback('lesson-map-feedback',data.aulas.length+' aulas. Nenhuma seleção foi gravada.');
 }
 async function previewMappings(){
   feedback('lesson-map-feedback','Consultando commits, tags e árvore do GitHub...');
   const result=await call('preview_lesson_mappings',el('lesson-map-repo').value.trim());
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
