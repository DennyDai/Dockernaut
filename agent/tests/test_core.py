import json
import os
import random
import tempfile
import unittest
from pathlib import Path

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
