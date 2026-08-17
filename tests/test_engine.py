import unittest
from datetime import datetime

from omookaway.engine import Config, Engine


class EngineAcceptanceTest(unittest.TestCase):
    def test_progress_advances_only_inside_current_work_hours_window(self):
        engine = Engine(
            Config(work_hours={"monday": [["09:00", "10:00"]]}),
            now=0,
            civil_now=datetime(2026, 8, 17, 8, 55),
        )

        dormant = engine.apply(
            {"type": "activity", "active": True},
            now=0,
            civil_now=datetime(2026, 8, 17, 8, 55),
        )
        entered = engine.apply(
            {"type": "time"}, now=300, civil_now=datetime(2026, 8, 17, 9, 0)
        )
        active = engine.apply(
            {"type": "activity", "active": True},
            now=300,
            civil_now=datetime(2026, 8, 17, 9, 0),
        )
        advanced = engine.apply(
            {"type": "time"}, now=360, civil_now=datetime(2026, 8, 17, 9, 1)
        )

        self.assertEqual(dormant["state"], "dormant")
        self.assertEqual(dormant["active_elapsed_seconds"], 0)
        self.assertEqual(entered["state"], "idle")
        self.assertEqual(entered["active_elapsed_seconds"], 0)
        self.assertEqual(active["state"], "work_interval")
        self.assertEqual(advanced["active_elapsed_seconds"], 60)

    def test_a_work_hours_boundary_discards_progress_and_upcoming_break(self):
        engine = Engine(
            Config(
                work_interval_seconds=60,
                work_hours={"monday": [["09:00", "09:02"], ["09:03", "10:00"]]},
            ),
            now=0,
            civil_now=datetime(2026, 8, 17, 9, 0),
        )
        engine.apply(
            {"type": "activity", "active": True},
            now=0,
            civil_now=datetime(2026, 8, 17, 9, 0),
        )
        warning = engine.apply(
            {"type": "time"}, now=60, civil_now=datetime(2026, 8, 17, 9, 1)
        )
        dormant = engine.apply(
            {"type": "time"}, now=120, civil_now=datetime(2026, 8, 17, 9, 2)
        )
        fresh = engine.apply(
            {"type": "time"}, now=180, civil_now=datetime(2026, 8, 17, 9, 3)
        )
        active = engine.apply(
            {"type": "activity", "active": True},
            now=180,
            civil_now=datetime(2026, 8, 17, 9, 3),
        )

        self.assertTrue(warning["upcoming_break"])
        self.assertEqual(dormant["state"], "dormant")
        self.assertFalse(dormant["upcoming_break"])
        self.assertEqual(fresh["state"], "idle")
        self.assertEqual(fresh["active_elapsed_seconds"], 0)
        self.assertEqual(active["state"], "work_interval")

    def test_downtime_across_midnight_cannot_create_a_catch_up_break(self):
        config = Config(
            work_interval_seconds=60, work_hours={"monday": [["23:00", "24:00"]]}
        )
        engine = Engine(config, now=0, civil_now=datetime(2026, 8, 17, 23, 0))
        engine.apply(
            {"type": "activity", "active": True},
            now=0,
            civil_now=datetime(2026, 8, 17, 23, 0),
        )
        engine.apply(
            {"type": "time"}, now=60, civil_now=datetime(2026, 8, 17, 23, 1)
        )

        restored = Engine.restore(
            engine.snapshot(now=65),
            now=5000,
            civil_now=datetime(2026, 8, 18, 9, 0),
        )
        status = restored.status(now=5000, civil_now=datetime(2026, 8, 18, 9, 0))

        self.assertEqual(status["state"], "dormant")
        self.assertFalse(status["upcoming_break"])
        self.assertEqual(status["active_elapsed_seconds"], 0)

    def test_work_hours_and_positive_cadence_are_validated_atomically(self):
        monday_morning = datetime(2026, 8, 17, 9, 0)
        engine = Engine(
            Config(work_hours={"monday": [["09:00", "12:00"]]}),
            now=0,
            civil_now=monday_morning,
        )
        engine.apply(
            {"type": "activity", "active": True}, now=0, civil_now=monday_morning
        )

        with self.assertRaises(ValueError):
            engine.apply(
                {
                    "type": "configure",
                    "config": {
                        "work_interval_seconds": 0,
                        "warning_seconds": 10,
                        "work_hours": {
                            "monday": [["09:00", "11:00"], ["10:00", "12:00"]]
                        },
                    },
                },
                now=60,
                civil_now=datetime(2026, 8, 17, 9, 1),
            )

        status = engine.apply(
            {"type": "time"}, now=60, civil_now=datetime(2026, 8, 17, 9, 1)
        )
        self.assertEqual(status["work_interval_seconds"], 1800)
        self.assertEqual(status["active_elapsed_seconds"], 60)

        with self.assertRaises(ValueError):
            engine.apply(
                {
                    "type": "configure",
                    "config": {
                        "work_hours": {
                            "monday": [["09:00", "11:00"], ["10:00", "12:00"]]
                        }
                    },
                },
                now=60,
                civil_now=datetime(2026, 8, 17, 9, 1),
            )
        self.assertEqual(
            engine.status(60, datetime(2026, 8, 17, 9, 1))["active_elapsed_seconds"], 60
        )

    def test_configuration_change_reconciles_without_an_overdue_break(self):
        monday = datetime(2026, 8, 17, 9, 0)
        engine = Engine(
            Config(work_hours={"monday": [["09:00", "12:00"]]}), 0, monday
        )
        engine.apply({"type": "activity", "active": True}, 0, monday)
        engine.apply({"type": "time"}, 600, datetime(2026, 8, 17, 9, 10))

        shortened = engine.apply(
            {"type": "configure", "config": {"work_interval_seconds": 300}},
            600,
            datetime(2026, 8, 17, 9, 10),
        )
        removed = engine.apply(
            {
                "type": "configure",
                "config": {"work_hours": {"monday": [["13:00", "14:00"]]}},
            },
            600,
            datetime(2026, 8, 17, 9, 10),
        )

        self.assertEqual(shortened["state"], "work_interval")
        self.assertEqual(shortened["active_elapsed_seconds"], 0)
        self.assertFalse(shortened["upcoming_break"])
        self.assertEqual(removed["state"], "dormant")
        self.assertEqual(removed["active_elapsed_seconds"], 0)

    def test_warning_duration_change_applies_to_the_current_warning(self):
        monday = datetime(2026, 8, 17, 9, 0)
        engine = Engine(
            Config(
                work_interval_seconds=60,
                warning_seconds=20,
                work_hours={"monday": [["09:00", "10:00"]]},
            ),
            0,
            monday,
        )
        engine.apply({"type": "activity", "active": True}, 0, monday)
        engine.apply({"type": "time"}, 60, datetime(2026, 8, 17, 9, 1))

        changed = engine.apply(
            {"type": "configure", "config": {"warning_seconds": 40}},
            65,
            datetime(2026, 8, 17, 9, 1, 5),
        )

        self.assertEqual(changed["state"], "warning")
        self.assertEqual(changed["deadline_in_seconds"], 40)

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
