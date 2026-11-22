"""Named character editor with ordered animation frames and live preview."""
from pathlib import Path
from collections import OrderedDict
import re
import shutil
import uuid
from copy import deepcopy

from PySide6.QtCore import Qt, QTimer, QSize, Signal, QTemporaryDir, QRectF, QThread, QSignalBlocker
from PySide6.QtGui import QPixmap, QPainter, QIcon, QFont, QFontDatabase, QColor, QPen, QImage
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLineEdit, QSpinBox, QListWidget, QListWidgetItem, QLabel,
    QPushButton, QFileDialog, QMessageBox, QDialogButtonBox, QCheckBox, QWidget, QScrollArea, QStackedWidget)

from maeagi_biseo.core.sprites import STATES, available_characters, read_manifest, scale_display_canvas, artwork_rows
from maeagi_biseo.core.character_store import save_character
from maeagi_biseo.core.character_catalog import registered_characters
from maeagi_biseo.resources import tr
from maeagi_biseo.llm.key_store import read_key, store_key
from maeagi_biseo.llm.settings import env_value
from maeagi_biseo.ui.dialogue import Bubble, bubble_position
from maeagi_biseo.ui.choice_combo import ChoiceComboBox as QComboBox
from maeagi_biseo.ui.chat_theme import apply_chat_theme, appearance_for
from maeagi_biseo.ui.settings_widgets import Disclosure, settings_link
from maeagi_biseo.ui.character_removal import confirm_character_removal, removal_action

LABELS = ('대기', '걷기', '잠자기', '점프', '낙하', '잡혀 있기', '벽 타기', '천장 이동', '대화', '쓰다듬기')


class SaveWorker(QThread):
    def __init__(self, args, kwargs, parent=None):
        super().__init__(parent)
        self.args, self.kwargs = args, kwargs
        self.identifier = None
        self.error = None

    def run(self):
        try:
            self.identifier = save_character(*self.args, **self.kwargs)
        except Exception as exc:
            self.error = str(exc) or tr('editor.save_failed')


class MapleWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, name, key, destination, parent=None):
        super().__init__(parent)
        self.name, self.key, self.destination = name, key, destination

    def run(self):
        from maeagi_biseo.core.maple_import import MapleClient, MapleImportError
        try:
            result = MapleClient(self.key).download(self.name, self.destination, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.loaded.emit(result)
        except (MapleImportError, OSError) as exc:
            self.failed.emit(str(exc) if isinstance(exc, MapleImportError) else tr('maple.save_error'))
        except Exception:
            self.failed.emit(tr('maple.invalid_response'))
        finally:
            self.key = ''


class FootPreview(QLabel):
    footPicked = Signal(float)
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def __init__(self):
        super().__init__()
        self.logical_size = QSize(130, 155)
        self.artwork_rows = (0, 155)

    def image_rect(self):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRectF()
        rect = self.contentsRect()
        return QRectF(rect.x() + (rect.width() - pixmap.width()) / 2,
                      rect.y() + (rect.height() - pixmap.height()) / 2, pixmap.width(), pixmap.height())

    def pick(self, event, clamp=False):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        rect = self.contentsRect()
        left = rect.x() + (rect.width() - pixmap.width()) / 2
        top = rect.y() + (rect.height() - pixmap.height()) / 2
        point = event.position()
        if not clamp and not (left <= point.x() <= left + pixmap.width() and top <= point.y() <= top + pixmap.height()):
            return
        self.footPicked.emit(max(0., min(1., (point.y() - top) / pixmap.height())))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pick(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.pick(event, clamp=True)


class MapleSearchInput(QLineEdit):
    """Keep Return local to search instead of activating a dialog default."""

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()


class CharacterEditor(QDialog):
    characterDeleted = Signal(str)

    def __init__(self, parent=None, selected_identifier=None, catalog_store=None):
        super().__init__(parent)
        self.catalog_store = catalog_store
        font_path = Path('C:/Windows/Fonts/malgun.ttf')
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
        self.setFont(QFont('Malgun Gothic', 10))
        self.setWindowTitle(tr('editor.heading'))
        self.setObjectName('characterEditor')
        self.resize(1040, 820)
        self.setMinimumSize(960, 740)
        mode = appearance_for(parent)
        apply_chat_theme(self, mode or 'light')
        self.identifier = None
        self.import_dir = QTemporaryDir()
        self.animations = {}
        self.canvas_size = [130, 155]
        self.comparison_box = [10, 10, 110, 140]
        self.current_state = 'idle'
        self.frame_index = 0
        self.loading = False
        self.maple_worker = None
        self.save_worker = None
        self.saving_dialog = None
        self._processed_preview_cache = OrderedDict()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        heading = QLabel(tr('editor.heading'))
        heading.setObjectName('settingsHeading')
        layout.addWidget(heading)
        maple_panel = QWidget()
        maple_layout = QVBoxLayout(maple_panel)
        maple_layout.setContentsMargins(0, 0, 0, 4)
        maple_row = QHBoxLayout()
        self.maple_name = MapleSearchInput()
        self.maple_name.setPlaceholderText(tr('maple.name_placeholder'))
        self.maple_name.setMaxLength(20)
        self.maple_key = MapleSearchInput()
        self.maple_key.setEchoMode(QLineEdit.Password)
        self.maple_key.setPlaceholderText(tr('maple.key_placeholder'))
        self.maple_key.setToolTip(tr('maple.key_help'))
        self._maple_loaded_key = env_value('NEXON_API_KEY') or read_key('nexon')
        self.maple_key.setText(self._maple_loaded_key)
        self.maple_button = QPushButton(tr('maple.import'))
        self.maple_button.clicked.connect(self.import_maple)
        self.maple_name.returnPressed.connect(self.import_maple)
        self.maple_key.returnPressed.connect(self.import_maple)
        maple_row.addWidget(self.maple_name)
        maple_row.addWidget(self.maple_key)
        maple_row.addWidget(self.maple_button)
        maple_layout.addLayout(maple_row)
        maple_layout.addWidget(settings_link(tr('maple.key_link'), 'https://openapi.nexon.com/ko/guide/prepare-in-advance/'),
                               0, Qt.AlignLeft)
        self.maple_status = QLabel(tr('maple.help'))
        self.maple_status.setWordWrap(True)
        maple_layout.addWidget(self.maple_status)
        self.maple_section = Disclosure(tr('editor.maple_section'), maple_panel)
        layout.addWidget(self.maple_section)
        columns = QHBoxLayout()
        columns.setSpacing(20)
        layout.addLayout(columns, 1)
        edit_panel = QWidget()
        edit_panel.setObjectName('editorPanel')
        edit_panel.setFixedWidth(390)
        edit_layout = QVBoxLayout(edit_panel)
        edit_layout.setContentsMargins(16, 16, 16, 16)
        edit_layout.setSpacing(12)
        edit_scroll = QScrollArea()
        edit_scroll.setWidgetResizable(True)
        edit_scroll.setFrameShape(QScrollArea.NoFrame)
        edit_scroll.setFixedWidth(410)
        edit_scroll.setWidget(edit_panel)
        columns.addWidget(edit_scroll)
        preview_panel = QWidget()
        preview_panel.setObjectName('editorPanel')
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(12)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QScrollArea.NoFrame)
        preview_scroll.setWidget(preview_panel)
        columns.addWidget(preview_scroll, 1)
        preview_heading = QLabel(tr('editor.preview'))
        preview_heading.setObjectName('captureHeading')
        preview_layout.addWidget(preview_heading)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.characters = QComboBox()
        self.characters.addItem(tr('editor.new_character'), None)
        for identifier, info in registered_characters(self.catalog_store).items():
            self.characters.addItem(info.name, identifier)
        self.delete_button = QPushButton(tr('editor.delete_character'))
        self.delete_button.setObjectName('deleteCharacter')
        self.delete_button.setEnabled(False)
        self.delete_button.hide()
        self.delete_button.clicked.connect(self.delete_selected)
        self.name = QLineEdit()
        self.name.setMaxLength(20)
        self.scale_box = QSpinBox()
        self.scale_box.setRange(25, 300)
        self.scale_box.setValue(100)
        self.scale_box.setSuffix(' %')
        self.scale_box.setToolTip(tr('editor.scale_help'))
        self.upscale_box = QComboBox()
        for factor in (1, 2, 4):
            self.upscale_box.addItem(tr(f'editor.upscale_{factor}'), factor)
        self.upscale_box.setToolTip(tr('editor.upscale_help'))
        self.smoothing_box = QComboBox()
        for strength in (0, 1, 2, 3):
            self.smoothing_box.addItem(tr(f'editor.smoothing_{strength}'), strength)
        self.smoothing_box.setToolTip(tr('editor.smoothing_help'))
        self.width_box = QSpinBox()
        self.height_box = QSpinBox()
        for box, value in ((self.width_box, 130), (self.height_box, 155)):
            box.setRange(16, 1024)
            box.setValue(value)
            box.setSuffix(' px')
        size = QHBoxLayout()
        size.addWidget(self.width_box)
        size.addWidget(self.height_box)
        self.behavior = QComboBox()
        for state, label in zip(STATES, LABELS):
            self.behavior.addItem(label, state)
        self.speed = QSpinBox()
        self.speed.setRange(16, 60000)
        self.speed.setSuffix(' ms / 장')
        self.speed.setValue(120)
        self.foot = QSpinBox()
        self.foot.setRange(1, self.height_box.value())
        self.foot.setValue(self.height_box.value())
        self.foot.setSuffix(' px (위에서부터)')
        form.addRow('편집할 메애기', self.characters)
        form.addRow('이름', self.name)
        form.addRow(tr('editor.display_scale'), self.scale_box)
        form.addRow('행동', self.behavior)
        for control in (self.characters, self.delete_button, self.name, self.scale_box,
                        self.width_box, self.height_box, self.behavior, self.speed, self.foot):
            control.setMinimumHeight(36)
        edit_layout.addLayout(form)
        note = QLabel(tr('editor.geometry_help'))
        note.setWordWrap(True)
        self.frames = QListWidget()
        self.frames.setIconSize(QSize(44, 44))
        self.frames.setObjectName('editorFrames')
        self.frames.setTextElideMode(Qt.ElideMiddle)
        self.frames.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.frame_heading = QLabel(tr('editor.frames'))
        self.frame_heading.setObjectName('captureHeading')
        frame_toolbar = QHBoxLayout()
        frame_toolbar.addWidget(self.frame_heading, 1)
        add_button = QPushButton(tr('editor.add_frames'))
        add_button.setObjectName('addCharacterFrames')
        add_button.clicked.connect(self.add_images)
        frame_toolbar.addWidget(add_button)
        edit_layout.addLayout(frame_toolbar)
        self.empty_frames = QLabel()
        self.empty_frames.setObjectName('editorEmptyFrames')
        self.empty_frames.setAlignment(Qt.AlignCenter)
        self.empty_frames.setWordWrap(True)
        self.frame_stack = QStackedWidget()
        self.frame_stack.setMinimumHeight(146)
        self.frame_stack.addWidget(self.frames)
        self.frame_stack.addWidget(self.empty_frames)
        edit_layout.addWidget(self.frame_stack, 1)
        buttons = QHBoxLayout()
        self.move_frame_up = QPushButton(tr('editor.move_frame_up'))
        self.move_frame_up.clicked.connect(lambda: self.reorder(-1))
        self.move_frame_down = QPushButton(tr('editor.move_frame_down'))
        self.move_frame_down.clicked.connect(lambda: self.reorder(1))
        self.remove_frame = QPushButton(tr('editor.remove_frame'))
        self.remove_frame.clicked.connect(self.remove_image)
        for button in (self.move_frame_up, self.move_frame_down, self.remove_frame):
            buttons.addWidget(button)
        self.copy_button = QPushButton(tr('editor.copy_frame'))
        self.copy_button.setObjectName('copyFrame')
        self.copy_button.clicked.connect(self.copy_frame)
        buttons.addWidget(self.copy_button)
        edit_layout.addLayout(buttons)
        timing = QFormLayout()
        timing.addRow(tr('editor.frame_speed'), self.speed)
        timing.addRow(tr('editor.foot_position'), self.foot)
        edit_layout.addLayout(timing)
        image_options = QWidget()
        image_form = QFormLayout(image_options)
        image_form.setContentsMargins(0, 4, 0, 0)
        image_form.addRow(tr('editor.image_size'), size)
        image_form.addRow(tr('editor.upscale'), self.upscale_box)
        image_form.addRow(tr('editor.smoothing'), self.smoothing_box)
        edit_layout.addWidget(Disclosure(tr('editor.image_options'), image_options))
        self.preview = FootPreview()
        self.preview.setCursor(Qt.CrossCursor)
        self.preview.setToolTip('발바닥을 클릭하거나 누른 채 움직여 기준선을 맞추세요. 재생은 자동으로 정지합니다.')
        self.preview.footPicked.connect(self.pick_foot)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setObjectName('editorPreview')
        self.preview.setMinimumHeight(400)
        self.bubble_anchor = QWidget(self.preview)
        self.bubble_anchor.hide()
        self.bubble_preview = Bubble(self.bubble_anchor)
        self.bubble_preview.setParent(self.preview, Qt.Widget)
        self.bubble_preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bubble_preview.setText(tr('editor.bubble_sample'))
        self.bubble_preview.adjustSize()
        controls = QHBoxLayout()
        self.play = QPushButton('정지')
        self.play.setCheckable(True)
        self.play.toggled.connect(self.toggle_play)
        self.left = QCheckBox('오른쪽 보기 (반전)')
        self.left.toggled.connect(self.refresh_preview)
        controls.addWidget(self.play)
        controls.addWidget(self.left)
        self.preview_original = QCheckBox(tr('editor.preview_original'))
        self.preview_original.hide()
        self.preview_original.setToolTip(tr('editor.preview_processing_help'))
        self.preview_original.toggled.connect(self.refresh_preview)
        controls.addWidget(self.preview_original)
        self.status = QLabel()
        preview_layout.addLayout(controls)
        preview_layout.addWidget(self.preview, 1)
        self.status.setObjectName('settingsSubtitle')
        preview_layout.addWidget(self.status)
        bubble_controls = QWidget()
        bubble_form = QFormLayout(bubble_controls)
        bubble_form.setContentsMargins(0, 4, 0, 0)
        self.bubble_x = QSpinBox()
        self.bubble_y = QSpinBox()
        for control in (self.bubble_x, self.bubble_y):
            control.setRange(-300, 300)
            control.setSuffix(' px')
            control.valueChanged.connect(self.refresh_preview)
        bubble_form.addRow(tr('editor.bubble_x'), self.bubble_x)
        bubble_form.addRow(tr('editor.bubble_y'), self.bubble_y)
        self.bubble_edge = QCheckBox(tr('editor.bubble_edge'))
        self.bubble_edge.toggled.connect(self.refresh_preview)
        bubble_form.addRow(self.bubble_edge)
        self.bubble_notice = QLabel(tr('editor.bubble_help'))
        self.bubble_notice.setWordWrap(True)
        bubble_form.addRow(self.bubble_notice)
        self.bubble_section = Disclosure(tr('editor.bubble_options'), bubble_controls)
        self.bubble_section.toggle.toggled.connect(self.update_bubble_preview)
        preview_layout.addWidget(self.bubble_section)
        self.preview.resized.connect(self.update_bubble_preview)
        preview_layout.addWidget(Disclosure(tr('editor.guide'), note))
        footer = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.footer = footer
        footer.button(QDialogButtonBox.Save).setText('저장')
        footer.button(QDialogButtonBox.Save).setObjectName('saveCharacter')
        footer.button(QDialogButtonBox.Cancel).setText('닫기')
        footer.accepted.connect(self.save)
        footer.rejected.connect(self.reject)
        footer_row = QHBoxLayout()
        footer_row.addWidget(self.delete_button)
        footer_row.addStretch()
        footer_row.addWidget(footer)
        layout.addLayout(footer_row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(120)
        self.behavior.currentIndexChanged.connect(self.change_behavior)
        self.characters.currentIndexChanged.connect(self.load_selected)
        self.speed.valueChanged.connect(self.change_speed)
        self.foot.valueChanged.connect(self.change_foot)
        self.width_box.valueChanged.connect(self.change_image_size)
        self.height_box.valueChanged.connect(self.change_image_size)
        self.scale_box.valueChanged.connect(self.refresh_preview)
        self.upscale_box.currentIndexChanged.connect(self.refresh_processing_preview)
        self.smoothing_box.currentIndexChanged.connect(self.refresh_processing_preview)
        self.frames.currentRowChanged.connect(self.select_frame)
        self.refresh_list()
        if selected_identifier is not None:
            index = self.characters.findData(selected_identifier)
            if index >= 0:
                self.characters.setCurrentIndex(index)
        if self.frames.count():
            self.frames.setFocus()
        else:
            self.name.setFocus()

    def done(self, result):
        if self.save_worker is not None:
            return
        if self.maple_worker is not None and self.maple_worker.isRunning():
            self.maple_worker.requestInterruption()
            self.maple_status.setText(tr('maple.cancelling'))
            return
        self.timer.stop()
        super().done(result)

    def closeEvent(self, event):
        if self.save_worker is not None:
            event.ignore()
            return
        super().closeEvent(event)

    def import_maple(self):
        if self.maple_worker is not None:
            return
        entered_key = self.maple_key.text().strip()
        key = entered_key or env_value('NEXON_API_KEY') or read_key('nexon')
        name = self.maple_name.text().strip()
        if not name or not key:
            self.maple_status.setText(tr('maple.name_required' if not name else 'maple.key_required'))
            return
        if any(entry.get('frames') for entry in self.animations.values()):
            if QMessageBox.question(self, tr('maple.import'), tr('maple.replace_confirm')) != QMessageBox.Yes:
                return
        if entered_key and entered_key != self._maple_loaded_key:
            try:
                store_key('nexon', entered_key)
            except (OSError, KeyError):
                self.maple_status.setText(tr('maple.key_save_error'))
                return
            self._maple_loaded_key = entered_key
        self.maple_button.setEnabled(False)
        self.characters.setEnabled(False)
        self.findChild(QPushButton, 'saveCharacter').setEnabled(False)
        self.maple_status.setText(tr('maple.loading'))
        self.maple_worker = MapleWorker(name, key, self.import_dir.path(), self)
        self.maple_worker.loaded.connect(self.apply_maple)
        self.maple_worker.failed.connect(self.maple_status.setText)
        self.maple_worker.finished.connect(self.maple_finished)
        self.maple_worker.start()

    def maple_finished(self):
        worker = self.maple_worker
        self.maple_worker = None
        worker.deleteLater()
        self.maple_button.setEnabled(True)
        self.characters.setEnabled(True)
        self.findChild(QPushButton, 'saveCharacter').setEnabled(True)
        if worker.isInterruptionRequested():
            self.maple_status.setText(tr('maple.cancelled'))

    def apply_maple(self, result):
        self.characters.setCurrentIndex(0)
        self.identifier = None
        self.loading = True
        self.name.setText(result['name'])
        self.animations = result['animations']
        self.canvas_size = result['canvas']
        width, height = self.canvas_size
        self.comparison_box = [0, 0, width, height]
        self.width_box.setValue(width)
        self.height_box.setValue(height)
        self.scale_box.setValue(100)
        self.bubble_x.setValue(0)
        self.bubble_y.setValue(0)
        self.behavior.setCurrentIndex(0)
        self.loading = False
        self.change_behavior()
        self.maple_status.setText(tr('maple.loaded'))

    def entry(self):
        return self.animations.setdefault(self.current_state, {'frames': [], 'frame_ms': 120})

    def logical_size(self):
        sizes = [entry.get('sizes', {}).get(path, self.canvas_size)
                 for entry in self.animations.values() for path in entry['frames']]
        return QSize(max([self.canvas_size[0]] + [size[0] for size in sizes]), max([self.canvas_size[1]] + [size[1] for size in sizes]))

    def change_image_size(self, *_):
        if self.loading:
            return
        paths = self.entry()['frames']
        row = self.frames.currentRow()
        if paths:
            row = row if row >= 0 else self.frame_index % len(paths)
            self.entry().setdefault('sizes', {})[paths[row]] = [self.width_box.value(), self.height_box.value()]
            self.play.setChecked(True)
            self.frame_index = row
        self.refresh_preview()

    def load_selected(self):
        self.upscale_box.setCurrentIndex(0)
        self.smoothing_box.setCurrentIndex(0)
        self.identifier = self.characters.currentData()
        self.delete_button.setText(tr(self.removal_text_key()))
        self.delete_button.setEnabled(self.identifier is not None)
        self.delete_button.setVisible(self.identifier is not None)
        self.animations = {}
        self.canvas_size = [130, 155]
        self.loading = True
        self.scale_box.setValue(100)
        self.name.clear()
        self.bubble_x.setValue(0)
        self.bubble_y.setValue(0)
        self.width_box.setValue(130)
        self.height_box.setValue(155)
        if self.identifier:
            folder = available_characters()[self.identifier].path
            try:
                manifest = read_manifest(folder)
                offset = manifest.get('bubble_offset', [0, 0])
                self.bubble_x.setValue(offset[0])
                self.bubble_y.setValue(offset[1])
                self.scale_box.setValue(manifest.get('display_scale', 100))
                self.name.setText(manifest.get('name', ''))
                width, height = manifest.get('canvas', [130, 155])
                self.canvas_size = [width, height]
                self.comparison_box = manifest.get('comparison_box', self.comparison_box)
                self.width_box.setValue(width)
                self.height_box.setValue(height)
                self.animations = {state: {'frames': [str(folder / filename) for filename in entry['frames']],
                    'frame_ms': entry.get('frame_ms', 120), 'foot_offset': entry.get('foot_offset', manifest.get('foot_offset', height))}
                    for state, entry in manifest.get('animations', {}).items()}
                for state, entry in manifest.get('animations', {}).items():
                    if 'frame_durations' in entry:
                        self.animations[state]['delays'] = dict(zip(self.animations[state]['frames'], entry['frame_durations']))
                    if 'frame_sizes' in entry:
                        self.animations[state]['sizes'] = dict(zip(self.animations[state]['frames'], entry['frame_sizes']))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                QMessageBox.warning(self, '불러오기 실패', str(exc))
        self.loading = False
        self.change_behavior()

    def removal_text_key(self):
        return removal_action(registered_characters(self.catalog_store).get(self.identifier))

    def delete_selected(self):
        if self.identifier is None or self.maple_worker is not None:
            return
        identifier = self.identifier
        if not confirm_character_removal(self, identifier, self.catalog_store):
            return
        self.characterDeleted.emit(identifier)
        self.characters.removeItem(self.characters.currentIndex())
        self.characters.setCurrentIndex(0)
        self.load_selected()

    def copy_frame(self):
        row = self.frames.currentRow()
        entry = self.entry()
        if not 0 <= row < len(entry['frames']):
            return
        source = entry['frames'][row]
        target = str(Path(self.import_dir.path()) / (uuid.uuid4().hex + Path(source).suffix))
        try:
            shutil.copyfile(source, target)
        except OSError:
            QMessageBox.warning(self, tr('editor.copy_frame'), tr('editor.copy_failed'))
            return
        entry['frames'].insert(row + 1, target)
        for field in ('sizes', 'delays'):
            if source in entry.get(field, {}):
                value = entry[field][source]
                entry[field][target] = list(value) if isinstance(value, list) else value
        self.refresh_list(row + 1)

    def change_behavior(self):
        self.current_state = self.behavior.currentData()
        self.loading = True
        self.speed.setValue(self.entry()['frame_ms'])
        self.foot.setMaximum(self.logical_size().height())
        self.foot.setValue(self.entry().get('foot_offset', self.logical_size().height()))
        self.loading = False
        self.frame_index = 0
        self.refresh_list()

    def change_speed(self, value):
        if not self.loading:
            self.entry()['frame_ms'] = value
            self.entry().pop('delays', None)
        self.refresh_preview()

    def change_foot(self, value):
        if not self.loading:
            self.entry()['foot_offset'] = value
        self.refresh_preview()

    def refresh_list(self, selected_row=0):
        paths = self.entry()['frames']
        action = self.behavior.currentText()
        with QSignalBlocker(self.frames):
            self.frames.clear()
            for index, path in enumerate(paths, 1):
                name = Path(path)
                generated = re.fullmatch(r'[0-9a-f]{32}(?:_[a-z0-9]+)*', name.stem)
                label = tr('editor.generated_frame', number=index) if generated else f'{index}. {name.name}'
                item = QListWidgetItem(QIcon(path), label)
                item.setToolTip(path)
                self.frames.addItem(item)
            row = min(selected_row, len(paths) - 1)
            self.frames.setCurrentRow(row)
        self.frame_heading.setText(tr('editor.frame_heading', action=action, count=len(paths)))
        self.empty_frames.setText(tr('editor.empty_frames', action=action))
        self.frame_stack.setCurrentWidget(self.frames if paths else self.empty_frames)
        self.select_frame(row)

    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '행동 이미지 / GIF 추가', '', '이미지 (*.png *.webp *.jpg *.jpeg *.gif)', options=QFileDialog.DontUseNativeDialog)
        first_added = len(self.entry()['frames'])
        invalid = []
        for path in paths:
            if Path(path).suffix.lower() == '.gif':
                from maeagi_biseo.core.gif_import import import_gif
                try:
                    frames, delays = import_gif(path, self.import_dir.path())
                    self.entry()['frames'].extend(frames)
                    for frame in frames:
                        image = QPixmap(frame)
                        self.entry().setdefault('sizes', {})[frame] = [max(16, min(1024, image.width())), max(16, min(1024, image.height()))]
                    self.entry().setdefault('delays', {}).update(delays)
                except (OSError, ValueError):
                    invalid.append(Path(path).name)
                continue
            if QPixmap(path).isNull():
                invalid.append(Path(path).name)
            else:
                self.entry()['frames'].append(path)
                image = QPixmap(path)
                self.entry().setdefault('sizes', {})[path] = [max(16, min(1024, image.width())), max(16, min(1024, image.height()))]
        if invalid:
            QMessageBox.warning(self, '이미지 읽기 실패', '\n'.join(invalid))
        if len(self.entry()['frames']) > first_added:
            self.refresh_list(first_added)

    def remove_image(self):
        row = self.frames.currentRow()
        if row >= 0:
            self.entry()['frames'].pop(row)
            self.refresh_list(row)

    def reorder(self, delta):
        row = self.frames.currentRow()
        frames = self.entry()['frames']
        target = row + delta
        if row >= 0 and 0 <= target < len(frames):
            frames[row], frames[target] = frames[target], frames[row]
            self.refresh_list(target)

    def pick_foot(self, fraction):
        if not self.entry()['frames']:
            return
        self.play.setChecked(True)
        if self.current_state == 'ceiling':
            fraction = 1 - fraction
        self.foot.setValue(max(1, round(fraction * self.logical_size().height())))
        self.refresh_preview()

    def toggle_play(self, stopped):
        self.play.setText('재생' if stopped else '정지')

    def select_frame(self, row):
        paths = self.entry()['frames']
        selected = 0 <= row < len(paths)
        self.move_frame_up.setEnabled(selected and row > 0)
        self.move_frame_down.setEnabled(selected and row < len(paths) - 1)
        self.copy_button.setEnabled(selected)
        self.remove_frame.setEnabled(selected)
        if selected:
            self.play.setChecked(True)
            self.frame_index = row
            size = self.entry().get('sizes', {}).get(paths[row], self.canvas_size)
            self.loading = True
            self.width_box.setValue(size[0])
            self.height_box.setValue(size[1])
            self.loading = False
        self.refresh_preview()

    def advance(self):
        if not self.play.isChecked():
            self.frame_index += 1
            self.refresh_preview()

    def processed_preview(self, path, size):
        factor = self.upscale_box.currentData()
        smoothing = self.smoothing_box.currentData()
        target = QSize(*size)
        if self.preview_original.isChecked() or (factor == 1 and smoothing == 0):
            return QPixmap(path).scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        source = Path(path)
        stamp = source.stat()
        key = (str(source), stamp.st_mtime_ns, stamp.st_size, factor, smoothing, tuple(size))
        cached = self._processed_preview_cache.get(key)
        if cached is not None:
            self._processed_preview_cache.move_to_end(key)
            return cached
        from maeagi_biseo.core.upscale import processed_frame
        with processed_frame(path, factor, smoothing) as image:
            rgba = image.tobytes()
            qt_image = QImage(rgba, image.width, image.height, image.width * 4, QImage.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(qt_image).scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # Cache display-sized frames only, never the large export buffers.
        self._processed_preview_cache[key] = pixmap
        while len(self._processed_preview_cache) > 16:
            self._processed_preview_cache.popitem(last=False)
        return pixmap

    def refresh_preview(self, *_):
        if self.loading:
            return
        entry = self.entry()
        fallback = not entry['frames']
        if fallback:
            entry = self.animations.get('idle', {'frames': [], 'frame_ms': 120})
        self.timer.setInterval(entry['frame_ms'])
        paths = entry['frames']
        self.play.setEnabled(len(paths) > 1)
        self.left.setEnabled(bool(paths))
        self.status.setVisible(bool(paths))
        if not paths:
            self.play.setChecked(True)
            self.bubble_preview.hide()
            self.preview.clear()
            self.preview.setText(tr('editor.empty_preview'))
            self.status.clear()
            return
        index = self.frame_index % len(paths)
        delay = entry.get('delays', {}).get(paths[index], entry['frame_ms'])
        self.timer.setInterval(delay)
        logical = self.logical_size()
        canvas = QPixmap(logical)
        self.preview.logical_size = logical
        self.foot.setMaximum(logical.height())
        canvas.fill(Qt.transparent)
        size = entry.get('sizes', {}).get(paths[index], self.canvas_size)
        try:
            image = self.processed_preview(paths[index], size)
        except (OSError, ValueError) as exc:
            self.preview.clear()
            self.bubble_preview.hide()
            self.status.setText(tr('editor.preview_processing_failed', error=str(exc)))
            return
        painter = QPainter(canvas)
        if self.current_state == 'ceiling':
            painter.translate(canvas.width(), canvas.height())
            painter.rotate(180)
        if self.left.isChecked():
            painter.translate(canvas.width(), 0)
            painter.scale(-1, 1)
        image_y = canvas.height() - image.height()
        painter.drawPixmap((canvas.width() - image.width()) // 2, image_y, image)
        top, bottom = artwork_rows(image)
        top, bottom = top + image_y, bottom + image_y
        if self.current_state == 'ceiling':
            top, bottom = canvas.height() - bottom, canvas.height() - top
        self.preview.artwork_rows = top, bottom
        painter.setPen(QPen(QColor('#d32f2f'), 1, Qt.DashLine))
        foot = min(canvas.height(), entry.get('foot_offset', canvas.height()))
        painter.drawLine(0, min(canvas.height() - 1, foot), canvas.width(), min(canvas.height() - 1, foot))
        painter.end()
        # Fixed zoom preserves apparent size when the selected image changes.
        zoom = min(self.scale_box.value() / 100, 480 / canvas.width(), 200 / canvas.height())
        self.preview.setPixmap(scale_display_canvas(canvas, QSize(round(canvas.width() * zoom), round(canvas.height() * zoom))))
        self.status.setText(f'{"대기 대체 · " if fallback else ""}{index + 1}/{len(paths)} · {size[0]}×{size[1]} · {delay}ms · {self.scale_box.value()}%')
        self.update_bubble_preview()

    def update_bubble_preview(self):
        if not self.bubble_section.toggle.isChecked():
            self.bubble_preview.hide()
            return
        rect = self.preview.image_rect().toRect()
        if rect.isEmpty():
            self.bubble_preview.hide()
            return
        top, bottom = self.preview.artwork_rows
        scale = rect.height() / self.preview.logical_size.height()
        rect.setTop(rect.y() + round(top * scale))
        rect.setHeight(max(1, round(bottom * scale) - round(top * scale)))
        self.bubble_anchor.setGeometry(rect)
        bounds = self.preview.contentsRect()
        if self.bubble_edge.isChecked():
            bounds.setTop(rect.top())
        offset = self.bubble_x.value(), self.bubble_y.value()
        x, y, below = bubble_position(rect, self.bubble_preview.size(), bounds, offset)
        self.bubble_preview.tail_on_top = below
        self.bubble_preview.move(x, y)
        self.bubble_preview.show()
        self.bubble_preview.update()
        self.bubble_notice.setText(tr('editor.bubble_below' if below else 'editor.bubble_help'))

    def refresh_processing_preview(self):
        processing = self.upscale_box.currentData() != 1 or self.smoothing_box.currentData() != 0
        self.preview_original.setVisible(processing)
        if not processing and self.preview_original.isChecked():
            self.preview_original.setChecked(False)
        else:
            self.refresh_preview()

    def save(self):
        if self.maple_worker is not None or self.save_worker is not None:
            return
        from maeagi_biseo.ui.saving_dialog import SavingDialog
        args = (self.name.text(), deepcopy(self.animations),
                (self.logical_size().width(), self.logical_size().height()), self.identifier, list(self.comparison_box))
        kwargs = dict(display_scale=self.scale_box.value(),
                      bubble_offset=[self.bubble_x.value(), self.bubble_y.value()],
                      upscale_factor=self.upscale_box.currentData(), smoothing=self.smoothing_box.currentData())
        self.save_worker = SaveWorker(args, kwargs, self)
        self.save_worker.finished.connect(self.finish_save)
        self.timer.stop()
        self.footer.setEnabled(False)
        self.saving_dialog = SavingDialog(self)
        self.saving_dialog.show()
        self.save_worker.start()

    def finish_save(self):
        worker = self.save_worker
        self.save_worker = None
        self.saving_dialog.accept()
        self.saving_dialog.deleteLater()
        self.saving_dialog = None
        self.footer.setEnabled(True)
        worker.deleteLater()
        if worker.error is not None:
            self.timer.start()
            QMessageBox.warning(self, tr('editor.save_failed'), worker.error)
            return
        self.identifier = worker.identifier
        self.accept()
