import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class InstallationContractTest(unittest.TestCase):
    def test_installer_places_every_mvp_component_and_starts_services(self):
        installer = (ROOT / "install.sh").read_text()

        self.assertIn("python -m pip install --user", installer)
        self.assertIn("omookaway.service", installer)
        self.assertIn("omookaway-activity.service", installer)
        self.assertIn("break_overlay.qml", (ROOT / "pyproject.toml").read_text())
        self.assertIn("integrations/activity", installer)
        self.assertIn("integrations/omarchy-shell", installer)
        self.assertIn("systemctl --user enable --now", installer)

    def test_services_have_independent_restartable_lifecycles(self):
        daemon = (ROOT / "systemd/omookaway.service").read_text()
        observer = (ROOT / "systemd/omookaway-activity.service").read_text()

        self.assertIn("Restart=on-failure", daemon)
        self.assertIn("After=omookaway.service", observer)
        self.assertIn("Requires=omookaway.service", observer)
        self.assertNotIn("Requires=omookaway-activity.service", daemon)

    def test_smoke_test_covers_real_environment_acceptance_scenarios(self):
        smoke = (ROOT / "smoke-test.sh").read_text()

        for scenario in (
            "Warning",
            "enforced Break",
            "fail-open release",
            "restart continuity",
            "multi-display",
        ):
            self.assertIn(scenario, smoke)

        self.assertIn("wait_for_state warning", smoke)
        self.assertIn("wait_for_state break", smoke)
        self.assertIn("wait_for_state enforcement_unavailable", smoke)
        self.assertIn("systemctl --user restart omookaway-activity.service", smoke)
        self.assertIn("omarchy-restart-shell", smoke)
        self.assertIn("display_count > 1", smoke)
        self.assertIn('namespace? == "omookaway-break"', smoke)

    def test_normal_operation_has_no_network_or_surveillance_interfaces(self):
        runtime = "\n".join(
            path.read_text()
            for directory in ("omookaway", "integrations", "systemd")
            for path in (ROOT / directory).rglob("*")
            if path.suffix in {".py", ".qml", ".service"}
        ).lower()

        for forbidden in (
            "http://",
            "https://",
            "curl",
            "wget",
            "requests",
            "urllib",
            "raw input",
            "window title",
            "microphone",
            "calendar",
            "meeting",
        ):
            self.assertNotIn(forbidden, runtime)


if __name__ == "__main__":
    unittest.main()
