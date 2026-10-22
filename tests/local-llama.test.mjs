import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { ensureLocalLlamaServer, ensureLocalLayaDecision } from '../shinkansen/custom/local-llama.js';
import { providerSettings } from '../shinkansen/lib/custom-provider-profiles.js';
import { isLocalSubtitleProvider } from '../shinkansen/lib/local-subtitle.js';
const endpoint = 'http://127.0.0.1:8080/v1/chat/completions';

test('Sleeping Watchdog is explicitly woken once and all callers wait for readiness', async () => {
  const original = globalThis.fetch;
  let release, finished = false;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push([String(url), options.method]);
    if (String(url).endsWith('/api/status')) return Response.json({ status: 'sleeping' });
    assert.equal(String(url), 'http://127.0.0.1:8080/api/wake');
    assert.equal(options.method, 'POST');
    await new Promise(resolve => { release = resolve; });
    return Response.json({ status: 'ok', state: 'running' });
  };
  try {
    const first = ensureLocalLlamaServer(endpoint).then(() => { finished = true; });
    const second = ensureLocalLlamaServer('http://127.0.0.1:8080/v1');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(finished, false);
    assert.equal(requests.length, 2);
    release();
    await Promise.all([first, second]);
    assert.equal(finished, true);
    assert.equal(requests.length, 2);
  } finally { globalThis.fetch = original; }
});

test('A model already starting joins wake; a running model avoids another wake', async () => {
  const original = globalThis.fetch;
  const requests = [];
  let state = 'starting';
  globalThis.fetch = async url => {
    requests.push(String(url));
    return Response.json(String(url).endsWith('/api/status') ? { status: state } : { status: 'ok', state: 'running' });
  };
  try {
    await ensureLocalLlamaServer(endpoint);
    assert.equal(requests.length, 2);
    state = 'running';
    await ensureLocalLlamaServer(endpoint);
    assert.equal(requests.length, 3);
  } finally { globalThis.fetch = original; }
});

test('HTTP 200 load failure rejects and releases the shared promise for a later retry', async () => {
  const original = globalThis.fetch;
  let ok = false;
  globalThis.fetch = async url => Response.json(String(url).endsWith('/api/status')
    ? { status: 'sleeping' } : { status: ok ? 'ok' : 'error', state: ok ? 'running' : 'failed' });
  try {
    await assert.rejects(ensureLocalLlamaServer(endpoint), /模型載入失敗/);
    ok = true;
    await ensureLocalLlamaServer(endpoint);
  } finally { globalThis.fetch = original; }
});

test('Cloud URLs containing localhost text do not invoke local startup', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw Error('Unexpected local request'); };
  try {
    await ensureLocalLlamaServer('https://localhost.example.com/v1');
    await ensureLocalLlamaServer('https://example.com/127.0.0.1/v1');
    await ensureLocalLlamaServer('invalid');
  } finally { globalThis.fetch = original; }
});

test('A direct llama endpoint keeps its own models probe without Watchdog APIs', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async url => { requests.push(String(url)); return Response.json({ data: [] }); };
  try {
    await ensureLocalLlamaServer('http://localhost:8084/v1/chat/completions/');
    assert.deepEqual(requests, ['http://localhost:8084/v1/models']);
  } finally { globalThis.fetch = original; }
});

test('YouTube warmup resolves the subtitle local profile while webpage uses online', async () => {
  const source = fs.readFileSync(new URL('../shinkansen/background.js', import.meta.url), 'utf8');
  const start = source.indexOf('  WARMUP_YT_TRANSLATION: {');
  const end = source.indexOf('  // DEBUG:', start);
  const requests = [];
  const layaWakes = [];
  const saved = { ytSubtitle: { engine: 'openai-compat-local', jevEnabled: true, jevApiUrl: 'http://127.0.0.1:8080/v1/systemone' },
    customProviderType: 'online',
    customProvider: { baseUrl: 'https://example.com/v1' },
    customProviderLocal: { baseUrl: 'http://127.0.0.1:8080/v1', model: 'Riva-Translate' } };
  const handlers = vm.runInNewContext('({' + source.slice(start, end) + '})', {
    getSettingsCached: async () => saved, providerSettings, isLocalSubtitleProvider, debugLog: async () => {},
    ensureLocalLlamaServer: async (url, model) => requests.push([url, model]),
    ensureLocalLayaDecision: async url => layaWakes.push(url),
  });
  await handlers.WARMUP_YT_TRANSLATION.handler();
  assert.deepEqual(requests, [['http://127.0.0.1:8080/v1', 'Riva-Translate']]);
  assert.deepEqual(layaWakes, ['http://127.0.0.1:8080/v1/systemone']);
  saved.ytSubtitle.engine = 'google';
  await handlers.WARMUP_YT_TRANSLATION.handler();
  assert.equal(requests.length, 1);
});

test('ensureLocalLayaDecision deduplicates concurrent wakes against Watchdog 8080', async () => {
  const original = globalThis.fetch;
  const requests = [];
  let release;
  globalThis.fetch = async (url, options) => {
    requests.push([String(url), options.method]);
    await new Promise(r => { release = r; });
    return Response.json({ status: 'ok' });
  };
  try {
    const a = ensureLocalLayaDecision('http://127.0.0.1:8080/v1/systemone');
    const b = ensureLocalLayaDecision('http://127.0.0.1:8080/v1/systemone');
    await new Promise(r => setImmediate(r));
    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0], ['http://127.0.0.1:8080/api/decision/wake', 'POST']);
    release();
    await Promise.all([a, b]);
  } finally { globalThis.fetch = original; }
});

test('After restart warmup loads the configured Riva instead of the default Qwen', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push([String(url), options.method]);
    if (String(url).endsWith('/api/status')) return Response.json({ status: 'sleeping', current_model_id: 'Qwen' });
    assert.equal(new URL(url).pathname, '/api/switch');
    assert.equal(new URL(url).searchParams.get('model'), 'Riva-Translate');
    return Response.json({ status: 'ok', current_model: 'Riva-Translate' });
  };
  try {
    await ensureLocalLlamaServer(endpoint, 'Riva-Translate');
    assert.equal(requests.length, 2);
    assert.equal(requests[1][1], 'POST');
  } finally { globalThis.fetch = original; }
});
