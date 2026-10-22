import test from 'node:test';
import assert from 'node:assert/strict';
import { translateBatch } from '../shinkansen/lib/openai-compat.js';

test('Blank model resolves Riva and translates ASR sentence groups with complete ranges', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    if (String(url).endsWith('/api/status')) return Response.json({status:'running',current_model_id:'Riva-Translate-test'});
    const body = JSON.parse(options.body);
    requests.push(body);
    const text = body.messages[1].content;
    return Response.json({choices:[{message:{content:text.startsWith('The train')?'火車五分鐘後會到':'站在黃線後'},finish_reason:'stop'}]});
  };
  try {
    const settings = {targetLanguage:'zh-TW',maxRetries:0,customProvider:{baseUrl:'http://127.0.0.1:8080/v1',model:'',systemPrompt:'ASR translation to Taiwan Chinese',temperature:0}};
    const result = await translateBatch(['1|The train\n2|will arrive in five minutes.\n3|Stand behind the yellow line.'],settings);
    assert.deepEqual(result.translations,['1-2|火車五分鐘後會到\n3|站在黃線後']);
    assert.deepEqual(requests.map(body=>body.messages[1].content),['The train will arrive in five minutes.','Stand behind the yellow line.']);
    assert.ok(requests.every(body=>body.shinkansen_target_language==='Traditional Chinese'));
    assert.ok(requests.every(body=>!('model' in body)));
  } finally { globalThis.fetch = originalFetch; }
});

test('Riva ASR groups remain bounded without dropping fragment IDs', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    if (String(url).endsWith('/api/status')) return Response.json({status:'running',current_model_id:'Riva-Translate-test'});
    const body=JSON.parse(options.body); requests.push(body);
    return Response.json({choices:[{message:{content:'完整譯文'},finish_reason:'stop'}]});
  };
  try {
    const input=Array.from({length:9},(_,i)=>`${i+1}|word${i+1}`).join('\n');
    const result=await translateBatch([input],{targetLanguage:'zh-TW',maxRetries:0,customProvider:{baseUrl:'http://127.0.0.1:8080/v1',model:'Riva-Translate-test',systemPrompt:'ASR translation'}});
    assert.deepEqual(result.translations,['1-8|完整譯文\n9|完整譯文']);
    assert.equal(requests.length,2);
    assert.equal(requests[1].messages[1].content,'word9');
  } finally { globalThis.fetch=originalFetch; }
});
