// 本地模型字幕：序列化推論，避免 Apple / 單模型端點同時收到多個影片批次。
export function isLocalSubtitleProvider(provider) {
  if (provider?.profileType === 'local') return true;
  if (provider?.profileType === 'online') return false;
  try {
    return ['localhost', '127.0.0.1', '[::1]'].includes(new URL(provider?.baseUrl || '').hostname) ||
      /apple|foundation.?models/i.test(provider?.model || '');
  } catch (_) { return false; }
}

const queues = new Map();
export function queueLocalSubtitle(provider, run) {
  if (!isLocalSubtitleProvider(provider)) return run();
  const key = new URL(provider.baseUrl).origin;
  const previous = queues.get(key) || Promise.resolve();
  const next = previous.catch(() => {}).then(run);
  queues.set(key, next);
  // 清理成功與失敗的佇列尾端，不留下 unhandled rejection。
  const clear = () => { if (queues.get(key) === next) queues.delete(key); };
  next.then(clear, clear);
  return next;
}

export function localSubtitlePrompt(targetLanguage) {
  const language = targetLanguage === 'zh-TW' ? '台灣繁體中文' : targetLanguage;
  return `Translate ALL speech to ${language}. Output only one line, no explanations or punctuation. ` +
    'Keep names brands numbers and profanity. Remove sound-effect tags only. Never omit dialogue or complete unfinished sentences.';
}
