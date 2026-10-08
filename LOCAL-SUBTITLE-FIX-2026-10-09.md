# 本地字幕缺漏修復與實測

影片：hcZLknUGT24，Can a KEI CAR Beat CHEAPEST Chinese EV?，23:43。
實際使用中的 Edge 擴充功能：Shinkansen Custom，mbhjmenbcbbdhknajlellaokildpknam。
來源路徑：C:/LLM_Project/translation_tools/shinkansen-custom/shinkansen。

## 實際設定與執行環境

從 Edge 的 sync/local extension storage 與瀏覽器語言讀取設定，未改寫瀏覽器資料庫。端點 http://127.0.0.1:8080/v1，經本機守護程式轉送至 8081。模型 Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M；heuristic ASR；Jev enabled；30 秒視窗、10 秒設定預翻量；thinking off。實際 API request temperature 為 customProvider 設定的 0；保存的字幕 temperature 為 1，現有一般字幕 handler 未將其覆寫進模型請求。

測試使用原始 background message handler、storage 合併、OpenAI adapter、Jev 邊界判斷、content-youtube 前景視窗與真實 LLM 回應。Chrome API 以 storage 快照與測試替身提供；翻譯快取與紀錄只存在測試記憶體。測試不是瀏覽器實際播放。

## 查明與修正

- 使用者播放紀錄顯示 30 秒視窗字幕批次等待 56～65 秒。停用本地全軌背景 worker，保留前景視窗預翻，避免同端點佇列互相競爭。
- 開始時間差包含說話時長。JSON3 保存 endMs，分句以真正停頓判定，保留原始來源片段；不搬動句尾文字。
- 本地字幕採精簡提示詞，完整保留對話與姓名、品牌、數字；既有儲存的長 prompt 保留，雲端路徑仍讀取自訂 prompt。
- 來源字幕的過濾只丟棄明確音效標記；Jev 語意分句保留。防止車型等真實文字被遠端 noise 判斷清空。
- Jev 分句片段是副本，完成集合現以 startMs 對回原始來源物件，防止成功視窗被誤判未完成。
- 型號名稱可保留原文字；含代名詞／助動詞的英文句子仍不得冒充完成譯文。
- 本地預翻提前量改依整個視窗耗時。譯文尚未到時維持原生 CC，影片保持連續播放。

## 真實模型驗證

| 時段 | 耗時 | 完成 |
| --- | ---: | --- |
| 0:00–0:30 | 17.623 s | 是 |
| 0:30–1:00 | 17.716 s | 是 |
| 1:00–1:30 | 11.109 s | 是 |
| 10:30–11:00 | 18.163 s | 是 |
| 17:30–18:00 | 26.526 s | 是 |
| 18:30–19:00 | 15.023 s | 是 |

44 次真實 LLM 請求，6 個視窗皆完成。唯一空白 cue 是 18:49.888 的 [music]；沒有對話被空白過濾。29.92 秒附近的車型名稱已有可顯示譯文。舊長提示詞樣本 input tokens 790/779/788；新提示詞樣本 83/89/87（來源分句不同，不把此數字當同句品質比較）。

37 個回歸測試通過，涵蓋重複字幕、補譯、短句、Jev 副本、車型標籤、真實句子漏翻防護、原生 CC 可見性及本地背景 worker 停用。全片原始字幕另做來源保留與每片段排程一次的檢查。JavaScript 語法與 git diff --check 通過。

原始實測回應：C:/LLM_Project/translation_tools/subtitle-diagnostics/local-llm-verification.json。
可重跑診斷：C:/LLM_Project/translation_tools/subtitle-diagnostics/real-llm-harness.mjs（需 --experimental-vm-modules，參數 10 0 windows）。

## 套用

在 Edge 擴充功能管理頁重新載入 Shinkansen Custom，再重新整理影片。瀏覽器控制工具本次無法啟動，未自動重新載入或聲稱實播驗證。
