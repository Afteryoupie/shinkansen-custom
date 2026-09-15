// content-fw-detect-main.js — Shinkansen main-world framework detect bridge
//
// 為什麼必要（Chrome for Claude probe 2026-05-19 在真實 X 推文驗證）:
//   Chrome content script isolated world 看不到 main world 的 expando 屬性
//   (React 18 設的 `__reactFiber$xxx` / `__reactProps$xxx` 等）。isolated world
//   `for (k in el)` 直接 reactKeysFound=0，即便 main world Object.keys(el) 含
//   `__reactFiber$xxx`。
//
//   修法：此 script 跑在 main world,offer sync CustomEvent bridge —
//     isolated world dispatch `shinkansen-fw-detect-request` event 到 element
//     → main world listener 跑 detect → dispatch `shinkansen-fw-detect-response`
//     event 帶 detail.result(primitive string，跨 world clone safe)
//
// 用途：isolated world 端 SK.isFrameworkManaged(el) 透過 bridge 拿 main-world
//   偵測結果，決定該 element 是否需 fall back 到 dual inject（避開 §15 single
//   mode 改 element 子樹後 React fiber DOM ref 變孤兒、X 推文「顯示更多」等
//   framework click handler 失效的問題，facebook/react#11538 同類）。

(() => {
  const cache = new WeakMap();

  function detect(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return 'none';
    if (cache.has(el)) return cache.get(el);
    let result = 'none';
    // React 16+(__reactFiber$xxx / __reactProps$xxx 是 community workaround
    // 公開使用多年的 marker，跨 React 版本 stable)
    for (const k in el) {
      if (k.charCodeAt(0) !== 95 /* '_' */) continue;
      if (k.startsWith('__reactFiber$') || k.startsWith('__reactProps$')) {
        result = 'react';
        break;
      }
    }
    // Vue 3 / Vue 2
    if (result === 'none' && (el.__vue_app__ || el.__vueParentComponent || el.__vue__)) {
      result = 'vue';
    }
    // 只快取正向結果：hydration 前查過的 element 若把 'none' 也永久釘死，SSR React 頁
    // (document_idle 早於 hydration 完成)之後 rescan 拿到 stale 'none' → 走 single
    // 注入 React 子樹 → click handler 失效，正是本 bridge 要防的 bug。偵測本身是
    // for-in + 兩個屬性讀取，對 'none' 重跑成本極低。
    if (result !== 'none') cache.set(el, result);
    return result;
  }

  window.addEventListener('shinkansen-fw-detect-request', (e) => {
    const el = e.target;
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return;
    const result = detect(el);
    // sync dispatch response — primitive string in detail，跨 world clone safe
    el.dispatchEvent(new CustomEvent('shinkansen-fw-detect-response', {
      detail: { result },
      bubbles: false,
    }));
  }, true /* capture phase */);
})();
