"""Movement engine: speed presets, realistic speed profiles, route playback, joystick, wobble."""
import asyncio
import logging
import math
import random
import time
from typing import List, Optional, Tuple

log = logging.getLogger("wanderpin.motion")

TICK = 0.5  # seconds between location updates while moving
R_EARTH = 6371000.0

# ------------------------------------------------------------------ presets --
# road: routing profile used when "follow roads" is on (None = straight line)
# profile: how speed behaves over time
PRESETS = [
    {"id": "stroll",   "name": "Stroll",       "kmh": 3.5, "profile": "steady",  "var": 0.10, "road": "foot", "icon": "stroll",  "accel": 0.6},
    {"id": "walk",     "name": "Walk",         "kmh": 5.0, "profile": "steady",  "var": 0.08, "road": "foot", "icon": "walk",    "accel": 0.8},
    {"id": "jog",      "name": "Jog",          "kmh": 9.0, "profile": "steady",  "var": 0.07, "road": "foot", "icon": "run",     "accel": 1.0},
    {"id": "run",      "name": "Run",          "kmh": 13.0, "profile": "steady", "var": 0.06, "road": "foot", "icon": "run",     "accel": 1.2},
    {"id": "bike",     "name": "Bike",         "kmh": 18.0, "profile": "steady", "var": 0.10, "road": "bike", "icon": "bike",    "accel": 1.0},
    {"id": "scooter",  "name": "E-Scooter",    "kmh": 24.0, "profile": "steady", "var": 0.05, "road": "bike", "icon": "scooter", "accel": 1.2},
    {"id": "city",     "name": "City Drive",   "kmh": 40.0, "profile": "city",   "var": 0.12, "road": "car",  "icon": "car",     "accel": 2.0},
    {"id": "traffic",  "name": "Traffic",      "kmh": 22.0, "profile": "traffic","var": 0.35, "road": "car",  "icon": "traffic", "accel": 1.6},
    {"id": "highway",  "name": "Highway",      "kmh": 105.0,"profile": "steady", "var": 0.06, "road": "car",  "icon": "highway", "accel": 2.5},
    {"id": "train",    "name": "Train",        "kmh": 140.0,"profile": "steady", "var": 0.03, "road": None,   "icon": "train",   "accel": 0.8},
    {"id": "plane",    "name": "Plane",        "kmh": 780.0,"profile": "steady", "var": 0.02, "road": None,   "icon": "plane",   "accel": 6.0},
]
PRESET_BY_ID = {p["id"]: p for p in PRESETS}

# Widely shared "safe wait" chart used by location-based game players (distance km -> minutes).
COOLDOWN_TABLE = [
    (1, 0.5), (2, 1), (4, 2), (10, 8), (12, 9), (15, 11), (20, 13), (25, 15), (30, 18),
    (65, 22), (81, 25), (100, 35), (250, 45), (500, 65), (750, 80), (1000, 100), (1500, 120),
]


def cooldown_minutes(km: float) -> float:
    if km < 0.5:
        return 0
    for d, m in COOLDOWN_TABLE:
        if km <= d:
            return m
    return 120


# --------------------------------------------------------------------- geo --
def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_EARTH * math.asin(min(1.0, math.sqrt(h)))


def offset(p, north_m: float, east_m: float):
    lat = p[0] + math.degrees(north_m / R_EARTH)
    lon = p[1] + math.degrees(east_m / (R_EARTH * max(0.01, math.cos(math.radians(p[0])))))
    return (lat, lon)


def bearing_vec(a, b) -> Tuple[float, float]:
    """Unit (north, east) vector from a to b (flat approximation, fine for short segments)."""
    n = (b[0] - a[0])
    e = (b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    L = math.hypot(n, e) or 1.0
    return n / L, e / L


def densify_great_circle(a, b, step_km=50.0):
    """Points along the great circle a->b (so long straight flights look right on the map)."""
    d = haversine(a, b) / 1000
    n = max(1, int(d / step_km))
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    delta = d * 1000 / R_EARTH
    if delta == 0:
        return [a, b]
    out = []
    for i in range(n + 1):
        f = i / n
        A = math.sin((1 - f) * delta) / math.sin(delta)
        B = math.sin(f * delta) / math.sin(delta)
        x = A * math.cos(la1) * math.cos(lo1) + B * math.cos(la2) * math.cos(lo2)
        y = A * math.cos(la1) * math.sin(lo1) + B * math.cos(la2) * math.sin(lo2)
        z = A * math.sin(la1) + B * math.sin(la2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out


class Path:
    def __init__(self, pts: List[Tuple[float, float]]):
        clean = [tuple(pts[0])]
        for p in pts[1:]:
            if haversine(clean[-1], p) > 0.05:
                clean.append(tuple(p))
        if len(clean) == 1:
            clean.append(clean[0])
        self.pts = clean
        self.cum = [0.0]
        for a, b in zip(clean, clean[1:]):
            self.cum.append(self.cum[-1] + haversine(a, b))
        self.length = self.cum[-1]

    def at(self, d: float):
        """(point, (north,east) heading) at distance d along the path."""
        d = max(0.0, min(self.length, d))
        lo, hi = 0, len(self.cum) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid
        a, b = self.pts[lo], self.pts[hi]
        seg = self.cum[hi] - self.cum[lo]
        f = 0 if seg == 0 else (d - self.cum[lo]) / seg
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), bearing_vec(a, b)

    def reversed(self) -> "Path":
        return Path(list(reversed(self.pts)))


# ------------------------------------------------------------- speed model --
class SpeedModel:
    """Produces a realistic, smoothly-changing speed for a preset + user target speed."""

    def __init__(self):
        self.current = 0.0  # m/s
        self.noise = 0.0
        self.stop_left = 0.0
        self.next_event_m = self._next_gap("steady")
        self.traffic_target = 1.0

    @staticmethod
    def _next_gap(profile):
        if profile == "city":
            return random.uniform(250, 800)     # traffic lights / stop signs
        if profile == "traffic":
            return random.uniform(80, 350)      # stop-and-go
        return float("inf")

    def tick(self, dt: float, target_mps: float, preset: dict, moved_m: float) -> float:
        profile, var, accel = preset["profile"], preset["var"], preset["accel"]
        # smoothed random variation (Ornstein-Uhlenbeck style)
        self.noise += (-self.noise * 0.15 + random.gauss(0, 0.35)) * dt
        self.noise = max(-2.5, min(2.5, self.noise))
        desired = target_mps * (1 + var * self.noise)

        if profile in ("city", "traffic"):
            if self.next_event_m == float("inf"):
                self.next_event_m = self._next_gap(profile)
            self.next_event_m -= moved_m
            if self.stop_left > 0:
                self.stop_left -= dt
                desired = 0.0
            elif self.next_event_m <= 0:
                # decide: full stop or slowdown
                if profile == "city":
                    self.stop_left = random.choice([0, 0, random.uniform(8, 45)])
                else:
                    self.stop_left = random.uniform(3, 25) if random.random() < 0.55 else 0
                    self.traffic_target = random.uniform(0.25, 1.0)
                self.next_event_m = self._next_gap(profile)
            if profile == "traffic":
                desired *= self.traffic_target
        else:
            self.next_event_m = float("inf")

        desired = max(0.0, desired)
        accel = max(accel, target_mps / 8.0)   # custom high speeds still get up to speed in a few seconds
        step = accel * dt
        self.current += max(-step * 1.5, min(step, desired - self.current))
        return max(0.0, self.current)


# ------------------------------------------------------------------ engine --
class Motion:
    def __init__(self, device, store):
        self.device = device
        self.store = store
        self.mode = "idle"            # idle | route | joystick
        self.base: Optional[Tuple[float, float]] = None   # position without wobble
        self.path: Optional[Path] = None
        self.pos_d = 0.0
        self.paused = False
        self.forward = True
        self.speed = SpeedModel()
        self.cur_speed = 0.0
        self.joy = (0.0, 0.0)
        self.joy_t = 0.0
        self.wobble = [0.0, 0.0]      # current lateral/along offset in metres
        self.trip = {"started": 0, "distance": 0.0}
        self.last_jump = None         # {"t":..., "km":..., "minutes":...}
        self._last_drift = 0.0
        self._task: Optional[asyncio.Task] = None
        self.finished_note = None
        last = store.state.data.get("last")
        if last:
            self.base = tuple(last)

    # --- settings helpers
    @property
    def preset(self) -> dict:
        return PRESET_BY_ID.get(self.store.settings.get("preset"), PRESET_BY_ID["walk"])

    @property
    def target_kmh(self) -> float:
        c = self.store.settings.get("custom_kmh")
        return float(c) if c else self.preset["kmh"]

    def start(self):
        self._task = asyncio.create_task(self._loop())

    # --- commands
    async def teleport(self, lat, lon):
        prev = self.device.current or self.base
        self.stop()
        await self.device.set(lat, lon)
        self.base = (lat, lon)
        self._remember()
        if prev:
            km = haversine(prev, (lat, lon)) / 1000
            mins = cooldown_minutes(km)
            self.last_jump = {"t": time.time(), "km": round(km, 2), "minutes": mins} if mins else None
        st = self.store.state.data["stats"]
        st["teleports"] = st.get("teleports", 0) + 1

    def start_route(self, pts, loop_mode=None):
        self.path = Path(pts)
        self.pos_d = 0.0
        self.forward = True
        self.paused = False
        self.mode = "route"
        self.speed = SpeedModel()
        self.trip = {"started": time.time(), "distance": 0.0}
        self.finished_note = None
        if loop_mode:
            self.store.update_settings({"loop_mode": loop_mode})

    def pause(self, on: bool):
        self.paused = on

    def stop(self):
        self.mode = "idle"
        self.path = None
        self.paused = False
        self.cur_speed = 0.0

    def joystick(self, x: float, y: float):
        mag = math.hypot(x, y)
        if mag > 1:
            x, y = x / mag, y / mag
        self.joy = (x, y)
        self.joy_t = time.time()
        if mag > 0.05 and self.mode != "joystick":
            if self.base is None and self.device.current:
                self.base = self.device.current
            self.mode = "joystick"
            self.path = None
            self.speed = SpeedModel()

    # --- status
    def status(self) -> dict:
        s = {
            "mode": self.mode,
            "paused": self.paused,
            "speed_kmh": round(self.cur_speed * 3.6, 1),
            "target_kmh": self.target_kmh,
            "preset": self.preset["id"],
            "finished": self.finished_note,
        }
        if self.mode == "route" and self.path:
            remaining = (self.path.length - self.pos_d) if self.forward else self.pos_d
            eta = remaining / max(0.3, self.target_kmh / 3.6)
            s["route"] = {
                "length": round(self.path.length),
                "done": round(self.pos_d if self.forward else self.path.length - self.pos_d),
                "eta_s": int(eta),
                "elapsed_s": int(time.time() - self.trip["started"]),
                "travelled": round(self.trip["distance"]),
            }
        if self.last_jump:
            left = self.last_jump["minutes"] * 60 - (time.time() - self.last_jump["t"])
            if left > 0:
                s["cooldown"] = {"left_s": int(left), "km": self.last_jump["km"], "minutes": self.last_jump["minutes"]}
        return s

    # --- internals
    def _remember(self):
        if self.base:
            self.store.state.data["last"] = list(self.base)

    def _apply_wobble(self, p, heading, moving: bool):
        if not self.store.settings.get("wobble"):
            return p
        amp = 2.5 if self.target_kmh < 30 else 1.2
        if not moving:
            amp = 1.5
        for i in (0, 1):
            self.wobble[i] += random.gauss(0, amp * 0.25) - self.wobble[i] * 0.2
            self.wobble[i] = max(-amp, min(amp, self.wobble[i]))
        hn, he = heading
        # lateral = perpendicular to heading, along = small forward/back jitter
        lat_m, along_m = self.wobble[0], self.wobble[1] * 0.4
        north = -he * lat_m + hn * along_m
        east = hn * lat_m + he * along_m
        return offset(p, north, east)

    async def _loop(self):
        last_save = time.time()
        while True:
            t0 = time.monotonic()
            try:
                await self._step()
            except Exception as e:  # device hiccup: device layer handles reconnecting
                log.debug("motion step failed: %r", e)
            if time.time() - last_save > 10:
                self._remember()
                self.store.state.save()
                last_save = time.time()
            await asyncio.sleep(max(0.05, TICK - (time.monotonic() - t0)))

    async def _step(self):
        if not self.device.connected:
            return
        if self.mode == "route" and self.path and not self.paused:
            await self._step_route()
        elif self.mode == "joystick":
            await self._step_joystick()
        elif self.mode == "idle" and self.store.settings.get("idle_drift") and self.base and self.device.current:
            if time.time() - self._last_drift > 3:
                self._last_drift = time.time()
                p = self._apply_wobble(self.base, (1, 0), False)
                await self.device.set(*p)

    async def _step_route(self):
        moved = self.cur_speed * TICK
        self.cur_speed = self.speed.tick(TICK, self.target_kmh / 3.6, self.preset, moved)
        d = self.cur_speed * TICK
        self.trip["distance"] += d
        st = self.store.state.data["stats"]
        st["distance_m"] = st.get("distance_m", 0) + d
        self.pos_d += d if self.forward else -d
        end = False
        if self.pos_d >= self.path.length and self.forward:
            self.pos_d = self.path.length
            end = True
        elif self.pos_d <= 0 and not self.forward:
            self.pos_d = 0
            end = True
        p, (hn, he) = self.path.at(self.pos_d)
        heading = (hn, he) if self.forward else (-hn, -he)
        self.base = p
        await self.device.set(*self._apply_wobble(p, heading, True))
        if end:
            mode = self.store.settings.get("loop_mode", "once")
            if mode == "pingpong":
                self.forward = not self.forward
            elif mode == "repeat":
                closed = haversine(self.path.pts[0], self.path.pts[-1]) < 30
                if closed:
                    self.pos_d = 0.0
                else:
                    self.forward = not self.forward  # avoid an instant jump back to the start
            else:
                self.finished_note = time.time()
                self.stop()
                self._remember()

    async def _step_joystick(self):
        x, y = self.joy
        if time.time() - self.joy_t > 1.2:
            x = y = 0.0
        mag = math.hypot(x, y)
        target = (self.target_kmh / 3.6) * mag
        self.cur_speed = self.speed.tick(TICK, target, {**self.preset, "profile": "steady"}, self.cur_speed * TICK)
        if mag < 0.05 and self.cur_speed < 0.05:
            self.mode = "idle"
            self.cur_speed = 0.0
            self._remember()
            return
        if not self.base:
            return
        hn, he = (y / mag, x / mag) if mag > 0 else (1, 0)
        d = self.cur_speed * TICK
        self.base = offset(self.base, hn * d, he * d)
        self.store.state.data["stats"]["distance_m"] = self.store.state.data["stats"].get("distance_m", 0) + d
        await self.device.set(*self._apply_wobble(self.base, (hn, he), True))
