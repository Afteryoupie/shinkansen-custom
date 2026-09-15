// custom/yt-player-btn.js — Shinkansen YouTube 播放器控制列專屬按鈕與 Alt+C 快捷鍵外掛模組
// 獨立模組：非侵入式載入，100% 不修改官方 content-youtube.js 原檔

(function(SK) {
  if (!SK || SK.disabled) return;

  const BTN_ID = '__sk_yt_trans_btn';

  // 播放器圖示 SVG：未開啟為空心白框、開啟後為實心白底黑字
  const _SK_YT_ICON_SVG = `
    <g class="__sk_yt_icon_off" style="display: block;">
      <rect x="2.5" y="4.5" width="19" height="15" rx="3" fill="none" stroke="#ffffff" stroke-width="1.8"/>
      <g transform="translate(12, 12) scale(0.58) translate(-12, -12)">
        <path fill="#ffffff" d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/>
      </g>
    </g>
    <g class="__sk_yt_icon_on" style="display: none;">
      <rect x="2.5" y="4.5" width="19" height="15" rx="3" fill="#ffffff"/>
      <g transform="translate(12, 12) scale(0.58) translate(-12, -12)">
        <path fill="#0f0f0f" d="M12.87 15.07l-2.54-2.51.03-.03c1.74-1.94 2.98-4.17 3.71-6.53H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z"/>
      </g>
    </g>
  `;

  function _updatePlayerButtonState() {
    const btn = document.getElementById(BTN_ID);
    if (!btn) return;
    const active = SK.YT?.active === true;
    const targetState = active ? 'true' : 'false';

    if (btn.getAttribute('data-active') === targetState) return;
    btn.setAttribute('data-active', targetState);
    btn.setAttribute('aria-pressed', targetState);
    btn.title = active ? '點擊關閉 Shinkansen AI 字幕翻譯 (Alt+C)' : '點擊開啟 Shinkansen AI 字幕翻譯 (Alt+C)';

    const offGroup = btn.querySelector('.__sk_yt_icon_off');
    const onGroup = btn.querySelector('.__sk_yt_icon_on');
    if (offGroup) offGroup.style.display = active ? 'none' : 'block';
    if (onGroup) onGroup.style.display = active ? 'block' : 'none';
  }

  // 乾淨劫持官方翻譯生命週期以自動同步按鈕燈號
  if (SK.translateYouTubeSubtitles) {
    const _origTranslate = SK.translateYouTubeSubtitles;
    SK.translateYouTubeSubtitles = async function(...args) {
      try {
        const res = await _origTranslate.apply(this, args);
        _updatePlayerButtonState();
        return res;
      } finally {
        _updatePlayerButtonState();
      }
    };
  }

  if (SK.stopYouTubeTranslation) {
    const _origStop = SK.stopYouTubeTranslation;
    SK.stopYouTubeTranslation = function(...args) {
      const res = _origStop?.apply(this, args);
      _updatePlayerButtonState();
      return res;
    };
  }

  let _isInjecting = false;

  function _injectPlayerButton() {
    if (_isInjecting) return;
    _isInjecting = true;
    try {
      const rightControls = document.querySelector('.ytp-right-controls');
      if (!rightControls) return;

      const ccBtn = rightControls.querySelector('.ytp-subtitles-button');
      const anchor = (ccBtn && ccBtn.parentNode === rightControls)
        ? ccBtn
        : (ccBtn ? ccBtn.closest('.ytp-right-controls > *') : null);
      const target = anchor || rightControls.querySelector('.ytp-settings-button') || rightControls.firstChild;

      let btn = document.getElementById(BTN_ID);
      if (btn) {
        if (btn.parentNode === rightControls) {
          if (anchor && anchor.parentNode === rightControls && btn.nextSibling !== anchor) {
            rightControls.insertBefore(btn, anchor);
          }
        } else {
          if (target && target.parentNode === rightControls && target !== btn) {
            rightControls.insertBefore(btn, target);
          } else {
            rightControls.appendChild(btn);
          }
        }
        _updatePlayerButtonState();
        return;
      }

      btn = document.createElement('button');
      btn.id = BTN_ID;
      btn.className = 'ytp-button __sk_yt_btn';
      btn.type = 'button';
      btn.style.position = 'relative';
      btn.style.width = '48px';
      btn.style.height = '100%';
      btn.style.verticalAlign = 'top';
      btn.style.cursor = 'pointer';
      btn.style.display = 'inline-flex';
      btn.style.alignItems = 'center';
      btn.style.justifyContent = 'center';
      btn.setAttribute('aria-label', 'Shinkansen AI 字幕翻譯 (Alt+C)');

      const active = SK.YT?.active === true;
      btn.setAttribute('data-active', active ? 'true' : 'false');
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      btn.title = active ? '點擊關閉 Shinkansen AI 字幕翻譯 (Alt+C)' : '點擊開啟 Shinkansen AI 字幕翻譯 (Alt+C)';

      btn.innerHTML = `
        <svg class="__sk_yt_icon" viewBox="0 0 24 24" width="22" height="22">
          ${_SK_YT_ICON_SVG}
        </svg>
      `;

      const offGroup = btn.querySelector('.__sk_yt_icon_off');
      const onGroup = btn.querySelector('.__sk_yt_icon_on');
      if (offGroup) offGroup.style.display = active ? 'none' : 'block';
      if (onGroup) onGroup.style.display = active ? 'block' : 'none';

      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        SK.translateYouTubeSubtitles({ source: 'manual' }).then(() => {
          _updatePlayerButtonState();
        });
      });

      if (target && target.parentNode === rightControls && target !== btn) {
        rightControls.insertBefore(btn, target);
      } else {
        rightControls.appendChild(btn);
      }
    } finally {
      _isInjecting = false;
    }
  }

  // 快捷鍵：Alt+C 觸發 YouTube 字幕翻譯
  window.addEventListener('keydown', (e) => {
    if (e.target && ['input', 'textarea'].includes(e.target.tagName?.toLowerCase())) return;
    if (e.altKey && (e.key === 'c' || e.key === 'C')) {
      e.preventDefault();
      SK.translateYouTubeSubtitles({ source: 'manual' }).then(() => {
        _updatePlayerButtonState();
      });
    }
  }, true);

  // 監聽 DOM 變更確保換影片時按鈕依然存在
  if (typeof MutationObserver !== 'undefined') {
    let _injectTimer = null;
    const _playerObserver = new MutationObserver(() => {
      if (_injectTimer) return;
      _injectTimer = setTimeout(() => {
        _injectTimer = null;
        if (document.querySelector('.ytp-right-controls')) {
          _injectPlayerButton();
        }
      }, 150);
    });
    _playerObserver.observe(document.body, { childList: true, subtree: true });
  }

  // 初次掛載注入
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _injectPlayerButton);
  } else {
    _injectPlayerButton();
  }

})(window.__SK);
