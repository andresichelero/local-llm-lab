from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import model_candidate_screen as screen


class ModelCandidateScreenTests(unittest.TestCase):
    def test_frozen_config_and_schedule_are_a_short_balanced_screen(self) -> None:
        config = screen.load_screen_config()
        schedule = screen.build_screen_schedule(config)

        self.assertEqual(config["experiment"], "granite-4.2-8b-short-screen-20261017-r1")
        self.assertEqual(len(schedule), 12)
        block_models = [schedule[index * 3]["model"] for index in range(4)]
        self.assertEqual(block_models, ["granite-4.2-8b", "qwen3.5-9b", "qwen3.5-9b", "granite-4.2-8b"])
        for model in config["models"]:
            for task in config["tasks"]:
                rows = [row for row in schedule if row["model"] == model and row["task"] == task]
                self.assertEqual([row["repeat"] for row in rows], [1, 2])
                self.assertTrue(all(row["stage"] == "measurement" for row in rows))

    def test_config_contract_pins_model_identity_and_runtime(self) -> None:
        config = screen.load_screen_config()
        self.assertEqual(config["models"]["granite-4.2-8b"]["sha256"],
                         "16a9369d0805f80b7377d25d87f937a90c05dc04ad79173a52001e42c9aab311")
        self.assertEqual(config["models"]["qwen3.5-9b"]["sha256"],
                         "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8")
        self.assertEqual(config["runtime"]["llama_cpp_revision"],
                         "620d2225cc436ab0b001e3200e590e3b286ef9ab")
        self.assertEqual(config["resource_requirements"]["minimum_free_vram_mib"], 7168)

    def test_blocked_readiness_never_starts_model_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readiness_root = root / "readiness"
            output_root = root / "screen"
            report = {"ready": False, "verdict": "BLOCKED", "gates": {}}
            with (
                patch.object(screen, "_port_is_free", return_value=True),
                patch.object(screen.campaign_readiness, "run_current_readiness", return_value=report),
                patch.object(screen.campaign_readiness, "input_hash_manifest",
                             return_value={"complete": True, "digest": "current", "records": []}),
                patch.object(screen.campaign_readiness, "validate_readiness_report",
                             return_value={"ready": False, "reason": "preflight_blocked"}),
                patch.object(screen, "_start_screen_server") as start_server,
            ):
                result = screen.execute_candidate_screen(
                    benchmark_root=root,
                    output_root=output_root,
                    evidence_root=readiness_root,
                )

        self.assertFalse(result["started"])
        self.assertEqual(result["status"], "not_ready")
        start_server.assert_not_called()

    def test_schedule_rejects_noncanonical_model_or_repeat_settings(self) -> None:
        config = screen.load_screen_config()
        config["schedule"]["repeats_per_model_task"] = 1
        with self.assertRaisesRegex(ValueError, "frozen screen schedule"):
            screen.validate_screen_config(config)


if __name__ == "__main__":
    unittest.main()
