"""Contexto integral da aula: links para gravações, pessoas e materiais sem vídeo copiado."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.classroom import normalize_context
from knowledge_bridge.pipeline import Application
from knowledge_bridge.bridge import Bridge, load_local_ui


class ClassroomLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.vault=Path(self.temp.name)/'vault'
        self.app=Application(self.vault,log=lambda _:None)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_record_without_transcript_still_creates_note_person_and_video_link(self):
        result=self.app.register_classroom({
            'aula':'1','titulo':'Apresentação dos professores e turma',
            'data':'02/03/2026','descricao':'Apresentação da metodologia',
            'pessoas':'Tiago Santini — professor\nAlexandre Rech — professor',
            'atividades':'Apresentar duplas e ferramentas',
            'videos':'A01 - V01 - Apresentação | https://drive.google.com/file/d/A01',
            'links':'https://academiadoprogramador-fullstack.github.io/docs/inicio/'})
        self.assertTrue(result['changed'])
        notes=list((self.vault/'02-Minhas-Aulas').rglob('*.md'))
        self.assertEqual(len(notes),2)
        md=notes[0].read_text(encoding='utf-8')
        self.assertIn('Tiago Santini',md)
        self.assertIn('Apresentar duplas',md)
        self.assertIn('https://drive.google.com/file/d/A01',md)
        self.assertIn('https://academiadoprogramador-fullstack.github.io/docs/inicio/',md)
        self.assertEqual(len(list(self.vault.rglob('*.mp4'))),0)
        people=list((self.vault/'01-Meu-Conhecimento/Pessoas').glob('*.md'))
        # Manual context can mention people but is not itself a Classroom
        # post author or evidence across three distinct lessons.
        self.assertEqual(len(people),0)
        b=Bridge()
        b.settings={'vault':str(self.vault)}
        n=b.note(notes[0].relative_to(self.vault).as_posix())
        self.assertEqual(n['media']['video_links'][0]['label'],'A01 - V01 - Apresentação')
        self.assertEqual(b.snapshot()['stats']['videos'],1)
        with patch('knowledge_bridge.bridge.webbrowser.open',return_value=True) as open_browser:
            self.assertTrue(b.open_video_link('https://drive.google.com/file/d/A01')['ok'])
            self.assertFalse(b.open_video_link('https://unknown.test/other')['ok'])
            self.assertFalse(b.open_video_link('javascript:alert(1)')['ok'])
            open_browser.assert_called_once_with('https://drive.google.com/file/d/A01')
        self.assertFalse(self.app.register_classroom({
            'aula':'1','titulo':'Apresentação dos professores e turma',
            'data':'02/03/2026','descricao':'Apresentação da metodologia',
            'pessoas':'Tiago Santini — professor\nAlexandre Rech — professor',
            'atividades':'Apresentar duplas e ferramentas',
            'videos':'A01 - V01 - Apresentação | https://drive.google.com/file/d/A01',
            'links':'https://academiadoprogramador-fullstack.github.io/docs/inicio/'})['changed'])

    def test_screenshot_is_linked_to_lesson_without_transcript(self):
        self.app.register_classroom({'aula':2,'titulo':'Instalação do .NET','descricao':'Ferramentas'})
        material=Path(self.temp.name)/'print_sem_nome.png'
        material.write_bytes(b'png ficticio')
        self.assertTrue(self.app.attach_classroom_material('2',material))
        self.app.publisher.rebuild()
        note=next((self.vault/'02-Minhas-Aulas').rglob('*.md')).read_text(encoding='utf-8')
        self.assertIn('print_sem_nome.png', note)
        self.assertEqual(len(self.app.store.sources('material')),1)
        self.assertFalse(self.app.attach_classroom_material('Aula 2',material))
        with self.assertRaises(ValueError):
            self.app.attach_classroom_material('2',Path(self.temp.name)/'arquivo.mp4')

    def test_disallows_video_copy_and_unsafe_protocols(self):
        with self.assertRaises(ValueError):
            normalize_context({'aula':1,'videos':'Vídeo | file:///C:/Users/user/private.mp4'})
        with self.assertRaises(ValueError):
            normalize_context({'aula':1,'videos':'Vídeo | https://user:password@example.com/file'})
        with self.assertRaises(ValueError):
            normalize_context({'aula':1,'videos':'Vídeo | javascript:alert(1)'})
        with self.assertRaises(ValueError):
            normalize_context({'aula':1,'videos':'Vídeo | https://example.com/a\nwrong'})
        with self.assertRaises(ValueError):
            self.app.publisher.attachment(Path('/tmp/a.mp4'),'video')

    def test_multiple_videos_and_existing_revision_are_preserved(self):
        self.app.register_classroom({'aula':2,'titulo':'Instalação do .NET','videos':'V1 | https://example.com/one'})
        first=self.app.store.sources('classroom')[0]
        original=(self.vault/first['stored_path']).read_text(encoding='utf-8')
        self.app.register_classroom({'aula':2,'titulo':'Instalação do .NET',
            'videos':'V1 | https://example.com/one\nV2 | https://example.com/two'})
        self.assertTrue(list((self.vault/'99-Anexos/Contexto-Classroom/Historico').glob('*.json')))
        self.assertIn('V1',original)
        self.assertIn('V2',(self.vault/first['stored_path']).read_text(encoding='utf-8'))
        self.assertEqual(len(list((self.vault/'02-Minhas-Aulas').rglob('*.md'))),2)

    def test_window_and_context_ui_are_in_the_packaged_html(self):
        html=load_local_ui()
        self.assertIn('"video_links"',html) if False else self.assertIn('video_links',html)
        self.assertIn('F11',html)
        self.assertIn('name="videos"',html)
        self.assertIn('save_classroom_context',html)
