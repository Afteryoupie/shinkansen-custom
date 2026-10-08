import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../shinkansen/content-youtube.js', import.meta.url), 'utf8');
function setup(units, send, playerRoot = null) {
  const noop = () => {};
  const SK = { sendLog: noop, sanitizeMarkers: s => s, getSubtitleBatchType: () => 'TEST',
    STATE: { targetLanguage: 'zh-TW' }, safeSendMessage: send, i18n: { bgErrorMessage: () => 'failed' },
    ASR_LAST_CUE_FALLBACK_MS: 1500, ASR_WINDOW_MAX_TAIL_EXTEND_MS: 12000, ASR_CUE_MAX_CHARS: 40, ASR_CUE_MIN_PIECE_MS: 1200, t: k => k, showToast: noop };
  vm.runInNewContext(source, { window: { __SK: SK, addEventListener: noop },
    document: { addEventListener: noop, querySelector: selector => selector === '#movie_player' ? playerRoot : null }, navigator: { userAgent: 'test' },
    browser: { storage: { onChanged: { addListener: noop }, sync: { get: async () => ({}) } } },
    location: { hostname: 'www.youtube.com', pathname: '/watch', href: 'https://www.youtube.com/watch?v=hcZLknUGT24' },
    setTimeout, clearTimeout, setInterval, clearInterval, URL, console });
  Object.assign(SK.YT, { active: true, isAsr: true, captionLang: 'en',
    config: { engine: 'google', targetLanguage: 'zh-TW' }, videoEl: null,
    rawSegments: [{ text: 'Hello', normText: 'hello', startMs: 0 }], bgQueue: units });
  return SK;
}
function unit(text, startMs, keys = [text.toLowerCase()]) {
  return { text, keys, _cue: { startMs, endMs: startMs + 2000, sourceText: text, segStarts: [startMs] } };
}
test('Repeated dialogue gets its own cue despite identical source key', async () => {
  const SK = setup([unit('>> Yeah.', 233840), unit('>> Yeah.', 658000)], async () => ({ ok: true, result: ['對'] }));
  await SK._startBackgroundTranslationWorker();
  assert.equal(SK.YT.displayCues.length, 2);
  assert.equal(SK._findActiveCue(659000).targetText, '對');
});
test('Shared first fragment cannot suppress a different merged sentence', async () => {
  const SK = setup([unit('Yes first sentence', 0, ['yes', 'first']), unit('Yes different sentence', 60000, ['yes', 'different'])],
    async ({ payload }) => ({ ok: true, result: [payload.texts[0].includes('different') ? '另一句' : '第一句'] }));
  await SK._startBackgroundTranslationWorker();
  assert.equal(SK._findActiveCue(61000).targetText, '另一句');
});
test('Temporary failure retries with cache bypass before completing the cue', async () => {
  const calls = [];
  const SK = setup([unit('Hello', 0)], async ({ payload }) => { calls.push(payload); return calls.length === 1 ? { ok: false } : { ok: true, result: ['你好'] }; });
  await SK._startBackgroundTranslationWorker();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].skipCache, true);
  assert.equal(SK.YT.displayCues[0].targetText, '你好');
});
test('Short pronouns and final conjunctions stay in their own subtitle', async () => {
  const replies = ['我', '因為'];
  const SK = setup([unit('Me', 0), unit('Because', 3000)], async () => ({ ok: true, result: [replies.shift()] }));
  await SK._startBackgroundTranslationWorker();
  assert.deepEqual(Array.from(SK.YT.displayCues, c => c.targetText), ['我', '因為']);
});
test('Untranslated output is retried; persistent failure does not poison caption cache', async () => {
  let calls = 0;
  const SK = setup([unit('Hello', 0)], async () => { calls++; return { ok: true, result: ['Hello'] }; });
  await SK._startBackgroundTranslationWorker();
  assert.equal(calls, 2);
  assert.equal(SK.YT.captionMap.size, 0);
  assert.equal(SK.YT.displayCues.length, 0);
});
test('Source switch prevents late background results from changing new subtitles', async () => {
  const SK = setup([unit('Hello', 0)], async () => { SK.YT.captionSourceGen++; return { ok: true, result: ['你好'] }; });
  await SK._startBackgroundTranslationWorker();
  assert.equal(SK.YT.captionMap.size, 0);
  assert.equal(SK.YT.displayCues.length, 0);
});
test('Local model does not start full-track worker competing with playback windows', async () => {
  let calls = 0;
  const SK = setup([unit('Hello', 0)], async () => { calls++; return {ok:true,result:['你好']}; });
  Object.assign(SK.YT.config, {engine:'openai-compat',localModel:true});
  await SK._startBackgroundTranslationWorker();
  assert.equal(calls, 0);
  assert.equal(SK.YT.bgWorkerRunning, false);
  assert.equal(SK.YT.bgQueue.length, 1);
});
test('Jev boundary copies mark original window segments complete', async () => {
  const SK = setup([], async ({type,payload}) => type === 'EVALUATE_YT_BOUNDARIES'
    ? {ok:true,breakBefore:[null,false]} : {ok:true,result:payload?.texts?.map(()=>'完整譯文')||[]});
  Object.assign(SK.YT.config, {asrMode:'heuristic',jevEnabled:true,jevApiKey:'test'});
  SK.YT.rawSegments = [{text:'a complete sentence',normText:'a complete sentence',startMs:0,endMs:3000},
    {text:'continued here.',normText:'continued here.',startMs:2000,endMs:4000}];
  await SK.translateWindowFrom(0);
  assert.equal(SK.YT.translatedWindows.has(0), true);
  assert.equal(SK.YT.displayCues[0].targetText, '完整譯文');
  assert.equal(SK.YT.rawSegments[1].jevBreakBefore, undefined);
});
test('Lowercase car model labels survive language validation', async () => {
  const source='at1 mini dolphin seagull essential.';
  const SK=setup([],async()=>({ok:true,result:[source]}));
  const result=await SK._translateSubtitleTexts([source], 'TEST', 0);
  assert.equal(result.result[0],source);
});
test('A sentence with an identifier is still rejected if echoed untranslated', async () => {
  const source='We can buy an AT1 car';
  const SK=setup([],async()=>({ok:true,result:[source]}));
  const result=await SK._translateSubtitleTexts([source], 'TEST', 0);
  assert.equal(result.result[0],null);
});
test('Native captions remain visible until a translated cue is ready', () => {
  const classes=new Set();
  const root={classList:{toggle:(name,on)=>on?classes.add(name):classes.delete(name)}};
  const SK=setup([],async()=>({ok:true}),root);
  SK._syncAsrNativeVisibility(null);
  assert.equal(classes.has('shinkansen-asr-ready'),false);
  SK._syncAsrNativeVisibility({targetText:'你好'});
  assert.equal(classes.has('shinkansen-asr-ready'),true);
  SK._syncAsrNativeVisibility(null);
  assert.equal(classes.has('shinkansen-asr-ready'),false);
});
