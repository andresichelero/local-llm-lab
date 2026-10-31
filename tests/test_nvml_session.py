import threading
import time

import pytest

from benchmark import nvml_session, opencode_baseline


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(nvml_session, '_session', None)
    monkeypatch.setattr(nvml_session, '_failure', None)


class Library:
    def __init__(self):
        self.inits = 0

    def nvmlInit_v2(self):
        self.inits += 1
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, index, handle):
        return 0

    def nvmlDeviceGetMemoryInfo_v2(self, device, reference):
        memory = reference._obj
        assert memory.version == 0x02000028
        memory.total, memory.free, memory.used = 8192 * nvml_session.MIB, 3000 * nvml_session.MIB, 4600 * nvml_session.MIB
        return 0

    def nvmlDeviceGetUtilizationRates(self, device, reference):
        reference._obj.gpu = 97
        return 0

    def nvmlDeviceGetTemperature(self, device, sensor, reference):
        reference._obj.value = 71
        return 0

    def nvmlDeviceGetClockInfo(self, device, clock, reference):
        reference._obj.value = 1905
        return 0

    def nvmlDeviceGetPowerUsage(self, device, reference):
        return 3  # the driver reports this sensor as unsupported


def test_session_opens_once_across_samples(fresh, monkeypatch):
    library = Library()
    monkeypatch.setattr(nvml_session.ctypes, 'CDLL', lambda name: library)
    assert nvml_session.memory_mib() == (8192, 3000, 4600)
    assert nvml_session.metrics() == {'vram_used_mib': 4600, 'gpu_util_pct': 97, 'temperature_c': 71,
                                      'gpu_clock_mhz': 1905, 'power_w': None}
    assert library.inits == 1


def test_failed_open_is_not_retried_each_sample(fresh, monkeypatch):
    calls = []
    def missing(name):
        calls.append(name)
        raise OSError('no library')
    monkeypatch.setattr(nvml_session.ctypes, 'CDLL', missing)
    for _ in range(3):
        with pytest.raises(nvml_session.NvmlError):
            nvml_session.memory_mib()
    assert len(calls) == 1


def test_windows_memory_uses_one_process_that_exits_on_stdin_close(tmp_path, monkeypatch):
    if opencode_baseline.os.name == 'nt':
        pytest.skip('the fake PowerShell is a POSIX script')
    starts = tmp_path / 'starts'
    fake = tmp_path / 'powershell.exe'
    fake.write_text(f'#!/bin/sh\necho x >> {starts}\nwhile read line; do echo 2097152; done\necho exited >> {starts}\n')
    fake.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{opencode_baseline.os.environ["PATH"]}')
    stop, host = threading.Event(), {'value': None, 'at': 0}
    thread = threading.Thread(target=opencode_baseline.windows_memory, args=(stop, host))
    thread.start()
    time.sleep(1.5)
    stop.set()
    thread.join(timeout=6)
    assert not thread.is_alive()
    assert host['value'] == 2048
    assert starts.read_text().split() == ['x', 'exited']
