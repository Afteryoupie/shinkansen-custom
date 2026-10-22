# Shinkansen Custom 重構企劃

日期：2026-10-23（Asia/Taipei）

決策狀態：使用者已選定 **TypeScript 擴充功能＋Go Watchdog 核心＋保留 macOS Swift UI**。

重構前基準：`890778680f2e30cfbaef7e6d58367dfaa1b309ba`。

雲端測試準備：`3defabe0c73e3fb2610849b06af9687240d7f188`，修正兩個 Laya 測試對本機 Python 路徑的依賴；實作時需包含此後續提交。

本文件是待執行企劃，不代表 Go 或 TypeScript 遷移已完成。雲端執行入口見 [CLOUD-HANDOFF.md](CLOUD-HANDOFF.md)。

## 1. 目標與邊界

將共用的 HTTP 代理、模型生命週期與 Native Host 啟動協調改成 Go；消除控制器對個人 Python 安裝路徑的依賴。擴充功能逐步改用 TypeScript，增加訊息、設定、字幕與 API 的型別約束。維持目前翻譯與原生 UI 行為，讓同一份核心在 macOS、Windows 使用。

本次不以提高模型 tokens/s 為承諾，不重新實作推論引擎，不引入 Tauri、Electron、React 或新的卡片式托盤面板。模型權重、GPU 元件、外部模型服務不會因控制器改寫而消失。Laya 與所選 MLX 後端仍可能需要 Python。

交付的是各平台可安裝、可更新、可回退的應用；不要求整套只有一個檔案、程序或語言。Swift 是有價值的原生介面資產，不為語言統一而重寫。

本輪平台範圍為 Windows 與 macOS 上的 Chrome／Edge；保留已有其他瀏覽器分支與資源，不把 Safari／iOS 的重新打包納入驗收承諾。

## 2. 原始碼現況與需要保留的資產

| 元件 | 現況 | 遷移要求 |
| --- | --- | --- |
| `shinkansen/manifest.json` | Manifest V3；module service worker、多個 MAIN／隔離世界 content scripts | 保留擴充功能 key、ID、權限、注入世界、時機、frame 設定與腳本相依順序 |
| `watchdog/server.py` | 手動 HTTP parsing、REST、SSE、dashboard、推論排隊 | Go 使用標準 HTTP server／proxy，保留公開契約與串流行為 |
| `watchdog/manager.py`、`state.py`、`config.py` | 模型發現、選擇持久化、啟停、健康檢查、閒置休眠 | 遷移到共用 Go 核心，平台程序管理分檔 |
| `watchdog/decision.py` | 獨立 Laya 程序、就緒識別與閒置管理 | 管理部分改 Go；不與翻譯模型共用推論鎖 |
| `watchdog/laya_backend.py` | Python／Laya／torch 推論服務 | 保留；檢查它對 `decision.py` 的常數／驗證函式依賴，移到小型 Python 共用模組後才能移除舊管理層 |
| `watchdog/LLMMenuBar.swift` | AppKit 自訂 NSView、進度條、17pt 倒數、SF Symbols、eventTracking 更新 | 優先原樣保留；API 契約完全相容才可宣告無需修改 |
| `windows/llm_tray.py` | 原生右鍵選單、短模型標籤、狀態圖示、退出處理 | 改 Go，維持操作及可見回饋；不換自訂彈窗 |
| `windows/native_host/LlamaLauncher.cs` | Native Messaging，一次 start 請求、pythonw 搜尋、程序脫離 | 改 Go；維持 Host 名稱與協定，解決執行模式、就緒與程序所有權 |
| `mac/launch_watchdog.py` | 探測服務、啟動、等待、逾時清理、日誌、啟動 Swift UI | 遷移啟動協調，不能只替換編譯器或一行命令 |
| `mac/build_watchdog_app.py` | Swift 編譯、Bundle、寫死建置時 Python／repo 路徑、ad-hoc signing | 改為封裝 Go 與 Swift 產物，執行期使用 Bundle 相對定位；可保留建置期 Python |

注意：舊文件可能提到 8765 bridge，但此基準的 `llm_watchdog.py` 只建立 8080 server。不得從舊說明自行恢復或佔用 8765；先查實際呼叫者。以原始碼與契約測試為準，避免干擾其他本機工具。

## 3. 目標結構

```text
TypeScript extension (build -> dist/shinkansen/)
       │ HTTP / SSE                 │ Native Messaging (when offline)
       ▼                            ▼
Go Watchdog core <--------- small Go native-host entry
       │
       ├─ Windows: native right-click tray
       ├─ macOS: retained Swift menu via compatible HTTP API
       ├─ llama-server / existing Apple / MLX backends
       └─ optional Python Laya service
```

建議新增 `watchdog-go/` 作為獨立 Go module，內含 `cmd/`、少量按職責劃分的 `internal/`、必要的嵌入資源與測試。Windows／macOS 程序行為用平台檔案或 build tags 區分。優先 `net/http`、`httputil.ReverseProxy`、`os/exec`、`context`、`embed`，不要先建立泛用外掛框架、DI 容器或多層 Repository。

原生選單需要的套件由實作時確認 API、授權與建置條件，鎖定版本。不要因托盤套件支援 macOS 就替換 Swift 面板。純 Go 核心可交叉編譯，不等於整個 App、cgo、AppKit 與簽章能在 Linux 完整驗證。

### 3.1 Native Host 與常駐程序

- 同一專案共用邏輯，Native Host 必須與常駐服務有分離的生命週期。
- 優先採小型獨立 Go Host 入口，降低瀏覽器 argv、stdio 與 GUI 啟動混淆；若選同一執行檔，須先證明模式辨識可行並補整合測試。不要為少一個檔案引入不可靠偵測。
- Chrome manifest `path` 是執行檔路徑，沒有任意 `args` 欄位；不能寫成 `path = "...exe native-host"`。來源 origin 與 Windows `--parent-window` 由瀏覽器傳入。
- Host 維持 `com.llm_project.llama_launcher`；依實際擴充功能 ID 建立 `allowed_origins`。使用長度前綴 UTF-8 JSON framing，stdout 專供協定，日誌另寫 stderr／檔案。
- 實作 single-instance／啟動協調：多分頁或多瀏覽器冷啟動不得產生多個核心或托盤；HTTP 200 或 busy port 不足以確認是自己的服務。
- Windows breakaway 取決於父 Job 的政策。失敗時必須呈現真實結果或採有測試支持的替代機制，不能回報已永久脫離。
- `CREATE_NO_WINDOW` 搭配 `DETACHED_PROCESS` 時前者被忽略；逐項確認程序旗標，不直接複製成保證。
- 清楚區分「程序已建立」「控制 API 就緒」「模型已就緒」。Host 的回應與擴充功能等待行為必須對應，不把 spawn 成功當作模型可用。
- 啟動服務脫離瀏覽器，模型子程序則由服務持有與清理；不可留下孤兒程序，也不可按名稱殺死其他工具的模型服務。

### 3.2 macOS 啟動與封裝

- 封裝 Go 核心與 Swift menu executable 為 `LLM watchdog.app`，以原生入口協調啟動，不在執行期依賴 shell／Python 啟動器或來源 checkout。
- 承接舊 launcher 的既有服務探測、等待就緒、日誌與啟動失敗處理。重複開啟 App 不重複建立 UI／後端。
- 維持 Swift `NSMenuItem.view`、倒數、進度條、eventTracking、原生鍵盤選單與狀態圖示。
- bundle 可移動；模型、設定、日誌與上次模型放在明確的外部位置。不可寫入已簽章 App bundle。
- 建置於 macOS，分別列出 arm64／x86_64 的支援與驗證結果；不要把交叉編譯成功當作實機成功。
- 本機 ad-hoc signing 與對外 Developer ID／notarization 分開標示。沒有發布憑證時可產生未公證產物，不能聲稱可無提示散布。

## 4. 相容性契約

Phase 0 應由程式碼補齊精確的 method、query、payload、回應與錯誤 fixture。以下為最低保留集合，並非已完成的規格。

| API／行為 | 要求 |
| --- | --- |
| `GET /api/status` | 保留 `status`（sleeping／starting／running）、模型 ID／名稱、backend_type、is_translation、models、idle_timeout、idle_remaining、auto_sleep_enabled、active_requests、request_count、decision；數字型別相容 Swift |
| `/health`、`/api/health` | 維持現有呼叫者相容；內部判定不能只靠 PID 存活就聲稱模型 ready |
| `/api/wake`、`/api/start` | 等待模型健康檢查；成功包含 `status=ok,state=running`；逾時與失敗明確回傳 |
| `/api/switch` | 模型識別、別名與既有 query／body 語意；成功／忙碌行為需 fixture；不可中途切掉串流使用的模型 |
| `/api/sleep`、`/api/toggle_auto_sleep`、`/api/auto_sleep` | 保留載入中／推論中保護及現有回應 |
| `/api/stop`、`/stop`、`/shutdown` | 回應後完成關閉；允許退出正在忙碌的服務，清理自己擁有的程序 |
| `GET /v1/models`、尾斜線與模型明細 | 保留被動清單與模型 alias；不能當作已喚醒證據 |
| `/v1/chat/completions` 與既有 `/v1/*` 轉發 | 非串流／SSE、狀態與錯誤轉發、模型路由、Riva target-language adaptation、Apple API path adaptation |
| `/v1/systemone`、`/api/decision/*` | 獨立 Laya 生命週期、payload 驗證、啟動 token／健康識別與失敗回退 |
| `/`、`/status`、favicon | 現有控制台及其操作路徑繼續可用 |
| 瀏覽器連線 | loopback 監聽、現有 CORS／OPTIONS 使用方式；不得未經設計改成對外網路服務 |

公開狀態與內部狀態可不同；Go 可增加內部 stopping／failed，但不能直接讓舊 Swift 或擴充功能把未知狀態當成正常睡眠。

### 4.1 排程、取消與持久化

- 基準對推論忙碌採最長 130 秒排隊，不再立即 409；GGUF readiness 最長 120 秒。保留時間語意，測試使用可控時間與可配置短 timeout，不真正等待兩分鐘。
- 推論鎖持有到整段 SSE 結束。客戶端 half-close 不等於放棄讀取，需保留完整回應；真正中斷／取消要釋放資源與鎖。
- 同時喚醒同一模型應共用啟動；不同模型的切換要與在途請求協調。控制 API 不可繞過這個保護。
- 休眠計時以最後完成活動與 monotonic 時間設計，啟動中及 active requests 不可被閒置檢查停止。
- 保存上次有效模型 ID；設定與日誌使用 OS 使用者資料目錄、可明確覆寫。只讀取遷移舊 `watchdog/last_model.json`，避免覆寫舊檔以保留回退。
- 缺少模型或外部執行檔時顯示具體狀態，不能自動下載大型模型或任意啟動其他路徑。

### 4.2 擴充功能與設定

- 保留網頁／YouTube／文件翻譯、雙語顯示、選軌、字幕時間軸、格式重試與快取規則。
- 保留 local／online 獨立設定、各 preset 模型、API Key 僅存本機且不匯出、已有自動保存與清除行為。
- 保留 Windows 對同步 Apple loopback 模型的執行期適配；不可覆寫 Mac 同步值或改寫 LAN／cloud 設定。
- 保留單一頂層翻譯／還原右鍵動作、取消行為、manifest key／ID、Native Host 名稱。
- 保留基準的 YouTube 觀看頁預熱及公開 `translateYouTubeSubtitles()` 入口，使用實際 `SK.safeSendMessage`；不要以不存在的 helper 製作通過的假測試。
- 新 TS 型別檢查不取代執行期 HTTP／storage 資料驗證；避免用大量 `any`、`@ts-nocheck` 假裝完成遷移。
- 不修改第三方 vendor minified code；建立 build 時原樣複製必要 vendor、圖示、字型、HTML、CSS 與 locales。

## 5. 分階段執行與交付門檻

每階段完成可審查的 commit，更新交接進度與實際命令結果。不要為一次性大改刪除舊實作。

### Phase 0：契約與基準

1. 讀取上述核心檔案與公開 `tests/`，列出所有使用中的 API 與啟動入口。
2. 建立脫敏 API／設定 fixture 與相容性清單，註明需保留的行為和已知缺陷；不得把缺陷當契約永久複製。
3. 建立可重現測試入口與依賴鎖檔策略，將 headless core 測試和原生 UI 測試分開。
4. 檢查 fresh clone 的資源完整性。`test/` 私有測試、模型、`backends/`、本機 key template 等不一定受 Git 追蹤；不得依賴開發者機器才能 build，也不得上傳秘密補齊缺檔。

**完成條件：** 新 checkout 可重現適用的基準測試；契約有來源與 fixture；雲端／原生測試邊界明確。

### Phase 1：Go 無介面核心

1. 新增 `watchdog-go/`，實作設定、模型掃描、生命週期、上次模型保存、API 與 dashboard。
2. 使用標準 HTTP 功能代理，驗證 SSE 即時 flush、half-close、取消、錯誤／逾時與模型切換時序。
3. 覆蓋現有 GGUF、K2 fork、MLX、Apple backends 的命令構造及路由；外部後端缺少時標示 unavailable，不能悄悄刪除平台能力。
4. 遷移 Laya 管理部分，保持 Python 推論服務與必要共用驗證模組；不要安裝 torch 來執行單純控制器測試。
5. 測試使用暫存目錄、隨機埠、受控假子程序及本機 HTTP server；不碰正式 8080 或真實模型程序。

**完成條件：** 契約、並行與取消測試通過；`go test -race`、`go vet` 在可用 runner 通過；舊 Python 仍可獨立運行。假模型的通過只代表控制器相容性。

### Phase 2：原生入口與安裝

1. Windows 原生右鍵托盤：圖示狀態、模型短標籤但完整 ID、選單開啟時更新、忙碌／斷線回饋、重複啟動防護、退出清理。
2. Go Native Host、Chrome／Edge 安裝與解除註冊；保留既有 ID。處理 stdio、程序脫離與服務辨識。
3. macOS App 包含 Go 核心與原有 Swift UI，遷移 launcher 職責，移除開發機絕對路徑。
4. 更新登入啟動與解除流程；啟動直接使用核心執行檔，不透過 `.bat`／`.command`。

**完成條件：** 各平台編譯與套件結構檢查；可用原生 runner 的整合測試通過；本機 GUI、重開機與瀏覽器生命週期仍須另外簽收。

### Phase 3：TypeScript 漸進遷移

1. 新增最小 Node build／typecheck 流程與 lockfile，固定支援的 Node 版本；不為 TS 引入 UI 框架。
2. 先遷移共用資料型別、訊息、設定與 provider／Watchdog client，再遷移背景服務、字幕、網頁注入、設定與 popup。
3. 過渡期間允許 JS／TS 共存；遷移的第一方 TS 檔需有實際型別保護。避免同一功能的 JS／TS 雙份手工維護。
4. 產物放 `dist/shinkansen/`，完整包含 manifest 與資源；保留舊 `shinkansen/` 作為過渡基準並說明載入路徑。
5. MAIN-world scripts 與傳統 content scripts 產出其可接受的格式，不把所有入口誤包成 ES module。background service worker 維持 module。
6. 現有測試中有讀 source／抽取 handler 的測試，遷移時調整到真實模組／產物入口，維持行為斷言，不只改搜尋字串讓測試通過。

**完成條件：** build、typecheck、原有回歸與產物資源驗證通過；新擴充功能使用舊 Python／新 Go 都能按相容性契約工作。

### Phase 4：雙平台驗收、切換與整理

依第 6 節實測，修正後才切換預設入口與發布說明。在 Go 尚未完成平台驗收前，保留 Python／C# 舊入口供明確回退；避免讓兩者同時搶 8080。

移除舊檔前再次檢查 Laya imports、建置腳本、登入啟動、Host registration 與文件引用。雲端可完成可審查的實作與 PR，但未取得真實平台證據前，狀態應為「待本機驗收」，不得宣告正式替換完成。

## 6. 驗證矩陣

| 測試層 | 可在一般雲端 Linux 執行 | 仍需原生／使用者環境 |
| --- | --- | --- |
| JS／TS | Node 回歸、typecheck、打包完整性、訊息與設定遷移 | Chrome／Edge 實際載入、儲存設定、網頁與字幕顯示 |
| Go 核心 | HTTP 契約、真 socket 假上游、串流、取消、排隊、子程序失敗與清理 | 真實模型、GPU、冷啟動與環境路徑 |
| Windows | 交叉編譯純核心；Windows CI 可驗證原生編譯與受控程序 | 右鍵選單、黑窗、Native Host、關閉瀏覽器、重開機 |
| macOS | Linux 可檢查打包腳本邏輯；macOS CI 才編譯 Swift／AppKit | Finder 啟動、選單開啟時倒數、明暗模式、休眠恢復、Apple／MLX |
| Laya | payload、管理狀態、失敗與 timeout 的 fixture 測試 | 已配置 Python／torch／模型的實際推論 |

本機最少驗收：

1. 全部關閉／重開機後，透過擴充功能公開入口啟動正確的已選模型；`/v1/models` 成功不算通過。
2. Chrome／Edge 同時觸發，只有一個核心與一個相應 UI；關閉瀏覽器後核心按設計存活。
3. 真實 YouTube 首次啟動、SPA 換片、取消、模型切換與連續字幕播放；記錄實際設定與模型。
4. 翻譯中不休眠，閒置能休眠，下一次翻譯能喚醒；串流中斷後不永久卡住佇列。
5. macOS 選單保持開啟時倒數與進度條仍更新，既有原生操作與圖示保留。
6. Windows 無不必要黑窗，右鍵行為、短模型標籤、狀態圖示與忙碌退出正常。
7. App／安裝目錄移動、含空白與非 ASCII 路徑、無模型／缺後端、埠被其他應用佔用時有明確結果。
8. 退出／解除登入啟動／回退後沒有自己啟動的殘留程序，也沒有停止其他應用的服務。

記錄延遲時分開報告控制器 API ready、模型 ready、第一個翻譯 token／字幕與整批完成；分開 cold／warm，不用假模型數字宣稱真實翻譯加速。

## 7. 回退與發布規則

- 在雲端分支工作，建議 `refactor/typescript-go`；若環境已分配任務分支，沿用它，不重設分支或強制推送。
- 以基準 commit 作為可恢復來源。回退是停止新核心、恢復舊啟動／Host 註冊並載入舊擴充功能；不清除使用者設定或模型。
- 安裝與解除只操作自己的檔案、程序與登錄項，變更前保存可還原資料；拒絕覆寫未知安裝。
- 模型、私密設定、API keys、臨時日誌、`.venv`、本機 Host manifest 與編譯產物不加入 Git。
- 新增相依項需有理由與 lockfile；不要求雲端安裝數十 GB 模型或取得使用者 API keys 才能完成程式測試。
- 只有取得平台實測證據後才移除舊執行路徑；沒有原生環境時交付清楚的待驗證清單。

## 8. 參考規格

- [Chrome Native Messaging：manifest、argv、stdio 與連線生命週期](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [Windows 程序建立旗標](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
- [Go HTTP ReverseProxy](https://pkg.go.dev/net/http/httputil#ReverseProxy)
- [Go os/exec](https://pkg.go.dev/os/exec)
- [TypeScript JavaScript 遷移指南](https://www.typescriptlang.org/docs/handbook/migrating-from-javascript.html)

套件版本與平台建置需求應在實作時再查官方文件；此企劃沒有固定未驗證的新框架版本。
