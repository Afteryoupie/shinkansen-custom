import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from watchdog import manager, server
from watchdog.state import state

class StartupIdleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        keys = ('current_model', 'models', 'llm_proc', 'is_starting', 'last_active_time', 'auto_sleep_enabled', 'active_requests', 'lock', 'should_exit')
        self.saved = {k: getattr(state, k) for k in keys}
        state.current_model = dict(id='K2-Horizon', name='K2-Horizon', type='gguf', path='/tmp/K2-Horizon.gguf', idle_timeout=180)
        state.models = [state.current_model]
        state.llm_proc = Mock(returncode=None, pid=123)
        state.llm_proc.poll.return_value = None
        state.is_starting = True
        state.last_active_time = time.time() - 600
        state.auto_sleep_enabled = True
        state.active_requests = 0
        state.should_exit = False
        state.lock = asyncio.Lock()

    async def asyncTearDown(self):
        for k, v in self.saved.items(): setattr(state, k, v)

    async def test_status_reads_do_not_kill_loading_model(self):
        for path in ('/api/status', '/status'):
            reader = asyncio.StreamReader()
            reader.feed_data(f'GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
            reader.feed_eof()
            writer = Mock(drain=AsyncMock(), wait_closed=AsyncMock())
            with patch.object(server, 'scan_models', return_value=state.models), patch.object(server, 'stop_llm') as stop:
                await server.handle_proxy_client(reader, writer)
                stop.assert_not_called()
                body = b''.join(c.args[0] for c in writer.write.call_args_list)
                self.assertIn(b'200 OK', body)
                self.assertIn(b'"starting"', body)

    async def test_background_idle_check_skips_startup(self):
        async def tick(_): state.should_exit = True
        with patch.object(manager.asyncio, 'sleep', side_effect=tick), patch.object(manager, 'stop_llm') as stop:
            await manager.idle_checker()
            stop.assert_not_called()

    async def test_k2_ready_after_old_limit(self):
        proc = state.llm_proc
        state.llm_proc = None
        state.is_starting = False
        clock = SimpleNamespace(time=time.time, monotonic=Mock(side_effect=[0, 0, 30, 30]))
        with patch.object(manager, 'time', clock), patch.object(manager, 'IFM_LLAMA_BIN') as binary, patch.object(manager.subprocess, 'Popen', return_value=proc), patch.object(manager, 'is_llm_ready', AsyncMock(side_effect=[False, True])), patch.object(manager.asyncio, 'sleep', AsyncMock()):
            binary.is_file.return_value = True
            self.assertTrue(await manager.start_llm())
            self.assertFalse(state.is_starting)
            self.assertGreater(state.last_active_time, time.time() - 2)

    async def test_timeout_cleans_up_process(self):
        proc = state.llm_proc
        state.llm_proc = None
        state.is_starting = False
        clock = SimpleNamespace(time=time.time, monotonic=Mock(side_effect=[0, 121]))
        with patch.object(manager, 'time', clock), patch.object(manager, 'IFM_LLAMA_BIN') as binary, patch.object(manager.subprocess, 'Popen', return_value=proc), patch.object(manager, 'stop_llm') as stop:
            binary.is_file.return_value = True
            self.assertFalse(await manager.start_llm())
            stop.assert_called_once()
            self.assertFalse(state.is_starting)
