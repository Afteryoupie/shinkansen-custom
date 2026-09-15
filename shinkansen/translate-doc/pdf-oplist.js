// pdf-oplist.js — PDF.js operator list 的輕量判斷（批次 7 §6.4，2026-09-14）
//
// 解析階段（pdf-engine.js parsePdf，opList 已為字型載入取得）與 renderer
//（pdf-renderer.js 底色取樣前置判斷）共用的單一資料源。獨立成檔是因為 renderer 不能
// import pdf-engine.js——那支模組載入時就呼叫 chrome.runtime.getURL 設 worker 路徑，
// node 端的 renderer unit spec 沒有這個 API 會炸。
import * as pdfjsLib from '../lib/vendor/pdfjs/pdf.min.mjs';

/**
 * 頁面是否可能有彩色底（有任何填色 / 影像 / 漸層 / form 繪圖指令）。純文字頁回 false，
 * renderer 據此跳過整頁 rasterize 取樣（書籍 / 論文類 200 頁實測每頁 ≈ 0.2s）。
 * opList 缺席 / 結構不明 → true（保守：照樣取樣）。
 */
export function pageMayHaveColoredBackground(opList) {
  const OPS = pdfjsLib.OPS;
  if (!opList || !opList.fnArray || !OPS) return true;
  const colorOps = new Set([OPS.fill, OPS.eoFill, OPS.fillStroke, OPS.eoFillStroke, OPS.closeFillStroke, OPS.closeEOFillStroke,
    OPS.shadingFill, OPS.paintImageXObject, OPS.paintInlineImageXObject, OPS.paintJpegXObject, OPS.paintImageMaskXObject,
    OPS.paintImageXObjectRepeat, OPS.paintImageMaskXObjectRepeat, OPS.paintImageMaskXObjectGroup, OPS.paintFormXObjectBegin, OPS.beginGroup].filter((v) => v != null));
  return opList.fnArray.some((fn) => colorOps.has(fn));
}
