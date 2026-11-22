"""User-facing character catalog and persistent startup selection."""
import json
from PySide6.QtCore import QSettings


def catalog_store():
    return QSettings('DesktopShimeji', 'Characters')


def preferences(store=None):
    from maeagi_biseo.core.sprites import character_id
    store = store if store is not None else catalog_store()
    try:
        hidden = json.loads(str(store.value('hidden', '[]')))
    except ValueError:
        hidden = []
    return character_id(str(store.value('default', ''))), {character_id(key) for key in hidden} if isinstance(hidden, list) else set()


def registered_characters(store=None):
    from maeagi_biseo.core.sprites import available_characters
    _, hidden = preferences(store)
    return {key: info for key, info in available_characters().items() if key not in hidden}


def set_default(identifier, hidden=None, store=None):
    from maeagi_biseo.core.sprites import available_characters, character_id
    identifier = character_id(identifier)
    if identifier not in available_characters():
        raise ValueError('Unknown character ID')
    store = store if store is not None else catalog_store()
    _, previous = preferences(store)
    hidden = previous if hidden is None else set(hidden)
    hidden.discard(identifier)
    store.setValue('default', identifier)
    store.setValue('hidden', json.dumps(sorted(hidden)))
    store.sync()


def delete_character(identifier, store=None):
    """Remove user artwork; bundled characters are removed from the catalog."""
    import shutil
    from maeagi_biseo.core.sprites import user_character_root, load_character
    from maeagi_biseo.resources import tr
    store = store if store is not None else catalog_store()
    characters = registered_characters(store)
    if identifier not in characters:
        raise ValueError(tr('editor.delete_missing'))
    if len(characters) <= 1:
        raise ValueError(tr('editor.delete_last'))
    path = characters[identifier].path
    root = user_character_root().resolve()
    resolved = path.resolve()
    # Delete only a direct child of the verified user character directory.
    if resolved.parent == root and not path.is_symlink():
        if path.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    selected, hidden = preferences(store)
    hidden.add(identifier)
    store.setValue('hidden', json.dumps(sorted(hidden)))
    if selected == identifier:
        store.setValue('default', next(key for key in characters if key != identifier))
    store.sync()
    load_character.cache_clear()
