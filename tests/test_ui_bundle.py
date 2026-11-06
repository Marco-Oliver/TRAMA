"""The shipped desktop window must render the same offline styles as the preview."""
import unittest
from knowledge_bridge.bridge import load_local_ui

class InterfaceBundleTests(unittest.TestCase):
    def test_classic_theme_is_included_in_packaged_window(self):
        html=load_local_ui()
        self.assertIn('Roboto Condensed',html)
        self.assertIn('Biblioteca do Obsidian',html)
        self.assertIn('data:image/png;base64,',html)
        self.assertIn('lib-folder-row',html)
        self.assertNotIn('<link rel="stylesheet"',html)
        self.assertNotIn('<script src=',html)
        self.assertNotIn('@import ',html)

    def test_packaged_window_keeps_hash_allowlisted_content_security_policy(self):
        import base64
        import hashlib
        import re
        from html import unescape
        html=load_local_ui()
        match=re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"',html)
        self.assertIsNotNone(match)
        policy=unescape(match.group(1))
        self.assertIn("default-src 'none'",policy)
        self.assertIn("script-src 'sha256-",policy)
        self.assertIn("style-src 'sha256-",policy)
        self.assertNotIn("'unsafe-inline'",policy)
        self.assertNotIn("'unsafe-eval'",policy)
        for tag in ("script","style"):
            for source in re.findall(rf'<{tag}>(.*?)</{tag}>', html, flags=re.S):
                digest=base64.b64encode(hashlib.sha256(source.encode('utf-8')).digest()).decode('ascii')
                self.assertIn("'sha256-"+digest+"'",policy)
        self.assertIn("connect-src 'none'",policy)

    def test_graph_assets_are_inlined_and_hash_allowed(self):
        import base64
        import hashlib
        import re
        from pathlib import Path
        html=load_local_ui()
        ui=Path(__file__).resolve().parents[1]/'knowledge_bridge'/'ui'
        policy=re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"',html).group(1)
        for name,tag in (('graph.js','script'),('graph.css','style')):
            source=(ui/name).read_text(encoding='utf-8')
            self.assertIn('<'+tag+'>'+source+'</'+tag+'>',html)
            checksum=base64.b64encode(hashlib.sha256(source.encode('utf-8')).digest()).decode('ascii')
            self.assertIn("'sha256-"+checksum+"'",policy)
        self.assertIn('TramaGraph.mount',html)
        self.assertIn('canvas',html)
        self.assertNotIn('<script src=',html)
        self.assertNotIn('<link rel="stylesheet"',html)

    def test_batch_dialog_does_not_process_during_file_selection(self):
        html=load_local_ui()
        self.assertIn('id="auto-paste-zone"',html)
        self.assertIn('id="auto-queue"',html)
        self.assertIn('Processar tudo',html)
        self.assertNotIn('auto-only-links',html)
        self.assertIn("call('stage_files')",html)
        self.assertIn("call('process_staged'",html)
        self.assertIn('pasteAutoImage',html)

    def test_ui_is_not_loading_remote_scripts_or_fonts(self):
        html=load_local_ui()
        self.assertNotIn('https://fonts.',html)
        self.assertNotIn('<iframe',html)

if __name__=='__main__':unittest.main()
