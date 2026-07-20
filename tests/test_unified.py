import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from types import SimpleNamespace
from wayweaver.adapters.base import Adapter
from wayweaver.adapters.local import LocalAdapter
from wayweaver.adapters.ssh import SSHAdapter
from wayweaver.adapters.vnc import VNCAdapter
from wayweaver.adapters.wayland import WaylandAdapter
from wayweaver.controller import Controller
from wayweaver.config import TargetConfig
from wayweaver.contracts import validate_params
from wayweaver.errors import (
    ActionError,
    CapabilityError,
    ConfigError,
    ContractError,
    SurfaceError,
    error_payload,
)
from wayweaver.operations import API_VERSION, OPERATIONS
from wayweaver.router import Router
from wayweaver.sequence import normalize
from wayweaver.types import Frame
from wayweaver.types import Capability


class StubAdapter(Adapter):
    def __init__(
        self, name, kind, capabilities, *, available=True, raw=None, failure=None
    ):
        super().__init__(name, {})
        self.kind = kind
        self.capabilities = frozenset(capabilities)
        self._is_available = available
        self.raw_operations = raw or {}
        self.failure = failure

    async def available(self):
        return self._is_available, None if self._is_available else "missing"

    async def perform(self, operation, params):
        if self.failure:
            raise ActionError(self.failure)
        return {"operation": operation, "params": params}

    async def raw(self, operation, params):
        return {"operation": operation, "params": params}


class LocalAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_in_configured_environment_and_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalAdapter(
                "local",
                {
                    "cwd": directory,
                    "environment": {"WAYWEAVER_LOCAL_TEST": "native"},
                },
            )
            available, reason = await adapter.available()
            code, stdout, stderr = await adapter.shell(
                'printf "%s:%s:" "$WAYWEAVER_LOCAL_TEST" "$PWD"; cat',
                b"payload",
            )

        self.assertTrue(available)
        self.assertIsNone(reason)
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.decode(),
            f"native:{Path(directory)}:payload",
        )
        self.assertEqual(stderr, b"")

    async def test_shell_result_distinguishes_transport_and_command_success(self):
        adapter = LocalAdapter("local", {})

        failed = await adapter.perform(
            "shell.execute",
            {"command": "exit 7"},
        )
        accepted = await adapter.perform(
            "shell.execute",
            {"command": "exit 7", "allowed_exit_codes": [0, 7]},
        )

        self.assertFalse(failed["success"])
        self.assertEqual(failed["exit_code"], 7)
        self.assertTrue(accepted["success"])
        with self.assertRaisesRegex(ActionError, "shell command exited 7"):
            await adapter.perform(
                "shell.execute",
                {"command": "exit 7", "check": True},
            )

    def test_router_resolves_desktop_adapter_through_local_transport(self):
        router = Router(
            TargetConfig(
                "host",
                ("x11", "local"),
                {
                    "x11": {
                        "kind": "x11",
                        "transport": "local",
                        "display": ":0",
                    },
                    "local": {"kind": "local"},
                },
            )
        )

        self.assertIs(router.adapters["x11"].transport, router.adapters["local"])

    def test_desktop_adapter_requires_shell_capable_transport(self):
        with self.assertRaisesRegex(ConfigError, "shell-capable transport"):
            Router(
                TargetConfig(
                    "broken",
                    (),
                    {
                        "x11": {
                            "kind": "x11",
                            "transport": "missing",
                        },
                    },
                )
            )


class SSHAdapterTests(unittest.IsolatedAsyncioTestCase):
    def test_defaults_to_accepting_only_new_host_keys(self):
        adapter = SSHAdapter("ssh", {"host": "example"})
        args, _, temporary = adapter._argv()

        self.assertIn("StrictHostKeyChecking=accept-new", args)
        self.assertNotIn("UserKnownHostsFile=/dev/null", args)
        self.assertIsNone(temporary)

    async def test_availability_requires_a_successful_remote_probe(self):
        adapter = SSHAdapter("ssh", {"host": "example"})
        adapter.shell = AsyncMock(return_value=(255, b"", b"permission denied"))

        with patch("wayweaver.adapters.ssh.shutil.which", return_value="/usr/bin/ssh"):
            available, reason = await adapter.available()
            cached = await adapter.available()

        self.assertFalse(available)
        self.assertEqual(reason, "permission denied")
        self.assertEqual(cached, (False, "permission denied"))
        adapter.shell.assert_awaited_once_with("true")


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def router(self, adapters, prefer=()):
        router = object.__new__(Router)
        router.target = TargetConfig("test", tuple(prefer), {})
        router.adapters = {adapter.name: adapter for adapter in adapters}
        router.status = {}
        router.probed_at = 0.0
        return router

    async def test_semantic_operation_falls_back_only_when_declared(self):
        semantic = StubAdapter("atspi", "atspi", {Capability.ELEMENTS}, available=False)
        visual = StubAdapter("x11", "x11", {Capability.CAPTURE, Capability.POINTER})
        router = self.router([semantic, visual], ("atspi", "x11"))

        adapter, fallback = await router.select_operation("element.activate")
        self.assertIs(adapter, visual)
        self.assertTrue(fallback)
        with self.assertRaises(CapabilityError):
            await router.select_operation("element.list")

    async def test_raw_operations_are_opt_in_and_availability_gated(self):
        available = StubAdapter("live", "test", set(), raw={"inspect": "Inspect state"})
        unavailable = StubAdapter(
            "dead", "test", set(), available=False, raw={"mutate": "Mutate state"}
        )
        router = self.router([available, unavailable])

        self.assertNotIn("raw:live", await router.operation_routes())
        routes = await router.operation_routes(include_raw=True)
        self.assertEqual(routes["raw:live"]["operations"], {"inspect": "Inspect state"})
        self.assertNotIn("raw:dead", routes)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_element_failure_retries_through_visual_fallback(self):
        semantic = StubAdapter(
            "atspi",
            "atspi",
            {Capability.ELEMENTS},
            failure="accessible element not found",
        )
        visual = StubAdapter("x11", "x11", {Capability.CAPTURE, Capability.POINTER})
        router = object.__new__(Router)
        router.target = TargetConfig("test", ("atspi", "x11"), {})
        router.adapters = {"atspi": semantic, "x11": visual}
        router.status = {}
        router.probed_at = 0.0
        controller = object.__new__(Controller)
        controller.routers = {"test": router}
        controller.observations = {}

        async def locate(target, locator, click):
            return {"target": target, "text": locator["text"], "clicked": click}

        controller.locate = locate
        result = await controller.perform(
            "test",
            "element.activate",
            {"selector": {"name": "Save"}},
        )

        self.assertTrue(result["backend"]["fallback"])
        self.assertEqual(result["backend"]["adapter"], "x11")
        self.assertEqual(
            result["backend"]["fallback_reason"], "accessible element not found"
        )
        self.assertTrue(result["data"]["clicked"])

    async def test_returns_versioned_envelope_and_prepares_selector(self):
        applications = StubAdapter(
            "x11",
            "x11",
            {Capability.APPLICATIONS},
        )
        applications.perform = AsyncMock(
            return_value={"application": {}, "matches": 1, "pid": 123}
        )
        router = object.__new__(Router)
        router.target = TargetConfig("test", ("x11",), {})
        router.adapters = {"x11": applications}
        router.status = {}
        router.probed_at = 0.0
        controller = object.__new__(Controller)
        controller.routers = {"test": router}
        controller.observations = {}

        result = await controller.perform(
            "test",
            "application.open",
            {"selector": {"name": "Terminal"}},
        )

        self.assertEqual(result["api_version"], API_VERSION)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"]["adapter"], "x11")
        applications.perform.assert_awaited_once_with(
            "application.open", {"name": "Terminal"}
        )
        self.assertIn("elapsed_ms", result["timing"])

    async def test_rejects_flat_params_and_stale_surfaces(self):
        pointer = StubAdapter("x11", "x11", {Capability.POINTER})
        router = object.__new__(Router)
        router.target = TargetConfig("test", ("x11",), {})
        router.adapters = {"x11": pointer}
        router.status = {}
        router.probed_at = 0.0
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(SimpleNamespace(cache_dir=Path(directory)))
            controller.routers = {"test": router}

        with self.assertRaises(ContractError):
            await controller.perform(
                "test",
                "pointer.click",
                {"x": 10, "y": 20},
            )
        with self.assertRaises(SurfaceError):
            await controller.perform(
                "test",
                "pointer.click",
                {
                    "point": {"x": 10, "y": 20},
                    "space": "surface",
                    "surface_id": "stale",
                },
            )

    async def test_observe_returns_coordinate_provenance(self):
        capture = StubAdapter("capture", "x11", {Capability.CAPTURE})
        router = object.__new__(Router)
        router.target = TargetConfig("test", ("capture",), {})
        router.adapters = {"capture": capture}
        router.status = {}
        router.probed_at = 0.0
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(SimpleNamespace(cache_dir=Path(directory)))
            controller.routers = {"test": router}
            controller.capture = AsyncMock(
                return_value=(Frame(b"png", 1600, 900, "x11"), "capture")
            )

            result = await controller.observe("test")

        self.assertEqual(result["surface"]["space"], "screen")
        self.assertEqual(result["surface"]["width"], 1600)
        self.assertEqual(result["surface"]["adapter"], "capture")
        self.assertEqual(
            controller.observations["test"]["observation_id"],
            result["observation_id"],
        )

    async def test_provenance_survives_processes_and_rejects_replaced_sessions(self):
        class PointerAdapter(StubAdapter):
            async def perform(self, operation, params):
                return {"x": params["x"], "y": params["y"], "action": "move"}

        capture = PointerAdapter(
            "desktop",
            "x11",
            {Capability.CAPTURE, Capability.POINTER},
        )
        capture.config["session_id"] = "session-one"
        router = object.__new__(Router)
        router.target = TargetConfig("test", ("desktop",), {})
        router.adapters = {"desktop": capture}
        router.status = {}
        router.probed_at = 0.0
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(cache_dir=Path(directory))
            first = Controller(config)
            first.routers = {"test": router}
            first.capture = AsyncMock(
                return_value=(Frame(b"png", 1600, 900, "x11"), "desktop")
            )
            observation = await first.observe("test")

            second = Controller(config)
            second.routers = {"test": router}
            moved = await second.perform(
                "test",
                "pointer.move",
                {
                    "point": {"x": 10, "y": 20},
                    "space": "surface",
                    "surface_id": observation["surface"]["id"],
                    "observation_id": observation["observation_id"],
                },
            )
            capture.config["session_id"] = "session-two"
            with self.assertRaisesRegex(SurfaceError, "replaced desktop session"):
                await second.perform(
                    "test",
                    "pointer.move",
                    {
                        "point": {"x": 10, "y": 20},
                        "space": "surface",
                        "surface_id": observation["surface"]["id"],
                        "observation_id": observation["observation_id"],
                    },
                )

        self.assertEqual(moved["data"]["x"], 10)


class OperationTests(unittest.TestCase):
    def test_registry_separates_semantic_visual_and_fallback_operations(self):
        self.assertEqual(OPERATIONS["application.open"].tier, "semantic")
        self.assertEqual(OPERATIONS["pointer.click"].tier, "visual")
        self.assertEqual(
            OPERATIONS["element.activate"].fallback,
            frozenset({Capability.CAPTURE, Capability.POINTER}),
        )
        self.assertEqual(OPERATIONS["element.wait"].tier, "semantic")
        self.assertFalse(OPERATIONS["element.wait"].fallback)

    def test_canonical_compact_steps_are_normalized(self):
        self.assertEqual(
            normalize({"application.open": "Terminal"}),
            ("application.open", {"selector": {"name": "Terminal"}}),
        )
        self.assertEqual(
            normalize({"window.focus": "Terminal"}),
            ("window.focus", {"selector": {"title": "Terminal"}}),
        )
        self.assertEqual(
            normalize({"pointer.click": [12, 34]}),
            (
                "pointer.click",
                {"point": {"x": 12, "y": 34}, "space": "screen"},
            ),
        )
        self.assertEqual(
            normalize({"element.activate": "Save"}),
            ("element.activate", {"selector": {"name": "Save"}}),
        )
        self.assertEqual(
            normalize({"element.wait": "Save"}),
            ("element.wait", {"selector": {"name": "Save"}}),
        )
        self.assertEqual(
            normalize({"window.fullscreen": "Chrome"}),
            ("window.fullscreen", {"selector": {"title": "Chrome"}}),
        )

    def test_error_payload_uses_stable_machine_fields(self):
        payload = error_payload(
            ContractError("bad params", details={"operation": "pointer.click"})
        )

        self.assertEqual(payload["code"], "INVALID_PARAMS")
        self.assertFalse(payload["retryable"])
        self.assertEqual(payload["details"]["operation"], "pointer.click")

    def test_selectors_require_identity_and_reject_conflicting_text_modes(self):
        schema = OPERATIONS["element.find"].params_schema

        with self.assertRaises(ContractError):
            validate_params("element.find", schema, {"selector": {}})
        with self.assertRaises(ContractError):
            validate_params(
                "element.find",
                schema,
                {
                    "selector": {
                        "text": "Save",
                        "exact": True,
                        "contains": True,
                    }
                },
            )


class FakeToolSSH:
    def __init__(self, tools):
        self.tools = tools
        self.commands = []

    async def available(self):
        return True, None

    async def shell(self, command, stdin=None):
        self.commands.append((command, stdin))
        return 0, ("\n".join(self.tools) + "\n").encode(), b""


class WaylandTests(unittest.IsolatedAsyncioTestCase):
    async def test_capabilities_and_raw_tools_follow_live_session(self):
        ssh = FakeToolSSH(
            ["wayweaver-applications", "wl-copy", "wl-paste", "wtype", "ydotool"]
        )
        adapter = WaylandAdapter("wayland", {"display": "wayland-1"}, ssh)

        available, reason = await adapter.available()

        self.assertTrue(available)
        self.assertIsNone(reason)
        self.assertEqual(
            adapter.capabilities,
            frozenset(
                {
                    Capability.APPLICATIONS,
                    Capability.CLIPBOARD,
                    Capability.KEYBOARD,
                    Capability.POINTER,
                }
            ),
        )
        self.assertNotIn(Capability.SCROLL, adapter.capabilities)
        self.assertEqual(
            adapter.raw_operations,
            {
                "wtype": "Call wtype with an argument list",
                "ydotool": "Call ydotool with an argument list",
            },
        )


class FakeRFB:
    width = 1600
    height = 900

    def __init__(self):
        self.pointers = []

    def pointer(self, x, y, buttons=0):
        self.pointers.append((x, y, buttons))

    def close(self):
        pass


class PointerTakeoverTests(unittest.TestCase):
    def test_vnc_reanchors_absolute_pointer_before_trajectory(self):
        adapter = VNCAdapter("vnc", {"host": "example", "port": 5900})
        adapter.pointer = (800, 450)
        connection = FakeRFB()
        adapter._connect = lambda: connection

        result = adapter._act_sync("click", {"x": 900, "y": 500, "duration_ms": 0})

        self.assertEqual(connection.pointers[0], (800, 450, 0))
        self.assertEqual(connection.pointers[-2:], [(900, 500, 1), (900, 500, 0)])
        self.assertEqual(result["x"], 900)
        self.assertEqual(result["y"], 500)


if __name__ == "__main__":
    unittest.main()
