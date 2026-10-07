"""Exercise HTTP path/model rewriting against a local mock translation API."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from watchdog import server
from watchdog.state import state


class TranslationProxyTest(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_request_routes_to_apple_api(self):
        saved = state.current_model
        captured = []

        async def upstream(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:"))
            body = json.loads(await reader.readexactly(length))
            captured.append((head.split(b"\r\n")[0], body))
            payload = json.dumps({"choices": [{"message": {"content": "本機翻譯測試"}, "finish_reason": "stop"}]}).encode()
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode() + payload)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        backend = await asyncio.start_server(upstream, "127.0.0.1", 0)
        proxy = await asyncio.start_server(server.handle_proxy_client, "127.0.0.1", 0)
        state.current_model = {"type": "apple-api", "id": "apple-intelligence-translation", "path": "permissive"}
        try:
            with patch.object(server, "LLM_INTERNAL_PORT", backend.sockets[0].getsockname()[1]), patch.object(server, "start_llm", AsyncMock(return_value=True)):
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy.sockets[0].getsockname()[1])
                body = json.dumps({"messages": [{"role": "user", "content": "Local translation test"}], "stream": False}).encode()
                writer.write(f"POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 5)
                self.assertIn("本機翻譯測試", json.loads(response.split(b"\r\n\r\n", 1)[1])["choices"][0]["message"]["content"])
                self.assertEqual(captured[0][0], b"POST /api/v1/chat/completions HTTP/1.1")
                self.assertEqual(captured[0][1]["model"], "permissive")
                writer.close()
                await writer.wait_closed()
        finally:
            state.current_model = saved
            proxy.close()
            backend.close()
            await proxy.wait_closed()
            await backend.wait_closed()
