from datetime import date

import pandas as pd
import pytest

from ercot_daily import build, cli, fetch, readme

from .conftest import DAY, demand, load_frame, solar


def assemble(client):
    return build.assemble(
        DAY,
        fetch.fetch_load(client, DAY),
        fetch.fetch_wind(client, DAY),
        fetch.fetch_solar(client, DAY),
        fetch.fetch_dam(client, DAY),
        fetch.fetch_rtm(client, DAY),
    )


def test_net_load_is_demand_minus_wind_minus_solar(client):
    day = assemble(client).set_index("hour_ending")
    assert day.at[14, "net_load_mw"] == demand(14) - 8_000 - solar(14)


def test_net_load_peaks_after_demand(client):
    s = build.summarize(assemble(client))
    assert s["demand_peak_he"] == 17
    assert s["net_peak_he"] > s["demand_peak_he"]


def test_missing_hour_is_incomplete_not_silently_dropped(client):
    client.frames[fetch.LOAD] = load_frame(hours=range(1, 24))
    with pytest.raises(build.IncompleteDay):
        assemble(client)


def test_fall_back_day_keeps_both_copies_of_the_repeated_hour(client):
    frame = load_frame()
    extra = frame[frame["hourEnding"] == "02:00"].assign(DSTFlag=True)
    frame = pd.concat([frame, extra], ignore_index=True)
    got = fetch.fetch_load(type(client)({fetch.LOAD: frame}), DAY)
    assert len(got) == 25


def test_spread_finds_the_real_time_spike(client):
    s = build.summarize(assemble(client))
    assert s["spread_he"] == 21
    assert s["spread"] > 900


def test_rerunning_a_day_replaces_it(client, tmp_path):
    day = assemble(client)
    empty = build.load_history(tmp_path / "daily.csv")
    history = build.append(build.append(empty, day), day)
    assert len(history) == 24


def test_targets_skip_days_already_stored(client):
    history = assemble(client)
    got = cli.targets(history, today=date(2026, 8, 22))
    assert got == [date(2026, 8, 21)]


def test_readme_update_is_idempotent(client):
    s = build.summarize(assemble(client))
    text = f"intro\n{readme.START}\nold\n{readme.END}\noutro\n"
    once = readme.replace_block(text, readme.recap(s, "HB_HOUSTON"))
    twice = readme.replace_block(once, readme.recap(s, "HB_HOUSTON"))
    assert once == twice
    assert once.startswith("intro") and once.endswith("outro\n")
    assert "HE21" in once


def test_dollar_signs_are_escaped_so_github_does_not_render_math(client):
    """GitHub treats text between two $ signs as LaTeX."""
    block = readme.recap(build.summarize(assemble(client)), "HB_HOUSTON")
    prices = [line for line in block.splitlines() if "MWh" in line][0]
    assert prices.count("$") == prices.count("\\$")
    assert "\\\\$" not in prices


def test_evening_ramp_spans_the_hours_the_constants_name(client):
    day = assemble(client).drop_duplicates("hour_ending").set_index("hour_ending")
    s = build.summarize(assemble(client))
    expected = (
        day.at[build.RAMP_TO_HE, "net_load_mw"]
        - day.at[build.RAMP_FROM_HE, "net_load_mw"]
    )
    assert s["evening_ramp_mw"] == expected


def test_recap_names_the_same_hours_it_measured(client):
    """The ramp sentence used to hardcode HE18-HE22 beside a constant that
    could be changed independently. Now one cannot drift from the other."""
    block = readme.recap(build.summarize(assemble(client)), "HB_HOUSTON")
    line = next(ln for ln in block.splitlines() if "Evening ramp" in ln)
    assert f"HE{build.RAMP_FROM_HE:02d}" in line
    assert f"HE{build.RAMP_TO_HE:02d}" in line


def test_a_history_that_stopped_updating_fails_the_run(client):
    """A quiet morning and a broken pipeline must not look the same."""
    history = assemble(client)  # operating day 2026-08-20
    assert cli.stale(history, date(2026, 8, 21)) is None
    assert cli.stale(history, date(2026, 8, 23)) is None
    assert "days behind" in cli.stale(history, date(2026, 8, 30))


def test_a_repository_with_no_history_is_stale(tmp_path):
    empty = build.load_history(tmp_path / "daily.csv")
    assert cli.stale(empty, date(2026, 8, 20)) is not None


def test_history_is_written_with_one_line_ending(client, tmp_path):
    """A Windows run and an Ubuntu run must produce identical bytes, or every
    daily commit rewrites the whole file instead of adding a day to it."""
    path = tmp_path / "data" / "daily.csv"
    build.write_history(assemble(client), path)
    assert b"\r\n" not in path.read_bytes()
    assert path.read_bytes().endswith(b"\n")


def test_recap_is_written_with_one_line_ending(client, tmp_path):
    path = tmp_path / "README.md"
    path.write_text(
        f"intro\n{readme.START}\nold\n{readme.END}\noutro\n",
        encoding="utf-8",
        newline="\n",
    )
    readme.update(path, readme.recap(build.summarize(assemble(client)), "HB_HOUSTON"))
    assert b"\r\n" not in path.read_bytes()


def test_derived_columns_carry_no_floating_point_tail(client):
    """48870.729999999996 and 48870.73 are the same double rendered two ways.
    Different pandas builds pick differently, and git calls it a changed row."""
    day = assemble(client)
    for value in day["net_load_mw"]:
        assert repr(float(value)) == repr(round(float(value), 2))
    for value in day["rtm_price"]:
        assert repr(float(value)) == repr(round(float(value), 4))


def test_writing_normalises_a_history_that_drifted(client, tmp_path):
    """The writer guarantees the file's precision, not only the builder, so
    rows written by an older version get cleaned up instead of persisting."""
    day = assemble(client).reset_index(drop=True)
    day.loc[0, "net_load_mw"] = 44428.78999999999
    day.loc[0, "rtm_price"] = 34.442499999999995
    path = tmp_path / "daily.csv"
    build.write_history(day, path)
    text = path.read_text()
    assert "44428.79" in text and "34.4425" in text
    assert "44428.78999999999" not in text
    assert "34.442499999999995" not in text
