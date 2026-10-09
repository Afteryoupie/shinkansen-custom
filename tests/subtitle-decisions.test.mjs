import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { LayaDecisionEngine } from '../shinkansen/lib/jev.js';
import { runSubtitleDecisionPipeline, runAsrDecisionPipeline, subtitleRepairPrompt } from '../shinkansen/lib/subtitle-decisions.js';
import { createTranslatePipeline } from '../shinkansen/lib/translate-pipeline.js';

const settings = { targetLanguage: 'zh-TW', ytSubtitle: { jevEnabled: true } };
const keep = { is_valid: true, needs_translation: true };
const validFormat = { needs_repair: false, source: 'laya' };
const badFormat = { needs_repair: true, reason: 'format', source: 'laya' };
function mockEngine(verdicts, reviews = []) {
  let n = 0;
  return { lastError: null, evaluateBatch: async texts => verdicts || texts.map(() => keep),
    reviewFormatBatch: async texts => reviews[n++] || texts.map(() => validFormat) };
}

test('Filtering preserves positions, names and target text and excludes only deliberate noise', async () => {
  const calls = [], commits = [];
  const engine = mockEngine([keep, {is_valid: false}, {is_valid: true, needs_translation: false}, keep]);
  const res = await runSubtitleDecisionPipeline({texts: ['Hi', '[music]', 'BMW M3', 'Bye'], sourceLanguage: 'en'}, settings,
    async payload => { calls.push(payload); return {result: ['你好', '再見'], usage: {inputTokens: 8}, commitSubtitleCache: async values => commits.push(values)}; }, {engine});
  assert.deepEqual(calls[0].texts, ['Hi', 'Bye']);
  assert.equal(calls[0].deferSubtitleCache, true);
  assert.deepEqual(res.result, ['你好', '', 'BMW M3', '再見']);
  assert.deepEqual(res.intentionalEmpty, [1]);
  assert.deepEqual(res.preservedIndices, [2]);
  assert.deepEqual(commits, [['你好', '再見']]);
  assert.equal(res.commitSubtitleCache, undefined);
});

test('All skipped rows avoid translation and format review', async () => {
  let calls = 0;
  const res = await runSubtitleDecisionPipeline({texts: ['[music]', 'BMW M3']}, settings,
    async () => { calls++; }, {engine: mockEngine([{is_valid:false}, {is_valid:true,needs_translation:false}])});
  assert.deepEqual(res.result, ['', 'BMW M3']);
  assert.equal(calls, 0);
});

test('Format repair submits only bad rows once, bypasses cache and aggregates usage', async () => {
  const calls = [];
  const engine = mockEngine(null, [[validFormat, badFormat], [validFormat]]);
  const res = await runSubtitleDecisionPipeline({texts: ['one', 'two']}, settings, async payload => {
    calls.push(payload); return {result: calls.length === 1 ? ['一', '```二```'] : ['二'], usage: {inputTokens: 3}};
  }, {engine});
  assert.deepEqual(res.result, ['一', '二']);
  assert.equal(res.usage.inputTokens, 6);
  assert.deepEqual(calls[1].texts, ['two']);
  assert.equal(calls[1].skipCache, true);
  assert.equal(calls[1].decisionRepair[0].reason, 'format');
  assert.equal(res.decisionReport.repaired, 1);
});

test('Persistent malformed output is rejected after one repair and never committed to cache', async () => {
  let calls = 0;
  const committed = [];
  const res = await runSubtitleDecisionPipeline({texts: ['one']}, settings, async () => {
    calls++; return {result: ['```壞格式```'], commitSubtitleCache: async values => committed.push(values)};
  }, {engine: mockEngine(null, [[badFormat], [badFormat]])});
  assert.equal(calls, 2);
  assert.deepEqual(res.result, [null]);
  assert.deepEqual(res.decisionRejected, [0]);
  assert.deepEqual(committed, [[null]]);
});

test('A failed repair retains good rows without a second repair pass', async () => {
  let calls = 0;
  const engine = new LayaDecisionEngine();
  const res = await runSubtitleDecisionPipeline({texts: ['one', 'two']}, settings, async () => {
    if (++calls > 1) throw new Error('offline');
    return {result: ['一', null]};
  }, {engine});
  assert.deepEqual(res.result, ['一', null]);
  assert.equal(res.decisionReport.unresolved, 1);
  assert.deepEqual(res.decisionReport.errors, ['offline']);
});

test('Wrong segment counts are retried without guessing positional alignment', async () => {
  let calls = 0;
  const res = await runSubtitleDecisionPipeline({texts: ['one', 'two']}, settings, async () => ({
    result: ++calls === 1 ? ['合併錯位'] : ['一', '二'],
  }), {engine: new LayaDecisionEngine()});
  assert.deepEqual(res.result, ['一', '二']);
  assert.equal(calls, 2);
});

test('Properly formatted mistranslations are not semantically judged', async () => {
  let calls = 0;
  const engine = new LayaDecisionEngine();
  const res = await runSubtitleDecisionPipeline({texts: ['This car has 180 horsepower.']}, settings,
    async () => { calls++; return {result: ['這輛車有300匹馬力']}; }, {engine});
  assert.equal(calls, 1);
  assert.deepEqual(res.result, ['這輛車有300匹馬力']);
  assert.deepEqual(engine.fallbackReviewFormat('Hello there'), {needs_repair:false,reason:null,source:'fallback'});
});

test('Disabled decisions preserve the existing translation path', async () => {
  const input = {texts: ['Hello']}, response = {result:['你好']};
  const res = await runSubtitleDecisionPipeline(input, {ytSubtitle:{jevEnabled:false}}, async payload => {
    assert.equal(payload, input); return response;
  });
  assert.equal(res, response);
});

test('Unavailable Laya retains dialogue and logs fallback instead of failing translation', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => { throw new Error('offline'); };
    const res = await runSubtitleDecisionPipeline({texts:['Hello']}, settings, async () => ({result:['你好']}));
    assert.deepEqual(res.result, ['你好']);
    assert.deepEqual(res.decisionReport.errors, ['offline']);
  } finally { globalThis.fetch = original; }
});

test('Laya cannot discard ordinary speech even with a confident noise classification', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ok:true,json:async()=>({answers:{valid_0:{type:'noul',noul:0},needs_0:{type:'noul',noul:1}}})});
    const res = await new LayaDecisionEngine({enabled:true}).evaluateBatch(['Hello, hello!']);
    assert.equal(res[0].is_valid, true);
    assert.equal(res[0].needs_translation, true);
  } finally { globalThis.fetch = original; }
});

test('A confident no-translation decision can preserve text when the noise decision is uncertain', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ok:true,json:async()=>({answers:{valid_0:{type:'noul',noul:.5},needs_0:{type:'noul',noul:.01}}})});
    const res = await new LayaDecisionEngine({enabled:true}).evaluateBatch(['Mighty Car Mods'],'zh-TW','en');
    assert.equal(res[0].is_valid,true);
    assert.equal(res[0].needs_translation,false);
  } finally { globalThis.fetch = original; }
});

test('Japanese Han text remains translatable while reliable target-language metadata and model labels can be preserved', () => {
  const engine = new LayaDecisionEngine();
  assert.equal(engine.fallbackEvaluate('東京駅','zh-TW','ja').needs_translation, true);
  assert.equal(engine.fallbackEvaluate('東京駅','zh-TW','auto').needs_translation, true);
  assert.equal(engine.fallbackEvaluate('你好','zh-TW','zh-TW').needs_translation, false);
  assert.equal(engine.fallbackEvaluate('你好','zh-TW','zh-CN').needs_translation, true);
  assert.equal(engine.fallbackEvaluate('BMW M3','zh-TW','en').needs_translation, false);
  assert.equal(engine.fallbackEvaluate('We can buy an AT1 car','zh-TW','en').needs_translation, true);
});

test('Format client sends the dedicated task and checks only eligible output rows', async () => {
  const original = globalThis.fetch;
  try {
    let calls = 0;
    globalThis.fetch = async (_, init) => {
      calls++;
      const request = JSON.parse(init.body);
      assert.equal(request.state.task, 'subtitle_format');
      assert.equal(request.state.pairs.length, 1);
      return {ok:true,json:async()=>({answers:{error_0:{type:'noul',noul:.99}}})};
    };
    const res = await new LayaDecisionEngine({enabled:true}).reviewFormatBatch(['a','b'],['正常譯文','```壞格式```']);
    assert.ok(res.every(review => review.needs_repair));
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test('ASR filtering preserves original IDs and explicit empty boundaries', async () => {
  const calls = [];
  const res = await runAsrDecisionPipeline({texts:['1|Hello\n2|[music]\n3|BMW M3\n4|Bye'],sourceLanguage:'en'}, settings,
    async payload => { calls.push(payload); return {result:[`1-1|${calls.length === 1 ? '你好' : '再見'}`]}; },
    {engine:mockEngine([keep,{is_valid:false},{is_valid:true,needs_translation:false},keep])});
  assert.deepEqual(calls.map(call=>call.texts[0]), ['1|Hello','1|Bye']);
  assert.deepEqual(res.result, ['1-1|你好\n2-2|\n3-3|BMW M3\n4-4|再見']);
  assert.deepEqual(res.asrIntentionalEmpty,[1]);
  assert.deepEqual(res.asrPreservedIndices,[2]);
});

test('ASR missing ranges get one cache-bypassing format repair', async () => {
  const calls = [];
  const res = await runAsrDecisionPipeline({texts:['1|Hello\n2|there']}, settings, async payload => {
    calls.push(payload); return {result:[calls.length === 1 ? '1-1|你好' : '1-2|你好']};
  }, {engine:mockEngine()});
  assert.equal(calls.length,2);
  assert.equal(calls[1].skipCache,true);
  assert.deepEqual(res.result,['1-2|你好']);
});

test('ASR format repair applies only to the bad output range and keeps good ranges', async () => {
  const calls = [];
  const res = await runAsrDecisionPipeline({texts:['1|Hello\n2|Bye']}, settings, async payload => {
    calls.push(payload); return {result:[calls.length === 1 ? '1-1|你好\n2-2|```再見```' : '1-1|再見']};
  }, {engine:mockEngine(null,[[validFormat,badFormat],[validFormat]])});
  assert.deepEqual(calls[1].texts,['1|Bye']);
  assert.deepEqual(res.result,['1-1|你好\n2-2|再見']);
});

test('Persistently incomplete ASR output is bounded and cannot shift the timeline', async () => {
  let calls=0;
  const res=await runAsrDecisionPipeline({texts:['1|Hello\n2|there']},settings,async()=>{
    calls++;return {result:['1-1|你好']};
  },{engine:mockEngine()});
  assert.equal(calls,2);
  assert.equal(res.ok,false);
  assert.equal(res.decisionReport.unresolved,1);
});

test('Correction prompt requests format repair and never includes a semantic verdict', () => {
  const prompt=subtitleRepairPrompt('Original subtitle instructions',{decisionRepair:[{translation:'```你好```',reason:'format'}]});
  assert.match(prompt,/original output format/);
  assert.match(prompt,/malformed/);
  assert.doesNotMatch(prompt,/incorrect meaning|omitted speech|wrong target language/);
});

test('The production background wrapper normalizes raw translator results and calls the shared pipeline', async () => {
  const source=fs.readFileSync(new URL('../shinkansen/background.js',import.meta.url),'utf8');
  const start=source.indexOf('async function applyJevSubtitleFilter('),end=source.indexOf('// ─── 訊息路由',start);
  const context={runSubtitleDecisionPipeline,runAsrDecisionPipeline,debugLog:()=>{}};
  vm.createContext(context);vm.runInContext(source.slice(start,end)+'\nthis.apply=applyJevSubtitleFilter;',context);
  const response=await context.apply({texts:['[music]','BMW M3']},settings,async()=>{throw new Error('No translation expected');});
  assert.deepEqual(response.result,['','BMW M3']);
});

test('The real translation cache defers writes and stores only approved output', async () => {
  const writes=[];
  const pipeline=createTranslatePipeline({
    cache:{getBatch:async texts=>texts.map(()=>null),setBatch:async (...args)=>writes.push(args)},usageDB:{},debugLog:()=>{},
    buildFixedGlossaryEntries:()=>[],preferArticleGlossaryEntries:values=>values,mergeExtraForbiddenTerms:()=>[],
    buildCacheKeySuffix:async()=> '_subtitle',logWebBatchUsage:async()=>false,detectForbiddenTermLeaks:()=>[],
    filterEchoPairsForCache:(texts,translations)=>({texts,translations,skipped:0}),
  });
  const response=await pipeline.runTranslatePipeline({payload:{texts:['one','two'],deferSubtitleCache:true},
    settings:{targetLanguage:'zh-TW'},sender:{},isWebPath:false,logLabel:'test',cachedRate:1,
    translate:async()=>({translations:['```壞格式```','二'],usage:{inputTokens:1,outputTokens:2}})});
  assert.deepEqual(writes,[]);
  await response.commitSubtitleCache([null,'二']);
  assert.deepEqual(writes,[[['two'],['二'],'_subtitle']]);
});
