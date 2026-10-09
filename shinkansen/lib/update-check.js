// update-check.js — GitHub Releases 更新檢查（v1.6.1 起）
//
// 為什麼有這個檔：手動從 GitHub 載入未封裝（unpacked）安裝的使用者沒有 Chrome
// Web Store 的自動更新機制，可能不知道有新版可下載。本模組透過 GitHub Releases
// API 拿最新 tag，比對 manifest.version，發現有新版就寫進 storage.local 的
// `updateAvailable` 物件，由 popup / 設定頁 / toast 三處讀取顯示提示。
//
// 觸發時機（在 background.js 註冊）：
//   - chrome.runtime.onStartup（Chrome 啟動時）
//   - chrome.alarms 'update-check' 24h 定時（Chrome 一直開著的備援）
//   - SW 第一次喚醒 fire-and-forget（背景模組載入時最早可跑的點）
//
// 對 Chrome Web Store 安裝（installType='normal'）的使用者跳過——CWS 走原生
// 自動更新機制不需要這層提示。只對 'development'（unpacked）與 'sideload'
// 兩種需要手動安裝的情境觸發。
//
// GitHub API rate limit：未驗證 60 req/hr/IP。三層觸發本身不保證 24h 一次——MV3 SW
// 每次冷啟都會跑「第一次喚醒 fire-and-forget」那層（unpacked 使用者一小時可達 60+ 次
// 冷啟 → 403），所以 checkForUpdate 內以 storage.local 的 updateCheckLastAt 節流
// （2026-09-11 code review §3.6-2）。

import { browser } from './compat.js';
import { debugLog } from './logger.js';
import { IS_MAS_BUILD } from './distribution.js';

const GITHUB_RELEASES_URL =
  'https://api.github.com/repos/jimmysu0309/shinkansen/releases/latest';
const STORAGE_KEY = 'updateAvailable';
// 上次真的打過 GitHub API 的時間（storage.local，跨 SW 冷啟）。與 updateAvailable 分開存：
// up-to-date 時 updateAvailable 會被 remove，節流時間戳不能跟著消失。
const LAST_CHECK_KEY = 'updateCheckLastAt';
// 23h 而非 24h：alarm 週期是 24h，若節流窗剛好也是 24h，alarm 觸發時距上次冷啟檢查
// 可能只差幾分鐘就被擋掉，下一次要再等 24h（實際間隔拉到 48h）。留 1h 餘裕。
export const UPDATE_CHECK_MIN_INTERVAL_MS = 23 * 60 * 60 * 1000;

/**
 * 取「今日」鍵字串 'YYYY-MM-DD' — **使用本地時區**而非 UTC。
 * 重要：絕對不要用 `new Date().toISOString().slice(0,10)`——那是 UTC 日期，
 * 台灣（UTC+8）使用者凌晨 0–8 點之間仍是 UTC 昨天，會讓節流判斷出錯（剛 dismiss
 * 過幾小時又看到提示）。所有與 lastNoticeShownDate 比對的地方都要用此 helper。
 */
export function localTodayKey() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/**
 * 把 'v1.6.0' / '1.6.0' 字串解析成 [major, minor, patch] 陣列；
 * 任何非數字段視為 0，避免 'v1.6.0-beta' 解析爆掉。
 */
function parseVersion(v) {
  const cleaned = String(v || '').replace(/^v/, '').split('-')[0];
  const parts = cleaned.split('.').map(s => parseInt(s, 10) || 0);
  while (parts.length < 3) parts.push(0);
  return parts.slice(0, 3);
}


/**
 * 判斷是否值得提示使用者更新。**只有 major 或 minor 升級才提示**，patch 級小修
 * 不打擾使用者（例如 1.6.4 → 1.6.5 不提示、1.6.4 → 1.7.0 / 2.0.0 才提示）。
 * 設計理由：頻繁的 patch 提示會讓使用者疲勞、忽略真正重要的版本。
 * @returns {boolean} 是否該顯示更新提示
 */
function isWorthNotifying() {
  // Custom builds are maintained independently of the upstream release channel.
  return false;
}

/**
 * 是否為「需要手動更新」的安裝來源（非 Chrome Web Store）。
 *
 * 判斷依據:`chrome.runtime.getManifest().update_url`。CWS 安裝時 Chrome
 * 會自動 inject 一個 update_url 欄位(指向 CWS 自動更新端點),自家
 * manifest.json 不寫此欄位 → 有 update_url = CWS,沒有 = unpacked / sideload。
 *
 * 為什麼不用 `chrome.management.getSelf()`:那需要 'management' permission,
 * CWS 審查會把它當敏感權限額外 review(它能列舉/disable 其他 extension)。
 * 我們只需要判斷「是不是 CWS 安裝」,不需要那個權限的所有能力。
 *
 * @returns {boolean}
 */
function isManualInstall() {
  try {
    const updateUrl = browser.runtime.getManifest().update_url;
    return !updateUrl;
  } catch (err) {
    // 理論上不會發生(getManifest 是同步且永遠可用)。保守估計算手動安裝。
    debugLog('warn', 'update-check', 'getManifest failed', { error: err.message });
    return true;
  }
}

/**
 * 對外主函式：檢查 GitHub 是否有新版。
 *
 * 行為：
 *   - 非手動安裝（CWS）→ 直接 return（CWS 自動更新）
 *   - fetch 失敗 / 非 200 → 寫 log 不寫 storage（避免清掉舊偵測結果）
 *   - latest > current → 寫 storage.updateAvailable
 *   - latest === current → 清 storage.updateAvailable（之前可能有殘留）
 *
 * @returns {Promise<{ checked: boolean, hasUpdate: boolean, version?: string, releaseUrl?: string, error?: string }>}
 */
export async function checkForUpdate() {
  await browser.storage.local.remove('updateAvailable');
  return { checked: false, hasUpdate: false, error: 'Custom build — upstream updates disabled' };
}

/**
 * 標記「今天已顯示過更新提示」。toast / banner 點擊「下次再說」時呼叫。
 * 用於每日節流——同一天 toast 不再重複出現，但隔天又會。
 */
export async function markUpdateNoticeShown() {
  const existing = await browser.storage.local.get(STORAGE_KEY);
  const cur = existing[STORAGE_KEY];
  if (!cur) return;
  await browser.storage.local.set({
    [STORAGE_KEY]: { ...cur, lastNoticeShownDate: localTodayKey() },
  });
}

/**
 * updateAvailable → 使用者點更新提示後要開的 URL(單一資料源——popup 與 options
 * 的 banner click handler 共用；2026-07-08 前兩邊各自實作，Safari 直下 .pkg 的
 * 分支只存在 popup 版，options 版點了只到 release 索引頁)。
 *
 * @param {object|null} updateAvailable storage.local 的 updateAvailable 物件
 * @param {boolean} isSafari Safari runtime(直接給 .pkg 下載連結)
 * @returns {string} 目標 URL(三層 fallback:releaseUrl > tag URL > releases 索引頁)
 */
export function buildUpdateDownloadUrl(updateAvailable, isSafari) {
  const version = updateAvailable?.version;
  if (isSafari && version) {
    return `https://github.com/jimmysu0309/shinkansen/releases/download/v${version}/shinkansen-macos-v${version}.pkg`;
  }
  return updateAvailable?.releaseUrl
    || (version
      ? `https://github.com/jimmysu0309/shinkansen/releases/tag/v${version}`
      : 'https://github.com/jimmysu0309/shinkansen/releases');
}


// 匯出供測試
export { parseVersion, isWorthNotifying };
