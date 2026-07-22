"""Tiny transparent regressions; deliberately avoids a high-dimensional VAR."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ols_summary(target: pd.Series, predictors: pd.DataFrame) -> pd.DataFrame:
    """Fit OLS with classical standard errors and return coefficient diagnostics."""
    data = pd.concat([target.rename("target"), predictors], axis=1).dropna()
    y = data.pop("target").to_numpy(dtype=float)
    x = data.to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    names = ["intercept", *data.columns]
    beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    residuals = y - x @ beta
    dof = len(y) - x.shape[1]
    sigma2 = (residuals @ residuals) / dof if dof > 0 else np.nan
    covariance = sigma2 * np.linalg.pinv(x.T @ x)
    se = np.sqrt(np.diag(covariance))
    r_squared = 1 - (residuals @ residuals) / ((y - y.mean()) @ (y - y.mean()))
    return pd.DataFrame({
        "term": names,
        "coefficient": beta,
        "std_error": se,
        "t_stat": beta / se,
        "n": len(y),
        "r_squared": r_squared,
    })


def lagged_pair_regression(
    midpoint: pd.DataFrame,
    source: str,
    target: str,
    arrivals: pd.DataFrame,
    radius_seconds: int = 90,
) -> pd.DataFrame:
    """Regress target's one-second changes on contemporaneous and lagged source moves."""
    selected = []
    changes = midpoint[[source, target]].diff()
    for event_time in arrivals["arrival_utc"].drop_duplicates():
        selected.append(changes.loc[event_time - pd.Timedelta(seconds=radius_seconds): event_time + pd.Timedelta(seconds=radius_seconds)])
    data = pd.concat(selected).sort_index()
    predictors = pd.DataFrame({
        "source_change_t": data[source],
        "source_change_t_minus_1": data[source].shift(1),
        "target_change_t_minus_1": data[target].shift(1),
    })
    return ols_summary(data[target], predictors)
