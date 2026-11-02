"""Security regression: bridge filesystem scope, URLs, ZIP portability and secrets."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.bridge import Bridge
from knowledge_bridge.pipeline import Application
from knowledge_bridge.recovery import DB_FILE, MANIFEST, restore_backup
from knowledge_bridge.update_service import check_release


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=Application(self.root/'vault', self.root/'no-config.env', log=lambda *_: None)
        self.addCleanup(self.app.close)
        self.vault=self.app.store.vault
        self.bridge=Bridge()
        self.bridge.settings={'vault':str(self.vault)}
    
    def test_attachment_must_be_registered_and_not_a_private_note(self):
        sensitive=self.vault/'not-authorized.txt'
        sensitive.write_text('private, not in catalog',encoding='utf-8')
        with patch("subprocess.Popen") as spawn, patch(
                "knowledge_bridge.bridge.os.startfile",create=True) as start:
            self.assertFalse(self.bridge.open_attachment('not-authorized.txt')['ok'])
            self.assertFalse(self.bridge.open_attachment('99-Anexos/../not-authorized.txt')['ok'])
            self.assertFalse(self.bridge.open_attachment('..\\not-authorized.txt')['ok'])
            spawn.assert_not_called()
            start.assert_not_called()
        original=self.root/'Aula-001-V01.txt'
        original.write_text('[0:03] Hello World em C#',encoding='utf-8')
        self.app.add_file(original)
        stored=self.app.store.sources('transcript')[0]['stored_path']
        with patch("subprocess.Popen") as spawn, patch(
                "knowledge_bridge.bridge.os.startfile",create=True) as start:
            self.assertTrue(self.bridge.open_attachment(stored)['ok'])
            (start if sys.platform=='win32' else spawn).assert_called_once()

    def test_update_release_link_must_have_exact_tag(self):
        with patch.object(self.bridge,'_release_repo',return_value='Marco-Oliver/TRAMA'), \
             patch('knowledge_bridge.bridge.webbrowser.open') as opener:
            for value in (
                'https://github.com/Marco-Oliver/TRAMA/releases/latest',
                'https://github.com/Marco-Oliver/TRAMA/releases/tag/v2.1.0?next=foo',
                'https://github.com/Marco-Oliver/TRAMA/releases/../elsewhere',
                'https://github.com/Marco-Oliver/TRAMA/releases/tag/v2.1.0#evil',
                'https://evil.test/Marco-Oliver/TRAMA/releases/tag/v2.1.0',
                'javascript:alert(1)',
            ):
                with self.subTest(value=value):
                    self.assertFalse(self.bridge.open_update_page(value)['ok'])
            opener.assert_not_called()
            official='https://github.com/Marco-Oliver/TRAMA/releases/tag/v2.1.0'
            self.assertTrue(self.bridge.open_update_page(official)['ok'])
            opener.assert_called_once_with(official)

    def test_malformed_links_do_not_crash_browser_bridge(self):
        for value in ('https://[bad', 'https://example.org:bad/', 'https://a.com/\u0000evil',
                      'file:///C:/private', 'http://user:pass@example.com/'):
            with self.subTest(value=value):
                self.assertFalse(self.bridge._valid_video_url(value))
        self.assertTrue(self.bridge._valid_video_url('https://drive.google.com/file/d/xyz/view'))

    def test_release_metadata_rejects_path_masquerade(self):
        class Fake:
            def __init__(self, obj):
                self.obj=obj
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n=0):return json.dumps(self.obj).encode('utf-8')
        official='Marco-Oliver/TRAMA'
        release={'tag_name':'v99.0.0',
                 'html_url':f'https://github.com/{official}/releases/tag/v99.0.0',
                 'assets':[{'name':'TRAMA_Setup.exe'}]}
        with patch('knowledge_bridge.update_service.urllib.request.urlopen',
                   return_value=Fake({**release,'html_url':release['html_url']+'?bad=1'})):
            self.assertFalse(check_release(official)['ok'])
        with patch('knowledge_bridge.update_service.urllib.request.urlopen',
                   return_value=Fake(release)):
            self.assertTrue(check_release(official)['available'])

    def test_restorer_rejects_windows_devices_and_trailing_aliases(self):
        with tempfile.TemporaryDirectory(dir=self.root) as scratch:
            source=Path(scratch)/'original.sqlite3'
            with closing(sqlite3.connect(source)) as conn:
                conn.execute('CREATE TABLE IF NOT EXISTS check_me (value INTEGER)')
                conn.commit()
            db=source.read_bytes()
            for i,name in enumerate(('CON.txt','folder/NUL.md','AUX','file.','trailing ',
                                     'COM1.txt','notes/LPT9.jpg')):
                with self.subTest(name=name):
                    archive=self.root/f'bad-{i}.zip'
                    bad=b'attack'
                    items={DB_FILE:db,name:bad}
                    manifest={'format':1,'files':{p:{
                        'size':len(blob),'sha256':hashlib.sha256(blob).hexdigest()}
                        for p,blob in items.items()}}
                    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as out:
                        for p,blob in items.items():out.writestr(p,blob)
                        out.writestr(MANIFEST,json.dumps(manifest))
                    destination=self.root/f'restored-{i}'
                    with self.assertRaisesRegex(ValueError,'Caminho inseguro'):
                        restore_backup(archive,destination)
                    self.assertFalse(destination.exists())

if __name__=='__main__':
    unittest.main()
