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
from pymobiledevice3.services.mobile_image_mounter import (
    PersonalizedImageMounter, fetch_personalized_ddi,
)

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
        self.gps_reset = None  # None | pending | sent | failed; not a GPS readback
        self._cleanup_task = None
        self.cleanup_error = None
        self.cleanup_timeout = 5
        self._ddi_task = None

    @property
    def connected(self) -> bool:
        return self.loc is not None

    def status(self) -> dict:
        return {"state": self.state, "step": self.step, "error": self.error,
                "device": self.info or None, "current": self.current,
                "gps_reset": self.gps_reset,
                "session_open": self.loc is not None,
                "auto_reconnect_armed": self.want_connected and self.auto_reconnect,
                "cleanup_pending": self._cleanup_task is not None and not self._cleanup_task.done(),
                "cleanup_error": self.cleanup_error}

    async def connect(self, quiet=False):
        async with self.lock:
            if self.connected and self.state == "connected":
                return
            self.want_connected = True
            self.state = "connecting" if not quiet else "reconnecting"
            self.error = None
            try:
                await asyncio.wait_for(self._connect(), 60)
                self.state = "connected"
                self.step = ""
                if self.current:  # restore location after a reconnect
                    await self._set_locked(*self.current)
            except Exception as e:
                try:
                    await self._teardown()
                except Exception as cleanup:
                    e = cleanup
                self.state = "reconnecting" if quiet and self.want_connected else "disconnected"
                self.error = friendly_error(e)
                if not quiet:
                    log.warning("connect failed: %s", self.error)
                raise e
            finally:
                self._ensure_watchdog()

    async def _connect(self):
        await self._teardown()
        self.step = "Looking for iPhone…"
        stack = AsyncExitStack()
        self.stack = stack
        try:
            lockdown = await create_using_usbmux(serial=self.info.get("udid"))
            stack.push_async_callback(lockdown.close)
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
            await self._prepare_developer_tools(lockdown)
            self.step = "Opening secure tunnel…"
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
            log.info("Connected")
        except BaseException:
            await self._teardown()
            raise

    async def _prepare_developer_tools(self, lockdown):
        self.step = "Checking the developer image on the iPhone…"
        async with PersonalizedImageMounter(lockdown=lockdown) as mounter:
            try:
                mounted = await asyncio.wait_for(mounter.is_image_mounted(mounter.IMAGE_TYPE), 12)
            except asyncio.TimeoutError as e:
                raise RuntimeError("The iPhone did not answer the developer image query. The image may already be cached; unlock the phone, reconnect the cable and try again.") from e
            if mounted:
                log.info("Developer image already mounted; skipped download and mount")
                return
            self.step = "Reading cached developer tools (downloads only if missing or outdated)…"
            if self._ddi_task is None or (self._ddi_task.done() and self._ddi_task.exception()):
                self._ddi_task = asyncio.create_task(asyncio.to_thread(fetch_personalized_ddi))
            # A cancelled connect must not start a second simultaneous cache download.
            image, manifest, trustcache = await asyncio.shield(self._ddi_task)
            self.step = "Mounting developer tools on the iPhone…"
            try:
                await asyncio.wait_for(mounter.mount(image, manifest, trustcache), 30)
            except AlreadyMountedError:
                pass

    async def _teardown(self):
        self.loc = None
        if self._cleanup_task is None and self.stack is not None:
            stack, self.stack = self.stack, None
            self._cleanup_task = asyncio.create_task(stack.aclose())
        if self._cleanup_task is None:
            return
        try:
            # Do not cancel a half-closed tunnel. Keep a strong reference and
            # block new connections until the same cleanup task has completed.
            await asyncio.wait_for(asyncio.shield(self._cleanup_task), self.cleanup_timeout)
        except Exception as e:
            self.want_connected = False
            self.cleanup_error = "Connection cleanup is incomplete. Try again shortly; restart the app if it continues to fail."
            log.error("Device cleanup failed or still pending: %r", e)
            raise RuntimeError(self.cleanup_error) from e
        else:
            self._cleanup_task = None
            self.cleanup_error = None

    async def disconnect(self, reset_location=False):
        if reset_location and (self.loc or self.current or self.gps_reset == "failed"):
            await self.clear()
            return
        async with self.lock:
            self.want_connected = False
            await self._teardown()
            self.state = "disconnected"
            self.step = ""

    async def reveal_developer_mode(self):
        from pymobiledevice3.services.amfi import AmfiService
        async with await create_using_usbmux() as lockdown:
            await AmfiService(lockdown).reveal_developer_mode_option_in_ui()

    async def set(self, lat: float, lon: float):
        async with self.lock:
            await self._set_locked(lat, lon)

    async def _set_locked(self, lat: float, lon: float):
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
        self.gps_reset = None

    async def clear(self):
        async with self.lock:
            self.want_connected = False
            self.current = None  # never replay the old location after a reset request
            self.gps_reset = "pending"
            self.error = None
            try:
                try:
                    for attempt in range(2):
                        try:
                            if not self.loc:
                                self.state = "connecting"
                                await asyncio.wait_for(self._connect(), 45)
                            await asyncio.wait_for(self.loc.clear(), 8)
                            # DVT sends no reply; this is not a real GPS readback.
                            await asyncio.sleep(0.3)
                            break
                        except Exception:
                            await self._teardown()
                            if attempt:
                                raise
                            log.warning("GPS reset channel failed; retrying on a fresh connection")
                finally:
                    await self._teardown()
                self.gps_reset = "sent"
                log.info("GPS reset command sent; simulation session and owned connections closed")
            except Exception as e:
                self.gps_reset = "failed"
                self.error = "Could not restore real GPS: " + friendly_error(e)
                log.exception("GPS reset failed")
                raise RuntimeError(self.error) from e
            finally:
                self.state = "disconnected"
                self.step = ""

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
        class DemoLocation:
            async def set(self, lat, lon):
                pass
            async def clear(self):
                pass
        self.loc = DemoLocation()

    async def _teardown(self):
        self.loc = None

    async def reveal_developer_mode(self):
        return None
