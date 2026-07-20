import json
import unittest
from unittest.mock import AsyncMock, patch

from wayweaver.adapters.adb import ADBAdapter
from wayweaver.adapters.android_ui import AndroidUI, parse_hierarchy
from wayweaver.adapters.atspi import ATSPIAdapter
from wayweaver.adapters.base import Adapter
from wayweaver.adapters.uia import UIAAdapter
from wayweaver.adapters.wayland_backends import GnomeBackend, KDotoolBackend
from wayweaver.errors import ActionError
from wayweaver.types import Capability


ANDROID_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="demo" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][1080,1920]">
    <node index="0" text="Delete" resource-id="demo:id/delete" class="android.widget.Button" package="demo" content-desc="Delete item" checkable="false" checked="false" clickable="true" enabled="true" focusable="true" focused="false" scrollable="false" long-clickable="true" password="false" selected="false" bounds="[800,1700][1040,1800]" />
  </node>
</hierarchy>"""


class FakeTransport(Adapter):
    kind = "fake"
    capabilities = frozenset({Capability.SHELL})

    def __init__(self, responses=None):
        super().__init__("transport", {})
        self.responses = responses or []
        self.calls = []

    async def available(self):
        return True, None

    async def shell(self, command, stdin=None):
        self.calls.append((command, stdin))
        response = self.responses.pop(0) if self.responses else {"available": True}
        return 0, json.dumps(response).encode(), b""


class UIAAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_state_wait_to_powershell_helper(self):
        transport = FakeTransport([{"name": "Save", "states": ["enabled"]}])
        adapter = UIAAdapter(
            "uia",
            {"transport": "local", "command": "C:\\tools\\wayweaver-uia.ps1"},
            transport,
        )

        result = await adapter.perform(
            "element.wait",
            {"name": "Save", "state": "enabled", "timeout": 3},
        )

        self.assertEqual(result["name"], "Save")
        command, stdin = transport.calls[0]
        self.assertEqual(command, "C:\\tools\\wayweaver-uia.ps1 -Action wait-state")
        self.assertEqual(
            json.loads(stdin),
            {"name": "Save", "state": "enabled", "timeout": 3},
        )


class ATSPIAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_restarts_helper_to_refresh_remote_accessibility_cache(self):
        adapter = ATSPIAdapter("atspi", {"wait_min_interval": 0}, FakeTransport())
        adapter._call = AsyncMock(
            side_effect=[
                ActionError("stale accessibility cache"),
                {"name": "Save", "states": ["enabled"]},
            ]
        )

        result = await adapter.perform(
            "element.wait",
            {"name": "Save", "timeout": 2, "interval": 0.05},
        )

        self.assertEqual(result["name"], "Save")
        self.assertEqual(adapter._call.await_count, 2)
        adapter._call.assert_awaited_with(
            "assert",
            {"name": "Save", "timeout": 2, "interval": 0.05},
        )


class AndroidUITests(unittest.IsolatedAsyncioTestCase):
    def test_parses_resource_identity_state_actions_and_bounds(self):
        elements = parse_hierarchy(ANDROID_XML)

        button = elements[1]
        self.assertEqual(button["name"], "Delete item")
        self.assertEqual(button["resource_id"], "demo:id/delete")
        self.assertEqual(button["role"], "button")
        self.assertEqual(
            button["bounds"], {"left": 800, "top": 1700, "width": 240, "height": 100}
        )
        self.assertIn("long-click", button["actions"])

    async def test_activates_freshly_resolved_element_by_center(self):
        calls = []

        async def run(*args):
            calls.append(args)
            if args[:2] == ("exec-out", "cat"):
                return ANDROID_XML
            return b""

        ui = AndroidUI(run)
        found = await ui.perform(
            "element.find",
            {"text": "Delete", "exact": True},
        )
        result = await ui.perform(
            "element.activate",
            {"resource_id": "demo:id/delete", "exact": True},
        )

        self.assertEqual(found["resource_id"], "demo:id/delete")
        self.assertEqual(result["point"], {"x": 920, "y": 1750})
        self.assertEqual(calls[-1], ("shell", "input", "tap", "920", "1750"))

    async def test_adb_advertises_elements_only_when_uiautomator_exists(self):
        adapter = ADBAdapter("android", {})
        adapter._run = AsyncMock(
            side_effect=[
                (0, b"device\n", b""),
                (1, b"", b"not found"),
                (0, b"device\n", b""),
                (0, b"/system/bin/uiautomator\n", b""),
            ]
        )

        with patch("wayweaver.adapters.adb.shutil.which", return_value="/usr/bin/adb"):
            first, _ = await adapter.available()
            without = adapter.capabilities
            second, _ = await adapter.available()
            with_uia = adapter.capabilities

        self.assertTrue(first and second)
        self.assertNotIn(Capability.ELEMENTS, without)
        self.assertIn(Capability.ELEMENTS, with_uia)


class WaylandBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_gnome_bridge_decodes_gvariant_and_dispatches_window_action(self):
        calls = []

        async def run(command, stdin=None):
            calls.append(command)
            if command.endswith("ListWindows"):
                return (
                    b"""('{"windows":[{"id":"7","title":"Editor","active":true}]}',)"""
                )
            return b"""('{"ok":true}',)"""

        backend = GnomeBackend(run)
        await backend.probe()
        windows = await backend.windows()
        await backend.window_action("focus_window", windows[0], {})

        self.assertEqual(windows[0]["title"], "Editor")
        self.assertIn("WindowAction", calls[-1])
        self.assertIn("focus_window", calls[-1])

    async def test_kdotool_returns_window_geometry_and_workspace_state(self):
        async def run(command, stdin=None):
            if "search --name" in command:
                return b"abc\n"
            if "getactivewindow" in command:
                return b"abc\n"
            if "getwindowname" in command:
                return b"Editor\norg.demo.Editor\n42\nWindow abc\n Position: 10,20\n Geometry: 800x600\n2\n"
            if command == "kdotool get_desktop":
                return b"2\n"
            if command == "kdotool get_num_desktops":
                return b"3\n"
            return b""

        backend = KDotoolBackend(run)
        windows = await backend.windows()
        workspaces = await backend.workspaces()

        self.assertEqual(
            windows[0],
            {
                "id": "abc",
                "title": "Editor",
                "class": "org.demo.Editor",
                "pid": 42,
                "desktop": 2,
                "x": 10,
                "y": 20,
                "width": 800,
                "height": 600,
                "active": True,
            },
        )
        self.assertEqual(
            [value["active"] for value in workspaces], [False, True, False]
        )


if __name__ == "__main__":
    unittest.main()
