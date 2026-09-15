// lib/bg-error.js — 背景端使用者面對錯誤的 error code 協定（SPEC-PRIVATE §27 錯誤字串族群）
//
// 為什麼背景不直接翻譯：service worker 載不了 lib/i18n.js（IIFE 掛 window），
// 也不知道使用者 uiLanguage（要 async 讀 settings），在 SW 端翻是錯的方向。
// 改成錯誤帶結構化 code（+ params）過協定（response.errorCode / errorParams、
// STREAMING_ERROR payload 同欄位），由 UI 端（content scripts / translate-doc）
// 用 lib/i18n.js 的 bgErrorMessage() 查 dict 組訊息。
//
// 相容性設計：
// - err.message 保留原字串當 fallback——沒對應 code 的錯誤（或 dict 缺 key 的
//   版本 drift）在 UI 端原樣顯示，不讓未知錯誤變空白
// - API 回的原始錯誤訊息（Gemini 英文 error.message 等）是 ground truth 證據，
//   不掛 code 原樣傳遞，或以 params（{msg} / {reason} / {preview}）帶進模板，
//   不被翻譯吞掉；完整原文另有 debugLog 紀錄
export function codedError(code, params, message) {
  const err = new Error(message);
  err.skCode = code;
  err.skParams = params || null;
  return err;
}
