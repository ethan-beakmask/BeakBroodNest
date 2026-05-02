#!/usr/bin/env python3
"""名稱可用性檢查工具

讀 CSV，對每個候選詞查詢以下來源並回填撞名數量：

  欄位       語意
  -----      -----
  github     GitHub repo name 等於該詞 (exact match, case-insensitive)
  gh_org     GitHub user/organization login 含該詞字根 (substring)
  gitlab     GitLab project name 等於該詞 (exact match)
  pypi       PyPI 是否已被佔用 (0/1)
  npm        npm 是否已被佔用 (0/1)

全 0 表示軟體圈無撞名與字根撞名，可進入 USPTO 商標查詢階段。
CSV 內任何額外欄位（如 note）會原樣保留。

用法:
  name_check.py <csv_path>           # 只查空白欄位
  name_check.py <csv_path> --force   # 強制重查所有欄位
  name_check.py --init <csv_path>    # 建立空白範本

GitHub Token (選用，避免 rate limit):
  export GITHUB_TOKEN=ghp_xxx
"""
import argparse
import csv
import json
import os
import sys
import time
from urllib import error, parse, request

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
USER_AGENT = "name-check/1.0"
TIMEOUT = 15


def http_get(url, headers=None):
    req = request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except error.HTTPError as e:
        body = e.read() if e.fp else b""
        return e.code, body


def _gh_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def github_exact(name):
    q = parse.quote(f"{name} in:name")
    url = f"https://api.github.com/search/repositories?q={q}&per_page=100"
    code, body = http_get(url, _gh_headers())
    if code == 403:
        raise RuntimeError("GitHub rate limit 觸發 (403)，請設 GITHUB_TOKEN")
    if code != 200:
        raise RuntimeError(f"GitHub HTTP {code}")
    data = json.loads(body)
    target = name.lower()
    return sum(1 for it in data.get("items", []) if it.get("name", "").lower() == target)


def github_org_substr(name):
    """GitHub user/org login 名稱含 NAME 字根的數量 (substring, case-insensitive)。"""
    q = parse.quote(f"{name} in:login")
    url = f"https://api.github.com/search/users?q={q}&per_page=1"
    code, body = http_get(url, _gh_headers())
    if code == 403:
        raise RuntimeError("GitHub rate limit 觸發 (403)，請設 GITHUB_TOKEN")
    if code != 200:
        raise RuntimeError(f"GitHub HTTP {code}")
    data = json.loads(body)
    return data.get("total_count", 0)


def gitlab_exact(name):
    q = parse.quote(name)
    url = f"https://gitlab.com/api/v4/projects?search={q}&per_page=100"
    code, body = http_get(url)
    if code == 429:
        raise RuntimeError("GitLab rate limit 觸發 (429)，稍後重試")
    if code != 200:
        raise RuntimeError(f"GitLab HTTP {code}")
    data = json.loads(body)
    target = name.lower()
    return sum(
        1
        for it in data
        if it.get("path", "").lower() == target or it.get("name", "").lower() == target
    )


def pypi_exact(name):
    code, _ = http_get(f"https://pypi.org/pypi/{parse.quote(name)}/json")
    return 1 if code == 200 else 0


def npm_exact(name):
    code, _ = http_get(f"https://registry.npmjs.org/{parse.quote(name)}")
    return 1 if code == 200 else 0


CHECKERS = {
    "github": github_exact,
    "gh_org": github_org_substr,
    "gitlab": gitlab_exact,
    "pypi": pypi_exact,
    "npm": npm_exact,
}
EXPECTED_ORDER = ["word"] + list(CHECKERS.keys())


def init_template(path):
    if os.path.exists(path):
        print(f"錯誤: {path} 已存在，不覆寫", file=sys.stderr)
        return 1
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(EXPECTED_ORDER)
    print(f"已建立空白範本: {path}", file=sys.stderr)
    print("請手動編輯加入候選詞於 word 欄位，其餘欄位留空後重跑本工具", file=sys.stderr)
    return 0


def run(path, force):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)

    if "word" not in original_fields:
        print("錯誤: CSV 必須包含 word 欄位", file=sys.stderr)
        return 1

    # 補入缺少的 checker 欄位（既有 row 該欄填空字串）
    added_cols = []
    for col in CHECKERS:
        if col not in original_fields:
            added_cols.append(col)
            for row in rows:
                row[col] = ""
    if added_cols:
        print(f"已補入新欄位: {', '.join(added_cols)}（原 row 該欄保留空白待查）", file=sys.stderr)

    # 寫回時的欄位順序：EXPECTED_ORDER 在前，使用者額外欄位（如 note）依原順序追加
    extra_fields = [f for f in original_fields if f not in EXPECTED_ORDER]
    out_fields = EXPECTED_ORDER + extra_fields

    if not GITHUB_TOKEN:
        print("警告: 未設 GITHUB_TOKEN，GitHub 查詢 rate limit 為 60/h", file=sys.stderr)

    total = sum(1 for r in rows if r["word"].strip())
    idx = 0
    for row in rows:
        word = row["word"].strip()
        if not word:
            continue
        idx += 1
        print(f"[{idx}/{total}] {word}", file=sys.stderr)
        for col, fn in CHECKERS.items():
            if not force and row.get(col, "").strip() != "":
                continue
            try:
                row[col] = str(fn(word))
                print(f"  {col}={row[col]}", file=sys.stderr)
            except Exception as e:
                print(f"  {col} 失敗: {e}", file=sys.stderr)
                row[col] = ""
            time.sleep(0.3)

    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
    print(f"已更新: {path}", file=sys.stderr)

    available = [
        r["word"]
        for r in rows
        if r["word"].strip() and all(r.get(c) == "0" for c in CHECKERS)
    ]
    if available:
        print("\n=== 全 0 候選（可進入 USPTO 人工查詢）===", file=sys.stderr)
        for w in available:
            print(f"  - {w}", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="檢查候選名稱在 GitHub/GitLab/PyPI/npm 的撞名數量（含 GitHub org 字根）"
    )
    ap.add_argument("csv_path", help="CSV 檔路徑")
    ap.add_argument("--force", action="store_true", help="強制重查所有欄位")
    ap.add_argument("--init", action="store_true", help="建立空白範本後結束")
    args = ap.parse_args()

    if args.init:
        return init_template(args.csv_path)
    if not os.path.exists(args.csv_path):
        print(f"錯誤: {args.csv_path} 不存在，可用 --init 建立範本", file=sys.stderr)
        return 1
    return run(args.csv_path, args.force)


if __name__ == "__main__":
    sys.exit(main())
