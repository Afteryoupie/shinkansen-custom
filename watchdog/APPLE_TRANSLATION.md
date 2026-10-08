# Apple Foundation Models 翻譯

來源：https://github.com/gouwsxander/Apple-Intelligence-API
版本：40083e051488dca6eddbb8507052dd22d079c610

執行 `mac/build-apple-translation.command` 建置；腳本套用 1MB HTTP body 限制修正。
LLM watchdog只顯示一個「Apple Foundation Models」，優先使用此 Swift API；
未建置時才使用原生 fm 作為備援。

路徑：新幹線 → 127.0.0.1:8080/v1 → LLM watchdog →
127.0.0.1:8081/api/v1 → FoundationModels。
API 後端使用 Apple 的 permissiveContentTransformations 文字轉換模式。
保持三分鐘閒置停止及模型切換。

新幹線 Base URL：`http://127.0.0.1:8080/v1`，API Key 留空。
請求中的模型名稱不決定實際模型；在LLM watchdog中選取模型。
插件以 `/api/status` 的 backend_type 辨識 Apple，並將實際後端加入快取識別，
避免切换本機模型時重用其他模型的譯文。

網頁翻譯：每批一段、1200 字元，使用經使用者授權的專用忠實翻譯短提示詞，
保留數字、技術名稱、網頁佔位符及相關固定術語。
影片字幕：沿用獨立的 YouTube / ASR 字幕 Prompt，每批上限兩段。
原有設定頁中的自訂 Prompt 保留；Apple 網頁測試覆寫送出的 Prompt。
修改插件原始碼後須重新載入開發版插件及刷新網頁。

超長單段不會自動拆分；字元上限並非 token 保證。
Apple 模型仍可能拒絕或誤譯，HTTP 200 不代表翻譯品質合格。

## 2026-10-01 整頁測試結論

Hugging Face K2-Horizon 頁面 123 段完成，約 82 秒。短提示詞消除了範例洩漏與段落錯位，
但 token、weight 等技術詞誤譯，模型名稱仍被改寫。依使用者指示停止進一步優化
Apple 網頁翻譯；網頁使用既有 Gemini / Google 預設，Apple 保留用於影片字幕。
網頁專用分支保留作為本次實驗紀錄，並非品質保證。

## 後續網頁 Prompt 改良

使用者決定繼續改良。新版明確限制忠實翻譯，按來源加入 token、weight、memory、dense 的
技術詞規則。純數字、容量、無空白的模型識別碼直接保留而不呼叫模型。
每批兩段實測發生序號標記外洩，維持每批一段。新版快取版本 v4。
八段樣本只需六次請求；影片字幕 Prompt 與兩段批次保持不變。

實測：新版八段樣本（含兩段純數字/模型 ID）約 4.3 秒、六次模型請求，
技術词與佔位符檢查通過。同一 Hugging Face 頁面的新版譯文已確認用詞改善；
因頁面在測試期間切到背景，未取得可靠的整頁完成秒數，不能當作整頁加速百分比。
