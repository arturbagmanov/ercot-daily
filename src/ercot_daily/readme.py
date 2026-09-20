"""Rewrite the block between the recap markers in README.md."""

from __future__ import annotations

from pathlib import Path

from .build import RAMP_FROM_HE, RAMP_TO_HE

START, END = "<!-- RECAP:START -->", "<!-- RECAP:END -->"


def recap(s: dict, hub: str) -> str:
    ramp = s["evening_ramp_mw"] / 1000
    direction = "rose" if ramp >= 0 else "fell"
    sign = "+" if s["spread"] >= 0 else "−"
    picture = (
        "<picture>\n"
        '  <source media="(prefers-color-scheme: dark)" '
        'srcset="reports/latest-dark.png">\n'
        '  <img alt="Yesterday\'s ERCOT demand, net load and Houston hub prices" '
        'src="reports/latest-light.png">\n'
        "</picture>"
    )
    peaks = (
        f"- Demand peaked at **HE{s['demand_peak_he']:02d}** at "
        f"{s['demand_peak_mw'] / 1000:.1f} GW; net load peaked at "
        f"**HE{s['net_peak_he']:02d}** at {s['net_peak_mw'] / 1000:.1f} GW."
    )
    ramp_line = (
        f"- Evening ramp: net load {direction} **{abs(ramp):.1f} GW** "
        f"from HE{RAMP_FROM_HE:02d} to HE{RAMP_TO_HE:02d}."
    )
    prices = (
        f"- {hub}: day-ahead averaged \\${s['dam_avg']:,.2f}/MWh, real-time "
        f"\\${s['rtm_avg']:,.2f}/MWh. Widest real-time minus day-ahead spread: "
        f"**{sign}\\${abs(s['spread']):,.2f}** at HE{s['spread_he']:02d}."
    )
    title = f"**Operating day {s['day']}** (hours ending, Central Prevailing Time)"
    return "\n".join([title, "", picture, "", peaks, ramp_line, prices])


def replace_block(text: str, block: str) -> str:
    if START not in text or END not in text:
        raise ValueError("README is missing the recap markers.")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{block}\n{END}{tail}"


def update(path: Path, block: str) -> None:
    path.write_text(
        replace_block(path.read_text(encoding="utf-8"), block),
        encoding="utf-8",
        newline="\n",
    )
