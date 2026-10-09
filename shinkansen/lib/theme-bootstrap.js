// Classic script before CSS: restore the last preference before first paint.
// Only the appearance preference is cached; extension storage remains authoritative.
(() => {
  const root = document.documentElement;
  const valid = value => ['light', 'dark', 'auto'].includes(value);
  const apply = pref => {
    const effective = pref === 'auto' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : pref;
    root.setAttribute('data-theme', effective);
    root.setAttribute('data-theme-pref', pref);
  };
  let cached;
  try { cached = localStorage.getItem('sk-ui-theme'); } catch (_) {}
  if (valid(cached)) apply(cached);
  else {
    // Prevent the system-dark stylesheet from painting before a saved light theme.
    apply('light');
    root.setAttribute('data-theme-pending', '');
  }
  window.__skThemeReady = (async () => {
    let pref = valid(cached) ? cached : 'auto';
    const api = globalThis.browser || globalThis.chrome;
    try {
      const saved = await api.storage.sync.get('uiTheme');
      pref = valid(saved.uiTheme) ? saved.uiTheme : 'auto';
    } catch (_) {
      try {
        const saved = await api.storage.local.get('uiTheme');
        if (valid(saved.uiTheme)) pref = saved.uiTheme;
      } catch (_) {}
    }
    apply(pref);
    try { localStorage.setItem('sk-ui-theme', pref); } catch (_) {}
    root.removeAttribute('data-theme-pending');
    return pref;
  })();
})();
