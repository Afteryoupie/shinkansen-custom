"""Local typed-decision HTTP adapter. Run only in watchdog/.venv."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from watchdog.decision import MODEL_ID, validate_payload


def predict(agent, payload):
    questions, context = payload["questions"], payload["state"]
    if isinstance(context, dict) and context.get("task") in ("subtitle_filter", "subtitle_format"):
        return predict_subtitles(agent, context, questions)
    # Each subtitle boundary has its own context: no indexing a long state that
    # would silently truncate at the checkpoint's 1024-token input limit.
    boundaries = context.get("boundaries") if isinstance(context, dict) else None
    keys = [f"boundary_{i}" for i in range(len(boundaries))] if isinstance(boundaries, list) else []
    if keys and set(questions) == set(keys) and all(questions[k]["type"] == "noul" for k in keys):
        if len(boundaries) > 32 or any(not isinstance(b, dict) or
                not all(isinstance(b.get(k), str) and len(b[k]) <= 4000 for k in ("left", "right")) for b in boundaries):
            raise ValueError("Expected at most 32 subtitle boundaries with left/right text")
        question = {"boundary": {"type": "choice", "instructions":
                    "Decide whether right starts a new sentence or continues the sentence in left.",
                    "criteria": {"A": "Right starts a new sentence.", "B": "Right continues the sentence in left."}}}
        results = agent.predict_batch(boundaries, question, batch_size=8)
        answers = {}
        for key, result in zip(keys, results):
            answer = result["answers"]["boundary"]
            answers[key] = {"type": "noul", "noul": answer["probabilities"]["A"],
                            "action": answer.get("action"), "uncalibrated": True}
        return {"answers": answers, "usage": {"input_tokens": sum(r["usage"]["input_tokens"] for r in results), "output_tokens": 0}}
    return agent.system_one(context, questions)


def predict_subtitles(agent, context, questions):
    """One short context per subtitle, shared neutral labels for the checkpoint."""
    target = context.get("targetLanguage", "zh-TW")
    source = context.get("sourceLanguage", "auto")
    if not all(isinstance(value, str) and len(value) <= 64 for value in (target, source)):
        raise ValueError("Invalid subtitle language")
    filtering = context["task"] == "subtitle_filter"
    rows = context.get("texts" if filtering else "pairs")
    if not isinstance(rows, list) or not 1 <= len(rows) <= (16 if filtering else 32):
        raise ValueError("Invalid subtitle batch")
    if filtering:
        if any(not isinstance(text, str) or len(text) > 1000 for text in rows):
            raise ValueError("Invalid subtitle text")
        contexts = [{"text": text, "sourceLanguage": source, "targetLanguage": target} for text in rows]
        common = {
            "valid": {"type": "choice", "instructions":
                      "Distinguish linguistic content from nonverbal noise. Greetings, repeated speech, names, model numbers and unfinished phrases are linguistic content.",
                      "criteria": {"A": "Speech or meaningful words, including names and fragments.",
                                   "B": "Only a nonverbal sound description, transcription garbage or meaningless symbols."}},
            "needs": {"type": "choice", "instructions":
                      f"Decide whether this text requires translation into {target}. Respect sourceLanguage. Japanese kanji is not evidence of Chinese. Do not omit advertisements, greetings or repetitions.",
                      "criteria": {"A": "Words requiring translation into the target language.",
                                   "B": "Already in the requested language and script, or only a name, brand or identifier that should stay unchanged."}}}
        expected = {f"{kind}_{i}" for i in range(len(rows)) for kind in common}
    else:
        if any(not isinstance(pair, dict) or not all(isinstance(pair.get(key), str) and len(pair[key]) <= 1000
               for key in ("source", "translation")) for pair in rows):
            raise ValueError("Invalid subtitle translation pair")
        contexts = [{**pair, "sourceLanguage": source, "targetLanguage": target} for pair in rows]
        # The user requests format checks only. Do not expose source meaning to
        # this classifier or turn it into translation-quality evaluation.
        contexts = [{"output": pair["translation"], "expectedFormat": "one plain subtitle line"} for pair in rows]
        common = {"error": {"type": "choice", "instructions":
                  "Does output follow the expected format? Check only formatting, never translation meaning or quality.",
                  "criteria": {"A": "One plain subtitle line without code fences, JSON, segment markers or explanation wrappers.",
                               "B": "Malformed output, extra lines, code fences, JSON, segment markers or explanation wrappers."}}}
        expected = {f"error_{i}" for i in range(len(rows))}
    if set(questions) != expected or any(q.get("type") != "noul" for q in questions.values()):
        raise ValueError("Invalid subtitle decision questions")
    results = agent.predict_batch(contexts, common, batch_size=8)
    if len(results) != len(rows):
        raise ValueError("Incomplete subtitle decisions")
    answers = {}
    for i, result in enumerate(results):
        if result["usage"].get("truncated"):
            continue  # Missing answers cause the extension to keep local rules.
        for kind in common:
            answer = result["answers"][kind]
            probabilities = answer["probabilities"]
            value = probabilities["A"] if filtering else 1 - probabilities["A"]
            answers[f"{kind}_{i}"] = {"type": "noul", "noul": value,
                                       "action": answer.get("action"), "uncalibrated": True}
            if not filtering:
                answers[f"{kind}_{i}"]["reason"] = "format"
    return {"answers": answers, "usage": {"input_tokens": sum(r["usage"]["input_tokens"] for r in results), "output_tokens": 0}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import laya
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    agent = laya.load(str(args.model), device=os.environ.get("LAYA_DEVICE") or None)
    # Readiness includes a real forward pass, not merely weight loading.
    agent.system_one("Hello", {"speech": {"type": "noul", "instructions": "Is this human speech?"}})
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, data):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/health":
                self.send_json(404, {"error": {"message": "Not found"}})
                return
            self.send_json(200, {"status": "ok", "model": MODEL_ID, "device": str(agent.device), "pid": os.getpid(),
                                 "startup_token": os.environ.get("LAYA_STARTUP_TOKEN", "")})

        def do_POST(self):
            if self.path != "/v1/systemone":
                self.send_json(404, {"error": {"message": "Not found"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 256 * 1024:
                    raise ValueError("Expected request body up to 256 KiB")
                payload = validate_payload(json.loads(self.rfile.read(length)))
                started = time.monotonic()
                with lock:
                    result = predict(agent, payload)
                result.update(model=MODEL_ID, device=str(agent.device), uncalibrated=True,
                              latency_ms=round((time.monotonic() - started) * 1000, 1))
                self.send_json(200, result)
            except (ValueError, TypeError, KeyError) as error:
                self.send_json(400, {"error": {"message": str(error)}})
            except Exception as error:
                self.send_json(500, {"error": {"message": str(error)}})

        def log_message(self, format, *args):
            print(format % args, flush=True)

    print(f"Laya ready: {agent.device} · {args.model}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
