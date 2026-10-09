/** Local Laya typed decisions. Uncertain or failed decisions retain local speech. */
export const LAYA_API_URL = 'http://127.0.0.1:8080/v1/systemone';
export class LayaDecisionEngine {
  constructor(options = {}) {
    this.enabled = options.enabled ?? false;
    this.apiUrl = options.apiUrl || LAYA_API_URL;
    this.apiKey = options.apiKey || '';
    // Includes cold-start time after Watchdog unloads an idle model.
    this.timeoutMs = options.timeoutMs ?? 90_000;
    this.confidenceThreshold = options.confidenceThreshold ?? 0.8;
    this.lastError = null;
  }

  static HALLUCINATION_PATTERNS = [
    /^\[(音楽|拍手|笑い|歓声|music|applause|laughter|silence)\]$/i,
    /^[♪♫♩♬\s.,!?:;_\-]+$/,
  ];

  _decision(answer, threshold = this.confidenceThreshold) {
    if (answer?.action?.act_probability < 0.5) return null;
    const p = answer?.noul;
    if (answer?.type !== 'noul' || typeof p !== 'number' || !Number.isFinite(p) || p < 0 || p > 1) return null;
    if (p >= threshold) return true;
    if (p <= 1 - threshold) return false;
    return null;
  }

  async _request(state, questions) {
    const controller = new AbortController();
    let timer;
    try {
      const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(new Error('timeout'));
          controller.abort();
        }, this.timeoutMs);
      });
      const request = (async () => {
        const response = await fetch(this.apiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}) },
          body: JSON.stringify({ model: 'laya-multilingual', state, questions }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (!data?.answers || typeof data.answers !== 'object' || Array.isArray(data.answers)) throw new Error('invalid answers');
        return data.answers;
      })();
      return await Promise.race([request, timeout]);
    } catch (error) {
      this.lastError = controller.signal.aborted ? 'timeout' : error.message;
      return null;
    } finally {
      clearTimeout(timer);
      controller.abort();
    }
  }

  async evaluateBatch(texts, targetLang = 'zh-TW', sourceLanguage = 'auto') {
    this.lastError = null;
    if (!Array.isArray(texts)) return [];
    const verdicts = texts.map(text => this.fallbackEvaluate(text, targetLang, sourceLanguage));
    if (!this.enabled) return verdicts;
    // Two questions per text, at most 32 questions per request.
    for (let offset = 0; offset < texts.length; offset += 16) {
      const batch = texts.slice(offset, offset + 16);
      if (verdicts.slice(offset, offset + 16).every(verdict => !verdict.is_valid || !verdict.needs_translation)) continue;
      const questions = {};
      batch.forEach((_, i) => {
        questions[`valid_${i}`] = { type: 'noul', instructions: `Is texts[${i}] human dialogue rather than a sound-effect tag or transcription noise? Preserve greetings and repeated speech.` };
        questions[`needs_${i}`] = { type: 'noul', instructions: `Does texts[${i}] need translation to ${targetLang}? Pure Han characters alone do not establish that Japanese text is Chinese.` };
      });
      if (batch.some(text => typeof text !== 'string' || text.length > 1000)) continue;
      const answers = await this._request({ task: 'subtitle_filter', texts: batch, targetLanguage: targetLang, sourceLanguage }, questions);
      if (!answers) break;
      batch.forEach((_, i) => {
        // Dropping speech has a higher cost than an unnecessary translation.
        let valid = this._decision(answers[`valid_${i}`], 0.95);
        let needs = this._decision(answers[`needs_${i}`], 0.95);
        // Han-only Japanese is ambiguous without reliable language evidence.
        if (/^zh/.test(targetLang) && /[\u3400-\u9fff]/.test(batch[i]) &&
            /^(auto|ja)/.test(sourceLanguage) && !/[\u3040-\u30ff\uac00-\ud7afA-Za-z]/.test(batch[i])) needs = true;
        // The zero-shot classifier can confidently mistake speech for noise.
        // Only explicitly bracketed nonverbal captions or symbols may be hidden.
        if (valid === false && /[\p{L}\p{N}]/u.test(batch[i]) && !/^\[[^\]]+\]$/.test(batch[i])) valid = true;
        if (valid === null) {
          const answer = answers[`valid_${i}`];
          const wellFormed = answer?.type === 'noul' && typeof answer.noul === 'number' &&
            Number.isFinite(answer.noul) && answer.noul >= 0 && answer.noul <= 1 && !(answer.action?.act_probability < 0.5);
          // A confident preserve decision can stand without a noise verdict.
          if (needs !== false || !wellFormed) return;
          valid = true;
        }
        const fallback = verdicts[offset + i];
        verdicts[offset + i] = {
          ...fallback,
          is_valid: fallback.is_valid && valid,
          needs_translation: fallback.is_valid && valid && fallback.needs_translation && (needs ?? true),
          source: 'laya',
        };
      });
    }
    return verdicts;
  }

  async reviewFormatBatch(texts, translations, targetLanguage = 'zh-TW', sourceLanguage = 'auto') {
    this.lastError = null;
    const verdicts = texts.map((text, i) => this.fallbackReviewFormat(translations[i]));
    if (!this.enabled) return verdicts;
    for (let offset = 0; offset < texts.length; offset += 32) {
      const pairs = texts.slice(offset, offset + 32).map((source, i) => ({ source, translation: translations[offset + i] }));
      const eligible = pairs.flatMap((pair, i) => !verdicts[offset + i].needs_repair && typeof pair.translation === 'string' && pair.translation.trim() &&
        pair.source.length <= 1000 && pair.translation.length <= 1000 ? [i] : []);
      if (!eligible.length) continue;
      const questions = Object.fromEntries(eligible.map((_, i) => [`error_${i}`, { type: 'noul',
        instructions: 'Is this output malformed for a plain single-line subtitle? Check format only, not meaning or translation quality.' }]));
      const answers = await this._request({ task: 'subtitle_format', pairs: eligible.map(i => pairs[i]), targetLanguage, sourceLanguage }, questions);
      if (!answers) break;
      eligible.forEach((index, i) => {
        const answer = answers[`error_${i}`];
        const error = this._decision(answer, 0.9);
        if (error !== null) verdicts[offset + index] = { needs_repair: error,
          reason: 'format', source: 'laya' };
      });
    }
    return verdicts;
  }

  fallbackReviewFormat(translation) {
    const invalid = typeof translation !== 'string' || !translation.trim() ||
      /[\r\n]|```|\[SEG_?\d+\]/i.test(translation) || /^\s*(?:\{[\s\S]*\}|\[\s*["{])/.test(translation);
    return { needs_repair: invalid, reason: invalid ? 'format' : null, source: 'fallback' };
  }

  async evaluateBoundaries(segments) {
    this.lastError = null;
    if (!Array.isArray(segments)) segments = [];
    const breakBefore = Array(segments.length).fill(null);
    let source = 'fallback';
    if (!this.enabled) return { breakBefore, source };
    // Limit one evaluation to 128 boundaries. The remaining segments retain local rules.
    const count = Math.min(segments.length - 1, 128);
    for (let offset = 0; offset < count; offset += 32) {
      const boundaries = [], questions = {};
      for (let i = 0; i < Math.min(32, count - offset); i++) {
        const index = offset + i + 1;
        boundaries.push({ left: segments[index - 1].text, right: segments[index].text });
        questions[`boundary_${i}`] = { type: 'noul', instructions: `Does boundaries[${i}].right begin a new sentence rather than continue boundaries[${i}].left?` };
      }
      const answers = await this._request({ boundaries }, questions);
      if (!answers) break;
      boundaries.forEach((_, i) => {
        const decision = this._decision(answers[`boundary_${i}`]);
        if (decision !== null) {
          breakBefore[offset + i + 1] = decision;
          source = 'laya';
        }
      });
    }
    return { breakBefore, source };
  }

  fallbackEvaluate(text, targetLang = 'zh-TW', sourceLanguage = 'auto') {
    const t = (text || '').trim();
    const is_valid = t.length > 0 && !LayaDecisionEngine.HALLUCINATION_PATTERNS.some(pattern => pattern.test(t));
    const detected_lang = /[\u3040-\u30ff]/.test(t) ? 'ja'
      : /[\uac00-\ud7af]/.test(t) ? 'ko'
      : /[\u4e00-\u9fff]/.test(t) ? 'auto' : 'en';
    const words = t.match(/[A-Za-z]+/g) || [];
    const identifier = /\b[A-Z][A-Z0-9-]*\d[A-Za-z0-9-]*\b/.test(t) && words.length <= 3 &&
      !/\b(?:i|you|we|they|he|she|it|is|are|was|were|have|has|will|can|could|should)\b/i.test(t);
    const base = language => language.split('-')[0];
    const sameLanguage = sourceLanguage !== 'auto' && base(sourceLanguage) === base(targetLang) &&
      (!/^zh/.test(targetLang) || sourceLanguage.toLowerCase() === targetLang.toLowerCase());
    const matchesScript = /^zh/.test(targetLang) ? /[\u3400-\u9fff]/.test(t) && !/[\u3040-\u30ff\uac00-\ud7af]/.test(t)
      : /^ja/.test(targetLang) ? /[\u3040-\u30ff\u3400-\u9fff]/.test(t)
      : /^ko/.test(targetLang) ? /[\uac00-\ud7af]/.test(t)
      : /[A-Za-z]/.test(t) && !/[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(t);
    // Reliable source metadata can establish the target language; Han-only text by itself cannot.
    return { is_valid, needs_translation: is_valid && !identifier && !(sameLanguage && matchesScript),
      detected_lang, confidence: 0.85, source: 'fallback' };
  }
}

// Preserve existing imports/settings while switching the provider to local Laya.
export { LayaDecisionEngine as JevDecisionEngine };
