// platform.js — runtime 平台偵測(iOS build 跑在 macOS 的辨別)。
//
// 為什麼需要:iOS build(safari-build-ios.sh,IS_IOS_BUILD=true)可透過 Apple
// Silicon Mac 的「iPhone 與 iPad App 在 Mac 上執行」直接裝進 macOS。這時
// IS_IOS_BUILD 仍是 true,但執行環境是 macOS Safari ——必須尊重 macOS 特性
// (popup 用桌面 popover 尺寸不放大、快速鍵提示用鍵盤而非四指 tap)。
//
// 「build 屬性」vs「平台屬性」分離(見 lib/distribution.js):
//   - 隱藏 PDF 入口是 **build 屬性**(translate-doc/ 被 strip)→ 不論 host OS
//     都要隱藏,沿用 body.runtime-ios(IS_IOS_BUILD 一律加)
//   - popup 放大 / 四指 tap 提示是 **平台屬性** → 只在真觸控裝置套用,Mac 上不套,
//     用 body.runtime-ios-touch(IS_IOS_BUILD && isTouchScreenDevice() 才加)
//
// 偵測訊號:Mac 沒有觸控螢幕 → navigator.maxTouchPoints === 0;真 iPhone / iPad
// 一律 ≥ 1。iPad 桌面模式雖把 navigator.platform 偽裝成 'MacIntel',maxTouchPoints
// 仍 = 5,所以不能用 platform 判,要用 maxTouchPoints(與 content-youtube.js 判
// 「iPad 偽裝 Mac」同一套訊號)。且為 **同步** 呼叫:popup zoom 必須在繪製前決定,
// 不能用 async 的 browser.runtime.getPlatformInfo()。
//
// 註:content-touch.js 的四指 tap 不需另外 gate —— Mac 無觸控硬體,根本不會派發
// TouchEvent,handler 在 Mac 上本就是 no-op(維持 IS_IOS_BUILD gate 即可)。

// 是否為真實觸控裝置(iPhone / iPad)。false = 桌面(含 iOS build 跑在 Mac)。
export function isTouchScreenDevice() {
  return typeof navigator !== 'undefined' && (navigator.maxTouchPoints || 0) >= 1;
}
