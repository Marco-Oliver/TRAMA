/* Browser-based smoke and visual checks with a completely offline fake bridge.
 * npm install --no-save playwright && npx playwright install chromium
 * node tests/ui_smoke.mjs
 */
import { chromium } from 'playwright';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { mkdir } from 'node:fs/promises';

const root = path.resolve(import.meta.dirname, '..');
const bundle = Boolean(process.env.TRAMA_BUNDLED_HTML);
const pagePath = bundle
  ? path.resolve(process.env.TRAMA_BUNDLED_HTML)
  : path.join(root,'knowledge_bridge/ui/index.html');
const prefix = bundle ? 'bundled-' : '';
const screenshots = path.join(root, 'ui-smoke-artifacts');
await mkdir(screenshots, { recursive: true });

const notes = [
  {id:'02-Minhas-Aulas/Aula-001/00-Visao-geral.md', title:'Hello World em C#', lesson:'Aula-001',
   section:'02-Minhas-Aulas',kind:'visao_geral',state:'resumida_com_ia',
   updated:'28/10/2026',content:'# Hello World em C#\n\nO professor explicou **Console.WriteLine** para escrever uma mensagem no terminal.\n\n## Código\n\n```csharp\nConsole.WriteLine("Olá!");\n```\n\n[[01-Meu-Conhecimento/Conceitos/console|Console]]\n\n## Trechos da transcrição com horários verificáveis\n\n- **0:10** — Console.WriteLine mostra saída. ^min-0-10\n\n> **Contexto próximo do TXT (para conferência):**\n>\n> - 0:10 — Console.WriteLine mostra saída.\n> - 0:12 — O console permite acompanhar o resultado.'},
  {id:'02-Minhas-Aulas/Aula-025/00-Visao-geral.md', title:'Angular — componentes',lesson:'Aula-025',
   section:'02-Minhas-Aulas',kind:'visao_geral',state:'resumida_com_ia',
   updated:'30/10/2026',content:'# Angular — componentes\n\nUm componente Angular organiza a interface.'},
  {id:'01-Meu-Conhecimento/Conceitos/console.md',title:'Console',section:'01-Meu-Conhecimento',
   kind:'conceito',state:'resumida_com_ia', updated:'27/10/2026',
   summary:'### Aula-001\n\n- **Explicação sugerida pela IA:** Console é um exemplo de saída.\n- **Menção literal na transcrição:** [[02-Minhas-Aulas/Aula-001/00-Visao-geral#^min-0-10|0:10]]',
   content:'# Console\n\nConceito de saída usado nos exemplos C#.'},
  {id:'01-Meu-Conhecimento/Conceitos/console.PROPOSTA.md',title:'Console',
   section:'01-Meu-Conhecimento',kind:'conceito',state:'resumida_com_ia',
   updated:'31/10/2026',content:'# Console\n\nVersão revisada da nota do projeto.'},
];
const makeBridge=({notes})=>{
 // Playwright serializes this function into the page. Never reference
 // Node-side closures from the injected fake bridge.
 let savedConsent=false;
 const baseNote=n=>({...n,media:{video:[],video_links:[],transcript:n.lesson==='Aula-001'?[{label:'Aula 001.txt',stored:'99-Anexos/Transcricoes-Originais/aula001.txt'}]:[],materials:[]},
   related:n.lesson==='Aula-001'?[
     {id:'01-Meu-Conhecimento/Conceitos/console.md',title:'Console',kind:'conceito',section:'01-Meu-Conhecimento'},
     {id:'01-Meu-Conhecimento/Pessoas/alec.md',title:'Alec',kind:'pessoa',section:'01-Meu-Conhecimento'},
     {id:'02-Minhas-Aulas/Aula-001/Aula-001-V01.md',title:'Gravação V01',kind:'aula',section:'02-Minhas-Aulas'},
   ]:[]});
 window.__TRAMA_API__=({
  snapshot: async()=>({connected:true,vault:'C:\\TRAMA-Teste\\Cofre',notes,stats:{notes:3,videos:2,transcriptions:2,materials:0,repositories:1},favorites:[notes[0].id]}),
  note: async id=>{const n=notes.find(n=>n.id===id);return n?baseNote(n.lesson==='Aula-001'?{...n,kind:'visao_geral',state:'fontes_organizadas',content:n.content+'\n\n## Em poucas palavras\n\n**Pendente:** a IA ainda não gerou o resumo desta aula.',summary:'**Pendente:** a IA ainda não gerou o resumo desta aula.'}:n):{error:'Nota não encontrada'};},
  graph: async()=>({nodes:notes.map(n=>({...n,kind:n.kind==='visao_geral'?'indice':n.kind})),edges:[[0,2]]}),
  lesson_code_config: async(lesson)=>({ok:true,fatal:false,erros:[],github_token_configurado:false,
    aulas:{'Aula-001':{professor:[],dupla:[]}},
    invalid:window.__tramaShowInvalid&&lesson==='Aula-002'?{'Aula-002':{
      raw:{professor:[{repo:'https://evil.invalid'}],dupla:[],injected:'<img src=x onerror="window.__tramaXss=true">'},
      digest:'d'.repeat(64)}}:{},
    datas:[{aula:'Aula-001',data:'2026-10-28',origem_data:'contexto_classroom'}]}),
  lesson_code_changes: async(lesson,data)=>({ok:true,invalidated:[]}),
  save_lesson_code: async (lesson,data,confirmed,replace_invalid=false,expected_digest='')=>{
    (window.__tramaCodeSaves??=[]).push({lesson,data,confirmed,replace_invalid,expected_digest});
    return {ok:confirmed,message:'Cadastro GitHub salvo.'};
  },
  preview_lesson_mappings: async (repo,dates,branch)=>{
    window.__tramaPreviewRepo=repo;window.__tramaPreviewBranch=branch;
    return {ok:true,repo,branch,
    taxa:{restantes:56,limite:60,consultas:3},truncado:false,
    candidatos:[{id:'pasta:test',tipo:'pasta',ref_tipo:'commit',ref:'a'.repeat(40),pasta:'V3',
      rotulo:'Pasta V3',data:'2026-10-28',sugestao_anterior:{ref_tipo:'commit',ref:'a'.repeat(40),pasta:'V2'}}],
    aulas:[{aula:'Aula-001',data:'2026-10-28',origem_data:'contexto_classroom',candidato_id:'pasta:test',
      motivo:'Sugestão apenas por data'}]};},
  suggest_lesson_mappings: async dates=>{
    (window.__tramaPythonSuggestCalls??=[]).push(dates);
    return {ok:true,aulas:[{aula:'Aula-001',data:dates['Aula-001'],candidato_id:'pasta:test',
      motivo:'Preferência por pasta do backend'}]};
  },
  apply_lesson_mappings: async (rows,confirmed)=>{(window.__tramaMapSaves??=[]).push({rows,confirmed});return {ok:true,message:'1 aula(s) confirmada(s)'};},
  process_lesson: async (lesson, confirmed, force)=>{
    window.__tramaLessonRefreshCalls=(window.__tramaLessonRefreshCalls||0)+1;
    (window.__tramaLessonForceArgs??=[]).push(force);
    if(!confirmed || lesson!=='Aula-001')
      return {ok:false,message:'Confirmação obrigatória'};
    if(window.__tramaLessonRefreshCalls===1)
      return {ok:false,reason:'local_limit',
              message:'O limite local de chamadas nesta execução foi atingido. Os trechos anteriores estão preservados.'};
    return {ok:true,message:'Análise retomada com trechos anteriores reaproveitados'};
  },
  search_transcript: async (stored,query)=>{
    window.__tramaTranscriptSearchCalls=(window.__tramaTranscriptSearchCalls||0)+1;
    return stored==='99-Anexos/Transcricoes-Originais/aula001.txt' && query==='terminal'
      ? {ok:true,excerpt:'[0:09] Comando no terminal <img src=x onerror="window.__tramaXss=true">',times:['0:09']}
      : {ok:true,excerpt:'',times:[]};
  },
  open_attachment: async()=>({ok:true}),
  ai_status: async()=>({configured:{gemini:true},confirmed_free:true,
                             processing_consent:savedConsent}),
  set_ai_processing_consent: async allowed=>{
    savedConsent=allowed===true;
    return {ok:true,processing_consent:savedConsent,
            message:savedConsent?'Autorização ativa nos Ajustes.':'Autorização revogada.'};
  },
  search_notes: async (query,limit=80)=>{
    const q=query.toLowerCase();
    const found=notes.filter(n=>(n.id+' '+n.title+' '+n.content).toLowerCase().includes(q));
    return {ok:true,total:found.length,matches:found.slice(0,limit).map(n=>({
      id:n.id,title:n.title,section:n.section,
      snippet:n.content.toLowerCase().includes(q)?n.content.slice(0,150):'',
      in_content:n.content.toLowerCase().includes(q)
    }))};
  },
  copy_note_link: async id=>({ok:true,message:'Link interno copiado.'}),
  compare_proposal: async id=>({ok:id.endsWith('.PROPOSTA.md'),original:'console.md',proposal:id,diff:'--- original\n+++ proposta\n-Versão antiga\n+Versão revisada <img src=x onerror=window.__tramaXss=true>',truncated:false}),
  vault_disk_usage: async()=>({ok:true,total_bytes:10485760,files:15,
    categories:{notes:1048576,attachments:2097152,repositories:5242880,catalog:1048576,other:1048576}}),
  check_updates: async()=>({ok:true,available:false,message:'Você já está na versão mais recente.'}),
  teacher_ask: async (question, mode, code, confirmed)=>confirmed?({
    ok:true,answer:question.includes('XSSTEST')
      ? 'Conteúdo malicioso simulado: <img src=x onerror="window.__tramaXss=true"> <svg onload="window.__tramaXss=true"></svg>'
      : mode==='corrigir'?'O código precisa de aspas corretas.':'Use **Console.WriteLine**. Veja a aula.',
    sources:[{id:notes[0].id,title:notes[0].title,section:notes[0].section}],
    provider:'offline-test',model:'persona',uncertainty:'',read_only:true
  }):({ok:false,message:'Consentimento obrigatório'}),
  teacher_reset: async()=>({ok:true}),
  backup_vault: async()=>({ok:true,message:'Backup fictício criado com sucesso.'}),
  restore_vault: async()=>({ok:true,message:'Restauração fictícia em pasta nova.'}),
  toggle_favorite: async()=>({ok:true,favorites:[notes[0].id]}),
  open_note: async()=>({ok:true}),
  open_obsidian: async()=>({ok:true}),
  window_action: async()=>({ok:true}),
  staged_items: async()=>({ok:true,items:[],max:100}),
  check_update: async()=>({ok:true}),
 });};

let errors=[];
const browser=await chromium.launch({headless:true});
try{
  for(const [width,height] of [[1366,850],[800,720]]){
    const page=await browser.newPage({viewport:{width,height}});
    page.on('pageerror',error=>errors.push(`${width}px: ${error.message}`));
    page.on('console',msg=>{if(msg.type()==='error')errors.push(`${width}px console: ${msg.text()}`);});
    await page.addInitScript(makeBridge, {notes});
    await page.goto(pathToFileURL(pagePath).href);
    const clippedNavigation=await page.evaluate(()=>{
      const button=document.querySelector('.nav-item[data-view="knowledge"]');
      const label=[...button.childNodes].find(n=>n.nodeType===Node.TEXT_NODE);
      if(!label)return true;
      const range=document.createRange();
      range.selectNodeContents(label);
      return range.getBoundingClientRect().right>button.getBoundingClientRect().right-2;
    });
    if(clippedNavigation)throw Error('Knowledge navigation label is visually clipped at '+width+'px');
    const assertNoUiError=async step=>{
      const status=(await page.locator('#status-message').textContent())||'';
      const toast=(await page.locator('#toast').textContent())||'';
      if(/Falha ao executar|ReferenceError:|TypeError:/.test(status+' '+toast))
        throw Error(step+': the app swallowed an error: '+status+' / '+toast);
    };
    await assertNoUiError('initial load');
    await page.locator('.nav-item[data-view="home"]').click();
    await page.getByRole('button',{name:'Conectar meu cofre'}).waitFor();
    await page.screenshot({path:path.join(screenshots,`${prefix}home-${width}.png`),fullPage:true});
    // Graph uses the exact approved Canvas renderer, including packaged CSP.
    await page.locator('.nav-item[data-view="graph"]').click();
    await page.locator('canvas.tg-canvas').waitFor();
    await page.locator('.tg-kind[data-kind="conceito"]').waitFor();
    const indexKind=page.locator('.tg-kind[data-kind="indice"]');
    await indexKind.waitFor();
    if(await indexKind.evaluate(el=>el.classList.contains('on')))
      throw Error('Index nodes must start hidden');
    await page.getByRole('button',{name:'Mostrar índices'}).click();
    if(!(await indexKind.evaluate(el=>el.classList.contains('on'))))
      throw Error('Show indexes filter did not enable index nodes');
    await page.getByRole('button',{name:'Ocultar índices'}).click();
    const conceptKind=page.locator('.tg-kind[data-kind="conceito"]');
    await conceptKind.click();
    if(await conceptKind.evaluate(el=>el.classList.contains('on')))
      throw Error('Concept filter did not hide nodes');
    await conceptKind.click();
    await page.locator('input.tg-search').fill('console');
    await page.locator('canvas.tg-canvas').hover({position:{x:15,y:15}});
    await page.mouse.wheel(0,-200);
    await page.getByRole('button',{name:'Centralizar'}).click();
    await page.getByRole('button',{name:'Tema escuro'}).click();
    await page.locator('.tg-root.tg-dark').waitFor();
    await assertNoUiError('graph interactions');
    await page.screenshot({path:path.join(screenshots,`${prefix}graph-${width}.png`)});
    await page.locator('.nav-item[data-view="home"]').click();
    if(await page.locator('canvas.tg-canvas').count())
      throw Error('Graph canvas remained mounted after leaving the view');
    await page.locator('.nav-item[data-view="graph"]').click();
    await page.getByRole('button',{name:'Tema claro'}).waitFor();
    await page.locator('.nav-item[data-view="home"]').click();
    await page.getByRole('button',{name:'Ver minhas aulas'}).click();
    await page.locator('.lesson-row').first().waitFor();
    await page.locator('#note-heading .note-title').getByText('Hello World em C#').waitFor();
    if((await page.locator('#note-content').innerText()).includes('Suas notas aparecerão'))
      throw Error('Lesson notes were not loaded into the interface');
    await assertNoUiError('lessons');
    // GitHub lesson mapping is manual and must remain inert until confirmation.
    await page.locator('#btn-lesson-code').click();
    await page.locator('#lesson-code-dialog').waitFor({state:'visible'});
    if(!(await page.locator('#lesson-code-token').innerText()).toLowerCase().includes('token github'))
      throw Error('Registration must show whether GitHub credentials are configured');
    if(await page.locator('#lesson-code-github-key[type="password"]').count()!==1 ||
       await page.locator('#lesson-code-save-token').count()!==1 ||
       await page.locator('#lesson-code-remove-token').count()!==1)
      throw Error('Secure DPAPI GitHub token controls are missing');
    await page.locator('#lesson-code-add-teacher').click();
    await page.locator('#lesson-code-add-teacher').click();
    await page.locator('#lesson-code-add-student').click();
    const teacher=page.locator('#code-teachers .code-repo-row');
    const students=page.locator('#code-students .code-repo-row');
    if(await teacher.count()!==2||await students.count()!==1)throw Error('Missing 2+1 GitHub form rows');
    await teacher.nth(0).locator('[data-code="rotulo"]').fill('Back-end professor');
    await teacher.nth(0).locator('[data-code="repo"]').fill('https://github.com/professor/backend');
    await teacher.nth(1).locator('[data-code="rotulo"]').fill('Front-end professor');
    await teacher.nth(1).locator('[data-code="repo"]').fill('https://github.com/professor/frontend');
    await students.locator('[data-code="rotulo"]').fill('Back-end dupla');
    await students.locator('[data-code="repo"]').fill('https://github.com/dupla/backend');
    await teacher.nth(0).locator('[data-code="id"]').fill('map-abcdef1234567890');
    const teacherSelector=students.locator('[data-code="professor_id"]');
    if(await teacherSelector.locator('option').count()!==3)
      throw Error('Pair teacher field is not a populated dropdown');
    if(!(await teacherSelector.locator('option[value="map-abcdef1234567890"]').innerText()).includes('Back-end professor'))
      throw Error('Teacher dropdown does not show readable labels for mapped IDs');
    await teacherSelector.selectOption('map-abcdef1234567890');
    await page.locator('#lesson-code-form button[type=submit]').click();
    await page.locator('#trama-confirm-dialog').waitFor({state:'visible'});
    await page.locator('#trama-confirm-cancel').click();
    if(await page.evaluate(()=>window.__tramaCodeSaves?.length||0))throw Error('GitHub form saved without user consent');
    await page.locator('#lesson-code-form button[type=submit]').click();
    await page.locator('#trama-confirm-accept').click();
    await page.waitForFunction(()=>window.__tramaCodeSaves?.length===1);
    const data=await page.evaluate(()=>window.__tramaCodeSaves[0]);
    if(data.lesson!=='Aula-001'||!data.confirmed||data.data.professor.length!==2||
       data.data.dupla.length!==1||data.data.dupla[0].professor_id!=='map-abcdef1234567890')
      throw Error('GitHub 2 professor + 1 student form did not submit exact data: '+JSON.stringify(data));
    // No empty registration may be saved implicitly.
    await page.locator('#lesson-code-number').fill('3');
    await page.locator('#lesson-code-load').click();
    await page.locator('#lesson-code-form button[type=submit]').click();
    if(!(await page.locator('#lesson-code-feedback').innerText()).includes('Cadastro vazio'))
      throw Error('Empty mapping was not rejected');
    if(await page.evaluate(()=>window.__tramaCodeSaves?.length)!==1)
      throw Error('Empty registration reached backend write');
    // An invalid old record must be shown as raw TEXT and specifically confirmed.
    await page.evaluate(()=>{window.__tramaShowInvalid=true;});
    await page.locator('#lesson-code-number').fill('2');
    await page.locator('#lesson-code-load').click();
    await page.locator('#lesson-code-invalid').waitFor({state:'visible'});
    const raw=await page.locator('#lesson-code-invalid-raw').innerText();
    if(!raw.includes('https://evil.invalid')||!raw.includes('<img'))
      throw Error('Invalid raw mapping not shown to user');
    if(await page.locator('#lesson-code-invalid img').count())
      throw Error('Untrusted raw JSON was interpreted as HTML');
    await page.locator('#lesson-code-add-teacher').click();
    await page.locator('#code-teachers [data-code="rotulo"]').fill('Professor corrigido');
    await page.locator('#code-teachers [data-code="repo"]').fill('https://github.com/professor/validado');
    await page.locator('#lesson-code-form button[type=submit]').click();
    await page.locator('#trama-confirm-dialog').waitFor({state:'visible'});
    if(!(await page.locator('#trama-confirm-title').innerText()).includes('registro inválido'))
      throw Error('Invalid mapping did not require specific confirmation');
    await page.locator('#trama-confirm-cancel').click();
    if(await page.evaluate(()=>window.__tramaCodeSaves?.length)!==1)
      throw Error('Invalid mapping replaced after denial');
    await page.locator('#lesson-code-form button[type=submit]').click();
    await page.locator('#trama-confirm-accept').click();
    await page.waitForFunction(()=>window.__tramaCodeSaves?.length===2);
    const replaced=await page.evaluate(()=>window.__tramaCodeSaves[1]);
    if(!replaced.replace_invalid||replaced.expected_digest!=='d'.repeat(64))
      throw Error('Explicit original-record digest was not sent with replacement');
    await page.locator('#lesson-code-map-open').click();
    await page.locator('#lesson-map-dialog').waitFor({state:'visible'});
    await page.locator('#lesson-map-repo').fill('https://github.com/professor/backend');
    await page.locator('#lesson-map-branch').fill('course/v7');
    if(!(await page.locator('#lesson-map-dialog').innerText()).includes('Aulas ainda não importadas não aparecem aqui'))
      throw Error('Unimported lessons warning is missing');
    await page.locator('#lesson-map-search').click();
    await page.waitForFunction(()=>window.__tramaPreviewBranch==='course/v7');
    await page.locator('.lesson-map-row').first().waitFor();
    if(!(await page.locator('#lesson-map-quota').innerText()).includes('56 de 60'))
      throw Error('Remaining API requests not displayed in map UI');
    await page.locator('.lesson-map-row input[type="date"]').first().fill('2026-10-29');
    await page.waitForFunction(()=>window.__tramaPythonSuggestCalls?.length===1);
    if(await page.locator('.lesson-map-row select').first().inputValue()!=='pasta:test')
      throw Error('Date edit ignored the Python-selected reference');
    if(await page.evaluate(()=>window.__tramaMapSaves?.length||0))
      throw Error('Mappings were written during preview');
    await page.locator('.lesson-map-row [data-map-check]').first().check();
    await page.locator('#lesson-map-save').click();
    await page.locator('#trama-confirm-dialog').waitFor({state:'visible'});
    await page.locator('#trama-confirm-cancel').click();
    if(await page.evaluate(()=>window.__tramaMapSaves?.length||0))
      throw Error('Mapping saved after declining consent');
    await page.locator('#lesson-map-save').click();
    await page.locator('#trama-confirm-accept').click();
    await page.waitForFunction(()=>window.__tramaMapSaves?.length===1);
    await page.locator('#lesson-map-dismiss').click();

    const sidebarCards=page.locator('#details-panel .detail-card');
    const technical=sidebarCards.filter({has:page.locator('h3', {hasText:'Conhecimentos técnicos'})});
    const people=sidebarCards.filter({has:page.locator('h3', {hasText:'Pessoas citadas'})});
    const recordings=sidebarCards.filter({has:page.locator('h3', {hasText:'Gravações e notas desta aula'})});
    // The right panel intentionally collapses at 800 px. Validate that its
    // relationships remain correctly categorized in the DOM at both sizes.
    await technical.getByText('Console').waitFor({state:'attached'});
    await people.getByText('Alec').waitFor({state:'attached'});
    await recordings.getByText('Gravação V01').waitFor({state:'attached'});
    if((await technical.innerText()).includes('Alec')||
       (await people.innerText()).includes('Console'))
      throw Error('People mixed with technical knowledge in the right panel');
    // The lessons workspace opens in 'Nota completa'; the action belongs to 'Resumo'.
    await page.locator('#note-tabs .tab').getByText('Resumo',{exact:true}).click();
    // Reanalysis must never reach the bridge without the user's confirmation.
    const refresh=page.locator('#refresh-this-lesson');
    if(!(await refresh.count())){
      const trace=await page.evaluate(()=>({
        view:app.view,tab:app.tab,noteKind:app.note?.kind,
        lesson:app.note?.lesson,selected:app.selected,
        buttons:[...document.querySelectorAll('#note-content button')].map(b=>b.textContent.trim()).slice(0,8),
        body:document.querySelector('#note-content')?.textContent.slice(0,350)
      }));
      throw Error('Scoped reanalysis button was not rendered: '+JSON.stringify(trace));
    }
    if(!((await page.locator('#note-content').innerText()).includes('Gerar resumo desta aula')))
      throw Error('Missing pending-summary action on real overview note');
    await refresh.waitFor({timeout:3000});
    await refresh.click();
    await page.locator('#trama-confirm-dialog').waitFor({state:'visible'});
    await page.locator('#trama-confirm-cancel').click();
    if(await page.evaluate(()=>window.__tramaLessonRefreshCalls||0))
      throw Error('Lesson reanalysis ran after cancelling consent');
    await refresh.click();
    await page.locator('#trama-confirm-dialog').waitFor({state:'visible'});
    await page.locator('#trama-confirm-accept').click();
    await page.waitForFunction(()=>window.__tramaLessonRefreshCalls===1);
    await page.locator('#lesson-ai-feedback').getByText('limite local',{exact:false}).waitFor();
    if(JSON.stringify(await page.evaluate(()=>window.__tramaLessonForceArgs))!=='[false]')
      throw Error('Pending lesson restarted all AI chunks instead of resuming cache');
    await refresh.click();
    await page.locator('#trama-confirm-dialog').waitFor({state:'visible'});
    await page.locator('#trama-confirm-accept').click();
    await page.waitForFunction(()=>window.__tramaLessonRefreshCalls===2);
    await assertNoUiError('lesson pending AI resume');

    // The transcript-search feature is local-only and must render untrusted
    // transcript text as text rather than executable HTML.
    await page.locator('#note-tabs .tab').filter({hasText:/^Transcrição$/}).click();
    await page.locator('#transcript-query').fill('terminal');
    await page.locator('#transcript-search').click();
    const excerpt=page.locator('.transcript-find-excerpt');
    await excerpt.waitFor();
    if(!(await excerpt.textContent()).includes('[0:09]'))
      throw Error('Transcript search lost the original timestamp');
    if(await page.evaluate(()=>Boolean(window.__tramaXss ||
         document.querySelector('#transcript-search-results img'))))
      throw Error('Untrusted transcript snippet executed HTML');
    if((await page.evaluate(()=>window.__tramaTranscriptSearchCalls||0))!==1)
      throw Error('Transcript search did not use the local bridge exactly once');

    await page.locator('[data-list-filter="favorites"]').click();
    if(await page.locator('.lesson-row').count()!==1)throw Error('Favorites filter did not work');
    await page.locator('[data-list-filter="recent"]').click();
    if(await page.locator('.lesson-row').count()!==2)throw Error('Recent filter did not work');
    if(!(await page.locator('.lesson-row').first().innerText()).includes('Aula 025'))
      throw Error('Recent filter must sort real Brazilian DD/MM/YYYY dates');
    await page.locator('[data-list-filter="all"]').click();
    await page.screenshot({path:path.join(screenshots,`${prefix}lessons-${width}.png`),fullPage:true});
    // A technical profile must show its own explanation, not the empty
    // generic lesson cards. The source time must open its matching block.
    await page.locator('.nav-item[data-view="knowledge"]').click();
    await page.locator('#note-heading .note-title').getByText('Console').waitFor();
    await page.locator('#note-tabs .tab').getByText('Resumo',{exact:true}).click();
    await page.locator('#note-content').getByText('Explicações e fontes das aulas').waitFor();
    if((await page.locator('#note-content').innerText()).includes('Principais conceitos'))
      throw Error('Technical concept summary still shows generic lesson cards');
    await page.locator('#note-content [data-lib-anchor="min-0-10"]').click();
    await page.locator('#library-workspace').waitFor({state:'visible'});
    await page.locator('#library-workspace #min-0-10').waitFor({state:'attached'});
    await page.locator('.lib-title').getByText('Hello World em C#').waitFor();
    // Each source timestamp must render as a separate list item; flattening
    // all blockquote lines makes study notes unreadable in the actual WebView.
    const quoteTimes=page.locator('#library-workspace .lib-md blockquote ul li');
    await quoteTimes.first().waitFor({state:'visible'});
    if(await quoteTimes.count()!==2 ||
       !(await quoteTimes.nth(0).innerText()).includes('0:10') ||
       !(await quoteTimes.nth(1).innerText()).includes('0:12'))
      throw Error('Transcript evidence was flattened instead of readable timestamp bullets');
    await assertNoUiError('concept source anchor navigation');

    await page.locator('#search-all').fill('Angular');
    await page.locator('#btn-search-all').click();
    await page.locator('#library-workspace').waitFor({state:'visible'});
    await page.locator('.lib-title').getByText('Angular — componentes').waitFor();
    await assertNoUiError('library search');
    // Full-text search must find the source sentence, not just title/path.
    await page.locator('#lib-folder-search').fill('terminal');
    await page.getByText(/nota\(s\) encontrada\(s\)/).waitFor({timeout:6000});
    await page.locator('#lib-tree-content .lib-file-row').first().waitFor();
    if(!((await page.locator('#lib-tree-content').innerText()).includes('terminal')))
      throw Error('Full-text search did not show an excerpt from the note');
    if(width<=800){
      const nowrap=await page.evaluate(()=>{
        const label=document.querySelector('#lib-tree-content .lib-file-row .file-label');
        return label?getComputedStyle(label).whiteSpace:'missing';
      });
      if(nowrap!=='normal')throw Error('Library note labels must wrap at 800px, found '+nowrap);
    }
    await page.screenshot({path:path.join(screenshots,`${prefix}library-${width}.png`),fullPage:true});
    await page.locator('.nav-item[data-view="teacher"]').click();
    await page.getByRole('heading',{name:/IA Professor/}).waitFor();
    await page.screenshot({path:path.join(screenshots,`${prefix}professor-empty-${width}.png`),fullPage:true});
    await page.locator('[data-teacher-mode="corrigir"]').click();
    if(!(await page.locator('#teacher-code').isVisible()))throw Error('Review-code box hidden');
    await page.locator('#teacher-question').fill('Como corrigir Console.WriteLine em C#?');
    await page.locator('#teacher-code').fill('Console.WriteLine("Olá);');
    await page.locator('#teacher-submit').click();
    const required=await page.locator('#teacher-feedback').textContent();
    if(!required.includes('autorização'))throw Error('No required consent UI');
    await page.locator('#teacher-consent').check();
    await page.locator('#teacher-submit').click();
    await page.getByText('O código precisa de aspas corretas.').waitFor();
    const geometry=await page.evaluate(()=>{
      const rect=selector=>document.querySelector(selector)?.getBoundingClientRect();
      const f=rect('#teacher-form'),q=rect('#teacher-question'),send=rect('#teacher-submit');
      const t=document.querySelector('#toast');
      const toast=t&&!t.classList.contains('hidden')?rect('#toast'):null;
      const intersects=(x,y)=>x&&y&&x.left<y.right&&x.right>y.left&&x.top<y.bottom&&x.bottom>y.top;
      return {form:f&&{top:f.top,bottom:f.bottom},question:q&&{top:q.top,bottom:q.bottom},
              submitCovered:intersects(send,toast)};
    });
    if(geometry.question.top<geometry.form.top-2||
       geometry.question.bottom>geometry.form.bottom+2)
       throw Error('Professor question field is clipped inside its form: '+JSON.stringify(geometry));
    if(geometry.submitCovered)throw Error('Toast overlaps Send button at '+width+'px');
    await page.screenshot({path:path.join(screenshots,`${prefix}professor-answer-${width}.png`),fullPage:true});
    // Attack simulation: model output must stay inert, even with forged HTML.
    await page.locator('[data-teacher-mode="explicar"]').click();
    await page.locator('#teacher-question').fill('XSSTEST: revise os exemplos de Hello World em C#');
    await page.locator('#teacher-consent').check();
    await page.locator('#teacher-submit').click();
    await page.getByText(/Conteúdo malicioso simulado/).waitFor();
    const unsafe = await page.evaluate(() =>
      Boolean(window.__tramaXss || document.querySelector('.teacher-markdown img[src=x]') ||
              document.querySelector('.teacher-markdown svg[onload]')));
    if(unsafe)throw Error('Untrusted AI output was interpreted as executable HTML');
    await page.locator('.teacher-ref').first().click();
    await page.locator('#library-workspace').waitFor({state:'visible'});
    await page.locator('.lib-title').getByText('Hello World em C#').waitFor();
    await assertNoUiError('teacher cited source');
    // Previous content-search filter may still be active; select Console explicitly.
    await page.locator('#lib-folder-search').fill('Console');
    await page.locator('#lib-tree-content [data-lib-note="01-Meu-Conhecimento/Conceitos/console.md"]').click();
    await page.getByText('Atualização disponível para revisão.').waitFor();
    await page.locator('[data-lib-note="01-Meu-Conhecimento/Conceitos/console.PROPOSTA.md"]').first().click();
    await page.locator('.lib-note-panel .lib-proposal-compare').click();
    await page.locator('#trama-diff-dialog').waitFor({state:'visible'});
    if(!(await page.locator('#trama-diff-content').innerText()).includes('Versão revisada'))
      throw Error('Safe proposal diff did not render');
    if(await page.locator('#trama-diff-content img').count())
      throw Error('Proposal diff injected arbitrary markup');
    await page.locator('#trama-diff-dismiss').click();
    await page.locator('.nav-item[data-view="settings"]').click();
    await page.locator('#ai-processing-consent').check();
    await page.getByText('Autorização ativa nos Ajustes.').waitFor();
    await page.locator('#ai-processing-consent').uncheck();
    await page.getByText('Autorização revogada.').waitFor();
    await page.locator('#check-storage').click();
    await page.getByText(/Total: 10.0 MB/).waitFor();
    await page.getByRole('button',{name:'Verificar atualizações'}).click();
    await page.getByText('Você já está na versão mais recente.').waitFor();
    await assertNoUiError('settings and updates');
    await page.screenshot({path:path.join(screenshots,`${prefix}settings-${width}.png`),fullPage:true});
    await page.locator('.nav-item[data-view="lessons"]').click();
    await page.locator('#btn-import').click();
    await page.locator('#auto-dialog').waitFor({state:'visible'});
    await page.locator('#auto-repos').fill('https://github.com/academiadoprogramador-fullstack/teste.git');
    if(!(await page.locator('#auto-dialog').innerText()).includes('Repositórios GitHub relacionados'))
       throw Error('Batch import is missing its dedicated GitHub field');
    if((await page.locator('#auto-dialog').innerText()).includes('Paint'))
       throw Error('Outdated Paint instructions remain in import');
    await page.locator('#auto-close').click();
    const dimensions=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth}));
    if(dimensions.scrollWidth>dimensions.viewport+2)throw Error(`Horizontal viewport overflow at ${width}: ${JSON.stringify(dimensions)}`);
    await page.close();
  }
  if(errors.length)throw Error('Browser errors:\n'+errors.join('\n'));
  console.log('PASS: two viewports, internal dialogs, content search, consent settings, GitHub import, study flow and screenshots');
}finally{
  await browser.close();
}
