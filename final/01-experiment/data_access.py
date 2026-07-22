"""Read-only access helpers for the final's SQLite order-book data."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd


EXPERIMENT_DIR = Path(__file__).resolve().parent
FINAL_DIR = EXPERIMENT_DIR.parent
DEFAULT_DB_PATH = FINAL_DIR / "world_cup_final_orderbooks.sqlite3"

# Core markets used throughout the research notebook.  Outcome names intentionally
# stay as YES/NO because the generic "Team to Advance" question is not team-labelled.
CORE_MARKETS = {
    "spain_regulation": "2941974",
    "draw_regulation": "2941975",
    "argentina_regulation": "2941976",
    "team_to_advance": "2942083",
    "extra_time": "2942084",
    "over_0_5": "2942074",
    "both_teams_score": "2945083",
}


def connect_readonly(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the local SQLite file in immutable read-only mode."""
    path = db_path.resolve()
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)


def recording_bounds(connection: sqlite3.Connection) -> pd.Series:
    """Return the coverage and row count without reading snapshot rows."""
    return pd.read_sql_query(
        """SELECT MIN(timestamp_utc) AS first_timestamp_utc,
                  MAX(timestamp_utc) AS last_timestamp_utc,
                  COUNT(*) AS snapshot_rows
           FROM top_of_book_snapshots""",
        connection,
    ).iloc[0]


def market_catalog(connection: sqlite3.Connection) -> pd.DataFrame:
    """Load the distinct market metadata once for labeling analyses."""
    return pd.read_sql_query(
        """SELECT market_id, market_question, outcome, priority_tier, analysis_category,
                  MIN(token_id) AS token_id
           FROM top_of_book_snapshots
           GROUP BY market_id, market_question, outcome, priority_tier, analysis_category""",
        connection,
    )


def _in_clause(values: Iterable[str]) -> tuple[str, list[str]]:
    items = list(values)
    if not items:
        raise ValueError("At least one value is required")
    return ",".join("?" for _ in items), items


def load_market_panel(
    connection: sqlite3.Connection,
    market_ids: Iterable[str] = CORE_MARKETS.values(),
    start_utc: str | None = None,
    end_utc: str | None = None,
) -> pd.DataFrame:
    """Load only the selected markets and analysis columns, ordered by timestamp."""
    placeholders, params = _in_clause(market_ids)
    where = [f"market_id IN ({placeholders})"]
    if start_utc is not None:
        where.append("timestamp_utc >= ?")
        params.append(start_utc)
    if end_utc is not None:
        where.append("timestamp_utc <= ?")
        params.append(end_utc)
    query = f"""
        SELECT timestamp_utc, token_id, market_id, market_question, outcome,
               midpoint, spread, best_bid_size, best_ask_size, top_of_book_changed
        FROM top_of_book_snapshots
        WHERE {' AND '.join(where)}
        ORDER BY timestamp_utc, market_id, outcome
    """
    frame = pd.read_sql_query(query, connection, params=params)
    if frame.empty:
        return frame
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    numeric = ["midpoint", "spread", "best_bid_size", "best_ask_size"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame["top_size"] = frame["best_bid_size"].fillna(0) + frame["best_ask_size"].fillna(0)
    frame["market_key"] = frame["market_id"].map(
        {market_id: key for key, market_id in CORE_MARKETS.items()}
    )
    frame["series"] = frame["market_key"] + " — " + frame["outcome"]
    return frame


def load_event_window(
    connection: sqlite3.Connection,
    center: pd.Timestamp,
    before_seconds: int = 120,
    after_seconds: int = 180,
    market_ids: Iterable[str] = CORE_MARKETS.values(),
) -> pd.DataFrame:
    """SQL-filter a compact market panel around one detected timestamp."""
    start = center - pd.Timedelta(seconds=before_seconds)
    end = center + pd.Timedelta(seconds=after_seconds)
    return load_market_panel(connection, market_ids, start.isoformat(), end.isoformat())
