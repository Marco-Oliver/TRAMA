import tempfile
import unittest
from pathlib import Path
from knowledge_bridge.vault_index import VaultIndex
from knowledge_bridge.gui import TramaDesktop


class TestVaultIndex(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.vault=Path(self.tmp.name)
        (self.vault/'01-Meu-Conhecimento').mkdir()
        (self.vault/'02-Minhas-Aulas').mkdir()
        (self.vault/'03-Meus-Projetos').mkdir()
        (self.vault/'01-Meu-Conhecimento'/'POO.md').write_text(
            '# POO\n\nAula: [[Aula 12]] e projeto [[Projeto API]].',encoding='utf-8')
        (self.vault/'02-Minhas-Aulas'/'Aula 12.md').write_text(
            "---\ntipo: 'aula'\n---\n# Aula 12\n\nAprendemos [[POO]].",encoding='utf-8')
        (self.vault/'03-Meus-Projetos'/'Projeto API.md').write_text(
            '# Projeto API\n',encoding='utf-8')
        (self.vault/'01-Meu-Conhecimento'/'Sem links.md').write_text(
            '# Sozinha\n',encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_graph_has_real_links_only(self):
        idx=VaultIndex(self.vault)
        nodes,edges=idx.graph()
        self.assertEqual(len(nodes),4)
        self.assertEqual(len(edges),2)
        selected=idx.resolve('POO|Explicação')
        self.assertEqual(selected.title,'POO')
        self.assertEqual(len(idx.related(selected)),2)
        self.assertEqual(idx.resolve('../outside'),None)

    def test_filters_and_metadata(self):
        idx=VaultIndex(self.vault)
        self.assertEqual(len(idx.filter('aulas')),1)
        self.assertEqual(len(idx.filter('projetos')),1)
        note=idx.filter('aulas')[0]
        self.assertEqual(note.metadata['tipo'],'aula')
        self.assertEqual(idx.filter('biblioteca','sozinha')[0].title,'Sozinha')

    def test_graph_layout_deterministic(self):
        idx=VaultIndex(self.vault)
        notes,edges=idx.graph()
        points=TramaDesktop._layout_graph(notes,edges)
        self.assertEqual(len(points),len(notes))
        self.assertTrue(all(-1.2 < x < 1.2 and -1.2 < y < 1.2 for x,y in points))
        self.assertEqual(points,TramaDesktop._layout_graph(notes,edges))

    def test_symlinks_are_excluded(self):
        file=self.vault/'outside.md'
        external=Path(self.tmp.name).parent/'trama-outside-untrusted.md'
        external.write_text('xx',encoding='utf-8')
        try:
            file.symlink_to(external)
        except (OSError,NotImplementedError):
            self.skipTest('Plataforma sem symlink')
        try:
            idx=VaultIndex(self.vault)
            self.assertNotIn('outside.md',[n.relative for n in idx.notes])
        finally:
            external.unlink(missing_ok=True)


if __name__=='__main__':unittest.main()
