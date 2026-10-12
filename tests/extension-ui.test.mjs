import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { DEFAULT_SETTINGS, migrateCustomProviderModelIfNeeded } from '../shinkansen/lib/storage.js';

test('Local defaults stay empty and legacy built-in models are cleared without changing chosen models', async () => {
  assert.equal(DEFAULT_SETTINGS.customProvider.model, '');
  assert.equal(DEFAULT_SETTINGS.translatePresets.find(p => p.engine === 'openai-compat').model, '');
  const patches = [];
  globalThis.chrome = { storage: { sync: { set: async patch => patches.push(patch) } } };
  try {
    await migrateCustomProviderModelIfNeeded({customProvider: {model: ''}});
    await migrateCustomProviderModelIfNeeded({customProvider: {model: 'Riva-Translate'}});
    assert.equal(patches.length, 0);
    await migrateCustomProviderModelIfNeeded({customProvider: {model: 'Qwen3VL-8B'},
      translatePresets: [{slot: 1, engine: 'openai-compat', model: 'Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M'}]});
    assert.equal(patches[0].customProvider.model, '');
    assert.equal(patches[0].translatePresets[0].model, '');
  } finally { delete globalThis.chrome; }
});
const read = name => fs.readFileSync(new URL('../shinkansen/' + name, import.meta.url), 'utf8');
function boot(cached, saved, dark = true, fail = false) {
  const attrs = new Map();
  const store = new Map(cached ? [['sk-ui-theme', cached]] : []);
  let release;
  const pending = new Promise(resolve => release = resolve);
  const context = { window: {}, document: { documentElement: {
    setAttribute: (k,v) => attrs.set(k,v), removeAttribute: k => attrs.delete(k),
  } }, localStorage: { getItem:k=>store.get(k), setItem:(k,v)=>store.set(k,v) },
  matchMedia:()=>({matches:dark}), chrome: {storage: {
    sync:{get:async()=>{await pending;if(fail)throw Error();return {uiTheme:saved};}},
    local:{get:async()=>{throw Error();}},
  } } };
  vm.runInNewContext(read('lib/theme-bootstrap.js'), context);
  return {attrs, store, release, ready:context.window.__skThemeReady};
}
test('Saved light theme is applied synchronously on a dark system', async()=>{
  const b=boot('light','light');
  assert.equal(b.attrs.get('data-theme'),'light');
  assert(!b.attrs.has('data-theme-pending'));
  b.release();await b.ready;
  assert.equal(b.attrs.get('data-theme'),'light');
});
test('First visit hides controls until saved theme resolves', async()=>{
  const b=boot(null,'light');
  assert(b.attrs.has('data-theme-pending'));
  assert.equal(b.attrs.get('data-theme'),'light');
  b.release();await b.ready;
  assert(!b.attrs.has('data-theme-pending'));
  assert.equal(b.store.get('sk-ui-theme'),'light');
});
test('Auto follows system and failed storage still reveals the page', async()=>{
  const auto=boot('auto','auto');assert.equal(auto.attrs.get('data-theme'),'dark');
  auto.release();await auto.ready;
  const fail=boot(null,null,false,true);fail.release();await fail.ready;
  assert(!fail.attrs.has('data-theme-pending'));
  assert.equal(fail.attrs.get('data-theme'),'light');
});
test('Upstream checker clears stale notices without fetching',async()=>{
  const removed=[];
  const source=read('lib/update-check.js').replace(/^import .*;.*$/gm,'').replace(/^export /gm,'').replace(/^\{ parseVersion, isWorthNotifying \};/m,'');
  const ctx={browser:{storage:{local:{remove:async key=>removed.push(key)}}},fetch:()=>{throw Error('upstream network request');}};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  const result=await vm.runInContext('checkForUpdate()',ctx);
  assert.equal(result.hasUpdate,false);assert.deepEqual(removed,['updateAvailable']);
  assert.equal(vm.runInContext("isWorthNotifying('99.0.0','2.6.1')",ctx),false);
});
test('Manifest version and display version match',()=>{
  const m=JSON.parse(read('manifest.json'));
  assert.equal(m.version,'2.6.1');assert.equal(m.version_name,'2.6.1-custom.20261009');
});
