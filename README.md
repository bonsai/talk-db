# talk-db

bonsai 全体の文章を横断して索引化し、**会話可能な知識（Talk Script 素材）**へ変換する中間層の Corpus DB です。

- 原文は `bonsai/*` の各リポジトリが Canon とします。
- `talk-db` は索引・意味・Talk Pattern 層を持ち、**原文をコピーせず**参照で追跡します。

## アーキテクチャ

```text
bonsai repos (essay-xxx, sf-xxx, novel-xxx, talkscripts, ...)
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
```

将来的に `relations` と `talk_patterns` を追加します。

## ディレクトリ

```text
data/               JSONL 形式の交換データ（Canon 寄り）
  ├─ works.jsonl
  ├─ passages.jsonl
  ├─ concepts.jsonl
  ├─ passage_concepts.jsonl
  └─ talk_patterns.jsonl
schema/
  ├─ schema.json
  └─ schema.sql
scripts/
  ├─ ingest.py        # bonsai/* をスキャンして JSONL を生成
  ├─ build_db.py      # JSONL → SQLite
  └─ requirements.txt
db/
  └─ talk.db          # SQLite + FTS5 検索用 DB（生成物）
.github/workflows/
  └─ ingest.yml       # 定期 / 手動インジェスト
```

## MVP テーブル

- `works`
- `passages`
- `concepts`
- `passage_concepts`

詳細は [`schema/schema.sql`](schema/schema.sql) を参照。

## 使い方

```bash
# 1. 依存を入れる
pip install -r scripts/requirements.txt

# 2. 指定リポジトリをスキャンして JSONL 生成
python scripts/ingest.py --repos ../talkscripts ../essay-xxx --output data/

# 3. SQLite DB を構築
python scripts/build_db.py --data data/ --db db/talk.db

# 4. 検索例
sqlite3 db/talk.db "SELECT * FROM passages_fts WHERE passages_fts MATCH 'AI';"
```

## ポリシー

1. **原文はコピーしない**: `works` は `repo + path + commit_sha + content_hash` でソースを参照します。
2. **JSONL ↔ SQLite**: JSONL を交換形式、SQLite を検索用に使います。
3. **MVP から始める**: 最初は `works / passages / concepts / passage_concepts` のみ。
