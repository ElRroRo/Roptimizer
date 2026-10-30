"""The array backend: CuPy on an NVIDIA GPU, else NumPy on the CPU, behind the one name `cp`.

Every engine module imports `cp` from here. On a GPU it is CuPy itself, so the GPU path is unchanged. Without
one (no CUDA device, no CuPy, or MSO_DEVICE=cpu) it is a thin NumPy stand-in that answers the few CuPy-only
calls the engine makes: the memory pool, free memory, the device name, synchronize and the seeded generator.
The CPU is slower, so runs there use the smaller "cpu" bank (mso/cli.py PROFILES).
"""
import os
import types

import numpy as np


def _cupy():
    if os.environ.get("MSO_DEVICE", "").lower() == "cpu":
        return None
    try:
        import cupy
        if cupy.cuda.runtime.getDeviceCount() < 1:
            return None
        float(cupy.arange(4).sum())           # a missing CUDA toolkit shows here, not halfway through a run
        return cupy
    except Exception:
        return None


def _available_ram():
    try:
        with open("/proc/meminfo") as f:
            info = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in f}
        return info.get("MemAvailable", info["MemFree"]), info["MemTotal"]
    except (OSError, KeyError, ValueError):
        try:
            pages, size = os.sysconf("SC_AVPHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
            return pages * size, os.sysconf("SC_PHYS_PAGES") * size
        except (AttributeError, OSError, ValueError):    # no sysconf (Windows): assume a modest machine
            return 8 * 2**30, 16 * 2**30


class _Pool:
    def free_all_blocks(self):
        pass

    def used_bytes(self):
        return 0


class _Random:
    """CuPy's global-generator calls on a NumPy Generator (seeded, so a CPU bank is reproducible on its own)."""
    def __init__(self):
        self.g = np.random.default_rng()

    def seed(self, s=None):
        self.g = np.random.default_rng(s)

    def random(self, size=None, dtype=np.float64):
        return self.g.random(size, dtype=dtype)

    def rand(self, *shape, dtype=np.float64):
        return self.g.random(shape, dtype=dtype)

    def standard_normal(self, size=None, dtype=np.float64):
        return self.g.standard_normal(size, dtype=dtype)

    def normal(self, loc=0.0, scale=1.0, size=None, dtype=np.float64):
        return (self.g.standard_normal(size, dtype=dtype) * scale + loc).astype(dtype, copy=False)


class _CPU(types.ModuleType):
    def __init__(self):
        super().__init__("cpu_backend")
        self.asnumpy = np.asarray
        self._pool = _Pool()
        self.random = _Random()
        name = f"CPU ({os.cpu_count()} threads)".encode()
        self.cuda = types.SimpleNamespace(
            runtime=types.SimpleNamespace(memGetInfo=_available_ram, getDeviceCount=lambda: 0,
                                          getDeviceProperties=lambda i: {"name": name}),
            Device=lambda *a: types.SimpleNamespace(synchronize=lambda: None))

    def get_default_memory_pool(self):
        return self._pool

    def __getattr__(self, k):
        return getattr(np, k)


_gpu = _cupy()
GPU = _gpu is not None
cp = _gpu if GPU else _CPU()
