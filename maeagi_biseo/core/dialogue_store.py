"""User-authored offline conversations, separate from bundled defaults."""
import json
from copy import deepcopy
from PySide6.QtCore import QSettings
from maeagi_biseo.resources import SCRIPTS, tr


def dialogue_store():
    return QSettings('DesktopShimeji', 'Dialogue')


def validate_scripts(scripts):
    if not isinstance(scripts, list) or len(scripts) > 100:
        raise ValueError(tr('dialogue.invalid'))
    for lines in scripts:
        if not isinstance(lines, list) or not 2 <= len(lines) <= 20:
            raise ValueError(tr('dialogue.invalid'))
        if any(not isinstance(line, str) or not line.strip() or len(line) > 200 for line in lines):
            raise ValueError(tr('dialogue.invalid'))
    return scripts


def load_scripts(store=None):
    store = store if store is not None else dialogue_store()
    try:
        if store.contains('scripts'):
            return validate_scripts(json.loads(str(store.value('scripts'))))
    except (ValueError, TypeError):
        pass
    return deepcopy(SCRIPTS)


def save_scripts(scripts, store=None):
    validate_scripts(scripts)
    store = store if store is not None else dialogue_store()
    store.setValue('scripts', json.dumps(scripts, ensure_ascii=False))
    store.sync()
