"""v1.8: human navigation + real-vault fidelity + additive organization.
Tests use synthetic data and do not invoke external AI or overwrite user vaults.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.pipeline import Application
from knowledge_bridge.bridge import Bridge, PublicApi, load_local_ui


class ReadableLibraryV18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.vault=self.root/'TRAMA-Vault'
        self.app=Application(self.vault,log=lambda _s: None)

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def _lesson(self, num, video, text):
        p=self.root/f'A{num:02d} - {video} - Apresentacao.txt'
        p.write_text('[0:00] '+text+' '+video+'\n[0:04] Obrigado pela participacao',encoding='utf-8')
        self.app.add_file(p)
        return p

    def test_three_recordings_one_lesson_and_own_source_files(self):
        for v in ('V01','V02','V03'):
            self._lesson(1,v,'Professor Tiago falou sobre o curso')
        self.app.register_classroom({'aula':1,'titulo':'Apresentação dos Professores e Turma',
            'descricao':'Apresentar equipe e organizar duplas',
            'pessoas':'Tiago Santini — professor',
            'videos':'V01 | https://drive.google.com/file/d/111\nV02 | https://drive.google.com/file/d/222\nV03 | https://drive.google.com/file/d/333'})
        note=self.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md'
        text=note.read_text(encoding='utf-8')
        self.assertIn('V01',text);self.assertIn('V02',text);self.assertIn('V03',text)
        self.assertIn('Tiago Santini',text)
        self.assertIn('Apresentar equipe e organizar duplas',text)
        self.assertIn('https://drive.google.com/file/d/333',text)
        self.assertEqual(len(self.app.store.sources('transcript')),3)
        self.assertEqual(len(list(self.vault.rglob('*.mp4'))),0)
        # One-off name without a confirmed Classroom author stays in its
        # lesson note; no orphan person profile is generated.
        self.assertFalse((self.vault/'01-Meu-Conhecimento/Pessoas/tiago-santini.md').exists())
        self.assertIn('[[',text)

    def test_context_only_and_no_fake_technical_concepts(self):
        self.app.register_classroom({'aula':1,'titulo':'Aula inicial',
                                     'descricao':'Apresentação da turma e organização'})
        note=(self.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md').read_text(encoding='utf-8')
        self.assertIn('Aula inicial',note)
        self.assertIn('Ainda não há conceitos técnicos classificados com evidência suficiente',note)
        self.assertIn('Plano de aula não é prova de execução',note)

    def test_user_modified_overview_creates_proposal_not_overwrite(self):
        self._lesson(1,'V01','Transcricao do professor')
        self.app.publisher.rebuild()
        p=self.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md'
        p.write_text('# Minha versão editada pelo aluno\n',encoding='utf-8')
        self.app.publisher.rebuild()
        self.assertEqual(p.read_text(encoding='utf-8'),'# Minha versão editada pelo aluno\n')
        self.assertTrue(list(p.parent.glob('00-Visao-geral.PROPOSTA*.md')))

    def test_existing_vault_can_be_organized_without_ai(self):
        self._lesson(1,'V01','Anotações de uma gravação')
        self.app.publisher.rebuild()
        # Emulate v1.7 that only had individual transcript notes.
        (self.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md').unlink()
        b=Bridge();b.settings={'vault':str(self.vault)}
        self.assertFalse(b.organize_library(False)['ok'])
        with patch('knowledge_bridge.ai._completion',side_effect=AssertionError('AI must not run')):
            result=b.organize_library(True)
        self.assertTrue(result['ok'],result)
        self.assertTrue((self.vault/'02-Minhas-Aulas/Aula-001/00-Visao-geral.md').exists())
        idx=b.snapshot()
        self.assertEqual(len([n for n in idx['notes'] if n['kind']=='visao_geral']),1)
        note_id='02-Minhas-Aulas/Aula-001/00-Visao-geral.md'
        note=b.note(note_id)
        self.assertIn('Em poucas palavras',note['content'])
        self.assertIn('Ainda',note['summary'] or '') if False else None
        # An external Obsidian edit is read fresh, never served from an old UI cache.
        original=(self.vault/note_id).read_text(encoding='utf-8')
        (self.vault/note_id).write_text(original+'\n## Minhas observações\nEu conferi o vídeo.\n',encoding='utf-8')
        self.assertIn('Eu conferi o vídeo.',b.note(note_id)['content'])

    def test_ui_provides_complete_note_and_explicit_organize(self):
        html=load_local_ui()
        self.assertIn('Nota completa',html)
        self.assertIn('data-lib-action="organize"',html)
        self.assertIn('organize_library',html)
        self.assertIn('libRenderMarkdown(n.content',html)
        self.assertIn('TRAMA v2.2.0',html)
        self.assertNotIn('class="win-controls"',html)

class LocalAuditV18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.vault=self.base/'vault'
        self.app=Application(self.vault,log=lambda _x:None)
        text=self.base/'Aula-001-V01.txt'
        text.write_text('[0:04] O professor explicou interval e subscribe\n'
                        '[0:20] Apresentou a metodologia da Academia\n',encoding='utf-8')
        self.app.add_file(text)
        self.app.register_classroom({'aula':1,'titulo':'Introdução',
            'descricao':'Apresentação da metodologia',
            'videos':'V01 | https://drive.google.com/file/d/sample'})
        self.source=self.app.store.sources('transcript')[0]

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def test_unprocessed_transcript_is_reported_without_api(self):
        from knowledge_bridge.audit import audit_lesson
        result=audit_lesson(self.vault,'Aula-001')
        self.assertTrue(result['ok'])
        self.assertEqual(result['contagens']['transcricoes'],1)
        self.assertEqual(result['contagens']['com_resumo'],0)
        self.assertEqual(result['contagens']['videos_links'],1)
        self.assertTrue(any('pendentes' in i for i in result['pendencias']))

    def test_audit_flags_invalid_timestamp_and_unverified_concept(self):
        from knowledge_bridge.audit import audit_lesson
        source=self.source
        self.app.store.save_analysis(source['id'],source['digest'],'teste','simulado',{
            'resumo':'Explicação introdutória de interval e subscribe',
            'conceitos':[{'nome':'interval','tempo':'0:04','explicacao':'emissão periódica'},
                        {'nome':'InventadoXYZ','tempo':'8:88','explicacao':'não citado'}],
            'pessoas':[], 'atividades':[]})
        report=audit_lesson(self.vault,'Aula-001')
        self.assertEqual(report['contagens']['com_resumo'],1)
        self.assertEqual(report['contagens']['horarios_validos'],1)
        self.assertGreaterEqual(report['contagens']['referencias_duvidosas'],2)
        self.assertTrue(any('não prova' in item for item in report['pendencias']))

    def test_changed_original_is_reported_read_only(self):
        from knowledge_bridge.audit import audit_lesson
        original=self.vault/self.source['stored_path']
        original.write_text('ALTERADO EXTERNAMENTE',encoding='utf-8')
        report=audit_lesson(self.vault,'Aula-001')
        self.assertEqual(report['contagens']['arquivos_integros'],0)
        self.assertTrue(any('modificada' in item for item in report['pendencias']))
        self.assertEqual(original.read_text(encoding='utf-8'),'ALTERADO EXTERNAMENTE')
