"""Small containers used by the settings pages."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QBoxLayout, QLayout, QLabel, QPushButton, QScrollArea
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from maeagi_biseo.resources import tr


class SettingsColumns(QWidget):
    def __init__(self, breakpoint=740, margin=12):
        super().__init__()
        self.breakpoint = breakpoint
        if margin:
            self.setObjectName('settingsColumns')
            self.setAttribute(Qt.WA_StyledBackground)
        self.columns = QBoxLayout(QBoxLayout.TopToBottom, self)
        self.columns.setSizeConstraint(QLayout.SetNoConstraint)
        self.columns.setContentsMargins(margin, margin, margin, margin)
        self.columns.setSpacing(14)
        self.columns.setAlignment(Qt.AlignTop)

    def add_panel(self, panel, stretch=1, *, top=False):
        self.columns.addWidget(panel, stretch, Qt.AlignTop if top else Qt.Alignment())

    def minimumSizeHint(self):
        hint = self.columns.minimumSize()
        margins = self.columns.contentsMargins()
        panel_width = max((self.columns.itemAt(index).minimumSize().width()
                           for index in range(self.columns.count())), default=0)
        hint.setWidth(panel_width + margins.left() + margins.right())
        return hint

    def resizeEvent(self, event):
        direction = QBoxLayout.LeftToRight if event.size().width() >= self.breakpoint else QBoxLayout.TopToBottom
        if self.columns.direction() != direction:
            self.columns.setDirection(direction)
            self.updateGeometry()
        super().resizeEvent(event)


def settings_card():
    card = QWidget()
    card.setObjectName('settingsCard')
    card.setAttribute(Qt.WA_StyledBackground)
    return card


def settings_link(text, url):
    button = QPushButton(text)
    button.setObjectName('settingsExternalLink')
    button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return button


class CharacterSettingsPreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setObjectName('settingsCharacterPreview')
        self.setAccessibleName(tr('settings.character_preview'))
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(184)
        self.image = None

    def set_character(self, identifier):
        from maeagi_biseo.core.sprites import SpriteError, load_character
        try:
            pack = load_character(identifier) if identifier else None
        except SpriteError:
            pack = None
        if pack is None:
            self.image = None
        else:
            frame = pack.frame('idle', 0)
            top, bottom = pack.frame_artwork_rows(frame)
            self.image = frame.copy(0, top, frame.width(), bottom - top)
        self.update_image()

    def update_image(self):
        if self.image is None:
            self.clear()
        else:
            self.setPixmap(self.image.scaled(min(200, max(1, self.width() - 16)), 152,
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()


class Disclosure(QWidget):
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        self.toggle = QPushButton(title)
        self.toggle.setObjectName('disclosureToggle')
        self.toggle.setCheckable(True)
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        content.setVisible(False)
        self.toggle.toggled.connect(content.setVisible)
        self.content = content
        self.reveal_timer = QTimer(self)
        self.reveal_timer.setSingleShot(True)
        self.reveal_timer.timeout.connect(self.reveal_content)
        self.toggle.toggled.connect(lambda opened: self.reveal_timer.start(0) if opened else self.reveal_timer.stop())

    def reveal_content(self):
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                ancestor.widget().layout().activate()
                ancestor.ensureWidgetVisible(self.content, 12, 16)
                break
            ancestor = ancestor.parentWidget()


def configure_form(form):
    from PySide6.QtWidgets import QFormLayout
    form.setRowWrapPolicy(QFormLayout.WrapAllRows)
    form.setContentsMargins(24, 20, 24, 20)
    form.setVerticalSpacing(12)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
