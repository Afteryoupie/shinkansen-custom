import './provider-performance.js';

export const PROVIDER_TYPES = ['online', 'local'];
export const CUSTOM_ENGINES = ['openai-compat', 'openai-compat-online', 'openai-compat-local'];

export function providerSettings(settings, engine) {
  const type = engine === 'openai-compat-online' ? 'online' : engine === 'openai-compat-local' ? 'local' : settings.customProviderType;
  const profile = type === 'online' ? settings.customProviderOnline : type === 'local' ? settings.customProviderLocal : null;
  return profile ? { ...settings, customProvider: { ...profile, profileType: type } } : settings;
}

export function inferProviderType(baseUrl) {
  return globalThis.__SKProviderPerformance.inferType(baseUrl);
}

// Synchronized Mac choices cannot run on a Windows loopback server. An empty
// model uses that server's current/default model; LAN/cloud backends stay intact.
export function localModelForPlatform(model, baseUrl) {
  const platform = globalThis.navigator?.userAgentData?.platform || globalThis.navigator?.platform || '';
  if (!/^win/i.test(platform) || !/^(apple(?:[- ]|$)|foundation.?models)/i.test(model || '')) return model;
  try {
    const url = new URL(baseUrl);
    if (['http:', 'https:'].includes(url.protocol) &&
        ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) return '';
  } catch { /* Invalid endpoints retain their normal validation error. */ }
  return model;
}

// Keep credentials out of synchronized settings and exported backups.
export function providerConfig(raw = {}) {
  const config = {};
  for (const key of ['baseUrl', 'model', 'systemPrompt', 'extraBodyJson']) {
    if (typeof raw[key] === 'string') config[key] = key === 'systemPrompt' ? raw[key] : raw[key].trim();
  }
  for (const [key, min, max] of [['temperature', 0, 2], ['fetchTimeoutSec', 5, 600],
    ['inputPerMTok', 0, Infinity], ['outputPerMTok', 0, Infinity], ['cachedDiscount', 0, 1]]) {
    if (typeof raw[key] === 'number' && Number.isFinite(raw[key]) && raw[key] >= min && raw[key] <= max) config[key] = raw[key];
  }
  for (const [key, [min, max]] of Object.entries(globalThis.__SKProviderPerformance.fields)) {
    if (Number.isInteger(raw[key]) && raw[key] >= min && raw[key] <= max) config[key] = raw[key];
  }
  if (['auto', 'throughput', 'latency', 'price'].includes(raw.routingSort)) config.routingSort = raw.routingSort;
  if (typeof raw.allowFallbacks === 'boolean') config.allowFallbacks = raw.allowFallbacks;
  for (const key of ['temperature', 'cachedDiscount']) if (raw[key] === null) config[key] = null;
  if (['auto', 'off', 'low', 'medium', 'high'].includes(raw.thinkingLevel)) config.thinkingLevel = raw.thinkingLevel;
  if (typeof raw.useStrongSegMarker === 'boolean') config.useStrongSegMarker = raw.useStrongSegMarker;
  return config;
}

export function resolveProviderProfiles(settings, defaults, local = {}) {
  const legacyType = inferProviderType(settings.customProvider?.baseUrl || defaults.baseUrl);
  const activeType = PROVIDER_TYPES.includes(settings.customProviderType) ? settings.customProviderType : legacyType;
  const profiles = {
    online: { ...defaults, baseUrl: '', model: '', systemPrompt: '', temperature: 0.7,
      cachedDiscount: null, useStrongSegMarker: false, routingSort: 'throughput', allowFallbacks: true },
    local: { ...defaults },
  };
  for (const type of PROVIDER_TYPES) {
    const saved = settings[type === 'online' ? 'customProviderOnline' : 'customProviderLocal'];
    profiles[type] = { ...profiles[type], ...providerConfig(saved || (type === legacyType ? settings.customProvider : {})) };
  }
  profiles.local.model = localModelForPlatform(profiles.local.model, profiles.local.baseUrl);
  const keys = {};
  for (const type of PROVIDER_TYPES) {
    keys[type] = typeof local.customProviderApiKeys?.[type] === 'string'
      ? local.customProviderApiKeys[type] : type === legacyType ? local.customProviderApiKey || '' : '';
  }
  return { profiles, keys, activeType };
}

export function activeProvider(state) {
  return { ...state.profiles[state.activeType], profileType: state.activeType, apiKey: state.keys[state.activeType] || '' };
}
