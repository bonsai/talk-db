# talk-db

bonsai 全体の文章を横断して索引化し、**会話可能な知識（Talk Script 素材）**へ変換する中間層の Corpus DB です。

- 原文は `bonsai/*` の各リポジトリが Canon とします。
- `talk-db` は索引・意味・Talk Pattern 層を持ち、**原文をコピーせず**参照で追跡します。

## Content Pipeline

```
bonsai/* repos (17 件)
    │
    ▼
[extraction] — 全文スキャン・分解
    │
    ├── 1. Git clone (GitHub Actions)
    ├── 2. Markdown scan (ingest.py)
    ├── 3. Passage decomposition
    ├── 4. Concept extraction
    │
    ▼
[talk-db: refining] — JEV スコアリング
    │
    ├── 5. Relations extraction (pattern → LLM)
    ├── 6. JEV scoring (typed decision)
    ├── 7. Talk pattern matching
    │
    ▼
[talkscripts: seed] — 素材選定
    │
    ├── 8. High-quality selection (JEV >= 0.7)
    ├── 9. Talk script generation
    ├── 10. Human check / revision
    │
    ▼
[talkscripts: stage] — 精製・公開
    │
    ├── 11. Quality check (RUBRIC 9 軸)
    ├── 12. VoiceVOX rendering
    ├── 13. MP4 encoding
    │
    ▼
[YouTube] — 動画公開
```

詳細は [`content/PIPELINE.md`](content/PIPELINE.md) を参照。

## アーキテクチャ

```text
bonsai repos (17 件)
        │
        │ ingest (GitHub Actions / 手動)
        ▼
   ┌─────────┐
   │  works  │  ← 作品メタデータ（repo + path + commit_sha で追跡）
   └────┬────┘
        │
   ┌────▼─────┐
   │ passages │  ← 段落・scene 単位の分解
   └────┬─────┘
        │
   ┌────▼──────┐     ┌───────────┐
   │ concepts  │◀────│passage_   │
   └───────────┘     │concepts   │
                     └───────────┘
        │
   ┌────▼──────┐
   │ relations │  ← SVO 関係 (JEV スコア付き)
   └───────────┘
```

## ディレクトリ

```text
data/               JSONL 形式の交換データ（Canon 寄り）
  ├─ works.jsonl
  ├─ passages.jsonl
  ├─ concepts.jsonl
  ├─ passage_concepts.jsonl
  ├─ relations.jsonl
  └─ relations_scored.jsonl  # JEV スコア付き
content/              # 精製フロー
  ├─ seed/             # 素材 (JEV スコアリング済み)
  ├─ refining/         # 精製 (Talk Script)
  ├─ stage/            # ステージ (チェック済み)
  └─ check/            # チェック (最終品質)
schema/
  ├─ schema.json
  └─ schema.sql
scripts/
  ├─ ingest.py                # bonsai/* をスキャンして JSONL を生成
  ├─ build_db.py              # JSONL → SQLite
  ├─ discover.py              # bonsai/* 自動発見
  ├─ extract_relations.py     # パターンベース SVO 抽出
  ├─ llm_extract_relations.py # LLM 高精度 SVO 抽出
  ├─ jeva.py                  # JEV スコアリング
  └─ requirements.txt
db/
  └─ talk.db          # SQLite + FTS5 検索用 DB（生成物）
.github/workflows/
  └─ ingest.yml       # 定期 / 手動インジェスト
```

## テーブル

| テーブル | 内容 |
|---|---|
| `works` | 作品メタデータ (124 件) |
| `passages` | 段落分解 (1634 件) |
| `concepts` | コンセプト (18 件) |
| `passage_concepts` | passage-concept 紐付け (694 件) |
| `relations` | SVO 関係 (654 件, JEV スコア付き) |
| `talk_patterns` | Talk Script パターン (5 件) |
| `passages_fts` | 全文検索 (FTS5) |

## JEV スコアリング

JEV (TypeSafe System One) で関係の「Talk 素材としての品質」を判定。

```bash
# OpenRouter API モード
python3 scripts/jeva.py \
  --relations data/relations.jsonl \
  --instruction talk_material \
  --output data/relations_scored.jsonl

# OpenJev ローカルモード
python3 scripts/jeva.py \
  --relations data/relations.jsonl \
  --instruction talk_material \
  --mode openjev \
  --output data/relations_scored.jsonl
```

### Judgment Instructions

```python
# Talk 素材品質
"talk_material": "この文章は Talk (会話・議論) の素材として適切か。",
"surprise": "意外な転換や逆説が含まれているか。",
"question": "明確な問いを立てているか。",
"revelation": "隠された事実を明らかにしているか。",
"analogy": "適切な比喩や類似関係を示しているか。",
"contradiction": "矛盾やパラドックスが含まれているか。",

# 関係性品質
"clear_relation": "主語 - 述語 - 目的語の関係は明確か。",
"deep_relation": "表面的ではなく本質的か。",
"novel_relation": "新規性があるか。",

# SVO 品質
"valid_svo": "文法的に成立しているか。",
"meaningful_svo": "意味のある関係を示しているか。",
"actionable_svo": "Talkscripts の生成に活用できるか。",
```

## bonsai/* 記事リポジトリ一覧 (17 件)

| リポジトリ | 型 | スコア |
|---|---|---|
| research-rakugo | rakugo | 12 |
| talkscripts | talkscript | 8 |
| unipath-skills | note | - |
| writing | essay | - |
| win-tips | note | - |
| tips-word | note | - |
| skill-crawler | research | - |
| skill-consolidator | research | - |
| pi-config-memo | note | - |
| mimic-me | research | - |
| hakkutu | research | - |
| char-distribution | research | - |
| yoshimoto-theater | fiction | - |
| repos-analyze | research | - |
| research-jev | research | - |
| life-design-skill | essay | - |
| houki-skill | note | - |

## 使い方

```bash
# 1. 依存を入れる
pip install -r scripts/requirements.txt

# 2. bonsai/* をスキャン
python3 scripts/ingest.py --repos ../research-rakugo ../talkscripts --output data/

# 3. 関係抽出 + JEV スコアリング
python3 scripts/extract_relations.py --input data/passages.jsonl \
  --relations data/relations.jsonl --output data/relations.jsonl --mode append
python3 scripts/jeva.py --relations data/relations.jsonl \
  --instruction talk_material --output data/relations_scored.jsonl

# 4. SQLite DB を構築
python3 scripts/build_db.py --data data/ --db db/talk.db

# 5. 検索例
sqlite3 db/talk.db "SELECT * FROM passages_fts WHERE passages_fts MATCH 'AI';"
sqlite3 db/talk.db "SELECT subject, predicate, object FROM relations WHERE jev_probability >= 0.7;"
```

## ポリシー

1. **原文はコピーしない**: `works` は `repo + path + commit_sha + content_hash` でソースを参照します。
2. **JSONL ↔ SQLite**: JSONL を交換形式、SQLite を検索用に使います。
3. **JEV 判定**: 関係の Talk 素材品質を自動スコアリング。信頼度 >= 0.7 のみ採用。
4. **原文追跡**: `bonsai/*` が Canon、`talk-db` は索引層。