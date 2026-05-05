"""Track-outline data via the bacinger/f1-circuits GeoJSON repo (MIT licensed).

The repo provides a clean LineString per circuit with all turn coordinates
plus metadata (length, opening year, location). Files are named by ISO
country code + opening year, e.g. ``au-1953.geojson`` for Albert Park.

Network access is needed only the first time a given circuit is visited;
``st.cache_data`` keeps subsequent requests in memory.
"""

from __future__ import annotations

import math

import requests
import streamlit as st

# Map our circuit_id -> bacinger filename (without extension). Covers all
# circuits used between roughly 2010 and 2026 plus a handful of historic
# venues. Anything not in this table falls back to lat/lng nearest-neighbor
# discovery via _bacinger_index().
CIRCUIT_FILE_MAP: dict[str, str] = {
    "albert_park": "au-1953",
    "americas": "us-2012",
    "bahrain": "bh-2002",
    "baku": "az-2016",
    "BAK": "az-2016",
    "catalunya": "es-1991",
    "hungaroring": "hu-1986",
    "imola": "it-1953",
    "interlagos": "br-1977",
    "istanbul": "tr-2005",
    "jeddah": "sa-2021",
    "losail": "qa-2004",
    "madrid": "es-2026",
    "marina_bay": "sg-2008",
    "miami": "us-2022",
    "monaco": "mc-1929",
    "monza": "it-1922",
    "mugello": "it-1914",
    "nurburgring": "de-1927",
    "portimao": "pt-2008",
    "red_bull_ring": "at-1969",
    "ricard": "fr-1969",
    "rodriguez": "mx-1962",
    "sepang": "my-1999",
    "shanghai": "cn-2004",
    "silverstone": "gb-1948",
    "sochi": "ru-2014",
    "spa": "be-1925",
    "suzuka": "jp-1962",
    "vegas": "us-2023",
    "villeneuve": "ca-1978",
    "yas_marina": "ae-2009",
    "zandvoort": "nl-1948",
}

GEOJSON_URL = "https://raw.githubusercontent.com/bacinger/f1-circuits/master/circuits/{}.geojson"
INDEX_URL = "https://api.github.com/repos/bacinger/f1-circuits/contents/circuits"


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_geojson(filename: str) -> dict | None:
    """Pull one GeoJSON file. Returns None on any failure (HTTP error, parse error)."""
    try:
        resp = requests.get(GEOJSON_URL.format(filename), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def _bacinger_index() -> list[dict]:
    """Fetch the list of available filenames + a quick centroid lookup.

    For any circuit not in CIRCUIT_FILE_MAP, we can find a nearest-neighbor
    match by comparing lat/lng to the centroid of each available GeoJSON.
    Cached for a day since the upstream repo doesn't change often.
    """
    try:
        resp = requests.get(INDEX_URL, timeout=15)
        resp.raise_for_status()
        files = [
            f["name"].replace(".geojson", "")
            for f in resp.json()
            if f.get("name", "").endswith(".geojson")
        ]
    except (requests.RequestException, ValueError, KeyError):
        return []

    index = []
    for name in files:
        data = _fetch_geojson(name)
        if not data or not data.get("features"):
            continue
        coords = data["features"][0].get("geometry", {}).get("coordinates", [])
        if not coords:
            continue
        avg_lng = sum(c[0] for c in coords) / len(coords)
        avg_lat = sum(c[1] for c in coords) / len(coords)
        index.append({"name": name, "lat": avg_lat, "lng": avg_lng})
    return index


def _haversine(lat1, lng1, lat2, lng2) -> float:
    """Distance between two lat/lng points in km."""
    R = 6371
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _find_by_proximity(lat: float, lng: float, max_km: float = 50.0) -> str | None:
    """Find a bacinger circuit whose centroid is within ``max_km`` of (lat, lng)."""
    if lat is None or lng is None:
        return None
    nearest = None
    best = float("inf")
    for c in _bacinger_index():
        d = _haversine(lat, lng, c["lat"], c["lng"])
        if d < best and d <= max_km:
            best = d
            nearest = c["name"]
    return nearest


def get_track_outline(circuit_id: str, lat: float | None = None, lng: float | None = None) -> dict | None:
    """Return the track outline for a circuit as ``{"coords": [[lng, lat], ...], "props": {...}}``.

    Tries the hard-coded map first (fast, no extra network), falls back to
    nearest-neighbor by lat/lng (one network call to list files, plus per-
    candidate fetches that get cached). Returns None if nothing usable is found.
    """
    name = CIRCUIT_FILE_MAP.get(circuit_id)
    if not name:
        name = _find_by_proximity(lat, lng) if lat is not None and lng is not None else None
    if not name:
        return None

    data = _fetch_geojson(name)
    if not data or not data.get("features"):
        return None

    feat = data["features"][0]
    coords = feat.get("geometry", {}).get("coordinates", [])
    if not coords:
        return None
    return {"coords": coords, "props": feat.get("properties", {})}
