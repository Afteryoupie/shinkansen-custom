// distribution-cs.js — content-script 版,跟 lib/distribution.js 同步。
//
// 為什麼需要兩份:content script 透過 manifest.content_scripts 注入,**不能用
// ES module import**(CLAUDE.md §工作風格),所以無法 reuse lib/distribution.js。
// 用 window.__SK 命名空間共享。
//
// 維護約束：本檔的 IS_MAS_BUILD / IS_IOS_BUILD 值必須跟 lib/distribution.js
// 完全一致；safari-app/safari-build.sh（MAS 軌）與 safari-build-ios.sh（iOS 軌）
// 會同時 override 兩個檔（drift check 排除兩個）。
//
// 載入順序:manifest content_scripts.js 內必排 content-ns.js 之後
// (content-ns.js 在 else 分支會做 `window.__SK = {}` 覆寫,放前面會被吹掉),
// 但必排 content.js 之前(content.js 內 maybeBuildUpdateNotice 會讀此值)。
// content-touch.js 的四指 tap 手勢以 IS_IOS_BUILD gate（handler 內動態讀，
// 載入順序不額外約束）。

if (window.__SK) {
  window.__SK.IS_MAS_BUILD = false;
  window.__SK.IS_IOS_BUILD = false;
}
