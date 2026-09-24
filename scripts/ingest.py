#!/usr/bin/env python3
"""
ingest.py

Scan bonsai repos and produce JSONL canon files for talk-db.
MVP: works, passages, concepts, passage_concepts
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


DEFAULT_CONCEPTS = [
    ("AI", "theme"),
    ("孤独", "theme"),
    ("記憶", "theme"),
    ("死", "theme"),
    ("家族", "theme"),
    ("仕事", "theme"),
    ("未来", "theme"),
    ("東京", "entity"),
    ("身体", "theme"),
    ("自由", "theme"),
    ("エントロピー", "theme"),
    ("情報", "theme"),
    ("仏教", "topic"),
    ("量子", "topic"),
    ("LLM", "topic"),
    ("ボルヘス", "entity"),
    ("シャノン", "entity"),
    ("落合陽一", "entity"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "untitled"


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def git_commit_sha(repo_path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def detect_title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:20]:
        m = re.match(r"^#+\s*(.+)", line)
        if m:
            return m.group(1).strip()
    return fallback


# works.type の存在論enum
# essay / fiction / dialogue / poem / note / research / script / other
TYPE_RULES = [
    # (優先度, 条件callable, type値)
    ("dialogue", lambda p, n, c: "対話" in str(p) or "dialogue" in n or "親子対話" in str(p)),
    ("poem", lambda p, n, c: "poem" in n or "詩" in str(p)),
    ("research", lambda p, n, c: "research" in n or "論文" in n or "paper" in n),
    ("script", lambda p, n, c: "台本" in str(p) or "script" in n or "知恵の館" in str(p) or "talk" in n),
    ("essay", lambda p, n, c: "essay" in n or "随筆" in str(p) or "評論" in str(p) or "考察" in str(p)),
    ("fiction", lambda p, n, c: "shortstory" in n or "novel" in n or "sf" in n or "物語" in str(p)),
    ("note", lambda p, n, c: "note" in n or "memo" in n or "断片" in str(p) or "seed" in str(p)),
]


def detect_type(path: Path, content: str = "") -> str:
    name = path.name.lower()
    path_str = str(path).lower()
    for t, fn in TYPE_RULES:
        if fn(path_str, name, content.lower()):
            return t
    return "other"


def detect_genre(text: str, path: Path) -> List[str]:
    genres = []
    lower = text.lower()
    name = path.name.lower()
    if "sf" in name or "科幻" in text or "未来" in text or "ai" in lower:
        genres.append("SF")
    if "哲学" in text or "思想" in text or "仏教" in text or "ヌル" in text:
        genres.append("哲学")
    if "技術" in text or "llm" in lower or "エントロピー" in text or "シャノン" in text:
        genres.append("技術")
    if " essay" in name or "エッセイ" in text:
        genres.append("エッセイ")
    return genres


def make_work_id(repo: str, path: Path, commit_sha: Optional[str]) -> str:
    repo_name = Path(repo).name
    rel = str(path).replace(os.sep, "-")
    base = f"{repo_name}--{rel}"
    if commit_sha:
        base += f"--{commit_sha[:7]}"
    h = hashlib.sha256(base.encode()).hexdigest()[:12]
    return f"{repo_name}-{h}"


def split_passages(text: str) -> List[tuple]:
    """Split text into paragraph-level passages with line numbers."""
    lines = text.splitlines()
    passages = []
    buf = []
    start_line = 1
    current_line = 0

    for idx, line in enumerate(lines, start=1):
        current_line = idx
        stripped = line.strip()
        if stripped == "":
            if buf:
                passages.append(("\n".join(buf), start_line, current_line - 1))
                buf = []
            start_line = current_line + 1
        else:
            buf.append(line)

    if buf:
        passages.append(("\n".join(buf), start_line, current_line))

    # Filter out headings-only blocks and very short noise
    result = []
    for text, s, e in passages:
        cleaned = text.strip()
        if len(cleaned) >= 20:
            result.append((cleaned, s, e))
    return result


def ingest_repo(repo_path: Path, concept_map: dict, existing_work_ids: set):
    works = []
    passages = []
    passage_concepts = []

    repo_abs = repo_path.resolve()
    repo_name = repo_abs.name
    repo_full = f"bonsai/{repo_name}"

    md_files = sorted(repo_abs.rglob("*.md"))

    for md in md_files:
        rel_path = md.relative_to(repo_abs)
        # skip hidden dirs and common non-content paths
        if any(part.startswith(".") for part in rel_path.parts):
            continue

        content = md.read_text(encoding="utf-8")
        chash = file_hash(md)
        commit_sha = git_commit_sha(repo_abs)
        title = detect_title(content, rel_path.stem)
        work_id = make_work_id(str(repo_abs), rel_path, commit_sha)

        if work_id in existing_work_ids:
            continue
        existing_work_ids.add(work_id)

        wtype = detect_type(md, content)
        genre = detect_genre(content, md)
        source_url = f"https://github.com/{repo_full}/blob/{commit_sha or 'main'}/{rel_path}"

        work = {
            "id": work_id,
            "repo": repo_full,
            "path": str(rel_path),
            "title": title,
            "author": "bonsai",
            "type": wtype,
            "genre": genre,
            "language": "ja",
            "summary": "",
            "source_url": source_url,
            "commit_sha": commit_sha,
            "content_hash": chash,
            "status": "indexed",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        works.append(work)

        for ordinal, (ptext, sline, eline) in enumerate(split_passages(content), start=1):
            passage_id = f"{work_id}-p{ordinal:04d}"
            passages.append(
                {
                    "id": passage_id,
                    "work_id": work_id,
                    "parent_id": None,
                    "type": "paragraph",
                    "ordinal": ordinal,
                    "text": ptext,
                    "start_line": sline,
                    "end_line": eline,
                    "created_at": now_iso(),
                }
            )

            for concept_id, name in concept_map.items():
                if name in ptext:
                    passage_concepts.append(
                        {
                            "passage_id": passage_id,
                            "concept_id": concept_id,
                            "confidence": 0.5,
                            "extractor": "keyword",
                        }
                    )

    return works, passages, passage_concepts


def write_jsonl(path: Path, records: List[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_existing_records(path: Path, key_fields=None) -> dict:
    records = {}
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if key_fields:
                key = tuple(rec[k] for k in key_fields)
            else:
                key = rec["id"]
            records[key] = rec
    return records


def main():
    parser = argparse.ArgumentParser(description="Ingest bonsai repos into talk-db JSONL")
    parser.add_argument("--repos", nargs="+", required=True, help="Paths to repos to scan")
    parser.add_argument("--output", default="data", help="Output directory for JSONL")
    parser.add_argument("--concepts", help="Path to concepts JSONL (seed)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    concepts = []
    concept_map = {}
    for name, ctype in DEFAULT_CONCEPTS:
        cid = slugify(name)
        concepts.append({"id": cid, "name": name, "type": ctype, "description": ""})
        concept_map[cid] = name

    if args.concepts and Path(args.concepts).exists():
        for rec in json.loads(Path(args.concepts).read_text(encoding="utf-8")):
            concepts.append(rec)
            concept_map[rec["id"]] = rec["name"]

    works_path = output_dir / "works.jsonl"
    passages_path = output_dir / "passages.jsonl"
    concepts_path = output_dir / "concepts.jsonl"
    passage_concepts_path = output_dir / "passage_concepts.jsonl"

    existing_works = load_existing_records(works_path)
    existing_passages = load_existing_records(passages_path)
    existing_passage_concepts = load_existing_records(passage_concepts_path, key_fields=["passage_id", "concept_id"])

    for repo in args.repos:
        repo_path = Path(repo)
        if not repo_path.is_dir():
            print(f"skip: {repo} is not a directory", file=sys.stderr)
            continue
        print(f"ingesting {repo_path} ...")
        ws, ps, pcs = ingest_repo(repo_path, concept_map, set(existing_works.keys()))
        for w in ws:
            existing_works[w["id"]] = w
        for p in ps:
            existing_passages[p["id"]] = p
        for pc in pcs:
            existing_passage_concepts[(pc["passage_id"], pc["concept_id"])] = pc

    write_jsonl(works_path, list(existing_works.values()))
    write_jsonl(passages_path, list(existing_passages.values()))
    write_jsonl(concepts_path, concepts)
    write_jsonl(passage_concepts_path, list(existing_passage_concepts.values()))

    print(
        f"wrote {len(existing_works)} works, {len(existing_passages)} passages, "
        f"{len(concepts)} concepts, {len(existing_passage_concepts)} passage_concepts"
    )


if __name__ == "__main__":
    main()
