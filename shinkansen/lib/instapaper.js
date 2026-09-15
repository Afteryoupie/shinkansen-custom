// lib/instapaper.js — Instapaper Full API（OAuth 1.0a + xAuth）封裝
//
// 「送到 Instapaper」功能的核心邏輯。Instapaper 沒有 Readwise 式單一 access
// token,要送「完整內容」只有 Full API（/api/1/...）做得到——它的 bookmarks/add
// 有 content 參數可吃整頁 HTML,Instapaper 端跑自己的 readability 抽正文。
// 因為頁面文字已被 Shinkansen 就地換成譯文,存進 Instapaper 的就是譯文版文章。
//
// 認證走 xAuth（x_auth_mode=client_auth）:使用者在 options 填一次 Instapaper
// email + 密碼,換一組 OAuth token + token secret,之後只存 token、密碼用完即丟。
//
// 設計成純 ESM + 依賴注入（fetchImpl / signImpl / 金鑰皆可注入),好寫單元測試:
//   - popup.js（module）/ options.js（module）/ background.js（module SW）三處 import
//   - content script 不載此檔（避免把 consumer secret 注入每個網頁,見 §4.0）
//   - 測試走注入,不依賴 gitignored 的 instapaper-keys.js,fresh clone / CI 不報錯
//
// 簽章遵循 RFC 5849（OAuth 1.0a):
//   base string = METHOD&pctEncode(URL)&pctEncode(排序後所有參數)
//   signing key = pctEncode(consumerSecret)&pctEncode(tokenSecret)
//   HMAC-SHA1 → base64
// content 全文也是 form 參數 → 必須納入 base string（base string 會很大,但這是
// Full API client 的標準作法,無功能問題）。

// ─── 端點常數 ──────────────────────────────────────────────
export const INSTAPAPER_ACCESS_TOKEN_URL = 'https://www.instapaper.com/api/1/oauth/access_token';
export const INSTAPAPER_ADD_URL = 'https://www.instapaper.com/api/1/bookmarks/add';
export const INSTAPAPER_VERIFY_URL = 'https://www.instapaper.com/api/1/account/verify_credentials';

// ─── consumer 金鑰讀取 ────────────────────────────────────
// instapaper-keys.js（gitignored）載入後掛在 globalThis.__SK.INSTAPAPER_KEYS。
// 讀不到（fresh clone / CI / 未申請）→ 回 null,呼叫端據此停用功能。
export function getInstapaperConsumerKeys() {
  const root = (typeof globalThis !== 'undefined') ? globalThis
    : (typeof self !== 'undefined') ? self
      : (typeof window !== 'undefined') ? window : {};
  const keys = root && root.__SK && root.__SK.INSTAPAPER_KEYS;
  if (keys && keys.consumerKey && keys.consumerSecret) {
    return { consumerKey: keys.consumerKey, consumerSecret: keys.consumerSecret };
  }
  return null;
}

// consumer 金鑰是否就緒（options / popup 用來決定要不要顯示功能入口）。
export function hasInstapaperConsumerKeys() {
  return getInstapaperConsumerKeys() !== null;
}

// ─── OAuth 工具（純函式）──────────────────────────────────

// RFC 3986 percent-encode。encodeURIComponent 不編碼 - _ . ! ~ * ' ( )；
// 其中 unreserved 只保留 - _ . ~,所以還要把 ! * ' ( ) 補編成 %XX。
export function oauthPercentEncode(str) {
  return encodeURIComponent(String(str)).replace(/[!*'()]/g, (c) =>
    '%' + c.charCodeAt(0).toString(16).toUpperCase());
}

// 排序 + 編碼所有參數成 RFC 5849 §3.4.1.3.2 的 normalized parameter string。
// params:{ k: v } 或 { k: [v1, v2] }（同 key 多值）。先各自 pctEncode,
// 再依「編碼後的 key,key 相同則編碼後的 value」字典序排序,組 key=value 以 & 連接。
export function normalizeOAuthParams(params) {
  const pairs = [];
  for (const key of Object.keys(params)) {
    const value = params[key];
    const values = Array.isArray(value) ? value : [value];
    for (const v of values) {
      pairs.push([oauthPercentEncode(key), oauthPercentEncode(v)]);
    }
  }
  pairs.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0)));
  return pairs.map(([k, v]) => `${k}=${v}`).join('&');
}

// base string = METHOD & pctEncode(URL) & pctEncode(normalized params)。
export function buildOAuthBaseString({ method, url, params }) {
  return [
    String(method).toUpperCase(),
    oauthPercentEncode(url),
    oauthPercentEncode(normalizeOAuthParams(params)),
  ].join('&');
}

// signing key = pctEncode(consumerSecret) & pctEncode(tokenSecret)。
export function buildOAuthSigningKey({ consumerSecret, tokenSecret }) {
  return `${oauthPercentEncode(consumerSecret || '')}&${oauthPercentEncode(tokenSecret || '')}`;
}

// 預設簽章實作:crypto.subtle HMAC-SHA1 → base64。瀏覽器（popup / options）與
// service worker（background）都有 crypto.subtle。測試環境注入 Node crypto。
export async function defaultSign(signingKey, baseString) {
  const enc = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    'raw', enc.encode(signingKey), { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', cryptoKey, enc.encode(baseString));
  const bytes = new Uint8Array(sig);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

// 簽一個請求,回 { authHeader, oauthParams, signature, baseString }。
// bodyParams 是非 oauth_ 的 form 參數（x_auth_* / url / title / content）,
// 一併納入 base string,但 authHeader 只列 oauth_ 參數。
// nonce / timestamp 可注入（測試固定值）;預設用 crypto.getRandomValues + Date.now。
export async function signRequest({
  method, url, consumerKey, consumerSecret, token, tokenSecret,
  bodyParams = {}, nonce, timestamp, signImpl = defaultSign,
}) {
  const oauthParams = {
    oauth_consumer_key: consumerKey,
    oauth_nonce: nonce || generateNonce(),
    oauth_signature_method: 'HMAC-SHA1',
    oauth_timestamp: String(timestamp || Math.floor(Date.now() / 1000)),
    oauth_version: '1.0',
  };
  if (token) oauthParams.oauth_token = token;

  const allParams = { ...bodyParams, ...oauthParams };
  const baseString = buildOAuthBaseString({ method, url, params: allParams });
  const signingKey = buildOAuthSigningKey({ consumerSecret, tokenSecret });
  const signature = await signImpl(signingKey, baseString);

  const headerParams = { ...oauthParams, oauth_signature: signature };
  const authHeader = 'OAuth ' + Object.keys(headerParams)
    .sort()
    .map((k) => `${oauthPercentEncode(k)}="${oauthPercentEncode(headerParams[k])}"`)
    .join(', ');

  return { authHeader, oauthParams, signature, baseString };
}

// crypto.getRandomValues 產生 nonce（hex）。SW / 瀏覽器皆有 crypto。
function generateNonce() {
  const arr = new Uint8Array(16);
  crypto.getRandomValues(arr);
  let s = '';
  for (let i = 0; i < arr.length; i++) s += arr[i].toString(16).padStart(2, '0');
  return s;
}

// 把 form 參數編碼成 application/x-www-form-urlencoded body。
// 刻意用 oauthPercentEncode（而非 URLSearchParams 的 space→+）讓 body 的編碼與
// 簽章 base string 的參數編碼完全一致,伺服器解出來的值才會跟我們簽的一致。
export function encodeFormBody(params) {
  return Object.keys(params)
    .map((k) => `${oauthPercentEncode(k)}=${oauthPercentEncode(params[k])}`)
    .join('&');
}

// 解析 access_token 回應:`oauth_token=xxx&oauth_token_secret=yyy`。
// 缺欄位回 null（呼叫端轉成 error）。
export function parseTokenResponse(text) {
  if (!text || typeof text !== 'string') return null;
  const sp = new URLSearchParams(text.trim());
  const token = sp.get('oauth_token');
  const tokenSecret = sp.get('oauth_token_secret');
  if (!token || !tokenSecret) return null;
  return { token, tokenSecret };
}

// 組 bookmarks/add 的 payload。url 必填;title / content 空值不帶。
//
// 為何**不**設 is_private_from_source（2026-06-15 實測結論）:
// 「影片綁架」的真正元兇是 EXTRACT_PAGE_HTML 廣播到所有 frame、被內嵌 youtube iframe
// frame 搶答（修在 content.js top-frame guard），不是 Instapaper re-crawl。實測「帶
// content + 不帶 is_private_from_source」送公開頁（readtrung 譯文）→ Instapaper 確實
// 用了我們的 content（存的是乾淨譯文、無影片），且**保留原始 source URL 連結**。
// 反之設 is_private_from_source 會讓 bookmark 變 private、url 變 instapaper://private-content
// （失去原文連結）——既然不必要就不設,留住 source URL 對使用者較好。
// 殘留風險:官方文件稱 content 對「可爬頁面」是 fallback;實測 stable 但無法保證 Instapaper
// 不會延遲 re-crawl 覆蓋。若日後發現 bookmark 延遲變回原文 / 影片,再加回 is_private_from_source。
// description(選填):文章摘要,對應 Full API 的 description 欄位(顯示在 Instapaper
// 項目底下)。空值 / 非字串不帶。摘要由 lib/gemini.js summarizeArticle 產出,best-effort
// ——產不出時這裡直接收到空值、不帶 description,書籤照常送(摘要是加值不擋送出)。
export function buildInstapaperPayload({ url, html, title, description }) {
  if (!url || typeof url !== 'string') {
    throw new Error('buildInstapaperPayload: url is required');
  }
  const payload = { url };
  if (title && typeof title === 'string') payload.title = title;
  if (html && typeof html === 'string') payload.content = html;
  if (description && typeof description === 'string') {
    const trimmed = description.trim();
    if (trimmed) payload.description = trimmed;
  }
  return payload;
}

// ─── 高階呼叫 ──────────────────────────────────────────────

function resolveKeys(consumerKey, consumerSecret) {
  if (consumerKey && consumerSecret) return { consumerKey, consumerSecret };
  const keys = getInstapaperConsumerKeys();
  if (keys) return keys;
  return null;
}

// xAuth:email + 密碼 → { ok:true, token, tokenSecret }。兼任「測試連結」
//（xAuth 成功 = 憑證有效）。失敗回 { ok:false, error:'CONFIG'|'AUTH'|'HTTP'|'NETWORK' }。
export async function instapaperXAuth({
  email, password, fetchImpl = fetch, signImpl = defaultSign,
  consumerKey, consumerSecret, nonce, timestamp,
}) {
  const keys = resolveKeys(consumerKey, consumerSecret);
  if (!keys) return { ok: false, error: 'CONFIG' };
  if (!email || !password) return { ok: false, error: 'AUTH' };

  const bodyParams = {
    x_auth_username: email,
    x_auth_password: password,
    x_auth_mode: 'client_auth',
  };
  try {
    const { authHeader } = await signRequest({
      method: 'POST', url: INSTAPAPER_ACCESS_TOKEN_URL,
      consumerKey: keys.consumerKey, consumerSecret: keys.consumerSecret,
      token: null, tokenSecret: null, bodyParams, nonce, timestamp, signImpl,
    });
    const res = await fetchImpl(INSTAPAPER_ACCESS_TOKEN_URL, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: encodeFormBody(bodyParams),
    });
    if (res.status === 401 || res.status === 403) return { ok: false, error: 'AUTH' };
    if (!res.ok) return { ok: false, error: 'HTTP', status: res.status };
    const text = await res.text();
    const parsed = parseTokenResponse(text);
    if (!parsed) return { ok: false, error: 'AUTH' };
    return { ok: true, token: parsed.token, tokenSecret: parsed.tokenSecret };
  } catch (err) {
    return { ok: false, error: 'NETWORK', message: err && err.message };
  }
}

// 送一篇 bookmark。payload 由 buildInstapaperPayload 產出。
// 回 { ok:true, status, data } 或 { ok:false, error:'CONFIG'|'AUTH'|'HTTP'|'NETWORK', status? }。
export async function saveToInstapaper({
  token, tokenSecret, payload, fetchImpl = fetch, signImpl = defaultSign,
  consumerKey, consumerSecret, nonce, timestamp,
}) {
  const keys = resolveKeys(consumerKey, consumerSecret);
  if (!keys) return { ok: false, error: 'CONFIG' };
  if (!token || !tokenSecret) return { ok: false, error: 'AUTH' };
  if (!payload || !payload.url) return { ok: false, error: 'HTTP', status: 0 };

  try {
    const { authHeader } = await signRequest({
      method: 'POST', url: INSTAPAPER_ADD_URL,
      consumerKey: keys.consumerKey, consumerSecret: keys.consumerSecret,
      token, tokenSecret, bodyParams: payload, nonce, timestamp, signImpl,
    });
    const res = await fetchImpl(INSTAPAPER_ADD_URL, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: encodeFormBody(payload),
    });
    if (res.status === 401 || res.status === 403) return { ok: false, error: 'AUTH', status: res.status };
    if (!res.ok) return { ok: false, error: 'HTTP', status: res.status };
    let data = null;
    try { data = await res.json(); } catch (_) { /* 非 JSON 也算成功，data 留 null */ }
    return { ok: true, status: res.status, data };
  } catch (err) {
    return { ok: false, error: 'NETWORK', message: err && err.message };
  }
}
