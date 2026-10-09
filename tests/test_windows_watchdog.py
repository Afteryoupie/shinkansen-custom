import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_tray', ROOT / 'windows/llm_tray.py')
tray = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tray)


class IconTests(unittest.TestCase):
    def test_request_lifecycle_and_disconnect(self):
        self.assertEqual(tray.icon_state(dict(status='running', active_requests=0)), 'ready')
        self.assertEqual(tray.icon_state(dict(status='running', active_requests=1)), 'running')
        self.assertEqual(tray.icon_state(dict(status='running', active_requests=0)), 'ready')
        self.assertEqual(tray.icon_state(dict(status='sleeping', active_requests=1)), 'sleeping')
        self.assertEqual(tray.icon_state(dict(status='starting', active_requests=1)), 'starting')
        self.assertEqual(tray.icon_state(None), 'offline')

    def test_refresh_updates_expression_without_backend_status_change(self):
        with patch.object(tray, 'RightClickIcon'), patch.object(tray, 'make_icon', side_effect=lambda s: s):
            app = tray.LLMTray()
            app.backend_pid = 123
            for count, expected in [(0, 'ready'), (1, 'running'), (0, 'ready')]:
                with patch.object(tray, 'request', return_value=dict(status='running', active_requests=count)):
                    app._refresh()
                self.assertEqual(app._tray.icon, expected)
            with patch.object(tray, 'request', side_effect=OSError('offline')):
                app._refresh()
            self.assertEqual(app._tray.icon, 'offline')


class CountdownTests(unittest.TestCase):
    def test_states_and_deadline(self):
        running = dict(status='running', idle_timeout=180, auto_sleep_enabled=True)
        self.assertEqual(tray.presentation(running, 200, 80)[1], '02:00')
        self.assertEqual(tray.presentation(running, 200, 81)[1], '01:59')
        self.assertEqual(tray.presentation(running, 200, 201)[1], '00:00')
        self.assertEqual(tray.presentation(dict(running, active_requests=1), 200, 80)[1], '推論中')
        self.assertEqual(tray.presentation(dict(running, auto_sleep_enabled=False), 200, 80)[1], '常駐')
        self.assertEqual(tray.presentation(dict(running, status='starting'), 200, 80)[1], '載入中…')
        self.assertEqual(tray.presentation(dict(running, status='sleeping'), 200, 80)[1], '待命')
        self.assertEqual(tray.presentation(None, 200, 80)[0], '未連線')


class MenuTests(unittest.TestCase):
    def setUp(self):
        # Model the Windows dialog API when running these menu tests on macOS.
        self.win_api_patch = patch('ctypes.windll', Mock(), create=True) if sys.platform != 'win32' else None
        if self.win_api_patch:
            self.win_api_patch.start()
        self.icon_patch = patch.object(tray, 'RightClickIcon')
        self.icon_patch.start()
        self.app = tray.LLMTray()
        self.app.data = dict(status='running', current_model='Test model', current_model_id='model',
                             idle_timeout=180, idle_remaining=90, auto_sleep_enabled=True,
                             models=[dict(id='model', name='Test model'), dict(id='other', name='Other model')])

    def tearDown(self):
        self.app._close()
        self.icon_patch.stop()
        if self.win_api_patch:
            self.win_api_patch.stop()

    def item(self, text):
        return next(item for item in self.app._items() if item.text == text)

    def test_native_menu_and_model_selection(self):
        with patch.object(self.app, 'action') as action:
            self.item('立即休眠')(self.app._tray)
            action.assert_called_with('sleep', '模型休眠')
            models = list(self.item('Test model').submenu.items)[2:]
            self.assertTrue(models[0].checked)
            self.assertFalse(models[0].enabled)
            models[1](self.app._tray)
            action.assert_called_with('switch?model=other', '切換模型')
        self.assertFalse(hasattr(self.app, 'root'))

    def test_decision_menu_uses_independent_lifecycle(self):
        self.app.data['decision'] = dict(status='sleeping', models=[dict(id='laya-multilingual')],
                                        runtime_available=True, auto_sleep_enabled=True)
        menu = self.item('決策模型 · Laya multilingual').submenu
        wake = next(item for item in menu.items if item.text == '啟動決策模型')
        self.assertTrue(wake.enabled)
        with patch.object(self.app, 'action') as action:
            wake(self.app._tray)
            action.assert_called_with('decision/wake', '決策模型操作')
        self.app.data['decision'].update(status='running', active_requests=1)
        menu = self.item('決策模型 · Laya multilingual').submenu
        sleep = next(item for item in menu.items if item.text == '決策模型休眠')
        self.assertFalse(sleep.enabled)

    def test_compact_model_keeps_original_selection_id(self):
        name = 'Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M'
        self.app.data['models'] = [dict(id=name, name=name)]
        self.app.data['current_model'] = name
        item = self.item(tray.compact_name(name))
        self.assertTrue(item.text.startswith('Qwen3VL-8B-Unc'))
        self.assertTrue(item.text.endswith(name[-10:]))
        model = list(item.submenu.items)[2]
        with patch.object(self.app, 'action') as action:
            model(self.app._tray)
            self.assertIn(name, action.call_args.args[0])
        self.assertEqual(self.app._items()[0].text, item.submenu.items[0].text)

    def test_startup_and_busy_disable_controls(self):
        self.app.busy = True
        self.assertFalse(self.item('正在處理…').enabled)
        self.assertFalse(self.item('Test model').enabled)
        self.app.busy = False
        self.app.data['status'] = 'starting'
        self.assertFalse(self.item('模型載入中…').enabled)
        self.app.data['status'] = 'sleeping'
        self.assertTrue(self.item('啟動模型').enabled)

    def test_connection_failure_keeps_reconnection(self):
        with patch.object(tray, 'request', side_effect=OSError('offline')):
            self.app._refresh()
        self.assertIsNone(self.app.data)
        self.assertTrue(self.item('重新整理狀態').enabled)
        self.assertFalse(self.item('啟動模型').enabled)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires the actual Windows clipboard and PowerShell')
    def test_clipboard_contains_api_url(self):
        self.app._copy()
        import subprocess
        import os
        executable = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        copied = subprocess.check_output([executable, '-NoProfile', '-Command', 'Get-Clipboard'], text=True).strip()
        self.assertEqual(copied, tray.API_BASE + '/v1')



    def test_busy_menu_keeps_exit_available(self):
        self.app.busy = True
        self.assertTrue(self.item('退出 LLM watchdog…').enabled)
        self.app.quitting = True
        self.assertFalse(self.item('退出 LLM watchdog…').enabled)

    def test_confirmed_exit_bypasses_busy_and_foregrounds_dialog(self):
        self.app.busy = True
        with patch('ctypes.windll.user32.MessageBoxW', return_value=6) as dialog, patch.object(self.app, 'action') as action:
            self.app._quit()
        action.assert_called_once_with('stop', '結束 LLM watchdog')
        flags = dialog.call_args.args[-1]
        self.assertTrue(flags & 0x10000)
        self.assertTrue(flags & 0x40000)

    def test_cancel_does_not_stop_service(self):
        with patch('ctypes.windll.user32.MessageBoxW', return_value=7), patch.object(self.app, 'action') as action:
            self.app._quit()
        action.assert_not_called()
        self.assertFalse(self.app.closed.is_set())

    def test_offline_tray_without_backend_can_close(self):
        self.app.data = None
        with patch('ctypes.windll.user32.MessageBoxW', return_value=6):
            self.app._quit()
        self.assertTrue(self.app.closed.is_set())

    def test_stop_action_runs_during_another_operation(self):
        self.app.busy = True
        def inline_worker(*, target, **kwargs):
            worker = Mock()
            worker.start.side_effect = target
            return worker
        with patch.object(tray.threading, 'Thread', side_effect=inline_worker), patch.object(tray, 'request', return_value={'status': 'stopped'}) as request:
            self.app.action('stop', '結束 LLM watchdog')
        request.assert_called_once_with('/api/stop', 'POST', timeout=10)
        self.assertTrue(self.app.closed.is_set())

    def test_lost_stop_response_after_backend_exit_closes_tray(self):
        def inline_worker(*, target, **kwargs):
            worker = Mock()
            worker.start.side_effect = target
            return worker
        with patch.object(tray.threading, 'Thread', side_effect=inline_worker), patch.object(tray, 'request', side_effect=OSError('connection closed')), patch.object(self.app, '_backend_exited', return_value=True):
            self.app.action('stop', '結束 LLM watchdog')
        self.assertTrue(self.app.closed.is_set())

    def test_failed_stop_keeps_retry_available(self):
        def inline_worker(*, target, **kwargs):
            worker = Mock()
            worker.start.side_effect = target
            return worker
        with patch.object(tray.threading, 'Thread', side_effect=inline_worker), patch.object(tray, 'request', side_effect=TimeoutError('timeout')), patch.object(self.app, '_backend_exited', return_value=False):
            self.app.action('stop', '結束 LLM watchdog')
        self.assertFalse(self.app.closed.is_set())
        self.assertFalse(self.app.quitting)
        self.assertTrue(self.item('退出 LLM watchdog…').enabled)

if __name__ == '__main__':
    unittest.main()
