#!/usr/bin/env python3
"""
build_db.py

Build SQLite + FTS5 search DB from JSONL canon files.
"""
import argparse
import json
import sqlite3
from pathlib import Path


SCHEMA_PATH = Path(__file__).parent.parent / "schema" / "schema.sql"


def load_jsonl(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data", help="JSONL data directory")
    parser.add_argument("--db", default="db/talk.db", help="Output SQLite path")
    args = parser.parse_args()

    data_dir = Path(args.data)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)

    tables = [
        "works", "passages", "concepts", "passage_concepts",
        "relations", "talk_patterns", "passage_patterns",
    ]
    for table in tables:
        records = load_jsonl(data_dir / f"{table}.jsonl")
        if not records:
            continue
        columns = list(records[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        cols = ", ".join(columns)
        sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
        # SQLite can only handle scalar values; convert lists/dicts to JSON strings
        for rec in records:
            row = []
            for col in columns:
                val = rec[col]
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                row.append(val)
            conn.execute(sql, row)

    conn.commit()
    conn.close()
    print(f"built {db_path}")


if __name__ == "__main__":
    run()
