"""Fluxo principal automático com IA simulada; sem chamadas reais nem dados do usuário."""
from __future__ import annotations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from knowledge_bridge.ai import AIResult, FreeAIRouter, _completion
from knowledge_bridge.auto_ingest import AutoOrganizer, parse_link_rows, clean_visual_result
from knowledge_bridge.pipeline import Application


class FakeAI:
    attempts=0
    def __init__(self, image_lesson=1):
        self.attempts=0
        self.image_lesson=image_lesson
        self.visual=0
        self.texts=0
    def active(self):return ['gemini']
    def read_classroom_material(self, mime, binary, filename, hint=''):
        self.attempts+=1;self.visual+=1
        assert binary.startswith(b'PNG')
        return AIResult({'resumo':'Apresentação do curso 2026', 'conceitos':[],
            'aula':self.image_lesson,'titulo':'Apresentação dos Professores e Turma',
            'data':'02/03/2026','descricao':'Apresentação da metodologia e das duplas.',
            'pessoas':['Tiago Santini — professor','Alexandre Rech — professor'],
            'atividades':['Atividade de apresentação no board'],
            'videos':[],'links':[], 'incertezas':['Atividade planejada, sem comprovar execução']},
            'gemini','gemini-3.5-flash-lite')
    def analyze(self,text,context):
        self.attempts+=1;self.texts+=1
        self.last_context=context
        return AIResult({'resumo':'O professor apresentou sua trajetória.',
            'tipo_aula':'apresentacao', 'conceitos':[],
            'pessoas':[{'nome':'Tiago Santini','papel':'professor',
                        'informacao':'Apresentou sua trajetória','tempo':'0:10'}],
            'atividades':[], 'ferramentas':[], 'marcos':[],
            'exemplos':[], 'duvidas':[]},'gemini','gemini-3.5-flash-lite')
    def compare(self,*args):
        raise AssertionError('Sem código nesse caso')


class WithoutAI:
    attempts=0
    def active(self):return []
    def read_classroom_material(self,*args):raise AssertionError('Não deve chamar API')


class AutoIngestTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.input=self.root/'entrada';self.input.mkdir()
        self.vault=self.root/'vault'
        self.app=Application(self.vault,config=self.root/'missing.env',log=lambda _:None)
        self.addCleanup(self.app.close)

    def transcript(self,name='A01 - V01 - Apresentação Tiago Santini.txt'):
        path=self.input/name
        path.write_text('[0:10] Sou Tiago Santini, professor da Academia.\n[0:15] Sou ex-aluno da academia.',encoding='utf8')
        return path

    def image(self,name='Captura classroom.png'):
        path=self.input/name
        path.write_bytes(b'PNG-example-not-a-real-image')
        return path

    def test_one_click_transcript_and_print_creates_context_and_people(self):
        self.app.ai=FakeAI()
        result=AutoOrganizer(self.app).run([self.transcript(),self.image()], '',authorized=True)
        self.assertEqual(result['files'],2)
        self.assertEqual(result['visual_analyzed'],1)
        self.assertEqual(result['lessons'],['Aula-001'])
        self.assertEqual(result['calls'],2)
        self.assertEqual(result['pending'],[])
        self.assertTrue(result['processed'])
        self.assertTrue((self.vault/'02-Minhas-Aulas'/'Aula-001').is_dir())
        notes='\n'.join(p.read_text(encoding='utf8') for p in
                       (self.vault/'02-Minhas-Aulas'/'Aula-001').glob('*.md'))
        self.assertIn('Apresentação da metodologia',notes)
        self.assertIn('Tiago Santini',notes)
        self.assertIn('Extração por IA',notes)
        self.assertIn('## Resumo da aula',notes)
        # One-off extracted context does not qualify for a person profile.
        self.assertFalse(list(self.vault.glob('01-Meu-Conhecimento/Pessoas/*.md')))
        self.assertIn('Contexto do Classroom',self.app.ai.last_context)

    def test_same_files_second_time_use_cache_and_no_duplicate(self):
        ai=FakeAI();self.app.ai=ai
        transcript,image=self.transcript(),self.image()
        a=AutoOrganizer(self.app)
        a.run([transcript,image],'',authorized=True)
        result=a.run([transcript,image],'',authorized=True)
        self.assertEqual(result['files'],0)
        self.assertEqual(result['visual_analyzed'],0)
        self.assertEqual(ai.attempts,2)
        self.assertEqual(len(self.app.store.sources('classroom')),1)

    def test_conflicting_filename_and_image_lesson_is_pending(self):
        self.app.ai=FakeAI(image_lesson=2)
        result=AutoOrganizer(self.app).run([self.transcript(),self.image('A01 - print.png')], '',authorized=True)
        self.assertTrue(any('difere' in x for x in result['pending']))
        self.assertEqual(len(self.app.store.sources('classroom')),0)

    def test_no_gemini_still_keeps_files_and_pending(self):
        self.app.ai=WithoutAI()
        result=AutoOrganizer(self.app).run([self.image('print classroom.png')],'',authorized=True)
        self.assertEqual(result['files'],1)
        self.assertTrue(result['pending'])
        self.assertEqual(len(self.app.store.sources('classroom')),0)
        self.assertTrue((self.vault/'90-Sistema'/'TRAMA-Importacoes-Pendentes.json').exists())

    def test_one_bare_video_link_with_single_transcript_associates(self):
        self.app.ai=WithoutAI()
        result=AutoOrganizer(self.app).run([self.transcript()],
                   'https://drive.google.com/file/d/123/view',authorized=True)
        self.assertEqual(result['lessons'],['Aula-001'])
        self.assertEqual(len(self.app.store.sources('classroom')),1)
        notes='\n'.join(p.read_text(encoding='utf8') for p in
                       (self.vault/'02-Minhas-Aulas'/'Aula-001').glob('*.md'))
        self.assertIn('drive.google.com/file/d/123', notes)

    def test_multi_lesson_ambiguous_link_is_saved_as_pending(self):
        self.app.ai=WithoutAI()
        second=self.transcript('A02 - Instalação.txt')
        second.write_text('[0:06] Baixar .NET SDK',encoding='utf8')
        result=AutoOrganizer(self.app).run([self.transcript(),second],
                    'https://example.com/material',authorized=True)
        self.assertTrue(any('Link sem aula' in x for x in result['pending']))
        registry=json.loads((self.vault/'90-Sistema'/'TRAMA-Importacoes-Pendentes.json').read_text())
        self.assertEqual(len(registry),1)
        self.assertEqual(len(self.app.store.sources('classroom')),0)

    def test_image_can_create_lesson_without_transcript(self):
        self.app.ai=FakeAI()
        result=AutoOrganizer(self.app).run([self.image()],'',authorized=True)
        self.assertEqual(result['lessons'],['Aula-001'])
        self.assertTrue((self.vault/'02-Minhas-Aulas'/'Aula-001'/'00-contexto-aula-001.md').exists())
        self.assertEqual(self.app.ai.attempts,1)

    def test_edited_original_auto_note_is_never_overwritten(self):
        self.app.ai=FakeAI()
        file=self.image()
        AutoOrganizer(self.app).run([file],'',authorized=True)
        original=list((self.vault/'99-Anexos'/'Contexto-Classroom').glob('*auto*.json'))[0]
        original.write_text('{"manual":true}',encoding='utf8')
        # Explicit stored extraction changed to a new payload; rebuild must not touch user edit.
        data={'titulo':'Título revisado','descricao':'Outra descrição','pessoas':'','atividades':'',
              'links':'','videos':'','data':''}
        src=self.app.store.sources('material')[0]
        AutoOrganizer(self.app)._save_extracted(src,'Aula-001',data,reason=file.name)
        self.assertEqual(original.read_text(),'{"manual":true}')
        self.assertTrue(list(original.parent.glob('*.PROPOSTA*.md')))

    def test_permission_is_required(self):
        with self.assertRaises(ValueError):
            AutoOrganizer(self.app).run([self.transcript()], '',authorized=False)
        self.assertEqual(self.app.store.sources(),[])

    def test_links_validation_and_classroom_material(self):
        for value in ['http://example.com','https://user:pass@example.com/x',
                      'https://example.com/name with space']:
            with self.subTest(value=value),self.assertRaises(ValueError):parse_link_rows(value)
        rows=parse_link_rows('Aula 01 | https://drive.google.com/file/d/AAA/view\nhttps://github.com/acme/notes')
        self.assertEqual(rows[0]['lesson'],'Aula-001')
        self.assertTrue(rows[1]['repo'])

    def test_structured_visual_rejects_unjustified_video_urls(self):
        r=clean_visual_result({'aula':1,'resumo':'teste','data':'2026-02-03',
                'links':['javascript:alert(1)'],'videos':[{'url':'file:///etc/passwd'}]})
        self.assertEqual(r['links'],'')
        self.assertEqual(r['videos'],'')
        self.assertEqual(r['data'],'')

    def test_router_uses_gemini_image_inline_data_not_text_only(self):
        seen=[]
        def mock_send(url,body,headers,provider):
            seen.append((url,body,headers))
            return {'candidates':[{'content':{'parts':[{'text':json.dumps({'resumo':'ok','conceitos':[], 'aula':1})}]}}]}
        with patch('knowledge_bridge.ai._send',mock_send):
            output=_completion('gemini','gemini-3.5-flash-lite','SECRET','extraia',('image/png',b'IMG'))
        self.assertEqual(output['aula'],1)
        self.assertEqual(seen[0][1]['contents'][0]['parts'][1]['inline_data']['data'],'SU1H')
        self.assertEqual(seen[0][2]['x-goog-api-key'],'SECRET')


    def test_later_classroom_print_does_not_reprocess_old_lesson_without_user_action(self):
        ai=FakeAI();self.app.ai=ai
        a=AutoOrganizer(self.app)
        a.run([self.transcript()],'',authorized=True)
        self.assertEqual(ai.texts,1)
        a.run([self.image()],'',authorized=True)
        self.assertEqual(ai.texts,1)
        self.assertEqual(ai.visual,1)
        # Same context/transcript remains cached even when resent.
        a.run([self.transcript(),self.image()],'',authorized=True)
        self.assertEqual(ai.texts,1)
        # An explicit user-triggered processing is allowed to use the new
        # Classroom context and invalidate this lesson's digest only.
        self.app.process(lesson_filter='Aula-001')
        self.assertEqual(ai.texts,2)

    def test_github_link_is_given_to_repository_indexer(self):
        self.app.ai=WithoutAI()
        urls=[]
        def fake_add_repo(url):
            urls.append(url)
            return True
        self.app.add_repo=fake_add_repo
        r=AutoOrganizer(self.app).run([],'https://github.com/turma/projeto',authorized=True)
        self.assertEqual(r['repositories'],1)
        self.assertEqual(urls,['https://github.com/turma/projeto'])

    def test_image_with_one_lesson_without_gemini_is_linked_but_not_read(self):
        self.app.ai=WithoutAI()
        screenshot=self.image('Captura sem titulo.png')
        r=AutoOrganizer(self.app).run([self.transcript(),screenshot],'',authorized=True)
        self.assertTrue(any('não lida' in x for x in r['pending']))
        row=next(s for s in self.app.store.sources('material'))
        self.assertEqual(row['lesson'],'Aula-001')
        self.assertEqual(len(self.app.store.sources('classroom')),0)
