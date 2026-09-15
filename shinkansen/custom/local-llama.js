// custom/local-llama.js — 本地 llama-server (0% 顯存智慧守護代理) 自動喚醒模組
// 獨立模組：負責在發送推論請求前探測 127.0.0.1:8080，休眠中則自動發出喚醒訊號並等待就緒

let _startingLlamaPromise = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 探測並在必要時拉起本地 llama-server
 * @param {string} baseUrl
 * @returns {Promise<void>}
 */
export async function ensureLocalLlamaServer(baseUrl) {
  if (!baseUrl || (!baseUrl.includes('127.0.0.1') && !baseUrl.includes('localhost'))) {
    return;
  }

  const checkUrl = baseUrl.endsWith('/chat/completions')
    ? baseUrl.replace('/chat/completions', '/models')
    : (baseUrl.replace(/\/+$/, '') + '/models');

  try {
    const probe = await fetch(checkUrl, { signal: AbortSignal.timeout(800) });
    if (probe.ok) return;
  } catch (_) {
    // 端口尚未開放（模型處於休眠或未啟動狀態）
  }

  if (_startingLlamaPromise) {
    return _startingLlamaPromise;
  }

  _startingLlamaPromise = (async () => {
    console.info('[shinkansen-custom] 本地模型處於休眠狀態，正在透過 Native Messaging 喚醒守護代理...');

    // 1. 透過 Chrome / Edge Native Messaging Host (com.llm_project.llama_launcher) 喚醒
    try {
      if (typeof chrome !== 'undefined' && chrome.runtime?.sendNativeMessage) {
        chrome.runtime.sendNativeMessage('com.llm_project.llama_launcher', { action: 'start' }, (resp) => {
          if (chrome.runtime.lastError) {
            console.warn('[shinkansen-custom] Native host 警告: ' + chrome.runtime.lastError.message);
          } else {
            console.info('[shinkansen-custom] Native host 喚醒回應: ' + JSON.stringify(resp));
          }
        });
      }
    } catch (e) {
      console.warn('[shinkansen-custom] sendNativeMessage 異常: ' + e.message);
    }

    // 2. 透過 HTTP Bridge 備援喚醒
    try {
      fetch('http://127.0.0.1:8765/start-llama', { method: 'POST' }).catch(() => {});
    } catch (_) {}

    // 3. 輪詢直到本地 llama-server 就緒（最長等候 15 秒）
    const t0 = Date.now();
    while (Date.now() - t0 < 15000) {
      await sleep(600);
      try {
        const check = await fetch(checkUrl, { signal: AbortSignal.timeout(800) });
        if (check.ok) {
          console.info(`[shinkansen-custom] 本地 llama-server 已就緒！耗時 ${Date.now() - t0}ms`);
          return;
        }
      } catch (_) {}
    }
    console.warn('[shinkansen-custom] 本地 llama-server 喚醒等候超時（15 秒）');
  })().finally(() => {
    _startingLlamaPromise = null;
  });

  return _startingLlamaPromise;
}
