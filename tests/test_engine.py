import unittest

from omookaway.engine import Config, Engine


class EngineAcceptanceTest(unittest.TestCase):
    def test_active_use_reaches_one_upcoming_break_and_warning(self):
        engine = Engine(Config(), now=0)

        active = engine.apply({"type": "activity", "active": True}, now=0)
        almost_due = engine.apply({"type": "time"}, now=1799)
        warning = engine.apply({"type": "time"}, now=1800)

        self.assertEqual(active["state"], "work_interval")
        self.assertEqual(active["work_interval_seconds"], 1800)
        self.assertEqual(almost_due["active_elapsed_seconds"], 1799)
        self.assertEqual(almost_due["progress"], 1799 / 1800)
        self.assertEqual(warning["state"], "warning")
        self.assertTrue(warning["upcoming_break"])
        self.assertEqual(warning["deadline_in_seconds"], 20)
        self.assertEqual(warning["permitted_commands"], [])

    def test_idle_time_does_not_advance_active_elapsed_time(self):
        engine = Engine(Config(), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=600)
        idle = engine.apply({"type": "activity", "active": False}, now=600)
        still_idle = engine.apply({"type": "time"}, now=1600)
        resumed = engine.apply({"type": "activity", "active": True}, now=1600)
        advanced = engine.apply({"type": "time"}, now=1700)

        self.assertEqual(idle["state"], "idle")
        self.assertEqual(still_idle["active_elapsed_seconds"], 600)
        self.assertEqual(resumed["state"], "work_interval")
        self.assertEqual(advanced["active_elapsed_seconds"], 700)

    def test_restored_warning_remains_owed(self):
        engine = Engine(Config(), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=1800)

        restored = Engine.restore(engine.snapshot(now=1805), now=9000)

        self.assertEqual(restored.status(now=9000)["state"], "warning")
        self.assertTrue(restored.status(now=9000)["upcoming_break"])
        self.assertEqual(restored.status(now=9000)["deadline_in_seconds"], 15)

    def test_warning_deadline_is_based_on_when_active_use_became_due(self):
        engine = Engine(Config(), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)

        warning = engine.apply({"type": "time"}, now=1800.5)

        self.assertEqual(warning["deadline_in_seconds"], 19.5)


if __name__ == "__main__":
    unittest.main()
