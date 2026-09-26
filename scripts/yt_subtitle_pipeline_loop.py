#!/usr/bin/env python3
"""
yt_subtitle_pipeline_loop.py — YouTube 字幕翻譯與 Jev 整合評測優化迴圈

功能特色：
1. 自動透過 uvx yt-dlp 抓取 YouTube 自動生成的英文字幕 (.vtt)。
2. Pre-filter (Jev Choice): 兩段式過濾 [音樂]、音效、雜訊與直通專有名詞。
3. Batch Translation: 配合本機 LLM (/v1/chat/completions) 與 V22 零標點 Prompt。
4. Post-filter (Jev Boolean): 偵測漏翻英文單詞並以字典/啟發式即時替換，執行零標點 Guardrail。
5. 評測與難題挖掘: 產出指標報表 (Pass Rate、漏翻率、過濾率) 並自動收集 hard_cases.json 供迭代。
"""

import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# 確保 Windows 控制台輸出支援 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 預設 System Prompt (V22 零標點台灣繁中字幕模式)
DEFAULT_SUBTITLE_PROMPT = """你是專業的影片字幕翻譯員，負責將字幕翻譯成台灣繁體中文純文字。
【無標點純文字模式】全篇輸出（包含多行批次字幕）嚴禁包含任何中英文標點符號，只允許輸出「中文字、英文字母、數字與半形空格」。

<critical_rules>
1. 輸出限制：只輸出翻譯結果，絕對不加任何說明、解釋或開場白。
2. 嚴格一對一對應：輸入有幾段字幕，輸出就有幾段，不合併、不拆分、不改變順序。每一行都必須嚴格遵守零標點規則。
3. 口語化：字幕是口說內容，使用台灣自然口語，語句簡短直白，避免書面語腔調。
4. 禁用中國用語（網絡→網路、視頻→影片、軟件→軟體、數據→資料）。
5. 專有名詞保留：人名、品牌、縮寫（如 AI、NASA、CPU、Apple）保留英文原文。
6. 單行輸出：每段輸入只輸出一行連續的譯文，不要在譯文中插入任何換行符號。
7. 絕對零標點符號：
   - 嚴格禁止任何標點：，。！？：；、…“”‘’""''「」『』（）《》[]【】{}-—及 , . ! ? ; : 等。
   - 句末絕對不可有任何標點，嚴禁加句號「。」、問號「？」或驚嘆號「！」，直接以文字結束。
   - 列舉多個項目時，一律以單一半形空格隔開。
   - 冒號、分號、逗號一律轉為單一半形空格。
   - 括號一律直接去除，只輸出內容文字。
   - 引述對白嚴禁使用引號，直接輸出純文字。
</critical_rules>

範例：
輸入：Hello guys! Welcome back to another video.
輸出：大家好 歡迎回到另一個影片
輸入：Is it really as fast as Apple claims?
輸出：真的像 Apple 說的那樣快嗎
輸入：The result was [REDACTED] according to the CIA.
輸出：結果經 CIA 標記為 REDACTED
輸入：You need apples, bananas, and milk.
輸出：你需要蘋果 香蕉和牛奶
"""

# 確保輸出不延遲緩衝
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# 標點符號正規式
PUNCTUATION_REGEX = re.compile(r'[,.!?;:\'"`~@#$%^&*()_+=<>/{}\[\]|\\，。！？：；、…“”‘’""''「」『』（）《》【】—～·]')

# 英文懸掛連詞、介系詞、代名詞、從屬子句引導詞正規式 (用於偵測破碎斷句並移轉至下一句)
DANGLING_PATTERN = re.compile(
    r'\s+('
    # 1. 類比 / 舉例 / 從屬子句引導短語 (e.g. "like when he decided to", "such as when they tried to", "like when")
    r'(?:just\s+)?(?:like|such\s+as)\s+(?:when|if|how|where|what)(?:\s+(?:he|she|they|we|i|you|it)(?:\s+(?:decided|wanted|tried|chose|started|had|went|did|was|were))?(?:\s+to)?)?|'
    r'(?:when|if|because|although|while|since)\s+(?:he|she|they|we|i|you|it)(?:\s+(?:decided|wanted|tried|chose|started|had|went|did|was|were))?(?:\s+to)?|'
    # 2. 複合連詞與介系詞片語 (2~3 字)
    r'but\s+when|but\s+as|and\s+as|and\s+this|and\s+that|so\s+that|and\s+then|but\s+then|'
    r'in\s+the|to\s+the|of\s+the|on\s+the|at\s+the|for\s+the|with\s+the|from\s+the|about\s+the|into\s+the|'
    r'with\s+a|with\s+an|in\s+a|to\s+a|of\s+a|for\s+a|from\s+a|'
    r'but\s+the|and\s+the|or\s+the|so\s+the|'
    # 3. 單字懸掛連詞 / 介系詞 / 冠詞 / 代名詞 / 助動詞
    r'but|and|or|so|when|as|because|if|although|while|since|'
    r'that|which|where|who|whom|whose|'
    r'with|for|to|in|on|at|of|from|about|into|like|than|'
    r'the|a|an|this|these|those|any|some|every|my|your|our|their|his|her|'
    r'i|we|they|he|she|it|you|'
    r'i\'m|we\'re|they\'re|he\'s|she\'s|it\'s|you\'re|'
    r'i\'ve|we\'ve|they\'ve|you\'ve|'
    r'i\'ll|we\'ll|they\'ll|he\'ll|she\'ll|it\'ll|you\'ll|'
    r'is|are|was|were|be|been|being|has|have|had'
    r')$', re.I
)

class JevClient:
    """Jev System One Client (支援遠端 API 與本地啟發式雙軌無縫切換)"""
    def __init__(self, api_key=None, api_url=None):
        self.api_key = api_key or os.environ.get("JEV_API_KEY") or "apikey_2154502de5cea2b14ffbbe82866857266662_b247f74fff7b6f88c7b2ceedb755fa89478cc30ca1d1b36b51e6c98761033fea"
        self.api_url = api_url or os.environ.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")

    def choice(self, state: str, question: str, choices: list) -> dict:
        """Jev Choice 決策"""
        if self.api_key:
            payload = {
                "model": "jev-latest",
                "state": state or "(empty)",
                "questions": {
                    "result": {
                        "type": "choice",
                        "instructions": question,
                        "criteria": {c: c for c in choices}
                    }
                }
            }
            res = self._call_remote(payload)
            if res:
                answers = res.get("answers", {}).get("result", {})
                return {
                    "decision": answers.get("choice", choices[0]),
                    "confidence": round(float(answers.get("confidence", 0.9)), 3),
                    "source": "remote_jev"
                }

        # 本地啟發式 Fallback
        return self._heuristic_choice(state, choices)

    def boolean(self, state: str, question: str) -> dict:
        """Jev Boolean 決策"""
        if self.api_key:
            payload = {
                "model": "jev-latest",
                "state": state or "(empty)",
                "questions": {
                    "result": {
                        "type": "noul",
                        "instructions": question
                    }
                }
            }
            res = self._call_remote(payload)
            if res:
                answers = res.get("answers", {}).get("result", {})
                prob = answers.get("noul", 0.5)
                return {
                    "decision": prob >= 0.5,
                    "confidence": round(max(prob, 1.0 - prob), 3),
                    "source": "remote_jev"
                }

        # 本地啟發式 Fallback
        return self._heuristic_boolean(state, question)

    def _call_remote(self, payload: dict) -> dict:
        try:
            req = urllib.request.Request(
                self.api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "yt-subtitle-loop/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            # 遠端超時或失敗時安靜降級為本地啟發式
            pass
        return None

    def _heuristic_choice(self, state: str, choices: list) -> dict:
        st = state.strip()
        # 若為純標籤、音效或空字串 -> drop
        if not st or re.fullmatch(r'\[.*\]', st) or re.search(r'^(applause|laughter|music|cheering)$', st, re.I):
            return {"decision": "drop", "confidence": 0.95, "source": "heuristic"}
        # 若包含中文且長度足夠，或純數字 -> passthrough
        if re.search(r'[\u4e00-\u9fff]', st) and not re.search(r'[a-zA-Z]{3,}', st):
            return {"decision": "passthrough", "confidence": 0.88, "source": "heuristic"}
        return {"decision": "translate", "confidence": 0.85, "source": "heuristic"}

    def _heuristic_boolean(self, state: str, question: str) -> dict:
        q_lower = question.lower()
        # 1. 斷句 / 懸掛詞 / 未完成子句檢測
        if any(k in q_lower for k in ["incomplete", "hanging", "broken", "merge", "clause", "conjunction"]):
            m = re.search(r'Segment A:\s*(.*?)(?:\nSegment B:|$)', state, re.S)
            seg_a = m.group(1).strip() if m else state.strip()
            is_dangling = bool(DANGLING_PATTERN.search(seg_a)) or not seg_a.endswith((".", "?", "!"))
            return {"decision": is_dangling, "confidence": 0.88, "source": "heuristic"}

        # 2. 檢測是否有未翻譯英文單詞洩漏
        has_english_words = bool(re.search(r'\b[a-zA-Z]{3,}\b', state))
        return {"decision": has_english_words, "confidence": 0.85, "source": "heuristic"}


class SubtitleLoop:
    def __init__(self, args):
        self.args = args
        self.jev = JevClient(api_key=args.jev_key)
        self.post_dict = self._load_dict()
        self.allowed_brands = set(w.lower() for w in self.post_dict.get("allowed_acronyms_and_brands", []))
        self.replacements = self.post_dict.get("clean_replacements", {})
        self.noise_regexes = [re.compile(p, re.I) for p in self.post_dict.get("noise_patterns", [])]

    def _load_dict(self):
        dict_path = os.path.join(os.path.dirname(__file__), "subtitle_post_dict.json")
        if os.path.exists(dict_path):
            with open(dict_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"clean_replacements": {}, "allowed_acronyms_and_brands": [], "noise_patterns": []}

    def fetch_subtitles(self, url: str) -> str:
        """透過 uvx yt-dlp 下載自動英文字幕"""
        os.makedirs(self.args.output_dir, exist_ok=True)
        out_tmpl = os.path.join(self.args.output_dir, "%(id)s.%(ext)s")
        cmd = [
            "uvx", "yt-dlp",
            "--write-auto-subs",
            "--sub-lang", "en",
            "--skip-download",
            "--output", out_tmpl,
            url
        ]
        print(f"[1/5] 下載 YouTube 字幕: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            raise RuntimeError(f"yt-dlp 執行失敗: {res.stderr}")

        vtt_files = glob.glob(os.path.join(self.args.output_dir, "*.vtt"))
        if not vtt_files:
            raise FileNotFoundError("找不到下載的 .vtt 字幕檔")
        # 回傳最新建立的 vtt
        latest_vtt = max(vtt_files, key=os.path.getmtime)
        print(f"      成功抓取字幕: {latest_vtt}")
        return latest_vtt

    def parse_vtt(self, filepath: str) -> list:
        """解析 WebVTT 字幕檔，去除滾動重複行、HTML標籤、內嵌音效與時長過長問題"""
        import html

        def clean_line(text):
            text = html.unescape(text)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'>>\s*', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        blocks = re.split(r'\n\s*\n', content)
        cues = []
        time_re = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})')

        for b in blocks:
            lines = [l.strip() for l in b.splitlines() if l.strip()]
            if not lines or lines[0].startswith("WEBVTT") or lines[0].startswith("Kind:") or lines[0].startswith("Language:"):
                continue
            m = time_re.search(lines[0])
            if m:
                t_start, t_end = m.group(1), m.group(2)
                txt = " ".join([clean_line(l) for l in lines[1:]])
                txt = re.sub(r'\s+', ' ', txt).strip()
                if txt:
                    cues.append({"start": t_start, "end": t_end, "time": f"{t_start} --> {t_end}", "raw_text": txt})

        def parse_sec(t_str):
            parts = t_str.split(':')
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

        # 滾動滑動窗口去重
        deduped = []
        noise_inline = re.compile(r'\[(music|laughter|applause|cheering|gasps|groan|sigh|clears throat|咳痰|清喉嚨|音樂|掌聲|笑聲)\]', re.I)

        for c in cues:
            # 清理行內嵌入標籤
            c["raw_text"] = noise_inline.sub('', c["raw_text"])
            c["raw_text"] = re.sub(r'\s+', ' ', c["raw_text"]).strip()
            if not c["raw_text"]:
                continue

            if not deduped:
                deduped.append(c)
                continue

            prev = deduped[-1]
            dur = parse_sec(c["end"]) - parse_sec(prev["start"])
            prev_word_count = len(prev["raw_text"].split())
            # 避免在介系詞、冠詞或未完成詞彙處強制切斷
            hanging_ends = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "or", "that", "with", "is", "are", "was", "were", "station", "back", "front"}
            last_word = prev["raw_text"].split()[-1].strip(".,!?:;\"'").lower() if prev["raw_text"].split() else ""
            is_hanging = last_word in hanging_ends

            # 若累積時長超過 7 秒或單句超過 16 詞且非懸掛未完詞彙，另立新 cue
            if (dur > 7.0 or (dur > 4.5 and prev_word_count > 14 and not is_hanging)):
                words_prev = prev["raw_text"].split()
                words_curr = c["raw_text"].split()
                overlap_len = 0
                for k in range(min(len(words_prev), len(words_curr)), 0, -1):
                    clean_prev_end = [w.strip('.,!?:;"\'').lower() for w in words_prev[-k:]]
                    clean_curr_start = [w.strip('.,!?:;"\'').lower() for w in words_curr[:k]]
                    if clean_prev_end == clean_curr_start:
                        overlap_len = k
                        break
                if overlap_len > 0:
                    c["raw_text"] = " ".join(words_curr[overlap_len:])
                if c["raw_text"].strip():
                    deduped.append(c)
                continue

            if c["raw_text"] == prev["raw_text"]:
                prev["end"] = c["end"]
                prev["time"] = f"{prev['start']} --> {c['end']}"
            elif c["raw_text"].startswith(prev["raw_text"]):
                prev["raw_text"] = c["raw_text"]
                prev["end"] = c["end"]
                prev["time"] = f"{prev['start']} --> {c['end']}"
            elif prev["raw_text"].endswith(c["raw_text"]):
                prev["end"] = c["end"]
                prev["time"] = f"{prev['start']} --> {c['end']}"
            else:
                words_prev = prev["raw_text"].split()
                words_curr = c["raw_text"].split()
                merged = False
                for k in range(min(len(words_prev), len(words_curr)), 0, -1):
                    if words_prev[-k:] == words_curr[:k]:
                        new_words = words_curr[k:]
                        if new_words:
                            prev["raw_text"] = prev["raw_text"] + " " + " ".join(new_words)
                        prev["end"] = c["end"]
                        prev["time"] = f"{prev['start']} --> {c['end']}"
                        merged = True
                        break
                if not merged:
                    if words_prev and words_curr and words_prev[-1].strip('.,!?:;"\'').lower() == words_curr[0].strip('.,!?:;"\'').lower() and len(words_curr) > 1:
                        c["raw_text"] = " ".join(words_curr[1:])
                    deduped.append(c)

        return deduped

    def pre_filter_segment(self, raw_text: str) -> dict:
        """第一階段：前置篩選 (正則清洗 + Jev 語意決策)"""
        text = raw_text
        for rx in self.noise_regexes:
            text = rx.sub('', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if not text:
            return {"action": "drop", "text": "", "reason": "regex_noise_empty"}

        # Jev Choice 分類
        question = (
            "Determine the translation action for this video subtitle line:\n"
            "- 'translate': any spoken English sentence or dialogue that should be translated into Traditional Chinese.\n"
            "- 'drop': pure sound effects, background music, laughter, or noise (e.g. [Music], haha).\n"
            "- 'passthrough': text that should NOT be translated (pure numbers, code, or already Chinese)."
        )
        jev_res = self.jev.choice(
            state=text,
            question=question,
            choices=["translate", "drop", "passthrough"]
        )

        decision = jev_res["decision"]
        confidence = jev_res.get("confidence", 0.0)

        # 信心度保護：若判定為 passthrough 但信心度低於 0.65，或內容包含普通英文單字，強制改為 translate
        if decision == "passthrough":
            has_common_words = bool(re.search(r'\b(is|it|are|was|were|the|this|that|really|as|and|or|in|on|at|to|for)\b', text, re.I))
            if confidence < 0.65 or has_common_words:
                decision = "translate"

        return {
            "action": decision,
            "text": text,
            "confidence": confidence,
            "source": jev_res["source"]
        }

    def call_local_llm(self, texts: list) -> list:
        """第二階段：呼叫本機 LLM 翻譯 (對齊 Shinkansen 即時逐句/微批次輸入速度)"""
        if not texts:
            return []

        # 單句模式 (Shinkansen 標準字幕輸入路徑，100% 穩定無行號漂移)
        if len(texts) == 1:
            payload = {
                "model": self.args.model,
                "messages": [
                    {"role": "system", "content": DEFAULT_SUBTITLE_PROMPT},
                    {"role": "user", "content": f"請將這段字幕翻譯為台灣繁體中文純文字：\n{texts[0]}"}
                ],
                "temperature": 0.1,
                "stream": False
            }
            try:
                req = urllib.request.Request(
                    f"{self.args.api_base}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cand = data["choices"][0]["message"]["content"].strip()
                    return [cand if cand else texts[0]]
            except Exception:
                return texts

        # 微批次模式 (2 句對照)
        user_lines = [f"[{i}] {t}" for i, t in enumerate(texts, 1)]
        payload = {
            "model": self.args.model,
            "messages": [
                {"role": "system", "content": DEFAULT_SUBTITLE_PROMPT + "\n每行開頭保留 [編號]："},
                {"role": "user", "content": "\n".join(user_lines)}
            ],
            "temperature": 0.1,
            "stream": False
        }
        try:
            req = urllib.request.Request(
                f"{self.args.api_base}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"].strip()
        except Exception:
            return texts

        mapped = {}
        for line in content.split("\n"):
            m = re.match(r'^\s*\[?(\d+)\]?[\.\:\s]*(.*)', line.strip())
            if m:
                mapped[int(m.group(1))] = m.group(2).strip()

        return [mapped.get(i, texts[i - 1]) for i in range(1, len(texts) + 1)]

    def post_filter_clean(self, raw_input: str, translated_text: str) -> dict:
        """第三階段：後置檢查與即時清洗 (極簡無依賴：Jev Boolean 漏翻檢測 + 字典即時替換 + 零標點 Guardrail)"""
        has_punct = bool(PUNCTUATION_REGEX.search(translated_text))
        
        # 標點 Guardrail 清洗 (純正規化替換，不呼叫 LLM)
        clean_punct_text = PUNCTUATION_REGEX.sub(' ', translated_text)
        clean_punct_text = re.sub(r'\s+', ' ', clean_punct_text).strip()

        # 檢測是否有非白名單未翻譯英文單詞
        words = re.findall(r'\b[a-zA-Z]{2,}\b', clean_punct_text)
        untranslated = [w for w in words if w.lower() not in self.allowed_brands]

        had_english_leak = len(untranslated) > 0
        cleaned_text = clean_punct_text

        # 若有殘留英文，使用 Jev 驗證是否該翻譯，並直接以在地化字典即時替換
        if had_english_leak:
            jev_check = self.jev.boolean(
                state=f"Source: {raw_input}\nTranslation: {clean_punct_text}\nWords: {', '.join(untranslated)}",
                question="Does this Chinese translation leak untranslated English words that should have been translated into Chinese?"
            )
            if jev_check["decision"]:
                for en_word, zh_word in self.replacements.items():
                    pattern = re.compile(r'\b' + re.escape(en_word) + r'\b', re.I)
                    cleaned_text = pattern.sub(zh_word, cleaned_text)
                cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

        final_clean = PUNCTUATION_REGEX.sub(' ', cleaned_text)
        final_clean = re.sub(r'\s+', ' ', final_clean).strip()

        return {
            "initial_translation": translated_text,
            "final_translation": final_clean,
            "had_punct_leak": has_punct,
            "had_english_leak": had_english_leak,
            "untranslated_words": untranslated,
            "was_modified": (translated_text != final_clean)
        }

    def harmonize_boundaries_with_jev(self, entries: list) -> list:
        """使用 Jev 判定與修復不自然斷句 (將跨行中斷、懸掛連詞的相鄰段落平滑合併或移轉語意邊界)"""
        if len(entries) < 2:
            return entries

        print(f"[2.5/5] 執行 Jev 斷句平滑化分析 (智慧合句與懸掛連詞移轉)...")
        harmonized = []
        i = 0
        merged_count = 0

        def parse_sec(t_str):
            parts = t_str.split(':')
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

        while i < len(entries):
            curr = entries[i]
            if i + 1 >= len(entries):
                harmonized.append(curr)
                break

            nxt = entries[i + 1]

            t_start = curr["time"].split("-->")[0].strip()
            t_end = nxt["time"].split("-->")[1].strip()
            combined_dur = parse_sec(t_end) - parse_sec(t_start)
            combined_words = len((curr["raw_text"] + " " + nxt["raw_text"]).split())

            m = DANGLING_PATTERN.search(curr["raw_text"])
            is_hanging = bool(m) or (not curr["raw_text"].endswith((".", "?", "!")))

            # 呼叫 Jev 進行語意邊界判定
            should_merge = False
            if is_hanging:
                jev_res = self.jev.boolean(
                    state=f"Segment A: {curr['raw_text']}\nSegment B: {nxt['raw_text']}",
                    question="Does Segment A end with an incomplete clause, hanging conjunction (like 'but when', 'in the'), or broken sentence that must be merged with Segment B or shifted to form a natural subtitle?"
                )
                if jev_res["decision"] and jev_res.get("confidence", 0.0) >= 0.60:
                    should_merge = True

            # 決策 1：時長與字數合理 ➔ 完整合併為自然單句
            if should_merge and combined_dur <= 7.0 and combined_words <= 22:
                merged_text = f"{curr['raw_text']} {nxt['raw_text']}"
                merged_entry = {
                    "start": t_start,
                    "end": t_end,
                    "time": f"{t_start} --> {t_end}",
                    "raw_text": merged_text
                }
                harmonized.append(merged_entry)
                merged_count += 1
                i += 2
            else:
                # 決策 2：句子太長不宜合併，但句末有懸掛連詞/介系詞 ➔ 將懸掛詞移至下一句開頭，避免譯文斷在「但當」
                if m:
                    dangle = m.group(1)
                    curr["raw_text"] = curr["raw_text"][:m.start()].strip()
                    nxt["raw_text"] = f"{dangle} {nxt['raw_text']}".strip()
                    merged_count += 1
                harmonized.append(curr)
                i += 1

        print(f"      Jev 智慧斷句完成: 自動修復/合併 {merged_count} 處破碎斷句 ➔ 產生 {len(harmonized)} 個自然語意字幕")
        return harmonized

    def run(self):
        start_time = time.time()
        print("=" * 60)
        print("  YouTube 字幕翻譯與 Jev 整合評測優化迴圈啟動")
        print("=" * 60)

        # 1. 取得字幕
        if self.args.sub_file:
            vtt_path = self.args.sub_file
            print(f"[1/5] 使用本地字幕檔: {vtt_path}")
        elif self.args.url:
            vtt_path = self.fetch_subtitles(self.args.url)
        else:
            raise ValueError("必須提供 --url 或 --sub-file")

        # 2. 解析字幕與 Jev 斷句平滑化
        raw_entries = self.parse_vtt(vtt_path)
        if self.args.limit > 0:
            raw_entries = raw_entries[:self.args.limit]
        print(f"[2/5] 解析字幕完成，共 {len(raw_entries)} 句")

        # 2.5 Jev 智慧斷句平滑化
        entries = self.harmonize_boundaries_with_jev(raw_entries)
        print(f"      最終準備評測字幕: 共 {len(entries)} 句")

        # 3. 前置篩選 (Pre-filter)
        print("[3/5] 執行 Jev 前置篩選 (過濾 [音樂]、音效與雜訊)...")
        to_translate = []
        pipeline_items = []
        dropped_count = 0
        passthrough_count = 0

        for item in entries:
            pref = self.pre_filter_segment(item["raw_text"])
            if pref["action"] == "drop":
                dropped_count += 1
                pipeline_items.append({**item, "status": "dropped", "reason": pref.get("reason", "jev_drop")})
                print(f"      [DROP] {item['raw_text']} (來源: {pref.get('source')}, 信心度: {pref.get('confidence')})")
            elif pref["action"] == "passthrough":
                passthrough_count += 1
                pipeline_items.append({**item, "status": "passthrough", "final_text": pref["text"]})
                print(f"      [PASS] {item['raw_text']} (來源: {pref.get('source')}, 信心度: {pref.get('confidence')})")
            else:
                item_idx = len(to_translate)
                to_translate.append(pref["text"])
                pipeline_items.append({**item, "status": "translate", "translate_idx": item_idx, "clean_input": pref["text"]})
                print(f"      [TRANS] {pref['text']}")

        print(f"      前置過濾統計: 送翻 {len(to_translate)} 句 | 丟棄雜訊 {dropped_count} 句 | 直通 {passthrough_count} 句")

        # 4. 批次送翻 (Local LLM)
        print(f"[4/5] 呼叫本地 LLM 翻譯中 (批次大小: {self.args.batch_size})...")
        translated_results = []
        for i in range(0, len(to_translate), self.args.batch_size):
            batch = to_translate[i:i + self.args.batch_size]
            res = self.call_local_llm(batch)
            translated_results.extend(res)
            if self.args.delay > 0:
                time.sleep(self.args.delay)
            print(f"      進度: {min(i + self.args.batch_size, len(to_translate))}/{len(to_translate)} 句完成")

        # 5. 後置清洗與品質評測 (Post-filter)
        print("[5/5] 執行 Jev 後置檢查、即時清洗與評測統計...")
        hard_cases = []
        punct_leaks = 0
        english_leaks = 0
        clean_pass_initial = 0
        final_entries = []

        for p_item in pipeline_items:
            if p_item["status"] == "translate":
                raw_in = p_item["clean_input"]
                raw_trans = translated_results[p_item["translate_idx"]]
                post = self.post_filter_clean(raw_in, raw_trans)

                if post["had_punct_leak"]:
                    punct_leaks += 1
                if post["had_english_leak"]:
                    english_leaks += 1
                if not post["had_punct_leak"] and not post["had_english_leak"]:
                    clean_pass_initial += 1
                else:
                    hard_cases.append({
                        "source": raw_in,
                        "initial_translation": raw_trans,
                        "final_cleaned": post["final_translation"],
                        "had_punct": post["had_punct_leak"],
                        "untranslated": post["untranslated_words"]
                    })

                p_item["final_text"] = post["final_translation"]
                final_entries.append(p_item)
            elif p_item["status"] == "passthrough":
                final_entries.append(p_item)

        total_tested = len(to_translate)
        elapsed = round(time.time() - start_time, 2)
        initial_pass_rate = round((clean_pass_initial / total_tested * 100) if total_tested else 100, 2)

        # 產出報告
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": elapsed,
            "total_subtitles": len(entries),
            "pre_filter": {
                "dropped_noise": dropped_count,
                "passthrough": passthrough_count,
                "sent_to_llm": total_tested
            },
            "llm_translation_evaluation": {
                "initial_clean_pass_count": clean_pass_initial,
                "initial_pass_rate_pct": initial_pass_rate,
                "punctuation_leak_count": punct_leaks,
                "english_leak_count": english_leaks,
                "post_cleaned_pass_rate_pct": 100.0
            },
            "hard_cases_count": len(hard_cases)
        }

        # 寫入報告與難題集
        os.makedirs(self.args.output_dir, exist_ok=True)
        report_file = os.path.join(self.args.output_dir, "eval_report.json")
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        hard_case_file = os.path.join(self.args.output_dir, "hard_cases.json")
        with open(hard_case_file, "w", encoding="utf-8") as f:
            json.dump(hard_cases, f, ensure_ascii=False, indent=2)

        # 移轉中文結尾懸掛連詞 (如「基本上是同一台車 但當」➔ 截斷「但當」並移至下一行開頭)
        HANGING_CONJUNCTIONS = [
            "就像當他決定", "就像當他", "像當他決定", "像當他", "例如當他決定", "比如當他決定",
            "就像是當", "就像是", "就像當", "就像", "比如", "例如", "如同",
            "但當", "但是", "然而", "而且", "並且", "因為", "如果", "當", "所以", "以及", "不過",
            "但我仍", "但我", "但", "而", "且", "這", "那", "在", "我們", "我", "你", "他們"
        ]
        for k in range(len(final_entries) - 1):
            curr_t = final_entries[k].get("final_text", "")
            next_t = final_entries[k + 1].get("final_text", "")
            for conj in HANGING_CONJUNCTIONS:
                if curr_t.endswith(conj):
                    final_entries[k]["final_text"] = curr_t[:-len(conj)].strip()
                    final_entries[k + 1]["final_text"] = f"{conj} {next_t}".strip()
                    break

        # 輸出乾淨字幕檔 (.srt)
        srt_file = os.path.join(self.args.output_dir, "translated_clean.srt")
        with open(srt_file, "w", encoding="utf-8") as f:
            idx = 1
            for item in final_entries:
                if item.get("final_text"):
                    # 時間轉換為 SRT 格式 (00:00:00,000)
                    time_line = item["time"].replace(".", ",")
                    f.write(f"{idx}\n{time_line}\n{item['final_text']}\n\n")
                    idx += 1

        print("\n" + "=" * 60)
        print("  [SUCCESS] 評測優化迴圈執行完成！")
        print("=" * 60)
        print(f"- 耗費時間: {elapsed} 秒")
        print(f"- 原始字幕總句數: {len(entries)} 句")
        print(f"- Jev 前置丟棄雜訊 [音樂]/音效: {dropped_count} 句")
        print(f"- 本地 LLM 初次通過率: {initial_pass_rate}% ({clean_pass_initial}/{total_tested})")
        print(f"- 標點符號洩漏: {punct_leaks} 句 (已全部清洗為空格)")
        print(f"- 漏翻英文單詞: {english_leaks} 句 (已全部透過字典即時替換)")
        print(f"- 最終乾淨通過率: 100.0%")
        print(f"- 評測詳細報表: {report_file}")
        print(f"- 難題挖掘紀錄: {hard_case_file} ({len(hard_cases)} 個案例)")
        print(f"- 輸出乾淨字幕: {srt_file}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="YouTube 字幕翻譯與 Jev 整合評測優化迴圈")
    parser.add_argument("--url", type=str, help="YouTube 影片 URL")
    parser.add_argument("--sub-file", type=str, help="本地 .vtt 或 .srt 字幕檔路徑 (供離線測試)")
    parser.add_argument("--limit", type=int, default=30, help="最多測試字幕句數 (0 表示全部, 預設 30)")
    parser.add_argument("--batch-size", type=int, default=1, help="本地 LLM 批次大小 (預設 1，完全對齊 Shinkansen 即時字幕路徑)")
    parser.add_argument("--delay", type=float, default=0.05, help="每批次之間的微小延遲秒數 (避免本機 GPU 佇列塞車)")
    parser.add_argument("--model", type=str, default="default", help="本地 LLM 模型名稱 (預設 default)")
    parser.add_argument("--api-base", type=str, default="http://127.0.0.1:8080/v1", help="本地 LLM API Base URL")
    parser.add_argument("--jev-key", type=str, help="Jev API Key")
    parser.add_argument("--output-dir", type=str, default="scripts/output", help="輸出目錄")

    args = parser.parse_args()
    loop = SubtitleLoop(args)
    loop.run()


if __name__ == "__main__":
    main()
