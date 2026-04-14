"""Raw API calls to the Jolpica (Ergast successor) F1 API."""

import time
import requests

from config import API_BASE_URL, API_RATE_LIMIT_DELAY


def _get(endpoint: str, limit: int = 1000) -> list[dict]:
    """Fetch all pages from an API endpoint, respecting rate limits."""
    results = []
    offset = 0
    while True:
        url = f"{API_BASE_URL}/{endpoint}.json?limit={limit}&offset={offset}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()["MRData"]
        total = int(data["total"])

        # The actual data is nested under a key like "RaceTable", "StandingsTable", etc.
        table_key = [k for k in data if k.endswith("Table")][0]
        table = data[table_key]

        # The list is under a key like "Races", "StandingsLists", etc.
        list_key = [k for k in table if isinstance(table[k], list)][0]
        items = table[list_key]
        results.extend(items)

        offset += limit
        if offset >= total:
            break
        time.sleep(API_RATE_LIMIT_DELAY)

    return results


def fetch_seasons() -> list[dict]:
    return _get("seasons", limit=100)


def fetch_races(year: int) -> list[dict]:
    return _get(f"{year}", limit=30)


def fetch_results(year: int) -> list[dict]:
    return _get(f"{year}/results", limit=1000)


def fetch_qualifying(year: int) -> list[dict]:
    return _get(f"{year}/qualifying", limit=1000)


def fetch_sprint_results(year: int) -> list[dict]:
    return _get(f"{year}/sprint", limit=1000)


def fetch_pit_stops(year: int, round_num: int) -> list[dict]:
    return _get(f"{year}/{round_num}/pitstops", limit=100)


def fetch_driver_standings_for_round(year: int, round_num: int) -> list[dict]:
    """Fetch driver standings after a specific round."""
    return _get(f"{year}/{round_num}/driverStandings", limit=100)


def fetch_constructor_standings_for_round(year: int, round_num: int) -> list[dict]:
    """Fetch constructor standings after a specific round."""
    return _get(f"{year}/{round_num}/constructorStandings", limit=100)
