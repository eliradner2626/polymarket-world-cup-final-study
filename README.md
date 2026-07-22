# World Cup final order-book collector

Records one top-of-book observation per YES/NO token each second from the markets in `recommended_world_cup_final_markets.csv`. It uses the public Polymarket market WebSocket, maintains local books from `book` and `price_change` messages, and saves only compact top-of-book samples to SQLite.

Install the dependencies once from the repository root:

```powershell
uv add pandas requests websockets
```

Start the collector around 10:00 a.m. PT (the default is one sample per second):

```powershell
uv run python final/collector.py
uv run python final/collector.py --interval 1
```

Stop it with Ctrl+C after the final. The program flushes pending rows, records the session end, and leaves prior sessions intact in `final/world_cup_final_orderbooks.sqlite3`.

Inspect the saved data:

```powershell
uv run python final/inspect_db.py
```

Keep the laptop plugged in, disable sleep, and leave the terminal running. The collector sends Polymarket's required `PING` heartbeat every 10 seconds and reconnects with REST book refreshes if the WebSocket drops.
