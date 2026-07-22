# World Cup final event study

The modules are intentionally small and importable from the research notebook:

- `data_access.py` uses an immutable read-only SQLite connection and SQL filters.
- `event_timeline.py` stores public minute-level anchors as broad UTC windows.
- `event_detection.py` picks the largest synchronized midpoint movement within each window.
- `metrics.py` computes response, liquidity, probability, and lead-lag diagnostics.
- `models.py` provides a compact OLS lag regression rather than a large VAR.
- `plots.py` keeps chart logic out of the notebook.

Run the notebook from the repository root with the project's Python/Jupyter kernel. The analysis never writes to the SQLite database.
