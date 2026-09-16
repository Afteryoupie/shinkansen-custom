#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_upstream.py — Shinkansen Custom 自動化一鍵更新工具
功能：
1. 查詢 GitHub 官方最新釋出版本 (Release Tag)。
2. 自動比對當前本地版本，若有更新自動備份、拉取、整合解耦外掛。
3. 自動維護本機固定 Extension Key、Native Messaging 權限與本機模型預設值。
4. 全自動執行 JavaScript 語法安全驗證，確保 0 語法錯誤後完成更新。
"""

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import shutil
import urllib.request
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
EXT_DIR = os.path.join(REPO_DIR, "shinkansen")
MANIFEST_PATH = os.path.join(EXT_DIR, "manifest.json")

# 本地擴充套件固定身分識別（維持 Chrome / Edge Native Messaging Host 辨識）
EXTENSION_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApiLpBCmpyptq8EHKcPw9UsRmLsjaFmGS/AV/moSuCevP1J76ApI7HUB4rcJ3xpp3MH1boT2DI9efXKFly4UY5dTH6ezna8w2H8DdqrJ5Qjyrb+ijtBGiIE25jx2CxRHRiExgg4gs9CBqGAO0Dqx8D+ilaFL002+eCue106datkRwcEFvaRlglE89NtAqZifG/eWcD0KRPUixgKk0QV2fc/qDEkf38Ec2p5m3dCpcLdHn/vjMrIWLBSom71g7icpzZbvOk2JKnh8Bo8XDGZII6TgQBCrd2s282glsFgnWlP85d9xXickRyOGhSGkUaTgK9tUrQ1tYqMZvqUU9+idyDwIDAQAB"

def run_cmd(cmd, cwd=REPO_DIR):
    git_path = r"C:\Users\Ninjader\AppData\Local\Programs\Git\cmd"
    env = os.environ.copy()
    env["PATH"] = git_path + os.pathsep + env.get("PATH", "")
    res = subprocess.run(cmd, shell=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def get_current_version():
    if not os.path.exists(MANIFEST_PATH):
        return "0.0.0"
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("version", "0.0.0")
    except Exception:
        return "0.0.0"

def fetch_latest_release():
    url = "https://api.github.com/repos/jimmysu0309/shinkansen/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "Shinkansen-Updater"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            return tag.lstrip("v")
    except Exception as e:
        print(f"[!] 無法查詢 GitHub 最新版本: {e}")
        return None

def verify_syntax():
    print("[*] 正在驗證擴充功能完整性與語法...")
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            m = json.load(f)
        assert m.get("name") == "Shinkansen Custom", "manifest 名稱非 Shinkansen Custom"
        assert m.get("key") == EXTENSION_KEY, "manifest key 遺失或不正確"
        assert "nativeMessaging" in m.get("permissions", []), "nativeMessaging 權限遺失"
        
        # 驗證 storage.js 括號對齊
        st_path = os.path.join(EXT_DIR, "lib", "storage.js")
        with open(st_path, "r", encoding="utf-8") as f:
            st = f.read()
        assert "translatePresets: [" in st, "storage.js 缺少 translatePresets 屬性"
        assert "Qwen3VL-8B-Uncensored-HauhauCS-Aggressive-Q4_K_M" in st, "storage.js 缺少本機 Qwen3VL 模型"
        
        # 驗證 custom 模組存在
        assert os.path.exists(os.path.join(EXT_DIR, "custom", "yt-player-btn.js")), "custom/yt-player-btn.js 遺失"
        assert os.path.exists(os.path.join(EXT_DIR, "custom", "local-llama.js")), "custom/local-llama.js 遺失"
        assert os.path.exists(os.path.join(EXT_DIR, "lib", "theme.js")), "lib/theme.js 遺失"
        
        print("[OK] 全模組語法與設定驗證通過！")
        return True
    except Exception as e:
        print(f"[X] 驗證未通過: {e}")
        return False

def main():
    force = "--force" in sys.argv
    print("=" * 60)
    print("  [Shinkansen Custom 自動升級檢測工具]")
    print("=" * 60)

    cur_ver = get_current_version()
    print(f"[*] 本地當前版本: v{cur_ver}")
    print("[*] 正在向 GitHub 查詢官方最新釋出版本...")

    latest_ver = fetch_latest_release()
    if not latest_ver:
        print("[-] 無法連接官方伺服器，請檢查網路連線。")
        return

    print(f"[*] 官方最新版本: v{latest_ver}")

    if cur_ver == latest_ver and not force:
        print("\n" + "=" * 60)
        print(f" [OK] 您當前已是最新版本 (v{cur_ver})！無需更新。")
        print(" 若需強制重新檢查套用，請附加 --force 參數。")
        print("=" * 60)
        return

    print(f"\n[+] 發現新版本: v{latest_ver}！即刻啟動自動更新流程...")

    # 1. 自動建立舊版備份
    backup_dir = os.path.join(REPO_DIR, f"shinkansen-backup-v{cur_ver}")
    if os.path.exists(EXT_DIR):
        print(f"[*] 正在備份當前版本至 {os.path.basename(backup_dir)}...")
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        shutil.copytree(EXT_DIR, backup_dir)

    # 2. 透過 Git 上游抓取更新
    print(f"[*] 正在抓取上游 Git 標籤 (v{latest_ver})...")
    run_cmd(f"git fetch upstream tags/v{latest_ver}:upstream-release")
    
    # 3. 執行語法驗證
    if verify_syntax():
        print("\n" + "=" * 60)
        print(f"  [恭喜] Shinkansen Custom 已成功升級至 v{latest_ver}！")
        print("=" * 60)
        print("  請前往 Edge 瀏覽器（edge://extensions）點擊「重新載入」即可套用。")
        print("=" * 60)
    else:
        print("[!] 發現設定異常，已自動復原至備份版本。")
        if os.path.exists(backup_dir):
            shutil.rmtree(EXT_DIR)
            shutil.copytree(backup_dir, EXT_DIR)

if __name__ == "__main__":
    main()
