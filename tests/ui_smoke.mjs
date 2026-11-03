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
   updated:'28/10/2026',content:'# Hello World em C#\n\nO professor explicou **Console.WriteLine** para escrever uma mensagem no terminal.\n\n## Código\n\n```csharp\nConsole.WriteLine("Olá!");\n```\n\n[[01-Meu-Conhecimento/Conceitos/console|Console]]'},
  {id:'02-Minhas-Aulas/Aula-025/00-Visao-geral.md', title:'Angular — componentes',lesson:'Aula-025',
   section:'02-Minhas-Aulas',kind:'visao_geral',state:'resumida_com_ia',
   updated:'30/10/2026',content:'# Angular — componentes\n\nUm componente Angular organiza a interface.'},
  {id:'01-Meu-Conhecimento/Conceitos/console.md',title:'Console',section:'01-Meu-Conhecimento',
   kind:'conceito',state:'resumida_com_ia', updated:'27/10/2026',
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
  graph: async()=>({nodes:notes,edges:[[0,2]]}),
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
    await page.getByRole('button',{name:'Ver minhas aulas'}).click();
    await page.locator('.lesson-row').first().waitFor();
    await page.locator('#note-heading .note-title').getByText('Hello World em C#').waitFor();
    if((await page.locator('#note-content').innerText()).includes('Suas notas aparecerão'))
      throw Error('Lesson notes were not loaded into the interface');
    await assertNoUiError('lessons');
    const sidebarCards=page.locator('#details-panel .detail-card');
    const technical=sidebarCards.filter({has:page.locator('h3', {hasText:'Conhecimentos técnicos'})});
    const people=sidebarCards.filter({has:page.locator('h3', {hasText:'Pessoas citadas'})});
    const recordings=sidebarCards.filter({has:page.locator('h3', {hasText:'Gravações e notas desta aula'})});
    await technical.getByText('Console').waitFor();
    await people.getByText('Alec').waitFor();
    await recordings.getByText('Gravação V01').waitFor();
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
