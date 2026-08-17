import unittest
from datetime import datetime

from omookaway.engine import Config, Engine


class EngineAcceptanceTest(unittest.TestCase):
    def test_upcoming_break_starts_with_default_snooze_budget(self):
        engine = Engine(Config(work_interval_seconds=60), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)

        warning = engine.apply({"type": "time"}, now=60)

        self.assertEqual(warning["state"], "warning")
        self.assertEqual(warning["snoozes_remaining"], 3)
        self.assertIn("snooze", warning["permitted_commands"])

    def test_snooze_postpones_the_same_upcoming_break_then_warns_again(self):
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20), now=0
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=60)

        snoozed = engine.apply({"type": "snooze"}, now=65)
        before_expiry = engine.apply({"type": "time"}, now=364.999)
        warning = engine.apply({"type": "time"}, now=365)

        self.assertEqual(snoozed["state"], "snooze")
        self.assertEqual(snoozed["deadline_in_seconds"], 300)
        self.assertEqual(snoozed["snoozes_remaining"], 2)
        self.assertEqual(before_expiry["state"], "snooze")
        self.assertEqual(warning["state"], "warning")
        self.assertEqual(warning["deadline_in_seconds"], 20)
        self.assertEqual(warning["snoozes_remaining"], 2)
        self.assertIn("snooze", warning["permitted_commands"])

    def test_activity_changes_do_not_discard_a_snoozed_upcoming_break(self):
        engine = Engine(Config(work_interval_seconds=60), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=60)
        engine.apply({"type": "snooze"}, now=65)

        idle = engine.apply({"type": "activity", "active": False}, now=100)
        active = engine.apply({"type": "activity", "active": True}, now=101)

        self.assertEqual(idle["state"], "snooze")
        self.assertEqual(active["state"], "snooze")
        self.assertEqual(active["snoozes_remaining"], 2)

    def test_ignored_warning_after_snooze_expiry_proceeds_to_enforcement(self):
        engine = Engine(
            Config(
                work_interval_seconds=60,
                warning_seconds=20,
                snooze_seconds=300,
            ),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=60)
        engine.apply({"type": "snooze"}, now=65)

        enforced = engine.apply({"type": "time"}, now=385)

        self.assertEqual(enforced["state"], "starting_break")
        self.assertEqual(enforced["snoozes_remaining"], 2)
        self.assertEqual(enforced["requested_effects"], [{"type": "launch_break"}])

    def test_exhausted_snooze_budget_proceeds_to_enforcement(self):
        engine = Engine(
            Config(
                work_interval_seconds=60,
                warning_seconds=20,
                snooze_seconds=300,
            ),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=60)

        remaining = []
        for snoozed_at in (65, 370, 675):
            snoozed = engine.apply({"type": "snooze"}, now=snoozed_at)
            remaining.append(snoozed["snoozes_remaining"])
            warning = engine.apply({"type": "time"}, now=snoozed_at + 300)

        self.assertEqual(remaining, [2, 1, 0])
        self.assertEqual(warning["snoozes_remaining"], 0)
        self.assertNotIn("snooze", warning["permitted_commands"])
        with self.assertRaisesRegex(ValueError, "Snooze is not available"):
            engine.apply({"type": "snooze"}, now=976)

        enforced = engine.apply({"type": "time"}, now=995)
        self.assertEqual(enforced["state"], "starting_break")
        self.assertEqual(enforced["snoozes_remaining"], 0)
        self.assertEqual(enforced["requested_effects"], [{"type": "launch_break"}])

    def test_snooze_is_ignored_outside_warning(self):
        engine = Engine(Config(), now=0)

        with self.assertRaisesRegex(ValueError, "Snooze is not available"):
            engine.apply({"type": "snooze"}, now=0)

        self.assertEqual(engine.status(0)["state"], "idle")

    def test_snooze_configuration_applies_only_to_new_upcoming_breaks(self):
        engine = Engine(
            Config(
                work_interval_seconds=60,
                warning_seconds=20,
                break_seconds=100,
                snooze_seconds=300,
                snooze_budget=3,
            ),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=60)
        configured = engine.apply(
            {
                "type": "configure",
                "config": {"snooze_seconds": 30, "snooze_budget": 1},
            },
            now=65,
        )

        current = engine.apply({"type": "snooze"}, now=66)
        self.assertEqual(configured["snoozes_remaining"], 3)
        self.assertEqual(current["deadline_in_seconds"], 300)

        engine.apply({"type": "time"}, now=366)
        engine.apply({"type": "time"}, now=386)
        engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["display"],
                "covered_display_ids": ["display"],
                "input_inhibited": True,
            },
            now=386,
        )
        engine.apply({"type": "time"}, now=486)
        next_warning = engine.apply({"type": "time"}, now=546)
        next_snooze = engine.apply({"type": "snooze"}, now=547)

        self.assertEqual(next_warning["snoozes_remaining"], 1)
        self.assertEqual(next_snooze["deadline_in_seconds"], 30)

    def test_manual_break_is_permitted_during_work_hours_and_launches_immediately(self):
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, break_seconds=100),
            now=0,
        )

        idle = engine.status(now=0)
        requested = engine.apply({"type": "start_manual_break"}, now=10)

        self.assertIn("start_manual_break", idle["permitted_commands"])
        self.assertEqual(requested["state"], "starting_break")
        self.assertEqual(requested["requested_effects"], [{"type": "launch_break"}])
        self.assertNotIn("deadline_in_seconds", requested)

    def test_manual_break_uses_the_established_completion_lifecycle(self):
        engine = self._start_manual_break(overlay_ready_at=11)

        finished = engine.apply({"type": "time"}, now=111)

        self.assertEqual(finished["last_break_outcome"], "satisfied")
        self.assertEqual(finished["today_satisfied_breaks"], 1)
        self.assertEqual(finished["state"], "work_interval")
        self.assertEqual(finished["active_elapsed_seconds"], 0)
        self.assertEqual(finished["requested_effects"], [{"type": "release_break"}])

    def test_manual_break_control_supports_satisfied_and_aborted_outcomes(self):
        aborted = self._start_manual_break().apply(
            {"type": "finish_break"}, now=29.999
        )
        satisfied = self._start_manual_break().apply({"type": "finish_break"}, now=30)

        self.assertEqual(aborted["last_break_outcome"], "aborted")
        self.assertEqual(aborted["today_aborted_breaks"], 1)
        self.assertEqual(aborted["active_elapsed_seconds"], 0)
        self.assertEqual(satisfied["last_break_outcome"], "satisfied")
        self.assertEqual(satisfied["today_satisfied_breaks"], 1)
        self.assertEqual(satisfied["active_elapsed_seconds"], 0)

    def test_manual_break_is_rejected_outside_work_hours_and_when_one_is_starting(self):
        monday = datetime(2026, 8, 17, 9, 0)
        dormant = Engine(
            Config(work_hours={"monday": [["10:00", "11:00"]]}),
            now=0,
            civil_now=monday,
        )
        with self.assertRaisesRegex(ValueError, "Manual Break is not available"):
            dormant.apply({"type": "start_manual_break"}, now=0, civil_now=monday)

        engine = Engine(Config(), now=0)
        engine.apply({"type": "start_manual_break"}, now=0)
        with self.assertRaisesRegex(ValueError, "Manual Break is not available"):
            engine.apply({"type": "start_manual_break"}, now=1)

        self.assertEqual(engine.status(1)["state"], "starting_break")
        self.assertEqual(engine.status(1)["requested_effects"], [])

    def test_warning_expiry_requests_a_break_without_starting_it(self):
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, break_seconds=100),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=60)

        requested = engine.apply({"type": "time"}, now=80)

        self.assertEqual(requested["state"], "starting_break")
        self.assertTrue(requested["upcoming_break"])
        self.assertEqual(requested["requested_effects"], [{"type": "launch_break"}])
        self.assertNotIn("break_remaining_seconds", requested)

    def test_break_starts_only_after_complete_coverage_and_input_inhibition(self):
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, break_seconds=100),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=80)

        incomplete = engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["left", "right"],
                "covered_display_ids": ["left"],
                "input_inhibited": True,
            },
            now=81,
        )

        self.assertEqual(incomplete["state"], "warning")
        self.assertTrue(incomplete["upcoming_break"])
        self.assertEqual(incomplete["requested_effects"], [{"type": "release_break"}])

        engine.apply({"type": "time"}, now=101)
        started = engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["left", "right"],
                "covered_display_ids": ["right", "left"],
                "input_inhibited": True,
            },
            now=102,
        )

        self.assertEqual(started["state"], "break")
        self.assertEqual(started["break_remaining_seconds"], 100)
        self.assertEqual(started["permitted_commands"], ["finish_break"])

    def test_break_control_classifies_outcome_at_twenty_percent(self):
        def breaking_engine() -> Engine:
            engine = Engine(
                Config(work_interval_seconds=60, warning_seconds=20, break_seconds=100),
                now=0,
            )
            engine.apply({"type": "activity", "active": True}, now=0)
            engine.apply({"type": "time"}, now=80)
            engine.apply(
                {
                    "type": "overlay_ready",
                    "display_ids": ["display"],
                    "covered_display_ids": ["display"],
                    "input_inhibited": True,
                },
                now=80,
            )
            return engine

        aborted = breaking_engine().apply({"type": "finish_break"}, now=99.999)
        satisfied = breaking_engine().apply({"type": "finish_break"}, now=100)

        self.assertEqual(aborted["last_break_outcome"], "aborted")
        self.assertEqual(aborted["today_aborted_breaks"], 1)
        self.assertEqual(aborted["today_satisfied_breaks"], 0)
        self.assertEqual(satisfied["last_break_outcome"], "satisfied")
        self.assertEqual(satisfied["today_satisfied_breaks"], 1)
        self.assertEqual(satisfied["requested_effects"], [{"type": "release_break"}])
        self.assertEqual(satisfied["state"], "work_interval")
        self.assertEqual(satisfied["active_elapsed_seconds"], 0)

    def test_break_timer_expiry_is_satisfied_and_waits_for_active_use_if_idle(self):
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, break_seconds=100),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=80)
        engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["display"],
                "covered_display_ids": ["display"],
                "input_inhibited": True,
            },
            now=80,
        )
        engine.apply({"type": "activity", "active": False}, now=100)

        finished = engine.apply({"type": "time"}, now=180)

        self.assertEqual(finished["last_break_outcome"], "satisfied")
        self.assertEqual(finished["state"], "idle")
        self.assertFalse(finished["upcoming_break"])
        resumed = engine.apply({"type": "activity", "active": True}, now=181)
        self.assertEqual(resumed["state"], "work_interval")
        self.assertEqual(resumed["active_elapsed_seconds"], 0)

    def test_active_break_revalidates_display_coverage_and_fails_open(self):
        engine = self._start_break()

        failed = engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["left", "right"],
                "covered_display_ids": ["left"],
                "input_inhibited": True,
            },
            now=81,
        )

        self.assertEqual(failed["state"], "warning")
        self.assertEqual(failed["consecutive_enforcement_failures"], 1)
        self.assertEqual(failed["requested_effects"], [{"type": "release_break"}])

    def test_second_enforcement_failure_stops_until_explicit_retry(self):
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20), now=0
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=80)
        first = engine.apply({"type": "overlay_failed", "error": "not ready"}, now=81)
        retry = engine.apply({"type": "time"}, now=81)
        second = engine.apply({"type": "overlay_failed", "error": "crashed"}, now=82)

        self.assertEqual(first["state"], "warning")
        self.assertEqual(retry["state"], "starting_break")
        self.assertEqual(retry["requested_effects"], [{"type": "launch_break"}])
        self.assertEqual(second["state"], "enforcement_unavailable")
        self.assertTrue(second["upcoming_break"])
        self.assertEqual(second["permitted_commands"], ["retry_enforcement"])

        requested = engine.apply({"type": "retry_enforcement"}, now=83)
        self.assertEqual(requested["state"], "starting_break")
        self.assertEqual(requested["requested_effects"], [{"type": "launch_break"}])

    def test_daemon_restart_clears_enforcement_unavailable_for_one_fresh_attempt(self):
        engine = Engine(Config(work_interval_seconds=1, warning_seconds=1), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=2)
        engine.apply({"type": "overlay_failed"}, now=3)
        engine.apply({"type": "time"}, now=3)
        unavailable = engine.apply({"type": "overlay_failed"}, now=4)
        self.assertEqual(unavailable["state"], "enforcement_unavailable")

        restored = Engine.restore(engine.snapshot(4), now=100)
        retried = restored.apply({"type": "time"}, now=100)

        self.assertEqual(retried["state"], "starting_break")
        self.assertEqual(retried["consecutive_enforcement_failures"], 0)
        self.assertEqual(retried["requested_effects"], [{"type": "launch_break"}])

    def test_daemon_restart_revalidates_an_active_break_before_enforcing(self):
        engine = self._start_break()

        restored = Engine.restore(engine.snapshot(81), now=100)
        status = restored.status(100)

        self.assertEqual(status["state"], "warning")
        self.assertTrue(status["upcoming_break"])
        self.assertNotIn("break_remaining_seconds", status)
        retried = restored.apply({"type": "time"}, now=100)
        self.assertEqual(retried["state"], "starting_break")
        self.assertEqual(retried["requested_effects"], [{"type": "launch_break"}])

    def test_daemon_restart_clears_a_single_enforcement_failure(self):
        engine = Engine(Config(work_interval_seconds=1, warning_seconds=1), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=2)
        failed = engine.apply({"type": "overlay_failed"}, now=3)
        self.assertEqual(failed["consecutive_enforcement_failures"], 1)

        restored = Engine.restore(engine.snapshot(3), now=100)

        self.assertEqual(restored.status(100)["consecutive_enforcement_failures"], 0)

    @staticmethod
    def _start_manual_break(overlay_ready_at: float = 10) -> Engine:
        engine = Engine(Config(break_seconds=100), now=0)
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "start_manual_break"}, now=10)
        engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["display"],
                "covered_display_ids": ["display"],
                "input_inhibited": True,
            },
            now=overlay_ready_at,
        )
        return engine

    @staticmethod
    def _start_break() -> Engine:
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, break_seconds=100),
            now=0,
        )
        engine.apply({"type": "activity", "active": True}, now=0)
        engine.apply({"type": "time"}, now=80)
        engine.apply(
            {
                "type": "overlay_ready",
                "display_ids": ["left"],
                "covered_display_ids": ["left"],
                "input_inhibited": True,
            },
            now=80,
        )
        return engine

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
        self.assertEqual(warning["permitted_commands"], ["snooze", "pause"])

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

    def test_pause_preserves_work_interval_progress_until_resume(self):
        started = datetime(2026, 8, 17, 9, 0)
        engine = Engine(Config(work_interval_seconds=600), now=0, civil_now=started)
        engine.apply({"type": "activity", "active": True}, now=0, civil_now=started)
        engine.apply(
            {"type": "time"}, now=120, civil_now=datetime(2026, 8, 17, 9, 2)
        )

        paused = engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T09:12:00"},
            now=120,
            civil_now=datetime(2026, 8, 17, 9, 2),
        )
        still_paused = engine.apply(
            {"type": "time"}, now=660, civil_now=datetime(2026, 8, 17, 9, 11)
        )
        resumed = engine.apply(
            {"type": "time"}, now=720, civil_now=datetime(2026, 8, 17, 9, 12)
        )

        self.assertEqual(paused["state"], "pause")
        self.assertEqual(paused["active_elapsed_seconds"], 120)
        self.assertEqual(paused["pause_deadline"], "2026-08-17T09:12:00")
        self.assertEqual(paused["permitted_commands"], ["resume"])
        self.assertEqual(still_paused["active_elapsed_seconds"], 120)
        self.assertEqual(resumed["state"], "work_interval")
        self.assertEqual(resumed["active_elapsed_seconds"], 120)

    def test_pause_preserves_upcoming_break_and_budget_then_resumes_with_fresh_warning(self):
        started = datetime(2026, 8, 17, 9, 0)
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, snooze_budget=3),
            now=0,
            civil_now=started,
        )
        engine.apply({"type": "activity", "active": True}, 0, started)
        engine.apply({"type": "time"}, 60, datetime(2026, 8, 17, 9, 1))
        engine.apply({"type": "snooze"}, 65, datetime(2026, 8, 17, 9, 1, 5))

        paused = engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T09:10:00"},
            65,
            datetime(2026, 8, 17, 9, 1, 5),
        )
        resumed = engine.apply(
            {"type": "time"}, 600, datetime(2026, 8, 17, 9, 10)
        )

        self.assertTrue(paused["upcoming_break"])
        self.assertEqual(paused["snoozes_remaining"], 2)
        self.assertEqual(resumed["state"], "warning")
        self.assertEqual(resumed["deadline_in_seconds"], 20)
        self.assertEqual(resumed["snoozes_remaining"], 2)
        self.assertEqual(resumed["permitted_commands"], ["snooze", "pause"])

    def test_pause_rejects_invalid_past_and_unavailable_requests(self):
        now = datetime(2026, 8, 17, 9, 0)
        engine = Engine(Config(), 0, now)

        for resume_at in ("not-a-time", "2026-08-17T09:00:00", "2026-08-17T08:59:59"):
            with self.assertRaisesRegex(ValueError, "future resume time"):
                engine.apply({"type": "pause", "resume_at": resume_at}, 0, now)

        with self.assertRaisesRegex(ValueError, "Pause is not available"):
            engine.apply(
                {"type": "pause", "resume_at": "2026-08-17T10:00:00"}, 0, now
            )

    def test_work_hours_boundary_discards_a_pause_and_its_preserved_obligation(self):
        engine = Engine(
            Config(
                work_interval_seconds=60,
                work_hours={"monday": [["09:00", "09:02"], ["09:03", "10:00"]]},
            ),
            0,
            datetime(2026, 8, 17, 9, 0),
        )
        engine.apply(
            {"type": "activity", "active": True}, 0, datetime(2026, 8, 17, 9, 0)
        )
        engine.apply({"type": "time"}, 60, datetime(2026, 8, 17, 9, 1))
        engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T09:30:00"},
            60,
            datetime(2026, 8, 17, 9, 1),
        )

        dormant = engine.apply(
            {"type": "time"}, 120, datetime(2026, 8, 17, 9, 2)
        )
        fresh = engine.apply(
            {"type": "time"}, 180, datetime(2026, 8, 17, 9, 3)
        )

        self.assertEqual(dormant["state"], "dormant")
        self.assertFalse(dormant["upcoming_break"])
        self.assertEqual(fresh["state"], "idle")
        self.assertEqual(fresh["active_elapsed_seconds"], 0)

    def test_activity_changes_do_not_cancel_pause_and_early_resume_uses_latest_activity(self):
        now = datetime(2026, 8, 17, 9, 0)
        engine = Engine(Config(), 0, now)
        engine.apply({"type": "activity", "active": True}, 0, now)
        engine.apply({"type": "time"}, 60, datetime(2026, 8, 17, 9, 1))
        engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T10:00:00"},
            60,
            datetime(2026, 8, 17, 9, 1),
        )

        paused = engine.apply(
            {"type": "activity", "active": False},
            120,
            datetime(2026, 8, 17, 9, 2),
        )
        resumed = engine.apply(
            {"type": "resume"}, 180, datetime(2026, 8, 17, 9, 3)
        )

        self.assertEqual(paused["state"], "pause")
        self.assertEqual(paused["active_elapsed_seconds"], 60)
        self.assertEqual(resumed["state"], "idle")
        self.assertEqual(resumed["active_elapsed_seconds"], 60)

    def test_pause_survives_daemon_restart_with_its_absolute_deadline(self):
        now = datetime(2026, 8, 17, 9, 0)
        engine = Engine(Config(), 0, now)
        engine.apply({"type": "activity", "active": True}, 0, now)
        engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T10:00:00"}, 0, now
        )

        restored = Engine.restore(
            engine.snapshot(0), 5000, datetime(2026, 8, 17, 9, 30)
        )
        status = restored.status(5000, datetime(2026, 8, 17, 9, 30))

        self.assertEqual(status["state"], "pause")
        self.assertEqual(status["pause_deadline"], "2026-08-17T10:00:00")
        self.assertEqual(status["permitted_commands"], ["resume"])

    def test_status_reconciles_an_expired_pause_before_reporting_controls(self):
        now = datetime(2026, 8, 17, 9, 0)
        engine = Engine(Config(), 0, now)
        engine.apply({"type": "activity", "active": True}, 0, now)
        engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T09:10:00"}, 0, now
        )

        status = engine.status(600, datetime(2026, 8, 17, 9, 10))

        self.assertEqual(status["state"], "work_interval")
        self.assertEqual(status["permitted_commands"], ["start_manual_break", "pause"])
        self.assertNotIn("pause_deadline", status)

    def test_early_resume_of_upcoming_break_starts_fresh_warning_without_budget_change(self):
        now = datetime(2026, 8, 17, 9, 0)
        engine = Engine(
            Config(work_interval_seconds=60, warning_seconds=20, snooze_budget=3),
            0,
            now,
        )
        engine.apply({"type": "activity", "active": True}, 0, now)
        engine.apply({"type": "time"}, 60, datetime(2026, 8, 17, 9, 1))
        engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T10:00:00"},
            60,
            datetime(2026, 8, 17, 9, 1),
        )

        resumed = engine.apply(
            {"type": "resume"}, 120, datetime(2026, 8, 17, 9, 2)
        )

        self.assertEqual(resumed["state"], "warning")
        self.assertEqual(resumed["deadline_in_seconds"], 20)
        self.assertEqual(resumed["snoozes_remaining"], 3)

    def test_work_hours_boundary_discards_paused_work_interval_progress(self):
        engine = Engine(
            Config(work_hours={"monday": [["09:00", "09:02"]]}),
            0,
            datetime(2026, 8, 17, 9, 0),
        )
        engine.apply(
            {"type": "activity", "active": True}, 0, datetime(2026, 8, 17, 9, 0)
        )
        engine.apply({"type": "time"}, 60, datetime(2026, 8, 17, 9, 1))
        engine.apply(
            {"type": "pause", "resume_at": "2026-08-17T10:00:00"},
            60,
            datetime(2026, 8, 17, 9, 1),
        )

        dormant = engine.status(120, datetime(2026, 8, 17, 9, 2))

        self.assertEqual(dormant["state"], "dormant")
        self.assertEqual(dormant["active_elapsed_seconds"], 0)
        self.assertNotIn("pause_deadline", dormant)


if __name__ == "__main__":
    unittest.main()
