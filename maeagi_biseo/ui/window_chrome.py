"""Theme native Windows title bars while preserving system window behavior."""
import ctypes

from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget, QDialog, QMenu


class WindowChromeFilter(QObject):
    def eventFilter(self, watched, event):
        if isinstance(watched, (QDialog, QMenu)) and event.type() == QEvent.Show:
            from maeagi_biseo.ui.chat_theme import appearance_for, apply_chat_theme
            # Follow the current parent/application appearance when reopening.
            apply_chat_theme(watched, appearance_for(watched.parentWidget()))
        if (isinstance(watched, QWidget) and watched.isWindow()
                and not watched.windowFlags() & Qt.FramelessWindowHint
                and watched.windowType() not in (Qt.Popup, Qt.ToolTip)
                and event.type() in (QEvent.Show, QEvent.PaletteChange)
                and watched.isVisible()):
            from maeagi_biseo.ui.chat_theme import COLORS
            ancestor = watched
            mode = None
            while ancestor is not None and mode is None:
                mode = ancestor.property('appearance')
                ancestor = ancestor.parentWidget()
            mode = mode or QApplication.instance().property('appearance') or 'light'
            apply_native_title_bar(watched, COLORS.get(mode, COLORS['light']), mode == 'dark')
        return False


def install_window_chrome():
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_window_chrome_filter'):
        app._window_chrome_filter = WindowChromeFilter(app)
        app.installEventFilter(app._window_chrome_filter)


def apply_native_title_bar(widget, colors, dark=False):
    if QGuiApplication.platformName() != 'windows':
        return
    try:
        set_attribute = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        set_attribute.restype = ctypes.c_long
        handle = int(widget.winId())
        attributes = [(20, int(dark)), (33, 2)]
        for attribute, key in ((34, 'line'), (35, 'background'), (36, 'text')):
            color = QColor(colors[key])
            attributes.append((attribute, color.red() | color.green() << 8 | color.blue() << 16))
        for attribute, value in attributes:
            data = ctypes.c_uint(value)
            set_attribute(handle, attribute, ctypes.byref(data), ctypes.sizeof(data))
    except (OSError, AttributeError):
        # Older Windows versions retain their standard title bar.
        pass
