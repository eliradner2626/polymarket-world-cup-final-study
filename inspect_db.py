"""Print a compact health and contents summary for the collector database."""

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "world_cup_final_orderbooks.sqlite3"


def database_size_bytes(path: Path) -> int:
    return sum(candidate.stat().st_size for candidate in (path, Path(str(path) + "-wal")) if candidate.exists())


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")
    connection = sqlite3.connect(DB_PATH)
    try:
        total, first, last = connection.execute("SELECT COUNT(*), MIN(timestamp_utc), MAX(timestamp_utc) FROM top_of_book_snapshots").fetchone()
        print(f"Database: {DB_PATH}")
        print(f"Size (database + WAL): {database_size_bytes(DB_PATH) / 1_000_000:.2f} MB")
        print(f"Total snapshot rows: {total}")
        print(f"First timestamp: {first or '-'}")
        print(f"Last timestamp: {last or '-'}")
        print("Rows per token:")
        for token_id, count in connection.execute("SELECT token_id, COUNT(*) FROM top_of_book_snapshots GROUP BY token_id ORDER BY token_id"):
            print(f"  {token_id}: {count}")
        print("Sessions:")
        for row in connection.execute("SELECT session_id, session_start_utc, session_end_utc, snapshot_interval_seconds, number_of_markets, number_of_tokens, stop_reason FROM sessions ORDER BY session_id"):
            print("  id=%s start=%s end=%s interval=%ss markets=%s tokens=%s stop=%s" % row)
        print("Integrity check: " + connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


if __name__ == "__main__":
    main()
