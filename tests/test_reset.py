"""Regression tests with a fake device transport; never touch a real phone."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_device_module():
    """Load the real Device implementation against isolated fake transport imports."""
    from unittest.mock import patch
    modules = {name: types.ModuleType(name) for name in [
        'pymobiledevice3', 'pymobiledevice3.exceptions', 'pymobiledevice3.lockdown',
        'pymobiledevice3.services', 'pymobiledevice3.services.dvt',
        'pymobiledevice3.services.dvt.instruments',
        'pymobiledevice3.services.dvt.instruments.dvt_provider',
        'pymobiledevice3.services.dvt.instruments.location_simulation',
        'pymobiledevice3.services.mobile_image_mounter', 'core.config',
    ]}
    modules['pymobiledevice3.exceptions'].AlreadyMountedError = type('AlreadyMountedError', (Exception,), {})
    modules['pymobiledevice3.lockdown'].create_using_usbmux = AsyncMock()
    modules['pymobiledevice3.services.dvt.instruments.dvt_provider'].DvtProvider = object
    modules['pymobiledevice3.services.dvt.instruments.location_simulation'].LocationSimulation = object
    modules['pymobiledevice3.services.mobile_image_mounter'].PersonalizedImageMounter = object
    modules['pymobiledevice3.services.mobile_image_mounter'].fetch_personalized_ddi = lambda: None
    modules['core.config'].TRANSPORT = 'userspace'
    spec = importlib.util.spec_from_file_location('core._device_under_test', ROOT / 'core/device.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


device_module = load_device_module()
Device = device_module.Device
from core.motion import Motion

class FakeLocation:
    def __init__(self, error=None):
        self.writes = []
        self.error = error
        self.cleared = 0
    async def set(self, lat, lon):
        self.writes.append((lat, lon))
    async def clear(self):
        if self.error:
            raise self.error
        self.cleared += 1

class FakeDevice(Device):
    def __init__(self, locations):
        super().__init__()
        self.locations = iter(locations)
        self.connections = 0
        self.teardowns = 0
    async def _connect(self):
        self.connections += 1
        self.loc = next(self.locations)
    async def _teardown(self):
        self.teardowns += 1
        self.loc = None
    def _ensure_watchdog(self):
        pass

class State:
    def __init__(self):
        self.data = {'last': [1, 2], 'stats': {'distance_m': 0, 'teleports': 0}}
    def save(self):
        pass
class Store:
    def __init__(self):
        self.state = State()
        self.settings = {'idle_drift': True, 'wobble': True, 'preset': 'walk'}

class ResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_session_is_cleared_and_released(self):
        loc = FakeLocation(); d = FakeDevice([])
        d.loc = loc; d.current = (1, 2); d.want_connected = True
        await d.clear()
        self.assertEqual(loc.cleared, 1)
        self.assertIsNone(d.loc)
        self.assertIsNone(d.current)
        self.assertFalse(d.want_connected)
        self.assertEqual(d.gps_reset, 'sent')
        self.assertEqual(d.state, 'disconnected')

    async def test_disconnected_reset_actually_opens_a_device(self):
        loc = FakeLocation(); d = FakeDevice([loc])
        await d.clear()
        self.assertEqual(d.connections, 1)
        self.assertEqual(loc.cleared, 1)

    async def test_stale_channel_retries_fresh_session(self):
        fresh = FakeLocation(); d = FakeDevice([fresh])
        d.loc = FakeLocation(OSError('lost connection'))
        await d.clear()
        self.assertEqual(fresh.cleared, 1)
        self.assertEqual(d.gps_reset, 'sent')

    async def test_failed_reset_is_not_success_and_never_replays_old_coords(self):
        bad = FakeLocation(OSError('lost connection'))
        d = FakeDevice([bad]); d.loc = bad; d.current = (1, 2); d.want_connected = True
        with self.assertRaises(RuntimeError):
            await d.clear()
        self.assertEqual(d.gps_reset, 'failed')
        self.assertIsNone(d.current)
        self.assertFalse(d.want_connected)
        self.assertIsNone(d.loc)
        self.assertIn('Could not restore real GPS', d.error)

    async def test_connect_restores_without_lock_deadlock(self):
        loc = FakeLocation(); d = FakeDevice([loc]); d.current = (1, 2)
        await asyncio.wait_for(d.connect(), 1)
        self.assertEqual(loc.writes, [(1, 2)])

    async def test_connect_after_reset_does_not_replay(self):
        first, second = FakeLocation(), FakeLocation()
        d = FakeDevice([second]); d.loc = first; d.current = (1, 2)
        await d.clear(); await d.connect()
        self.assertEqual(second.writes, [])

    async def test_clear_waits_for_inflight_write(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        loc = FakeLocation()
        async def write(lat, lon):
            entered.set(); await finish.wait(); loc.writes.append((lat, lon))
        loc.set = write
        d = FakeDevice([]); d.loc = loc
        writer = asyncio.create_task(d.set(3, 4)); await entered.wait()
        reset = asyncio.create_task(d.clear()); await asyncio.sleep(0)
        self.assertEqual(loc.cleared, 0)
        finish.set(); await writer; await reset
        self.assertIsNone(d.current)
        self.assertEqual(loc.cleared, 1)

    async def test_motion_reset_drains_writer_and_drift_cache(self):
        d = FakeDevice([]); d.loc = FakeLocation(); d.current = (1, 2)
        store = Store(); m = Motion(d, store)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def step():
            entered.set()
            try: await asyncio.sleep(100)
            finally: cancelled.set()
        m._step = step; m.start(); await entered.wait()
        await m.reset()
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(m.base)
        self.assertIsNone(store.state.data['last'])
        self.assertEqual(m.mode, 'idle')
        self.assertEqual(m.joy, (0, 0))
        m._task.cancel(); await asyncio.gather(m._task, return_exceptions=True)

    async def test_failure_still_clears_movement_cache(self):
        d = FakeDevice([FakeLocation(OSError('offline'))])
        d.loc = FakeLocation(OSError('offline')); d.current = (1, 2)
        store = Store(); m = Motion(d, store); m.mode = 'route'
        with self.assertRaises(RuntimeError): await m.reset()
        self.assertEqual(m.mode, 'idle')
        self.assertIsNone(m.base)
        self.assertIsNone(store.state.data['last'])

    async def test_disconnect_propagates_reset_failure(self):
        d = FakeDevice([FakeLocation(OSError('offline'))])
        d.loc = FakeLocation(OSError('offline'))
        with self.assertRaises(RuntimeError): await d.disconnect(reset_location=True)
        self.assertEqual(d.gps_reset, 'failed')

class MovementRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_route_cannot_stop_replacement_route(self):
        entered, release = asyncio.Event(), asyncio.Event()
        d = FakeDevice([]); d.loc = FakeLocation()
        async def send(lat, lon):
            entered.set(); await release.wait()
        d.loc.set = send
        m = Motion(d, Store())
        m.store.settings['wobble'] = False
        m.start_route([[0, 0], [0, 0.000001]])
        m.speed.tick = lambda *a: 10
        old = asyncio.create_task(m._step_route()); await entered.wait()
        m.start_route([[1, 1], [1, 2]])
        replacement = m.path
        release.set(); await old
        self.assertEqual(m.mode, 'route')
        self.assertIs(m.path, replacement)

    async def test_teleport_cannot_be_overwritten_by_old_idle_drift(self):
        entered, release = asyncio.Event(), asyncio.Event()
        d = FakeDevice([]); d.loc = FakeLocation(); d.current = (1, 2)
        async def send(lat, lon):
            if (lat, lon) == (3, 4):
                entered.set(); await release.wait()
        d.loc.set = send
        m = Motion(d, Store()); m.store.settings['wobble'] = False
        async def drifting():
            await entered.wait(); await m._step()
        m._task = asyncio.create_task(drifting())
        tp = asyncio.create_task(m.teleport(3, 4)); await entered.wait()
        await asyncio.sleep(0.01); release.set(); await tp
        await asyncio.sleep(0.01)
        try:
            self.assertEqual(d.current, (3, 4))
        finally:
            if m._task:
                m._task.cancel(); await asyncio.gather(m._task, return_exceptions=True)

class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_cleanup_is_not_cancelled_or_forgotten(self):
        from contextlib import AsyncExitStack
        finish = asyncio.Event(); ended = asyncio.Event()
        async def close():
            await finish.wait(); ended.set()
        d = Device(); d.stack = AsyncExitStack(); d.stack.push_async_callback(close)
        d.cleanup_timeout = 0.01; d.want_connected = True
        with self.assertRaises(RuntimeError): await d._teardown()
        self.assertTrue(d.status()['cleanup_pending'])
        self.assertFalse(d.want_connected)
        task = d._cleanup_task
        self.assertFalse(task.cancelled())
        finish.set()
        await asyncio.wait_for(asyncio.shield(task), 1)
        await d._teardown()
        self.assertTrue(ended.is_set()); self.assertIsNone(d._cleanup_task)

    async def test_cleanup_failure_cannot_report_reset_success(self):
        from contextlib import AsyncExitStack
        async def fail_close(): raise OSError('close failed')
        d = Device(); d.loc = FakeLocation(); d.stack = AsyncExitStack()
        d.stack.push_async_callback(fail_close)
        with self.assertRaises(RuntimeError): await d.clear()
        self.assertEqual(d.gps_reset, 'failed')
        self.assertIsNotNone(d.cleanup_error)

    async def test_already_connected_is_idempotent(self):
        d = FakeDevice([]); d.loc = FakeLocation(); d.state = 'connected'
        await d.connect(); self.assertEqual(d.connections, 0)

    async def test_mounted_image_skips_fetch_and_closes_service(self):
        from unittest.mock import patch
        class Mounter:
            IMAGE_TYPE = 'Personalized'
            closed = False
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed = True
            async def is_image_mounted(self, image_type): return True
        m = Mounter(); d = Device()
        with patch.object(device_module, 'PersonalizedImageMounter', return_value=m), patch.object(device_module, 'fetch_personalized_ddi') as fetch:
            await d._prepare_developer_tools(object())
            fetch.assert_not_called()
        self.assertTrue(m.closed)

    async def test_failed_image_query_closes_service(self):
        from unittest.mock import patch
        class Mounter:
            IMAGE_TYPE = 'Personalized'
            closed = False
            async def __aenter__(self): return self
            async def __aexit__(self, *args): self.closed = True
            async def is_image_mounted(self, image_type): raise OSError('device disconnected')
        m = Mounter(); d = Device()
        with patch.object(device_module, 'PersonalizedImageMounter', return_value=m):
            with self.assertRaises(OSError): await d._prepare_developer_tools(object())
        self.assertTrue(m.closed)

    async def test_setup_failure_closes_lockdown(self):
        from unittest.mock import patch
        lockdown = types.SimpleNamespace(all_values={}, product_version='26.6.2', udid='TEST',
            get_developer_mode_status=AsyncMock(return_value=False), close=AsyncMock())
        d = Device()
        with patch.object(device_module, 'create_using_usbmux', AsyncMock(return_value=lockdown)):
            with self.assertRaises(Exception): await d._connect()
        lockdown.close.assert_awaited_once()
        self.assertIsNone(d.stack)
        self.assertIsNone(d._cleanup_task)

if __name__ == '__main__': unittest.main()
