"""Infer likely information-arrival seconds from synchronized market movement."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_feature_panel(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pivot midpoint and top-size data into one-second series by token label."""
    midpoint = panel.pivot(index="timestamp_utc", columns="series", values="midpoint").sort_index()
    size = panel.pivot(index="timestamp_utc", columns="series", values="top_size").sort_index()
    return midpoint, size


def synchronized_score(
    midpoint: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    baseline_seconds: int = 180,
) -> pd.DataFrame:
    """Score each second by robust, cross-market absolute midpoint movement."""
    changes = midpoint.diff()
    baseline = changes.loc[(changes.index >= start - pd.Timedelta(seconds=baseline_seconds)) & (changes.index < start)]
    scale = baseline.abs().quantile(0.90).replace(0, np.nan).fillna(0.005)
    window = changes.loc[(changes.index >= start) & (changes.index <= end)]
    normalized = window.abs().divide(scale, axis="columns").clip(upper=10)
    result = pd.DataFrame({
        "synchronized_score": normalized.sum(axis=1),
        "markets_moving": (window.abs() > 0).sum(axis=1),
        "mean_abs_change": window.abs().mean(axis=1),
    })
    return result.sort_values(["synchronized_score", "markets_moving"], ascending=False)


def detect_event_arrivals(midpoint: pd.DataFrame, timeline: pd.DataFrame) -> pd.DataFrame:
    """Choose the strongest synchronized-movement second inside each event window."""
    rows: list[dict[str, object]] = []
    for event in timeline.itertuples(index=False):
        scores = synchronized_score(midpoint, event.start_utc, event.end_utc)
        if scores.empty:
            continue
        candidate_time, candidate = next(iter(scores.iterrows()))
        rows.append({
            "event_id": event.event_id,
            "label": event.label,
            "event_type": event.event_type,
            "minute": event.minute,
            "window_start_utc": event.start_utc,
            "window_end_utc": event.end_utc,
            "arrival_utc": candidate_time,
            **candidate.to_dict(),
        })
    return pd.DataFrame(rows).sort_values("arrival_utc").reset_index(drop=True)


def event_window(midpoint: pd.DataFrame, arrival: pd.Timestamp, seconds_before: int = 60, seconds_after: int = 120) -> pd.DataFrame:
    """Return a relative-time midpoint frame around one inferred arrival second."""
    window = midpoint.loc[arrival - pd.Timedelta(seconds=seconds_before): arrival + pd.Timedelta(seconds=seconds_after)].copy()
    window.index = (window.index - arrival).total_seconds().astype(int)
    window.index.name = "seconds_from_arrival"
    return window
