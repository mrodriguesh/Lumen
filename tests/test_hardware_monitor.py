import unittest
from pathlib import Path
import re
from lumen import hardware

WEB = Path(__file__).resolve().parent.parent / "lumen" / "web"


class HardwareMonitorTests(unittest.TestCase):
    def test_cpu_info(self):
        info = hardware.cpu_info()
        self.assertIn("name", info)
        self.assertIn("logical", info)
        self.assertGreaterEqual(info["logical"], 1)
        self.assertIn("cores_label", info)
        self.assertIn("ghz", info)

    def test_cpu_usage(self):
        sys_pct, app_pct = hardware.cpu_usage()
        self.assertIsInstance(sys_pct, float)
        self.assertIsInstance(app_pct, float)
        self.assertGreaterEqual(sys_pct, 0.0)
        self.assertLessEqual(sys_pct, 100.0)
        self.assertGreaterEqual(app_pct, 0.0)
        self.assertLessEqual(app_pct, 100.0)

    def test_ram_usage(self):
        ram = hardware.ram_usage()
        self.assertIn("total_gb", ram)
        self.assertIn("used_gb", ram)
        self.assertIn("system_pct", ram)
        self.assertIn("app_mb", ram)
        self.assertGreaterEqual(ram["total_gb"], 0.0)
        self.assertGreaterEqual(ram["system_pct"], 0.0)
        self.assertLessEqual(ram["system_pct"], 100.0)

    def test_monitor_stats_payload(self):
        stats = hardware.monitor_stats()
        self.assertIn("cpu", stats)
        self.assertIn("ram", stats)
        self.assertIn("engines", stats)
        self.assertIsInstance(stats["engines"], list)
        self.assertGreaterEqual(len(stats["engines"]), 3)
        self.assertTrue(any(e["id"] == "whisper" for e in stats["engines"]))

    def test_ui_markup_and_icons(self):
        html = (WEB / "index.html").read_text("utf-8")
        self.assertIn('id="open-monitor"', html)
        self.assertIn('id="sys-monitor-pop"', html)

        svg = (WEB / "icons.svg").read_text("utf-8")
        self.assertIn('id="cpu"', svg)
        self.assertIn('id="ram"', svg)
        self.assertIn('id="gpu"', svg)


if __name__ == "__main__":
    unittest.main()

