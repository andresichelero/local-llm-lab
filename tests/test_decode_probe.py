from benchmark import decode_probe


def sample(util, reasons, clock=1900):
    return {'gpu_util_pct': util, 'gpu_clock_mhz': clock, 'memory_clock_mhz': 7001, 'power_w': 230.0,
            'temperature_c': 70, 'reasons': reasons, 'vram_used_mib': 5000 + util}


def request(kind, tok_s, accepted=80, drafted=100):
    return {'kind': kind, 'arm': 'base', 'power_limit_w': 239.8, 'memory_clock_mhz': 7001, 'tok_s': tok_s,
            'draft_accepted': accepted, 'draft_n': drafted, 'clock_mhz': 1900, 'power_w': 230.0, 'peak_mib': 5100,
            'output_sha': 'abc'}


def test_draft_arm_adds_only_the_draft_cache_flags():
    base = decode_probe.server_command('base')
    assert decode_probe.server_command('draft-q4') == base + ['-ctkd', 'q4_0', '-ctvd', 'q4_0']


def test_busy_summary_ignores_idle_samples_but_keeps_their_vram():
    summary = decode_probe.busy_summary([sample(100, 4), sample(95, 0), sample(0, 0, clock=300)], 239.8)
    assert summary['samples'] == 2
    assert summary['clock_mhz'] == 1900
    assert summary['power_cap_share'] == 0.5
    assert summary['peak_mib'] == 5100


def test_busy_summary_without_samples_keeps_the_limit():
    assert decode_probe.busy_summary([], 239.8) == {'power_limit_w': 239.8}


def test_summary_leaves_warmup_out():
    lines = decode_probe.summarize([request('warmup', 10.0), request('short', 100.0), request('short', 110.0)])
    assert len(lines) == 1
    assert 'n=2 tok/s median 105.0 range 100.0-110.0 acceptance 0.800' in lines[0]
