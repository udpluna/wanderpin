"""Tiny JSON-file storage for settings, places, routes, schedules, history and app state."""
import json
import os
import secrets
import time
import uuid
from pathlib import Path

from .config import BASE_DIR, DATA_DIR

DEFAULT_SETTINGS = {
    "units": "mph",               # "mph" | "kmh"
    "theme": "dark",              # "dark" | "light"
    "map_layer": "auto",           # auto | streets | dark | satellite
    "preset": "walk",
    "custom_kmh": None,           # user speed override (km/h); None = preset speed
    "wobble": True,               # natural GPS wobble while moving
    "idle_drift": False,          # tiny GPS drift while parked
    "follow_roads": True,
    "loop_mode": "once",          # "once" | "repeat" | "pingpong"
    "auto_connect": True,
    "auto_reconnect": True,
    "reset_on_exit": True,
    "cooldown_warnings": True,
    "lan_enabled": False,
    "lan_key": "",
    "open_in_browser": False,
    "onboarded": False,
    "terms_accepted": False,
    "support_nudged": False,
    "donated_click": False,
}


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


class JsonFile:
    def __init__(self, name: str, default):
        self.path: Path = DATA_DIR / f"{name}.json"
        self.default = default
        self._data = None

    @property
    def data(self):
        if self._data is None:
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except Exception:
                self._data = json.loads(json.dumps(self.default))
        return self._data

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), "utf-8")
        os.replace(tmp, self.path)


class Store:
    def __init__(self):
        self.settings_file = JsonFile("settings", DEFAULT_SETTINGS)
        self.places = JsonFile("places", [])
        self.routes = JsonFile("routes", [])
        self.schedules = JsonFile("schedules", [])
        self.history = JsonFile("history", [])
        self.state = JsonFile("state", {"last": None, "stats": {"distance_m": 0, "teleports": 0}})
        s = self.settings_file.data
        for k, v in DEFAULT_SETTINGS.items():
            s.setdefault(k, v)
        if not s["lan_key"]:
            s["lan_key"] = secrets.token_urlsafe(9)
        self.settings_file.save()
        self._migrate_v1()

    # --- settings
    @property
    def settings(self) -> dict:
        return self.settings_file.data

    def update_settings(self, patch: dict) -> dict:
        for k, v in patch.items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = v
        self.settings_file.save()
        return self.settings

    # --- generic list helpers
    def add(self, coll: JsonFile, item: dict) -> dict:
        item = dict(item)
        item.setdefault("id", _new_id())
        item.setdefault("created", int(time.time()))
        coll.data.append(item)
        coll.save()
        return item

    def update(self, coll: JsonFile, item_id: str, patch: dict):
        for it in coll.data:
            if it.get("id") == item_id:
                it.update({k: v for k, v in patch.items() if k != "id"})
                coll.save()
                return it
        return None

    def remove(self, coll: JsonFile, item_id: str):
        coll._data = [it for it in coll.data if it.get("id") != item_id]
        coll.save()

    def get(self, coll: JsonFile, item_id: str):
        return next((it for it in coll.data if it.get("id") == item_id), None)

    def push_history(self, lat: float, lon: float, name: str):
        key = (round(lat, 5), round(lon, 5))
        h = [x for x in self.history.data if (round(x["lat"], 5), round(x["lon"], 5)) != key]
        h.insert(0, {"id": _new_id(), "lat": lat, "lon": lon, "name": name, "t": int(time.time())})
        self.history._data = h[:100]
        self.history.save()

    def _migrate_v1(self):
        """Import bookmarks/history from the first version (wanderpin_data.json next to the app)."""
        old = BASE_DIR / "wanderpin_data.json"
        marker = DATA_DIR / ".migrated_v1"
        if not old.exists() or marker.exists():
            return
        try:
            d = json.loads(old.read_text("utf-8"))
            for b in d.get("bookmarks", []):
                self.add(self.places, {"name": b["name"], "lat": b["lat"], "lon": b["lon"], "emoji": "📍"})
            for h in reversed(d.get("history", [])):
                self.push_history(h["lat"], h["lon"], h["name"])
        except Exception:
            pass
        marker.write_text("ok")
