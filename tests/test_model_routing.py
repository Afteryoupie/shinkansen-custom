import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
from watchdog import server
from watchdog.state import state

MODELS = [dict(id=x, name=x.upper(), path='/models/'+x, type='mlx') for x in ('a','b')]

class RoutingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved=(state.current_model,state.models,state.request_lock,state.active_requests)
        state.current_model=MODELS[0].copy();state.models=MODELS;state.request_lock=None;state.active_requests=0
        self.captured=[];self.switches=[];self.gate=asyncio.Event();self.hold=False
        async def switch(model):
            self.switches.append(model);state.current_model=next(m for m in MODELS if m['id']==model);return True,'ok'
        self.patches=[patch.object(server,'scan_models',return_value=MODELS),patch.object(server,'start_llm',AsyncMock(return_value=True)),patch.object(server,'switch_model',side_effect=switch)]
        for p in self.patches:p.start()
        self.backend=await asyncio.start_server(self.upstream,'127.0.0.1',0)
        self.portpatch=patch.object(server,'LLM_INTERNAL_PORT',self.backend.sockets[0].getsockname()[1]);self.portpatch.start()
        self.proxy=await asyncio.start_server(server.handle_proxy_client,'127.0.0.1',0)
    async def asyncTearDown(self):
        self.gate.set();self.proxy.close();self.backend.close();await self.proxy.wait_closed();await self.backend.wait_closed()
        self.portpatch.stop()
        for p in self.patches:p.stop()
        state.current_model,state.models,state.request_lock,state.active_requests=self.saved
    async def upstream(self,reader,writer):
        head=await reader.readuntil(b'\r\n\r\n');length=next(int(l.split(b':',1)[1]) for l in head.split(b'\r\n') if l.lower().startswith(b'content-length:'))
        body=json.loads(await reader.readexactly(length));self.captured.append(body)
        if self.hold and len(self.captured)==1:
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\ndata: first\n\n');await writer.drain();await self.gate.wait()
            writer.write(b'data: [DONE]\n\n')
        else:
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}')
        await writer.drain();writer.close();await writer.wait_closed()
    async def request(self,model='default',fragment=False,halfclose=False,extra=None):
        reader,writer=await asyncio.open_connection('127.0.0.1',self.proxy.sockets[0].getsockname()[1])
        body=json.dumps({'model':model,'messages':[],**(extra or {})}).encode();head=f'POST /v1/chat/completions HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'.encode()
        if fragment:
            writer.write(head[:12]);await writer.drain();await asyncio.sleep(.01);writer.write(head[12:]+body[:3]);await writer.drain();await asyncio.sleep(.01);writer.write(body[3:])
        else:writer.write(head+body)
        await writer.drain()
        if halfclose:writer.write_eof()
        result=await asyncio.wait_for(reader.read(),3);writer.close();await writer.wait_closed();return result
    async def test_id_switch(self):
        self.assertIn(b'200 OK',await self.request('b'));self.assertEqual(self.switches,['b']);self.assertEqual(self.captured[0]['model'],'/models/b');self.assertEqual(state.active_requests,0)
    async def test_name_and_path(self):
        await self.request('B');await self.request('/models/a');self.assertEqual(self.switches,['b','a'])
    async def test_default_and_current_do_not_switch(self):
        await self.request();await self.request('a');self.assertEqual(self.switches,[])
    async def test_unknown_and_invalid_are_rejected(self):
        self.assertIn(b'400 Bad Request',await self.request('unknown'));self.assertIn(b'400 Bad Request',await self.request(123));self.assertEqual(self.captured,[])
    async def test_fragmented_request(self):
        self.assertIn(b'200 OK',await self.request('b',fragment=True))
    async def test_busy_rejected_until_stream_finishes(self):
        self.hold=True;first=asyncio.create_task(self.request('a',halfclose=True))
        while not self.captured:await asyncio.sleep(.01)
        try:
            response=await self.request('b')
            self.assertIn(b'409 Conflict',response)
            self.assertEqual(self.switches,[])
        finally:
            self.gate.set()
            r1=await first
        self.assertIn(b'[DONE]',r1)
        self.assertIn(b'200 OK',await self.request('b'))
        self.assertEqual(self.switches,['b'])
    async def test_start_failure_clears_busy(self):
        with patch.object(server,'start_llm',AsyncMock(return_value=False)):
            self.assertIn(b'503 Service Unavailable',await self.request())
        self.assertIn(b'200 OK',await self.request());self.assertEqual(state.active_requests,0)
    async def test_riva_default_uses_translation_target_without_leaking_metadata(self):
        state.current_model = dict(id='Riva-Translate-test',name='Riva',path='/models/riva',type='gguf')
        messages = [{'role':'system','content':'Translate to Taiwan Chinese'}, {'role':'user','content':'Hello'}]
        await self.request(extra={'messages':messages,'shinkansen_target_language':'Traditional Chinese'})
        self.assertEqual(self.captured[0]['messages'][1]['content'],'Translate this into Traditional Chinese: Hello')
        self.assertNotIn('shinkansen_target_language',self.captured[0])
    async def test_other_models_keep_original_messages(self):
        messages = [{'role':'user','content':'Hello'}]
        await self.request(extra={'messages':messages,'shinkansen_target_language':'Traditional Chinese'})
        self.assertEqual(self.captured[0]['messages'],messages)
        self.assertNotIn('shinkansen_target_language',self.captured[0])
