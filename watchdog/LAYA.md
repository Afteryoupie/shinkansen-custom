# Laya multilingual 決策模型

Watchdog 的「決策模型」區塊管理 Laya multilingual，和翻譯／聊天模型分別啟停。
macOS 選單列、Windows 系統匣及網頁控制台均可啟動、休眠和切換自動休眠。
推論請求自動喚醒模型，閒置 180 秒卸載，正在處理的請求不會觸發休眠。

- 公共決策端點：`http://127.0.0.1:8080/v1/systemone`
- 狀態：`GET /api/decision/status`，也包含在 `/api/status` 的 `decision` 欄位。
- 控制：`POST /api/decision/wake`、`/api/decision/sleep`、`/api/decision/toggle_auto_sleep`。
- 內部服務只監聽 `127.0.0.1:8082`。翻譯服務仍使用 8081。
- 模型不會列入 OpenAI 聊天模型清單，不會因決策請求切換翻譯模型。
- 模型記錄：系統暫存目錄中的 `llm-watchdog-laya.log`。

## 安裝

模型來源：[convaiinnovations/laya-multilingual](https://huggingface.co/convaiinnovations/laya-multilingual)。
本次使用版本 `1720e3e3357cfe1e281542e223f8273b0890ca34`，權重及 tokenizer 共約 678 MB。
本機下載目錄為 `~/LLM/Models/Laya-Multilingual`；`download-manifest.json` 記錄版本、檔案大小及 SHA256。
權重、encoder 設定及 tokenizer 已完整下載，載入時使用離線模式。

在儲存庫根目錄建立獨立 Python 環境，不修改既有翻譯引擎的環境：

```sh
python3 -m venv watchdog/.venv
watchdog/.venv/bin/python -m pip install -r watchdog/requirements-laya.txt
hf download convaiinnovations/laya-multilingual \
  --revision 1720e3e3357cfe1e281542e223f8273b0890ca34 \
  --local-dir ~/LLM/Models/Laya-Multilingual
```

Windows 的 Python 路徑為 `watchdog/.venv/Scripts/python.exe`。模型預設位於 Watchdog
模型目錄下的 `Laya-Multilingual`。可用 `LAYA_MODEL_DIR` 和 `LAYA_PYTHON` 覆寫路徑。

本機 Windows RX 9070 GRE 使用 Python 3.12 與 AMD ROCm 7.2.1 的獨立環境。
重建此 GPU 環境時改用 `watchdog/requirements-laya-rocm.txt`，不要再安裝 CPU 版清單：

```powershell
& .\watchdog\.venv\Scripts\python.exe -m pip install -r watchdog/requirements-laya-rocm.txt
& .\watchdog\.venv\Scripts\python.exe -c "import torch; print(torch.version.hip, torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

ROCm 的 AMD GPU 透過 PyTorch `cuda` 介面操作；狀態顯示 `cuda:0` 代表 AMD GPU，
並非 NVIDIA。翻譯模型另走 llama.cpp Vulkan，需安裝 LunarG Vulkan runtime；
`llama-server.exe --list-devices` 必須列出 RX 9070 GRE。

M3 已以 PyTorch MPS（Metal）實測。裝有 ROCm PyTorch 的 AMD 系統會使用
`torch.cuda` 介面；需依作業系統與顯卡安裝相容的 ROCm wheel，不能使用 macOS wheel。
Windows RX 9070 GRE 已使用 ROCm 7.2.1 實測 GPU 張量運算、Laya 載入與字幕決策。
ROCm 7.13／7.14 在本機會回報 `device kernel image is invalid`，因此固定使用已驗證的 7.2.1。
服務自動選擇可用裝置，沒有 GPU 時使用 CPU；`LAYA_DEVICE` 可指定 `mps`、`cuda` 或 `cpu`。

## 新幹線

重新載入擴充功能後，舊 Jev 設定會轉為本機 Laya 並啟用。不需金鑰。
既有 `jevEnabled`、`jevApiUrl` 與字幕邊界欄位保留以兼容已開啟的內容腳本；
設定頁及實際 provider 改為 Laya，新增 `decisionBackend: "laya"` 標記避免反覆遷移。

API 接受 `{model, state, questions}`，回傳 `{model, answers, usage, device, latency_ms}`。
支援 `noul`、`choice`、`score`，每次最多 32 個問題，HTTP body 上限 256 KiB。
`jev-latest` 為相容的模型名稱別名，實際執行的始終是本機 Laya。

字幕斷句將每個 left/right 邊界獨立批次推論，避免長影片上下文超過模型的
1024-token 預設長度。使用中立 A/B choice 後轉回 noul 格式，減少直接 noul 的標籤偏差。
只有機率達 0.8 或低於 0.2 時提供邊界提示，其餘保留本地規則。
模型輸出的機率尚未校準，不能把門檻視為準確率保證。即使決策服務失敗，
字幕仍保留原始片段、時間和本地分句的長度／停頓限制。

翻譯前使用 `task: "subtitle_filter"`，逐項判斷是否為內容、是否需要翻譯。
需 0.95 門檻才採用模型過濾；即使模型把正常文字判成雜訊，也不直接刪除對話，
只允許明確標示的非語言字幕或符號隱藏。可靠來源語言已符合目標時及純型號可保留原文；
只有漢字的日文不因外觀近似中文就跳過翻譯。問候、告別、廣告口播與重複對話保留。

翻譯後使用 `task: "subtitle_format"`。**只檢查輸出格式，不判斷翻譯語意是否正確。**
模型只看到輸出與「一行純字幕」要求，原文不送入格式分類器；機率達 0.9 才採用模型判斷。
空譯文、額外換行、程式碼區塊、JSON 或字幕標記等另有直接格式檢查。
段數不符及 ASR 編號缺漏／重疊由程式檢查，不靠模型猜配對。
格式失敗的部分繞過快取重試一次；修正結果再檢查，有效輸出才寫入快取。
啟用決策時停用人工字幕的提前串流顯示，避免尚未檢查就注入字幕。

ASR 編號批次分開送出需要翻譯的連續區段，結果對回原始編號。
音效空列透過 `asrIntentionalEmpty` 明確標示，仍保留時間邊界，避免前一句延伸到音效期間。
除錯記錄 `Laya subtitle pipeline` 的 `filtered`、`preserved`、`checked`、
`repairAttempted`、`repaired`、`unresolved` 可確認這些階段是否執行。
`checked` 包含本地及模型格式檢查；`modelDecisions` 是達到門檻而採用的模型格式判斷數，
不是 HTTP 請求數。判斷不明確時仍可能已請求模型，但沿用本地結果。

## 驗證

```sh
node --test tests/subtitle-decisions.test.mjs tests/subtitle-jev.test.mjs tests/subtitle-background.test.mjs tests/subtitle-splitting.test.mjs tests/extension-ui.test.mjs
watchdog/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Windows 系統匣測試另需 pystray、Pillow。
Windows Python venv 啟動器會建立不同 PID 的子程序；後端使用每次啟動產生的識別碼
驗證健康檢查，休眠時終止整個程序樹，避免誤報 8082 衝突或留下模型程序。
RX 9070 GRE 主機已實測 CPU 與 ROCm GPU 冷啟動、字幕決策、格式檢查與休眠後再次喚醒；
GPU 驗證包含 Laya 決策 → Riva Vulkan 翻譯 → Laya 格式檢查的實際 HTTP 流程。
此驗證不代表已測試瀏覽器播放中的字幕品質。
單元測試使用模擬決策後端；M3 的實際載入、推論、HTTP 端點與釋放記憶體另以本機服務驗證。
