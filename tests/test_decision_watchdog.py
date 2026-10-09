import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from watchdog import server, manager
from watchdog.decision import DecisionManager, validate_payload
from watchdog.laya_backend import predict
from watchdog.state import state

PAYLOAD = {"model": "laya-multilingual", "state": {"boundaries": [{"left": "ask Dr.", "right": "Smith"}]},
           "questions": {"boundary_0": {"type": "noul", "instructions": "Is this a sentence boundary?"}}}


class DecisionRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.decision = Mock()
        self.decision.evaluate = AsyncMock(return_value={"answers": {"boundary_0": {"type": "noul", "noul": .1}}})
        self.decision.active_requests = 0
        self.decision.starting = False
        self.decision.lock.locked.return_value = False
        self.patch = patch.object(server, "decision", self.decision)
        self.patch.start()
        self.proxy = await asyncio.start_server(server.handle_proxy_client, "127.0.0.1", 0)
        self.saved = (state.current_model, state.request_lock, state.active_requests)
        state.current_model = {"id": "translation", "name": "Translation", "type": "gguf"}
        state.request_lock = asyncio.Lock()
        state.active_requests = 1
        await state.request_lock.acquire()

    async def asyncTearDown(self):
        self.proxy.close()
        await self.proxy.wait_closed()
        self.patch.stop()
        state.request_lock.release()
        state.current_model, state.request_lock, state.active_requests = self.saved

    async def request(self, path="/v1/systemone", payload=PAYLOAD, fragment=False, extra=""):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.proxy.sockets[0].getsockname()[1])
        body = json.dumps(payload).encode()
        head = f"POST {path} HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n{extra}\r\n".encode()
        writer.write(head + (body[:4] if fragment else body))
        await writer.drain()
        if fragment:
            await asyncio.sleep(.01)
            writer.write(body[4:])
            await writer.drain()
        response = await asyncio.wait_for(reader.read(), 2)
        writer.close()
        await writer.wait_closed()
        return response

    async def test_fragmented_decisions_run_while_chat_is_busy(self):
        response = await self.request(fragment=True)
        self.assertIn(b"200 OK", response)
        self.decision.evaluate.assert_awaited_once_with(PAYLOAD)
        self.assertEqual(state.current_model["id"], "translation")
        self.assertEqual(state.active_requests, 1)
        self.assertTrue(state.request_lock.locked())

    async def test_invalid_input_does_not_wake_any_model(self):
        for payload in ({"model": "translation", "state": {}, "questions": PAYLOAD["questions"]},
                        {"state": {}, "questions": {}}, {"state": None, "questions": PAYLOAD["questions"]}):
            self.assertIn(b"400 Bad Request", await self.request(payload=payload))
        self.assertIn(b"400 Bad Request", await self.request(extra="Transfer-Encoding: chunked\r\n"))
        self.decision.evaluate.assert_not_awaited()

    async def test_sleep_protects_active_decision_requests(self):
        self.decision.active_requests = 1
        self.assertIn(b"409 Conflict", await self.request(path="/api/decision/sleep"))
        self.decision.stop.assert_not_called()

    async def test_backend_failure_returns_json_for_extension_fallback(self):
        self.decision.evaluate.side_effect = RuntimeError("offline")
        response = await self.request()
        self.assertIn(b"503 Service Unavailable", response)
        self.assertEqual(json.loads(response.split(b"\r\n\r\n")[1])["error"]["message"], "offline")


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_requests_serialize_and_clear_activity_on_error(self):
        d = DecisionManager()
        d._start = AsyncMock()
        entered = asyncio.Event()
        release = asyncio.Event()
        async def http(*args):
            entered.set()
            await release.wait()
            raise RuntimeError("failed")
        d._http = http
        first = asyncio.create_task(d.evaluate(PAYLOAD))
        await entered.wait()
        second = asyncio.create_task(d.evaluate(PAYLOAD))
        await asyncio.sleep(0)
        self.assertEqual(d.active_requests, 2)
        d.check_idle()
        self.assertTrue(d.lock.locked())
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        self.assertEqual(d.active_requests, 0)
        self.assertFalse(d.lock.locked())
        self.assertEqual(d.last_error, "failed")

    async def test_idle_policy_is_independent_and_respects_requests(self):
        d = DecisionManager()
        d.stop = Mock()
        d.last_active = time.monotonic() - 181
        d.auto_sleep = False
        d.check_idle()
        d.stop.assert_not_called()
        d.auto_sleep = True
        d.active_requests = 1
        d.check_idle()
        d.stop.assert_not_called()
        d.active_requests = 0
        d.check_idle()
        d.stop.assert_called_once()

    async def test_idle_loop_checks_decisions_even_with_chat_auto_sleep_off(self):
        saved = (state.should_exit, state.auto_sleep_enabled)
        state.should_exit = False
        state.auto_sleep_enabled = False
        def checked():
            state.should_exit = True
        try:
            with patch.object(manager.asyncio, 'sleep', AsyncMock()), patch.object(manager.decision, 'check_idle', side_effect=checked) as check:
                await manager.idle_checker()
                check.assert_called_once()
        finally:
            state.should_exit, state.auto_sleep_enabled = saved


class AdapterTests(unittest.TestCase):
    def test_boundary_contexts_are_batched_individually_and_keep_ids(self):
        agent = Mock()
        agent.predict_batch.return_value = [{"answers": {"boundary": {"probabilities": {"A": .1, "B": .9}}},
                                             "usage": {"input_tokens": 20}}]
        result = predict(agent, PAYLOAD)
        self.assertEqual(result["answers"]["boundary_0"]["noul"], .1)
        self.assertEqual(agent.predict_batch.call_args.args[0], PAYLOAD["state"]["boundaries"])
        self.assertEqual(agent.predict_batch.call_args.args[1]["boundary"]["type"], "choice")
        self.assertEqual(agent.predict_batch.call_args.kwargs["batch_size"], 8)
        agent.system_one.assert_not_called()

    def test_laya_never_appears_in_chat_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "Laya-Multilingual"
            model.mkdir()
            (model / "config.json").write_text('{}')
            (model / "rl_agent_config.json").write_text('{}')
            for platform in ('darwin', 'win32'):
                with patch.object(manager, 'MODELS_DIR', Path(tmp)), patch.object(manager.sys, 'platform', platform):
                    self.assertNotIn('Laya-Multilingual', [m['id'] for m in manager.scan_models()])

    def test_generic_noul_choice_score_passthrough(self):
        for qtype in ('noul', 'choice', 'score'):
            payload = {"state": "hello", "questions": {"q": {"type": qtype, "instructions": "Classify"}}}
            self.assertEqual(validate_payload(payload), payload)
            agent = Mock()
            predict(agent, payload)
            agent.system_one.assert_called_once_with(payload['state'], payload['questions'])


if __name__ == '__main__':
    unittest.main()
