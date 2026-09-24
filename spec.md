# talk-db Spec — 作品分類・関係抽出・自動発見設計

## 1. works.type — 作品の存在論 enum

Type は「その文章が何なのか」を分類する。**Genre とは分離する**。

```
type enum:
  - essay      — 随筆・評論・考察 (思考の文章)
  - fiction    — 小説 (フィクション)
  - sf         —  SF 小説 (fiction の subtype として genre に含める)
  - dialogue   — 対話・インタビュー・会話記録
  - poem       — 詩
  - note       — メモ・断片・箇条書き
  - research   — 研究・論文・技術文書
  - script     — 台本・動画台本・朗読用テキスト
  - other      — 上記に当てはまらない
```

**Type と Genre の分離**:
```yaml
type: fiction
genre:
  - SF
  - 哲学的

type: essay
genre:
  - 哲学
  - 技術

type: fiction
genre:
  - SF
```

この分離により、
- `type: fiction AND genre: SF` → SF 小説
- `type: essay AND genre: SF` → SF に関する評論/考察
- `type: fiction AND genre: []` → ジャンル未指定の物語

など、**2 軸で文章の性質を定義できる**。

## 2. 型検出ルール (ingest.py 実装)

ファイル名・パス・内容のトリガーから自動分類。

### 2.1 File name / Path 検出

```yaml
rules:
  # Type 検出 (ファイル名・パスベース)
  - name: essay
    patterns:
      - filename: "essay-*"
      - filename: "*_essay*"
      - path: contains("essay")
    weight: 1.0

  - name: fiction
    patterns:
      - filename: "shortstory-*"
      - filename: "novel-*"
      - filename: "*story*"
      - path: contains("SFショートショート")
      - path: contains("SF落語")
    weight: 1.0

  - name: dialogue
    patterns:
      - filename: "対話*"
      - filename: "*dialogue*"
      - filename: "*会話*"
    weight: 0.9

  - name: script
    patterns:
      - path: contains("知恵の館")
      - filename: "*台本*"
      - filename: "talk-*"
      - filename: "*script*"
    weight: 0.8

  - name: poem
    patterns:
      - filename: "poem*"
      - filename: "*詩*"
    weight: 1.0

  - name: research
    patterns:
      - filename: "research-*"
      - filename: "*論文*"
      - filename: "*paper*"
    weight: 0.9

  - name: note
    patterns:
      - filename: "*note*"
      - filename: "*memo*"
      - path: contains("seed")
    weight: 0.7

  # Genre 検出 (内容ベース)
  - name: SF
    patterns:
      - text: contains("SF" OR "宇宙" OR "未来" OR "AI" OR "タイムトラベル")
      - path: contains("SF")
    weight: 0.7

  - name: 哲学
    patterns:
      - text: contains("哲学" OR "思想" OR "存在" OR "認識")
    weight: 0.6

  - name: 技術
    patterns:
      - text: contains("技術" OR "コード" OR "実装" OR "API")
    weight: 0.5

  - name: 落語
    patterns:
      - path: contains("SF落語")
      - text: contains("噺家" OR "口上" OR "オチ")
    weight: 0.7
```

### 2.2 判定アルゴリズム

```
1. filename/Path ルールをスコアリング
2. 最もスコアが高い type を選択
3. 同点の場合: filename > path > content の優先
4. 内容解析 (字数 < 50 なら note 優先)
5. 最終的に "other" にフォールバック
```

## 3. relations テーブル設計

SVO (Subject-Verb-Object) 形式で「文章の意味関係」を記録。

```
relations テーブル:
  id              TEXT PRIMARY KEY
  subject         TEXT NOT NULL    -- 主語 (例: "AI", "人間", "記憶")
  subject_type    TEXT             -- entity / concept / abstract
  predicate       TEXT NOT NULL    -- 述語 (例: "求める", " fear ", "記憶する", "問いかける")
  object          TEXT             -- 目的語 (例: "真実", "AI", "過去")
  object_type     TEXT             -- entity / concept / abstract
  passage_id      TEXT             -- 関係が含まれる passage の ID
  work_id         TEXT             -- 元の作品 ID
  confidence      REAL             -- 抽出信頼度 (0.0 ~ 1.0)
  extractor       TEXT             -- manual / keyword / llm / pattern
```

### 使用例

```
AI → 知る → 孤独
人間 → fear → AI
記憶 → 失われる → 自我
```

### 抽出戦略 (フェーズ分け)

| フェーズ | 方法 | 精度 |
|----------|------|------|
| MVP | 手動で seed 登録 | 100% |
| v2 | キーワードパターン (`X は Y を`) | 60-70% |
| v3 | LLM による意味解析 | 80%+ |

## 4. talk_patterns テーブル設計

Talkscripts 固有のパターン定義。

```
talk_patterns テーブル:
  id            TEXT PRIMARY KEY
  name          TEXT NOT NULL    -- パターン名
  description   TEXT             -- 説明
  pattern       TEXT             -- 構造定義 (例: "A→B→unexpected_C")
```

```
passage_patterns テーブル:
  passage_id    TEXT
  pattern_id    TEXT
  confidence    REAL
  extractor     TEXT
  PRIMARY KEY (passage_id, pattern_id)
```

### 初期パターン例

| id | name | pattern | 説明 |
|---|---|---|---|
| surprise | 意外な転換 | A→B→unexpected_C | 読者の予想を裏切る転換点 |
| question | 問い | situation→question→exploration | 状況から問いを立てる |
| contradiction | 矛盾 | A→not_A | 相反する命題の提示 |
| revelation | 開示 | hidden_X→reveal_X | 隠れた事実の明か |
| analogy | 比喩 | X→Y | 異なる概念の結びつけ |

## 5. bonsai/* 自動発見インジェスト

現在の `talk-db` は talkscripts からのみ読み込んでいる。次は **bonsai の全テキストリポジトリを探索** する。

### 5.1 検出対象の基準

```
bonsai/* リポジトリの候補基準:
  - .md / .txt / .mdx が含まれる
  - コードリポジトリではない (Python, JS, Go などのソースコード中心でない)
  - 日本語または英語の自然言語文章を含む
```

### 5.2 検出アプローチ

**Approach A: ローカルスキャン** (`scripts/discover.py`)
```
1. /home/bons/repos/* を走査
2. .git があるものをリポジトリと認識
3. *.md ファイルがあるか確認
4. 記事の傾向を判定 (essay / fiction / etc)
5. 候補リストを出力
```

**Approach B: GitHub API 検索** (GitHub Actions 内)
```
1. "bonsai" org の全リポジトリを取得
2. "content:readme" または "*.md" でフィルタ
3. 各リポジトリのファイル構造を分析
4. 対象かどうかを判定
```

### 5.3 候補スコアリング

```yaml
score_components:
  md_file_count:      +1 per file (max 5)
  total_char_count:   +2 if > 1000 chars
  avg_paragraph_len:  +1 if > 50 chars
  has_emoji:          -1 (技術文書かもしれない)
  has_code_blocks:    -1 (コードリポジトリかもしれない)
  language_score:     +2 if primarily Japanese/English
  repo_name_match:    +2 if name matches known essay/sf/novel patterns
```

## 6. 開発ロードマップ

| 段階 | タスク | 成果物 |
|------|--------|--------|
| **1. 現在** | Type 定義・検出ルール | `spec.md`, `schema.sql`, `ingest.py` 更新 |
| **2. 次** | relations / talk_patterns テーブル追加 | `schema.sql` 更新 + 初期データ |
| **3. その次** | bonsai/* 自動発見インジェスト | `scripts/discover.py` + GitHub Actions |
| **4. さらに次** | LLM による関係抽出 | 意味解析パイプライン |

## 7. 重要な設計判断

### Q: なぜ Type と Genre を分離するのか?
A: **同じ型 (fiction) でも異なったジャンル (SF, 純文学) に分類できる**ため。
- `type: fiction, genre: [SF]` → SF 小説
- `type: fiction, genre: [文学]` → 純文学
- `type: essay, genre: [哲学, SF]` → SF に関する哲学論考

### Q: SF を Type にしないのは?
A: SF は「ジャンル」であり「型の概念」ではない。
SF 作品も「小説 (fiction)」「評論 (essay)」「対話 (dialogue)」になり得るため。

### Q: relations を最初から実装しないのは?
A: **SVO 抽出は精度が難しい**ため。MVP では手動 seed で十分。
v2 でキーワードパターン、v3 で LLM 抽出に段階的に高度化する。

### Q: talk_patterns は何のためにある?
A: **Talkscripts 用に変換しやすい「型」としての文章パターン**を索引化するため。
「問い→展開→着地」のパターンを検索できれば、Talkscripts の生成が自動化できる。