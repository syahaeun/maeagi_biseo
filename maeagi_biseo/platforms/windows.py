"""Read visible Windows window edges without changing other applications."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
import time

from PySide6.QtCore import QRect, QPoint
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class WindowSurface:
    handle: int
    rect: QRect


def logical_rect(rect, monitor, screen_origin, scale):
    """DWM reports physical pixels; Qt positions use per-screen logical pixels."""
    left, top, right, bottom = rect
    return QRect(round(screen_origin.x() + (left - monitor[0]) / scale),
                 round(screen_origin.y() + (top - monitor[1]) / scale),
                 round((right - left) / scale), round((bottom - top) / scale))


def monitor_screen(info, screens):
    named = next((screen for screen in screens
                  if screen.name().casefold() == info.szDevice.casefold()), None)
    if named is not None:
        return named
    # Recent Qt versions may expose the monitor's friendly name instead of DISPLAYn.
    # On Windows, Qt keeps native screen origins while scaling each screen's size.
    for screen in screens:
        geometry = screen.geometry()
        scale = screen.devicePixelRatio()
        if (geometry.left() == info.rcMonitor.left and geometry.top() == info.rcMonitor.top
                and abs(geometry.width() * scale - (info.rcMonitor.right - info.rcMonitor.left)) <= 2
                and abs(geometry.height() * scale - (info.rcMonitor.bottom - info.rcMonitor.top)) <= 2):
            return screen
    return None


def exposed(surface, surfaces, x):
    """EnumWindows order is front to back; reject an edge covered by a window."""
    point = QPoint(round(x), surface.rect.top() + 1)
    for other in surfaces:
        if other.handle == surface.handle:
            return True
        if other.rect.contains(point):
            return False
    return False


def landing_surface(surfaces, foot_x, foot_y, width, minimum_top, tolerance=40):
    candidates = [surface for surface in surfaces
                  if surface.rect.width() >= width
                  and surface.rect.left() <= foot_x <= surface.rect.right()
                  and surface.rect.top() >= minimum_top
                  and abs(surface.rect.top() - foot_y) <= tolerance
                  and exposed(surface, surfaces, foot_x)]
    return min(candidates, key=lambda item: abs(item.rect.top() - foot_y), default=None)


def crossed_surface(surfaces, old_x, old_y, new_x, new_y, width, minimum_top):
    """Sweep the feet segment so fast falls cannot tunnel through thin edges."""
    if new_y <= old_y:
        return None, None
    hits = []
    for surface in surfaces:
        top = surface.rect.top()
        if surface.rect.width() < width or top < minimum_top or not old_y <= top <= new_y:
            continue
        ratio = (top - old_y) / (new_y - old_y)
        x = old_x + (new_x - old_x) * ratio
        if surface.rect.left() <= x <= surface.rect.right() and exposed(surface, surfaces, x):
            hits.append((ratio, surface, x))
    if not hits:
        return None, None
    _, surface, x = min(hits, key=lambda item: item[0])
    return surface, x


class MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD),
                ('szDevice', wintypes.WCHAR * 32)]


class WindowTracker:
    def __init__(self, excluded_pid=None):
        self.excluded_pid = os.getpid() if excluded_pid is None else excluded_pid
        self.cached = []
        self.next_scan = 0
        self.supported = sys.platform == 'win32'
        if not self.supported:
            return
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'IsIconic': ([wintypes.HWND], wintypes.BOOL),
            'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'GetWindowLongW': ([wintypes.HWND, ctypes.c_int], wintypes.LONG),
            'GetClassNameW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'MonitorFromWindow': ([wintypes.HWND, wintypes.DWORD], wintypes.HANDLE),
            'GetMonitorInfoW': ([wintypes.HANDLE, ctypes.POINTER(MonitorInfo)], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user32, name)
            function.argtypes, function.restype = args, result
        self.dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self.dwm.DwmGetWindowAttribute.restype = wintypes.LONG

    def snapshot(self, force=False):
        if not self.supported:
            return []
        now = time.monotonic()
        if not force and now < self.next_scan:
            return self.cached
        surfaces = []

        def visit(hwnd, _):
            if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
                return True
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.excluded_pid:
                return True
            # Tooltips, desktop, taskbar and our own bubbles are not platforms.
            if self.user32.GetWindowLongW(hwnd, -20) & 0x80:
                return True
            class_name = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, class_name, len(class_name))
            if class_name.value in ('Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
                return True
            cloaked = wintypes.DWORD()
            if self.dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                return True
            rect = wintypes.RECT()
            if self.dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
                if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
            if rect.right <= rect.left or rect.bottom <= rect.top:
                return True
            monitor = self.user32.MonitorFromWindow(hwnd, 2)
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if not self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return True
            screen = monitor_screen(info, QGuiApplication.screens())
            if screen is None:
                # Unknown displays must not be placed using the wrong DPI scale.
                return True
            bounds = logical_rect((rect.left, rect.top, rect.right, rect.bottom),
                                  (info.rcMonitor.left, info.rcMonitor.top),
                                  screen.geometry().topLeft(), screen.devicePixelRatio())
            surfaces.append(WindowSurface(int(hwnd), bounds))
            return True

        callback = self.callback_type(visit)
        self.user32.EnumWindows(callback, 0)
        self.cached = surfaces
        self.next_scan = now + .08
        return surfaces


WINDOW_TRACKER = WindowTracker()


def park_capture_window(widget):
    """Keep a capturable HWND beyond all monitors using native coordinates."""
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows' or not widget.isVisible():
        return False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                    ctypes.c_int,ctypes.c_int,wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    handle = wintypes.HWND(int(widget.winId()))
    right = user32.GetSystemMetrics(76)+user32.GetSystemMetrics(78)
    top = user32.GetSystemMetrics(77)
    rect = wintypes.RECT()
    if user32.GetWindowRect(handle,ctypes.byref(rect)) and rect.left >= right+64:
        return True
    # NOSIZE | NOZORDER | NOACTIVATE | NOOWNERZORDER. Keep capture pixels intact.
    return bool(user32.SetWindowPos(handle,None,right+64,top,0,0,0x215))


def keep_above_taskbar(widget, *, behind=None):
    """Keep pets above visible applications without taking keyboard focus."""
    if sys.platform != 'win32' or QGuiApplication.platformName() != 'windows' or not widget.isVisible():
        return
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    target = int(widget.winId())
    if behind is not None:
        # Anchor older pets below newer pets instead of promoting every window
        # independently to HWND_TOPMOST on staggered timers.
        anchor = int(behind.winId())
        if user32.GetWindow(anchor, 2) != target:
            user32.SetWindowPos(target, wintypes.HWND(anchor), 0, 0, 0, 0, 0x13)
        return
    handle = user32.GetTopWindow(None)
    while handle and handle != target:
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, name, len(name))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if user32.IsWindowVisible(handle) and pid.value != os.getpid():
            # HWND_TOPMOST; SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE.
            user32.SetWindowPos(target, wintypes.HWND(-1), 0, 0, 0, 0, 0x13)
            return
        handle = user32.GetWindow(handle, 2)  # GW_HWNDNEXT
