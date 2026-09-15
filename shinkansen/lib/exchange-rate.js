// exchange-rate.js — USD ↔ TWD 匯率抓取 + 快取（v1.8.41 起）
//
// 為什麼有這個檔：使用者面對的金額（toast line2、popup 累計、用量明細表格、chart)
// 在 v1.8.41 起支援 TWD 顯示。匯率不能寫死，需要每天從外部抓最新值。
//
// 設計：
//   - 來源：open.er-api.com（免費、no API key、CORS 全開、daily 更新、TWD 在支援列表內）
//     最初用 frankfurter.app 但它只覆蓋 ECB 官方匯率，TWD 不在裡面（hard-fail 404）
//   - 排程：background.js 用 chrome.alarms 24h 跑一次，結果存 storage.local.exchangeRate
//   - fallback 三層：fresh fetch → cached（任何時候）→ 寫死 31.6（連 cache 都沒有時）
//   - SW idle 限制：fetch 走 15s AbortController，避免 MV3 30s timeout 把訊息吞掉
//
// 對下游（popup / options / content-toast)：一律呼叫 getCachedRate() 拿 { rate, fetchedAt, source }
// 不直接打 API——避免每個 surface 各自 fetch 浪費 quota。

import { browser } from './compat.js';
import { debugLog } from './logger.js';

export const FALLBACK_USD_TWD_RATE = 31.6;
// open.er-api.com 回傳結構：{ result: 'success', rates: { TWD: 31.65, ... }, time_last_update_utc: '...' }
const RATE_API_URL = 'https://open.er-api.com/v6/latest/USD';
const STORAGE_KEY = 'exchangeRate';
const FRESHNESS_MS = 24 * 60 * 60 * 1000; // 24h

/**
 * 從 open.er-api.com 抓最新 USD → TWD 匯率。
 * 失敗（網路、HTTP 非 2xx、JSON 結構異常、result != success、timeout）一律回 null，呼叫端走 fallback。
 *
 * @returns {Promise<number | null>}
 */
export async function fetchUsdTwdRate() {
  const ac = new AbortController();
  const timeoutId = setTimeout(() => ac.abort(), 15_000);
  let resp;
  try {
    resp = await fetch(RATE_API_URL, {
      headers: { 'Accept': 'application/json' },
      signal: ac.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    const isAbort = err?.name === 'AbortError';
    debugLog('warn', 'exchange-rate', isAbort ? 'fetch timeout' : 'fetch failed', { error: err.message });
    return null;
  }
  clearTimeout(timeoutId);
  if (!resp.ok) {
    debugLog('warn', 'exchange-rate', `open.er-api HTTP ${resp.status}`, { status: resp.status });
    return null;
  }
  let json;
  try {
    json = await resp.json();
  } catch (err) {
    debugLog('warn', 'exchange-rate', 'response not JSON', { error: err.message });
    return null;
  }
  if (json?.result !== 'success') {
    debugLog('warn', 'exchange-rate', 'API result not success', { result: json?.result });
    return null;
  }
  const rate = Number(json?.rates?.TWD);
  if (!Number.isFinite(rate) || rate <= 0) {
    debugLog('warn', 'exchange-rate', 'invalid TWD rate in response', { rate });
    return null;
  }
  return rate;
}

/**
 * 抓最新匯率並寫入 storage.local。成功回 stored object，失敗回 null（不動 storage)。
 * background.js 的 alarm / 手動 refresh 走這條。
 */
export async function refreshExchangeRate() {
  const rate = await fetchUsdTwdRate();
  if (rate === null) return null;
  const payload = {
    rate,
    fetchedAt: Date.now(),
    source: 'open.er-api',
  };
  await browser.storage.local.set({ [STORAGE_KEY]: payload });
  debugLog('info', 'exchange-rate', 'rate updated', { rate });
  return payload;
}

/**
 * 讀目前 cached 匯率。永遠回一個可用的 rate object——cache 不存在時組 fallback。
 *
 * @returns {Promise<{ rate: number, fetchedAt: number, source: 'open.er-api' | 'fallback' }>}
 */
export async function getCachedRate() {
  try {
    const { [STORAGE_KEY]: cached } = await browser.storage.local.get(STORAGE_KEY);
    if (cached && Number.isFinite(cached.rate) && cached.rate > 0) {
      return cached;
    }
  } catch {
    // storage 讀失敗一律走 fallback，不讓上游當掉
  }
  return {
    rate: FALLBACK_USD_TWD_RATE,
    fetchedAt: 0,
    source: 'fallback',
  };
}

/**
 * 判斷 cached rate 是否還新鮮（< 24h)。background SW 喚醒時用此決定要不要主動 refetch。
 * cache 不存在或 fetchedAt=0(fallback）一律視為過期。
 */
export async function isCacheFresh() {
  try {
    const { [STORAGE_KEY]: cached } = await browser.storage.local.get(STORAGE_KEY);
    if (!cached || !cached.fetchedAt) return false;
    return Date.now() - cached.fetchedAt < FRESHNESS_MS;
  } catch {
    return false;
  }
}
