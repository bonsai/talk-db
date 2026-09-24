#!/usr/bin/env python3
"""
discover.py

bonsai/* リポジトリを自動発見し、文章リポジトリをスコアリング。
候補を出力 → ingest に渡すことで横断索引が構築できる。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


# bonsai org の文章系リポジトリ一覧
KNOWN_TEXT_REPOS = {
    "research-rakugo",
    "talkscripts",
    "unipath-skills",
    "writing",
    "win-tips",
    "tips-word",
    "skill-crawler",
    "skill-consolidator",
    "pi-config-memo",
    "mimic-me",
    "hakkutu",
    "char-distribution",
    "yoshimoto-theater",
    "repos-analyze",
    "research-jev",
    "life-design-skill",
    "houki-skill",
}

# 除外すべきコードリポジトリ
SKIP_REPOS = {
    "talk-db",  # skip itself
    "agents",
    "wf-errors",
    "issues",
    "localbqml",
    "bons.ai",
    "emoji-shiritori",
    "gh-chatgpt-ext",
    "idol-playlist",
    "showa-covers",
    "leanvj",
    "terminal-capture",
    "plego",
    "idol-db",
    "kimura",
}

# 文章系ファイル拡張子
ARTICLE_EXTENSIONS = {".md", ".txt", ".mdx", ".markdown"}


def git_log_count(repo_path: Path) -> int:
    """コミット数を取得 (文章のリポジトリほどコミットが多い傾向がある)"""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout.strip())
    except Exception:
        return 0


def count_md_files(repo_path: Path) -> int:
    """.md ファイル数をカウント"""
    return sum(1 for f in repo_path.rglob("*.md") if f.is_file())


def count_lines_md_files(repo_path: Path) -> int:
    """.md ファイルの合計行数"""
    total = 0
    for f in repo_path.rglob("*.md"):
        try:
            total += sum(1 for _ in f.open("r", encoding="utf-8"))
        except Exception:
            pass
    return total


def has_code_heavy(repo_path: Path) -> bool:
    """コード塊が支配的かチェック (除外判定)"""
    md_count = count_md_files(repo_path)
    if md_count == 0:
        return True

    # .py, .js, .go などのファイルが md より多いか
    code_exts = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp"}
    code_count = sum(1 for f in repo_path.rglob("*") if f.suffix in code_exts and f.is_file())
    total_files = sum(1 for f in repo_path.rglob("*") if f.is_file())

    if total_files == 0:
        return True

    code_ratio = code_count / total_files
    return code_ratio > 0.5 and md_count < 5


def classify_candidate(repo_path: Path, md_count: int, line_count: int) -> dict:
    """リポジトリの特性からクラスターを分類"""
    name = repo_path.name.lower()
    commit_count = git_log_count(repo_path)

    # 文章の傾向を分類
    type_score = {}

    if "essay" in name:
        type_score["essay"] = 2.0
    if "sf" in name:
        type_score["sf"] = 2.0
    if "shortstory" in name or "novel" in name or "fiction" in name:
        type_score["fiction"] = 2.0
    if "dialogue" in name or "対話" in name:
        type_score["dialogue"] = 2.0
    if "poem" in name or "詩" in name:
        type_score["poem"] = 2.0
    if "rakugo" in name or "落語" in name:
        type_score["rakugo"] = 2.0
    if "talk" in name:
        type_score["talkscript"] = 2.0

    # 内容ベース (ファイル名の傾向)
    has_essay_files = sum(1 for f in repo_path.rglob("*.md") if "essay" in f.name.lower())
    has_sf_files = sum(1 for f in repo_path.rglob("*.md") if "sf" in f.name.lower() or "科幻" in f.name)
    has_story_files = sum(1 for f in repo_path.rglob("*.md") if "story" in f.name.lower() or "novel" in f.name.lower())
    has_dialogue_files = sum(1 for f in repo_path.rglob("*.md") if "対話" in f.name or "dialogue" in f.name.lower())

    if has_essay_files > 0:
        type_score["essay"] = max(type_score.get("essay", 0), 1.0 + has_essay_files * 0.5)
    if has_sf_files > 0:
        type_score["sf"] = max(type_score.get("sf", 0), 1.0 + has_sf_files * 0.5)
    if has_story_files > 0:
        type_score["fiction"] = max(type_score.get("fiction", 0), 1.0 + has_story_files * 0.5)
    if has_dialogue_files > 0:
        type_score["dialogue"] = max(type_score.get("dialogue", 0), 1.0 + has_dialogue_files * 0.5)

    # スコアリング
    score = 0
    if md_count >= 3:
        score += 2
    if md_count >= 10:
        score += 3
    if line_count > 5000:
        score += 2
    elif line_count > 1000:
        score += 1
    if commit_count > 5:
        score += 1
    if commit_count > 20:
        score += 1

    # 主要な type を決定
    primary_type = "other"
    if type_score:
        primary_type = max(type_score.items(), key=lambda x: x[1])[0]

    return {
        "path": str(repo_path),
        "name": name,
        "md_count": md_count,
        "line_count": line_count,
        "commit_count": commit_count,
        "primary_type": primary_type,
        "type_scores": type_score,
        "score": score,
        "is_code_heavy": has_code_heavy(repo_path),
    }


def discover(repo_root: Path, min_md_count: int = 3, min_score: int = 2) -> List[dict]:
    """
    repo_root 直下の git リポジトリをスキャンし、文章リポジトリをスコアリング。
    """
    candidates = []

    for item in sorted(repo_root.iterdir()):
        if not item.is_dir():
            continue
        if item.name.startswith("."):
            continue
        if item.name in SKIP_REPOS:
            print(f"skip (known code repo): {item.name}", file=sys.stderr)
            continue

        md_count = count_md_files(item)
        if md_count < min_md_count:
            continue

        if has_code_heavy(item):
            print(f"skip (code-heavy): {item.name} (md={md_count})", file=sys.stderr)
            continue

        line_count = count_lines_md_files(item)
        result = classify_candidate(item, md_count, line_count)
        result["score"] += line_count // 1000  # 文章量ボーナス

        # 既知の文章リポジトリはスコアを補正
        if item.name in KNOWN_TEXT_REPOS:
            result["score"] += 3  # Known text repo bonus
            result["known"] = True

        if result["score"] >= min_score and not result["is_code_heavy"]:
            candidates.append(result)
            print(f"found: {item.name} (type={result['primary_type']}, score={result['score']})")

    # スコアで降順ソート
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Discover bonsai text repositories")
    parser.add_argument("--root", default="/home/bons/repos", help="Root directory to scan")
    parser.add_argument("--output", help="Output JSON file (default: stdout)")
    parser.add_argument("--min-md", type=int, default=3, help="Minimum .md files to consider")
    parser.add_argument("--min-score", type=int, default=2, help="Minimum score to include")
    args = parser.parse_args()

    root_path = Path(args.root)
    if not root_path.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        sys.exit(1)

    candidates = discover(root_path, args.min_md, args.min_score)

    output_data = {
        "discovered_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "root": str(root_path),
        "total_repos": len(candidates),
        "candidates": candidates,
    }

    output_str = json.dumps(output_data, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_str, encoding="utf-8")
        print(f"wrote {len(candidates)} candidates to {args.output}")
    else:
        print(output_str)


if __name__ == "__main__":
    main()