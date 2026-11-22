"""Plain-text editing for alternating two-pet conversations."""
from copy import deepcopy
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit
from maeagi_biseo.ui.choice_combo import ChoiceComboBox
from maeagi_biseo.core.dialogue_store import load_scripts, validate_scripts
from maeagi_biseo.resources import SCRIPTS, tr


class DialogueEditor(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store
        self.scripts = load_scripts(store)
        self.current = -1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        help_label = QLabel(tr('dialogue.help'))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.selector = ChoiceComboBox()
        self.selector.setAccessibleName(tr('dialogue.title'))
        layout.addWidget(self.selector)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(230)
        self.editor.setPlaceholderText(tr('dialogue.placeholder'))
        self.editor.setAccessibleName(tr('dialogue.title'))
        layout.addWidget(self.editor)
        row = QHBoxLayout()
        for key, callback in (('dialogue.add', self.add_script), ('dialogue.delete', self.delete_script), ('dialogue.reset', self.reset_scripts)):
            button = QPushButton(tr(key))
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.selector.currentIndexChanged.connect(self.select_script)
        self.refresh()

    def stash(self):
        if 0 <= self.current < len(self.scripts):
            self.scripts[self.current] = [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]

    def refresh(self, selected=0):
        self.selector.blockSignals(True)
        self.selector.clear()
        for index in range(len(self.scripts)):
            self.selector.addItem(tr('dialogue.item', number=index + 1))
        self.selector.setCurrentIndex(selected if self.scripts else -1)
        self.selector.blockSignals(False)
        self.current = -1
        self.select_script(self.selector.currentIndex())

    def select_script(self, index):
        self.stash()
        self.current = index
        self.editor.setPlainText('\n'.join(self.scripts[index]) if index >= 0 else '')
        self.editor.setEnabled(index >= 0)

    def add_script(self):
        self.stash()
        if len(self.scripts) >= 100:
            return
        self.scripts.append([])
        self.refresh(len(self.scripts) - 1)
        self.editor.setFocus()

    def delete_script(self):
        if self.current >= 0:
            del self.scripts[self.current]
            self.refresh(min(self.current, len(self.scripts) - 1))

    def reset_scripts(self):
        self.scripts = deepcopy(SCRIPTS)
        self.refresh()

    def values(self):
        self.stash()
        return validate_scripts(deepcopy(self.scripts))
