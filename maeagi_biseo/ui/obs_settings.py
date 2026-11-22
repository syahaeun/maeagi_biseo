"""OBS preferences are drafts until the enclosing settings dialog is saved."""
from PySide6.QtWidgets import QWidget, QFormLayout, QVBoxLayout, QLabel, QCheckBox, QSpinBox, QPushButton, QScrollArea
from maeagi_biseo.ui.choice_combo import ChoiceComboBox
from maeagi_biseo.ui.settings_widgets import SettingsColumns, configure_form, settings_card
from maeagi_biseo.core.obs_settings import load_obs, normalize_obs
from maeagi_biseo.resources import tr
from maeagi_biseo.ui.obs_placement import ObsPlacementEditor


class ObsSettingsPage(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.setObjectName('settingsPage')
        config = load_obs(store)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        columns = SettingsColumns()
        layout.addWidget(columns)
        controls = settings_card()
        columns.add_panel(controls, 3)
        form = QFormLayout(controls)
        configure_form(form)
        heading = QLabel(tr('obs.settings_heading'))
        heading.setObjectName('captureHeading')
        form.addRow(heading)
        help_text = QLabel(tr('obs.settings_help'))
        help_text.setWordWrap(True)
        form.addRow(help_text)
        self.options_box = QWidget()
        self.options_box.setObjectName('captureCard')
        options = QVBoxLayout(self.options_box)
        options.setContentsMargins(14,12,14,12)
        options.setSpacing(9)
        options.addWidget(QLabel(tr('obs.basic_options')))
        self.enabled = QCheckBox(tr('obs.enabled'))
        self.enabled.setChecked(config['enabled'])
        options.addWidget(self.enabled)
        self.desktop_motion = QCheckBox(tr('obs.desktop_motion'))
        self.desktop_motion.setChecked(config['desktop_motion'])
        options.addWidget(self.desktop_motion)
        options_help = QLabel(tr('obs.options_help'))
        options_help.setWordWrap(True)
        options.addWidget(options_help)
        form.addRow(self.options_box)
        placement_link = QPushButton(tr('obs.edit_placement'))
        placement_link.clicked.connect(self.show_placement)
        form.addRow(placement_link)
        self.fields = {}
        for key in ('pet_scale', 'bubble_scale'):
            spin = QSpinBox()
            spin.setObjectName('obs_' + key)
            spin.setRange(25, 300)
            spin.setSuffix(' %')
            spin.setValue(config[key])
            self.fields[key] = spin
            form.addRow(tr('obs.' + key), spin)
        self.bubble_position = ChoiceComboBox()
        self.bubble_position.addItem(tr('obs.bubble_above'), 'above')
        self.bubble_position.addItem(tr('obs.bubble_below'), 'below')
        self.bubble_position.setCurrentIndex(self.bubble_position.findData(config['bubble_position']))
        form.addRow(tr('obs.bubble_position'), self.bubble_position)
        self.position = ChoiceComboBox()
        self.position.addItem(tr('obs.follow'), 'follow')
        self.position.addItem(tr('obs.fixed'), 'fixed')
        self.position.setCurrentIndex(self.position.findData(config['position']))
        form.addRow(tr('obs.position'), self.position)
        self.motion_help = QLabel()
        self.motion_help.setWordWrap(True)
        form.addRow(self.motion_help)
        self.position.currentIndexChanged.connect(self.refresh_motion_help)
        self.refresh_motion_help()
        preview_card = settings_card()
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_heading = QLabel(tr('obs.placement_title'))
        preview_heading.setObjectName('captureHeading')
        preview_heading.setWordWrap(True)
        preview_layout.addWidget(preview_heading)
        self.placement = ObsPlacementEditor(self.values,config,self)
        preview_layout.addWidget(self.placement)
        preview_layout.addStretch()
        columns.add_panel(preview_card, 4)
        for field in self.fields.values():
            field.valueChanged.connect(self.placement.refresh)
        self.bubble_position.currentIndexChanged.connect(self.placement.refresh)
        self.placement.refresh()

    def refresh_motion_help(self):
        self.motion_help.setText(tr('obs.motion_help' if self.position.currentData()=='fixed' else 'obs.follow_help'))

    def values(self):
        return normalize_obs(dict(enabled=self.enabled.isChecked(), position=self.position.currentData(),
                                  bubble_position=self.bubble_position.currentData(),
                                  desktop_motion=self.desktop_motion.isChecked(),
                                  **(self.placement.values() if hasattr(self,'placement') else {}),
                                  **{key: field.value() for key, field in self.fields.items()}))

    def show_placement(self):
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor,QScrollArea):
                ancestor.ensureWidgetVisible(self.placement.preview, 0, 12)
                break
            ancestor = ancestor.parentWidget()
        self.placement.preview.setFocus()
