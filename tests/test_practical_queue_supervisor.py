"""Capacity waits must not consume model attempts or alter frozen records."""
from benchmark.practical_queue_supervisor import action_for


def test_gpu_capacity_block_waits_until_the_frozen_floor():
    manifest = {'status': 'blocked', 'error': 'infrastructure retry exhausted for this episode',
                'latest_episode': {'failure': 'infrastructure'}}
    blocked = [{'status': 'blocked', 'failure': 'infrastructure',
                'error': 'GPU capacity gate failed (6728 MiB free; need 7000 MiB)'}]
    assert action_for(manifest, blocked, 6991, 7000) == 'waiting_for_vram'
    assert action_for(manifest, blocked, 7000, 7000) == 'resume'


def test_noncapacity_error_is_not_retried_blindly():
    manifest = {'status': 'blocked', 'error': 'infrastructure retry exhausted for this episode'}
    blocked = [{'status': 'blocked', 'failure': 'infrastructure', 'error': 'hash mismatch'}]
    assert action_for(manifest, blocked, 8000, 7000) == 'needs_attention'


def test_completed_and_failed_quality_records_are_not_restarted():
    assert action_for({'status': 'complete'}, [], 6000, 7000) == 'complete'
    assert action_for({'status': 'failed'}, [], 8000, 7000) == 'needs_attention'
