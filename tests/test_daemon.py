import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from omookaway.daemon import Daemon, StateFiles
from omookaway.engine import Config, Engine


class StateFilesTest(unittest.TestCase):
    def test_missing_state_starts_with_dormant_activity_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")

            status = files.load(now=0).status(now=30)

            self.assertEqual(status["state"], "activity_unavailable")
            self.assertEqual(status["active_elapsed_seconds"], 0)
            self.assertFalse(status["degraded_wall_clock_mode"])

    def test_published_status_and_restore_reconcile_work_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            monday = datetime(2026, 8, 17, 9, 0)
            engine = Engine(
                Config(work_hours={"monday": [["09:00", "10:00"]]}), 0, monday
            )
            engine.apply({"type": "activity", "active": True}, 0, monday)
            engine.apply({"type": "time"}, 300, datetime(2026, 8, 17, 9, 5))

            files.publish(engine, 300, datetime(2026, 8, 17, 9, 5))
            restored = files.load(9000, datetime(2026, 8, 17, 11, 0))

            published = json.loads((root / "status.json").read_text())
            self.assertEqual(published["state"], "work_interval")
            self.assertEqual(
                restored.status(9000, datetime(2026, 8, 17, 11, 0))["state"],
                "dormant",
            )

    def test_published_status_is_authoritative_and_state_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            engine = Engine(Config(), now=0)
            engine.apply({"type": "activity", "active": True}, now=0)
            engine.apply({"type": "time"}, now=1800)

            files.publish(engine, now=1805)
            status = json.loads((root / "status.json").read_text())
            restored = files.load(now=9000)

            self.assertEqual(status["state"], "warning")
            self.assertEqual(status["permitted_commands"], ["snooze", "pause"])
            self.assertEqual(restored.status(now=9000)["deadline_in_seconds"], 15)

    def test_invalid_persisted_lifecycle_fails_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "config": {
                            "work_interval_seconds": 1800,
                            "warning_seconds": 20,
                        },
                        "state": "not-a-state",
                        "active": True,
                        "active_elapsed_seconds": 100,
                        "warning_remaining_seconds": None,
                    }
                )
            )

            restored = files.load(now=0)

            self.assertEqual(restored.status(now=0)["state"], "activity_unavailable")
            self.assertIn("saved state", restored.status(now=0)["state_error"])

    def test_persisted_state_contains_only_cadence_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            engine = Engine(Config(), now=0)

            files.publish(engine, now=0)

            persisted = json.loads((root / "state.json").read_text())
            forbidden = {
                "active", "input_active", "away_sources",
                "activity_observation_available", "raw_inputs", "activity_timeline",
                "application", "window", "calendar", "meeting", "microphone",
                "telemetry", "history",
            }
            self.assertTrue(forbidden.isdisjoint(persisted))
            self.assertEqual(persisted["version"], 1)

    def test_invalid_persisted_values_fail_safe_with_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            (root / "state.json").write_text(json.dumps({"version": 1, "config": {}}))

            restored = files.load(now=0)

            status = restored.status(now=0)
            self.assertEqual(status["state"], "activity_unavailable")
            self.assertIn(str(root / "state.json"), status["state_error"])


class DaemonOverlayContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_daemon_restart_relaunches_an_owed_break_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            engine = Engine(Config(work_interval_seconds=1, warning_seconds=1), now=0)
            engine.apply({"type": "activity", "active": True}, now=0)
            engine.apply({"type": "time"}, now=2)
            files.publish(engine, now=2)
            overlay = AsyncMock()
            daemon = Daemon(root / "engine.sock", files, overlay=overlay)

            await daemon.restore_effects()

            overlay.launch.assert_awaited_once_with()
            self.assertEqual(daemon.engine.status(daemon.engine.last_at)["state"], "starting_break")

    async def test_runtime_observer_loss_publishes_authoritative_dormant_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            daemon = Daemon(root / "engine.sock", files, overlay=object())
            daemon.engine.apply(
                {"type": "activity", "active": True}, now=daemon.engine.last_at
            )
            reader = AsyncMock()
            reader.readline.return_value = (
                b'{"type":"activity_observation","available":false}\n'
            )
            writer = Mock()
            writer.drain = AsyncMock()
            writer.wait_closed = AsyncMock()

            await daemon.handle(reader, writer)

            response = json.loads(writer.write.call_args.args[0])
            published = json.loads((root / "status.json").read_text())
            self.assertEqual(response["state"], "activity_unavailable")
            self.assertEqual(published["state"], "activity_unavailable")
            self.assertFalse(published["degraded_wall_clock_mode"])

    async def test_rejected_manual_break_returns_the_authoritative_state(self):
        class Writer:
            def __init__(self):
                self.value = b""

            def write(self, value):
                self.value += value

            async def drain(self):
                pass

            def close(self):
                pass

            async def wait_closed(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daemon = Daemon(
                root / "engine.sock",
                StateFiles(root / "state.json", root / "status.json"),
                overlay=object(),
            )
            daemon.engine = Engine(Config(), now=0)
            daemon.engine.apply({"type": "start_manual_break"}, now=0)
            reader = AsyncMock()
            reader.readline.return_value = b'{"type":"start_manual_break"}\n'
            writer = Writer()

            await daemon.handle(reader, writer)

            response = json.loads(writer.value)
            self.assertEqual(response["error"], "Manual Break is not available")
            self.assertEqual(response["state"], "starting_break")
            self.assertEqual(response["permitted_commands"], [])

    async def test_process_launch_failure_returns_to_an_owed_warning(self):
        class FailedOverlay:
            def __init__(self):
                self.release = AsyncMock()

            async def launch(self):
                raise OSError("quickshell unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            daemon = Daemon(root / "engine.sock", files, overlay=FailedOverlay())
            daemon.engine = Engine(Config(work_interval_seconds=1, warning_seconds=1), 0)
            daemon.engine.apply({"type": "activity", "active": True}, 0)
            requested = daemon.engine.apply({"type": "time"}, 2)

            await daemon.dispatch_effects(requested)

            status = daemon.engine.status(2)
            self.assertEqual(status["state"], "warning")
            self.assertTrue(status["upcoming_break"])
            self.assertIn("quickshell unavailable", status["enforcement_error"])
            daemon.overlay.release.assert_awaited_once_with()

    async def test_overlay_process_exit_fails_open_through_the_engine_seam(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            overlay = AsyncMock()
            daemon = Daemon(root / "engine.sock", files, overlay=overlay)
            daemon.engine = Engine(
                Config(work_interval_seconds=1, warning_seconds=1), now=0
            )
            daemon.engine.apply({"type": "activity", "active": True}, now=0)
            daemon.engine.apply({"type": "time"}, now=2)

            await daemon.overlay_failed("process crashed")

            status = json.loads((root / "status.json").read_text())
            self.assertEqual(status["state"], "warning")
            self.assertTrue(status["upcoming_break"])
            self.assertEqual(status["enforcement_error"], "process crashed")
            overlay.release.assert_awaited_once_with()

            retry = daemon.engine.apply(
                {"type": "time"}, now=daemon.engine.last_at
            )
            await daemon.dispatch_effects(retry)
            overlay.launch.assert_awaited_once_with()

    async def test_display_disconnect_and_hotplug_release_partial_coverage(self):
        for error in ("display disconnected", "display topology changed"):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                overlay = AsyncMock()
                daemon = Daemon(
                    root / "engine.sock",
                    StateFiles(root / "state.json", root / "status.json"),
                    overlay=overlay,
                )
                daemon.engine = Engine(Config(), now=0)
                daemon.engine.apply({"type": "start_manual_break"}, now=0)

                await daemon.overlay_failed(error)

                status = daemon.engine.status(0)
                self.assertEqual(status["state"], "warning")
                self.assertTrue(status["upcoming_break"])
                self.assertEqual(status["enforcement_error"], error)
                overlay.release.assert_awaited_once_with()

    async def test_overlay_failure_releases_even_when_status_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = StateFiles(root / "state.json", root / "status.json")
            overlay = AsyncMock()
            daemon = Daemon(root / "engine.sock", files, overlay=overlay)
            daemon.engine = Engine(Config(), now=0)
            daemon.engine.apply({"type": "start_manual_break"}, now=0)
            files.publish = Mock(side_effect=OSError("disk full"))

            with self.assertRaisesRegex(OSError, "disk full"):
                await daemon.overlay_failed("display disconnected")

            overlay.release.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
