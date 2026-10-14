from __future__ import annotations

import os
import shlex
from pathlib import Path
import tempfile
import unittest

from benchmark.opencode_controlled_probe import (
    _isolated_environment,
    _last_wildcard_action,
    _terminal_deny_rule,
    calibration_gate,
    child_task_calls,
    derive_profile,
    read_only_smoke_gate,
    require_runtime_revision,
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
                },
                "repo-explorer": {"mode": "subagent", "permission": {"edit": "deny", "bash": "deny"}},
                "independent-reviewer": {"mode": "subagent", "permission": {"edit": "deny", "bash": "deny"}},
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
        for profile in (smoke, control, treatment):
            for agent in profile["agent"].values():
                self.assertEqual(agent["permission"]["external_directory"], {"*": "deny"})
            for child in ("repo-explorer", "independent-reviewer"):
                self.assertEqual(profile["agent"][child]["permission"]["bash"], {"*": "deny"})
                self.assertEqual(profile["agent"][child]["permission"]["edit"], {"*": "deny"})
        for tool in ("bash", "edit"):
            self.assertEqual(smoke["agent"]["build"]["permission"][tool], {"*": "deny"})
            self.assertEqual(control["agent"]["build"]["permission"][tool], {"*": "allow"})
            self.assertEqual(treatment["agent"]["build"]["permission"][tool], {"*": "allow"})

    def test_permission_gate_rejects_rules_that_follow_a_broad_deny(self) -> None:
        base = [
            {"permission": "*", "pattern": "*", "action": "allow"},
            {"permission": "external_directory", "pattern": "*", "action": "ask"},
            {"permission": "external_directory", "pattern": "/tmp/opencode/*", "action": "allow"},
            {"permission": "external_directory", "pattern": "*", "action": "deny"},
            {"permission": "external_directory", "pattern": "/isolated/tool-output/*", "action": "allow"},
        ]
        safe_output_exception = {("external_directory", "/isolated/tool-output/*", "allow")}
        self.assertEqual(_last_wildcard_action(base, "external_directory"), "deny")
        self.assertTrue(_terminal_deny_rule(base, "external_directory", safe_output_exception))
        self.assertFalse(
            _terminal_deny_rule(
                [*base, {"permission": "external_directory", "pattern": "/outside/*", "action": "allow"}],
                "external_directory",
                safe_output_exception,
            )
        )
        self.assertFalse(
            _terminal_deny_rule(
                [*base, {"permission": "*", "pattern": "*", "action": "ask"}],
                "external_directory",
                safe_output_exception,
            )
        )

    def test_runtime_revision_accepts_stderr_banner(self) -> None:
        self.assertEqual(require_runtime_revision("", "version: d81235049", "d81235049"), "version: d81235049")
        with self.assertRaisesRegex(RuntimeError, "Unexpected llama.cpp build"):
            require_runtime_revision("version: other", "", "d81235049")

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
        events.pop()
        events.append({"type": "tool_use", "part": {"tool": "bash", "state": {"status": "completed", "input": {"command": "python -m unittest"}, "metadata": {"exit": 0}}}})
        self.assertFalse(workflow_gate("treatment", True, events))
        events.pop()
        events.append({"type": "tool_use", "part": {"tool": "read", "state": {"status": "completed", "input": {}}}})
        self.assertFalse(workflow_gate("treatment", True, events))

    def test_isolated_environment_creates_guarded_edit_executable_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            workspace = run_dir / "workspace"
            install_root = Path(temp) / "install"
            workspace.mkdir(parents=True)
            env = _isolated_environment("opencode", run_dir, install_root, workspace)
            script = run_dir / "bin" / "guarded-edit"
            self.assertTrue(script.is_file())
            guarded_edit_path = Path(__file__).resolve().parents[1] / "benchmark/guarded_edit.py"
            self.assertEqual(
                script.read_text(encoding="utf-8"),
                f'#!/usr/bin/env bash\nexec python3 {shlex.quote(str(guarded_edit_path))} "$@"\n',
            )
            if os.name != "nt":
                self.assertEqual(script.stat().st_mode & 0o777, 0o755)
            self.assertTrue(env["PATH"].startswith(str(run_dir / "bin") + ":"))


if __name__ == "__main__":
    unittest.main()
