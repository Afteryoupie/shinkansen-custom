// theme.js — Shinkansen 介面主題管理（石板海軍珊瑚 白色版 / 深色版 / 跟隨系統）
import { browser } from './compat.js';

/**
 * 解析出實際運行的主題（'light' 或 'dark'）
 * @param {string} themePref - 'auto' | 'light' | 'dark'
 * @returns {'light' | 'dark'}
 */
export function resolveEffectiveTheme(themePref) {
  if (themePref === 'light' || themePref === 'dark') {
    return themePref;
  }
  // 'auto' 或未設定：偵測系統深淺色外觀
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return 'light';
}

/**
 * 套用主題至 document.documentElement
 * @param {string} themePref - 'auto' | 'light' | 'dark'
 * @returns {'light' | 'dark'} effective theme
 */
export function applyTheme(themePref) {
  const effective = resolveEffectiveTheme(themePref);
  document.documentElement.setAttribute('data-theme', effective);
  document.documentElement.setAttribute('data-theme-pref', themePref || 'auto');
  return effective;
}

/**
 * 初始化主題設定並掛載變更監聽器
 * @param {Function} [onChangeCallback] - 當主題變更時回呼 (pref, effective)
 * @returns {Promise<string>} 載入的主題偏好
 */
export async function initTheme(onChangeCallback) {
  let savedPref = 'auto';
  try {
    const res = await browser.storage.sync.get('uiTheme');
    if (res?.uiTheme) savedPref = res.uiTheme;
  } catch (_e) {
    try {
      const res = await browser.storage.local.get('uiTheme');
      if (res?.uiTheme) savedPref = res.uiTheme;
    } catch (_err) {}
  }

  applyTheme(savedPref);

  // 監聽系統深淺色切換（當偏好為 auto 時即時更新）
  if (typeof window !== 'undefined' && window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', () => {
      const currentPref = document.documentElement.getAttribute('data-theme-pref') || 'auto';
      if (currentPref === 'auto') {
        const eff = applyTheme('auto');
        if (onChangeCallback) onChangeCallback('auto', eff);
      }
    });
  }

  // 監聽跨分頁 / 跨視窗之 storage 變更
  if (browser?.storage?.onChanged) {
    browser.storage.onChanged.addListener((changes, area) => {
      if ((area === 'sync' || area === 'local') && changes.uiTheme) {
        const newPref = changes.uiTheme.newValue || 'auto';
        const eff = applyTheme(newPref);
        if (onChangeCallback) onChangeCallback(newPref, eff);
      }
    });
  }

  return savedPref;
}
