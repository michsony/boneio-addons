import copy
import importlib.util
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "components/boneio_irrigation" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
expand, validation = load("expand"), load("validation")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.c = yaml.safe_load((ROOT / "examples/esp32-irrigation.yaml").read_text(encoding="utf8"))["boneio_irrigation"][0]["configuration"]

    def test_valid_installation_and_calendar_dates(self):
        validation.validate(self.c)
        self.assertGreater(len(expand.settings(self.c)), 24)
        generated = expand.expand_controller(self.c)
        self.assertEqual(len(generated["sprinkler"]), len(self.c["zones"]))
        self.assertNotIn("BIS_", str(generated))

    def test_duplicate_physical_output_rejected(self):
        self.c["zones"][1]["channel"] = self.c["zones"][0]["channel"]
        with self.assertRaises(ValueError): validation.validate(self.c)

    def test_duration_limits_rejected(self):
        self.c["zones"][0]["seconds"] = self.c["zones"][0]["max"] + 1
        with self.assertRaises(ValueError): validation.validate(self.c)

    def test_incompatible_pump_rejected(self):
        self.c["zones"][0]["allowedPumps"] = []
        with self.assertRaises(ValueError): validation.validate(self.c)

    def test_parallel_needs_explicit_hydraulic_groups(self):
        self.c["parallel"] = 2
        with self.assertRaises(ValueError): validation.validate(self.c)

    def test_snapshot_signature_stable_after_capacity_key_reorder(self):
        def boot(c): return expand.expand_controller(c)["esphome.on_boot"][0]["then"][0]["lambda"]
        before = boot(self.c)
        self.c["capacity"] = dict(reversed(list(self.c["capacity"].items())))
        self.assertEqual(before, boot(self.c))

    def test_raw_gpio_switch_not_declared_twice(self):
        self.c["zones"][0]["channel"] = "switch:existing_relay"
        generated = expand.expand_controller(self.c)
        self.assertFalse(any(v["id"] == "existing_relay" for v in generated["switch"]))
        self.assertEqual(generated["sprinkler"][0]["valves"][0]["valve_switch_id"], "existing_relay")


if __name__ == "__main__": unittest.main()
