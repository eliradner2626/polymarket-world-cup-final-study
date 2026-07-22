"""Small, interpretable event-study and probability diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def event_response_table(
    midpoint: pd.DataFrame,
    top_size: pd.DataFrame,
    arrivals: pd.DataFrame,
    baseline_seconds: int = 30,
    horizon_seconds: int = 60,
) -> pd.DataFrame:
    """Measure peak response, persistence, reversal, and top-size change per event/series."""
    rows: list[dict[str, object]] = []
    for event in arrivals.itertuples(index=False):
        t0 = event.arrival_utc
        before = midpoint.loc[t0 - pd.Timedelta(seconds=baseline_seconds): t0 - pd.Timedelta(seconds=1)]
        after = midpoint.loc[t0: t0 + pd.Timedelta(seconds=horizon_seconds)]
        size_before = top_size.loc[t0 - pd.Timedelta(seconds=baseline_seconds): t0 - pd.Timedelta(seconds=1)]
        size_after = top_size.loc[t0: t0 + pd.Timedelta(seconds=horizon_seconds)]
        if before.empty or after.empty:
            continue
        baseline = before.mean()
        deviations = after.subtract(baseline, axis="columns")
        peak = deviations.abs().max()
        final = after.iloc[-1].subtract(baseline)
        for series in midpoint.columns:
            peak_value = peak[series]
            end_value = final[series]
            reversal = np.nan if not np.isfinite(peak_value) or peak_value == 0 else 1 - abs(end_value) / peak_value
            before_size = size_before[series].mean()
            after_size = size_after[series].mean()
            liquidity_pct = np.nan if before_size == 0 or not np.isfinite(before_size) else 100 * (after_size / before_size - 1)
            rows.append({
                "event_id": event.event_id,
                "label": event.label,
                "event_type": event.event_type,
                "arrival_utc": t0,
                "series": series,
                "peak_abs_midpoint_change": peak_value,
                "end_midpoint_change": end_value,
                "reversal_ratio": reversal,
                "top_size_change_pct": liquidity_pct,
            })
    return pd.DataFrame(rows)


def regulation_probability_diagnostic(panel: pd.DataFrame) -> pd.DataFrame:
    """Check whether the three regulation YES midpoints sum close to one."""
    subset = panel[(panel["outcome"] == "YES") & panel["market_key"].isin([
        "spain_regulation", "draw_regulation", "argentina_regulation"
    ])]
    wide = subset.pivot(index="timestamp_utc", columns="market_key", values="midpoint").sort_index()
    wide["sum_yes"] = wide.sum(axis=1, min_count=3)
    wide["sum_minus_one"] = wide["sum_yes"] - 1
    return wide


def lead_lag_table(
    midpoint: pd.DataFrame,
    source: str,
    target: str,
    center: pd.Timestamp,
    radius_seconds: int = 90,
    max_lag: int = 5,
) -> pd.DataFrame:
    """Correlate one-second changes; positive lag means source moves first."""
    changes = midpoint[[source, target]].diff().loc[
        center - pd.Timedelta(seconds=radius_seconds): center + pd.Timedelta(seconds=radius_seconds)
    ].dropna()
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            x, y = changes[source].to_numpy()[:-lag], changes[target].to_numpy()[lag:]
        elif lag < 0:
            x, y = changes[source].to_numpy()[-lag:], changes[target].to_numpy()[:lag]
        else:
            x, y = changes[source].to_numpy(), changes[target].to_numpy()
        valid = np.isfinite(x) & np.isfinite(y)
        correlation = np.corrcoef(x[valid], y[valid])[0, 1] if valid.sum() > 2 else np.nan
        rows.append({"lag_seconds": lag, "correlation": correlation, "n": int(valid.sum())})
    return pd.DataFrame(rows)
