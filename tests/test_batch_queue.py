"""Fila de importação: sem processar até confirmação explícita."""
from __future__ import annotations
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
import sys
from knowledge_bridge.bridge import Bridge, PublicApi
from knowledge_bridge.auto_ingest import AutoOrganizer, parse_link_rows
from knowledge_bridge.pipeline import Application

# PNG 1x1 válido, fornecido inline para não depender de recursos externos.
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO1M8K8AAAAASUVORK5CYII=')

class QueuedImportTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.vault=self.root/'vault';self.vault.mkdir()
        self.inputs=self.root/'inputs';self.inputs.mkdir()
        self.bridge=Bridge();self.bridge.settings={'vault':str(self.vault)}
        self.addCleanup(self.bridge.clear_staged)

    def _mock_dialog(self, paths):
        mock=Mock();mock.OPEN_DIALOG='open';self.bridge._window=Mock()
        self.bridge._window.create_file_dialog.return_value=[str(p) for p in paths]
        return patch.dict(sys.modules,{'webview':mock})

    def test_select_twice_then_remove_without_processing_or_writing_vault(self):
        a=self.inputs/'A01 - V01.txt';a.write_text('[0:02] Apresentação',encoding='utf8')
        b=self.inputs/'A01 - V02.txt';b.write_text('[0:03] Turma',encoding='utf8')
        with self._mock_dialog([a]):r=self.bridge.stage_files()
        self.assertEqual(len(r['items']),1)
        with self._mock_dialog([b]):r=self.bridge.stage_files()
        self.assertEqual(len(r['items']),2)
        with self._mock_dialog([a]):r=self.bridge.stage_files()
        self.assertEqual(len(r['items']),2)
        self.assertEqual(list(self.vault.rglob('*')),[])
        self.bridge.remove_staged(r['items'][0]['id'])
        self.assertEqual(len(self.bridge.staged_items()['items']),1)

    def test_clipboard_png_stages_without_network_and_deduplicates(self):
        encoded='data:image/png;base64,'+base64.b64encode(PNG).decode()
        first=self.bridge.stage_clipboard_image(encoded)
        self.assertEqual(len(first['items']),1)
        self.assertEqual(self.bridge.stage_clipboard_image(encoded)['added'] if 'added' in self.bridge.stage_clipboard_image(encoded) else 0,0)
        self.assertEqual(len(self.bridge.staged_items()['items']),1)
        self.assertEqual(list(self.vault.rglob('*')),[])
        self.assertFalse(self.bridge.stage_clipboard_image('data:text/html;base64,WA==')['ok'])
        self.assertFalse(self.bridge.stage_clipboard_image('data:image/png;base64,'+base64.b64encode(b'not-an-image').decode())['ok'])
        self.bridge.clear_staged()
        self.assertEqual(len(self.bridge.staged_items()['items']),0)

    def test_no_processing_without_explicit_consent(self):
        r=self.bridge.process_staged('https://example.com',False)
        self.assertFalse(r['ok'])
        self.assertEqual(list(self.vault.rglob('*')),[])

    def test_public_api_does_not_leak_paths_in_queue(self):
        path=self.inputs/'A01.txt';path.write_text('teste')
        with self._mock_dialog([path]):
            r=PublicApi(self.bridge).stage_files()
        self.assertEqual(r['items'][0]['name'],'A01.txt')
        self.assertNotIn(str(self.root),json.dumps(r))

    def test_process_queue_runs_single_organizer_call_and_clears(self):
        path=self.inputs/'A01 - V01.txt';path.write_text('[0:00] Introdução')
        with self._mock_dialog([path]):self.bridge.stage_files()
        app=Application(self.vault,config=self.root/'env-missing',log=lambda _:None)
        class FakeOrganizer:
            received=[]
            def __init__(self,_app):pass
            def run(self,paths,links,authorized):
                FakeOrganizer.received.append((paths,links,authorized))
                return {'files':1,'visual_analyzed':0,'lessons':['Aula-001'],
                        'repositories':0,'pending':[],'errors':[],'calls':0}
        with patch.object(self.bridge,'_make_application',return_value=app),patch('knowledge_bridge.auto_ingest.AutoOrganizer',FakeOrganizer):
            r=self.bridge.process_staged('https://example.com/material',True)
        self.assertTrue(r['ok'])
        self.assertEqual(len(FakeOrganizer.received),1)
        self.assertEqual(len(FakeOrganizer.received[0][0]), 1)
        self.assertTrue(FakeOrganizer.received[0][0][0].samefile(path))
        self.assertTrue(FakeOrganizer.received[0][2])
        self.assertEqual(self.bridge.staged_items()['items'],[])

class LessonGroupingTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.app=Application(self.root/'vault',config=self.root/'not-configured',log=lambda _:None)
        self.addCleanup(self.app.close)
        class NoAI:
            attempts=0
            def active(self):return []
        self.app.ai=NoAI()

    def test_three_videos_for_one_classroom_post_are_one_lesson(self):
        text='\n'.join(f'Aula 01 | V0{i} - Parte {i} | https://drive.google.com/file/d/{i}/view' for i in range(1,4))
        result=AutoOrganizer(self.app).run([],text,authorized=True)
        self.assertEqual(result['lessons'],['Aula-001'])
        sources=self.app.store.sources('classroom')
        self.assertEqual(len(sources),1)
        note=json.loads((self.app.store.vault/sources[0]['stored_path']).read_text(encoding='utf8'))
        self.assertEqual(len(note['videos']),3)
        self.assertEqual([x['titulo'] for x in note['videos']],['V01 - Parte 1','V02 - Parte 2','V03 - Parte 3'])
        next_link='Aula 01 | V04 - Parte 4 | https://drive.google.com/file/d/4/view'
        AutoOrganizer(self.app).run([],next_link,authorized=True)
        self.assertEqual(len(self.app.store.sources('classroom')),1)
        note=json.loads((self.app.store.vault/self.app.store.sources('classroom')[0]['stored_path']).read_text(encoding='utf8'))
        self.assertEqual(len(note['videos']),4)
        AutoOrganizer(self.app).run([],next_link,authorized=True)
        self.assertEqual(len(self.app.store.sources('classroom')),1)
        self.assertEqual(len(json.loads((self.app.store.vault/self.app.store.sources('classroom')[0]['stored_path']).read_text())['videos']),4)

    def test_explicit_aula_02_does_not_get_assumed_to_be_aula_01(self):
        text='\n'.join([
            'Aula 01 | V01 | https://drive.google.com/file/d/a/view',
            'Aula 02 | V01 | https://drive.google.com/file/d/b/view',
            'https://drive.google.com/file/d/unknown/view',
        ])
        result=AutoOrganizer(self.app).run([],text,authorized=True)
        self.assertEqual(result['lessons'],['Aula-001','Aula-002'])
        self.assertTrue(any('Link sem aula identificada' in msg for msg in result['pending']))
        self.assertEqual(len(self.app.store.sources('classroom')),2)
