import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from omookaway import cli


class ShellCommandContractTest(unittest.TestCase):
    def test_activity_observer_uses_the_published_idle_threshold(self):
        observer = (
            Path(__file__).parents[1] / "integrations" / "activity" / "shell.qml"
        ).read_text()

        self.assertIn("idle_threshold_seconds", observer)
        self.assertIn("watchChanges: true", observer)

    def test_activity_observer_forwards_logind_lock_and_sleep_signals(self):
        observer = (
            Path(__file__).parents[1] / "integrations" / "activity" / "shell.qml"
        ).read_text()

        self.assertIn("PrepareForSleep", observer)
        self.assertIn("member='Lock'", observer)
        self.assertIn("member='Unlock'", observer)
        self.assertIn('"omookaway", "lock"', observer)
        self.assertIn('"omookaway", "suspend"', observer)

    def test_shell_widget_invokes_the_public_start_break_command(self):
        widget = (
            Path(__file__).parents[1]
            / "integrations"
            / "omarchy-shell"
            / "BarWidget.qml"
        ).read_text()

        self.assertIn('command: ["omookaway", "start-break"]', widget)
        self.assertIn('commands.indexOf("start_manual_break")', widget)
        self.assertIn('command: ["omookaway", "resume"]', widget)
        self.assertIn('commands.indexOf("resume")', widget)

    def test_start_break_sends_the_manual_break_command(self):
        output = StringIO()
        request = AsyncMock(return_value={"state": "starting_break"})

        with (
            patch("sys.argv", ["omookaway", "start-break"]),
            patch.object(cli, "request", request),
            redirect_stdout(output),
        ):
            cli.main()

        request.assert_awaited_once_with({"type": "start_manual_break"})
        self.assertEqual(json.loads(output.getvalue())["state"], "starting_break")

    def test_snooze_sends_the_public_snooze_command(self):
        output = StringIO()
        request = AsyncMock(return_value={"state": "snooze"})

        with (
            patch("sys.argv", ["omookaway", "snooze"]),
            patch.object(cli, "request", request),
            redirect_stdout(output),
        ):
            cli.main()

        request.assert_awaited_once_with({"type": "snooze"})
        self.assertEqual(json.loads(output.getvalue())["state"], "snooze")

    def test_pause_sends_the_chosen_resume_time(self):
        output = StringIO()
        request = AsyncMock(return_value={"state": "pause"})

        with (
            patch("sys.argv", ["omookaway", "pause", "2026-08-17T14:30:00-07:00"]),
            patch.object(cli, "request", request),
            redirect_stdout(output),
        ):
            cli.main()

        request.assert_awaited_once_with(
            {"type": "pause", "resume_at": "2026-08-17T14:30:00-07:00"}
        )
        self.assertEqual(json.loads(output.getvalue())["state"], "pause")

    def test_resume_sends_the_public_resume_command(self):
        output = StringIO()
        request = AsyncMock(return_value={"state": "work_interval"})

        with (
            patch("sys.argv", ["omookaway", "resume"]),
            patch.object(cli, "request", request),
            redirect_stdout(output),
        ):
            cli.main()

        request.assert_awaited_once_with({"type": "resume"})
        self.assertEqual(json.loads(output.getvalue())["state"], "work_interval")

    def test_lock_and_suspend_transitions_send_public_engine_events(self):
        request = AsyncMock(return_value={"state": "idle"})

        for argv, event in (
            (["omookaway", "lock", "locked"], {"type": "lock", "locked": True}),
            (
                ["omookaway", "suspend", "resumed"],
                {"type": "suspend", "suspended": False},
            ),
        ):
            with (
                patch("sys.argv", argv),
                patch.object(cli, "request", request),
                redirect_stdout(StringIO()),
            ):
                cli.main()

        self.assertEqual(
            [call.args[0] for call in request.await_args_list],
            [
                {"type": "lock", "locked": True},
                {"type": "suspend", "suspended": False},
            ],
        )


if __name__ == "__main__":
    unittest.main()
