// Shared by classic content scripts and ES modules: one set of webpage limits.
(function () {
  function isOpenRouter(baseUrl) {
    try { return ['openrouter.ai', 'eu.openrouter.ai', 'us.openrouter.ai'].includes(new URL(baseUrl).hostname); }
    catch { return false; }
  }
  function isFreeProvider(provider) {
    return isOpenRouter(provider?.baseUrl) && /:free$/.test(provider?.model || '');
  }
  function inferType(baseUrl) {
    try {
      const host = new URL(baseUrl).hostname.toLowerCase();
      return ['localhost', '[::1]'].includes(host) || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) ||
        host.endsWith('.local') ? 'local' : 'online';
    } catch { return 'local'; }
  }
  const fields = {
    webConcurrency: [1, 50], webBatchUnits: [1, 100], webBatchChars: [500, 20000],
  };
  function config(provider = {}, type = 'online') {
    const local = type === 'local';
    const free = !local && isFreeProvider(provider);
    const values = {
      webConcurrency: local ? 1 : free ? 2 : 6,
      webBatchUnits: local || free ? 40 : 20,
      webBatchChars: local || free ? 7000 : 3500,
      firstBatchUnits: local ? 4 : 6, firstBatchChars: local ? 1000 : 1200,
    };
    for (const [key, [min, max]] of Object.entries(fields)) {
      if (Number.isInteger(provider[key]) && provider[key] >= min && provider[key] <= max) values[key] = provider[key];
    }
    // Free-tier concurrency does not remove the account's request-rate limit.
    if (free) values.webConcurrency = Math.min(values.webConcurrency, 2);
    values.firstBatchUnits = Math.min(values.firstBatchUnits, values.webBatchUnits);
    values.firstBatchChars = Math.min(values.firstBatchChars, values.webBatchChars);
    return values;
  }
  globalThis.__SKProviderPerformance = { isOpenRouter, isFreeProvider, inferType, config, fields };
})();
