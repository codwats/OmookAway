import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from omookaway import cli


class ShellCommandContractTest(unittest.TestCase):
    def test_shell_widget_invokes_the_public_start_break_command(self):
        widget = (
            Path(__file__).parents[1]
            / "integrations"
            / "omarchy-shell"
            / "BarWidget.qml"
        ).read_text()

        self.assertIn('command: ["omookaway", "start-break"]', widget)
        self.assertIn('commands.indexOf("start_manual_break")', widget)

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


if __name__ == "__main__":
    unittest.main()
