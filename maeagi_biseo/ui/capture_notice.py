"""Non-activating countdown that stays visible while settings are minimized."""
import math
import time
from weakref import ref

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel

from maeagi_biseo.resources import tr


class CaptureNotice(QLabel):
    def __init__(self, owner):
        flags = (Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                 Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        super().__init__(None, flags)
        self.owner = ref(owner)
        owner.destroyed.connect(self.deleteLater)
        self.setObjectName('captureNotice')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.PlainText)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.ready = None

    def begin(self, delay_ms, ready, status, reading_text):
        self.stop()
        self.setStyleSheet(self.owner().window().styleSheet())
        self.ready = ready
        self.status = status
        self.reading_text = reading_text
        self.deadline = time.monotonic() + delay_ms / 1000
        self.timer.start()
        self.tick()

    def tick(self):
        if self.ready is None:
            return
        seconds = math.ceil(self.deadline - time.monotonic())
        message = tr('capture.countdown', seconds=seconds) if seconds > 0 else self.reading_text
        if self.text() != message or not self.isVisible():
            self.status.setText(message)
            self.setText(message)
            self.adjustSize()
            screen = QApplication.screenAt(QCursor.pos()) or self.owner().screen()
            self.move(screen.availableGeometry().center() - self.rect().center())
            self.show()
        if seconds <= 0:
            self.timer.stop()
            ready, self.ready = self.ready, None
            ready()

    def stop(self):
        self.timer.stop()
        self.ready = None
        self.status = None
        self.hide()
