"""Process-wide NVML session for GPU telemetry.

Every short-lived NVML client inside WSL, nvidia-smi included, leaves live
allocations in the Windows driver's NVRM pool until the host reboots. Measured
on an RTX 3070: about 23 allocations per nvidia-smi call. Samplers therefore
share one nvmlInit per process and never shut it down.
"""
from __future__ import annotations

import ctypes
import threading

MIB = 1024 ** 2
TEMPERATURE_GPU = 0
CLOCK_GRAPHICS = 0


class NvmlError(RuntimeError):
    pass


class _MemoryV2(ctypes.Structure):
    _fields_ = [('version', ctypes.c_uint), ('total', ctypes.c_ulonglong), ('reserved', ctypes.c_ulonglong),
                ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


class _Utilization(ctypes.Structure):
    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]


# nvidia-smi reads the v2 struct too, so memory.used stays comparable with older campaigns.
MEMORY_V2 = ctypes.sizeof(_MemoryV2) | (2 << 24)

_lock = threading.Lock()
_session = None
_failure = None


def _open():
    """Open once. A failure is kept, because retrying each second would add a client per sample."""
    global _session, _failure
    with _lock:
        if _session is None and _failure is None:
            try:
                library = ctypes.CDLL('libnvidia-ml.so.1')
                if library.nvmlInit_v2():
                    raise NvmlError('nvmlInit_v2 failed')
                device = ctypes.c_void_p()
                if library.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device)):
                    raise NvmlError('no GPU at index 0')
                _session = library, device
            except (OSError, AttributeError, NvmlError) as error:
                _failure = NvmlError(str(error))
        if _failure:
            raise _failure
        return _session


def memory_mib():
    """Return (total, free, used) in MiB."""
    library, device = _open()
    memory = _MemoryV2(version=MEMORY_V2)
    if library.nvmlDeviceGetMemoryInfo_v2(device, ctypes.byref(memory)):
        raise NvmlError('nvmlDeviceGetMemoryInfo_v2 failed')
    return memory.total // MIB, memory.free // MIB, memory.used // MIB


def metrics():
    """Return the sampler's GPU values; a sensor this driver does not expose stays None."""
    library, device = _open()
    values = {'vram_used_mib': memory_mib()[2], 'gpu_util_pct': None, 'temperature_c': None,
              'gpu_clock_mhz': None, 'power_w': None}
    utilization = _Utilization()
    if not library.nvmlDeviceGetUtilizationRates(device, ctypes.byref(utilization)):
        values['gpu_util_pct'] = utilization.gpu
    number = ctypes.c_uint()
    if not library.nvmlDeviceGetTemperature(device, TEMPERATURE_GPU, ctypes.byref(number)):
        values['temperature_c'] = number.value
    if not library.nvmlDeviceGetClockInfo(device, CLOCK_GRAPHICS, ctypes.byref(number)):
        values['gpu_clock_mhz'] = number.value
    if not library.nvmlDeviceGetPowerUsage(device, ctypes.byref(number)):
        values['power_w'] = number.value / 1000
    return values
