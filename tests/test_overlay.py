import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from omookaway.overlay import OverlayProcess


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminate = Mock()
        self.wait = AsyncMock(return_value=17)


class OverlayProcessContractTest(unittest.IsolatedAsyncioTestCase):
    def test_qml_exposes_the_overlay_contract_without_asserting_visual_details(self):
        source = (Path(__file__).parents[1] / "omookaway" / "break_overlay.qml").read_text()

        self.assertIn("model: Quickshell.screens", source)
        self.assertIn("WlrKeyboardFocus.Exclusive", source)
        self.assertIn("break_remaining_seconds", source)
        self.assertIn('["omookaway", "finish-break"]', source)
        self.assertIn('"overlay-ready"', source)
        self.assertIn('"overlay-failed"', source)
        self.assertIn("readinessTimeout", source)

    async def test_launch_uses_a_dedicated_quickshell_process(self):
        process = FakeProcess()
        spawn = AsyncMock(return_value=process)
        failed = AsyncMock()
        overlay = OverlayProcess(Path("/overlay/shell.qml"), failed, spawn=spawn)

        await overlay.launch()

        spawn.assert_awaited_once_with("qs", "--path", "/overlay/shell.qml")
        self.assertTrue(overlay.running)
        await asyncio.sleep(0)
        failed.assert_awaited_once_with("Break overlay exited with status 17")

    async def test_deliberate_release_does_not_report_a_crash(self):
        process = FakeProcess()
        process.wait = AsyncMock()
        spawn = AsyncMock(return_value=process)
        failed = AsyncMock()
        overlay = OverlayProcess(Path("/overlay/shell.qml"), failed, spawn=spawn)
        await overlay.launch()

        await overlay.release()

        process.terminate.assert_called_once_with()
        process.wait.assert_awaited_once_with()
        failed.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
