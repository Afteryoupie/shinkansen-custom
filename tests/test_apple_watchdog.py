"""Apple backend lifecycle checks without requiring model inference or a license."""
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from watchdog import manager
from watchdog.state import state


class AppleBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = (state.current_model, state.llm_proc, state.lock, state.is_starting)
        state.lock = asyncio.Lock()
        state.llm_proc = None
        state.is_starting = False
        state.current_model = {"id": "apple-foundation-system", "name": "Apple", "type": "apple", "path": "system"}

    async def asyncTearDown(self):
        state.current_model, state.llm_proc, state.lock, state.is_starting = self.saved

    async def test_discovery_without_weights(self):
        with patch.object(manager.sys, "platform", "darwin"), patch.object(manager, "APPLE_API_BIN") as api, patch.object(manager, "FM_BIN") as fm, patch.object(manager, "MODELS_DIR") as models:
            api.is_file.return_value = True
            fm.is_file.return_value = True
            models.exists.return_value = False
            self.assertEqual([m["id"] for m in manager.scan_models()], ["apple-intelligence-translation"])

    async def test_starts_only_system_model_on_loopback(self):
        check = Mock(returncode=0, communicate=AsyncMock(return_value=(b"Available", b"")))
        proc = Mock()
        proc.poll.return_value = None
        with patch.object(manager.asyncio, "create_subprocess_exec", AsyncMock(return_value=check)), patch.object(manager.subprocess, "Popen", return_value=proc) as popen, patch.object(manager, "is_llm_ready", AsyncMock(return_value=True)):
            self.assertTrue(await manager.start_llm())
            self.assertEqual(popen.call_args.kwargs["args"], [str(manager.FM_BIN), "serve", "--host", "127.0.0.1", "--port", str(manager.LLM_INTERNAL_PORT)])

    async def test_license_failure_does_not_launch_server(self):
        check = Mock(returncode=69, communicate=AsyncMock(return_value=(b"", b"Not agreed")))
        with patch.object(manager.asyncio, "create_subprocess_exec", AsyncMock(return_value=check)), patch.object(manager.subprocess, "Popen") as popen:
            self.assertFalse(await manager.start_llm())
            popen.assert_not_called()
            self.assertFalse(state.is_starting)

    async def test_translation_backend_lifecycle(self):
        state.current_model = {"id": "apple-intelligence-translation", "name": "Apple Translation", "type": "apple-api", "path": "base"}
        proc = Mock()
        proc.poll.return_value = None
        with patch.object(manager.subprocess, "Popen", return_value=proc) as popen, patch.object(manager, "is_llm_ready", AsyncMock(return_value=True)):
            self.assertTrue(await manager.start_llm())
            self.assertEqual(popen.call_args.kwargs["args"], [str(manager.APPLE_API_BIN), "serve", "--hostname", "127.0.0.1", "--port", str(manager.LLM_INTERNAL_PORT)])


if __name__ == "__main__":
    unittest.main()
