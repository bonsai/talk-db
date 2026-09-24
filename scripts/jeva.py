#!/usr/bin/env python3
"""
jeva.py — JEV (typed decision) scoring for talk-db relations

JEV (TypeSafe System One) の Python 実装。
2 つのモードをサポート:
1. OpenRouter Jev API (~typesafe/jev-latest)
2. OpenJev ローカル (Qwen3.5-4B モデル)

Usage:
    # OpenRouter API モード
    python scripts/jeva.py --relations data/relations.jsonl --instruction talk_material
    
    # OpenJev ローカルモード
    python scripts/jeva.py --relations data/relations.jsonl --mode openjev --model Qwen3.5-4B
    
    # ダミー実行 (テスト)
    python scripts/jeva.py --relations data/relations.jsonl --dry-run
"""
import json
import os
import sys
import time
import hashlib
import requests
from typing import List, Dict, Optional, Tuple, Any, Union
from dataclasses import dataclass, field


@dataclass
class Event:
    """JEV でスコアリング対象のイベント"""
    key: str
    text: str
    instruction: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Scored:
    """JEV によるスコアリング結果"""
    key: str
    text: str
    instruction: str
    probability: float
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# Talk-db 用 JEV judgment instructions
# JEV で判定したい「関係の性質」を定義

JUDGMENT_INSTRUCTIONS = {
    # Talk 素材としての品質
    "talk_material": "この文章は Talk (会話・議論) の素材として適切か。",
    "surprise": "この文章には意外な転換や逆説が含まれているか。",
    "question": "この文章は明確な問いを立てているか。",
    "revelation": "この文章は隠された事実を明らかにしているか。",
    "analogy": "この文章は適切な比喩や類似関係を示しているか。",
    "contradiction": "この文章には矛盾やパラドックスが含まれているか。",
    
    # 関係性としての品質
    "clear_relation": "この主語 - 述語 - 目的語の関係は明確か。",
    "deep_relation": "この関係は表面的ではなく本質的か。",
    "novel_relation": "この関係は新規性があるか。",
    
    # 概念の関連性
    "theme_alignment": "この文章はテーマ (SF・哲学・技術) に適合しているか。",
    "cross_domain": "この文章は異なる分野を横断しているか。",
    
    # SVO 抽出の品質
    "valid_svo": "この SVO (主語 - 述語 - 目的語) は文法的に成立しているか。",
    "meaningful_svo": "この SVO は意味のある関係を示しているか。",
    "actionable_svo": "この SVO は Talkscripts の生成に活用できるか。",
}


class JevClient:
    """
    JEV (TypeSafe System One / OpenJev) へのクライアント。
    
    文章の「関係性の強さ」や「Talk 素材としての品質」を Jev で判定。
    
    Usage:
        # OpenRouter API モード
        client = JevClient(mode="openrouter")
        scored = client.score_event(event, instruction="この関係は Talk に適しているか")
        
        # OpenJev ローカルモード (Qwen3.5-4B)
        client = JevClient(mode="openjev", model="Qwen/Qwen3.5-4B")
        scored = client.score_event(event, instruction="関係の明確性")
    """
    
    OPENROUTER_BASE = "https://openrouter.ai/api/alpha/decisions"
    OPENROUTER_MODEL = "~typesafe/jev-latest"
    OPENJEV_ENDPOINT = "http://localhost:8000/score"  # OpenJev サーバー
    
    def __init__(
        self,
        mode: str = "openrouter",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        host: str = "localhost",
        port: int = 8000,
        dry_run: bool = False
    ):
        """
        Args:
            mode: "openrouter" or "openjev"
            api_key: OpenRouter API key
            model: OpenJev model ID (e.g., "Qwen/Qwen3.5-4B")
            host: OpenJev server host
            port: OpenJev server port
            dry_run: API を呼ばずにダミー結果を返す
        """
        self.mode = mode
        self.dry_run = dry_run
        self.model = model or "Qwen/Qwen3.5-4B"
        self.host = host
        self.port = port
        self.key = api_key or self._find_key()
        
        if mode == "openrouter":
            self.base = self.OPENROUTER_BASE
            self.jev_model = self.OPENROUTER_MODEL
        elif mode == "openjev":
            self.base = f"http://{host}:{port}/score"
            self.jev_model = model
        else:
            raise ValueError(f"Unknown mode: {mode}")
    
    def _find_key(self) -> str:
        """API key を environment / ファイルから自動検出"""
        for env_key in ["OPENROUTER_API_KEY", "TYPESAFE_API_KEY"]:
            val = os.environ.get(env_key, "")
            if val:
                return val
        # ~/.config/semgrep/.env
        for path in [".env", os.path.expanduser("~/.config/semgrep/.env")]:
            if os.path.exists(path):
                with open(path, "r") as f:
                    for line in f:
                        line = line.strip()
                        for prefix in ["OPENROUTER_API_KEY=", "TYPESAFE_API_KEY="]:
                            if line.startswith(prefix):
                                return line.split("=", 1)[1].strip()
        raise ValueError("No Jev API key found. Set OPENROUTER_API_KEY or TYPESAFE_API_KEY")
    
    def score_event(self, event: Event, instruction: str) -> Scored:
        """単一 event をスコアリング"""
        if self.dry_run:
            return Scored(
                key=event.key,
                text=event.text[:200],
                instruction=instruction,
                probability=-1.0,
                error="dry run"
            )
        
        if self.mode == "openrouter":
            return self._score_openrouter(event, instruction)
        elif self.mode == "openjev":
            return self._score_openjev(event, instruction)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")
    
    def _score_openrouter(self, event: Event, instruction: str) -> Scored:
        """OpenRouter Jev API でのスコアリング"""
        state = {event.key: self._clip(event.text, 1800)}
        question = {
            event.key + "_m0": {
                "type": "noul",
                "instructions": f'Does event {event.key} match the meaning: "{instruction}"?'
            }
        }
        
        body = json.dumps({
            "model": self.jev_model,
            "state": state,
            "questions": question
        })
        
        return self._round_trip(body, event)
    
    def _score_openjev(self, event: Event, instruction: str) -> Scored:
        """OpenJev ローカルでのスコアリング"""
        # OpenJev の API フォーマット
        state = event.text[:1800]
        options = [
            {"id": "yes", "description": "Yes, this matches the meaning"},
            {"id": "no", "description": "No, this does not match"},
        ]
        
        body = json.dumps({
            "state": state,
            "question": instruction,
            "options": options
        })
        
        try:
            resp = requests.post(
                self.base,
                headers={"Content-Type": "application/json"},
                data=body.encode(),
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            prob = data.get("yes", 0.0)
            return Scored(
                key=event.key,
                text=event.text[:200],
                instruction=instruction,
                probability=prob
            )
        except Exception as e:
            return Scored(
                key=event.key,
                text=event.text[:200],
                instruction=instruction,
                probability=0.0,
                error=str(e)
            )
    
    def score_events(self, events: List[Event], instruction: str) -> List[Scored]:
        """
        複数 event をバッチ処理でスコアリング。
        """
        scored_results = []
        
        for event in events:
            scored = self.score_event(event, instruction)
            scored_results.append(scored)
            
            # レート制限対策 (OpenRouter のみ)
            if self.mode == "openrouter" and not self.dry_run:
                time.sleep(0.5)
        
        return scored_results
    
    def _round_trip(self, body: str, event: Event) -> Scored:
        """HTTP リクエストを retries 付きで実行"""
        last_error = None
        
        for attempt in range(6):
            try:
                resp = requests.post(
                    self.base,
                    headers={
                        "Authorization": f"Bearer {self.key}",
                        "Content-Type": "application/json",
                    },
                    data=body.encode(),
                    timeout=60
                )
                
                if resp.status_code in [429, 529] or resp.status_code >= 500:
                    last_error = f"{resp.status_code}"
                    time.sleep(self._backoff(attempt))
                    continue
                
                if resp.status_code != 200:
                    return Scored(
                        key=event.key, text=event.text[:200],
                        instruction=event.instruction or "",
                        probability=0.0,
                        error=f"HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                
                data = resp.json()
                answers = data.get("answers", data.get("data", {}).get("answers", {}))
                key = event.key + "_m0"
                if key in answers:
                    prob = answers[key].get("noul", 0.0)
                    return Scored(
                        key=event.key, text=event.text[:200],
                        instruction=event.instruction or "",
                        probability=float(prob)
                    )
                return Scored(
                    key=event.key, text=event.text[:200],
                    instruction=event.instruction or "",
                    probability=0.0,
                    error="no answer from Jev"
                )
                
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                time.sleep(self._backoff(attempt))
        
        return Scored(
            key=event.key, text=event.text[:200],
            instruction=event.instruction or "",
            probability=0.0,
            error=f"Max retries exceeded: {last_error}"
        )
    
    @staticmethod
    def _clip(s: str, n: int) -> str:
        """文字列を指定長にクリップ"""
        if len(s) <= n:
            return s
        return s[:n]
    
    @staticmethod
    def _backoff(attempt: int) -> float:
        """指数バックオフ (最小 0.5 秒)"""
        delay = min(1 << attempt, 30)
        return max(0.5, delay)


def create_jev_events_from_relations(relations: List[Dict], instruction: str) -> List[Event]:
    """
    relations.jsonl の関係データを JEV 用イベントに変換。
    """
    events = []
    for rel in relations:
        text = f"{rel.get('subject', '')} {rel.get('predicate', '')} {rel.get('object', '')}"
        event = Event(
            key=f"rel-{rel.get('id', hashlib.sha256(text.encode()).hexdigest()[:8])}",
            text=text,
            instruction=instruction,
            metadata={
                "subject": rel.get("subject", ""),
                "predicate": rel.get("predicate", ""),
                "object": rel.get("object", ""),
                "extractor": rel.get("extractor", ""),
                "work_id": rel.get("work_id", ""),
                "passage_id": rel.get("passage_id", ""),
            }
        )
        events.append(event)
    return events


def run_jev_scoring(
    relations_path: str = "data/relations.jsonl",
    instruction: str = "talk_material",
    output_path: Optional[str] = None,
    dry_run: bool = False,
    min_score: float = 0.5,
    batch_size: int = 30,
    mode: str = "openrouter"
) -> List[Scored]:
    """
    relations に JEV スコアリングを適用。
    
    Args:
        relations_path: 入力 relations JSONL
        instruction: JEV judgment instruction (JUDGMENT_INSTRUCTIONS から選択)
        output_path: 出力先 (None で stdout)
        dry_run: ダミー実行
        min_score: 信頼度閾値
        batch_size: バッチサイズ
        mode: "openrouter" or "openjev"
    """
    # relations を読み込み
    with open(relations_path, "r", encoding="utf-8") as f:
        relations = [json.loads(line) for line in f if line.strip()]
    
    # JEV instruction を取得
    if isinstance(instruction, str) and instruction in JUDGMENT_INSTRUCTIONS:
        instruction_text = JUDGMENT_INSTRUCTIONS[instruction]
    else:
        instruction_text = instruction
    
    print(f"Scoring {len(relations)} relations with JEV instruction:")
    print(f'  "{instruction_text}"')
    print()
    
    # イベントに変換
    events = create_jev_events_from_relations(relations, instruction_text)
    
    # JEV スコアリング
    client = JevClient(mode=mode, dry_run=dry_run)
    
    scored_results = []
    for start in range(0, len(events), batch_size):
        end = min(start + batch_size, len(events))
        batch = events[start:end]
        
        print(f"Batch {start // batch_size + 1}: scoring {len(batch)} events")
        results = client.score_events(batch, instruction_text)
        scored_results.extend(results)
        
        # スコアの分布を表示
        scores = [r.probability for r in results if r.probability >= 0]
        if scores:
            avg = sum(scores) / len(scores)
            high = sum(1 for s in scores if s > 0.8)
            print(f"  avg={avg:.2f}, high(>0.8)={high}/{len(scores)}")
    
    # 結果を保存
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            for r in scored_results:
                f.write(json.dumps(r.__dict__, ensure_ascii=False) + "\n")
        print(f"\nSaved {len(scored_results)} scored results to {output_path}")
    
    return scored_results


def apply_jev_filter(
    relations: List[Dict],
    scored_results: List[Scored],
    min_probability: float = 0.5
) -> List[Dict]:
    """
    JEV スコアリング結果を使って関係をフィルタリング。
    信頼度が高い関係のみを残す。
    """
    score_map = {r.key: r.probability for r in scored_results}
    filtered = []
    
    for rel in relations:
        key = rel.get("id", f"rel-{hashlib.sha256(rel.get('text', '').encode()).hexdigest()[:8]}")
        prob = score_map.get(key, 0.0)
        
        if prob >= min_probability:
            rel["jev_probability"] = prob
            filtered.append(rel)
    
    return filtered


if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="JEV scoring for talk-db relations")
    parser.add_argument("--relations", default="data/relations.jsonl", help="Input relations JSONL")
    parser.add_argument("--instruction", default="talk_material", help=f"JEV instruction: {list(JUDGMENT_INSTRUCTIONS.keys())}")
    parser.add_argument("--output", help="Output scored results JSONL")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no API calls)")
    parser.add_argument("--min-score", type=float, default=0.5, help="Minimum probability threshold")
    parser.add_argument("--batch-size", type=int, default=30, help="Batch size for JEV API")
    parser.add_argument("--mode", default="openrouter", choices=["openrouter", "openjev"], help="JEV mode")
    args = parser.parse_args()
    
    print("JEV Scoring for talk-db relations")
    print("=" * 60)
    print(f"Relations: {args.relations}")
    print(f"Instruction: {args.instruction}")
    print(f"Output: {args.output or 'stdout'}")
    print(f"Dry run: {args.dry_run}")
    print(f"Min score: {args.min_score}")
    print(f"Mode: {args.mode}")
    print()
    
    try:
        scored_results = run_jev_scoring(
            relations_path=args.relations,
            instruction=args.instruction,
            output_path=args.output,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            mode=args.mode
        )
        
        # フィルタリング結果を出力
        filtered = apply_jev_filter(
            [json.loads(line) for line in open(args.relations, "r", encoding="utf-8")],
            scored_results,
            min_probability=args.min_score
        )
        
        print(f"\nFiltered: {len(filtered)} relations >= {args.min_score}")
        
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)