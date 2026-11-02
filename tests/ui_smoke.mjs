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
   updated:'2026-10-28T15:00:00',content:'# Hello World em C#\n\nO professor explicou **Console.WriteLine** para escrever uma mensagem no terminal.\n\n## Código\n\n```csharp\nConsole.WriteLine("Olá!");\n```\n\n[[01-Meu-Conhecimento/Conceitos/console|Console]]'},
  {id:'02-Minhas-Aulas/Aula-025/00-Visao-geral.md', title:'Angular — componentes',lesson:'Aula-025',
   section:'02-Minhas-Aulas',kind:'visao_geral',state:'resumida_com_ia',
   updated:'2026-10-30T18:00:00',content:'# Angular — componentes\n\nUm componente Angular organiza a interface.'},
  {id:'01-Meu-Conhecimento/Conceitos/console.md',title:'Console',section:'01-Meu-Conhecimento',
   kind:'conceito',state:'resumida_com_ia', updated:'2026-10-27T13:00:00',
   content:'# Console\n\nConceito de saída usado nos exemplos C#.'},
];
const baseNote = n=>({...n,media:{video:[],video_links:[],transcript:[],materials:[]},related:[]});
const makeBridge=({notes})=>{window.__TRAMA_API__=({
  snapshot: async()=>({connected:true,vault:'C:\\TRAMA-Teste\\Cofre',notes,stats:{notes:3,videos:2,transcriptions:2,materials:0,repositories:1},favorites:[notes[0].id]}),
  note: async id=>{const n=notes.find(n=>n.id===id);return n?baseNote(n):{error:'Nota não encontrada'};},
  graph: async()=>({nodes:notes,edges:[[0,2]]}),
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
    await page.locator('.nav-item[data-view="home"]').click();
    await page.getByRole('button',{name:'Conectar meu cofre'}).waitFor();
    await page.screenshot({path:path.join(screenshots,`${prefix}home-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Ver minhas aulas'}).click();
    await page.locator('.lesson-row').first().waitFor();
    await page.locator('[data-list-filter="favorites"]').click();
    if(await page.locator('.lesson-row').count()!==1)throw Error('Favorites filter did not work');
    await page.locator('[data-list-filter="recent"]').click();
    if(await page.locator('.lesson-row').count()!==2)throw Error('Recent filter did not work');
    await page.locator('[data-list-filter="all"]').click();
    await page.screenshot({path:path.join(screenshots,`${prefix}lessons-${width}.png`),fullPage:true});
    await page.locator('#search-all').fill('Angular');
    await page.locator('#btn-search-all').click();
    await page.locator('#library-workspace').waitFor({state:'visible'});
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
    await page.locator('.nav-item[data-view="settings"]').click();
    await page.getByRole('button',{name:'Verificar atualizações'}).click();
    await page.getByText('Você já está na versão mais recente.').waitFor();
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
