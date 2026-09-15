// stream-reuse.js — streaming 批次 partial-reuse 規劃
//
// v1.10.61:streaming 路徑(background.js handleTranslateStream)改成「只補缺的」。
// 原本只要這批有一段快取 miss(allHit=false)就把整批 texts 重送 Gemini(含已快取段
// 落),跟 handleTranslate / openai-compat 的 missing-only 行為不一致 —— RSS feed 頂端
// 插入新文章時,新段落落進 batch 0 會讓整批連已翻段落一起重打 API。
//
// 本模組抽成純函式,讓「index 對映」這個唯一的新風險可被單元測試鎖死:
//   - cachedSegments[i].idx 必須是原始 texts 的 index(content 端 segmentIdx 對應
//     job.texts,emit 錯 index 會把譯文注入錯段落)
//   - missingIdxs[k] 把「送給 translateBatchStream 的 missingTexts 內的 index k」remap
//     回原始 texts 的 index(stream 的 onSegment 給的是 missingTexts 內的 index)
//   - missingTexts 用來寫回 cache(寫錯配對會永久污染快取)
//
// 不放任何副作用(不 import chrome / storage),純資料轉換,可直接被 spec import。

/**
 * 把一批 texts 依快取命中狀況分流。
 * @param {Array<string|null>} cached getBatch 回傳的等長陣列,命中為譯文字串、未命中為 null
 * @param {string[]} texts 原文陣列(與 cached 等長)
 * @returns {{
 *   missingIdxs: number[],          // 未命中段落在原始 texts 的 index(= stream missing-index 的 remap 表)
 *   missingTexts: string[],         // 未命中段落原文(送 translateBatchStream + 寫回 cache 用)
 *   cachedSegments: Array<{idx:number, translation:string}>  // 已命中段落(以原始 index 即刻回推 content)
 * }}
 */
export function planStreamingPartialReuse(cached, texts) {
  const missingIdxs = [];
  const missingTexts = [];
  const cachedSegments = [];
  for (let i = 0; i < texts.length; i++) {
    if (cached[i] == null) {
      missingIdxs.push(i);
      missingTexts.push(texts[i]);
    } else {
      cachedSegments.push({ idx: i, translation: cached[i] });
    }
  }
  return { missingIdxs, missingTexts, cachedSegments };
}
