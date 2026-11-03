from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.ai import AIResult, FreeAIRouter, NoFreeProvider, ProviderError, _extract_json
from knowledge_bridge.content import chunks, guess_modules, lesson_identity, timed_lines
from knowledge_bridge.pipeline import Application

class TestParser(unittest.TestCase):
    def test_name(self):
        self.assertEqual(lesson_identity('A168-V02-Gravacao'),('Aula-168','V02'))
        self.assertEqual(lesson_identity('Aula 171 - apoio'),('Aula-171',None))

    def test_timestamps(self):
        text='Oi pessoal\n0:04\nVamos de Angular\n0:08\nUsar subscribe'
        self.assertEqual(timed_lines(text)[1], ('0:04','Vamos de Angular'))
        self.assertEqual(timed_lines('[0:09] outro exemplo'), [('0:09','outro exemplo')])

    def test_chunks(self):
        text='\n'.join(f'[0:{i:02}] Palavra {i}' for i in range(25))
        c=chunks(text,max_chars=75)
        self.assertGreater(len(c),1)
        self.assertIn('Palavra 24',c[-1])

    def test_json(self):
        self.assertEqual(_extract_json('```json\n{"resumo":"ok","conceitos":[]}\n```')['resumo'],'ok')

class TestSystem(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.home=Path(self.temp.name)
        self.inbox=self.home/'entrada'
        self.inbox.mkdir()
        self.vault=self.home/'Obsidian'
        self.cfg=self.home/'config.env'
        self.cfg.write_text('FREE_TIER_CONFIRMED=NO\n', encoding='utf-8')
        self.a=Application(self.vault,self.cfg,log=lambda x:None)

    def tearDown(self):
        self.a.close()
        self.temp.cleanup()

    def make_lesson(self):
        text='O professor apresentou Angular e RxJS\n0:04\nUsamos subscribe para acompanhar o processamento\n0:12\nA atualização era a cada cinco segundos'
        p=self.inbox/'Aula-168-V01.txt'
        p.write_text(text,encoding='utf-8')
        return p

    def test_import_dedupe_and_no_ai(self):
        self.make_lesson()
        self.assertEqual(self.a.scan(self.inbox),1)
        self.assertEqual(self.a.scan(self.inbox),0)
        self.assertEqual(len(self.a.store.sources('transcript')),1)
        self.a.process()
        self.assertEqual(self.a.stats().get('WAITING_FOR_PROVIDER'),1)
        dashboard=(self.vault/'00-Inicio/Dashboard.md').read_text(encoding='utf-8')
        self.assertIn('Aula-168-V01',dashboard)
        self.assertEqual(len(list((self.vault/'02-Minhas-Aulas').rglob('*.md'))),2)

    def test_ai_and_reimport(self):
        self.make_lesson()
        self.a.scan(self.inbox)
        payload={"resumo":"O professor mostrou atualização de status com RxJS.",
                 "conceitos":[{"nome":"RxJS","explicacao":"Assinatura de eventos", "tempo":"0:04"},
                             {"nome":"Inválido","explicacao":"Incerto", "tempo":"99:99"}],
                 "exemplos":[],"duvidas":[]}
        self.a.ai.active=lambda:['gemini']
        self.a.ai.analyze=lambda t,c:AIResult(payload,'gemini','gemini-3.5-flash-lite')
        self.a.process()
        self.assertEqual(self.a.stats().get('PUBLISHED'),1)
        self.assertIn('RxJS',(self.vault/'00-Inicio/MEU_CONTEXTO.md').read_text(encoding='utf-8'))
        lessons=list((self.vault/'02-Minhas-Aulas').rglob('*.md'))
        self.assertNotIn('99:99',lessons[0].read_text(encoding='utf-8'))
        # Reexecução não exige IA nem duplica dados
        self.a.ai.analyze=lambda t,c: (_ for _ in ()).throw(AssertionError('AI chamada duas vezes'))
        self.a.process()
        self.assertEqual(len(lessons),2)
        self.assertEqual(len(list((self.vault/'01-Meu-Conhecimento/Conceitos').glob('*.md'))),1)

    def test_video_is_linked_not_copied(self):
        self.make_lesson(); self.a.scan(self.inbox)
        video=self.inbox/'Aula-168-V01.mp4'
        video.write_bytes(b'conteudo video simulado')
        with self.assertRaisesRegex(ValueError, 'não armazena vídeos'):
            self.a.add_file(video)
        self.a.register_classroom({
            'aula': '168', 'titulo': 'RxJS e Angular',
            'videos': 'A168 - V01 - Aula RxJS | https://drive.google.com/file/d/example',
            'descricao': 'Aplicando o que aprendemos na API.'
        })
        note=next((self.vault/'02-Minhas-Aulas').rglob('*.md')).read_text(encoding='utf-8')
        self.assertIn('https://drive.google.com/file/d/example',note)
        self.assertIn('RxJS e Angular',note)
        self.assertEqual(list((self.vault/'99-Anexos/Videos').glob('*.mp4')),[])
        self.assertEqual(len(self.a.store.sources('video')),0)

    def test_user_edit_is_preserved(self):
        self.make_lesson();self.a.scan(self.inbox)
        note=next((self.vault/'02-Minhas-Aulas').rglob('*.md'))
        note.write_text('# MINHA EDICAO',encoding='utf-8')
        self.a.publisher.rebuild()
        self.assertEqual(note.read_text(encoding='utf-8'),'# MINHA EDICAO')
        self.assertTrue(list(note.parent.glob('*.PROPOSTA.md')))

    def test_new_content_invalidates_old_analysis(self):
        file=self.make_lesson()
        self.a.scan(self.inbox)
        self.a.ai.analyze=lambda t,c:AIResult({'resumo':'Resumo inicial','conceitos':[{'nome':'RxJS','explicacao':'interval','tempo':'0:04'}], 'exemplos':[], 'duvidas':[]}, 'gemini', 'gemini-3.5-flash-lite')
        self.a.process()
        file.write_text(file.read_text(encoding='utf-8')+'\n0:20\nNovo conteúdo sobre API',encoding='utf-8')
        self.a.scan(self.inbox)
        self.assertEqual(self.a.stats().get('READY'),1)
        note=next((self.vault/'02-Minhas-Aulas').rglob('*.md'))
        self.assertIn('Pendente:',note.read_text(encoding='utf-8'))
        self.assertNotIn('Resumo inicial',note.read_text(encoding='utf-8'))

    def test_different_lesson_same_content_retains_both_sources(self):
        # A copy of the same speech may represent two different published
        # lessons. Content de-duplication must not erase a lesson record.
        file=self.make_lesson()
        (self.inbox/'Aula-169-V01.txt').write_bytes(file.read_bytes())
        self.assertEqual(self.a.scan(self.inbox),2)
        self.assertEqual(len(self.a.store.sources('transcript')),2)
        self.assertEqual(len({r['stored_path'] for r in self.a.store.sources('transcript')}),1)

    def test_free_only(self):
        router=FreeAIRouter({'FREE_TIER_CONFIRMED':'NO','GEMINI_API_KEY':'sk-secret'})
        self.assertEqual(router.active(),[])
        with self.assertRaises(NoFreeProvider):
            router.analyze('aula','contexto')
        router=FreeAIRouter({'FREE_TIER_CONFIRMED':'YES','GEMINI_API_KEY':'key', 'MAX_REQUESTS_PER_RUN':'1'})
        with patch('knowledge_bridge.ai._completion',side_effect=ProviderError('gemini','cota',quota=True)):
            with self.assertRaises(NoFreeProvider):router.analyze('aula','contexto')
        self.assertEqual(router.active(),[])

if __name__=='__main__':
    unittest.main()

class TestSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.vault = self.base / "cofre"
        self.inbox = self.base / "aulas"
        self.inbox.mkdir()
        self.config = self.base / "config.env"
        self.config.write_text("FREE_TIER_CONFIRMED=NO\n", encoding="utf-8")
        self.app = Application(self.vault,self.config,log=lambda s:None)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_never_scan_obisidian_as_input(self):
        with self.assertRaises(ValueError):
            self.app.scan(self.base)

    def test_no_arbitrary_external_repo_hosts(self):
        with self.assertRaises(ValueError):
            self.app.add_repo("https://example.org/code/repo")
        with self.assertRaises(ValueError):
            self.app.add_repo("git@github.com:alguem/repo.git")

    def test_unknown_extensions_are_ignored(self):
        malicious = self.inbox / "aula.cmd"
        malicious.write_text("echo nao-execute",encoding="utf-8")
        self.assertFalse(self.app.add_file(malicious))
        self.assertEqual(len(self.app.store.sources()),0)

    def test_symlinks_are_rejected(self):
        original=self.inbox / "real.txt"
        original.write_text("Uma aula",encoding="utf-8")
        link=self.inbox / "atalho.txt"
        try:
            link.symlink_to(original)
        except (OSError,NotImplementedError):
            self.skipTest("SO não permite criar links simbólicos")
        with self.assertRaises(ValueError):
            self.app.add_file(link)

    def test_excessive_transcript_rejected(self):
        huge=self.inbox/"grande.txt"
        with huge.open("wb") as stream:
            stream.truncate(21*1024*1024)
        with self.assertRaises(ValueError):
            self.app.add_file(huge)

    def test_publishing_rejects_outside_vault(self):
        with self.assertRaises(ValueError):
            self.app.publisher.write("../nao.md", "nao escrever")

class TestAtomicAttachment(unittest.TestCase):
    def test_failed_copy_does_not_register_partial_attachment(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            input_file=root / "Aula-55-material.pdf"
            input_file.write_bytes(b"material de teste"*80)
            app=Application(root/"vault",root/"empty.env",log=lambda x:None)
            try:
                with patch("knowledge_bridge.publishing.shutil.copy2",side_effect=OSError("disco cheio")):
                    with self.assertRaises(OSError):
                        app.add_file(input_file)
                attachments=list((root/"vault"/"99-Anexos"/"Materiais-Originais").glob("*.pdf"))
                self.assertEqual(attachments,[])
                self.assertEqual(len(app.store.sources()),0)
            finally:
                app.close()
