import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { registerPageContextMenus, refreshPageContextMenu } from '../shinkansen/lib/page-context-menu.js';

test('One direct menu toggles translate/original and follows the active tab', async () => {
  const created = [], sent = [];
  const badges = new Map();
  let install, startup, click, activate, focus, slot = 1, activeTab = 5;
  globalThis.chrome = {
    i18n: { getMessage: key => key === 'contextTranslatePage' ? '翻譯本頁' : '顯示原文' },
    runtime: { onInstalled: { addListener: fn => { install = fn; } }, onStartup: { addListener: fn => { startup = fn; } } },
    contextMenus: { removeAll: async () => { created.length = 0; },
      create: (item, callback) => { created.push(item); callback(); },
      update: async (id, properties) => { Object.assign(created.find(item => item.id === id), properties); },
      onClicked: { addListener: fn => { click = fn; } } },
    action: { getBadgeText: async ({ tabId }) => badges.get(tabId) || '' },
    windows: { onFocusChanged: { addListener: fn => { focus = fn; } } },
    tabs: { query: async () => [{ id: activeTab }],
      onActivated: { addListener: fn => { activate = fn; } },
      sendMessage: async (...args) => { sent.push(args); badges.set(args[0], args[1].type === 'RESTORE_PAGE' ? '' : '●'); } },
  };
  try {
    registerPageContextMenus(async () => ({ popupButtonSlot: slot }));
    await install();
    assert.deepEqual(created.map(item => item.title), ['翻譯本頁']);
    assert.equal(created[0].parentId, undefined);
    assert(created.every(item => item.documentUrlPatterns.includes('https://*/*')));
    await startup();
    assert.equal(created.length, 1);
    await click({ menuItemId: 'shinkansen-page-action', frameId: 17 }, { id: 5 });
    assert.deepEqual(sent[0], [5, { type: 'TRANSLATE_PRESET', payload: { slot: 1, force: true, translateOnly: true } }, { frameId: 0 }]);
    assert.equal(created[0].title, '顯示原文');
    await click({ menuItemId: 'shinkansen-page-action' }, { id: 5 });
    assert.deepEqual(sent[1], [5, { type: 'RESTORE_PAGE' }, { frameId: 0 }]);
    assert.equal(created[0].title, '翻譯本頁');
    slot = 99;
    await click({ menuItemId: 'shinkansen-page-action' }, { id: 5 });
    assert.equal(sent[2][1].payload.slot, 2);
    activeTab = 7;
    await activate();
    assert.equal(created[0].title, '翻譯本頁');
    activeTab = 5;
    await focus();
    assert.equal(created[0].title, '顯示原文');
    badges.set(5, '');
    await refreshPageContextMenu();
    assert.equal(created[0].title, '翻譯本頁');
    await click({ menuItemId: 'other' }, { id: 5 });
    await click({ menuItemId: 'shinkansen-page-action' }, {});
    assert.equal(sent.length, 3);
  } finally { delete globalThis.chrome; }
});

test('Explicit translate does not cancel work in progress; shortcut still cancels', async () => {
  const source = fs.readFileSync(new URL('../shinkansen/content.js', import.meta.url), 'utf8');
  const start = source.indexOf('async function handleTranslatePreset(');
  const end = source.indexOf('SK.handleTranslatePreset =', start);
  let canceled = 0;
  const context = { STATE: { translating: true, abortController: new AbortController() },
    SK: { sendLog() {} }, abortInProgressTranslation: () => { canceled++; } };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nthis.run = handleTranslatePreset;', context);
  await context.run(2, { translateOnly: true, force: true });
  assert.equal(canceled, 0);
  await context.run(2);
  assert.equal(canceled, 1);
});

test('Manifest permission and both labels exist for every shipped locale', () => {
  const base = new URL('../shinkansen/', import.meta.url);
  assert(JSON.parse(fs.readFileSync(new URL('manifest.json', base))).permissions.includes('contextMenus'));
  for (const locale of fs.readdirSync(new URL('_locales/', base))) {
    const messages = JSON.parse(fs.readFileSync(new URL(`_locales/${locale}/messages.json`, base)));
    assert(messages.contextTranslatePage.message);
    assert(messages.contextShowOriginal.message);
  }
});

test('Show original cancels pending translation before restoring the page', () => {
  const source = fs.readFileSync(new URL('../shinkansen/content.js', import.meta.url), 'utf8');
  const handler = source.match(/if \(msg\?\.type === 'RESTORE_PAGE'\) \{([\s\S]*?)\n    \}/)[1];
  const steps = [];
  const context = { STATE: { translating: true },
    abortInProgressTranslation: () => steps.push('abort'),
    restorePage: () => steps.push('restore'), sendResponse: () => steps.push('respond') };
  vm.createContext(context);
  vm.runInContext('this.run = () => {' + handler + '};', context);
  context.run();
  assert.deepEqual(steps, ['abort', 'restore', 'respond']);
  steps.length = 0;
  context.STATE.translating = false;
  context.run();
  assert.deepEqual(steps, ['restore', 'respond']);
});
