"""Join one operating day, derive net load, keep the running history."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .fetch import KEY

COLUMNS = [
    "operating_day",
    "hour_ending",
    "dst",
    "demand_mw",
    "wind_mw",
    "solar_mw",
    "net_load_mw",
    "dam_price",
    "rtm_price",
]

# Evening ramp: net load at HE21 minus HE17.
#
# net-load-forecasting-ercot reports "demand peaks at hour 17, net load at
# hour 21". Those labels come from EIA-930, whose timestamp column is
# "UTC Time at End of Hour", so they are hour-ENDING labels despite the
# panel's docstring calling them hour-beginning. Hour 17 there is HE17 here.
RAMP_FROM_HE, RAMP_TO_HE = 17, 21


class IncompleteDay(Exception):
    """A series is missing hours; try again after ERCOT finishes posting."""


def assemble(day: date, load, wind, solar, dam, rtm) -> pd.DataFrame:
    df = load
    for part in (wind, solar, dam, rtm):
        df = df.merge(part, on=KEY, how="outer")
    missing = df.columns[df.isna().any()].tolist()
    if missing or not 23 <= len(df) <= 25:
        raise IncompleteDay(f"{day}: {len(df)} hours, gaps in {missing}")
    # Rounded to the precision of its own inputs. Left unrounded the
    # subtraction leaves tails like 48870.729999999996, which different pandas
    # builds render differently, so git reports a changed row on a day whose
    # numbers did not change.
    df["net_load_mw"] = (df["demand_mw"] - df["wind_mw"] - df["solar_mw"]).round(2)
    df["operating_day"] = str(day)
    return df.sort_values(["hour_ending", "dst"], ascending=[True, False])[COLUMNS]


def write_history(history: pd.DataFrame, path: Path) -> None:
    """Write the history with LF endings whatever the platform.

    A run on Windows and a run on the Ubuntu runner have to produce identical
    bytes. Otherwise every commit rewrites the whole file instead of adding a
    day to it, and the commit history stops being readable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(path, index=False, lineterminator="\n")


def load_history(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype={"operating_day": str})
    return pd.DataFrame(columns=COLUMNS)


def append(history: pd.DataFrame, day_df: pd.DataFrame) -> pd.DataFrame:
    """Add a day, replacing it if already present, so reruns are harmless."""
    day = day_df["operating_day"].iloc[0]
    kept = history[history["operating_day"] != day]
    parts = [p for p in (kept, day_df) if not p.empty]
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["operating_day", "hour_ending"], kind="stable")


def summarize(day_df: pd.DataFrame) -> dict:
    d = day_df.reset_index(drop=True)
    spread = d["rtm_price"] - d["dam_price"]
    by_he = d.drop_duplicates("hour_ending").set_index("hour_ending")["net_load_mw"]
    peak_d, peak_n, peak_s = (
        d["demand_mw"].idxmax(),
        d["net_load_mw"].idxmax(),
        spread.abs().idxmax(),
    )
    return {
        "day": d["operating_day"].iloc[0],
        "demand_peak_he": int(d.at[peak_d, "hour_ending"]),
        "demand_peak_mw": float(d.at[peak_d, "demand_mw"]),
        "net_peak_he": int(d.at[peak_n, "hour_ending"]),
        "net_peak_mw": float(d.at[peak_n, "net_load_mw"]),
        "evening_ramp_mw": float(by_he[RAMP_TO_HE] - by_he[RAMP_FROM_HE]),
        "dam_avg": float(d["dam_price"].mean()),
        "rtm_avg": float(d["rtm_price"].mean()),
        "spread_he": int(d.at[peak_s, "hour_ending"]),
        "spread": float(spread[peak_s]),
    }
