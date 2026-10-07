// domain-utils.js — 自動翻譯網站名單的網域正規化 + 比對、網域術語表的範圍 key（網域 / 路徑前綴）比對（content script 與 Node 測試共用）
//
// content script 不能 import ES module，故用 UMD 寫法（掛 window.__SKDomain + module.exports），
// 比照 lib/format-currency.js / lib/shortcut-utils.js。content-spa.js 的白名單比對統一走這份
// 單一來源，避免比對規則散落多處 drift。
//
// 背景：使用者在 options「自動翻譯網站」每行填一個網域，但實際常貼完整網址
//（`https://stratechery.com/`）。比對時的 location.hostname 只有 `stratechery.com`，
// 協定與尾斜線會讓 exact-match 永遠不命中。normalizeDomainEntry 把使用者任意形式的輸入
//（含協定 / 路徑 / query / hash / 尾斜線 / 埠號 / www. / 尾端點）收斂成純主機名，
// 讓 `https://stratechery.com/`、`stratechery.com/`、`stratechery.com` 三者等價。
(function (global) {
  'use strict';

  // 把一行白名單輸入正規化成純主機名。保留萬用字元前綴 `*.`（比對子網域用）。
  // 結構性通則：只看 URL 語法特徵（協定 / 路徑分隔 / 埠號 / www.），非站點特判。
  function normalizeDomainEntry(raw) {
    var s = String(raw == null ? '' : raw).trim().toLowerCase();
    if (!s) return '';
    // 保留萬用字元前綴 `*.`，其餘照網域正規化後再接回
    var wildcard = '';
    if (s.indexOf('*.') === 0) { wildcard = '*.'; s = s.slice(2); }
    // 去掉協定（https:// / http:// / 任意 scheme://）
    s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//, '');
    // 去掉路徑 / query / hash，只留主機名（含可能的埠號）
    s = s.split(/[/?#]/)[0];
    // 去掉埠號與使用者輸入殘留的尾端點
    s = s.replace(/:\d+$/, '').replace(/\.+$/, '');
    return wildcard + s;
  }

  // hostname 是否命中白名單。比對規則：
  //   - `*.example.com`：命中 example.com 自身與所有子網域
  //   - 一般網域：兩邊都去掉開頭 `www.` 再 exact-match
  //     （讓 `culpium.com` 與 `www.culpium.com` 互通；要匹配所有子網域請用 `*.culpium.com`）
  function matchDomain(hostname, whitelist) {
    if (!hostname || !Array.isArray(whitelist) || !whitelist.length) return false;
    var host = String(hostname).toLowerCase();
    var normHost = host.replace(/^www\./, '');
    return whitelist.some(function (raw) {
      var pattern = normalizeDomainEntry(raw);
      if (!pattern) return false;
      if (pattern.indexOf('*.') === 0) {
        var suffix = pattern.slice(1);       // ".example.com"
        return host === pattern.slice(2) || host.endsWith(suffix);
      }
      return normHost === pattern.replace(/^www\./, '');
    });
  }

  // 把「範圍 key」（網域專用術語表的 key）正規化成 `host` 或 `host/path` 形式：
  //   - 主機名部分走 normalizeDomainEntry（去協定 / 埠號 / 小寫 / 保留 `*.`）
  //   - 路徑部分保留（去 query / hash / 尾斜線；路徑大小寫依 URL 語意保留原樣）
  //   例：`https://Example.com/news/?p=1` → `example.com/news`；`example.com/` → `example.com`
  // 有路徑 = 只對該路徑之下的頁面生效（結構性通則：URL 路徑前綴，非站點特判）。
  function normalizeScopeEntry(raw) {
    var s = String(raw == null ? '' : raw).trim();
    if (!s) return '';
    var host = normalizeDomainEntry(s);
    if (!host) return '';
    var stripped = s.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '');
    var slash = stripped.indexOf('/');
    var path = slash === -1 ? '' : normalizePath(stripped.slice(slash).split(/[?#]/)[0]);
    return path ? host + path : host;
  }

  // 路徑正規化：去尾斜線、合併連續斜線；根路徑 `/` 視為「無路徑限定」回空字串
  function normalizePath(p) {
    var out = String(p == null ? '' : p).replace(/\/{2,}/g, '/').replace(/\/+$/, '');
    return out === '' || out === '/' ? '' : (out.charAt(0) === '/' ? out : '/' + out);
  }

  // 百分比編碼容錯：頁面 pathname 是編碼後形式、使用者輸入可能是原字，比對前兩邊都解碼
  function safeDecode(p) {
    try { return decodeURIComponent(p); } catch (e) { return p; }
  }

  // 把 byDomain key 拆成 { host, path }。
  //   - 標準形 `host/path`（normalizeScopeEntry 產出）→ path 生效
  //   - 含協定 / query / hash 的 key = v2.0.86 前使用者貼上的完整網址（當時存原樣、
  //     語意是整站）→ 維持整站比對，path 忽略；不需 migration
  function splitScopeKey(raw) {
    var s = String(raw == null ? '' : raw).trim();
    var legacyUrl = /^[a-z][a-z0-9+.-]*:\/\//i.test(s) || /[?#]/.test(s);
    var host = normalizeDomainEntry(s);
    if (legacyUrl) return { host: host, path: '' };
    var slash = s.indexOf('/');
    return { host: host, path: slash === -1 ? '' : normalizePath(s.slice(slash)) };
  }

  // byDomain 物件（網域專用術語表等「以網域字串為 key」的設定）中，頁面命中哪些 key。
  // 主機名比對規則與 matchDomain 完全一致（單一資料源）：`*.` 萬用字元、www. 互通、
  // 輸入正規化。key 帶路徑（`host/path`）時另要求頁面 pathname 等於該路徑或位於其下
  //（以 `/` 為段落邊界：`/content/12` 不會誤中 `/content/123`）；未傳 pathname 時
  // 只比主機名（舊呼叫端相容）。
  // 回傳依「具體度」排序的命中 key 陣列：整站 key 在前、路徑 key 依路徑長度遞增在後，
  // 同層字母序——呼叫端依序合併、後者覆蓋前者，越具體的範圍優先。
  function matchingDomainKeys(hostname, byDomain, pathname) {
    if (!hostname || !byDomain || typeof byDomain !== 'object' || Array.isArray(byDomain)) return [];
    var page = pathname == null ? null : safeDecode(normalizePath(String(pathname)));
    var scopes = {};
    var hits = Object.keys(byDomain).filter(function (key) {
      var scope = splitScopeKey(key);
      scopes[key] = scope;
      if (!matchDomain(hostname, [scope.host])) return false;
      if (!scope.path || page === null) return true;
      var want = safeDecode(scope.path);
      return page === want || page.indexOf(want + '/') === 0;
    });
    return hits.sort(function (a, b) {
      var d = scopes[a].path.length - scopes[b].path.length;
      if (d !== 0) return d;
      return a < b ? -1 : (a > b ? 1 : 0);
    });
  }

  var api = {
    normalizeDomainEntry: normalizeDomainEntry,
    normalizeScopeEntry: normalizeScopeEntry,
    matchDomain: matchDomain,
    matchingDomainKeys: matchingDomainKeys
  };
  // global = window（頁面 / content script）或 globalThis（MV3 service worker 的
  // ES module import 副作用載入——SW 沒有 window，background.js 走 globalThis.__SKDomain）
  global.__SKDomain = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
