// block-types.js — block type 共用常數(單一資料源)
//
// SPEC §17.4.4:這幾種 block type 送翻譯;其他(table / page-number 等)不送,
// 保留原文。原本 index.js / translate.js / reader.js / pdf-renderer.js 各抄一份,
// 收斂到此檔統一 import(四份手抄遲早 drift)。
//
// 注意:caption / formula / figure 是 classifyBlockType(layout-analyzer.js)
// 目前永不產出的預留 type——分類器未實作,僅 debug 色盤與此清單先佔位。
// 實際會出現的 type 只有 paragraph / heading / list-item / footnote /
// page-number / table。

export const TRANSLATABLE_TYPES = new Set(['paragraph', 'heading', 'list-item', 'caption', 'footnote']);
