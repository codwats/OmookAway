import json
import tempfile
import unittest
from pathlib import Path

from omookaway.daemon import StateFiles
from omookaway.engine import Config, Engine


class StateFilesTest(unittest.TestCase):
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
            self.assertEqual(status["permitted_commands"], [])
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

            self.assertEqual(restored.status(now=0)["state"], "idle")


if __name__ == "__main__":
    unittest.main()
