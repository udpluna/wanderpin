"""App-wide configuration: paths, product settings (product.json) and defaults."""
import json
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
STATIC_DIR = BASE_DIR / "static"

_DEFAULT_PRODUCT = {
    "app_name": "WanderPin",
    "version": "1.0.0",
    "publisher": "WanderPin",
    # Donations + project links (shown in the app's "Support" dialog)
    "donate_url": "",            # e.g. https://buymeacoffee.com/yourname
    "github_repo": "",           # e.g. yourname/wanderpin  (also used for update checks)
    "support_email": "",
    # Free map providers - no API keys needed.
    #   type "vector": a MapLibre style URL (OpenFreeMap: free, no keys, no limits, commercial use OK)
    #   type "raster": an XYZ tile URL
    "map": {
        "auto_light": "streets",
        "auto_dark": "dark",
        "layers": {
            "streets": {"name": "Streets", "type": "vector",
                        "style": "https://tiles.openfreemap.org/styles/liberty",
                        "preview": "#e9e4d8"},
            "light": {"name": "Light", "type": "vector",
                      "style": "https://tiles.openfreemap.org/styles/positron",
                      "preview": "#f2f3f0"},
            "dark": {"name": "Dark", "type": "vector",
                     "style": "https://tiles.openfreemap.org/styles/dark",
                     "preview": "#1d2330"},
            "satellite": {"name": "Satellite", "type": "raster", "max_zoom": 19,
                          "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                          "attribution": "Imagery &copy; Esri, Maxar, Earthstar Geographics",
                          "preview": "#3d4a2f"},
            "osm": {"name": "OpenStreetMap classic", "type": "raster", "max_zoom": 19,
                    "url": "/tiles/osm/{z}/{x}/{y}.png",
                    "attribution": "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
                    "preview": "#aad3df"},
        },
    },
    # Search: Photon (built for search-as-you-type), falls back to Nominatim.
    "geocoder": {"provider": "photon", "url": "https://photon.komoot.io",
                 "fallback_url": "https://nominatim.openstreetmap.org"},
    # Road routing (FOSSGIS OSRM servers - max 1 request per second, which the app enforces).
    "routing": {
        "foot": "https://routing.openstreetmap.de/routed-foot",
        "bike": "https://routing.openstreetmap.de/routed-bike",
        "car": "https://routing.openstreetmap.de/routed-car",
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _load_product() -> dict:
    p = BASE_DIR / "product.json"
    try:
        return _merge(_DEFAULT_PRODUCT, json.loads(p.read_text("utf-8")))
    except Exception:
        return _DEFAULT_PRODUCT


PRODUCT = _load_product()
APP_NAME = PRODUCT["app_name"]
VERSION = PRODUCT["version"]

if os.name == "nt":
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
elif sys.platform == "darwin":
    DATA_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
else:
    DATA_DIR = Path.home() / f".{APP_NAME.lower()}"
if os.environ.get("WANDERPIN_DEMO"):
    DATA_DIR = DATA_DIR / "demo"   # keep demo data separate from real data
DATA_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("WANDERPIN_PORT", "8765"))
TRANSPORT = os.environ.get("WANDERPIN_TRANSPORT", "userspace")  # or "tunneld"
_contact = PRODUCT.get("github_repo") and "YOUR_" not in PRODUCT["github_repo"] and f"https://github.com/{PRODUCT['github_repo']}" or PRODUCT.get("support_email") or "desktop app"
USER_AGENT = f"{APP_NAME}/{VERSION} (+{_contact})"
TILE_CACHE = DATA_DIR / "tilecache"
