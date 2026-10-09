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

test('Manual Chinese wins even with a legacy English ASR preference', () => {
  for (const hints of [undefined, true, { preferEnglishAsr: true }]) {
    const chosen = SK._chooseBestCaptionTrack(tracks, null, 'zh-TW', hints);
    assert.equal(chosen.track, tracks[0]);
    assert.equal(chosen.action, 'switch-to-native');
  }
});
test('Manual English is translated without requiring an ASR track', () => {
  const english = { languageCode: 'en-GB', kind: '' };
  const chosen = SK._chooseBestCaptionTrack([english], null, 'zh-TW');
  assert.equal(chosen.track, english);
  assert.equal(chosen.sourceLanguage, 'en-GB');
  assert.equal(chosen.action, 'switch');
});
test('Manual English wins over original and dubbed ASR', () => {
  const list = [{languageCode:'zh-TW',kind:'asr'}, {languageCode:'ja',kind:'asr'}, {languageCode:'en',kind:''}];
  assert.equal(SK._chooseBestCaptionTrack(list, null, 'zh-TW', { originalAudioLang:'ja' }).track, list[2]);
});
test('Chinese variants and ambiguous Chinese precede English without skipping conversion', () => {
  for (const languageCode of ['zh', 'zh-CN', 'zh-Hans']) {
    const chinese = {languageCode, kind:''};
    const chosen = SK._chooseBestCaptionTrack([tracks[1], chinese], null, 'zh-TW');
    assert.equal(chosen.track, chinese);
    assert.equal(chosen.action, 'switch');
  }
});
test('Active manual English remains; YouTube auto-translation is removed', () => {
  const list = tracks.slice(1);
  assert.equal(SK._chooseBestCaptionTrack(list, list[0], 'zh-TW').action, 'noop');
  assert.equal(SK._chooseBestCaptionTrack(list, { ...list[0], translationLanguageCode: 'zh-TW' }, 'zh-TW').action, 'switch');
});
test('Original-language ASR wins over dubbed English and conflicting default index', () => {
  const list = [{languageCode:'en',kind:'asr'}, {languageCode:'ja',kind:'asr'}];
  for (const ordered of [list, [...list].reverse()]) {
    const chosen = SK._chooseBestCaptionTrack(ordered, null, 'zh-TW', { originalAudioLang:'ja-JP', defaultCaptionTrackIndex:ordered.indexOf(list[0]) });
    assert.equal(chosen.track, list[1]);
    assert.equal(chosen.sourceLanguage, 'ja');
    assert.equal(chosen.action, 'switch');
  }
});
test('ASR uses default hint or unique track, but never guesses among multiple languages', () => {
  const list = [{languageCode:'en',kind:'asr'}, {languageCode:'ko',kind:'asr'}];
  assert.equal(SK._chooseBestCaptionTrack(list, null, 'zh-TW', {defaultCaptionTrackIndex:1}).track, list[1]);
  assert.equal(SK._chooseBestCaptionTrack([list[1]], null, 'zh-TW').track, list[1]);
  assert.equal(SK._chooseBestCaptionTrack(list, null, 'zh-TW').track, undefined);
  assert.equal(SK._chooseBestCaptionTrack([list[0]], null, 'zh-TW', {originalAudioLang:'ja'}).track, undefined);
});
test('Manual Chinese beats Chinese ASR regardless of array order', () => {
  const list = [{languageCode:'zh-TW',kind:'asr'}, tracks[0]];
  assert.equal(SK._chooseBestCaptionTrack(list, null, 'zh-TW').track, tracks[0]);
  assert.equal(SK._chooseBestCaptionTrack(list, tracks[0], 'zh-TW').action, 'skip');
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


test('ASR batch-tail overflow keeps timing and strips subtitle punctuation', () => {
  const original = SK.stripSubtitlePunctuation;
  SK.stripSubtitlePunctuation = text => text.replace(/[，。！]/g, '');
  try {
    const result = SK.ASR.parseLlmOutput('1|你好！\n2-4|第二句。', segs(['a', 'b', 'c']), 1500);
    assert.deepEqual(JSON.parse(JSON.stringify(result)), [
      { s: 0, e: 500, t: '你好' }, { s: 500, e: 1500, t: '第二句' },
    ]);
  } finally { SK.stripSubtitlePunctuation = original; }
});

test('ASR reversed ranges are normalized before full coverage validation', () => {
  const result = SK.ASR.parseLlmOutput('3-1|完整句', segs(['a', 'b', 'c']), 1500);
  assert.equal(result.length, 1);
  assert.equal(result[0].s, 0);
  assert.equal(result[0].e, 1500);
});

test('ASR gaps, overlaps, missing tails and invalid starts still trigger retries', () => {
  for (const text of ['1|a\n3|c', '1-2|a\n2-3|b', '1-2|a', '4-5|a', '0-3|a', '1-4|a\n4|b', '']) {
    assert.throws(() => SK.ASR.parseLlmOutput(text, segs(['a', 'b', 'c']), 1500), /ASR response/, text);
  }
});

test('ASR legacy JSON retains complete timeline validation', () => {
  const raw = segs(['a', 'b', 'c']);
  const result = SK.ASR.parseLlmOutput('[{"s":0,"e":1500,"t":"完整句"}]', raw, 1500);
  assert.equal(result[0].e, 1500);
  assert.throws(() => SK.ASR.parseLlmOutput('[{"s":0,"e":500,"t":"缺尾"}]', raw, 1500), /incomplete legacy timeline/);
});

test('A stalled fetch that ignores abort still reaches the timeout fallback', { timeout: 500 }, async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Promise(() => {});
    const engine = new JevDecisionEngine({ enabled: true, apiKey: 'test', timeoutMs: 10 });
    const result = await engine.evaluateBatch(['human speech']);
    assert.equal(result[0].is_valid, true);
    assert.equal(result[0].source, 'fallback');
    assert.equal(engine.lastError, 'timeout');
  } finally { globalThis.fetch = original; }
});

test('Malformed JSON, wrong answer types and out-of-range probabilities retain speech', async () => {
  const original = globalThis.fetch;
  try {
    const engine = new JevDecisionEngine({ enabled: true, apiKey: 'test' });
    globalThis.fetch = async () => ({ ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } });
    assert.equal((await engine.evaluateBatch(['speech']))[0].source, 'fallback');
    for (const answer of [{ type: 'noul', noul: 2 }, { type: 'noul', noul: -1 }, { type: 'noul', noul: NaN }, { type: 'choice', noul: 0 }]) {
      globalThis.fetch = async () => ({ ok: true, json: async () => ({ answers: { valid_0: answer, needs_0: { type: 'noul', noul: 0 } } }) });
      assert.equal((await engine.evaluateBatch(['speech']))[0].needs_translation, true);
    }
  } finally { globalThis.fetch = original; }
});

test('Filtering batches stay bounded and keep result order across requests', async () => {
  const original = globalThis.fetch;
  let requests = 0;
  try {
    globalThis.fetch = async (_, init) => {
      requests++;
      const body = JSON.parse(init.body);
      assert.ok(Object.keys(body.questions).length <= 32);
      return { ok: true, json: async () => ({ answers: Object.fromEntries(Object.keys(body.questions).map(key => [key, { type: 'noul', noul: 1 }])) }) };
    };
    const result = await new JevDecisionEngine({ enabled: true, apiKey: 'test' }).evaluateBatch(Array(37).fill('speech'));
    assert.equal(requests, 3);
    assert.equal(result.length, 37);
    assert.ok(result.every(item => item.is_valid && item.needs_translation && item.source === 'jev'));
  } finally { globalThis.fetch = original; }
});

test('Production refinement applies remote boundaries without mutating input and survives errors', async () => {
  const original = SK.safeSendMessage;
  const raw = segs(['we are done', 'now leave', 'together']);
  try {
    SK.safeSendMessage = async message => {
      assert.equal(message.type, 'EVALUATE_YT_BOUNDARIES');
      assert.equal(message.payload.segments.length, 3);
      return { ok: true, breakBefore: [null, true, false] };
    };
    const refined = await SK._refineAsrBoundaries(raw, { jevEnabled: true, jevApiKey: 'test' });
    assert.equal(refined[1].jevBreakBefore, true);
    assert.equal(raw[1].jevBreakBefore, undefined);
    assert.equal(SK._heuristicMergeAsr(refined, 'en').length, 2);
    SK.safeSendMessage = async () => { throw Error('background unavailable'); };
    assert.equal(await SK._refineAsrBoundaries(raw, { jevEnabled: true, jevApiKey: 'test' }), raw);
    SK.safeSendMessage = async () => { throw Error('must not request'); };
    assert.equal(await SK._refineAsrBoundaries(raw, { jevEnabled: true }), raw);
  } finally { SK.safeSendMessage = original; }
});

test('Semantic continuation cannot remove safety limits or join long silences', () => {
  const raw = segs(Array(70).fill('word'), Array(70).fill(false));
  const result = SK._heuristicMergeAsr(raw, 'en');
  assert.ok(result.length > 1);
  assert.ok(result.every(item => item.text.split(' ').length <= 30));
  assert.equal(result.flatMap(item => item.sourceSegs).length, raw.length);
  const gap = segs(['first', 'second'], [null, false]);
  gap[1].startMs = 10000;
  assert.equal(SK._heuristicMergeAsr(gap, 'en').length, 2);
});

test('Continuous two-second ASR fragments merge using speech end times', () => {
  const raw = [
    { text: 'When we started Mighty Car Mods we used', normText: 'a', startMs: 80, endMs: 4799 },
    { text: 'a Datsu Seor as our project car which', normText: 'b', startMs: 2159, endMs: 7200 },
    { text: 'on its release was the cheapest brand', normText: 'c', startMs: 4799, endMs: 9440 },
    { text: 'new car you could buy in Australia.', normText: 'd', startMs: 7200, endMs: 11679 },
  ];
  const result = SK._heuristicMergeAsr(raw, 'en');
  assert.ok(result.length < raw.length);
  assert.equal(result.flatMap(s => s.sourceSegs).length, raw.length);
  assert.equal(result.map(s => s.text).join(' '), raw.map(s => s.text).join(' '));
});
test('Real silence remains a boundary even with explicit speech durations', () => {
  const raw = [{text:'we are talking',normText:'a',startMs:0,endMs:2000},
    {text:'more words here',normText:'b',startMs:7000,endMs:9000}];
  assert.equal(SK._heuristicMergeAsr(raw, 'en').length, 2);
});
