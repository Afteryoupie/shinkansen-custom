// Run against the selected Apple translation backend on the watchdog's 8080 port.
import assert from 'node:assert/strict';

globalThis.browser = {
  storage: {
    sync: { get: async () => ({}), set: async () => {} },
    local: { get: async () => ({}), set: async () => {} },
    onChanged: { addListener() {} },
  },
  runtime: { getURL: path => path },
};
const { translateBatch } = await import('../shinkansen/lib/openai-compat.js');
const original = [
  'The train arrives at the station at nine tomorrow morning.',
  'Please save your work before restarting the computer.',
  'This translation runs locally on your Mac.',
  'Mixed-precision ⟦0⟧4-bit⟦/0⟧ MLX quantization of ⟦1⟧IFM/K2-Horizon-3.7B⟦/1⟧, converted from revision 943ce4e.',
  'This dense model uses 6.5 bits per weight and has a 512K (524,288-token) context window.',
  'Peak memory is 4.3 GB. The KV cache adds 144 KB per token.',
  '4.1 GB',
  'K2-Horizon-3.7B-4bit',
];
const settings = {
  targetLanguage: 'zh-TW',
  appleWebTranslation: true,
  maxUnitsPerBatch: Number(process.env.APPLE_BATCH_SIZE || 2),
  maxCharsPerBatch: 3500,
  customProvider: {
    baseUrl: 'http://127.0.0.1:8080/v1',
    model: 'Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M',
    systemPrompt: '將原文翻譯為台灣繁體中文，僅輸出譯文。保留分隔符號、段落與序號標記。',
    temperature: 0,
    thinkingLevel: 'auto',
    fetchTimeoutSec: 90,
    useStrongSegMarker: true,
  },
};
const requests = [];
const fetchImpl = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  if (String(url).endsWith('/chat/completions')) requests.push(JSON.parse(options.body));
  return fetchImpl(url, options);
};
const started = Date.now();
const result = await translateBatch(original, settings, [], [{ source: '4-bit', target: '4位元' }], []);
assert.equal(result.translations.length, original.length);
for (const text of result.translations.slice(0, 6)) {
  assert.match(text, /\p{Script=Han}/u);
  assert.doesNotMatch(text, /Error:|SHINKANSEN_SEG|Exceeded context/i);
}
assert.equal(requests.length, 6, 'Numeric units and model IDs must avoid model requests');
assert.equal(result.translations[6], original[6]);
assert.equal(result.translations[7], original[7]);
assert.match(result.translations[3], /⟦0⟧4位元⟦\/0⟧/);
assert.match(result.translations[3], /⟦1⟧IFM\/K2-Horizon-3\.7B⟦\/1⟧/);
assert.match(result.translations[3], /943ce4e/);
assert.match(result.translations[4], /權重/);
assert.match(result.translations[4], /524,288/);
assert.doesNotMatch(result.translations[4], /字元|重量/);
assert.match(result.translations[5], /記憶體/);
assert.match(result.translations[5], /4\.3 GB/);
for (const request of requests) {
  assert.equal(request.model, settings.customProvider.model);
  assert.ok(request.messages[0].content.length < 1000);
}
console.log(JSON.stringify({ elapsedMs: Date.now() - started, requests: requests.length, original, ...result }, null, 2));
