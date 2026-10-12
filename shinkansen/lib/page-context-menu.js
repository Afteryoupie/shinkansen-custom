import { browser } from './compat.js';
import { getSettingsCached, pickPopupSlot } from './storage.js';

const MENU_ID = 'shinkansen-page-action';
let refreshVersion = 0;
const warn = error => console.warn('[shinkansen] context menu:', error?.message || error);

export async function refreshPageContextMenu() {
  if (!browser.contextMenus) return;
  const version = ++refreshVersion;
  try {
    const [tab] = await browser.tabs.query({ active: true, lastFocusedWindow: true });
    const restore = tab?.id != null && !!(await browser.action.getBadgeText({ tabId: tab.id }));
    if (version !== refreshVersion) return;
    await browser.contextMenus.update(MENU_ID, {
      title: browser.i18n.getMessage(restore ? 'contextShowOriginal' : 'contextTranslatePage') ||
        (restore ? '顯示原文' : '翻譯本頁'),
    });
  } catch (error) { warn(error); }
}

export function registerPageContextMenus(getSettings = getSettingsCached) {
  if (!browser.contextMenus) return;
  async function rebuild() {
    await browser.contextMenus.removeAll();
    await new Promise((resolve, reject) => {
      browser.contextMenus.create({
        id: MENU_ID, title: browser.i18n.getMessage('contextTranslatePage') || '翻譯本頁',
        contexts: ['page', 'frame', 'selection', 'link', 'image', 'video', 'audio', 'editable'],
        documentUrlPatterns: ['http://*/*', 'https://*/*', 'file:///*'],
      }, () => browser.runtime.lastError ? reject(browser.runtime.lastError) : resolve());
    });
    await refreshPageContextMenu();
  }
  const refresh = () => rebuild().catch(warn);
  browser.runtime.onInstalled.addListener(refresh);
  browser.runtime.onStartup?.addListener(refresh);
  browser.tabs.onActivated.addListener(refreshPageContextMenu);
  browser.windows?.onFocusChanged?.addListener(refreshPageContextMenu);
  browser.contextMenus.onClicked.addListener(async (info, tab) => {
    if (tab?.id == null || info.menuItemId !== MENU_ID) return;
    try {
      const restore = !!(await browser.action.getBadgeText({ tabId: tab.id }));
      const message = restore
        ? { type: 'RESTORE_PAGE' }
        : { type: 'TRANSLATE_PRESET', payload: {
          slot: pickPopupSlot((await getSettings()).popupButtonSlot), force: true, translateOnly: true,
        } };
      await browser.tabs.sendMessage(tab.id, message, { frameId: 0 });
      await refreshPageContextMenu();
    } catch (error) { warn(error); }
  });
}
