import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { translateSingleBlock, translateDocument } from '../shinkansen/translate-doc/translate.js';
import { resolveProviderProfiles, activeProvider, inferProviderType, providerSettings } from '../shinkansen/lib/custom-provider-profiles.js';
import { DEFAULT_SETTINGS, getSettings, setSettings } from '../shinkansen/lib/storage.js';
import { sanitizeImport } from '../shinkansen/options/import-sanitize.js';
import { isLocalSubtitleProvider } from '../shinkansen/lib/local-subtitle.js';

test('Legacy online and local settings retain credentials only in their own profile', () => {
  for (const [type, baseUrl] of [['online', 'https://api.example.com/v1'], ['local', 'http://127.0.0.1:8080/v1']]) {
    const state = resolveProviderProfiles({ customProvider: { baseUrl, model: 'chosen', temperature: null },
      translatePresets: [{ slot: 2, engine: 'openai-compat', model: 'preset' }] },
    DEFAULT_SETTINGS.customProvider, { customProviderApiKey: 'private-key' });
    assert.equal(state.activeType, type);
    assert.equal(state.profiles[type].model, 'chosen');
    assert.equal(state.profiles[type].temperature, null);
    assert.equal(state.keys[type], 'private-key');
    assert.equal(state.keys[type === 'online' ? 'local' : 'online'], '');
    assert.equal(state.profiles[type === 'online' ? 'local' : 'online'].model, '');
  }
  assert.equal(inferProviderType('https://localhost.example.com/v1'), 'online');
  assert.equal(inferProviderType('http://192.168.1.4:8080/v1'), 'local');
});

test('Switching independent configurations preserves models, prompts, prices and keys', () => {
  const state = resolveProviderProfiles({ customProviderType: 'online',
    customProviderOnline: { baseUrl: 'https://api.example.com/v1', model: 'cloud', systemPrompt: 'Cloud prompt', inputPerMTok: 2 },
    customProviderLocal: { baseUrl: 'http://192.168.1.4:8080/v1', model: 'local', systemPrompt: 'Local prompt', inputPerMTok: 0 },
  }, DEFAULT_SETTINGS.customProvider, { customProviderApiKeys: { online: 'cloud-key', local: '' }, customProviderApiKey: 'stale-key' });
  assert.equal(activeProvider(state).apiKey, 'cloud-key');
  state.activeType = 'local';
  assert.equal(activeProvider(state).apiKey, '');
  assert.equal(activeProvider(state).model, 'local');
  assert.equal(activeProvider(state).systemPrompt, 'Local prompt');
  assert.equal(isLocalSubtitleProvider(activeProvider(state)), true);
  state.activeType = 'online';
  assert.equal(activeProvider(state).model, 'cloud');
  assert.equal(activeProvider(state).inputPerMTok, 2);
  assert.equal(isLocalSubtitleProvider(activeProvider(state)), false);
});

test('Import retains both configurations and removes credentials and invalid values', () => {
  const raw = { customProviderType: 'online', customProviderOnline: {
    baseUrl: 'https://api.example.com/v1', model: 'cloud', apiKey: 'private', temperature: null,
    presetModels: { 1: 'custom', 2: null }, fetchTimeoutSec: 90, cachedDiscount: null,
  }, customProviderLocal: { baseUrl: 'http://127.0.0.1:8080/v1', apiKey: 'local-private',
    inputPerMTok: Infinity, thinkingLevel: 'invalid', temperature: 0 }, customProviderApiKeys: { online: 'private' } };
  const { clean, warnings } = sanitizeImport(raw, key => key);
  assert.equal(clean.customProviderType, 'online');
  assert.equal(clean.customProviderOnline.model, 'cloud');
  assert.equal(clean.customProviderOnline.temperature, null);
  assert.equal(clean.customProviderLocal.temperature, 0);
  assert(!('inputPerMTok' in clean.customProviderLocal));
  assert(!JSON.stringify(clean).includes('private'));
  assert.equal(warnings.length, 2);
});

test('Production settings reader selects the active profile and its local key', async () => {
  const sync = { customProviderType: 'online', localModelSelectionsSaved: true,
    customProvider: { baseUrl: 'http://127.0.0.1:8080/v1', model: 'old' },
    customProviderOnline: { baseUrl: 'https://api.example.com/v1', model: 'cloud' },
    customProviderLocal: { baseUrl: 'http://127.0.0.1:8080/v1', model: 'local' } };
  const local = { customProviderApiKeys: { online: 'online-key', local: 'local-key' } };
  const area = values => ({
    get: async keys => keys === null ? structuredClone(values) : Object.fromEntries((Array.isArray(keys) ? keys : [keys])
      .filter(key => key in values).map(key => [key, structuredClone(values[key])])),
    set: async patch => Object.assign(values, patch), remove: async () => {},
  });
  globalThis.chrome = { storage: { sync: area(sync), local: area(local) } };
  try {
    let settings = await getSettings();
    assert.equal(settings.customProvider.model, 'cloud');
    assert.equal(settings.customProvider.apiKey, 'online-key');
    sync.customProviderType = 'local';
    settings = await getSettings();
    assert.equal(settings.customProvider.model, 'local');
    assert.equal(settings.customProvider.apiKey, 'local-key');
    const online = providerSettings(settings, 'openai-compat-online');
    const localSelected = providerSettings(settings, 'openai-compat-local');
    assert.equal(online.customProvider.model, 'cloud');
    assert.equal(online.customProvider.apiKey, 'online-key');
    assert.equal(localSelected.customProvider.model, 'local');
    assert.equal(localSelected.customProvider.apiKey, 'local-key');
    await setSettings({ customProvider: { apiKey: 'updated-key', model: 'updated-local' } });
    settings = await getSettings();
    assert.equal(settings.customProvider.apiKey, 'updated-key');
    assert.equal(settings.customProvider.model, 'updated-local');
    assert(!JSON.stringify(sync).includes('updated-key'));
  } finally { delete globalThis.chrome; }
});

test('Both custom translation choices survive settings import independently', () => {
  const { clean } = sanitizeImport({
    translatePresets: [
      { slot: 1, engine: 'openai-compat-online', model: null, label: 'Online' },
      { slot: 2, engine: 'openai-compat-local', model: 'local-model', label: 'Local' },
    ], ytSubtitle: { engine: 'openai-compat-online' },
  }, key => key);
  assert.equal(clean.translatePresets[0].engine, 'openai-compat-online');
  assert.equal(clean.translatePresets[1].engine, 'openai-compat-local');
  assert.equal(clean.translatePresets[1].model, 'local-model');
  assert.equal(clean.ytSubtitle.engine, 'openai-compat-online');
});

test('Legacy backups replace the matching profile on an upgraded installation', () => {
  const { clean } = sanitizeImport({ customProvider: { baseUrl: 'https://api.example.com/v1', model: 'restored' } }, key => key);
  const state = resolveProviderProfiles({ customProviderType: 'local',
    customProviderOnline: { model: 'previous' }, ...clean }, DEFAULT_SETTINGS.customProvider);
  assert.equal(activeProvider(state).model, 'restored');
});

test('Subtitle and glossary routing recognize both custom choices', () => {
  const source = fs.readFileSync(new URL('../shinkansen/content-ns.js', import.meta.url), 'utf8');
  const context = { SK: {} };
  for (const name of ['getSubtitleBatchType', 'getGlossaryExtractType']) {
    const body = source.match(new RegExp(`SK\\.${name} = function ${name}\\([^]*?\\n  };`))[0];
    vm.runInNewContext(body, context);
  }
  for (const engine of ['openai-compat-online', 'openai-compat-local', 'openai-compat']) {
    assert.equal(context.SK.getSubtitleBatchType(engine, false), 'TRANSLATE_SUBTITLE_BATCH_CUSTOM');
    assert.equal(context.SK.getSubtitleBatchType(engine, true), 'TRANSLATE_ASR_SUBTITLE_BATCH_CUSTOM');
    assert.equal(context.SK.getGlossaryExtractType(engine), 'EXTRACT_GLOSSARY_CUSTOM');
  }
  assert.equal(context.SK.getSubtitleBatchType('google', false), 'TRANSLATE_SUBTITLE_BATCH_GOOGLE');
});

test('Document retry sends the selected custom source to the production handler', async () => {
  const messages = [];
  globalThis.chrome = { runtime: { sendMessage: async message => {
    messages.push(message);
    return { ok: true, result: ['你好'], usage: {} };
  } } };
  try {
    for (const engine of ['openai-compat-online', 'openai-compat-local']) {
      const block = { blockId: 'paragraph', type: 'paragraph', plainText: 'Hello' };
      await translateSingleBlock(block, { engine });
      const message = messages.findLast(m => m.type === 'TRANSLATE_DOC_BATCH_CUSTOM');
      assert.equal(message.payload.engine, engine);
      assert.equal(block.translation, '你好');
    }
  } finally { delete globalThis.chrome; }
});

test('Document batch keeps its online or local source and selected model', async () => {
  const messages = [];
  globalThis.chrome = { runtime: { sendMessage: async message => {
    messages.push(message);
    return { ok: true, result: ['你好'], usage: {} };
  } } };
  try {
    for (const engine of ['openai-compat-online', 'openai-compat-local']) {
      const block = { blockId: engine, type: 'paragraph', plainText: 'Hello', readingOrder: 1 };
      const doc = { pages: [{ blocks: [block] }], meta: { filename: 'test.pdf' } };
      await translateDocument(doc, { engine, modelOverride: 'chosen-model' });
      const message = messages.findLast(m => m.type === 'TRANSLATE_DOC_BATCH_CUSTOM');
      assert.equal(message.payload.engine, engine);
      assert.equal(message.payload.modelOverride, 'chosen-model');
      assert.equal(block.translation, '你好');
    }
  } finally { delete globalThis.chrome; }
});
