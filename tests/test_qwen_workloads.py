import pytest

from benchmark.qwen_workloads import WorkspaceTools, safe_path


def test_workspace_paths_cannot_escape(tmp_path):
    for name in ("../secret", "/etc/passwd", "nested/../../secret"):
        with pytest.raises(ValueError):
            safe_path(tmp_path, name)
    assert safe_path(tmp_path, "src/a.py") == tmp_path / "src/a.py"


def test_workspace_symlink_escape_rejected(tmp_path):
    (tmp_path / "outside").symlink_to("/tmp", target_is_directory=True)
    with pytest.raises(ValueError):
        safe_path(tmp_path, "outside/secret")


def test_protected_existing_tests_cannot_be_replaced(tmp_path):
    tools = WorkspaceTools("B1", tmp_path)
    with pytest.raises(ValueError, match="protected"):
        tools.call("write", {"path": "tests/test_existing.py", "content": "pass"})


def test_only_candidate_owned_regular_files_are_written(tmp_path):
    tools = WorkspaceTools("B1", tmp_path)
    tools.call("write", {"path": "src/test.py", "content": "x=1"})
    assert (tmp_path / "src/test.py").read_text() == "x=1"
    with pytest.raises(ValueError):
        tools.call("write", {"path": ".env", "content": "x=1"})


@pytest.mark.parametrize(
    "task,phase", [("B1", 1), ("B2", 1), ("M1", 1), ("D1", 1), ("D1", 2)]
)
def test_reused_functional_oracles_accept_references_reject_seed(tmp_path, task, phase):
    from benchmark import practical_tasks_v2 as tasks
    from benchmark.practical_runtime_v2 import LAB, _grader_result

    contract = (
        tasks.M1_INDEPENDENT_CONTRACT if task == "M1" else tasks.HISTORICAL_CONTRACT
    )
    tasks.seed_task(task, tmp_path, with_skills=False, task_contract_id=contract)
    assert not _grader_result(
        task, phase, tmp_path, lab=LAB, task_contract_id=contract
    )["passed"]
    for name, content in tasks.reference_files(
        task, phase=phase, task_contract_id=contract
    ).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert _grader_result(task, phase, tmp_path, lab=LAB, task_contract_id=contract)[
        "passed"
    ]


def test_development_roundtrip_reaches_trusted_grading(tmp_path):
    import json
    from benchmark import practical_tasks_v2 as tasks
    from benchmark.qwen_workloads import run_development

    class ReferenceClient:
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                files = tasks.reference_files("B1")
                files["tests/test_agent.py"] = tasks.checks_source("B1")
                calls = [
                    {
                        "id": "c" + str(i),
                        "type": "function",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps({"path": path, "content": content}),
                        },
                    }
                    for i, (path, content) in enumerate(files.items())
                ]
                calls.append(
                    {
                        "id": "tests",
                        "type": "function",
                        "function": {"name": "run_tests", "arguments": "{}"},
                    }
                )
                message = {"role": "assistant", "content": None, "tool_calls": calls}
            else:
                message = {"role": "assistant", "content": "Done"}
            return {"choices": [{"message": message, "finish_reason": "stop"}]}

    result = run_development(ReferenceClient(), "python_fix", tmp_path)
    assert result["status"] == "complete"
    assert result["functional_correct"] is True
    assert (tmp_path / "phase-1.zip").is_file()
