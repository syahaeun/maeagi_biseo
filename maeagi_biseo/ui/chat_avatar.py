"""Local chat portraits made from the character's idle artwork or a user-chosen picture."""
import hashlib
import os
import re
from functools import lru_cache
from math import isfinite, log
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from maeagi_biseo.resources import tr
from maeagi_biseo.core.sprites import IMAGE_TYPES, artwork_rows, read_manifest

DEFAULT_CROP = (100, 0, 0)
AVATAR_BACKGROUND = '#504466'
CORNER_RATIO = .27
MIN_SCALE = .12
MAX_SCALE = 8.0
CHAT_SIZES = (44, 34)
CUSTOM_MAX_SIDE = 512
IMPORT_MAX_PIXELS = 80_000_000


def avatar_image_root():
    return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'DesktopShimeji' / 'avatars'


def custom_avatar_path(root, identifier):
    """The managed copy for one character; identifiers outside a safe charset are hashed."""
    name = str(identifier)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name):
        name = 'id_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:32]
    return Path(root) / f'{name}.png'


def read_avatar_image(path):
    """Read any supported picture, shrunk to CUSTOM_MAX_SIDE. Raises ValueError if unreadable."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        if size.width() * size.height() > IMPORT_MAX_PIXELS:
            raise ValueError(tr('chat.avatar_import_failed'))
        if max(size.width(), size.height()) > CUSTOM_MAX_SIDE:
            reader.setScaledSize(size.scaled(QSize(CUSTOM_MAX_SIDE, CUSTOM_MAX_SIDE), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError(tr('chat.avatar_import_failed'))
    if max(image.width(), image.height()) > CUSTOM_MAX_SIDE:
        image = image.scaled(CUSTOM_MAX_SIDE, CUSTOM_MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def save_custom_avatar(image, target):
    """Write the managed PNG atomically. Raises OSError on failure."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.tmp')
    if not image.save(str(temp), 'PNG'):
        temp.unlink(missing_ok=True)
        raise OSError(tr('chat.avatar_save_failed'))
    os.replace(temp, target)
    _read_custom_avatar.cache_clear()


def remove_custom_avatar(target):
    Path(target).unlink(missing_ok=True)
    _read_custom_avatar.cache_clear()


def custom_avatar(path):
    try:
        return _read_custom_avatar(Path(path), Path(path).stat().st_mtime_ns)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=64)
def _read_custom_avatar(path, _stamp):
    image = QImage(str(path))
    return None if image.isNull() else QPixmap.fromImage(image)


def has_transparency(image):
    picture = image.toImage()
    if not picture.hasAlphaChannel():
        return False
    corners = ((0, 0), (picture.width() - 1, 0), (0, picture.height() - 1), (picture.width() - 1, picture.height() - 1))
    return any(picture.pixelColor(x, y).alpha() < 16 for x, y in corners)


def initial_crop(image):
    """Cut-out artwork starts on the face; an ordinary photo starts on its centred square."""
    return face_crop(image) if has_transparency(image) else dict(x=.5, y=.5, scale=1.0)


def normalize_crop(value):
    if isinstance(value, dict):
        try:
            x, y, scale = (float(value[key]) for key in ('x', 'y', 'scale'))
        except (TypeError, ValueError, KeyError, OverflowError):
            return DEFAULT_CROP
        if all(isfinite(entry) for entry in (x, y, scale)):
            return dict(x=max(0, min(1, x)), y=max(0, min(1, y)), scale=max(.04, min(MAX_SCALE, scale)))
        return DEFAULT_CROP
    try:
        zoom, x, y = map(int, value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_CROP
    return max(100, min(250, zoom)), max(-100, min(100, x)), max(-100, min(100, y))


def full_scale(width, height):
    """Scale at which the square frame shows the whole artwork."""
    return max(width, height) / max(1, min(width, height))


def crop_rect(area, crop):
    """Square crop in area coordinates. A side wider than the artwork keeps it centred on that axis."""
    side = min(area.width(), area.height()) * crop['scale']
    side = min(side, max(area.width(), area.height()))

    def place(start, length, centre):
        if side >= length:
            return start + (length - side) / 2
        return max(start, min(start + length - side, start + centre * length - side / 2))

    return QRectF(place(area.left(), area.width(), crop['x']), place(area.top(), area.height(), crop['y']), side, side)


def face_crop(image):
    """Guess a head-and-shoulders crop: the opaque bounds of the top part of the trimmed artwork."""
    fallback = dict(x=.5, y=.3, scale=.6)
    if image is None or image.isNull():
        return fallback
    picture = image.toImage().convertToFormat(QImage.Format_ARGB32)
    width, height = picture.width(), picture.height()
    rows = max(1, int(height * .42))
    left, right, top, bottom = width, -1, rows, -1
    for y in range(rows):
        for x in range(width):
            if (picture.pixel(x, y) >> 24) & 0xFF > 24:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < 0:
        return fallback
    side = max(right - left + 1, bottom - top + 1) * 1.12
    return normalize_crop(dict(x=(left + right + 1) / 2 / width, y=(top + bottom + 1) / 2 / height,
                               scale=max(MIN_SCALE, side / min(width, height))))


def avatar_source(path):
    if path is None:
        return None
    manifest = path / 'character.json'
    try:
        stamp = (manifest if manifest.is_file() else path).stat().st_mtime_ns
        return _read_avatar_source(path, stamp)
    except (OSError, TypeError, ValueError, AttributeError, KeyError):
        return None


@lru_cache(maxsize=128)
def _read_avatar_source(path, _stamp):
    if path.is_dir():
        data = read_manifest(path)
        frames = data.get('animations', {}).get('idle', {}).get('frames', [])
        manifest = path / 'character.json'
        folder = manifest.resolve().parent if manifest.is_file() else path.resolve()
        if frames:
            image_path = (folder / frames[0]).resolve()
        else:
            idle = folder / 'idle.png'
            image_path = idle if idle.is_file() else next(iter(sorted(folder.glob('idle_*.png'))), idle)
        if not image_path.is_relative_to(folder):
            return None
    else:
        image_path = path
    if image_path.suffix.casefold() not in IMAGE_TYPES:
        return None
    reader = QImageReader(str(image_path))
    size = reader.size()
    if max(size.width(), size.height()) > 360:
        reader.setScaledSize(size.scaled(QSize(360, 360), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return None
    top, bottom = artwork_rows(image)
    return QPixmap.fromImage(image.copy(0, top, image.width(), bottom - top))


def draw_cropped(painter, image, frame, crop):
    """Draw image so that its crop square fills frame; returns the scale factor used."""
    source = crop_rect(QRectF(image.rect()), crop)
    factor = frame.width() / source.width()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, factor < 1)
    target = QRectF(frame.left() - source.left() * factor, frame.top() - source.top() * factor,
                    image.width() * factor, image.height() * factor)
    painter.drawPixmap(target, image, QRectF(image.rect()))
    return factor


def avatar_pixmap(image, name, size, crop=DEFAULT_CROP):
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    area = QRectF(0, 0, size, size)
    clip = QPainterPath()
    clip.addRoundedRect(area, size * CORNER_RATIO, size * CORNER_RATIO)
    painter.fillPath(clip, QColor(AVATAR_BACKGROUND))
    painter.setClipPath(clip)
    if image is None:
        painter.setPen(QColor('#f4edff'))
        font = QFont(painter.font())
        font.setPixelSize(max(10, size // 2))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(area, Qt.AlignCenter, name[:1])
    else:
        crop = normalize_crop(crop)
        if isinstance(crop, dict):
            draw_cropped(painter, image, area, crop)
        else:
            source = QRectF(image.rect())
            zoom, x, y = crop
            factor = (size * .88 / max(source.width(), source.height())) * zoom / 100
            width, height = source.width() * factor, source.height() * factor
            target = QRectF((size - width) / 2 + x * size / 250,
                            (size - height) / 2 + y * size / 250, width, height)
            painter.drawPixmap(target, image, source)
    painter.end()
    return canvas


class AvatarCropView(QWidget):
    """A fixed rounded frame; the artwork is dragged and zoomed underneath it."""
    changed = Signal()

    def __init__(self, image, crop):
        super().__init__()
        self.image = image
        self.max_scale = min(MAX_SCALE, full_scale(image.width(), image.height()))
        crop = normalize_crop(crop)
        self.selection = crop if isinstance(crop, dict) else initial_crop(image)
        self.drag_point = None
        self.setMinimumSize(320, 320)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self.setAccessibleName(tr('chat.avatar_source'))
        self.setAccessibleDescription(tr('chat.avatar_help'))

    def sizeHint(self):
        return QSize(340, 340)

    def frame_rect(self):
        side = max(40, min(self.width(), self.height()) - 44)
        frame = QRectF(0, 0, side, side)
        frame.moveCenter(QRectF(self.rect()).center())
        return frame

    def source_rect(self):
        return crop_rect(QRectF(self.image.rect()), self.selection)

    def set_image(self, image, crop=None):
        self.image = image
        self.max_scale = min(MAX_SCALE, full_scale(image.width(), image.height()))
        self.set_selection(crop if crop is not None else initial_crop(image))

    def set_selection(self, crop):
        crop = normalize_crop(crop)
        if not isinstance(crop, dict):
            crop = dict(x=.5, y=.5, scale=self.max_scale)
        crop['scale'] = max(MIN_SCALE, min(self.max_scale, crop['scale']))
        # Store the clamped position so dragging past an edge never builds up hidden slack.
        box = crop_rect(QRectF(self.image.rect()), crop)
        width, height = self.image.width(), self.image.height()
        self.selection = dict(x=box.center().x() / width, y=box.center().y() / height, scale=crop['scale'])
        self.update()
        self.changed.emit()

    def pan(self, dx, dy):
        """Move the artwork by (dx, dy) widget pixels."""
        source = self.source_rect()
        factor = self.frame_rect().width() / source.width()
        centre = source.center() - QPointF(dx, dy) / factor
        self.set_selection({**self.selection, 'x': centre.x() / self.image.width(),
                            'y': centre.y() / self.image.height()})

    def zoom(self, steps):
        """Positive steps zoom in around the frame centre."""
        self.set_selection({**self.selection, 'scale': self.selection['scale'] * (.88 ** steps)})

    def fit_face(self):
        self.set_selection(face_crop(self.image))

    def fit_full(self):
        self.set_selection(dict(x=.5, y=.5, scale=self.max_scale))

    def slider_value(self):
        span = log(self.max_scale / MIN_SCALE)
        if span <= 0:
            return 1000
        return round(1000 * log(self.max_scale / self.selection['scale']) / span)

    def set_slider_value(self, value):
        scale = self.max_scale * (MIN_SCALE / self.max_scale) ** (value / 1000)
        self.set_selection({**self.selection, 'scale': scale})

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        frame = self.frame_rect()
        radius = frame.width() * CORNER_RATIO
        outline = QPainterPath()
        outline.addRoundedRect(frame, radius, radius)
        painter.fillPath(outline, QColor(AVATAR_BACKGROUND))
        draw_cropped(painter, self.image, frame, self.selection)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        shade = shade.subtracted(outline)
        painter.fillPath(shade, QColor(18, 13, 27, 150))
        painter.setPen(QPen(QColor('#d6baff'), 2))
        painter.drawPath(outline)
        if self.hasFocus():
            painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.DashLine))
            painter.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_point = event.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag_point is None:
            return
        point = event.position()
        self.pan(point.x() - self.drag_point.x(), point.y() - self.drag_point.y())
        self.drag_point = point

    def mouseReleaseEvent(self, event):
        self.drag_point = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.fit_face()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if steps:
            self.zoom(steps)
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        step = 24 if event.modifiers() & Qt.ShiftModifier else 6
        arrows = {Qt.Key_Left: (step, 0), Qt.Key_Right: (-step, 0), Qt.Key_Up: (0, step), Qt.Key_Down: (0, -step)}
        if key == Qt.Key_Space:
            self.fit_face()
        elif key in arrows:
            self.pan(*arrows[key])
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom(1)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom(-1)
        else:
            super().keyPressEvent(event)


class ChatAvatarDialog(QDialog):
    """Pick the framing; optionally swap in a user picture.

    After accept, image_choice is None (keep the current picture), 'character' (drop the custom
    picture) or a QImage to store as the new custom picture.
    """

    def __init__(self, image, name, crop, parent=None, character_image=None, custom=False):
        super().__init__(parent)
        self.setWindowTitle(tr('chat.avatar_title'))
        self.setMinimumWidth(560)
        self.image, self.name = image, name
        self.character_image = character_image if character_image is not None else (None if custom else image)
        self.custom = custom
        self.image_choice = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        help_text = QLabel(tr('chat.avatar_help'))
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        columns = QHBoxLayout()
        editor = QVBoxLayout()
        self.source = AvatarCropView(image, crop)
        editor.addWidget(self.source, 1)
        zoom_row = QHBoxLayout()
        zoom_label = QLabel(tr('chat.avatar_zoom'))
        zoom_row.addWidget(zoom_label)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setObjectName('avatarZoom')
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setAccessibleName(tr('chat.avatar_zoom'))
        zoom_label.setBuddy(self.zoom_slider)
        zoom_row.addWidget(self.zoom_slider, 1)
        editor.addLayout(zoom_row)
        fit_row = QHBoxLayout()
        self.face_button = QPushButton(tr('chat.avatar_face'))
        self.face_button.clicked.connect(self.source.fit_face)
        fit_row.addWidget(self.face_button)
        self.full_button = QPushButton(tr('chat.avatar_reset'))
        self.full_button.clicked.connect(self.source.fit_full)
        fit_row.addWidget(self.full_button)
        editor.addLayout(fit_row)
        source_row = QHBoxLayout()
        self.import_button = QPushButton(tr('chat.avatar_import'))
        self.import_button.setObjectName('avatarImport')
        self.import_button.clicked.connect(self.choose_image)
        source_row.addWidget(self.import_button)
        self.character_button = QPushButton(tr('chat.avatar_character'))
        self.character_button.setObjectName('avatarCharacter')
        self.character_button.clicked.connect(self.use_character_image)
        source_row.addWidget(self.character_button)
        editor.addLayout(source_row)
        self.refresh_source_buttons()
        columns.addLayout(editor, 1)
        preview_column = QVBoxLayout()
        heading = QLabel(tr('chat.avatar_preview'))
        heading.setAlignment(Qt.AlignCenter)
        preview_column.addWidget(heading)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setAccessibleName(tr('chat.avatar_preview'))
        preview_column.addWidget(self.preview)
        sizes_heading = QLabel(tr('chat.avatar_sizes'))
        sizes_heading.setAlignment(Qt.AlignCenter)
        preview_column.addWidget(sizes_heading)
        sizes_row = QHBoxLayout()
        sizes_row.addStretch()
        self.small_previews = []
        for size in CHAT_SIZES:
            label = QLabel()
            label.setAccessibleName(tr('chat.avatar_sizes'))
            sizes_row.addWidget(label)
            self.small_previews.append((size, label))
        sizes_row.addStretch()
        preview_column.addLayout(sizes_row)
        preview_column.addStretch()
        columns.addLayout(preview_column)
        layout.addLayout(columns)
        self.source.changed.connect(self.update_preview)
        self.zoom_slider.valueChanged.connect(self.source.set_slider_value)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr('common.save'))
        buttons.button(QDialogButtonBox.Cancel).setText(tr('common.cancel'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_preview()
        self.source.setFocus()

    def crop(self):
        return self.source.selection

    def refresh_source_buttons(self):
        self.character_button.setEnabled(self.custom and self.character_image is not None)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('chat.avatar_file_title'), '', tr('chat.avatar_file_filter'),
                                              options=QFileDialog.DontUseNativeDialog)
        if path:
            self.load_image_file(path)

    def load_image_file(self, path):
        try:
            picture = read_avatar_image(path)
        except ValueError as exc:
            QMessageBox.warning(self, tr('chat.avatar_title'), str(exc))
            return False
        self.set_picture(QPixmap.fromImage(picture), picture, custom=True)
        return True

    def use_character_image(self):
        if self.character_image is not None:
            self.set_picture(self.character_image, 'character', custom=False)

    def set_picture(self, pixmap, choice, custom):
        self.image, self.image_choice, self.custom = pixmap, choice, custom
        self.source.set_image(pixmap)
        self.refresh_source_buttons()
        self.source.setFocus()

    def update_preview(self):
        crop = self.crop()
        self.preview.setPixmap(avatar_pixmap(self.image, self.name, 120, crop))
        for size, label in self.small_previews:
            label.setPixmap(avatar_pixmap(self.image, self.name, size, crop))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(self.source.slider_value())
        self.zoom_slider.blockSignals(False)
