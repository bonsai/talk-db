#!/usr/bin/env python3
"""
extract_relations.py

Passages から SVO (Subject-Verb-Object) 関係を抽出。
MVP: パターンベース抽出
- "X は Y を..."
- "X が Y を..."
- "X は Y だ"
- "X は Y を...と..."
などから関係パターンを検出。

将来的に LLM による意味解析にアップグレード可能。
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# 関係抽出パターン定義
# 日本語の文章から SVO を抽出
# 区切り文字: 空白、句点、読点、・ などを境界として扱う
EXTRACTION_PATTERNS = [
    # 基本 SVO: X は Y を (X=主語、Y=目的語)
    {
        "name": "svo_basic",
        "pattern": r"([^\s・。、\u3000-\u3001\u3002]{2,15})\s*(?:は|が)\s*([^\s・。、\u3000-\u3001\u3002]{1,15})\s*(?:を|に|へ)",
        "subject": 1,
        "object": 2,
    },
    # 対比/関係: X と Y
    {
        "name": "relation",
        "pattern": r"([^\s・。、\u3000-\u3001\u3002]{2,15})\s*(?:と|ととも)\s*([^\s・。、\u3000-\u3001\u3002]{2,15})",
        "subject": 1,
        "object": 2,
    },
    # 定義/述語: X は Y である/だ
    {
        "name": "is_a",
        "pattern": r"([^\s・。、\u3000-\u3001\u3002]{2,15})\s*(?:は|が)\s*([^\s・。、\u3000-\u3001\u3002]{1,15})\s*(?:だ|である|なる|ある)",
        "subject": 1,
        "object": 2,
    },
    # 関連: X における Y
    {
        "name": "in_context",
        "pattern": r"([^\s・。、\u3000-\u3001\u3002]{2,15})\s*(?:における|に関して|について|による)",
        "subject": 1,
        "object": None,  # 特殊: 対象のみ抽出
    },
]

# 抽出対象から除外する単語
STOP_WORDS = {
    "これ", "それ", "あれ", "これら", "それら",
    "いう", "なる", "ある", "する", "できる",
    "この", "その", "あの", "どの",
    "私", "私自身", "自分", "僕", "僕自身",
    "私達", "私たち", "皆", "みんな",
}

# 名詞化パターン (抽出を改善)
# 実際には LLM が理想だが、MVP はシンプルに

# 信頼性が高いパターン (より精密)
HIGH_CONFIDENCE_INDICATORS = [
    r"〜は〜を",
    r"〜が〜を",
    r"〜は〜である",
    r"〜と〜は",
    r"〜における",
    r"〜に関する",
    r"〜に起因",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_relation_id(subject: str, predicate: str, object: str) -> str:
    base = f"{subject}--{predicate}--{object}"
    return f"rel-{hashlib.sha256(base.encode()).hexdigest()[:8]}"


def clean_subject(text: str) -> Optional[str]:
    """抽出された主語をクリーンアップ"""
    text = text.strip()
    if len(text) < 2 or len(text) > 30:
        return None
    if text.lower() in STOP_WORDS:
        return None
    # 日本語名詞として妥当か
    if not re.search(r"[\u3000-\u9fff\u3040-\u309f\u30a0-\u30ff]", text):
        return None
    return text


def clean_object(text: str) -> Optional[str]:
    """抽出された目的語をクリーンアップ"""
    text = text.strip()
    if len(text) < 2 or len(text) > 30:
        return None
    if text.lower() in STOP_WORDS:
        return None
    if not re.search(r"[\u3000-\u9fff\u3040-\u309f\u30a0-\u30ff]", text):
        return None
    return text


def extract_from_passage(text: str) -> List[dict]:
    """単一 passage から SVO 関係を抽出"""
    relations = []

    for pattern_def in EXTRACTION_PATTERNS:
        pattern = pattern_def["pattern"]
        match = re.search(pattern, text)

        if not match:
            continue

        subject_text = match.group(pattern_def["subject"])
        subject = clean_subject(subject_text)

        if not subject:
            continue

        object_text = None
        if pattern_def.get("object") is not None:
            object_text = match.group(pattern_def["object"])
            object_ = clean_object(object_text)

            # subject と object が似ていないかチェック
            if subject == object_:
                continue

        # 信頼度: パターンによる
        confidence = 0.5
        if pattern_def["name"] == "svo_basic":
            confidence = 0.7
        elif pattern_def["name"] == "is_a":
            confidence = 0.8
        elif pattern_def["name"] == "relation":
            confidence = 0.4
        elif pattern_def["name"] == "in_context":
            confidence = 0.3

        # object が None の場合は in_context として特別処理
        if object_text is None:
            object_text = subject_text  # context のみを対象とする
            object_ = subject  # 便宜上
            relations.append({
                "subject": subject,
                "subject_type": "entity",
                "predicate": f"context:{pattern_def['name']}",
                "object": subject,
                "object_type": "entity",
                "confidence": 0.3,
                "extractor": "pattern",
                "source_pattern": pattern_def["name"],
            })
            continue

        relations.append({
            "subject": subject,
            "subject_type": "entity",
            "predicate": pattern_def["name"],
            "object": object_,
            "object_type": "concept",
            "confidence": confidence,
            "extractor": "pattern",
            "source_pattern": pattern_def["name"],
        })

    return relations


def load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_existing_relations(path: Path) -> Dict[Tuple, dict]:
    """既存の relations を辞書形式で読み込み (重複回避)"""
    records = {}
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = (rec["subject"], rec["predicate"], rec["object"])
            records[key] = rec
    return records


def main():
    parser = argparse.ArgumentParser(
        description="Extract SVO relations from passages"
    )
    parser.add_argument(
        "--input",
        default="data/passages.jsonl",
        help="Input passages JSONL",
    )
    parser.add_argument(
        "--relations",
        default="data/relations.jsonl",
        help="Existing relations JSONL to merge with",
    )
    parser.add_argument(
        "--output",
        default="data/relations.jsonl",
        help="Output relations JSONL",
    )
    parser.add_argument(
        "--mode",
        choices=["overwrite", "append"],
        default="append",
        help="Append or overwrite relations",
    )
    args = parser.parse_args()

    # passages を読み込み
    passages = load_jsonl(Path(args.input))
    if not passages:
        print("warning: no passages found", file=sys.stderr)
        return

    # 既存 relations を読み込み
    existing = load_existing_relations(Path(args.relations))

    new_relations = []
    total_extracted = 0

    for passage in passages:
        text = passage.get("text", "")
        passage_id = passage.get("id", "")
        work_id = passage.get("work_id", "")

        extracted = extract_from_passage(text)
        total_extracted += len(extracted)

        for rel in extracted:
            # work_id と passage_id を追加
            rel["passage_id"] = passage_id
            rel["work_id"] = work_id
            rel["id"] = make_relation_id(rel["subject"], rel["predicate"], rel["object"])

            key = (rel["subject"], rel["predicate"], rel["object"])
            if key not in existing:
                new_relations.append(rel)
                existing[key] = rel

    # 既存 + 新規 を結合
    if args.mode == "overwrite":
        all_relations = list(existing.values())
    else:
        # 既存 (hand-crafted) を先に、新規 (pattern-based) を後ろに
        all_relations = list(existing.values()) + new_relations

    # JSONL に出力
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as f:
        for r in all_relations:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(
        f"extracted {total_extracted} relations from {len(passages)} passages, "
        f"added {len(new_relations)} new ones, "
        f"total {len(all_relations)} relations"
    )

    # サンプル出力
    if new_relations:
        print("\nNew relations:")
        for r in new_relations[:5]:
            print(f"  {r['subject']} --{r['predicate']}--> {r['object']}")


if __name__ == "__main__":
    main()