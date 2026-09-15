// compat.js — Safari / Firefox 相容性 shim
// Chrome Extension 使用 `chrome.*`，Safari / Firefox 使用 `browser.*`。
// 這個 shim 讓同一份程式碼在兩種環境都能運作。
// 所有 ES module 檔案（background.js、popup.js、options.js、lib/*.js）
// 透過 `import { browser } from './compat.js'` 取得跨平台的 API 物件。
//
// 為什麼用 Proxy 而非 const：ES module 只 evaluate 一次，若用
// `export const browser = globalThis.chrome`，import 當下若 globalThis.chrome
// 還沒設好就會永遠是 undefined。Proxy 把解析延後到 property access 時，
// 確保每次呼叫都讀到最新的 globalThis.chrome / globalThis.browser。
// （直接影響：Playwright 單 worker 跑多個 unit test 時，不同 spec 各自設
// globalThis.chrome mock，若用 const 只有第一個 spec 的 mock 會生效。）

export const browser = new Proxy({}, {
  get(_, prop) {
    const target = globalThis.browser ?? globalThis.chrome;
    return target?.[prop];
  },
});
