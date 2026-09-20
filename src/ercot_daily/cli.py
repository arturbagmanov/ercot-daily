"""python -m ercot_daily.cli run [--date YYYY-MM-DD]

Without --date, fills whichever of the last two operating days are missing
from data/daily.csv. Two days is the limit: the wind and solar reports only
carry 48 hours of actuals, so an older gap cannot be recovered from them.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import HUB, build, chart, fetch, readme

ROOT = Path.cwd()
HISTORY = ROOT / "data" / "daily.csv"
LOOKBACK_DAYS = 2
STALE_AFTER_DAYS = 3


def market_today() -> date:
    return datetime.now(ZoneInfo("America/Chicago")).date()


def targets(history, today: date) -> list[date]:
    have = set(history["operating_day"].astype(str))
    days = [today - timedelta(days=n) for n in range(LOOKBACK_DAYS, 0, -1)]
    return [d for d in days if str(d) not in have]


def stale(history, today: date) -> str | None:
    """Why the history has fallen behind, or None if it is current.

    Without this a broken morning is indistinguishable from a quiet one: the
    run fetches nothing, exits 0, commits nothing, and the badge stays green
    while the recap in the README silently ages. Returning non-zero after
    STALE_AFTER_DAYS is what makes the badge mean something.
    """
    if not len(history):
        return "no operating days recorded yet"
    newest = str(history["operating_day"].max())
    age = (today - date.fromisoformat(newest)).days
    if age > STALE_AFTER_DAYS:
        return f"newest operating day is {newest}, {age} days behind"
    return None


def run(days: list[date]) -> int:
    from .client import ErcotClient

    history = build.load_history(HISTORY)
    client = ErcotClient()
    added = 0
    for day in days:
        try:
            day_df = build.assemble(
                day,
                fetch.fetch_load(client, day),
                fetch.fetch_wind(client, day),
                fetch.fetch_solar(client, day),
                fetch.fetch_dam(client, day),
                fetch.fetch_rtm(client, day),
            )
        except (LookupError, build.IncompleteDay) as exc:
            # Not published yet. The later scheduled run will try again.
            print(f"skip {day}: {exc}")
            continue
        history = build.append(history, day_df)
        added += 1
        print(f"added {day}")

    if added:
        build.write_history(history, HISTORY)
        latest = history["operating_day"].max()
        day_df = history[history["operating_day"] == latest]
        summary = build.summarize(day_df)
        chart.draw(day_df, summary, ROOT / "reports", HUB)
        readme.update(ROOT / "README.md", readme.recap(summary, HUB))
    else:
        print("nothing new")

    behind = stale(history, market_today())
    if behind:
        print(f"stale: {behind}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ercot_daily")
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="fetch missing days and refresh the recap")
    run_cmd.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args(argv)

    if args.date:
        days = [args.date]
    else:
        today = market_today()
        days = targets(build.load_history(HISTORY), today)
    if not days:
        print("up to date")
        return 0
    return run(days)


if __name__ == "__main__":
    sys.exit(main())
