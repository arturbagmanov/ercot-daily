import pandas as pd
import pytest

from ercot_daily import fetch

from .conftest import DAY, FakeClient, solar


def test_hour_ending_accepts_every_format_ercot_uses():
    parsed = fetch.hour_ending(pd.Series(["01:00", "24:00", 7, "9"]))
    assert parsed.tolist() == [1, 24, 7, 9]


def test_renewables_use_actual_output_not_potential(client):
    """HSL is uncurtailed potential. Subtracting it would understate net load."""
    got = fetch.fetch_solar(client, DAY).set_index("hour_ending")["solar_mw"]
    assert got[14] == solar(14)
    assert got[14] != solar(14) + 3_000


def test_latest_posting_wins(client):
    """Stale postings carry -999 offsets; none may survive."""
    got = fetch.fetch_wind(client, DAY)
    assert len(got) == 24
    assert (got["wind_mw"] >= 8_000).all()


def test_missing_gen_column_fails_loudly(client):
    client.frames[fetch.WIND] = client.frames[fetch.WIND].drop(columns="genSystemWide")
    with pytest.raises(KeyError, match="Observed columns"):
        fetch.fetch_wind(client, DAY)


def test_real_time_quarter_hours_collapse_to_one_row_per_hour(client):
    got = fetch.fetch_rtm(client, DAY)
    assert len(got) == 24
    assert got.set_index("hour_ending").at[1, "rtm_price"] == 25.0


def test_unpublished_day_is_a_lookup_error_not_a_crash():
    empty = FakeClient({fetch.LOAD: pd.DataFrame(columns=["hourEnding", "total"])})
    with pytest.raises(LookupError):
        fetch.fetch_load(empty, DAY)
