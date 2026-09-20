"""Minimal client for ERCOT's Public API.

Every request needs two credentials (one alone returns 401):
an OAuth id_token from ERCOT's Azure B2C endpoint, and the
Ocp-Apim-Subscription-Key header.
"""

from __future__ import annotations

import os
import time

import pandas as pd
import requests

TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
BASE_URL = "https://api.ercot.com/api/public-reports"

PAGE_SIZE = 5000
PAUSE_SECONDS = 2.1  # stay under the public API's per-minute request limit
TOKEN_LIFETIME = 50 * 60  # tokens last an hour; refresh early


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set.")
    return value


class ErcotClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.username = _env("ERCOT_API_USERNAME")
        self.password = _env("ERCOT_API_PASSWORD")
        self.subscription_key = _env("ERCOT_API_SUBSCRIPTION_KEY")
        self.session = session or requests.Session()
        self._token: str | None = None
        self._expires = 0.0

    def _headers(self) -> dict[str, str]:
        if self._token is None or time.monotonic() > self._expires:
            response = self.session.post(
                TOKEN_URL,
                data={
                    "username": self.username,
                    "password": self.password,
                    "grant_type": "password",
                    "scope": f"openid {CLIENT_ID} offline_access",
                    "client_id": CLIENT_ID,
                    "response_type": "id_token",
                },
                timeout=30,
            )
            response.raise_for_status()
            self._token = response.json()["id_token"]
            self._expires = time.monotonic() + TOKEN_LIFETIME
        return {
            "Authorization": f"Bearer {self._token}",
            "Ocp-Apim-Subscription-Key": self.subscription_key,
        }

    def get(self, endpoint: str, params: dict) -> pd.DataFrame:
        """Fetch every page of an endpoint into one DataFrame."""
        frames, page, retries = [], 1, 0
        while True:
            response = self.session.get(
                BASE_URL + endpoint,
                params={**params, "page": page, "size": PAGE_SIZE},
                headers=self._headers(),
                timeout=60,
            )
            if response.status_code == 429 and retries < 5:
                retries += 1
                time.sleep(15)
                continue
            response.raise_for_status()
            body = response.json()
            fields = [f["name"] for f in body["fields"]]
            frames.append(pd.DataFrame(body.get("data", []), columns=fields))
            if page >= body.get("_meta", {}).get("totalPages", 1):
                break
            page += 1
            time.sleep(PAUSE_SECONDS)
        return pd.concat(frames, ignore_index=True)
