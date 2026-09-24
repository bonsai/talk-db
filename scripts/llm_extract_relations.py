#!/usr/bin/env python3
"""
llm_extract_relations.py

LLM による高精度 SVO 関係抽出
- パターン抽出では見逃した関係を検出
- 信頼度スコアも LLM が判定
- 既存のパターン抽出結果を上書き / マージ可能
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import openai


def get_client() -> openai.OpenAI:
    """OpenRouter 経由の OpenAI クライアントを構築"""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENROUTER_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    return openai.OpenAI(api_key=api_key, base_url=base_url or "https://api.openai.com/v1")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 抽出する SVO の定義
SVO_SCHEMA = """
関係 (Relation) を抽出してください。

ルール:
1. 主語 (subject): 文の主体。固有名詞・抽象概念・実体を抽出。
2. 述語 (predicate): 関係を表す動詞・形容詞。短く簡潔に。
3. 目的語 (object): 主語が対象とするもの。
4. 信頼度 (confidence): 0.0〜1.0。文脈から明確な関係ほど高く。
5. 既に抽出済みの関係はスキップ。新しい関係のみ出力。

出力形式 (JSON):
[
  {"subject": "...", "predicate": "...", "object": "...", "confidence": 0.X},
  ...
]
"""

# 抽出対象から除外するパターン
STOP_SUBJECTS = {
    "これ", "それ", "あれ", "これら", "それら", "それ",
    "私", "僕", "自分", "自分自身",
    "私達", "私たち", "皆", "みんな", "我々",
}

STOP_PREDICATES = {
    "言う", "考える", "思う", "感じる", "なる", "ある", "する",
    "できる", "ない", "ある", "いる",
}


def clean_text(text: str) -> str:
    """抽出対象としてクリーンなテキストを返す"""
    # マークダウン処理
    text = text.replace("**", "").replace("*", "")
    text = text.replace("`", "").replace("```", "")
    text = text.replace("#", "").replace(">", "")
    text = text.replace("|", " ")
    text = text.replace("-", " ")
    # 短すぎる passage はスキップ
    if len(text) < 30:
        return ""
    return text.strip()


def extract_with_llm(client: openai.OpenAI, passages: List[dict], batch_size: int = 5) -> List[dict]:
    """LLM で relations を抽出"""
    client_model = os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4-20250514")
    
    new_relations = []
    total_processed = 0
    
    for batch_start in range(0, len(passages), batch_size):
        batch = passages[batch_start:batch_start + batch_size]
        texts = []
        for p in batch:
            text = clean_text(p.get("text", ""))
            if text:
                texts.append(f"[{p.get('id', '?')}]: {text}")
        
        if not texts:
            continue
        
        prompt = f"""{SVO_SCHEMA}

対象テキスト:
{chr(10).join(texts)}

指示:
- 上記テキストから、以下の形式で関係 (SVO) を抽出してください
- 各関係は新しい情報であること (既知の繰り返しは避ける)
- confidence は 0.5 以上のみ
- subject と object が同じ場合はスキップ
- JSON 配列としてのみ出力。他のテキストを含めない。
"""
        
        try:
            response = client.chat.completions.create(
                model=client_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            
            content = response.choices[0].message.content.strip()
            
            # JSON 部分を抽出 (バッククオートで囲まれている場合に対応)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            
            # JSON として解析
            relations_json = json.loads(content)
            
            for rel in relations_json:
                if isinstance(rel, dict):
                    subject = rel.get("subject", "").strip()
                    predicate = rel.get("predicate", "").strip()
                    object_ = rel.get("object", "").strip()
                    confidence = float(rel.get("confidence", 0.5))
                    
                    # フィルタリング
                    if subject in STOP_SUBJECTS:
                        continue
                    if predicate in STOP_PREDICATES:
                        continue
                    if subject == object_:
                        continue
                    if len(subject) < 2 or len(object_) < 2:
                        continue
                    if confidence < 0.5:
                        continue
                    
                    # source passage を追記
                    relations.append({
                        "id": f"llm-{hashlib.sha256(f'{subject}-{predicate}-{object_}'.encode()).hexdigest()[:8]}",
                        "subject": subject,
                        "subject_type": "entity",
                        "predicate": predicate,
                        "object": object_,
                        "object_type": "concept",
                        "passage_id": batch[0].get("id", ""),
                        "work_id": batch[0].get("work_id", ""),
                        "confidence": confidence,
                        "extractor": "llm",
                        "source_model": client_model,
                    })
            
            total_processed += len(batch)
            print(f"  batch {batch_start // batch_size + 1}: extracted {len(relations_json)} relations from {len(batch)} passages")
            
            # API レート制限対策
            time.sleep(0.5)
            
        except json.JSONDecodeError as e:
            print(f"  JSON decode error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
    
    return new_relations


def load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save_jsonl(path: Path, records: List[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="LLM-based SVO relation extraction")
    parser.add_argument("--passages", default="data/passages.jsonl", help="Input passages JSONL")
    parser.add_argument("--relations", default="data/relations.jsonl", help="Output relations JSONL")
    parser.add_argument("--batch-size", type=int, default=5, help="Batch size for LLM processing")
    parser.add_argument("--dry-run", action="store_true", help="Show first passage without API call")
    parser.add_argument("--limit", type=int, help="Limit number of passages to process")
    args = parser.parse_args()
    
    passages = load_jsonl(Path(args.passages))
    if not passages:
        print("No passages found", file=sys.stderr)
        sys.exit(1)
    
    if args.dry_run:
        print("Dry run mode - would process:")
        for p in passages[:3]:
            print(f"  {p['id']}: {p.get('text', '')[:80]}...")
        return
    
    if args.limit:
        passages = passages[:args.limit]
    
    print(f"Processing {len(passages)} passages with LLM...")
    print(f"Model: {os.environ.get('LLM_MODEL', 'claude-sonnet-4-20250514')}")
    
    client = get_client()
    new_relations = extract_with_llm(client, passages, args.batch_size)
    
    # 既存の relations とマージ
    existing = load_jsonl(Path(args.relations))
    existing_ids = {r["id"] for r in existing}
    
    for r in new_relations:
        if r["id"] not in existing_ids:
            existing.append(r)
            existing_ids.add(r["id"])
    
    # 保存
    save_jsonl(Path(args.relations), existing)
    
    print(f"Total relations: {len(existing)}")
    print(f"New LLM relations: {len(new_relations)}")


if __name__ == "__main__":
    import hashlib
    main()