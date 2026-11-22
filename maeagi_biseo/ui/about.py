"""Application identity and concise usage information."""
from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout

from maeagi_biseo.core.updates import REPOSITORY_URL, UpdateChecker
from maeagi_biseo.resources import application_icon_path, tr
from maeagi_biseo.ui.settings_widgets import SettingsColumns, settings_card, settings_link


class AboutPage(QScrollArea):
    def __init__(self, parent=None, *, updates=None):
        super().__init__(parent)
        self.updates = updates if updates is not None else UpdateChecker(self)
        self.setWidgetResizable(True)
        page = SettingsColumns()
        details = settings_card()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(20, 20, 20, 20)
        details_layout.setSpacing(10)
        hero = settings_card()
        hero.setObjectName('aboutHero')
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 24, 16, 24)
        hero_layout.setSpacing(12)

        icon = QLabel()
        icon.setObjectName('aboutIcon')
        icon.setPixmap(QIcon(str(application_icon_path())).pixmap(96, 96))
        icon.setAlignment(Qt.AlignCenter)
        icon.setAccessibleName(tr('about.name'))
        hero_layout.addWidget(icon)
        for key, name in (('about.name', 'aboutTitle'),
                          ('about.version', 'aboutVersion'),
                          ('about.creator', 'aboutCreator')):
            label = QLabel(tr(key, version=self.updates.version) if key == 'about.version' else tr(key))
            label.setObjectName(name)
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(key != 'about.creator')
            hero_layout.addWidget(label, 0, Qt.AlignHCenter if key == 'about.version' else Qt.Alignment())

        hero_layout.addWidget(self._update_panel())
        link = settings_link(tr('updates.repository'), REPOSITORY_URL)
        link.setObjectName('aboutLink')
        hero_layout.addWidget(link, 0, Qt.AlignHCenter)
        hero_layout.addStretch()
        for heading, text in (('about.features_title', 'about.features'),
                              ('about.data_title', 'about.data'),
                              ('about.usage_title', 'about.usage')):
            title = QLabel(tr(heading))
            title.setObjectName('aboutSectionTitle')
            details_layout.addWidget(title)
            body = QLabel(tr(text))
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            details_layout.addWidget(body)
            details_layout.addSpacing(8)
        details_layout.addStretch()
        page.add_panel(hero, 2)
        page.add_panel(details, 3)
        self.setWidget(page)
        self.updates.changed.connect(self._render_update)
        self._render_update()

    def _update_panel(self):
        panel = settings_card()
        layout = QVBoxLayout(panel)
        self.beta_checkbox = QCheckBox(tr('updates.include_beta'))
        self.beta_checkbox.toggled.connect(self.updates.set_include_beta)
        layout.addWidget(self.beta_checkbox)
        self.release_title = QLabel()
        self.release_title.setObjectName('aboutSectionTitle')
        self.release_title.setWordWrap(True)
        layout.addWidget(self.release_title)
        self.release_notes = QLabel()
        self.release_notes.setTextFormat(Qt.PlainText)
        self.release_notes.setWordWrap(True)
        layout.addWidget(self.release_notes)
        actions = QHBoxLayout()
        actions.addStretch()
        self.later_button = QPushButton(tr('updates.later'))
        self.later_button.clicked.connect(self.updates.dismiss)
        actions.addWidget(self.later_button)
        self.release_button = QPushButton(tr('updates.open'))
        self.release_button.setObjectName('saveSettings')
        self.release_button.clicked.connect(self._open_release)
        actions.addWidget(self.release_button)
        layout.addLayout(actions)
        self.check_button = QPushButton(tr('updates.check'))
        self.check_button.clicked.connect(self.updates.check)
        layout.addWidget(self.check_button)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        return panel

    def _open_release(self):
        if self.updates.release is not None:
            QDesktopServices.openUrl(QUrl(self.updates.release.url))

    def _render_update(self):
        with QSignalBlocker(self.beta_checkbox):
            self.beta_checkbox.setChecked(self.updates.include_beta)
        release = self.updates.release
        dismissed = self.updates.dismissed
        for widget in (self.release_title, self.release_notes, self.release_button):
            widget.setVisible(release is not None)
        self.later_button.setVisible(release is not None and not dismissed)
        if release is not None:
            key = 'updates.beta_available' if release.beta else 'updates.available'
            self.release_title.setText(tr(key, version=release.tag))
            preview = '\n'.join(line.strip() for line in release.notes.splitlines() if line.strip())
            lines = preview.splitlines()
            self.release_notes.setText(
                '\n'.join(lines[:4])[:360] + ('…' if len(lines) > 4 or len(preview) > 360 else '')
            )
            self.release_notes.setVisible(bool(preview))
        state = self.updates.state
        self.check_button.setVisible(release is None or state in ('error', 'checking'))
        self.check_button.setEnabled(state != 'checking')
        message = ''
        if state in ('checking', 'error', 'current', 'unpublished'):
            key = 'updates.unpublished_with_beta' if state == 'unpublished' and self.updates.include_beta else f'updates.{state}'
            message = tr(key)
        elif dismissed:
            message = tr('updates.dismissed')
        self.status.setText(message)
        self.status.setVisible(bool(message))
