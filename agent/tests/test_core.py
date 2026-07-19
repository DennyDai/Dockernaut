import json
import os
import random
import tempfile
import unittest
from pathlib import Path

from dockernaut.adapters.x11 import X11Adapter
from dockernaut.cli import load_json
from dockernaut.config import ConfigError, load_config
from dockernaut.motion import trajectory
from dockernaut.sequence import normalize, run_sequence
from dockernaut.vision import Word, find_text


class CliTests(unittest.TestCase):
    def test_long_inline_json_is_not_treated_as_a_path(self):
        payload = {"steps": [{"type": "x" * 300}]}
        self.assertEqual(load_json(json.dumps(payload)), payload)


class ConfigTests(unittest.TestCase):
    def test_loads_targets_and_expands_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.toml"
            path.write_text('[targets.vm.ssh]\nhost="${TEST_HOST}"\n')
            os.environ["TEST_HOST"] = "example.test"
            config = load_config(path)
            self.assertEqual(config.target("vm").adapters["ssh"]["host"], "example.test")

    def test_missing_environment_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.toml"
            path.write_text('[targets.vm.ssh]\nhost="${DOCKERNAUT_MISSING_TEST}"\n')
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_rejects_scalar_adapter_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.toml"
            path.write_text('[targets.vm]\ntypo="not-an-adapter-table"\n[targets.vm.ssh]\nhost="localhost"\n')
            with self.assertRaises(ConfigError):
                load_config(path)


class MotionTests(unittest.TestCase):
    def test_trajectory_ends_exactly_at_target(self):
        points, duration = trajectory((10, 20), (500, 400), rng=random.Random(7))
        self.assertGreater(duration, 0)
        self.assertGreater(len(points), 8)
        self.assertEqual(points[-1], (500, 400))
        self.assertGreater(len(set(points)), 8)


class VisionTests(unittest.TestCase):
    def word(self, text, token, left, top, line="1"):
        return Word(text, token, 95, left, top, 50, 20, ("1", "1", "1", line))

    def test_region_disambiguates_visible_text(self):
        words = [
            self.word("Target", "target", 10, 10),
            self.word("Target", "target", 700, 500, "2"),
        ]
        match = find_text(words, {"text": "target", "region": [600, 400, 900, 700]})
        self.assertEqual(match["x"], 725)
        self.assertEqual(match["matches"], 1)
        self.assertEqual(match["total_matches"], 2)

    def test_fuzzy_region_recovers_minor_ocr_error(self):
        words = [
            self.word("ferminal", "ferminal", 20, 40),
            self.word("Emulator", "emulator", 80, 40),
            self.word("Terminal", "terminal", 700, 500, "2"),
            self.word("Emulator", "emulator", 760, 500, "2"),
        ]
        match = find_text(words, {
            "text": "Terminal Emulator",
            "region": [0, 0, 220, 180],
            "fuzzy": True,
        })
        self.assertEqual(match["match"], "fuzzy")
        self.assertEqual(match["matches"], 1)
        self.assertEqual(match["total_matches"], 2)



class FakeSSH:
    def __init__(self):
        self.commands = []

    async def shell(self, command, stdin=None):
        self.commands.append(command)
        if "wmctrl -lG" in command:
            return 0, b"0x01000003  0 10 20 800 600 desktop-vm Terminal - vm@desktop-vm\\n", b""
        if "xdotool getactivewindow" in command:
            return 0, str(int("0x01000003", 16)).encode(), b""
        return 0, b"", b""


class X11Tests(unittest.IsolatedAsyncioTestCase):
    async def test_launches_application_without_visual_search(self):
        ssh = FakeSSH()
        adapter = X11Adapter("x11", {"display": ":1"}, ssh)
        result = await adapter.act("launch", {"command": "xfce4-terminal"})
        self.assertEqual(result["command"], "xfce4-terminal")
        self.assertIn("nohup sh -lc xfce4-terminal", ssh.commands[-1])

    async def test_focuses_window_by_title(self):
        ssh = FakeSSH()
        adapter = X11Adapter("x11", {"display": ":1"}, ssh)
        result = await adapter.act("focus_window", {"title": "terminal"})
        self.assertTrue(result["window"]["active"])
        self.assertIn("wmctrl -ia 0x01000003", ssh.commands[-1])

    async def test_optional_close_skips_missing_window(self):
        adapter = X11Adapter("x11", {"display": ":1"}, FakeSSH())
        result = await adapter.act("close_window", {"title": "Missing", "if_exists": True})
        self.assertTrue(result["skipped"])



class FakeController:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    async def act(self, target, action, params):
        self.calls.append((target, action, params))
        if action == self.fail:
            raise RuntimeError("expected failure")
        return {"action": action}

    async def observe(self, target, ocr):
        return {"target": target, "ocr": "failure state"}


class SequenceTests(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_explicit_and_compact_steps(self):
        self.assertEqual(normalize({"action": "click", "params": {"x": 1, "y": 2}}), ("click", {"x": 1, "y": 2}))
        self.assertEqual(normalize({"scroll": "down"}), ("scroll", {"direction": "down"}))
        self.assertEqual(normalize({"screenshot": True}), ("screenshot", {}))
        self.assertEqual(normalize({"launch": "xfce4-terminal"}), ("launch", {"command": "xfce4-terminal"}))
        self.assertEqual(normalize({"wait_window": "Terminal"}), ("wait_window", {"title": "Terminal"}))

    async def test_runs_steps_without_agent_round_trips(self):
        controller = FakeController()
        result = await run_sequence(controller, "vm", [{"click": [10, 20]}, {"type": "hello"}, {"key": "Return"}])
        self.assertTrue(result["ok"])
        self.assertEqual([call[1] for call in controller.calls], ["click", "type", "key"])

    async def test_failure_returns_completed_steps_and_observation(self):
        controller = FakeController("type")
        result = await run_sequence(controller, "vm", [{"click": [10, 20]}, {"type": "hello"}, {"key": "Return"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], 1)
        self.assertEqual(len(result["completed"]), 1)
        self.assertEqual(result["observation"]["ocr"], "failure state")


if __name__ == "__main__":
    unittest.main()
