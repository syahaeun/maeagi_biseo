"""A quiet choice indicator without a separate native arrow button."""
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QPainter, QPolygonF, QPalette
from PySide6.QtWidgets import QComboBox


class ChoiceComboBox(QComboBox):
    def _on_indicator(self, event):
        return (event.position().x() < 28 if self.layoutDirection() == Qt.RightToLeft
                else event.position().x() >= self.width() - 28)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_indicator(event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_indicator(event):
            if self.count():
                QTimer.singleShot(0, self.showPopup)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() <= 1:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        group = QPalette.Active if self.isEnabled() else QPalette.Disabled
        painter.setBrush(self.palette().color(group, QPalette.PlaceholderText))
        x = 16 if self.layoutDirection() == Qt.RightToLeft else self.width() - 16
        y = self.height() / 2
        painter.drawPolygon(QPolygonF([QPointF(x - 4, y - 2), QPointF(x + 4, y - 2), QPointF(x, y + 3)]))
