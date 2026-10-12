import './provider-performance.js';

let nextFreeRequestAt = 0;

// Free-model calls share an account limit, including retries and glossary calls.
export function reserveFreeRequest(provider, now = Date.now()) {
  if (!globalThis.__SKProviderPerformance.isFreeProvider(provider)) return 0;
  const start = Math.max(now, nextFreeRequestAt);
  nextFreeRequestAt = start + 3100;
  return start - now;
}

export async function waitForFreeRequest(provider) {
  const delay = reserveFreeRequest(provider);
  if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay));
}
