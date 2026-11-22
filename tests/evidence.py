"""Native-window screenshots and action evidence for real GUI tests."""
import json
import time
from datetime import datetime, timezone, timedelta
from PySide6.QtWidgets import QApplication
from tests.artifacts import artifact_path


class Evidence:
    def __init__(self, filename='ui/evidence.json'):
        self.path = artifact_path(filename)
        self.data = {'test_kind': 'native_ui_real_gemini', 'status': 'running',
                     'started_at': datetime.now(timezone(timedelta(hours=9))).isoformat(),
                     'actions': [], 'screenshots': []}
        self.started = time.monotonic()
        self.write()

    def action(self, name, **details):
        self.data['actions'].append({'name': name, 'elapsed_seconds': round(time.monotonic() - self.started, 2), **details})
        self.write()

    def screenshot(self, widget, filename):
        QApplication.processEvents()
        # Capture the native window, not an offscreen QWidget render.
        screenshot = widget.screen().grabWindow(int(widget.winId()))
        method = 'native_window'
        image = screenshot.toImage()
        samples = [image.pixelColor(x, y) for x in range(0, image.width(), max(1, image.width()//8))
                   for y in range(0, image.height(), max(1, image.height()//8))]
        if samples and all(color.red() == color.green() == color.blue() == 0 for color in samples):
            screenshot = widget.grab()
            method = 'qt_visible_widget_render_native_capture_black'
        if screenshot.isNull():
            raise AssertionError('Native window screenshot failed')
        path = artifact_path('ui/' + filename)
        if not screenshot.save(str(path)):
            raise AssertionError('Could not save screenshot')
        self.data['screenshots'].append({'path': str(path), 'capture_method': method})
        self.write()
        return path

    def finish(self, passed, error=None):
        self.data['status'] = 'passed' if passed else 'failed'
        self.data['elapsed_seconds'] = round(time.monotonic() - self.started, 2)
        if error:
            self.data['error'] = str(error)
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
