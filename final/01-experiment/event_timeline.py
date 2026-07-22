"""Approximate event windows from public final-match reporting.

The time windows, not the listed minutes, are the unit used for inference because
public tickers do not provide a synchronized exchange clock.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class MatchEvent:
    """A public match-time anchor plus a deliberately broad UTC search window."""

    event_id: str
    minute: str
    label: str
    event_type: str
    start_utc: str
    end_utc: str
    note: str


# Kickoff is reported as 19:00 UTC. The long halftime show makes post-break UTC
# conversion imprecise, so later events intentionally receive wider windows.
EVENTS = (
    MatchEvent("kickoff", "0'", "Kickoff", "structural", "2026-07-19T18:58:00Z", "2026-07-19T19:04:00Z", "Opening whistle / market transition from pre-match."),
    MatchEvent("messi_chance", "6'", "Messi early chance", "ambiguous", "2026-07-19T19:03:00Z", "2026-07-19T19:13:00Z", "Important Argentina chance reported around the sixth minute."),
    MatchEvent("halftime", "45'", "Halftime", "structural", "2026-07-19T19:42:00Z", "2026-07-19T19:57:00Z", "Scoreless first half; reporting notes an extended halftime show."),
    MatchEvent("second_half", "46'", "Second-half kickoff", "structural", "2026-07-19T20:10:00Z", "2026-07-19T20:27:00Z", "Wide window accommodates the unusually long halftime interval."),
    MatchEvent("red_card", "90+2'", "Enzo Fernández red card", "definitive", "2026-07-19T20:57:00Z", "2026-07-19T21:14:00Z", "Argentina reduced to ten at the end of normal time."),
    MatchEvent("disallowed_goal", "96'", "Williams goal disallowed", "ambiguous", "2026-07-19T21:08:00Z", "2026-07-19T21:27:00Z", "Spain briefly appeared to score; the goal was disallowed."),
    MatchEvent("winning_goal", "106'", "Torres winning goal", "definitive", "2026-07-19T21:18:00Z", "2026-07-19T21:39:00Z", "Ferran Torres scored Spain's 1-0 extra-time winner."),
    MatchEvent("full_time", "120+'", "Full time", "structural", "2026-07-19T21:38:00Z", "2026-07-19T22:00:00Z", "Final whistle and transition to post-match settlement."),
)


SOURCES = {
    "fotmob": "https://www.fotmob.com/en/matches/spain-vs-3adef/5qgsu1iu#4653858:tab=ticker",
    "fifa": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/spain-argentina-final-report-highlights",
    "ap": "https://apnews.com/article/fccc26aa12d9226e63d06b601b770617",
    "el_pais": "https://elpais.com/deportes/mundial-futbol/2026-07-19/espana-argentina-en-directo-la-final-del-mundial-en-vivo.html",
    "al_jazeera": "https://www.aljazeera.com/sports/2026/7/20/key-takeaways-from-the-world-cup-2026-final-as-spain-beat-argentina",
}


def timeline_frame() -> pd.DataFrame:
    """Return event metadata with parsed UTC bounds for event detection."""
    frame = pd.DataFrame(asdict(event) for event in EVENTS)
    frame["start_utc"] = pd.to_datetime(frame["start_utc"], utc=True)
    frame["end_utc"] = pd.to_datetime(frame["end_utc"], utc=True)
    return frame
