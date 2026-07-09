"""
location.py
-----------
Where Rydel actually is — resolved with a fallback chain, so the greeting's time-of-day and weather
follow him when he travels instead of being hardcoded to Newcastle.

Resolution priority:
  1. MANUAL OVERRIDE  — "I'm in <place>" (persisted until cleared / "I'm back home").
  2. BROWSER GEO      — dashboard geolocation (consented), reverse-geocoded, cached last-known.
  3. LAST-KNOWN       — the previous successful resolution.
  4. DEFAULT          — Newcastle, stated neutrally (final fallback only).

Geocoding + weather use Open-Meteo (free, no key); reverse-geocoding uses BigDataCloud (free, no key).
Every network call degrades gracefully — a failure never blocks the greeting.
"""
from __future__ import annotations

import logging
import time

import requests

import kv_store

logger = logging.getLogger(__name__)

_DEFAULT = {"place": "Newcastle", "lat": -32.9283, "lon": 151.7817,
            "timezone": "Australia/Sydney", "source": "default"}

_K_OVERRIDE = "location:override"
_K_GEO = "location:geo"
_K_LAST = "location:last_known"

_WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "drizzling", 53: "drizzling", 55: "drizzling",
    61: "raining lightly", 63: "raining", 65: "raining heavily",
    66: "raining", 67: "raining", 71: "snowing", 73: "snowing", 75: "snowing",
    80: "showery", 81: "showery", 82: "showery", 95: "stormy", 96: "stormy", 99: "stormy",
}

_weather_cache: dict = {}   # keyed by "lat,lon" → {ts, data}
_CACHE_SECONDS = 15 * 60


# ── Geocoding ────────────────────────────────────────────────────────────────

def geocode(place: str) -> dict | None:
    """Place name → {place, lat, lon, timezone}. Open-Meteo geocoding. None on failure."""
    if not place or not place.strip():
        return None
    try:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": place.strip(), "count": 1, "language": "en"},
                         timeout=(4, 8))
        if r.status_code != 200:
            return None
        res = (r.json().get("results") or [])
        if not res:
            return None
        g = res[0]
        name = g.get("name") or place.strip()
        admin = g.get("admin1")
        label = f"{name}, {admin}" if admin and admin != name else name
        return {"place": label, "short": name, "lat": g.get("latitude"),
                "lon": g.get("longitude"), "timezone": g.get("timezone") or "auto"}
    except requests.RequestException as e:
        logger.info("geocode(%s) failed: %s", place, e)
        return None


def reverse_geocode(lat: float, lon: float) -> dict | None:
    """Coordinates → {place, short, lat, lon, timezone}. BigDataCloud (free). None on failure."""
    try:
        r = requests.get("https://api.bigdatacloud.net/data/reverse-geocode-client",
                         params={"latitude": lat, "longitude": lon, "localityLanguage": "en"},
                         timeout=(4, 8))
        if r.status_code != 200:
            return None
        d = r.json()
        city = d.get("city") or d.get("locality") or d.get("principalSubdivision")
        region = d.get("principalSubdivision")
        if not city:
            return None
        label = f"{city}, {region}" if region and region != city else city
        return {"place": label, "short": city, "lat": lat, "lon": lon, "timezone": "auto"}
    except requests.RequestException as e:
        logger.info("reverse_geocode failed: %s", e)
        return None


# ── Manual override + browser geo (persisted) ────────────────────────────────

def set_override(place: str) -> dict | None:
    """'I'm in <place>' → resolve + persist. Returns the resolved loc, or None if unresolvable."""
    g = geocode(place)
    if not g:
        return None
    loc = {**g, "source": "override", "set_at": time.time()}
    kv_store.put(_K_OVERRIDE, loc)
    kv_store.put(_K_LAST, loc)
    return loc


def clear_override() -> None:
    """'I'm back home' → drop the override AND the stale last-known (which the override had set),
    so resolution falls through to live device geo or the Newcastle default — not the trip's city."""
    kv_store.delete(_K_OVERRIDE)
    kv_store.delete(_K_LAST)


def set_geo(lat: float, lon: float) -> dict | None:
    """Dashboard-provided browser coordinates → reverse-geocode + cache as last-known."""
    rg = reverse_geocode(lat, lon) or {"place": "your location", "short": "there",
                                        "lat": lat, "lon": lon, "timezone": "auto"}
    loc = {**rg, "source": "geolocation", "set_at": time.time()}
    kv_store.put(_K_GEO, loc)
    kv_store.put(_K_LAST, loc)
    return loc


def resolve() -> dict:
    """The fallback chain. Always returns a location dict with a 'source' tag."""
    ov = kv_store.get(_K_OVERRIDE)
    if ov and ov.get("lat") is not None:
        return ov
    geo = kv_store.get(_K_GEO)
    if geo and geo.get("lat") is not None:
        return geo
    last = kv_store.get(_K_LAST)
    if last and last.get("lat") is not None:
        return {**last, "source": "last-known"}
    return dict(_DEFAULT)


import re as _re

_SET_RE = _re.compile(r"\bi'?m (?:currently )?(?:in|at|travell?ing to|flying to|heading to|visiting|"
                      r"over in|now in|based in) ([A-Za-z][A-Za-z .'\-]+)", _re.I)
_CLEAR_RE = _re.compile(r"\bi'?m back home\b|\bback in newcastle\b|\bclear my location\b|"
                        r"\breset my location\b|\bi'?m home\b", _re.I)
_WHERE_RE = _re.compile(r"\bwhere (do you think |are you sure )?(i am|am i)\b|"
                        r"\bwhere do you (think|reckon) i'?m\b|\bwhat'?s my location\b", _re.I)


def handle_location_command(text: str) -> tuple[str | None, bool]:
    """'I'm in <place>' / 'I'm back home' / 'where do you think I am?' — deterministic."""
    if not text:
        return None, False
    if _WHERE_RE.search(text):
        return "I've got you in " + describe(), True
    if _CLEAR_RE.search(text):
        clear_override()
        return "Got it — cleared. I'll use your device location, or Newcastle if I can't tell.", True
    m = _SET_RE.search(text)
    if m:
        place = m.group(1).strip().rstrip(".")
        # Strip trailing time/qualifier phrases so "Melbourne this week" → "Melbourne".
        place = _re.sub(r"\s+(this week|this weekend|today|tonight|right now|now|currently|"
                        r"at the moment|for .*|until .*|till .*|tomorrow|next week|"
                        r"a few days|the week|all week)\s*$", "", place, flags=_re.I).strip()
        loc = set_override(place)
        if not loc:
            return f"I couldn't place “{place}” — try a city name and I'll switch your weather/time to it.", True
        return f"Noted — you're in {loc['place']}. I'll use its time and weather from now.", True
    return None, False


def describe(loc: dict | None = None) -> str:
    """Honest 'where do you think I am' answer — place + how she knows."""
    loc = loc or resolve()
    how = {"override": "you told me you're there",
           "geolocation": "your browser shared it",
           "last-known": "it's the last place I had you",
           "default": "I don't have a live location, so I'm defaulting to Newcastle"}.get(
        loc.get("source"), "resolved")
    return f"{loc.get('place', 'Newcastle')} — {how}."


# ── Weather + local time for the resolved location ───────────────────────────

def weather_and_localtime(loc: dict | None = None) -> dict | None:
    """Current temp + condition + today's high + LOCAL hour for the resolved location.
    timezone=auto → Open-Meteo returns times in the location's local zone. None on failure."""
    loc = loc or resolve()
    lat, lon = loc.get("lat"), loc.get("lon")
    if lat is None or lon is None:
        return None
    key = f"{round(lat, 2)},{round(lon, 2)}"
    now = time.time()
    c = _weather_cache.get(key)
    if c and now - c["ts"] < _CACHE_SECONDS:
        return c["data"]
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params={"latitude": lat, "longitude": lon,
                                 "current": "temperature_2m,weather_code",
                                 "daily": "temperature_2m_max",
                                 "timezone": "auto", "forecast_days": 1},
                         timeout=(4, 8))
        if r.status_code != 200:
            return None
        d = r.json()
        cur = d.get("current") or {}
        if cur.get("temperature_2m") is None:
            return None
        local_hour = None
        t = cur.get("time")   # e.g. "2026-07-07T15:00" in local tz
        if t and "T" in t:
            try:
                local_hour = int(t.split("T")[1].split(":")[0])
            except (ValueError, IndexError):
                local_hour = None
        data = {
            "temp_c": cur.get("temperature_2m"),
            "condition": _WMO.get(cur.get("weather_code"), "fine"),
            "high_c": ((d.get("daily") or {}).get("temperature_2m_max") or [None])[0],
            "place": loc.get("short") or loc.get("place"),
            "local_hour": local_hour,
        }
        _weather_cache[key] = {"ts": now, "data": data}
        return data
    except requests.RequestException as e:
        logger.info("weather_and_localtime failed: %s", e)
        return None
