import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { bindLocalModelPicker } from '../shinkansen/options/local-model-picker.js';
import { migrateCustomProviderModelIfNeeded } from '../shinkansen/lib/storage.js';
import { sanitizeImport } from '../shinkansen/options/import-sanitize.js';

function controls(value = '') {
  class Control extends EventTarget {
    value = ''; hidden = false; disabled = false; options = [];
    replaceChildren(...options) { this.options = options; }
    add(option) { this.options.push(option); }
    setAttribute() {} removeAttribute() {}
  }
  const fields = Object.fromEntries(['baseUrl', 'input', 'select', 'refresh', 'clear', 'status', 'hint', 'apiKey']
    .map(key => [key, new Control()]));
  fields.baseUrl.value = 'http://127.0.0.1:8080/v1/chat/completions/';
  fields.input.value = value;
  const update = bindLocalModelPicker({ ...fields, t: key => key });
  return { ...fields, update };
}

test('Local selection reads endpoint IDs, hides aliases, and feeds existing save handlers', async () => {
  const original = { fetch: globalThis.fetch, Option: globalThis.Option };
  globalThis.Option = class { constructor(text, value) { Object.assign(this, { text, value }); } };
  globalThis.fetch = async url => {
    assert.equal(url, 'http://127.0.0.1:8080/v1/models');
    return Response.json({ data: [
      { id: 'Qwen', owned_by: 'local-llm' }, { id: 'Qwen' },
      { id: 'C:\\models\\Qwen.gguf', owned_by: 'local-llm' },
      { id: 'default', owned_by: 'local-llm' }, { id: 'org/Riva' },
    ] });
  };
  try {
    const c = controls('saved-model');
    await c.update();
    assert.equal(c.input.hidden, true);
    assert.equal(c.select.hidden, false);
    assert.deepEqual(c.select.options.map(o => o.value), ['', 'Qwen', 'org/Riva', 'saved-model']);
    assert.equal(c.select.value, 'saved-model');
    let notified = false;
    c.input.addEventListener('input', () => { notified = true; });
    c.select.value = 'org/Riva';
    c.select.dispatchEvent(new Event('change'));
    assert.equal(c.input.value, 'org/Riva');
    assert.equal(notified, true);
    c.clear.dispatchEvent(new Event('click'));
    assert.equal(c.input.value, '');
    assert.equal(c.select.value, '');
  } finally { Object.assign(globalThis, original); }
});

test('Failure preserves saved model and stale local responses cannot replace remote controls', async () => {
  const original = { fetch: globalThis.fetch, Option: globalThis.Option };
  globalThis.Option = class { constructor(text, value) { Object.assign(this, { text, value }); } };
  try {
    globalThis.fetch = async () => { throw Error('offline'); };
    const c = controls('saved-model');
    await c.update();
    assert.equal(c.select.value, 'saved-model');
    assert.equal(c.refresh.disabled, false);
    assert.equal(c.status.textContent, 'options.cp.localError');
    let resolve;
    globalThis.fetch = () => new Promise(r => { resolve = r; });
    const pending = c.update();
    c.baseUrl.value = 'https://api.example.com/v1';
    await c.update();
    resolve(Response.json({ data: [{ id: 'stale' }] }));
    await pending;
    assert.equal(c.input.hidden, false);
    assert.equal(c.select.hidden, true);
    assert.equal(c.input.value, 'saved-model');
    assert(!c.select.options.some(o => o.value === 'stale'));
  } finally { Object.assign(globalThis, original); }
});

test('Explicit Qwen choices survive legacy migration and settings export/import', async () => {
  const settings = { localModelSelectionsSaved: true,
    customProvider: { model: 'Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M' },
    translatePresets: [{ slot: 1, engine: 'openai-compat', model: 'Qwen3VL-8B', label: 'Qwen' }] };
  const clean = sanitizeImport(settings, key => key).clean;
  assert.equal(clean.localModelSelectionsSaved, true);
  assert.equal(clean.translatePresets[0].model, 'Qwen3VL-8B');
  globalThis.chrome = { storage: { sync: { set: () => { throw Error('Selected model was cleared'); } } } };
  try { await migrateCustomProviderModelIfNeeded(clean); }
  finally { delete globalThis.chrome; }
});

test('Production custom webpage handler sends preset model to adapter and cache without changing subtitle default', async () => {
  const source = fs.readFileSync(new URL('../shinkansen/background.js', import.meta.url), 'utf8');
  const handler = source.match(/TRANSLATE_BATCH_CUSTOM: \{[\s\S]*?handler: ([\s\S]*?),\s*\},/)[1];
  const start = source.indexOf('async function handleTranslateCustom(');
  const end = source.indexOf('// ─── v1.4.0:', start);
  const settings = { targetLanguage: 'zh-TW', customProvider: { baseUrl: 'http://127.0.0.1:8080/v1', model: 'subtitle-default' } };
  const seen = [];
  const context = { getSettingsCached: async () => settings,
    getEffectiveSystemPrompt: (_, prompt) => prompt,
    customProviderPricing: () => ({}), resolveCustomProviderCachedRate: () => 0,
    customProviderModelKeyPart: async cp => cp.model,
    customPromptForKey: () => '', DEFAULT_SETTINGS: { customProvider: { temperature: 0.7 } },
    translateBatchCustom: async (_, effective) => effective.customProvider.model,
    pipeline: { runTranslatePipeline: async config => { seen.push(config); return config.translate(['Hello']); } },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nthis.run = ' + handler + ';', context);
  assert.equal(await context.run({ texts: ['Hello'], modelOverride: 'webpage-model' }), 'webpage-model');
  assert.equal(seen[0].keyParts.modelKeyPart, 'webpage-model');
  assert.equal(settings.customProvider.model, 'subtitle-default');
  assert.equal(await context.run({ texts: ['Hello'], modelOverride: null }), 'subtitle-default');
});
