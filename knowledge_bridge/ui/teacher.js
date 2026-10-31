'use strict';
// Conversa do Professor: memória apenas em RAM, não grava nada no Obsidian.
// Exibir material do modelo como texto escapado com o renderer seguro da biblioteca.
const teacherState={messages:[],busy:false,mode:'explicar',draft:'',code:''};
function teacherClearVisual(el){
 const r=document.createElement('p');r.className='teacher-empty';
 r.textContent='Pergunte sobre suas aulas, peça desafios ou cole um código para receber dicas. O Professor usa apenas notas encontradas no Obsidian.';
 el.append(r);
}
function teacherOpenSource(source){
 app.selected=source.id;
 setView('library');
}
function teacherDrawMessages(){
 const log=$('teacher-log');if(!log)return;log.replaceChildren();
 if(!teacherState.messages.length){teacherClearVisual(log);return;}
 for(const entry of teacherState.messages){
  const wrap=document.createElement('article');
  wrap.className='teacher-bubble '+(entry.role==='user'?'teacher-user':'teacher-assistant');
  const role=document.createElement('strong');
  role.className='teacher-role';
  role.textContent=entry.role==='user'?'Você':'IA Professor';
  wrap.append(role);
  if(entry.role==='assistant'&&entry.answer){
   const content=document.createElement('div');
   content.className='teacher-markdown';
   // libRenderMarkdown escapes source/model text and renders code blocks.
   content.innerHTML=libRenderMarkdown(entry.answer,'','Professor');
   wrap.append(content);
  }else{
   const text=document.createElement('p');text.className='teacher-plain';
   text.textContent=entry.answer||entry.question||'';
   wrap.append(text);
  }
  if(entry.sources?.length){
   const label=document.createElement('p');
   label.className='teacher-cite-label';label.textContent='Notas consultadas';
   wrap.append(label);
   const refs=document.createElement('div');refs.className='teacher-references';
   for(const source of entry.sources){
    const button=document.createElement('button');button.type='button';
    button.className='teacher-ref';button.textContent=source.title||source.id;
    button.title=source.id;button.addEventListener('click',()=>teacherOpenSource(source));
    refs.append(button);
   }
   wrap.append(refs);
  }
  if(entry.provider){
   const caption=document.createElement('small');caption.className='teacher-model';
   caption.textContent='Modelo: '+entry.provider+' · '+entry.model+' · IA pode errar; confira as notas.';
   wrap.append(caption);
  }
  if(entry.uncertainty){
   const warning=document.createElement('p');warning.className='teacher-uncertainty';
   warning.textContent='Limitação: '+entry.uncertainty;wrap.append(warning);
  }
  log.append(wrap);
 }
 log.scrollTop=log.scrollHeight;
}
function renderTeacher(el){
 el.innerHTML=`<div class="teacher-area">
 <div class="teacher-header"><div><h2>IA Professor <span class="teacher-beta">Experimental</span></h2>
 <p>Seu material do Obsidian, explicado com a IA gratuita configurada. <strong>Leitura apenas:</strong> nenhuma nota será alterada.</p></div>
 <button type="button" id="teacher-clear" class="teacher-secondary">Nova conversa</button></div>
 <div class="teacher-modes" role="group" aria-label="Objetivo da conversa">
  <button data-teacher-mode="explicar" type="button">✦ Explicar / revisar</button>
  <button data-teacher-mode="desafiar" type="button">◇ Criar desafios</button>
  <button data-teacher-mode="corrigir" type="button">⌘ Corrigir meu código</button>
 </div>
 <div id="teacher-log" class="teacher-log" role="log" aria-live="polite"></div>
 <form id="teacher-form" class="teacher-form">
  <label for="teacher-question">O que você quer estudar?</label>
  <textarea id="teacher-question" rows="2" maxlength="2500" placeholder="Ex.: Como o professor explicou Hello World em C#?" required></textarea>
  <div id="teacher-code-box" class="teacher-code-box hidden">
   <label for="teacher-code">Cole seu código (não será executado)</label>
   <textarea id="teacher-code" rows="6" maxlength="6500" spellcheck="false" placeholder="Cole apenas o código que deseja revisar. Remova senhas e chaves."></textarea>
  </div>
  <label class="teacher-consent"><input type="checkbox" id="teacher-consent"/>
   Autorizo enviar esta pergunta, o código colado (se houver), trechos das notas selecionadas e parte da conversa à API gratuita configurada.</label>
  <div class="teacher-controls"><p id="teacher-feedback" role="status">Uma pergunta pode consumir cota gratuita da API. Nenhuma cobrança é garantida se a conta externa tiver faturamento habilitado.</p>
  <button id="teacher-submit" type="submit">Enviar pergunta</button></div>
 </form></div>`;
 const modeButtons=[...el.querySelectorAll('[data-teacher-mode]')];
 const codeBox=el.querySelector('#teacher-code-box');
 function syncMode(){
  for(const button of modeButtons){
   const selected=button.dataset.teacherMode===teacherState.mode;
   button.classList.toggle('active',selected);
   button.setAttribute('aria-pressed',selected?'true':'false');
  }
  codeBox.classList.toggle('hidden',teacherState.mode!=='corrigir');
 }
 modeButtons.forEach(button=>button.addEventListener('click',()=>{
  teacherState.draft=el.querySelector('#teacher-question').value;
  teacherState.code=el.querySelector('#teacher-code').value;
  teacherState.mode=button.dataset.teacherMode;syncMode();
 }));
 el.querySelector('#teacher-question').value=teacherState.draft;
 el.querySelector('#teacher-code').value=teacherState.code;
 syncMode();
 teacherDrawMessages();
 el.querySelector('#teacher-clear').addEventListener('click',async()=>{
  if(teacherState.busy)return;
  const response=await call('teacher_reset');
  if(!response?.ok){el.querySelector('#teacher-feedback').textContent=response?.message||'Não foi possível limpar.';return;}
  teacherState.messages=[];teacherState.draft='';teacherState.code='';
  el.querySelector('#teacher-question').value='';
  el.querySelector('#teacher-code').value='';
  teacherDrawMessages();
 });
 el.querySelector('#teacher-form').addEventListener('submit',async event=>{
  event.preventDefault();
  if(teacherState.busy)return;
  const question=el.querySelector('#teacher-question').value.trim();
  const code=teacherState.mode==='corrigir'?el.querySelector('#teacher-code').value:'';
  const status=el.querySelector('#teacher-feedback'),button=el.querySelector('#teacher-submit');
  if(!question){status.textContent='Escreva sua dúvida primeiro.';return;}
  if(teacherState.mode==='corrigir'&&!code.trim()){status.textContent='Cole o código para corrigir.';return;}
  if(!el.querySelector('#teacher-consent').checked){status.textContent='Marque a autorização para enviar dados à API.';return;}
  teacherState.busy=true;button.disabled=true;
  status.textContent='Buscando suas aulas e preparando uma resposta baseada nas fontes…';
  teacherState.draft=question;teacherState.code=code;
  try{
   const answer=await call('teacher_ask',question,teacherState.mode,code,true);
   if(!answer?.ok){status.textContent=answer?.message||'Não foi possível responder.';return;}
   teacherState.messages.push({role:'user',question});
   teacherState.messages.push({role:'assistant',answer:answer.answer,sources:answer.sources,
                               provider:answer.provider,model:answer.model,uncertainty:answer.uncertainty});
   teacherState.messages=teacherState.messages.slice(-18);
   teacherState.draft='';teacherState.code='';
   el.querySelector('#teacher-question').value='';el.querySelector('#teacher-code').value='';
   el.querySelector('#teacher-consent').checked=false;
   teacherDrawMessages();
   status.textContent='Resposta baseada nas notas listadas acima. Confira as fontes quando necessário.';
  }finally{teacherState.busy=false;button.disabled=false;}
 });
}
