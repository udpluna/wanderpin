"""HTTP API + static UI."""
import asyncio
import datetime as dt
import logging
import socket
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import os

from . import services
from .config import APP_NAME, PORT, PRODUCT, STATIC_DIR, VERSION

from .device import DemoDevice, Device, friendly_error
from .motion import PRESET_BY_ID, PRESETS, Motion, haversine
from .store import Store

log = logging.getLogger("wanderpin")

store = Store()
device = DemoDevice() if os.environ.get("WANDERPIN_DEMO") else Device()
motion = Motion(device, store)
_update_info: dict = {}


# ----------------------------------------------------------------- helpers --
def _real(v):
    """Ignore unfilled placeholders like YOUR_GITHUB_USERNAME."""
    return v if v and "YOUR_" not in v else ""


def lan_ip() -> Optional[str]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def fail(e: Exception, code=500):
    log.error("%s", e)
    raise HTTPException(code, friendly_error(e))


# --------------------------------------------------------------- scheduler --
async def scheduler_loop():
    fired = set()
    while True:
        await asyncio.sleep(10)
        now = dt.datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        for s in list(store.schedules.data):
            try:
                if not s.get("enabled", True) or s.get("time") != now.strftime("%H:%M"):
                    continue
                if now.weekday() not in s.get("days", list(range(7))):
                    continue
                key = (s["id"], stamp)
                if key in fired:
                    continue
                fired.add(key)
                if not device.connected:
                    continue
                log.info("Schedule fired: %s", s.get("name"))
                if s.get("preset"):
                    store.update_settings({"preset": s["preset"], "custom_kmh": None})
                if s["action"] == "teleport":
                    await motion.teleport(s["lat"], s["lon"])
                elif s["action"] == "route":
                    r = store.get(store.routes, s.get("route_id"))
                    if r:
                        if device.current and haversine(device.current, r["path"][0]) > 50:
                            await motion.teleport(*r["path"][0])
                        motion.start_route(r["path"], s.get("loop_mode") or r.get("loop_mode"))
                elif s["action"] == "reset":
                    motion.stop()
                    await device.clear()
                s["last_run"] = int(time.time())
                store.schedules.save()
            except Exception as e:
                log.warning("schedule failed: %s", e)
        if len(fired) > 1000:
            fired.clear()


@asynccontextmanager
async def lifespan(_app):
    global _update_info
    device.auto_reconnect = store.settings.get("auto_reconnect", True)
    motion.start()
    asyncio.create_task(scheduler_loop())

    async def _upd():
        global _update_info
        _update_info = await services.check_update(VERSION)
    asyncio.create_task(_upd())

    if store.settings.get("auto_connect") and store.settings.get("terms_accepted"):
        async def _auto():
            try:
                await device.connect()
            except Exception:
                device.want_connected = False
        asyncio.create_task(_auto())
    yield
    try:
        motion.stop()
        motion._remember()
        store.state.save()
        await device.disconnect(reset_location=store.settings.get("reset_on_exit", True))
    except Exception:
        pass


app = FastAPI(lifespan=lifespan, title=APP_NAME)


@app.middleware("http")
async def lan_guard(request: Request, call_next):
    """Requests from other devices on the network need the access key (shown as a QR code)."""
    host = request.client.host if request.client else "127.0.0.1"
    if host not in ("127.0.0.1", "::1", "localhost"):
        key = store.settings["lan_key"]
        given = request.query_params.get("key") or request.headers.get("x-access-key") or request.cookies.get("wp_key")
        if not store.settings.get("lan_enabled") or given != key:
            return JSONResponse({"detail": "Not allowed"}, status_code=403)
        resp = await call_next(request)
        if request.query_params.get("key"):
            resp.set_cookie("wp_key", key, max_age=3600 * 24 * 365, httponly=True, samesite="lax")
        return resp
    return await call_next(request)


# ------------------------------------------------------------------ models --
class LatLon(BaseModel):
    lat: float
    lon: float
    name: Optional[str] = None


class PlanReq(BaseModel):
    points: List[List[float]]
    road: Optional[str] = None      # foot | bike | car | None


class StartReq(BaseModel):
    path: List[List[float]]
    loop_mode: Optional[str] = None
    teleport_to_start: bool = True


class TravelReq(BaseModel):
    lat: float
    lon: float
    roads: bool = True


class SpeedReq(BaseModel):
    preset: Optional[str] = None
    kmh: Optional[float] = None
    reset_custom: bool = False


class JoyReq(BaseModel):
    x: float
    y: float


class TextReq(BaseModel):
    text: str


class UrlReq(BaseModel):
    url: str


# ---------------------------------------------------------------------- ui --
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/tiles/osm/{z}/{x}/{y}.png")
async def osm_tile(z: int, x: int, y: int):
    try:
        data = await services.osm_tile(z, x, y)
    except Exception:
        raise HTTPException(404, "tile unavailable")
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})


# ------------------------------------------------------------------- state --
@app.get("/api/boot")
async def boot():
    return {
        "app": {"name": APP_NAME, "version": VERSION, "donate_url": _real(PRODUCT.get("donate_url")),
                "github_repo": _real(PRODUCT.get("github_repo")), "support_email": PRODUCT.get("support_email"),
                "publisher": PRODUCT.get("publisher")},
        "presets": PRESETS,
        "map": PRODUCT["map"],
        "settings": store.settings,
        "last": store.state.data.get("last"),
    }


@app.get("/api/state")
async def state():
    s = device.status()
    s["motion"] = motion.status()
    s["update"] = _update_info or None
    s["stats"] = store.state.data.get("stats", {})
    return s


# ------------------------------------------------------------------ device --
@app.post("/api/connect")
async def connect():
    try:
        await device.connect()
    except Exception as e:
        fail(e)
    return await state()


@app.post("/api/disconnect")
async def disconnect():
    motion.stop()
    await device.disconnect(reset_location=True)
    return await state()


@app.post("/api/reveal-devmode")
async def reveal_devmode():
    try:
        await device.reveal_developer_mode()
    except Exception as e:
        fail(e)
    return {"ok": True}


@app.post("/api/reset")
async def reset():
    motion.stop()
    try:
        await device.clear()
    except Exception as e:
        fail(e)
    return await state()


# ---------------------------------------------------------------- movement --
@app.post("/api/teleport")
async def teleport(p: LatLon):
    try:
        await motion.teleport(p.lat, p.lon)
    except Exception as e:
        fail(e)
    name = p.name or await services.reverse(p.lat, p.lon) or f"{p.lat:.5f}, {p.lon:.5f}"
    store.push_history(p.lat, p.lon, name)
    return await state()


@app.post("/api/route/plan")
async def route_plan(r: PlanReq):
    if len(r.points) < 2:
        raise HTTPException(400, "Add at least two stops.")
    return await services.plan_route(r.points, r.road)


@app.post("/api/route/start")
async def route_start(r: StartReq):
    if not device.connected:
        raise HTTPException(409, "Connect your iPhone first.")
    if len(r.path) < 2:
        raise HTTPException(400, "Route is empty.")
    try:
        start = tuple(r.path[0])
        if r.teleport_to_start and (not device.current or haversine(device.current, start) > 30):
            await motion.teleport(*start)
    except Exception as e:
        fail(e)
    motion.start_route(r.path, r.loop_mode)
    return await state()


@app.post("/api/travel")
async def travel(t: TravelReq):
    """Move from the current spot to a destination at the current speed preset."""
    if not device.connected:
        raise HTTPException(409, "Connect your iPhone first.")
    here = device.current or motion.base
    if not here:
        raise HTTPException(400, "Set a starting location first (teleport somewhere).")
    road = motion.preset.get("road") if t.roads else None
    plan = await services.plan_route([list(here), [t.lat, t.lon]], road)
    motion.start_route(plan["path"], "once")
    return {"plan": plan, **(await state())}


@app.post("/api/route/pause")
async def route_pause():
    motion.pause(True)
    return await state()


@app.post("/api/route/resume")
async def route_resume():
    motion.pause(False)
    return await state()


@app.post("/api/route/stop")
async def route_stop():
    motion.stop()
    return await state()


@app.post("/api/speed")
async def speed(s: SpeedReq):
    patch = {}
    if s.preset and s.preset in PRESET_BY_ID:
        patch["preset"] = s.preset
        patch["custom_kmh"] = None
    if s.kmh is not None:
        patch["custom_kmh"] = max(0.5, min(1200.0, s.kmh))
    if s.reset_custom:
        patch["custom_kmh"] = None
    store.update_settings(patch)
    return await state()


@app.post("/api/joystick")
async def joystick(j: JoyReq):
    if not device.connected:
        raise HTTPException(409, "Connect your iPhone first.")
    motion.joystick(j.x, j.y)
    return {"ok": True}


# ----------------------------------------------------------------- search --
@app.get("/api/geocode")
async def geocode(q: str, lat: Optional[float] = None, lon: Optional[float] = None):
    try:
        return await services.geocode(q, (lat, lon) if lat is not None else None)
    except Exception:
        raise HTTPException(502, "Search is unavailable right now. Check your internet connection.")


@app.get("/api/reverse")
async def reverse(lat: float, lon: float):
    return {"name": await services.reverse(lat, lon)}


# ---------------------------------------------------------------- settings --
@app.post("/api/settings")
async def settings(patch: dict):
    s = store.update_settings(patch)
    device.auto_reconnect = s.get("auto_reconnect", True)
    return s


@app.post("/api/open")
async def open_external(u: UrlReq):
    """Open a link in the user's normal web browser (only well-known, safe hosts)."""
    from urllib.parse import urlparse
    import webbrowser
    allowed = {"github.com", "www.github.com", "buymeacoffee.com", "www.buymeacoffee.com", "ko-fi.com",
               "www.openstreetmap.org", "openfreemap.org", "routing.openstreetmap.de", "www.apple.com",
               "apps.microsoft.com", "www.python.org"}
    donate = urlparse(PRODUCT.get("donate_url") or "").hostname
    if donate:
        allowed.add(donate)
    p = urlparse(u.url)
    if p.scheme != "https" or p.hostname not in allowed:
        raise HTTPException(400, "Link not allowed")
    webbrowser.open(u.url)
    return {"ok": True}


@app.get("/api/lan")
async def lan():
    ip = lan_ip()
    k = store.settings["lan_key"]
    return {"enabled": store.settings.get("lan_enabled"), "ip": ip,
            "url": f"http://{ip}:{PORT}/?key={k}" if ip else None}


@app.post("/api/lan/regenerate")
async def lan_regen():
    import secrets
    store.update_settings({"lan_key": secrets.token_urlsafe(9)})
    return await lan()


# ------------------------------------------------------------ collections --
COLLS = {"places": store.places, "routes": store.routes, "schedules": store.schedules, "history": store.history}


def _coll(name):
    if name not in COLLS:
        raise HTTPException(404, "Unknown collection")
    return COLLS[name]


@app.get("/api/{name}")
async def list_items(name: str):
    return _coll(name).data


@app.post("/api/{name}")
async def add_item(name: str, item: dict):
    return store.add(_coll(name), item)


@app.put("/api/{name}/{item_id}")
async def update_item(name: str, item_id: str, patch: dict):
    it = store.update(_coll(name), item_id, patch)
    if not it:
        raise HTTPException(404, "Not found")
    return it


@app.delete("/api/{name}/{item_id}")
async def delete_item(name: str, item_id: str):
    store.remove(_coll(name), item_id)
    return {"ok": True}


@app.delete("/api/{name}")
async def clear_items(name: str):
    if name != "history":
        raise HTTPException(400, "Only history can be cleared in one go.")
    store.history._data = []
    store.history.save()
    return {"ok": True}


# -------------------------------------------------------------------- gpx --
@app.post("/api/gpx/import")
async def gpx_import(t: TextReq):
    try:
        return services.gpx_to_points(t.text)
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that GPX file: {e}")


@app.post("/api/gpx/export")
async def gpx_export(r: dict):
    xml = services.points_to_gpx(r.get("name", "Route"), r["path"])
    fname = "".join(c for c in r.get("name", "route") if c.isalnum() or c in " -_").strip() or "route"
    return Response(xml, media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.gpx"'})
