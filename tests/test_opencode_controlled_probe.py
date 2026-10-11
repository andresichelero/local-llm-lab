from __future__ import annotations

import unittest

from benchmark.opencode_controlled_probe import (
    calibration_gate,
    child_task_calls,
    derive_profile,
    read_only_smoke_gate,
    workflow_gate,
)


def event(tool: str, input_value: dict, status: str = "completed") -> dict:
    return {
        "type": "tool_use",
        "part": {
            "tool": tool,
            "state": {"status": status, "input": input_value},
        },
    }


class ControlledProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "agent": {
                "build": {
                    "steps": 10,
                    "permission": {
                        "task": {
                            "*": "deny",
                            "repo-explorer": "allow",
                            "independent-reviewer": "allow",
                        }
                    },
                }
            }
        }

    def test_profile_variants_keep_base_immutable_and_bound_steps(self) -> None:
        smoke = derive_profile(self.base, "smoke")
        control = derive_profile(self.base, "control")
        treatment = derive_profile(self.base, "treatment")
        self.assertEqual(self.base["agent"]["build"]["steps"], 10)
        self.assertEqual(smoke["agent"]["build"]["steps"], 10)
        self.assertEqual(control["agent"]["build"]["steps"], 20)
        self.assertEqual(control["agent"]["build"]["permission"]["task"], {"*": "deny"})
        self.assertEqual(
            treatment["agent"]["build"]["permission"]["task"],
            {"*": "deny", "repo-explorer": "allow", "independent-reviewer": "allow"},
        )

    def test_child_calls_require_completed_task_events(self) -> None:
        events = [
            event("task", {"subagent_type": "repo-explorer", "description": "inspect"}),
            event("task", {"subagent_type": "independent-reviewer"}, "running"),
            event("read", {"filePath": "x"}),
        ]
        self.assertEqual(child_task_calls(events), ["repo-explorer"])

    def test_read_only_smoke_requires_names_completed_child_and_no_changes(self) -> None:
        names = "test_ignores_blank_and_comment_lines, test_splits_on_first_equals_and_trims, test_strips_matching_quotes"
        completed = [event("task", {"subagent_type": "repo-explorer"})]
        self.assertTrue(read_only_smoke_gate(completed, names, []))
        self.assertFalse(read_only_smoke_gate(completed, names, ["changed.py"]))
        self.assertFalse(read_only_smoke_gate([], names, []))
        self.assertFalse(read_only_smoke_gate(completed, "test_alpha", []))
        self.assertFalse(read_only_smoke_gate(completed, names + ", test_extra", []))

    def test_calibration_requires_success_and_treatment_children_in_order(self) -> None:
        children = ["repo-explorer", "independent-reviewer"]
        self.assertTrue(calibration_gate("control", True, []))
        self.assertFalse(calibration_gate("control", True, ["repo-explorer"]))
        self.assertTrue(calibration_gate("treatment", True, children))
        self.assertFalse(calibration_gate("treatment", False, children))
        self.assertFalse(calibration_gate("treatment", True, list(reversed(children))))
        self.assertFalse(calibration_gate("treatment", True, [*children, "repo-explorer"]))

    def test_treatment_workflow_requires_tests_before_review_and_review_output(self) -> None:
        events = [
            event("task", {"subagent_type": "repo-explorer"}),
            {"type": "tool_use", "part": {"tool": "edit", "state": {"status": "completed", "input": {}}}},
            {"type": "tool_use", "part": {"tool": "bash", "state": {"status": "completed", "input": {"command": "python -m unittest"}, "metadata": {"exit": 0}}}},
            event("task", {"subagent_type": "independent-reviewer"}),
        ]
        events[-1]["part"]["state"]["output"] = "Reviewed the diff and passing tests; scope is correct."
        self.assertTrue(workflow_gate("treatment", True, events))
        events[-1]["part"]["state"]["output"] = ""
        self.assertFalse(workflow_gate("treatment", True, events))
        events[-1]["part"]["state"]["output"] = "Reviewed the diff and passing tests; scope is correct."
        events[2]["part"]["state"]["input"] = {"command": "python -m compileall"}
        self.assertFalse(workflow_gate("treatment", True, events))
        events[2]["part"]["state"]["input"] = {"command": "python -m unittest"}
        events[2]["part"]["state"]["metadata"]["exit"] = 1
        self.assertFalse(workflow_gate("treatment", True, events))
        events[2]["part"]["state"]["metadata"]["exit"] = 0
        events[1], events[2] = events[2], events[1]
        self.assertFalse(workflow_gate("treatment", True, events))
        events[1], events[2] = events[2], events[1]
        events.append({"type": "tool_use", "part": {"tool": "edit", "state": {"status": "completed", "input": {}}}})
        self.assertFalse(workflow_gate("treatment", True, events))


if __name__ == "__main__":
    unittest.main()
