"""Aceleração por hardware: o que está ligado, com o que, e o que ficou na CPU.

Tudo é opcional e detectado uma vez por processo (subprocesso/imports só na primeira pergunta). Nenhuma função
levanta exceção: sem GPU, sem driver ou sem a biblioteca, devolve None/False e o diagnóstico segue funcionando.
"""
import ctypes
import json
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.request
import winreg

if platform.system() == "Windows":
    import ctypes.wintypes as wintypes
else:
    wintypes = None

log = logging.getLogger("lumen.hardware")

_LOCK = threading.Lock()
_CACHE = {}


def _once(key, fn):
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
    value = fn()
    with _LOCK:
        _CACHE[key] = value
    return value


def nvidia():
    """{name, vram_mb, used_mb, driver} da primeira GPU NVIDIA, ou None (sem nvidia-smi/GPU)."""
    def probe():
        if not shutil.which("nvidia-smi"):
            return None
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return None
        lines = (out.stdout or "").strip().splitlines()
        if out.returncode or not lines:
            return None
        parts = [p.strip() for p in lines[0].split(",")]
        if len(parts) < 2:
            return None
        def mb(value):
            try:
                return int(float(value))
            except ValueError:
                return 0
        return {"name": parts[0], "vram_mb": mb(parts[1]), "used_mb": mb(parts[2]) if len(parts) > 2 else 0,
                "driver": parts[3] if len(parts) > 3 else ""}
    return _once("nvidia", probe)


def cuda():
    """CTranslate2 (Whisper) enxerga ao menos uma GPU CUDA?"""
    def probe():
        try:
            import ctranslate2
            return int(ctranslate2.get_cuda_device_count()) > 0
        except Exception:  # noqa: BLE001 - biblioteca ausente ou driver incompatível
            return False
    return _once("cuda", probe)


def directml():
    """O onnxruntime instalado tem o provedor DirectML (filtro de música na GPU)?"""
    def probe():
        try:
            import onnxruntime
            return "DmlExecutionProvider" in onnxruntime.get_available_providers()
        except Exception:  # noqa: BLE001
            return False
    return _once("directml", probe)


def vulkan():
    """O stable-diffusion.cpp (capas) está baixado e usa Vulkan?"""
    def probe():
        try:
            from . import imagegen
            return bool(imagegen.ready())
        except Exception:  # noqa: BLE001
            return False
    return _once("vulkan", probe)


def ui_gpu():
    """A janela WebView2 foi iniciada com GPU? (opt-in por LUMEN_WEBVIEW_GPU=1 no launcher)."""
    return os.environ.get("LUMEN_WEBVIEW_GPU") == "1"


def cdp_gpu():
    """O Edge sem janela (PNG/PDF) foi iniciado com GPU? (opt-in por LUMEN_CDP_GPU=1)."""
    return os.environ.get("LUMEN_CDP_GPU") == "1"


# --- MONITOR EM TEMPO REAL: CPU, RAM, GPU E MOTORES DO LÚMEN ---

# Estruturas do Windows ctypes
if platform.system() == "Windows" and wintypes is not None:
    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    _GetSystemTimes = ctypes.windll.kernel32.GetSystemTimes
    _GetSystemTimes.argtypes = [ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME)]
    _GetSystemTimes.restype = wintypes.BOOL

    _GetProcessTimes = ctypes.windll.kernel32.GetProcessTimes
    _GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
                                 ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME)]
    _GetProcessTimes.restype = wintypes.BOOL

    _GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo
    _GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD]
    _GetProcessMemoryInfo.restype = wintypes.BOOL
else:
    _MEMORYSTATUSEX = None
    _PROCESS_MEMORY_COUNTERS_EX = None
    _FILETIME = None
    _GetSystemTimes = None
    _GetProcessTimes = None
    _GetProcessMemoryInfo = None


def cpu_info():
    """Metadados estáticos do processador: modelo, frequencia base e contagem de núcleos."""
    def probe():
        name = "Processador"
        mhz = 0
        if platform.system() == "Windows":
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                    name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                    mhz, _ = winreg.QueryValueEx(key, "~MHz")
            except OSError:
                name = platform.processor() or "Processador"
        else:
            name = platform.processor() or "Processador"

        name = " ".join((name or "Processador").split())
        logical = os.cpu_count() or 1
        physical = max(1, logical // 2) if logical > 1 else 1
        ghz = round(mhz / 1000.0, 1) if mhz else 0.0
        return {
            "name": name,
            "logical": logical,
            "physical": physical,
            "cores_label": f"{physical}C / {logical}T",
            "ghz": ghz,
        }
    return _once("cpu_info", probe)


_last_cpu_sample = None
_cpu_lock = threading.Lock()


def _ft_to_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _sample_cpu_raw():
    if not _GetSystemTimes or not _GetProcessTimes:
        return 0, 0, 0, time.monotonic()
    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
    _GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))

    c, e, k, u = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
    _GetProcessTimes(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    return _ft_to_int(idle), _ft_to_int(kernel) + _ft_to_int(user), _ft_to_int(k) + _ft_to_int(u), time.monotonic()


def cpu_usage():
    """Retorna (system_cpu_pct, app_cpu_pct) calculados por deltas no Windows."""
    global _last_cpu_sample
    with _cpu_lock:
        now_idle, now_sys, now_app, now_t = _sample_cpu_raw()
        if not _last_cpu_sample or (now_t - _last_cpu_sample[3]) > 10.0:
            time.sleep(0.04)
            now_idle2, now_sys2, now_app2, now_t2 = _sample_cpu_raw()
            sys_delta = now_sys2 - now_sys
            idle_delta = now_idle2 - now_idle
            app_delta = now_app2 - now_app
            _last_cpu_sample = (now_idle2, now_sys2, now_app2, now_t2)
        else:
            sys_delta = now_sys - _last_cpu_sample[1]
            idle_delta = now_idle - _last_cpu_sample[0]
            app_delta = now_app - _last_cpu_sample[2]
            _last_cpu_sample = (now_idle, now_sys, now_app, now_t)

    sys_pct = round(100.0 * (sys_delta - idle_delta) / sys_delta, 1) if sys_delta > 0 else 0.0
    app_pct = round(100.0 * app_delta / sys_delta, 1) if sys_delta > 0 else 0.0
    return max(0.0, min(100.0, sys_pct)), max(0.0, min(100.0, app_pct))


def ram_usage():
    """Retorna dados de RAM do sistema e uso exclusivo do processo Lúmen."""
    if not _MEMORYSTATUSEX or not _GetProcessMemoryInfo:
        return {"total_gb": 0.0, "used_gb": 0.0, "avail_gb": 0.0, "system_pct": 0.0, "app_mb": 0.0, "app_pct": 0.0}

    stat = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))

    pmc = _PROCESS_MEMORY_COUNTERS_EX()
    pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
    _GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)

    total_phys = stat.ullTotalPhys
    avail_phys = stat.ullAvailPhys
    used_phys = total_phys - avail_phys
    app_bytes = pmc.WorkingSetSize

    total_gb = round(total_phys / (1024 ** 3), 1)
    used_gb = round(used_phys / (1024 ** 3), 1)
    avail_gb = round(avail_phys / (1024 ** 3), 1)
    sys_pct = round(100.0 * used_phys / total_phys, 1) if total_phys else 0.0

    app_mb = round(app_bytes / (1024 ** 2), 1)
    app_pct = round(100.0 * app_bytes / total_phys, 1) if total_phys else 0.0

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "avail_gb": avail_gb,
        "system_pct": sys_pct,
        "app_mb": app_mb,
        "app_pct": app_pct,
    }


_gpu_cache = None
_gpu_cache_ts = 0.0
_gpu_lock = threading.Lock()


def gpu_usage():
    """Métricas em tempo real da GPU NVIDIA com cache de 1.5s para evitar overhead."""
    global _gpu_cache, _gpu_cache_ts
    with _gpu_lock:
        now = time.monotonic()
        if _gpu_cache is not None and (now - _gpu_cache_ts) < 1.5:
            return _gpu_cache

        if not shutil.which("nvidia-smi"):
            _gpu_cache = None
            _gpu_cache_ts = now
            return None

        try:
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lines = (out.stdout or "").strip().splitlines()
            if out.returncode or not lines:
                _gpu_cache = None
                _gpu_cache_ts = now
                return None
            parts = [p.strip() for p in lines[0].split(",")]
            if len(parts) < 7:
                _gpu_cache = None
                _gpu_cache_ts = now
                return None

            def to_int(v, d=0):
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    return d

            vram_total = to_int(parts[1])
            vram_used = to_int(parts[2])
            vram_free = to_int(parts[3])
            gpu_pct = to_int(parts[4])
            temp_c = to_int(parts[5])
            driver = parts[6]
            vram_pct = round(100.0 * vram_used / vram_total, 1) if vram_total else 0.0

            res = {
                "available": True,
                "name": parts[0],
                "vram_total_mb": vram_total,
                "vram_used_mb": vram_used,
                "vram_free_mb": vram_free,
                "vram_pct": vram_pct,
                "gpu_pct": gpu_pct,
                "temp_c": temp_c,
                "driver": driver,
            }
            _gpu_cache = res
            _gpu_cache_ts = now
            return res
        except Exception:
            _gpu_cache = None
            _gpu_cache_ts = now
            return None


def ollama_stats():
    """Consulta modelos carregados no Ollama e status da porta local."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/ps", headers={"User-Agent": "Lumen"})
        with urllib.request.urlopen(req, timeout=1.2) as r:
            data = json.load(r)
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size_mb": round(m.get("size", 0) / (1024 * 1024)),
                    "vram_mb": round(m.get("size_vram", 0) / (1024 * 1024)),
                })
            return {"online": True, "models": models}
    except Exception:
        return {"online": False, "models": []}


def monitor_stats():
    """Retrato consolidado para o painel de monitoramento do Lúmen."""
    info_cpu = cpu_info()
    sys_cpu, app_cpu = cpu_usage()
    ram = ram_usage()
    gpu = gpu_usage()
    ol = ollama_stats()

    # Motores do aplicativo
    has_cuda = cuda()
    has_dml = directml()
    engines = [
        {
            "id": "whisper",
            "name": "Transcrição",
            "tech": "Whisper · CUDA (GPU)" if has_cuda else "Whisper · CPU",
            "active": True,
            "status": "Acelerado" if has_cuda else "CPU",
        },
        {
            "id": "llm",
            "name": "Raciocínio IA",
            "tech": f"Ollama · {gpu['name'] if gpu else 'GPU'}" if ol["online"] else "Ollama Local",
            "active": ol["online"],
            "status": f"{len(ol['models'])} na VRAM" if ol["models"] else ("Pronto" if ol["online"] else "Offline"),
        },
        {
            "id": "audio",
            "name": "Filtro de Voz",
            "tech": "DirectML · GPU" if has_dml else "CPU Nativo",
            "active": has_dml,
            "status": "DirectML" if has_dml else "Standard",
        },
        {
            "id": "protect",
            "name": "Proteção",
            "tech": "Restic · Criptografia Local",
            "active": True,
            "status": "Protegido",
        },
    ]

    gpu_payload = None
    if gpu:
        gpu_payload = {
            **gpu,
            "models": ol.get("models", []),
            "models_vram_mb": sum(m.get("vram_mb", 0) for m in ol.get("models", [])),
        }

    return {
        "cpu": {
            **info_cpu,
            "system_pct": sys_cpu,
            "app_pct": app_cpu,
        },
        "ram": ram,
        "gpu": gpu_payload,
        "engines": engines,
        "timestamp": time.time(),
    }


def summary():
    """Um retrato só, para o diagnóstico e para o prompt de otimização."""
    gpu = nvidia()
    return {
        "gpu": gpu,
        "cuda": cuda(),
        "directml": directml(),
        "vulkan": vulkan(),
        "ui_gpu": ui_gpu(),
        "cdp_gpu": cdp_gpu(),
    }

