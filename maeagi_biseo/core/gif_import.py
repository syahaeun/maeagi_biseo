"""Decode GIFs into composited PNG frames using Qt's bundled image plugin."""
import uuid
from pathlib import Path
from PySide6.QtGui import QImageReader


def import_gif(source, destination):
    reader = QImageReader(str(source))
    prefix = uuid.uuid4().hex
    paths, delays = [], {}
    try:
        while reader.canRead():
            image = reader.read()
            if image.isNull():
                raise ValueError(reader.errorString())
            path = Path(destination) / f'{prefix}_{len(paths):04d}.png'
            if not image.save(str(path)):
                raise ValueError('GIF 프레임을 저장하지 못했습니다.')
            paths.append(str(path))
            delays[str(path)] = max(16, reader.nextImageDelay())
        if not paths:
            raise ValueError('GIF 이미지를 읽지 못했습니다.')
    except Exception:
        for path in paths:
            Path(path).unlink(missing_ok=True)
        raise
    return paths, delays
