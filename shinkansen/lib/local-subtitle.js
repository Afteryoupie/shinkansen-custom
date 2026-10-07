// 本地模型字幕：序列化推論，避免 Apple / 單模型端點同時收到多個影片批次。
export function isLocalSubtitleProvider(provider) {
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
  return `Translate the entire subtitle into ${language}. Output only the translation on one line. ` +
    'Translate dialogue and greetings completely. Keep names, brands and technical abbreviations. ' +
    'Do not add explanations or invent missing words. Use spaces for pauses, without punctuation.';
}
