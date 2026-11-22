"""Small modal saving indicator, animated without a progress bar."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget
from maeagi_biseo.resources import tr


class Spinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        self.angle = (self.angle + 24) % 360
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#8b5cf6'), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(self.rect().adjusted(8, 8, -8, -8), -self.angle * 16, 260 * 16)
        painter.end()


class SavingDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr('editor.saving_title'))
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setWindowModality(Qt.WindowModal)
        self.setFixedSize(320, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        self.spinner = Spinner(self)
        layout.addWidget(self.spinner, 0, Qt.AlignHCenter)
        for key in ('editor.saving_title', 'editor.saving_detail'):
            label = QLabel(tr(key))
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)

    def reject(self):
        # Saving commits a manifest atomically; keep its source files alive.
        pass

    def closeEvent(self, event):
        event.ignore()
