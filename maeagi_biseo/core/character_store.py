"""Persist imported character artwork independently of application installation."""
import json
import shutil
import uuid
import re
from pathlib import Path
from PySide6.QtGui import QImage

from maeagi_biseo.core.sprites import STATES, SpritePack, CharacterInfo, user_character_root, load_character


def save_character(name, animations, canvas, identifier=None, comparison_box=None, display_scale=100, bubble_offset=None, upscale_factor=1, smoothing=0):
    if type(smoothing) is not int or smoothing not in (0, 1, 2, 3):
        raise ValueError('Invalid smoothing strength')
    if type(upscale_factor) is not int or upscale_factor not in (1, 2, 4):
        raise ValueError('Invalid upscale factor')
    name = name.strip()
    if not name:
        raise ValueError('메애기 이름을 입력해주세요.')
    if not animations.get('idle', {}).get('frames'):
        raise ValueError('대기 이미지는 최소 한 장 필요합니다.')
    root = user_character_root()
    root.mkdir(parents=True, exist_ok=True)
    if identifier is not None and not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
        raise ValueError('잘못된 메애기 ID입니다.')
    identifier = identifier or 'user_' + uuid.uuid4().hex
    folder = root / identifier
    # Unique filenames keep the previous manifest usable until the new one commits.
    batch = uuid.uuid4().hex
    created = []
    folder.mkdir(exist_ok=True)
    try:
        manifest = {'name': name, 'facing': 'left', 'canvas': list(canvas), 'foot_offset': canvas[1], 'animations': {}, 'display_scale': display_scale}
        manifest['bubble_offset'] = list(bubble_offset) if bubble_offset is not None else [0, 0]
        if comparison_box is not None:
            manifest['comparison_box'] = list(comparison_box)
        for state in STATES:
            entry = animations.get(state, {})
            frames = []
            for index, source in enumerate(entry.get('frames', [])):
                source = Path(source)
                suffix = '.png' if upscale_factor > 1 or smoothing else source.suffix.lower()
                filename = f'{batch}_{state}_{index:03d}{suffix}'
                target = folder / filename
                created.append(target)
                if upscale_factor > 1 or smoothing:
                    from maeagi_biseo.core.upscale import upscale_frame
                    upscale_frame(source, target, upscale_factor, smoothing)
                else:
                    shutil.copyfile(source, target)
                frames.append(filename)
            if frames:
                manifest['animations'][state] = {'frames': frames, 'frame_ms': entry.get('frame_ms', 120),
                    'foot_offset': entry.get('foot_offset', canvas[1])}
                if entry.get('delays'):
                    manifest['animations'][state]['frame_durations'] = [entry['delays'].get(str(path), entry.get('frame_ms', 120)) for path in entry['frames']]
                if entry.get('sizes'):
                    manifest['animations'][state]['frame_sizes'] = [entry['sizes'].get(str(path), list(canvas)) for path in entry['frames']]
        staging = folder / f'{batch}.json'
        created.append(staging)
        staging.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        # Validate every copied frame using the same loader as the running pets.
        validation = folder / f'validate_{batch}'
        validation.mkdir()
        try:
            (validation / 'character.json').write_text(json.dumps(manifest), encoding='utf-8')
            for target in created[:-1]:
                shutil.copyfile(target, validation / target.name)
            # QImage supports worker threads; QPixmap requires the GUI thread.
            SpritePack(CharacterInfo(identifier, name, validation), image_type=QImage)
        finally:
            shutil.rmtree(validation)
        staging.replace(folder / 'character.json')
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    load_character.cache_clear()
    # Old files are intentionally retained: active pets can still reference them.
    return identifier
