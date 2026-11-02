"""Regression checks for styled controls while native Windows chrome stays available."""
from unittest import TestCase
from unittest.mock import Mock

from knowledge_bridge.bridge import Bridge, load_local_ui


class ClassicChromeV15Tests(TestCase):
    def test_exactly_one_group_of_window_controls_and_compact_branding(self):
        html = load_local_ui()
        # The single set of window controls is drawn by Windows itself.
        self.assertIn('class="toolbar-brand"', html)
        self.assertIn('class="toolbar-brand-name">TRAMA</span>', html)
        self.assertNotIn('class="win-controls"', html)
        for button_id in ('win-min', 'win-max', 'win-close'):
            self.assertNotIn(f'id="{button_id}"', html)
        self.assertNotIn("classic-controls-enabled", html)
        self.assertIn("event.key==='F11'", html)
        self.assertIn('TRAMA v2.0', html)

    def test_buttons_dispatch_to_native_window_without_exposing_window_to_js(self):
        bridge = Bridge()
        native = Mock()
        bridge._window = native
        self.assertTrue(bridge.window_action('minimize')['ok'])
        native.minimize.assert_called_once_with()
        self.assertTrue(bridge.window_action('maximize')['ok'])
        native.maximize.assert_called_once_with()
        self.assertTrue(bridge.window_action('maximize')['ok'])
        native.restore.assert_called_once_with()
        self.assertTrue(bridge.window_action('fullscreen')['ok'])
        native.toggle_fullscreen.assert_called_once_with()
        self.assertTrue(bridge.window_action('close')['ok'])
        native.destroy.assert_called_once_with()
        self.assertFalse(bridge.window_action('unsupported')['ok'])

    def test_native_maximize_and_restore_events_keep_button_in_sync(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from knowledge_bridge.bridge import start_webview

        class Hook:
            def __init__(self): self.listeners = []
            def __iadd__(self, listener):
                self.listeners.append(listener)
                return self
            def emit(self):
                for listener in self.listeners: listener()

        native = Mock()
        native.events = SimpleNamespace(maximized=Hook(), restored=Hook())
        renderer = Mock()
        renderer.create_window.return_value = native
        with patch.dict(sys.modules, {'webview': renderer}):
            start_webview()
        bridge = renderer.create_window.call_args.kwargs['js_api']._bridge
        native.events.maximized.emit()
        self.assertTrue(bridge._is_maximized)
        bridge.window_action('maximize')
        native.restore.assert_called_once_with()
        native.events.restored.emit()
        self.assertFalse(bridge._is_maximized)
        bridge.window_action('maximize')
        native.maximize.assert_called_once_with()
