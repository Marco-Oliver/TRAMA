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
];
const makeBridge=({notes})=>{
 // Playwright serializes this function into the page. Never reference
 // Node-side closures from the injected fake bridge.
 const baseNote=n=>({...n,media:{video:[],video_links:[],transcript:[],materials:[]},related:[]});
 window.__TRAMA_API__=({
  snapshot: async()=>({connected:true,vault:'C:\\TRAMA-Teste\\Cofre',notes,stats:{notes:3,videos:2,transcriptions:2,materials:0,repositories:1},favorites:[notes[0].id]}),
  note: async id=>{const n=notes.find(n=>n.id===id);return n?baseNote(n.lesson==='Aula-001'?{...n,kind:'aula',state:'aguardando_ia',summary:'Pendente: resumo não gerado.'}:n):{error:'Nota não encontrada'};},
  graph: async()=>({nodes:notes,edges:[[0,2]]}),
  process_lesson: async (lesson, confirmed)=>{
    window.__tramaLessonRefreshCalls=(window.__tramaLessonRefreshCalls||0)+1;
    return confirmed && lesson==='Aula-001' ? {ok:true,message:'Análise simulada'} : {ok:false,message:'Confirmação obrigatória'};
  },
  ai_status: async()=>({configured:{gemini:true},confirmed_free:true}),
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
    await refresh.waitFor({timeout:3000});
    page.once('dialog',dialog=>dialog.dismiss());
    await refresh.click();
    if(await page.evaluate(()=>window.__tramaLessonRefreshCalls||0))
      throw Error('Lesson reanalysis ran after cancelling consent');
    page.once('dialog',dialog=>dialog.accept());
    await refresh.click();
    await page.waitForFunction(()=>window.__tramaLessonRefreshCalls===1);
    await assertNoUiError('lesson reanalysis');

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
    await page.locator('.nav-item[data-view="settings"]').click();
    await page.getByRole('button',{name:'Verificar atualizações'}).click();
    await page.getByText('Você já está na versão mais recente.').waitFor();
    await assertNoUiError('settings and updates');
    await page.screenshot({path:path.join(screenshots,`${prefix}settings-${width}.png`),fullPage:true});
    const dimensions=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth}));
    if(dimensions.scrollWidth>dimensions.viewport+2)throw Error(`Horizontal viewport overflow at ${width}: ${JSON.stringify(dimensions)}`);
    await page.close();
  }
  if(errors.length)throw Error('Browser errors:\n'+errors.join('\n'));
  console.log('PASS: two viewports, navigation, home, list filters, search, teacher consent, review, sources, updates, screenshots');
}finally{
  await browser.close();
}
