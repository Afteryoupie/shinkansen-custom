import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Drive the public activation entry and the real content messaging helper.
// No SK.sendMessage shim: production only defines safeSendMessage.
export function activationHarness(saved, sendMessage) {
  const noop = () => {};
  const logs = [];
  const SK = { sendLog: (...args) => logs.push(args), isExtensionContextAlive: () => true,
    STATE: { targetLanguage: 'zh-TW' }, t: key => key, showToast: noop, hideToast: noop };
  const root = { className: 'ytp-caption-window-container', classList: { add: noop, remove: noop, toggle: noop },
    querySelectorAll: () => [], querySelector: () => null };
  const window = { __SK: SK, addEventListener: noop, removeEventListener: noop, dispatchEvent: noop };
  const event = { addListener: noop };
  const browser = { runtime: { sendMessage }, storage: { sync: { get: async () => saved }, onChanged: event } };
  const context = vm.createContext({ window, browser, navigator: { userAgent: 'test' },
    document: { body: root, addEventListener: noop, querySelectorAll: () => [],
      querySelector: selector => ['#movie_player', '.ytp-caption-window-container'].includes(selector) ? root : null,
      getElementById: () => ({}) },
    MutationObserver: class { observe() {} disconnect() {} }, CustomEvent: class { constructor(type) { this.type = type; } },
    location: { hostname: 'www.youtube.com', pathname: '/watch', href: 'https://www.youtube.com/watch?v=JjHD7igpCSU' },
    setTimeout: () => 1, clearTimeout: noop, setInterval: () => 1, clearInterval: noop, URL, console });
  const ns = fs.readFileSync(new URL('../shinkansen/content-ns.js', import.meta.url), 'utf8');
  const start = ns.indexOf('  SK.safeSendMessage =');
  vm.runInContext('(function(SK) {' + ns.slice(start, ns.indexOf('  // ─── 共用常數', start)) + '})(window.__SK);', context);
  vm.runInContext(fs.readFileSync(new URL('../shinkansen/content-youtube.js', import.meta.url), 'utf8'), context);
  return { SK, logs };
}

test('First YouTube activation reaches activated and sends warmup through the production helper', async () => {
  const messages = [];
  const saved = { ytSubtitle: { engine: 'openai-compat-local', preferOriginalTrack: false, debugToast: false },
    displayMode: 'single', targetLanguage: 'zh-TW' };
  const { SK, logs } = activationHarness(saved, async message => { messages.push(message); return { ok: true }; });
  assert.equal(SK.sendMessage, undefined);
  await new Promise(resolve => setImmediate(resolve));
  // Watch page entry warms up immediately even before translateYouTubeSubtitles is called.
  assert.equal(messages.filter(m => m.type === 'WARMUP_YT_TRANSLATION').length, 1);
  await SK.translateYouTubeSubtitles();
  assert.equal(messages.filter(m => m.type === 'WARMUP_YT_TRANSLATION').length >= 1, true);
  assert.equal(logs.some(([, , message]) => message === 'activated'), true);
  assert.equal(SK.YT.active, true);
});

test('A failed model warmup is reported without breaking YouTube activation', async () => {
  const { SK, logs } = activationHarness({ ytSubtitle: { engine: 'openai-compat-local', preferOriginalTrack: false } },
    async () => { throw Error('offline'); });
  await SK.translateYouTubeSubtitles();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(logs.some(([, , message]) => message === 'activated'), true);
  assert.equal(logs.some(([, , message]) => message === 'local model warmup failed'), true);
});

test('Orphan content script after extension reload does not throw unhandled rejection on getYtConfig', async () => {
  const { SK } = activationHarness({ ytSubtitle: { engine: 'openai-compat-local' } }, async () => ({ ok: true }));
  SK.isExtensionContextAlive = () => false;
  SK.YT.config = null;
  const cfg = await SK._getYtConfig();
  assert.equal(cfg.windowSizeS, 30);
});
