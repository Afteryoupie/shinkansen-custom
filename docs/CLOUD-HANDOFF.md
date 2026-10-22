# 雲端 Codex 重構交接

日期：2026-10-23（Asia/Taipei）

## 可直接貼入雲端任務的指令

```text
請在 Afteryoupie/shinkansen-custom 執行 docs/REFACTOR-PLAN.md 的重構，先完整閱讀本文件與企劃。

使用者已選定：擴充功能 TypeScript、共用 Watchdog 核心 Go、保留 macOS LLMMenuBar.swift 原生介面，以及 Windows 原生右鍵系統匣。不要再次討論 Rust／Go 選型，不引入 Tauri 或重新設計托盤 UI。

重構前功能基準為 890778680f2e30cfbaef7e6d58367dfaa1b309ba，後續測試準備提交為 3defabe0c73e3fb2610849b06af9687240d7f188。先確認 checkout 包含兩者和本交接文件，讀取實際程式碼，重跑適用測試。沿用雲端任務分支或建立 refactor/typescript-go，不強推 main。

按 Phase 0 到 Phase 4 逐步實作並提交可審查的變更，持續更新 docs/CLOUD-HANDOFF.md 的執行進度、命令結果與待驗證項目。此任務是實作，不要只重新撰寫企劃。保留所有列出的行為與回退路徑；原生環境不可用時，繼續完成其餘獨立工作及可建置產物，明確標註缺少的實機證據。

遵守原始核心路徑執行規則；Agent、測試與背景服務不得依賴 .bat／.command。不要上傳本機設定、金鑰、模型或虛擬環境。不要啟動或停止不屬於測試的服務，不把 mock／交叉編譯當成真實瀏覽器、GPU 或 Mac／Windows GUI 驗證。必要時提供完整手動驗收命令。

完成後交付程式碼、建置／測試結果、Windows 與 macOS 安裝及回退說明、剩餘本機驗收清單，並建立供審查的 PR。尚未取得雙平台實測證據時保留舊實作與原預設啟動路徑，標示「待本機驗收」。
```

## 已完成的本地準備

- [x] 對本地未提交改動完成差異與常見憑證格式檢查。
- [x] 同步本地基準 `8907786` 至 `origin/main`。
- [x] 使用者確認 Go 核心＋保留 Swift。
- [x] 乾淨 Git 快照驗證；以 `3defabe` 移除兩個 Laya 測試的本機路徑依賴。
- [x] 將企劃、交接與驗證邊界寫入 Git。
- [ ] Phase 0：契約、fixture、fresh-clone 測試與相依項策略。
- [ ] Phase 1：Go 無介面核心。
- [ ] Phase 2：Native Host、Windows tray、macOS launcher／App。
- [ ] Phase 3：TypeScript 與可載入擴充功能產物。
- [ ] Phase 4：雙平台實機驗收、預設入口切換與舊碼整理。

最後五項尚未開始，勿將文件提交視為實作完成。

## 基準包含什麼

- Watchdog 狀態探測與明確喚醒、依 origin／model 合併啟動、已保存模型切換。
- YouTube 觀看頁與公開翻譯入口預熱、擴充功能 reload 後的失效 context 保護。
- Mac 同步 Apple 模型在 Windows loopback 的執行期適配，不覆寫同步設定。
- GGUF 載入 120 秒窗口、推論忙碌時最多 130 秒排隊、上次模型保存。
- Windows C# Native Host、安裝／解除、登入啟動整合、tray 重複實例防護。
- 推送前補正 half-close 誤判，將舊「忙碌回 409」測試改為真 socket 的排隊／串流／模型切換驗證。

## 2026-10-23 的本地驗證結果

| 項目 | 結果 | 限制 |
| --- | --- | --- |
| Node v24.19.0，`node --test tests/*.test.mjs` | 116／116 通過 | Node harness；不是瀏覽器全片播放 |
| Python 3.14.4，unittest discovery | 56 項：55 通過、1 skipped | 跳過會修改使用者剪貼簿的測試；多數後端行為有 mock |
| 僅 Git 追蹤檔案的乾淨快照 | Node 116／116；修正後 portable Python 38／38 通過 | 在 Windows 執行；沒有帶入未追蹤的專案檔，不等於已在雲端 Linux 執行 |
| PowerShell AST parse | 3 檔通過 | `start-watchdog.ps1`、`setup-autostart.ps1`、`install-native-host.ps1`；未操作登錄或登入啟動 |
| C# Native Host | csc 編譯成功 | 輸出在忽略目錄，未替換已安裝 Host，未執行實際 Native Messaging |
| Git 差異與敏感內容 | `git diff --check` 通過；常見憑證格式未發現命中 | 另經完整變更閱讀；不是正式安全稽核 |
| macOS／真實模型／重開機／瀏覽器實播 | 本次未執行 | 必須另外驗證，不能引用舊文件結果當本輪結果 |

第一次 Python suite 失敗是舊 409 預期不符新排隊行為，已修正測試與 half-close 問題後重跑通過。不要恢復舊預期來「修好」測試。

另一次乾淨快照測試發現兩個 Laya lifecycle tests 未替換 Python 路徑，會在未安裝 Laya 的 checkout 提前失敗。`3defabe` 將這兩個已模擬 Popen 的測試指向測試直譯器，再次驗證 38 項 portable suite 全部通過。這不會啟動真實 Laya，也不修改產品行為。

本地驗證使用 `scripts/output/verification-venv/` 的隔離環境，借用既有 Pillow／pystray，不新增全域套件。該環境不受 Git 追蹤，雲端需建立自己的環境。

## 雲端起手式

先讀環境內實際存在的 AGENTS.md／技能，再閱讀本企劃。此儲存庫 `.gitignore` 忽略本機 `AGENTS.md`，不能假設會隨 clone 帶入；以下是必要規則的公開交接摘要，不包含本機私人路徑或技能內容。

- 新設計先自行由原始碼回答問題，只詢問實際缺漏的設計決策。
- Bug fix 執行 correctness review；檢查時同時注意不必要抽象與依賴。技能可用時使用 code-review-skill／ponytail-review；不可用時依同等原則執行，不因缺少個人技能而停工。
- 不自動新增或修改使用者技能、插件或 Dotfiles；本次只是專案重構。
- 權限失敗先使用環境允許的權限工具；仍無法執行時回報確切完整命令，不能報成成功。
- 核心、模型、測試直接使用原始可執行檔；Python 使用專案虛擬環境，不全域 pip install。

可在 repository root 執行的基準命令（Linux 範例；不是所有環境均已驗證）：

```sh
git status --short
git merge-base --is-ancestor 890778680f2e30cfbaef7e6d58367dfaa1b309ba HEAD
git merge-base --is-ancestor 3defabe0c73e3fb2610849b06af9687240d7f188 HEAD
node --version
node --test tests/*.test.mjs
```

未有專案虛擬環境時，先確認可用 Python 核心路徑，再建立 `.venv`。目前 portable Python tests 不需要載入 torch；以下只執行不依賴托盤的 suite：

```sh
python3 -m venv .venv
.venv/bin/python -m unittest discover -s tests -p 'test_model*.py'
.venv/bin/python -m unittest discover -s tests -p 'test_startup_idle.py'
.venv/bin/python -m unittest discover -s tests -p 'test_decision_watchdog.py'
.venv/bin/python -m unittest discover -s tests -p 'test_apple*.py'
```

這些命令中的 Apple 測試使用受控替身，不能證明 Apple Intelligence 可用。`test_windows_watchdog.py` 會匯入 Pillow／pystray，在 headless Linux 可能需要顯示環境；將其分到合適 runner 或明確標記不可執行，不能刪除測試或假裝已通過。互動剪貼簿測試應在專門的測試桌面執行。

建立 Go module 後，在 module 根目錄執行 `go test ./...`、`go test -race ./...`、`go vet ./...`；原生 UI 用平台 tags／獨立 package 分開，讓 headless core 真正可測。race detector 的工具鏈條件需在 runner 上滿足。

建立 TypeScript 工具鏈時，同時提供且實際執行 `npm ci`、`npm run typecheck`、`npm run build`、`npm test`，提交 lockfile。這些 npm scripts 在基準中尚不存在，不要在建立前宣稱已執行。

## 不可漏掉的現有行為與陷阱

1. Swift UI 不只讀 status，也會呼叫 switch／sleep／wake／auto-sleep／decision／stop；回應欄位與型別須相容。
2. `mac/launch_watchdog.py` 的等待就緒與失敗清理必須移植；`.app` 不能繼續引用開發機 Python 或 checkout。
3. Chrome Host manifest 不支援直接附加任意子命令；同一 exe 分模式需要明確 argv 設計，不能把命令列當 path。
4. Windows breakaway 有前提；現有 fallback 不保證脫離 Job。測試不能只檢查 spawn 成功。
5. Laya 推論模組目前從 `watchdog.decision` import `MODEL_ID`／`validate_payload`；移除 Python 管理層前拆開必要依賴。
6. `backends/`、模型、`.venv`、last_model、Host JSON／exe、Instapaper 本機金鑰不在公開基準中；缺少私人元件時 graceful unavailable，不要求秘密或整台機器快照。
7. 不把 8765 舊 bridge 描述當成現有需求；不要與其他本機工具搶埠。
8. 不把所有 JS 一次改副檔名後靠 any／忽略檢查通過；保留各腳本執行世界與注入順序。
9. 不在單次遷移同時更改選軌、提示詞、Laya 預設、模型 ID 或 UI 設計；若發現獨立 bug，單獨記錄與測試。
10. 使用者已選 Go＋Swift；Rust、Tauri、自訂 Windows 浮動面板不在本輪工作範圍。

## 雲端執行紀錄（由接手者更新）

| 階段 | Commit／PR | 實際執行命令與結果 | 未驗證／阻礙 |
| --- | --- | --- | --- |
| Phase 0 | 待執行 | 待執行 | fresh-clone／portable baseline |
| Phase 1 | 待執行 | 待執行 | 真實模型另驗 |
| Phase 2 | 待執行 | 待執行 | Windows／macOS 原生環境 |
| Phase 3 | 待執行 | 待執行 | 瀏覽器載入及實播 |
| Phase 4 | 待執行 | 待執行 | 使用者兩平台實機驗收 |

每次交付應附：已完成與剩餘範圍、精確測試結果、產物路徑、已知限制，以及能直接執行的下一步。不得把待驗收改成通過。
