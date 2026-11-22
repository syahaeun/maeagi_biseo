"""Chat and provider settings; transport lives in llm.py."""
from maeagi_biseo.resources import tr, style, DEFAULTS, PRESETS, PERSONAS
import json
import threading
from datetime import datetime
from maeagi_biseo.llm.client import generate_reply, list_models, choose_chat_model
from maeagi_biseo.llm.settings import PROVIDERS, load_api_key, normalize_config, provider_defaults, key_with_source
from maeagi_biseo.llm.key_store import store_key
from maeagi_biseo.ui.message_input import MessageInput
from maeagi_biseo.ui.chat_theme import apply_chat_theme, appearance_for
from maeagi_biseo.ui.chat_avatar import (DEFAULT_CROP, ChatAvatarDialog, avatar_image_root, avatar_pixmap, avatar_source,
                                   custom_avatar, custom_avatar_path, normalize_crop, remove_custom_avatar,
                                   save_custom_avatar)
from maeagi_biseo.ui.capture_notice import CaptureNotice
from maeagi_biseo.ui.settings_widgets import CharacterSettingsPreview, Disclosure, SettingsColumns, configure_form, settings_card, settings_link
from maeagi_biseo.ui.dialogue_editor import DialogueEditor
from maeagi_biseo.ui.character_removal import confirm_character_removal, removal_action
from maeagi_biseo.ui.obs_settings import ObsSettingsPage
from maeagi_biseo.core.obs_settings import save_obs
from maeagi_biseo.core.dialogue_store import save_scripts
from maeagi_biseo.ui.sol_erda import SolErdaPanel, MesoPanel
from maeagi_biseo.core.sprites import STATES
from maeagi_biseo.core.character_catalog import registered_characters, preferences, set_default
from maeagi_biseo.core.character_profiles import PERSONA_FIELDS, load_profiles, persona_for, save_profiles, profile_store
from copy import deepcopy
from maeagi_biseo.core.amounts import format_meso
from PySide6.QtCore import Qt, QEvent, QSize, QSettings, QThread, Signal, QTimer, QSignalBlocker
from PySide6.QtGui import QIcon, QTextCursor
from PySide6.QtWidgets import QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLayout, QLineEdit, QComboBox, QPlainTextEdit, QPushButton, QTabWidget, QDialogButtonBox, QMessageBox, QScrollArea, QSpinBox, QCheckBox, QGridLayout, QListWidget, QListWidgetItem
from maeagi_biseo.ui.choice_combo import ChoiceComboBox as QComboBox

CAPTURE_DELAY_MS = 5000

def persona_prompt(config):
    return PERSONAS['prompt_template'].format(**config)

def request_reply(config, key, messages, tool_executor=None):
    if tool_executor is None:
        return generate_reply(config, key, messages, persona_prompt(config))
    return generate_reply(config, key, messages, persona_prompt(config), tool_executor=tool_executor)

class ReplyWorker(QThread):
    result = Signal(str)
    error = Signal(str)
    tool_event = Signal(object)
    capture_requested = Signal(object)
    capture_finished = Signal()
    confirmation_requested = Signal(object)

    def __init__(self, config, key, messages, parent=None, tool_executor=None):
        super().__init__(parent)
        self.config, self.key, self.messages = (dict(config), key, list(messages))
        self.tool_executor = tool_executor
        self.capture_gate = None
        self.confirmation = None
        QApplication.instance().aboutToQuit.connect(self.wait)

    def run(self):
        try:
            self.result.emit(request_reply(self.config, self.key, self.messages, self.tool_executor))
        except ValueError as exc:
            self.error.emit(str(exc))
        except Exception:
            self.error.emit(tr('api.invalid_response'))

    def prepare_capture(self):
        gate = threading.Event()
        self.capture_gate = gate
        self.capture_requested.emit(gate)
        if not gate.wait(20) or self.isInterruptionRequested():
            raise ValueError(tr('farming.capture_cancelled'))

    def cancel_pending_capture(self):
        self.requestInterruption()
        if self.capture_gate is not None:
            self.capture_gate.set()
        if self.confirmation is not None:
            self.confirmation['choice'] = 'cancel'
            self.confirmation['ready'].set()

    def confirm_farming_start(self, snapshot):
        if self.isInterruptionRequested():
            return 'cancel'
        line = tr('farming.confirm_intro')
        try:
            answer = generate_reply({**self.config, 'timeout_seconds': 5}, self.key,
                                    [{'role': 'user', 'content': tr('farming.confirm_persona_request')}],
                                    persona_prompt(self.config))
            phrase = ' '.join(answer.split())
            if 0 < len(phrase) <= 100 and not any(character.isdigit() for character in phrase):
                line = phrase
        except ValueError:
            pass
        if self.isInterruptionRequested():
            return 'cancel'
        request = {'snapshot': snapshot, 'intro': line, 'choice': 'cancel', 'ready': threading.Event()}
        self.confirmation = request
        self.confirmation_requested.emit(request)
        if not request['ready'].wait(300) or self.isInterruptionRequested():
            return 'cancel'
        return request['choice']
class ModelListWorker(ReplyWorker):
    models = Signal(list)

    def run(self):
        try:
            self.models.emit(list_models(self.config, self.key))
        except ValueError as exc:
            self.error.emit(str(exc))
        except Exception:
            self.error.emit(tr('api.invalid_response'))


STYLE = style('theme.qss')
PERSONA_LIMIT = 500


class PersonaTextEdit(QPlainTextEdit):
    def __init__(self, text):
        super().__init__(text[:PERSONA_LIMIT])
        self._limit_pending = False
        self._limit_timer = QTimer(self)
        self._limit_timer.setSingleShot(True)
        self._limit_timer.timeout.connect(self.enforce_limit)
        self.textChanged.connect(self.schedule_limit)
        self.setMinimumHeight(self.fontMetrics().lineSpacing() * 4 + 32)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(text)

    def setPlainText(self, text):
        super().setPlainText(text[:PERSONA_LIMIT])

    def insertPlainText(self, text):
        cursor = self.textCursor()
        selected = cursor.selectedText()
        room = max(0, PERSONA_LIMIT - (len(self.toPlainText()) - len(selected)))
        super().insertPlainText(text[:room])

    def insertFromMimeData(self, source):
        if source.hasText():
            self.insertPlainText(source.text())

    def schedule_limit(self):
        # Do not mutate the document inside Qt's key/IME/undo textChanged stack.
        if not self._limit_pending:
            self._limit_pending = True
            self._limit_timer.start(0)

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)
        self.enforce_limit()

    def enforce_limit(self):
        self._limit_timer.stop()
        self._limit_pending = False
        text = self.toPlainText()
        if len(text) <= PERSONA_LIMIT:
            return
        maximum = max(0, self.document().characterCount() - 1)
        end = min(maximum, len(text[:PERSONA_LIMIT].encode('utf-16-le')) // 2)
        previous = self.textCursor()
        position = max(0, min(previous.position(), end))
        with QSignalBlocker(self):
            cursor = self.textCursor()
            cursor.setPosition(end)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.setPosition(min(position, max(0, self.document().characterCount() - 1)))
            self.setTextCursor(cursor)
        # Truncation happened after the original signal; refresh dependent previews.
        self.textChanged.emit()

def gemini_chat_config(config, profiles):
    if config['provider'] == 'gemini':
        return config
    defaults = provider_defaults('gemini')
    profile = profiles.get('gemini')
    if isinstance(profile, dict):
        defaults.update({field: profile[field] for field in defaults if field in profile})
    return normalize_config({**config, **defaults, 'provider': 'gemini'}, official=True)


class SettingsDialog(QDialog):

    def __init__(self, config, key, parent=None, keys=None, profiles=None, capture_store=None, character_store=None, selected_character=None, catalog_store=None, farming_store=None, dialogue_store=None, credential_store=None, settings_store=None):
        super().__init__(parent)
        self.store_saved_key = credential_store.store_key if credential_store is not None else store_key
        config = normalize_config(config, official=True)
        if config['provider'] != 'gemini':
            config = gemini_chat_config(config, profiles or {})
            key = (keys or {}).get('gemini') or load_api_key(provider='gemini')
        self.character_store = character_store if character_store is not None else profile_store()
        self.catalog_store = catalog_store
        self.character_profiles = deepcopy(load_profiles(self.character_store))
        self.persona_defaults = {field: config[field] for field in PERSONA_FIELDS}
        self.selected_character = None
        self.provider_keys = dict(keys or {})
        self.provider_keys[config['provider']] = key
        self.loaded_provider_keys = dict(self.provider_keys)
        self.provider_drafts = {k: dict(v) for k, v in (profiles or {}).items() if k in PROVIDERS and isinstance(v, dict)}
        self.selected_provider = config['provider']
        self.test_worker = None
        self.pending_runtime_action = None
        self.setWindowTitle(tr('settings.title'))
        self.setObjectName('settingsDialog')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        self.resize(1040, 850)
        self.setMinimumSize(820, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(16)
        title = QLabel(tr('settings.title'))
        title.setObjectName('settingsHeading')
        layout.addWidget(title)
        subtitle = QLabel(tr('settings.redesign_intro'))
        subtitle.setObjectName('settingsSubtitle')
        layout.addWidget(subtitle)
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setObjectName('settingsNavigation')
        self.navigation.setFixedWidth(160)
        body.addWidget(self.navigation)
        tabs = QTabWidget()
        tabs.setObjectName('settingsTabs')
        tabs.tabBar().hide()
        body.addWidget(tabs, 1)
        layout.addLayout(body, 1)
        persona_page = SettingsColumns()
        persona = settings_card()
        persona_page.add_panel(persona, 3)
        form = QFormLayout(persona)
        configure_form(form)
        self.character_selector = QComboBox()
        self.character_selector.setObjectName('settingsCharacterSelector')
        for identifier, info in registered_characters(self.catalog_store).items():
            self.character_selector.addItem(info.name, identifier)
        form.addRow(tr('settings.character'), self.character_selector)
        self.startup_character = QComboBox()
        for identifier, info in registered_characters(self.catalog_store).items():
            self.startup_character.addItem(info.name, identifier)
        default, _ = preferences(self.catalog_store)
        index = self.startup_character.findData(default)
        if index >= 0:
            self.startup_character.setCurrentIndex(index)
        form.addRow(tr('settings.startup_character'), self.startup_character)
        management_page = SettingsColumns()
        management = settings_card()
        management_page.add_panel(management, 3)
        management_preview_card = settings_card()
        management_preview_layout = QVBoxLayout(management_preview_card)
        management_preview_layout.setContentsMargins(16, 16, 16, 16)
        management_preview_title = QLabel(tr('settings.character_preview'))
        management_preview_title.setObjectName('captureHeading')
        management_preview_layout.addWidget(management_preview_title)
        self.management_preview = CharacterSettingsPreview()
        management_preview_layout.addWidget(self.management_preview)
        management_preview_layout.addStretch()
        management_page.add_panel(management_preview_card, 2, top=True)
        management_layout = QVBoxLayout(management)
        management_layout.setContentsMargins(24, 20, 24, 20)
        management_layout.setSpacing(14)
        management_heading = QLabel(tr('settings.character_management'))
        management_heading.setObjectName('captureHeading')
        management_layout.addWidget(management_heading)
        self.management_selector = QComboBox()
        self.management_selector.setAccessibleName(tr('settings.character'))
        for identifier, info in registered_characters(self.catalog_store).items():
            self.management_selector.addItem(info.name, identifier)
        self.management_selector.currentIndexChanged.connect(self.character_selector.setCurrentIndex)
        self.character_selector.currentIndexChanged.connect(self.management_selector.setCurrentIndex)
        management_layout.addWidget(self.management_selector)
        runtime_help = QLabel(tr('settings.runtime_help'))
        runtime_help.setWordWrap(True)
        management_layout.addWidget(runtime_help)
        for text_key, action in (('settings.save_open_chat', 'chat'), ('menu.add_character', 'spawn'), ('menu.edit_characters', 'edit')):
            button = QPushButton(tr(text_key))
            button.clicked.connect(lambda checked=False, action=action: self.request_runtime_action(action))
            management_layout.addWidget(button)
        recover = QPushButton(tr('menu.recover'))
        recover.clicked.connect(self.recover_selected_pet)
        management_layout.addWidget(recover)
        self.recover_button = recover
        self.remove_character_button = QPushButton()
        self.remove_character_button.setObjectName('removeManagedCharacter')
        self.remove_character_button.clicked.connect(self.remove_selected_character)
        management_layout.addWidget(self.remove_character_button)
        self.dialogue_editor = DialogueEditor(dialogue_store)
        management_layout.addWidget(Disclosure(tr('dialogue.title'), self.dialogue_editor))
        management_layout.addStretch()
        intro = QLabel(tr('settings.intro'))
        intro.setWordWrap(True)
        form.addRow(intro)
        preset = QComboBox()
        self.preset = preset
        preset.addItems([tr('settings.custom'), *PRESETS])
        form.addRow(tr('settings.preset'), preset)
        self.fields = {}
        for field, label in [('name', tr('settings.name')), ('personality', tr('settings.personality')), ('tone', tr('settings.tone')), ('interests', tr('settings.interests'))]:
            entry = QLineEdit(config[field][:20]) if field == 'name' else PersonaTextEdit(config[field])
            if field == 'name':
                entry.setMaxLength(20)
            self.fields[field] = entry
            field_label = QLabel(tr('settings.limit_label', label=label, limit=20 if field == 'name' else PERSONA_LIMIT))
            field_label.setBuddy(entry)
            form.addRow(field_label, entry)
            if field != 'name':
                entry.textChanged.connect(lambda e=entry, l=field_label, title=label: l.setText(
                    tr('settings.field_count', label=title, count=len(e.text()), limit=PERSONA_LIMIT)))
        self.extra = PersonaTextEdit(config['extra'])
        self.extra.setPlaceholderText(tr('settings.extra_placeholder'))
        form.addRow(Disclosure(tr('settings.limit_label', label=tr('settings.extra'), limit=PERSONA_LIMIT), self.extra))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(self.preview.fontMetrics().lineSpacing() * 10 + 32)
        self.preview_section = Disclosure(tr('settings.preview', name=config['name']), self.preview)
        self.action_checks = {}
        actions = QGridLayout()
        for index, state in enumerate(STATES):
            checkbox = QCheckBox(tr('action.' + state))
            checkbox.setChecked(True)
            checkbox.setObjectName('allow_' + state)
            if state == 'idle':
                checkbox.setEnabled(False)
            self.action_checks[state] = checkbox
            actions.addWidget(checkbox, index // 2, index % 2)
        action_content = QWidget()
        action_layout = QVBoxLayout(action_content)
        action_layout.addLayout(actions)
        action_help = QLabel(tr('settings.actions_help'))
        action_help.setWordWrap(True)
        action_layout.addWidget(action_help)
        form.addRow(Disclosure(tr('settings.allowed_actions'), action_content))
        persona_preview_card = settings_card()
        persona_preview_layout = QVBoxLayout(persona_preview_card)
        persona_preview_layout.setContentsMargins(16, 16, 16, 16)
        persona_preview_title = QLabel(tr('settings.character_preview'))
        persona_preview_title.setObjectName('captureHeading')
        persona_preview_layout.addWidget(persona_preview_title)
        self.character_preview = CharacterSettingsPreview()
        persona_preview_layout.addWidget(self.character_preview)
        persona_preview_layout.addWidget(self.preview_section)
        persona_preview_layout.addStretch()
        persona_page.add_panel(persona_preview_card, 2, top=True)
        persona_scroll = QScrollArea()
        persona_scroll.setWidgetResizable(True)
        persona_scroll.setWidget(persona_page)
        tabs.addTab(persona_scroll, tr('settings.persona_tab'))
        self.management_page = QScrollArea()
        self.management_page.setWidgetResizable(True)
        self.management_page.setWidget(management_page)
        tabs.addTab(self.management_page, tr('settings.character_management'))
        api_page = SettingsColumns()
        api = settings_card()
        api_page.add_panel(api, 3)
        api_form = QFormLayout(api)
        configure_form(api_form)
        self.api_form = api_form
        help_text = QLabel(tr('settings.api_help'))
        help_text.setWordWrap(True)
        api_form.addRow(help_text)
        api_form.addRow(settings_link(tr('settings.gemini_key_link'), 'https://aistudio.google.com/apikey'))
        self.provider = QComboBox()
        self.provider.setObjectName('providerSelector')
        self.provider.addItem(PROVIDERS['gemini']['label'], 'gemini')
        api_form.addRow(tr('settings.provider'), self.provider)
        advanced = QWidget()
        self.connection_form = QFormLayout(advanced)
        configure_form(self.connection_form)
        self.api_format = QComboBox()
        for identifier in ('openai', 'gemini', 'claude'):
            self.api_format.addItem(tr('settings.format_' + identifier), identifier)
        self.api_format.setCurrentIndex(self.api_format.findData(config['api_format']))
        self.api_format.setEnabled(config['provider'] == 'other')
        self.connection_form.addRow(tr('settings.api_format'), self.api_format)
        self.fields['base_url'] = QLineEdit(config['base_url'])
        self.fields['base_url'].setPlaceholderText(tr('settings.url_placeholder'))
        self.connection_form.addRow(tr('settings.base_url'), self.fields['base_url'])
        self.model_combo = QComboBox()
        self.model_combo.setObjectName('modelSelector')
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.setEditText(config['model'])
        self.fields['model'] = self.model_combo.lineEdit()
        self.fields['model'].setPlaceholderText(tr('settings.model_placeholder'))
        self.key = QLineEdit(key)
        self.key.setObjectName('apiKey')
        self.key.setEchoMode(QLineEdit.Password)
        api_form.addRow(tr('settings.api_key'), self.key)
        show = QPushButton(tr('settings.toggle_key'))
        show.clicked.connect(lambda: self.key.setEchoMode(QLineEdit.Normal if self.key.echoMode() == QLineEdit.Password else QLineEdit.Password))
        api_form.addRow('', show)
        self.load_key_button = QPushButton(tr('settings.reload_key'))
        self.load_key_button.setObjectName('reloadApiKey')
        self.load_key_button.clicked.connect(self.reload_key)
        api_form.addRow('', self.load_key_button)
        self.key_source = QLabel()
        self.key_source.setWordWrap(True)
        loaded_key, source = key_with_source(self.selected_provider)
        if key and key == loaded_key:
            self.key_source.setText(tr('settings.key_source', source=source))
        else:
            self.key_source.hide()
        api_form.addRow(self.key_source)
        api_form.addRow(tr('settings.model'), self.model_combo)
        self.models_button = QPushButton(tr('settings.load_models'))
        self.models_button.setObjectName('loadModels')
        self.models_button.clicked.connect(self.load_models)
        api_form.addRow('', self.models_button)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(64, 65536)
        self.max_tokens.setSingleStep(512)
        self.max_tokens.setValue(int(config.get('max_tokens', 4096)))
        self.connection_form.addRow(tr('settings.max_tokens'), self.max_tokens)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 180)
        self.timeout.setSingleStep(15)
        self.timeout.setValue(int(config['timeout_seconds']))
        self.connection_form.addRow(tr('settings.timeout'), self.timeout)
        note = QLabel(tr('settings.key_help'))
        note.setWordWrap(True)
        api_form.addRow(note)
        api_form.addRow(Disclosure(tr('settings.advanced_connection'), advanced))
        connection_test = settings_card()
        test_form = QFormLayout(connection_test)
        configure_form(test_form)
        test_heading = QLabel(tr('settings.connection_preview'))
        test_heading.setObjectName('captureHeading')
        test_form.addRow(test_heading)
        self.test_prompt = QLineEdit(tr('settings.test_prompt'))
        self.test_prompt.setMaxLength(500)
        test_form.addRow(tr('settings.test_message'), self.test_prompt)
        self.test_button = QPushButton(tr('settings.test_button'))
        self.test_button.setObjectName('testConnection')
        self.test_button.clicked.connect(self.test_connection)
        test_form.addRow(self.test_button)
        self.test_output = QPlainTextEdit()
        self.test_output.setReadOnly(True)
        self.test_output.setMaximumHeight(110)
        self.test_output.setPlaceholderText(tr('settings.test_help'))
        test_form.addRow(tr('settings.test_result'), self.test_output)
        api_page.add_panel(connection_test, 2, top=True)
        self.api_scroll = QScrollArea()
        self.api_scroll.setObjectName('apiSettingsScroll')
        self.api_scroll.setWidgetResizable(True)
        self.api_scroll.setWidget(api_page)
        tabs.addTab(self.api_scroll, tr('settings.api_tab'))
        self.sol_erda_panel = SolErdaPanel()
        self.meso_panel = MesoPanel()
        self.capture_store = capture_store if capture_store is not None else QSettings('DesktopShimeji', 'Capture')
        capture = QWidget()
        capture.setObjectName('settingsPage')
        capture_layout = QVBoxLayout(capture)
        capture_layout.setContentsMargins(20, 20, 20, 20)
        capture_layout.setSpacing(16)
        capture_intro = QLabel(tr('settings.capture_intro'))
        capture_intro.setWordWrap(True)
        capture_layout.addWidget(capture_intro)
        self.read_all_button = QPushButton(tr('settings.read_all'))
        self.read_all_button.setObjectName('readAllCapture')
        self.read_all_button.clicked.connect(self.read_all_capture)
        capture_layout.addWidget(self.read_all_button, 0, Qt.AlignRight)
        cards = SettingsColumns(margin=0)
        for panel, title_key in ((self.sol_erda_panel, 'settings.sol_erda_tab'), (self.meso_panel, 'settings.meso_tab')):
            card = QWidget()
            card.setObjectName('captureCard')
            card_layout = QVBoxLayout(card)
            heading = QLabel(tr(title_key))
            heading.setObjectName('captureHeading')
            card_layout.addWidget(heading)
            # The shared page provides the instructions once, above both cards.
            panel.layout().itemAt(0).widget().hide()
            panel.setMinimumHeight(410)
            card_layout.addWidget(panel)
            cards.add_panel(card)
        capture_layout.addWidget(cards)
        capture_layout.addStretch()
        self.capture_page = QScrollArea()
        self.capture_page.setWidgetResizable(True)
        self.capture_page.setWidget(capture)
        tabs.addTab(self.capture_page, tr('settings.capture_tab'))
        from maeagi_biseo.ui.farming_panel import FarmingPanel
        self.farming_panel = FarmingPanel(store=farming_store)
        tabs.addTab(self.farming_panel, tr('farming.tab'))
        self.obs_page = ObsSettingsPage(settings_store)
        self.obs_page.placement.set_character(self.character_selector.currentData())
        self.character_selector.currentIndexChanged.connect(
            lambda: self.obs_page.placement.set_character(self.character_selector.currentData()))
        if any(getattr(pet, 'broadcast_window', None) is not None and pet.broadcast_window.isVisible()
               for pet in getattr(parent, 'pets', [])):
            self.obs_page.enabled.setChecked(True)
        self.obs_scroll = QScrollArea()
        self.obs_scroll.setObjectName('obsSettingsScroll')
        self.obs_scroll.setWidgetResizable(True)
        self.obs_scroll.setWidget(self.obs_page)
        tabs.addTab(self.obs_scroll, tr('obs.settings_tab'))
        from maeagi_biseo.ui.about import AboutPage
        self.about_page = AboutPage(updates=getattr(parent, 'updates', None))
        self.about_index = tabs.addTab(self.about_page, tr('about.tab'))
        for panel in (self.sol_erda_panel, self.meso_panel):
            panel.manual.configure(self.capture_store)
        self.capture_queue = []
        self.capture_sequence_timer = QTimer(self)
        self.capture_sequence_timer.setInterval(150)
        self.capture_sequence_timer.timeout.connect(self.advance_capture_queue)
        for index in range(tabs.count()):
            page = tabs.widget(index)
            if isinstance(page, QScrollArea):
                page.setProperty('settingsPanel', True)
            self.navigation.addItem(tabs.tabText(index))
        self.navigation.currentRowChanged.connect(tabs.setCurrentIndex)
        tabs.currentChanged.connect(self.navigation.setCurrentRow)
        self.navigation.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.setObjectName('settingsActions')
        buttons.button(QDialogButtonBox.Save).setObjectName('saveSettings')
        buttons.button(QDialogButtonBox.Save).setText(tr('common.save'))
        buttons.button(QDialogButtonBox.Cancel).setText(tr('common.cancel'))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_chat_theme(self, appearance_for(parent))
        preset.currentTextChanged.connect(self.apply_preset)
        for entry in self.fields.values():
            entry.textChanged.connect(self.update_preview)
        self.extra.textChanged.connect(self.update_preview)
        self.provider.currentIndexChanged.connect(self.change_provider)
        self.update_connection_fields()
        self.update_preview()
        index = self.character_selector.findData(selected_character)
        if index >= 0:
            self.character_selector.setCurrentIndex(index)
        self.change_character()
        self.character_selector.currentIndexChanged.connect(self.change_character)

    def read_all_capture(self):
        if self.capture_queue or any(p.manual.busy for p in (self.sol_erda_panel, self.meso_panel)):
            return
        self.capture_queue = [(self.sol_erda_panel, CAPTURE_DELAY_MS), (self.meso_panel, 0)]
        self.capture_sequence_timer.start()
        self.advance_capture_queue()

    def advance_capture_queue(self):
        busy = any(p.manual.busy for p in (self.sol_erda_panel, self.meso_panel))
        self.read_all_button.setEnabled(not busy and not self.capture_queue)
        if self.capture_queue and not busy:
            panel, delay_ms = self.capture_queue.pop(0)
            panel.manual.schedule('read', delay_ms=delay_ms, restore_after=not self.capture_queue)
        elif not busy:
            self.capture_sequence_timer.stop()
            if self.isMinimized():
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def done(self, result):
        self.capture_queue.clear()
        self.capture_sequence_timer.stop()
        for panel in (self.sol_erda_panel, self.meso_panel):
            panel.manual.cancel_pending()
        super().done(result)

    def stash_character(self):
        if self.selected_character is not None:
            self.character_profiles[self.selected_character] = {
                'persona': {field: self.fields[field].text().strip() for field in PERSONA_FIELDS if field != 'extra'} | {'extra': self.extra.toPlainText().strip()},
                'allowed_actions': [state for state, check in self.action_checks.items() if check.isChecked()]}

    def runtime_pet(self):
        from maeagi_biseo.app import PETS
        parent = self.parentWidget()
        pets = parent.pets if parent is not None and hasattr(parent, 'pets') else PETS
        return next((pet for pet in pets if pet.kind == self.character_selector.currentData()), None)

    def request_runtime_action(self, action):
        if action == 'edit':
            from maeagi_biseo.app import edit_characters
            edit_characters(parent=self, identifier=self.character_selector.currentData())
            self.refresh_character_choices()
            return
        if action == 'spawn':
            from maeagi_biseo.app import spawn_pet
            spawn_pet(kind=self.character_selector.currentData())
            self.refresh_runtime_controls()
            return
        self.pending_runtime_action = (action, self.character_selector.currentData())
        self.save()

    def refresh_character_choices(self):
        self.stash_character()
        characters = registered_characters(self.catalog_store)
        selected = self.character_selector.currentData()
        startup = self.startup_character.currentData()
        if startup not in characters:
            startup = preferences(self.catalog_store)[0]
        for selector, previous in ((self.character_selector, selected), (self.management_selector, selected),
                                   (self.startup_character, startup)):
            with QSignalBlocker(selector):
                selector.clear()
                for identifier, info in characters.items():
                    selector.addItem(info.name, identifier)
                selector.setCurrentIndex(max(0, selector.findData(previous)))
        for identifier, profile in load_profiles(self.character_store).items():
            self.character_profiles.setdefault(identifier, profile)
        self.selected_character = None
        self.change_character()
        self.obs_page.placement.set_character(self.selected_character)

    def remove_selected_character(self):
        identifier = self.character_selector.currentData()
        if not confirm_character_removal(self, identifier, self.catalog_store):
            return
        from maeagi_biseo.app import close_removed_character
        close_removed_character(identifier)
        self.refresh_character_choices()
        parent = self.parentWidget()
        if isinstance(parent, ChatWindow):
            parent.refresh_targets()

    def recover_selected_pet(self):
        pet = self.runtime_pet()
        if pet is not None:
            pet.go_to_floor()

    def refresh_runtime_controls(self):
        pet = self.runtime_pet()
        self.recover_button.setEnabled(pet is not None)
        characters = registered_characters(self.catalog_store)
        info = characters.get(self.character_selector.currentData())
        self.remove_character_button.setText(tr(removal_action(info)))
        self.remove_character_button.setEnabled(info is not None and len(characters) > 1)
        self.remove_character_button.setToolTip(tr('editor.delete_last') if len(characters) == 1 else '')

    def change_character(self):
        self.stash_character()
        self.selected_character = self.character_selector.currentData()
        self.character_preview.set_character(self.selected_character)
        self.management_preview.set_character(self.selected_character)
        profile = self.character_profiles.get(self.selected_character, {})
        persona = {**self.persona_defaults, **profile.get('persona', {})}
        if not profile and self.selected_character is not None:
            persona['name'] = self.character_selector.currentText()
        for field in PERSONA_FIELDS:
            if field == 'extra':
                self.extra.setPlainText(persona[field])
            else:
                self.fields[field].setText(persona[field])
        self.preset.setCurrentIndex(0)
        allowed = profile.get('allowed_actions', list(STATES))
        for state, check in self.action_checks.items():
            check.setChecked(state == 'idle' or state in allowed)
        self.update_preview()

        self.refresh_runtime_controls()

    def update_connection_fields(self):
        custom = self.selected_provider in ('local', 'other')
        self.connection_form.setRowVisible(self.fields['base_url'], custom)
        self.connection_form.setRowVisible(self.api_format, self.selected_provider == 'other')
        if not custom:
            self.fields['base_url'].setText(PROVIDERS[self.selected_provider]['base_url'])

    def change_provider(self):
        old = self.selected_provider
        self.provider_drafts[old] = self.values()
        self.provider_keys[old] = self.key.text().strip()
        identifier = self.provider.currentData()
        self.selected_provider = identifier
        config = self.provider_drafts.get(identifier, provider_defaults(identifier))
        self.fields['base_url'].setText(config['base_url'])
        self.model_combo.clear()
        self.model_combo.setEditText(config['model'])
        self.api_format.setCurrentIndex(self.api_format.findData(config['api_format']))
        self.api_format.setEnabled(identifier == 'other')
        self.max_tokens.setValue(int(config.get('max_tokens', 4096)))
        self.timeout.setValue(int(config.get('timeout_seconds', 90 if identifier == 'gemini' else 45)))
        if identifier in self.provider_keys:
            self.key.setText(self.provider_keys[identifier])
            self.key_source.clear()
            self.key_source.hide()
        else:
            self.reload_key()
        self.key.setEchoMode(QLineEdit.Password)
        self.update_connection_fields()
        self.test_output.clear()

    def reload_key(self):
        key, source = key_with_source(self.selected_provider)
        self.loaded_provider_keys[self.selected_provider] = key
        self.key.setText(key)
        self.key_source.setText(tr('settings.key_source', source=source) if source else tr('settings.key_missing'))
        self.key_source.show()

    def load_models(self):
        if self.test_worker:
            return
        self.set_testing(True)
        self.test_output.setPlainText(tr('settings.models_running'))
        worker = ModelListWorker(self.values(), self.key.text().strip(), [], QApplication.instance())
        self.test_worker = worker
        worker.models.connect(self.models_loaded)
        worker.error.connect(self.test_failed)
        worker.finished.connect(self.test_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def models_loaded(self, models):
        previous = self.fields['model'].text().strip()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if previous in models:
            self.model_combo.setCurrentText(previous)
        elif self.api_format.currentData() == 'gemini':
            self.model_combo.setCurrentText(choose_chat_model(models))
        self.test_output.setPlainText(tr('settings.models_success', count=len(models)))
        self.api_scroll.ensureWidgetVisible(self.model_combo)

    def test_connection(self):
        if self.test_worker:
            return
        prompt = self.test_prompt.text().strip()
        if not prompt:
            self.test_output.setPlainText(tr('settings.test_empty'))
            return
        self.set_testing(True)
        self.test_output.setPlainText(tr('settings.test_running', timeout=self.timeout.value()))
        self.api_scroll.ensureWidgetVisible(self.test_output)
        # Keep the worker alive even if the settings dialog is closed mid-request.
        worker = ReplyWorker(self.values(), self.key.text().strip(),
            [dict(role='user', content=prompt)], QApplication.instance())
        self.test_worker = worker
        worker.result.connect(self.test_succeeded)
        worker.error.connect(self.test_failed)
        worker.finished.connect(self.test_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def set_testing(self, active):
        for widget in (self.test_button, self.test_prompt, self.key, self.provider,
                       self.fields['base_url'], self.model_combo, self.models_button,
                       self.load_key_button, self.max_tokens, self.timeout):
            widget.setEnabled(not active)
        self.api_format.setEnabled(not active and self.selected_provider == 'other')

    def test_succeeded(self, answer):
        self.test_output.setPlainText(tr('settings.test_success', answer=answer))
        self.api_scroll.ensureWidgetVisible(self.test_output)

    def test_failed(self, error):
        self.test_output.setPlainText(tr('settings.test_failure', error=error))
        self.api_scroll.ensureWidgetVisible(self.test_output)

    def test_finished(self):
        self.test_worker = None
        self.set_testing(False)

    def values(self):
        return {**{k: v.text().strip() for k, v in self.fields.items()}, 'extra': self.extra.toPlainText().strip(),
                'provider': self.selected_provider, 'api_format': self.api_format.currentData(),
                'max_tokens': str(self.max_tokens.value()), 'timeout_seconds': str(self.timeout.value())}

    def apply_preset(self, name):
        if name in PRESETS:
            for field, value in zip(('personality', 'tone', 'interests'), PRESETS[name]):
                self.fields[field].setText(value)

    def update_preview(self):
        self.preview.setPlainText(persona_prompt(self.values()))
        self.preview_section.toggle.setText(tr('settings.preview', name=self.fields['name'].text().strip()))

    def save(self):
        try:
            scripts = self.dialogue_editor.values()
        except ValueError as exc:
            QMessageBox.warning(self, tr('dialogue.title'), str(exc))
            return
        self.stash_character()
        if any(not profile['persona'].get('name', '').strip() for profile in self.character_profiles.values() if 'persona' in profile):
            QMessageBox.warning(self, tr('settings.name_required_title'), tr('settings.name_required'))
            return
        if not self.fields['name'].text().strip():
            QMessageBox.warning(self, tr('settings.name_required_title'), tr('settings.name_required'))
            return
        self.provider_keys[self.selected_provider] = self.key.text().strip()
        try:
            for provider, key in self.provider_keys.items():
                if key != self.loaded_provider_keys.get(provider, ''):
                    self.store_saved_key(provider, key)
                    self.loaded_provider_keys[provider] = key
        except (OSError, KeyError):
            QMessageBox.warning(self, tr('settings.title'), tr('settings.key_save_error'))
            return
        self.provider_drafts[self.selected_provider] = self.values()
        self.sol_erda_panel.manual.save_settings()
        self.meso_panel.manual.save_settings()
        self.capture_store.sync()
        save_scripts(scripts, self.dialogue_editor.store)
        save_profiles(self.character_profiles, self.character_store)
        if self.startup_character.currentData():
            set_default(self.startup_character.currentData(), store=self.catalog_store)
        self.accept()

class ChatWindow(QWidget):

    def __init__(self, pets, dialogue, settings_store=None, character_store=None, catalog_store=None, farming_store=None, capture_store=None, avatar_root=None):
        super().__init__()
        self.pets, self.dialogue = (pets, dialogue)
        self.avatar_root = avatar_root if avatar_root is not None else avatar_image_root()
        self._settings_dialog = None
        self.character_store = character_store if character_store is not None else profile_store()
        self.farming_store = farming_store
        self.capture_store = capture_store if capture_store is not None else QSettings('DesktopShimeji', 'Capture')
        self.catalog_store = catalog_store
        self.store = settings_store if settings_store is not None else QSettings('DesktopShimeji', 'Chat')
        saved = {k: str(self.store.value(k, v)) for k, v in DEFAULTS.items()}
        if saved['name'] in PERSONAS.get('previous_names', []):
            saved['name'] = DEFAULTS['name']
            self.store.setValue('name', saved['name'])
        legacy = PERSONAS.get('legacy_defaults', {})
        if legacy and all(not self.store.contains(k) or str(self.store.value(k)) == value
                          for k, value in legacy.items()):
            saved.update({k: DEFAULTS[k] for k in legacy})
        if not self.store.contains('provider') and self.store.contains('base_url'):
            saved.pop('provider', None)
        self.config = normalize_config(saved, official=True)
        try:
            self.provider_profiles = json.loads(str(self.store.value('provider_profiles', '{}')))
            if not isinstance(self.provider_profiles, dict):
                self.provider_profiles = {}
        except ValueError:
            self.provider_profiles = {}
        previous_provider = self.config['provider']
        if previous_provider != 'gemini':
            self.provider_profiles[previous_provider] = {
                field: self.config[field] for field in provider_defaults(previous_provider)
            }
            self.config = gemini_chat_config(self.config, self.provider_profiles)
        self.key = load_api_key(provider='gemini')
        self.provider_keys = {'gemini': self.key}
        self.history = []
        self.histories = {}
        self.transcripts = {}
        self.drafts = {}
        self.unread = {}
        try:
            crops = json.loads(str(self.store.value('chat_avatar_crops', '{}')))
        except ValueError:
            crops = {}
        self.avatar_crops = {key: normalize_crop(value) for key, value in crops.items()} if isinstance(crops, dict) else {}
        self.contact_items = {}
        self.contact_paths = {}
        self.previous_entry = None
        self.worker = None
        self.thread_id = None
        self.setObjectName('chat')
        self.setWindowTitle(tr('chat.title'))
        self.resize(820, 720)
        self.setMinimumSize(460, 540)
        shell = QHBoxLayout(self)
        shell.setContentsMargins(16, 16, 16, 16)
        shell.setSpacing(12)
        self.inbox = QWidget()
        self.inbox.setObjectName('chatInbox')
        self.inbox.setAttribute(Qt.WA_StyledBackground)
        self.inbox.setFixedWidth(222)
        inbox_layout = QVBoxLayout(self.inbox)
        inbox_layout.setContentsMargins(12, 14, 12, 12)
        inbox_title = QLabel(tr('chat.inbox'))
        inbox_title.setObjectName('chatInboxTitle')
        inbox_layout.addWidget(inbox_title)
        self.contact_search = QLineEdit()
        self.contact_search.setPlaceholderText(tr('chat.find_character'))
        self.contact_search.setClearButtonEnabled(True)
        self.contact_search.textChanged.connect(self.filter_contacts)
        inbox_layout.addWidget(self.contact_search)
        self.contacts = QListWidget()
        self.contacts.setObjectName('chatContacts')
        self.contacts.setAccessibleName(tr('chat.inbox'))
        self.contacts.setIconSize(QSize(40, 40))
        self.contacts.setTextElideMode(Qt.ElideRight)
        self.contacts.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.contacts.currentItemChanged.connect(self.select_contact)
        inbox_layout.addWidget(self.contacts, 1)
        shell.addWidget(self.inbox)
        channel = QWidget()
        layout = QVBoxLayout(channel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        shell.addWidget(channel, 1)
        header_widget = QWidget()
        header_widget.setObjectName('chatHeader')
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(12)
        header = QHBoxLayout()
        self.thread_avatar = QLabel()
        self.thread_avatar.setFixedSize(44, 44)
        header.addWidget(self.thread_avatar)
        self.heading = QLabel()
        self.heading.setObjectName('chatHeading')
        self.heading.setTextFormat(Qt.PlainText)
        header.addWidget(self.heading, 1)
        self.profile_button = QPushButton(tr('chat.profile'))
        self.profile_button.clicked.connect(self.edit_avatar)
        header.addWidget(self.profile_button)
        self.theme_selector = QComboBox()
        self.theme_selector.setObjectName('chatThemeSelector')
        self.theme_selector.setAccessibleName(tr('chat.appearance'))
        self.theme_selector.addItem(tr('chat.theme_light'), 'light')
        self.theme_selector.addItem(tr('chat.theme_dark'), 'dark')
        saved_theme = str(self.store.value('appearance', 'light'))
        self.theme_selector.setCurrentIndex(max(0, self.theme_selector.findData(saved_theme)))
        self.theme_selector.currentIndexChanged.connect(self.change_theme)
        header.addWidget(self.theme_selector)
        header_layout.addLayout(header)
        controls = QHBoxLayout()
        self.target_selector = QComboBox()
        self.target_selector.setObjectName('chatCharacterSelector')
        self.target_selector.setAccessibleName(tr('settings.character'))
        self.target_selector.currentIndexChanged.connect(self.select_target)
        controls.addWidget(self.target_selector, 1)
        self.settings_button = QPushButton(tr('common.settings'))
        self.settings_button.setObjectName('openSettings')
        self.settings_button.clicked.connect(self.settings)
        controls.addWidget(self.settings_button)
        self.summon_button = QPushButton(tr('chat.summon'))
        self.summon_button.setObjectName('summonChatCharacter')
        self.summon_button.clicked.connect(self.summon_character)
        controls.addWidget(self.summon_button)
        self.clear_button = QPushButton(tr('chat.new'))
        self.clear_button.clicked.connect(self.clear_chat)
        controls.addWidget(self.clear_button)
        header_layout.addLayout(controls)
        layout.addWidget(header_widget)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('chatThreadScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().installEventFilter(self)
        self.messages = QWidget()
        self.messages.setObjectName('chatMessages')
        conversation = QVBoxLayout(self.messages)
        conversation.setSizeConstraint(QLayout.SetMinimumSize)
        conversation.setContentsMargins(4, 10, 4, 10)
        self.empty_chat = QLabel(tr('chat.empty_thread'))
        self.empty_chat.setObjectName('chatSubtitle')
        self.empty_chat.setAlignment(Qt.AlignCenter)
        self.empty_chat.setWordWrap(True)
        conversation.addWidget(self.empty_chat)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(9)
        self.rows.setAlignment(Qt.AlignTop)
        conversation.addLayout(self.rows, 1)
        self.scroll.setWidget(self.messages)
        layout.addWidget(self.scroll, 1)
        self.status = QLabel(tr('chat.welcome'))
        self.status.setObjectName('chatStatus')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.capture_notice = CaptureNotice(self)
        composer = QWidget()
        composer.setObjectName('chatComposer')
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 12, 12, 12)
        composer_layout.setSpacing(10)
        self.input = MessageInput()
        self.input.setObjectName('chatInput')
        self.input.setPlaceholderText(tr('chat.input_placeholder'))
        self.input.sendRequested.connect(self.send)
        self.input.setFixedHeight(72)
        composer_layout.addWidget(self.input)
        composer_actions = QHBoxLayout()
        input_help = QLabel(tr('chat.input_help'))
        input_help.setObjectName('chatInputHelp')
        composer_actions.addWidget(input_help, 1)
        self.send_button = QPushButton(tr('chat.send'))
        self.send_button.setObjectName('send')
        self.send_button.clicked.connect(self.send)
        composer_actions.addWidget(self.send_button)
        composer_layout.addLayout(composer_actions)
        layout.addWidget(composer)
        apply_chat_theme(self, self.theme_selector.currentData())
        self.refresh_heading()
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda low, high: self.scroll.verticalScrollBar().setValue(high))
        self.target_refresh_timer = QTimer(self)
        self.target_refresh_timer.timeout.connect(self.refresh_targets)
        self.target_refresh_timer.start(700)
        self.refresh_targets()
        self.update_chat_layout()

    def change_theme(self):
        mode = self.theme_selector.currentData()
        apply_chat_theme(self, mode)
        self.store.setValue('appearance', mode)
        self.store.sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'target_selector'):
            self.update_chat_layout()

    def update_chat_layout(self):
        compact = self.width() < 700
        self.inbox.setVisible(not compact)
        self.target_selector.setVisible(compact)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Resize and hasattr(self, 'rows')
                and watched is self.scroll.viewport()):
            width = event.size().width()
            for bubble in self.messages.findChildren(QLabel):
                if bubble.property('chatBubble'):
                    self.size_message(bubble, width)
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and hasattr(self, 'contacts'):
            self.mark_thread_read()

    def profile_name(self, identifier, name):
        return persona_for(identifier, {**self.config, 'name': name}, self.character_store)['name']

    def avatar_image(self, identifier):
        custom = custom_avatar(custom_avatar_path(self.avatar_root, identifier)) if identifier else None
        return custom if custom is not None else avatar_source(self.contact_paths.get(identifier))

    def avatar(self, identifier, name, size):
        return avatar_pixmap(self.avatar_image(identifier), name, size,
                             self.avatar_crops.get(identifier, DEFAULT_CROP))

    def edit_avatar(self):
        identifier = self.thread_id
        if not identifier:
            return
        character = avatar_source(self.contact_paths.get(identifier))
        custom = custom_avatar(custom_avatar_path(self.avatar_root, identifier))
        image = custom if custom is not None else character
        if image is None:
            return
        dialog = ChatAvatarDialog(image, self.current_config()['name'],
                                  self.avatar_crops.get(identifier, DEFAULT_CROP), self,
                                  character_image=character, custom=custom is not None)
        if dialog.exec() == QDialog.Accepted:
            target = custom_avatar_path(self.avatar_root, identifier)
            try:
                if dialog.image_choice == 'character':
                    remove_custom_avatar(target)
                elif dialog.image_choice is not None:
                    save_custom_avatar(dialog.image_choice, target)
            except OSError:
                QMessageBox.warning(self, tr('chat.avatar_title'), tr('chat.avatar_save_failed'))
                dialog.deleteLater()
                return
            self.avatar_crops[identifier] = dialog.crop()
            self.store.setValue('chat_avatar_crops', json.dumps(self.avatar_crops))
            self.store.sync()
            self.refresh_heading()
            self.refresh_contact(identifier, refresh_icon=True)
            self.render_history()
        dialog.deleteLater()

    def select_contact(self, current, _previous):
        if current is not None and not self.worker:
            self.target_selector.setCurrentIndex(self.target_selector.findData(current.data(Qt.UserRole)))

    def filter_contacts(self, query):
        needle = query.strip().casefold()
        for item in self.contact_items.values():
            item.setHidden(needle not in item.data(Qt.AccessibleTextRole).casefold())

    def refresh_contact(self, identifier, *, refresh_icon=False):
        item = self.contact_items.get(identifier)
        if item is None:
            return
        index = self.target_selector.findData(identifier)
        name = self.profile_name(identifier, self.target_selector.itemText(index))
        entries = self.transcripts.get(identifier) or []
        preview = tr('chat.no_messages')
        if entries:
            entry = entries[-1]
            body = ' '.join(entry['text'].split())
            count = self.unread.get(identifier, 0)
            time_text = entry['time'].strftime('%H:%M')
            if count:
                name_line = tr('chat.contact_unread', name=name, count=count)
            else:
                name_line = name
            preview = f'{time_text} · {body}'
        else:
            name_line = name
        item.setData(Qt.AccessibleTextRole, name)
        item.setText(f'{name_line}\n{preview}')
        if refresh_icon:
            pixmap = self.avatar(identifier, name, 40)
            icon = QIcon(pixmap)
            icon.addPixmap(pixmap, QIcon.Selected)
            item.setIcon(icon)

    def mark_thread_read(self):
        identifier = self.thread_id
        if self.unread.pop(identifier, 0):
            self.refresh_contact(identifier)

    def prioritize_contact(self, identifier):
        item = self.contact_items.get(identifier)
        if item is None:
            return
        row = self.contacts.row(item)
        if row <= 0:
            return
        with QSignalBlocker(self.contacts):
            selected = self.contacts.currentItem()
            self.contacts.insertItem(0, self.contacts.takeItem(row))
            self.contacts.setCurrentItem(selected)
            if selected is item:
                self.contacts.scrollToTop()

    def refresh_heading(self):
        name = self.current_config()['name']
        identifier = self.thread_id
        self.heading.setText(name)
        self.thread_avatar.setPixmap(self.avatar(identifier, name, 44))
        self.profile_button.setEnabled(avatar_source(self.contact_paths.get(identifier)) is not None and not self.worker)
        self.update_summon_button()
        self.setWindowTitle(tr('chat.title_for', name=name))

    def current_config(self):
        identifier = self.thread_id
        fallback = dict(self.config)
        info = registered_characters(self.catalog_store).get(identifier)
        if info:
            fallback['name'] = info.name
        return {**self.config, **persona_for(identifier, fallback, self.character_store)} if identifier else dict(self.config)

    @property
    def target(self):
        return next((pet for pet in self.pets if pet.kind == self.thread_id), None)

    def update_summon_button(self):
        available = self.thread_id in self.contact_items
        self.summon_button.setVisible(available)
        active = self.target is not None
        self.summon_button.setText(tr('chat.summoned' if active else 'chat.summon'))
        self.summon_button.setEnabled(available and not active and not self.worker)

    def summon_character(self):
        if self.worker or self.target is not None or self.thread_id not in self.contact_items:
            return
        from maeagi_biseo.app import spawn_pet
        pet = spawn_pet(kind=self.thread_id)
        if pet is not None and pet not in self.pets:
            self.pets.append(pet)
        self.update_summon_button()

    def select_target(self):
        if self.worker:
            return
        identifier = self.target_selector.currentData()
        if identifier == self.thread_id:
            self.mark_thread_read()
            return
        previous = self.thread_id
        self.histories[previous] = self.history
        self.drafts[previous] = self.input.toPlainText()
        self.thread_id = identifier
        self.history = self.histories.setdefault(identifier, [])
        self.input.clear()
        self.input.setPlainText(self.drafts.get(identifier, ''))
        with QSignalBlocker(self.contacts):
            self.contacts.setCurrentItem(self.contact_items.get(identifier))
        self.render_history()
        self.refresh_heading()
        self.mark_thread_read()

    def render_history(self):
        self.clear_rows()
        identifier = self.thread_id
        if identifier in self.transcripts:
            for entry in self.transcripts[identifier]:
                self.render_entry(entry)
            return
        config = self.current_config()
        for message in self.history:
            user = message['role'] == 'user'
            self.render_entry(dict(speaker=tr('chat.user') if user else config['name'], text=message['content'],
                                   kind='user' if user else 'assistant', time=datetime.now()))

    def refresh_targets(self):
        if self.worker or getattr(self, '_refreshing_targets', False):
            return
        characters = registered_characters(self.catalog_store)
        self.contact_paths = {identifier: info.path for identifier, info in characters.items()}
        items = [(identifier, info.name) for identifier, info in characters.items()]
        existing = [(self.target_selector.itemData(index), self.target_selector.itemText(index)) for index in range(self.target_selector.count())]
        if items == existing:
            self.update_summon_button()
            return
        selected = self.thread_id or preferences(self.catalog_store)[0]
        self.target_selector.blockSignals(True)
        self.contacts.blockSignals(True)
        self.target_selector.clear()
        self.contacts.clear()
        self.contact_items.clear()
        for identifier, name in items:
            self.target_selector.addItem(name, identifier)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
            item.setData(Qt.UserRole, identifier)
            self.contacts.addItem(item)
            self.contact_items[identifier] = item
            self.refresh_contact(identifier, refresh_icon=True)
        index = self.target_selector.findData(selected)
        if index >= 0:
            self.target_selector.setCurrentIndex(index)
        if self.target_selector.currentData() in self.contact_items:
            self.contacts.setCurrentItem(self.contact_items[self.target_selector.currentData()])
        self.target_selector.blockSignals(False)
        self.contacts.blockSignals(False)
        self.filter_contacts(self.contact_search.text())
        self.select_target()

    def open_for(self, pet=None, *, identifier=None):
        if not self.worker:
            self.refresh_targets()
            identifier = identifier or getattr(pet, 'kind', None) or self.thread_id
            index = self.target_selector.findData(identifier)
            if index >= 0:
                self.target_selector.blockSignals(True)
                self.target_selector.setCurrentIndex(index)
                self.target_selector.blockSignals(False)
            self.select_target()
            identifier = self.thread_id
            self.prioritize_contact(identifier)
            self.refresh_contact(identifier, refresh_icon=True)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        self.mark_thread_read()

    def settings(self, pet=None):
        if getattr(self, '_settings_dialog', None) is not None:
            if getattr(pet, 'kind', None) is not None:
                index = self._settings_dialog.character_selector.findData(pet.kind)
                if index >= 0:
                    self._settings_dialog.character_selector.setCurrentIndex(index)
                self._settings_dialog.navigation.setCurrentRow(0)
            self._settings_dialog.showNormal()
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self.config, self.key, self, keys=self.provider_keys, profiles=self.provider_profiles,
            character_store=self.character_store, selected_character=getattr(pet, 'kind', None) or self.thread_id, catalog_store=self.catalog_store,
            capture_store=self.capture_store, farming_store=self.farming_store, dialogue_store=getattr(self.dialogue, 'store', None),
            settings_store=self.store)
        self._settings_dialog = dialog
        dialog.setWindowModality(Qt.NonModal)
        dialog.finished.connect(lambda result: self._settings_finished(dialog, result))
        dialog.show()

    def open_updates(self, *, check=False):
        self.settings()
        dialog = self._settings_dialog
        dialog.navigation.setCurrentRow(dialog.about_index)
        if check:
            dialog.about_page.updates.check()

    def _settings_finished(self, dialog, result):
        self._settings_dialog = None
        dialog.deleteLater()
        if result == QDialog.Accepted:
            obs_config = save_obs(dialog.obs_page.values(), self.store)
            self.config = {**dialog.values(), **{field: self.config[field] for field in PERSONA_FIELDS}}
            self.key = dialog.key.text().strip()
            self.provider_keys = dialog.provider_keys
            profile_fields = ('provider', 'api_format', 'base_url', 'model', 'max_tokens', 'timeout_seconds')
            self.provider_profiles = {k: {field: value[field] for field in profile_fields if field in value}
                                      for k, value in dialog.provider_drafts.items()}
            self.store.setValue('provider_profiles', json.dumps(self.provider_profiles))
            for key, value in self.config.items():
                self.store.setValue(key, value)
            from maeagi_biseo.core.character_profiles import allowed_for
            for pet in self.pets:
                pet.set_allowed_actions(allowed_for(pet.kind, self.character_store))
                if hasattr(pet, 'apply_obs_settings'):
                    pet.apply_obs_settings(obs_config)
            self.refresh_heading()
            for identifier in self.contact_items:
                self.refresh_contact(identifier, refresh_icon=True)
            self.status.setText(tr('chat.settings_saved'))
            if dialog.pending_runtime_action is not None:
                action, identifier = dialog.pending_runtime_action
                if action == 'chat':
                    self.open_for(identifier=identifier)
    def add_message(self, speaker, text, user=False, *, kind=None):
        identifier = self.thread_id
        entry = dict(speaker=speaker, text=text, kind=kind or ('user' if user else 'assistant'), time=datetime.now())
        self.transcripts.setdefault(identifier, []).append(entry)
        self.render_entry(entry)
        if entry['kind'] == 'assistant' and identifier and (self.isMinimized() or not self.isActiveWindow()):
            self.unread[identifier] = self.unread.get(identifier, 0) + 1
        self.prioritize_contact(identifier)
        self.refresh_contact(identifier)

    def render_entry(self, entry):
        timestamp = entry['time']
        same_day = self.previous_entry is not None and self.previous_entry['time'].date() == timestamp.date()
        if not same_day:
            day = QLabel(tr('chat.date', year=timestamp.year, month=timestamp.month, day=timestamp.day))
            day.setObjectName('chatDate')
            self.rows.addWidget(day, 0, Qt.AlignHCenter)
        kind = entry['kind']
        user = kind == 'user'
        message = QWidget()
        row = QHBoxLayout(message)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        body = QVBoxLayout()
        body.setSpacing(3)
        if kind == 'assistant':
            grouped = same_day and self.previous_entry['kind'] == kind and self.previous_entry['speaker'] == entry['speaker']
            avatar = QLabel()
            avatar.setFixedSize(34, 34)
            if not grouped:
                avatar.setPixmap(self.avatar(self.thread_id, entry['speaker'], 34))
                sender = QLabel(entry['speaker'])
                sender.setTextFormat(Qt.PlainText)
                sender.setObjectName('chatMessageMeta')
                body.addWidget(sender)
            row.addWidget(avatar, 0, Qt.AlignTop)
        if user or kind in ('record', 'notice'):
            row.addStretch(1)
        label = QLabel(entry['text'])
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setObjectName({'user': 'userMessage', 'assistant': 'assistantMessage',
                             'record': 'chatRecord', 'notice': 'chatNotice'}[kind])
        label.setProperty('chatBubble', True)
        if kind in ('record', 'notice'):
            sender = QLabel(entry['speaker'])
            sender.setTextFormat(Qt.PlainText)
            sender.setObjectName('chatMessageMeta')
            body.addWidget(sender)
        body.addWidget(label, 0, Qt.AlignRight if user else Qt.Alignment())
        clock = QLabel(timestamp.strftime('%H:%M'))
        clock.setObjectName('chatMessageMeta')
        body.addWidget(clock, 0, Qt.AlignRight if user else Qt.AlignLeft)
        row.addLayout(body)
        if not user:
            row.addStretch(1)
        self.rows.addWidget(message)
        self.size_message(label, self.scroll.viewport().width())
        self.empty_chat.hide()
        self.previous_entry = entry

    def size_message(self, label, viewport_width):
        label.ensurePolished()
        metrics = label.fontMetrics()
        natural = max((metrics.horizontalAdvance(line) for line in label.text().splitlines()), default=0) + 30
        width = max(48, min(round(viewport_width * .76), natural, 480))
        label.setFixedWidth(width)
        label.setFixedHeight(max(metrics.height() + 20, label.heightForWidth(width)))
        message = label.parentWidget()
        message.layout().invalidate()
        message.setMinimumHeight(message.layout().minimumSize().height())

    def clear_chat(self):
        if self.worker:
            return
        self.history.clear()
        identifier = self.thread_id
        self.transcripts.pop(identifier, None)
        self.unread.pop(identifier, None)
        self.clear_rows()
        self.refresh_contact(identifier)
        self.status.setText(tr('chat.cleared'))

    def clear_rows(self):
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.previous_entry = None
        self.empty_chat.show()

    def send(self):
        QApplication.inputMethod().commit()
        text = self.input.toPlainText().strip()
        if not text or self.worker:
            return
        if not self.config['model'] or not self.config['base_url']:
            self.settings()
            return
        if len(text) > 12000:
            self.status.setText(tr('chat.too_long'))
            return
        self.pending = text
        config = self.current_config()
        self.reply_name = config['name']
        self.add_message(tr('chat.user'), text, True)
        self.input.clear()
        self.set_busy(True)
        self.status.setText(tr('chat.thinking', name=config['name']))
        self.worker = ReplyWorker(config, self.key, self.history[-20:] + [dict(role='user', content=text)], self)
        from maeagi_biseo.core.farming_tools import FarmingTools, BalanceCapture, capture_options
        reader = BalanceCapture(capture_options(self.capture_store), before=self.worker.prepare_capture,
                                after=self.worker.capture_finished.emit)
        self.worker.tool_executor = FarmingTools(store=self.farming_store, reader=reader, character_id=self.thread_id or '', report=self.worker.tool_event.emit,
                                               confirm_start=self.worker.confirm_farming_start)
        self.worker.capture_requested.connect(self.prepare_farming_capture)
        self.worker.capture_finished.connect(self.finish_farming_capture)
        self.worker.tool_event.connect(self.farming_tool_event)
        self.worker.confirmation_requested.connect(self.confirm_farming_start)
        self.worker.result.connect(self.receive)
        self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def set_busy(self, busy):
        for button in (self.send_button, self.clear_button, self.settings_button, self.target_selector, self.contacts):
            button.setEnabled(not busy)
        identifier = self.thread_id
        self.profile_button.setEnabled(not busy and avatar_source(self.contact_paths.get(identifier)) is not None)
        self.summon_button.setEnabled(not busy and identifier in self.contact_items and self.target is None)

    def prepare_farming_capture(self, gate):
        if self.worker is None or self.worker.isInterruptionRequested():
            gate.set()
            return
        self.capture_notice.begin(CAPTURE_DELAY_MS, gate.set, self.status, tr('farming.capture_reading'))

    def finish_farming_capture(self):
        self.capture_notice.stop()
        self.status.setText(tr('farming.capture_review'))

    def farming_tool_event(self, event):
        if event['event'] == 'running':
            self.status.setText(tr('farming.tool_running', tool=event['tool']))
            return
        result = event['result']
        status = result.get('status')
        if status in ('started', 'completed'):
            session = result['session']
            if status == 'started':
                text = tr('farming.started_receipt', meso=format_meso(session['start_meso']), fragments=str(session['start_fragments']))
            else:
                text = tr('farming.completed_receipt', minutes=round(session['duration_seconds'] / 60, 1),
                          meso=format_meso(session['meso_change'], signed=True), fragments=f"{session['fragment_change']:+}")
        elif status == 'cancelled':
            text = tr('farming.cancelled_receipt')
        elif status == 'start_cancelled':
            text = tr('farming.start_cancelled')
        elif status == 'error':
            text = tr('farming.error_receipt', error=result.get('error', ''))
        else:
            return
        # A local receipt remains visible even if the following LLM request fails.
        self.add_message(tr('farming.system'), text, kind='record')

    def confirm_farming_start(self, request):
        if request['ready'].is_set():
            return
        snapshot = request['snapshot']
        text = tr('farming.confirm_start', intro=request.get('intro', tr('farming.confirm_intro')),
                  meso=format_meso(snapshot['meso']), fragments=str(snapshot['fragments']))
        self.add_message(getattr(self, 'reply_name', self.current_config()['name']), text)
        pet = self.target
        if pet is not None:
            self.dialogue.say_to_user(pet, text)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr('farming.confirm_title'))
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText(text)
        dialog.setIcon(QMessageBox.Question)
        start = dialog.addButton(tr('farming.confirm_yes'), QMessageBox.AcceptRole)
        retry = dialog.addButton(tr('farming.confirm_retry'), QMessageBox.ActionRole)
        cancel = dialog.addButton(tr('common.cancel'), QMessageBox.RejectRole)
        dialog.setDefaultButton(cancel)
        self.farming_confirmation_dialog = dialog
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.timeout.connect(dialog.reject)
        timer.start(299000)
        def decided(_):
            timer.stop()
            request['choice'] = 'start' if dialog.clickedButton() == start else 'retry' if dialog.clickedButton() == retry else 'cancel'
            request['ready'].set()
            self.farming_confirmation_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(decided)
        dialog.open()

    def receive(self, answer):
        self.history.extend([dict(role='user', content=self.pending), dict(role='assistant', content=answer)])
        self.add_message(getattr(self, 'reply_name', self.current_config()['name']), answer)
        pet = self.target
        if pet:
            self.dialogue.say_to_user(pet, answer)
        self.status.setText(tr('chat.received'))

    def failed(self, error):
        self.add_message(tr('chat.error_title'), error + tr('chat.retry_hint'), kind='notice')
        self.status.setText(tr('chat.send_failed'))
        if not self.input.toPlainText():
            self.input.setPlainText(self.pending)

    def finished(self):
        self.capture_notice.stop()
        self.worker.deleteLater()
        self.worker = None
        self.set_busy(False)

    def shutdown(self):
        self.capture_notice.stop()
        if self.worker:
            self.worker.cancel_pending_capture()
            dialog = getattr(self, 'farming_confirmation_dialog', None)
            if dialog is not None:
                dialog.reject()
            self.worker.wait()
