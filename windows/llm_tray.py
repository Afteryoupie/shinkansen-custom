"""Windows native right-click tray for LLM watchdog."""
import json
import math
import threading
import time
from pathlib import Path
import urllib.request
import urllib.parse
import webbrowser

from PIL import Image
import pystray

API_BASE = 'http://127.0.0.1:8080'
# A constant, non-interactive header anchors the width of both native menus.
MENU_CAPTION = 'LLM watchdog' + '\u2007' * 28

PAPER, INK, ACCENT = '#F5F3EC', '#242620', '#BF421F'


def compact_name(text, head=14, tail=10):
    return text if len(text) <= head + tail + 1 else text[:head] + '…' + text[-tail:]


def compact_line(text, limit=28):
    # Chinese characters take approximately two Latin character columns.
    import unicodedata
    width = 0
    for index, char in enumerate(text):
        width += 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        if width > limit:
            return text[:index] + '…'
    return text


def request(path, method='GET', timeout=3):
    req = urllib.request.Request(API_BASE + path, method=method,
                                 data=b'' if method == 'POST' else None)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def presentation(data, deadline, now):
    """Derive the visible status from a monotonic backend deadline."""
    if not data:
        return '未連線', '—', '請確認 LLM watchdog 已啟動', 0
    status = data.get('status')
    if status == 'starting':
        return '載入中', '載入中…', '模型就緒後開始計時', 0
    if status != 'running':
        return '休眠待命', '待命', '下一次請求會自動喚醒', 0
    if data.get('active_requests', 0):
        return '運行就緒', '推論中', '完成請求後重新開始倒數', 0
    timeout = data.get('idle_timeout', 0)
    if not data.get('auto_sleep_enabled', True) or timeout <= 0:
        return '運行就緒', '常駐', '自動休眠已關閉或此模型保持常駐', 0
    remaining = max(0, math.ceil(deadline - now))
    return ('運行就緒', f'{remaining // 60:02d}:{remaining % 60:02d}',
            '後自動休眠 · 新請求會重設倒數' if remaining else '等待服務進入休眠',
            min(1, remaining / timeout))


def make_icon(status):
    state = status if status in ('running', 'sleeping', 'starting') else 'offline'
    path = Path(__file__).resolve().parents[1] / 'watchdog/assets' / f'watchdog-{state}.png'
    with Image.open(path) as source:
        image = source.convert('RGBA')
    return image.resize((64, 64), Image.Resampling.LANCZOS)

class RightClickIcon(pystray.Icon):
    def _on_notify(self, wparam, lparam):
        # pystray's Windows backend caches the native menu. Refresh immediately
        # before opening it, never destroy/rebuild a menu under the pointer.
        if lparam == 0x0205:  # WM_RBUTTONUP
            self.update_menu()
        return super()._on_notify(wparam, lparam)


class LLMTray:
    def __init__(self):
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.data = None
        self.deadline = 0
        self.busy = False
        self.quitting = False
        self.feedback = ''
        self.backend_pid = None
        self._tray = RightClickIcon('llm_watchdog', make_icon('offline'), 'LLM watchdog',
                                    menu=pystray.Menu(lambda: iter(self._items())))

    def _items(self):
        with self.lock:
            data = dict(self.data) if self.data else {}
            state, countdown, detail, _ = presentation(self.data, self.deadline, time.monotonic())
            busy, feedback, quitting = self.busy, self.feedback, self.quitting
        enabled = bool(data) and not busy and data.get('status') != 'starting'
        running = data.get('status') == 'running'
        model_id = data.get('current_model_id')
        model_items = [pystray.MenuItem(MENU_CAPTION, None, enabled=False), pystray.Menu.SEPARATOR]
        for model in data.get('models', []):
            selected = model['id'] == model_id
            path = 'switch?model=' + urllib.parse.quote(model['id'], safe='')
            model_items.append(pystray.MenuItem(compact_name(model['name']), self._handler(path, '切換模型'),
                checked=lambda _, chosen=selected: chosen,
                enabled=enabled and not (selected and running)))
        if not data.get('models'):
            model_items.append(pystray.MenuItem('尚無可用模型', None, enabled=False))
        items = [
            pystray.MenuItem(MENU_CAPTION, None, enabled=False),
            pystray.MenuItem(state, None, enabled=False),
            pystray.MenuItem('休眠倒數：' + countdown, None, enabled=False),
            pystray.MenuItem(compact_line(detail), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(compact_name(data.get('current_model', '選擇模型')), pystray.Menu(*model_items), enabled=enabled),
            pystray.MenuItem('正在處理…' if busy else '模型載入中…' if data.get('status') == 'starting' else '立即休眠' if running else '啟動模型',
                            self._handler('sleep' if running else 'wake', '模型休眠' if running else '啟動模型'), enabled=enabled),
            pystray.MenuItem('閒置時自動休眠', self._handler('toggle_auto_sleep', '更新休眠策略'),
                            checked=lambda _: data.get('auto_sleep_enabled', False),
                            enabled=bool(data) and not busy and data.get('idle_timeout', 0) > 0),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('開啟網頁控制台', lambda *_: webbrowser.open(API_BASE + '/status')),
            pystray.MenuItem('複製 API 網址', self._copy),
            pystray.MenuItem('重新整理狀態', lambda *_: threading.Thread(target=self._refresh, daemon=True).start()),
        ]
        if feedback:
            items.append(pystray.MenuItem(compact_line(feedback), None, enabled=False))
        items.extend([pystray.Menu.SEPARATOR,
                      pystray.MenuItem('退出 LLM watchdog…', self._quit, enabled=not quitting)])
        return items

    def _handler(self, path, label):
        def handle(icon=None, item=None):
            self.action(path, label)
        return handle

    def action(self, path, label):
        with self.lock:
            if self.quitting or ((self.busy or not self.data) and path != 'stop'):
                return
            if path == 'stop':
                self.quitting = True
            self.busy = True
            self.feedback = label + '中，請稍候…'
        def work():
            try:
                result = request('/api/' + path, 'POST', timeout=10 if path == 'stop' else 180)
                if result.get('status') not in ('ok', 'stopped'):
                    raise RuntimeError(result.get('message', '服務未完成操作'))
                with self.lock:
                    self.feedback = label + '完成'
                if path == 'stop':
                    self._close()
                    return
            except Exception as error:
                if path == 'stop' and self._backend_exited():
                    self._close()
                    return
                with self.lock:
                    self.feedback = label + '失敗：' + str(error)
                self._tray.notify(self.feedback, 'LLM watchdog')
            finally:
                with self.lock:
                    self.busy = False
                    if path == 'stop':
                        self.quitting = False
            self._refresh()
        threading.Thread(target=work, daemon=True).start()

    def _copy(self, icon=None, item=None):
        import ctypes
        user, kernel = ctypes.windll.user32, ctypes.windll.kernel32
        kernel.GlobalAlloc.restype = ctypes.c_void_p
        kernel.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel.GlobalLock.restype = ctypes.c_void_p
        kernel.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel.GlobalFree.argtypes = [ctypes.c_void_p]
        user.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user.SetClipboardData.restype = ctypes.c_void_p
        text = (API_BASE + '/v1' + '\0').encode('utf-16-le')
        handle = kernel.GlobalAlloc(0x0002, len(text))
        copied = False
        try:
            if not handle:
                raise OSError('無法配置剪貼簿記憶體')
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                raise OSError('無法存取剪貼簿記憶體')
            ctypes.memmove(pointer, text, len(text))
            kernel.GlobalUnlock(handle)
            if not user.OpenClipboard(None):
                raise OSError('剪貼簿暫時無法使用')
            try:
                if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
                    raise OSError('無法寫入剪貼簿')
                copied = True  # Clipboard owns the allocated memory now.
            finally:
                user.CloseClipboard()
            self._tray.notify('API 網址已複製', 'LLM watchdog')
        except OSError as error:
            self._tray.notify(str(error), 'LLM watchdog')
        finally:
            if handle and not copied:
                kernel.GlobalFree(handle)

    def _quit(self, icon=None, item=None):
        import ctypes
        with self.lock:
            if self.quitting:
                return
        # MB_SETFOREGROUND | MB_TOPMOST: a tray-owned dialog must remain visible.
        if ctypes.windll.user32.MessageBoxW(None, '結束 LLM watchdog？這會停止模型與本機 API 服務。', 'LLM watchdog', 0x24 | 0x10000 | 0x40000) != 6:
            return
        if self.data or (self.backend_pid is not None and not self._backend_exited()):
            self.action('stop', '結束 LLM watchdog')
        else:
            self._close()

    def _close(self):
        self.closed.set()
        self._tray.stop()

    def _backend_exited(self):
        if self.backend_pid is None:
            return False
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, self.backend_pid)
        if not handle:
            return kernel.GetLastError() == 87
        try:
            return kernel.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))

    def _refresh(self):
        try:
            data = request('/api/status')
        except Exception:
            data = None
        with self.lock:
            old_status = self.data.get('status') if self.data else None
            self.data = data
            if data:
                self.deadline = time.monotonic() + data.get('idle_remaining', 0)
                if self.backend_pid is None:
                    try:
                        import tempfile
                        self.backend_pid = int((Path(tempfile.gettempdir()) / 'llm_watchdog.pid').read_text())
                    except (OSError, ValueError):
                        pass
            state, countdown, _, _ = presentation(data, self.deadline, time.monotonic())
            status = data.get('status') if data else None
            if status != old_status:
                self._tray.icon = make_icon(status)
            self._tray.title = ('LLM watchdog · ' + state + ' · ' + countdown)[:127]

    def _poll(self):
        while not self.closed.is_set():
            self._refresh()
            if self._backend_exited():
                self._close()
                return
            self.closed.wait(2)

    def run(self):
        threading.Thread(target=self._poll, daemon=True).start()
        self._tray.run()
        self.closed.set()


if __name__ == '__main__':
    LLMTray().run()