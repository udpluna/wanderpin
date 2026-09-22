"""Search (geocoding), road routing and GPX import/export."""
import asyncio
import functools
import io
from typing import List

import requests

from .config import PRODUCT, USER_AGENT
from .motion import densify_great_circle, haversine

import time
from urllib.parse import urlparse

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_cache: dict = {}

# Free community servers ask for at most 1 request per second - we respect that.
_RATE = {"nominatim.openstreetmap.org": 1.05, "routing.openstreetmap.de": 1.05, "photon.komoot.io": 0.35}
_last_call: dict = {}
_host_locks: dict = {}


async def _throttle(url: str):
    host = urlparse(url).hostname or ""
    gap = _RATE.get(host)
    if not gap:
        return
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = _last_call.get(host, 0) + gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call[host] = time.monotonic()


async def _get_json(url: str, params: dict):
    key = (url, tuple(sorted(params.items())))
    if key in _cache:
        return _cache[key]
    await _throttle(url)
    loop = asyncio.get_running_loop()
    r = await loop.run_in_executor(None, functools.partial(_session.get, url, params=params, timeout=8))
    r.raise_for_status()
    data = r.json()
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = data
    return data


# ---------------------------------------------------------------- geocoding --
def _photon_label(pr: dict):
    name = pr.get("name") or " ".join(x for x in (pr.get("housenumber"), pr.get("street")) if x) or pr.get("city") or ""
    street = " ".join(x for x in (pr.get("housenumber"), pr.get("street")) if x)
    parts = [street if street and street != name else None, pr.get("city") or pr.get("town") or pr.get("village"),
             pr.get("state"), pr.get("country")]
    seen, detail = set(), []
    for x in parts:
        if x and x not in seen and x != name:
            seen.add(x)
            detail.append(x)
    return name, ", ".join(detail)


async def geocode(q: str, near=None) -> List[dict]:
    g = PRODUCT["geocoder"]
    if g.get("provider", "photon") == "photon":
        try:
            params = {"q": q, "limit": 8}
            if near:
                params.update(lat=round(near[0], 3), lon=round(near[1], 3))
            d = await _get_json(g["url"].rstrip("/") + "/api/", params)
            out = []
            for f in d.get("features", []):
                name, detail = _photon_label(f.get("properties", {}))
                lon, lat = f["geometry"]["coordinates"][:2]
                out.append({"name": name or detail, "detail": detail, "lat": lat, "lon": lon,
                            "type": f.get("properties", {}).get("osm_value", "")})
            return out
        except Exception:
            if not g.get("fallback_url"):
                raise
    base = g.get("fallback_url") or g["url"]
    d = await _get_json(base.rstrip("/") + "/search", {"format": "jsonv2", "limit": 8, "q": q})
    out = []
    for p in d:
        parts = p.get("display_name", "").split(",")
        out.append({"name": parts[0].strip(), "detail": ",".join(parts[1:]).strip(),
                    "lat": float(p["lat"]), "lon": float(p["lon"]), "type": p.get("type", "")})
    return out


async def reverse(lat: float, lon: float) -> str:
    g = PRODUCT["geocoder"]
    try:
        if g.get("provider", "photon") == "photon":
            d = await _get_json(g["url"].rstrip("/") + "/reverse", {"lat": round(lat, 5), "lon": round(lon, 5), "limit": 1})
            f = d.get("features") or []
            if f:
                name, detail = _photon_label(f[0].get("properties", {}))
                return ", ".join(x for x in (name, detail) if x)
        base = g.get("fallback_url") or g["url"]
        d = await _get_json(base.rstrip("/") + "/reverse",
                            {"format": "jsonv2", "lat": round(lat, 5), "lon": round(lon, 5), "zoom": 17})
        return d.get("display_name", "")
    except Exception:
        return ""


# ------------------------------------------------------------------ routing --
async def plan_route(points: List[List[float]], road: str) -> dict:
    """road: foot | bike | car | None (straight / great-circle)."""
    pts = [tuple(p) for p in points]
    if road and road in PRODUCT["routing"]:
        coords = ";".join(f"{p[1]:.6f},{p[0]:.6f}" for p in pts)
        base = PRODUCT["routing"][road].rstrip("/")
        try:
            d = await _get_json(f"{base}/route/v1/driving/{coords}", {"overview": "full", "geometries": "geojson"})
            if d.get("routes"):
                r = d["routes"][0]
                path = [(c[1], c[0]) for c in r["geometry"]["coordinates"]]
                # make sure the route starts/ends exactly on the chosen points
                path = [pts[0]] + path + [pts[-1]]
                return {"path": path, "distance": r["distance"], "roads": True}
        except Exception:
            pass
    path = []
    for a, b in zip(pts, pts[1:]):
        seg = densify_great_circle(a, b)
        path.extend(seg if not path else seg[1:])
    dist = sum(haversine(a, b) for a, b in zip(path, path[1:]))
    return {"path": path, "distance": dist, "roads": False, "fallback": bool(road)}


# ---------------------------------------------------------------------- gpx --
def gpx_to_points(text: str) -> dict:
    import gpxpy
    g = gpxpy.parse(io.StringIO(text))
    pts, name = [], None
    for t in g.tracks:
        name = name or t.name
        for s in t.segments:
            pts += [(p.latitude, p.longitude) for p in s.points]
    if not pts:
        for r in g.routes:
            name = name or r.name
            pts += [(p.latitude, p.longitude) for p in r.points]
    if not pts:
        pts = [(w.latitude, w.longitude) for w in g.waypoints]
    if len(pts) < 2:
        raise ValueError("That GPX file has no route or track in it.")
    return {"name": name or "Imported route", "path": pts}


def points_to_gpx(name: str, path) -> str:
    import gpxpy.gpx
    g = gpxpy.gpx.GPX()
    t = gpxpy.gpx.GPXTrack(name=name)
    s = gpxpy.gpx.GPXTrackSegment()
    s.points = [gpxpy.gpx.GPXTrackPoint(lat, lon) for lat, lon in path]
    t.segments.append(s)
    g.tracks.append(t)
    return g.to_xml()


async def check_update(current: str) -> dict:
    """Checks the project's GitHub Releases for a newer version."""
    repo = PRODUCT.get("github_repo")
    if not repo or "YOUR_" in repo:
        return {}
    try:
        d = await _get_json(f"https://api.github.com/repos/{repo}/releases/latest", {})
        from packaging.version import Version
        tag = str(d.get("tag_name", "0")).lstrip("vV")
        if Version(tag) > Version(current):
            return {"version": tag, "url": d.get("html_url", f"https://github.com/{repo}/releases"),
                    "notes": (d.get("body") or "")[:500]}
    except Exception:
        pass
    return {}


# ------------------------------------------------------------ tile proxy --
# OpenStreetMap's tile servers require a proper User-Agent and at least 7 days of caching,
# so the classic OSM layer is loaded through this small local cache.
_TILE_TTL = 7 * 86400


async def osm_tile(z: int, x: int, y: int) -> bytes:
    from .config import TILE_CACHE
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise ValueError("bad tile")
    path = TILE_CACHE / str(z) / str(x) / f"{y}.png"
    if path.exists() and time.time() - path.stat().st_mtime < _TILE_TTL:
        return path.read_bytes()
    loop = asyncio.get_running_loop()
    try:
        r = await loop.run_in_executor(None, functools.partial(
            _session.get, f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", timeout=10))
        r.raise_for_status()
    except Exception:
        if path.exists():
            return path.read_bytes()   # stale is better than nothing
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.content
