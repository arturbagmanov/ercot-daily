"""Synthetic ERCOT responses shaped like the real API: field names as the
API returns them, hour-ending as '01:00' strings in some reports and integers
in others, wind and solar re-posted hourly, real-time in 15-minute intervals.
"""

from datetime import date

import pandas as pd
import pytest

from ercot_daily import fetch

DAY = date(2026, 8, 20)


def demand(he: int) -> float:
    return 50_000 + 1_500 * min(he, 17) - 800 * max(0, he - 17)


def solar(he: int) -> float:
    return max(0.0, 25_000 - 2_500 * abs(he - 14)) if 8 <= he <= 20 else 0.0


def load_frame(hours=range(1, 25)):
    return pd.DataFrame(
        {
            "operDay": [str(DAY)] * len(hours),
            "hourEnding": [f"{h:02d}:00" for h in hours],
            "coast": [1.0] * len(hours),
            "total": [demand(h) for h in hours],
            "DSTFlag": [False] * len(hours),
        }
    )


def renewable_frame(
    values, postings=("2026-08-21T01:55:00", "2026-08-21T02:55:00"), stale_offset=-999.0
):
    """Two postings; the later one carries the true values."""
    rows = []
    for i, posted in enumerate(postings):
        latest = i == len(postings) - 1
        for he in range(1, 25):
            gen = values(he) if latest else values(he) + stale_offset
            rows.append(
                {
                    "postedDatetime": posted,
                    "deliveryDate": str(DAY),
                    "hourEnding": he,
                    "genSystemWide": gen,
                    "HSLSystemWide": gen + 3_000,  # potential exceeds output
                    "STPPFSystemWide": gen + 500,
                    "DSTFlag": False,
                }
            )
    return pd.DataFrame(rows)


def dam_frame():
    return pd.DataFrame(
        {
            "deliveryDate": [str(DAY)] * 24,
            "hourEnding": [f"{h:02d}:00" for h in range(1, 25)],
            "settlementPoint": ["HB_HOUSTON"] * 24,
            "settlementPointPrice": [30.0 + h for h in range(1, 25)],
            "DSTFlag": [False] * 24,
        }
    )


def rtm_frame():
    rows = []
    for h in range(1, 25):
        for interval, price in enumerate([10.0, 20.0, 30.0, 40.0], start=1):
            rows.append(
                {
                    "deliveryDate": str(DAY),
                    "deliveryHour": h,
                    "deliveryInterval": interval,
                    "settlementPoint": "HB_HOUSTON",
                    "settlementPointType": "HU",
                    "settlementPointPrice": price + (1_000 if h == 21 else 0),
                    "DSTFlag": False,
                }
            )
    return pd.DataFrame(rows)


class FakeClient:
    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def get(self, endpoint, params):
        self.calls.append((endpoint, params))
        return self.frames[endpoint].copy()


@pytest.fixture
def client():
    return FakeClient(
        {
            fetch.LOAD: load_frame(),
            fetch.WIND: renewable_frame(lambda he: 8_000.0 + 300 * (he >= 19)),
            fetch.SOLAR: renewable_frame(solar),
            fetch.DAM: dam_frame(),
            fetch.RTM: rtm_frame(),
        }
    )
