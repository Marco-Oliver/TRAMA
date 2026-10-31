"""End-to-end tests for the three linked layers with a two-author Git history."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.ai import AIResult, FreeAIRouter, NoFreeProvider
from knowledge_bridge.code_intel import (concept_from_text, index_repository,
                                         match_lesson_to_repository, potential_transcript_corrections,
                                         redact_sensitive)
from knowledge_bridge.pipeline import Application
from knowledge_bridge.secure_keys import KeyVault


class LinkedKnowledgeTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which('git'):
            self.skipTest('git not installed')
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.vault=self.base/'cofre'
        self.repo=self.base/'codigo'
        self.repo.mkdir()
        self.inbox=self.base/'entrada'
        self.inbox.mkdir()
        self.transcript=self.inbox/'Aula-168-V01.txt'
        self.transcript.write_text('''Ok, hoje usamos o exustrix no RXJS.\n0:04\nO exustrix faz com que não tenha chamadas em paralelo.\n0:25\nA gente já tinha aprendido subscribe. Hoje estamos usando para atualizar o status.\n''',encoding='utf-8')
        self._git('init','-q')
        (self.repo/'src').mkdir()
        (self.repo/'docs').mkdir()
        (self.repo/'src'/'certificados.ts').write_text('''import { interval } from 'rxjs';
import { exhaustMap, takeUntilDestroyed } from 'rxjs/operators';
class Certificados {
  atualizar() {
    interval(5000).pipe(exhaustMap(() => this.service.obterStatus())).subscribe();
  }
}
''',encoding='utf-8')
        (self.repo/'docs'/'frontend.md').write_text('# Módulo frontend\nAtualização assíncrona de status de certificados com RxJS.\n',encoding='utf-8')
        self._git('add','.')
        self._commit('Aluno A','a@example.com','primeira implementação')
        (self.repo/'src'/'certificados.ts').write_text((self.repo/'src'/'certificados.ts').read_text(encoding='utf-8')+'\n// revisão em dupla\n',encoding='utf-8')
        self._git('add','.')
        self._commit('Aluno B','b@example.com','refatoração no componente')
        self.config=self.base/'config.env'
        self.config.write_text('FREE_TIER_CONFIRMED=NO\n',encoding='utf-8')
        self.app=Application(self.vault,self.config,log=lambda _s:None)

    def tearDown(self):
        if hasattr(self,'app'):self.app.close()
        if hasattr(self,'tmp'):self.tmp.cleanup()

    def _git(self,*args):
        return subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,text=True,check=True)

    def _commit(self,name,email,msg):
        self._git('-c',f'user.name={name}','-c',f'user.email={email}',
                  '-c','commit.gpgsign=false','commit','-qm',msg)

    def test_incremental_three_layers_and_shared_authorship(self):
        self.app.add_file(self.transcript)
        self.app.publisher.rebuild()
        self.assertEqual(self.app.add_repo(str(self.repo)),True)
        repo=json.loads(self.app.store.repositories()[0]['payload'])
        self.assertTrue(repo['collaboration'])
        self.assertEqual(len(repo['history']),2)
        self.assertTrue(repo['documentation'])
        self.assertTrue(any(x['concept']=='exhaustMap' for x in repo['evidence']))
        lesson=next(p for p in (self.vault/'02-Minhas-Aulas').rglob('*.md') if p.name!='00-Visao-geral.md')
        initial=lesson.read_text(encoding='utf-8')
        self.assertIn('Relações com códigos e projetos',initial)
        self.assertIn('Hipótese',initial.title())
        project=next((self.vault/'03-Meus-Projetos').rglob('*.md')).read_text(encoding='utf-8')
        self.assertIn('```typescript',project)
        self.assertIn('src/certificados.ts',project)
        self.assertIn('Aluno A',project)
        self.assertIn('Aluno B',project)
        self.assertIn('não inferir autoria individual',project)
        self.assertIn('docs/frontend.md',project)
        self.assertIn('MEU_CONTEXTO',(self.vault/'00-Inicio/Dashboard.md').read_text(encoding='utf-8'))
        self.assertIn('Evolução: antes na aula, agora no código',(self.vault/'00-Inicio/MEU_CONTEXTO.md').read_text(encoding='utf-8'))
        self.assertEqual(self.app.add_repo(str(self.repo)),False)
        self.assertEqual(len(self.app.store.repositories()),1)

    def test_ai_cross_references_are_validated_and_cached(self):
        self.app.add_file(self.transcript)
        self.app.add_repo(str(self.repo))
        payload={'resumo':'Explicou como atualizar certificados via RxJS',
                 'conceitos':[{'nome':'exhaustMap','explicacao':'Evita consultas concorrentes','tempo':'0:04'}],
                 'exemplos':[], 'duvidas':['transcrição diz exustrix']}
        times=[]
        def summary(text,context):
            times.append('summary')
            return AIResult(payload,'gemini','gemini-3.5-flash-lite')
        def compare(transcript,evidence,context):
            times.append('compare')
            e=next(x for x in evidence if x['concept']=='exhaustMap')
            valid={'conceito':'exhaustMap','tempo':'0:04','path':e['path'],'line':e['line'],
                   'explicacao':'Operador usado no fluxo','evolucao':'Foi explicado em aula e aparece no código'}
            return AIResult({'resumo':'Ligação proposta', 'conceitos':[],
                'relacoes':[valid,dict(valid,line=9999)],
                'correcoes':[{'ouvido':'exustrix','sugestao':'exhaustMap','tempo':'0:04',
                             'path':e['path'],'line':e['line'],'justificativa':'operador existe no arquivo'},
                            {'ouvido':'algo inventado','sugestao':'x','tempo':'0:04','path':e['path'],'line':e['line']}],
                'novidades':[{'conceito':'interval','tempo':'88:88','explicacao':'usou atualização periódica'}]},
                'gemini','gemini-3.5-flash-lite')
        self.app.ai.analyze=summary
        self.app.ai.compare=compare
        self.app.process()
        self.assertEqual(times.count('summary'),1)
        self.assertEqual(times.count('compare'),1)
        r=self.app.store.repositories()[0]
        s=self.app.store.sources('transcript')[0]
        linked=self.app.store.connection(s['id'],s['digest'],r['url'],r['sha'])
        self.assertEqual(len(linked['relacoes']),1)
        self.assertEqual(len(linked['correcoes']),1)
        self.assertEqual(linked['novidades'][0]['tempo'],'')
        text=next(p for p in (self.vault/'02-Minhas-Aulas').rglob('*.md') if p.name!='00-Visao-geral.md').read_text(encoding='utf-8')
        self.assertIn('Comparação revisada por IA',text)
        self.assertIn('exustrix',text)
        self.assertIn('revisão humana necessária',text)
        self.app.process()
        self.assertEqual(times.count('compare'),1)
        self.assertEqual(times.count('summary'),1)

    def test_fallback_from_rate_limited_free_gemini_to_free_groq(self):
        from knowledge_bridge.ai import ProviderError
        router=FreeAIRouter({'FREE_TIER_CONFIRMED':'YES',
            'FREE_PROVIDER_ORDER':'gemini,groq,openrouter','GEMINI_API_KEY':'free-key-1',
            'GROQ_API_KEY':'free-key-2','OPENROUTER_API_KEY':'free-key-3','MAX_REQUESTS_PER_RUN':'3'})
        seen=[]
        def fake(provider,model,key,prompt):
            seen.append((provider,model))
            if provider=='gemini':raise ProviderError('gemini','429',quota=True)
            return {'resumo':'feito na Groq Free','conceitos':[]}
        with patch('knowledge_bridge.ai._completion',side_effect=fake):
            result=router.analyze('Conteúdo','contexto')
        self.assertEqual(result.provider,'groq')
        self.assertEqual(seen,[('gemini','gemini-3.5-flash-lite'),('groq','openai/gpt-oss-20b')])
        self.assertNotIn('gemini',router.active())

    def test_free_limited_calls_never_use_paid_fallback(self):
        router=FreeAIRouter({'FREE_TIER_CONFIRMED':'YES','FREE_PROVIDER_ORDER':'gemini',
                             'GEMINI_API_KEY':'fake','MAX_REQUESTS_PER_RUN':'1'})
        def fake_completion(provider,model,key,prompt):
            self.assertEqual(provider,'gemini')
            self.assertEqual(model,'gemini-3.5-flash-lite')
            return {'resumo':'ok','conceitos':[]}
        with patch('knowledge_bridge.ai._completion',side_effect=fake_completion) as fn:
            router.analyze('teste','aula')
            with self.assertRaises(Exception):router.analyze('teste','aula')
            self.assertEqual(fn.call_count,1)
        router=FreeAIRouter({'FREE_TIER_CONFIRMED':'NO','GEMINI_API_KEY':'fake'})
        with self.assertRaises(NoFreeProvider):router.compare('text',[],'project')


class SourceSafetyTests(unittest.TestCase):
    def test_mask_tokens_and_password_before_exposing_code(self):
        text='api_key = "top_secret_password_124"\nkey = "teste"\nsk-12345678901234567890123456789'
        safe=redact_sensitive(text)
        self.assertNotIn('top_secret_password_124',safe)
        self.assertNotIn('sk-123456',safe)

    def test_keys_are_not_saved_in_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys=KeyVault(Path(tmp)/'keys.json')
            with patch('knowledge_bridge.secure_keys._crypt',side_effect=lambda b,enc: b[::-1]):
                keys.save('gemini','sensitive-key-123456')
                self.assertNotIn('sensitive-key',keys.path.read_text(encoding='utf-8'))
                self.assertEqual(keys.get_env()['GEMINI_API_KEY'],'sensitive-key-123456')
                keys.remove('gemini')
                self.assertFalse(keys.configured()['gemini'])

    def test_evidence_not_attributed_automatically(self):
        self.assertIn('exhaustMap',concept_from_text('o professor fala exustrix'))
        empty={'evidence':[]}
        self.assertEqual(match_lesson_to_repository('exustrix',None,empty),[])
        self.assertEqual(potential_transcript_corrections('exustrix',empty),[])

if __name__=='__main__':unittest.main()
