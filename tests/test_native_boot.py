"""Prevent recursion when pywebview inspects the JS-exposed API."""
import inspect
from unittest import TestCase
from unittest.mock import Mock, patch
from knowledge_bridge.bridge import Bridge, PublicApi, start_webview

class NativeBootTests(TestCase):
    def test_exposed_api_only_contains_whitelisted_callables(self):
        bridge=Bridge()
        bridge._window=Mock()
        api=PublicApi(bridge)
        public={k:v for k,v in inspect.getmembers(api) if not k.startswith('_')}
        self.assertEqual(set(public), {
            'snapshot','vault_disk_usage','note','search_notes','graph','audit_note','organize_library','select_vault','backup_vault','restore_vault','import_materials','auto_import',
            'staged_items','stage_files','stage_clipboard_image','remove_staged','clear_staged','process_staged',
            'process','process_lesson','add_repo','toggle_favorite','reveal_note','copy_note_link','compare_proposal','open_note',
            'open_obsidian','open_attachment','open_video_link','open_code_link','window_action',
            'save_classroom_context','import_classroom_materials',
            'ai_status','set_ai_processing_consent','save_ai_key','remove_ai_key',
            'test_ai','open_ai_test_report','search_transcript','teacher_ask','teacher_reset','check_updates','open_update_page','prepare_update','launch_update'
        })
        self.assertTrue(all(callable(v) for v in public.values()))
        self.assertNotIn('window',public)
        self.assertNotIn('settings',public)

    def test_window_backend_stays_private_and_not_exposed_to_js(self):
        import sys
        mock_webview=Mock()
        mock_webview.create_window.return_value=Mock()
        with patch.dict(sys.modules,{'webview':mock_webview}):
            start_webview()
        kwargs=mock_webview.create_window.call_args.kwargs
        self.assertIs(kwargs['frameless'],False)
        self.assertIs(kwargs['resizable'],True)
        self.assertIs(kwargs['easy_drag'],False)
        self.assertGreaterEqual(kwargs['min_size'][0],800)
        api=kwargs['js_api']
        self.assertIsInstance(api,PublicApi)
        self.assertIs(api._bridge._window,mock_webview.create_window.return_value)
        self.assertIsNone(getattr(api, 'window', None))
        mock_webview.start.assert_called_once_with(debug=False)

class LauncherTests(TestCase):
    def test_no_gui_self_test_is_offline(self):
        from trama_launcher import smoke_test
        smoke_test()

    def test_packaging_files_are_present(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for file in ('TRAMA.spec', 'TRAMA_Instalador.iss', 'GERAR_APP_WINDOWS.bat',
                     'trama_launcher.py', 'assets/trama.ico', 'knowledge_bridge/ui/index.html'):
            self.assertTrue((root/file).is_file(), file)
