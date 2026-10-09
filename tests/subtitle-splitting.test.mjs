import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const ns = fs.readFileSync(new URL('../shinkansen/content-ns.js', import.meta.url), 'utf8');
const SK = {};
for (const key of ['ASR_CUE_MAX_CHARS', 'ASR_CUE_MIN_PIECE_MS']) {
  SK[key] = Number(ns.match(new RegExp(`SK\\.${key} = (\\d+)`))[1]);
}
const noop = () => {};
vm.runInNewContext(fs.readFileSync(new URL('../shinkansen/content-youtube.js', import.meta.url), 'utf8'), {
  window: { __SK: SK, addEventListener: noop }, document: { addEventListener: noop, querySelector: () => null },
  browser: { storage: { onChanged: { addListener: noop }, sync: { get: async () => ({}) } } },
  location: { hostname: 'www.youtube.com', pathname: '/watch', href: 'https://www.youtube.com/watch?v=BT7dKLwgfjg' },
  setTimeout, clearTimeout, setInterval, clearInterval, URL, console, Intl,
});
const compact = text => text.replace(/\s/g, '');
function verify(text, start, end, cues) {
  assert.equal(compact(cues.map(c => c.text).join('')), compact(text));
  assert.equal(cues[0].startMs, start);
  assert.equal(cues.at(-1).endMs, end);
  cues.forEach((c, i) => {
    assert(c.text.length > 0);
    assert(c.endMs > c.startMs);
    if (cues.length > 1) assert(c.endMs - c.startMs >= SK.ASR_CUE_MIN_PIECE_MS);
    if (i) assert.equal(c.startMs, cues[i-1].endMs);
  });
}
test('Screenshot sentence becomes short sequential cues without an orphan tail', () => {
  const text = '無限刃 至少這是我的推測 無論如何 它似乎可能會比平均的客製化線條刃重很多';
  // Synthetic timing: screenshot text is real, per-word video timestamps unavailable.
  const cues = SK.ASR.splitLongCue(387000, 395000, text, [389000, 392000]);
  verify(text, 387000, 395000, cues);
  assert(cues.length >= 2);
  assert(cues.every(c => c.text.length <= 24 && c.text.length >= 6));
  assert(!cues.some(c => c.text === '很多'));
  console.log('Screenshot preview:', cues.map(c => c.text));
});
test('Punctuation and whitespace are preferred over cutting a phrase', () => {
  const text = '這是第一段完整的說明 接下來是第二段完整的說明 最後是第三段完整的說明';
  const cues = SK.ASR.splitLongCue(0, 9000, text, [3000, 6000]);
  verify(text, 0, 9000, cues);
  assert(cues.every(c => c.text.length <= 24));
});
test('Short cue stays intact rather than flashing multiple pieces', () => {
  const text = '這是一段需要保留所有內容但是時間太短不能繼續切成更多字幕的說明';
  const cues = SK.ASR.splitLongCue(0, 1800, text, []);
  verify(text, 0, 1800, cues);
  assert.equal(cues.length, 1);
});
test('English words, model identifiers and emoji survive splitting', () => {
  for (const text of ['Infinity Blade is heavier than the average custom blade by a considerable margin',
    '這個 InfinityBladeX100 型號的設計相當特別 而且比其他款式更加厚重 很值得仔細觀察',
    '這個設計真的非常特別😀接下來我們會仔細看看不同零件組合的重量與外型變化']) {
    const cues = SK.ASR.splitLongCue(0, 12000, text, [2500, 5000, 7500, 10000]);
    verify(text, 0, 12000, cues);
    if (text.includes('InfinityBladeX100')) assert(cues.some(c => c.text.includes('InfinityBladeX100')));
    assert(!cues.some(c => /[\uD800-\uDBFF]$/.test(c.text)));
  }
});
test('Closely spaced onsets never create backwards or sub-minimum pieces', () => {
  const text = '這是需要拆分的字幕內容'.repeat(8);
  const cues = SK.ASR.splitLongCue(1000, 7300, text, [1050, 1100, 7200, 7290]);
  verify(text, 1000, 7300, cues);
});
