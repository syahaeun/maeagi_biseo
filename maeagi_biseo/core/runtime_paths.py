"""Writable capture output, separated from bundled read-only resources."""
import sys
from pathlib import Path
from PySide6.QtCore import QStandardPaths
from maeagi_biseo.resources import PROJECT_ROOT


def capture_output_root():
    if getattr(sys, 'frozen', False):
        return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'DesktopShimeji' / 'Capture'
    return PROJECT_ROOT / 'Test'
