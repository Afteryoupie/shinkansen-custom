import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import '../shinkansen/lib/provider-performance.js';
import { buildThinkingPayload } from '../shinkansen/lib/openai-compat-thinking.js';
import { providerConfig } from '../shinkansen/lib/custom-provider-profiles.js';
import { sanitizeImport } from '../shinkansen/options/import-sanitize.js';
import { translateBatch } from '../shinkansen/lib/openai-compat.js';
import { fetchWithRetry } from '../shinkansen/lib/llm-common.js';

const free = { baseUrl: 'https://openrouter.ai/api/v1', model: 'nvidia/nemotron-3-super-120b-a12b:free' };
const performance = globalThis.__SKProviderPerformance;

test('Free and local webpage limits prioritize a small first batch and bound concurrency', () => {
  assert.deepEqual(performance.config(free, 'online'), { webConcurrency: 2, webBatchUnits: 40,
    webBatchChars: 7000, firstBatchUnits: 6, firstBatchChars: 1200 });
  assert.equal(performance.config({ ...free, webConcurrency: 30 }, 'online').webConcurrency, 2);
  const local = performance.config({ webBatchUnits: 2, webBatchChars: 500 }, 'local');
  assert.equal(local.webConcurrency, 1);
  assert.equal(local.firstBatchUnits, 2);
  assert.equal(local.firstBatchChars, 500);
  assert.equal(performance.isFreeProvider({ ...free, baseUrl: 'https://other.example/?openrouter.ai' }), false);
});

test('OpenRouter disables reasoning and keeps provider fallback without adding a paid model', () => {
  const body = buildThinkingPayload({ ...free, level: 'off' });
  assert.deepEqual(body.reasoning, { enabled: false, exclude: true });
  assert.deepEqual(body.provider, { sort: 'throughput', allow_fallbacks: true });
  assert(!('models' in body));
  const overridden = buildThinkingPayload({ ...free, level: 'off', routingSort: 'latency',
    extraBodyRaw: JSON.stringify({ provider: { max_price: { prompt: 0 } } }) });
  assert.equal(overridden.provider.sort, 'latency');
  assert.equal(overridden.provider.max_price.prompt, 0);
  assert(!('provider' in buildThinkingPayload({ baseUrl: 'http://127.0.0.1:8080/v1', level: 'off' })));
});

test('Performance and routing settings round-trip while invalid limits are rejected', () => {
  const config = { ...free, webConcurrency: 2, webBatchUnits: 40, webBatchChars: 7000,
    routingSort: 'latency', allowFallbacks: false };
  assert.deepEqual(sanitizeImport({ customProviderOnline: config }, key => key).clean.customProviderOnline, config);
  const invalid = providerConfig({ webConcurrency: 0, webBatchUnits: 1.5, webBatchChars: Infinity, routingSort: 'invalid' });
  assert.deepEqual(invalid, {});
});

test('Free request reservations stay below 20 starts in a rolling minute', async () => {
  const { reserveFreeRequest } = await import('../shinkansen/lib/openrouter-rate-limit.js?reservation-test');
  const starts = Array.from({ length: 30 }, () => 1000 + reserveFreeRequest(free, 1000));
  for (const time of starts) assert(starts.filter(t => t >= time && t < time + 60000).length <= 20);
  assert.equal(reserveFreeRequest({ ...free, model: 'paid-model' }, 1000), 0);
  assert.equal(reserveFreeRequest({ baseUrl: 'http://127.0.0.1:8080/v1', model: 'local:free' }, 1000), 0);
});

test('The production free-model request retains the exact model and disables thinking', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return Response.json({ choices: [{ message: { content: '你好' }, finish_reason: 'stop' }] });
  };
  try {
    const result = await translateBatch(['Hello'], { targetLanguage: 'zh-TW', maxRetries: 0,
      customProvider: { ...free, thinkingLevel: 'off', useStrongSegMarker: false } });
    assert.equal(result.translations[0], '你好');
    assert.equal(requests[0].model, free.model);
    assert.equal(requests[0].reasoning.enabled, false);
    assert.equal(requests[0].provider.allow_fallbacks, true);
    assert(!('models' in requests[0]));
  } finally { globalThis.fetch = original; }
});

test('Request pacing runs before every HTTP attempt, including a retry', async () => {
  const original = globalThis.fetch;
  const events = [];
  globalThis.fetch = async () => {
    events.push('fetch');
    return Response.json({}, { status: events.length === 2 ? 503 : 200 });
  };
  try {
    const response = await fetchWithRetry('https://example.com', {}, {
      maxRetries: 1, beforeFetch: async () => { events.push('pace'); },
    });
    assert.equal(response.status, 200);
    assert.deepEqual(events, ['pace', 'fetch', 'pace', 'fetch']);
  } finally { globalThis.fetch = original; }
});

test('Production custom scheduling starts later batches before the first completes', async () => {
  const source = fs.readFileSync(new URL('../shinkansen/content.js', import.meta.url), 'utf8');
  const workerStart = source.indexOf('  async function runWithConcurrency(');
  const workerEnd = source.indexOf('  // ─── Greedy', workerStart);
  const flowStart = source.indexOf('    if (jobs.length > 0) {', source.indexOf('const useStreaming ='));
  const flowEnd = source.indexOf("    SK.sendLog('info', 'translate', 'translateUnits complete'", flowStart);
  for (const [concurrency, partial] of [[2, false], [1, false], [2, true]]) {
    const started = [], releases = [];
    const context = { jobs: [0, 1, 2].map(id => ({ id, texts: ['Hello'] })), maxConcurrent: concurrency, signal: new AbortController().signal,
      useStreaming: false, providerPerformance: {}, partialModeActive: partial,
      tu_entry: Date.now(), SK: { sendLog: () => {} },
      runBatch: async job => { started.push(job.id); await new Promise(resolve => { releases[job.id] = resolve; }); },
    };
    vm.createContext(context);
    vm.runInContext(source.slice(workerStart, workerEnd) + '\nthis.run = async () => {\n' + source.slice(flowStart, flowEnd) + '\n};', context);
    const pending = context.run();
    assert.deepEqual(started, concurrency === 2 && !partial ? [0, 1] : [0]);
    releases[0]();
    await new Promise(resolve => setImmediate(resolve));
    if (!partial) {
      if (releases[1]) releases[1]();
      await new Promise(resolve => setImmediate(resolve));
      if (releases[2]) releases[2]();
    }
    await pending;
    assert.deepEqual(started, partial ? [0] : [0, 1, 2]);
  }
});
