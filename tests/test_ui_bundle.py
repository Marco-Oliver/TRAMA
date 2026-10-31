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
