import threading
import time

from benchmark.linux_sandbox import watch_policy_deadline
from benchmark.practical_policy import BudgetLedger, BudgetPolicy


def test_tool_without_progress_cannot_use_operational_maximum_deadline():
    ledger = BudgetLedger(BudgetPolicy(20, .08, mode='operational'))
    stop, expired = threading.Event(), threading.Event()
    thread = threading.Thread(target=watch_policy_deadline, args=(ledger, stop, expired.set))
    started = time.monotonic()
    thread.start()
    assert expired.wait(1)
    thread.join(1)
    assert ledger.extensions == 0
    assert time.monotonic()-started < .5


def test_watch_can_extend_only_on_fresh_progress_and_stops_at_double_budget():
    now, proof = [0.0], [None]
    ledger = BudgetLedger(BudgetPolicy(20, 10, mode='operational'),
                          clock=lambda: now[0], progress_probe=lambda: proof[0])
    now[0], proof[0] = 10, 'file-a'
    assert ledger.remaining_seconds() == 5
    now[0] = 15
    assert ledger.remaining_seconds() == 0
    assert ledger.extensions == 1


def test_host_watch_stops_silent_tool_without_any_model_request(tmp_path):
    from benchmark.linux_sandbox import ResourceLimits, SandboxSpec, SandboxSupervisor
    from benchmark.model_broker import BrokerPolicy
    from test_linux_sandbox import python_runtime
    workspace = tmp_path/'seed'
    workspace.mkdir()
    (workspace/'wait.py').write_text('import time; time.sleep(30)\n')
    policy = BudgetPolicy(20, 1, mode='operational')
    result = SandboxSupervisor().run(SandboxSpec(
        argv=('/usr/bin/python3.12', '/workspace/wait.py'), workspace=workspace,
        runtime_ro=python_runtime(), limits=ResourceLimits(wall_seconds=10),
        broker=BrokerPolicy(upstream_port=12345, model_allowlist=('m',),
                            max_requests=policy.max_model_requests, request_limits=policy.as_dict())))
    assert result.timed_out and result.infrastructure_error is None
    assert result.cleanup_verified
    assert result.resource_evidence['budget_ledger']['extensions'] == 0
