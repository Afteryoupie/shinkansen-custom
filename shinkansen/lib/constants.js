// constants.js — lib/ 與 content script 共用的批次翻譯數值常數
//
// 注意：content-ns.js（content script 環境）因為不能用 ES module import，
// 以 SK.DEFAULT_UNITS_PER_BATCH / SK.DEFAULT_CHARS_PER_BATCH 鏡像這兩個值。
// 修改此檔時必須同步更新 content-ns.js 的對應常數。

/**
 * 每批翻譯段數上限：避免單批 placeholder slot 過多導致 LLM 對齊失準。
 * v1.5.8 起 12 → 20；2026-09-14 起 20 → 40（與字元預算同步翻倍）。
 * 依據：每批固定 prompt 開銷約 2,400 token（system prompt + 禁用詞 + 格式規則），
 * 20 段 / 3,500 字元時佔 input 65%；實測 HN 討論串（968 段）批次 52 → 25、
 * input token 191K → 126K、費用 −10%、首批可見時間不變、整頁完成時間不變；
 * 對齊錯號 HN 25 批 1 次（seq marker 自動對回）、維基百科 40 批 0 次。
 * 文件翻譯（translate-doc）早已用每批 50 段驗證同一佔位符協定可承受。
 */
export const DEFAULT_UNITS_PER_BATCH = 40;

/**
 * 每批字元預算上限（7000 chars ≈ 2000 英文 tokens）。2026-09-14 起 3500 → 7000，
 * 理由見上。維基百科實測單批最大 output 4,481 token，距 maxOutputTokens 8192 仍有餘裕；
 * 超出時走 output truncated → 逐段 fallback 路徑（不寫快取）。
 */
export const DEFAULT_CHARS_PER_BATCH = 7000;
