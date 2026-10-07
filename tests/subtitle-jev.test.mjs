import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { JevDecisionEngine } from '../shinkansen/lib/jev.js';

const SK = { ASR_LAST_CUE_FALLBACK_MS: 1500 };
const noop = () => {};
vm.runInNewContext(fs.readFileSync(new URL('../shinkansen/content-youtube.js', import.meta.url), 'utf8'), {
  window: { __SK: SK, addEventListener: noop },
  document: { addEventListener: noop, querySelector: () => null },
  browser: { storage: { onChanged: { addListener: noop }, sync: { get: async () => ({}) } } },
  location: { hostname: 'www.youtube.com', pathname: '/watch', href: 'https://www.youtube.com/watch?v=example' },
  setTimeout, clearTimeout, setInterval, clearInterval, URL, console,
});
const segs = (texts, hints = []) => texts.map((text, i) => ({ text, normText: text, startMs: i * 500, jevBreakBefore: hints[i] }));
const tracks = [{ languageCode: 'zh-TW', kind: '' }, { languageCode: 'en', kind: '' }, { languageCode: 'en-US', kind: 'asr' }];

test('English ASR preference overrides native target and manual English', () => {
  const chosen = SK._chooseBestCaptionTrack(tracks, null, 'zh-TW', true);
  assert.equal(chosen.track.kind, 'asr');
  assert.equal(chosen.track.languageCode, 'en-US');
  assert.equal(chosen.action, 'switch');
});
test('Default and unavailable English ASR retain original native preference', () => {
  assert.equal(SK._chooseBestCaptionTrack(tracks, null, 'zh-TW').track.languageCode, 'zh-TW');
  assert.equal(SK._chooseBestCaptionTrack(tracks.slice(0, 2), null, 'zh-TW', true).track.languageCode, 'zh-TW');
});
test('Active English ASR remains; YouTube auto-translation is removed', () => {
  assert.equal(SK._chooseBestCaptionTrack(tracks, tracks[2], 'zh-TW', true).action, 'noop');
  assert.equal(SK._chooseBestCaptionTrack(tracks, { ...tracks[2], translationLanguageCode: 'zh-TW' }, 'zh-TW', true).action, 'switch');
});
test('Confident boundaries survive compaction and preserve all original fragments/timing', () => {
  const raw = segs(['we finished the work', 'now we can leave', 'see you tomorrow'], [null, true, true]);
  const result = SK._heuristicMergeAsr(raw, 'en');
  assert.equal(result.length, 3);
  assert.equal(result[0].endMs, raw[1].startMs);
  assert.deepEqual(Array.from(result.flatMap(r => r.sourceSegs)), raw);
});
test('Local punctuation boundaries and filler words preserve speech', () => {
  const raw = segs(['uh', 'we are done.', 'let us go']);
  const result = SK._heuristicMergeAsr(raw, 'en');
  assert.equal(result.length, 2);
  assert.equal(result[0].text, 'uh we are done.');
});
test('Continuous ASR has bounded sentences without dropping words', () => {
  const raw = segs(Array.from({ length: 70 }, (_, i) => `word${i}`));
  const result = SK._heuristicMergeAsr(raw, 'en');
  assert.ok(result.length >= 3);
  assert.ok(result.every(s => s.text.split(' ').length <= 30));
  assert.equal(result.flatMap(s => s.sourceSegs).length, raw.length);
});
test('Local filter preserves farewell, subscribe dialogue and Han-only Japanese', () => {
  const engine = new JevDecisionEngine();
  for (const text of ['thank you for watching', 'please subscribe', 'thanks', '東京', 'yes yes yes yes']) {
    const verdict = engine.fallbackEvaluate(text, 'zh-TW');
    assert.equal(verdict.is_valid, true, text);
    assert.equal(verdict.needs_translation, true, text);
  }
  assert.equal(engine.fallbackEvaluate('[Music]').is_valid, false);
});
test('Current TypeSafe request/response contract and uncertainty handling', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_, init) => {
      const request = JSON.parse(init.body);
      assert.equal(request.model, 'jev-latest');
      assert.ok(request.state.boundaries[0].left);
      assert.equal(request.questions.boundary_0.type, 'noul');
      return { ok: true, json: async () => ({ answers: {
        boundary_0: { type: 'noul', noul: 0.95 }, boundary_1: { type: 'noul', noul: 0.05 },
        boundary_2: { type: 'noul', noul: 0.51 },
      } }) };
    };
    const engine = new JevDecisionEngine({ enabled: true, apiKey: 'test' });
    assert.deepEqual((await engine.evaluateBoundaries(segs(['a', 'b', 'c', 'd']))).breakBefore, [null, true, false, null]);
  } finally { globalThis.fetch = original; }
});
test('HTTP errors, malformed results and missing keys retain local decisions', async () => {
  const original = globalThis.fetch;
  try {
    const engine = new JevDecisionEngine({ enabled: true, apiKey: 'test' });
    globalThis.fetch = async () => ({ ok: false, status: 401 });
    assert.equal((await engine.evaluateBoundaries(segs(['a', 'b']))).source, 'fallback');
    assert.equal(engine.lastError, 'HTTP 401');
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ decisions: {} }) });
    assert.equal((await engine.evaluateBatch(['hello']))[0].needs_translation, true);
    globalThis.fetch = async () => { throw Error('must not call'); };
    assert.equal((await new JevDecisionEngine({ enabled: true }).evaluateBoundaries(segs(['a', 'b']))).source, 'fallback');
  } finally { globalThis.fetch = original; }
});
test('Response body timeout is covered and recovers without dropping subtitles', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_, init) => ({ ok: true, json: () => new Promise((_, reject) => {
      init.signal.addEventListener('abort', () => reject(Object.assign(Error('aborted'), { name: 'AbortError' })), { once: true });
    }) });
    const engine = new JevDecisionEngine({ enabled: true, apiKey: 'test', timeoutMs: 10 });
    assert.equal((await engine.evaluateBatch(['hello']))[0].is_valid, true);
    assert.equal(engine.lastError, 'timeout');
  } finally { globalThis.fetch = original; }
});
test('Semantic continuation joins a short onset gap that local rules would split', () => {
  const raw = segs(['this sentence is', 'not complete yet']);
  raw[1].startMs = 1300;
  raw[1].jevBreakBefore = false;
  assert.equal(SK._heuristicMergeAsr(raw, 'en').length, 1);
});
test('An abbreviation does not create a sentence boundary', () => {
  assert.equal(SK._heuristicMergeAsr(segs(['ask Dr.', 'Smith about it']), 'en').length, 1);
});
test('Remote filtering rejects only confident negatives and keeps uncertain speech', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ answers: {
      valid_0: { type: 'noul', noul: 0 }, needs_0: { type: 'noul', noul: 1 },
      valid_1: { type: 'noul', noul: 0.5 }, needs_1: { type: 'noul', noul: 0.5 },
      valid_2: { type: 'noul', noul: 'false' }, needs_2: { type: 'noul', noul: 0 },
    } }) });
    const result = await new JevDecisionEngine({ enabled: true, apiKey: 'test' }).evaluateBatch(['noise', 'speech', 'dialogue']);
    assert.equal(result[0].is_valid, false);
    assert.equal(result[1].is_valid, true);
    assert.equal(result[1].needs_translation, true);
    assert.equal(result[2].source, 'fallback');
  } finally { globalThis.fetch = original; }
});
test('Boundary evaluation is bounded and keeps original indices across batches', async () => {
  const original = globalThis.fetch;
  let requests = 0;
  try {
    globalThis.fetch = async (_, init) => {
      requests++;
      const request = JSON.parse(init.body);
      assert.ok(Object.keys(request.questions).length <= 32);
      return { ok: true, json: async () => ({ answers: Object.fromEntries(Object.keys(request.questions).map(k => [k, { type: 'noul', noul: 0.99 }])) }) };
    };
    const result = await new JevDecisionEngine({ enabled: true, apiKey: 'test' }).evaluateBoundaries(segs(Array(150).fill('text')));
    assert.equal(requests, 4);
    assert.equal(result.breakBefore.length, 150);
    assert.equal(result.breakBefore[128], true);
    assert.equal(result.breakBefore[129], null);
  } finally { globalThis.fetch = original; }
});
