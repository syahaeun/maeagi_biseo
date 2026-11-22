"""Per-character preferences, independent of artwork and API credentials."""
import json
from PySide6.QtCore import QSettings
from maeagi_biseo.core.sprites import STATES, sprite_roots, read_manifest, character_id
from maeagi_biseo.resources import DEFAULTS

PERSONA_FIELDS = ('name', 'personality', 'tone', 'interests', 'extra')


def profile_store():
    return QSettings('DesktopShimeji', 'CharacterProfiles')


def load_profiles(store=None):
    store = store if store is not None else profile_store()
    bundled = {}
    for root in reversed(sprite_roots()):
        if root.is_dir():
            for folder in root.iterdir():
                if folder.is_dir():
                    try:
                        profile = read_manifest(folder).get('profile')
                        if isinstance(profile, dict):
                            bundled[character_id(folder.name)] = profile
                    except ValueError:
                        continue
    try:
        data = json.loads(str(store.value('profiles', '{}')))
        if isinstance(data, dict):
            bundled.update({character_id(key): value for key, value in data.items() if isinstance(value, dict)})
        return bundled
    except (ValueError, TypeError):
        return bundled


def persona_for(identifier, fallback=None, store=None):
    base = DEFAULTS if fallback is None else fallback
    saved = load_profiles(store).get(character_id(identifier), {}).get('persona', {})
    return {key: str(saved.get(key, base[key])) for key in PERSONA_FIELDS}


def allowed_for(identifier, store=None):
    saved = load_profiles(store).get(character_id(identifier), {}).get('allowed_actions', list(STATES))
    return set(saved).intersection(STATES) | {'idle'} if isinstance(saved, list) else set(STATES)


def save_profiles(profiles, store=None):
    store = store if store is not None else profile_store()
    store.setValue('profiles', json.dumps(profiles, ensure_ascii=False))
    store.sync()
