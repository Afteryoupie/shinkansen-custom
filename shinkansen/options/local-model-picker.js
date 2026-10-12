// Keep the existing model input as the value used by save/test/subtitle handlers.
export function fillModelSelect(select, value, ids, defaultLabel) {
  select.replaceChildren(new Option(defaultLabel, ''));
  for (const id of new Set([...ids, ...(value ? [value] : [])])) {
    select.add(new Option(id.split(/[\\/]/).pop(), id));
  }
  select.value = value;
}

export function bindLocalModelPicker({ baseUrl, input, select, refresh, clear, status, hint, apiKey, t, onModels = () => {} }) {
  let request = 0;
  function endpoint() {
    try {
      const url = new URL(baseUrl.value.trim());
      return ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) &&
        ['http:', 'https:'].includes(url.protocol) ? url : null;
    } catch { return null; }
  }
  function render(ids = []) {
    fillModelSelect(select, input.value.trim(), ids, t('options.cp.localDefault'));
    onModels(ids);
  }
  async function update() {
    const token = ++request;
    const url = endpoint();
    input.hidden = !!url;
    hint.hidden = !!url;
    select.hidden = refresh.hidden = clear.hidden = status.hidden = !url;
    refresh.disabled = false;
    select.removeAttribute('aria-busy');
    if (!url) { onModels([]); return; }
    render();
    status.textContent = t('options.cp.localLoading');
    refresh.disabled = true;
    select.setAttribute('aria-busy', 'true');
    url.pathname = url.pathname.replace(/\/+$/, '').replace(/\/chat\/completions$/, '') + '/models';
    url.search = url.hash = '';
    try {
      const key = apiKey.value.trim();
      const response = await fetch(url.href, {
        headers: key ? { Authorization: `Bearer ${key}` } : {},
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      if (!Array.isArray(body.data)) throw new Error('Invalid model list');
      const ids = body.data.filter(model => typeof model.id === 'string' && model.id &&
        !(model.owned_by === 'local-llm' && (model.id === 'default' || /[/\\]/.test(model.id))))
        .map(model => model.id);
      if (token !== request) return;
      render(ids);
      status.textContent = t(ids.length ? 'options.cp.localReady' : 'options.cp.localEmpty');
    } catch {
      if (token !== request) return;
      status.textContent = t('options.cp.localError');
    } finally {
      if (token === request) {
        refresh.disabled = false;
        select.removeAttribute('aria-busy');
      }
    }
  }
  select.addEventListener('change', () => {
    input.value = select.value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  clear.addEventListener('click', () => {
    select.value = '';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  refresh.addEventListener('click', update);
  baseUrl.addEventListener('change', update);
  return update;
}
