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

  _decision(answer) {
    if (answer?.action?.act_probability < 0.5) return null;
    const p = answer?.noul;
    if (answer?.type !== 'noul' || typeof p !== 'number' || !Number.isFinite(p) || p < 0 || p > 1) return null;
    if (p >= this.confidenceThreshold) return true;
    if (p <= 1 - this.confidenceThreshold) return false;
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

  async evaluateBatch(texts, targetLang = 'zh-TW') {
    this.lastError = null;
    if (!Array.isArray(texts)) return [];
    const verdicts = texts.map(text => this.fallbackEvaluate(text, targetLang));
    if (!this.enabled) return verdicts;
    // Two questions per text, at most 32 questions per request.
    for (let offset = 0; offset < texts.length; offset += 16) {
      const batch = texts.slice(offset, offset + 16);
      const questions = {};
      batch.forEach((_, i) => {
        questions[`valid_${i}`] = { type: 'noul', instructions: `Is texts[${i}] human dialogue rather than a sound-effect tag or transcription noise? Preserve greetings and repeated speech.` };
        questions[`needs_${i}`] = { type: 'noul', instructions: `Does texts[${i}] need translation to ${targetLang}? Pure Han characters alone do not establish that Japanese text is Chinese.` };
      });
      const answers = await this._request({ texts: batch, targetLanguage: targetLang }, questions);
      if (!answers) break;
      batch.forEach((_, i) => {
        const valid = this._decision(answers[`valid_${i}`]);
        const needs = this._decision(answers[`needs_${i}`]);
        if (valid === null) return;
        const fallback = verdicts[offset + i];
        verdicts[offset + i] = {
          ...fallback,
          is_valid: fallback.is_valid && valid,
          needs_translation: fallback.is_valid && valid && (needs ?? true),
          source: 'laya',
        };
      });
    }
    return verdicts;
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

  fallbackEvaluate(text, targetLang = 'zh-TW') {
    const t = (text || '').trim();
    const is_valid = t.length > 0 && !LayaDecisionEngine.HALLUCINATION_PATTERNS.some(pattern => pattern.test(t));
    const detected_lang = /[\u3040-\u30ff]/.test(t) ? 'ja'
      : /[\uac00-\ud7af]/.test(t) ? 'ko'
      : /[\u4e00-\u9fff]/.test(t) ? 'auto' : 'en';
    // Han-only text may be Japanese. Without source-language evidence, keep translation enabled.
    return { is_valid, needs_translation: is_valid, detected_lang, confidence: 0.85, source: 'fallback' };
  }
}

// Preserve existing imports/settings while switching the provider to local Laya.
export { LayaDecisionEngine as JevDecisionEngine };
