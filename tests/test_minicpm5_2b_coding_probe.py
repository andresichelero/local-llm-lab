from __future__ import annotations

import unittest

from benchmark.minicpm5_2b_coding_probe import (
    AGENT_STEPS,
    BROKER_PORT,
    CONTEXT_TOKENS,
    GENERATION,
    MODEL,
    TASKS,
    WARMUP_TASK,
    build_rows,
    build_profile,
)


class MiniCPM5ProbeTests(unittest.TestCase):
    def test_profile_pins_identity_generation_and_isolation(self) -> None:
        profile = build_profile()

        self.assertEqual(AGENT_STEPS, 20)
        self.assertEqual(profile["model"], f"local/{MODEL['alias']}")
        self.assertIs(profile["autoupdate"], False)
        self.assertEqual(profile["subagent_depth"], 0)
        self.assertEqual(set(profile["agent"]), {"build"})
        self.assertEqual(profile["agent"]["build"]["steps"], AGENT_STEPS)
        self.assertEqual(profile["agent"]["build"]["permission"], {
            "task": {"*": "deny"},
            "bash": {"*": "allow"},
            "edit": {"*": "allow"},
            "external_directory": {"*": "deny"},
        })

        local = profile["provider"]["local"]
        self.assertEqual(local["options"]["baseURL"], f"http://127.0.0.1:{BROKER_PORT}/v1")
        self.assertEqual(set(local["models"]), {MODEL["alias"]})
        candidate = local["models"][MODEL["alias"]]
        self.assertEqual(candidate["limit"], {
            "context": CONTEXT_TOKENS, "output": GENERATION["max_tokens"]
        })
        self.assertEqual(candidate["options"], {
            key: value for key, value in GENERATION.items() if key != "max_tokens"
        })


    def test_expanded_screen_has_warmup_and_remaining_tasks(self) -> None:
        rows = build_rows()

        self.assertEqual(rows[0], {
            "block": 1,
            "stage": "warmup",
            "model": "minicpm5-2b",
            "task": WARMUP_TASK,
            "repeat": 0,
        })
        self.assertEqual([row["task"] for row in rows[1:]], list(TASKS))
        self.assertTrue(all(row["stage"] == "measurement" and row["repeat"] == 1
                            for row in rows[1:]))
        self.assertEqual([row["block"] for row in rows], list(range(1, len(rows) + 1)))
