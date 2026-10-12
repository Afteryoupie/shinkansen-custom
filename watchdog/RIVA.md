# Riva 翻譯適配

Riva 的 GGUF chat template 不會保留一般自然語言 system 指示。新幹線在送往本機 Watchdog（localhost／127.0.0.1:8080）的翻譯請求附加 `shinkansen_target_language`；Watchdog 根據實際選中的模型處理，不要求前端模型欄位填寫名稱。

選中 Riva 時，Watchdog 將目標語言轉為 Riva 的原生 user 翻譯指示。這個欄位會在代理轉送前移除，其他模型的 messages 維持原樣。一般直接 API 呼叫仍可使用 NVIDIA 官方格式，例如 system=`en-zh-tw`。

Riva 本機批次翻譯逐段執行。ASR 提示中的連續 `編號|片段` 會依句尾標點合併，最多八個片段一組，再逐組翻譯；編號與範圍由程式生成。只處理帶 ASR 提示、從 1 連續編號的輸入，其他格式沿用原有流程。這能避免 Riva 回傳英文原文或缺少 ASR 範圍，並保留 Laya 的覆蓋與格式檢查。

修改後重啟 Watchdog，並重新載入瀏覽器中的新幹線插件及影片頁面。保留模型名稱空白時仍可由 Watchdog 工具列切換模型。

2026-10-12：真實 GPU 實測 12 組英譯繁中字幕、三段對齊及四片段 ASR。Riva 與 HY 均通過 Laya 格式檢查，沒有缺段、範圍缺漏或修復重試。這不是翻譯品質保證；Riva 仍有「platform clear」的語意誤譯。單句速度是在模型已載入時測量，包含翻譯函式呼叫，不包含影片取字幕及瀏覽器顯示延遲。

官方模板：https://huggingface.co/nvidia/Riva-Translate-4B-Instruct-v2/blob/main/chat_template.jinja
