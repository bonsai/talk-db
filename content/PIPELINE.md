# talk-db Content Pipeline

bonsai 全文書 → JEV スコアリング → Talk Script → 動画・朗読

## 全体フロー

```
bonsai/* repos
    │
    ▼
[extraction]
    │
    ├── 1. Git clone (GitHub Actions)
    ├── 2. Markdown scan (ingest.py)
    ├── 3. Passage decomposition (split_passages)
    ├── 4. Concept extraction (keyword → LLM)
    │
    ▼
[talk-db: refining]
    │
    ├── 5. Relations extraction (pattern → LLM)
    ├── 6. JEV scoring (typed decision)
    ├── 7. Talk pattern matching
    │
    ▼
[talkscripts: seed]
    │
    ├── 8. High-quality selection (JEV >= 0.7)
    ├── 9. Talk script generation
    ├── 10. Human check / revision
    │
    ▼
[talkscripts: stage]
    │
    ├── 11. Quality check (RUBRIC 9 軸)
    ├── 12. VoiceVOX rendering
    ├── 13. MP4 encoding
    │
    ▼
[コンテンツフォルダ]
    │
    ├── 14. YouTube upload
    ├── 15. Website publishing
    └── 16. Analytics (JEV analytics)
```

## Folder Structure

```text
talk-db/
├─ data/                    # JSONL canon files
│  ├─ works.jsonl
│  ├─ passages.jsonl
│  ├─ concepts.jsonl
│  ├─ passage_concepts.jsonl
│  ├─ relations.jsonl
│  └─ relations_scored.jsonl  # JEV スコア付き
│
├─ content/                 # 精製フロー
│  ├─ seed/                 # 素材 (JEV スコアリング済み)
│  ├─ refining/             # 精製 (Talk Script)
│  ├─ stage/                # ステージ (チェック済み)
│  └─ check/                # チェック (最終品質)
│
├─ db/                      # SQLite DB (生成物)
│  └─ talk.db
│
├─ scripts/                 # パイプラインスクリプト
│  ├─ ingest.py             # リポジトリスキャン
│  ├─ extract_relations.py  # SVO 関係抽出
│  ├─ llm_extract_relations.py  # LLM 高精度抽出
│  ├─ jeva.py               # JEV スコアリング
│  └─ discover.py           # bonsai/* 自動発見
│
└─ .github/workflows/
   └─ ingest.yml            # 自動パイプライン
```

## JEV スコアリング

JEV (TypeSafe System One) で関係の「Talk 素材としての品質」を判定。

### Judgment Instructions

```python
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
```

### 使用方法

```bash
# OpenRouter API モード
python scripts/jeva.py \
  --relations data/relations.jsonl \
  --instruction talk_material \
  --output data/relations_scored.jsonl

# OpenJev ローカルモード
python scripts/jeva.py \
  --relations data/relations.jsonl \
  --instruction talk_material \
  --mode openjev \
  --output data/relations_scored.jsonl
```

### 信頼度フィルタ

```python
# JEV スコア >= 0.7 の関係のみを Talk 素材として採用
filtered = apply_jev_filter(relations, scored_results, min_probability=0.7)
```

## 精製フロー

### 1. extraction (bonsai/* repos)

- リポジトリスキャン (ingest.py)
- Markdown 分解 (passages)
- コンセプト抽出 (concepts)

### 2. refining (talk-db)

- 関係抽出 (relations)
- JEV スコアリング (talk_material, surprise, etc.)
- Talk pattern マッチング

### 3. seed (talkscripts)

- 高品質素材選定 (JEV >= 0.7)
- Talk Script 生成

### 4. stage (talkscripts)

- 品質チェック (RUBRIC 9 軸)
- VoiceVOX レンダリング
- MP4 エンコーディング

### 5. check (talkscripts)

- 最終品質確認
- YouTube 公開
- アナリティクス

## リポジトリ一覧

### 文章リポジトリ (17 件)

| リポジトリ | 説明 | 型 |
|---|---|---|
| research-rakugo | 落語の型を探る研究 | fiction |
| talkscripts | 台本リポジトリ | script |
| unipath-skills | VoiceFlow-style skill collection | note |
| writing | 文章 | essay |
| win-tips | Windows のヒント | note |
| tips-word | 言葉のヒント | note |
| skill-crawler | スキルクローラー | research |
| skill-consolidator | スキル統合 | research |
| pi-config-memo | Pi 設定メモ | note |
| mimic-me | 模倣 | research |
| hakkutu | 発見 | research |
| char-distribution | 文字分布 | research |
| yoshimoto-theater | 吉本劇場 | fiction |
| repos-analyze | リポジトリ分析 | research |
| research-jev | Jev 研究 | research |
| life-design-skill | 人生デザインスキル | essay |
| houki-skill | ほうきスキル | note |

### コードリポジトリ (除外)

- agents, wf-errors, issues, localbqml, bons.ai, emoji-shiritori, gh-chatgpt-ext, idol-playlist, showa-covers, leanvj, terminal-capture, plego, idol-db, kimura

## 次回タスク

- [ ] LLM による高精度 SVO 抽出
- [ ] passage_patterns (talkscript 用パターンマッチング)
- [ ] 自動 talkscript 生成
- [ ] Rubric 9 軸自動採点
- [ ] VoiceVOX + MP4 エンコード自動化