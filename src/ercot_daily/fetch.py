"""One function per series. Each returns a tidy hourly frame keyed on
(hour_ending, dst) for a single operating day in Central Prevailing Time.

`dst` separates the repeated hour on the autumn fall-back day.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from . import HUB

LOAD = "/np6-345-cd/act_sys_load_by_wzn"
WIND = "/np4-732-cd/wpp_hrly_avrg_actl_fcast"
SOLAR = "/np4-737-cd/spp_hrly_avrg_actl_fcast"
DAM = "/np4-190-cd/dam_stlmnt_pnt_prices"
RTM = "/np6-905-cd/spp_node_zone_hub"

KEY = ["hour_ending", "dst"]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def col(df: pd.DataFrame, wanted: str) -> str:
    """Find a column by normalised name. Fail loudly with the full header."""
    matches = [c for c in df.columns if _norm(c) == _norm(wanted)]
    if len(matches) != 1:
        raise KeyError(
            f"Expected exactly one column matching {wanted!r}, found {matches}. "
            f"Observed columns: {list(df.columns)}"
        )
    return matches[0]


def hour_ending(values: pd.Series) -> pd.Series:
    """'01:00', '1', 1 and '24:00' all become integers 1..24."""
    return values.astype(str).str.split(":").str[0].astype(int)


def _dst(df: pd.DataFrame) -> pd.Series:
    flags = [c for c in df.columns if _norm(c) == "dstflag"]
    if not flags:
        return pd.Series(False, index=df.index)
    return df[flags[0]].astype(str).str.upper().isin(["Y", "TRUE", "1"])


def _empty(df: pd.DataFrame, name: str, day: date) -> None:
    if df.empty:
        raise LookupError(f"{name}: no rows published for {day} yet.")


def fetch_load(client, day: date) -> pd.DataFrame:
    df = client.get(
        LOAD, {"operatingDayFrom": str(day), "operatingDayTo": str(day)}
    )
    _empty(df, "load", day)
    return pd.DataFrame(
        {
            "hour_ending": hour_ending(df[col(df, "hourEnding")]),
            "dst": _dst(df),
            "demand_mw": df[col(df, "total")].astype(float),
        }
    )


def _renewable(client, endpoint: str, day: date, name: str) -> pd.DataFrame:
    """Wind and solar reports are re-posted hourly, each carrying a rolling
    48-hour window of actuals. Keep the latest posting per hour.

    GEN is what the fleet produced. HSL is what it *could* have produced
    (uncurtailed potential) and is the wrong input for net load.
    """
    df = client.get(
        endpoint,
        {
            "deliveryDateFrom": str(day),
            "deliveryDateTo": str(day),
            "postedDatetimeFrom": f"{day}T00:00:00",
        },
    )
    _empty(df, name, day)
    tidy = pd.DataFrame(
        {
            "hour_ending": hour_ending(df[col(df, "hourEnding")]),
            "dst": _dst(df),
            "posted": pd.to_datetime(df[col(df, "postedDatetime")]),
            f"{name}_mw": pd.to_numeric(df[col(df, "genSystemWide")], errors="coerce"),
        }
    ).dropna(subset=[f"{name}_mw"])
    return (
        tidy.sort_values("posted")
        .groupby(KEY, as_index=False)
        .last()
        .drop(columns="posted")
    )


def fetch_wind(client, day: date) -> pd.DataFrame:
    return _renewable(client, WIND, day, "wind")


def fetch_solar(client, day: date) -> pd.DataFrame:
    return _renewable(client, SOLAR, day, "solar")


def _price_params(day: date, hub: str) -> dict:
    return {
        "deliveryDateFrom": str(day),
        "deliveryDateTo": str(day),
        "settlementPoint": hub,
    }


def fetch_dam(client, day: date, hub: str = HUB) -> pd.DataFrame:
    df = client.get(DAM, _price_params(day, hub))
    _empty(df, "day-ahead price", day)
    return pd.DataFrame(
        {
            "hour_ending": hour_ending(df[col(df, "hourEnding")]),
            "dst": _dst(df),
            "dam_price": df[col(df, "settlementPointPrice")].astype(float),
        }
    )


def fetch_rtm(client, day: date, hub: str = HUB) -> pd.DataFrame:
    """Real-time settles every 15 minutes; average the four intervals."""
    df = client.get(RTM, _price_params(day, hub))
    _empty(df, "real-time price", day)
    tidy = pd.DataFrame(
        {
            "hour_ending": hour_ending(df[col(df, "deliveryHour")]),
            "dst": _dst(df),
            "rtm_price": df[col(df, "settlementPointPrice")].astype(float),
        }
    )
    return tidy.groupby(KEY, as_index=False)["rtm_price"].mean()
