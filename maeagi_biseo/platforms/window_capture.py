"""Capture an HWND through Windows Graphics Capture without changing focus."""
import ctypes
from ctypes import wintypes
import threading

from maeagi_biseo.resources import tr
from PIL import Image


def capture_window(hwnd, client, timeout=5):
    from windows_capture import WindowsCapture

    ready = threading.Event()
    frames = []
    errors = []
    capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False,
                             draw_border=False, secondary_window=False)

    @capture.event
    def on_frame_arrived(frame, control):
        try:
            frames.append(Image.fromarray(frame.frame_buffer[:, :, 2::-1].copy()))
        except Exception as exc:
            errors.append(exc)
        finally:
            control.stop()
            ready.set()

    @capture.event
    def on_closed():
        ready.set()

    control = capture.start_free_threaded()
    try:
        if not ready.wait(timeout):
            raise RuntimeError(tr('capture.window_timeout'))
    finally:
        control.stop()
    if errors:
        raise RuntimeError(tr('capture.window_convert')) from errors[0]
    if not frames:
        raise RuntimeError(tr('capture.window_closed'))
    image = frames[0]
    # WGC includes the title bar but excludes invisible DWM resize borders.
    rect = wintypes.RECT()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect))
    if result != 0 or image.size != (rect.right - rect.left, rect.bottom - rect.top):
        ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    if image.size != (rect.right - rect.left, rect.bottom - rect.top):
        raise RuntimeError(tr('capture.window_resized'))
    box = (client[0] - rect.left, client[1] - rect.top,
           client[2] - rect.left, client[3] - rect.top)
    if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
        raise RuntimeError(tr('capture.window_changed'))
    image = image.crop(box)
    if not any(high for low, high in image.getextrema()):
        raise RuntimeError(tr('capture.window_black'))
    return image
