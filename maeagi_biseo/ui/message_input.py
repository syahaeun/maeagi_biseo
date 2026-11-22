"""Chat editor with IME-aware hints and Enter-to-send behavior."""
from PySide6.QtCore import Qt, QTimer, Signal, QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QLabel


class MessageInput(QPlainTextEdit):
    sendRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hint = ''
        self._preedit = ''
        self._submit_pending = False
        # Keep native placeholder state unchanged while the Windows IME owns a
        # preedit cursor. The visual hint is a passive child of the viewport.
        self._hint_label = QLabel(self.viewport())
        self._hint_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._hint_label.setTextFormat(Qt.PlainText)
        self._hint_label.setWordWrap(True)
        self._hint_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._hint_label.hide()
        self.setOverwriteMode(False)
        self.setCursorWidth(1)
        self.textChanged.connect(self._update_hint)

    def setPlaceholderText(self, text):
        self._hint = text
        self._hint_label.setText(text)
        self.setAccessibleDescription(text)
        self._update_hint()

    def placeholderText(self):
        return self._hint if not self._preedit and self.document().isEmpty() else ''

    def _update_hint(self):
        visible = not self._preedit and self.document().isEmpty()
        self._hint_label.setVisible(bool(self._hint) and visible)
        self._position_hint()

    def _position_hint(self):
        if not hasattr(self, '_hint_label'):
            return
        margin = round(self.document().documentMargin())
        self._hint_label.setGeometry(self.viewport().rect().adjusted(margin, margin, -margin, -margin))
        color = self.palette().color(QPalette.PlaceholderText).name()
        style = f'background: transparent; border: none; padding: 0px; color: {color};'
        if self._hint_label.styleSheet() != style:
            self._hint_label.setStyleSheet(style)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_hint()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange, QEvent.PaletteChange):
            self._position_hint()

    def inputMethodEvent(self, event):
        self._preedit = event.preeditString()
        self.setOverwriteMode(False)
        self._update_hint()
        super().inputMethodEvent(event)
        self._update_hint()

    def clear(self):
        QApplication.inputMethod().reset()
        self._preedit = ''
        super().clear()
        self._update_hint()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Insert and event.modifiers() == Qt.NoModifier:
            self.setOverwriteMode(False)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            event.accept()
            if event.isAutoRepeat() or self._submit_pending:
                return
            self._submit_pending = True
            QApplication.inputMethod().commit()
            QTimer.singleShot(0, self._finish_submit)
            return
        self.setOverwriteMode(False)
        super().keyPressEvent(event)

    def _finish_submit(self):
        self._submit_pending = False
        if not self._preedit and self.toPlainText().strip():
            self.sendRequested.emit()
