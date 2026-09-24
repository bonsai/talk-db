-- talk-db MVP schema
-- SQLite + FTS5

PRAGMA foreign_keys = ON;

-- 作品単位のメタデータ
CREATE TABLE IF NOT EXISTS works (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    title TEXT,
    author TEXT,
    type TEXT,            -- fiction / essay / script / poem / other
    genre TEXT,           -- JSON array ["SF", "哲学"]
    language TEXT,
    summary TEXT,
    source_url TEXT,
    commit_sha TEXT,
    content_hash TEXT,    -- sha256 of raw file content
    status TEXT,          -- discovered / indexed / stale
    created_at TEXT,      -- ISO8601
    updated_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_works_repo_path_commit
    ON works(repo, path, commit_sha);

-- 段落・scene 単位の分解
CREATE TABLE IF NOT EXISTS passages (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES passages(id) ON DELETE CASCADE,
    type TEXT,            -- chapter / scene / paragraph / sentence
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_passages_work_id ON passages(work_id);
CREATE INDEX IF NOT EXISTS idx_passages_parent_id ON passages(parent_id);

-- 概念（テーマ・キーワード・トピック）
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT,            -- theme / keyword / entity / topic
    description TEXT
);

--  passage → concept の紐付け
CREATE TABLE IF NOT EXISTS passage_concepts (
    passage_id TEXT NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    confidence REAL,      -- 0.0 ~ 1.0
    extractor TEXT,       -- manual / keyword / llm
    PRIMARY KEY (passage_id, concept_id)
);

CREATE INDEX IF NOT EXISTS idx_pc_concept ON passage_concepts(concept_id);
CREATE INDEX IF NOT EXISTS idx_pc_passage ON passage_concepts(passage_id);

-- 全文検索用 FTS5 仮想テーブル
CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text,
    content='passages',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts(rowid, text)
    VALUES (NEW.rowid, NEW.text);
END;

CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text)
    VALUES ('delete', OLD.rowid, OLD.text);
END;

CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text)
    VALUES ('delete', OLD.rowid, OLD.text);
    INSERT INTO passages_fts(rowid, text)
    VALUES (NEW.rowid, NEW.text);
END;

-- 将来的に追加するテーブル（定義のみ）
-- relations: SVO 形式の意味関係
-- talk_patterns: talkscripts 用パターン
