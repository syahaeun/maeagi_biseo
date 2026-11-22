"""Load character artwork from image packs. No procedural character drawing."""
import json
import sys
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QStandardPaths
from PySide6.QtGui import QPixmap, QPainter, QImage

from maeagi_biseo.resources import tr, PROJECT_ROOT, read_json

IMAGE_TYPES = {'.png', '.webp', '.jpg', '.jpeg'}
STATES = ('idle', 'walk', 'sleep', 'hop', 'fall', 'drag', 'climb', 'ceiling', 'talk', 'pet')


def character_id(identifier):
    return read_json('characters.json').get('aliases', {}).get(identifier, identifier)


class SpriteError(ValueError):
    pass


def scale_display_canvas(image, size):
    """Use one display resampler for editor previews and running pets."""
    return image.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def artwork_rows(image):
    """Return the first visible row and the exclusive end of visible artwork."""
    if isinstance(image, QPixmap):
        image = image.toImage()
    rgba = image.convertToFormat(QImage.Format_RGBA8888)
    alpha = bytes(rgba.constBits())[3::4]
    occupied = alpha.rstrip(b'\x00')
    if not occupied:
        return 0, image.height()
    width = image.width()
    top = (len(occupied) - len(occupied.lstrip(b'\x00'))) // width
    return top, (len(occupied) + width - 1) // width


@dataclass(frozen=True)
class CharacterInfo:
    identifier: str
    name: str
    path: Path


def user_character_root():
    return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'DesktopShimeji' / 'characters'


def sprite_roots():
    if getattr(sys, 'frozen', False):
        external = Path(sys.executable).parent / 'Images'
        return [user_character_root(), external / 'Characters', external / 'Shimeji',
                Path(sys._MEIPASS) / 'Images' / 'Characters']
    images = PROJECT_ROOT / 'Images'
    return [user_character_root(), images / 'Characters', images / 'Shimeji']


def read_manifest(folder):
    path = folder / 'character.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (OSError, ValueError, UnicodeError):
        raise SpriteError(tr('sprites.invalid_manifest', name=folder.name)) from None


def available_characters():
    characters = {}
    for root in sprite_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            identifier = character_id(path.name if path.is_dir() else path.stem)
            if identifier in characters:
                continue
            if path.is_dir():
                try:
                    manifest = read_manifest(path)
                except SpriteError:
                    continue
                if not manifest and not (path / 'idle.png').is_file():
                    continue
                label = manifest.get('name', identifier)
            elif path.suffix.casefold() in IMAGE_TYPES:
                label = identifier
            else:
                continue
            characters[identifier] = CharacterInfo(identifier, str(label), path)
    return characters


def default_character(preferred=None):
    from maeagi_biseo.core.character_catalog import registered_characters, preferences
    characters = registered_characters()
    selected, _ = preferences()
    if preferred is None and selected in characters:
        return selected
    bundled_default = read_json('characters.json').get('default')
    if preferred is None and bundled_default in characters:
        return bundled_default
    if preferred in characters:
        return preferred
    if characters:
        return next(iter(characters))
    raise SpriteError(tr('sprites.none_found'))


class SpritePack:
    def __init__(self, info, *, image_type=QPixmap):
        self.image_type = image_type
        self.info = info
        manifest = read_manifest(info.path) if info.path.is_dir() else {}
        self.facing = manifest.get('facing', 'left')
        if self.facing not in ('left', 'right'):
            raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
        canvas = manifest.get('canvas', [130, 155])
        try:
            width, height = canvas
            if any(type(value) is not int or not 16 <= value <= 2048 for value in (width, height)):
                raise ValueError()
            self.canvas = QSize(width, height)
            self.foot_offset = manifest.get('foot_offset', height)
            if type(self.foot_offset) is not int or not 1 <= self.foot_offset <= height:
                raise ValueError()
        except (TypeError, ValueError):
            raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier)) from None
        animations = manifest.get('animations', {})
        if not isinstance(animations, dict):
            raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
        self.animations = {}
        self.durations = {}
        self.feet = {}
        self.images = {}
        self._artwork_rows = {}
        if info.path.is_file():
            animations = {'idle': {'frames': [info.path.name], 'frame_ms': 150}}
        for state in STATES:
            entry = animations.get(state)
            if entry is None and info.path.is_dir():
                frames = sorted(path.name for path in info.path.glob(state + '_*.png'))
                if (info.path / (state + '.png')).is_file():
                    frames.insert(0, state + '.png')
                if frames:
                    entry = {'frames': frames, 'frame_ms': 120}
            if entry is None:
                continue
            if not isinstance(entry, dict):
                raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
            frames = entry.get('frames', [])
            duration = entry.get('frame_ms', 120)
            foot = entry.get('foot_offset', self.foot_offset)
            if type(foot) is not int or not 1 <= foot <= height:
                raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
            self.feet[state] = foot
            if (not isinstance(frames, list) or not frames or type(duration) is not int
                    or not 16 <= duration <= 60000):
                raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
            sizes = entry.get('frame_sizes', [list(canvas)] * len(frames))
            if not isinstance(sizes, list) or len(sizes) != len(frames):
                raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
            for filename, size in zip(frames, sizes):
                if not isinstance(size, list) or len(size) != 2 or any(type(value) is not int or not 16 <= value <= canvas[index] for index, value in enumerate(size)):
                    raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
                self.load_frame(filename, QSize(*size))
            self.animations[state] = (tuple(frames), duration)
            delays = entry.get('frame_durations')
            if delays is not None:
                if not isinstance(delays, list) or len(delays) != len(frames) or any(type(delay) is not int or not 16 <= delay <= 60000 for delay in delays):
                    raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
                self.durations[state] = delays
        if 'idle' not in self.animations:
            raise SpriteError(tr('sprites.missing_idle', name=info.identifier))
        # Align feet on one anchor, extending the canvas only for visible artwork.
        self.source_canvas = QSize(self.canvas)
        self.foot_offset = max(self.feet.values())
        frame_bottoms = {}
        canvas_height = height
        for state, (frames, _) in self.animations.items():
            offset = self.foot_offset - self.feet[state]
            if not offset:
                continue
            for filename in frames:
                if filename not in frame_bottoms:
                    image = self.images[filename]
                    if isinstance(image, QPixmap):
                        image = image.toImage()
                    rgba = image.convertToFormat(QImage.Format_RGBA8888)
                    alpha = bytes(rgba.constBits())[3::4].rstrip(b'\x00')
                    frame_bottoms[filename] = (len(alpha) + width - 1) // width
                canvas_height = max(canvas_height, frame_bottoms[filename] + offset)
        self.canvas.setHeight(canvas_height)
        self.state_images = {}
        for state, (frames, _) in self.animations.items():
            for filename in frames:
                image = self.blank_canvas()
                image.fill(Qt.transparent)
                painter = QPainter(image)
                draw = painter.drawImage if self.image_type is QImage else painter.drawPixmap
                draw(0, self.foot_offset - self.feet[state], self.images[filename])
                painter.end()
                self.state_images[state, filename] = image
        self.display_scale = manifest.get('display_scale', 100)
        self.bubble_offset = manifest.get('bubble_offset', [0, 0])
        if (not isinstance(self.bubble_offset, list) or len(self.bubble_offset) != 2
                or any(type(value) is not int or not -300 <= value <= 300 for value in self.bubble_offset)):
            raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
        if type(self.display_scale) is not int or not 25 <= self.display_scale <= 300:
            raise SpriteError(tr('sprites.invalid_manifest', name=info.identifier))
        if self.display_scale != 100:
            factor = self.display_scale / 100
            self.canvas = QSize(max(1, round(self.canvas.width() * factor)), max(1, round(self.canvas.height() * factor)))
            self.foot_offset = max(1, round(self.foot_offset * factor))
            self.state_images = {key: scale_display_canvas(image, self.canvas)
                                 for key, image in self.state_images.items()}

    def blank_canvas(self):
        if self.image_type is QImage:
            return QImage(self.canvas, QImage.Format_ARGB32_Premultiplied)
        return QPixmap(self.canvas)

    def load_frame(self, filename, target_size=None):
        if not isinstance(filename, str):
            raise SpriteError(tr('sprites.invalid_manifest', name=self.info.identifier))
        if filename in self.images:
            return
        folder = self.info.path if self.info.path.is_dir() else self.info.path.parent
        # Store Python redirects LocalAppData files into LocalCache, while
        # resolving the directory alone can retain the unredirected path.
        # Anchor to the existing manifest's physical parent before containment.
        manifest = folder / 'character.json'
        if manifest.is_file():
            folder = manifest.resolve().parent
        path = (folder / filename).resolve()
        if not path.is_relative_to(folder.resolve()) or path.suffix.casefold() not in IMAGE_TYPES:
            raise SpriteError(tr('sprites.invalid_frame', path=filename))
        image = self.image_type(str(path))
        if image.isNull():
            raise SpriteError(tr('sprites.invalid_frame', path=str(path)))
        target_size = target_size or self.canvas
        if image.size() != self.canvas or target_size != self.canvas:
            scaled = image.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image = self.blank_canvas()
            image.fill(Qt.transparent)
            painter = QPainter(image)
            draw = painter.drawImage if self.image_type is QImage else painter.drawPixmap
            draw((self.canvas.width() - scaled.width()) // 2,
                               self.canvas.height() - scaled.height(), scaled)
            painter.end()
        self.images[filename] = image

    def frame(self, state, elapsed_ms):
        state = state if state in self.animations else 'idle'
        frames, duration = self.animations[state]
        index = int(max(0, elapsed_ms) // duration) % len(frames)
        if state in self.durations:
            elapsed = max(0, elapsed_ms) % sum(self.durations[state])
            for index, delay in enumerate(self.durations[state]):
                if elapsed < delay:
                    break
                elapsed -= delay
        return self.state_images[state, frames[index]]

    @cached_property
    def idle_top_margin(self):
        """Transparent rows shared by every idle frame at display size."""
        return min(self.frame_artwork_rows(self.state_images['idle', filename])[0]
                   for filename in self.animations['idle'][0])

    def frame_artwork_rows(self, image):
        key = image.cacheKey()
        if key not in self._artwork_rows:
            self._artwork_rows[key] = artwork_rows(image)
        return self._artwork_rows[key]


@lru_cache(maxsize=64)
def load_character(identifier):
    identifier = character_id(identifier)
    info = available_characters().get(identifier)
    if info is None:
        raise SpriteError(tr('sprites.not_found', name=identifier))
    return SpritePack(info)
