"""Live-diagnostic behavior tested fully offline with fake model responses."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.ai import FreeAIRouter, ProviderError
from knowledge_bridge.bridge import Bridge
from knowledge_bridge.diagnostic import (
    MissingTestSources, _read_real_sources, format_diagnostic_report,
    run_ai_diagnostic, SAMPLE_TRANSCRIPT,
)
from knowledge_bridge.store import Store


class AIDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    @staticmethod
    def fake_provider(provider, model, key, prompt):
        assert provider == 'gemini'
        assert model == 'gemini-3.5-flash-lite'
        assert key == 'my-secret-do-not-echo'
        if 'EVIDÊNCIAS DE CÓDIGO' not in prompt:
            return {'resumo':'O professor explicou interval e exhaustMap.',
                    'conceitos':[{'nome':'interval','tempo':'00:05','explicacao':'emite periodicamente'}],
                    'duvidas':[], 'exemplos':[]}
        return {'resumo':'Relação entre aula e código', 'conceitos': [],
                'relacoes':[{'conceito':'exhaustMap','tempo':'04:08',
                             'path':'exemplo/polling.ts','line':9,
                             'explicacao':'Controla requisições concorrentes',
                             'evolucao':'Antes estudou interval, agora aplicou polling'},
                            {'conceito':'inventado','tempo':'99:99',
                             'path':'inventado.txt','line':999,
                             'explicacao':'falsa','evolucao':'falsa'}],
                'correcoes':[{'ouvido':'exaust map','sugestao':'exhaustMap','tempo':'03:05',
                             'path':'exemplo/polling.ts','line':9,'justificativa':'código sugere'}],
                'novidades':[]}

    def test_demo_is_two_calls_and_disposes_of_invalid_references(self):
        router=FreeAIRouter({'GEMINI_API_KEY':'my-secret-do-not-echo',
                             'FREE_PROVIDER_ORDER':'gemini',
                             'FREE_TIER_CONFIRMED':'YES', 'MAX_REQUESTS_PER_RUN':'2'})
        with patch('knowledge_bridge.ai._completion',side_effect=self.fake_provider) as completion:
            result=run_ai_diagnostic(router,'demo')
        self.assertEqual(completion.call_count,2)
        self.assertEqual(result['requests'],2)
        self.assertEqual(len(result['relations']),1)
        self.assertEqual(result['invalid_references_discarded'],1)
        self.assertEqual(result['suggested_corrections'][0]['review'],'HIPÓTESE — revisão humana necessária')
        report=format_diagnostic_report(result)
        self.assertNotIn('my-secret-do-not-echo',report)
        self.assertNotIn('http.get',report)
        self.assertIn('revisão humana',report.lower())

    def test_real_sources_read_only_and_matched(self):
        vault=self.base/'vault'
        with TempStore(vault) as store:
            (vault/'transcricoes').mkdir()
            (vault/'transcricoes'/'Aula-168.txt').write_text(SAMPLE_TRANSCRIPT,encoding='utf-8')
            store.conn.execute("""INSERT INTO sources(id,original_path,kind,digest,label,lesson,video,stored_path,status)
            VALUES('1','origin','transcript','abc','Aula 168','Aula-168','','transcricoes/Aula-168.txt','READY')""")
            store.save_repo('https://github.com/exemplo/test','Exemplo','sha',{
                'evidence':[{'path':'src/a.ts','line':3,'concept':'exhaustMap','snippet':'3: exhaustMap(() => getStatus())'}]
            },'STORED')
            store.conn.commit()
        before=(vault/'transcricoes'/'Aula-168.txt').read_bytes()
        # A sqlite3.Connection used as a context manager commits/rolls back,
        # but DOES NOT close the handle. This locks estado.sqlite3 on Windows.
        real_connect = sqlite3.connect
        open_handles = []
        def tracked_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            open_handles.append(conn)
            return conn
        with patch('knowledge_bridge.diagnostic.sqlite3.connect', side_effect=tracked_connect):
            transcript,evidence,repo=_read_real_sources(vault)
        self.assertEqual(len(open_handles), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            open_handles[0].execute('SELECT 1')  # Must already be closed.
        self.assertIn('interval',transcript)
        self.assertEqual(evidence[0]['path'],'src/a.ts')
        self.assertEqual(before,(vault/'transcricoes'/'Aula-168.txt').read_bytes())

    def test_real_sources_close_db_even_when_query_fails(self):
        vault = self.base / 'broken_vault'
        db = vault / '.base-conhecimento' / 'estado.sqlite3'
        db.parent.mkdir(parents=True)
        # Intentionally malformed SQLite schema, query must fail and close handle.
        with sqlite3.connect(db) as setup:
            setup.execute('CREATE TABLE irrelevant(x INT)')
        setup.close()
        real_connect = sqlite3.connect
        handles = []
        def tracked_connect(*args, **kwargs):
            c = real_connect(*args, **kwargs)
            handles.append(c)
            return c
        with patch('knowledge_bridge.diagnostic.sqlite3.connect', side_effect=tracked_connect):
            with self.assertRaises(MissingTestSources):
                _read_real_sources(vault)
        self.assertEqual(len(handles), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            handles[0].execute('SELECT 1')

    def test_ui_stats_closes_readonly_database(self):
        vault = self.base / 'stats_vault'
        with TempStore(vault) as store:
            store.conn.execute("""INSERT INTO sources(id,original_path,kind,digest,label,status)
                VALUES('one','test','transcript','hash','Aula','READY')""")
            store.conn.commit()
        real_connect = sqlite3.connect
        handles = []
        def tracked_connect(*args, **kwargs):
            c = real_connect(*args, **kwargs)
            handles.append(c)
            return c
        with patch('knowledge_bridge.bridge.sqlite3.connect', side_effect=tracked_connect):
            result = Bridge()._stats(vault)
        self.assertEqual(result['transcriptions'], 1)
        self.assertEqual(len(handles), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            handles[0].execute('SELECT 1')

    def test_real_requires_imported_sources(self):
        with self.assertRaises(MissingTestSources):
            _read_real_sources(self.base)

    def test_bridge_requires_consent_and_secret_without_exposing_token(self):
        bridge=Bridge()
        bridge.settings={'confirmed_free':True}
        bridge._key_vault.get_env=lambda:{'GEMINI_API_KEY':'my-secret-do-not-echo'}
        with patch('knowledge_bridge.ai._completion',side_effect=self.fake_provider) as completion, \
             patch('knowledge_bridge.bridge.DATA_HOME',self.base):
            self.assertFalse(bridge.test_ai('gemini','demo',False)['ok'])
            self.assertEqual(completion.call_count,0)
            response=bridge.test_ai('gemini','demo',True)
        self.assertTrue(response['ok'],response)
        self.assertTrue((self.base/'diagnosticos'/'RELATORIO_TESTE_IA.txt').is_file())
        self.assertNotIn('my-secret-do-not-echo',json.dumps(response))
        self.assertEqual(completion.call_count,2)

    def test_failed_remote_request_does_not_echo_key(self):
        bridge=Bridge()
        bridge.settings={'confirmed_free':True}
        bridge._key_vault.get_env=lambda:{'GEMINI_API_KEY':'my-secret-do-not-echo'}
        with patch('knowledge_bridge.ai._completion',side_effect=ProviderError('gemini','limite gratuito atingido (429)',True)):
            response=bridge.test_ai('gemini','demo',True)
        self.assertFalse(response['ok'])
        self.assertIn('429',response['message'])
        self.assertNotIn('my-secret-do-not-echo',json.dumps(response))


class TempStore:
    def __init__(self,vault):self.store=Store(vault)
    def __enter__(self):return self.store
    def __exit__(self,*args):self.store.close()


if __name__=='__main__':unittest.main()
