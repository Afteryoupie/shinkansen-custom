// Wait for local inference readiness before starting the translation timeout.
const starting = new Map();
const startingLaya = new Map();

function requestNativeLauncher() {
  const runtime = globalThis.chrome?.runtime;
  if (!runtime?.sendNativeMessage) return Promise.resolve(null);
  return new Promise(resolve => {
    try {
      runtime.sendNativeMessage('com.llm_project.llama_launcher', { action: 'start' }, response => {
        if (runtime.lastError) console.warn('[shinkansen-custom] Native host: ' + runtime.lastError.message);
        resolve(response || null);
      });
    } catch (error) {
      console.warn('[shinkansen-custom] Native host: ' + error.message);
      resolve(null);
    }
  });
}

async function prepareLocalServer(url, model) {
  const watchdog = url.port === '8080';
  const checkUrl = watchdog ? new URL('/api/status', url).href
    : url.href.replace(/\/chat\/completions\/?$/, '').replace(/\/+$/, '') + '/models';
  const probe = async () => {
    try {
      const response = await fetch(checkUrl, { signal: AbortSignal.timeout(2000) });
      if (!response.ok) return null;
      return watchdog ? await response.json() : { status: 'running' };
    } catch (_) { return null; }
  };
  let status = await probe();
  if (!status) {
    // Only needed when the proxy itself is offline, not when its model sleeps.
    await requestNativeLauncher();
    const deadline = Date.now() + 15000;
    while (!status && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 600));
      status = await probe();
    }
    if (!status) throw new Error('無法連線到本機 LLM 服務，請啟動 LLM watchdog（或執行 windows/install-native-host.ps1 註冊自動喚醒）。');
  }
  if (!watchdog) return;
  const target = status.models?.find(m => [m.id, m.name, m.path].includes(model));
  const switchModel = model && ![status.current_model_id, status.current_model].includes(target?.id || model);
  if (!switchModel && status.status === 'running') return;
  // /v1/models is a passive catalog and succeeds even while the model sleeps.
  // /api/wake waits for the engine's health check, including an ongoing start.
  const wakeUrl = new URL(switchModel ? '/api/switch' : '/api/wake', url);
  if (switchModel) wakeUrl.searchParams.set('model', model);
  const response = await fetch(wakeUrl, {
    method: 'POST', signal: AbortSignal.timeout(130000),
  });
  if (!response.ok) throw new Error(`LLM watchdog 喚醒失敗：HTTP ${response.status}`);
  const result = await response.json();
  if (result.status !== 'ok' || (!switchModel && result.state !== 'running')) {
    throw new Error('LLM watchdog 模型載入失敗，請檢查模型與可用記憶體。');
  }
}

export async function ensureLocalLlamaServer(baseUrl, model = '') {
  let url;
  try { url = new URL(baseUrl); } catch (_) { return; }
  if (!['127.0.0.1', 'localhost'].includes(url.hostname)) return;
  model = model === 'default' ? '' : model;
  const key = JSON.stringify([url.origin, model]);
  if (!starting.has(key)) {
    const pending = prepareLocalServer(url, model).finally(() => starting.delete(key));
    starting.set(key, pending);
  }
  return starting.get(key);
}

export async function ensureLocalLayaDecision(apiUrl) {
  let url;
  try { url = new URL(apiUrl || 'http://127.0.0.1:8080/v1/systemone'); } catch (_) { return; }
  if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.port !== '8080') return;
  const key = url.origin;
  if (!startingLaya.has(key)) {
    const pending = (async () => {
      const wakeUrl = new URL('/api/decision/wake', url).href;
      const response = await fetch(wakeUrl, { method: 'POST', signal: AbortSignal.timeout(130000) });
      if (!response.ok) throw new Error(`Laya 決策模型喚醒失敗：HTTP ${response.status}`);
      const result = await response.json();
      if (result.status !== 'ok') throw new Error(result.message || 'Laya 決策模型載入失敗。');
    })().finally(() => startingLaya.delete(key));
    startingLaya.set(key, pending);
  }
  return startingLaya.get(key);
}
