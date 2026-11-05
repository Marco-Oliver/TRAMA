"""Regression checks for native WebView to Obsidian read-only bridge."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from knowledge_bridge.bridge import Bridge
from knowledge_bridge.pipeline import Application

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.vault=self.base/'Minha Biblioteca'
        self.vault.mkdir()
        folder=self.vault/'02-Minhas-Aulas'
        folder.mkdir()
        (folder/'Aula 168.md').write_text(
            "---\ntipo: 'aula'\naula: 'Aula-168'\n---\n# Aula 168\n\n## Resumo da aula\nO professor explicou [[POO]].\n",encoding='utf-8')
        know=self.vault/'01-Meu-Conhecimento';know.mkdir()
        (know/'POO.md').write_text('# POO\n',encoding='utf-8')
        self.bridge=Bridge()
        self.bridge.settings={'vault':str(self.vault)}

    def tearDown(self):self.temp.cleanup()

    def test_snapshot_and_notes_refer_to_original_vault(self):
        result=self.bridge.snapshot()
        self.assertTrue(result['connected'])
        self.assertEqual(result['stats']['notes'],2)
        selected=self.bridge.note('02-Minhas-Aulas/Aula 168.md')
        self.assertIn('O professor explicou',selected['summary'])
        self.assertEqual(selected['lesson'],'Aula-168')
        self.assertEqual(len(selected['related']),1)

    def test_paths_and_remote_actions_fail_closed(self):
        self.assertIn('error',self.bridge.note('../secrets.md'))
        self.assertIn('error',self.bridge.note('C:/Windows/system.ini'))
        self.assertFalse(self.bridge.open_attachment('../any.py')['ok'])
        self.assertFalse(self.bridge.open_attachment('01-Meu-Conhecimento/POO.md/../../../../evil.exe')['ok'])
        self.assertFalse(self.bridge.process(confirmed=False)['ok'])
        self.assertFalse(self.bridge.add_repo('https://evil.test/example')['ok'])

    def test_favorite_requires_real_note_and_persists_in_settings(self):
        with patch.object(self.bridge, '_save') as save:
            fail=self.bridge.toggle_favorite('../wrong.md')
            self.assertFalse(fail['ok'])
            self.assertEqual(save.call_count,0)
            note='01-Meu-Conhecimento/POO.md'
            first=self.bridge.toggle_favorite(note)
            self.assertTrue(first['ok'])
            self.assertIn(note,self.bridge.snapshot()['favorites'])
            second=self.bridge.toggle_favorite(note)
            self.assertTrue(second['ok'])
            self.assertNotIn(note,second['favorites'])

    def test_process_failure_does_not_leave_application_locked(self):
        with patch.object(self.bridge,'_make_application',
                          side_effect=RuntimeError('token=private-error-value')):
            response=self.bridge.process(True)
        self.assertFalse(response['ok'])
        self.assertNotIn('private-error-value',response['message'])
        self.assertFalse(self.bridge._write_lock.locked())

    def test_repository_init_failure_does_not_leave_application_locked(self):
        with patch('knowledge_bridge.bridge.Application',
                   side_effect=RuntimeError('password=private-error-value')):
            response=self.bridge.add_repo('https://github.com/example/public')
        self.assertFalse(response['ok'])
        self.assertNotIn('private-error-value',response['message'])
        self.assertFalse(self.bridge._write_lock.locked())

    def test_graph_has_real_connections(self):
        result=self.bridge.graph()
        self.assertEqual(len(result['nodes']),2)
        self.assertEqual(len(result['edges']),1)

    def test_graph_provides_kinds_without_changing_notes(self):
        overview=self.vault/'02-Minhas-Aulas'/'Aula-131'
        overview.mkdir()
        (overview/'00-Visao-geral.md').write_text(
            '---\ntipo: visao_geral\n---\n# Aula 131\n\n[[POO]]\n',
            encoding='utf-8')
        (overview/'A131-V01.md').write_text(
            '---\ntipo: aula\n---\n# Gravação 01\n\n[[POO]]\n',
            encoding='utf-8')
        (overview/'Duvida.md').write_text(
            '---\ntipo: duvida\n---\n# Dúvida\n\n[[POO]]\n',
            encoding='utf-8')
        projects=self.vault/'03-Meus-Projetos'
        projects.mkdir()
        (projects/'App.md').write_text('# Aplicativo\n',encoding='utf-8')
        index=self.vault/'Minha-Biblioteca.md'
        index.write_text('# Minha Biblioteca\n',encoding='utf-8')
        result=self.bridge.graph()
        types={item['id']:item['kind'] for item in result['nodes']}
        self.assertEqual(types['01-Meu-Conhecimento/POO.md'],'conceito')
        self.assertEqual(types['02-Minhas-Aulas/Aula 168.md'],'aula')
        self.assertEqual(types['02-Minhas-Aulas/Aula-131/00-Visao-geral.md'],'indice')
        self.assertEqual(types['02-Minhas-Aulas/Aula-131/A131-V01.md'],'aula')
        self.assertEqual(types['02-Minhas-Aulas/Aula-131/Duvida.md'],'duvida')
        self.assertEqual(types['03-Meus-Projetos/App.md'],'projeto')
        self.assertEqual(types['Minha-Biblioteca.md'],'indice')
        self.assertTrue(all(item['kind'] for item in result['nodes']))
        self.assertEqual(self.bridge.graph()['edges'],result['edges'])

    def test_reading_does_not_change_notes(self):
        file=self.vault/'02-Minhas-Aulas'/'Aula 168.md'
        original=file.read_bytes()
        self.bridge.snapshot();self.bridge.note('02-Minhas-Aulas/Aula 168.md');self.bridge.graph()
        self.assertEqual(file.read_bytes(),original)

if __name__=='__main__':unittest.main()

class ClassicWindowTests(unittest.TestCase):
    def test_window_controls_are_limited_to_known_actions(self):
        from unittest.mock import Mock
        bridge=Bridge()
        bridge._window=Mock()
        self.assertEqual(bridge.window_action('execute'),{'ok':False})
        bridge._window.assert_not_called()
        self.assertTrue(bridge.window_action('minimize')['ok'])
        bridge._window.minimize.assert_called_once()
        self.assertTrue(bridge.window_action('maximize')['ok'])
        bridge._window.maximize.assert_called_once()
        self.assertTrue(bridge.window_action('maximize')['ok'])
        bridge._window.restore.assert_called_once()
        self.assertTrue(bridge.window_action('close')['ok'])
        bridge._window.destroy.assert_called_once()

    def test_tags_from_frontmatter_and_content(self):
        with tempfile.TemporaryDirectory() as folder:
            vault=Path(folder)
            (vault/'POO.md').write_text('---\ntags: [csharp, curso]\n---\n# POO\nUma nota com #orientacao/objetos\n',encoding='utf-8')
            bridge=Bridge()
            bridge.settings={'vault':str(vault)}
            note=bridge.note('POO.md')
            self.assertEqual(note['tags'],['csharp','curso','orientacao/objetos'])
