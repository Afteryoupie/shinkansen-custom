/**
 * lib/jev.js — TypeSafe AI Jev (System One) 類型化決策模組
 * 專為 YouTube 字幕與影片翻譯設計的次秒級決策過濾層：
 *   1. is_valid (Boolean): 判定是否為有效人聲發言（過濾純音效標籤 [Music]、[Applause]、♪、幻覺字幕）
 *   2. needs_translation (Boolean): 判定是否需要翻譯（僅在已是目標語言時放行原文）
 *   3. detected_lang (Choice): 語意語系判定 (ja, en, ko, zh, etc.)
 *
 * 高可用性（Graceful Fallback）：
 *   - 若未啟用、未填 API Key、網路異常或回應逾時，自動無縫降級走本地啟發式規則。
 *   - 完全不阻斷或崩潰任何既有翻譯管線。
 */

export class JevDecisionEngine {
  constructor(options = {}) {
    this.enabled = options.enabled ?? false;
    this.apiUrl = options.apiUrl || 'https://api.typesafe.ai/v1/systemone';
    this.apiKey = options.apiKey || '';
    this.timeoutMs = options.timeoutMs || 600;
    this.confidenceThreshold = options.confidenceThreshold || 0.6;
  }

  // 本地啟發式正則（純本地兜底使用）
  static HALLUCINATION_PATTERNS = [
    /^\[(音楽|拍手|笑い|歓声|music|applause|laughter|silence)\]$/i,
    /^[♪♫♩♬\s.,!?:;_\-]+$/,
  ];

  /**
   * 批次評估多個字幕文字
   * @param {string[]} texts
   * @param {string} targetLang - 目標語言代碼 (如 'zh-TW')
   * @returns {Promise<Array<{is_valid: boolean, needs_translation: boolean, detected_lang: string, confidence: number, source: string}>>}
   */
  async evaluateBatch(texts, targetLang = 'zh-TW') {
    if (!Array.isArray(texts) || texts.length === 0) return [];

    // 若未啟用或無 Key，直接逐條走本地啟發式規則
    if (!this.enabled || !this.apiKey) {
      return texts.map(t => this.fallbackEvaluate(t, targetLang));
    }

    const t0 = Date.now();
    const questions = texts.map((t, idx) => ({
      context: (t || '').trim(),
      questions: [
        {
          id: `valid_${idx}`,
          type: 'boolean',
          question: 'Is this text valid human dialogue rather than music/sound effect tags or transcription hallucination?',
        },
        {
          id: `needs_${idx}`,
          type: 'boolean',
          question: `Does this text need translation to ${targetLang}? (False only if already entirely in ${targetLang}; greetings must also be translated)`,
        },
        {
          id: `lang_${idx}`,
          type: 'choice',
          question: 'What is the primary spoken language of this text?',
          choices: ['ja', 'en', 'ko', 'zh', 'other'],
        },
      ],
    }));

    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);

      const resp = await fetch(this.apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`,
        },
        body: JSON.stringify({ items: questions }),
        signal: controller.signal,
      });
      clearTimeout(timer);

      if (resp.ok) {
        const data = await resp.json();
        const decisions = data.decisions || {};
        return texts.map((t, idx) => {
          const v = decisions[`valid_${idx}`];
          const n = decisions[`needs_${idx}`];
          const l = decisions[`lang_${idx}`];
          const fallback = this.fallbackEvaluate(t, targetLang);
          if (!v || !n || typeof v.answer !== 'boolean' || typeof n.answer !== 'boolean' ||
              Math.min(v.confidence ?? 0, n.confidence ?? 0) < this.confidenceThreshold) return fallback;

          return {
            is_valid: fallback.is_valid,
            needs_translation: fallback.needs_translation || n.answer,
            detected_lang: l?.answer || 'auto',
            confidence: ((v.confidence || 1) + (n.confidence || 1)) / 2,
            source: 'jev',
            latencyMs: Date.now() - t0,
          };
        });
      }
    } catch (err) {
      // 網路逾時或異常，直接降級走本地規則
    }

    return texts.map(t => this.fallbackEvaluate(t, targetLang));
  }

  /**
   * 本地啟發式評估
   */
  fallbackEvaluate(text, targetLang = 'zh-TW') {
    const t = (text || '').trim();
    if (t.length === 0) {
      return { is_valid: false, needs_translation: false, detected_lang: 'auto', confidence: 1.0, source: 'fallback' };
    }

    // 1. 幻覺與音效標籤過濾
    let is_valid = true;
    for (const pat of JevDecisionEngine.HALLUCINATION_PATTERNS) {
      if (pat.test(t)) {
        is_valid = false;
        break;
      }
    }
    // 2. 語言與翻譯需求判定
    const hasKana = /[\u3040-\u30ff]/.test(t);
    const hasHangul = /[\uac00-\ud7af]/.test(t);
    const hasHanzi = /[\u4e00-\u9fff]/.test(t);

    let detected_lang = 'en';
    if (hasKana) detected_lang = 'ja';
    else if (hasHangul) detected_lang = 'ko';
    else if (hasHanzi && !hasKana) detected_lang = 'zh';

    let needs_translation = true;
    if (targetLang.startsWith('zh') && detected_lang === 'zh' && !/[A-Za-z]/.test(t)) {
      needs_translation = false;
    }

    return {
      is_valid,
      needs_translation,
      detected_lang,
      confidence: 0.85,
      source: 'fallback',
    };
  }
}
