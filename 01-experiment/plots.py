"""Matplotlib helpers for the notebook's concise figures."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd


def plot_event_midpoints(window: pd.DataFrame, title: str, series: list[str] | None = None):
    """Plot selected midpoint paths relative to the inferred arrival second."""
    chosen = window if series is None else window[[name for name in series if name in window]]
    fig, ax = plt.subplots(figsize=(12, 5))
    for name in chosen.columns:
        ax.plot(chosen.index, chosen[name], linewidth=1.3, label=name)
    ax.axvline(0, color="black", linestyle="--", linewidth=1, label="inferred arrival")
    ax.set(title=title, xlabel="Seconds from inferred arrival", ylabel="Midpoint")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8)
    fig.tight_layout()
    return fig, ax


def plot_probability_diagnostic(diagnostic: pd.DataFrame, arrivals: pd.DataFrame):
    """Plot regulation YES sum minus one and mark inferred information arrivals."""
    fig, ax = plt.subplots(figsize=(13, 4))
    ax.plot(diagnostic.index, diagnostic["sum_minus_one"], color="#7a3e9d", linewidth=0.8)
    ax.axhline(0, color="black", linewidth=1)
    for event in arrivals.itertuples(index=False):
        ax.axvline(event.arrival_utc, color="gray", alpha=0.35, linewidth=0.8)
    ax.set(title="Regulation YES probabilities: Spain + draw + Argentina − 1", xlabel="UTC time", ylabel="Probability-sum residual")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig, ax


def plot_lead_lag(lead_lag: pd.DataFrame, title: str):
    """Plot lag correlations, where positive lag means the source moved first."""
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.bar(lead_lag["lag_seconds"], lead_lag["correlation"], color="#287d8e")
    ax.axvline(0, color="black", linewidth=1)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set(title=title, xlabel="Lag seconds (positive = source leads)", ylabel="Correlation of midpoint changes")
    fig.tight_layout()
    return fig, ax
