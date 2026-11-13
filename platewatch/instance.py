"""Keep repeated launches from opening competing camera windows on Windows."""
from contextlib import contextmanager
import hashlib
import sys
from .settings import APP_DIR, APP_TITLE


@contextmanager
def desktop_instance():
    if sys.platform != "win32":
        yield True
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = "Local\\PlateWatch_" + hashlib.sha256(str(APP_DIR).lower().encode()).hexdigest()[:20]
    handle = kernel.CreateMutexW(None, False, name)
    already_open = ctypes.get_last_error() == 183
    try:
        if already_open:
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user.FindWindowW.restype = wintypes.HWND
            user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user.SetForegroundWindow.argtypes = [wintypes.HWND]
            window = user.FindWindowW("TkTopLevel", APP_TITLE)
            if window:
                user.ShowWindow(window, 9)
                user.SetForegroundWindow(window)
        yield not already_open
    finally:
        if handle:
            kernel.CloseHandle(handle)
