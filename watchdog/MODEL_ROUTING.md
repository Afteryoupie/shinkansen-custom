# 依請求 model 自動切換

所有程式繼續使用 `http://127.0.0.1:8080/v1`，在推論 JSON 的 `model` 填入 `/v1/models` 列出的模型 ID。也可使用模型名稱或完整路徑。

- 指定模型：空閒時自動切換並載入；同一模型不重複切換。
- `default`、空字串或省略 model：使用當下選定的模型（包含最近一次自動切換）。
- 忙碌：所有其他推論請求立即回覆 HTTP 409，不排隊，即使請求相同模型也一樣。`error.message` 為「模型正被其他請求使用，請稍後重試」。客戶端可自行決定稍後重試。
- 不存在的模型：HTTP 400，不會默默改用其他模型。
- 模型啟動失敗：HTTP 503。
- 手動切換或休眠在推論期間也回覆 409，避免中断正在輸出的內容。
- SSE 串流結束後才解除忙碌狀態；切換與模型載入期間也視為忙碌。

例如：

```json
{"model":"Hy-MT2-1.8B-Abliterated-8bit","messages":[{"role":"user","content":"Translate: Hello"}]}
```

切換時仍需要載入模型，首次請求需保留足夠的客戶端逾時時間。JSON 推論請求請使用 Content-Length；不支援 chunked request body。
