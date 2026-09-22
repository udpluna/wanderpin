"""iPhone connection: developer-disk mount, iOS 17+ tunnel, location simulation, auto-reconnect."""
import asyncio
import logging
import time
from contextlib import AsyncExitStack
from typing import Optional

from pymobiledevice3.exceptions import AlreadyMountedError
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import auto_mount

from .config import TRANSPORT

log = logging.getLogger("wanderpin.device")


class DeveloperModeOff(Exception):
    pass


def friendly_error(e: Exception) -> str:
    name = type(e).__name__
    msg = str(e)
    if isinstance(e, DeveloperModeOff):
        return msg
    if "Usbmux" in name or "NoDevice" in name or "ConnectionFailed" in name or "usbmux" in msg.lower():
        return ("No iPhone found. Plug it in with a data cable, unlock it and tap “Trust”. "
                "On Windows, Apple Devices (Microsoft Store) or iTunes must be installed.")
    if "PasswordRequired" in name or "Pairing" in name or "NotPaired" in name:
        return "Unlock your iPhone and tap “Trust This Computer”, then try again."
    if "Timeout" in name or "timed out" in msg.lower():
        return "The iPhone took too long to answer. Unplug it, plug it back in, unlock it and try again."
    return f"{name}: {msg}" if msg else name


class Device:
    def __init__(self):
        self.stack: Optional[AsyncExitStack] = None
        self.loc: Optional[LocationSimulation] = None
        self.info: dict = {}
        self.current: Optional[tuple] = None   # last location sent to the phone
        self.state = "disconnected"            # disconnected | connecting | connected | reconnecting
        self.step = ""                         # human readable connect progress
        self.error: Optional[str] = None
        self.want_connected = False
        self.lock = asyncio.Lock()
        self._watch: Optional[asyncio.Task] = None
        self.auto_reconnect = True

    @property
    def connected(self) -> bool:
        return self.loc is not None

    def status(self) -> dict:
        return {"state": self.state, "step": self.step, "error": self.error,
                "device": self.info or None, "current": self.current}

    async def connect(self, quiet=False):
        async with self.lock:
            self.want_connected = True
            self.state = "connecting" if not quiet else "reconnecting"
            self.error = None
            try:
                await self._connect()
                self.state = "connected"
                self.step = ""
                if self.current:  # restore location after a reconnect
                    await self.set(*self.current)
            except Exception as e:
                await self._teardown()
                self.state = "reconnecting" if quiet else "disconnected"
                self.error = friendly_error(e)
                if not quiet:
                    log.warning("connect failed: %s", self.error)
                raise
            finally:
                self._ensure_watchdog()

    async def _connect(self):
        await self._teardown()
        self.step = "Looking for iPhone…"
        lockdown = await create_using_usbmux()
        conn = getattr(getattr(lockdown, "service", None), "mux_device", None)
        self.info = {
            "name": lockdown.all_values.get("DeviceName", "iPhone"),
            "ios": lockdown.product_version,
            "model": lockdown.all_values.get("ProductType", ""),
            "udid": lockdown.udid,
            "wifi": bool(conn and getattr(conn, "connection_type", "USB") != "USB"),
        }
        log.info("Found %s (iOS %s)", self.info["name"], self.info["ios"])
        try:
            dev_mode = await lockdown.get_developer_mode_status()
        except Exception:
            dev_mode = True
        if not dev_mode:
            raise DeveloperModeOff(
                "Developer Mode is off on the iPhone. Turn it on in Settings › Privacy & Security › "
                "Developer Mode (the phone will restart), then connect again.")
        self.step = "Preparing developer tools (first time downloads ~20 MB)…"
        try:
            await auto_mount(lockdown)
        except AlreadyMountedError:
            pass
        self.step = "Opening secure tunnel…"
        stack = AsyncExitStack()
        try:
            if TRANSPORT == "tunneld":
                from pymobiledevice3.tunneld.api import get_tunneld_devices
                rsds = await get_tunneld_devices()
                rsd = next((r for r in rsds if r.udid == lockdown.udid), rsds[0] if rsds else None)
                if rsd is None:
                    raise RuntimeError("No tunnel found. Is the admin tunnel window running?")
            else:
                from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
                rsd = await stack.enter_async_context(UserspaceRsdTunnel(serial=lockdown.udid))
            self.step = "Starting location service…"
            dvt = await stack.enter_async_context(DvtProvider(rsd))
            self.loc = await stack.enter_async_context(LocationSimulation(dvt))
            self.stack = stack
        except BaseException:
            await stack.aclose()
            raise
        log.info("Connected")

    async def _teardown(self):
        self.loc = None
        if self.stack:
            try:
                await asyncio.wait_for(self.stack.aclose(), 5)
            except Exception:
                pass
        self.stack = None

    async def disconnect(self, reset_location=False):
        async with self.lock:
            self.want_connected = False
            if reset_location and self.loc:
                try:
                    await self.loc.clear()
                except Exception:
                    pass
                self.current = None
            await self._teardown()
            self.state = "disconnected"
            self.step = ""

    async def reveal_developer_mode(self):
        from pymobiledevice3.services.amfi import AmfiService
        lockdown = await create_using_usbmux()
        await AmfiService(lockdown).reveal_developer_mode_option_in_ui()

    async def set(self, lat: float, lon: float):
        if not self.loc:
            raise RuntimeError("iPhone not connected")
        try:
            await asyncio.wait_for(self.loc.set(lat, lon), 8)
        except Exception:
            self.loc = None
            self.state = "reconnecting" if self.want_connected and self.auto_reconnect else "disconnected"
            self.error = "Connection to the iPhone was lost."
            raise
        self.current = (lat, lon)

    async def clear(self):
        if self.loc:
            await self.loc.clear()
        self.current = None

    def _ensure_watchdog(self):
        if not self._watch or self._watch.done():
            self._watch = asyncio.create_task(self._watchdog())

    async def _watchdog(self):
        """Reconnect automatically when the cable wiggles / phone locks / tunnel drops."""
        while True:
            await asyncio.sleep(4)
            if self.want_connected and self.auto_reconnect and not self.connected and not self.lock.locked():
                try:
                    await self.connect(quiet=True)
                    log.info("Reconnected")
                except Exception:
                    pass


class DemoDevice(Device):
    """Pretend iPhone for testing the UI and taking store screenshots (WANDERPIN_DEMO=1)."""

    async def _connect(self):
        self.step = "Looking for iPhone…"
        await asyncio.sleep(0.6)
        self.info = {"name": "Demo iPhone", "ios": "18.6", "model": "iPhone16,1", "udid": "DEMO", "wifi": False}
        self.loc = True  # truthy marker

    async def _teardown(self):
        self.loc = None

    async def set(self, lat, lon):
        if not self.loc:
            raise RuntimeError("iPhone not connected")
        self.current = (lat, lon)

    async def clear(self):
        self.current = None

    async def reveal_developer_mode(self):
        return None
