import ctypes
from ctypes import wintypes

class RECT(ctypes.Structure):
    _fields_ = [
        ('left', wintypes.LONG),
        ('top', wintypes.LONG),
        ('right', wintypes.LONG),
        ('bottom', wintypes.LONG)
    ]

class MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', RECT),
        ('rcWork', RECT),
        ('dwFlags', wintypes.DWORD),
        ('szDevice', wintypes.WCHAR * 32)
    ]

def get_monitors():
    """Сканирует и возвращает список всех подключенных мониторов в Windows."""
    monitors = []
    
    def monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)
        if ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
            is_primary = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY = 1
            monitors.append({
                "device": info.szDevice,
                "is_primary": is_primary,
                "x": info.rcMonitor.left,
                "y": info.rcMonitor.top,
                "width": info.rcMonitor.right - info.rcMonitor.left,
                "height": info.rcMonitor.bottom - info.rcMonitor.top,
                "work_width": info.rcWork.right - info.rcWork.left,
                "work_height": info.rcWork.bottom - info.rcWork.top,
            })
        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.LPARAM
    )
    
    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(monitor_enum_proc), 0)
    except Exception:
        pass
        
    return monitors

def get_secondary_monitor():
    """Возвращает параметры второго (не основного) монитора, если он подключен."""
    monitors = get_monitors()
    secondary = next((m for m in monitors if not m.get("is_primary")), None)
    return secondary
