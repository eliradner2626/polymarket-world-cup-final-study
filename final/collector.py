"""Record one top-of-book observation per Polymarket token per interval."""

import argparse
import asyncio
import json
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import websockets


HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "recommended_world_cup_final_markets.csv"
DB_PATH = HERE / "world_cup_final_orderbooks.sqlite3"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
BOOK_URL = "https://clob.polymarket.com/book"
HEARTBEAT_SECONDS = 10
RECONNECT_DELAY_SECONDS = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def database_size_bytes(path: Path) -> int:
    """Include WAL data, which is where recent SQLite writes normally reside."""
    return sum(candidate.stat().st_size for candidate in (path, Path(str(path) + "-wal")) if candidate.exists())


def exchange_time(value: Any) -> str | None:
    """Convert Polymarket's millisecond timestamp to ISO UTC when possible."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat(
            timespec="milliseconds"
        )
    except (TypeError, ValueError, OSError):
        return str(value)


@dataclass(frozen=True)
class TokenMeta:
    token_id: str
    market_id: str
    question: str
    outcome: str
    priority_tier: str
    analysis_category: str


@dataclass
class OrderBook:
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    initialized: bool = False
    latest_exchange_timestamp: str | None = None
    latest_hash: str | None = None

    def load_snapshot(self, message: dict[str, Any]) -> None:
        self.bids = self._levels(message.get("bids", []))
        self.asks = self._levels(message.get("asks", []))
        self.initialized = True
        self._metadata(message)

    @staticmethod
    def _levels(levels: list[dict[str, Any]]) -> dict[Decimal, Decimal]:
        result: dict[Decimal, Decimal] = {}
        for level in levels:
            try:
                price, size = Decimal(str(level["price"])), Decimal(str(level["size"]))
            except (KeyError, InvalidOperation):
                continue
            if size > 0:
                result[price] = size
        return result

    def apply_change(self, change: dict[str, Any], enclosing: dict[str, Any]) -> None:
        try:
            price = Decimal(str(change["price"]))
            size = Decimal(str(change["size"]))
        except (KeyError, InvalidOperation):
            return
        side = str(change.get("side", "")).upper()
        levels = self.bids if side in {"BUY", "BID"} else self.asks if side in {"SELL", "ASK"} else None
        if levels is None:
            return
        if size <= 0:
            levels.pop(price, None)
        else:
            levels[price] = size
        self._metadata(change)
        self._metadata(enclosing)

    def _metadata(self, message: dict[str, Any]) -> None:
        timestamp = message.get("timestamp")
        if timestamp is not None:
            self.latest_exchange_timestamp = exchange_time(timestamp)
        if message.get("hash") is not None:
            self.latest_hash = str(message["hash"])

    def top(self) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        bid = max(self.bids, default=None)
        ask = min(self.asks, default=None)
        return bid, self.bids.get(bid), ask, self.asks.get(ask)


def read_tokens(path: Path) -> dict[str, TokenMeta]:
    frame = pd.read_csv(path, dtype=str).fillna("")
    required = {"clob_token_ids", "market_id", "question", "priority_tier", "analysis_category"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
    tokens: dict[str, TokenMeta] = {}
    for row_number, row in frame.iterrows():
        try:
            ids = json.loads(row["clob_token_ids"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid clob_token_ids on CSV row {row_number + 2}: {exc}") from exc
        if not isinstance(ids, list) or len(ids) < 2:
            raise ValueError(f"CSV row {row_number + 2} needs YES and NO token IDs")
        for token_id, outcome in ((str(ids[0]), "YES"), (str(ids[1]), "NO")):
            candidate = TokenMeta(token_id, row["market_id"], row["question"], outcome, row["priority_tier"], row["analysis_category"])
            existing = tokens.get(token_id)
            if existing and existing != candidate:
                raise ValueError(f"Token {token_id} appears with conflicting market metadata")
            tokens[token_id] = candidate
    return tokens


def setup_db(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY,
            session_start_utc TEXT NOT NULL,
            session_end_utc TEXT,
            snapshot_interval_seconds REAL NOT NULL,
            number_of_markets INTEGER NOT NULL,
            number_of_tokens INTEGER NOT NULL,
            stop_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS top_of_book_snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            timestamp_utc TEXT NOT NULL,
            token_id TEXT NOT NULL,
            market_id TEXT NOT NULL,
            market_question TEXT NOT NULL,
            outcome TEXT NOT NULL,
            priority_tier TEXT,
            analysis_category TEXT,
            best_bid TEXT,
            best_bid_size TEXT,
            best_ask TEXT,
            best_ask_size TEXT,
            midpoint TEXT,
            spread TEXT,
            latest_exchange_timestamp TEXT,
            latest_book_hash TEXT,
            book_initialized INTEGER NOT NULL,
            top_of_book_changed INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_token_time
            ON top_of_book_snapshots(token_id, timestamp_utc);
    """)
    connection.commit()


def refresh_book(token_id: str) -> tuple[str, dict[str, Any]]:
    response = requests.get(BOOK_URL, params={"token_id": token_id}, timeout=20)
    response.raise_for_status()
    return token_id, response.json()


async def refresh_all_books(books: dict[str, OrderBook]) -> None:
    """REST refresh after a connection gap so incremental updates start from a known book."""
    results = await asyncio.gather(*(asyncio.to_thread(refresh_book, token) for token in books), return_exceptions=True)
    successes = 0
    for result in results:
        if isinstance(result, Exception):
            print(f"REST book refresh failed: {result}")
            continue
        token_id, payload = result
        books[token_id].load_snapshot(payload)
        successes += 1
    print(f"REST books loaded: {successes}/{len(books)}")


async def heartbeat(websocket: Any) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await websocket.send("PING")


def apply_message(payload: Any, books: dict[str, OrderBook]) -> None:
    messages = payload if isinstance(payload, list) else [payload]
    for message in messages:
        if not isinstance(message, dict):
            continue
        event = message.get("event_type")
        if event == "book":
            token = str(message.get("asset_id", ""))
            if token in books:
                books[token].load_snapshot(message)
        elif event == "price_change":
            changes = message.get("price_changes") or [message]
            for change in changes:
                token = str(change.get("asset_id") or message.get("asset_id") or "")
                if token in books:
                    books[token].apply_change(change, message)


def sample_rows(session_id: int, metadata: dict[str, TokenMeta], books: dict[str, OrderBook], prior: dict[str, tuple[Any, ...] | None]) -> list[tuple[Any, ...]]:
    now = utc_now()
    rows = []
    for token_id, meta in metadata.items():
        book = books[token_id]
        bid, bid_size, ask, ask_size = book.top()
        midpoint = (bid + ask) / 2 if bid is not None and ask is not None else None
        spread = ask - bid if bid is not None and ask is not None else None
        top = (bid, bid_size, ask, ask_size)
        changed = prior.get(token_id) is not None and top != prior[token_id]
        prior[token_id] = top
        rows.append((session_id, now, token_id, meta.market_id, meta.question, meta.outcome, meta.priority_tier,
                     meta.analysis_category, decimal_text(bid), decimal_text(bid_size), decimal_text(ask),
                     decimal_text(ask_size), decimal_text(midpoint), decimal_text(spread), book.latest_exchange_timestamp,
                     book.latest_hash, int(book.initialized), int(changed)))
    return rows


INSERT_SQL = """INSERT INTO top_of_book_snapshots (
    session_id, timestamp_utc, token_id, market_id, market_question, outcome, priority_tier, analysis_category,
    best_bid, best_bid_size, best_ask, best_ask_size, midpoint, spread, latest_exchange_timestamp,
    latest_book_hash, book_initialized, top_of_book_changed
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


async def collect(interval: float) -> None:
    metadata = read_tokens(CSV_PATH)
    market_count = len({item.market_id for item in metadata.values()})
    print(f"Loaded {market_count} markets and {len(metadata)} unique tokens from {CSV_PATH.name}.")
    connection = sqlite3.connect(DB_PATH)
    setup_db(connection)
    cursor = connection.execute("""INSERT INTO sessions (session_start_utc, snapshot_interval_seconds, number_of_markets, number_of_tokens)
                                 VALUES (?, ?, ?, ?)""", (utc_now(), interval, market_count, len(metadata)))
    session_id = cursor.lastrowid
    connection.commit()
    books = {token: OrderBook() for token in metadata}
    pending: deque[tuple[Any, ...]] = deque()
    prior: dict[str, tuple[Any, ...] | None] = {}
    started = time.monotonic()
    next_sample, next_status, last_commit = started, started + 30, started
    connected = False
    reconnects = 0
    stop_reason = "unknown"

    try:
        while True:
            # A REST baseline also covers a slow initial snapshot from the socket.
            await refresh_all_books(books)
            try:
                async with websockets.connect(WS_URL, ping_interval=None, close_timeout=5, max_size=None) as websocket:
                    await websocket.send(json.dumps({"type": "market", "assets_ids": list(metadata), "custom_feature_enabled": True}))
                    connected = True
                    beat = asyncio.create_task(heartbeat(websocket))
                    print("WebSocket connected.")
                    try:
                        while True:
                            now = time.monotonic()
                            timeout = max(0, min(next_sample, next_status) - now)
                            try:
                                raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                                if raw != "PONG":
                                    apply_message(json.loads(raw), books)
                            except asyncio.TimeoutError:
                                pass
                            now = time.monotonic()
                            if now >= next_sample:
                                pending.extend(sample_rows(session_id, metadata, books, prior))
                                next_sample += interval
                                while next_sample <= now:
                                    next_sample += interval
                            if pending and (now - last_commit >= 5 or len(pending) >= len(metadata) * 10):
                                connection.executemany(INSERT_SQL, pending)
                                connection.commit()
                                pending.clear()
                                last_commit = now
                            if now >= next_status:
                                rows = connection.execute("SELECT COUNT(*) FROM top_of_book_snapshots").fetchone()[0] + len(pending)
                                initialized = sum(book.initialized for book in books.values())
                                size_mb = database_size_bytes(DB_PATH) / 1_000_000
                                print(f"Status: runtime={now-started:.0f}s connected=yes rows={rows} initialized={initialized}/{len(books)} reconnects={reconnects} db={size_mb:.2f} MB")
                                next_status += 30
                    finally:
                        beat.cancel()
                        await asyncio.gather(beat, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                connected = False
                reconnects += 1
                print(f"WebSocket disconnected ({exc}); reconnecting in {RECONNECT_DELAY_SECONDS}s.")
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
    except KeyboardInterrupt:
        stop_reason = "Ctrl+C"
        print("Stopping collector...")
    finally:
        if pending:
            connection.executemany(INSERT_SQL, pending)
        connection.execute("UPDATE sessions SET session_end_utc = ?, stop_reason = ? WHERE session_id = ?", (utc_now(), stop_reason, session_id))
        connection.commit()
        connection.close()
        print("Database flushed and session closed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0, help="Snapshot interval in seconds (default: 1)")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    asyncio.run(collect(args.interval))


if __name__ == "__main__":
    main()
