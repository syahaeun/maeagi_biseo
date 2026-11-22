"""WGC failures must stop the session and never return desktop pixels."""
import re
import unittest
from maeagi_biseo.resources import tr
from unittest.mock import Mock, patch

from maeagi_biseo.platforms.window_capture import capture_window


class WindowCaptureTests(unittest.TestCase):
    def run_failure(self, dispatch, message):
        handlers = {}
        capture, control = Mock(), Mock()
        capture.event.side_effect = lambda fn: handlers.setdefault(fn.__name__, fn)
        capture.start_free_threaded.side_effect = lambda: (dispatch(handlers), control)[1]
        with patch('windows_capture.WindowsCapture', return_value=capture), \
             self.assertRaisesRegex(RuntimeError, re.escape(tr('capture.' + message))):
            capture_window(123, (0, 0, 400, 240), timeout=0)
        control.stop.assert_called_once()

    def test_timeout_stops_capture(self):
        self.run_failure(lambda handlers: None, 'window_timeout')

    def test_closed_window_returns_no_image(self):
        self.run_failure(lambda handlers: handlers['on_closed'](), 'window_closed')

    def test_bad_frame_stops_capture(self):
        internal = Mock()
        self.run_failure(lambda handlers: handlers['on_frame_arrived'](object(), internal),
                         'window_convert')
        internal.stop.assert_called_once()
