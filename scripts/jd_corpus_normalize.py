"""JD 语料归一化脚本（纯规则，无 LLM）。

将 data/jd_corpus/raw/<source>/ 下的原始数据集，去重、统一字段后写入
data/jd_corpus/normalized/<source>.jsonl，并维护 manifest。

用法：
    python -m scripts.jd_corpus_normalize rocxu-ai
    python -m scripts.jd_corpus_normalize --all

字段口径见 research/jd-corpus-acquisition.md §4.1（本阶段不解析能力，只保留来源已有结构）：
    job_title | company? | city? | text_raw | duty? | require? | source | license | collected_at | dedup_key

新增来源需实现一个 reader 函数返回 record dict 列表，再在 SOURCES 注册。
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "data" / "jd_corpus"

# 空壳/垃圾过滤阈值（与模块一 CLEAN_MIN_REQ_LEN 语义一致）
MIN_TEXT_LEN = 30


def _now() -> str:
    return date.today().isoformat()


def _norm(s: str) -> str:
    """标题规范化（去空白/全半角统一/小写），用于去重键。"""
    return re.sub(r"\s+", "", s).replace("（", "(").replace("）", ")").lower()


def _text_key(s: str) -> str:
    """正文去重键：去空白与常见噪声后取 hash，避免大文本存键。"""
    t = re.sub(r"\s+", "", s)
    return hashlib.md5(t.encode("utf-8")).hexdigest()


def read_rocxu_ai(path: Path) -> list[dict]:
    """RocXuLi res.csv：两列 _c0(岗位名) / text(整段原文，非分列)。"""
    records = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return records
        for row in reader:
            if len(row) < 2:
                continue
            title, text = row[0], row[1]
            records.append(
                {
                    "job_title": (title or "").strip(),
                    "text_raw": (text or "").strip(),
                    "duty": "",
                    "require": "",
                }
            )
    return records


# source 标识 → (原始子目录名, reader 函数, license 结论)
SOURCES = {
    "rocxu-ai": ("rocxu-ai", read_rocxu_ai, "hf: RocXuLi/AI_Job_DataSet_1000_list（本机确认可下载）"),
}


def normalize(source: str) -> int:
    if source not in SOURCES:
        print(f"未知来源: {source}，可用: {sorted(SOURCES)}")
        return 0
    subdir, reader_fn, license_note = SOURCES[source]

    raw_dir = CORPUS_DIR / "raw" / subdir
    if not raw_dir.exists():
        print(f"raw 目录不存在: {raw_dir}")
        return 0

    records: list[dict] = []
    for f in sorted(raw_dir.iterdir()):
        if f.is_file() and f.suffix.lower() == ".csv":
            records.extend(reader_fn(f))
    if not records:
        print(f"{source}: 未读取到记录")
        return 0

    # 去重 + 过滤空壳
    seen: set[str] = set()
    kept: list[dict] = []
    dropped_empty = 0
    dropped_dup = 0
    for rec in records:
        title = rec["job_title"]
        text = rec["text_raw"]
        if len(text) < MIN_TEXT_LEN:
            dropped_empty += 1
            continue
        key = (_norm(title), _text_key(text))
        if key in seen:
            dropped_dup += 1
            continue
        seen.add(key)
        rec["company"] = ""
        rec["source"] = source
        rec["license"] = license_note
        rec["collected_at"] = _now()
        rec["dedup_key"] = key[1]
        kept.append(rec)

    # 写 normalized
    norm_dir = CORPUS_DIR / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    out = norm_dir / f"{source}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 维护 manifest
    manifest = CORPUS_DIR / "manifest.csv"
    header = ["source", "license", "collected_at", "rows", "note"]
    new_manifest = manifest.exists() is False
    with open(manifest, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new_manifest:
            w.writerow(header)
        w.writerow(
            [
                source,
                license_note,
                _now(),
                len(kept),
                f"read {len(records)}; drop <{MIN_TEXT_LEN}: {dropped_empty}; dup: {dropped_dup}",
            ]
        )

    print(f"{source}: read {len(records)} -> kept {len(kept)} -> {out}")
    print(f"  (dropped short {dropped_empty}, dup {dropped_dup})")
    return len(kept)


def main() -> None:
    parser = argparse.ArgumentParser(description="JD 语料归一化（纯规则）")
    parser.add_argument("source", nargs="?", help="来源标识，或 --all")
    parser.add_argument("--all", action="store_true", help="归一化全部已注册来源")
    args = parser.parse_args()

    if args.all:
        total = 0
        for s in SOURCES:
            total += normalize(s)
        print(f"total kept: {total}")
    elif args.source:
        normalize(args.source)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
