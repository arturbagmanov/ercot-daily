"""The client is the part most likely to break in production: a token that
expires mid-run, a second page nobody noticed, a rate limit at 08:30. None of
that shows up in the fixture-driven tests, so it is exercised here against a
fake session.
"""

import time

import pytest
import requests

from ercot_daily import client as client_module
from ercot_daily.client import ErcotClient

CREDENTIALS = {
    "ERCOT_API_USERNAME": "user",
    "ERCOT_API_PASSWORD": "secret",
    "ERCOT_API_SUBSCRIPTION_KEY": "key-123",
}


REASONS = {200: "OK", 400: "Bad Request", 403: "Forbidden", 429: "Too Many Requests"}


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.url = "https://api.ercot.com/api/public-reports/endpoint"

    @property
    def ok(self):
        return self.status_code < 400

    @property
    def reason(self):
        return REASONS.get(self.status_code, "Error")

    def json(self):
        return self._payload


def page(rows, total_pages):
    return FakeResponse(
        {
            "fields": [{"name": "hourEnding"}, {"name": "total"}],
            "data": rows,
            "_meta": {"totalPages": total_pages},
        }
    )


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.tokens_issued = 0
        self.requests = []
        self.headers = {}

    def post(self, url, data=None, timeout=None):
        self.tokens_issued += 1
        return FakeResponse({"id_token": f"token-{self.tokens_issued}"})

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append({"url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Page pauses and the 429 backoff are real seconds. Skip them."""
    monkeypatch.setattr(time, "sleep", lambda _: None)


def test_a_missing_credential_is_caught_before_any_request(monkeypatch):
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY")
    with pytest.raises(RuntimeError, match="ERCOT_API_SUBSCRIPTION_KEY"):
        ErcotClient(session=FakeSession([]))


def test_both_credentials_are_sent_together():
    """One alone returns 401, which is the trap this guards against."""
    session = FakeSession([page([["01:00", 50_000.0]], 1)])
    ErcotClient(session=session).get("/endpoint", {"operatingDayFrom": "2026-08-20"})
    headers = session.requests[0]["headers"]
    assert headers["Authorization"] == "Bearer token-1"
    assert headers["Ocp-Apim-Subscription-Key"] == "key-123"


def test_every_page_is_fetched_and_concatenated():
    session = FakeSession(
        [
            page([["01:00", 1.0]], 3),
            page([["02:00", 2.0]], 3),
            page([["03:00", 3.0]], 3),
        ]
    )
    got = ErcotClient(session=session).get("/endpoint", {})
    assert list(got["hourEnding"]) == ["01:00", "02:00", "03:00"]
    assert [r["params"]["page"] for r in session.requests] == [1, 2, 3]


def test_a_rate_limit_is_retried_rather_than_raised():
    session = FakeSession(
        [FakeResponse(status_code=429), page([["01:00", 50_000.0]], 1)]
    )
    got = ErcotClient(session=session).get("/endpoint", {})
    assert len(got) == 1
    assert len(session.requests) == 2


def test_a_persistent_rate_limit_eventually_raises():
    session = FakeSession([FakeResponse(status_code=429)] * 6)
    with pytest.raises(requests.HTTPError):
        ErcotClient(session=session).get("/endpoint", {})


def test_the_token_is_reused_until_it_expires():
    session = FakeSession([page([], 1), page([], 1)])
    client = ErcotClient(session=session)
    client.get("/endpoint", {})
    client.get("/endpoint", {})
    assert session.tokens_issued == 1

    client._expires = 0.0  # as it would be an hour into a long backfill
    session.responses.append(page([], 1))
    client.get("/endpoint", {})
    assert session.tokens_issued == 2
    assert session.requests[-1]["headers"]["Authorization"] == "Bearer token-2"


def test_an_empty_response_still_carries_the_column_names():
    """fetch's strict column lookup runs on whatever comes back, including
    nothing, so an unpublished day must not arrive as a shapeless frame."""
    session = FakeSession([page([], 1)])
    got = ErcotClient(session=session).get("/endpoint", {})
    assert got.empty
    assert list(got.columns) == ["hourEnding", "total"]


def test_page_size_is_requested_explicitly():
    session = FakeSession([page([], 1)])
    ErcotClient(session=session).get("/endpoint", {"settlementPoint": "HB_HOUSTON"})
    params = session.requests[0]["params"]
    assert params["size"] == client_module.PAGE_SIZE
    assert params["settlementPoint"] == "HB_HOUSTON"


def test_a_refusal_carries_ercot_s_own_explanation():
    """A bare "403 Forbidden" does not say whether the product is wrong, the
    page size is over the limit or the quota is spent. ERCOT says which."""
    body = '{"statusCode": 403, "message": "Page size exceeds the maximum."}'
    session = FakeSession([FakeResponse(status_code=403, text=body)])
    with pytest.raises(requests.HTTPError, match="Page size exceeds the maximum"):
        ErcotClient(session=session).get("/np6-345-cd/act_sys_load_by_wzn", {})


def test_a_refused_token_request_names_the_status():
    session = FakeSession([])
    session.post = lambda *a, **k: FakeResponse(status_code=400, text="invalid_grant")
    with pytest.raises(requests.HTTPError, match="invalid_grant"):
        ErcotClient(session=session).get("/endpoint", {})


def test_the_requested_page_size_is_the_one_ercot_accepts():
    assert client_module.PAGE_SIZE == 1000


def test_the_client_identifies_itself():
    """Courtesy to a public agency's API, and a name for ERCOT to recognise
    if their bot protection ever has to be asked to let this client through.
    It is not what gets past Imperva; nothing in the headers is."""
    session = FakeSession([page([], 1)])
    ErcotClient(session=session)
    assert "ercot-daily" in session.headers["User-Agent"]
    assert "python-requests" not in session.headers["User-Agent"]
    assert session.headers["Accept"] == "application/json"
