# macOS 27 本地 Apple Foundation Models

LLM watchdog偵測到 `/usr/bin/fm` 時會列出「Apple Foundation Models（本機）」。
在選單列或 http://127.0.0.1:8080/status 選取即可，客戶端仍使用
http://127.0.0.1:8080/v1。請求中的模型名稱會轉為 Apple 的 `system`。

首次使用須由使用者在終端機執行 `sudo fm license`，閱讀並接受全機適用的
Apple CLI 條款，並在系統設定中啟用 Apple Intelligence。可用
`fm available --model system` 確認可用性。

後端使用 `fm serve --host 127.0.0.1 --port 8081`，
並在 API 請求中明確指定 `model: system` 選用本地模型。
沿用LLM watchdog的串流轉發、切換及閒置停止流程。
停止的是 fm 服務進程；Apple 管理的系統模型記憶體由 macOS 自行回收，
不保證全部釋放。模型上下文與支援參數受 Apple 的 Chat Completions API 限制。

更新程式後重新啟動 LLM watchdog.app；建置方式見 watchdog/design/WINDOWS.md。

官方介紹：https://developer.apple.com/videos/play/wwdc2026/334/

## OpenCode 實測（2026-10-01）

- 環境：macOS 27.0.1、OpenCode 桌面版 1.18.31。
- 經 8080 代理的簡短 Chat Completions 請求成功，回覆 `APPLE_LOCAL_OK`，
  API 回傳 `model: system`。
- OpenCode 使用既有 local provider 的 `default_model`（8080/v1）與 Build
  代理，請求已送達 Apple 後端，但收到
  `The session's transcript exceeded the model's context size.`，未產生正文回覆。
- LLM watchdog會將既有 local 模型別名改為 `system`；OpenCode 顯示的 Ling 名稱
  是既有設定標籤，實際後端以LLM watchdog狀態與 API 的 `model` 為準。
- 尚未通過 OpenCode Build 代理與工具操作測試；需另配置精簡提示與工具集，
  並依實際模型限制設定上下文，不能將 API 連線成功視為編程代理可用。
